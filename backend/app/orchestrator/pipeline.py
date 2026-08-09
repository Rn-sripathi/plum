"""Claim processing pipeline — Phase 2 wiring (no document verifier yet;
that stage slots in front in Phase 3, and vision extraction in Phase 4).

Stage order (PLAN.md §4): intake -> [verify docs] -> extract -> adjudicate ->
fraud -> synthesize. Every stage's work lands in the trace; failures degrade,
they never crash the pipeline.
"""

from uuid import uuid4

from app.agents.extraction import from_submitted
from app.engine.adjudicator import adjudicate
from app.engine.fraud import assess_fraud
from app.engine.synthesizer import synthesize
from app.kb.snapshot import PolicySnapshot
from app.models import ClaimDecision, ClaimSubmission, DocumentQuality, FraudAssessment, Outcome
from app.orchestrator.trace import TraceBuilder

PENALTY_DEGRADED = -0.20
PENALTY_POOR_DOC = -0.10
PENALTY_UNITEMIZED = -0.05


def process_claim(
    submission: ClaimSubmission,
    snapshot: PolicySnapshot,
    claim_id: str | None = None,
) -> ClaimDecision:
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

    documents = [from_submitted(d) for d in submission.documents]
    tb.step(
        "extraction_agent",
        action="extract structured data from documents",
        outcome=Outcome.SKIPPED,
        detail="Pre-extracted content supplied with the submission; vision extraction skipped (test mode).",
        input_summary=", ".join(f"{d.file_id}:{d.doc_type.value}" for d in documents),
    )
    for doc in documents:
        if doc.quality is DocumentQuality.POOR:
            penalties.append((f"document {doc.file_id} quality POOR", PENALTY_POOR_DOC))
            tb.step(
                "extraction_agent",
                action="document quality check",
                outcome=Outcome.DEGRADED,
                detail=f"Document {doc.file_id} is poor quality; extracted fields carry lower confidence.",
                confidence_delta=PENALTY_POOR_DOC,
            )

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
