"""Claim processing pipeline.

Stage order (PLAN.md §4): intake -> verify documents (fail fast, TC001–TC003)
-> extract -> adjudicate -> fraud -> synthesize. Every stage's work lands in
the trace; component failures degrade, they never crash the pipeline.

Returns `ClaimDecision`, or `DocumentProblemReport` when verification stops
the claim before any decision is made.
"""

from uuid import uuid4

from app.agents.extraction import extract_documents
from app.agents.llm import DocumentAI
from app.agents.verifier import verify_documents
from app.core.errors import DocumentVerificationStop
from app.engine.adjudicator import adjudicate
from app.engine.fraud import assess_fraud
from app.engine.synthesizer import synthesize
from app.kb.snapshot import PolicySnapshot
from app.models import ClaimDecision, ClaimSubmission, FraudAssessment, Outcome
from app.models.documents import DocumentProblemReport
from app.orchestrator.trace import TraceBuilder

PENALTY_DEGRADED = -0.20
PENALTY_UNITEMIZED = -0.05


def process_claim(
    submission: ClaimSubmission,
    snapshot: PolicySnapshot,
    claim_id: str | None = None,
    doc_ai: DocumentAI | None = None,
) -> ClaimDecision | DocumentProblemReport:
    claim_id = claim_id or f"CLM_{uuid4().hex[:8].upper()}"
    tb = TraceBuilder(claim_id)
    penalties: list[tuple[str, float]] = []

    tb.step(
        "intake_validator",
        action="validate submission payload",
        outcome=Outcome.PASS,
        detail=(
            f"Claim by {submission.member_id} for {submission.claim_category.value}, "
            f"treatment {submission.treatment_date}, amount ₹{submission.claimed_amount}, "
            f"{len(submission.documents)} document(s)."
        ),
    )

    try:
        verified = verify_documents(submission, snapshot, tb, doc_ai)
    except DocumentVerificationStop as stop:
        tb.step(
            "document_verifier",
            action="verification stopped",
            outcome=Outcome.FAIL,
            detail=(
                f"{len(stop.problems)} document problem(s) found; processing stopped before "
                f"any decision. The claim is returned to the member with instructions."
            ),
        )
        return DocumentProblemReport(claim_id=claim_id, problems=stop.problems, trace=tb.build())

    # Verifier warnings (poor quality, unverified fields) carry confidence deltas.
    penalties += [
        (s.detail, s.confidence_delta)
        for s in tb.steps
        if s.component == "document_verifier" and s.confidence_delta
    ]

    documents = extract_documents(verified.documents, doc_ai, tb, penalties)

    adjudication = adjudicate(submission, documents, snapshot)
    for check in adjudication.checks:
        tb.step(
            "adjudication_engine",
            action=check.name,
            outcome=check.outcome,
            detail=check.detail,
            rule_ref=check.rule_ref,
        )
    if adjudication.financial:
        tb.step(
            "adjudication_engine",
            action="financial computation",
            outcome=Outcome.PASS,
            detail=" → ".join(
                f"{s.step} ₹{s.amount_after}" for s in adjudication.financial.steps
            ),
            rule_ref="coverage",
        )
    if any("itemized" in note for note in adjudication.notes):
        penalties.append(("bill not itemized; adjudicated on billed total", PENALTY_UNITEMIZED))

    if submission.simulate_component_failure:
        # TC011: the least critical stage takes the simulated hit — same
        # machinery as a real component outage (degrade, don't crash).
        fraud = FraudAssessment()
        tb.mark_degraded(
            "fraud_checker",
            detail=(
                "Component failure (simulated): fraud checker crashed and was skipped; "
                "velocity rules were not evaluated for this claim."
            ),
            confidence_delta=PENALTY_DEGRADED,
        )
        penalties.append(("fraud_checker failed and was skipped", PENALTY_DEGRADED))
    else:
        fraud = assess_fraud(submission, snapshot.terms.fraud_thresholds)
        tb.step(
            "fraud_checker",
            action="velocity and threshold rules",
            outcome=Outcome.FAIL if fraud.signals else Outcome.PASS,
            detail=(
                " | ".join(s.detail for s in fraud.signals)
                if fraud.signals
                else "No fraud signals: same-day, monthly, and high-value checks all within limits."
            ),
            rule_ref="fraud_thresholds",
        )

    return synthesize(submission, adjudication, fraud, penalties, tb)
