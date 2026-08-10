"""DocumentAI — the only place the system talks to an LLM (GPT-4o vision).

Used for judgment calls only: classifying an uploaded file's document type
and extracting structured fields from it. Never for money decisions.

Resilience contract (PLAN.md §4): every call has a timeout and bounded
retries; on failure this raises `ComponentUnavailable` and callers degrade
(trust declared type / proceed on pre-extracted content). With no API key
configured, `is_configured` is False and callers never attempt a call.
"""

import json
from pathlib import Path
from typing import NamedTuple

from app.agents.imaging import MAX_PDF_PAGES, image_parts
from app.core.config import Settings
from app.core.errors import ComponentUnavailable
from app.models import DocumentQuality, DocumentType
from app.models.documents import DocumentContent

_CLASSIFY_SCHEMA = {
    "name": "document_classification",
    "schema": {
        "type": "object",
        "properties": {
            "pages": {
                "type": "array",
                "description": "One entry per page supplied, in the same order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "doc_type": {"type": "string", "enum": [t.value for t in DocumentType]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "quality": {"type": "string", "enum": [q.value for q in DocumentQuality]},
                        "reason": {"type": "string"},
                    },
                    "required": ["doc_type", "confidence", "quality", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["pages"],
        "additionalProperties": False,
    },
}


class PageClassification(NamedTuple):
    """What one page of an uploaded file turned out to be."""

    doc_type: DocumentType
    confidence: float
    quality: DocumentQuality

_EXTRACT_SCHEMA = {
    "name": "document_extraction",
    "schema": {
        "type": "object",
        "properties": {
            "patient_name": {"type": ["string", "null"]},
            "date": {"type": ["string", "null"], "description": "ISO date if legible"},
            "doctor_name": {"type": ["string", "null"]},
            "doctor_registration": {"type": ["string", "null"]},
            "hospital_name": {"type": ["string", "null"]},
            "diagnosis": {"type": ["string", "null"]},
            "treatment": {"type": ["string", "null"]},
            "medicines": {"type": ["array", "null"], "items": {"type": "string"}},
            "tests_ordered": {"type": ["array", "null"], "items": {"type": "string"}},
            "test_name": {"type": ["string", "null"]},
            "line_items": {
                "type": ["array", "null"],
                "items": {
                    "type": "object",
                    "properties": {"description": {"type": "string"}, "amount": {"type": "number"}},
                    "required": ["description", "amount"],
                    "additionalProperties": False,
                },
            },
            "total": {"type": ["number", "null"]},
            "field_confidence": {
                "type": "object",
                "description": "0..1 confidence per extracted field name",
                "additionalProperties": {"type": "number"},
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Obscured/illegible/ambiguous fields, stamps over text, corrections",
            },
        },
        "required": ["field_confidence", "warnings"],
        "additionalProperties": False,
    },
}

_CLASSIFY_PROMPT = """Classify each page of this Indian medical document upload, using
these definitions. The types are an insurer's categories, not everyday language, so follow
the definitions even when a document's specialty suggests otherwise.

The images are the pages of ONE uploaded file, in order. Members routinely scan several
different documents into a single PDF, so classify EVERY page on its own evidence — a
prescription on page 1 does not make page 2 a prescription. Return one entry per page
supplied, in order.

DECIDING RULE: if the document's purpose is to charge money — it lists amounts and a total
payable — it is a BILL, whichever kind of clinic issued it. A dental clinic's invoice is a
HOSPITAL_BILL, not a DENTAL_REPORT. A report never carries charges.

  PRESCRIPTION        A doctor's Rx: medicines with dosage/duration, or tests ordered.
                      No charges.
  HOSPITAL_BILL       An itemized invoice or receipt from any hospital or clinic —
                      including dental, eye and ayurvedic clinics — listing services
                      with amounts and a total.
  PHARMACY_BILL       An itemized invoice from a pharmacy/chemist: medicines with
                      quantity, MRP and amount. Usually shows a drug licence number.
  LAB_REPORT          Laboratory test results: test names with values, units and
                      normal ranges.
  DIAGNOSTIC_REPORT   Imaging findings written by a radiologist (MRI, CT, X-ray,
                      ultrasound) — narrative findings and an impression, no charges.
  DISCHARGE_SUMMARY   Hospital admission/discharge narrative: course of treatment,
                      dates of admission and discharge.
  DENTAL_REPORT       Dental clinical findings or a treatment plan with NO charges.

Also assess readability: GOOD = the text can be read; POOR = readable but degraded
(blurred, skewed, stamped over); UNREADABLE = no text can be recovered."""

_EXTRACT_PROMPT = """You are extracting structured data from an Indian medical document
({doc_type}). Documents may be handwritten, stamped over, photographed at an angle, or
partially illegible. Extract what you can read; NEVER guess. For each extracted field,
give a 0..1 confidence in field_confidence. List every legibility problem in warnings.
Expand Indian medical shorthand (HTN=Hypertension, T2DM=Type 2 Diabetes)."""


class DocumentAI:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = None
        if settings.openai_api_key:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.openai_api_key,
                timeout=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries,
            )

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def _vision_call(self, system: str, image_path: Path, schema: dict) -> tuple[dict, int]:
        """Returns the parsed response and the document's page count."""
        if self._client is None:
            raise ComponentUnavailable("llm", "No LLM configured (OPENAI_API_KEY not set).")
        try:
            uris, pages = image_parts(image_path)
            response = self._client.chat.completions.create(
                model=self._settings.openai_model,
                response_format={"type": "json_schema", "json_schema": schema},
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": uri}} for uri in uris
                        ],
                    },
                ],
            )
            return json.loads(response.choices[0].message.content), pages
        except ComponentUnavailable:
            raise
        except Exception as exc:  # SDK/timeouts/network — degrade, never crash the pipeline
            raise ComponentUnavailable("llm", f"LLM call failed after retries: {exc}") from exc

    def classify(self, image_path: Path) -> list[PageClassification]:
        """Identify what each page of an upload is, and how readable it is.

        One entry per page, page 1 first — an image yields exactly one. A PDF
        is classified page by page in a single call, because a member who
        scans a prescription and a bill into one file has supplied both
        documents, and typing the file by its first page would report the
        second as missing.
        """
        data, _ = self._vision_call(_CLASSIFY_PROMPT, image_path, _CLASSIFY_SCHEMA)
        pages = [
            PageClassification(
                DocumentType(page["doc_type"]),
                float(page["confidence"]) if isinstance(page.get("confidence"), int | float) else 0.0,
                DocumentQuality(page["quality"]),
            )
            for page in (data.get("pages") or [])
        ]
        if not pages:
            raise ComponentUnavailable("llm", "Classifier returned no page classifications.")
        return pages

    def extract(self, image_path: Path, doc_type: DocumentType) -> tuple[DocumentContent, dict[str, float], list[str]]:
        """Extract structured fields with per-field confidence and warnings.

        Multi-page PDFs are sent page by page in one request so line items
        are aggregated across pages.
        """
        data, pages = self._vision_call(
            _EXTRACT_PROMPT.format(doc_type=doc_type.value), image_path, _EXTRACT_SCHEMA
        )
        # A schema constrains the model, it does not guarantee it: gpt-4o
        # intermittently returns null for a field's score despite the schema
        # declaring a number. An absent score means "none stated", which reads
        # the same as no confidence — never a crashed claim.
        confidence = {
            k: (float(v) if isinstance(v, int | float) else 0.0)
            for k, v in (data.pop("field_confidence", None) or {}).items()
        }
        warnings = [str(w) for w in (data.pop("warnings", None) or [])]
        if pages > MAX_PDF_PAGES:
            warnings.append(
                f"Document has {pages} pages; only the first {MAX_PDF_PAGES} were read. "
                f"Line items on later pages were not extracted."
            )
        content = DocumentContent.model_validate({k: v for k, v in data.items() if v is not None})
        return content, confidence, warnings
