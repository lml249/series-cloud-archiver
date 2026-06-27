from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .models import FileSystemSeries, MPSubscriptionEvidence
from .redaction import redact_sensitive_text


TV_TYPE = "电视剧"


@dataclass
class MPSubscriptionRecord:
    name: str
    year: str = ""
    media_type: str = ""
    tmdbid: int = 0
    season: int = 0
    total_episode: int = 0
    date: str = ""


@dataclass
class MPTransferHistoryRecord:
    id: int
    title: str = ""
    year: str = ""
    media_type: str = ""
    category: str = ""
    seasons: str = ""
    episodes: str = ""
    src: str = ""
    dest: str = ""
    mode: str = ""
    status: bool = False
    date: str = ""
    downloader: str = ""
    download_hash: str = ""
    tmdbid: int = 0
    imdbid: str = ""
    doubanid: str = ""


class MoviePilotClient:
    def __init__(self, base_url: str, token: str, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _get(self, path: str, query: Optional[Dict[str, object]] = None) -> object:
        query = dict(query or {})
        if self.token:
            query["token"] = self.token
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            text = response.read().decode("utf-8", "replace")
        return json.loads(text) if text else []

    def _delete_json(self, path: str, query: Optional[Dict[str, object]] = None, body: Optional[Dict[str, object]] = None) -> Dict[str, object]:
        query = dict(query or {})
        if self.token:
            query["token"] = self.token
        url = f"{self.base_url}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            url,
            data=json.dumps(body or {}, ensure_ascii=False).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                text = response.read().decode("utf-8", "replace")
                return {
                    "http_status": response.status,
                    "ok": 200 <= response.status < 300,
                    "response": json.loads(text) if text else {},
                }
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            return {
                "http_status": exc.code,
                "ok": False,
                "response": _parse_json_object(text),
            }

    def current_subscriptions(self) -> List[MPSubscriptionRecord]:
        payload = self._get("/api/v1/subscribe/list")
        return [_record_from_payload(item) for item in _as_list(payload)]

    def subscription_history(self, page_size: int = 100) -> List[MPSubscriptionRecord]:
        records: List[MPSubscriptionRecord] = []
        page = 1
        while True:
            payload = self._get(
                f"/api/v1/subscribe/history/{urllib.parse.quote(TV_TYPE)}",
                {"page": page, "count": page_size},
            )
            page_records = [_record_from_payload(item) for item in _as_list(payload)]
            records.extend(page_records)
            if len(page_records) < page_size:
                break
            page += 1
        return records

    def recognize_file(self, path: str) -> object:
        return self._get("/api/v1/media/recognize_file2", {"path": path})

    def transfer_history(
        self,
        title: str,
        page_size: int = 100,
        success_only: bool = True,
    ) -> List[MPTransferHistoryRecord]:
        records: List[MPTransferHistoryRecord] = []
        page = 1
        query: Dict[str, object] = {"title": title, "count": page_size}
        if success_only:
            query["status"] = "true"
        while True:
            payload = self._get("/api/v1/history/transfer", {**query, "page": page})
            page_records = [_transfer_record_from_payload(item) for item in _transfer_history_items(payload)]
            records.extend(page_records)
            if len(page_records) < page_size:
                break
            page += 1
        return records

    def delete_transfer_history(
        self,
        history_id: int,
        deletesrc: bool = True,
        deletedest: bool = True,
    ) -> Dict[str, object]:
        return self._delete_json(
            "/api/v1/history/transfer",
            query={"deletesrc": str(deletesrc).lower(), "deletedest": str(deletedest).lower()},
            body={"id": history_id},
        )


def mp_cleanup_preview_from_transfer_history(
    base_url: str,
    token: str,
    title: str,
    expected_title: str = "",
    expected_tmdbid: int = 0,
    expected_hash_prefix: str = "",
    include_deletedest: bool = True,
    include_deletesrc: bool = True,
    timeout: int = 20,
) -> Dict[str, object]:
    client = MoviePilotClient(base_url, token, timeout=timeout)
    records = client.transfer_history(title)
    return build_mp_cleanup_preview(
        title=title,
        records=records,
        expected_title=expected_title,
        expected_tmdbid=expected_tmdbid,
        expected_hash_prefix=expected_hash_prefix,
        include_deletedest=include_deletedest,
        include_deletesrc=include_deletesrc,
    )


def build_mp_cleanup_preview(
    title: str,
    records: List[MPTransferHistoryRecord],
    expected_title: str = "",
    expected_tmdbid: int = 0,
    expected_hash_prefix: str = "",
    include_deletedest: bool = True,
    include_deletesrc: bool = True,
) -> Dict[str, object]:
    warnings: List[str] = []
    blockers: List[str] = []
    filtered = _filter_transfer_records(
        records,
        expected_title=expected_title,
        expected_tmdbid=expected_tmdbid,
        expected_hash_prefix=expected_hash_prefix,
    )
    if not filtered:
        blockers.append("no_matching_mp_transfer_history")
    if records and not filtered:
        warnings.append("mp_transfer_history_found_but_filtered_out")
    if any(not record.status for record in filtered):
        blockers.append("mp_transfer_history_contains_failed_records")
    if any(record.mode and record.mode != "link" for record in filtered):
        warnings.append("mp_transfer_mode_not_all_link")

    hashes = sorted({record.download_hash for record in filtered if record.download_hash})
    downloaders = sorted({record.downloader for record in filtered if record.downloader})
    source_roots = sorted({_parent_dir(record.src) for record in filtered if record.src})
    destination_roots = sorted({_series_root_from_dest(record.dest) for record in filtered if record.dest})
    episodes = sorted({_episode_number(record.episodes) for record in filtered if _episode_number(record.episodes)})
    duplicate_episodes = _duplicate_episode_numbers(filtered)
    if duplicate_episodes:
        warnings.append("duplicate_episode_records")
    if episodes and _missing_episode_numbers(episodes):
        warnings.append("episode_gap_detected")
    if len(hashes) > 1:
        warnings.append("multiple_download_hashes")
    if len(downloaders) > 1:
        warnings.append("multiple_downloaders")
    if len(source_roots) > 1:
        warnings.append("multiple_source_roots")
    if len(destination_roots) > 1:
        warnings.append("multiple_destination_roots")
    if expected_hash_prefix and not any(item.startswith(expected_hash_prefix.lower()) for item in hashes):
        blockers.append("expected_qb_hash_not_found")
    if expected_tmdbid and any(record.tmdbid and record.tmdbid != expected_tmdbid for record in filtered):
        blockers.append("unexpected_tmdbid_in_mp_history")
    if not include_deletesrc and not include_deletedest:
        blockers.append("no_mp_delete_scope_selected")

    rows = [_cleanup_transfer_row(record) for record in sorted(filtered, key=lambda record: (_episode_number(record.episodes) or 0, record.id))]
    report = {
        "mode": "readonly-mp-cleanup-preview",
        "title": title,
        "expected_title": expected_title,
        "expected_tmdbid": expected_tmdbid,
        "expected_hash_prefix": expected_hash_prefix,
        "ok": bool(filtered) and not blockers,
        "ready_for_manual_cleanup_approval": bool(filtered) and not blockers,
        "summary": {
            "records_found": len(records),
            "records_matched": len(filtered),
            "episode_count": len(episodes),
            "episode_min": min(episodes) if episodes else None,
            "episode_max": max(episodes) if episodes else None,
            "missing_in_range": _missing_episode_numbers(episodes),
            "download_hash_count": len(hashes),
            "downloader_count": len(downloaders),
            "source_root_count": len(source_roots),
            "destination_root_count": len(destination_roots),
        },
        "mp_delete_plan": {
            "endpoint": {"method": "DELETE", "path": "/api/v1/history/transfer"},
            "query": {"deletesrc": include_deletesrc, "deletedest": include_deletedest},
            "record_ids": [record.id for record in filtered],
            "per_record_body": "TransferHistory JSON from MP transfer history",
            "effect": "MP deletes destination media file when deletedest=true, deletes source media file when deletesrc=true, then emits DownloadFileDeleted with the download hash; MP download chain removes the qBittorrent task without files after the source file deletion event.",
        },
        "qb_targets": [
            {
                "hash_prefix": item[:12],
                "downloader": _downloader_for_hash(filtered, item),
                "mp_download_delete_fallback": {
                    "endpoint": {"method": "DELETE", "path": f"/api/v1/download/{item}"},
                    "note": "Fallback only if transfer-history deletion does not remove the downloader task; do not call both paths blindly.",
                },
            }
            for item in hashes
        ],
        "source_roots": source_roots,
        "destination_roots": destination_roots,
        "records": rows,
        "warnings": warnings,
        "blockers": blockers,
        "safety": "readonly preview only; no MoviePilot DELETE request, qBittorrent action, hlink deletion, source deletion, or filesystem deletion is performed",
    }
    return report


def execute_mp_cleanup_from_preview_report(
    base_url: str,
    token: str,
    preview: Dict[str, object],
    expected_title: str,
    expected_tmdbid: int,
    expected_hash_prefix: str,
    expected_record_count: int,
    expected_episode_count: int,
    expected_episode_min: int,
    expected_episode_max: int,
    expected_hash_prefixes: Optional[Iterable[str]] = None,
    expected_episodes: Optional[Iterable[int]] = None,
    include_deletesrc: bool = True,
    include_deletedest: bool = True,
    timeout: int = 20,
    continue_on_error: bool = False,
    allow_multiple_hashes: bool = False,
    allow_multiple_source_roots: bool = False,
) -> Dict[str, object]:
    client = MoviePilotClient(base_url, token, timeout=timeout)
    return execute_mp_cleanup_from_preview(
        client,
        preview,
        expected_title=expected_title,
        expected_tmdbid=expected_tmdbid,
        expected_hash_prefix=expected_hash_prefix,
        expected_hash_prefixes=expected_hash_prefixes,
        expected_record_count=expected_record_count,
        expected_episode_count=expected_episode_count,
        expected_episode_min=expected_episode_min,
        expected_episode_max=expected_episode_max,
        expected_episodes=expected_episodes,
        include_deletesrc=include_deletesrc,
        include_deletedest=include_deletedest,
        continue_on_error=continue_on_error,
        allow_multiple_hashes=allow_multiple_hashes,
        allow_multiple_source_roots=allow_multiple_source_roots,
    )


def execute_mp_cleanup_from_preview(
    client: MoviePilotClient,
    preview: Dict[str, object],
    expected_title: str,
    expected_tmdbid: int,
    expected_hash_prefix: str,
    expected_record_count: int,
    expected_episode_count: int,
    expected_episode_min: int,
    expected_episode_max: int,
    expected_hash_prefixes: Optional[Iterable[str]] = None,
    expected_episodes: Optional[Iterable[int]] = None,
    include_deletesrc: bool = True,
    include_deletedest: bool = True,
    continue_on_error: bool = False,
    allow_multiple_hashes: bool = False,
    allow_multiple_source_roots: bool = False,
) -> Dict[str, object]:
    expected_episode_list = _normalize_expected_episodes(expected_episodes)
    blockers = _mp_cleanup_execution_blockers(
        preview,
        expected_title=expected_title,
        expected_tmdbid=expected_tmdbid,
        expected_hash_prefix=expected_hash_prefix,
        expected_hash_prefixes=expected_hash_prefixes,
        expected_record_count=expected_record_count,
        expected_episode_count=expected_episode_count,
        expected_episode_min=expected_episode_min,
        expected_episode_max=expected_episode_max,
        expected_episodes=expected_episode_list,
        include_deletesrc=include_deletesrc,
        include_deletedest=include_deletedest,
        allow_multiple_hashes=allow_multiple_hashes,
        allow_multiple_source_roots=allow_multiple_source_roots,
    )
    records = preview.get("records") if isinstance(preview.get("records"), list) else []
    normalized_hash_prefixes = _normalize_hash_prefixes(expected_hash_prefixes, expected_hash_prefix)
    result: Dict[str, object] = {
        "mode": "mp-cleanup-execute-result",
        "title": preview.get("title", ""),
        "ok": False,
        "approved": True,
        "endpoint": {"method": "DELETE", "path": "/api/v1/history/transfer"},
        "query": {"deletesrc": include_deletesrc, "deletedest": include_deletedest},
        "expected": {
            "title": expected_title,
            "tmdbid": expected_tmdbid,
            "hash_prefix": expected_hash_prefix.lower(),
            "hash_prefixes": normalized_hash_prefixes,
            "record_count": expected_record_count,
            "episode_count": expected_episode_count,
            "episode_min": expected_episode_min,
            "episode_max": expected_episode_max,
            "episodes": expected_episode_list,
            "allow_multiple_hashes": allow_multiple_hashes,
            "allow_multiple_source_roots": allow_multiple_source_roots,
        },
        "summary": {
            "planned_count": len(records),
            "attempted_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "stopped_on_failure": False,
        },
        "results": [],
        "blockers": blockers,
        "safety": "approved MoviePilot cleanup execution; delete requests are sent only for validated transfer history IDs from the preview report",
    }
    if blockers:
        result["safety"] = "blocked before sending any MoviePilot DELETE request"
        return result

    execution_results = []
    stopped = False
    for item in records:
        if not isinstance(item, dict):
            continue
        history_id = int(item.get("id") or 0)
        if history_id <= 0:
            response = {"id": history_id, "ok": False, "message": "invalid_history_id"}
        else:
            delete_result = client.delete_transfer_history(history_id, deletesrc=include_deletesrc, deletedest=include_deletedest)
            api_response = delete_result.get("response") if isinstance(delete_result.get("response"), dict) else {}
            api_success = bool(api_response.get("success")) if api_response else bool(delete_result.get("ok"))
            response = {
                "id": history_id,
                "episode": item.get("episodes") or "",
                "hash_prefix": item.get("hash_prefix") or "",
                "src": item.get("src") or "",
                "dest": item.get("dest") or "",
                "ok": bool(delete_result.get("ok")) and api_success,
                "http_status": delete_result.get("http_status"),
                "api_success": api_success,
                "message": str(api_response.get("message") or ""),
            }
        execution_results.append(response)
        if not response["ok"] and not continue_on_error:
            stopped = True
            break

    success_count = sum(1 for item in execution_results if isinstance(item, dict) and item.get("ok"))
    failure_count = sum(1 for item in execution_results if isinstance(item, dict) and not item.get("ok"))
    result["ok"] = len(execution_results) == len(records) and failure_count == 0
    result["summary"] = {
        "planned_count": len(records),
        "attempted_count": len(execution_results),
        "success_count": success_count,
        "failure_count": failure_count,
        "stopped_on_failure": stopped,
    }
    result["results"] = execution_results
    return result


def render_mp_cleanup_execute_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    query = report.get("query") if isinstance(report.get("query"), dict) else {}
    lines = [
        "# MoviePilot Cleanup Execute",
        "",
        f"- Title: `{report.get('title', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Approved: `{bool(report.get('approved'))}`",
        f"- Planned: `{summary.get('planned_count', 0)}`",
        f"- Attempted: `{summary.get('attempted_count', 0)}`",
        f"- Success: `{summary.get('success_count', 0)}`",
        f"- Failure: `{summary.get('failure_count', 0)}`",
        f"- Stopped on failure: `{summary.get('stopped_on_failure', False)}`",
        f"- MP endpoint: `DELETE /api/v1/history/transfer?deletesrc={str(query.get('deletesrc')).lower()}&deletedest={str(query.get('deletedest')).lower()}`",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    lines.extend(["", "| # | MP ID | Episode | OK | HTTP | Message |", "| ---: | ---: | --- | --- | ---: | --- |"])
    for index, item in enumerate(report.get("results", []), start=1):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {index} | {id} | {episode} | {ok} | {http_status} | {message} |".format(
                index=index,
                id=item.get("id") or "",
                episode=_escape(str(item.get("episode") or "")),
                ok=item.get("ok"),
                http_status=item.get("http_status") or "",
                message=_escape(str(item.get("message") or "")),
            )
        )
    return "\n".join(lines)


def render_mp_cleanup_preview(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    plan = report.get("mp_delete_plan") if isinstance(report.get("mp_delete_plan"), dict) else {}
    query = plan.get("query") if isinstance(plan.get("query"), dict) else {}
    lines = [
        "# MoviePilot Cleanup Preview",
        "",
        f"- Title: `{report.get('title', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Ready for manual cleanup approval: `{bool(report.get('ready_for_manual_cleanup_approval'))}`",
        f"- Records matched: `{summary.get('records_matched', 0)}` of `{summary.get('records_found', 0)}`",
        f"- Episode count: `{summary.get('episode_count', 0)}`",
        f"- Episode range: `{summary.get('episode_min', '')}-{summary.get('episode_max', '')}`",
        f"- Missing in range: `{summary.get('missing_in_range', [])}`",
        f"- qB hash count: `{summary.get('download_hash_count', 0)}`",
        f"- Source roots: `{report.get('source_roots', [])}`",
        f"- Destination roots: `{report.get('destination_roots', [])}`",
        f"- Planned MP endpoint: `DELETE /api/v1/history/transfer?deletesrc={str(query.get('deletesrc')).lower()}&deletedest={str(query.get('deletedest')).lower()}`",
        "- Safety: readonly preview only; no delete request was sent.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    qb_targets = report.get("qb_targets")
    if isinstance(qb_targets, list) and qb_targets:
        lines.extend(["", "## qB Targets", ""])
        lines.extend(
            f"- `{item.get('hash_prefix', '')}` downloader `{item.get('downloader', '')}`"
            for item in qb_targets
            if isinstance(item, dict)
        )
    lines.extend(["", "| # | MP ID | Episode | Mode | Hash | Source | Destination |", "| ---: | ---: | --- | --- | --- | --- | --- |"])
    for index, item in enumerate(report.get("records", []), start=1):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {index} | {id} | {episode} | {mode} | {hash_prefix} | {src} | {dest} |".format(
                index=index,
                id=item.get("id") or "",
                episode=_escape(str(item.get("episodes") or "")),
                mode=_escape(str(item.get("mode") or "")),
                hash_prefix=_escape(str(item.get("hash_prefix") or "")),
                src=_escape(str(item.get("src") or "")),
                dest=_escape(str(item.get("dest") or "")),
            )
        )
    return "\n".join(lines)


def fetch_mp_subscription_evidence(base_url: str, token: str) -> List[MPSubscriptionEvidence]:
    client = MoviePilotClient(base_url, token)
    return build_mp_subscription_evidence(
        current=client.current_subscriptions(),
        history=client.subscription_history(),
    )


def build_mp_subscription_evidence(
    current: Iterable[MPSubscriptionRecord],
    history: Iterable[MPSubscriptionRecord],
) -> List[MPSubscriptionEvidence]:
    current_keys: Set[Tuple[object, ...]] = set()
    current_name_keys: Set[Tuple[object, ...]] = set()
    for record in current:
        if _is_tv(record):
            current_keys.update(_identity_keys(record))
            current_name_keys.add(_name_season_key(record))

    evidence: List[MPSubscriptionEvidence] = []
    seen: Set[Tuple[object, ...]] = set()
    for record in history:
        if not _is_tv(record):
            continue
        current_found = bool(current_keys.intersection(_identity_keys(record))) or _name_season_key(record) in current_name_keys
        if current_found:
            continue
        dedupe_key = _best_identity_key(record)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        evidence.append(
            MPSubscriptionEvidence(
                name=record.name,
                year=record.year,
                media_type=record.media_type,
                tmdbid=record.tmdbid,
                season=record.season,
                total_episode=record.total_episode,
                history_date=record.date,
                current_subscription_found=False,
                matched=False,
            )
        )
    return evidence


def _transfer_record_from_payload(item: object) -> MPTransferHistoryRecord:
    data = item if isinstance(item, dict) else {}
    return MPTransferHistoryRecord(
        id=int(data.get("id") or 0),
        title=str(data.get("title") or ""),
        year=str(data.get("year") or ""),
        media_type=str(data.get("type") or ""),
        category=str(data.get("category") or ""),
        seasons=str(data.get("seasons") or ""),
        episodes=str(data.get("episodes") or ""),
        src=str(data.get("src") or ""),
        dest=str(data.get("dest") or ""),
        mode=str(data.get("mode") or ""),
        status=bool(data.get("status")),
        date=str(data.get("date") or ""),
        downloader=str(data.get("downloader") or ""),
        download_hash=str(data.get("download_hash") or ""),
        tmdbid=int(data.get("tmdbid") or 0),
        imdbid=str(data.get("imdbid") or ""),
        doubanid=str(data.get("doubanid") or ""),
    )


def _parse_json_object(text: str) -> Dict[str, object]:
    try:
        parsed = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {"raw": redact_sensitive_text(text)}
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def _mp_cleanup_execution_blockers(
    preview: Dict[str, object],
    expected_title: str,
    expected_tmdbid: int,
    expected_hash_prefix: str,
    expected_record_count: int,
    expected_episode_count: int,
    expected_episode_min: int,
    expected_episode_max: int,
    expected_hash_prefixes: Optional[Iterable[str]],
    expected_episodes: Optional[Iterable[int]],
    include_deletesrc: bool,
    include_deletedest: bool,
    allow_multiple_hashes: bool = False,
    allow_multiple_source_roots: bool = False,
) -> List[str]:
    blockers: List[str] = []
    expected_episode_list = _normalize_expected_episodes(expected_episodes)
    expected_episode_set = set(expected_episode_list)
    normalized_hash_prefixes = _normalize_hash_prefixes(expected_hash_prefixes, expected_hash_prefix)
    allowed_warnings = {"episode_gap_detected"} if expected_episode_set else set()
    if allow_multiple_hashes:
        allowed_warnings.add("multiple_download_hashes")
    if allow_multiple_source_roots:
        allowed_warnings.add("multiple_source_roots")
    if preview.get("mode") != "readonly-mp-cleanup-preview":
        blockers.append("preview_mode_not_supported")
    if not preview.get("ready_for_manual_cleanup_approval"):
        blockers.append("preview_not_ready_for_manual_cleanup_approval")
    if preview.get("blockers"):
        blockers.append("preview_has_blockers")
    warnings = preview.get("warnings") if isinstance(preview.get("warnings"), list) else []
    unexpected_warnings = [warning for warning in warnings if warning not in allowed_warnings]
    if unexpected_warnings:
        blockers.append("preview_has_warnings")
    if expected_title and preview.get("title") != expected_title:
        blockers.append("expected_title_mismatch")
    if expected_tmdbid and int(preview.get("expected_tmdbid") or 0) not in {0, expected_tmdbid}:
        blockers.append("expected_tmdbid_mismatch")
    preview_hash_prefixes = _normalize_hash_prefixes(None, str(preview.get("expected_hash_prefix") or ""))
    if normalized_hash_prefixes and preview_hash_prefixes and not _all_hash_prefixes_covered(preview_hash_prefixes, normalized_hash_prefixes):
        blockers.append("expected_hash_prefix_mismatch")
    if not include_deletesrc and not include_deletedest:
        blockers.append("no_mp_delete_scope_selected")

    summary = preview.get("summary") if isinstance(preview.get("summary"), dict) else {}
    records = preview.get("records") if isinstance(preview.get("records"), list) else []
    if int(summary.get("destination_root_count") or 0) > 1:
        blockers.append("destination_root_count_mismatch")
    if expected_record_count and len(records) != expected_record_count:
        blockers.append("record_count_mismatch")
    if expected_record_count and int(summary.get("records_matched") or 0) != expected_record_count:
        blockers.append("summary_record_count_mismatch")
    if expected_episode_count and int(summary.get("episode_count") or 0) != expected_episode_count:
        blockers.append("episode_count_mismatch")
    if expected_episode_min and int(summary.get("episode_min") or 0) != expected_episode_min:
        blockers.append("episode_min_mismatch")
    if expected_episode_max and int(summary.get("episode_max") or 0) != expected_episode_max:
        blockers.append("episode_max_mismatch")
    if summary.get("missing_in_range") and not expected_episode_set:
        blockers.append("preview_episode_gap_detected")
    if expected_episode_set:
        if expected_episode_count and len(expected_episode_set) != expected_episode_count:
            blockers.append("expected_episode_list_count_mismatch")
        if expected_episode_min and min(expected_episode_set) != expected_episode_min:
            blockers.append("expected_episode_list_min_mismatch")
        if expected_episode_max and max(expected_episode_set) != expected_episode_max:
            blockers.append("expected_episode_list_max_mismatch")

    plan = preview.get("mp_delete_plan") if isinstance(preview.get("mp_delete_plan"), dict) else {}
    query = plan.get("query") if isinstance(plan.get("query"), dict) else {}
    if bool(query.get("deletesrc")) != include_deletesrc:
        blockers.append("deletesrc_scope_mismatch")
    if bool(query.get("deletedest")) != include_deletedest:
        blockers.append("deletedest_scope_mismatch")

    ids: Set[int] = set()
    episodes: Set[int] = set()
    record_hash_prefixes: List[str] = []
    for item in records:
        if not isinstance(item, dict):
            blockers.append("invalid_record_shape")
            continue
        history_id = int(item.get("id") or 0)
        if history_id <= 0:
            blockers.append("invalid_history_id")
        if history_id in ids:
            blockers.append("duplicate_history_id")
        ids.add(history_id)
        episode = int(item.get("episode_number") or 0)
        if episode <= 0:
            blockers.append("invalid_episode_number")
        if episode in episodes:
            blockers.append("duplicate_episode_number")
        episodes.add(episode)
        record_hash_prefix = str(item.get("hash_prefix") or "").lower()
        if record_hash_prefix:
            record_hash_prefixes.append(record_hash_prefix)
        if normalized_hash_prefixes and not _hash_matches_any_prefix(record_hash_prefix, normalized_hash_prefixes):
            blockers.append("record_hash_prefix_mismatch")
        if expected_title and str(item.get("title") or "") != expected_title:
            blockers.append("record_title_mismatch")
        if expected_tmdbid and int(item.get("tmdbid") or 0) not in {0, expected_tmdbid}:
            blockers.append("record_tmdbid_mismatch")
        if item.get("status") is not True:
            blockers.append("record_not_successful")
    if expected_episode_set:
        if episodes != expected_episode_set:
            blockers.append("record_episode_list_mismatch")
    elif expected_episode_min and expected_episode_max and episodes:
        expected_episodes = set(range(expected_episode_min, expected_episode_max + 1))
        if episodes != expected_episodes:
            blockers.append("record_episode_range_mismatch")
    if normalized_hash_prefixes and not _all_hash_prefixes_covered(normalized_hash_prefixes, record_hash_prefixes):
        blockers.append("expected_hash_prefix_not_found")
    return sorted(set(blockers))


def _transfer_history_items(payload: object) -> List[object]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("list"), list):
            return list(data["list"])
    return _as_list(payload)


def _filter_transfer_records(
    records: List[MPTransferHistoryRecord],
    expected_title: str = "",
    expected_tmdbid: int = 0,
    expected_hash_prefix: str = "",
) -> List[MPTransferHistoryRecord]:
    expected_hash_prefix = expected_hash_prefix.lower()
    filtered: List[MPTransferHistoryRecord] = []
    for record in records:
        if expected_title and record.title != expected_title:
            continue
        if expected_tmdbid and record.tmdbid and record.tmdbid != expected_tmdbid:
            continue
        if expected_hash_prefix and not record.download_hash.lower().startswith(expected_hash_prefix):
            continue
        filtered.append(record)
    return filtered


def _normalize_hash_prefixes(prefixes: Optional[Iterable[str]], fallback: str = "") -> List[str]:
    values: List[str] = []
    if prefixes is None:
        values = []
    elif isinstance(prefixes, str):
        values = [prefixes]
    else:
        values = [str(item) for item in prefixes]
    if fallback:
        values.append(fallback)

    normalized: List[str] = []
    seen: Set[str] = set()
    for value in values:
        for part in str(value or "").split(","):
            token = part.strip().lower()
            if token and token not in seen:
                normalized.append(token)
                seen.add(token)
    return normalized


def _hash_prefix_match(left: str, right: str) -> bool:
    left = str(left or "").lower()
    right = str(right or "").lower()
    return bool(left and right and (left.startswith(right) or right.startswith(left)))


def _hash_matches_any_prefix(value: str, prefixes: Iterable[str]) -> bool:
    return any(_hash_prefix_match(value, prefix) for prefix in prefixes)


def _all_hash_prefixes_covered(expected: Iterable[str], actual: Iterable[str]) -> bool:
    actual_list = [str(item or "").lower() for item in actual if str(item or "")]
    return all(_hash_matches_any_prefix(prefix, actual_list) for prefix in expected)


def _normalize_expected_episodes(episodes: Optional[Iterable[int]]) -> List[int]:
    if not episodes:
        return []
    return sorted({int(item) for item in episodes if int(item) > 0})


def _cleanup_transfer_row(record: MPTransferHistoryRecord) -> Dict[str, object]:
    return {
        "id": record.id,
        "title": record.title,
        "year": record.year,
        "tmdbid": record.tmdbid,
        "seasons": record.seasons,
        "episodes": record.episodes,
        "episode_number": _episode_number(record.episodes),
        "mode": record.mode,
        "status": record.status,
        "downloader": record.downloader,
        "hash_prefix": record.download_hash[:12],
        "src": record.src,
        "dest": record.dest,
        "date": record.date,
    }


def _episode_number(value: str) -> int:
    match = re.search(r"(?i)E\s*(\d{1,4})", value or "")
    return int(match.group(1)) if match else 0


def _missing_episode_numbers(episodes: List[int]) -> List[int]:
    unique = sorted(set(item for item in episodes if item > 0))
    if not unique:
        return []
    return [item for item in range(unique[0], unique[-1] + 1) if item not in unique]


def _duplicate_episode_numbers(records: List[MPTransferHistoryRecord]) -> List[int]:
    seen: Set[int] = set()
    duplicates: Set[int] = set()
    for record in records:
        episode = _episode_number(record.episodes)
        if not episode:
            continue
        if episode in seen:
            duplicates.add(episode)
        seen.add(episode)
    return sorted(duplicates)


def _parent_dir(path: str) -> str:
    path = path.rstrip("/")
    if "/" not in path:
        return path
    return path.rsplit("/", 1)[0]


def _series_root_from_dest(path: str) -> str:
    marker = "/Season "
    if marker in path:
        return path.split(marker, 1)[0]
    return _parent_dir(path)


def _downloader_for_hash(records: List[MPTransferHistoryRecord], download_hash: str) -> str:
    for record in records:
        if record.download_hash == download_hash:
            return record.downloader
    return ""


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def match_mp_subscription(
    series: FileSystemSeries,
    evidence: List[MPSubscriptionEvidence],
) -> Optional[MPSubscriptionEvidence]:
    series_text = _normalize(series.title)
    series_seasons = _series_seasons(series)
    best: Optional[MPSubscriptionEvidence] = None
    best_score = 0
    for item in evidence:
        if item.season and series_seasons and item.season not in series_seasons:
            continue
        score = 0
        item_name = _normalize(item.name)
        if item_name and item_name in series_text:
            score = 80
        elif item_name and _compact(item_name) in _compact(series_text):
            score = 70
        elif item_name and _word_overlap(item_name, series_text) >= 0.6:
            score = 55
        if score and item.year and item.year in series.title:
            score += 10
        if score and item.season:
            score += 5
        if score > best_score:
            best_score = score
            best = item
    if best and best_score >= 55:
        return MPSubscriptionEvidence(
            name=best.name,
            year=best.year,
            media_type=best.media_type,
            tmdbid=best.tmdbid,
            season=best.season,
            total_episode=best.total_episode,
            history_date=best.history_date,
            current_subscription_found=best.current_subscription_found,
            matched=True,
        )
    return None


def _record_from_payload(item: object) -> MPSubscriptionRecord:
    data = item if isinstance(item, dict) else {}
    return MPSubscriptionRecord(
        name=str(data.get("name") or ""),
        year=str(data.get("year") or ""),
        media_type=str(data.get("type") or ""),
        tmdbid=int(data.get("tmdbid") or 0),
        season=int(data.get("season") or 0),
        total_episode=int(data.get("total_episode") or 0),
        date=str(data.get("date") or data.get("last_update") or ""),
    )


def _as_list(payload: object) -> List[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return list(data["items"])
        if isinstance(payload.get("items"), list):
            return list(payload["items"])
    return []


def _is_tv(record: MPSubscriptionRecord) -> bool:
    return record.media_type == TV_TYPE or record.media_type.lower() in {"tv", "series"}


def _identity_keys(record: MPSubscriptionRecord) -> Set[Tuple[object, ...]]:
    keys: Set[Tuple[object, ...]] = {_name_season_key(record)}
    if record.tmdbid:
        keys.add(("tmdb", record.tmdbid, record.season or 0))
    return keys


def _best_identity_key(record: MPSubscriptionRecord) -> Tuple[object, ...]:
    if record.tmdbid:
        return ("tmdb", record.tmdbid, record.season or 0)
    return _name_season_key(record)


def _name_season_key(record: MPSubscriptionRecord) -> Tuple[object, ...]:
    return ("name", _normalize(record.name), record.year, record.season or 0)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _compact(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.casefold())


def _series_seasons(series: FileSystemSeries) -> Set[int]:
    seasons = set(series.signal.seasons)
    for match in re.finditer(r"(?i)\bS(?P<season>\d{1,2})\b", series.title):
        seasons.add(int(match.group("season")))
    for match in re.finditer(r"第\s*(?P<season>\d{1,2})\s*季", series.title):
        seasons.add(int(match.group("season")))
    return seasons


def _word_overlap(left: str, right: str) -> float:
    left_words = set(re.findall(r"[0-9a-z\u4e00-\u9fff]+", left.casefold()))
    right_words = set(re.findall(r"[0-9a-z\u4e00-\u9fff]+", right.casefold()))
    if not left_words:
        return 0.0
    return len(left_words & right_words) / len(left_words)
