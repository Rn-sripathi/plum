"""Knowledge-store integration: Qdrant semantic index (embedded, fake
embedder), semantic tier in the exclusion check, graph fallback wiring, and
live-credential tests that skip when the env vars are absent."""

import os

import pytest

from app.core.config import Settings
from app.core.errors import ComponentUnavailable
from app.engine.checks import check_exclusions
from app.kb.semantic import SemanticHit, SemanticPolicyIndex
from app.models import ClaimSubmission, Decision, Outcome, RejectionReason
from app.orchestrator.pipeline import process_claim


def bow_embedder(texts):
    """Deterministic bag-of-words embedding — token overlap ≈ cosine similarity."""
    vectors = []
    for text in texts:
        v = [0.0] * 128
        for token in text.lower().replace("(", " ").replace(")", " ").split():
            v[hash(token) % 128] += 1.0
        vectors.append(v)
    return vectors


def _isolated_settings(tmp_path) -> Settings:
    """Settings that can never reach live stores, whatever is in .env."""
    return Settings(
        OPENAI_API_KEY=None,
        QDRANT_URL=None,
        QDRANT_API_KEY=None,
        qdrant_local_dir=tmp_path,
    )


@pytest.fixture(scope="module")
def semantic_index(tmp_path_factory, snapshot):
    index = SemanticPolicyIndex(
        _isolated_settings(tmp_path_factory.mktemp("qdrant")), embedder=bow_embedder
    )
    count = index.ingest(snapshot.terms)
    assert count > 30
    return index


class TestSemanticIndex:
    def test_search_finds_exclusion_concepts(self, semantic_index):
        hits = semantic_index.search("Teeth whitening treatment", top_k=3)
        assert hits and hits[0].concept.lower() == "teeth whitening"
        assert hits[0].rule_ref
        assert 0 < hits[0].score <= 1.0

    def test_healthy_after_ingest(self, semantic_index):
        assert semantic_index.healthy()

    def test_unconfigured_index_raises_component_unavailable(self, tmp_path):
        index = SemanticPolicyIndex(_isolated_settings(tmp_path))
        assert not index.is_configured
        with pytest.raises(ComponentUnavailable):
            index.search("anything")


class TestSemanticExclusionTier:
    def _claim(self):
        return ClaimSubmission.model_validate(
            {
                "member_id": "EMP009",
                "policy_id": "PLUM_GHI_2024",
                "claim_category": "CONSULTATION",
                "treatment_date": "2024-10-18",
                "claimed_amount": 3000,
                "documents": [{"file_id": "F1", "actual_type": "PRESCRIPTION"}],
            }
        )

    def test_semantic_hint_used_when_tokens_miss(self, snapshot):
        # "Stomach reduction operation" shares no distinctive token with any
        # exclusion clause — only the vector hint can catch it.
        check, match = check_exclusions(
            self._claim(),
            "Stomach reduction operation",
            None,
            snapshot,
            semantic_hints=[
                SemanticHit("Bariatric surgery", "exclusion", "exclusions.conditions[6]", 0.86)
            ],
        )
        assert check.outcome is Outcome.FAIL
        assert check.rejection_reason is RejectionReason.EXCLUDED_CONDITION
        assert "semantically" in check.detail and "0.86" in check.detail
        assert match is not None and match.concept == "Bariatric surgery"

    def test_low_score_hint_ignored(self, snapshot):
        check, match = check_exclusions(
            self._claim(),
            "Stomach reduction operation",
            None,
            snapshot,
            semantic_hints=[
                SemanticHit("Bariatric surgery", "exclusion", "exclusions.conditions[6]", 0.40)
            ],
        )
        assert check.outcome is Outcome.PASS
        assert match is None

    def test_token_tier_wins_over_hints(self, snapshot):
        # TC012-style text: token match must fire, not the semantic wording.
        check, _ = check_exclusions(
            self._claim(),
            "Morbid Obesity — BMI 37",
            None,
            snapshot,
            semantic_hints=[
                SemanticHit("Health supplements and tonics", "exclusion", "x", 0.99)
            ],
        )
        assert check.outcome is Outcome.FAIL
        assert "matched on" in check.detail  # token wording, not "semantically"


class FailingGraph:
    is_configured = True

    def document_requirements(self, policy_id, category):
        raise ComponentUnavailable("policy_graph", "connection refused")


class TestGraphFallback:
    def test_graph_outage_degrades_not_crashes(self, snapshot, test_cases):
        case = next(c for c in test_cases if c["case_id"] == "TC004")
        submission = ClaimSubmission.model_validate(case["input"])
        result = process_claim(submission, snapshot, claim_id="TC004G", graph=FailingGraph())
        assert result.decision is Decision.APPROVED
        assert result.confidence == pytest.approx(0.93)
        degraded = [s for s in result.trace.steps if s.component == "policy_retriever"]
        assert degraded and degraded[0].outcome is Outcome.DEGRADED
        assert "snapshot fallback" in degraded[0].detail

    def test_no_graph_means_snapshot_source_no_penalty(self, snapshot, test_cases):
        case = next(c for c in test_cases if c["case_id"] == "TC004")
        submission = ClaimSubmission.model_validate(case["input"])
        result = process_claim(submission, snapshot, claim_id="TC004S")
        source = [s for s in result.trace.steps if s.component == "policy_retriever"]
        assert source and source[0].outcome is Outcome.PASS
        assert "snapshot" in source[0].detail
        assert result.confidence == pytest.approx(0.98)


needs_pg = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
needs_neo4j = pytest.mark.skipif(not os.environ.get("NEO4J_URI"), reason="NEO4J_URI not set")


@needs_pg
def test_postgres_store_roundtrip(snapshot, test_cases):
    from app.core.store import PostgresClaimStore

    store = PostgresClaimStore(os.environ["DATABASE_URL"])
    case = next(c for c in test_cases if c["case_id"] == "TC004")
    submission = ClaimSubmission.model_validate(case["input"])
    result = process_claim(submission, snapshot, claim_id="PGTEST_TC004")
    store.save(submission, result)
    record = store.get("PGTEST_TC004")
    assert record and record["status"] == "APPROVED"
    assert store.healthy()


@needs_neo4j
def test_neo4j_ingest_and_query(snapshot):
    from app.kb.graph import PolicyGraph

    graph = PolicyGraph(Settings())
    counts = graph.ingest(snapshot.terms)
    assert counts.get("Category") == 6
    reqs = graph.document_requirements("PLUM_GHI_2024", "CONSULTATION")
    assert reqs == ["HOSPITAL_BILL", "PRESCRIPTION"]
    graph.close()
