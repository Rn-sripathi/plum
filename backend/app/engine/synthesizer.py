"""Decision synthesizer — combines rule outcomes, fraud signals, and
confidence penalties into the final `ClaimDecision` (PLAN.md §6 confidence
model). Pure code; always returns.

Confidence: starts at BASE (0.98 — residual uncertainty is honest, never 1.0),
minus the penalties the pipeline collected. Thresholds:
  < 0.50            -> MANUAL_REVIEW
  0.50–0.75         -> keep decision, recommend manual review
  degraded pipeline -> always recommend manual review (TC011)
"""

from decimal import Decimal

from app.models import (
    Adjudication,
    ClaimDecision,
    ClaimSubmission,
    Decision,
    FraudAssessment,
    Outcome,
)
from app.orchestrator.trace import TraceBuilder

from .checks import fmt_inr

BASE_CONFIDENCE = 0.98
GRAY_ZONE_LOW = 0.50
GRAY_ZONE_HIGH = 0.75


def synthesize(
    claim: ClaimSubmission,
    adjudication: Adjudication,
    fraud: FraudAssessment,
    penalties: list[tuple[str, float]],
    tb: TraceBuilder,
) -> ClaimDecision:
    confidence = BASE_CONFIDENCE + sum(delta for _, delta in penalties)
    confidence = max(0.0, min(1.0, round(confidence, 4)))
    tb.step(
        "decision_synthesizer",
        action="confidence rollup",
        outcome=Outcome.PASS,
        detail=(
            f"Confidence {confidence:.2f} = base {BASE_CONFIDENCE}"
            + "".join(f" {delta:+.2f} ({reason})" for reason, delta in penalties)
            if penalties
            else f"Confidence {confidence:.2f} = base {BASE_CONFIDENCE}; no penalties."
        ),
    )

    decision = adjudication.decision
    reasons: list[str] = []
    manual_review_recommended = False

    # Why confidence moved. Reporting only the final number ("0.48 is below
    # the floor") is circular — the reader needs the signals that caused it,
    # which otherwise sit buried in the trace.
    concerns: list[str] = [
        check.detail
        for check in adjudication.checks
        if check.outcome is Outcome.FAIL
        and check.rejection_reason is None
        and check.name != "line_items"
    ]
    concerns += [reason for reason, delta in penalties if delta]
    # A signal can surface both as an engine check and as a confidence
    # penalty; say it once.
    concerns = list(dict.fromkeys(concerns))

    if fraud.requires_manual_review and decision is not Decision.REJECTED:
        decision = Decision.MANUAL_REVIEW
        reasons.append(
            "Routed to manual review — fraud signals require a human decision; the claim is not auto-rejected."
        )
        reasons += [s.detail for s in fraud.signals]
    elif confidence < GRAY_ZONE_LOW and decision in (Decision.APPROVED, Decision.PARTIAL):
        decision = Decision.MANUAL_REVIEW
        reasons.append(
            f"Routed to manual review: confidence {confidence:.2f} is below the "
            f"{GRAY_ZONE_LOW} auto-decision floor because of the following."
        )

    if GRAY_ZONE_LOW <= confidence <= GRAY_ZONE_HIGH:
        manual_review_recommended = True
        reasons.append(
            f"Manual review recommended: confidence {confidence:.2f} sits in the review zone "
            f"({GRAY_ZONE_LOW}–{GRAY_ZONE_HIGH}) because of the following."
        )
    if tb.degraded_components:
        manual_review_recommended = True
        reasons.append(
            f"Processing was incomplete — {', '.join(tb.degraded_components)} failed and was skipped. "
            "Manual review recommended."
        )
    if concerns:
        if not reasons:  # nothing above already introduced them
            reasons.append(
                f"Confidence {confidence:.2f} (from {BASE_CONFIDENCE}); the following were noted."
            )
        reasons += concerns

    approved_amount = Decimal(0)
    if decision in (Decision.APPROVED, Decision.PARTIAL) and adjudication.financial:
        approved_amount = adjudication.financial.final_payable

    if decision is Decision.REJECTED:
        failing = [c for c in adjudication.checks if c.rejection_reason is not None]
        if failing:
            reasons.insert(0, failing[0].detail)
            reasons += [f"Also failed: {c.detail}" for c in failing[1:]]
    elif decision in (Decision.APPROVED, Decision.PARTIAL):
        reasons.insert(
            0,
            f"{'Approved' if decision is Decision.APPROVED else 'Partially approved'} "
            f"{fmt_inr(approved_amount)} of claimed {fmt_inr(claim.claimed_amount)}.",
        )
        for item in adjudication.line_items:
            if not item.approved:
                reasons.append(f"Line item rejected — {item.reason}")
        if adjudication.financial:
            for s in adjudication.financial.steps:
                if s.adjustment != 0:
                    reasons.append(
                        f"{s.description} {fmt_inr(s.adjustment)} "
                        f"({fmt_inr(s.amount_before)} → {fmt_inr(s.amount_after)})"
                    )
    elif decision is Decision.MANUAL_REVIEW and adjudication.decision in (
        Decision.APPROVED,
        Decision.PARTIAL,
    ):
        reasons.append(
            f"Rule checks alone would have {adjudication.decision.value.lower()} "
            f"{fmt_inr(adjudication.financial.final_payable) if adjudication.financial else 'the claim'}; "
            "held pending review."
        )

    reasons += adjudication.notes

    tb.step(
        "decision_synthesizer",
        action="final decision",
        outcome=Outcome.PASS if decision is not Decision.REJECTED else Outcome.FAIL,
        detail=f"{decision.value}; approved amount {fmt_inr(approved_amount)}; confidence {confidence:.2f}.",
    )

    return ClaimDecision(
        claim_id=tb.claim_id,
        decision=decision,
        approved_amount=approved_amount,
        reasons=reasons,
        rejection_reasons=adjudication.rejection_reasons if decision is Decision.REJECTED else [],
        confidence=confidence,
        manual_review_recommended=manual_review_recommended,
        fraud_signals=fraud.signals,
        line_items=adjudication.line_items,
        financial=adjudication.financial,
        degraded_components=list(tb.degraded_components),
        trace=tb.build(),
    )
