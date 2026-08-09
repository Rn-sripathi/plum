"""Fraud checker — deterministic velocity and threshold rules from
`fraud_thresholds` (TC009). Flags route to MANUAL_REVIEW, never auto-reject."""

from app.models import ClaimSubmission, FraudAssessment, FraudSignal, FraudSignalCode
from app.models.policy import FraudThresholds

from .checks import fmt_inr


def assess_fraud(claim: ClaimSubmission, thresholds: FraudThresholds) -> FraudAssessment:
    signals: list[FraudSignal] = []
    history = claim.claims_history or []
    ref_date = claim.submission_date or claim.treatment_date

    same_day = [e for e in history if e.date == ref_date]
    if len(same_day) + 1 > thresholds.same_day_claims_limit:
        ids = ", ".join(e.claim_id for e in same_day)
        signals.append(
            FraudSignal(
                code=FraudSignalCode.SAME_DAY_LIMIT_EXCEEDED,
                detail=(
                    f"This is claim #{len(same_day) + 1} from member {claim.member_id} on {ref_date} "
                    f"(earlier today: {ids}) — above the same-day limit of "
                    f"{thresholds.same_day_claims_limit}."
                ),
            )
        )

    same_month = [e for e in history if (e.date.year, e.date.month) == (ref_date.year, ref_date.month)]
    if len(same_month) + 1 > thresholds.monthly_claims_limit:
        signals.append(
            FraudSignal(
                code=FraudSignalCode.MONTHLY_LIMIT_EXCEEDED,
                detail=(
                    f"{len(same_month) + 1} claims in {ref_date:%B %Y} — above the monthly limit "
                    f"of {thresholds.monthly_claims_limit}."
                ),
            )
        )

    if claim.claimed_amount > thresholds.auto_manual_review_above:
        signals.append(
            FraudSignal(
                code=FraudSignalCode.HIGH_VALUE_CLAIM,
                detail=(
                    f"Claimed amount {fmt_inr(claim.claimed_amount)} exceeds the automatic "
                    f"manual-review threshold of {fmt_inr(thresholds.auto_manual_review_above)}."
                ),
            )
        )

    return FraudAssessment(signals=signals, requires_manual_review=bool(signals))
