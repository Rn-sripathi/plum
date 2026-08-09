"""TC001–TC003: early document-problem detection. The message quality is part
of the evaluation — these tests assert the member-facing text names the exact
document types, files, and patient names involved."""

import pytest

from app.models import ClaimSubmission, DocumentProblemKind
from app.models.documents import DocumentProblemReport
from app.orchestrator.pipeline import process_claim


@pytest.fixture(scope="module")
def reports(test_cases, snapshot):
    out = {}
    for case in test_cases:
        if case["case_id"] in ("TC001", "TC002", "TC003"):
            sub = ClaimSubmission.model_validate(case["input"])
            out[case["case_id"]] = process_claim(sub, snapshot, claim_id=case["case_id"])
    return out


@pytest.mark.parametrize("case_id", ["TC001", "TC002", "TC003"])
def test_stops_without_decision(case_id, reports):
    report = reports[case_id]
    assert isinstance(report, DocumentProblemReport)
    assert report.decision is None
    assert report.problems, "must carry at least one specific problem"
    for p in report.problems:
        assert p.message and p.action_needed, "every problem must be actionable"


def test_tc001_names_uploaded_and_required_types(reports):
    p = reports["TC001"].problems[0]
    assert p.kind is DocumentProblemKind.WRONG_TYPE
    assert p.found == "PRESCRIPTION"
    assert p.required == "HOSPITAL_BILL"
    assert "PRESCRIPTION" in p.message and "HOSPITAL_BILL" in p.message
    assert "hospital bill" in p.action_needed.lower()


def test_tc002_asks_reupload_of_specific_document(reports):
    problems = reports["TC002"].problems
    assert len(problems) == 1  # only the blurry bill is a problem
    p = problems[0]
    assert p.kind is DocumentProblemKind.UNREADABLE
    assert p.file_name == "blurry_bill.jpg"
    assert "too blurred to read" in p.message
    assert "re-upload" in p.action_needed.lower()
    # Names the one file to replace, and says the claim itself is fine.
    assert "blurry_bill.jpg" in p.action_needed
    assert "not been rejected" in p.message


def test_tc003_surfaces_both_patient_names(reports):
    problems = reports["TC003"].problems
    assert [p.kind for p in problems] == [DocumentProblemKind.PATIENT_MISMATCH]
    message = problems[0].message
    assert "Rajesh Kumar" in message and "Arjun Mehta" in message
    assert "prescription_rajesh.jpg" in message and "bill_arjun.jpg" in message


def test_trace_records_the_stop(reports):
    trace = reports["TC001"].trace
    assert any(s.component == "document_verifier" and s.outcome.value == "FAIL" for s in trace.steps)
