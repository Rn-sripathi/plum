"""Claim processing pipeline.

Stage order (PLAN.md §4): intake -> verify documents (fail fast, TC001–TC003)
-> extract -> adjudicate -> fraud -> synthesize. Every stage's work lands in
the trace; component failures degrade, they never crash the pipeline.

Returns `ClaimDecision`, or `DocumentProblemReport` when verification stops
the claim before any decision is made.
"""

from collections.abc import Callable
from uuid import uuid4

from app.agents.extraction import extract_documents
from app.agents.llm import DocumentAI
from app.agents.verifier import verify_documents
from app.core.errors import ComponentUnavailable, DocumentVerificationStop
from app.engine.adjudicator import adjudicate
from app.engine.fraud import assess_fraud
from app.engine.synthesizer import synthesize
from app.kb.graph import PolicyGraph
from app.kb.semantic import SemanticHit, SemanticPolicyIndex
from app.kb.snapshot import PolicySnapshot
from app.models import ClaimDecision, ClaimSubmission, FraudAssessment, Outcome, TraceStep
from app.models.documents import DocumentProblemReport
from app.orchestrator.trace import TraceBuilder

PENALTY_DEGRADED = -0.20
PENALTY_UNITEMIZED = -0.05
PENALTY_AMOUNT_MISMATCH = -0.25
PENALTY_SEMANTIC_DOWN = -0.10
PENALTY_GRAPH_DOWN = -0.05


def process_claim(
    submission: ClaimSubmission,
    snapshot: PolicySnapshot,
    claim_id: str | None = None,
    doc_ai: DocumentAI | None = None,
    semantic: SemanticPolicyIndex | None = None,
    graph: PolicyGraph | None = None,
    on_step: Callable[[TraceStep], None] | None = None,
) -> ClaimDecision | DocumentProblemReport:
    claim_id = claim_id or f"CLM_{uuid4().hex[:8].upper()}"
    tb = TraceBuilder(claim_id, on_step=on_step)
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

    # --- Policy retriever: rule source + semantic concept candidates ---------
    if graph is not None and graph.is_configured:
        try:
            graph_reqs = graph.document_requirements(
                submission.policy_id, submission.claim_category.value
            )
            snap_reqs = snapshot.document_requirements(submission.claim_category)
            consistent = sorted(graph_reqs) == sorted(snap_reqs.required if snap_reqs else [])
            if consistent:
                tb.step(
                    "policy_retriever", "rule source", Outcome.PASS,
                    f"Rules loaded from the Neo4j policy graph; document requirements "
                    f"({', '.join(graph_reqs)}) consistent with the snapshot.",
                    rule_ref="kb.graph",
                )
            else:
                penalties.append(("policy graph inconsistent with snapshot", PENALTY_GRAPH_DOWN))
                tb.step(
                    "policy_retriever", "rule source", Outcome.DEGRADED,
                    f"Graph/snapshot mismatch for {submission.claim_category.value}: graph "
                    f"{graph_reqs or '(empty — run app.kb.ingest)'} vs snapshot "
                    f"{snap_reqs.required if snap_reqs else []}. Snapshot takes precedence.",
                    confidence_delta=PENALTY_GRAPH_DOWN, rule_ref="kb.graph",
                )
        except ComponentUnavailable as exc:
            penalties.append(("policy graph unavailable; snapshot fallback", PENALTY_GRAPH_DOWN))
            tb.step(
                "policy_retriever", "rule source", Outcome.DEGRADED,
                f"Policy graph unavailable ({exc.message}); in-memory snapshot fallback.",
                confidence_delta=PENALTY_GRAPH_DOWN, rule_ref="kb.graph",
            )
    else:
        tb.step(
            "policy_retriever", "rule source", Outcome.PASS,
            "In-memory policy snapshot (authoritative; no policy graph configured).",
            rule_ref="kb.snapshot",
        )

    semantic_hints: list[SemanticHit] | None = None
    if semantic is not None and semantic.is_configured:
        texts: list[str] = []
        for doc in documents:
            content = doc.content
            texts += [t for t in (content.diagnosis, content.treatment) if t]
            texts += [item.description for item in (content.line_items or [])]
        try:
            best: dict[str, SemanticHit] = {}
            for text in texts:
                for hit in semantic.search(text, top_k=3, min_score=0.5):
                    if hit.concept not in best or hit.score > best[hit.concept].score:
                        best[hit.concept] = hit
            semantic_hints = sorted(best.values(), key=lambda h: -h.score)
            tb.step(
                "policy_retriever", "semantic concept matching", Outcome.PASS,
                f"Vector index returned {len(semantic_hints)} candidate concept(s) for "
                f"{len(texts)} claim text(s): "
                + (", ".join(f"'{h.concept}' ({h.score:.2f})" for h in semantic_hints[:3]) or "none")
                + ". Candidates only — the deterministic engine decides.",
                rule_ref="kb.semantic",
            )
        except ComponentUnavailable as exc:
            penalties.append(("semantic index unavailable; token matching only", PENALTY_SEMANTIC_DOWN))
            tb.step(
                "policy_retriever", "semantic concept matching", Outcome.DEGRADED,
                f"Vector index unavailable ({exc.message}); deterministic token matching only.",
                confidence_delta=PENALTY_SEMANTIC_DOWN, rule_ref="kb.semantic",
            )

    adjudication = adjudicate(submission, documents, snapshot, semantic_hints)
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
    if any(
        c.name == "amount_reconciliation" and c.outcome is Outcome.FAIL
        for c in adjudication.checks
    ):
        # Claimed and documented amounts disagree: either an over-claim or a
        # misread document. Push the claim into the review band rather than
        # settling silently on the documented figure.
        penalties.append(("claimed amount disagrees with the documents", PENALTY_AMOUNT_MISMATCH))

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
