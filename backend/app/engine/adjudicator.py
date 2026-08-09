"""Adjudication engine — deterministic, zero LLM, never raises.

Runs every rule check in PLAN.md §6 order and returns the complete picture:
all checks (passing and failing), per-line-item verdicts, the eligible
amount, and the financial breakdown. The first failing check with a
rejection reason sets the primary reason; later failures stay visible in
`checks` and the trace.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from app.kb.semantic import SemanticHit
from app.kb.snapshot import PolicySnapshot
from app.models import (
    Adjudication,
    ClaimSubmission,
    Decision,
    ExtractedDocument,
    Outcome,
)
from app.models.documents import LineItem

from . import checks as C
from . import financial


@dataclass
class ClaimFacts:
    """What the documents tell us — assembled once, used by every check."""

    diagnosis: str | None = None
    treatment_text: str | None = None
    hospital_name: str | None = None
    line_items: list[LineItem] = field(default_factory=list)
    itemized: bool = True
    documented_total: Decimal | None = None
    notes: list[str] = field(default_factory=list)


def gather_facts(claim: ClaimSubmission, documents: list[ExtractedDocument]) -> ClaimFacts:
    facts = ClaimFacts()
    bill_total: Decimal | None = None
    documented_total: Decimal | None = None
    for doc in documents:
        content = doc.content
        if facts.diagnosis is None and content.diagnosis:
            facts.diagnosis = content.diagnosis
        if facts.treatment_text is None and content.treatment:
            facts.treatment_text = content.treatment
        if facts.hospital_name is None and content.hospital_name:
            facts.hospital_name = content.hospital_name
        if content.line_items:
            facts.line_items.extend(content.line_items)
        elif content.total is not None:
            bill_total = content.total
    if facts.line_items:
        facts.documented_total = sum((i.amount for i in facts.line_items), Decimal(0))
    else:
        facts.documented_total = bill_total
        amount = bill_total if bill_total is not None else claim.claimed_amount
        facts.line_items = [LineItem(description="Billed amount (no itemized bill)", amount=amount)]
        facts.itemized = False
        facts.notes.append(
            "Bill has no itemized line items; adjudicated against the billed total."
        )
    return facts


def adjudicate(
    claim: ClaimSubmission,
    documents: list[ExtractedDocument],
    snapshot: PolicySnapshot,
    semantic_hints: list[SemanticHit] | None = None,
) -> Adjudication:
    facts = gather_facts(claim, documents)
    member = snapshot.get_member(claim.member_id)
    all_checks = []

    # §6 order: eligibility -> submission -> exclusions -> waiting -> pre-auth
    # -> line items -> per-claim cap -> financials
    all_checks += C.check_eligibility(claim, snapshot)
    all_checks += C.check_submission_rules(claim, snapshot)
    all_checks.append(
        C.check_amount_reconciliation(claim, facts.documented_total, facts.itemized)
    )

    exclusion_check, exclusion_match = C.check_exclusions(
        claim, facts.diagnosis, facts.treatment_text, snapshot, semantic_hints
    )
    all_checks.append(exclusion_check)

    all_checks += C.check_waiting_periods(claim, member, facts.diagnosis, snapshot)
    all_checks.append(C.check_pre_authorization(claim, facts.line_items, snapshot))

    line_decisions, line_check = C.adjudicate_line_items(
        claim, facts.line_items, exclusion_match, snapshot
    )
    all_checks.append(line_check)

    eligible = sum((d.claimed_amount for d in line_decisions if d.approved), Decimal(0))
    all_checks.append(C.check_per_claim_cap(claim, eligible, snapshot))

    rejections = [c.rejection_reason for c in all_checks if c.rejection_reason is not None]
    notes = list(facts.notes)

    if rejections:
        decision = Decision.REJECTED
        breakdown = None
    else:
        if any(not d.approved for d in line_decisions):
            decision = Decision.PARTIAL
        else:
            decision = Decision.APPROVED
        cat_terms = snapshot.category_terms(claim.claim_category)
        breakdown, fin_notes = financial.compute_breakdown(
            category=claim.claim_category,
            cat_terms=cat_terms,
            coverage=snapshot.terms.coverage,
            line_items=line_decisions,
            is_network_hospital=snapshot.is_network_hospital(
                claim.hospital_name or facts.hospital_name
            ),
            ytd_claims_amount=claim.ytd_claims_amount,
        )
        notes += fin_notes

    return Adjudication(
        checks=all_checks,
        line_items=line_decisions,
        eligible_amount=eligible,
        financial=breakdown,
        decision=decision,
        rejection_reasons=rejections[:1],  # primary only; the rest stay in checks/trace
        notes=notes,
    )
