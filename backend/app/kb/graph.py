"""Policy graph — Neo4j (AuraDB) representation of the policy.

Graph shape:
    (Policy)-[:HAS_CATEGORY]->(Category {sub_limit, copay_percent, ...})
    (Category)-[:REQUIRES_DOC|:ACCEPTS_DOC]->(DocType)
    (Policy)-[:EXCLUDES]->(Exclusion {clause})
    (Policy)-[:HAS_WAITING_PERIOD]->(Condition {key, days})
    (Policy)-[:COVERS]->(Member)<-[:DEPENDENT_OF]-(Member)

This is the multi-policy scale story: onboarding a policy is an ingestion
run, and rule lookups become traversals. At runtime the pipeline reads
document requirements from the graph and cross-checks them against the
in-memory snapshot; if the graph is unreachable the snapshot carries on
(−0.05 confidence, trace notes the degraded source). Activated by
`NEO4J_URI` + `NEO4J_PASSWORD`; absent = snapshot-only mode, no penalty.
"""

from decimal import Decimal

from app.core.config import Settings
from app.core.errors import ComponentUnavailable
from app.models.policy import PolicyTerms


def _props(data: dict) -> dict:
    """Neo4j-safe property map: Decimals -> float, drop None/collections."""
    out = {}
    for key, value in data.items():
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, (str, int, float, bool)):
            out[key] = value
    return out


class PolicyGraph:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._driver = None

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.neo4j_uri and self._settings.neo4j_password)

    def _session(self):
        if not self.is_configured:
            raise ComponentUnavailable("policy_graph", "Neo4j not configured (NEO4J_URI unset).")
        if self._driver is None:
            from neo4j import GraphDatabase

            self._driver = GraphDatabase.driver(
                self._settings.neo4j_uri,
                auth=(self._settings.neo4j_username, self._settings.neo4j_password),
                connection_timeout=10,
            )
        return self._driver.session()

    def ingest(self, terms: PolicyTerms) -> dict[str, int]:
        """(Re)build this policy's subgraph. Returns node counts by label."""
        pid = terms.policy_id
        try:
            with self._session() as session:
                session.run(
                    "MERGE (p:Policy {policy_id: $pid}) "
                    "SET p.name = $name, p.insurer = $insurer, "
                    "    p.per_claim_limit = $pcl, p.annual_opd_limit = $aol",
                    pid=pid, name=terms.policy_name, insurer=terms.insurer,
                    pcl=float(terms.coverage.per_claim_limit),
                    aol=float(terms.coverage.annual_opd_limit),
                )
                for name, cat in terms.opd_categories.items():
                    session.run(
                        "MATCH (p:Policy {policy_id: $pid}) "
                        "MERGE (c:Category {policy_id: $pid, name: $name}) "
                        "SET c += $props MERGE (p)-[:HAS_CATEGORY]->(c)",
                        pid=pid, name=name.upper(), props=_props(cat.model_dump()),
                    )
                for cat_name, reqs in terms.document_requirements.items():
                    for doc_type, rel in [(t, "REQUIRES_DOC") for t in reqs.required] + [
                        (t, "ACCEPTS_DOC") for t in reqs.optional
                    ]:
                        session.run(
                            f"MATCH (c:Category {{policy_id: $pid, name: $cat}}) "
                            f"MERGE (d:DocType {{name: $doc}}) MERGE (c)-[:{rel}]->(d)",
                            pid=pid, cat=cat_name, doc=doc_type,
                        )
                for clause in (
                    terms.exclusions.conditions
                    + terms.exclusions.dental_exclusions
                    + terms.exclusions.vision_exclusions
                ):
                    session.run(
                        "MATCH (p:Policy {policy_id: $pid}) "
                        "MERGE (e:Exclusion {policy_id: $pid, clause: $clause}) "
                        "MERGE (p)-[:EXCLUDES]->(e)",
                        pid=pid, clause=clause,
                    )
                for key, days in terms.waiting_periods.specific_conditions.items():
                    session.run(
                        "MATCH (p:Policy {policy_id: $pid}) "
                        "MERGE (w:Condition {policy_id: $pid, key: $key}) SET w.days = $days "
                        "MERGE (p)-[:HAS_WAITING_PERIOD]->(w)",
                        pid=pid, key=key, days=days,
                    )
                for member in terms.members:
                    session.run(
                        "MATCH (p:Policy {policy_id: $pid}) "
                        "MERGE (m:Member {member_id: $mid}) SET m += $props "
                        "MERGE (p)-[:COVERS]->(m)",
                        pid=pid, mid=member.member_id,
                        props=_props(member.model_dump(exclude={"dependents"})),
                    )
                for member in terms.members:
                    if member.primary_member_id:
                        session.run(
                            "MATCH (d:Member {member_id: $dep}), (m:Member {member_id: $primary}) "
                            "MERGE (d)-[:DEPENDENT_OF]->(m)",
                            dep=member.member_id, primary=member.primary_member_id,
                        )
                counts = session.run(
                    "MATCH (n) WHERE n.policy_id = $pid OR n:DocType OR n:Member "
                    "RETURN labels(n)[0] AS label, count(n) AS n",
                    pid=pid,
                ).data()
            return {row["label"]: row["n"] for row in counts}
        except ComponentUnavailable:
            raise
        except Exception as exc:
            raise ComponentUnavailable("policy_graph", f"Graph ingestion failed: {exc}") from exc

    def document_requirements(self, policy_id: str, category: str) -> list[str]:
        """Required doc types for a category, straight from the graph."""
        try:
            with self._session() as session:
                rows = session.run(
                    "MATCH (:Category {policy_id: $pid, name: $cat})-[:REQUIRES_DOC]->(d:DocType) "
                    "RETURN d.name AS name ORDER BY name",
                    pid=policy_id, cat=category,
                ).data()
            return [r["name"] for r in rows]
        except ComponentUnavailable:
            raise
        except Exception as exc:
            raise ComponentUnavailable("policy_graph", f"Graph query failed: {exc}") from exc

    def healthy(self) -> bool:
        if not self.is_configured:
            return False
        try:
            with self._session() as session:
                session.run("RETURN 1")
            return True
        except Exception:
            return False

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
