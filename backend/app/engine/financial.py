"""Ordered financial computation — the order is graded (TC010):

    eligible base -> network discount -> co-pay -> sub-limit cap -> annual limit

Each step is recorded with before/adjustment/after amounts so the decision
output can show the full breakdown.
"""

from decimal import ROUND_HALF_UP, Decimal

from app.models import ClaimCategory, FinancialBreakdown, FinancialStep, LineItemDecision
from app.models.policy import CategoryTerms, Coverage

TWO_PLACES = Decimal("0.01")


def rupees(x: Decimal) -> Decimal:
    return x.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_breakdown(
    category: ClaimCategory,
    cat_terms: CategoryTerms,
    coverage: Coverage,
    line_items: list[LineItemDecision],
    is_network_hospital: bool,
    ytd_claims_amount: Decimal | None,
) -> tuple[FinancialBreakdown, list[str]]:
    """Compute the payable amount from approved line items. Returns the
    breakdown plus notes for any assumptions made along the way."""
    notes: list[str] = []
    cat_key = category.value.lower()
    steps: list[FinancialStep] = []

    eligible = rupees(sum((d.claimed_amount for d in line_items if d.approved), Decimal(0)))
    running = eligible
    steps.append(
        FinancialStep(
            step="eligible_base",
            description=f"Eligible base: sum of {sum(1 for d in line_items if d.approved)} approved line item(s).",
            amount_before=eligible,
            adjustment=Decimal(0),
            amount_after=eligible,
        )
    )

    discount_pct = cat_terms.network_discount_percent if is_network_hospital else Decimal(0)
    discount = rupees(running * discount_pct / 100)
    steps.append(
        FinancialStep(
            step="network_discount",
            description=(
                f"Network hospital discount ({discount_pct}%) applied."
                if is_network_hospital and discount_pct
                else "No network discount (provider not in network or category has none)."
            ),
            amount_before=running,
            adjustment=-discount,
            amount_after=running - discount,
            rule_ref=f"opd_categories.{cat_key}.network_discount_percent",
        )
    )
    running -= discount

    copay = rupees(running * cat_terms.copay_percent / 100)
    steps.append(
        FinancialStep(
            step="copay",
            description=(
                f"Co-pay ({cat_terms.copay_percent}%) borne by member."
                if copay
                else f"No co-pay for {cat_key} claims."
            ),
            amount_before=running,
            adjustment=-copay,
            amount_after=running - copay,
            rule_ref=f"opd_categories.{cat_key}.copay_percent",
        )
    )
    running -= copay

    # Sub-limit: for CONSULTATION it binds only the consultation-fee line items
    # (PLAN.md §12.1); for other categories it caps the whole claim amount.
    if category is ClaimCategory.CONSULTATION:
        fee_total = sum(
            (d.claimed_amount for d in line_items if d.approved and "consultation" in d.description.lower()),
            Decimal(0),
        )
        excess = max(Decimal(0), fee_total - cat_terms.sub_limit)
        if excess:
            # The excess was billed pre-discount/co-pay; deduct it scaled the same way.
            scale = (1 - discount_pct / 100) * (1 - cat_terms.copay_percent / 100)
            cap_cut = rupees(excess * scale)
            desc = (
                f"Consultation-fee line items total {fee_total}, above the "
                f"{cat_terms.sub_limit} sub-limit; excess deducted."
            )
        else:
            cap_cut = Decimal(0)
            desc = f"Consultation-fee line items within the {cat_terms.sub_limit} sub-limit."
    else:
        cap_cut = max(Decimal(0), running - cat_terms.sub_limit)
        desc = (
            f"Amount capped at the {cat_key} sub-limit of {cat_terms.sub_limit}."
            if cap_cut
            else f"Within the {cat_key} sub-limit of {cat_terms.sub_limit}."
        )
    steps.append(
        FinancialStep(
            step="sub_limit_cap",
            description=desc,
            amount_before=running,
            adjustment=-cap_cut,
            amount_after=running - cap_cut,
            rule_ref=f"opd_categories.{cat_key}.sub_limit",
        )
    )
    running -= cap_cut

    if ytd_claims_amount is None:
        ytd = Decimal(0)
        notes.append("YTD claims amount not provided; assumed ₹0 for the annual OPD limit check.")
    else:
        ytd = ytd_claims_amount
    remaining_annual = max(Decimal(0), coverage.annual_opd_limit - ytd)
    annual_cut = max(Decimal(0), running - remaining_annual)
    steps.append(
        FinancialStep(
            step="annual_limit_cap",
            description=(
                f"Annual OPD limit {coverage.annual_opd_limit}: {remaining_annual} remaining after "
                f"{ytd} claimed YTD." + (" Amount capped." if annual_cut else "")
            ),
            amount_before=running,
            adjustment=-annual_cut,
            amount_after=running - annual_cut,
            rule_ref="coverage.annual_opd_limit",
        )
    )
    running -= annual_cut

    return FinancialBreakdown(steps=steps, final_payable=rupees(running)), notes
