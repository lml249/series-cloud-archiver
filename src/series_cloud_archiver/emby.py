from __future__ import annotations

import sqlite3
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .episode import episode_signal
from .models import EmbyEvidence, FileSystemSeries
from .redaction import redact_sensitive_text


REFRESH_LIBRARY_TASK_KEY = "RefreshLibrary"


class EmbyClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _auth_headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-Emby-Token"] = self.api_key
        return headers

    def _get(self, path: str, query: Dict[str, str]) -> object:
        url = _url_with_query(f"{self.base_url}{path}", query)
        request = urllib.request.Request(url, headers=self._auth_headers())
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            text = response.read().decode("utf-8", "replace")
        return json.loads(text) if text else {}

    def _post_empty(self, path: str, query: Optional[Dict[str, str]] = None) -> Dict[str, object]:
        url = _url_with_query(f"{self.base_url}{path}", query or {})
        request = urllib.request.Request(url, data=b"", headers=self._auth_headers(), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode("utf-8", "replace")
                return {
                    "http_status": response.status,
                    "ok": 200 <= response.status < 300,
                    "response": _parse_json_object(text),
                }
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            return {
                "http_status": exc.code,
                "ok": False,
                "response": _parse_json_object(text),
            }

    def series_items(self) -> List[Dict[str, object]]:
        payload = self._get(
            "/emby/Items",
            {
                "Recursive": "true",
                "IncludeItemTypes": "Series",
                "Fields": "Path,RecursiveItemCount,ProviderIds",
            },
        )
        if not isinstance(payload, dict):
            return []
        return list(payload.get("Items") or [])

    def refresh_library(self) -> Dict[str, object]:
        return self._post_empty("/emby/Library/Refresh")

    def scheduled_tasks(self) -> List[Dict[str, object]]:
        payload = self._get("/emby/ScheduledTasks", {})
        return list(payload) if isinstance(payload, list) else []

    def task_by_key(self, key: str) -> Dict[str, object]:
        for task in self.scheduled_tasks():
            if task.get("Key") == key:
                return task
        return {}

    def wait_for_task(
        self,
        key: str,
        poll_seconds: float = 10.0,
        max_wait_seconds: int = 900,
    ) -> Dict[str, object]:
        started = time.monotonic()
        polls: List[Dict[str, object]] = []
        seen_running = False
        timed_out = False
        while True:
            task = self.task_by_key(key)
            state = str(task.get("State") or "")
            last = task.get("LastExecutionResult") if isinstance(task.get("LastExecutionResult"), dict) else {}
            polls.append(
                {
                    "state": state,
                    "last_status": last.get("Status"),
                    "last_start_utc": last.get("StartTimeUtc"),
                    "last_end_utc": last.get("EndTimeUtc"),
                }
            )
            if state == "Running":
                seen_running = True
            elapsed = time.monotonic() - started
            if state != "Running" and (seen_running or len(polls) >= 2 or max_wait_seconds <= 0):
                break
            if elapsed >= max_wait_seconds:
                timed_out = state == "Running"
                break
            sleep_for = min(float(poll_seconds), max(0.0, max_wait_seconds - elapsed))
            if sleep_for <= 0:
                timed_out = state == "Running"
                break
            time.sleep(sleep_for)
        return {
            "key": key,
            "timed_out": timed_out,
            "final_task": task,
            "polls": polls,
        }

    def items_by_search(self, search_term: str, limit: int = 1000) -> List[Dict[str, object]]:
        items: List[Dict[str, object]] = []
        start = 0
        while True:
            payload = self._get(
                "/emby/Items",
                {
                    "Recursive": "true",
                    "SearchTerm": search_term,
                    "Fields": "Path,ProviderIds,RecursiveItemCount",
                    "StartIndex": str(start),
                    "Limit": str(limit),
                },
            )
            if not isinstance(payload, dict):
                break
            page = list(payload.get("Items") or [])
            items.extend(page)
            total = int(payload.get("TotalRecordCount") or len(items))
            if not page or len(items) >= total:
                break
            start += len(page)
        return items


def refresh_and_verify_emby_library(
    base_url: str,
    api_key: str,
    title: str,
    stale_path_prefixes: Sequence[str],
    strm_path_prefixes: Sequence[str],
    expected_strm_records: int = 0,
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
    library_db_path: str = "",
    skip_refresh: bool = False,
    poll_seconds: float = 10.0,
    max_wait_seconds: int = 900,
    timeout: int = 20,
) -> Dict[str, object]:
    client = EmbyClient(base_url, api_key, timeout=timeout)
    blockers: List[str] = []
    warnings: List[str] = []
    refresh: Dict[str, object] = {"requested": not skip_refresh}
    if not skip_refresh:
        result = client.refresh_library()
        refresh["request"] = result
        if not result.get("ok"):
            blockers.append("emby_refresh_request_failed")
        task = client.wait_for_task(REFRESH_LIBRARY_TASK_KEY, poll_seconds=poll_seconds, max_wait_seconds=max_wait_seconds)
        refresh["task"] = _summarize_task_wait(task)
        if task.get("timed_out"):
            blockers.append("emby_refresh_task_timeout")
    else:
        refresh["request"] = {"skipped": True}
        try:
            refresh["task"] = _summarize_task_wait({"final_task": client.task_by_key(REFRESH_LIBRARY_TASK_KEY), "polls": [], "timed_out": False})
        except Exception as exc:  # pragma: no cover - integration guard
            warnings.append(f"emby_task_check_failed:{type(exc).__name__}:{exc}")

    verification = verify_emby_library_paths(
        client,
        title=title,
        stale_path_prefixes=stale_path_prefixes,
        strm_path_prefixes=strm_path_prefixes,
        expected_strm_records=expected_strm_records,
        expected_episode_count=expected_episode_count,
        expected_episode_min=expected_episode_min,
        expected_episode_max=expected_episode_max,
        library_db_path=library_db_path,
    )
    blockers.extend(verification.get("blockers", []))
    warnings.extend(verification.get("warnings", []))
    report = {
        "mode": "emby-refresh-verify",
        "title": title,
        "ok": not blockers,
        "refresh": refresh,
        "verification": verification,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "safety": "Emby library refresh and readonly verification only; no filesystem deletion, qBittorrent action, MoviePilot cleanup, or direct Emby database write is performed",
    }
    return report


def verify_emby_library_paths(
    client: EmbyClient,
    title: str,
    stale_path_prefixes: Sequence[str],
    strm_path_prefixes: Sequence[str],
    expected_strm_records: int = 0,
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
    library_db_path: str = "",
) -> Dict[str, object]:
    if library_db_path:
        return _verify_emby_paths_from_db(
            library_db_path,
            title=title,
            stale_path_prefixes=stale_path_prefixes,
            strm_path_prefixes=strm_path_prefixes,
            expected_strm_records=expected_strm_records,
            expected_episode_count=expected_episode_count,
            expected_episode_min=expected_episode_min,
            expected_episode_max=expected_episode_max,
        )
    items = client.items_by_search(title)
    report = _build_path_verification(
        method="emby_api_search",
        title=title,
        stale_path_prefixes=stale_path_prefixes,
        strm_path_prefixes=strm_path_prefixes,
        stale_rows=_rows_for_prefixes(items, stale_path_prefixes),
        strm_rows=_rows_for_prefixes(items, strm_path_prefixes),
        expected_strm_records=expected_strm_records,
        expected_episode_count=expected_episode_count,
        expected_episode_min=expected_episode_min,
        expected_episode_max=expected_episode_max,
    )
    report["warnings"].append("emby_api_search_may_hide_duplicate_versions; set EMBY_LIBRARY_DB_PATH for exact local verification")
    return report


def render_emby_refresh_verify_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    refresh = report.get("refresh") if isinstance(report.get("refresh"), dict) else {}
    task = refresh.get("task") if isinstance(refresh.get("task"), dict) else {}
    verification = report.get("verification") if isinstance(report.get("verification"), dict) else {}
    totals = verification.get("totals") if isinstance(verification.get("totals"), dict) else {}
    strm = verification.get("strm") if isinstance(verification.get("strm"), dict) else {}
    lines = [
        "# Emby Refresh Verification",
        "",
        f"- Title: `{report.get('title', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Refresh requested: `{bool(refresh.get('requested'))}`",
        f"- Refresh task state: `{task.get('state', '')}`",
        f"- Refresh last status: `{task.get('last_status', '')}`",
        f"- Verification method: `{verification.get('method', '')}`",
        f"- Stale path records: `{totals.get('stale_records', 0)}`",
        f"- STRM records: `{totals.get('strm_records', 0)}`",
        f"- STRM episode count: `{strm.get('episode_count', 0)}`",
        f"- STRM episode range: `{strm.get('episode_min', '')}-{strm.get('episode_max', '')}`",
        f"- STRM missing: `{strm.get('missing_in_range', [])}`",
        "- Safety: Emby refresh and readonly verification only; no files or Emby database rows are deleted.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)

    stale = verification.get("stale_paths")
    if isinstance(stale, list) and stale:
        lines.extend(["", "## Stale Paths", "", "| Prefix | Records | Sample |", "| --- | ---: | --- |"])
        for item in stale:
            if isinstance(item, dict):
                lines.append(f"| {_escape(str(item.get('prefix') or ''))} | {item.get('record_count', 0)} | {_escape(str(item.get('sample_path') or ''))} |")
    strm_paths = verification.get("strm_paths")
    if isinstance(strm_paths, list) and strm_paths:
        lines.extend(["", "## STRM Paths", "", "| Prefix | Records | Episodes | Missing | Sample |", "| --- | ---: | ---: | --- | --- |"])
        for item in strm_paths:
            if isinstance(item, dict):
                lines.append(
                    "| {prefix} | {records} | {episodes} | {missing} | {sample} |".format(
                        prefix=_escape(str(item.get("prefix") or "")),
                        records=item.get("record_count", 0),
                        episodes=item.get("episode_count", 0),
                        missing=_escape(str(item.get("missing_in_range", []))),
                        sample=_escape(str(item.get("sample_path") or "")),
                    )
                )
    return "\n".join(lines)


def fetch_emby_evidence(base_url: str, api_key: str) -> List[EmbyEvidence]:
    client = EmbyClient(base_url, api_key)
    evidence: List[EmbyEvidence] = []
    for item in client.series_items():
        evidence.append(
            EmbyEvidence(
                name=str(item.get("Name") or ""),
                item_id=str(item.get("Id") or ""),
                path=str(item.get("Path") or ""),
                episode_count=int(item.get("RecursiveItemCount") or item.get("ChildCount") or 0),
                matched=False,
            )
        )
    return evidence


def match_emby(series: FileSystemSeries, items: List[EmbyEvidence]) -> Optional[EmbyEvidence]:
    series_path = series.path.rstrip("/")
    best: Optional[EmbyEvidence] = None
    best_score = 0
    for item in items:
        item_path = item.path.rstrip("/")
        score = 0
        if item_path and (series_path == item_path or series_path.startswith(item_path + "/") or item_path.startswith(series_path + "/")):
            score = 100
        elif item.name and item.name.lower() in series.title.lower():
            score = 35
        elif series.title.lower() in item.name.lower():
            score = 30
        if score > best_score:
            best_score = score
            best = item
    if best:
        return EmbyEvidence(
            name=best.name,
            item_id=best.item_id,
            path=best.path,
            episode_count=best.episode_count,
            matched=True,
        )
    return None


def _verify_emby_paths_from_db(
    library_db_path: str,
    title: str,
    stale_path_prefixes: Sequence[str],
    strm_path_prefixes: Sequence[str],
    expected_strm_records: int,
    expected_episode_count: int,
    expected_episode_min: int,
    expected_episode_max: int,
) -> Dict[str, object]:
    db_path = Path(library_db_path)
    if not db_path.exists():
        return {
            "method": "sqlite_library_db",
            "title": title,
            "library_db_path": library_db_path,
            "stale_paths": [],
            "strm_paths": [],
            "strm": _episode_summary([]),
            "totals": {"stale_records": 0, "strm_records": 0},
            "blockers": ["emby_library_db_not_found"],
            "warnings": [],
        }
    connection = sqlite3.connect(_sqlite_readonly_uri(db_path), uri=True)
    connection.row_factory = sqlite3.Row
    try:
        stale_rows = _db_rows_for_prefixes(connection, stale_path_prefixes)
        strm_rows = _db_rows_for_prefixes(connection, strm_path_prefixes)
    finally:
        connection.close()
    report = _build_path_verification(
        method="sqlite_library_db",
        title=title,
        stale_path_prefixes=stale_path_prefixes,
        strm_path_prefixes=strm_path_prefixes,
        stale_rows=stale_rows,
        strm_rows=strm_rows,
        expected_strm_records=expected_strm_records,
        expected_episode_count=expected_episode_count,
        expected_episode_min=expected_episode_min,
        expected_episode_max=expected_episode_max,
    )
    report["library_db_path"] = library_db_path
    return report


def _db_rows_for_prefixes(connection: sqlite3.Connection, prefixes: Sequence[str]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for prefix in _normalize_prefixes(prefixes):
        for row in connection.execute(
            """
            SELECT Id, type, Name, SeriesName, Path, IndexNumber, ParentIndexNumber
            FROM MediaItems
            WHERE Path LIKE ?
            ORDER BY ParentIndexNumber, IndexNumber, Path
            """,
            (prefix + "%",),
        ):
            rows.append(
                {
                    "id": row["Id"],
                    "type": row["type"],
                    "name": row["Name"],
                    "series_name": row["SeriesName"],
                    "path": row["Path"],
                    "index_number": row["IndexNumber"],
                    "parent_index_number": row["ParentIndexNumber"],
                }
            )
    return rows


def _rows_for_prefixes(items: Sequence[Dict[str, object]], prefixes: Sequence[str]) -> List[Dict[str, object]]:
    normalized = _normalize_prefixes(prefixes)
    rows: List[Dict[str, object]] = []
    for item in items:
        path = str(item.get("Path") or "")
        if any(path.startswith(prefix) for prefix in normalized):
            rows.append(
                {
                    "id": item.get("Id"),
                    "type": item.get("Type"),
                    "name": item.get("Name"),
                    "series_name": item.get("SeriesName"),
                    "path": path,
                    "index_number": item.get("IndexNumber"),
                    "parent_index_number": item.get("ParentIndexNumber"),
                }
            )
    return rows


def _build_path_verification(
    method: str,
    title: str,
    stale_path_prefixes: Sequence[str],
    strm_path_prefixes: Sequence[str],
    stale_rows: Sequence[Dict[str, object]],
    strm_rows: Sequence[Dict[str, object]],
    expected_strm_records: int,
    expected_episode_count: int,
    expected_episode_min: int,
    expected_episode_max: int,
) -> Dict[str, object]:
    blockers: List[str] = []
    warnings: List[str] = []
    stale_paths = [_prefix_summary(prefix, stale_rows) for prefix in _normalize_prefixes(stale_path_prefixes)]
    strm_paths = [_prefix_summary(prefix, strm_rows) for prefix in _normalize_prefixes(strm_path_prefixes)]
    stale_count = len(stale_rows)
    strm_count = len(strm_rows)
    episodes = _episode_numbers_from_rows(strm_rows)
    strm = _episode_summary(episodes)
    if stale_count:
        blockers.append("emby_stale_path_records_present")
    if strm_path_prefixes and strm_count == 0:
        blockers.append("emby_strm_records_missing")
    if expected_strm_records and strm_count != expected_strm_records:
        blockers.append("emby_strm_record_count_mismatch")
    if expected_episode_count and strm["episode_count"] != expected_episode_count:
        blockers.append("emby_strm_episode_count_mismatch")
    if expected_episode_min and strm["episode_min"] != expected_episode_min:
        blockers.append("emby_strm_episode_min_mismatch")
    if expected_episode_max and strm["episode_max"] != expected_episode_max:
        blockers.append("emby_strm_episode_max_mismatch")
    if strm["missing_in_range"]:
        blockers.append("emby_strm_episode_gap_detected")
    return {
        "method": method,
        "title": title,
        "stale_paths": stale_paths,
        "strm_paths": strm_paths,
        "strm": strm,
        "totals": {"stale_records": stale_count, "strm_records": strm_count},
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
    }


def _prefix_summary(prefix: str, rows: Sequence[Dict[str, object]]) -> Dict[str, object]:
    matched = [row for row in rows if str(row.get("path") or "").startswith(prefix)]
    episodes = _episode_numbers_from_rows(matched)
    summary = _episode_summary(episodes)
    return {
        "prefix": prefix,
        "record_count": len(matched),
        "episode_count": summary["episode_count"],
        "episode_min": summary["episode_min"],
        "episode_max": summary["episode_max"],
        "missing_in_range": summary["missing_in_range"],
        "sample_path": str(matched[0].get("path") or "") if matched else "",
    }


def _episode_numbers_from_rows(rows: Sequence[Dict[str, object]]) -> List[int]:
    episodes = set()
    for row in rows:
        index_number = row.get("index_number")
        if index_number is not None and _looks_like_episode_row(row):
            try:
                episode = int(index_number)
            except (TypeError, ValueError):
                episode = 0
            if episode > 0:
                episodes.add(episode)
                continue
        path = str(row.get("path") or "")
        for episode in episode_signal([Path(path).name]).episodes:
            if episode > 0:
                episodes.add(episode)
    return sorted(episodes)


def _looks_like_episode_row(row: Dict[str, object]) -> bool:
    row_type = row.get("type")
    if row_type == 8 or str(row_type).lower() == "episode":
        return True
    path = str(row.get("path") or "")
    return Path(path).suffix.lower() in {".strm", ".mkv", ".mp4"}


def _episode_summary(episodes: Sequence[int]) -> Dict[str, object]:
    unique = sorted(set(item for item in episodes if item > 0))
    missing = []
    if unique:
        present = set(unique)
        missing = [item for item in range(unique[0], unique[-1] + 1) if item not in present]
    return {
        "episode_count": len(unique),
        "episode_min": min(unique) if unique else None,
        "episode_max": max(unique) if unique else None,
        "missing_in_range": missing,
        "episodes": unique,
    }


def _normalize_prefixes(prefixes: Sequence[str]) -> List[str]:
    return [prefix.rstrip("/") for prefix in prefixes if prefix]


def _summarize_task_wait(task_wait: Dict[str, object]) -> Dict[str, object]:
    final_task = task_wait.get("final_task") if isinstance(task_wait.get("final_task"), dict) else {}
    last = final_task.get("LastExecutionResult") if isinstance(final_task.get("LastExecutionResult"), dict) else {}
    return {
        "key": final_task.get("Key") or task_wait.get("key") or REFRESH_LIBRARY_TASK_KEY,
        "name": final_task.get("Name") or "",
        "state": final_task.get("State") or "",
        "last_status": last.get("Status"),
        "last_start_utc": last.get("StartTimeUtc"),
        "last_end_utc": last.get("EndTimeUtc"),
        "timed_out": bool(task_wait.get("timed_out")),
        "poll_count": len(task_wait.get("polls") or []),
        "polls": task_wait.get("polls") or [],
    }


def _parse_json_object(text: str) -> object:
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {"raw": redact_sensitive_text(text)}


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _url_with_query(base_url: str, query: Dict[str, str]) -> str:
    if not query:
        return base_url
    return f"{base_url}?{urllib.parse.urlencode(query)}"


def _sqlite_readonly_uri(db_path: Path) -> str:
    path = str(db_path.expanduser().resolve(strict=False))
    quoted_path = urllib.parse.quote(path, safe="/:")
    return f"file:{quoted_path}?mode=ro"
