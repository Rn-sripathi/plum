"""Claim store round-trip tests."""

from app.core.store import SqliteClaimStore
from app.models import ClaimSubmission
from app.orchestrator.pipeline import process_claim


def test_save_get_roundtrip(tmp_path, snapshot, test_cases):
    store = SqliteClaimStore(tmp_path / "claims.db")
    case = next(c for c in test_cases if c["case_id"] == "TC004")
    submission = ClaimSubmission.model_validate(case["input"])
    result = process_claim(submission, snapshot, claim_id="TC004")

    store.save(submission, result)
    record = store.get("TC004")
    assert record is not None
    assert record["status"] == "APPROVED"
    assert record["member_id"] == "EMP001"
    assert record["result"]["approved_amount"] == "1350.00"
    assert record["result"]["trace"]["steps"], "trace persisted with the decision"

    assert store.get("MISSING") is None
    assert store.list_recent() and store.list_recent()[0]["claim_id"] == "TC004"
    assert store.healthy()
