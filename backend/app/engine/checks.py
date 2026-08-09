"""Individual adjudication rule checks (PLAN.md §6 order).

Every check returns a `RuleCheck` with a specific, number-and-date-bearing
detail string — these become trace steps and rejection messages. Checks never
raise; unknown/missing data degrades to SKIPPED with an explanation.
"""

import datetime as dt
from decimal import Decimal

from app.engine import matching
from app.kb.semantic import SemanticHit
from app.kb.snapshot import PolicySnapshot
from app.models import (
    ClaimSubmission,
    LineItemDecision,
    Outcome,
    RejectionReason,
    RuleCheck,
)
from app.models.documents import LineItem
from app.models.policy import Member


def fmt_inr(amount: Decimal | int) -> str:
    """₹1,234.50 with trailing .00 stripped — used in member-facing messages."""
    d = Decimal(amount)
    sign = "-" if d < 0 else ""
    q = abs(d).quantize(Decimal("0.01"))
    text = f"{q:,.2f}".removesuffix(".00")
    return f"{sign}₹{text}"


def check_eligibility(claim: ClaimSubmission, snapshot: PolicySnapshot) -> list[RuleCheck]:
    checks: list[RuleCheck] = []
    member = snapshot.get_member(claim.member_id)
    if member is None:
        checks.append(
            RuleCheck(
                rule_ref="members",
                name="eligibility.member",
                outcome=Outcome.FAIL,
                detail=f"Member id '{claim.member_id}' is not in the policy roster.",
                rejection_reason=RejectionReason.MEMBER_NOT_FOUND,
            )
        )
    else:
        checks.append(
            RuleCheck(
                rule_ref="members",
                name="eligibility.member",
                outcome=Outcome.PASS,
                detail=f"Member {member.member_id} ({member.name}, {member.relationship}) found in roster.",
            )
        )

    holder = snapshot.terms.policy_holder
    if claim.policy_id != snapshot.terms.policy_id:
        checks.append(
            RuleCheck(
                rule_ref="policy_id",
                name="eligibility.policy",
                outcome=Outcome.FAIL,
                detail=f"Claim references policy '{claim.policy_id}' but the active policy is '{snapshot.terms.policy_id}'.",
                rejection_reason=RejectionReason.POLICY_INACTIVE,
            )
        )
    elif not snapshot.policy_active_on(claim.treatment_date):
        checks.append(
            RuleCheck(
                rule_ref="policy_holder",
                name="eligibility.policy",
                outcome=Outcome.FAIL,
                detail=(
                    f"Policy {snapshot.terms.policy_id} is not active on {claim.treatment_date} "
                    f"(period {holder.policy_start_date} to {holder.policy_end_date}, status {holder.renewal_status})."
                ),
                rejection_reason=RejectionReason.POLICY_INACTIVE,
            )
        )
    else:
        checks.append(
            RuleCheck(
                rule_ref="policy_holder",
                name="eligibility.policy",
                outcome=Outcome.PASS,
                detail=f"Policy {snapshot.terms.policy_id} active on treatment date {claim.treatment_date}.",
            )
        )
    return checks


def check_submission_rules(claim: ClaimSubmission, snapshot: PolicySnapshot) -> list[RuleCheck]:
    rules = snapshot.terms.submission_rules
    checks: list[RuleCheck] = []

    submitted = claim.submission_date or claim.treatment_date
    days = (submitted - claim.treatment_date).days
    if days > rules.deadline_days_from_treatment:
        checks.append(
            RuleCheck(
                rule_ref="submission_rules.deadline_days_from_treatment",
                name="submission.deadline",
                outcome=Outcome.FAIL,
                detail=(
                    f"Submitted {days} days after treatment ({claim.treatment_date}); "
                    f"the deadline is {rules.deadline_days_from_treatment} days."
                ),
                rejection_reason=RejectionReason.DEADLINE_EXCEEDED,
            )
        )
    else:
        checks.append(
            RuleCheck(
                rule_ref="submission_rules.deadline_days_from_treatment",
                name="submission.deadline",
                outcome=Outcome.PASS,
                detail=f"Submitted {days} days after treatment, within the {rules.deadline_days_from_treatment}-day deadline.",
            )
        )

    if claim.claimed_amount < rules.minimum_claim_amount:
        checks.append(
            RuleCheck(
                rule_ref="submission_rules.minimum_claim_amount",
                name="submission.minimum_amount",
                outcome=Outcome.FAIL,
                detail=(
                    f"Claimed amount {fmt_inr(claim.claimed_amount)} is below the minimum "
                    f"claimable amount of {fmt_inr(rules.minimum_claim_amount)}."
                ),
                rejection_reason=RejectionReason.BELOW_MINIMUM_AMOUNT,
            )
        )
    else:
        checks.append(
            RuleCheck(
                rule_ref="submission_rules.minimum_claim_amount",
                name="submission.minimum_amount",
                outcome=Outcome.PASS,
                detail=f"Claimed amount {fmt_inr(claim.claimed_amount)} meets the {fmt_inr(rules.minimum_claim_amount)} minimum.",
            )
        )
    return checks


# Calibrated against text-embedding-3-small live scores: true paraphrase
# matches land ~0.5–0.65 (e.g. "stomach reduction operation" -> "Bariatric
# surgery" at 0.57); unrelated diagnoses score well below 0.5.
SEMANTIC_EXCLUSION_THRESHOLD = 0.55


def check_exclusions(
    claim: ClaimSubmission,
    diagnosis: str | None,
    treatment_text: str | None,
    snapshot: PolicySnapshot,
    semantic_hints: list[SemanticHit] | None = None,
) -> tuple[RuleCheck, matching.ConceptMatch | None]:
    """Claim-level exclusion: diagnosis/treatment matched against the policy
    exclusion clauses. A match rejects the whole claim (TC012).

    Tiered: deterministic token match first; when it finds nothing, candidate
    matches from the vector index (computed upstream, passed in — the engine
    itself does no I/O) are accepted above SEMANTIC_EXCLUSION_THRESHOLD.
    """
    clauses = snapshot.terms.exclusions.conditions
    searched = " ; ".join(t for t in (diagnosis, treatment_text) if t)
    if not searched:
        return (
            RuleCheck(
                rule_ref="exclusions.conditions",
                name="exclusions.claim_level",
                outcome=Outcome.SKIPPED,
                detail="No diagnosis or treatment text available to screen against exclusions.",
            ),
            None,
        )
    match = matching.match_exclusion(searched, clauses)
    if match is None and semantic_hints:
        best = max(
            (
                h
                for h in semantic_hints
                if h.concept_type == "exclusion" and h.score >= SEMANTIC_EXCLUSION_THRESHOLD
            ),
            key=lambda h: h.score,
            default=None,
        )
        if best is not None:
            return (
                RuleCheck(
                    rule_ref=best.rule_ref,
                    name="exclusions.claim_level",
                    outcome=Outcome.FAIL,
                    detail=(
                        f"'{searched}' semantically matches policy exclusion '{best.concept}' "
                        f"(vector similarity {best.score:.2f}). This condition is not covered "
                        f"under the policy at any time."
                    ),
                    rejection_reason=RejectionReason.EXCLUDED_CONDITION,
                ),
                matching.ConceptMatch(concept=best.concept, matched_tokens=set(), score=best.score),
            )
    if match:
        return (
            RuleCheck(
                rule_ref="exclusions.conditions",
                name="exclusions.claim_level",
                outcome=Outcome.FAIL,
                detail=(
                    f"'{searched}' matches policy exclusion '{match.concept}' "
                    f"(matched on: {', '.join(sorted(match.matched_tokens))}). "
                    "This condition is not covered under the policy at any time."
                ),
                rejection_reason=RejectionReason.EXCLUDED_CONDITION,
            ),
            match,
        )
    return (
        RuleCheck(
            rule_ref="exclusions.conditions",
            name="exclusions.claim_level",
            outcome=Outcome.PASS,
            detail=f"Diagnosis/treatment ('{searched}') matches no policy exclusion.",
        ),
        None,
    )


def check_waiting_periods(
    claim: ClaimSubmission,
    member: Member | None,
    diagnosis: str | None,
    snapshot: PolicySnapshot,
) -> list[RuleCheck]:
    wp = snapshot.terms.waiting_periods
    if member is None:
        return [
            RuleCheck(
                rule_ref="waiting_periods",
                name="waiting_period",
                outcome=Outcome.SKIPPED,
                detail="Member unknown; waiting periods cannot be evaluated.",
            )
        ]
    join = snapshot.effective_join_date(member)
    if join is None:
        return [
            RuleCheck(
                rule_ref="waiting_periods",
                name="waiting_period",
                outcome=Outcome.SKIPPED,
                detail=f"No join date known for {member.member_id}; waiting periods cannot be evaluated.",
            )
        ]

    checks: list[RuleCheck] = []

    initial_from = join + dt.timedelta(days=wp.initial_waiting_period_days)
    if claim.treatment_date < initial_from:
        checks.append(
            RuleCheck(
                rule_ref="waiting_periods.initial_waiting_period_days",
                name="waiting_period.initial",
                outcome=Outcome.FAIL,
                detail=(
                    f"Treatment on {claim.treatment_date} falls in the initial "
                    f"{wp.initial_waiting_period_days}-day waiting period (joined {join}). "
                    f"Claims are eligible from {initial_from}."
                ),
                rejection_reason=RejectionReason.WAITING_PERIOD,
            )
        )
    else:
        checks.append(
            RuleCheck(
                rule_ref="waiting_periods.initial_waiting_period_days",
                name="waiting_period.initial",
                outcome=Outcome.PASS,
                detail=f"Initial {wp.initial_waiting_period_days}-day waiting period complete (joined {join}).",
            )
        )

    if diagnosis:
        key = matching.match_condition_key(diagnosis, list(wp.specific_conditions))
        if key:
            days = wp.specific_conditions[key]
            eligible_from = join + dt.timedelta(days=days)
            if claim.treatment_date < eligible_from:
                checks.append(
                    RuleCheck(
                        rule_ref=f"waiting_periods.specific_conditions.{key}",
                        name=f"waiting_period.{key}",
                        outcome=Outcome.FAIL,
                        detail=(
                            f"Diagnosis '{diagnosis}' falls under the {days}-day waiting period for "
                            f"{key.replace('_', ' ')} (member joined {join}). Treatment on "
                            f"{claim.treatment_date} is inside this period. The member is eligible "
                            f"for {key.replace('_', ' ')}-related claims from {eligible_from}."
                        ),
                        rejection_reason=RejectionReason.WAITING_PERIOD,
                    )
                )
            else:
                checks.append(
                    RuleCheck(
                        rule_ref=f"waiting_periods.specific_conditions.{key}",
                        name=f"waiting_period.{key}",
                        outcome=Outcome.PASS,
                        detail=f"{days}-day waiting period for {key.replace('_', ' ')} complete (eligible since {eligible_from}).",
                    )
                )
        else:
            checks.append(
                RuleCheck(
                    rule_ref="waiting_periods.specific_conditions",
                    name="waiting_period.condition_specific",
                    outcome=Outcome.PASS,
                    detail=f"Diagnosis '{diagnosis}' matches no condition-specific waiting period.",
                )
            )
    return checks


def check_pre_authorization(
    claim: ClaimSubmission,
    line_items: list[LineItem],
    snapshot: PolicySnapshot,
) -> RuleCheck:
    """Pre-auth via category terms: named high-value tests above the threshold
    require an authorization reference on the claim (TC007)."""
    cat = snapshot.category_terms(claim.claim_category)
    rule_ref = f"opd_categories.{claim.claim_category.value.lower()}.high_value_tests_requiring_pre_auth"
    if cat is None or not cat.high_value_tests_requiring_pre_auth:
        return RuleCheck(
            rule_ref=rule_ref,
            name="pre_authorization",
            outcome=Outcome.PASS,
            detail=f"No pre-authorization rules apply to {claim.claim_category.value} claims.",
        )

    threshold = cat.pre_auth_threshold or Decimal(0)
    validity = snapshot.terms.pre_authorization.validity_days
    for item in line_items:
        test = matching.match_in_list(item.description, cat.high_value_tests_requiring_pre_auth)
        if test and item.amount > threshold:
            if claim.pre_authorization_ref:
                return RuleCheck(
                    rule_ref=rule_ref,
                    name="pre_authorization",
                    outcome=Outcome.PASS,
                    detail=(
                        f"'{item.description}' ({fmt_inr(item.amount)}) requires pre-authorization; "
                        f"reference '{claim.pre_authorization_ref}' provided."
                    ),
                )
            return RuleCheck(
                rule_ref=rule_ref,
                name="pre_authorization",
                outcome=Outcome.FAIL,
                detail=(
                    f"'{item.description}' ({fmt_inr(item.amount)}) requires pre-authorization because "
                    f"{test} above {fmt_inr(threshold)} must be pre-approved, and no authorization was "
                    f"obtained. To resubmit: request pre-authorization from the insurer for this "
                    f"procedure and attach the approval reference (valid {validity} days from issue)."
                ),
                rejection_reason=RejectionReason.PRE_AUTH_MISSING,
            )
    return RuleCheck(
        rule_ref=rule_ref,
        name="pre_authorization",
        outcome=Outcome.PASS,
        detail="No line item triggers a pre-authorization requirement.",
    )


def adjudicate_line_items(
    claim: ClaimSubmission,
    line_items: list[LineItem],
    claim_exclusion: matching.ConceptMatch | None,
    snapshot: PolicySnapshot,
) -> tuple[list[LineItemDecision], RuleCheck]:
    """Per-item verdicts (TC006). When the claim itself is excluded, every
    item inherits that exclusion."""
    cat = snapshot.category_terms(claim.claim_category)
    cat_key = claim.claim_category.value.lower()
    decisions: list[LineItemDecision] = []

    if claim_exclusion is not None:
        for item in line_items:
            decisions.append(
                LineItemDecision(
                    description=item.description,
                    claimed_amount=item.amount,
                    approved=False,
                    reason=f"Claim excluded under policy: '{claim_exclusion.concept}'.",
                    rule_ref="exclusions.conditions",
                )
            )
        check = RuleCheck(
            rule_ref="exclusions.conditions",
            name="line_items",
            outcome=Outcome.FAIL,
            detail=f"All {len(line_items)} line item(s) rejected — the claim is excluded.",
        )
        return decisions, check

    excluded_list = (cat.excluded_procedures + cat.excluded_items) if cat else []
    # Category-specific exclusion lists live in two places in the policy file.
    extra_exclusions = {
        "dental": snapshot.terms.exclusions.dental_exclusions,
        "vision": snapshot.terms.exclusions.vision_exclusions,
    }.get(cat_key, [])

    for item in line_items:
        hit = matching.match_in_list(item.description, excluded_list + extra_exclusions)
        if hit:
            decisions.append(
                LineItemDecision(
                    description=item.description,
                    claimed_amount=item.amount,
                    approved=False,
                    reason=f"'{item.description}' is an excluded procedure under the {cat_key} category ('{hit}').",
                    rule_ref=f"opd_categories.{cat_key}.excluded_procedures",
                )
            )
            continue
        global_hit = matching.match_exclusion(item.description, snapshot.terms.exclusions.conditions)
        if global_hit:
            decisions.append(
                LineItemDecision(
                    description=item.description,
                    claimed_amount=item.amount,
                    approved=False,
                    reason=f"'{item.description}' matches policy exclusion '{global_hit.concept}'.",
                    rule_ref="exclusions.conditions",
                )
            )
            continue
        decisions.append(
            LineItemDecision(description=item.description, claimed_amount=item.amount, approved=True)
        )

    rejected = [d for d in decisions if not d.approved]
    outcome = Outcome.FAIL if rejected else Outcome.PASS
    detail = (
        f"{len(decisions) - len(rejected)} of {len(decisions)} line item(s) approved; "
        + "; ".join(f"'{d.description}' rejected: {d.reason}" for d in rejected)
        if rejected
        else f"All {len(decisions)} line item(s) covered under {cat_key}."
    )
    return decisions, RuleCheck(
        rule_ref=f"opd_categories.{cat_key}",
        name="line_items",
        outcome=outcome,
        detail=detail,
    )


def check_per_claim_cap(
    claim: ClaimSubmission, eligible_amount: Decimal, snapshot: PolicySnapshot
) -> RuleCheck:
    """Effective cap = max(per_claim_limit, category sub_limit), checked on the
    eligible amount after excluded items are removed (PLAN.md §12.5)."""
    cap = snapshot.per_claim_cap(claim.claim_category)
    base_limit = snapshot.terms.coverage.per_claim_limit
    rule_ref = (
        "coverage.per_claim_limit"
        if cap == base_limit
        else f"opd_categories.{claim.claim_category.value.lower()}.sub_limit"
    )
    if eligible_amount > cap:
        return RuleCheck(
            rule_ref=rule_ref,
            name="per_claim_limit",
            outcome=Outcome.FAIL,
            detail=(
                f"Claimed amount {fmt_inr(claim.claimed_amount)} (eligible {fmt_inr(eligible_amount)}) "
                f"exceeds the per-claim limit of {fmt_inr(cap)} for {claim.claim_category.value} claims. "
                f"Claims above this limit are not payable."
            ),
            rejection_reason=RejectionReason.PER_CLAIM_EXCEEDED,
        )
    return RuleCheck(
        rule_ref=rule_ref,
        name="per_claim_limit",
        outcome=Outcome.PASS,
        detail=f"Eligible amount {fmt_inr(eligible_amount)} is within the {fmt_inr(cap)} per-claim limit.",
    )
