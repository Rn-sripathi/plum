"""Retrieval eval — does policy search find the clause that answers the question?

The assistant's citations are only as good as what retrieval returns, and
"looks fine" is not a measurement. Each case is phrased the way someone would
actually ask, never in the clause's own words, so the test is recall on
paraphrase rather than string matching.

The negatives are the important half. The policy says nothing about
physiotherapy or dialysis, so nearest-neighbour search still returns its closest
concepts — and how *those* score is what tells us where a relevance floor
belongs. Without them a threshold is a guess.

Run:  uv run python -m app.eval.retrieval
"""

from dataclasses import dataclass

from app.core.config import settings
from app.kb.retrieval import KnowledgeBase
from app.kb.semantic import SemanticPolicyIndex
from app.kb.snapshot import PolicySnapshot


@dataclass(frozen=True)
class Case:
    question: str
    expected: str | None  # None = the policy has no clause for this


CASES = [
    # Exclusions, asked in a member's words rather than the clause's.
    Case("is teeth whitening covered", "exclusions.dental_exclusions[0]"),
    Case("can I claim for braces for my daughter", "exclusions.dental_exclusions[1]"),
    Case("does the policy pay for laser eye surgery", "exclusions.vision_exclusions[0]"),
    Case("I want to claim a weight loss programme", "exclusions.conditions[5]"),
    Case("is gastric bypass surgery covered", "exclusions.conditions[6]"),
    Case("claiming for a nose job", "exclusions.conditions[7]"),
    Case("IVF and fertility treatment cover", "exclusions.conditions[4]"),
    Case("can I claim for multivitamin tonics", "exclusions.conditions[9]"),
    Case("flu shot before a holiday", "exclusions.conditions[8]"),
    Case("rehab for alcohol dependence", "exclusions.conditions[2]"),
    Case("injury I caused myself", "exclusions.conditions[0]"),
    # Waiting periods.
    Case("how long until I can claim for diabetes", "waiting_periods.specific_conditions.diabetes"),
    Case("when can I claim for high blood pressure", "waiting_periods.specific_conditions.hypertension"),
    Case("knee replacement — how long is the wait", "waiting_periods.specific_conditions.joint_replacement"),
    Case("pregnancy cover waiting time", "waiting_periods.specific_conditions.maternity"),
    Case("therapy for depression, when am I eligible", "waiting_periods.specific_conditions.mental_health"),
    Case("cataract operation waiting period", "waiting_periods.specific_conditions.cataract"),
    Case("underactive thyroid claim wait", "waiting_periods.specific_conditions.thyroid_disorders"),
    Case("hernia repair waiting period", "waiting_periods.specific_conditions.hernia"),
    # Covered treatments.
    Case("is a root canal covered", "opd_categories.dental.covered_procedures"),
    Case("does it cover ayurvedic treatment", "opd_categories.alternative_medicine.covered_procedures"),
    # Nothing in the policy covers these; the floor is calibrated on them.
    Case("is physiotherapy covered", None),
    Case("does the policy cover dialysis", None),
    Case("what is the wifi password", None),
]


def run(top_k: int = 3) -> dict:
    """Recall@1 and @k over the golden set, plus the score bands per outcome."""
    snapshot = PolicySnapshot.from_file(settings.policy_terms_path)
    semantic = SemanticPolicyIndex(settings)
    kb = KnowledgeBase(snapshot, semantic=semantic)

    hits_at_1 = hits_at_k = wanted = 0
    top_scores: dict[str, list[float]] = {"found": [], "missed": [], "negative": []}
    misses: list[str] = []

    for case in CASES:
        result = kb.search_policy(case.question, top_k=top_k)
        refs = [hit["rule_ref"] for hit in result["hits"]]
        scores = [hit.get("score") for hit in result["hits"]]
        top = scores[0] if scores and scores[0] is not None else None

        if case.expected is None:
            if top is not None:
                top_scores["negative"].append(top)
            continue

        wanted += 1
        if refs[:1] == [case.expected]:
            hits_at_1 += 1
        if case.expected in refs:
            hits_at_k += 1
            if top is not None:
                top_scores["found"].append(top)
        else:
            misses.append(f"{case.question} → wanted {case.expected}, got {refs}")
            if top is not None:
                top_scores["missed"].append(top)

    return {
        "tier": result["source"],
        "cases": len(CASES),
        "positives": wanted,
        "recall_at_1": round(hits_at_1 / wanted, 3) if wanted else None,
        f"recall_at_{top_k}": round(hits_at_k / wanted, 3) if wanted else None,
        "top_score": {
            band: {
                "n": len(values),
                "min": round(min(values), 3) if values else None,
                "mean": round(sum(values) / len(values), 3) if values else None,
                "max": round(max(values), 3) if values else None,
            }
            for band, values in top_scores.items()
        },
        "misses": misses,
    }


def main() -> None:
    report = run()
    print(f"tier: {report['tier']}  cases: {report['cases']}  positives: {report['positives']}")
    print(f"recall@1: {report['recall_at_1']}   recall@3: {report['recall_at_3']}")
    for band, stats in report["top_score"].items():
        print(f"top score [{band:8}] n={stats['n']:2} min={stats['min']} mean={stats['mean']} max={stats['max']}")
    for miss in report["misses"]:
        print(f"  MISS {miss}")


if __name__ == "__main__":
    main()
