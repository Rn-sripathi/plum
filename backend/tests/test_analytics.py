"""Portfolio aggregation (GET /analytics).

`summarize` is a pure function over stored rows, so these assert the
definitions rather than any wiring: what counts as decided, what a stopped
claim is allowed to contribute to, and how time is attributed per stage.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.analytics import summarize
from app.main import create_app


def decided(status="APPROVED", claimed="1500", approved="1350", confidence=0.98, **extra):
    return {
        "claim_id": f"CLM_{status}_{claimed}",
        "submitted_at": "2024-11-01T00:00:00Z",
        "member_id": "EMP001",
        "category": "CONSULTATION",
        "status": status,
        "result": {
            "approved_amount": approved,
            "confidence": confidence,
            "financial": {"steps": [{"amount_before": claimed}]},
            "trace": {"steps": []},
            **extra,
        },
    }


def stopped(*kinds, steps=()):
    return {
        "claim_id": "CLM_STOP",
        "submitted_at": "2024-11-01T00:00:00Z",
        "member_id": "EMP001",
        "category": "CONSULTATION",
        "status": "DOCUMENTS_REQUIRED",
        "result": {
            "problems": [{"kind": k} for k in kinds],
            "trace": {"steps": list(steps)},
        },
    }


def test_empty_store_yields_no_figures_rather_than_zeros_that_look_real():
    summary = summarize([])
    assert summary["total"] == 0
    assert summary["money"]["payout_ratio"] is None
    assert summary["confidence"]["mean"] is None


def test_a_stopped_claim_is_not_a_rejection():
    """It never reached a decision, so it cannot colour the decision mix or
    drag down the payout ratio — but it is still a claim that arrived."""
    summary = summarize([decided(), stopped("WRONG_TYPE")])

    assert (summary["total"], summary["decided"], summary["stopped"]) == (2, 1, 1)
    mix = {m["status"]: m["count"] for m in summary["decision_mix"]}
    assert mix["REJECTED"] == 0
    assert mix["DOCUMENTS_REQUIRED"] == 1
    assert summary["money"]["payout_ratio"] == pytest.approx(0.9)
    assert summary["stops"] == [{"kind": "WRONG_TYPE", "count": 1}]


def test_payout_ratio_is_approved_over_claimed():
    summary = summarize([
        decided(claimed="1000", approved="900"),
        decided(status="REJECTED", claimed="1000", approved="0"),
    ])
    assert summary["money"] == {
        "claimed": "2000",
        "approved": "900",
        "payout_ratio": pytest.approx(0.45),
    }


def test_confidence_bins_do_not_double_count_a_boundary():
    dist = {
        b["bin"]: b["count"]
        for b in summarize([decided(confidence=c) for c in (0.7, 0.8, 0.9, 1.0)])["confidence"][
            "distribution"
        ]
    }
    assert dist == {"<0.6": 0, "0.6–0.7": 0, "0.7–0.8": 1, "0.8–0.9": 1, "0.9–1.0": 2}


def test_stage_time_is_per_claim_the_stage_ran_in_not_per_step():
    """A stage that logs many steps must not look cheap, and one that runs
    rarely must not look cheap for having been absent."""
    trace = (
        {"component": "document_verifier", "duration_ms": 400},
        {"component": "document_verifier", "duration_ms": 600},
        {"component": "extraction_agent", "duration_ms": 2000},
    )
    summary = summarize([stopped("UNREADABLE", steps=trace), decided()])

    timing = {t["component"]: t for t in summary["timing"]}
    assert timing["document_verifier"]["per_claim_ms"] == 1000  # 2 steps, 1 claim
    assert timing["document_verifier"]["steps"] == 2
    # Sorted by cost per claim, so the expensive stage leads.
    assert summary["timing"][0]["component"] == "extraction_agent"


def test_decision_mix_order_keeps_the_validated_colour_sequence():
    """The mix order is the order stacked segments touch, and the fills are
    validated for colour-blind separation in that sequence. PARTIAL beside
    REJECTED collapses to ΔE 2.3 under deuteranopia, so the two must not be
    neighbours — this is a colour-safety constraint, not a display preference.
    """
    order = [m["status"] for m in summarize([decided()])["decision_mix"]]
    assert order == ["APPROVED", "PARTIAL", "MANUAL_REVIEW", "REJECTED", "DOCUMENTS_REQUIRED"]
    assert abs(order.index("PARTIAL") - order.index("REJECTED")) > 1


def test_degraded_components_are_counted_across_runs():
    summary = summarize([
        decided(degraded_components=["fraud_checker"]),
        decided(degraded_components=["fraud_checker"]),
        decided(),
    ])
    assert summary["degraded"] == [{"component": "fraud_checker", "runs": 2}]


def test_endpoint_serves_a_summary_for_an_empty_store(tmp_path):
    with TestClient(create_app(database_path=tmp_path / "claims.db")) as client:
        body = client.get("/analytics").json()
    assert body["available"] is True
    assert body["total"] == 0
