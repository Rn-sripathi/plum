"""Ingest policy_terms.json into every configured knowledge store.

Run:  uv run python -m app.kb.ingest

- Qdrant (embedded local by default; cloud when QDRANT_URL is set) — needs
  OPENAI_API_KEY for embeddings.
- Neo4j AuraDB — needs NEO4J_URI + NEO4J_PASSWORD.
- Postgres claim store schema is created automatically at app startup; no
  ingestion needed.

Skips anything unconfigured — this command is idempotent and safe to re-run
after every policy change ("a new policy is an ingestion run, not a code
change").
"""

from app.core.config import settings
from app.core.errors import ComponentUnavailable
from app.kb.graph import PolicyGraph
from app.kb.semantic import SemanticPolicyIndex
from app.kb.snapshot import PolicySnapshot


def main() -> None:
    snapshot = PolicySnapshot.from_file(settings.policy_terms_path)
    print(f"policy: {snapshot.terms.policy_id} ({len(snapshot.terms.members)} members)")

    semantic = SemanticPolicyIndex(settings)
    if semantic.is_configured:
        try:
            count = semantic.ingest(snapshot.terms)
            target = settings.qdrant_url or f"embedded ({settings.qdrant_local_path})"
            print(f"qdrant: indexed {count} policy concepts -> {target}")
        except ComponentUnavailable as exc:
            print(f"qdrant: FAILED — {exc.message}")
    else:
        print("qdrant: skipped (OPENAI_API_KEY not set — embeddings unavailable)")

    graph = PolicyGraph(settings)
    if graph.is_configured:
        try:
            counts = graph.ingest(snapshot.terms)
            print(f"neo4j: ingested {counts} -> {settings.neo4j_uri}")
        except ComponentUnavailable as exc:
            print(f"neo4j: FAILED — {exc.message}")
        finally:
            graph.close()
    else:
        print("neo4j: skipped (NEO4J_URI / NEO4J_PASSWORD not set)")


if __name__ == "__main__":
    main()
