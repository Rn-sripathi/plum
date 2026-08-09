"""Claim store — system of record for submissions, results, and traces.

SQLite (stdlib) by default so the system runs anywhere with zero setup; the
`ClaimStore` protocol is the seam where a Postgres implementation slots in
for production (documented trade-off: one-node SQLite is fine for assignment
scale; at 10x we swap the implementation, not the callers).

Per the resilience table (PLAN.md §4): if the store fails, processing
continues in memory and the decision is still returned — persistence failure
is a warning, never a crash.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from app.models import ClaimSubmission
from app.models.adjudication import ClaimDecision
from app.models.documents import DocumentProblemReport

_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id     TEXT PRIMARY KEY,
    submitted_at TEXT NOT NULL,
    member_id    TEXT NOT NULL,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL,
    submission   TEXT NOT NULL,  -- ClaimSubmission JSON
    result       TEXT NOT NULL   -- ClaimDecision / DocumentProblemReport JSON
);
CREATE INDEX IF NOT EXISTS idx_claims_member ON claims (member_id, submitted_at);
"""


class ClaimStore(Protocol):
    def save(self, submission: ClaimSubmission, result: ClaimDecision | DocumentProblemReport) -> None: ...
    def get(self, claim_id: str) -> dict | None: ...
    def list_recent(self, limit: int = 50) -> list[dict]: ...
    def healthy(self) -> bool: ...


class SqliteClaimStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def save(self, submission: ClaimSubmission, result: ClaimDecision | DocumentProblemReport) -> None:
        status = "DOCUMENTS_REQUIRED" if isinstance(result, DocumentProblemReport) else result.decision.value
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO claims VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    result.claim_id,
                    datetime.now(timezone.utc).isoformat(),
                    submission.member_id,
                    submission.claim_category.value,
                    status,
                    submission.model_dump_json(),
                    result.model_dump_json(),
                ),
            )

    def get(self, claim_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,)).fetchone()
        if row is None:
            return None
        return {
            "claim_id": row["claim_id"],
            "submitted_at": row["submitted_at"],
            "member_id": row["member_id"],
            "category": row["category"],
            "status": row["status"],
            "submission": json.loads(row["submission"]),
            "result": json.loads(row["result"]),
        }

    def list_recent(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT claim_id, submitted_at, member_id, category, status FROM claims "
                "ORDER BY submitted_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def healthy(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False
