from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List, Optional, Set

from .models import FileSystemSeries, ManualCompletionEvidence


def load_manual_completion_evidence(path: str) -> List[ManualCompletionEvidence]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records = payload.get("manual_completions", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("manual completion file must contain a list or manual_completions list")

    evidence: List[ManualCompletionEvidence] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        paths = _paths_from_item(item)
        if not paths:
            paths = [""]
        for item_path in paths:
            evidence.append(
                ManualCompletionEvidence(
                    title=str(item.get("title") or item.get("recognized_title") or ""),
                    path=item_path,
                    tmdbid=int(item.get("tmdbid") or item.get("tmdb_id") or 0),
                    season=int(item.get("season") or 0),
                    confirmed_at=str(item.get("confirmed_at") or ""),
                    note=str(item.get("note") or ""),
                    matched=False,
                )
            )
    return evidence


def match_manual_completion(
    series: FileSystemSeries,
    evidence: Iterable[ManualCompletionEvidence],
) -> Optional[ManualCompletionEvidence]:
    series_path = _normalize_path(series.path)
    series_title = _compact(series.title)
    series_seasons = _series_seasons(series)

    for item in evidence:
        if item.path and _normalize_path(item.path) == series_path:
            return _matched(item)

    for item in evidence:
        if item.path:
            continue
        if item.season and series_seasons and item.season not in series_seasons:
            continue
        if item.title and _compact(item.title) in series_title:
            return _matched(item)
    return None


def _matched(item: ManualCompletionEvidence) -> ManualCompletionEvidence:
    return ManualCompletionEvidence(
        title=item.title,
        path=item.path,
        tmdbid=item.tmdbid,
        season=item.season,
        confirmed_at=item.confirmed_at,
        note=item.note,
        matched=True,
    )


def _paths_from_item(item: dict) -> List[str]:
    values: List[str] = []
    for key in ("path", "paths"):
        value = item.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(part) for part in value if part)
    return values


def _normalize_path(value: str) -> str:
    return value.rstrip("/")


def _compact(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.casefold())


def _series_seasons(series: FileSystemSeries) -> Set[int]:
    seasons = set(series.signal.seasons)
    for match in re.finditer(r"(?i)\bS(?P<season>\d{1,2})\b", series.title):
        seasons.add(int(match.group("season")))
    for match in re.finditer(r"第\s*(?P<season>\d{1,2})\s*季", series.title):
        seasons.add(int(match.group("season")))
    return seasons
