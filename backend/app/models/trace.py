"""DecisionTrace — the observability contract.

Every pipeline component appends `TraceStep`s. The completed trace must let an
operations reviewer reconstruct the decision without any other artifact:
what was checked, in what order, what passed/failed, and how each signal
moved the confidence score.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from .enums import Outcome


class TraceStep(BaseModel):
    """One recorded action by one component."""

    seq: int = Field(description="1-based position in the pipeline run.")
    component: str = Field(description="Component name, e.g. 'document_verifier'.")
    action: str = Field(description="What was checked or done.")
    input_summary: str | None = Field(
        default=None, description="What the component looked at (compact)."
    )
    outcome: Outcome
    detail: str = Field(description="Human-readable, specific result.")
    confidence_delta: float = Field(
        default=0.0, description="Signed confidence adjustment contributed by this step."
    )
    rule_ref: str | None = Field(
        default=None,
        description="Pointer into policy terms, e.g. 'waiting_periods.specific_conditions.diabetes'.",
    )
    started_at: datetime | None = None
    duration_ms: float | None = None


class DecisionTrace(BaseModel):
    """Complete, ordered record of one claim's processing run."""

    claim_id: str
    steps: list[TraceStep] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    degraded_components: list[str] = Field(
        default_factory=list,
        description="Components that failed or ran on a fallback during this run.",
    )
