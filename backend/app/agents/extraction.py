"""Extraction agent — dual-mode.

Test mode: a verified document carrying pre-extracted `content` becomes an
`ExtractedDocument` with `extraction_skipped=True` and full field confidence.
Real mode: GPT-4o vision extracts from the stored file with per-field
confidence and legibility warnings. Per the resilience table: if the LLM is
down and no pre-extracted content exists, processing stops with retry
guidance (`ComponentUnavailable`) — the one failure the pipeline cannot
degrade around.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter

from app.agents.llm import DocumentAI
from app.core.errors import ComponentUnavailable
from app.models import DocumentQuality, ExtractedDocument, Outcome, VerifiedDocument
from app.models.documents import DocumentContent
from app.orchestrator.trace import TraceBuilder

PENALTY_LOW_FIELD_CONFIDENCE = -0.10
LOW_FIELD_THRESHOLD = 0.7
# Documents per claim are few; the cap exists so a pathological upload cannot
# open an unbounded number of connections to the vision API at once.
MAX_PARALLEL_EXTRACTIONS = 4


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
    """Extract every verified document, choosing the mode per document.

    Vision extraction is the pipeline's only slow stage — seconds per document,
    and a claim carries several. The calls are independent, so they run
    concurrently and the claim waits for the slowest rather than the sum. The
    trace is written afterwards in document order: concurrency must not make
    the record of a decision non-deterministic.
    """
    live_docs = [
        (i, doc)
        for i, doc in enumerate(documents)
        # Nothing to extract *from*: the submission supplied the document's
        # contents itself (eval cases), so pass them through unchanged.
        if doc.content is None and doc.storage_path is not None
    ]
    if live_docs and (doc_ai is None or not doc_ai.is_configured):
        raise ComponentUnavailable(
            "extraction_agent",
            f"Document {live_docs[0][1].file_id} has no pre-extracted content and no vision "
            f"extraction is available. Please retry later — the claim was not decided.",
        )

    def read(doc: VerifiedDocument) -> tuple[DocumentContent, dict[str, float], list[str], float]:
        started = perf_counter()
        try:
            content, confidence, warnings = doc_ai.extract(Path(doc.storage_path), doc.doc_type)
        except ComponentUnavailable as exc:
            raise ComponentUnavailable(
                "extraction_agent",
                f"Extraction failed for document {doc.file_id} ({exc.message}). "
                f"Please retry later — the claim was not decided.",
            ) from exc
        return content, confidence, warnings, (perf_counter() - started) * 1000

    reads: dict[int, tuple] = {}
    if live_docs:
        with ThreadPoolExecutor(max_workers=min(len(live_docs), MAX_PARALLEL_EXTRACTIONS)) as pool:
            futures = {pool.submit(read, doc): i for i, doc in live_docs}
            for future in futures:
                reads[futures[future]] = future.result()

    extracted: list[ExtractedDocument] = []
    live, skipped = 0, 0
    for i, doc in enumerate(documents):
        if i not in reads:
            extracted.append(from_verified(doc))
            skipped += 1
            continue
        content, confidence, warnings, elapsed_ms = reads[i]
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
        # The model scores every field in the schema, and reports 0.0 for the
        # ones that field simply is not on this kind of document — a
        # prescription has no line_items or total. Only a field that was
        # actually read can have been hard to read; a field it tried and failed
        # to recover is reported in `warnings`, which is penalized either way.
        present = content.model_dump()
        low = [
            k
            for k, v in confidence.items()
            if v < LOW_FIELD_THRESHOLD and present.get(k) is not None
        ]
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
                duration_ms=round(elapsed_ms, 1),
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
