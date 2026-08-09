"""Adjudication engine and decision contracts.

The engine is a pure function: `ExtractedClaim + ApplicableRules + MemberContext
-> Adjudication`. It never raises — every rule outcome, passing or failing,
is recorded and the financial breakdown shows each computation step in order
(network discount before co-pay, TC010).
"""

from decimal import Decimal

from pydantic import BaseModel, Field

from .enums import Decision, FraudSignalCode, Outcome, RejectionReason
from .trace import DecisionTrace


class RuleCheck(BaseModel):
    """Outcome of one adjudication rule (§6 of the plan)."""

    rule_ref: str = Field(description="Pointer into policy terms.")
    name: str = Field(description="Short rule name, e.g. 'waiting_period.diabetes'.")
    outcome: Outcome
    detail: str = Field(description="Specific result incl. relevant numbers/dates.")
    rejection_reason: RejectionReason | None = Field(
        default=None, description="Set when outcome is FAIL and the rule rejects."
    )


class LineItemDecision(BaseModel):
    """Per-line-item verdict (TC006 requires itemized reasons)."""

    description: str
    claimed_amount: Decimal
    approved: bool
    reason: str | None = Field(
        default=None, description="Why this item was rejected (when approved=False)."
    )
    rule_ref: str | None = None


class FinancialStep(BaseModel):
    """One step of the ordered financial computation (order is graded, TC010)."""

    step: str = Field(description="e.g. 'eligible_base', 'network_discount', 'copay'.")
    description: str
    amount_before: Decimal
    adjustment: Decimal = Field(description="Signed change applied at this step.")
    amount_after: Decimal
    rule_ref: str | None = None


class FinancialBreakdown(BaseModel):
    """Ordered computation from eligible base to final payable amount."""

    steps: list[FinancialStep]
    final_payable: Decimal


class Adjudication(BaseModel):
    """Complete engine output — all checks run, even after a hard fail."""

    checks: list[RuleCheck]
    line_items: list[LineItemDecision] = Field(default_factory=list)
    eligible_amount: Decimal = Field(
        description="Claimed amount minus excluded line items; basis of the per-claim cap check."
    )
    financial: FinancialBreakdown | None = Field(
        default=None, description="Present unless the claim was hard-rejected."
    )
    decision: Decision = Field(description="Engine-recommended decision (pre-fraud/confidence).")
    rejection_reasons: list[RejectionReason] = Field(
        default_factory=list,
        description="Primary reason first, per §6 check order.",
    )
    notes: list[str] = Field(default_factory=list)


class FraudSignal(BaseModel):
    """One named fraud indicator (TC009 requires specific signals in output)."""

    code: FraudSignalCode
    detail: str


class FraudAssessment(BaseModel):
    """Output of the fraud checker's velocity/document rules."""

    signals: list[FraudSignal] = Field(default_factory=list)
    requires_manual_review: bool = False


class ClaimDecision(BaseModel):
    """Final pipeline output — the API response for a decided claim."""

    claim_id: str
    decision: Decision
    approved_amount: Decimal = Decimal(0)
    currency: str = "INR"
    reasons: list[str] = Field(
        description="Human-readable explanation of the decision, specific and actionable."
    )
    rejection_reasons: list[RejectionReason] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    manual_review_recommended: bool = Field(
        default=False,
        description="Set when confidence is in the 0.50–0.75 gray zone or processing degraded (TC011).",
    )
    fraud_signals: list[FraudSignal] = Field(default_factory=list)
    line_items: list[LineItemDecision] = Field(default_factory=list)
    financial: FinancialBreakdown | None = None
    degraded_components: list[str] = Field(default_factory=list)
    trace: DecisionTrace
