from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import get_settings
from .models import ApprovalStatus, BidSource, Decision, Tender


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_settings().database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tenders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    external_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    bid_number TEXT NOT NULL,
                    title TEXT NOT NULL,
                    ministry TEXT,
                    department TEXT,
                    quantity INTEGER,
                    start_at TEXT,
                    end_at TEXT,
                    url TEXT,
                    document_url TEXT,
                    raw_json TEXT,
                    fit_score REAL DEFAULT 0,
                    matched_keywords TEXT,
                    reasons TEXT,
                    decision TEXT,
                    analysis_json TEXT,
                    approval_status TEXT DEFAULT 'pending',
                    proposal_path TEXT,
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source, external_id)
                );

                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    bid_number TEXT,
                    details TEXT
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bid_number TEXT NOT NULL,
                    status TEXT NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

    def upsert_tender(
        self,
        tender: Tender,
        *,
        fit_score: float = 0.0,
        matched_keywords: list[str] | None = None,
        reasons: list[str] | None = None,
    ) -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO tenders (
                    external_id, source, bid_number, title, ministry, department,
                    quantity, start_at, end_at, url, document_url, raw_json,
                    fit_score, matched_keywords, reasons, first_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, external_id) DO UPDATE SET
                    title=excluded.title,
                    ministry=excluded.ministry,
                    department=excluded.department,
                    quantity=excluded.quantity,
                    start_at=excluded.start_at,
                    end_at=excluded.end_at,
                    url=excluded.url,
                    document_url=excluded.document_url,
                    raw_json=excluded.raw_json,
                    fit_score=excluded.fit_score,
                    matched_keywords=excluded.matched_keywords,
                    reasons=excluded.reasons,
                    updated_at=excluded.updated_at
                """,
                (
                    tender.external_id,
                    tender.source.value,
                    tender.bid_number,
                    tender.title,
                    tender.ministry,
                    tender.department,
                    tender.quantity,
                    tender.start_at.isoformat() if tender.start_at else None,
                    tender.end_at.isoformat() if tender.end_at else None,
                    tender.url,
                    tender.document_url,
                    json.dumps(tender.raw),
                    fit_score,
                    json.dumps(matched_keywords or []),
                    json.dumps(reasons or []),
                    now,
                    now,
                ),
            )

    def list_tenders(
        self,
        *,
        min_score: float = 0.0,
        limit: int = 50,
        decision: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM tenders WHERE fit_score >= ?"
        params: list[Any] = [min_score]
        if decision:
            query += " AND decision = ?"
            params.append(decision)
        query += " ORDER BY fit_score DESC, end_at ASC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_by_bid_number(self, bid_number: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM tenders WHERE bid_number = ? ORDER BY updated_at DESC LIMIT 1",
                (bid_number,),
            ).fetchone()
        return dict(row) if row else None

    def save_analysis(
        self,
        bid_number: str,
        *,
        decision: Decision,
        analysis: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE tenders
                SET decision = ?, analysis_json = ?, updated_at = ?
                WHERE bid_number = ?
                """,
                (decision.value, json.dumps(analysis), _utc_now(), bid_number),
            )

    def set_proposal_path(self, bid_number: str, path: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE tenders SET proposal_path = ?, updated_at = ? WHERE bid_number = ?",
                (path, _utc_now(), bid_number),
            )

    def set_approval(self, bid_number: str, status: ApprovalStatus, note: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE tenders SET approval_status = ?, updated_at = ? WHERE bid_number = ?",
                (status.value, _utc_now(), bid_number),
            )
            conn.execute(
                "INSERT INTO approvals (bid_number, status, note, created_at) VALUES (?, ?, ?, ?)",
                (bid_number, status.value, note, _utc_now()),
            )

    def log_action(self, action: str, bid_number: str | None = None, details: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO actions (created_at, action, bid_number, details) VALUES (?, ?, ?, ?)",
                (_utc_now(), action, bid_number, details),
            )

    def tender_from_row(self, row: dict[str, Any]) -> Tender:
        return Tender(
            external_id=row["external_id"],
            source=BidSource(row["source"]),
            bid_number=row["bid_number"],
            title=row["title"],
            ministry=row.get("ministry"),
            department=row.get("department"),
            quantity=row.get("quantity"),
            start_at=_parse_dt(row.get("start_at")),
            end_at=_parse_dt(row.get("end_at")),
            url=row.get("url"),
            document_url=row.get("document_url"),
            raw=json.loads(row.get("raw_json") or "{}"),
        )


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
