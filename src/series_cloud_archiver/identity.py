from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from .moviepilot import MoviePilotClient


def load_identity_overrides(path: str) -> Dict[Tuple[str, str], Dict[str, object]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records = payload.get("identity_overrides", payload) if isinstance(payload, dict) else payload
    overrides: Dict[Tuple[str, str], Dict[str, object]] = {}
    if not isinstance(records, list):
        raise ValueError("identity file must contain a list or identity_overrides list")
    for record in records:
        if not isinstance(record, dict):
            continue
        title = str(record.get("match_title") or record.get("title") or "")
        path_value = str(record.get("match_path") or "")
        if title:
            overrides[("title", title)] = record
        if path_value:
            overrides[("path", path_value)] = record
    return overrides


def identity_for_candidate(
    candidate: Dict[str, object],
    overrides: Dict[Tuple[str, str], Dict[str, object]],
) -> Optional[Dict[str, object]]:
    path_value = str(candidate.get("path") or "")
    title = str(candidate.get("title") or "")
    if path_value and ("path", path_value) in overrides:
        return overrides[("path", path_value)]
    if title and ("title", title) in overrides:
        return overrides[("title", title)]
    return None


def resolve_identity_overrides_from_scan_report(
    scan_report: Dict[str, object],
    mp_base_url: str,
    mp_token: str,
    top: int = 0,
    output_path: str = "",
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, object]:
    client = MoviePilotClient(mp_base_url, mp_token)
    records: List[Dict[str, object]] = []
    warnings: List[str] = []
    candidates = _candidate_titles_missing_identity(scan_report)
    if top > 0:
        candidates = candidates[:top]

    def persist(attempted: int) -> None:
        if not output_path:
            return
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_identity_overrides(_identity_payload(records, warnings, len(candidates), attempted)) + "\n", encoding="utf-8")

    persist(0)
    attempted = 0
    for index, candidate in enumerate(candidates, start=1):
        title = str(candidate.get("title") or "")
        if progress:
            progress(f"[{index}/{len(candidates)}] recognizing: {title}")
        try:
            payload = client.recognize_file(title)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"recognize_failed: {title}: {exc}")
            attempted = index
            persist(attempted)
            if progress:
                progress(f"[{index}/{len(candidates)}] failed: {title}: {exc}")
            continue
        record = _override_from_recognition(candidate, payload)
        if record:
            records.append(record)
            if progress:
                progress(f"[{index}/{len(candidates)}] resolved: {title} -> tmdbid={record['tmdbid']} season={record['season']}")
        elif progress:
            progress(f"[{index}/{len(candidates)}] skipped: {title}")
        attempted = index
        persist(attempted)

    return _identity_payload(records, warnings, len(candidates), attempted)


def _identity_payload(
    records: List[Dict[str, object]],
    warnings: List[str],
    input_candidates: int,
    attempted: int,
) -> Dict[str, object]:
    return {
        "identity_overrides": records,
        "warnings": warnings,
        "summary": {
            "input_candidates": input_candidates,
            "attempted": attempted,
            "resolved": len(records),
        },
    }


def render_identity_overrides(payload: Dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _candidate_titles_missing_identity(scan_report: Dict[str, object]) -> List[Dict[str, object]]:
    seen: Set[str] = set()
    candidates: List[Dict[str, object]] = []
    for candidate in scan_report.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        if candidate.get("status") != "candidate_for_cloud_check":
            continue
        if _candidate_has_identity(candidate):
            continue
        title = str(candidate.get("title") or "")
        if not title or title in seen:
            continue
        seen.add(title)
        candidates.append(candidate)
    return candidates


def _candidate_has_identity(candidate: Dict[str, object]) -> bool:
    for key in ("manual_completion", "mp"):
        value = candidate.get(key)
        if isinstance(value, dict) and int(value.get("tmdbid") or 0) and int(value.get("season") or 0):
            return True
    return False


def _override_from_recognition(candidate: Dict[str, object], payload: object) -> Optional[Dict[str, object]]:
    if not isinstance(payload, dict):
        return None
    meta = payload.get("meta_info") if isinstance(payload.get("meta_info"), dict) else {}
    media = payload.get("media_info") if isinstance(payload.get("media_info"), dict) else {}
    tmdbid = int(media.get("tmdb_id") or 0)
    if not tmdbid:
        return None
    media_type = str(media.get("type") or meta.get("type") or "")
    if media_type not in {"电视剧", "tv", "series"}:
        return None
    season = _resolved_season(candidate, meta, media)
    expected_episodes = _expected_episodes(media, season)
    return {
        "match_title": str(candidate.get("title") or ""),
        "match_path": str(candidate.get("path") or ""),
        "title": str(media.get("title") or meta.get("name") or ""),
        "en_title": str(media.get("en_title") or meta.get("en_name") or ""),
        "year": str(media.get("year") or meta.get("year") or ""),
        "tmdbid": tmdbid,
        "season": season,
        "expected_episodes": expected_episodes,
        "method": "moviepilot_recognize_file2",
        "confidence": "high" if season else "needs_season_review",
        "note": _season_note(meta, media, season),
    }


def _resolved_season(candidate: Dict[str, object], meta: Dict[str, object], media: Dict[str, object]) -> int:
    seasons = candidate.get("seasons")
    if isinstance(seasons, list):
        season_values = sorted({int(value) for value in seasons if isinstance(value, int) or str(value).isdigit()})
        if len(season_values) == 1 and season_values[0]:
            return season_values[0]
        if len(season_values) > 1:
            return 0
    begin = int(meta.get("begin_season") or 0)
    end = int(meta.get("end_season") or 0)
    if begin and end and end != begin:
        return 0
    if begin and (not end or end == begin):
        return begin
    keys = [int(key) for key in (media.get("seasons") or {}).keys() if str(key).isdigit() and int(key) > 0]
    if len(keys) == 1:
        return keys[0]
    title_season = _season_from_text(str(candidate.get("title") or ""))
    return title_season


def _expected_episodes(media: Dict[str, object], season: int) -> List[int]:
    if not season:
        return []
    seasons = media.get("seasons") if isinstance(media.get("seasons"), dict) else {}
    values = seasons.get(str(season)) or seasons.get(season) or []
    if isinstance(values, list):
        return sorted(int(value) for value in values if isinstance(value, int) or str(value).isdigit())
    return []


def _season_note(meta: Dict[str, object], media: Dict[str, object], season: int) -> str:
    if season:
        return "Resolved by single season signal or candidate title."
    begin = meta.get("begin_season")
    end = meta.get("end_season")
    seasons = sorted(str(key) for key in (media.get("seasons") or {}).keys())
    return f"Season unresolved; meta range={begin}-{end}, media seasons={','.join(seasons)}"


def _season_from_text(text: str) -> int:
    match = re.search(r"(?i)\bS(?P<season>\d{1,2})\b", text)
    if match:
        return int(match.group("season"))
    match = re.search(r"第\s*(?P<season>\d{1,2})\s*季", text)
    return int(match.group("season")) if match else 0
