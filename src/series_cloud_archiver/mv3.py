from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple


DEFAULT_PROBE_PATHS = ["/", "/api", "/api/v1", "/openapi.json", "/api/v1/openapi.json"]
SENSITIVE_METHOD_HINTS = ("delete", "remove", "transfer", "save", "move", "rename", "strm", "download")


class MV3Client:
    def __init__(self, base_url: str, token: str = "", timeout: int = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def get(self, path: str) -> Tuple[int, Dict[str, str], bytes]:
        url = self._url(path)
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, dict(response.headers.items()), response.read(1024 * 1024)
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read(64 * 1024)

    def _url(self, path: str) -> str:
        query = {}
        if self.token:
            query["token"] = self.token
        url = f"{self.base_url}{path if path.startswith('/') else '/' + path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url


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


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _safety_text() -> str:
    return "readonly GET probe only; no MV3 transfer, STRM generation, save, move, rename, or delete endpoint is called"
