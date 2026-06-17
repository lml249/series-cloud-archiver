from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple


DEFAULT_PROBE_PATHS = ["/", "/api", "/api/v1", "/openapi.json", "/api/v1/openapi.json", "/api/v1/config"]
DEFAULT_INSTANCE_PATHS = [
    "/api/v1/cloud-drive/instances",
    "/api/v1/media-transfer/instances",
    "/api/v1/media-transfer/status",
    "/api/v1/media-transfer/records?page=1&page_size=5",
    "/api/v1/strm/config",
    "/api/v1/strm/generate/status",
    "/api/v1/strm/records/dirs",
    "/api/v1/strm/records/stats",
    "/api/v1/files/115/offline/quota",
    "/api/v1/files/115/offline/tasks",
]
SENSITIVE_METHOD_HINTS = ("delete", "remove", "transfer", "save", "move", "rename", "strm", "download")
SENSITIVE_KEY_RE = re.compile(
    r"(^pc$|^uid$|^fuuid$|token|cookie|password|passwd|secret|authorization|api[_-]?key|access[_-]?key|refresh|pick[_-]?code|pickcode|receive[_-]?code|share[_-]?code|sign|credential|user[_-]?id|user[_-]?name|phone|email|vip)",
    re.IGNORECASE,
)
SENSITIVE_URL_KEY_RE = re.compile(
    r"(^face$|direct|download|redirect|play|stream|thumb|thumbnail|cover|poster|image|pic|photo|avatar|url|uri|link)",
    re.IGNORECASE,
)
OPENAPI_PATHS = ["/openapi.json", "/api/v1/openapi.json"]
MV3_RELEVANT_PATH_HINTS = (
    "cloud-drive",
    "files/115",
    "files/cloud",
    "media-transfer",
    "share-transfer",
    "resource-search",
    "strm",
    "organize",
    "offline",
    "task",
)
MV3_PREVIEW_HINTS = ("search", "preview", "parse", "recommend", "status", "quota", "records", "items", "libraries")
MV3_WRITE_HINTS = (
    "create",
    "execute",
    "receive",
    "generate",
    "offline/add",
    "copy",
    "folder",
    "upload",
    "download",
    "refresh",
    "set-default",
    "regenerate",
    "fill-pickcode",
    "redirect",
    "run",
    "save",
    "share",
    "trigger",
    "logout",
    "unlock",
    "skip",
    "organize",
    "recognize",
    "reorganize",
)
MV3_DESTRUCTIVE_HINTS = ("delete", "remove", "clear", "cleanup", "move", "rename", "cancel", "revert", "reset")


class MV3Client:
    def __init__(self, base_url: str, token: str = "", timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def get(self, path: str) -> Tuple[int, Dict[str, str], bytes]:
        url = self._url(path)
        headers = {"Accept": "application/json"}
        if self.token:
            headers["X-API-Key"] = self.token
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, dict(response.headers.items()), response.read(1024 * 1024)
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read(64 * 1024)

    def post_json(self, path: str, payload: Dict[str, object]) -> Tuple[int, Dict[str, str], bytes]:
        url = self._url(path)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            headers["X-API-Key"] = self.token
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, dict(response.headers.items()), response.read(1024 * 1024)
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read(1024 * 1024)

    def _url(self, path: str) -> str:
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        return url


def add_mv3_offline_task(
    base_url: str,
    token: str,
    magnet_urls: List[str],
    storage: str = "",
    wp_path: str = "",
    wp_path_id: str = "",
    timeout: int = 30,
) -> Dict[str, object]:
    clean_urls = [url.strip() for url in magnet_urls if url.strip()]
    body: Dict[str, object] = {"urls": "\n".join(clean_urls)}
    if storage:
        body["storage"] = storage
    if wp_path:
        body["wp_path"] = wp_path
    if wp_path_id:
        body["wp_path_id"] = wp_path_id

    client = MV3Client(base_url, token, timeout=timeout)
    status, headers, response_body = client.post_json("/api/v1/files/115/offline/add", body)
    text = response_body.decode("utf-8", "replace")
    parsed = _parse_json(text)
    sanitized_response = _sanitize_json(parsed if isinstance(parsed, (dict, list)) else text)
    api_success = _api_success(parsed)
    return {
        "mode": "mv3-offline-add-one-result",
        "endpoint": {"method": "POST", "path": "/api/v1/files/115/offline/add"},
        "ok": 200 <= status < 300 and api_success,
        "http_ok": 200 <= status < 300,
        "api_success": api_success,
        "status": status,
        "response_content_type": _header(headers, "content-type"),
        "response_body_bytes": len(response_body),
        "request": _redacted_offline_add_request(body, len(clean_urls)),
        "response": sanitized_response,
        "safety": "exactly one MV3 offline-add request was sent; magnet URIs are redacted from this report",
    }


def ensure_mv3_115_path(
    base_url: str,
    token: str,
    target_path: str,
    storage: str = "",
    timeout: int = 30,
) -> Dict[str, object]:
    segments = [segment for segment in target_path.strip("/").split("/") if segment]
    if not segments:
        raise ValueError("target_path must contain at least one segment")

    client = MV3Client(base_url, token, timeout=timeout)
    parent_id = "0"
    current_path = ""
    steps = []
    for segment in segments:
        current_path = f"{current_path}/{segment}"
        existing = _find_115_child_folder(client, parent_id, segment, storage)
        if existing:
            parent_id = str(existing.get("cid") or existing.get("file_id") or existing.get("id") or "")
            steps.append(
                {
                    "path": current_path,
                    "name": segment,
                    "action": "reused",
                    "folder_id": parent_id,
                }
            )
            continue
        body: Dict[str, object] = {"parent_id": parent_id, "name": segment}
        if storage:
            body["storage"] = storage
        status, headers, response_body = client.post_json("/api/v1/files/115/folder", body)
        text = response_body.decode("utf-8", "replace")
        parsed = _parse_json(text)
        payload = _unwrap_api_payload(parsed)
        api_success = _api_success(parsed)
        folder_id = _extract_folder_id(payload)
        steps.append(
            {
                "path": current_path,
                "name": segment,
                "action": "created",
                "ok": 200 <= status < 300 and api_success and bool(folder_id),
                "http_ok": 200 <= status < 300,
                "api_success": api_success,
                "status": status,
                "response_content_type": _header(headers, "content-type"),
                "folder_id": folder_id,
                "request": _sanitize_json(body),
                "response": _sanitize_json(payload if isinstance(payload, (dict, list)) else parsed),
            }
        )
        if not (200 <= status < 300 and api_success and folder_id):
            break
        parent_id = folder_id
    ok = bool(steps) and len(steps) == len(segments) and all(step.get("action") == "reused" or step.get("ok") for step in steps)
    return {
        "mode": "mv3-ensure-115-path-result",
        "endpoint": {"method": "POST", "path": "/api/v1/files/115/folder"},
        "ok": ok,
        "target_path": "/" + "/".join(segments),
        "storage": storage,
        "final_folder_id": parent_id if ok else "",
        "steps": steps,
        "safety": "creates missing folders only for the approved target path; no files, torrents, STRM records, or existing folders are deleted or moved",
    }


def check_mv3_offline_task(
    base_url: str,
    token: str,
    info_hash: str,
    target_folder_id: str = "",
    target_path: str = "",
    storage: str = "",
    timeout: int = 30,
) -> Dict[str, object]:
    client = MV3Client(base_url, token, timeout=timeout)
    query = urllib.parse.urlencode({"storage": storage}) if storage else ""
    tasks_path = "/api/v1/files/115/offline/tasks" + (f"?{query}" if query else "")
    task_status, task_headers, task_body = client.get(tasks_path)
    task_payload = _unwrap_api_payload(_parse_json(task_body.decode("utf-8", "replace")))
    task = _find_offline_task(task_payload, info_hash)
    folder = _read_115_folder(client, target_folder_id, storage) if target_folder_id else {}
    path_info = _read_115_info(client, target_path, storage) if target_path else {}
    folder_count = int(folder.get("count") or 0) if isinstance(folder, dict) else 0
    task_done = bool(task) and int(task.get("percentDone") or 0) >= 100 and str(task.get("status_text") or "") == "下载成功"
    if bool(task) and int(task.get("status") or 0) == 2:
        task_done = True
    ready_for_strm = task_done and folder_count > 0
    return {
        "mode": "readonly-mv3-offline-status-one",
        "ok": 200 <= task_status < 300 and bool(task),
        "ready_for_strm": ready_for_strm,
        "info_hash": info_hash,
        "target_folder_id": target_folder_id,
        "target_path": target_path,
        "storage": storage,
        "task_found": bool(task),
        "task": _offline_task_summary(task) if task else {},
        "target_folder": {
            "found": bool(folder),
            "file_count": folder_count,
            "sample_names": _folder_sample_names(folder),
        },
        "target_path_info": {
            "found": bool(path_info),
            "file_id": str(path_info.get("file_id") or "") if isinstance(path_info, dict) else "",
            "file_name": str(path_info.get("file_name") or "") if isinstance(path_info, dict) else "",
        },
        "http": {
            "tasks_status": task_status,
            "tasks_content_type": _header(task_headers, "content-type"),
        },
        "safety": "readonly status check only; no offline task, STRM generation, file operation, qBittorrent action, hlink deletion, or filesystem deletion is performed",
    }


def browse_mv3_cloud_folder(
    base_url: str,
    token: str,
    folder_id: str = "",
    path: str = "",
    storage: str = "115-default",
    limit: int = 1150,
    timeout: int = 60,
) -> Dict[str, object]:
    client = MV3Client(base_url, token, timeout=timeout)
    warnings: List[str] = []
    normalized_path = _normalize_cloud_path(path) if path else ""
    folder_id = str(folder_id or "")
    if not folder_id and not normalized_path:
        warnings.append("folder_id_or_path_required")

    info: Dict[str, object] = {}
    info_status = 0
    info_content_type = ""
    if normalized_path:
        info, info_status, info_content_type = _read_cloud_info_status(client, "", normalized_path, storage)
        if info and not folder_id:
            folder_id = _extract_folder_id(info)
        if not info:
            warnings.append("path_info_not_found")

    folder_payload: object = {}
    browse_status = 0
    browse_content_type = ""
    if folder_id:
        folder_payload, browse_status, browse_content_type = _read_cloud_folder_status(client, folder_id, storage, limit)
    rows = _cloud_rows(folder_payload)
    items = [_cloud_browse_item_summary(row, index) for index, row in enumerate(rows[:200], start=1)]
    episode_numbers = _episode_numbers_from_scan_items([{"name": item.get("name")} for item in items if isinstance(item, dict)])
    if not rows and folder_id:
        warnings.append("no_cloud_items_found")
    if episode_numbers and _missing_episode_numbers(episode_numbers):
        warnings.append("episode_gap_detected")
    if episode_numbers and min(episode_numbers) > 1:
        warnings.append("episode_range_does_not_start_at_1")

    return {
        "mode": "readonly-mv3-cloud-browse",
        "endpoint": {"method": "GET", "path": "/api/v1/files/cloud/browse"},
        "ok": 200 <= browse_status < 300 and bool(rows),
        "http_ok": 200 <= browse_status < 300,
        "browse_status": browse_status,
        "browse_content_type": browse_content_type,
        "info_status": info_status,
        "info_content_type": info_content_type,
        "folder_id": folder_id,
        "path": normalized_path,
        "storage": storage,
        "limit": limit,
        "summary": {
            "item_count": len(rows),
            "folder_count": sum(1 for row in rows if _cloud_item_kind(row) == "folder"),
            "file_count": sum(1 for row in rows if _cloud_item_kind(row) == "file"),
            "episode_count": len(episode_numbers),
            "episode_min": min(episode_numbers) if episode_numbers else None,
            "episode_max": max(episode_numbers) if episode_numbers else None,
            "missing_in_range": _missing_episode_numbers(episode_numbers),
        },
        "folder_info": _cloud_info_summary(info) if info else {},
        "items": items,
        "warnings": warnings,
        "safety": "readonly cloud browse only; no organize transfer, rename, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed",
    }


def render_mv3_cloud_browse_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# MV3 Cloud Browse",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Path: `{report.get('path', '')}`",
        f"- Folder ID: `{report.get('folder_id', '')}`",
        f"- Storage: `{report.get('storage', '')}`",
        f"- Items: `{summary.get('item_count', 0)}`",
        f"- Files: `{summary.get('file_count', 0)}`",
        f"- Folders: `{summary.get('folder_count', 0)}`",
        f"- Episode count: `{summary.get('episode_count', 0)}`",
        f"- Episode range: `{summary.get('episode_min', '')}-{summary.get('episode_max', '')}`",
        f"- Missing in range: `{summary.get('missing_in_range', [])}`",
        "- Safety: cloud browse only; no transfer, rename, STRM generation, or deletion was performed.",
    ]
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    lines.extend(["", "| # | Name | Kind | Episode | Size |", "| ---: | --- | --- | ---: | ---: |"])
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {index} | {name} | {kind} | {episode} | {size} |".format(
                index=item.get("index") or "",
                name=_escape(str(item.get("name") or "")),
                kind=_escape(str(item.get("kind") or "")),
                episode=item.get("episode") or "",
                size=_escape(str(item.get("size") or "")),
            )
        )
    return "\n".join(lines)


def search_mv3_resources(
    base_url: str,
    token: str,
    keyword: str,
    channels: Optional[List[str]] = None,
    timeout: int = 60,
) -> Dict[str, object]:
    body: Dict[str, object] = {"keyword": keyword}
    if channels:
        body["channels"] = channels
    client = MV3Client(base_url, token, timeout=timeout)
    status, headers, response_body = client.post_json("/api/v1/resource-search/search", body)
    text = response_body.decode("utf-8", "replace")
    parsed = _parse_json(text)
    payload = _unwrap_api_payload(parsed)
    api_success = _api_success(parsed)
    items = _resource_search_items(payload)
    return {
        "mode": "readonly-mv3-resource-search",
        "endpoint": {"method": "POST", "path": "/api/v1/resource-search/search"},
        "ok": 200 <= status < 300 and api_success,
        "http_ok": 200 <= status < 300,
        "api_success": api_success,
        "status": status,
        "response_content_type": _header(headers, "content-type"),
        "keyword": keyword,
        "channels": channels or [],
        "result_count": len(items),
        "items": [_resource_search_summary(item, index) for index, item in enumerate(items, start=1)],
        "response_shape": _json_shape(payload),
        "warnings": [] if items else ["no_resource_search_items_found"],
        "safety": "resource search only; no share parsing, receive/transfer, offline task, STRM generation, file operation, qBittorrent action, hlink deletion, or filesystem deletion is performed",
    }


def preview_mv3_share(
    base_url: str,
    token: str,
    keyword: str,
    selection_index: int = 1,
    channels: Optional[List[str]] = None,
    expected_title_contains: str = "",
    timeout: int = 60,
) -> Dict[str, object]:
    client = MV3Client(base_url, token, timeout=timeout)
    resolution = _resolve_mv3_share(client, keyword, selection_index, channels, expected_title_contains)
    report = _public_share_resolution(resolution)
    search = report.get("search") if isinstance(report.get("search"), dict) else {}
    parse_report = report.get("parse") if isinstance(report.get("parse"), dict) else {}
    browse_report = report.get("browse") if isinstance(report.get("browse"), dict) else {}
    selected_summary = report.get("selected") if isinstance(report.get("selected"), dict) else {}
    parse_ok = bool(parse_report.get("ok")) if not parse_report.get("skipped") else False
    browse_ok = bool(browse_report.get("ok")) if not browse_report.get("skipped") else False
    report["mode"] = "readonly-mv3-share-preview"
    report["ok"] = bool(search.get("ok")) and bool(selected_summary) and (parse_ok or browse_ok)
    report["safety"] = "search + share parse/browse preview only; no share receive/transfer, offline task, STRM generation, file operation, qBittorrent action, hlink deletion, or filesystem deletion is performed"
    return report


def receive_mv3_share(
    base_url: str,
    token: str,
    keyword: str,
    selection_index: int = 1,
    browse_index: int = 1,
    channels: Optional[List[str]] = None,
    expected_title_contains: str = "",
    target_path: str = "/未整理",
    storage: str = "115-default",
    timeout: int = 60,
) -> Dict[str, object]:
    client = MV3Client(base_url, token, timeout=timeout)
    resolution = _resolve_mv3_share(client, keyword, selection_index, channels, expected_title_contains)
    report = _public_share_resolution(resolution)
    warnings = list(report.get("warnings", [])) if isinstance(report.get("warnings"), list) else []
    raw = resolution.get("_raw") if isinstance(resolution.get("_raw"), dict) else {}
    browse_items = raw.get("browse_items") if isinstance(raw.get("browse_items"), list) else []
    browse_selection = browse_items[browse_index - 1] if 0 < browse_index <= len(browse_items) else {}
    if not browse_selection:
        warnings.append("browse_index_not_found")

    normalized_target_path = _normalize_cloud_path(target_path)
    if not normalized_target_path:
        warnings.append("target_path_required")
    file_id = _share_item_file_id(browse_selection) if isinstance(browse_selection, dict) else ""
    if not file_id:
        warnings.append("browse_selection_file_id_not_found")

    share_code = str(raw.get("share_code") or "")
    receive_code = str(raw.get("receive_code") or "")
    if not share_code:
        warnings.append("share_code_not_available_for_receive")

    receive_report: Dict[str, object] = {"skipped": True}
    if browse_selection and normalized_target_path and file_id and share_code:
        receive_body: Dict[str, object] = {
            "share_code": share_code,
            "file_ids": [file_id],
            "target_path": normalized_target_path,
        }
        if receive_code:
            receive_body["receive_code"] = receive_code
        if storage:
            receive_body["storage"] = storage
        receive_status, receive_headers, receive_response_body = client.post_json("/api/v1/share-transfer/receive", receive_body)
        receive_parsed = _parse_json(receive_response_body.decode("utf-8", "replace"))
        receive_payload = _unwrap_api_payload(receive_parsed)
        receive_api_success = _api_success(receive_parsed)
        receive_report = _mv3_api_call_summary(
            "POST",
            "/api/v1/share-transfer/receive",
            receive_status,
            receive_headers,
            receive_body,
            receive_payload,
            receive_api_success,
            receive_response_body,
        )

    report["mode"] = "mv3-share-receive-one-result"
    report["ok"] = bool(receive_report.get("ok"))
    report["browse_index"] = browse_index
    report["browse_selection"] = _share_browse_item_summary(browse_selection, browse_index) if isinstance(browse_selection, dict) and browse_selection else {}
    report["target_path"] = normalized_target_path
    report["storage"] = storage
    report["receive"] = receive_report
    report["warnings"] = warnings
    report["safety"] = "exactly one approved MV3 share receive request may be sent; no organize/recognize/transfer, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed"
    return report


def scan_mv3_organize_source(
    base_url: str,
    token: str,
    source_path: str,
    source_file_id: str = "",
    storage: str = "115-default",
    is_cloud_source: bool = True,
    is_dir: bool = True,
    timeout: int = 120,
) -> Dict[str, object]:
    body: Dict[str, object] = {
        "sources": [
            {
                "source_path": source_path,
                "source_file_id": source_file_id,
                "is_cloud_source": is_cloud_source,
                "is_dir": is_dir,
            }
        ],
        "exclude_extensions": [],
        "max_size_bytes": 0,
    }
    client = MV3Client(base_url, token, timeout=timeout)
    status, headers, response_body = client.post_json("/api/v1/organize/scan-source", body)
    parsed = _parse_json(response_body.decode("utf-8", "replace"))
    payload = _unwrap_api_payload(parsed)
    api_success = _api_success(parsed)
    rows = _organize_scan_items(payload)
    summary = payload.get("summary") if isinstance(payload, dict) and isinstance(payload.get("summary"), dict) else {}
    episode_numbers = _episode_numbers_from_scan_items(rows)
    return {
        "mode": "readonly-mv3-organize-scan-source",
        "endpoint": {"method": "POST", "path": "/api/v1/organize/scan-source"},
        "ok": 200 <= status < 300 and api_success,
        "http_ok": 200 <= status < 300,
        "api_success": api_success,
        "status": status,
        "response_content_type": _header(headers, "content-type"),
        "source_path": source_path,
        "source_file_id": source_file_id,
        "storage": storage,
        "is_cloud_source": is_cloud_source,
        "is_dir": is_dir,
        "summary": {
            "total": int(summary.get("total") or len(rows)),
            "candidate": int(summary.get("candidate") or sum(1 for row in rows if not str(row.get("skip_reason") or ""))),
            "skip_ext": int(summary.get("skip_ext") or 0),
            "skip_size": int(summary.get("skip_size") or 0),
            "skip_other": int(summary.get("skip_other") or 0),
            "in_library": int(summary.get("in_library") or sum(1 for row in rows if bool(row.get("in_library")))),
            "episode_count": len(episode_numbers),
            "episode_min": min(episode_numbers) if episode_numbers else None,
            "episode_max": max(episode_numbers) if episode_numbers else None,
            "missing_in_range": _missing_episode_numbers(episode_numbers),
        },
        "items": [_organize_scan_item_summary(row, index) for index, row in enumerate(rows[:100], start=1)],
        "warnings": _organize_scan_warnings(rows, episode_numbers),
        "safety": "organize scan-source only; MV3 documents this endpoint as scan/filter preview that does not recognize media or write to disk; no organize transfer, rename, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed",
    }


def render_mv3_organize_scan_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# MV3 Organize Scan Source",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Source path: `{report.get('source_path', '')}`",
        f"- Total: `{summary.get('total', 0)}`",
        f"- Candidate: `{summary.get('candidate', 0)}`",
        f"- In library: `{summary.get('in_library', 0)}`",
        f"- Episode count: `{summary.get('episode_count', 0)}`",
        f"- Episode range: `{summary.get('episode_min', '')}-{summary.get('episode_max', '')}`",
        f"- Missing in range: `{summary.get('missing_in_range', [])}`",
        "- Safety: scan-source only; no transfer, rename, STRM generation, or deletion was performed.",
        "",
        "| # | Name | Episode | Size | Skip reason | In library |",
        "| ---: | --- | ---: | ---: | --- | --- |",
    ]
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {index} | {name} | {episode} | {size} | {skip_reason} | {in_library} |".format(
                index=item.get("index") or "",
                name=_escape(str(item.get("name") or "")),
                episode=item.get("episode") or "",
                size=_escape(str(item.get("size") or "")),
                skip_reason=_escape(str(item.get("skip_reason") or "")),
                in_library=str(bool(item.get("in_library"))),
            )
        )
    return "\n".join(lines)


def render_mv3_share_preview_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    selected = report.get("selected") if isinstance(report.get("selected"), dict) else {}
    search = report.get("search") if isinstance(report.get("search"), dict) else {}
    parse = report.get("parse") if isinstance(report.get("parse"), dict) else {}
    browse = report.get("browse") if isinstance(report.get("browse"), dict) else {}
    lines = [
        "# MV3 Share Preview",
        "",
        f"- Keyword: `{report.get('keyword', '')}`",
        f"- Selected: `{selected.get('title', '')}`",
        f"- Search results: `{search.get('result_count', 0)}`",
        f"- Parse OK: `{bool(parse.get('ok'))}`",
        f"- Browse OK: `{bool(browse.get('ok'))}`",
        f"- Browse items: `{browse.get('item_count', 0)}`",
        "- Safety: preview only; no receive/transfer or STRM generation was performed.",
        "",
        "| # | Name | Kind | Size |",
        "| ---: | --- | --- | ---: |",
    ]
    for item in browse.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {index} | {name} | {kind} | {size} |".format(
                index=item.get("index") or "",
                name=_escape(str(item.get("name") or "")),
                kind=_escape(str(item.get("kind") or "")),
                size=_escape(str(item.get("size") or "")),
            )
        )
    return "\n".join(lines)


def render_mv3_share_receive_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    selected = report.get("selected") if isinstance(report.get("selected"), dict) else {}
    browse_selection = report.get("browse_selection") if isinstance(report.get("browse_selection"), dict) else {}
    receive = report.get("receive") if isinstance(report.get("receive"), dict) else {}
    lines = [
        "# MV3 Share Receive Result",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Selected: `{selected.get('title', '')}`",
        f"- Browse selection: `{browse_selection.get('name', '')}`",
        f"- Browse kind: `{browse_selection.get('kind', '')}`",
        f"- Browse size: `{browse_selection.get('size', '')}`",
        f"- Target path: `{report.get('target_path', '')}`",
        f"- Storage: `{report.get('storage', '')}`",
        f"- Receive OK: `{bool(receive.get('ok'))}`",
        f"- Receive HTTP status: `{receive.get('status', '')}`",
        "- Safety: one approved receive request only; no organize, STRM generation, qB action, hlink deletion, or filesystem deletion was performed.",
    ]
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    return "\n".join(lines)


def render_mv3_resource_search_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        "# MV3 Resource Search",
        "",
        f"- Keyword: `{report.get('keyword', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Result count: `{report.get('result_count', 0)}`",
        "- Safety: search only; no transfer or STRM generation was performed.",
        "",
        "| # | Title | Channel | Size | Type | Share code |",
        "| ---: | --- | --- | ---: | --- | --- |",
    ]
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {index} | {title} | {channel} | {size} | {media_type} | {share_code} |".format(
                index=item.get("index") or "",
                title=_escape(str(item.get("title") or "")),
                channel=_escape(str(item.get("channel") or "")),
                size=_escape(str(item.get("size") or "")),
                media_type=_escape(str(item.get("media_type") or "")),
                share_code=_escape(str(item.get("share_code") or "")),
            )
        )
    return "\n".join(lines)


def render_mv3_offline_status_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    task = report.get("task") if isinstance(report.get("task"), dict) else {}
    folder = report.get("target_folder") if isinstance(report.get("target_folder"), dict) else {}
    lines = [
        "# MV3 Offline Status",
        "",
        f"- Ready for STRM: `{bool(report.get('ready_for_strm'))}`",
        f"- Task found: `{bool(report.get('task_found'))}`",
        f"- Name: `{task.get('name', '')}`",
        f"- Status: `{task.get('status_text', '')}`",
        f"- Percent: `{task.get('percent_done', '')}`",
        f"- Target path: `{report.get('target_path', '')}`",
        f"- Target folder ID: `{report.get('target_folder_id', '')}`",
        f"- Target file count: `{folder.get('file_count', 0)}`",
        "",
        "No write operation was performed.",
    ]
    return "\n".join(lines)


def render_mv3_ensure_path_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        "# MV3 Ensure 115 Path Result",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Storage: `{report.get('storage', '')}`",
        f"- Target path: `{report.get('target_path', '')}`",
        f"- Final folder ID: `{report.get('final_folder_id', '')}`",
        "",
        "## Steps",
        "",
        "| Path | Action | OK | Folder ID |",
        "| --- | --- | --- | --- |",
    ]
    for step in report.get("steps", []):
        if not isinstance(step, dict):
            continue
        lines.append(
            "| {path} | {action} | {ok} | {folder_id} |".format(
                path=_escape(str(step.get("path") or "")),
                action=_escape(str(step.get("action") or "")),
                ok=str(step.get("ok", step.get("action") == "reused")),
                folder_id=_escape(str(step.get("folder_id") or "")),
            )
        )
    return "\n".join(lines)


def render_mv3_offline_add_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    selection = report.get("selection") if isinstance(report.get("selection"), dict) else {}
    request = report.get("request") if isinstance(report.get("request"), dict) else {}
    lines = [
        "# MV3 Offline Add Result",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- HTTP status: `{report.get('status', '')}`",
        f"- Title: `{selection.get('title', '')}`",
        f"- Priority: `{selection.get('priority', '')}`",
        f"- TMDB ID: `{selection.get('tmdbid', '')}`",
        f"- Season: `{selection.get('season', '')}`",
        f"- Storage: `{request.get('storage', '')}`",
        f"- Target path: `{request.get('wp_path', '')}`",
        f"- Magnet count: `{request.get('magnet_count', 0)}`",
        "- Privacy: magnet URIs are not written to this report.",
        "",
        "## Sanitized Response",
        "",
        "```json",
        json.dumps(report.get("response", {}), ensure_ascii=False, indent=2),
        "```",
    ]
    return "\n".join(lines)


def probe_mv3(base_url: str, token: str = "", paths: Optional[List[str]] = None) -> Dict[str, object]:
    if not base_url:
        return {
            "mode": "readonly-mv3-probe",
            "configured": False,
            "reachable": False,
            "base_url_configured": False,
            "token_configured": bool(token),
            "probes": [],
            "warnings": ["mv3_base_url_not_configured"],
            "safety": _safety_text(),
        }

    client = MV3Client(base_url, token)
    probes = []
    warnings: List[str] = []
    for path in paths or DEFAULT_PROBE_PATHS:
        try:
            status, headers, body = client.get(path)
            probes.append(_probe_result(path, status, headers, body))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"probe_failed:{path}:{exc}")
            probes.append({"path": path, "ok": False, "error": str(exc)})

    reachable = any(bool(item.get("ok")) for item in probes)
    openapi = _best_openapi_probe(probes)
    return {
        "mode": "readonly-mv3-probe",
        "configured": True,
        "reachable": reachable,
        "base_url_configured": True,
        "token_configured": bool(token),
        "probes": probes,
        "openapi_summary": _openapi_summary(openapi) if openapi else {},
        "warnings": warnings,
        "safety": _safety_text(),
    }


def render_mv3_probe_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    return _render_markdown(report)


def inspect_mv3_capabilities(base_url: str, token: str = "", include_all: bool = False) -> Dict[str, object]:
    if not base_url:
        return {
            "mode": "readonly-mv3-capabilities",
            "configured": False,
            "reachable": False,
            "base_url_configured": False,
            "token_configured": bool(token),
            "openapi": {},
            "categories": _empty_capability_categories(),
            "warnings": ["mv3_base_url_not_configured"],
            "safety": _capability_safety_text(),
        }

    client = MV3Client(base_url, token)
    warnings: List[str] = []
    openapi_path = ""
    payload: Optional[Dict[str, object]] = None
    for path in OPENAPI_PATHS:
        try:
            status, headers, body = client.get(path)
            probe = _probe_result(path, status, headers, body)
            if isinstance(probe.get("openapi"), dict):
                openapi_path = path
                payload = probe["openapi"]  # type: ignore[assignment]
                break
            warnings.append(f"openapi_probe_unusable:{path}:status_{status}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"openapi_probe_failed:{path}:{exc}")

    if payload is None:
        return {
            "mode": "readonly-mv3-capabilities",
            "configured": True,
            "reachable": False,
            "base_url_configured": True,
            "token_configured": bool(token),
            "openapi": {},
            "categories": _empty_capability_categories(),
            "warnings": warnings or ["openapi_not_found"],
            "safety": _capability_safety_text(),
        }

    categories = _classify_openapi(payload, include_all=include_all)
    paths = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    return {
        "mode": "readonly-mv3-capabilities",
        "configured": True,
        "reachable": True,
        "base_url_configured": True,
        "token_configured": bool(token),
        "openapi": {
            "source_path": openapi_path,
            "title": str(info.get("title") or ""),
            "description": str(info.get("description") or ""),
            "version": str(info.get("version") or ""),
            "path_count": len(paths),
            "method_count": sum(len(value) for value in paths.values() if isinstance(value, dict)),
        },
        "categories": categories,
        "suggested_flow": [
            "先用 GET /api/v1/cloud-drive/instances、GET /api/v1/media-transfer/instances 确认 MV3 已配置的网盘和转存实例。",
            "再用 POST /api/v1/media-transfer/preview 或资源搜索类 POST 做预览；这些接口仍需先单独验证是否完全无副作用。",
            "最后才允许人工审批后的 POST /api/v1/media-transfer/execute 或 STRM 生成接口；默认命令不会调用它们。",
        ],
        "warnings": warnings,
        "safety": _capability_safety_text(),
    }


def render_mv3_capabilities_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    return _render_capabilities_markdown(report)


def inspect_mv3_instances(
    base_url: str,
    token: str = "",
    paths: Optional[List[str]] = None,
    timeout: int = 10,
    retry_failed_once: bool = False,
) -> Dict[str, object]:
    if not base_url:
        return {
            "mode": "readonly-mv3-instance-probe",
            "configured": False,
            "reachable": False,
            "base_url_configured": False,
            "token_configured": bool(token),
            "probes": [],
            "summary": {},
            "warnings": ["mv3_base_url_not_configured"],
            "safety": _instance_safety_text(),
        }

    client = MV3Client(base_url, token, timeout=timeout)
    probes = []
    warnings: List[str] = []
    allow_dynamic_paths = paths is None
    paths_to_probe = list(paths or DEFAULT_INSTANCE_PATHS)
    seen_paths = set()
    index = 0
    while index < len(paths_to_probe):
        path = paths_to_probe[index]
        index += 1
        if path in seen_paths:
            continue
        seen_paths.add(path)
        if not str(path).startswith("/"):
            warnings.append(f"skipped_non_absolute_path:{path}")
            continue
        try:
            status, headers, body = client.get(path)
            probes.append(_instance_probe_result(path, status, headers, body, attempts=1))
            if allow_dynamic_paths and path == "/api/v1/media-transfer/instances" and 200 <= status < 300:
                parsed = _parse_json(body.decode("utf-8", "replace"))
                for dynamic_path in _media_transfer_library_paths(_unwrap_api_payload(parsed)):
                    if dynamic_path not in seen_paths and dynamic_path not in paths_to_probe:
                        paths_to_probe.append(dynamic_path)
        except Exception as exc:  # noqa: BLE001
            if retry_failed_once:
                warnings.append(f"instance_probe_retry:{path}:{exc}")
                try:
                    status, headers, body = client.get(path)
                    probes.append(_instance_probe_result(path, status, headers, body, attempts=2, previous_error=str(exc)))
                    continue
                except Exception as retry_exc:  # noqa: BLE001
                    warnings.append(f"instance_probe_failed:{path}:{retry_exc}")
                    probes.append({"path": path, "ok": False, "error": str(retry_exc), "attempts": 2, "previous_error": str(exc)})
            else:
                warnings.append(f"instance_probe_failed:{path}:{exc}")
                probes.append({"path": path, "ok": False, "error": str(exc), "attempts": 1})

    return {
        "mode": "readonly-mv3-instance-probe",
        "configured": True,
        "reachable": any(bool(item.get("ok")) for item in probes),
        "base_url_configured": True,
        "token_configured": bool(token),
        "probes": probes,
        "summary": _instance_probe_summary(probes),
        "warnings": warnings,
        "timeout": timeout,
        "retry_failed_once": retry_failed_once,
        "safety": _instance_safety_text(),
    }


def render_mv3_instances_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    return _render_instances_markdown(report)


def _probe_result(path: str, status: int, headers: Dict[str, str], body: bytes) -> Dict[str, object]:
    content_type = _header(headers, "content-type")
    text = body.decode("utf-8", "replace")
    parsed = _parse_json(text)
    result: Dict[str, object] = {
        "path": path,
        "ok": 200 <= status < 300,
        "status": status,
        "content_type": content_type,
        "body_bytes_sampled": len(body),
        "json": isinstance(parsed, (dict, list)),
    }
    if isinstance(parsed, dict):
        result["json_keys"] = sorted(str(key) for key in parsed.keys())[:30]
        if "openapi" in parsed or "paths" in parsed:
            result["openapi"] = parsed
    elif isinstance(parsed, list):
        result["json_items"] = len(parsed)
    return result


def _instance_probe_result(
    path: str,
    status: int,
    headers: Dict[str, str],
    body: bytes,
    attempts: int = 1,
    previous_error: str = "",
) -> Dict[str, object]:
    content_type = _header(headers, "content-type")
    text = body.decode("utf-8", "replace")
    parsed = _parse_json(text)
    payload = _unwrap_api_payload(parsed)
    result: Dict[str, object] = {
        "path": path,
        "ok": 200 <= status < 300,
        "status": status,
        "content_type": content_type,
        "body_bytes_sampled": len(body),
        "json": isinstance(parsed, (dict, list)),
        "payload_shape": _json_shape(payload),
        "payload_count": _json_count(payload),
        "attempts": attempts,
    }
    if previous_error:
        result["previous_error"] = previous_error
    if isinstance(parsed, dict):
        result["json_keys"] = sorted(str(key) for key in parsed.keys())[:30]
    elif isinstance(parsed, list):
        result["json_items"] = len(parsed)
    if isinstance(payload, (dict, list)):
        result["sample"] = _sanitize_json(_sample_json(payload))
    return result


def _unwrap_api_payload(parsed: object) -> object:
    if isinstance(parsed, dict) and "data" in parsed and any(key in parsed for key in ("code", "message", "success")):
        return parsed.get("data")
    return parsed


def _json_shape(value: object) -> str:
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if value is None:
        return "null"
    return type(value).__name__


def _json_count(value: object) -> int:
    if isinstance(value, (list, dict)):
        return len(value)
    return 0


def _sample_json(value: object, max_items: int = 10, max_keys: int = 40) -> object:
    if isinstance(value, list):
        return value[:max_items]
    if isinstance(value, dict):
        return {key: value[key] for key in sorted(value.keys(), key=str)[:max_keys]}
    return value


def _sanitize_json(value: object, key: str = "", depth: int = 0) -> object:
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {str(item_key): _sanitize_json(item_value, str(item_key), depth + 1) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_sanitize_json(item, key, depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return _sanitize_string(key, value)
    return value


def _sanitize_string(key: str, value: str) -> str:
    if _is_sensitive_key(key):
        return "[REDACTED]"
    lowered = value.lower()
    if SENSITIVE_URL_KEY_RE.search(key) and (value.startswith("http://") or value.startswith("https://")):
        return "[REDACTED_URL]"
    if "magnet:?" in lowered:
        return "[REDACTED]"
    if any(marker in lowered for marker in ("token=", "cookie=", "pickcode=", "apikey=", "api_key=", "authorization=")):
        return "[REDACTED]"
    if len(value) > 300:
        return value[:300] + "...[TRUNCATED]"
    return value


def _redacted_offline_add_request(body: Dict[str, object], magnet_count: int) -> Dict[str, object]:
    redacted: Dict[str, object] = {}
    for key, value in body.items():
        if key == "urls":
            redacted[key] = "[REDACTED_MAGNET_URIS]"
        else:
            redacted[key] = _sanitize_json(value, key)
    redacted["magnet_count"] = magnet_count
    return redacted


def _api_success(parsed: object) -> bool:
    if not isinstance(parsed, dict):
        return True
    if "success" in parsed:
        return bool(parsed.get("success"))
    if "code" in parsed:
        return parsed.get("code") in (0, "0", "success", "ok")
    return True


def _find_115_child_folder(client: MV3Client, parent_id: str, name: str, storage: str) -> Dict[str, object]:
    query = urllib.parse.urlencode({"cid": parent_id, "limit": 1000, "storage": storage})
    status, _headers, body = client.get(f"/api/v1/files/115/browse?{query}")
    if not (200 <= status < 300):
        return {}
    parsed = _parse_json(body.decode("utf-8", "replace"))
    payload = _unwrap_api_payload(parsed)
    rows = _cloud_rows(payload)
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_name = str(row.get("n") or row.get("name") or "")
        folder_id = str(row.get("cid") or row.get("file_id") or row.get("id") or "")
        if row_name == name and folder_id:
            return row
    return {}


def _extract_folder_id(value: object) -> str:
    if isinstance(value, dict):
        for key in ("cid", "file_id", "id", "folder_id"):
            if value.get(key):
                return str(value.get(key))
        for key in ("data", "folder", "result"):
            nested = _extract_folder_id(value.get(key))
            if nested:
                return nested
    if isinstance(value, list) and value:
        return _extract_folder_id(value[0])
    return ""


def _read_115_folder(client: MV3Client, folder_id: str, storage: str) -> Dict[str, object]:
    payload, _status, _content_type = _read_cloud_folder_status(client, folder_id, storage, 20)
    if isinstance(payload, dict):
        rows = _cloud_rows(payload)
        if "count" not in payload and rows:
            payload = dict(payload)
            payload["count"] = len(rows)
        return payload
    if isinstance(payload, list):
        return {"count": len(payload), "items": payload}
    return {}


def _read_115_info(client: MV3Client, path: str, storage: str) -> Dict[str, object]:
    payload, _status, _content_type = _read_cloud_info_status(client, "", path, storage)
    return payload


def _read_cloud_folder_status(client: MV3Client, folder_id: str, storage: str, limit: int) -> Tuple[object, int, str]:
    query = urllib.parse.urlencode({"cid": folder_id, "limit": max(1, limit), "storage": storage})
    status, headers, body = client.get(f"/api/v1/files/cloud/browse?{query}")
    if not (200 <= status < 300):
        fallback_status, fallback_headers, fallback_body = client.get(f"/api/v1/files/115/browse?{query}")
        fallback_payload = _unwrap_api_payload(_parse_json(fallback_body.decode("utf-8", "replace")))
        return fallback_payload, fallback_status, _header(fallback_headers, "content-type")
    payload = _unwrap_api_payload(_parse_json(body.decode("utf-8", "replace")))
    return payload, status, _header(headers, "content-type")


def _read_cloud_info_status(client: MV3Client, file_id: str, path: str, storage: str) -> Tuple[Dict[str, object], int, str]:
    params: Dict[str, str] = {"storage": storage}
    if file_id:
        params["file_id"] = file_id
    if path:
        params["path"] = path
    query = urllib.parse.urlencode(params)
    status, headers, body = client.get(f"/api/v1/files/cloud/info?{query}")
    if not (200 <= status < 300):
        return {}, status, _header(headers, "content-type")
    payload = _unwrap_api_payload(_parse_json(body.decode("utf-8", "replace")))
    return payload if isinstance(payload, dict) else {}, status, _header(headers, "content-type")


def _cloud_rows(payload: object) -> List[Dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "files", "list", "data", "children", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("data", "result", "payload"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = _cloud_rows(value)
            if nested:
                return nested
    return []


def _cloud_browse_item_summary(item: Dict[str, object], index: int) -> Dict[str, object]:
    name = _first_present(item, ["name", "file_name", "filename", "n", "title"])
    return {
        "index": index,
        "name": name,
        "kind": _cloud_item_kind(item),
        "episode": _episode_number_from_text(name),
        "size": _format_size_value(_first_raw_present(item, ["size", "size_text", "file_size", "file_size_text", "s"])),
        "file_id": _first_present(item, ["cid", "file_id", "id", "fid", "folder_id"]),
        "raw": _sanitize_json(_sample_json(item, max_keys=30)),
    }


def _cloud_item_kind(item: Dict[str, object]) -> str:
    raw_type = str(_first_present(item, ["type", "file_type", "kind", "category"])).lower()
    if raw_type in ("folder", "dir", "directory"):
        return "folder"
    if raw_type in ("file", "video", "subtitle"):
        return "file"
    for key in ("is_dir", "is_folder", "folder", "isdir", "is_directory"):
        value = item.get(key)
        if isinstance(value, bool):
            return "folder" if value else "file"
        if str(value).lower() in ("1", "true", "yes"):
            return "folder"
        if str(value).lower() in ("0", "false", "no"):
            return "file"
    if str(item.get("fid") or ""):
        return "file"
    if str(item.get("cid") or item.get("folder_id") or ""):
        return "folder"
    return raw_type or "unknown"


def _cloud_info_summary(info: Dict[str, object]) -> Dict[str, object]:
    name = _first_present(info, ["name", "file_name", "filename", "n", "title"])
    return {
        "name": name,
        "kind": _cloud_item_kind(info),
        "file_id": _extract_folder_id(info),
        "size": _format_size_value(_first_raw_present(info, ["size", "size_text", "file_size", "file_size_text", "s"])),
        "raw": _sanitize_json(_sample_json(info, max_keys=30)),
    }


def _find_offline_task(payload: object, info_hash: str) -> Dict[str, object]:
    rows = []
    if isinstance(payload, dict) and isinstance(payload.get("tasks"), list):
        rows = payload["tasks"]
    elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
        rows = payload["data"]
    elif isinstance(payload, list):
        rows = payload
    wanted = info_hash.lower()
    for row in rows:
        if isinstance(row, dict) and str(row.get("info_hash") or "").lower() == wanted:
            return row
    return {}


def _offline_task_summary(task: Dict[str, object]) -> Dict[str, object]:
    return {
        "info_hash": str(task.get("info_hash") or ""),
        "name": str(task.get("name") or ""),
        "percent_done": int(task.get("percentDone") or 0),
        "status": int(task.get("status") or 0),
        "status_text": str(task.get("status_text") or ""),
        "waiting_text": str(task.get("waiting_text") or ""),
        "size_bytes": int(task.get("size") or 0),
        "file_id": str(task.get("file_id") or ""),
        "target_folder_id": str(task.get("wp_path_id") or ""),
        "retry_count": int(task.get("retry_count") or 0),
    }


def _folder_sample_names(folder: Dict[str, object]) -> List[str]:
    rows = folder.get("data") if isinstance(folder.get("data"), list) else []
    names = []
    for row in rows[:10]:
        if isinstance(row, dict):
            names.append(str(row.get("n") or row.get("name") or ""))
    return names


def _resource_search_items(payload: object) -> List[Dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "results", "list", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for value in payload.values():
        if isinstance(value, list):
            rows = [item for item in value if isinstance(item, dict)]
            if rows:
                return rows
    return []


def _resource_search_summary(item: Dict[str, object], index: int) -> Dict[str, object]:
    return {
        "index": index,
        "title": _first_present(item, ["title", "name", "filename", "file_name", "resource_name"]),
        "channel": _first_present(item, ["channel", "source", "site", "provider", "platform"]),
        "media_type": _first_present(item, ["media_type", "type", "category"]),
        "size": _first_present(item, ["size", "size_text", "file_size", "file_size_text"]),
        "share_code": _first_present(item, ["share_code", "shareId", "share_id"]),
        "receive_code_available": bool(_first_present(item, ["receive_code", "receiveCode", "password", "pwd"])),
        "raw": _sanitize_json(_sample_json(item, max_keys=30)),
    }


def _mv3_api_call_summary(
    method: str,
    path: str,
    status: int,
    headers: Dict[str, str],
    request_body: Dict[str, object],
    payload: object,
    api_success: bool,
    response_body: bytes,
) -> Dict[str, object]:
    return {
        "endpoint": {"method": method, "path": path},
        "ok": 200 <= status < 300 and api_success,
        "http_ok": 200 <= status < 300,
        "api_success": api_success,
        "status": status,
        "response_content_type": _header(headers, "content-type"),
        "response_body_bytes": len(response_body),
        "request": _sanitize_json(request_body),
        "response_shape": _json_shape(payload),
        "response_count": _json_count(payload),
        "sample": _sanitize_json(_sample_json(payload, max_items=10, max_keys=30)) if isinstance(payload, (dict, list)) else _sanitize_json(payload),
    }


def _mv3_share_browse_summary(
    status: int,
    headers: Dict[str, str],
    request_body: Dict[str, object],
    payload: object,
    api_success: bool,
    response_body: bytes,
) -> Dict[str, object]:
    report = _mv3_api_call_summary(
        "POST",
        "/api/v1/share-transfer/browse",
        status,
        headers,
        request_body,
        payload,
        api_success,
        response_body,
    )
    items = _share_browse_items(payload)
    report["item_count"] = len(items)
    report["folder_count"] = sum(1 for item in items if _share_item_kind(item) == "folder")
    report["file_count"] = sum(1 for item in items if _share_item_kind(item) == "file")
    report["items"] = [_share_browse_item_summary(item, index) for index, item in enumerate(items[:50], start=1)]
    return report


def _resolve_mv3_share(
    client: MV3Client,
    keyword: str,
    selection_index: int,
    channels: Optional[List[str]],
    expected_title_contains: str,
) -> Dict[str, object]:
    search_body: Dict[str, object] = {"keyword": keyword}
    if channels:
        search_body["channels"] = channels
    search_status, search_headers, search_response_body = client.post_json("/api/v1/resource-search/search", search_body)
    search_text = search_response_body.decode("utf-8", "replace")
    search_parsed = _parse_json(search_text)
    search_payload = _unwrap_api_payload(search_parsed)
    search_api_success = _api_success(search_parsed)
    items = _resource_search_items(search_payload)
    warnings: List[str] = []
    selected = items[selection_index - 1] if 0 < selection_index <= len(items) else {}
    if not selected:
        warnings.append("selection_index_not_found")

    selected_summary = _resource_search_summary(selected, selection_index) if selected else {}
    selected_title = str(selected_summary.get("title") or "")
    if expected_title_contains and expected_title_contains not in selected_title:
        warnings.append("expected_title_contains_mismatch")
        selected = {}

    share_code = ""
    receive_code = ""
    parse_report: Dict[str, object] = {"skipped": True}
    browse_report: Dict[str, object] = {"skipped": True}
    browse_payload: object = {}
    if selected:
        share_url = _first_raw_present(selected, ["share_url", "share_link", "url", "link"])
        share_code = _first_raw_present(selected, ["share_code", "shareId", "share_id"])
        receive_code = _first_raw_present(selected, ["receive_code", "receiveCode", "password", "pwd"])
        if not share_url:
            warnings.append("selected_resource_has_no_share_url")
        else:
            parse_body: Dict[str, object] = {"share_url": share_url}
            if receive_code:
                parse_body["receive_code"] = receive_code
            parse_status, parse_headers, parse_response_body = client.post_json("/api/v1/share-transfer/parse", parse_body)
            parse_parsed = _parse_json(parse_response_body.decode("utf-8", "replace"))
            parse_payload = _unwrap_api_payload(parse_parsed)
            parse_api_success = _api_success(parse_parsed)
            parse_report = _mv3_api_call_summary(
                "POST",
                "/api/v1/share-transfer/parse",
                parse_status,
                parse_headers,
                parse_body,
                parse_payload,
                parse_api_success,
                parse_response_body,
            )
            share_code = _find_first_raw_key(parse_payload, ["share_code", "shareCode", "shareId", "share_id"]) or share_code
            receive_code = _find_first_raw_key(parse_payload, ["receive_code", "receiveCode", "password", "pwd"]) or receive_code

        if not share_code:
            warnings.append("share_code_not_available_for_browse")
        else:
            browse_body: Dict[str, object] = {"share_code": share_code}
            if receive_code:
                browse_body["receive_code"] = receive_code
            browse_status, browse_headers, browse_response_body = client.post_json("/api/v1/share-transfer/browse", browse_body)
            browse_parsed = _parse_json(browse_response_body.decode("utf-8", "replace"))
            browse_payload = _unwrap_api_payload(browse_parsed)
            browse_api_success = _api_success(browse_parsed)
            browse_report = _mv3_share_browse_summary(
                browse_status,
                browse_headers,
                browse_body,
                browse_payload,
                browse_api_success,
                browse_response_body,
            )

    return {
        "keyword": keyword,
        "channels": channels or [],
        "selection_index": selection_index,
        "selected": selected_summary,
        "search": {
            "endpoint": {"method": "POST", "path": "/api/v1/resource-search/search"},
            "ok": 200 <= search_status < 300 and search_api_success,
            "http_ok": 200 <= search_status < 300,
            "api_success": search_api_success,
            "status": search_status,
            "response_content_type": _header(search_headers, "content-type"),
            "result_count": len(items),
        },
        "parse": parse_report,
        "browse": browse_report,
        "warnings": warnings,
        "_raw": {
            "share_code": share_code,
            "receive_code": receive_code,
            "browse_items": _share_browse_items(browse_payload),
        },
    }


def _public_share_resolution(resolution: Dict[str, object]) -> Dict[str, object]:
    return {key: value for key, value in resolution.items() if key != "_raw"}


def _organize_scan_items(payload: object) -> List[Dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "files", "data", "list", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _organize_scan_item_summary(item: Dict[str, object], index: int) -> Dict[str, object]:
    name = _first_present(item, ["name", "file_name", "filename", "n", "path"])
    path = _first_present(item, ["path", "source_path"])
    return {
        "index": index,
        "name": name,
        "path": path,
        "episode": _episode_number_from_text(name or path),
        "size": _format_size_value(_first_raw_present(item, ["size", "size_bytes", "file_size", "s"])),
        "is_cloud_source": bool(item.get("is_cloud_source")),
        "source_file_id": _first_present(item, ["source_file_id", "file_id", "fid", "cid"]),
        "skip_reason": _first_present(item, ["skip_reason", "skipReason"]),
        "in_library": bool(item.get("in_library")),
        "raw": _sanitize_json(_sample_json(item, max_keys=30)),
    }


def _episode_numbers_from_scan_items(items: List[Dict[str, object]]) -> List[int]:
    episodes = []
    for item in items:
        name = str(item.get("name") or item.get("path") or "")
        episode = _episode_number_from_text(name)
        if episode is not None:
            episodes.append(episode)
    return sorted(set(episodes))


def _episode_number_from_text(text: str) -> Optional[int]:
    match = re.search(r"[Ss](\d{1,2})[Ee](\d{1,3})", text)
    if match:
        return int(match.group(2))
    match = re.search(r"(?:第\s*)?(\d{1,3})(?:\s*[集话話])", text)
    if match:
        return int(match.group(1))
    return None


def _missing_episode_numbers(episodes: List[int]) -> List[int]:
    if not episodes:
        return []
    found = set(episodes)
    return [episode for episode in range(min(found), max(found) + 1) if episode not in found]


def _organize_scan_warnings(items: List[Dict[str, object]], episodes: List[int]) -> List[str]:
    warnings = []
    if not items:
        warnings.append("no_scan_items_found")
    if episodes and _missing_episode_numbers(episodes):
        warnings.append("episode_gap_detected")
    if episodes and min(episodes) > 1:
        warnings.append("episode_range_does_not_start_at_1")
    if items and all(bool(item.get("in_library")) for item in items):
        warnings.append("all_scan_items_marked_in_library")
    return warnings


def _share_browse_items(payload: object) -> List[Dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "files", "list", "data", "children"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("data", "result", "payload"):
        value = payload.get(key)
        if isinstance(value, dict):
            nested = _share_browse_items(value)
            if nested:
                return nested
    for value in payload.values():
        if isinstance(value, list):
            rows = [item for item in value if isinstance(item, dict)]
            if rows:
                return rows
    return []


def _share_browse_item_summary(item: Dict[str, object], index: int) -> Dict[str, object]:
    return {
        "index": index,
        "name": _first_present(item, ["name", "file_name", "filename", "n", "title"]),
        "kind": _share_item_kind(item),
        "size": _format_size_value(_first_raw_present(item, ["size", "size_text", "file_size", "file_size_text", "s"])),
        "raw": _sanitize_json(_sample_json(item, max_keys=30)),
    }


def _share_item_kind(item: Dict[str, object]) -> str:
    raw_type = str(_first_present(item, ["type", "file_type", "kind", "category"])).lower()
    if raw_type in ("folder", "dir", "directory"):
        return "folder"
    if raw_type in ("file", "video", "subtitle"):
        return "file"
    for key in ("is_dir", "is_folder", "folder", "isdir"):
        value = item.get(key)
        if isinstance(value, bool):
            return "folder" if value else "file"
        if str(value).lower() in ("1", "true", "yes"):
            return "folder"
    if str(item.get("fid") or item.get("file_id") or ""):
        return "file"
    if str(item.get("cid") or item.get("folder_id") or ""):
        return "folder"
    return raw_type or "unknown"


def _share_item_file_id(item: Dict[str, object]) -> str:
    for key in ("file_id", "fid", "id", "cid", "folder_id"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _normalize_cloud_path(path: str) -> str:
    segments = [segment for segment in str(path or "").strip().strip("/").split("/") if segment]
    return "/" + "/".join(segments) if segments else ""


def _first_present(item: Dict[str, object], keys: List[str]) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(_sanitize_json(value, key))
    return ""


def _first_raw_present(item: Dict[str, object], keys: List[str]) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _format_size_value(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.isdigit():
        return text
    size = float(text)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.2f} {unit}"


def _find_first_raw_key(value: object, keys: List[str], depth: int = 0) -> str:
    if depth > 5:
        return ""
    if isinstance(value, dict):
        for key in keys:
            item = value.get(key)
            if item not in (None, ""):
                return str(item)
        for item in value.values():
            found = _find_first_raw_key(item, keys, depth + 1)
            if found:
                return found
    if isinstance(value, list):
        for item in value[:20]:
            found = _find_first_raw_key(item, keys, depth + 1)
            if found:
                return found
    return ""


def _is_sensitive_key(key: str) -> bool:
    return bool(key and (SENSITIVE_KEY_RE.search(key) or SENSITIVE_URL_KEY_RE.search(key)))


def _instance_probe_summary(probes: List[Dict[str, object]]) -> Dict[str, object]:
    counts = {str(probe.get("path")): int(probe.get("payload_count") or 0) for probe in probes if probe.get("path")}
    failed = [str(probe.get("path")) for probe in probes if not probe.get("ok")]
    return {
        "ok_count": sum(1 for probe in probes if probe.get("ok")),
        "failed_count": len(failed),
        "failed_paths": failed,
        "payload_counts": counts,
        "recommended_read_sequence": [
            "GET /api/v1/cloud-drive/instances",
            "GET /api/v1/media-transfer/instances",
            "GET /api/v1/media-transfer/libraries?instance=<media-transfer-instance>",
            "GET /api/v1/strm/config",
            "GET /api/v1/media-transfer/status",
        ],
    }


def _media_transfer_library_paths(payload: object) -> List[str]:
    if not isinstance(payload, list):
        return []
    paths = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip()
        if slug:
            paths.append(f"/api/v1/media-transfer/libraries?instance={urllib.parse.quote(slug, safe='')}")
    return paths


def _openapi_summary(probe: Dict[str, object]) -> Dict[str, object]:
    payload = probe.get("openapi")
    if not isinstance(payload, dict):
        return {}
    paths = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
    methods = []
    sensitive = []
    for path, value in sorted(paths.items()):
        if not isinstance(value, dict):
            continue
        for method in sorted(value.keys()):
            entry = {"method": str(method).upper(), "path": str(path)}
            methods.append(entry)
            lowered = f"{method} {path}".lower()
            if any(hint in lowered for hint in SENSITIVE_METHOD_HINTS):
                sensitive.append(entry)
    return {
        "title": str((payload.get("info") or {}).get("title") or "") if isinstance(payload.get("info"), dict) else "",
        "version": str((payload.get("info") or {}).get("version") or "") if isinstance(payload.get("info"), dict) else "",
        "path_count": len(paths),
        "method_count": len(methods),
        "safe_get_paths_sample": [item for item in methods if item["method"] == "GET"][:20],
        "sensitive_method_hints_sample": sensitive[:20],
    }


def _classify_openapi(payload: Dict[str, object], include_all: bool = False) -> Dict[str, List[Dict[str, object]]]:
    paths = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
    schemas = ((payload.get("components") or {}).get("schemas") or {}) if isinstance(payload.get("components"), dict) else {}
    categories = _empty_capability_categories()
    for path, value in sorted(paths.items()):
        if not isinstance(value, dict):
            continue
        for method, operation in sorted(value.items()):
            if not isinstance(operation, dict):
                continue
            endpoint = _endpoint_summary(str(method).upper(), str(path), operation, schemas if isinstance(schemas, dict) else {})
            if not include_all and not _is_relevant_endpoint(endpoint):
                continue
            category = _endpoint_category(endpoint)
            categories[category].append(endpoint)
    return categories


def _empty_capability_categories() -> Dict[str, List[Dict[str, object]]]:
    return {
        "readonly_get": [],
        "preview_or_search_post": [],
        "transfer_or_write_post": [],
        "destructive_or_cleanup": [],
        "other_relevant": [],
    }


def _endpoint_summary(method: str, path: str, operation: Dict[str, object], schemas: Dict[str, object]) -> Dict[str, object]:
    request = _request_schema_summary(operation, schemas)
    return {
        "method": method,
        "path": path,
        "summary": str(operation.get("summary") or ""),
        "tags": [str(tag) for tag in operation.get("tags", []) if isinstance(operation.get("tags"), list)],
        "parameters": _parameter_summary(operation),
        "request_schema": request,
    }


def _parameter_summary(operation: Dict[str, object]) -> List[Dict[str, object]]:
    output: List[Dict[str, object]] = []
    parameters = operation.get("parameters")
    if not isinstance(parameters, list):
        return output
    for parameter in parameters:
        if not isinstance(parameter, dict):
            continue
        output.append(
            {
                "name": str(parameter.get("name") or ""),
                "in": str(parameter.get("in") or ""),
                "required": bool(parameter.get("required", False)),
                "type": _schema_type(parameter.get("schema")),
            }
        )
    return output


def _request_schema_summary(operation: Dict[str, object], schemas: Dict[str, object]) -> Dict[str, object]:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return {}
    content = body.get("content")
    if not isinstance(content, dict):
        return {}
    for content_type in ("application/json", "multipart/form-data", "application/x-www-form-urlencoded"):
        value = content.get(content_type)
        if isinstance(value, dict):
            schema = value.get("schema")
            return _schema_summary(content_type, schema, schemas)
    for content_type, value in sorted(content.items()):
        if isinstance(value, dict):
            return _schema_summary(str(content_type), value.get("schema"), schemas)
    return {}


def _schema_summary(content_type: str, schema: object, schemas: Dict[str, object]) -> Dict[str, object]:
    ref = _schema_ref(schema)
    resolved = schemas.get(ref, {}) if ref else schema
    summary: Dict[str, object] = {
        "content_type": content_type,
        "ref": ref,
        "type": _schema_type(resolved),
        "required": [],
        "properties": [],
    }
    if isinstance(resolved, dict):
        required = resolved.get("required")
        if isinstance(required, list):
            summary["required"] = [str(item) for item in required]
        properties = resolved.get("properties")
        if isinstance(properties, dict):
            summary["properties"] = [
                {"name": str(name), "type": _schema_type(value)}
                for name, value in sorted(properties.items())
                if isinstance(value, dict)
            ]
    return summary


def _schema_ref(schema: object) -> str:
    if not isinstance(schema, dict):
        return ""
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return ref.rsplit("/", 1)[-1]
    items = schema.get("items")
    if isinstance(items, dict):
        return _schema_ref(items)
    return ""


def _schema_type(schema: object) -> str:
    if not isinstance(schema, dict):
        return ""
    if "$ref" in schema:
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    if "type" in schema:
        schema_type = str(schema.get("type") or "")
        if schema_type == "array" and isinstance(schema.get("items"), dict):
            item_type = _schema_type(schema["items"])
            return f"array[{item_type}]" if item_type else "array"
        return schema_type
    if "anyOf" in schema and isinstance(schema.get("anyOf"), list):
        return " | ".join(part for part in (_schema_type(item) for item in schema["anyOf"]) if part)
    return ""


def _is_relevant_endpoint(endpoint: Dict[str, object]) -> bool:
    text = _endpoint_text(endpoint)
    return any(hint in text for hint in MV3_RELEVANT_PATH_HINTS)


def _endpoint_category(endpoint: Dict[str, object]) -> str:
    method = str(endpoint.get("method") or "").upper()
    text = _endpoint_text(endpoint)
    if method == "GET":
        return "readonly_get"
    if method in {"DELETE", "PUT", "PATCH"} or any(hint in text for hint in MV3_DESTRUCTIVE_HINTS):
        return "destructive_or_cleanup"
    if method == "POST" and any(hint in text for hint in MV3_WRITE_HINTS):
        return "transfer_or_write_post"
    if method == "POST" and any(hint in text for hint in MV3_PREVIEW_HINTS):
        return "preview_or_search_post"
    return "other_relevant"


def _endpoint_text(endpoint: Dict[str, object]) -> str:
    tags = " ".join(endpoint.get("tags", [])) if isinstance(endpoint.get("tags"), list) else ""
    return f"{endpoint.get('method', '')} {endpoint.get('path', '')} {endpoint.get('summary', '')} {tags}".lower()


def _best_openapi_probe(probes: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
    for probe in probes:
        if isinstance(probe.get("openapi"), dict):
            return probe
    return None


def _parse_json(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _header(headers: Dict[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""


def _render_markdown(report: Dict[str, object]) -> str:
    lines = [
        "# Series Cloud Archiver MV3 Probe",
        "",
        f"- Mode: `{report.get('mode', '')}`",
        f"- Configured: `{report.get('configured', False)}`",
        f"- Reachable: `{report.get('reachable', False)}`",
        f"- Token configured: `{report.get('token_configured', False)}`",
        f"- Timeout: `{report.get('timeout', '')}`",
        f"- Retry failed once: `{report.get('retry_failed_once', False)}`",
        "- Safety: readonly GET probe only; no MV3 transfer, STRM generation, save, move, rename, or delete endpoint is called.",
        "",
    ]
    warnings = report.get("warnings", [])
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.extend(["## Probe Results", "", "| Path | OK | Status | Content-Type | JSON | Keys |", "| --- | --- | ---: | --- | --- | --- |"])
    for probe in report.get("probes", []):
        if not isinstance(probe, dict):
            continue
        keys = ", ".join(probe.get("json_keys", [])) if isinstance(probe.get("json_keys"), list) else ""
        lines.append(
            "| {path} | {ok} | {status} | {content_type} | {json_value} | {keys} |".format(
                path=_escape(str(probe.get("path") or "")),
                ok=probe.get("ok", False),
                status=probe.get("status", ""),
                content_type=_escape(str(probe.get("content_type") or "")),
                json_value=probe.get("json", False),
                keys=_escape(keys),
            )
        )

    summary = report.get("openapi_summary")
    if isinstance(summary, dict) and summary:
        lines.extend(["", "## OpenAPI Summary", ""])
        lines.append(f"- Title: `{summary.get('title', '')}`")
        lines.append(f"- Version: `{summary.get('version', '')}`")
        lines.append(f"- Paths: `{summary.get('path_count', 0)}`")
        lines.append(f"- Methods: `{summary.get('method_count', 0)}`")
        lines.append("")
        lines.append("### GET paths sample")
        for item in summary.get("safe_get_paths_sample", []):
            if isinstance(item, dict):
                lines.append(f"- `{item.get('method')} {item.get('path')}`")
        lines.append("")
        lines.append("### Sensitive method hints sample")
        for item in summary.get("sensitive_method_hints_sample", []):
            if isinstance(item, dict):
                lines.append(f"- `{item.get('method')} {item.get('path')}`")

    return "\n".join(lines)


def _render_capabilities_markdown(report: Dict[str, object]) -> str:
    lines = [
        "# Series Cloud Archiver MV3 Capabilities",
        "",
        f"- Mode: `{report.get('mode', '')}`",
        f"- Configured: `{report.get('configured', False)}`",
        f"- Reachable: `{report.get('reachable', False)}`",
        f"- Token configured: `{report.get('token_configured', False)}`",
        "- Safety: readonly OpenAPI GET only; no MV3 transfer, STRM generation, save, move, rename, or delete endpoint is called.",
        "",
    ]
    openapi = report.get("openapi")
    if isinstance(openapi, dict) and openapi:
        lines.extend(
            [
                "## OpenAPI",
                "",
                f"- Source: `{openapi.get('source_path', '')}`",
                f"- Title: `{openapi.get('title', '')}`",
                f"- Version: `{openapi.get('version', '')}`",
                f"- Paths: `{openapi.get('path_count', 0)}`",
                f"- Methods: `{openapi.get('method_count', 0)}`",
                "",
            ]
        )

    warnings = report.get("warnings", [])
    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    categories = report.get("categories")
    if isinstance(categories, dict):
        title_map = {
            "readonly_get": "Readonly GET",
            "preview_or_search_post": "Preview/Search POST",
            "transfer_or_write_post": "Transfer/Write POST",
            "destructive_or_cleanup": "Destructive/Cleanup",
            "other_relevant": "Other Relevant",
        }
        for key in ("readonly_get", "preview_or_search_post", "transfer_or_write_post", "destructive_or_cleanup", "other_relevant"):
            rows = categories.get(key, [])
            if not isinstance(rows, list):
                continue
            lines.extend([f"## {title_map[key]} ({len(rows)})", ""])
            if not rows:
                lines.append("- None")
                lines.append("")
                continue
            lines.extend(["| Method | Path | Summary | Request |", "| --- | --- | --- | --- |"])
            for endpoint in rows:
                if isinstance(endpoint, dict):
                    lines.append(
                        "| {method} | {path} | {summary} | {request} |".format(
                            method=_escape(str(endpoint.get("method") or "")),
                            path=_escape(str(endpoint.get("path") or "")),
                            summary=_escape(str(endpoint.get("summary") or "")),
                            request=_escape(_format_request_schema(endpoint.get("request_schema"))),
                        )
                    )
            lines.append("")

    suggested = report.get("suggested_flow", [])
    if isinstance(suggested, list) and suggested:
        lines.extend(["## Suggested Flow", ""])
        for item in suggested:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _render_instances_markdown(report: Dict[str, object]) -> str:
    lines = [
        "# Series Cloud Archiver MV3 Instance Probe",
        "",
        f"- Mode: `{report.get('mode', '')}`",
        f"- Configured: `{report.get('configured', False)}`",
        f"- Reachable: `{report.get('reachable', False)}`",
        f"- Token configured: `{report.get('token_configured', False)}`",
        "- Safety: readonly GET probe only; no MV3 transfer, STRM generation, save, move, rename, or delete endpoint is called.",
        "- Redaction: token, cookie, password, pickcode, key-like fields, and URL-like fields are redacted in samples.",
        "",
    ]

    summary = report.get("summary")
    if isinstance(summary, dict) and summary:
        lines.extend(["## Summary", ""])
        lines.append(f"- OK endpoints: `{summary.get('ok_count', 0)}`")
        lines.append(f"- Failed endpoints: `{summary.get('failed_count', 0)}`")
        failed = summary.get("failed_paths", [])
        if isinstance(failed, list) and failed:
            lines.append(f"- Failed paths: `{', '.join(str(item) for item in failed)}`")
        lines.append("")

    warnings = report.get("warnings", [])
    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.extend(["## Probe Results", "", "| Path | OK | Status | Shape | Count | Keys |", "| --- | --- | ---: | --- | ---: | --- |"])
    for probe in report.get("probes", []):
        if not isinstance(probe, dict):
            continue
        keys = ", ".join(probe.get("json_keys", [])) if isinstance(probe.get("json_keys"), list) else ""
        lines.append(
            "| {path} | {ok} | {status} | {shape} | {count} | {keys} |".format(
                path=_escape(str(probe.get("path") or "")),
                ok=probe.get("ok", False),
                status=probe.get("status", ""),
                shape=_escape(str(probe.get("payload_shape") or "")),
                count=probe.get("payload_count", 0),
                keys=_escape(keys),
            )
        )

    lines.extend(["", "## Sanitized Samples", ""])
    for probe in report.get("probes", []):
        if not isinstance(probe, dict) or "sample" not in probe:
            continue
        lines.append(f"### `{probe.get('path')}`")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(probe.get("sample"), ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")

    return "\n".join(lines).rstrip()


def _format_request_schema(schema: object) -> str:
    if not isinstance(schema, dict) or not schema:
        return ""
    ref = str(schema.get("ref") or schema.get("type") or "")
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    properties = schema.get("properties") if isinstance(schema.get("properties"), list) else []
    parts = []
    if ref:
        parts.append(ref)
    if required:
        parts.append("required: " + ", ".join(str(item) for item in required))
    elif properties:
        parts.append("fields: " + ", ".join(str(item.get("name")) for item in properties[:8] if isinstance(item, dict)))
    return "; ".join(parts)


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _safety_text() -> str:
    return "readonly GET probe only; no MV3 transfer, STRM generation, save, move, rename, or delete endpoint is called"


def _capability_safety_text() -> str:
    return "readonly OpenAPI GET only; no MV3 transfer, STRM generation, save, move, rename, or delete endpoint is called"


def _instance_safety_text() -> str:
    return "readonly GET probe only; no MV3 transfer, STRM generation, save, move, rename, or delete endpoint is called"
