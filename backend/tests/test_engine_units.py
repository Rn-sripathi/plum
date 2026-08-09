"""Unit tests for the deterministic engine building blocks."""

from decimal import Decimal

from app.engine import matching
from app.engine.financial import compute_breakdown
from app.engine.fraud import assess_fraud
from app.models import (
    ClaimCategory,
    ClaimSubmission,
    FraudSignalCode,
    LineItemDecision,
    Outcome,
)
from app.orchestrator.pipeline import process_claim


class TestMatching:
    CONDITION_KEYS = [
        "diabetes", "hypertension", "thyroid_disorders", "joint_replacement",
        "maternity", "mental_health", "obesity_treatment", "hernia", "cataract",
    ]

    def test_diabetes_diagnosis_maps(self):
        assert matching.match_condition_key("Type 2 Diabetes Mellitus", self.CONDITION_KEYS) == "diabetes"

    def test_shorthand_expansion(self):
        assert matching.match_condition_key("T2DM, poorly controlled", self.CONDITION_KEYS) == "diabetes"
        assert matching.match_condition_key("HTN follow-up", self.CONDITION_KEYS) == "hypertension"

    def test_herniation_does_not_match_hernia(self):
        # Exact token match only — no substring matching.
        assert matching.match_condition_key("Suspected Lumbar Disc Herniation", self.CONDITION_KEYS) is None

    def test_joint_pain_does_not_match_joint_replacement(self):
        # ALL distinctive tokens of the key must be present.
        assert matching.match_condition_key("Chronic Joint Pain", self.CONDITION_KEYS) is None

    def test_obesity_diagnosis_matches_exclusion(self, snapshot):
        match = matching.match_exclusion(
            "Morbid Obesity — BMI 37", snapshot.terms.exclusions.conditions
        )
        assert match is not None
        assert match.concept == "Obesity and weight loss programs"

    def test_bariatric_treatment_matches_exclusion(self, snapshot):
        match = matching.match_exclusion(
            "Bariatric Consultation and Customised Diet Plan",
            snapshot.terms.exclusions.conditions,
        )
        assert match is not None and match.concept == "Bariatric surgery"

    def test_clean_diagnosis_matches_nothing(self, snapshot):
        assert matching.match_exclusion("Viral Fever", snapshot.terms.exclusions.conditions) is None
        assert matching.match_exclusion("Acute Bronchitis", snapshot.terms.exclusions.conditions) is None

    def test_procedure_list_matching(self):
        excluded = ["Teeth Whitening", "Veneers", "Orthodontic Treatment (Braces)"]
        assert matching.match_in_list("Teeth Whitening", excluded) == "Teeth Whitening"
        assert matching.match_in_list("Root Canal Treatment", excluded) is None
        assert matching.match_in_list("MRI Lumbar Spine", ["MRI", "CT Scan"]) == "MRI"


class TestFinancial:
    def _items(self, *pairs):
        return [
            LineItemDecision(description=d, claimed_amount=Decimal(a), approved=True)
            for d, a in pairs
        ]

    def test_network_discount_before_copay_tc010_numbers(self, snapshot):
        breakdown, _ = compute_breakdown(
            category=ClaimCategory.CONSULTATION,
            cat_terms=snapshot.category_terms(ClaimCategory.CONSULTATION),
            coverage=snapshot.terms.coverage,
            line_items=self._items(("Consultation Fee", 1500), ("Medicines", 3000)),
            is_network_hospital=True,
            ytd_claims_amount=Decimal(8000),
        )
        order = [s.step for s in breakdown.steps]
        assert order == ["eligible_base", "network_discount", "copay", "sub_limit_cap", "annual_limit_cap"]
        assert order.index("network_discount") < order.index("copay")
        by_step = {s.step: s for s in breakdown.steps}
        assert by_step["network_discount"].amount_after == Decimal("3600.00")
        assert by_step["copay"].amount_after == Decimal("3240.00")
        assert breakdown.final_payable == Decimal("3240.00")

    def test_non_network_copay_only(self, snapshot):
        breakdown, _ = compute_breakdown(
            category=ClaimCategory.CONSULTATION,
            cat_terms=snapshot.category_terms(ClaimCategory.CONSULTATION),
            coverage=snapshot.terms.coverage,
            line_items=self._items(("Consultation Fee", 1000), ("Tests", 500)),
            is_network_hospital=False,
            ytd_claims_amount=Decimal(5000),
        )
        assert breakdown.final_payable == Decimal("1350.00")

    def test_sub_limit_caps_whole_claim_for_dental(self, snapshot):
        breakdown, _ = compute_breakdown(
            category=ClaimCategory.DENTAL,
            cat_terms=snapshot.category_terms(ClaimCategory.DENTAL),
            coverage=snapshot.terms.coverage,
            line_items=self._items(("Multiple Root Canals", 12000)),
            is_network_hospital=False,
            ytd_claims_amount=Decimal(0),
        )
        assert breakdown.final_payable == Decimal("10000.00")

    def test_annual_limit_caps_payout(self, snapshot):
        breakdown, _ = compute_breakdown(
            category=ClaimCategory.CONSULTATION,
            cat_terms=snapshot.category_terms(ClaimCategory.CONSULTATION),
            coverage=snapshot.terms.coverage,
            line_items=self._items(("Consultation Fee", 2000)),
            is_network_hospital=False,
            ytd_claims_amount=Decimal(49000),  # only 1000 left of the 50000 annual limit
        )
        assert breakdown.final_payable == Decimal("1000.00")

    def test_missing_ytd_noted(self, snapshot):
        _, notes = compute_breakdown(
            category=ClaimCategory.CONSULTATION,
            cat_terms=snapshot.category_terms(ClaimCategory.CONSULTATION),
            coverage=snapshot.terms.coverage,
            line_items=self._items(("Consultation Fee", 1000)),
            is_network_hospital=False,
            ytd_claims_amount=None,
        )
        assert any("assumed" in n for n in notes)


class TestAmountReconciliation:
    """Guards against settling on misread amounts: if what the member claimed
    and what the documents say disagree, a human must look."""

    def _claim(self, amount: int, total: int | None):
        docs = [{"file_id": "F1", "actual_type": "PRESCRIPTION", "content": {"diagnosis": "Viral Fever"}}]
        bill = {"file_id": "F2", "actual_type": "HOSPITAL_BILL", "content": {}}
        if total is not None:
            bill["content"] = {"line_items": [{"description": "Consultation Fee", "amount": total}]}
        docs.append(bill)
        return ClaimSubmission.model_validate(
            {
                "member_id": "EMP001",
                "policy_id": "PLUM_GHI_2024",
                "claim_category": "CONSULTATION",
                "treatment_date": "2024-11-01",
                "claimed_amount": amount,
                "ytd_claims_amount": 0,
                "documents": docs,
            }
        )

    def test_matching_amounts_pass_cleanly(self, snapshot):
        result = process_claim(self._claim(1500, 1500), snapshot, claim_id="REC1")
        check = next(c for c in result.trace.steps if c.action == "amount_reconciliation")
        assert check.outcome is Outcome.PASS
        assert result.confidence > 0.9
        assert result.manual_review_recommended is False

    def test_reasons_state_why_confidence_fell(self, snapshot):
        """A decision must name the signals behind its confidence, not just
        report the resulting number — "0.48 is below 0.5" explains nothing."""
        result = process_claim(self._claim(1500, 1150), snapshot, claim_id="REC5")
        text = " ".join(result.reasons)
        assert "₹1,500" in text and "₹1,150" in text, (
            f"the discrepancy that lowered confidence must appear in the reasons: {result.reasons}"
        )
        assert any("review" in r.lower() for r in result.reasons)

    def test_misread_or_overclaimed_amount_routes_to_review(self, snapshot):
        # Documents show ₹1,150 but the member claimed ₹1,500 — the exact
        # failure a blurry bill produced against the live vision model.
        result = process_claim(self._claim(1500, 1150), snapshot, claim_id="REC2")
        check = next(c for c in result.trace.steps if c.action == "amount_reconciliation")
        assert check.outcome is Outcome.FAIL
        assert "₹1,500" in check.detail and "₹1,150" in check.detail
        assert result.manual_review_recommended is True
        assert result.confidence < 0.75

    def test_rounding_difference_tolerated(self, snapshot):
        result = process_claim(self._claim(1500, 1495), snapshot, claim_id="REC3")
        check = next(c for c in result.trace.steps if c.action == "amount_reconciliation")
        assert check.outcome is Outcome.PASS

    def test_no_documented_total_is_skipped_not_failed(self, snapshot):
        result = process_claim(self._claim(1500, None), snapshot, claim_id="REC4")
        check = next(c for c in result.trace.steps if c.action == "amount_reconciliation")
        assert check.outcome is Outcome.SKIPPED


class TestFraud:
    def _claim(self, history_dates: list[str], amount: int = 1000) -> ClaimSubmission:
        return ClaimSubmission.model_validate(
            {
                "member_id": "EMP008",
                "policy_id": "PLUM_GHI_2024",
                "claim_category": "CONSULTATION",
                "treatment_date": "2024-10-30",
                "claimed_amount": amount,
                "claims_history": [
                    {"claim_id": f"CLM_{i}", "date": d, "amount": 1000}
                    for i, d in enumerate(history_dates)
                ],
                "documents": [{"file_id": "F1", "actual_type": "PRESCRIPTION"}],
            }
        )

    def test_same_day_over_limit_flags(self, snapshot):
        result = assess_fraud(
            self._claim(["2024-10-30", "2024-10-30", "2024-10-30"]),
            snapshot.terms.fraud_thresholds,
        )
        assert result.requires_manual_review
        codes = [s.code for s in result.signals]
        assert FraudSignalCode.SAME_DAY_LIMIT_EXCEEDED in codes

    def test_same_day_at_limit_passes(self, snapshot):
        # Limit is 2/day: one earlier claim + this one = 2 -> no flag.
        result = assess_fraud(self._claim(["2024-10-30"]), snapshot.terms.fraud_thresholds)
        assert not result.signals

    def test_high_value_flags(self, snapshot):
        result = assess_fraud(self._claim([], amount=26000), snapshot.terms.fraud_thresholds)
        assert result.requires_manual_review
        assert result.signals[0].code is FraudSignalCode.HIGH_VALUE_CLAIM
