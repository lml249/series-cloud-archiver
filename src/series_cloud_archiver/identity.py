from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from .moviepilot import MoviePilotClient
from .redaction import redact_sensitive_text


TMDBID_PATTERN = re.compile(r"\{tmdbid=(?P<tmdbid>\d+)\}", re.IGNORECASE)


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
    if path_value:
        best_path = ""
        best_record: Optional[Dict[str, object]] = None
        normalized = _normalize_path(path_value)
        for key, record in overrides.items():
            if key[0] != "path":
                continue
            override_path = _normalize_path(str(key[1] or ""))
            if override_path and normalized.startswith(override_path + "/") and len(override_path) > len(best_path):
                best_path = override_path
                best_record = record
        if best_record:
            return best_record
    return None


def _normalize_path(value: str) -> str:
    return str(value or "").rstrip("/")


def resolve_identity_overrides_from_scan_report(
    scan_report: Dict[str, object],
    mp_base_url: str,
    mp_token: str,
    top: int = 0,
    output_path: str = "",
    timeout: int = 20,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, object]:
    return _resolve_identity_overrides_from_candidates(
        _candidate_titles_missing_identity(scan_report),
        mp_base_url,
        mp_token,
        top=top,
        output_path=output_path,
        timeout=timeout,
        progress=progress,
    )


def resolve_identity_overrides_from_cloud_report(
    cloud_report: Dict[str, object],
    mp_base_url: str,
    mp_token: str,
    top: int = 0,
    output_path: str = "",
    timeout: int = 20,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, object]:
    return _resolve_identity_overrides_from_candidates(
        _candidates_from_cloud_identity_review(cloud_report),
        mp_base_url,
        mp_token,
        top=top,
        output_path=output_path,
        timeout=timeout,
        progress=progress,
    )


def _resolve_identity_overrides_from_candidates(
    candidates: List[Dict[str, object]],
    mp_base_url: str,
    mp_token: str,
    top: int = 0,
    output_path: str = "",
    timeout: int = 20,
    progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, object]:
    client = MoviePilotClient(mp_base_url, mp_token, timeout=timeout)
    records: List[Dict[str, object]] = []
    unresolved: List[Dict[str, object]] = []
    warnings: List[str] = []
    if top > 0:
        candidates = candidates[:top]

    def persist(attempted: int) -> None:
        if not output_path:
            return
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_identity_overrides(_identity_payload(records, unresolved, warnings, len(candidates), attempted)) + "\n",
            encoding="utf-8",
        )

    persist(0)
    attempted = 0
    for index, candidate in enumerate(candidates, start=1):
        title = str(candidate.get("title") or "")
        if progress:
            progress(f"[{index}/{len(candidates)}] recognizing: {title}")
        record, diagnostics = _resolve_candidate_identity(client, candidate)
        if record:
            records.append(record)
            if progress:
                progress(
                    f"[{index}/{len(candidates)}] resolved: {title} -> tmdbid={record['tmdbid']} "
                    f"season={record['season']} query={record.get('matched_query', '')}"
                )
        elif progress:
            unresolved.append(_unresolved_identity(candidate, diagnostics))
            progress(f"[{index}/{len(candidates)}] skipped: {title}")
        else:
            unresolved.append(_unresolved_identity(candidate, diagnostics))
        attempted = index
        persist(attempted)

    return _identity_payload(records, unresolved, warnings, len(candidates), attempted)


def _identity_payload(
    records: List[Dict[str, object]],
    unresolved: List[Dict[str, object]],
    warnings: List[str],
    input_candidates: int,
    attempted: int,
) -> Dict[str, object]:
    return {
        "identity_overrides": records,
        "unresolved_identity": unresolved,
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


def _candidates_from_cloud_identity_review(cloud_report: Dict[str, object]) -> List[Dict[str, object]]:
    seen: Set[Tuple[str, str]] = set()
    candidates: List[Dict[str, object]] = []
    for item in cloud_report.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("status") != "needs_identity_review":
            continue
        source_paths = item.get("source_paths") if isinstance(item.get("source_paths"), list) else []
        path_value = str(source_paths[0]) if source_paths else ""
        title = str(item.get("title") or "")
        key = (title, path_value)
        if not title or key in seen:
            continue
        seen.add(key)
        season = int(item.get("season") or 0)
        candidate = {
            "title": title,
            "path": path_value,
            "status": "candidate_for_cloud_check",
            "video_count": int(item.get("expected_count") or 0),
            "episode_numbers": item.get("expected_episodes") if isinstance(item.get("expected_episodes"), list) else [],
            "seasons": [season] if season else [],
        }
        candidates.append(candidate)
    return candidates


def _candidate_has_identity(candidate: Dict[str, object]) -> bool:
    for key in ("manual_completion", "mp"):
        value = candidate.get(key)
        if isinstance(value, dict) and int(value.get("tmdbid") or 0) and int(value.get("season") or 0):
            return True
    tmdbid = _tmdbid_from_text(str(candidate.get("title") or "") + " " + str(candidate.get("path") or ""))
    season = _season_from_candidate(candidate)
    if tmdbid and season:
        return True
    return False


def _tmdbid_from_text(text: str) -> int:
    match = TMDBID_PATTERN.search(text or "")
    return int(match.group("tmdbid")) if match else 0


def _season_from_candidate(candidate: Dict[str, object]) -> int:
    title_season = _season_from_text(str(candidate.get("title") or ""))
    if title_season:
        return title_season
    seasons = candidate.get("seasons")
    if isinstance(seasons, list):
        season_values = sorted({int(value) for value in seasons if isinstance(value, int) or str(value).isdigit()})
        if len(season_values) == 1:
            return season_values[0]
    return 0


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


def _resolve_candidate_identity(client: MoviePilotClient, candidate: Dict[str, object]) -> Tuple[Optional[Dict[str, object]], List[Dict[str, object]]]:
    diagnostics: List[Dict[str, object]] = []
    for query in _identity_query_variants(candidate):
        try:
            payload = client.recognize_file(query)
        except Exception as exc:  # noqa: BLE001
            diagnostics.append(
                {
                    "query": query,
                    "status": "error",
                    "error_type": exc.__class__.__name__,
                    "error": redact_sensitive_text(str(exc)),
                }
            )
            continue
        record = _override_from_recognition(candidate, payload)
        diagnostics.append(_identity_query_diagnostic(query, payload, resolved=bool(record)))
        if record:
            record["matched_query"] = query
            return record, diagnostics
    return None, diagnostics


def _identity_query_variants(candidate: Dict[str, object]) -> List[str]:
    values = [
        str(candidate.get("title") or ""),
        *_path_query_variants(str(candidate.get("path") or "")),
    ]
    clean_values: List[str] = []
    for value in values:
        for variant in _title_query_variants(value):
            if variant and variant not in clean_values:
                clean_values.append(variant)
    return clean_values


def _path_query_variants(path_value: str) -> List[str]:
    if not path_value:
        return []
    parts = [part for part in re.split(r"/+", path_value.strip("/")) if part]
    if not parts:
        return []
    values = [path_value]
    if parts:
        values.append(parts[-1])
    if len(parts) >= 2:
        values.append(parts[-2])
    return values


def _title_query_variants(value: str) -> List[str]:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return []
    variants = [text]
    without_season = re.sub(r"(?i)\s+Season\s+\d{1,2}\b", "", text).strip()
    if without_season and without_season != text:
        variants.append(without_season)
    without_season_dir = re.sub(r"(?i)(?:^|[/\s._-])Season\s*\d{1,2}$", "", text).strip(" /._-")
    if without_season_dir and without_season_dir not in variants:
        variants.append(without_season_dir)
    basename = text.rsplit("/", 1)[-1]
    if basename and basename not in variants:
        variants.append(basename)
    return variants


def _identity_query_diagnostic(query: str, payload: object, *, resolved: bool) -> Dict[str, object]:
    if not isinstance(payload, dict):
        return {"query": query, "status": "unresolved", "reason": "non_object_response"}
    meta = payload.get("meta_info") if isinstance(payload.get("meta_info"), dict) else {}
    media = payload.get("media_info") if isinstance(payload.get("media_info"), dict) else {}
    tmdbid = int(media.get("tmdb_id") or 0)
    media_type = str(media.get("type") or meta.get("type") or "")
    if resolved:
        status = "resolved"
        reason = ""
    elif not tmdbid:
        status = "unresolved"
        reason = "missing_tmdbid"
    elif media_type not in {"电视剧", "tv", "series"}:
        status = "unresolved"
        reason = "non_tv_media_type"
    else:
        status = "unresolved"
        reason = "season_unresolved"
    return {
        "query": query,
        "status": status,
        "reason": reason,
        "media_type": media_type,
        "title": str(media.get("title") or meta.get("name") or ""),
        "year": str(media.get("year") or meta.get("year") or ""),
        "tmdbid": tmdbid,
        "begin_season": meta.get("begin_season"),
        "end_season": meta.get("end_season"),
        "media_seasons": sorted(str(key) for key in (media.get("seasons") or {}).keys()) if isinstance(media.get("seasons"), dict) else [],
    }


def _unresolved_identity(candidate: Dict[str, object], diagnostics: List[Dict[str, object]]) -> Dict[str, object]:
    return {
        "title": str(candidate.get("title") or ""),
        "match_path": str(candidate.get("path") or ""),
        "season": _season_from_candidate(candidate),
        "expected_episodes": candidate.get("episode_numbers") if isinstance(candidate.get("episode_numbers"), list) else [],
        "queries": diagnostics,
        "next_action": "人工补充 identity override，或修正标题/路径后重新运行 identity-resolve。",
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
