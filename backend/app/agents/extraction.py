"""Extraction agent — Phase 2 ships only the test-mode path.

When a submitted document carries pre-extracted `content` (eval cases), it is
converted to an `ExtractedDocument` with `extraction_skipped=True` and full
field confidence. The GPT-4o vision path plugs in here in Phase 4 behind the
same output contract.
"""

from app.models import DocumentQuality, DocumentType, ExtractedDocument
from app.models.claim import SubmittedDocument
from app.models.documents import DocumentContent


def from_submitted(doc: SubmittedDocument) -> ExtractedDocument:
    """Test-mode extraction: trust the declared type and supplied content."""
    content = doc.content or DocumentContent()
    if content.patient_name is None and doc.patient_name_on_doc:
        content = content.model_copy(update={"patient_name": doc.patient_name_on_doc})
    return ExtractedDocument(
        file_id=doc.file_id,
        doc_type=doc.actual_type or DocumentType.PRESCRIPTION,
        quality=doc.quality or DocumentQuality.GOOD,
        content=content,
        field_confidence={
            name: 1.0 for name, value in content.model_dump().items() if value is not None
        },
        extraction_skipped=True,
    )
