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

from app.agents.llm import DocumentAI
from app.core.errors import ComponentUnavailable, DocumentVerificationStop
from app.kb.snapshot import PolicySnapshot
from app.models import (
    ClaimSubmission,
    DocumentProblem,
    DocumentProblemKind,
    DocumentQuality,
    DocumentType,
    Outcome,
    VerifiedDocument,
    VerifiedDocuments,
)
from app.orchestrator.trace import TraceBuilder

PENALTY_POOR_DOC = -0.10
PENALTY_UNVERIFIED_FIELD = -0.05

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
    for doc in docs:
        eff, quality, source = doc.actual_type, doc.quality, "DECLARED"
        if doc_ai is not None and doc_ai.is_configured and doc.storage_path:
            try:
                cls_type, conf, cls_quality = doc_ai.classify(Path(doc.storage_path))
                quality = quality or cls_quality
                if eff is not None and cls_type is not eff and conf >= 0.6:
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

    # 1. Required document types ------------------------------------------------
    reqs = snapshot.document_requirements(claim.claim_category)
    required = list(reqs.required) if reqs else []
    submitted_types = [t.value if t else "UNKNOWN" for t in eff_types]
    uploaded_desc = ", ".join(
        f"{t}{f' ({d.file_name})' if d.file_name else ''}"
        for d, t in zip(docs, submitted_types)
    )
    missing = [t for t in required if t not in submitted_types]
    if missing:
        allowed = set(required) | set(reqs.optional if reqs else [])
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
    else:
        tb.step(
            "document_verifier", "required document types", Outcome.PASS,
            f"All required types for {category} present ({', '.join(required)}). Uploaded: {uploaded_desc}.",
            rule_ref=f"document_requirements.{category}",
        )

    # 2. Readability ------------------------------------------------------------
    for doc, eff, quality in zip(docs, eff_types, eff_quality):
        doc_label = f"{eff.value if eff else 'document'}" + (
            f" ('{doc.file_name}')" if doc.file_name else f" ({doc.file_id})"
        )
        if quality is DocumentQuality.UNREADABLE:
            problems.append(
                DocumentProblem(
                    kind=DocumentProblemKind.UNREADABLE,
                    file_id=doc.file_id,
                    file_name=doc.file_name,
                    found=f"unreadable {eff.value if eff else 'document'}",
                    required="a readable copy of the same document",
                    message=(
                        f"Your {doc_label} could not be read — the image is too blurry or damaged "
                        f"to extract any information. The claim itself is fine; only this one "
                        f"document needs to be re-uploaded."
                    ),
                    action_needed=(
                        f"Re-upload {doc_label} as a clear, well-lit photo or PDF "
                        f"(all corners visible, no shadows) and resubmit."
                    ),
                )
            )
            tb.step(
                "document_verifier", "readability check", Outcome.FAIL,
                f"{doc_label} is UNREADABLE; requesting re-upload of this document only.",
            )
        elif quality is DocumentQuality.POOR:
            warnings.append(f"{doc_label} is poor quality; extracted fields carry lower confidence.")
            tb.step(
                "document_verifier", "readability check", Outcome.DEGRADED,
                f"{doc_label} is poor quality; proceeding with lower confidence.",
                confidence_delta=PENALTY_POOR_DOC,
            )

    # 3. Cross-document patient consistency --------------------------------------
    named: list[tuple[str, str]] = []  # (doc label, name)
    for doc, eff in zip(docs, eff_types):
        name = doc.patient_name_on_doc or (doc.content.patient_name if doc.content else None)
        if name:
            label = f"{eff.value if eff else 'document'}" + (
                f" ('{doc.file_name}')" if doc.file_name else ""
            )
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
                f"All documents name '{patient}', which is not the member or a known dependent.",
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
            "No patient names present on the documents; nothing to cross-check.",
        )

    # 4. Doctor registration format (warning only) --------------------------------
    for doc in docs:
        reg = doc.content.doctor_registration if doc.content else None
        if reg and not _REG_RE.match(reg):
            warnings.append(f"Doctor registration '{reg}' does not match any known state format.")
            tb.step(
                "document_verifier", "registration format", Outcome.DEGRADED,
                f"Registration '{reg}' on {doc.file_id} does not match known formats; unverified.",
                confidence_delta=PENALTY_UNVERIFIED_FIELD,
            )

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
