from __future__ import annotations

import json
import hashlib
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


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
MEDIA_EXTENSIONS = {
    ".avi",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".rmvb",
    ".ts",
    ".webm",
    ".wmv",
}
SIDECAR_EXTENSIONS = {
    ".ass",
    ".idx",
    ".srt",
    ".ssa",
    ".sub",
    ".sup",
    ".vtt",
}
METADATA_SIDECAR_EXTENSIONS = {
    ".jpeg",
    ".jpg",
    ".nfo",
    ".png",
    ".webp",
}
DEFAULT_ORGANIZE_EXCLUDE_EXTENSIONS = sorted(METADATA_SIDECAR_EXTENSIONS)


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
    media_items = [item for item in items if isinstance(item, dict) and str(item.get("media_kind") or "video") == "video"]
    subtitle_sidecars = [item for item in items if isinstance(item, dict) and str(item.get("media_kind") or "") == "subtitle_sidecar"]
    metadata_sidecars = [item for item in items if isinstance(item, dict) and str(item.get("media_kind") or "") == "metadata_sidecar"]
    episode_numbers = _episode_numbers_from_scan_items([{"name": item.get("name")} for item in media_items])
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
            "video_file_count": sum(1 for item in items if isinstance(item, dict) and str(item.get("media_kind") or "") == "video"),
            "sidecar_file_count": len(subtitle_sidecars) + len(metadata_sidecars),
            "subtitle_sidecar_file_count": len(subtitle_sidecars),
            "metadata_sidecar_file_count": len(metadata_sidecars),
            "metadata_sidecar_samples": [str(item.get("name") or "") for item in metadata_sidecars[:10]],
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
        f"- Video files: `{summary.get('video_file_count', 0)}`",
        f"- Subtitle sidecars: `{summary.get('subtitle_sidecar_file_count', 0)}`",
        f"- Metadata sidecars: `{summary.get('metadata_sidecar_file_count', 0)}`",
        f"- Episode count: `{summary.get('episode_count', 0)}`",
        f"- Episode range: `{summary.get('episode_min', '')}-{summary.get('episode_max', '')}`",
        f"- Missing in range: `{summary.get('missing_in_range', [])}`",
        "- Safety: cloud browse only; no transfer, rename, STRM generation, or deletion was performed.",
    ]
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    lines.extend(["", "| # | Name | Kind | Media kind | Episode | Size |", "| ---: | --- | --- | --- | ---: | ---: |"])
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {index} | {name} | {kind} | {media_kind} | {episode} | {size} |".format(
                index=item.get("index") or "",
                name=_escape(str(item.get("name") or "")),
                kind=_escape(str(item.get("kind") or "")),
                media_kind=_escape(str(item.get("media_kind") or "")),
                episode=item.get("episode") or "",
                size=_escape(str(item.get("size") or "")),
            )
        )
    return "\n".join(lines)


def verify_mv3_cloud_media_sidecars(
    base_url: str,
    token: str,
    path: str = "",
    folder_id: str = "",
    storage: str = "115-default",
    limit: int = 1150,
    max_depth: int = 4,
    timeout: int = 60,
) -> Dict[str, object]:
    client = MV3Client(base_url, token, timeout=timeout)
    warnings: List[str] = []
    blockers: List[str] = []
    normalized_path = _normalize_cloud_path(path) if path else ""
    root_id = str(folder_id or "")
    info: Dict[str, object] = {}
    info_status = 0
    info_content_type = ""
    if not root_id and normalized_path:
        info, info_status, info_content_type = _read_cloud_info_status(client, "", normalized_path, storage)
        root_id = _extract_folder_id(info)
        if not info:
            blockers.append("cloud_media_path_not_found")
    if not root_id:
        blockers.append("cloud_media_folder_required")

    scan: Dict[str, object] = {
        "visited_folder_count": 0,
        "file_count": 0,
        "video_file_count": 0,
        "subtitle_sidecar_file_count": 0,
        "metadata_sidecar_file_count": 0,
        "other_file_count": 0,
        "metadata_sidecars": [],
        "folders": [],
        "truncated": False,
    }
    if root_id:
        scan = _scan_mv3_cloud_media_sidecars(
            client,
            root_id,
            normalized_path,
            storage,
            limit=max(1, limit),
            max_depth=max(0, max_depth),
        )
        warnings.extend(str(warning) for warning in scan.get("warnings", []) if warning)
        if int(scan.get("metadata_sidecar_file_count") or 0) > 0:
            blockers.append("cloud_media_metadata_sidecar_present")
        if scan.get("truncated"):
            blockers.append("cloud_media_scan_truncated")

    return {
        "mode": "readonly-mv3-cloud-media-sidecar-verify",
        "endpoint": {"method": "GET", "path": "/api/v1/files/cloud/browse"},
        "ok": not blockers,
        "path": normalized_path,
        "folder_id": root_id,
        "storage": storage,
        "limit": limit,
        "max_depth": max_depth,
        "info_status": info_status,
        "info_content_type": info_content_type,
        "folder_info": _cloud_info_summary(info) if info else {},
        "scan": scan,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": "readonly cloud media sidecar verification only; no cloud media move/delete, STRM generation, qBittorrent action, hlink deletion, local filesystem deletion, or scraping is performed",
    }


def cleanup_mv3_cloud_media_sidecars(
    base_url: str,
    token: str,
    path: str = "",
    folder_id: str = "",
    storage: str = "115-default",
    limit: int = 1150,
    max_depth: int = 4,
    timeout: int = 60,
    approve_delete: bool = False,
    expected_delete_count: int = -1,
) -> Dict[str, object]:
    client = MV3Client(base_url, token, timeout=timeout)
    warnings: List[str] = []
    blockers: List[str] = []
    normalized_path = _normalize_cloud_path(path) if path else ""
    root_id = str(folder_id or "")
    info: Dict[str, object] = {}
    info_status = 0
    info_content_type = ""
    if not root_id and normalized_path:
        info, info_status, info_content_type = _read_cloud_info_status(client, "", normalized_path, storage)
        root_id = _extract_folder_id(info)
        if not info:
            blockers.append("cloud_media_path_not_found")
    if not root_id:
        blockers.append("cloud_media_folder_required")

    scan = _empty_cloud_sidecar_scan()
    if root_id:
        scan = _scan_mv3_cloud_media_sidecars(
            client,
            root_id,
            normalized_path,
            storage,
            limit=max(1, limit),
            max_depth=max(0, max_depth),
        )
        warnings.extend(str(warning) for warning in scan.get("warnings", []) if warning)
        if scan.get("truncated"):
            blockers.append("cloud_media_scan_truncated")

    metadata_sidecars = [
        item
        for item in scan.get("metadata_sidecars", [])
        if isinstance(item, dict) and str(item.get("file_id") or "")
    ]
    metadata_count = int(scan.get("metadata_sidecar_file_count") or 0)
    delete_ids = [str(item.get("file_id") or "") for item in metadata_sidecars]
    if metadata_count != len(delete_ids):
        blockers.append("metadata_sidecar_file_ids_incomplete")
    if expected_delete_count >= 0 and metadata_count != expected_delete_count:
        blockers.append("expected_delete_count_mismatch")

    operation: Dict[str, object] = {"skipped": True, "reason": "dry_run"}
    post_scan: Dict[str, object] = {}
    if approve_delete:
        if metadata_count <= 0:
            operation = {"skipped": True, "reason": "no_metadata_sidecars"}
        elif not blockers:
            operation = _mv3_delete_115(client, delete_ids, storage)
            post_scan = _scan_mv3_cloud_media_sidecars(
                client,
                root_id,
                normalized_path,
                storage,
                limit=max(1, limit),
                max_depth=max(0, max_depth),
            )
            if int(post_scan.get("metadata_sidecar_file_count") or 0) > 0:
                blockers.append("post_delete_metadata_sidecar_still_present")
            if post_scan.get("truncated"):
                blockers.append("post_delete_cloud_media_scan_truncated")
            warnings.extend(str(warning) for warning in post_scan.get("warnings", []) if warning)
        else:
            operation = {"skipped": True, "reason": "blocked"}

    ok = not blockers and (not approve_delete or bool(operation.get("ok")) or metadata_count == 0)
    return {
        "mode": "mv3-cloud-media-sidecar-cleanup-result",
        "ok": ok,
        "dry_run": not approve_delete,
        "path": normalized_path,
        "folder_id": root_id,
        "storage": storage,
        "limit": limit,
        "max_depth": max_depth,
        "info_status": info_status,
        "info_content_type": info_content_type,
        "folder_info": _cloud_info_summary(info) if info else {},
        "delete_plan": {
            "metadata_sidecar_count": metadata_count,
            "expected_delete_count": expected_delete_count,
            "file_ids": delete_ids,
            "items": metadata_sidecars,
        },
        "scan": scan,
        "operation": operation,
        "post_scan": post_scan,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": (
            "default dry-run; approved execution deletes only MV3 cloud media metadata sidecars "
            "(.nfo/.jpg/.jpeg/.png/.webp) discovered under the requested cloud media folder. "
            "Video files and subtitle sidecars are never selected. Cloud storage is only for transfer and STRM generation; "
            "scraping must happen against the STRM library side."
        ),
    }


def cleanup_mv3_cloud_duplicate_videos(
    base_url: str,
    token: str,
    season_path: str,
    strm_root: str,
    expected_episode_count: int,
    folder_id: str = "",
    storage: str = "115-default",
    limit: int = 1150,
    timeout: int = 60,
    approve_delete: bool = False,
    expected_delete_count: int = -1,
) -> Dict[str, object]:
    client = MV3Client(base_url, token, timeout=timeout)
    warnings: List[str] = []
    blockers: List[str] = []
    normalized_season_path = _normalize_cloud_path(season_path)
    normalized_strm_root = str(strm_root or "").rstrip("/")
    info: Dict[str, object] = {}
    info_status = 0
    info_content_type = ""
    folder_id = str(folder_id or "")

    if not normalized_season_path:
        blockers.append("season_path_required")
    if not normalized_strm_root:
        blockers.append("strm_root_required")
    if expected_episode_count <= 0:
        blockers.append("expected_episode_count_required")

    if normalized_season_path and not folder_id:
        info, info_status, info_content_type = _read_cloud_info_status(client, "", normalized_season_path, storage)
        folder_id = _extract_folder_id(info)
        if not info or not folder_id:
            blockers.append("cloud_season_path_not_found")
    elif folder_id:
        info, info_status, info_content_type = _read_cloud_info_status(client, folder_id, "", storage)

    folder_summary = _empty_cloud_folder_summary(normalized_season_path, exists=bool(folder_id), status=info_status, content_type=info_content_type)
    if folder_id:
        folder_summary = _cloud_folder_summary_by_id(
            client,
            folder_id,
            normalized_season_path,
            storage,
            limit=max(1, limit),
            info=info,
            info_status=info_status,
            info_content_type=info_content_type,
        )
        if not bool(folder_summary.get("browse_ok")):
            blockers.append("cloud_season_browse_failed")
        if int(folder_summary.get("folder_count") or 0) > 0:
            blockers.append("cloud_season_contains_child_folders")

    media_items = [item for item in folder_summary.get("media_items", []) if isinstance(item, dict)]
    protected_targets = _protected_cloud_file_names_from_strm_root(normalized_strm_root, normalized_season_path)
    protected_names = set(protected_targets.get("names", []))
    strm_files = list(protected_targets.get("strm_files", []))
    if protected_targets.get("warnings"):
        warnings.extend(str(item) for item in protected_targets.get("warnings", []))
    if len(strm_files) != expected_episode_count:
        blockers.append("strm_file_count_mismatch")
    if len(protected_names) != expected_episode_count:
        blockers.append("protected_strm_target_count_mismatch")

    by_episode: Dict[int, List[Dict[str, object]]] = {}
    for item in media_items:
        episode = item.get("episode")
        if isinstance(episode, int) and episode > 0:
            by_episode.setdefault(episode, []).append(item)
    episode_numbers = sorted(by_episode)
    duplicate_episodes = [episode for episode, items in by_episode.items() if len(items) > 1]
    if len(episode_numbers) != expected_episode_count:
        blockers.append("cloud_episode_count_mismatch")
    missing_episodes = _missing_episode_numbers(episode_numbers)
    if missing_episodes:
        blockers.append("cloud_episode_gap_detected")

    delete_items: List[Dict[str, object]] = []
    protected_items: List[Dict[str, object]] = []
    ambiguous_episodes: List[int] = []
    for episode, items in sorted(by_episode.items()):
        protected_for_episode = [item for item in items if str(item.get("name") or "") in protected_names]
        if len(items) == 1:
            protected_items.extend(_public_cloud_duplicate_video_item(item, "single") for item in items)
            continue
        if len(protected_for_episode) != 1:
            ambiguous_episodes.append(episode)
            continue
        protected_item = protected_for_episode[0]
        protected_items.append(_public_cloud_duplicate_video_item(protected_item, "strm_target"))
        for item in items:
            if item is protected_item:
                continue
            delete_items.append(_public_cloud_duplicate_video_item(item, "duplicate_not_referenced_by_strm"))

    if ambiguous_episodes:
        blockers.append("ambiguous_duplicate_episode_protection")
    if any(not str(item.get("file_id") or "") for item in delete_items):
        blockers.append("duplicate_video_file_ids_incomplete")
    if expected_delete_count >= 0 and len(delete_items) != expected_delete_count:
        blockers.append("expected_delete_count_mismatch")

    operation: Dict[str, object] = {"skipped": True, "reason": "dry_run"}
    post_verify: Dict[str, object] = {}
    if approve_delete:
        if not delete_items:
            operation = {"skipped": True, "reason": "no_duplicate_videos"}
        elif not blockers:
            operation = _mv3_delete_115(client, [str(item.get("file_id") or "") for item in delete_items], storage)
            post_folder = _cloud_folder_summary_by_id(client, folder_id, normalized_season_path, storage, limit=max(1, limit))
            post_media_items = [item for item in post_folder.get("media_items", []) if isinstance(item, dict)]
            post_episodes = sorted({item["episode"] for item in post_media_items if isinstance(item.get("episode"), int)})
            post_names = {str(item.get("name") or "") for item in post_media_items}
            post_missing_protected = sorted(name for name in protected_names if name not in post_names)
            post_duplicate_episodes = sorted(
                episode
                for episode in post_episodes
                if sum(1 for item in post_media_items if item.get("episode") == episode) > 1
            )
            post_verify = {
                "video_file_count": len(post_media_items),
                "episode_count": len(post_episodes),
                "episodes": post_episodes,
                "missing_in_range": _missing_episode_numbers(post_episodes),
                "duplicate_episodes": post_duplicate_episodes,
                "missing_protected_strm_targets": post_missing_protected,
                "browse_ok": bool(post_folder.get("browse_ok")),
            }
            if len(post_media_items) != expected_episode_count:
                blockers.append("post_delete_video_count_mismatch")
            if len(post_episodes) != expected_episode_count:
                blockers.append("post_delete_episode_count_mismatch")
            if post_verify["missing_in_range"]:
                blockers.append("post_delete_episode_gap_detected")
            if post_duplicate_episodes:
                blockers.append("post_delete_duplicate_episodes_still_present")
            if post_missing_protected:
                blockers.append("post_delete_missing_protected_strm_targets")
        else:
            operation = {"skipped": True, "reason": "blocked"}

    ok = not blockers and (not approve_delete or bool(operation.get("ok")) or not delete_items)
    return {
        "mode": "mv3-cloud-duplicate-video-cleanup-result",
        "ok": ok,
        "dry_run": not approve_delete,
        "season_path": normalized_season_path,
        "strm_root": normalized_strm_root,
        "folder_id": folder_id,
        "storage": storage,
        "limit": limit,
        "expected_episode_count": expected_episode_count,
        "info_status": info_status,
        "info_content_type": info_content_type,
        "folder_info": _cloud_info_summary(info) if info else {},
        "summary": {
            "video_file_count": len(media_items),
            "episode_count": len(episode_numbers),
            "episodes": episode_numbers,
            "missing_in_range": missing_episodes,
            "duplicate_episodes": duplicate_episodes,
            "protected_strm_target_count": len(protected_names),
            "strm_file_count": len(strm_files),
        },
        "delete_plan": {
            "duplicate_video_count": len(delete_items),
            "expected_delete_count": expected_delete_count,
            "items": delete_items,
        },
        "protected_items": protected_items,
        "protected_strm_targets": protected_targets,
        "operation": operation,
        "post_verify": post_verify,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": (
            "default dry-run; approved execution deletes only duplicate MV3 cloud video files in one season "
            "when every episode still has exactly one STRM-referenced protected video. STRM target files are never selected."
        ),
    }


def render_mv3_cloud_duplicate_video_cleanup_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    plan = report.get("delete_plan") if isinstance(report.get("delete_plan"), dict) else {}
    operation = report.get("operation") if isinstance(report.get("operation"), dict) else {}
    lines = [
        "# MV3 Cloud Duplicate Video Cleanup",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Dry run: `{bool(report.get('dry_run'))}`",
        f"- Season path: `{report.get('season_path', '')}`",
        f"- STRM root: `{report.get('strm_root', '')}`",
        f"- Video files: `{summary.get('video_file_count', 0)}`",
        f"- Episodes: `{summary.get('episode_count', 0)}`",
        f"- Duplicate episodes: `{summary.get('duplicate_episodes', [])}`",
        f"- Duplicate videos planned: `{plan.get('duplicate_video_count', 0)}`",
        f"- Expected delete count: `{plan.get('expected_delete_count', -1)}`",
        f"- Delete submitted: `{bool(operation.get('ok'))}`",
        "- Safety: only duplicate videos not referenced by STRM are selected.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    if items:
        lines.extend(["", "## Planned Duplicate Video Deletes", ""])
        for item in items[:80]:
            if isinstance(item, dict):
                lines.append(f"- `E{int(item.get('episode') or 0):02d}` `{item.get('name', '')}` `{item.get('file_id', '')}`")
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    return "\n".join(lines)


def render_mv3_cloud_media_sidecar_cleanup_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    plan = report.get("delete_plan") if isinstance(report.get("delete_plan"), dict) else {}
    operation = report.get("operation") if isinstance(report.get("operation"), dict) else {}
    lines = [
        "# MV3 Cloud Media Sidecar Cleanup",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Dry run: `{bool(report.get('dry_run'))}`",
        f"- Path: `{report.get('path', '')}`",
        f"- Folder ID: `{report.get('folder_id', '')}`",
        f"- Storage: `{report.get('storage', '')}`",
        f"- Metadata sidecars planned: `{plan.get('metadata_sidecar_count', 0)}`",
        f"- Expected delete count: `{plan.get('expected_delete_count', -1)}`",
        f"- Delete submitted: `{bool(operation.get('ok'))}`",
        "- Safety: only metadata sidecars are selected; videos and subtitles are not selected.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    items = plan.get("items") if isinstance(plan.get("items"), list) else []
    if items:
        lines.extend(["", "## Planned Metadata Sidecar Deletes", ""])
        for item in items[:50]:
            if isinstance(item, dict):
                lines.append(f"- `{item.get('path', '')}`")
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    return "\n".join(lines)


def render_mv3_cloud_media_sidecar_verify_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    scan = report.get("scan") if isinstance(report.get("scan"), dict) else {}
    lines = [
        "# MV3 Cloud Media Sidecar Verify",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Path: `{report.get('path', '')}`",
        f"- Folder ID: `{report.get('folder_id', '')}`",
        f"- Storage: `{report.get('storage', '')}`",
        f"- Folders scanned: `{scan.get('visited_folder_count', 0)}`",
        f"- Video files: `{scan.get('video_file_count', 0)}`",
        f"- Subtitle sidecars: `{scan.get('subtitle_sidecar_file_count', 0)}`",
        f"- Metadata sidecars: `{scan.get('metadata_sidecar_file_count', 0)}`",
        "- Safety: readonly cloud media sidecar verification only; no writes were performed.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    metadata_sidecars = scan.get("metadata_sidecars")
    if isinstance(metadata_sidecars, list) and metadata_sidecars:
        lines.extend(["", "## Metadata Sidecars", ""])
        for item in metadata_sidecars[:20]:
            if isinstance(item, dict):
                lines.append(f"- `{item.get('path', '')}`")
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    return "\n".join(lines)


def repair_mv3_wrong_root(
    base_url: str,
    token: str,
    wrong_root: str,
    correct_root: str,
    strm_root: str,
    storage: str = "115-default",
    title_filter: str = "",
    approve_move: bool = False,
    approve_delete_duplicates: bool = False,
    approve_delete_empty: bool = False,
    limit: int = 1000,
    timeout: int = 120,
) -> Dict[str, object]:
    client = MV3Client(base_url, token, timeout=timeout)
    normalized_wrong_root = _normalize_cloud_path(wrong_root)
    normalized_correct_root = _normalize_cloud_path(correct_root)
    normalized_strm_root = str(strm_root or "").rstrip("/")
    warnings: List[str] = []
    blockers: List[str] = []

    if not normalized_wrong_root:
        blockers.append("wrong_root_required")
    if not normalized_correct_root:
        blockers.append("correct_root_required")
    if normalized_wrong_root == normalized_correct_root:
        blockers.append("wrong_root_must_differ_from_correct_root")
    if not normalized_strm_root:
        warnings.append("strm_root_not_configured")

    wrong_root_folder = _cloud_folder_summary_by_path(client, normalized_wrong_root, storage, limit)
    title_rows = [
        row
        for row in wrong_root_folder.get("rows", [])
        if isinstance(row, dict) and _cloud_item_kind(row) == "folder"
    ]
    if title_filter:
        title_rows = [
            row
            for row in title_rows
            if title_filter in _cloud_name(row)
        ]
    if not wrong_root_folder.get("exists") and normalized_wrong_root:
        warnings.append("wrong_root_not_found")
    if not title_rows and wrong_root_folder.get("exists"):
        warnings.append("wrong_root_has_no_title_folders")

    items: List[Dict[str, object]] = []
    if not blockers:
        for row in title_rows:
            items.append(
                _plan_mv3_wrong_root_title(
                    client,
                    row,
                    normalized_wrong_root,
                    normalized_correct_root,
                    normalized_strm_root,
                    storage,
                    limit,
                    approve_move=approve_move,
                    approve_delete_duplicates=approve_delete_duplicates,
                    approve_delete_empty=approve_delete_empty,
                )
            )

    root_cleanup: Dict[str, object] = {"skipped": True}
    if not blockers and approve_delete_empty and wrong_root_folder.get("exists"):
        refreshed_wrong_root = _cloud_folder_summary_by_path(client, normalized_wrong_root, storage, limit)
        refreshed_rows = [row for row in refreshed_wrong_root.get("rows", []) if isinstance(row, dict)]
        if not refreshed_rows:
            root_id = str(refreshed_wrong_root.get("folder_id") or "")
            if root_id:
                root_cleanup = _mv3_delete_115(client, [root_id], storage)
            else:
                root_cleanup = {"skipped": True, "reason": "wrong_root_folder_id_not_found"}

    verify_wrong_root = _cloud_folder_summary_by_path(client, normalized_wrong_root, storage, limit) if normalized_wrong_root else {}
    report_blockers = list(blockers)
    for item in items:
        item_blockers = item.get("blockers") if isinstance(item.get("blockers"), list) else []
        report_blockers.extend(str(blocker) for blocker in item_blockers)

    write_requested = approve_move or approve_delete_duplicates or approve_delete_empty
    item_ok = all(bool(item.get("ok")) for item in items) if items else not bool(title_rows)
    no_wrong_children_after_write = True
    if write_requested and verify_wrong_root.get("exists"):
        no_wrong_children_after_write = len(verify_wrong_root.get("rows", [])) == 0

    return {
        "mode": "mv3-repair-wrong-root-result",
        "ok": not report_blockers and item_ok and no_wrong_children_after_write,
        "dry_run": not write_requested,
        "write_approvals": {
            "approve_move": approve_move,
            "approve_delete_duplicates": approve_delete_duplicates,
            "approve_delete_empty": approve_delete_empty,
        },
        "wrong_root": normalized_wrong_root,
        "correct_root": normalized_correct_root,
        "strm_root": normalized_strm_root,
        "storage": storage,
        "title_filter": title_filter,
        "wrong_root_found": bool(wrong_root_folder.get("exists")),
        "wrong_root_title_count": len(title_rows),
        "items": items,
        "root_cleanup": root_cleanup,
        "post_verify": {
            "wrong_root_exists": bool(verify_wrong_root.get("exists")),
            "wrong_root_child_count": len(verify_wrong_root.get("rows", [])) if isinstance(verify_wrong_root.get("rows"), list) else 0,
        },
        "warnings": warnings,
        "blockers": sorted(set(report_blockers)),
        "safety": (
            "default dry-run; write requests are allowed only through explicit approve flags. "
            "The command compares wrong cloud root, correct cloud root, and STRM targets before moving or deleting 115 items. "
            "It does not call MV3 organize transfer, STRM generation, qBittorrent, MoviePilot cleanup, or Emby refresh."
        ),
    }


def render_mv3_wrong_root_repair_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        "# MV3 Wrong Root Repair",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Dry run: `{bool(report.get('dry_run'))}`",
        f"- Wrong root: `{report.get('wrong_root', '')}`",
        f"- Correct root: `{report.get('correct_root', '')}`",
        f"- STRM root: `{report.get('strm_root', '')}`",
        f"- Titles found: `{report.get('wrong_root_title_count', 0)}`",
        "- Safety: compares cloud + STRM evidence before any approved move/delete.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    lines.extend(
        [
            "",
            "| Title | Decision | Action | Wrong media | Correct media | STRM wrong targets | OK |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        wrong = item.get("wrong") if isinstance(item.get("wrong"), dict) else {}
        correct = item.get("correct") if isinstance(item.get("correct"), dict) else {}
        strm = item.get("strm") if isinstance(item.get("strm"), dict) else {}
        lines.append(
            "| {title} | {decision} | {action} | {wrong_media} | {correct_media} | {strm_wrong} | {ok} |".format(
                title=_escape(str(item.get("title") or "")),
                decision=_escape(str(item.get("decision") or "")),
                action=_escape(str(item.get("action") or "")),
                wrong_media=wrong.get("media_count", 0),
                correct_media=correct.get("media_count", 0),
                strm_wrong=strm.get("wrong_target_count", 0),
                ok=str(bool(item.get("ok"))),
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
    try:
        status, headers, response_body = client.post_json("/api/v1/resource-search/search", body)
    except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        error_type = "TimeoutError" if isinstance(exc, (TimeoutError, socket.timeout)) else type(exc).__name__
        return {
            "mode": "readonly-mv3-resource-search",
            "endpoint": {"method": "POST", "path": "/api/v1/resource-search/search"},
            "ok": False,
            "http_ok": False,
            "api_success": False,
            "status": 0,
            "response_content_type": "",
            "keyword": keyword,
            "channels": channels or [],
            "result_count": 0,
            "items": [],
            "response_shape": {},
            "error_type": error_type,
            "error": str(exc),
            "warnings": ["mv3_resource_search_request_failed"],
            "safety": "resource search only; no share parsing, receive/transfer, offline task, STRM generation, file operation, qBittorrent action, hlink deletion, or filesystem deletion is performed",
        }
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
    browse_cid: str = "",
    channels: Optional[List[str]] = None,
    expected_title_contains: str = "",
    timeout: int = 60,
) -> Dict[str, object]:
    client = MV3Client(base_url, token, timeout=timeout)
    resolution = _resolve_mv3_share(client, keyword, selection_index, browse_cid, channels, expected_title_contains)
    report = _public_share_resolution(resolution)
    search = report.get("search") if isinstance(report.get("search"), dict) else {}
    parse_report = report.get("parse") if isinstance(report.get("parse"), dict) else {}
    browse_report = report.get("browse") if isinstance(report.get("browse"), dict) else {}
    selected_summary = report.get("selected") if isinstance(report.get("selected"), dict) else {}
    parse_ok = bool(parse_report.get("ok")) if not parse_report.get("skipped") else False
    browse_ok = bool(browse_report.get("ok")) if not browse_report.get("skipped") else False
    report["mode"] = "readonly-mv3-share-preview"
    browse_item_count = int(browse_report.get("item_count") or 0) if isinstance(browse_report.get("item_count"), int) else 0
    report["ok"] = bool(search.get("ok")) and bool(selected_summary) and parse_ok and browse_ok and browse_item_count > 0
    report["safety"] = "search + share parse/browse preview only; no share receive/transfer, offline task, STRM generation, file operation, qBittorrent action, hlink deletion, or filesystem deletion is performed"
    return report


def receive_mv3_share(
    base_url: str,
    token: str,
    keyword: str,
    selection_index: int = 1,
    browse_index: int = 1,
    browse_cid: str = "",
    receive_all_files: bool = False,
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
    channels: Optional[List[str]] = None,
    expected_title_contains: str = "",
    target_path: str = "/未整理",
    storage: str = "115-default",
    timeout: int = 60,
) -> Dict[str, object]:
    client = MV3Client(base_url, token, timeout=timeout)
    resolution = _resolve_mv3_share(client, keyword, selection_index, browse_cid, channels, expected_title_contains)
    report = _public_share_resolution(resolution)
    warnings = list(report.get("warnings", [])) if isinstance(report.get("warnings"), list) else []
    raw = resolution.get("_raw") if isinstance(resolution.get("_raw"), dict) else {}
    browse_items = raw.get("browse_items") if isinstance(raw.get("browse_items"), list) else []
    browse_selection = browse_items[browse_index - 1] if 0 < browse_index <= len(browse_items) else {}
    if not browse_selection and not receive_all_files:
        warnings.append("browse_index_not_found")

    normalized_target_path = _normalize_cloud_path(target_path)
    if not normalized_target_path:
        warnings.append("target_path_required")
    selected_items = _share_receive_items(
        browse_items,
        browse_selection if isinstance(browse_selection, dict) else {},
        receive_all_files,
    )
    excluded_metadata_sidecars = _share_metadata_sidecars_excluded_from_receive(
        browse_items,
        browse_selection if isinstance(browse_selection, dict) else {},
        receive_all_files,
    )
    if excluded_metadata_sidecars:
        warnings.append("metadata_sidecars_excluded_from_receive")
    file_ids = [_share_item_file_id(item) for item in selected_items]
    file_ids = [item for item in file_ids if item]
    if not file_ids:
        warnings.append("browse_selection_file_id_not_found")
    video_items = [item for item in selected_items if _share_item_is_video(item)]
    episode_numbers = sorted(
        {
            episode
            for episode in (_episode_number_from_text(_share_item_name(item)) for item in video_items)
            if episode is not None
        }
    )
    missing_expected = [
        episode
        for episode in range(expected_episode_min, expected_episode_max + 1)
        if episode not in set(episode_numbers)
    ] if expected_episode_min and expected_episode_max else []
    if expected_episode_count and len(episode_numbers) != expected_episode_count:
        warnings.append("episode_count_mismatch")
    if missing_expected:
        warnings.append("episode_range_incomplete")
    if receive_all_files and expected_episode_count and len(video_items) != expected_episode_count:
        warnings.append("video_file_count_mismatch")

    share_code = str(raw.get("share_code") or "")
    receive_code = str(raw.get("receive_code") or "")
    if not share_code:
        warnings.append("share_code_not_available_for_receive")

    receive_report: Dict[str, object] = {"skipped": True}
    blocking_warnings = {
        "browse_index_not_found",
        "target_path_required",
        "browse_selection_file_id_not_found",
        "share_code_not_available_for_receive",
        "episode_count_mismatch",
        "episode_range_incomplete",
        "video_file_count_mismatch",
    }
    if normalized_target_path and file_ids and share_code and not (set(warnings) & blocking_warnings):
        receive_body: Dict[str, object] = {
            "share_code": share_code,
            "file_ids": file_ids,
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
    report["browse_cid"] = browse_cid
    report["receive_all_files"] = receive_all_files
    report["file_id_count"] = len(file_ids)
    report["selected_item_count"] = len(selected_items)
    report["video_file_count"] = len(video_items)
    report["sidecar_file_count"] = sum(1 for item in selected_items if _share_item_is_sidecar(item))
    report["excluded_metadata_sidecar_count"] = len(excluded_metadata_sidecars)
    report["excluded_metadata_sidecars"] = [
        _share_browse_item_summary(item, index)
        for index, item in enumerate(excluded_metadata_sidecars[:50], start=1)
    ]
    report["episode_count"] = len(episode_numbers)
    report["episode_min"] = min(episode_numbers) if episode_numbers else None
    report["episode_max"] = max(episode_numbers) if episode_numbers else None
    report["episodes"] = episode_numbers
    report["missing_expected"] = missing_expected
    report["expected_episode_count"] = expected_episode_count
    report["expected_episode_min"] = expected_episode_min
    report["expected_episode_max"] = expected_episode_max
    report["browse_selection"] = _share_browse_item_summary(browse_selection, browse_index) if isinstance(browse_selection, dict) and browse_selection else {}
    report["receive_items"] = [_share_browse_item_summary(item, index) for index, item in enumerate(selected_items[:50], start=1)]
    report["target_path"] = normalized_target_path
    report["storage"] = storage
    report["receive"] = receive_report
    report["warnings"] = warnings
    report["safety"] = "exactly one approved MV3 share receive request may be sent; selected share item IDs are gated by optional episode coverage checks and metadata scraping sidecars are excluded. Cloud storage is only for transfer and STRM generation; scraping must happen against the STRM library side. No organize/recognize/transfer, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed"
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
        "exclude_extensions": DEFAULT_ORGANIZE_EXCLUDE_EXTENSIONS,
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
        "excluded_extensions": DEFAULT_ORGANIZE_EXCLUDE_EXTENSIONS,
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
        "safety": "organize scan-source only; metadata scraping sidecars are excluded because cloud storage is only for transfer and STRM generation. MV3 documents this endpoint as scan/filter preview that does not recognize media or write to disk; no organize transfer, rename, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed",
    }


def execute_mv3_organize_transfer_from_browse_report(
    base_url: str,
    token: str,
    browse_report: Dict[str, object],
    target_dir: str,
    strm_dir: str,
    tmdb_id: int,
    expected_episode_count: int,
    expected_episode_min: int,
    expected_episode_max: int,
    expected_episodes: Optional[List[int]] = None,
    mode: str = "move",
    is_cloud_target: bool = True,
    background: bool = False,
    source_path_override: str = "",
    timeout: int = 180,
) -> Dict[str, object]:
    warnings: List[str] = []
    blockers: List[str] = []
    source_path = str(source_path_override or browse_report.get("path") or "")
    normalized_target_dir = _normalize_cloud_path(target_dir)
    normalized_strm_dir = _normalize_cloud_path(strm_dir)
    if not source_path:
        blockers.append("browse_report_missing_source_path")
    if not normalized_target_dir:
        blockers.append("target_dir_required")
    if _looks_like_mv3_category_dir(normalized_target_dir):
        blockers.append("target_dir_should_be_organize_root_not_media_category")
    if not normalized_strm_dir:
        blockers.append("strm_dir_required")
    if _looks_like_mv3_category_dir(normalized_strm_dir):
        blockers.append("strm_dir_should_be_strm_root_not_media_category")
    if not tmdb_id:
        blockers.append("tmdb_id_required")
    if expected_episode_count <= 0:
        blockers.append("expected_episode_count_required")
    if expected_episode_min <= 0 or expected_episode_max <= 0:
        blockers.append("expected_episode_range_required")

    items = [item for item in browse_report.get("items", []) if isinstance(item, dict)]
    file_items = [item for item in items if str(item.get("kind") or "") == "file"]
    media_items = [item for item in file_items if _browse_report_item_media_kind(item) == "video"]
    metadata_sidecar_items = [item for item in file_items if _browse_report_item_media_kind(item) == "metadata_sidecar"]
    if metadata_sidecar_items:
        warnings.append("metadata_sidecars_excluded_from_organize_transfer")
    files = _transfer_files_from_cloud_browse_items(media_items, source_path)
    episode_numbers = _episode_numbers_from_scan_items(files)
    expected_episode_list = sorted({int(item) for item in (expected_episodes or []) if int(item) > 0})
    expected_episode_set = set(expected_episode_list)
    if not expected_episode_set and expected_episode_min and expected_episode_max:
        expected_episode_set = set(range(expected_episode_min, expected_episode_max + 1))
    missing_expected = [episode for episode in sorted(expected_episode_set) if episode not in set(episode_numbers)]
    extra_episodes = [episode for episode in episode_numbers if expected_episode_set and episode not in expected_episode_set]
    if expected_episode_list:
        if expected_episode_count and len(expected_episode_list) != expected_episode_count:
            blockers.append("expected_episode_list_count_mismatch")
        if expected_episode_min and min(expected_episode_list) != expected_episode_min:
            blockers.append("expected_episode_list_min_mismatch")
        if expected_episode_max and max(expected_episode_list) != expected_episode_max:
            blockers.append("expected_episode_list_max_mismatch")
    if len(episode_numbers) != expected_episode_count:
        blockers.append("episode_count_mismatch")
    if missing_expected:
        blockers.append("episode_range_incomplete")
    if extra_episodes:
        blockers.append("unexpected_episodes_present")
    if len(files) != expected_episode_count:
        blockers.append("video_file_count_mismatch")
    if not files:
        blockers.append("no_transfer_files")
    if any(not str(file.get("source_file_id") or "") for file in files):
        blockers.append("missing_source_file_id")
    if mode not in ("move", "copy"):
        blockers.append("unsupported_transfer_mode")

    request_body: Dict[str, object] = {
        "files": files,
        "target_dir": normalized_target_dir,
        "is_cloud_target": is_cloud_target,
        "mode": mode,
        "strm_dir": normalized_strm_dir,
        "tmdb_id": tmdb_id,
        "enable_primary_category": True,
        "enable_secondary_category": True,
        "copy_subtitles": False,
        "copy_non_media": False,
        "background": background,
    }
    transfer_report: Dict[str, object] = {"skipped": True}
    completion_verification = _organize_completion_verification_hint(
        normalized_target_dir,
        normalized_strm_dir,
        tmdb_id,
        expected_episode_count,
        expected_episode_min,
        expected_episode_max,
        expected_episode_list,
        episode_numbers,
        transfer_report,
    )
    if not blockers:
        client = MV3Client(base_url, token, timeout=timeout)
        try:
            status, headers, response_body = client.post_json("/api/v1/organize/transfer", request_body)
            parsed = _parse_json(response_body.decode("utf-8", "replace"))
            payload = _unwrap_api_payload(parsed)
            api_success = _api_success(parsed)
            transfer_report = _mv3_api_call_summary(
                "POST",
                "/api/v1/organize/transfer",
                status,
                headers,
                request_body,
                payload,
                api_success,
                response_body,
            )
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            blockers.append("mv3_transfer_request_failed")
            warnings.append(f"mv3_transfer_request_failed:{type(exc).__name__}:{exc}")
            transfer_report = _mv3_api_error_summary(
                "POST",
                "/api/v1/organize/transfer",
                request_body,
                exc,
            )
        completion_verification = _organize_completion_verification_hint(
            normalized_target_dir,
            normalized_strm_dir,
            tmdb_id,
            expected_episode_count,
            expected_episode_min,
            expected_episode_max,
            expected_episode_list,
            episode_numbers,
            transfer_report,
        )

    return {
        "mode": "mv3-organize-transfer-result",
        "ok": bool(transfer_report.get("ok")) and not blockers,
        "source_path": source_path,
        "target_dir": normalized_target_dir,
        "strm_dir": normalized_strm_dir,
        "tmdb_id": tmdb_id,
        "transfer_mode": mode,
        "is_cloud_target": is_cloud_target,
        "background": background,
        "expected_episode_count": expected_episode_count,
        "expected_episode_min": expected_episode_min,
        "expected_episode_max": expected_episode_max,
        "expected_episodes": expected_episode_list,
        "episode_count": len(episode_numbers),
        "episode_min": min(episode_numbers) if episode_numbers else None,
        "episode_max": max(episode_numbers) if episode_numbers else None,
        "episodes": episode_numbers,
        "missing_expected": missing_expected,
        "unexpected_episodes": extra_episodes,
        "file_count": len(files),
        "excluded_metadata_sidecar_count": len(metadata_sidecar_items),
        "excluded_metadata_sidecars": [
            _browse_report_item_summary(item, index)
            for index, item in enumerate(metadata_sidecar_items[:50], start=1)
        ],
        "request_summary": _organize_transfer_request_summary(request_body),
        "transfer": transfer_report,
        "completion_verification": completion_verification,
        "warnings": warnings,
        "blockers": sorted(set(blockers)),
        "safety": (
            "approved MV3 organize transfer; request is built only from video files in a complete readonly cloud browse report "
            "and sends one /api/v1/organize/transfer call. Cloud storage is used only for transfer and STRM generation; "
            "cloud media metadata sidecars are not copied, and scraping must happen against the STRM library side. "
            "No qBittorrent action, hlink deletion, local filesystem deletion, or MP cleanup is performed"
        ),
    }


def generate_mv3_strm(
    base_url: str,
    token: str,
    source_dir: str,
    target_dir: str,
    storage: str = "115-default",
    cloud: bool = True,
    incremental: bool = True,
    overwrite: bool = False,
    organize: bool = False,
    openlist: bool = False,
    enable_primary_category: bool = True,
    enable_secondary_category: bool = True,
    template: str = "",
    allow_organize: bool = False,
    timeout: int = 180,
) -> Dict[str, object]:
    warnings: List[str] = []
    blockers: List[str] = []
    normalized_source_dir = _normalize_cloud_path(source_dir)
    normalized_target_dir = _normalize_cloud_path(target_dir)
    if not normalized_source_dir:
        blockers.append("source_dir_required")
    if not normalized_target_dir:
        blockers.append("target_dir_required")
    if normalized_target_dir.startswith("/已整理"):
        blockers.append("target_dir_looks_like_cloud_media_root")
    if cloud and normalized_source_dir.startswith("/volume"):
        blockers.append("source_dir_looks_like_local_strm_root")
    if organize and not allow_organize:
        blockers.append("strm_generate_organize_disabled")
        warnings.append("cloud_media_is_transfer_and_strm_only_use_mv3_organize_transfer_first")

    request_body: Dict[str, object] = {
        "source_dir": normalized_source_dir,
        "target_dir": normalized_target_dir,
        "cloud": cloud,
        "storage": storage or None,
        "incremental": incremental,
        "overwrite": overwrite,
        "organize": organize,
        "openlist": openlist,
        "enable_primary_category": enable_primary_category,
        "enable_secondary_category": enable_secondary_category,
    }
    if template:
        request_body["template"] = template

    generate_report: Dict[str, object] = {"skipped": True}
    if not blockers:
        client = MV3Client(base_url, token, timeout=timeout)
        try:
            status, headers, response_body = client.post_json("/api/v1/strm/generate", request_body)
            parsed = _parse_json(response_body.decode("utf-8", "replace"))
            payload = _unwrap_api_payload(parsed)
            api_success = _api_success(parsed)
            generate_report = _mv3_api_call_summary(
                "POST",
                "/api/v1/strm/generate",
                status,
                headers,
                request_body,
                payload,
                api_success,
                response_body,
            )
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            blockers.append("mv3_strm_generate_request_failed")
            warnings.append(f"mv3_strm_generate_request_failed:{type(exc).__name__}:{exc}")
            generate_report = _mv3_api_error_summary(
                "POST",
                "/api/v1/strm/generate",
                request_body,
                exc,
            )

    return {
        "mode": "mv3-strm-generate-result",
        "ok": bool(generate_report.get("ok")) and not blockers,
        "source_dir": normalized_source_dir,
        "target_dir": normalized_target_dir,
        "storage": storage,
        "cloud": cloud,
        "incremental": incremental,
        "overwrite": overwrite,
        "organize": organize,
        "openlist": openlist,
        "allow_organize": allow_organize,
        "enable_primary_category": enable_primary_category,
        "enable_secondary_category": enable_secondary_category,
        "template": template,
        "request_summary": _strm_generate_request_summary(request_body),
        "generate": generate_report,
        "warnings": warnings,
        "blockers": sorted(set(blockers)),
        "safety": (
            "approved MV3 STRM generation only; cloud storage remains the source for STRM files, not the scraping target. "
            "Scraping must happen against the STRM library side; no cloud media move/delete, qBittorrent action, "
            "hlink deletion, local filesystem deletion, or MP cleanup is performed"
        ),
    }


def render_mv3_strm_generate_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    generate = report.get("generate") if isinstance(report.get("generate"), dict) else {}
    lines = [
        "# MV3 STRM Generate Result",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Source dir: `{report.get('source_dir', '')}`",
        f"- Target dir: `{report.get('target_dir', '')}`",
        f"- Storage: `{report.get('storage', '')}`",
        f"- Cloud source: `{bool(report.get('cloud'))}`",
        f"- Incremental: `{bool(report.get('incremental'))}`",
        f"- Overwrite: `{bool(report.get('overwrite'))}`",
        f"- Organize: `{bool(report.get('organize'))}`",
        f"- Generate OK: `{bool(generate.get('ok'))}`",
        f"- Generate HTTP status: `{generate.get('status', '')}`",
        "- Safety: one approved MV3 STRM generate request only; cloud storage remains the source for STRM files, and scraping must happen against the STRM library side.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    return "\n".join(lines)


def list_mv3_strm_records(
    base_url: str,
    token: str,
    keyword: str = "",
    record_ids: Optional[List[int]] = None,
    source: str = "",
    path_dir: str = "",
    missing_pickcode: Optional[bool] = None,
    use_regex: Optional[bool] = None,
    page: int = 1,
    page_size: int = 100,
    timeout: int = 60,
) -> Dict[str, object]:
    query: Dict[str, object] = {
        "page": max(1, int(page or 1)),
        "page_size": max(1, int(page_size or 100)),
    }
    if keyword:
        query["keyword"] = keyword
    if source:
        query["source"] = source
    if path_dir:
        query["path_dir"] = path_dir
    if missing_pickcode is not None:
        query["missing_pickcode"] = "true" if missing_pickcode else "false"
    if use_regex is not None:
        query["use_regex"] = "true" if use_regex else "false"
    path = "/api/v1/strm/records?" + urllib.parse.urlencode(query)
    client = MV3Client(base_url, token, timeout=timeout)
    warnings: List[str] = []
    status, headers, response_body = client.get(path)
    parsed = _parse_json(response_body.decode("utf-8", "replace"))
    payload = _unwrap_api_payload(parsed)
    api_success = _api_success(parsed)
    rows = _strm_record_rows(payload)
    clean_record_ids = sorted({int(record_id) for record_id in (record_ids or []) if int(record_id) > 0})
    filtered_rows = rows
    if clean_record_ids:
        wanted = set(clean_record_ids)
        filtered_rows = [row for row in rows if _strm_record_id(row) in wanted]
        missing_ids = sorted(wanted - {_strm_record_id(row) for row in filtered_rows})
        if missing_ids:
            warnings.append(f"record_ids_not_found:{missing_ids}")
    summaries = [_strm_record_summary(row) for row in filtered_rows[:200]]
    episodes = sorted(
        {
            episode
            for episode in (
                _episode_number_from_text(str(item.get("strm_path") or "") + " " + str(item.get("source_path") or ""))
                for item in summaries
            )
            if episode is not None
        }
    )
    return {
        "mode": "readonly-mv3-strm-records",
        "endpoint": {"method": "GET", "path": "/api/v1/strm/records"},
        "ok": 200 <= status < 300 and api_success,
        "http_ok": 200 <= status < 300,
        "api_success": api_success,
        "status": status,
        "response_content_type": _header(headers, "content-type"),
        "query": {
            "keyword": keyword,
            "record_ids": clean_record_ids,
            "source": source,
            "path_dir": path_dir,
            "missing_pickcode": missing_pickcode,
            "use_regex": use_regex,
            "page": query["page"],
            "page_size": query["page_size"],
        },
        "pagination": _strm_record_pagination(payload),
        "raw_record_count": len(rows),
        "matched_record_count": len(filtered_rows),
        "reported_record_count": len(summaries),
        "episode_count": len(episodes),
        "episodes": episodes,
        "missing_in_range": _missing_episode_numbers(episodes),
        "records": summaries,
        "warnings": warnings,
        "safety": "readonly MV3 STRM record listing only; no STRM generation, record mutation, cloud media move/delete, qBittorrent action, hlink deletion, local filesystem deletion, or MP cleanup is performed",
    }


def render_mv3_strm_records_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(_public_strm_records_report(report), ensure_ascii=False, indent=2)
    lines = [
        "# MV3 STRM Records",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Matched records: `{report.get('matched_record_count', 0)}`",
        f"- Reported records: `{report.get('reported_record_count', 0)}`",
        f"- Episodes: `{report.get('episodes', [])}`",
        f"- Missing in range: `{report.get('missing_in_range', [])}`",
        "- Safety: readonly MV3 STRM records listing only; no writes were performed.",
        "",
        "| ID | Episode | Source | STRM path | Source path | Exists hint |",
        "| ---: | ---: | --- | --- | --- | --- |",
    ]
    for record in report.get("records", []) if isinstance(report.get("records"), list) else []:
        if not isinstance(record, dict):
            continue
        lines.append(
            "| {id} | {episode} | {source} | {strm_path} | {source_path} | {exists} |".format(
                id=record.get("id", ""),
                episode=record.get("episode", ""),
                source=record.get("source", ""),
                strm_path=record.get("strm_path", ""),
                source_path=record.get("source_path", ""),
                exists=record.get("exists_hint", ""),
            )
        )
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    return "\n".join(lines)


def _public_strm_records_report(report: Dict[str, object]) -> Dict[str, object]:
    public_report = dict(report)
    records = public_report.get("records")
    if isinstance(records, list):
        public_report["records"] = [
            _public_strm_record(record) if isinstance(record, dict) else record
            for record in records
        ]
    return public_report


def _public_strm_record(record: Dict[str, object]) -> Dict[str, object]:
    public_record = dict(record)
    if "strm_content" in public_record:
        public_record["strm_content"] = "[REDACTED]" if public_record.get("strm_content") else ""
    return public_record


def materialize_mv3_strm_records(
    base_url: str,
    token: str,
    record_ids: List[int],
    expected_record_ids: Optional[List[int]] = None,
    expected_strm_prefix: str = "",
    expected_source_prefix: str = "",
    host_strm_prefix: str = "",
    rewrite_strm_prefix: str = "",
    keyword: str = "",
    overwrite: bool = False,
    timeout: int = 60,
) -> Dict[str, object]:
    warnings: List[str] = []
    blockers: List[str] = []
    clean_record_ids = sorted({int(record_id) for record_id in record_ids if int(record_id) > 0})
    clean_expected_ids = sorted({int(record_id) for record_id in (expected_record_ids or []) if int(record_id) > 0})
    if not clean_record_ids:
        blockers.append("record_ids_required")
    if clean_expected_ids and clean_record_ids != clean_expected_ids:
        blockers.append("record_id_safety_mismatch")

    records_report: Dict[str, object] = {"skipped": True}
    records: List[Dict[str, object]] = []
    if not blockers:
        records_report = list_mv3_strm_records(
            base_url,
            token,
            keyword=keyword,
            record_ids=clean_record_ids,
            page=1,
            page_size=max(100, len(clean_record_ids)),
            timeout=timeout,
        )
        if not records_report.get("ok"):
            blockers.append("mv3_strm_records_read_failed")
        records = [record for record in records_report.get("records", []) if isinstance(record, dict)]
        found_ids = sorted({int(record.get("id") or 0) for record in records})
        missing_ids = sorted(set(clean_record_ids) - set(found_ids))
        if missing_ids:
            blockers.append("record_ids_not_found")

    writes: List[Dict[str, object]] = []
    if not blockers:
        for record in records:
            writes.append(
                _materialize_strm_record(
                    record,
                    expected_strm_prefix=expected_strm_prefix,
                    expected_source_prefix=expected_source_prefix,
                    host_strm_prefix=host_strm_prefix,
                    rewrite_strm_prefix=rewrite_strm_prefix,
                    overwrite=overwrite,
                )
            )
        for write in writes:
            if not write.get("ok"):
                blockers.extend(str(item) for item in write.get("blockers", []) if item)
            warnings.extend(str(item) for item in write.get("warnings", []) if item)

    return {
        "mode": "mv3-strm-records-materialize-result",
        "ok": not blockers and bool(writes),
        "record_ids": clean_record_ids,
        "expected_record_ids": clean_expected_ids,
        "keyword": keyword,
        "expected_strm_prefix": expected_strm_prefix,
        "expected_source_prefix": expected_source_prefix,
        "host_strm_prefix": host_strm_prefix,
        "rewrite_strm_prefix": rewrite_strm_prefix,
        "overwrite": overwrite,
        "records_query": {
            "ok": bool(records_report.get("ok")),
            "matched_record_count": records_report.get("matched_record_count"),
            "warnings": records_report.get("warnings", []),
        },
        "writes": writes,
        "warnings": sorted(set(warnings)),
        "blockers": sorted(set(blockers)),
        "safety": "approved filesystem materialization from MV3 STRM record content only; no MV3 generation, cloud media move/delete, qBittorrent action, hlink deletion, or MP cleanup is performed",
    }


def render_mv3_strm_records_materialize_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        "# MV3 STRM Records Materialize Result",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Record IDs: `{report.get('record_ids', [])}`",
        f"- Overwrite: `{bool(report.get('overwrite'))}`",
        f"- Host STRM prefix: `{report.get('host_strm_prefix', '')}`",
        "- Safety: approved write of STRM files from MV3 record content only; no cloud, qB, hlink, or MP cleanup was performed.",
        "",
        "| Record ID | Action | Host path | Bytes | SHA256 |",
        "| ---: | --- | --- | ---: | --- |",
    ]
    for write in report.get("writes", []) if isinstance(report.get("writes"), list) else []:
        if not isinstance(write, dict):
            continue
        lines.append(
            "| {id} | {action} | {path} | {size} | {sha} |".format(
                id=write.get("record_id", ""),
                action=write.get("action", ""),
                path=write.get("host_path", ""),
                size=write.get("bytes_written", 0),
                sha=write.get("sha256", ""),
            )
        )
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    return "\n".join(lines)


def redirect_mv3_strm_records(
    base_url: str,
    token: str,
    record_ids: List[int],
    expected_record_ids: Optional[List[int]] = None,
    old_prefix: str = "",
    new_prefix: str = "",
    expected_source_prefix: str = "",
    keyword: str = "",
    strm_dir: str = "",
    timeout: int = 180,
) -> Dict[str, object]:
    warnings: List[str] = []
    blockers: List[str] = []
    clean_record_ids = sorted({int(record_id) for record_id in record_ids if int(record_id) > 0})
    clean_expected_ids = sorted({int(record_id) for record_id in (expected_record_ids or []) if int(record_id) > 0})
    old_prefix = old_prefix.rstrip("/")
    new_prefix = new_prefix.rstrip("/")
    expected_source_prefix = expected_source_prefix.rstrip("/")
    if not clean_record_ids:
        blockers.append("record_ids_required")
    if clean_expected_ids and clean_record_ids != clean_expected_ids:
        blockers.append("record_id_safety_mismatch")
    if not old_prefix:
        blockers.append("old_prefix_required")
    if not new_prefix:
        blockers.append("new_prefix_required")
    if old_prefix and new_prefix and old_prefix == new_prefix:
        blockers.append("redirect_prefixes_must_differ")

    before_report: Dict[str, object] = {"skipped": True}
    before_records: List[Dict[str, object]] = []
    expected_after_paths: Dict[int, str] = {}
    if not blockers:
        before_report = list_mv3_strm_records(
            base_url,
            token,
            keyword=keyword,
            record_ids=clean_record_ids,
            page=1,
            page_size=max(100, len(clean_record_ids)),
            timeout=timeout,
        )
        if not before_report.get("ok"):
            blockers.append("mv3_strm_records_read_failed")
        before_records = [record for record in before_report.get("records", []) if isinstance(record, dict)]
        _validate_redirect_record_set(before_records, clean_record_ids, old_prefix, expected_source_prefix, blockers, phase="before")
        if not blockers:
            expected_after_paths = _expected_redirect_paths(before_records, old_prefix, new_prefix)

    request_body: Dict[str, object] = {
        "old_prefix": old_prefix,
        "new_prefix": new_prefix,
        "record_ids": clean_record_ids,
    }
    if strm_dir:
        request_body["strm_dir"] = strm_dir

    redirect_report: Dict[str, object] = {"skipped": True}
    redirect_payload: object = {}
    if not blockers:
        client = MV3Client(base_url, token, timeout=timeout)
        try:
            status, headers, response_body = client.post_json("/api/v1/strm/records/redirect", request_body)
            parsed = _parse_json(response_body.decode("utf-8", "replace"))
            payload = _unwrap_api_payload(parsed)
            redirect_payload = payload
            api_success = _api_success(parsed)
            redirect_report = _mv3_api_call_summary(
                "POST",
                "/api/v1/strm/records/redirect",
                status,
                headers,
                request_body,
                payload,
                api_success,
                response_body,
            )
            if not redirect_report.get("ok"):
                blockers.append("mv3_strm_records_redirect_failed")
            _validate_redirect_mutation_result(payload, len(clean_record_ids), blockers)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            blockers.append("mv3_strm_records_redirect_request_failed")
            warnings.append(f"mv3_strm_records_redirect_request_failed:{type(exc).__name__}:{exc}")
            redirect_report = _mv3_api_error_summary(
                "POST",
                "/api/v1/strm/records/redirect",
                request_body,
                exc,
            )

    after_report: Dict[str, object] = {"skipped": True}
    after_records: List[Dict[str, object]] = []
    post_blockers: List[str] = []
    if not blockers:
        after_report = list_mv3_strm_records(
            base_url,
            token,
            keyword=keyword,
            record_ids=clean_record_ids,
            page=1,
            page_size=max(100, len(clean_record_ids)),
            timeout=timeout,
        )
        if not after_report.get("ok"):
            post_blockers.append("mv3_strm_records_post_read_failed")
        after_records = [record for record in after_report.get("records", []) if isinstance(record, dict)]
        _validate_redirect_record_set(after_records, clean_record_ids, new_prefix, expected_source_prefix, post_blockers, phase="after")
        _validate_redirect_expected_paths(after_records, expected_after_paths, post_blockers)

    all_blockers = sorted(set(blockers + post_blockers))
    return {
        "mode": "mv3-strm-records-redirect-result",
        "ok": bool(redirect_report.get("ok")) and not all_blockers,
        "record_ids": clean_record_ids,
        "expected_record_ids": clean_expected_ids,
        "record_count": len(clean_record_ids),
        "keyword": keyword,
        "old_prefix": old_prefix,
        "new_prefix": new_prefix,
        "strm_dir": strm_dir,
        "expected_source_prefix": expected_source_prefix,
        "request_summary": _strm_records_redirect_request_summary(request_body),
        "before": _strm_redirect_records_summary(before_records, old_prefix),
        "redirect": redirect_report,
        "after": _strm_redirect_records_summary(after_records, new_prefix, expected_after_paths),
        "redirect_payload_summary": _redirect_payload_counts(redirect_payload),
        "warnings": sorted(set(warnings)),
        "blockers": all_blockers,
        "safety": "approved MV3 STRM record redirect only; records are read before and after, and no cloud media move/delete, qBittorrent action, hlink deletion, local filesystem deletion, or MP cleanup is performed",
    }


def render_mv3_strm_records_redirect_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    redirect = report.get("redirect") if isinstance(report.get("redirect"), dict) else {}
    before = report.get("before") if isinstance(report.get("before"), dict) else {}
    after = report.get("after") if isinstance(report.get("after"), dict) else {}
    lines = [
        "# MV3 STRM Records Redirect Result",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Record IDs: `{report.get('record_ids', [])}`",
        f"- Old prefix: `{report.get('old_prefix', '')}`",
        f"- New prefix: `{report.get('new_prefix', '')}`",
        f"- Before matched prefix: `{before.get('matching_prefix_count', 0)}`",
        f"- After matched prefix: `{after.get('matching_prefix_count', 0)}`",
        f"- Redirect OK: `{bool(redirect.get('ok'))}`",
        f"- Redirect HTTP status: `{redirect.get('status', '')}`",
        "- Safety: one approved MV3 STRM record redirect request only; no qB, hlink, local filesystem, or MP cleanup was performed.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    return "\n".join(lines)


def regenerate_mv3_strm_records(
    base_url: str,
    token: str,
    record_ids: List[int],
    timeout: int = 180,
) -> Dict[str, object]:
    warnings: List[str] = []
    blockers: List[str] = []
    clean_record_ids = sorted({int(record_id) for record_id in record_ids if int(record_id) > 0})
    if not clean_record_ids:
        blockers.append("record_ids_required")

    request_body: Dict[str, object] = {"record_ids": clean_record_ids}
    regenerate_report: Dict[str, object] = {"skipped": True}
    if not blockers:
        client = MV3Client(base_url, token, timeout=timeout)
        try:
            status, headers, response_body = client.post_json("/api/v1/strm/records/regenerate", request_body)
            parsed = _parse_json(response_body.decode("utf-8", "replace"))
            payload = _unwrap_api_payload(parsed)
            api_success = _api_success(parsed)
            regenerate_report = _mv3_api_call_summary(
                "POST",
                "/api/v1/strm/records/regenerate",
                status,
                headers,
                request_body,
                payload,
                api_success,
                response_body,
            )
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            blockers.append("mv3_strm_records_regenerate_request_failed")
            warnings.append(f"mv3_strm_records_regenerate_request_failed:{type(exc).__name__}:{exc}")
            regenerate_report = _mv3_api_error_summary(
                "POST",
                "/api/v1/strm/records/regenerate",
                request_body,
                exc,
            )

    return {
        "mode": "mv3-strm-records-regenerate-result",
        "ok": bool(regenerate_report.get("ok")) and not blockers,
        "record_ids": clean_record_ids,
        "record_count": len(clean_record_ids),
        "request_summary": _strm_records_regenerate_request_summary(request_body),
        "regenerate": regenerate_report,
        "warnings": warnings,
        "blockers": sorted(set(blockers)),
        "safety": "approved MV3 STRM record regeneration only; no cloud media move/delete, qBittorrent action, hlink deletion, local filesystem deletion, or MP cleanup is performed",
    }


def render_mv3_strm_records_regenerate_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    regenerate = report.get("regenerate") if isinstance(report.get("regenerate"), dict) else {}
    lines = [
        "# MV3 STRM Records Regenerate Result",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Record IDs: `{report.get('record_ids', [])}`",
        f"- Record count: `{report.get('record_count', 0)}`",
        f"- Regenerate OK: `{bool(regenerate.get('ok'))}`",
        f"- Regenerate HTTP status: `{regenerate.get('status', '')}`",
        "- Safety: one approved MV3 STRM record-regenerate request only; no qB, hlink, local filesystem, or MP cleanup was performed.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    return "\n".join(lines)


def render_mv3_organize_transfer_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    transfer = report.get("transfer") if isinstance(report.get("transfer"), dict) else {}
    completion = report.get("completion_verification") if isinstance(report.get("completion_verification"), dict) else {}
    lines = [
        "# MV3 Organize Transfer Result",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Source path: `{report.get('source_path', '')}`",
        f"- Target dir: `{report.get('target_dir', '')}`",
        f"- STRM dir: `{report.get('strm_dir', '')}`",
        f"- TMDB ID: `{report.get('tmdb_id', '')}`",
        f"- Files: `{report.get('file_count', 0)}`",
        f"- Excluded metadata sidecars: `{report.get('excluded_metadata_sidecar_count', 0)}`",
        f"- Episode count: `{report.get('episode_count', 0)}`",
        f"- Episode range: `{report.get('episode_min', '')}-{report.get('episode_max', '')}`",
        f"- Missing expected: `{report.get('missing_expected', [])}`",
        f"- Transfer OK: `{bool(transfer.get('ok'))}`",
        f"- Transfer HTTP status: `{transfer.get('status', '')}`",
        f"- Completion status: `{completion.get('status', '')}`",
        "- Safety: one approved MV3 organize transfer only; only video files are submitted, cloud metadata sidecars are not copied, and scraping must happen against the STRM library side.",
    ]
    next_steps = completion.get("required_followup")
    if isinstance(next_steps, list) and next_steps:
        lines.extend(["", "## Required Follow-up", ""])
        lines.extend(f"- `{step}`" for step in next_steps)
    excluded = report.get("excluded_metadata_sidecars")
    if isinstance(excluded, list) and excluded:
        lines.extend(["", "## Excluded Cloud Metadata Sidecars", ""])
        lines.extend(f"- `{item.get('name', '')}`" for item in excluded if isinstance(item, dict))
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    return "\n".join(lines)


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
        f"- Excluded extensions: `{report.get('excluded_extensions', [])}`",
        f"- Episode count: `{summary.get('episode_count', 0)}`",
        f"- Episode range: `{summary.get('episode_min', '')}-{summary.get('episode_max', '')}`",
        f"- Missing in range: `{summary.get('missing_in_range', [])}`",
        "- Safety: scan-source only; metadata scraping sidecars are excluded, and no transfer, rename, STRM generation, or deletion was performed.",
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
        f"- Receive all files: `{bool(report.get('receive_all_files'))}`",
        f"- File IDs: `{report.get('file_id_count', 0)}`",
        f"- Episodes: `{report.get('episodes', [])}`",
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
        "| # | Title | Channel | Size | Type | Share code available |",
        "| ---: | --- | --- | ---: | --- | --- |",
    ]
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {index} | {title} | {channel} | {size} | {media_type} | {share_code_available} |".format(
                index=item.get("index") or "",
                title=_escape(str(item.get("title") or "")),
                channel=_escape(str(item.get("channel") or "")),
                size=_escape(str(item.get("size") or "")),
                media_type=_escape(str(item.get("media_type") or "")),
                share_code_available=str(bool(item.get("share_code_available"))),
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


def _plan_mv3_wrong_root_title(
    client: MV3Client,
    title_row: Dict[str, object],
    wrong_root: str,
    correct_root: str,
    strm_root: str,
    storage: str,
    limit: int,
    approve_move: bool,
    approve_delete_duplicates: bool,
    approve_delete_empty: bool,
) -> Dict[str, object]:
    title = _cloud_name(title_row)
    title_folder_id = _cloud_file_id(title_row)
    wrong_title_path = f"{wrong_root}/{title}"
    correct_title_path = f"{correct_root}/{title}"
    wrong_season = _best_season_summary(client, wrong_title_path, title_folder_id, storage, limit)
    correct_title = _cloud_folder_summary_by_path(client, correct_title_path, storage, limit)
    correct_season = _best_season_summary(client, correct_title_path, str(correct_title.get("folder_id") or ""), storage, limit)
    strm_summary = _strm_title_summary(strm_root, title, wrong_root, correct_root)

    wrong_episodes = set(wrong_season.get("episodes", []))
    correct_episodes = set(correct_season.get("episodes", []))
    wrong_media_count = int(wrong_season.get("media_count") or 0)
    correct_media_count = int(correct_season.get("media_count") or 0)
    wrong_file_ids = [
        str(item.get("file_id") or "")
        for item in wrong_season.get("media_items", [])
        if isinstance(item, dict) and str(item.get("file_id") or "")
    ]
    blockers: List[str] = []
    warnings: List[str] = []
    decision = "blocked"
    action = "none"
    operations: List[Dict[str, object]] = []
    expected_count = max(wrong_media_count, correct_media_count, int(strm_summary.get("episode_count") or 0))

    strm_wrong_targets = int(strm_summary.get("wrong_target_count") or 0)
    strm_correct_targets = int(strm_summary.get("correct_target_count") or 0)
    strm_total = int(strm_summary.get("total_strm") or 0)

    if not title:
        blockers.append("title_name_not_found")
    if not wrong_season.get("exists"):
        blockers.append("wrong_season_not_found")
    if wrong_media_count <= 0 and not wrong_season.get("folders"):
        decision = "empty_wrong_folder"
        if approve_delete_empty and str(wrong_season.get("folder_id") or ""):
            action = "delete_empty_wrong_season"
            operations.append(_mv3_delete_115(client, [str(wrong_season.get("folder_id"))], storage))
        else:
            action = "dry_run_delete_empty_wrong_season"
    elif wrong_media_count > 0 and wrong_media_count == correct_media_count and wrong_episodes and wrong_episodes == correct_episodes and strm_wrong_targets == 0:
        decision = "delete_duplicate_wrong_season"
        wrong_season_id = str(wrong_season.get("folder_id") or "")
        if not wrong_season_id:
            blockers.append("wrong_season_folder_id_not_found")
        elif approve_delete_duplicates:
            action = "delete_duplicate_wrong_season"
            operations.append(_mv3_delete_115(client, [wrong_season_id], storage))
            _append_empty_wrong_parent_delete(
                client,
                operations,
                wrong_title_path,
                title_folder_id,
                storage,
                limit,
                approve_delete_empty,
            )
        else:
            action = "dry_run_delete_duplicate_wrong_season"
    elif wrong_media_count > 0 and correct_media_count < wrong_media_count and strm_wrong_targets == 0 and len(wrong_file_ids) == wrong_media_count:
        decision = "move_wrong_media_to_correct_season"
        correct_target_id = str(correct_season.get("folder_id") or "")
        if not correct_target_id:
            blockers.append("correct_season_folder_id_not_found")
        if correct_media_count > 0 and correct_episodes - wrong_episodes:
            blockers.append("correct_season_has_unmatched_extra_episodes")
        if strm_total and strm_correct_targets == 0:
            blockers.append("strm_does_not_point_to_correct_root")
        if not blockers:
            if approve_move:
                action = "move_wrong_media_to_correct_season"
                operations.append(_mv3_move_115(client, wrong_file_ids, correct_target_id, storage))
                if approve_delete_empty and str(wrong_season.get("folder_id") or ""):
                    refreshed_wrong_season = _cloud_folder_summary_by_path(client, str(wrong_season.get("path") or ""), storage, limit)
                    if int(refreshed_wrong_season.get("media_count") or 0) == 0 and int(refreshed_wrong_season.get("folder_count") or 0) == 0:
                        operations.append(_mv3_delete_115(client, [str(wrong_season.get("folder_id"))], storage))
                _append_empty_wrong_parent_delete(
                    client,
                    operations,
                    wrong_title_path,
                    title_folder_id,
                    storage,
                    limit,
                    approve_delete_empty,
                )
            else:
                action = "dry_run_move_wrong_media_to_correct_season"
    else:
        blockers.append("ambiguous_wrong_root_state")
        if strm_wrong_targets > 0:
            blockers.append("strm_points_to_wrong_root")
        if wrong_media_count > 0 and correct_media_count > 0 and wrong_episodes != correct_episodes:
            blockers.append("wrong_and_correct_episode_sets_differ")
        if wrong_media_count > 0 and len(wrong_file_ids) != wrong_media_count:
            blockers.append("wrong_media_file_ids_incomplete")

    post_wrong = _cloud_folder_summary_by_path(client, str(wrong_season.get("path") or ""), storage, limit) if operations else wrong_season
    post_correct = _cloud_folder_summary_by_path(client, str(correct_season.get("path") or ""), storage, limit) if operations else correct_season
    post_strm = _strm_title_summary(strm_root, title, wrong_root, correct_root)
    operation_ok = all(bool(operation.get("ok")) for operation in operations) if operations else True
    post_ok = _mv3_wrong_root_item_verified(decision, post_wrong, post_correct, post_strm, expected_count, write_executed=bool(operations))
    ok = not blockers and operation_ok and (post_ok if operations else True)

    if strm_total == 0:
        warnings.append("strm_files_not_found_for_title")

    return {
        "title": title,
        "wrong_title_path": wrong_title_path,
        "correct_title_path": correct_title_path,
        "decision": decision,
        "action": action,
        "ok": ok,
        "expected_episode_count": expected_count,
        "wrong": _public_cloud_folder_summary(wrong_season),
        "correct": _public_cloud_folder_summary(correct_season),
        "strm": post_strm if operations else strm_summary,
        "operations": operations,
        "post_verify": {
            "wrong": _public_cloud_folder_summary(post_wrong),
            "correct": _public_cloud_folder_summary(post_correct),
            "strm": post_strm,
        },
        "warnings": warnings,
        "blockers": sorted(set(blockers)),
    }


def _best_season_summary(
    client: MV3Client,
    title_path: str,
    title_folder_id: str,
    storage: str,
    limit: int,
) -> Dict[str, object]:
    title_summary = _cloud_folder_summary_by_path(client, title_path, storage, limit)
    if not title_folder_id:
        title_folder_id = str(title_summary.get("folder_id") or "")
    title_rows = title_summary.get("rows") if isinstance(title_summary.get("rows"), list) else []
    season_rows = [
        row
        for row in title_rows
        if isinstance(row, dict) and _cloud_item_kind(row) == "folder" and _looks_like_season_folder(_cloud_name(row))
    ]
    if season_rows:
        def rank(row: Dict[str, object]) -> Tuple[int, str]:
            name = _cloud_name(row)
            match = re.search(r"(\d{1,3})", name)
            number = int(match.group(1)) if match else 999
            return (number, name)

        selected = sorted(season_rows, key=rank)[0]
        season_name = _cloud_name(selected)
        return _cloud_folder_summary_by_id(
            client,
            _cloud_file_id(selected),
            f"{_normalize_cloud_path(title_path)}/{season_name}",
            storage,
            limit,
        )
    media_count = int(title_summary.get("media_count") or 0)
    if media_count > 0 or title_summary.get("exists"):
        return title_summary
    if title_folder_id:
        return _cloud_folder_summary_by_id(client, title_folder_id, _normalize_cloud_path(title_path), storage, limit)
    return title_summary


def _append_empty_wrong_parent_delete(
    client: MV3Client,
    operations: List[Dict[str, object]],
    wrong_title_path: str,
    title_folder_id: str,
    storage: str,
    limit: int,
    approve_delete_empty: bool,
) -> None:
    if not approve_delete_empty or not title_folder_id:
        return
    if operations and not all(bool(operation.get("ok")) for operation in operations):
        return
    refreshed_title = _cloud_folder_summary_by_path(client, wrong_title_path, storage, limit)
    if not refreshed_title.get("exists") and title_folder_id:
        refreshed_title = _cloud_folder_summary_by_id(client, title_folder_id, wrong_title_path, storage, limit)
    if int(refreshed_title.get("media_count") or 0) == 0 and int(refreshed_title.get("folder_count") or 0) == 0:
        operations.append(_mv3_delete_115(client, [title_folder_id], storage))


def _cloud_folder_summary_by_path(client: MV3Client, path: str, storage: str, limit: int) -> Dict[str, object]:
    normalized = _normalize_cloud_path(path)
    info, status, content_type = _read_cloud_info_status(client, "", normalized, storage)
    folder_id = _extract_folder_id(info)
    summary = _empty_cloud_folder_summary(normalized, exists=bool(folder_id), status=status, content_type=content_type)
    if not folder_id:
        return summary
    return _cloud_folder_summary_by_id(client, folder_id, normalized, storage, limit, info=info, info_status=status, info_content_type=content_type)


def _cloud_folder_summary_by_id(
    client: MV3Client,
    folder_id: str,
    path: str,
    storage: str,
    limit: int,
    info: Optional[Dict[str, object]] = None,
    info_status: int = 0,
    info_content_type: str = "",
) -> Dict[str, object]:
    payload, browse_status, browse_content_type = _read_cloud_folder_status(client, folder_id, storage, limit)
    rows = _cloud_rows(payload)
    media_items = [_cloud_media_item_summary(row) for row in rows if _cloud_item_kind(row) == "file" and _is_media_name(_cloud_name(row))]
    folders = [_cloud_name(row) for row in rows if _cloud_item_kind(row) == "folder"]
    episodes = sorted({item["episode"] for item in media_items if isinstance(item.get("episode"), int)})
    summary = {
        "exists": bool(folder_id),
        "path": _normalize_cloud_path(path),
        "folder_id": folder_id,
        "info_status": info_status,
        "info_content_type": info_content_type,
        "browse_status": browse_status,
        "browse_content_type": browse_content_type,
        "browse_ok": 200 <= browse_status < 300,
        "item_count": len(rows),
        "folder_count": len(folders),
        "folders": folders[:20],
        "media_count": len(media_items),
        "episodes": episodes,
        "missing_in_range": _missing_episode_numbers(episodes),
        "media_items": media_items,
        "rows": rows,
    }
    if info is not None:
        summary["info"] = _cloud_info_summary(info) if info else {}
    return summary


def _empty_cloud_folder_summary(path: str, exists: bool = False, status: int = 0, content_type: str = "") -> Dict[str, object]:
    return {
        "exists": exists,
        "path": _normalize_cloud_path(path),
        "folder_id": "",
        "info_status": status,
        "info_content_type": content_type,
        "browse_status": 0,
        "browse_content_type": "",
        "browse_ok": False,
        "item_count": 0,
        "folder_count": 0,
        "folders": [],
        "media_count": 0,
        "episodes": [],
        "missing_in_range": [],
        "media_items": [],
        "rows": [],
    }


def _public_cloud_folder_summary(summary: Dict[str, object]) -> Dict[str, object]:
    media_items = summary.get("media_items") if isinstance(summary.get("media_items"), list) else []
    return {
        "exists": bool(summary.get("exists")),
        "path": str(summary.get("path") or ""),
        "folder_id": str(summary.get("folder_id") or ""),
        "browse_ok": bool(summary.get("browse_ok")),
        "item_count": int(summary.get("item_count") or 0),
        "folder_count": int(summary.get("folder_count") or 0),
        "folders": list(summary.get("folders", []))[:20] if isinstance(summary.get("folders"), list) else [],
        "media_count": int(summary.get("media_count") or 0),
        "episodes": list(summary.get("episodes", [])) if isinstance(summary.get("episodes"), list) else [],
        "missing_in_range": list(summary.get("missing_in_range", [])) if isinstance(summary.get("missing_in_range"), list) else [],
        "sample_media": [str(item.get("name") or "") for item in media_items[:10] if isinstance(item, dict)],
    }


def _cloud_media_item_summary(row: Dict[str, object]) -> Dict[str, object]:
    name = _cloud_name(row)
    return {
        "name": name,
        "episode": _episode_number_from_text(name),
        "file_id": _cloud_file_id(row),
        "size": _format_size_value(_first_raw_present(row, ["size", "size_text", "file_size", "file_size_text", "s"])),
    }


def _scan_mv3_cloud_media_sidecars(
    client: MV3Client,
    root_id: str,
    root_path: str,
    storage: str,
    limit: int,
    max_depth: int,
) -> Dict[str, object]:
    warnings: List[str] = []
    folders: List[Dict[str, object]] = []
    metadata_sidecars: List[Dict[str, object]] = []
    queue: List[Tuple[str, str, int]] = [(root_id, root_path, 0)]
    visited: Set[str] = set()
    file_count = 0
    video_file_count = 0
    subtitle_sidecar_file_count = 0
    metadata_sidecar_file_count = 0
    other_file_count = 0
    truncated = False

    while queue:
        folder_id, folder_path, depth = queue.pop(0)
        if not folder_id or folder_id in visited:
            continue
        visited.add(folder_id)
        folder_payload, status, content_type = _read_cloud_folder_status(client, folder_id, storage, limit)
        rows = _cloud_rows(folder_payload)
        folder_summary = {
            "path": folder_path,
            "folder_id": folder_id,
            "status": status,
            "content_type": content_type,
            "item_count": len(rows),
            "depth": depth,
        }
        folders.append(folder_summary)
        if not (200 <= status < 300):
            warnings.append(f"cloud_folder_browse_failed:{folder_path or folder_id}:{status}")
            truncated = True
            continue
        if len(rows) >= limit:
            warnings.append(f"cloud_folder_browse_may_be_truncated:{folder_path or folder_id}")
            truncated = True
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = _cloud_name(row)
            child_path = _cloud_join_path(folder_path, name)
            kind = _cloud_item_kind(row)
            media_kind = _cloud_item_media_kind(row)
            if kind == "folder":
                child_id = _extract_folder_id(row)
                if child_id and depth < max_depth:
                    queue.append((child_id, child_path, depth + 1))
                elif child_id:
                    warnings.append(f"cloud_folder_max_depth_reached:{child_path}")
                    truncated = True
                continue
            if kind != "file":
                continue
            file_count += 1
            if media_kind == "video":
                video_file_count += 1
            elif media_kind == "subtitle_sidecar":
                subtitle_sidecar_file_count += 1
            elif media_kind == "metadata_sidecar":
                metadata_sidecar_file_count += 1
                if len(metadata_sidecars) < 50:
                    metadata_sidecars.append(
                        {
                            "path": child_path,
                            "name": name,
                            "file_id": _first_present(row, ["fid", "file_id", "id", "cid", "folder_id"]),
                            "size": _format_size_value(_first_raw_present(row, ["size", "size_text", "file_size", "file_size_text", "s"])),
                        }
                    )
            else:
                other_file_count += 1

    return {
        "visited_folder_count": len(visited),
        "file_count": file_count,
        "video_file_count": video_file_count,
        "subtitle_sidecar_file_count": subtitle_sidecar_file_count,
        "metadata_sidecar_file_count": metadata_sidecar_file_count,
        "other_file_count": other_file_count,
        "metadata_sidecars": metadata_sidecars,
        "folders": folders[:50],
        "truncated": truncated,
        "warnings": warnings,
    }


def _empty_cloud_sidecar_scan() -> Dict[str, object]:
    return {
        "visited_folder_count": 0,
        "file_count": 0,
        "video_file_count": 0,
        "subtitle_sidecar_file_count": 0,
        "metadata_sidecar_file_count": 0,
        "other_file_count": 0,
        "metadata_sidecars": [],
        "folders": [],
        "truncated": False,
        "warnings": [],
    }


def _protected_cloud_file_names_from_strm_root(strm_root: str, expected_cloud_prefix: str) -> Dict[str, object]:
    root = Path(strm_root) if strm_root else Path("__missing__")
    warnings: List[str] = []
    records: List[Dict[str, object]] = []
    names: Set[str] = set()
    if not root.exists():
        return {"root": str(root), "names": [], "records": [], "strm_files": [], "warnings": ["strm_root_missing"]}
    files = sorted(root.rglob("*.strm"))
    normalized_prefix = _normalize_cloud_path(expected_cloud_prefix)
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError as exc:
            warnings.append(f"strm_read_failed:{path}:{exc}")
            continue
        target = _cloud_path_from_strm_content(content)
        if not target:
            warnings.append(f"strm_target_path_missing:{path}")
            continue
        name = Path(urllib.parse.unquote(target)).name
        if normalized_prefix and not _path_has_prefix(_normalize_cloud_path(target), normalized_prefix):
            warnings.append(f"strm_target_prefix_mismatch:{path}")
        if name:
            names.add(name)
        records.append(
            {
                "strm_file": str(path),
                "episode": _episode_number_from_text(path.name),
                "target_path": _sanitize_cloud_path_for_report(target),
                "target_name": name,
            }
        )
    return {
        "root": str(root),
        "names": sorted(names),
        "records": records[:200],
        "strm_files": [str(item) for item in files[:200]],
        "warnings": warnings,
    }


def _cloud_path_from_strm_content(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.query:
        query = urllib.parse.parse_qs(parsed.query)
        values = query.get("path") or query.get("file") or query.get("source")
        if values:
            return urllib.parse.unquote(str(values[0]))
    if text.startswith("/"):
        return urllib.parse.unquote(text)
    return ""


def _sanitize_cloud_path_for_report(path: str) -> str:
    return urllib.parse.unquote(str(path or "")).split("&pickcode=", 1)[0]


def _public_cloud_duplicate_video_item(item: Dict[str, object], reason: str) -> Dict[str, object]:
    return {
        "name": str(item.get("name") or ""),
        "episode": item.get("episode"),
        "file_id": str(item.get("file_id") or ""),
        "size": str(item.get("size") or ""),
        "reason": reason,
    }


def _strm_title_summary(strm_root: str, title: str, wrong_root: str, correct_root: str) -> Dict[str, object]:
    title_dir = Path(strm_root) / title if strm_root and title else Path("__missing__")
    strm_files = sorted(title_dir.rglob("*.strm")) if title_dir.exists() else []
    episodes: List[int] = []
    wrong_target_count = 0
    correct_target_count = 0
    plain_series_root_count = 0
    samples = []
    normalized_wrong = _normalize_cloud_path(wrong_root)
    normalized_correct = _normalize_cloud_path(correct_root)
    for path in strm_files:
        name_episode = _episode_number_from_text(path.name)
        if name_episode is not None:
            episodes.append(name_episode)
        target = ""
        try:
            target = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            target = ""
        decoded_target = urllib.parse.unquote(target)
        if normalized_wrong and (normalized_wrong in target or normalized_wrong in decoded_target):
            wrong_target_count += 1
        wrong_target_present = bool(normalized_wrong and (normalized_wrong in target or normalized_wrong in decoded_target))
        correct_target_present = bool(normalized_correct and (normalized_correct in target or normalized_correct in decoded_target))
        if correct_target_present and not wrong_target_present:
            correct_target_count += 1
        if "/series/" in decoded_target and "/已整理/series/" not in decoded_target:
            plain_series_root_count += 1
        if len(samples) < 5:
            samples.append({"file": str(path), "episode": name_episode, "target_class": _classify_strm_target(decoded_target, normalized_wrong, normalized_correct)})
    distinct_episodes = sorted(set(episodes))
    return {
        "exists": title_dir.exists(),
        "title_dir": str(title_dir) if strm_root and title else "",
        "total_strm": len(strm_files),
        "episode_count": len(distinct_episodes),
        "episodes": distinct_episodes,
        "missing_in_range": _missing_episode_numbers(distinct_episodes),
        "wrong_target_count": wrong_target_count,
        "correct_target_count": correct_target_count,
        "plain_series_root_count": plain_series_root_count,
        "samples": samples,
    }


def _mv3_move_115(client: MV3Client, file_ids: List[str], target_cid: str, storage: str) -> Dict[str, object]:
    body: Dict[str, object] = {"file_ids": file_ids, "target_cid": target_cid}
    if storage:
        body["storage"] = storage
    status, headers, response_body = client.post_json("/api/v1/files/115/move", body)
    parsed = _parse_json(response_body.decode("utf-8", "replace"))
    payload = _unwrap_api_payload(parsed)
    api_success = _api_success(parsed)
    return {
        "endpoint": {"method": "POST", "path": "/api/v1/files/115/move"},
        "ok": 200 <= status < 300 and api_success,
        "http_ok": 200 <= status < 300,
        "api_success": api_success,
        "status": status,
        "response_content_type": _header(headers, "content-type"),
        "request_summary": {"file_id_count": len(file_ids), "target_cid": target_cid, "storage": storage},
        "response": _sanitize_json(payload if isinstance(payload, (dict, list)) else parsed),
    }


def _mv3_delete_115(client: MV3Client, file_ids: List[str], storage: str) -> Dict[str, object]:
    body: Dict[str, object] = {"file_ids": file_ids}
    if storage:
        body["storage"] = storage
    status, headers, response_body = client.post_json("/api/v1/files/115/delete", body)
    parsed = _parse_json(response_body.decode("utf-8", "replace"))
    payload = _unwrap_api_payload(parsed)
    api_success = _api_success(parsed)
    return {
        "endpoint": {"method": "POST", "path": "/api/v1/files/115/delete"},
        "ok": 200 <= status < 300 and api_success,
        "http_ok": 200 <= status < 300,
        "api_success": api_success,
        "status": status,
        "response_content_type": _header(headers, "content-type"),
        "request_summary": {"file_ids": file_ids, "storage": storage, "count": len(file_ids)},
        "response": _sanitize_json(payload if isinstance(payload, (dict, list)) else parsed),
    }


def _mv3_wrong_root_item_verified(
    decision: str,
    wrong: Dict[str, object],
    correct: Dict[str, object],
    strm: Dict[str, object],
    expected_count: int,
    write_executed: bool,
) -> bool:
    if not write_executed:
        return True
    correct_media_count = int(correct.get("media_count") or 0)
    strm_wrong_targets = int(strm.get("wrong_target_count") or 0)
    if decision in {"delete_duplicate_wrong_season", "move_wrong_media_to_correct_season"}:
        wrong_media_count = int(wrong.get("media_count") or 0)
        return wrong_media_count == 0 and correct_media_count >= expected_count and strm_wrong_targets == 0
    if decision == "empty_wrong_folder":
        return int(wrong.get("media_count") or 0) == 0
    return False


def _cloud_name(item: Dict[str, object]) -> str:
    return str(_first_raw_present(item, ["name", "file_name", "filename", "fn", "n", "title"]))


def _cloud_file_id(item: Dict[str, object]) -> str:
    for key in ("fid", "file_id", "id", "cid", "folder_id"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _looks_like_season_folder(name: str) -> bool:
    return bool(re.search(r"(?i)(^season\s*0*\d+$|^s0*\d+$|第\s*\d+\s*季)", name or ""))


def _is_media_name(name: str) -> bool:
    return Path(name).suffix.lower() in MEDIA_EXTENSIONS


def _classify_strm_target(target: str, wrong_root: str, correct_root: str) -> str:
    if wrong_root and wrong_root in target:
        return "wrong_root"
    if correct_root and correct_root in target:
        return "correct_root"
    if "/series/" in target:
        return "plain_series_root"
    if not target:
        return "empty"
    return "other"


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
        paths = value.get("paths")
        if isinstance(paths, list) and paths:
            nested = _extract_folder_id(paths[-1])
            if nested:
                return nested
        if value.get("parent_id") and value.get("parent_path") and _cloud_name(value):
            return str(value.get("parent_id"))
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
    name = _first_present(item, ["name", "file_name", "filename", "fn", "n", "title"])
    return {
        "index": index,
        "name": name,
        "kind": _cloud_item_kind(item),
        "media_kind": _cloud_item_media_kind(item),
        "episode": _episode_number_from_text(name),
        "size": _format_size_value(_first_raw_present(item, ["size", "size_text", "file_size", "file_size_text", "s"])),
        "file_id": _first_present(item, ["fid", "file_id", "id", "cid", "folder_id"]),
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
    if _looks_like_115_fid_folder(item):
        return "folder"
    if str(item.get("fid") or ""):
        return "file"
    if str(item.get("cid") or item.get("folder_id") or ""):
        return "folder"
    return raw_type or "unknown"


def _looks_like_115_fid_folder(item: Dict[str, object]) -> bool:
    if not str(item.get("fid") or ""):
        return False
    name = _cloud_name(item)
    if Path(name).suffix:
        return False
    for key in ("size", "size_text", "file_size", "file_size_text", "s", "fs", "sha1"):
        value = item.get(key)
        if value not in (None, "", 0, "0"):
            return False
    if str(item.get("ico") or "").strip():
        return False
    if str(item.get("ftype") or "").strip():
        return False
    return True


def _cloud_item_media_kind(item: Dict[str, object]) -> str:
    kind = _cloud_item_kind(item)
    if kind != "file":
        return kind
    suffix = Path(_cloud_name(item)).suffix.lower()
    if suffix in MEDIA_EXTENSIONS:
        return "video"
    if suffix in SIDECAR_EXTENSIONS:
        return "subtitle_sidecar"
    if suffix in METADATA_SIDECAR_EXTENSIONS:
        return "metadata_sidecar"
    return "file"


def _cloud_info_summary(info: Dict[str, object]) -> Dict[str, object]:
    name = _first_present(info, ["name", "file_name", "filename", "fn", "n", "title"])
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
        "share_code_available": bool(_first_raw_present(item, ["share_code", "shareId", "share_id"])),
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
    raw_response = _parse_json(response_body.decode("utf-8", "replace"))
    api_message = _first_present(raw_response, ["message", "msg", "detail", "error"]) if isinstance(raw_response, dict) else ""
    api_code = _first_present(raw_response, ["code", "errcode", "error_code"]) if isinstance(raw_response, dict) else ""
    return {
        "endpoint": {"method": method, "path": path},
        "ok": 200 <= status < 300 and api_success,
        "http_ok": 200 <= status < 300,
        "api_success": api_success,
        "api_code": _sanitize_json(api_code),
        "api_message": _sanitize_json(api_message),
        "status": status,
        "response_content_type": _header(headers, "content-type"),
        "response_body_bytes": len(response_body),
        "request": _sanitize_json(request_body),
        "response_shape": _json_shape(payload),
        "response_count": _json_count(payload),
        "sample": _sanitize_json(_sample_json(payload, max_items=10, max_keys=30)) if isinstance(payload, (dict, list)) else _sanitize_json(payload),
    }


def _mv3_api_error_summary(
    method: str,
    path: str,
    request_body: Dict[str, object],
    exc: BaseException,
) -> Dict[str, object]:
    return {
        "endpoint": {"method": method, "path": path},
        "ok": False,
        "http_ok": False,
        "api_success": False,
        "status": 0,
        "error_type": type(exc).__name__,
        "error": str(exc),
        "request": _sanitize_json(request_body),
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
    browse_cid: str,
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
            if browse_cid:
                browse_body["cid"] = browse_cid
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
        "browse_cid": browse_cid,
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


def _browse_report_item_media_kind(item: Dict[str, object]) -> str:
    raw_kind = str(item.get("media_kind") or "").lower()
    if raw_kind in {"video", "subtitle_sidecar", "metadata_sidecar"}:
        return raw_kind
    name = str(item.get("name") or item.get("path") or "")
    suffix = Path(name).suffix.lower()
    if suffix in MEDIA_EXTENSIONS:
        return "video"
    if suffix in SIDECAR_EXTENSIONS:
        return "subtitle_sidecar"
    if suffix in METADATA_SIDECAR_EXTENSIONS:
        return "metadata_sidecar"
    return raw_kind or "file"


def _browse_report_item_summary(item: Dict[str, object], index: int) -> Dict[str, object]:
    name = str(item.get("name") or "")
    return {
        "index": index,
        "name": name,
        "kind": str(item.get("kind") or ""),
        "media_kind": _browse_report_item_media_kind(item),
        "episode": item.get("episode") or _episode_number_from_text(name),
        "size": str(item.get("size") or ""),
        "file_id": str(item.get("file_id") or ""),
    }


def _transfer_files_from_cloud_browse_items(items: List[Dict[str, object]], source_path: str) -> List[Dict[str, object]]:
    files: List[Dict[str, object]] = []
    normalized_source = source_path.rstrip("/")
    for item in items:
        name = str(item.get("name") or "")
        if not name:
            continue
        source_file_id = str(item.get("file_id") or "")
        item_path = f"{normalized_source}/{name}" if normalized_source else name
        files.append(
            {
                "source_path": item_path,
                "source_file_id": source_file_id,
                "is_cloud_source": True,
                "name": name,
            }
        )
    return files


def _organize_transfer_request_summary(request_body: Dict[str, object]) -> Dict[str, object]:
    files = request_body.get("files") if isinstance(request_body.get("files"), list) else []
    return {
        "endpoint": {"method": "POST", "path": "/api/v1/organize/transfer"},
        "target_dir": request_body.get("target_dir") or "",
        "strm_dir": request_body.get("strm_dir") or "",
        "tmdb_id": request_body.get("tmdb_id") or 0,
        "is_cloud_target": bool(request_body.get("is_cloud_target")),
        "mode": request_body.get("mode") or "",
        "background": bool(request_body.get("background")),
        "file_count": len(files),
        "files": [
            {
                "source_path": str(file.get("source_path") or ""),
                "source_file_id": str(file.get("source_file_id") or ""),
                "is_cloud_source": bool(file.get("is_cloud_source")),
            }
            for file in files[:100]
            if isinstance(file, dict)
        ],
    }


def _organize_completion_verification_hint(
    target_dir: str,
    strm_dir: str,
    tmdb_id: int,
    expected_episode_count: int,
    expected_episode_min: int,
    expected_episode_max: int,
    expected_episodes: List[int],
    episodes: List[int],
    transfer_report: Dict[str, object],
) -> Dict[str, object]:
    if transfer_report.get("skipped"):
        status = "not_submitted"
        required_followup: List[str] = []
    elif transfer_report.get("ok"):
        status = "confirmed_success"
        required_followup = ["mv3-cloud-browse organized season", "strm-verify"]
    elif transfer_report.get("error_type") in {"TimeoutError", "timeout"}:
        status = "unverified_after_timeout"
        required_followup = ["mv3-cloud-browse organized season", "strm-verify before any cleanup"]
    else:
        status = "failed"
        required_followup = []
    return {
        "status": status,
        "target_dir": target_dir,
        "strm_dir": strm_dir,
        "tmdb_id": tmdb_id,
        "expected_episode_count": expected_episode_count,
        "expected_episode_min": expected_episode_min,
        "expected_episode_max": expected_episode_max,
        "expected_episodes": expected_episodes,
        "request_episodes": episodes,
        "required_followup": required_followup,
        "requires_followup_before_cleanup": bool(required_followup),
        "note": "A timeout means the HTTP client stopped waiting; MV3 may still complete the organize job. Treat it as unverified until cloud browse and STRM verification pass.",
    }


def _strm_generate_request_summary(request_body: Dict[str, object]) -> Dict[str, object]:
    return {
        "endpoint": {"method": "POST", "path": "/api/v1/strm/generate"},
        "source_dir": request_body.get("source_dir") or "",
        "target_dir": request_body.get("target_dir") or "",
        "storage": request_body.get("storage") or "",
        "cloud": bool(request_body.get("cloud")),
        "incremental": bool(request_body.get("incremental")),
        "overwrite": bool(request_body.get("overwrite")),
        "organize": bool(request_body.get("organize")),
        "openlist": bool(request_body.get("openlist")),
        "enable_primary_category": bool(request_body.get("enable_primary_category")),
        "enable_secondary_category": bool(request_body.get("enable_secondary_category")),
        "template_configured": bool(request_body.get("template")),
    }


def _strm_records_regenerate_request_summary(request_body: Dict[str, object]) -> Dict[str, object]:
    record_ids = request_body.get("record_ids") if isinstance(request_body.get("record_ids"), list) else []
    return {
        "endpoint": {"method": "POST", "path": "/api/v1/strm/records/regenerate"},
        "record_ids": [int(record_id) for record_id in record_ids if isinstance(record_id, int)],
        "record_count": len(record_ids),
    }


def _strm_records_redirect_request_summary(request_body: Dict[str, object]) -> Dict[str, object]:
    record_ids = request_body.get("record_ids") if isinstance(request_body.get("record_ids"), list) else []
    return {
        "endpoint": {"method": "POST", "path": "/api/v1/strm/records/redirect"},
        "old_prefix": request_body.get("old_prefix") or "",
        "new_prefix": request_body.get("new_prefix") or "",
        "strm_dir": request_body.get("strm_dir") or "",
        "record_ids": [int(record_id) for record_id in record_ids if isinstance(record_id, int)],
        "record_count": len(record_ids),
    }


def _strm_record_rows(payload: object) -> List[Dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "records", "list", "data", "results", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _strm_record_rows(nested)
    return []


def _strm_record_pagination(payload: object) -> Dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    summary: Dict[str, object] = {}
    for key in ("page", "page_size", "total", "total_count", "pages", "count"):
        if key in payload:
            summary[key] = payload.get(key)
    nested = payload.get("pagination")
    if isinstance(nested, dict):
        for key in ("page", "page_size", "total", "total_count", "pages", "count"):
            if key in nested and key not in summary:
                summary[key] = nested.get(key)
    return summary


def _strm_record_id(row: Dict[str, object]) -> int:
    value = _first_raw_present(row, ["id", "record_id", "recordId"])
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _strm_record_summary(row: Dict[str, object]) -> Dict[str, object]:
    strm_path = str(_first_present(row, ["strm_path", "strmPath", "path", "file_path", "filePath"]))
    source_path = str(_first_present(row, ["source_path", "sourcePath", "target_path", "targetPath", "src_path", "srcPath"]))
    title = str(_first_present(row, ["title", "name", "media_title", "mediaTitle"]))
    episode = _episode_number_from_text(" ".join([strm_path, source_path, title]))
    strm_content = _first_raw_present(row, ["strm_content", "strmContent", "content"])
    return {
        "id": _strm_record_id(row),
        "title": title,
        "episode": episode,
        "source": str(_first_present(row, ["source", "source_type", "sourceType", "record_source", "recordSource"])),
        "strm_path": strm_path,
        "source_path": source_path,
        "strm_content": strm_content,
        "strm_content_present": bool(strm_content),
        "strm_content_sha256": hashlib.sha256(strm_content.encode("utf-8")).hexdigest() if strm_content else "",
        "pickcode_present": bool(_first_present(row, ["pickcode", "pick_code", "pickCode"])),
        "exists_hint": _first_present(row, ["exists", "file_exists", "fileExists", "is_exists", "isExists", "status"]),
        "raw": _sanitize_json(_sample_json(row, max_keys=30)),
    }


def _validate_redirect_record_set(
    records: List[Dict[str, object]],
    expected_ids: List[int],
    expected_strm_prefix: str,
    expected_source_prefix: str,
    blockers: List[str],
    phase: str,
) -> None:
    found_ids = sorted({int(record.get("id") or 0) for record in records})
    if found_ids != sorted(expected_ids):
        blockers.append(f"{phase}_record_ids_mismatch")
    for record in records:
        strm_path = str(record.get("strm_path") or "")
        source_path = str(record.get("source_path") or "")
        if expected_strm_prefix and not _path_has_prefix(strm_path, expected_strm_prefix):
            blockers.append(f"{phase}_strm_path_prefix_mismatch")
        if expected_source_prefix and not _path_has_prefix(source_path, expected_source_prefix):
            blockers.append(f"{phase}_source_path_prefix_mismatch")


def _validate_redirect_mutation_result(payload: object, expected_count: int, blockers: List[str]) -> None:
    counts = _redirect_payload_counts(payload)
    skipped = int(counts.get("skipped") or 0)
    failed = int(counts.get("failed") or 0)
    changed = int(counts.get("success") or counts.get("updated") or counts.get("changed") or 0)
    if failed:
        blockers.append("mv3_strm_records_redirect_failed_records")
    if skipped:
        blockers.append("mv3_strm_records_redirect_skipped_records")
    if expected_count and changed not in (0, expected_count):
        blockers.append("mv3_strm_records_redirect_partial_success")
    if expected_count and changed == 0:
        blockers.append("mv3_strm_records_redirect_no_records_changed")


def _redirect_payload_counts(payload: object) -> Dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    counts: Dict[str, int] = {}
    for key in ("success", "failed", "skipped", "updated", "changed"):
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        try:
            counts[key] = int(value)
        except (TypeError, ValueError):
            pass
    return counts


def _expected_redirect_paths(records: List[Dict[str, object]], old_prefix: str, new_prefix: str) -> Dict[int, str]:
    expected: Dict[int, str] = {}
    for record in records:
        record_id = int(record.get("id") or 0)
        strm_path = str(record.get("strm_path") or "")
        if record_id and _path_has_prefix(strm_path, old_prefix):
            expected[record_id] = _replace_path_prefix(strm_path, old_prefix, new_prefix)
    return expected


def _validate_redirect_expected_paths(records: List[Dict[str, object]], expected_paths: Dict[int, str], blockers: List[str]) -> None:
    if not expected_paths:
        return
    by_id = {int(record.get("id") or 0): str(record.get("strm_path") or "") for record in records}
    for record_id, expected_path in expected_paths.items():
        if by_id.get(record_id) != expected_path:
            blockers.append("after_strm_path_expected_rewrite_mismatch")
            return


def _replace_path_prefix(path: str, old_prefix: str, new_prefix: str) -> str:
    old_prefix = old_prefix.rstrip("/")
    new_prefix = new_prefix.rstrip("/")
    if path == old_prefix:
        return new_prefix
    suffix = path[len(old_prefix) :].lstrip("/")
    return new_prefix + ("/" + suffix if suffix else "")


def _path_has_prefix(path: str, prefix: str) -> bool:
    path = str(path or "").rstrip("/")
    prefix = str(prefix or "").rstrip("/")
    return bool(prefix and (path == prefix or path.startswith(prefix + "/")))


def _strm_redirect_records_summary(records: List[Dict[str, object]], expected_prefix: str, expected_paths: Optional[Dict[int, str]] = None) -> Dict[str, object]:
    expected_prefix = expected_prefix.rstrip("/")
    matching = [
        record
        for record in records
        if _path_has_prefix(str(record.get("strm_path") or ""), expected_prefix)
    ]
    expected_paths = expected_paths or {}
    expected_rewrite_matches = [
        record
        for record in records
        if expected_paths.get(int(record.get("id") or 0)) == str(record.get("strm_path") or "")
    ]
    episodes = sorted({int(record.get("episode") or 0) for record in records if int(record.get("episode") or 0) > 0})
    return {
        "record_count": len(records),
        "matching_prefix_count": len(matching),
        "expected_rewrite_match_count": len(expected_rewrite_matches),
        "episodes": episodes,
        "sample_paths": [str(record.get("strm_path") or "") for record in records[:5]],
    }


def _materialize_strm_record(
    record: Dict[str, object],
    expected_strm_prefix: str,
    expected_source_prefix: str,
    host_strm_prefix: str,
    rewrite_strm_prefix: str,
    overwrite: bool,
) -> Dict[str, object]:
    blockers: List[str] = []
    warnings: List[str] = []
    record_id = int(record.get("id") or 0)
    strm_path = str(record.get("strm_path") or "")
    original_strm_path = strm_path
    source_path = str(record.get("source_path") or "")
    content = str(record.get("strm_content") or "")
    expected_strm_prefix = expected_strm_prefix.rstrip("/")
    expected_source_prefix = expected_source_prefix.rstrip("/")
    rewrite_from, rewrite_to = _parse_strm_rewrite_prefix(rewrite_strm_prefix)
    if rewrite_strm_prefix and (not rewrite_from or not rewrite_to):
        blockers.append("rewrite_strm_prefix_invalid")
    elif rewrite_from:
        if strm_path == rewrite_from:
            strm_path = rewrite_to
        elif strm_path.startswith(rewrite_from.rstrip("/") + "/"):
            strm_path = rewrite_to.rstrip("/") + "/" + strm_path[len(rewrite_from.rstrip("/")) :].lstrip("/")
        else:
            blockers.append("rewrite_strm_prefix_mismatch")

    host_prefix, mv3_prefix = _parse_host_strm_prefix(host_strm_prefix)
    host_path = ""
    if not strm_path:
        blockers.append("strm_path_required")
    if not content:
        blockers.append("strm_content_required")
    if expected_strm_prefix and not strm_path.startswith(expected_strm_prefix.rstrip("/") + "/") and strm_path != expected_strm_prefix:
        blockers.append("strm_path_prefix_mismatch")
    if expected_source_prefix and not source_path.startswith(expected_source_prefix.rstrip("/") + "/") and source_path != expected_source_prefix:
        blockers.append("source_path_prefix_mismatch")
    if not host_prefix or not mv3_prefix:
        blockers.append("host_strm_prefix_required")
    elif strm_path and strm_path != mv3_prefix and not strm_path.startswith(mv3_prefix.rstrip("/") + "/"):
        blockers.append("host_strm_prefix_mismatch")
    elif strm_path:
        suffix = strm_path[len(mv3_prefix.rstrip("/")) :].lstrip("/")
        host_path = str(Path(host_prefix) / suffix)
        if not Path(host_path).is_absolute():
            blockers.append("host_path_not_absolute")
    if host_path and Path(host_path).exists() and not overwrite:
        blockers.append("target_file_exists")

    action = "skipped"
    bytes_written = 0
    content_bytes = content.encode("utf-8")
    sha256 = hashlib.sha256(content_bytes).hexdigest() if content else ""
    if not blockers:
        target = Path(host_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content_bytes if content.endswith("\n") else content_bytes + b"\n")
        bytes_written = target.stat().st_size
        action = "written"
        if bytes_written == 0:
            blockers.append("written_file_empty")

    return {
        "ok": not blockers and action == "written",
        "record_id": record_id,
        "action": action,
        "strm_path": strm_path,
        "original_strm_path": original_strm_path,
        "source_path": source_path,
        "host_path": host_path,
        "bytes_written": bytes_written,
        "sha256": sha256,
        "overwrite": overwrite,
        "warnings": sorted(set(warnings)),
        "blockers": sorted(set(blockers)),
    }


def _parse_host_strm_prefix(value: str) -> Tuple[str, str]:
    if "=" not in value:
        return "", ""
    host_prefix, mv3_prefix = value.split("=", 1)
    return host_prefix.rstrip("/"), mv3_prefix.rstrip("/")


def _parse_strm_rewrite_prefix(value: str) -> Tuple[str, str]:
    if "=" not in value:
        return "", ""
    source_prefix, target_prefix = value.split("=", 1)
    return source_prefix.rstrip("/"), target_prefix.rstrip("/")


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
    match = re.search(r"(?i)(?:^|[\s._\-\[\(])E(?:P)?(\d{1,3})(?=$|[\s._\-\]\)])", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:第\s*)?(\d{1,3})(?:\s*[集话話])", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(?:^|[\s._\-\[\(])0*(\d{1,3})(?=$|[\s._\-\]\)])", text)
    if match:
        episode = int(match.group(1))
        if 1 <= episode <= 999:
            return episode
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


def _share_receive_items(
    browse_items: List[Dict[str, object]],
    browse_selection: Dict[str, object],
    receive_all_files: bool,
) -> List[Dict[str, object]]:
    if receive_all_files:
        return [
            item
            for item in browse_items
            if _share_item_kind(item) == "file" and not _share_item_is_metadata_sidecar(item)
        ]
    if browse_selection and not _share_item_is_metadata_sidecar(browse_selection):
        return [browse_selection]
    return []


def _share_metadata_sidecars_excluded_from_receive(
    browse_items: List[Dict[str, object]],
    browse_selection: Dict[str, object],
    receive_all_files: bool,
) -> List[Dict[str, object]]:
    if receive_all_files:
        return [
            item
            for item in browse_items
            if _share_item_kind(item) == "file" and _share_item_is_metadata_sidecar(item)
        ]
    if browse_selection and _share_item_is_metadata_sidecar(browse_selection):
        return [browse_selection]
    return []


def _share_item_name(item: Dict[str, object]) -> str:
    return _first_present(item, ["name", "file_name", "filename", "fn", "n", "title"])


def _share_item_is_video(item: Dict[str, object]) -> bool:
    return Path(_share_item_name(item)).suffix.lower() in MEDIA_EXTENSIONS


def _share_item_is_sidecar(item: Dict[str, object]) -> bool:
    return Path(_share_item_name(item)).suffix.lower() in SIDECAR_EXTENSIONS


def _share_item_is_metadata_sidecar(item: Dict[str, object]) -> bool:
    return Path(_share_item_name(item)).suffix.lower() in METADATA_SIDECAR_EXTENSIONS


def _share_browse_item_summary(item: Dict[str, object], index: int) -> Dict[str, object]:
    name = _share_item_name(item)
    return {
        "index": index,
        "name": name,
        "kind": _share_item_kind(item),
        "media_kind": _share_item_media_kind(item),
        "episode": _episode_number_from_text(name),
        "size": _format_size_value(_first_raw_present(item, ["size", "size_text", "file_size", "file_size_text", "s"])),
        "file_id": _share_item_file_id(item),
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


def _share_item_media_kind(item: Dict[str, object]) -> str:
    if _share_item_kind(item) != "file":
        return _share_item_kind(item)
    if _share_item_is_video(item):
        return "video"
    if _share_item_is_sidecar(item):
        return "subtitle_sidecar"
    if _share_item_is_metadata_sidecar(item):
        return "metadata_sidecar"
    return "file"


def _share_item_file_id(item: Dict[str, object]) -> str:
    for key in ("file_id", "fid", "id", "cid", "folder_id"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _normalize_cloud_path(path: str) -> str:
    segments = [segment for segment in str(path or "").strip().strip("/").split("/") if segment]
    return "/" + "/".join(segments) if segments else ""


def _cloud_join_path(parent: str, name: str) -> str:
    parent_path = _normalize_cloud_path(parent) if parent else ""
    clean_name = str(name or "").strip().strip("/")
    if not clean_name:
        return parent_path
    if not parent_path:
        return f"/{clean_name}"
    return f"{parent_path}/{clean_name}"


def _looks_like_mv3_category_dir(path: str) -> bool:
    tail = (path or "").rstrip("/").rsplit("/", 1)[-1].lower()
    return tail in {"series", "movie", "movies", "anime", "tv", "电视剧", "电影", "动漫"}


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
