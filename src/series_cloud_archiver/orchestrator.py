from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional

from .config import ScanConfig
from .models import ScanReport
from .scanner import scan
from .storage import Repository, StoredSeries


def evaluate(config: ScanConfig, db_path: str) -> ScanReport:
    output_top = config.top
    report = scan(replace(config, top=0))
    repo = Repository(db_path)
    try:
        for candidate in report.candidates:
            repo.upsert_candidate(candidate)
    finally:
        repo.close()
    if output_top > 0:
        report.candidates = report.candidates[:output_top]
    return report


def list_status(db_path: str, limit: int = 100, status: Optional[str] = None) -> List[StoredSeries]:
    repo = Repository(db_path)
    try:
        return repo.list_series(limit=limit, status=status)
    finally:
        repo.close()


def status_detail(db_path: str, query: str) -> Dict[str, object]:
    repo = Repository(db_path)
    try:
        series = repo.find_series(query)
        if not series:
            return {"found": False, "query": query}
        return {
            "found": True,
            "series": series.__dict__,
            "audit": repo.audit_for(series.path),
        }
    finally:
        repo.close()


def plan_cleanup(db_path: str, query: str) -> Dict[str, object]:
    repo = Repository(db_path)
    try:
        series = repo.find_series(query)
        if not series:
            return {"found": False, "query": query}
        plan = repo.create_cleanup_plan(series)
        plan["found"] = True
        return plan
    finally:
        repo.close()
