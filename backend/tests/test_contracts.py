"""Contract tests: every eval case input must parse through ClaimSubmission.

This is the Phase 1 exit gate — if these pass, the eval runner can feed
`test_cases.json` to the pipeline verbatim.
"""

from decimal import Decimal

import pytest

from app.models import ClaimCategory, ClaimSubmission, DocumentType


def test_all_twelve_cases_parse(test_cases):
    assert len(test_cases) == 12
    parsed = {c["case_id"]: ClaimSubmission.model_validate(c["input"]) for c in test_cases}
    assert set(parsed) == {f"TC{i:03d}" for i in range(1, 13)}


@pytest.fixture(scope="module")
def by_id(test_cases):
    return {c["case_id"]: c["input"] for c in test_cases}


def test_tc004_documents_fully_typed(by_id):
    claim = ClaimSubmission.model_validate(by_id["TC004"])
    assert claim.claim_category is ClaimCategory.CONSULTATION
    assert claim.claimed_amount == Decimal(1500)
    assert claim.ytd_claims_amount == Decimal(5000)
    rx, bill = claim.documents
    assert rx.actual_type is DocumentType.PRESCRIPTION
    assert rx.content.diagnosis == "Viral Fever"
    assert bill.actual_type is DocumentType.HOSPITAL_BILL
    assert [i.amount for i in bill.content.line_items] == [1000, 300, 200]
    assert bill.content.total == Decimal(1500)


def test_tc009_claims_history_parses(by_id):
    claim = ClaimSubmission.model_validate(by_id["TC009"])
    assert len(claim.claims_history) == 3
    assert all(e.date.isoformat() == "2024-10-30" for e in claim.claims_history)
    assert claim.claims_history[0].provider == "City Clinic A"


def test_tc011_failure_simulation_flag(by_id):
    claim = ClaimSubmission.model_validate(by_id["TC011"])
    assert claim.simulate_component_failure is True
    assert claim.claim_category is ClaimCategory.ALTERNATIVE_MEDICINE


def test_tc002_quality_and_tc003_patient_names(by_id):
    tc002 = ClaimSubmission.model_validate(by_id["TC002"])
    assert tc002.documents[1].quality.value == "UNREADABLE"
    tc003 = ClaimSubmission.model_validate(by_id["TC003"])
    assert tc003.documents[0].patient_name_on_doc == "Rajesh Kumar"
    assert tc003.documents[1].patient_name_on_doc == "Arjun Mehta"


def test_rejects_unknown_top_level_field():
    with pytest.raises(ValueError):
        ClaimSubmission.model_validate(
            {
                "member_id": "EMP001",
                "policy_id": "P",
                "claim_category": "CONSULTATION",
                "treatment_date": "2024-11-01",
                "claimed_amount": 100,
                "documents": [{"file_id": "F1"}],
                "not_a_field": True,
            }
        )
