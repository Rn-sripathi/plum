"""Live knowledge-store verification — run after `python -m app.kb.ingest`.

Run:  uv run python scripts/verify_kb.py   (from backend/)

Checks each configured store end to end:
- Postgres/SQLite claim store connectivity
- Neo4j graph: document-requirements query for CONSULTATION
- Qdrant semantic search: a paraphrase the token matcher cannot catch
"""

from app.core.config import settings
from app.core.store import make_store
from app.kb.graph import PolicyGraph
from app.kb.semantic import SemanticPolicyIndex


def main() -> None:
    store = make_store(settings)
    kind = type(store).__name__.removesuffix("ClaimStore")
    print(f"store   [{kind}]: {'healthy' if store.healthy() else 'UNAVAILABLE'}")

    graph = PolicyGraph(settings)
    if graph.is_configured:
        try:
            reqs = graph.document_requirements("PLUM_GHI_2024", "CONSULTATION")
            print(f"neo4j   [graph]: connected — CONSULTATION requires {reqs}")
        except Exception as exc:
            print(f"neo4j   [graph]: UNREACHABLE ({exc}) — snapshot fallback would apply")
        finally:
            graph.close()
    else:
        print("neo4j   [graph]: not configured (snapshot only)")

    semantic = SemanticPolicyIndex(settings)
    if semantic.is_configured:
        try:
            query = "Stomach reduction operation for weight"
            hits = semantic.search(query, top_k=3)
            top = ", ".join(f"'{h.concept}' ({h.score:.2f})" for h in hits)
            print(f"qdrant  [semantic]: ready — '{query}' -> {top}")
        except Exception as exc:
            print(f"qdrant  [semantic]: FAILED ({exc}) — token-matching fallback would apply")
    else:
        print("qdrant  [semantic]: disabled (no OPENAI_API_KEY)")


if __name__ == "__main__":
    main()
