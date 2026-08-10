"""Semantic policy index — Qdrant vector search over policy concepts.

One point per policy concept (every exclusion clause, covered/excluded
procedure/item, covered system, waiting-period condition), embedded with
OpenAI `text-embedding-3-small`. At claim time, diagnosis/treatment/line-item
texts are embedded and nearest-neighbor searched; hits become *candidate*
matches that the deterministic engine still threshold-checks — the index
widens recall, it never decides.

Runs against Qdrant Cloud when `QDRANT_URL` is set, otherwise an embedded
local index under `data/qdrant/` (no server, no account). Embeddings require
`OPENAI_API_KEY`; without it `is_configured` is False and the token matcher
carries semantic matching alone (documented fallback tier).
"""

from dataclasses import dataclass
from typing import Callable

from app.core.config import Settings
from app.core.errors import ComponentUnavailable
from app.models.policy import PolicyTerms

Embedder = Callable[[list[str]], list[list[float]]]

COLLECTION = "policy_concepts"


@dataclass
class SemanticHit:
    """A policy concept the vector index considers close to the query text."""

    concept: str
    concept_type: str  # exclusion | excluded_procedure | covered_procedure | ...
    rule_ref: str
    score: float  # cosine similarity 0..1


def _concepts(terms: PolicyTerms) -> list[dict]:
    concepts: list[dict] = []

    def add(text: str, concept_type: str, rule_ref: str) -> None:
        concepts.append({"concept": text, "concept_type": concept_type, "rule_ref": rule_ref})

    for i, clause in enumerate(terms.exclusions.conditions):
        add(clause, "exclusion", f"exclusions.conditions[{i}]")
    for i, clause in enumerate(terms.exclusions.dental_exclusions):
        add(clause, "exclusion", f"exclusions.dental_exclusions[{i}]")
    for i, clause in enumerate(terms.exclusions.vision_exclusions):
        add(clause, "exclusion", f"exclusions.vision_exclusions[{i}]")
    for cat_name, cat in terms.opd_categories.items():
        base = f"opd_categories.{cat_name}"
        for p in cat.excluded_procedures + cat.excluded_items:
            add(p, "excluded_procedure", f"{base}.excluded_procedures")
        for p in cat.covered_procedures + cat.covered_items + cat.covered_systems:
            add(p, "covered_procedure", f"{base}.covered_procedures")
    for key, days in terms.waiting_periods.specific_conditions.items():
        add(
            f"{key.replace('_', ' ')} ({days}-day waiting period)",
            "waiting_condition",
            f"waiting_periods.specific_conditions.{key}",
        )
    return concepts


def _openai_embedder(settings: Settings) -> Embedder:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds)

    def embed(texts: list[str]) -> list[list[float]]:
        response = client.embeddings.create(model=settings.embedding_model, input=texts)
        return [d.embedding for d in response.data]

    return embed


class SemanticPolicyIndex:
    def __init__(self, settings: Settings, embedder: Embedder | None = None):
        self._settings = settings
        self._embedder = embedder
        if self._embedder is None and settings.openai_api_key:
            self._embedder = _openai_embedder(settings)
        self._client = None

    @property
    def is_configured(self) -> bool:
        return self._embedder is not None

    def _qdrant(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            if self._settings.qdrant_url:
                self._client = QdrantClient(
                    url=self._settings.qdrant_url, api_key=self._settings.qdrant_api_key
                )
            else:
                self._settings.qdrant_local_path.mkdir(parents=True, exist_ok=True)
                self._client = QdrantClient(path=str(self._settings.qdrant_local_path))
        return self._client

    def ingest(self, terms: PolicyTerms) -> int:
        """(Re)build the concept collection from policy terms. Returns count."""
        from qdrant_client.models import Distance, PointStruct, VectorParams

        if not self.is_configured:
            raise ComponentUnavailable(
                "semantic_index", "No embedder available (OPENAI_API_KEY not set)."
            )
        concepts = _concepts(terms)
        try:
            vectors = self._embedder([c["concept"] for c in concepts])
            client = self._qdrant()
            if client.collection_exists(COLLECTION):
                client.delete_collection(COLLECTION)
            client.create_collection(
                COLLECTION,
                vectors_config=VectorParams(size=len(vectors[0]), distance=Distance.COSINE),
            )
            client.upsert(
                COLLECTION,
                points=[
                    PointStruct(id=i, vector=v, payload=c)
                    for i, (v, c) in enumerate(zip(vectors, concepts))
                ],
            )
        except ComponentUnavailable:
            raise
        except Exception as exc:
            raise ComponentUnavailable("semantic_index", f"Ingestion failed: {exc}") from exc
        return len(concepts)

    def search(self, text: str, top_k: int = 3, min_score: float = 0.0) -> list[SemanticHit]:
        if not self.is_configured:
            raise ComponentUnavailable(
                "semantic_index", "No embedder available (OPENAI_API_KEY not set)."
            )
        try:
            vector = self._embedder([text])[0]
            points = self._qdrant().query_points(COLLECTION, query=vector, limit=top_k).points
        except Exception as exc:
            raise ComponentUnavailable("semantic_index", f"Search failed: {exc}") from exc
        return [
            SemanticHit(
                concept=p.payload["concept"],
                concept_type=p.payload["concept_type"],
                rule_ref=p.payload["rule_ref"],
                score=float(p.score),
            )
            for p in points
            if p.score >= min_score
        ]

    def warm(self) -> None:
        """Pay the index's first-use cost before a user does.

        The embedded local index loads its collection from disk on the first
        query — measured at ~24s cold against ~0.7s warm. In the pipeline that
        cost hid inside a claim that was already doing vision calls; the
        assistant surfaces it as a 24-second first question, which is why this
        is called at startup rather than left to the first caller.
        """
        if not self.is_configured:
            return
        try:
            self.search("warm", top_k=1)
        except Exception:  # a cold index that will not load is the search's problem
            pass

    def healthy(self) -> bool:
        if not self.is_configured:
            return False
        try:
            return self._qdrant().collection_exists(COLLECTION)
        except Exception:
            return False
