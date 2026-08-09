"""Phase 2 exit gate: the 9 decision cases (TC004–TC012) through the pipeline
with zero LLM involvement, asserting the expected outcomes from test_cases.json
plus each case's `system_must` obligations."""

from decimal import Decimal

import pytest

from app.models import ClaimSubmission, Decision, FraudSignalCode, Outcome, RejectionReason
from app.orchestrator.pipeline import process_claim

DECISION_CASES = [f"TC{i:03d}" for i in range(4, 13)]


@pytest.fixture(scope="module")
def decisions(test_cases, snapshot):
    """Run every decision case once through the pipeline."""
    results = {}
    for case in test_cases:
        if case["case_id"] in DECISION_CASES:
            submission = ClaimSubmission.model_validate(case["input"])
            results[case["case_id"]] = process_claim(submission, snapshot, claim_id=case["case_id"])
    return results


@pytest.mark.parametrize("case_id", DECISION_CASES)
def test_expected_decision(case_id, decisions, test_cases):
    expected = next(c for c in test_cases if c["case_id"] == case_id)["expected"]
    result = decisions[case_id]
    assert result.decision.value == expected["decision"], (
        f"{case_id}: expected {expected['decision']}, got {result.decision.value} — {result.reasons}"
    )
    if "approved_amount" in expected:
        assert result.approved_amount == Decimal(expected["approved_amount"]), (
            f"{case_id}: expected ₹{expected['approved_amount']}, got ₹{result.approved_amount}"
        )


@pytest.mark.parametrize("case_id", DECISION_CASES)
def test_trace_is_complete(case_id, decisions):
    trace = decisions[case_id].trace
    assert len(trace.steps) >= 5
    assert [s.seq for s in trace.steps] == list(range(1, len(trace.steps) + 1))
    components = {s.component for s in trace.steps}
    assert "adjudication_engine" in components
    assert "decision_synthesizer" in components


def test_tc004_clean_approval(decisions):
    r = decisions["TC004"]
    assert r.confidence > 0.85
    text = " ".join(r.reasons)
    assert "Co-pay" in text and "₹150" in text


def test_tc005_waiting_period_states_eligibility_date(decisions):
    r = decisions["TC005"]
    assert r.rejection_reasons == [RejectionReason.WAITING_PERIOD]
    assert "2024-11-30" in " ".join(r.reasons)


def test_tc006_itemized_partial(decisions):
    r = decisions["TC006"]
    rejected = [i for i in r.line_items if not i.approved]
    approved = [i for i in r.line_items if i.approved]
    assert [i.description for i in approved] == ["Root Canal Treatment"]
    assert [i.description for i in rejected] == ["Teeth Whitening"]
    assert rejected[0].reason and "excluded" in rejected[0].reason.lower()


def test_tc007_pre_auth_missing_with_resubmission_guidance(decisions):
    r = decisions["TC007"]
    assert r.rejection_reasons == [RejectionReason.PRE_AUTH_MISSING]
    text = " ".join(r.reasons).lower()
    assert "pre-authorization" in text and "resubmit" in text


def test_tc008_per_claim_limit_names_both_amounts(decisions):
    r = decisions["TC008"]
    assert r.rejection_reasons == [RejectionReason.PER_CLAIM_EXCEEDED]
    text = " ".join(r.reasons)
    assert "₹5,000" in text and "₹7,500" in text


def test_tc009_fraud_routed_to_review_with_signals(decisions):
    r = decisions["TC009"]
    assert r.decision is Decision.MANUAL_REVIEW
    assert [s.code for s in r.fraud_signals] == [FraudSignalCode.SAME_DAY_LIMIT_EXCEEDED]
    assert "limit of 2" in r.fraud_signals[0].detail
    assert not r.rejection_reasons  # routed to review, not rejected


def test_tc010_discount_before_copay_breakdown_visible(decisions):
    r = decisions["TC010"]
    steps = {s.step: s for s in r.financial.steps}
    order = [s.step for s in r.financial.steps]
    assert order.index("network_discount") < order.index("copay")
    assert steps["network_discount"].amount_after == Decimal("3600.00")
    assert steps["copay"].amount_after == Decimal("3240.00")
    text = " ".join(r.reasons)
    assert "₹900" in text and "₹360" in text  # breakdown shown in output


def test_tc011_degraded_but_approved(decisions):
    r = decisions["TC011"]
    assert r.decision is Decision.APPROVED
    assert r.degraded_components == ["fraud_checker"]
    assert r.manual_review_recommended is True
    assert r.confidence < decisions["TC004"].confidence
    assert any(s.outcome is Outcome.DEGRADED for s in r.trace.steps)
    assert "incomplete" in " ".join(r.reasons).lower()


def test_tc012_exclusion_high_confidence(decisions):
    r = decisions["TC012"]
    assert r.rejection_reasons == [RejectionReason.EXCLUDED_CONDITION]
    assert r.confidence > 0.90
