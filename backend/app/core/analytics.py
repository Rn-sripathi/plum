"""Portfolio figures over decided claims.

A pure aggregation over stored records: no store, no HTTP, no LLM, so it is
testable on a list of dicts. Every figure is derived from a decision the
pipeline already made and recorded — this module never re-decides anything, and
never estimates. A claim that stopped at document verification has no decision,
so it counts toward volume and toward *why claims stop*, and is excluded from
every money and confidence figure.

Scale note (ARCHITECTURE.md, 10x): this reads recent results and folds them in
Python, which is right at demo volume and wrong at 75k/year. The shape to grow
into is columns materialized on write (status, amounts, confidence, duration)
plus SQL aggregation, with these definitions as the spec for those queries.
"""

from collections import Counter
from decimal import Decimal

# A claim that never reached a decision is not a rejection: it is a claim we
# handed back. Keeping it out of the decision mix is what makes the mix honest.
STOPPED = "DOCUMENTS_REQUIRED"
# Order is load-bearing, not cosmetic: it is the order segments touch in the
# stacked bar, and the fills are validated for colour-blind separation in
# exactly this sequence. Putting REJECTED next to PARTIAL collapses that pair to
# ΔE 2.3 under deuteranopia (against a floor of 6). It also reads as a
# progression: paid in full, paid in part, sent to a human, refused, never
# decided.
DECISIONS = ("APPROVED", "PARTIAL", "MANUAL_REVIEW", "REJECTED")
CONFIDENCE_BINS = ((0.0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01))


def _bin_label(low: float, high: float) -> str:
    return f"<{high:.1f}" if low == 0.0 else f"{low:.1f}–{min(high, 1.0):.1f}"


def summarize(records: list[dict]) -> dict:
    """Aggregate stored claims into the figures the analytics view renders.

    `records` are store rows: `status`, `category`, `member_id` and the decision
    `result` (a ClaimDecision or a DocumentProblemReport, as stored).
    """
    decided = [r for r in records if r["status"] != STOPPED]
    stopped = [r for r in records if r["status"] == STOPPED]

    claimed = Decimal(0)
    approved = Decimal(0)
    confidences: list[float] = []
    bins = Counter()
    stage_ms: dict[str, float] = {}
    stage_runs: Counter = Counter()
    degraded: Counter = Counter()
    manual_review = 0

    for record in decided:
        result = record["result"]
        approved += Decimal(str(result.get("approved_amount") or 0))
        # The claimed amount lives on the financial breakdown's first step,
        # which is the eligible base the engine started from.
        steps = (result.get("financial") or {}).get("steps") or []
        if steps:
            claimed += Decimal(str(steps[0]["amount_before"]))
        confidence = result.get("confidence")
        if confidence is not None:
            confidences.append(confidence)
            for low, high in CONFIDENCE_BINS:
                if low <= confidence < high:
                    bins[_bin_label(low, high)] += 1
                    break
        if result.get("manual_review_recommended"):
            manual_review += 1
        for component in result.get("degraded_components") or []:
            degraded[component] += 1

    # Timing is per component across every run, decided or stopped: a claim that
    # stopped early still spent its seconds reading documents. Divided by the
    # claims a component actually ran in, not by all claims — a stage that runs
    # rarely should not look cheap because it was absent, and a stage that logs
    # many steps per claim should not look cheap per step.
    claims_seen: Counter = Counter()
    for record in records:
        per_record: dict[str, float] = {}
        for step in (record["result"].get("trace") or {}).get("steps") or []:
            if step.get("duration_ms") is None:
                continue
            per_record[step["component"]] = per_record.get(step["component"], 0.0) + step["duration_ms"]
            stage_runs[step["component"]] += 1
        for component, total in per_record.items():
            stage_ms[component] = stage_ms.get(component, 0.0) + total
            claims_seen[component] += 1

    problems = Counter(
        problem["kind"]
        for record in stopped
        for problem in record["result"].get("problems") or []
    )

    return {
        "total": len(records),
        "decided": len(decided),
        "stopped": len(stopped),
        "decision_mix": [
            {"status": status, "count": sum(1 for r in records if r["status"] == status)}
            for status in (*DECISIONS, STOPPED)
        ],
        "by_category": [
            {"category": category, "count": count}
            for category, count in Counter(r["category"] for r in records).most_common()
        ],
        "money": {
            "claimed": str(claimed),
            "approved": str(approved),
            # Share of every rupee claimed that the policy actually pays. Not a
            # rate the system controls — an outcome of co-pay, sub-limits and
            # exclusions, which is exactly why it is worth watching.
            "payout_ratio": float(approved / claimed) if claimed else None,
        },
        "confidence": {
            "mean": round(sum(confidences) / len(confidences), 3) if confidences else None,
            "manual_review": manual_review,
            "distribution": [
                {"bin": _bin_label(low, high), "count": bins[_bin_label(low, high)]}
                for low, high in CONFIDENCE_BINS
            ],
        },
        "stops": [
            {"kind": kind, "count": count} for kind, count in problems.most_common()
        ],
        "timing": sorted(
            (
                {
                    "component": component,
                    "per_claim_ms": round(total / claims_seen[component], 1),
                    "total_ms": round(total, 1),
                    "steps": stage_runs[component],
                    "claims": claims_seen[component],
                }
                for component, total in stage_ms.items()
            ),
            key=lambda t: -t["per_claim_ms"],
        ),
        "degraded": [
            {"component": component, "runs": runs} for component, runs in degraded.most_common()
        ],
    }
