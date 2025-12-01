from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import List, Optional

_DEFAULT_DB_PATH = os.getenv("FINAL_DECISION_DB_PATH", "./final_decisions.db")


@dataclass
class FinalDecisionRecord:
    candidate_name: str
    role: str
    decision: str
    next_action: Optional[str]
    updated_at: datetime


class FinalDecisionStore:
    """SQLite-backed helper for tracking final hiring decisions."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _DEFAULT_DB_PATH
        self._lock = Lock()
        self._ensure_table()

    # ------------------------------------------------------------------
    def upsert_decision(
        self,
        *,
        candidate_name: str,
        role: str,
        decision: str,
        next_action: Optional[str] = None,
        updated_at: Optional[datetime] = None,
    ) -> None:
        slug = self._normalize(candidate_name)
        role_slug = self._normalize(role)
        if not slug or not role_slug:
            return
        timestamp = (updated_at or datetime.now(timezone.utc)).isoformat()

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO final_decisions (
                        candidate_name,
                        candidate_slug,
                        role,
                        role_slug,
                        decision,
                        next_action,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(candidate_slug, role_slug)
                    DO UPDATE SET
                        decision=excluded.decision,
                        next_action=excluded.next_action,
                        updated_at=excluded.updated_at
                    """,
                    (
                        candidate_name.strip(),
                        slug,
                        role.strip(),
                        role_slug,
                        decision.strip(),
                        next_action.strip() if next_action else None,
                        timestamp,
                    ),
                )

    def get_decision(
        self,
        *,
        candidate_name: str,
        role_name: Optional[str] = None,
    ) -> Optional[FinalDecisionRecord]:
        slug = self._normalize(candidate_name)
        if not slug:
            return None
        role_slug = self._normalize(role_name) if role_name else None

        with self._connect() as conn:
            if role_slug:
                row = conn.execute(
                    """
                    SELECT candidate_name, role, decision, next_action, updated_at
                    FROM final_decisions
                    WHERE candidate_slug = ? AND role_slug = ?
                    """,
                    (slug, role_slug),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT candidate_name, role, decision, next_action, updated_at
                    FROM final_decisions
                    WHERE candidate_slug = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (slug,),
                ).fetchone()

        if not row:
            return None

        updated_at = datetime.now(timezone.utc)
        if row[4]:
            try:
                updated_at = datetime.fromisoformat(row[4])
            except ValueError:
                pass
        return FinalDecisionRecord(
            candidate_name=row[0],
            role=row[1],
            decision=row[2],
            next_action=row[3],
            updated_at=updated_at,
        )

    def list_decisions(self, role_name: Optional[str] = None) -> List[FinalDecisionRecord]:
        role_slug = self._normalize(role_name) if role_name else None

        with self._connect() as conn:
            if role_slug:
                rows = conn.execute(
                    """
                    SELECT candidate_name, role, decision, next_action, updated_at
                    FROM final_decisions
                    WHERE role_slug = ?
                    ORDER BY updated_at DESC
                    """,
                    (role_slug,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT candidate_name, role, decision, next_action, updated_at
                    FROM final_decisions
                    ORDER BY updated_at DESC
                    """
                ).fetchall()

        records: List[FinalDecisionRecord] = []
        for row in rows:
            timestamp = datetime.now(timezone.utc)
            if row[4]:
                try:
                    timestamp = datetime.fromisoformat(row[4])
                except ValueError:
                    pass
            records.append(
                FinalDecisionRecord(
                    candidate_name=row[0],
                    role=row[1],
                    decision=row[2],
                    next_action=row[3],
                    updated_at=timestamp,
                )
            )
        return records

    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _ensure_table(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS final_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_name TEXT NOT NULL,
                    candidate_slug TEXT NOT NULL,
                    role TEXT NOT NULL,
                    role_slug TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    next_action TEXT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_final_decisions_slug
                ON final_decisions(candidate_slug, role_slug)
                """
            )

    @staticmethod
    def _normalize(value: Optional[str]) -> str:
        return " ".join(value.strip().lower().split()) if value else ""


_store_instance: Optional[FinalDecisionStore] = None


def get_final_decision_store() -> FinalDecisionStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = FinalDecisionStore()
    return _store_instance
