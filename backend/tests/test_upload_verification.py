"""Upload-path verification behaviours the 12 assignment cases never exercise.

The eval cases hand the pipeline pre-typed documents, so everything the
classifier decides — and every way a real file can go wrong — is invisible to
them. These tests drive the vision path with a stub `DocumentAI`.
"""

import pytest

from app.agents.extraction import extract_documents
from app.agents.llm import PageClassification
from app.agents.verifier import verify_documents
from app.core.errors import DocumentVerificationStop
from app.models import (
    ClaimSubmission,
    DocumentContent,
    DocumentProblemKind,
    DocumentQuality,
    DocumentType,
)
from app.models.claim import SubmittedDocument
from app.orchestrator.trace import TraceBuilder
from tests.helpers import legible_page


class StubDocumentAI:
    """Vision stand-in: returns scripted page classifications per file name."""

    is_configured = True

    def __init__(self, pages_by_name: dict[str, list[PageClassification]]):
        self._pages = pages_by_name

    def classify(self, image_path) -> list[PageClassification]:
        return self._pages[image_path.name]

    def extract(self, image_path, doc_type):
        return DocumentContent(patient_name="Rajesh Kumar"), {"patient_name": 1.0}, []


def _claim(*documents: SubmittedDocument, category: str = "CONSULTATION") -> ClaimSubmission:
    return ClaimSubmission(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category=category,
        treatment_date="2024-11-01",
        claimed_amount=1500,
        documents=list(documents),
    )


def _doc(file_id: str, path) -> SubmittedDocument:
    return SubmittedDocument(file_id=file_id, file_name=path.name, storage_path=str(path))


def _good(doc_type: DocumentType) -> PageClassification:
    return PageClassification(doc_type, 0.95, DocumentQuality.GOOD)


def test_damaged_file_is_not_also_accused_of_being_the_wrong_type(tmp_path, snapshot):
    """A file that would not open tells us nothing about its type.

    Reporting it as a missing/wrong document as well sends the member to
    replace a document we never saw, and the file may be the very one
    required.
    """
    broken = tmp_path / "corrupt.jpg"
    broken.write_bytes(b"not an image" * 20)
    bill = legible_page(tmp_path / "bill.jpg")
    claim = _claim(_doc("F001", broken), _doc("F002", bill))
    doc_ai = StubDocumentAI({"bill.jpg": [_good(DocumentType.HOSPITAL_BILL)]})

    with pytest.raises(DocumentVerificationStop) as stop:
        verify_documents(claim, snapshot, TraceBuilder("CLM_TEST"), doc_ai)

    problems = stop.value.problems
    assert [p.kind for p in problems] == [DocumentProblemKind.UNREADABLE]
    assert "could not be opened" in problems[0].message


def test_one_pdf_holding_two_documents_satisfies_both_requirements(tmp_path, snapshot):
    """Members routinely scan a whole claim into a single PDF.

    Typing the file by its first page reported the second document as
    missing — a specific, actionable, and false instruction.
    """
    scan = legible_page(tmp_path / "scan.pdf")
    claim = _claim(_doc("F001", scan))
    doc_ai = StubDocumentAI({
        "scan.pdf": [_good(DocumentType.PRESCRIPTION), _good(DocumentType.HOSPITAL_BILL)]
    })

    verified = verify_documents(claim, snapshot, TraceBuilder("CLM_TEST"), doc_ai)

    assert len(verified.documents) == 1
    assert verified.documents[0].doc_type is DocumentType.PRESCRIPTION


def test_second_page_read_at_low_confidence_does_not_satisfy_a_requirement(tmp_path, snapshot):
    """A hesitant reading is not evidence a document was supplied."""
    scan = legible_page(tmp_path / "scan.pdf")
    claim = _claim(_doc("F001", scan))
    doc_ai = StubDocumentAI({
        "scan.pdf": [
            _good(DocumentType.PRESCRIPTION),
            PageClassification(DocumentType.HOSPITAL_BILL, 0.3, DocumentQuality.GOOD),
        ]
    })

    with pytest.raises(DocumentVerificationStop) as stop:
        verify_documents(claim, snapshot, TraceBuilder("CLM_TEST"), doc_ai)

    assert stop.value.problems[0].required == "HOSPITAL_BILL"


def test_extraction_records_its_own_duration_per_document(tmp_path, snapshot):
    """Extraction runs concurrently, so wall-clock between trace steps would
    misattribute the time; each step carries its own measurement."""
    prescription = legible_page(tmp_path / "rx.jpg")
    bill = legible_page(tmp_path / "bill.jpg")
    claim = _claim(_doc("F001", prescription), _doc("F002", bill))
    doc_ai = StubDocumentAI({
        "rx.jpg": [_good(DocumentType.PRESCRIPTION)],
        "bill.jpg": [_good(DocumentType.HOSPITAL_BILL)],
    })
    tb = TraceBuilder("CLM_TEST")
    verified = verify_documents(claim, snapshot, tb, doc_ai)

    extracted = extract_documents(verified.documents, doc_ai, tb, [])

    assert len(extracted) == 2
    assert all(s.duration_ms is not None for s in tb.steps)
    # Order follows the submission, not whichever extraction finished first.
    assert [d.file_id for d in extracted] == ["F001", "F002"]


def test_a_null_field_score_from_the_model_does_not_crash_the_claim(monkeypatch, tmp_path):
    """The schema declares a number; gpt-4o intermittently sends null anyway."""
    from app.agents.llm import DocumentAI
    from app.core.config import Settings

    ai = DocumentAI(Settings(openai_api_key="test-key"))
    monkeypatch.setattr(
        DocumentAI,
        "_vision_call",
        lambda self, system, path, schema: (
            {"patient_name": "Rajesh Kumar", "field_confidence": {"patient_name": None}, "warnings": None},
            1,
        ),
    )

    content, confidence, warnings = ai.extract(tmp_path / "bill.jpg", DocumentType.HOSPITAL_BILL)

    assert content.patient_name == "Rajesh Kumar"
    assert confidence == {"patient_name": 0.0}
    assert warnings == []
