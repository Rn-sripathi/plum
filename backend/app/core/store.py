"""Claim store — system of record for submissions, results, and traces.

Two implementations of one `ClaimStore` protocol:
- `SqliteClaimStore` (stdlib) — zero-setup default, runs anywhere.
- `PostgresClaimStore` (psycopg) — production store (e.g. Neon); activated by
  `DATABASE_URL`. Traces live in JSONB so ops can query them directly.

Per the resilience table (PLAN.md §4): if the store fails, processing
continues in memory and the decision is still returned — persistence failure
is a warning, never a crash.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from app.core.config import Settings
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


_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id     TEXT PRIMARY KEY,
    submitted_at TIMESTAMPTZ NOT NULL,
    member_id    TEXT NOT NULL,
    category     TEXT NOT NULL,
    status       TEXT NOT NULL,
    submission   JSONB NOT NULL,
    result       JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_member ON claims (member_id, submitted_at);
"""


class PostgresClaimStore:
    """Same contract as SqliteClaimStore, on Postgres (Neon). JSONB columns
    make the trace queryable: e.g.
    `SELECT claim_id FROM claims WHERE result->'rejection_reasons' ? 'WAITING_PERIOD'`.
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        with self._connect() as conn:
            conn.execute(_PG_SCHEMA)

    def _connect(self):
        import psycopg

        return psycopg.connect(self.dsn, autocommit=True)

    def save(self, submission: ClaimSubmission, result: ClaimDecision | DocumentProblemReport) -> None:
        status = "DOCUMENTS_REQUIRED" if isinstance(result, DocumentProblemReport) else result.decision.value
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO claims VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                ON CONFLICT (claim_id) DO UPDATE SET
                    submitted_at = EXCLUDED.submitted_at, status = EXCLUDED.status,
                    submission = EXCLUDED.submission, result = EXCLUDED.result
                """,
                (
                    result.claim_id,
                    datetime.now(timezone.utc),
                    submission.member_id,
                    submission.claim_category.value,
                    status,
                    submission.model_dump_json(),
                    result.model_dump_json(),
                ),
            )

    def get(self, claim_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT claim_id, submitted_at, member_id, category, status, submission, result "
                "FROM claims WHERE claim_id = %s",
                (claim_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "claim_id": row[0],
            "submitted_at": row[1].isoformat(),
            "member_id": row[2],
            "category": row[3],
            "status": row[4],
            "submission": row[5],
            "result": row[6],
        }

    def list_recent(self, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT claim_id, submitted_at, member_id, category, status FROM claims "
                "ORDER BY submitted_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [
            {
                "claim_id": r[0],
                "submitted_at": r[1].isoformat(),
                "member_id": r[2],
                "category": r[3],
                "status": r[4],
            }
            for r in rows
        ]

    def healthy(self) -> bool:
        try:
            with self._connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception:
            return False


def make_store(settings: Settings) -> "ClaimStore":
    """Postgres when DATABASE_URL is set (Neon in production), SQLite otherwise."""
    if settings.database_url:
        return PostgresClaimStore(settings.database_url)
    return SqliteClaimStore(settings.database_path)
