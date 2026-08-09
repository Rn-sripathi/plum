"""Document verification and extraction contracts.

`DocumentContent` is a single permissive schema covering all four document
layouts in `sample_documents_guide.md` (prescription, hospital bill, lab
report, pharmacy bill). Fields are optional because real documents are messy;
unknown fields are preserved via `extra="allow"`.
"""

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import DocumentProblemKind, DocumentQuality, DocumentType
from .trace import DecisionTrace


class LineItem(BaseModel):
    """One billed line item on a hospital/pharmacy bill."""

    description: str
    amount: Decimal


class DocumentContent(BaseModel):
    """Structured fields extracted from (or pre-supplied for) one document."""

    model_config = ConfigDict(extra="allow")

    patient_name: str | None = None
    date: dt.date | None = None
    doctor_name: str | None = None
    doctor_registration: str | None = None
    hospital_name: str | None = None
    diagnosis: str | None = None
    treatment: str | None = None
    medicines: list[str] | None = None
    tests_ordered: list[str] | None = None
    test_name: str | None = None
    line_items: list[LineItem] | None = None
    total: Decimal | None = None


class DocumentProblem(BaseModel):
    """One specific, actionable document problem (TC001–TC003).

    `message` is member-facing and must name what was found and what is
    required; `action_needed` tells the member exactly what to do next.
    """

    file_id: str | None = None
    file_name: str | None = None
    kind: DocumentProblemKind
    found: str | None = Field(
        default=None, description="What was uploaded / found on the document."
    )
    required: str | None = Field(
        default=None, description="What the policy requires instead."
    )
    message: str
    action_needed: str


class VerifiedDocument(BaseModel):
    """One document that passed early verification, ready for extraction.

    `type_source` records whether the type came from the declared test-mode
    field or from vision classification (affects confidence).
    """

    file_id: str
    file_name: str | None = None
    doc_type: DocumentType
    type_source: Literal["DECLARED", "CLASSIFIED"] = "DECLARED"
    quality: DocumentQuality = DocumentQuality.GOOD
    patient_name_on_doc: str | None = None
    content: DocumentContent | None = Field(
        default=None, description="Pre-extracted content passed through (test mode)."
    )
    storage_path: str | None = None
    warnings: list[str] = Field(default_factory=list)


class VerifiedDocuments(BaseModel):
    """Output of the Document Verifier when the claim may proceed.

    Blocking problems are never returned on this model — they are raised as
    `DocumentVerificationStop` carrying `DocumentProblem`s. `warnings` holds
    non-blocking notes (e.g. POOR quality, unverifiable registration number)
    that feed the confidence rollup.
    """

    documents: list[VerifiedDocument]
    warnings: list[str] = Field(default_factory=list)


class DocumentProblemReport(BaseModel):
    """Returned instead of a decision when verification stops the claim early
    (TC001–TC003). `decision` is explicitly None — the claim was neither
    approved nor rejected; the member must fix the documents and resubmit."""

    claim_id: str
    status: Literal["DOCUMENTS_REQUIRED"] = "DOCUMENTS_REQUIRED"
    decision: None = None
    problems: list[DocumentProblem]
    trace: DecisionTrace


class ExtractedDocument(BaseModel):
    """Output of the Extraction Agent for one document.

    `field_confidence` maps field name -> 0..1 confidence; obscured or
    unextractable fields appear in `warnings` instead of failing the document.
    """

    file_id: str
    doc_type: DocumentType
    quality: DocumentQuality = DocumentQuality.GOOD
    content: DocumentContent
    field_confidence: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    extraction_skipped: bool = Field(
        default=False,
        description="True when pre-extracted content was used (test mode).",
    )
