"""In-memory policy snapshot loaded from `policy_terms.json`.

This is the canonical rule source for Phase 1–3 and the permanent fallback
when the graph/vector stores are unavailable (PLAN.md §4). All lookups are
read-only accessors over the typed `PolicyTerms` model — no policy logic
(thresholds, ordering, decisions) lives here.
"""

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app.models.enums import ClaimCategory
from app.models.policy import (
    CategoryTerms,
    DocumentRequirements,
    Member,
    PolicyTerms,
)


class PolicySnapshot:
    """Read-only accessor over one policy's terms and member roster."""

    def __init__(self, terms: PolicyTerms):
        self.terms = terms
        self._members: dict[str, Member] = {m.member_id: m for m in terms.members}

    @classmethod
    def from_file(cls, path: Path | str) -> "PolicySnapshot":
        raw = Path(path).read_text(encoding="utf-8")
        return cls(PolicyTerms.model_validate_json(raw))

    # --- members -----------------------------------------------------------

    def get_member(self, member_id: str) -> Member | None:
        return self._members.get(member_id)

    def eligible_patients(self, member_id: str) -> list[Member]:
        """The member plus any dependents present in the roster.

        Dependent ids referenced but missing from the roster are skipped —
        the policy file references DEP003–DEP006 without defining them.
        """
        member = self.get_member(member_id)
        if member is None:
            return []
        patients = [member]
        patients += [d for dep_id in member.dependents if (d := self.get_member(dep_id))]
        return patients

    def effective_join_date(self, member: Member) -> date | None:
        """Join date for waiting-period math; dependents inherit the primary's."""
        if member.join_date is not None:
            return member.join_date
        if member.primary_member_id:
            primary = self.get_member(member.primary_member_id)
            if primary is not None:
                return primary.join_date
        return None

    # --- policy lookups ----------------------------------------------------

    def policy_active_on(self, day: date) -> bool:
        holder = self.terms.policy_holder
        return (
            holder.renewal_status == "ACTIVE"
            and holder.policy_start_date <= day <= holder.policy_end_date
        )

    def category_terms(self, category: ClaimCategory) -> CategoryTerms | None:
        return self.terms.opd_categories.get(category.value.lower())

    def document_requirements(self, category: ClaimCategory) -> DocumentRequirements | None:
        return self.terms.document_requirements.get(category.value)

    def per_claim_cap(self, category: ClaimCategory) -> Decimal:
        """Effective per-claim cap: max(per_claim_limit, category sub_limit).

        Documented assumption (PLAN.md §12.5): reconciles the global ₹5,000
        per-claim limit with categories whose sub-limit exceeds it (dental,
        diagnostic) — required for TC006 vs TC008 to both hold.
        """
        base = self.terms.coverage.per_claim_limit
        cat = self.category_terms(category)
        if cat is not None and cat.sub_limit > base:
            return cat.sub_limit
        return base

    def waiting_period_end(self, join_date: date, condition_key: str | None = None) -> date:
        """First eligible date: join date + initial period, or the
        condition-specific period when `condition_key` matches one."""
        days = self.terms.waiting_periods.initial_waiting_period_days
        if condition_key:
            days = self.terms.waiting_periods.specific_conditions.get(condition_key, days)
        return join_date + timedelta(days=days)

    def is_network_hospital(self, hospital_name: str | None) -> bool:
        if not hospital_name:
            return False
        needle = hospital_name.strip().lower()
        return any(h.strip().lower() == needle for h in self.terms.network_hospitals)
