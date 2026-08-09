"""DocumentAI — the only place the system talks to an LLM (GPT-4o vision).

Used for judgment calls only: classifying an uploaded file's document type
and extracting structured fields from it. Never for money decisions.

Resilience contract (PLAN.md §4): every call has a timeout and bounded
retries; on failure this raises `ComponentUnavailable` and callers degrade
(trust declared type / proceed on pre-extracted content). With no API key
configured, `is_configured` is False and callers never attempt a call.
"""

import base64
import json
import mimetypes
from pathlib import Path

from app.core.config import Settings
from app.core.errors import ComponentUnavailable
from app.models import DocumentQuality, DocumentType
from app.models.documents import DocumentContent

_CLASSIFY_SCHEMA = {
    "name": "document_classification",
    "schema": {
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

_EXTRACT_PROMPT = """You are extracting structured data from an Indian medical document
({doc_type}). Documents may be handwritten, stamped over, photographed at an angle, or
partially illegible. Extract what you can read; NEVER guess. For each extracted field,
give a 0..1 confidence in field_confidence. List every legibility problem in warnings.
Expand Indian medical shorthand (HTN=Hypertension, T2DM=Type 2 Diabetes)."""


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


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

    def _vision_call(self, system: str, image_path: Path, schema: dict) -> dict:
        if self._client is None:
            raise ComponentUnavailable("llm", "No LLM configured (OPENAI_API_KEY not set).")
        try:
            response = self._client.chat.completions.create(
                model=self._settings.openai_model,
                response_format={"type": "json_schema", "json_schema": schema},
                messages=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": _data_uri(image_path)}}
                        ],
                    },
                ],
            )
            return json.loads(response.choices[0].message.content)
        except ComponentUnavailable:
            raise
        except Exception as exc:  # SDK/timeouts/network — degrade, never crash the pipeline
            raise ComponentUnavailable("llm", f"LLM call failed after retries: {exc}") from exc

    def classify(self, image_path: Path) -> tuple[DocumentType, float, DocumentQuality]:
        """Identify a document's type and readability from the image alone."""
        data = self._vision_call(
            "Classify this Indian medical document by type and assess its readability.",
            image_path,
            _CLASSIFY_SCHEMA,
        )
        return (
            DocumentType(data["doc_type"]),
            float(data["confidence"]),
            DocumentQuality(data["quality"]),
        )

    def extract(self, image_path: Path, doc_type: DocumentType) -> tuple[DocumentContent, dict[str, float], list[str]]:
        """Extract structured fields with per-field confidence and warnings."""
        data = self._vision_call(_EXTRACT_PROMPT.format(doc_type=doc_type.value), image_path, _EXTRACT_SCHEMA)
        confidence = {k: float(v) for k, v in data.pop("field_confidence", {}).items()}
        warnings = list(data.pop("warnings", []))
        content = DocumentContent.model_validate({k: v for k, v in data.items() if v is not None})
        return content, confidence, warnings
