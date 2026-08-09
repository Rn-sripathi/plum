"""TraceBuilder — the single writer of `DecisionTrace` steps.

Components never construct TraceSteps directly; the pipeline records what each
one did through this builder, which owns sequencing and timing.
"""

from collections.abc import Callable
from datetime import datetime, timezone

from app.models import DecisionTrace, Outcome, TraceStep


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TraceBuilder:
    """Sole writer of trace steps.

    `on_step` is invoked as each step is recorded, letting the API stream the
    decision as it is being made. It must never raise into the pipeline: a
    broken consumer (disconnected browser) cannot be allowed to fail a claim.
    """

    def __init__(self, claim_id: str, on_step: Callable[[TraceStep], None] | None = None):
        self.claim_id = claim_id
        self.started_at = _now()
        self.steps: list[TraceStep] = []
        self.degraded_components: list[str] = []
        self._on_step = on_step

    def step(
        self,
        component: str,
        action: str,
        outcome: Outcome,
        detail: str,
        *,
        input_summary: str | None = None,
        confidence_delta: float = 0.0,
        rule_ref: str | None = None,
    ) -> None:
        step = TraceStep(
            seq=len(self.steps) + 1,
            component=component,
            action=action,
            input_summary=input_summary,
            outcome=outcome,
            detail=detail,
            confidence_delta=confidence_delta,
            rule_ref=rule_ref,
            started_at=_now(),
        )
        self.steps.append(step)
        if self._on_step is not None:
            try:
                self._on_step(step)
            except Exception:  # a dead listener must not fail the claim
                self._on_step = None

    def mark_degraded(self, component: str, detail: str, confidence_delta: float) -> None:
        self.degraded_components.append(component)
        self.step(
            component,
            action="component failure handled",
            outcome=Outcome.DEGRADED,
            detail=detail,
            confidence_delta=confidence_delta,
        )

    def build(self) -> DecisionTrace:
        return DecisionTrace(
            claim_id=self.claim_id,
            steps=self.steps,
            started_at=self.started_at,
            finished_at=_now(),
            degraded_components=self.degraded_components,
        )
