"""Policy snapshot loader tests against the real policy_terms.json."""

from datetime import date
from decimal import Decimal

from app.models import ClaimCategory


def test_policy_parses_with_key_figures(snapshot):
    assert snapshot.terms.policy_id == "PLUM_GHI_2024"
    assert snapshot.terms.coverage.per_claim_limit == Decimal(5000)
    assert snapshot.terms.submission_rules.minimum_claim_amount == Decimal(500)
    assert len(snapshot.terms.members) == 12


def test_member_and_dependent_resolution(snapshot):
    rajesh = snapshot.get_member("EMP001")
    assert rajesh is not None and rajesh.name == "Rajesh Kumar"
    patients = snapshot.eligible_patients("EMP001")
    assert {p.member_id for p in patients} == {"EMP001", "DEP001", "DEP002"}
    assert snapshot.get_member("NOPE") is None
    assert snapshot.eligible_patients("NOPE") == []


def test_missing_dependents_are_tolerated(snapshot):
    # EMP007 references DEP004/DEP005 which are absent from the roster.
    patients = snapshot.eligible_patients("EMP007")
    assert {p.member_id for p in patients} == {"EMP007"}


def test_dependent_inherits_primary_join_date(snapshot):
    spouse = snapshot.get_member("DEP001")
    assert spouse.join_date is None
    assert snapshot.effective_join_date(spouse) == date(2024, 4, 1)


def test_category_terms_lookup(snapshot):
    consultation = snapshot.category_terms(ClaimCategory.CONSULTATION)
    assert consultation.copay_percent == Decimal(10)
    assert consultation.network_discount_percent == Decimal(20)
    dental = snapshot.category_terms(ClaimCategory.DENTAL)
    assert "Root Canal Treatment" in dental.covered_procedures
    assert "Teeth Whitening" in dental.excluded_procedures


def test_document_requirements(snapshot):
    reqs = snapshot.document_requirements(ClaimCategory.CONSULTATION)
    assert reqs.required == ["PRESCRIPTION", "HOSPITAL_BILL"]
    pharmacy = snapshot.document_requirements(ClaimCategory.PHARMACY)
    assert pharmacy.required == ["PRESCRIPTION", "PHARMACY_BILL"]


def test_per_claim_cap_assumption(snapshot):
    # PLAN.md §12.5: effective cap = max(per_claim_limit, category sub_limit).
    assert snapshot.per_claim_cap(ClaimCategory.CONSULTATION) == Decimal(5000)
    assert snapshot.per_claim_cap(ClaimCategory.DENTAL) == Decimal(10000)
    assert snapshot.per_claim_cap(ClaimCategory.DIAGNOSTIC) == Decimal(10000)
    assert snapshot.per_claim_cap(ClaimCategory.PHARMACY) == Decimal(15000)


def test_waiting_period_end_diabetes(snapshot):
    # TC005: joined 2024-09-01 + 90 days -> eligible 2024-11-30.
    assert snapshot.waiting_period_end(date(2024, 9, 1), "diabetes") == date(2024, 11, 30)
    # Unknown condition falls back to the 30-day initial period.
    assert snapshot.waiting_period_end(date(2024, 9, 1)) == date(2024, 10, 1)


def test_network_hospital_matching(snapshot):
    assert snapshot.is_network_hospital("Apollo Hospitals")
    assert snapshot.is_network_hospital("  apollo hospitals ")
    assert not snapshot.is_network_hospital("City Clinic, Bengaluru")
    assert not snapshot.is_network_hospital(None)


def test_policy_active_window(snapshot):
    assert snapshot.policy_active_on(date(2024, 11, 1))
    assert not snapshot.policy_active_on(date(2025, 4, 1))
