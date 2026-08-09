"""Extraction agent — dual-mode.

Test mode: a verified document carrying pre-extracted `content` becomes an
`ExtractedDocument` with `extraction_skipped=True` and full field confidence.
Real mode: GPT-4o vision extracts from the stored file with per-field
confidence and legibility warnings. Per the resilience table: if the LLM is
down and no pre-extracted content exists, processing stops with retry
guidance (`ComponentUnavailable`) — the one failure the pipeline cannot
degrade around.
"""

from pathlib import Path

from app.agents.llm import DocumentAI
from app.core.errors import ComponentUnavailable
from app.models import DocumentQuality, ExtractedDocument, Outcome, VerifiedDocument
from app.models.documents import DocumentContent
from app.orchestrator.trace import TraceBuilder

PENALTY_LOW_FIELD_CONFIDENCE = -0.10
LOW_FIELD_THRESHOLD = 0.7


def from_verified(doc: VerifiedDocument) -> ExtractedDocument:
    """Test-mode extraction: trust the verified type and supplied content."""
    content = doc.content or DocumentContent()
    if content.patient_name is None and doc.patient_name_on_doc:
        content = content.model_copy(update={"patient_name": doc.patient_name_on_doc})
    return ExtractedDocument(
        file_id=doc.file_id,
        file_name=doc.file_name,
        doc_type=doc.doc_type,
        quality=doc.quality or DocumentQuality.GOOD,
        content=content,
        field_confidence={
            name: 1.0 for name, value in content.model_dump().items() if value is not None
        },
        extraction_skipped=True,
    )


def extract_documents(
    documents: list[VerifiedDocument],
    doc_ai: DocumentAI | None,
    tb: TraceBuilder,
    penalties: list[tuple[str, float]],
) -> list[ExtractedDocument]:
    """Extract every verified document, choosing the mode per document."""
    extracted: list[ExtractedDocument] = []
    live, skipped = 0, 0
    for doc in documents:
        # Nothing to extract *from*: the submission supplied the document's
        # contents itself (eval cases), so pass them through unchanged.
        if doc.content is not None or doc.storage_path is None:
            extracted.append(from_verified(doc))
            skipped += 1
            continue
        if doc_ai is None or not doc_ai.is_configured:
            raise ComponentUnavailable(
                "extraction_agent",
                f"Document {doc.file_id} has no pre-extracted content and no vision "
                f"extraction is available. Please retry later — the claim was not decided.",
            )
        try:
            content, confidence, warnings = doc_ai.extract(Path(doc.storage_path), doc.doc_type)
        except ComponentUnavailable as exc:
            raise ComponentUnavailable(
                "extraction_agent",
                f"Extraction failed for document {doc.file_id} ({exc.message}). "
                f"Please retry later — the claim was not decided.",
            ) from exc
        extracted.append(
            ExtractedDocument(
                file_id=doc.file_id,
                file_name=doc.file_name,
                doc_type=doc.doc_type,
                quality=doc.quality,
                content=content,
                field_confidence=confidence,
                warnings=warnings,
            )
        )
        live += 1
        low = [k for k, v in confidence.items() if v < LOW_FIELD_THRESHOLD]
        if low or warnings:
            name = doc.file_name or doc.file_id
            detail = (
                f"Some fields on '{name}' were hard to read"
                + (f" ({', '.join(low)})" if low else "")
                + (f"; the reader noted: {'; '.join(warnings)}" if warnings else "")
                + "."
            )
            penalties.append((detail, PENALTY_LOW_FIELD_CONFIDENCE))
            tb.step(
                "extraction_agent", "field confidence review", Outcome.DEGRADED, detail,
                confidence_delta=PENALTY_LOW_FIELD_CONFIDENCE,
            )
    tb.step(
        "extraction_agent",
        action="extract structured data from documents",
        outcome=Outcome.PASS if live else Outcome.SKIPPED,
        detail=(
            f"{live} document(s) extracted via GPT-4o vision; {skipped} used pre-extracted "
            f"content (test mode)."
            if live
            else "Pre-extracted content supplied with the submission; vision extraction skipped (test mode)."
        ),
        input_summary=", ".join(f"{d.file_id}:{d.doc_type.value}" for d in extracted),
    )
    return extracted
