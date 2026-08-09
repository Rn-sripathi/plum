"""Typed errors raised at component boundaries.

Only two error families stop the pipeline: `IntakeError` (bad submission) and
`DocumentVerificationStop` (TC001–TC003, carries member-facing problems).
Everything else is degradation: components catch their own failures, apply a
fallback, and record it — per the resilience table in PLAN.md §4.
"""

from app.models.documents import DocumentProblem


class ClaimsError(Exception):
    """Base class for all typed pipeline errors."""

    code = "CLAIMS_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class IntakeError(ClaimsError):
    """Submission payload failed validation before any processing."""

    code = "INTAKE_ERROR"

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


class DocumentVerificationStop(ClaimsError):
    """Early stop: documents are wrong/unreadable/inconsistent (TC001–TC003).

    Not a failure of the system — the claim is returned to the member with
    specific, actionable problems and no decision is made.
    """

    code = "DOCUMENT_PROBLEMS"

    def __init__(self, problems: list[DocumentProblem]):
        super().__init__("; ".join(p.message for p in problems))
        self.problems = problems


class ExtractionFailed(ClaimsError):
    """Extraction produced nothing usable for a document and no fallback exists."""

    code = "EXTRACTION_FAILED"

    def __init__(self, file_id: str, cause: str):
        super().__init__(f"Extraction failed for document {file_id}: {cause}")
        self.file_id = file_id
        self.cause = cause


class ComponentUnavailable(ClaimsError):
    """A dependency (LLM, KB, DB) is down and a fallback was engaged.

    Raised only when even the fallback cannot proceed; otherwise components
    degrade silently and record it in the trace.
    """

    code = "COMPONENT_UNAVAILABLE"

    def __init__(self, component: str, message: str, fallback_used: str | None = None):
        super().__init__(message)
        self.component = component
        self.fallback_used = fallback_used
