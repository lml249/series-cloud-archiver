from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .models import ScanCandidate


SCHEMA = """
CREATE TABLE IF NOT EXISTS series_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  video_count INTEGER NOT NULL,
  age_days REAL NOT NULL,
  score INTEGER NOT NULL,
  reasons_json TEXT NOT NULL,
  blockers_json TEXT NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  series_path TEXT NOT NULL,
  event_type TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  message TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cleanup_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  series_path TEXT NOT NULL,
  status TEXT NOT NULL,
  deletion_targets_json TEXT NOT NULL,
  blockers_json TEXT NOT NULL,
  created_at REAL NOT NULL
);
"""


@dataclass
class StoredSeries:
    title: str
    path: str
    status: str
    size_bytes: int
    video_count: int
    age_days: float
    score: int
    reasons: List[str]
    blockers: List[str]
    updated_at: float


class Repository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert_candidate(self, candidate: ScanCandidate) -> None:
        now = time.time()
        current = self.conn.execute(
            "SELECT status FROM series_items WHERE path = ?",
            (candidate.path,),
        ).fetchone()
        old_status = current["status"] if current else None
        self.conn.execute(
            """
            INSERT INTO series_items (
              title, path, status, size_bytes, video_count, age_days, score,
              reasons_json, blockers_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
              title=excluded.title,
              status=excluded.status,
              size_bytes=excluded.size_bytes,
              video_count=excluded.video_count,
              age_days=excluded.age_days,
              score=excluded.score,
              reasons_json=excluded.reasons_json,
              blockers_json=excluded.blockers_json,
              updated_at=excluded.updated_at
            """,
            (
                candidate.title,
                candidate.path,
                candidate.status,
                candidate.size_bytes,
                candidate.video_count,
                candidate.age_days,
                candidate.score,
                json.dumps(candidate.reasons, ensure_ascii=False),
                json.dumps(candidate.blockers, ensure_ascii=False),
                now,
            ),
        )
        if old_status != candidate.status:
            self.add_audit(
                candidate.path,
                "state_changed" if old_status else "series_discovered",
                old_status,
                candidate.status,
                f"{candidate.title}: {old_status or 'new'} -> {candidate.status}",
                candidate.to_dict(),
            )
        else:
            self.add_audit(
                candidate.path,
                "series_refreshed",
                old_status,
                candidate.status,
                f"{candidate.title}: refreshed {candidate.status}",
                {"score": candidate.score, "blockers": candidate.blockers, "reasons": candidate.reasons},
            )
        self.conn.commit()

    def add_audit(
        self,
        series_path: str,
        event_type: str,
        from_status: Optional[str],
        to_status: Optional[str],
        message: str,
        payload: Dict[str, object],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO audit_events (
              series_path, event_type, from_status, to_status, message,
              payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                series_path,
                event_type,
                from_status,
                to_status,
                message,
                json.dumps(payload, ensure_ascii=False),
                time.time(),
            ),
        )

    def list_series(self, limit: int = 100, status: Optional[str] = None) -> List[StoredSeries]:
        sql = "SELECT * FROM series_items"
        params: List[object] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY status, score DESC, size_bytes DESC, title LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [self._row_to_series(row) for row in rows]

    def find_series(self, query: str) -> Optional[StoredSeries]:
        row = self.conn.execute(
            "SELECT * FROM series_items WHERE path = ? OR title = ?",
            (query, query),
        ).fetchone()
        if not row:
            row = self.conn.execute(
                "SELECT * FROM series_items WHERE title LIKE ? ORDER BY score DESC LIMIT 1",
                (f"%{query}%",),
            ).fetchone()
        return self._row_to_series(row) if row else None

    def create_cleanup_plan(self, series: StoredSeries) -> Dict[str, object]:
        blockers = list(series.blockers)
        blockers.extend(
            [
                "missing_mv3_strm_evidence",
                "missing_emby_strm_verification",
                "missing_playback_probe",
                "missing_qb_seed_age_evidence",
                "manual_approval_required",
            ]
        )
        status = "blocked"
        deletion_targets: List[str] = []
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO cleanup_plans (
              series_path, status, deletion_targets_json, blockers_json, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                series.path,
                status,
                json.dumps(deletion_targets, ensure_ascii=False),
                json.dumps(blockers, ensure_ascii=False),
                now,
            ),
        )
        self.add_audit(
            series.path,
            "cleanup_plan_created",
            series.status,
            series.status,
            f"cleanup blocked for {series.title}",
            {"blockers": blockers, "deletion_targets": deletion_targets},
        )
        self.conn.commit()
        return {
            "series": series.title,
            "path": series.path,
            "status": status,
            "deletion_targets": deletion_targets,
            "blockers": blockers,
            "created_at": now,
        }

    def audit_for(self, series_path: str, limit: int = 20) -> List[Dict[str, object]]:
        rows = self.conn.execute(
            """
            SELECT event_type, from_status, to_status, message, payload_json, created_at
            FROM audit_events
            WHERE series_path = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (series_path, limit),
        ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "from_status": row["from_status"],
                "to_status": row["to_status"],
                "message": row["message"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _row_to_series(self, row: sqlite3.Row) -> StoredSeries:
        return StoredSeries(
            title=row["title"],
            path=row["path"],
            status=row["status"],
            size_bytes=int(row["size_bytes"]),
            video_count=int(row["video_count"]),
            age_days=float(row["age_days"]),
            score=int(row["score"]),
            reasons=json.loads(row["reasons_json"]),
            blockers=json.loads(row["blockers_json"]),
            updated_at=float(row["updated_at"]),
        )

