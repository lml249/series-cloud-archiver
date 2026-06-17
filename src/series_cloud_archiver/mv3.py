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
    r"(token|cookie|password|passwd|secret|authorization|api[_-]?key|access[_-]?key|refresh|pickcode|sign|credential|user[_-]?id|user[_-]?name|phone|email|vip)",
    re.IGNORECASE,
)
SENSITIVE_URL_KEY_RE = re.compile(r"(direct|download|redirect|play|stream|thumb|cover|url|uri|link)", re.IGNORECASE)
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
    status, _headers, body = client.get(f"/api/v1/files/115/list?{query}")
    if not (200 <= status < 300):
        return {}
    parsed = _parse_json(body.decode("utf-8", "replace"))
    payload = _unwrap_api_payload(parsed)
    rows = []
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        rows = payload["data"]
    elif isinstance(payload, list):
        rows = payload
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
