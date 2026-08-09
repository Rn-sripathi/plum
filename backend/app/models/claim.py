"""Claim submission contracts — the pipeline's entry boundary.

`ClaimSubmission` mirrors the input shape of `test_cases.json` exactly, so eval
cases feed the pipeline verbatim. Real UI submissions produce the same model
(documents carry file references instead of pre-extracted `content`).
"""

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from .documents import DocumentContent
from .enums import ClaimCategory, DocumentQuality, DocumentType


class ClaimHistoryEntry(BaseModel):
    """A previously submitted claim, used by the fraud checker's velocity rules."""

    claim_id: str
    date: dt.date
    amount: Decimal
    provider: str | None = None


class SubmittedDocument(BaseModel):
    """One uploaded document.

    In test mode, `actual_type` / `quality` / `content` / `patient_name_on_doc`
    are trusted as ground truth and vision extraction is skipped (the trace
    records this). In real mode only `file_id` / `file_name` / `storage_path`
    are set and classification + extraction run on the file.
    """

    model_config = ConfigDict(extra="forbid")

    file_id: str
    file_name: str | None = None
    actual_type: DocumentType | None = Field(
        default=None, description="Ground-truth document type (test mode)."
    )
    quality: DocumentQuality | None = Field(
        default=None, description="Pre-assessed readability (test mode)."
    )
    patient_name_on_doc: str | None = Field(
        default=None, description="Patient name printed on the document (test mode)."
    )
    content: DocumentContent | None = Field(
        default=None, description="Pre-extracted document content (test mode)."
    )
    storage_path: str | None = Field(
        default=None, description="Path to the uploaded file (real mode)."
    )


class ClaimSubmission(BaseModel):
    """Input contract of the whole pipeline (POST /claims body).

    Errors raised downstream: `IntakeError` (unknown member, inactive policy,
    amount/deadline violations) and `DocumentVerificationStop` (TC001–TC003).
    """

    model_config = ConfigDict(extra="forbid")

    member_id: str
    policy_id: str
    claim_category: ClaimCategory
    treatment_date: dt.date
    claimed_amount: Decimal = Field(gt=0)
    hospital_name: str | None = Field(
        default=None, description="Provider name; checked against the network list."
    )
    ytd_claims_amount: Decimal | None = Field(
        default=None,
        description="Year-to-date claimed total; payload value trusted over DB state.",
    )
    claims_history: list[ClaimHistoryEntry] | None = Field(
        default=None,
        description="Prior claims; payload value trusted over DB state.",
    )
    pre_authorization_ref: str | None = Field(
        default=None,
        description="Insurer pre-authorization reference, when one was obtained.",
    )
    simulate_component_failure: bool = Field(
        default=False,
        description="Test hook (TC011): force a non-critical component to fail.",
    )
    submission_date: dt.date | None = Field(
        default=None,
        description="Defaults to treatment_date when absent (test determinism).",
    )
    documents: list[SubmittedDocument] = Field(min_length=1)
