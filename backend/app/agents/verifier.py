"""Document Verifier — fail-fast gate before any processing (TC001–TC003).

Checks, in order: required document types for the claim category, per-document
readability, cross-document patient consistency, and doctor-registration
format (warning only). Blocking problems raise `DocumentVerificationStop`
carrying member-facing `DocumentProblem`s — each names exactly what was found,
what is required, and what to do next. Generic errors are a spec violation.

Test mode trusts the declared `actual_type`/`quality`; the vision classifier
slots in here in Phase 4 behind the same contract.
"""

import re
from pathlib import Path

from app.agents.imaging import (
    POOR_SHARPNESS,
    UNREADABLE_SHARPNESS,
    is_decodable,
    measure_quality,
)
from app.agents.llm import DocumentAI
from app.core.errors import ComponentUnavailable, DocumentVerificationStop
from app.kb.snapshot import PolicySnapshot
from app.models import (
    ClaimSubmission,
    DocumentProblem,
    DocumentProblemKind,
    DocumentQuality,
    DocumentType,
    ExtractedDocument,
    Outcome,
    VerifiedDocument,
    VerifiedDocuments,
)
from app.orchestrator.trace import TraceBuilder

PENALTY_POOR_DOC = -0.10
PENALTY_UNVERIFIED_FIELD = -0.05

# A requirement names the evidence the insurer needs, not the department that
# produced it. `document_requirements.DIAGNOSTIC` asks for a LAB_REPORT, but an
# MRI claim's report is radiology, which the classifier correctly labels
# DIAGNOSTIC_REPORT. Without an equivalence, such a claim cannot satisfy its own
# requirement by any route: auto-detect reports a missing LAB_REPORT, and
# declaring one is contradicted by the classifier.
_EQUIVALENT_TYPES = {
    DocumentType.LAB_REPORT.value: {
        DocumentType.LAB_REPORT.value,
        DocumentType.DIAGNOSTIC_REPORT.value,
    },
    DocumentType.DIAGNOSTIC_REPORT.value: {
        DocumentType.DIAGNOSTIC_REPORT.value,
        DocumentType.LAB_REPORT.value,
    },
}


def _accepts(doc_type: str) -> set[str]:
    """Document types that satisfy a requirement for `doc_type`."""
    return _EQUIVALENT_TYPES.get(doc_type, {doc_type})


# State-format registration numbers per sample_documents_guide.md, plus the
# national Ayurveda format (AYUR/<STATE>/NNNN/YYYY).
_REG_RE = re.compile(r"^(?:[A-Z]{2}/\d{4,6}/(?:19|20)\d{2}|AYUR/[A-Z]{2}/\d{3,6}/(?:19|20)\d{2})$")


def _norm_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def verify_documents(
    claim: ClaimSubmission,
    snapshot: PolicySnapshot,
    tb: TraceBuilder,
    doc_ai: DocumentAI | None = None,
) -> VerifiedDocuments:
    problems: list[DocumentProblem] = []
    warnings: list[str] = []
    docs = claim.documents
    category = claim.claim_category.value

    # 0. Establish each document's effective type and quality --------------------
    # Test mode: declared `actual_type` is ground truth. Real mode: GPT-4o vision
    # classifies the file; a mismatch with the declared type is a blocking
    # problem; a classifier outage degrades to trusting the declared type.
    eff_types: list[DocumentType | None] = []
    eff_quality: list[DocumentQuality | None] = []
    type_sources: list[str] = []
    damaged: set[str] = set()
    illegible: set[str] = set()
    # Types found on a file's later pages. A single PDF can carry a whole
    # claim's paperwork, and those pages satisfy requirements too.
    further_types: list[list[DocumentType]] = []
    for doc in docs:
        eff, quality, source = doc.actual_type, doc.quality, "DECLARED"
        extra: list[DocumentType] = []

        # Legibility is measured in code, not asked of the model: a heavily
        # blurred bill came back classified PRESCRIPTION at 0.95 with quality
        # GOOD, which turned "your bill is unreadable" into a false accusation
        # that the member uploaded the wrong document. An illegible file is
        # never classified — there is nothing there to classify.
        if doc.storage_path and is_decodable(Path(doc.storage_path)):
            measured, score = measure_quality(Path(doc.storage_path))
            if measured is DocumentQuality.UNREADABLE:
                quality = DocumentQuality.UNREADABLE
                tb.step(
                    "document_verifier", "image legibility", Outcome.FAIL,
                    f"{doc.file_id} ('{doc.file_name or doc.file_id}') measured focus score "
                    f"{score:.2f}, below the legibility floor of {UNREADABLE_SHARPNESS} — the "
                    f"image carries no readable detail. Classification and extraction skipped; "
                    f"nothing can be read from it.",
                )
                eff_types.append(eff)
                eff_quality.append(DocumentQuality.UNREADABLE)
                type_sources.append(source)
                further_types.append([])
                illegible.add(doc.file_id)
                continue
            if measured is DocumentQuality.POOR and quality is None:
                quality = DocumentQuality.POOR
                tb.step(
                    "document_verifier", "image legibility", Outcome.DEGRADED,
                    f"{doc.file_id} measured focus score {score:.2f} (sharp documents score "
                    f"well above {POOR_SHARPNESS}); readable but degraded, so extracted "
                    f"fields carry lower confidence.",
                    confidence_delta=PENALTY_POOR_DOC,
                )

        # File integrity — a damaged upload is the member's to fix, and
        # checking locally avoids a vision call that would fail confusingly.
        if doc.storage_path and not is_decodable(Path(doc.storage_path)):
            damaged.add(doc.file_id)
            name = doc.file_name or doc.file_id
            problems.append(
                DocumentProblem(
                    kind=DocumentProblemKind.UNREADABLE,
                    file_id=doc.file_id,
                    file_name=doc.file_name,
                    found="a damaged or unsupported file",
                    required="a valid JPG, PNG, or PDF",
                    message=(
                        f"'{name}' could not be opened — the file is damaged or is not a "
                        f"supported format. Nothing could be read from it."
                    ),
                    action_needed=(
                        f"Re-upload '{name}' as a JPG, PNG, or PDF. If you exported it from "
                        f"another app, try taking a fresh photo of the original document."
                    ),
                )
            )
            tb.step(
                "document_verifier", "file integrity", Outcome.FAIL,
                f"{doc.file_id} ('{name}') is not a decodable image or PDF; "
                f"reported to the member as a damaged upload.",
            )
            eff_types.append(eff)
            eff_quality.append(DocumentQuality.UNREADABLE)
            type_sources.append(source)
            further_types.append([])
            continue

        if doc_ai is not None and doc_ai.is_configured and doc.storage_path:
            try:
                pages = doc_ai.classify(Path(doc.storage_path))
                cls_type, conf, cls_quality = pages[0]
                quality = quality or cls_quality
                # Later pages of the same upload can be different documents.
                # Only confident readings count, and only ones the first page
                # did not already provide.
                for page in pages[1:]:
                    if page.confidence >= 0.6 and page.doc_type not in {cls_type, *extra}:
                        extra.append(page.doc_type)
                if extra:
                    tb.step(
                        "document_verifier", "multi-page upload", Outcome.PASS,
                        f"{doc.file_id} ('{doc.file_name or doc.file_id}') holds "
                        f"{len(pages)} pages carrying more than one document: "
                        f"{', '.join([cls_type.value, *(t.value for t in extra)])}. "
                        f"Each counts toward the required types for this claim.",
                    )
                # A type read off an unreadable scan is a guess, not evidence:
                # never accuse the member of the wrong document when the real
                # problem is that we could not read it. The UNREADABLE check
                # below owns this document's message.
                unreadable = quality is DocumentQuality.UNREADABLE
                # An interchangeable label is not a wrong document: a member who
                # declares LAB_REPORT for an imaging report is not mistaken.
                equivalent = eff is not None and cls_type.value in _accepts(eff.value)
                if (
                    eff is not None
                    and cls_type is not eff
                    and not equivalent
                    and conf >= 0.6
                    and not unreadable
                ):
                    problems.append(
                        DocumentProblem(
                            kind=DocumentProblemKind.WRONG_TYPE,
                            file_id=doc.file_id,
                            file_name=doc.file_name,
                            found=cls_type.value,
                            required=eff.value,
                            message=(
                                f"'{doc.file_name or doc.file_id}' was uploaded as a {eff.value} "
                                f"but the document reads as a {cls_type.value}."
                            ),
                            action_needed=f"Upload the actual {eff.value.replace('_', ' ').lower()} for this claim.",
                        )
                    )
                    tb.step(
                        "document_verifier", "document classification", Outcome.FAIL,
                        f"{doc.file_id}: declared {eff.value} but classified as {cls_type.value} (conf {conf:.2f}).",
                    )
                elif unreadable:
                    if eff is None:
                        eff, source = cls_type, "CLASSIFIED"
                    tb.step(
                        "document_verifier", "document classification", Outcome.DEGRADED,
                        f"{doc.file_id}: too unreadable to classify reliably "
                        f"(best guess {cls_type.value} at {conf:.2f}); treating illegibility as "
                        f"the problem to report.",
                    )
                else:
                    if eff is None:
                        eff, source = cls_type, "CLASSIFIED"
                    tb.step(
                        "document_verifier", "document classification", Outcome.PASS,
                        f"{doc.file_id}: classified as {cls_type.value} (conf {conf:.2f}), quality {quality.value if quality else 'GOOD'}.",
                    )
            except ComponentUnavailable:
                warnings.append(
                    f"Document classifier unavailable for {doc.file_id}; trusting declared type."
                )
                tb.step(
                    "document_verifier", "document classification", Outcome.DEGRADED,
                    f"{doc.file_id}: classifier unavailable; declared type {eff.value if eff else 'UNKNOWN'} trusted, unverified.",
                    confidence_delta=PENALTY_POOR_DOC,
                )
        if eff is None:
            problems.append(
                DocumentProblem(
                    kind=DocumentProblemKind.UNCLASSIFIED,
                    file_id=doc.file_id,
                    file_name=doc.file_name,
                    found="document of unknown type",
                    required="a typed document",
                    message=(
                        f"The type of '{doc.file_name or doc.file_id}' could not be determined "
                        f"from the upload."
                    ),
                    action_needed="Select the document type when uploading, or upload a clearer copy.",
                )
            )
        eff_types.append(eff)
        eff_quality.append(quality)
        type_sources.append(source)
        further_types.append(extra)

    # 1. Required document types ------------------------------------------------
    reqs = snapshot.document_requirements(claim.claim_category)
    required = list(reqs.required) if reqs else []
    submitted_types = [t.value if t else "UNKNOWN" for t in eff_types]
    # What the upload supplied in total, counting every document found inside a
    # multi-page file — the set a requirement is satisfied from.
    supplied_types = submitted_types + [t.value for extra in further_types for t in extra]
    uploaded_desc = ", ".join(
        f"{' + '.join([t, *(x.value for x in extra)])}"
        f"{f' ({d.file_name})' if d.file_name else ''}"
        for d, t, extra in zip(docs, submitted_types, further_types)
    )
    # An unread document has no known type, so it cannot be judged missing or
    # wrong — it might well be the very document required. Its own unreadable
    # problem is the honest, actionable one; types are re-checked on re-upload.
    # This covers both ways a document can go unread: too blurred to classify,
    # and a file that would not open at all. Reporting a damaged upload as the
    # wrong type as well tells the member to replace a document we never saw.
    unread = illegible | damaged
    missing = (
        [] if unread else [t for t in required if not _accepts(t) & set(supplied_types)]
    )
    if missing:
        allowed = {a for t in required for a in _accepts(t)} | set(reqs.optional if reqs else [])
        surplus = [
            (d, t) for d, t in zip(docs, submitted_types)
            if t not in allowed or submitted_types.count(t) > 1
        ]
        for miss in missing:
            if surplus:
                found_doc, found_type = surplus[0]
                message = (
                    f"A {category} claim requires: {' and '.join(required)}. "
                    f"You uploaded {uploaded_desc} — a {found_type} was provided where a "
                    f"{miss} is required, and no {miss} was included."
                )
                found = found_type
            else:
                message = (
                    f"A {category} claim requires: {' and '.join(required)}. "
                    f"You uploaded {uploaded_desc}; no {miss} was included."
                )
                found = uploaded_desc
            problems.append(
                DocumentProblem(
                    kind=DocumentProblemKind.WRONG_TYPE if surplus else DocumentProblemKind.MISSING_REQUIRED,
                    file_id=surplus[0][0].file_id if surplus else None,
                    file_name=surplus[0][0].file_name if surplus else None,
                    found=found,
                    required=miss,
                    message=message,
                    action_needed=f"Upload the {miss.replace('_', ' ').lower()} for this treatment and resubmit the claim.",
                )
            )
        tb.step(
            "document_verifier", "required document types", Outcome.FAIL,
            f"Missing required type(s): {', '.join(missing)}. Uploaded: {uploaded_desc}.",
            rule_ref=f"document_requirements.{category}",
        )
    elif unread:
        tb.step(
            "document_verifier", "required document types", Outcome.SKIPPED,
            f"{len(unread)} document(s) could not be read, so their type is unknown; "
            f"the {category} requirement ({', '.join(required)}) is re-checked once a "
            f"legible copy is uploaded.",
            rule_ref=f"document_requirements.{category}",
        )
    else:
        tb.step(
            "document_verifier", "required document types", Outcome.PASS,
            f"All required types for {category} present ({', '.join(required)}). Uploaded: {uploaded_desc}.",
            rule_ref=f"document_requirements.{category}",
        )

    # 2. Readability ------------------------------------------------------------
    for doc, eff, quality in zip(docs, eff_types, eff_quality):
        if doc.file_id in damaged:
            continue  # already reported as a damaged file; don't say it twice
        doc_label = f"{eff.value if eff else 'document'}" + (
            f" ('{doc.file_name}')" if doc.file_name else f" ({doc.file_id})"
        )
        if quality is DocumentQuality.UNREADABLE:
            file_ref = doc.file_name or doc.file_id
            others = [d for d in docs if d.file_id != doc.file_id]
            others_note = (
                f" Your other {'document is' if len(others) == 1 else 'documents are'} fine — "
                f"only this one needs replacing."
                if others
                else ""
            )
            problems.append(
                DocumentProblem(
                    kind=DocumentProblemKind.UNREADABLE,
                    file_id=doc.file_id,
                    file_name=doc.file_name,
                    found="a document too blurred to read",
                    required=(
                        f"a legible copy (a {category} claim needs: {', '.join(required)})"
                        if required
                        else "a legible copy of the same document"
                    ),
                    message=(
                        f"'{file_ref}' is too blurred to read — no text could be recovered from "
                        f"it, so we cannot tell what document it is or what it says. Your claim "
                        f"has not been rejected and nothing else is wrong with it.{others_note}"
                    ),
                    action_needed=(
                        f"Re-upload '{file_ref}': photograph the original in good light with the "
                        f"whole page flat in frame, hold steady until the camera focuses, and "
                        f"check the text is readable before submitting. A scanned PDF works too."
                    ),
                )
            )
            tb.step(
                "document_verifier", "readability check", Outcome.FAIL,
                f"'{file_ref}' is unreadable. Claim not rejected; a re-upload of this one "
                f"document is all that is required.",
            )
        elif quality is DocumentQuality.POOR:
            warnings.append(f"{doc_label} is poor quality; extracted fields carry lower confidence.")
            tb.step(
                "document_verifier", "readability check", Outcome.DEGRADED,
                f"{doc_label} is poor quality; proceeding with lower confidence.",
                confidence_delta=PENALTY_POOR_DOC,
            )

    # Checks that need the documents' *contents* (patient identity, doctor
    # registration) run after extraction — see verify_extracted_documents.
    if problems:
        raise DocumentVerificationStop(problems)

    return VerifiedDocuments(
        documents=[
            VerifiedDocument(
                file_id=d.file_id,
                file_name=d.file_name,
                doc_type=eff,
                type_source=source,
                quality=quality or DocumentQuality.GOOD,
                patient_name_on_doc=d.patient_name_on_doc,
                content=d.content,
                storage_path=d.storage_path,
            )
            for d, eff, quality, source in zip(docs, eff_types, eff_quality, type_sources)
        ],
        warnings=warnings,
    )


def verify_extracted_documents(
    claim: ClaimSubmission,
    documents: list[ExtractedDocument],
    snapshot: PolicySnapshot,
    tb: TraceBuilder,
) -> list[str]:
    """Second verification phase — the checks that need document *contents*.

    Whether a claim's documents describe the same patient cannot be known
    before the documents are read, so this runs after extraction and can still
    stop the claim before any adjudication happens. Structural problems (wrong
    type, unreadable, damaged) are caught earlier, in verify_documents.

    Returns non-blocking warnings; raises DocumentVerificationStop on a
    patient mismatch.
    """
    problems: list[DocumentProblem] = []
    warnings: list[str] = []

    named: list[tuple[str, str]] = []  # (label, patient name)
    for doc in documents:
        name = doc.content.patient_name
        if name:
            label = doc.doc_type.value + (f" ('{doc.file_name}')" if doc.file_name else "")
            named.append((label, name))

    distinct = {_norm_name(n) for _, n in named}
    if len(distinct) > 1:
        listing = "; ".join(f"{label} is for {name}" for label, name in named)
        problems.append(
            DocumentProblem(
                kind=DocumentProblemKind.PATIENT_MISMATCH,
                found=" / ".join(sorted({n for _, n in named})),
                required="all documents for the same patient",
                message=(
                    f"The uploaded documents belong to different patients: {listing}. "
                    f"All documents in one claim must be for the same person."
                ),
                action_needed=(
                    "Check the files and re-upload documents that all belong to the patient "
                    "this claim is for. If you are claiming for a dependent, every document "
                    "must carry the dependent's name."
                ),
            )
        )
        tb.step(
            "document_verifier", "patient consistency", Outcome.FAIL,
            f"Documents name different patients: {listing}.",
        )
    elif named:
        patient = named[0][1]
        eligible = {_norm_name(m.name) for m in snapshot.eligible_patients(claim.member_id)}
        if eligible and _norm_name(patient) not in eligible:
            warnings.append(
                f"Patient name '{patient}' on the documents does not match the member or a "
                f"registered dependent; flagged for review."
            )
            tb.step(
                "document_verifier", "patient consistency", Outcome.DEGRADED,
                f"All documents name '{patient}', which is neither the member "
                f"({claim.member_id}) nor a registered dependent.",
                confidence_delta=PENALTY_UNVERIFIED_FIELD,
            )
        else:
            tb.step(
                "document_verifier", "patient consistency", Outcome.PASS,
                f"All named documents agree on patient '{patient}'.",
            )
    else:
        tb.step(
            "document_verifier", "patient consistency", Outcome.SKIPPED,
            "No patient name could be read from any document; nothing to cross-check.",
        )

    for doc in documents:
        reg = doc.content.doctor_registration
        if reg and not _REG_RE.match(reg):
            warnings.append(f"Doctor registration '{reg}' does not match any known state format.")
            tb.step(
                "document_verifier", "registration format", Outcome.DEGRADED,
                f"Registration '{reg}' on {doc.file_id} does not match known state formats; unverified.",
                confidence_delta=PENALTY_UNVERIFIED_FIELD,
            )

    if problems:
        raise DocumentVerificationStop(problems)
    return warnings
