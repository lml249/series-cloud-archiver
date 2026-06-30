from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set


DEFAULT_TRANSFER_STATUSES = ["cloud_strm_not_found"]
DEFAULT_CLOUD_ROOT = "/已整理/series"
DEFAULT_STRM_ROOT = "/strm"
OFFLINE_DESTINATION_MODES = {"season", "root"}
MV3_PREVIEW_ENDPOINT = {"method": "POST", "path": "/api/v1/media-transfer/preview"}
MV3_OFFLINE_ENDPOINT = {"method": "POST", "path": "/api/v1/files/115/offline/add"}
MV3_STRM_GENERATE_ENDPOINT = {"method": "POST", "path": "/api/v1/strm/generate"}
FORBIDDEN_EXECUTION_ENDPOINTS = [
    "POST /api/v1/media-transfer/execute",
    "POST /api/v1/strm/generate",
    "POST /api/v1/files/115/offline/add",
    "POST /api/v1/files/115/offline/add_bt",
    "POST /api/v1/files/115/copy",
    "POST /api/v1/files/115/delete",
    "POST /api/v1/files/115/move",
    "DELETE /api/v1/strm/records/{record_id}",
]
TITLE_STOP_TOKENS = {"a", "an", "and", "in", "of", "on", "the", "to", "with"}
TECHNICAL_TOKENS = {
    "1080p",
    "2160p",
    "aac",
    "ac3",
    "adweb",
    "atmos",
    "bluray",
    "chdweb",
    "ddp",
    "dovi",
    "dts",
    "dv",
    "h264",
    "h265",
    "hdr",
    "hhweb",
    "hevc",
    "iq",
    "dl",
    "nf",
    "ourtv",
    "season",
    "web",
    "webdl",
    "x264",
    "x265",
}
TMDBID_PATTERN = re.compile(r"\{tmdbid=\d+\}", re.IGNORECASE)
YEAR_SUFFIX_PATTERN = re.compile(r"\(\d{4}\)")
YEAR_VALUE_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
SEASON_TOKEN_PATTERN = re.compile(r"(?i)^s\d{1,2}$")
EPISODE_TOKEN_PATTERN = re.compile(r"(?i)^e\d{1,3}$")
CJK_TITLE_PATTERN = re.compile(r"(?:[0-9０-９]+)?[\u4e00-\u9fff]+(?:[0-9０-９]+|[·・][\u4e00-\u9fff]+|[\u4e00-\u9fff]+)*")
TV_SIGNAL_PATTERN = re.compile(
    r"(?i)(\bS\d{1,2}\b|\bS\d{1,2}\s*[-~_]\s*S?\d{1,2}\b|\bE\d{1,3}\b|第\s*\d{1,3}\s*[季集话話]|全\s*\d{1,4}\s*[集话話]|全集|完结|complete)"
)


def load_cloud_check_report(path: str) -> Dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_mv3_transfer_plan(path: str) -> Dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_optional_json_report(path: Optional[str]) -> Optional[Dict[str, object]]:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def plan_mv3_transfers_from_cloud_report(
    cloud_report: Dict[str, object],
    statuses: Iterable[str] = DEFAULT_TRANSFER_STATUSES,
    top: int = 0,
) -> Dict[str, object]:
    wanted = {status for status in statuses if status}
    items = []
    for item in cloud_report.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("status") not in wanted:
            continue
        if not int(item.get("tmdbid") or 0) or not int(item.get("season") or 0):
            continue
        items.append(_transfer_item(item))

    items.sort(key=lambda item: (-int(item["size_bytes"]), str(item["title"]), int(item["season"])))
    total_items = len(items)
    if top > 0:
        items = items[:top]

    return {
        "mode": "readonly-mv3-transfer-plan",
        "source_mode": cloud_report.get("mode", ""),
        "included_statuses": sorted(wanted),
        "total_planned": total_items,
        "total_size_bytes": sum(int(item["size_bytes"]) for item in items),
        "status_counts": dict(sorted(Counter(item["source_status"] for item in items).items())),
        "items": items,
        "warnings": list(cloud_report.get("warnings", [])) if isinstance(cloud_report.get("warnings"), list) else [],
        "safety": "readonly plan only; no MV3 transfer, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed",
    }


def render_mv3_transfer_plan(plan: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(plan, ensure_ascii=False, indent=2)
    return _render_markdown(plan)


def plan_mv3_restored_transfer_queue(
    cloud_report: Dict[str, object],
    transfer_plan: Optional[Dict[str, object]] = None,
    historical_scan: Optional[Dict[str, object]] = None,
    mv3_report: Optional[Dict[str, object]] = None,
    top: int = 0,
) -> Dict[str, object]:
    cloud_items = [item for item in cloud_report.get("items", []) if isinstance(item, dict)]
    transfer_items = [item for item in (transfer_plan or {}).get("items", []) if isinstance(item, dict)]
    transfer_by_identity = {
        (int(item.get("tmdbid") or 0), int(item.get("season") or 0)): item
        for item in transfer_items
        if int(item.get("tmdbid") or 0) and int(item.get("season") or 0)
    }
    transfer_by_title = {str(item.get("title") or ""): item for item in transfer_items if str(item.get("title") or "")}

    ready = []
    identity_review = []
    for item in cloud_items:
        status = str(item.get("status") or "")
        tmdbid = int(item.get("tmdbid") or 0)
        season = int(item.get("season") or 0)
        transfer_item = transfer_by_identity.get((tmdbid, season)) or transfer_by_title.get(str(item.get("title") or "")) or {}
        if status == "cloud_strm_not_found" and tmdbid and season:
            ready.append(_restored_queue_item(item, transfer_item, "cloud_strm_not_found"))
        elif status == "needs_identity_review" or not tmdbid or not season:
            identity_review.append(_restored_queue_item(item, transfer_item, "needs_identity_review_before_transfer"))

    ready.sort(key=lambda row: (-int(row.get("size_bytes") or 0), str(row.get("title") or ""), int(row.get("season") or 0)))
    identity_review.sort(key=lambda row: (-int(row.get("size_bytes") or 0), str(row.get("title") or ""), int(row.get("season") or 0)))
    historical = _historical_candidates(historical_scan)
    row_limit = max(0, int(top or 0))

    return {
        "mode": "readonly-mv3-restored-transfer-queue",
        "source_mode": cloud_report.get("mode", ""),
        "current_items": len(cloud_items),
        "summary": {
            "ready_when_mv3_restored": len(ready),
            "needs_identity_review": len(identity_review),
            "historical_candidate_for_cloud_check": len(historical),
        },
        "mv3_status": _mv3_status_summary(mv3_report),
        "ready_when_mv3_restored": _limit_rows(ready, row_limit),
        "needs_identity_review_before_transfer": _limit_rows(identity_review, row_limit),
        "historical_candidate_samples": _limit_rows(historical, row_limit or 20),
        "row_limit": row_limit,
        "warnings": _restored_queue_warnings(cloud_report, transfer_plan, historical_scan, mv3_report),
        "safety": (
            "readonly queue only; no MV3 search, share receive, organize transfer, STRM generation, "
            "qBittorrent action, MoviePilot cleanup, Emby refresh, cloud write, hlink deletion, or filesystem deletion is performed"
        ),
    }


def render_mv3_restored_transfer_queue(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    return _render_restored_transfer_queue_markdown(report)


def plan_mv3_preview_manifest(
    transfer_plan: Dict[str, object],
    instances_report: Optional[Dict[str, object]] = None,
    capabilities_report: Optional[Dict[str, object]] = None,
    limit: int = 10,
    cloud_root: str = DEFAULT_CLOUD_ROOT,
    instance: str = "",
) -> Dict[str, object]:
    raw_items = [item for item in transfer_plan.get("items", []) if isinstance(item, dict)]
    selected_items = raw_items[: limit if limit > 0 else len(raw_items)]
    context = _mv3_manifest_context(instances_report, capabilities_report, cloud_root, instance)
    items = [
        _preview_manifest_item(index, item, context)
        for index, item in enumerate(selected_items, start=1)
    ]
    warnings = []
    if isinstance(transfer_plan.get("warnings"), list):
        warnings.extend(str(item) for item in transfer_plan["warnings"])
    warnings.extend(context.get("warnings", []))
    return {
        "mode": "readonly-mv3-preview-manifest",
        "source_mode": transfer_plan.get("mode", ""),
        "available_items": len(raw_items),
        "planned_items": len(items),
        "limit": limit,
        "total_size_bytes": sum(int(item.get("size_bytes") or 0) for item in items),
        "mv3_context": context,
        "items": items,
        "forbidden_endpoints": FORBIDDEN_EXECUTION_ENDPOINTS,
        "warnings": warnings,
        "safety": "readonly manifest only; no MV3 preview, transfer execute, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed",
    }


def render_mv3_preview_manifest(manifest: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(manifest, ensure_ascii=False, indent=2)
    return _render_preview_manifest_markdown(manifest)


def plan_mv3_offline_manifest(
    transfer_plan: Dict[str, object],
    qb_torrents: List[Dict[str, object]],
    instances_report: Optional[Dict[str, object]] = None,
    limit: int = 10,
    cloud_root: str = DEFAULT_CLOUD_ROOT,
    strm_root: str = DEFAULT_STRM_ROOT,
    min_seed_days: int = 7,
    destination_mode: str = "season",
) -> Dict[str, object]:
    if destination_mode not in OFFLINE_DESTINATION_MODES:
        raise ValueError(f"destination_mode must be one of {sorted(OFFLINE_DESTINATION_MODES)}")
    raw_items = [item for item in transfer_plan.get("items", []) if isinstance(item, dict)]
    selected_items = raw_items[: limit if limit > 0 else len(raw_items)]
    context = _mv3_offline_context(instances_report, cloud_root, strm_root)
    items = [
        _offline_manifest_item(index, item, qb_torrents, context, min_seed_days, destination_mode)
        for index, item in enumerate(selected_items, start=1)
    ]
    warnings = []
    if isinstance(transfer_plan.get("warnings"), list):
        warnings.extend(str(item) for item in transfer_plan["warnings"])
    warnings.extend(context.get("warnings", []))
    return {
        "mode": "readonly-mv3-offline-manifest",
        "source_mode": transfer_plan.get("mode", ""),
        "available_items": len(raw_items),
        "planned_items": len(items),
        "limit": limit,
        "total_size_bytes": sum(int(item.get("size_bytes") or 0) for item in items),
        "mv3_context": context,
        "min_seed_days": min_seed_days,
        "destination_mode": destination_mode,
        "items": items,
        "forbidden_endpoints": [
            "POST /api/v1/files/115/offline/add",
            "POST /api/v1/files/115/offline/add_bt",
            "POST /api/v1/strm/generate",
            "POST /api/v1/files/115/delete",
            "POST /api/v1/files/115/move",
            "DELETE /api/v1/strm/records/{record_id}",
        ],
        "warnings": warnings,
        "safety": "readonly offline manifest only; no MV3 offline task, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed; magnet URIs are not written to reports",
    }


def render_mv3_offline_manifest(manifest: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(manifest, ensure_ascii=False, indent=2)
    return _render_offline_manifest_markdown(manifest)


def plan_mv3_share_search_from_transfer_plan(
    transfer_plan: Dict[str, object],
    search_reports: Dict[str, Dict[str, object]],
    limit: int = 10,
    max_candidates: int = 5,
    offset: int = 0,
) -> Dict[str, object]:
    raw_items = [item for item in transfer_plan.get("items", []) if isinstance(item, dict)]
    start = max(0, offset)
    stop = start + limit if limit > 0 else len(raw_items)
    selected_items = raw_items[start:stop]
    items = [
        _share_search_plan_item(index, item, search_reports.get(str(item.get("title") or ""), {}), max_candidates)
        for index, item in enumerate(selected_items, start=start + 1)
    ]
    ready_count = sum(1 for item in items if item.get("recommended_candidate"))
    return {
        "mode": "readonly-mv3-share-search-plan",
        "source_mode": transfer_plan.get("mode", ""),
        "available_items": len(raw_items),
        "planned_items": len(items),
        "ready_items": ready_count,
        "limit": limit,
        "offset": offset,
        "max_candidates": max_candidates,
        "total_size_bytes": sum(int(item.get("size_bytes") or 0) for item in items),
        "items": items,
        "warnings": list(transfer_plan.get("warnings", [])) if isinstance(transfer_plan.get("warnings"), list) else [],
        "safety": "readonly MV3 resource-search planning only; no share receive, organize transfer, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed",
    }


def render_mv3_share_search_plan(plan: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(plan, ensure_ascii=False, indent=2)
    return _render_share_search_plan_markdown(plan)


def _transfer_item(item: Dict[str, object]) -> Dict[str, object]:
    return {
        "source_status": str(item.get("status") or ""),
        "title": str(item.get("title") or ""),
        "tmdbid": int(item.get("tmdbid") or 0),
        "season": int(item.get("season") or 0),
        "size_bytes": int(item.get("size_bytes") or 0),
        "candidate_count": int(item.get("candidate_count") or 0),
        "expected_count": int(item.get("expected_count") or 0),
        "expected_episodes": _int_list(item.get("expected_episodes")),
        "missing_episodes": _int_list(item.get("missing_episodes")),
        "titles": _string_list(item.get("titles")),
        "source_paths": _string_list(item.get("source_paths")),
        "search_keywords": _search_keywords_for_item(item),
        "blockers": _string_list(item.get("blockers")),
    }


def _restored_queue_item(item: Dict[str, object], transfer_item: Dict[str, object], queue_status: str) -> Dict[str, object]:
    source_paths = _merge_keywords(_string_list(transfer_item.get("source_paths")) + _string_list(item.get("source_paths")), limit=20)
    titles = _merge_keywords(_string_list(transfer_item.get("titles")) + _string_list(item.get("titles")), limit=20)
    search_keywords = _merge_keywords(
        _string_list(transfer_item.get("search_keywords")) + _search_keywords_for_item(item),
        limit=12,
    )
    return {
        "queue_status": queue_status,
        "source_status": str(item.get("status") or transfer_item.get("source_status") or ""),
        "title": str(item.get("title") or transfer_item.get("title") or ""),
        "tmdbid": int(item.get("tmdbid") or transfer_item.get("tmdbid") or 0),
        "season": int(item.get("season") or transfer_item.get("season") or 0),
        "size_bytes": int(item.get("size_bytes") or transfer_item.get("size_bytes") or 0),
        "expected_count": int(item.get("expected_count") or transfer_item.get("expected_count") or 0),
        "expected_episodes": _int_list(item.get("expected_episodes")),
        "missing_episodes": _int_list(item.get("missing_episodes")),
        "candidate_count": int(item.get("candidate_count") or transfer_item.get("candidate_count") or 0),
        "source_paths": source_paths,
        "titles": titles,
        "search_keywords": search_keywords,
        "blockers": _merge_keywords(_string_list(item.get("blockers")) + _string_list(transfer_item.get("blockers")), limit=20),
        "next_gate": _restored_queue_next_gate(queue_status),
    }


def _restored_queue_next_gate(queue_status: str) -> str:
    if queue_status == "cloud_strm_not_found":
        return "after MV3 license is active, run MV3 share/cloud search and compare episode coverage plus total size before any receive or organize transfer"
    return "resolve TMDB ID and season first, then regenerate cloud-check before any MV3 transfer"


def _historical_candidates(historical_scan: Optional[Dict[str, object]]) -> List[Dict[str, object]]:
    if not isinstance(historical_scan, dict):
        return []
    rows = []
    for candidate in historical_scan.get("candidates", []):
        if not isinstance(candidate, dict) or candidate.get("status") != "candidate_for_cloud_check":
            continue
        rows.append(
            {
                "title": str(candidate.get("title") or ""),
                "path": str(candidate.get("path") or ""),
                "size_bytes": int(candidate.get("size_bytes") or 0),
                "video_count": int(candidate.get("video_count") or 0),
                "seasons": _int_list(candidate.get("seasons")),
                "tmdbid": int(_nested_int(candidate, "mp", "tmdbid") or _nested_int(candidate, "manual_completion", "tmdbid") or 0),
                "season": int(_nested_int(candidate, "mp", "season") or _nested_int(candidate, "manual_completion", "season") or 0),
                "reasons": _string_list(candidate.get("reasons")),
            }
        )
    rows.sort(key=lambda row: (-int(row.get("size_bytes") or 0), str(row.get("title") or "")))
    return rows


def _nested_int(source: Dict[str, object], outer: str, key: str) -> int:
    value = source.get(outer)
    if not isinstance(value, dict):
        return 0
    raw = value.get(key)
    return int(raw) if isinstance(raw, int) or str(raw).isdigit() else 0


def _mv3_status_summary(mv3_report: Optional[Dict[str, object]]) -> Dict[str, object]:
    if not isinstance(mv3_report, dict):
        return {
            "configured": False,
            "reachable": False,
            "license_status": "unknown",
            "warnings": ["mv3_report_missing"],
        }
    return {
        "configured": bool(mv3_report.get("configured")),
        "reachable": bool(mv3_report.get("reachable")),
        "license_status": str(mv3_report.get("license_status") or "unknown"),
        "warnings": _string_list(mv3_report.get("warnings")),
    }


def _restored_queue_warnings(
    cloud_report: Dict[str, object],
    transfer_plan: Optional[Dict[str, object]],
    historical_scan: Optional[Dict[str, object]],
    mv3_report: Optional[Dict[str, object]],
) -> List[str]:
    warnings = []
    warnings.extend(_string_list(cloud_report.get("warnings")))
    if isinstance(transfer_plan, dict):
        warnings.extend(_string_list(transfer_plan.get("warnings")))
    else:
        warnings.append("transfer_plan_missing")
    if not isinstance(historical_scan, dict):
        warnings.append("historical_scan_missing")
    mv3_status = _mv3_status_summary(mv3_report)
    warnings.extend(_string_list(mv3_status.get("warnings")))
    if mv3_status.get("license_status") not in {"active", "ok", "licensed", "not_detected_by_probe"}:
        warnings.append("mv3_not_ready_for_transfer")
    return _merge_keywords(warnings, limit=50)


def _limit_rows(rows: List[Dict[str, object]], limit: int) -> List[Dict[str, object]]:
    return rows[:limit] if limit > 0 else rows


def _mv3_manifest_context(
    instances_report: Optional[Dict[str, object]],
    capabilities_report: Optional[Dict[str, object]],
    cloud_root: str,
    instance: str,
) -> Dict[str, object]:
    warnings: List[str] = []
    cloud_drive = _first_cloud_drive(instances_report)
    media_instance = instance or _first_media_transfer_instance(instances_report)
    preview_schema = _preview_schema(capabilities_report)
    failed_paths = []
    if isinstance(instances_report, dict):
        summary = instances_report.get("summary")
        if isinstance(summary, dict) and isinstance(summary.get("failed_paths"), list):
            failed_paths = [str(path) for path in summary["failed_paths"]]
            if failed_paths:
                warnings.append("mv3_instance_probe_has_failed_paths")
    mount_paths = {}
    if isinstance(cloud_drive, dict) and isinstance(cloud_drive.get("mount_path"), dict):
        mount_paths = {str(key): str(value) for key, value in cloud_drive["mount_path"].items()}
    normalized_cloud_root = (cloud_root or DEFAULT_CLOUD_ROOT).rstrip("/") or DEFAULT_CLOUD_ROOT
    if mount_paths and normalized_cloud_root not in mount_paths and normalized_cloud_root not in mount_paths.values():
        warnings.append(f"cloud_root_not_in_mv3_mount_paths:{normalized_cloud_root}")
    if not media_instance:
        warnings.append("mv3_media_transfer_instance_not_found")
    if not preview_schema:
        warnings.append("mv3_preview_schema_not_found")
    return {
        "cloud_root": normalized_cloud_root,
        "cloud_drive_slug": str(cloud_drive.get("slug") or "") if isinstance(cloud_drive, dict) else "",
        "cloud_drive_name": str(cloud_drive.get("name") or "") if isinstance(cloud_drive, dict) else "",
        "cloud_mount_paths": mount_paths,
        "share_transfer_default_path": str(cloud_drive.get("share_transfer_default_path") or "") if isinstance(cloud_drive, dict) else "",
        "media_transfer_instance": media_instance,
        "preview_endpoint": MV3_PREVIEW_ENDPOINT,
        "preview_request_schema": preview_schema,
        "failed_instance_paths": failed_paths,
        "warnings": warnings,
    }


def _first_cloud_drive(instances_report: Optional[Dict[str, object]]) -> Dict[str, object]:
    sample = _probe_sample(instances_report, "/api/v1/cloud-drive/instances")
    if isinstance(sample, dict) and isinstance(sample.get("instances"), list) and sample["instances"]:
        first = sample["instances"][0]
        return first if isinstance(first, dict) else {}
    if isinstance(sample, list) and sample and isinstance(sample[0], dict):
        return sample[0]
    return {}


def _first_media_transfer_instance(instances_report: Optional[Dict[str, object]]) -> str:
    sample = _probe_sample(instances_report, "/api/v1/media-transfer/instances")
    if isinstance(sample, list) and sample:
        first = sample[0]
        if isinstance(first, dict):
            return str(first.get("slug") or "")
    return ""


def _probe_sample(report: Optional[Dict[str, object]], path: str) -> object:
    if not isinstance(report, dict):
        return None
    probes = report.get("probes")
    if not isinstance(probes, list):
        return None
    for probe in probes:
        if isinstance(probe, dict) and probe.get("path") == path:
            return probe.get("sample")
    return None


def _preview_schema(capabilities_report: Optional[Dict[str, object]]) -> Dict[str, object]:
    if not isinstance(capabilities_report, dict):
        return {}
    categories = capabilities_report.get("categories")
    if not isinstance(categories, dict):
        return {}
    for row in categories.get("preview_or_search_post", []):
        if isinstance(row, dict) and row.get("path") == MV3_PREVIEW_ENDPOINT["path"]:
            schema = row.get("request_schema")
            return schema if isinstance(schema, dict) else {}
    return {}


def _preview_manifest_item(index: int, item: Dict[str, object], context: Dict[str, object]) -> Dict[str, object]:
    destination = _proposed_cloud_destination(context.get("cloud_root", DEFAULT_CLOUD_ROOT), item)
    blockers = [
        "missing_mv3_source_library_id",
        "missing_mv3_source_item_id",
        "missing_mv3_target_library_id",
        "requires_mv3_preview_before_execute",
        "requires_manual_approval_before_execute",
    ]
    failed_paths = context.get("failed_instance_paths")
    if isinstance(failed_paths, list) and any("media-transfer/libraries" in str(path) for path in failed_paths):
        blockers.append("mv3_libraries_probe_unavailable")
    if not context.get("media_transfer_instance"):
        blockers.append("missing_mv3_media_transfer_instance")
    return {
        "priority": index,
        "title": str(item.get("title") or ""),
        "tmdbid": int(item.get("tmdbid") or 0),
        "season": int(item.get("season") or 0),
        "expected_count": int(item.get("expected_count") or 0),
        "candidate_count": int(item.get("candidate_count") or 0),
        "size_bytes": int(item.get("size_bytes") or 0),
        "proposed_cloud_destination": destination,
        "source_titles": _string_list(item.get("titles")),
        "source_paths": _string_list(item.get("source_paths")),
        "mv3_preview_call": {
            "method": MV3_PREVIEW_ENDPOINT["method"],
            "path": MV3_PREVIEW_ENDPOINT["path"],
            "body_template": {
                "instance": context.get("media_transfer_instance") or "[REQUIRES_MV3_INSTANCE]",
                "source_library_id": "[REQUIRES_MV3_SOURCE_LIBRARY_ID]",
                "source_item_id": "[REQUIRES_MV3_SOURCE_ITEM_ID]",
                "target_library_id": "[REQUIRES_MV3_TARGET_LIBRARY_ID]",
            },
        },
        "execution_blockers": blockers,
        "source_blockers": _string_list(item.get("blockers")),
    }


def _share_search_plan_item(index: int, item: Dict[str, object], search_report: Dict[str, object], max_candidates: int) -> Dict[str, object]:
    candidates = [
        _share_search_candidate(row, item)
        for row in search_report.get("items", [])
        if isinstance(row, dict)
    ]
    candidates.sort(key=lambda row: (-int(row.get("score") or 0), float(row.get("size_delta_ratio") or 999), int(row.get("search_index") or 0)))
    selected = candidates[: max_candidates if max_candidates > 0 else len(candidates)]
    recommended = selected[0] if selected and int(selected[0].get("score") or 0) >= 60 and not selected[0].get("blockers") else {}
    warnings = []
    if not search_report:
        warnings.append("search_report_missing")
    elif not bool(search_report.get("ok")):
        warnings.append("search_report_not_ok")
    if candidates and not recommended:
        warnings.append("no_candidate_passed_recommendation_gate")
    if not candidates:
        warnings.append("no_search_candidates_found")
    search_warnings = _string_list(search_report.get("warnings"))
    for warning in search_warnings:
        if warning not in warnings:
            warnings.append(warning)
    keyword_reports = _share_search_keyword_reports(search_report)
    return {
        "priority": index,
        "title": str(item.get("title") or ""),
        "tmdbid": int(item.get("tmdbid") or 0),
        "season": int(item.get("season") or 0),
        "expected_count": int(item.get("expected_count") or 0),
        "expected_episodes": _int_list(item.get("expected_episodes")),
        "size_bytes": int(item.get("size_bytes") or 0),
        "source_paths": _string_list(item.get("source_paths")),
        "search_keywords": _search_keywords_for_item(item),
        "search_ok": bool(search_report.get("ok")),
        "search_result_count": int(search_report.get("result_count") or len(search_report.get("items", [])) if isinstance(search_report.get("items"), list) else 0),
        "keyword_reports": keyword_reports,
        "search_errors": _share_search_errors(keyword_reports),
        "recommended_candidate": recommended,
        "candidates": selected,
        "warnings": warnings,
    }


def _share_search_keyword_reports(search_report: Dict[str, object]) -> List[Dict[str, object]]:
    rows = search_report.get("keyword_reports")
    if not isinstance(rows, list):
        return []
    reports: List[Dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        reports.append(
            {
                "keyword": str(row.get("keyword") or ""),
                "ok": bool(row.get("ok")),
                "result_count": int(row.get("result_count") or 0),
                "status": int(row.get("status") or 0),
                "channels": _string_list(row.get("channels")),
                "fallback": bool(row.get("fallback")),
                "fallback_reason": str(row.get("fallback_reason") or ""),
                "error_type": str(row.get("error_type") or ""),
                "error": str(row.get("error") or ""),
                "warnings": _string_list(row.get("warnings")),
            }
        )
    return reports


def _share_search_errors(keyword_reports: List[Dict[str, object]]) -> List[Dict[str, object]]:
    errors: List[Dict[str, object]] = []
    for row in keyword_reports:
        if row.get("ok") and not row.get("error_type"):
            continue
        if not row.get("error_type") and not row.get("error") and int(row.get("status") or 0) == 0:
            continue
        errors.append(
            {
                "keyword": str(row.get("keyword") or ""),
                "status": int(row.get("status") or 0),
                "channels": _string_list(row.get("channels")),
                "fallback": bool(row.get("fallback")),
                "fallback_reason": str(row.get("fallback_reason") or ""),
                "error_type": str(row.get("error_type") or ""),
                "error": str(row.get("error") or ""),
                "warnings": _string_list(row.get("warnings")),
            }
        )
    return errors


def _share_search_candidate(row: Dict[str, object], transfer_item: Dict[str, object]) -> Dict[str, object]:
    title = str(row.get("title") or "")
    expected_count = int(transfer_item.get("expected_count") or 0)
    expected_episodes = _int_list(transfer_item.get("expected_episodes"))
    local_size = int(transfer_item.get("size_bytes") or 0)
    remote_size = _share_result_size_bytes(row.get("size"), title)
    score = 0
    reasons: List[str] = []
    blockers: List[str] = []
    normalized_title = _compact(str(transfer_item.get("title") or ""))
    normalized_remote = _compact(title)
    if normalized_title and normalized_title in normalized_remote:
        score += 35
        reasons.append("title_contains")
        if _has_chinese_subtitle_drift(str(transfer_item.get("title") or ""), title):
            blockers.append("possible_chinese_subtitle_mismatch")
    elif _search_keyword_matches(row, normalized_remote):
        score += 30
        reasons.append("search_keyword_contains")
    elif normalized_title and _title_token_overlap(str(transfer_item.get("title") or ""), title) >= 0.6:
        score += 25
        reasons.append("title_token_overlap")
    else:
        blockers.append("title_not_matched")

    episodes = _episode_numbers_from_text(title)
    missing_expected = [episode for episode in expected_episodes if episode not in episodes] if expected_episodes and episodes else []
    unexpected_episodes = [episode for episode in episodes if expected_episodes and episode not in expected_episodes]
    if expected_episodes and episodes and not missing_expected:
        score += 25
        reasons.append("explicit_episodes_cover_expected")
    elif expected_episodes and episodes:
        blockers.append("missing_expected_episodes")
    elif expected_count and len(episodes) >= expected_count:
        score += 25
        reasons.append("episode_count_covers_expected")
    elif expected_count and _has_complete_marker(title):
        score += 15
        reasons.append("complete_marker")
    elif expected_count:
        blockers.append("episode_coverage_unclear")

    season = int(transfer_item.get("season") or 0)
    explicit_seasons = _explicit_seasons_from_text(title)
    if season and explicit_seasons:
        if season in explicit_seasons:
            score += 10
            reasons.append("season_matches")
        else:
            blockers.append("season_mismatch")
    elif season and _season_matches(title, season):
        score += 10
        reasons.append("season_matches")

    size_delta = _size_delta_ratio(local_size, remote_size)
    if size_delta is not None:
        if size_delta <= 0.35:
            score += 20
            reasons.append("size_similar")
        elif size_delta <= 0.75:
            score += 10
            reasons.append("size_somewhat_similar")
        else:
            blockers.append("size_far_from_local")
    else:
        reasons.append("remote_size_unknown")

    if bool(row.get("share_code_available")):
        score += 10
        reasons.append("share_code_available")

    return {
        "search_index": int(row.get("index") or 0),
        "title": title,
        "channel": str(row.get("channel") or ""),
        "media_type": str(row.get("media_type") or ""),
        "size": str(row.get("size") or ""),
        "size_bytes": remote_size or 0,
        "size_delta_ratio": round(size_delta, 4) if size_delta is not None else None,
        "score": score,
        "reasons": reasons,
        "blockers": blockers,
        "episode_numbers": episodes,
        "missing_expected_episodes": missing_expected,
        "unexpected_episodes": unexpected_episodes,
        "search_keyword": str(row.get("search_keyword") or ""),
        "share_code_available": bool(row.get("share_code_available")),
    }


def _search_keywords_for_item(item: Dict[str, object], limit: int = 8) -> List[str]:
    values: List[str] = []
    values.append(str(item.get("title") or ""))
    values.extend(_string_list(item.get("search_keywords")))
    values.extend(_string_list(item.get("titles")))
    for path in _string_list(item.get("source_paths")):
        values.extend(_keyword_variants_from_path(path))
    keywords: List[str] = []
    for value in values:
        keywords.extend(_search_keyword_variants(value))
    return _merge_keywords(keywords, limit=limit)


def search_keywords_for_item(item: Dict[str, object], limit: int = 8) -> List[str]:
    return _search_keywords_for_item(item, limit=limit)


def _search_keyword_variants(value: object) -> List[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    cjk_title = _cjk_title_guess(raw)
    english_title = _english_title_guess(raw)
    cleaned = _clean_search_keyword(raw)
    candidates = [cjk_title, english_title]
    if not ((cjk_title or english_title) and _has_cjk(cleaned) and re.search(r"[A-Za-z]", cleaned)):
        candidates.append(cleaned)
    return [candidate for candidate in _merge_keywords(candidates, limit=4) if _is_useful_search_keyword(candidate)]


def _clean_search_keyword(value: str) -> str:
    text = TMDBID_PATTERN.sub(" ", value or "")
    text = re.sub(r"[\[\]【】{}（）()]", " ", text)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"(?i)\bSeason\s*0?\d{1,2}\b", " ", text)
    text = re.sub(r"(?i)\bS\d{1,2}(?:E\d{1,3})?\b", " ", text)
    text = re.sub(r"第\s*0?\d{1,2}\s*季", " ", text)
    text = YEAR_VALUE_PATTERN.sub(" ", text)
    tokens = []
    for raw_token in re.split(r"[\s\-]+", text):
        token = raw_token.strip(" \t\r\n:：,，;；'\"")
        if not token:
            continue
        lowered = token.casefold()
        if lowered in TECHNICAL_TOKENS:
            continue
        if re.fullmatch(r"(?i)\d+p|fps|\d+bit|v\d+|proper|repack", token):
            continue
        tokens.append(token)
    return " ".join(tokens).strip()


def _cjk_title_guess(value: str) -> str:
    cleaned = _clean_search_keyword(value)
    matches = CJK_TITLE_PATTERN.findall(cleaned)
    if not matches:
        return ""
    matches.sort(key=len, reverse=True)
    return matches[0].strip("·・")


def _has_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value or ""))


def _english_title_guess(value: str) -> str:
    text = TMDBID_PATTERN.sub(" ", value or "")
    text = re.sub(r"[\[\]【】{}（）()]", " ", text)
    text = re.sub(r"[._]+", " ", text)
    tokens: List[str] = []
    for raw_token in re.split(r"[\s\-]+", text):
        token = raw_token.strip(" \t\r\n:：,，;；'\"")
        if not token:
            continue
        lowered = token.casefold()
        if re.search(r"[\u4e00-\u9fff]", token):
            if tokens:
                break
            continue
        if YEAR_VALUE_PATTERN.fullmatch(token) or re.fullmatch(r"(?i)S\d{1,2}(?:E\d{1,3})?", token):
            if tokens:
                break
            continue
        if lowered in TECHNICAL_TOKENS or re.fullmatch(r"(?i)\d+p|fps|\d+bit|v\d+|proper|repack", token):
            if tokens:
                break
            continue
        if re.search(r"[A-Za-z]", token):
            tokens.append(token)
            continue
        if tokens:
            break
    title_tokens = [token for token in tokens if token.casefold() not in TITLE_STOP_TOKENS]
    if len(title_tokens) >= 2 or any(len(token) >= 4 for token in title_tokens):
        return " ".join(tokens).strip()
    return ""


def _is_useful_search_keyword(value: str) -> bool:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) < 2:
        return False
    if TMDBID_PATTERN.search(text):
        return False
    if not re.search(r"[A-Za-z\u4e00-\u9fff]", text):
        return False
    if not _title_token_set(text):
        return False
    if re.fullmatch(r"(?i)(?:season|s)\s*0?\d{1,2}", text):
        return False
    compact = re.sub(r"[\W_]+", "", text.casefold(), flags=re.UNICODE)
    if compact in {"season", "tmdbid", "tmdb", "series", "tv"}:
        return False
    return True


def _search_keyword_matches(row: Dict[str, object], normalized_remote: str) -> bool:
    keyword = str(row.get("search_keyword") or "")
    normalized_keyword = _compact(keyword)
    return bool(normalized_keyword and normalized_keyword in normalized_remote)


def _has_chinese_subtitle_drift(expected_title: str, remote_title: str) -> bool:
    expected = _first_chinese_run(expected_title)
    if len(expected) < 2:
        return False
    remote = re.sub(r"\s+", "", remote_title or "")
    index = remote.find(expected)
    if index < 0:
        return False
    suffix = remote[index + len(expected) :]
    suffix = _chinese_title_suffix(suffix)
    if not suffix or _chinese_suffix_is_metadata(suffix):
        return False
    return bool(re.match(r"(?:\d{1,4}[\s:：\-—_]*[\u4e00-\u9fff]|[\u4e00-\u9fff]{1,12})", suffix))


def _chinese_title_suffix(value: str) -> str:
    text = re.sub(r"^[\s:：,，\-—_【】\[\]（）()]+", "", value or "")
    text = re.sub(r"^(?:19|20)\d{2}[)）]?", "", text)
    return re.sub(r"^[\s:：,，\-—_【】\[\]（）()]+", "", text)


def _chinese_suffix_is_metadata(value: str) -> bool:
    return bool(
        re.match(
            r"(?i)^(?:"
            r"S0?\d{1,2}(?:E|\b)|Season0?\d{1,2}\b|第?\d{1,3}[集话話期]|第\d{1,2}季|"
            r"第[一二三四五六七八九十百两]+[季集部]|[全共]\d{1,3}[集话話期]|"
            r"更新|更至|完结|全集|Complete|4K|8K|720P|1080P|2160P|HDR|DV|DOVI|WEB|"
            r"BluRay|BD|Remux|HEVC|H265|H264|杜比|高码|国粤|国语|粤语|中字"
            r")",
            value or "",
        )
    )


def _first_chinese_run(value: str) -> str:
    match = re.search(r"[\u4e00-\u9fff]{2,}", value or "")
    return match.group(0) if match else ""


def _keyword_variants_from_path(path: str) -> List[str]:
    name = Path(path).name
    if not name:
        return []
    without_identity = TMDBID_PATTERN.sub("", YEAR_SUFFIX_PATTERN.sub("", name))
    dotted = re.sub(r"[._]+", " ", without_identity)
    return [without_identity.strip(), dotted.strip()]


def _merge_keywords(values: List[str], limit: int = 8) -> List[str]:
    merged: List[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) < 2:
            continue
        if any(text.lower() == item.lower() for item in merged):
            continue
        merged.append(text)
        if len(merged) >= limit:
            break
    return merged


def _parse_size_bytes(value: object) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    compact = text.replace(",", "").replace(" ", "")
    matches = list(re.finditer(r"(?i)(\d+(?:\.\d+)?)(b|k|kb|kib|m|mb|mib|g|gb|gib|t|tb|tib)", compact))
    if not matches:
        return int(float(compact)) if compact.isdigit() else 0
    return max(_size_match_bytes(match) for match in matches)


def _share_result_size_bytes(size_value: object, title: str) -> int:
    explicit_size = _parse_size_bytes(size_value)
    if _looks_like_real_share_size(explicit_size):
        return explicit_size
    title_size = _parse_size_bytes(title)
    if _looks_like_real_share_size(title_size):
        return title_size
    return 0


def _looks_like_real_share_size(size_bytes: int) -> bool:
    # Resource search providers sometimes expose 4K/4096 as a placeholder or
    # video-quality token, not as a real share size.
    return int(size_bytes or 0) >= 10 * 1024 * 1024


def _size_match_bytes(match: re.Match[str]) -> int:
    number = float(match.group(1))
    unit = match.group(2).lower()
    factor = {
        "b": 1,
        "k": 1024,
        "kb": 1000,
        "m": 1024**2,
        "mb": 1000**2,
        "g": 1024**3,
        "gb": 1000**3,
        "t": 1024**4,
        "tb": 1000**4,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
    }[unit]
    return int(number * factor)


def _size_delta_ratio(local_size: int, remote_size: int) -> Optional[float]:
    if local_size <= 0 or remote_size <= 0:
        return None
    return abs(local_size - remote_size) / max(local_size, remote_size)


def _episode_numbers_from_text(text: str) -> List[int]:
    import re

    episodes = set()
    for end in re.findall(r"(?:更新至|更至|更新到|更新至第|更至第|至第)\s*0?(\d{1,3})\s*[集话話期]", text):
        last = int(end)
        if 0 < last <= 300:
            episodes.update(range(1, last + 1))
    for start, end in re.findall(r"(?i)(?:S\d{1,2})?E?0?(\d{1,3})\s*[-~到至]\s*(?:S\d{1,2})?E?0?(\d{1,3})\s*[集话話]?", text):
        a, b = int(start), int(end)
        if 0 < a <= b <= 300:
            episodes.update(range(a, b + 1))
    for episode in re.findall(r"(?i)S\d{1,2}E(\d{1,3})|第\s*(\d{1,3})\s*[集话話]", text):
        value = next((part for part in episode if part), "")
        if value and 0 < int(value) <= 300:
            episodes.add(int(value))
    return sorted(episodes)


def _has_complete_marker(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in ["完结", "complete"]):
        return True
    return bool(re.search(r"(?i)(全|共)\s*\d{1,3}\s*[集话話]", text))


def _season_matches(text: str, season: int) -> bool:
    if season <= 0:
        return False
    patterns = [
        rf"(?i)\bS0?{season}\b",
        rf"第\s*0?{season}\s*季",
        rf"Season\s*0?{season}\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _explicit_seasons_from_text(text: str) -> List[int]:
    seasons = set()
    patterns = [
        r"(?i)\bS0?(\d{1,2})(?=E|\b)",
        r"(?i)\bSeason\s*0?(\d{1,2})\b",
        r"第\s*0?(\d{1,2})\s*季",
    ]
    for pattern in patterns:
        for value in re.findall(pattern, text or ""):
            season = int(value)
            if 0 < season <= 99:
                seasons.add(season)
    return sorted(seasons)


def _compact(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).lower()


def _title_token_overlap(left: str, right: str) -> float:
    left_tokens = set(_title_tokens(left))
    right_tokens = set(_title_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _title_tokens(value: str) -> List[str]:
    return sorted(_title_token_set(value))


def _title_token_set(value: str) -> Set[str]:
    text = YEAR_SUFFIX_PATTERN.sub(" ", TMDBID_PATTERN.sub(" ", value.casefold()))
    tokens: Set[str] = set()
    for raw in re.findall(r"[a-z]+|[0-9]+|[\u4e00-\u9fff]+", text):
        token = raw.strip()
        if not token or token.isdigit():
            continue
        if token in TITLE_STOP_TOKENS or token in TECHNICAL_TOKENS:
            continue
        if SEASON_TOKEN_PATTERN.match(token) or EPISODE_TOKEN_PATTERN.match(token):
            continue
        if len(token) <= 1 and not re.search(r"[\u4e00-\u9fff]", token):
            continue
        tokens.add(token)
    return tokens


def _normalized_title_match(left: str, right: str) -> bool:
    if not _title_years_are_compatible(left, right):
        return False

    left_tokens = _title_token_set(left)
    if not left_tokens:
        return False
    right_tokens = _title_token_set(right)
    overlap = left_tokens.intersection(right_tokens)
    if not overlap:
        return False

    left_compact = "".join(sorted(left_tokens))
    right_compact = "".join(sorted(right_tokens))
    if left_compact and len(left_compact) >= 4 and left_compact in right_compact:
        return True

    overlap_ratio = len(overlap) / max(1, len(left_tokens))
    has_cjk_overlap = any(re.search(r"[\u4e00-\u9fff]", token) for token in overlap)
    return overlap_ratio >= 0.67 or (has_cjk_overlap and overlap_ratio >= 0.5)


def _years_from_text(value: str) -> Set[int]:
    return {int(match.group(0)) for match in YEAR_VALUE_PATTERN.finditer(value)}


def _has_tv_signal(value: str) -> bool:
    return bool(TV_SIGNAL_PATTERN.search(value))


def _title_years_are_compatible(left: str, right: str) -> bool:
    left_years = _years_from_text(left)
    if not left_years:
        return True
    right_years = _years_from_text(right)
    if not right_years:
        return True
    if left_years.intersection(right_years):
        return True
    return _has_tv_signal(right)


def _looks_like_cloud_media_root(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").rstrip("/")
    parts = [part for part in normalized.split("/") if part]
    return "已整理" in parts or "未整理" in parts or normalized.lower() in {"/series", "/movie", "/movies", "/anime", "/tv"}


def _looks_like_strm_root(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").rstrip("/")
    parts = [part.lower() for part in normalized.split("/") if part]
    if not normalized or _looks_like_cloud_media_root(normalized):
        return False
    return any(
        part == "strm"
        or part.startswith("strm-")
        or part.startswith("strm_")
        or part.endswith("-strm")
        or part.endswith("_strm")
        or "-strm-" in part
        or "_strm_" in part
        for part in parts
    )


def _proposed_cloud_destination(cloud_root: object, item: Dict[str, object]) -> str:
    root = str(cloud_root or DEFAULT_CLOUD_ROOT).rstrip("/") or DEFAULT_CLOUD_ROOT
    title = _safe_cloud_segment(_strip_identity_suffix(str(item.get("title") or "unknown")))
    tmdbid = int(item.get("tmdbid") or 0)
    season = int(item.get("season") or 0)
    season_segment = f"Season {season:02d}" if season > 0 else "Season XX"
    return f"{root}/{title} {{tmdbid={tmdbid}}}/{season_segment}"


def _strip_identity_suffix(value: str) -> str:
    return " ".join(TMDBID_PATTERN.sub(" ", value).split())


def _safe_cloud_segment(value: str) -> str:
    cleaned = value.replace("/", " ").replace("\\", " ").strip()
    return " ".join(cleaned.split()) or "unknown"


def _mv3_offline_context(instances_report: Optional[Dict[str, object]], cloud_root: str, strm_root: str) -> Dict[str, object]:
    warnings: List[str] = []
    cloud_drive = _first_cloud_drive(instances_report)
    mount_paths = {}
    if isinstance(cloud_drive, dict) and isinstance(cloud_drive.get("mount_path"), dict):
        mount_paths = {str(key): str(value) for key, value in cloud_drive["mount_path"].items()}
    normalized_cloud_root = (cloud_root or DEFAULT_CLOUD_ROOT).rstrip("/") or DEFAULT_CLOUD_ROOT
    normalized_strm_root = (strm_root or DEFAULT_STRM_ROOT).rstrip("/") or DEFAULT_STRM_ROOT
    if mount_paths and normalized_cloud_root not in mount_paths and normalized_cloud_root not in mount_paths.values():
        warnings.append(f"cloud_root_not_in_mv3_mount_paths:{normalized_cloud_root}")
    if not cloud_drive:
        warnings.append("mv3_cloud_drive_not_found")
    if _looks_like_cloud_media_root(normalized_strm_root):
        warnings.append("strm_root_looks_like_cloud_media_root")
    if not _looks_like_strm_root(normalized_strm_root):
        warnings.append("strm_root_not_obviously_strm_side")
    return {
        "cloud_root": normalized_cloud_root,
        "strm_root": normalized_strm_root,
        "cloud_drive_slug": str(cloud_drive.get("slug") or "") if isinstance(cloud_drive, dict) else "",
        "cloud_drive_name": str(cloud_drive.get("name") or "") if isinstance(cloud_drive, dict) else "",
        "cloud_mount_paths": mount_paths,
        "share_transfer_default_path": str(cloud_drive.get("share_transfer_default_path") or "") if isinstance(cloud_drive, dict) else "",
        "offline_endpoint": MV3_OFFLINE_ENDPOINT,
        "strm_generate_endpoint": MV3_STRM_GENERATE_ENDPOINT,
        "warnings": warnings,
    }


def _offline_manifest_item(
    index: int,
    item: Dict[str, object],
    qb_torrents: List[Dict[str, object]],
    context: Dict[str, object],
    min_seed_days: int,
    destination_mode: str,
) -> Dict[str, object]:
    matches = _match_qb_torrents_for_transfer_item(item, qb_torrents)
    magnet_count = sum(1 for torrent in matches if str(torrent.get("magnet_uri") or ""))
    seed_ok_count = sum(1 for torrent in matches if int(torrent.get("seeding_time") or 0) >= min_seed_days * 86400)
    destination = _proposed_cloud_destination(context.get("cloud_root", DEFAULT_CLOUD_ROOT), item)
    offline_wp_path = str(context.get("cloud_root") or DEFAULT_CLOUD_ROOT).rstrip("/") or DEFAULT_CLOUD_ROOT
    if destination_mode == "season":
        offline_wp_path = destination
    blockers = [
        "requires_manual_approval_before_offline_add",
        "requires_mv3_offline_preview_or_single_item_probe",
        "requires_strm_generation_after_offline_completion",
        "requires_cloud_strm_rescan_before_cleanup",
    ]
    if not matches:
        blockers.append("missing_qb_torrent_match")
    if matches and magnet_count == 0:
        blockers.append("missing_qb_magnet_uri")
    if matches and seed_ok_count < len(matches):
        blockers.append("qb_seed_age_short_for_some_torrents")
    if not context.get("cloud_drive_slug"):
        blockers.append("missing_mv3_cloud_drive")
    if any(str(warning).startswith("strm_root_") for warning in context.get("warnings", [])):
        blockers.append("strm_root_must_be_strm_side")
    return {
        "priority": index,
        "title": str(item.get("title") or ""),
        "tmdbid": int(item.get("tmdbid") or 0),
        "season": int(item.get("season") or 0),
        "expected_count": int(item.get("expected_count") or 0),
        "candidate_count": int(item.get("candidate_count") or 0),
        "size_bytes": int(item.get("size_bytes") or 0),
        "proposed_cloud_destination": destination,
        "offline_wp_path": offline_wp_path,
        "offline_destination_mode": destination_mode,
        "source_titles": _string_list(item.get("titles")),
        "source_paths": _string_list(item.get("source_paths")),
        "qb_match_count": len(matches),
        "qb_magnet_available_count": magnet_count,
        "qb_seed_age_ok_count": seed_ok_count,
        "qb_matches": [_qb_match_summary(torrent) for torrent in matches],
        "mv3_offline_call": {
            "method": MV3_OFFLINE_ENDPOINT["method"],
            "path": MV3_OFFLINE_ENDPOINT["path"],
            "body_template": {
                "storage": context.get("cloud_drive_slug") or "[REQUIRES_MV3_CLOUD_DRIVE]",
                "urls": "[REDACTED_MAGNET_URIS_FROM_QB]",
                "wp_path": offline_wp_path,
                "wp_path_id": "[OPTIONAL_TARGET_FOLDER_ID]",
            },
        },
        "post_offline_strm_generate_call": {
            "method": MV3_STRM_GENERATE_ENDPOINT["method"],
            "path": MV3_STRM_GENERATE_ENDPOINT["path"],
            "body_template": {
                "storage": context.get("cloud_drive_slug") or "[REQUIRES_MV3_CLOUD_DRIVE]",
                "source_dir": destination,
                "target_dir": context.get("strm_root") or DEFAULT_STRM_ROOT,
                "cloud": True,
                "incremental": True,
                "overwrite": False,
            },
        },
        "execution_blockers": blockers,
        "source_blockers": _string_list(item.get("blockers")),
    }


def _match_qb_torrents_for_transfer_item(item: Dict[str, object], qb_torrents: List[Dict[str, object]]) -> List[Dict[str, object]]:
    wanted_titles = [str(item.get("title") or "")]
    wanted_titles.extend(_string_list(item.get("titles")))
    wanted_paths = _string_list(item.get("source_paths"))
    matches = []
    for torrent in qb_torrents:
        name = str(torrent.get("name") or "")
        content_path = str(torrent.get("content_path") or "")
        save_path = str(torrent.get("save_path") or "")
        if any(path and (content_path == path or content_path.startswith(path + "/") or path.startswith(content_path + "/")) for path in wanted_paths):
            matches.append(torrent)
            continue
        torrent_text = " ".join([name, content_path, save_path])
        if any(title and _normalized_title_match(title, torrent_text) for title in wanted_titles):
            matches.append(torrent)
    matches.sort(key=lambda torrent: (-int(torrent.get("size") or torrent.get("total_size") or 0), str(torrent.get("name") or "")))
    return matches


def _qb_match_summary(torrent: Dict[str, object]) -> Dict[str, object]:
    seeding_time = int(torrent.get("seeding_time") or 0)
    return {
        "name": str(torrent.get("name") or ""),
        "hash": str(torrent.get("hash") or ""),
        "state": str(torrent.get("state") or ""),
        "progress": round(float(torrent.get("progress") or 0.0), 4),
        "seed_days": round(seeding_time / 86400.0, 2),
        "size_bytes": int(torrent.get("size") or torrent.get("total_size") or 0),
        "magnet_available": bool(str(torrent.get("magnet_uri") or "")),
    }


def _int_list(value: object) -> List[int]:
    if not isinstance(value, list):
        return []
    return [int(item) for item in value if isinstance(item, int) or str(item).isdigit()]


def _string_list(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _render_markdown(plan: Dict[str, object]) -> str:
    lines = [
        "# Series Cloud Archiver MV3 Transfer Plan",
        "",
        f"- Mode: `{plan.get('mode', '')}`",
        f"- Source mode: `{plan.get('source_mode', '')}`",
        f"- Included statuses: `{', '.join(plan.get('included_statuses', []))}`",
        f"- Planned groups before row limit: `{plan.get('total_planned', 0)}`",
        f"- Planned size in this report: `{_human_size(int(plan.get('total_size_bytes') or 0))}`",
        f"- Source status counts: `{plan.get('status_counts', {})}`",
        "- Safety: readonly plan only; no MV3 transfer, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed.",
        "",
    ]
    warnings = plan.get("warnings", [])
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.extend(
        [
            "## Transfer Queue",
            "",
            "| Priority | Size | TMDB ID | Season | Expected | Candidates | Title | Source title sample | Source path sample |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for index, item in enumerate(plan.get("items", []), start=1):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {priority} | {size} | {tmdbid} | {season} | {expected} | {candidates} | {title} | {source_title} | {source_path} |".format(
                priority=index,
                size=_human_size(int(item.get("size_bytes") or 0)),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                expected=_episode_cell(item.get("expected_episodes")) or item.get("expected_count") or "",
                candidates=item.get("candidate_count") or "",
                title=_escape_cell(str(item.get("title") or "")),
                source_title=_escape_cell(_first(item.get("titles"))),
                source_path=_escape_cell(_first(item.get("source_paths"))),
            )
        )
    lines.append("")
    lines.append(
        "Next gate: before any real MV3 transfer, each row still needs a transfer API mapping, STRM re-scan, Emby library confirmation, playback probe, qB seed-age check, and manual approval."
    )
    return "\n".join(lines)


def _render_restored_transfer_queue_markdown(report: Dict[str, object]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    mv3_status = report.get("mv3_status") if isinstance(report.get("mv3_status"), dict) else {}
    lines = [
        "# MV3 Restored Transfer Queue",
        "",
        f"- Mode: `{report.get('mode', '')}`",
        f"- Source mode: `{report.get('source_mode', '')}`",
        f"- Current cloud-check items: `{report.get('current_items', 0)}`",
        f"- Ready when MV3 restored: `{summary.get('ready_when_mv3_restored', 0)}`",
        f"- Needs identity review: `{summary.get('needs_identity_review', 0)}`",
        f"- Historical candidate samples available: `{summary.get('historical_candidate_for_cloud_check', 0)}`",
        f"- MV3 configured: `{bool(mv3_status.get('configured'))}`",
        f"- MV3 reachable: `{bool(mv3_status.get('reachable'))}`",
        f"- MV3 license status: `{mv3_status.get('license_status', '')}`",
        "- Safety: readonly queue only; no MV3 search, transfer, STRM generation, qBittorrent action, MoviePilot cleanup, Emby refresh, cloud write, hlink deletion, or filesystem deletion is performed.",
    ]
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    lines.extend(["", "## Ready When MV3 Restored", ""])
    _append_queue_table(lines, report.get("ready_when_mv3_restored"))
    lines.extend(["", "## Needs Identity Review Before Transfer", ""])
    _append_queue_table(lines, report.get("needs_identity_review_before_transfer"))
    historical = report.get("historical_candidate_samples")
    if isinstance(historical, list) and historical:
        lines.extend(
            [
                "",
                "## Historical Candidate Samples",
                "",
                "| # | Size | TMDB ID | Season | Videos | Title | Path |",
                "| ---: | ---: | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for index, item in enumerate(historical, start=1):
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {index} | {size} | {tmdbid} | {season} | {videos} | {title} | {path} |".format(
                    index=index,
                    size=_human_size(int(item.get("size_bytes") or 0)),
                    tmdbid=item.get("tmdbid") or "",
                    season=item.get("season") or "",
                    videos=item.get("video_count") or "",
                    title=_escape_cell(str(item.get("title") or "")),
                    path=_escape_cell(str(item.get("path") or "")),
                )
            )
    lines.append("")
    lines.append("Next gate: activate MV3 first, then run share/cloud search for ready rows and compare whole-season size plus episode coverage before any receive/organize/STRM operation.")
    return "\n".join(lines)


def _append_queue_table(lines: List[str], rows: object) -> None:
    if not isinstance(rows, list) or not rows:
        lines.append("_No rows._")
        return
    lines.extend(
        [
            "| # | Size | TMDB ID | Season | Expected | Title | Keywords | Source path sample | Next gate |",
            "| ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for index, item in enumerate(rows, start=1):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {index} | {size} | {tmdbid} | {season} | {expected} | {title} | {keywords} | {source_path} | {next_gate} |".format(
                index=index,
                size=_human_size(int(item.get("size_bytes") or 0)),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                expected=_episode_cell(item.get("expected_episodes")) or item.get("expected_count") or "",
                title=_escape_cell(str(item.get("title") or "")),
                keywords=_escape_cell(", ".join(_string_list(item.get("search_keywords"))[:3])),
                source_path=_escape_cell(_first(item.get("source_paths"))),
                next_gate=_escape_cell(str(item.get("next_gate") or "")),
            )
        )


def _render_preview_manifest_markdown(manifest: Dict[str, object]) -> str:
    context = manifest.get("mv3_context") if isinstance(manifest.get("mv3_context"), dict) else {}
    lines = [
        "# Series Cloud Archiver MV3 Preview Manifest",
        "",
        f"- Mode: `{manifest.get('mode', '')}`",
        f"- Source mode: `{manifest.get('source_mode', '')}`",
        f"- Available transfer items: `{manifest.get('available_items', 0)}`",
        f"- Planned items in this manifest: `{manifest.get('planned_items', 0)}`",
        f"- Planned size in this manifest: `{_human_size(int(manifest.get('total_size_bytes') or 0))}`",
        f"- MV3 preview endpoint: `{MV3_PREVIEW_ENDPOINT['method']} {MV3_PREVIEW_ENDPOINT['path']}`",
        f"- MV3 media-transfer instance: `{context.get('media_transfer_instance', '')}`",
        f"- Proposed cloud root: `{context.get('cloud_root', '')}`",
        "- Safety: readonly manifest only; no MV3 preview, transfer execute, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed.",
        "",
        "## Forbidden Endpoints",
        "",
    ]
    for endpoint in manifest.get("forbidden_endpoints", []):
        lines.append(f"- `{endpoint}`")
    warnings = manifest.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "## Manifest Items",
            "",
            "| Priority | Size | TMDB ID | Season | Expected | Title | Proposed cloud destination | Preview call | Blockers | Source path sample |",
            "| ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        preview_call = item.get("mv3_preview_call") if isinstance(item.get("mv3_preview_call"), dict) else {}
        lines.append(
            "| {priority} | {size} | {tmdbid} | {season} | {expected} | {title} | {destination} | {preview} | {blockers} | {source_path} |".format(
                priority=item.get("priority") or "",
                size=_human_size(int(item.get("size_bytes") or 0)),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                expected=_episode_cell(item.get("expected_episodes")) or item.get("expected_count") or "",
                title=_escape_cell(str(item.get("title") or "")),
                destination=_escape_cell(str(item.get("proposed_cloud_destination") or "")),
                preview=_escape_cell(f"{preview_call.get('method', '')} {preview_call.get('path', '')}".strip()),
                blockers=_escape_cell(", ".join(_string_list(item.get("execution_blockers")))),
                source_path=_escape_cell(_first(item.get("source_paths"))),
            )
        )
    lines.append("")
    lines.append(
        "Next gate: fill MV3 source/target library IDs through a successful readonly library/item lookup, then call the preview endpoint for one approved row before any execute endpoint is allowed."
    )
    return "\n".join(lines)


def _render_offline_manifest_markdown(manifest: Dict[str, object]) -> str:
    context = manifest.get("mv3_context") if isinstance(manifest.get("mv3_context"), dict) else {}
    lines = [
        "# Series Cloud Archiver MV3 Offline Manifest",
        "",
        f"- Mode: `{manifest.get('mode', '')}`",
        f"- Source mode: `{manifest.get('source_mode', '')}`",
        f"- Available transfer items: `{manifest.get('available_items', 0)}`",
        f"- Planned items in this manifest: `{manifest.get('planned_items', 0)}`",
        f"- Planned size in this manifest: `{_human_size(int(manifest.get('total_size_bytes') or 0))}`",
        f"- MV3 cloud drive: `{context.get('cloud_drive_slug', '')}`",
        f"- Proposed cloud root: `{context.get('cloud_root', '')}`",
        f"- Minimum qB seed days: `{manifest.get('min_seed_days', 0)}`",
        f"- Offline destination mode: `{manifest.get('destination_mode', 'season')}`",
        "- Safety: readonly offline manifest only; no MV3 offline task, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed.",
        "- Privacy: magnet URIs are not written to this report.",
        "",
        "## Forbidden Endpoints",
        "",
    ]
    for endpoint in manifest.get("forbidden_endpoints", []):
        lines.append(f"- `{endpoint}`")
    warnings = manifest.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "## Manifest Items",
            "",
            "| Priority | Size | TMDB ID | Season | Expected | qB Matches | Magnets | Seed OK | Title | Offline target | Proposed organized destination | Blockers |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {priority} | {size} | {tmdbid} | {season} | {expected} | {matches} | {magnets} | {seed_ok} | {title} | {offline} | {destination} | {blockers} |".format(
                priority=item.get("priority") or "",
                size=_human_size(int(item.get("size_bytes") or 0)),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                expected=_episode_cell(item.get("expected_episodes")) or item.get("expected_count") or "",
                matches=item.get("qb_match_count") or 0,
                magnets=item.get("qb_magnet_available_count") or 0,
                seed_ok=item.get("qb_seed_age_ok_count") or 0,
                title=_escape_cell(str(item.get("title") or "")),
                offline=_escape_cell(str(item.get("offline_wp_path") or item.get("proposed_cloud_destination") or "")),
                destination=_escape_cell(str(item.get("proposed_cloud_destination") or "")),
                blockers=_escape_cell(", ".join(_string_list(item.get("execution_blockers")))),
            )
        )
    lines.append("")
    lines.append(
        "Next gate: choose one approved row with qB magnet coverage, run a single MV3 offline-add probe only after explicit approval, then wait for cloud completion before generating STRM."
    )
    return "\n".join(lines)


def _render_share_search_plan_markdown(plan: Dict[str, object]) -> str:
    lines = [
        "# Series Cloud Archiver MV3 Share Search Plan",
        "",
        f"- Mode: `{plan.get('mode', '')}`",
        f"- Source mode: `{plan.get('source_mode', '')}`",
        f"- Available transfer items: `{plan.get('available_items', 0)}`",
        f"- Planned items in this report: `{plan.get('planned_items', 0)}`",
        f"- Items with recommended candidate: `{plan.get('ready_items', 0)}`",
        f"- Planned size in this report: `{_human_size(int(plan.get('total_size_bytes') or 0))}`",
        "- Safety: readonly MV3 resource-search planning only; no share receive, organize transfer, STRM generation, qBittorrent action, hlink deletion, or filesystem deletion is performed.",
        "",
        "## Recommended Candidates",
        "",
        "| Priority | Size | TMDB ID | Season | Expected | Title | Candidate | Candidate size | Score | Reasons | Blockers |",
        "| ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | --- | --- |",
    ]
    for item in plan.get("items", []):
        if not isinstance(item, dict):
            continue
        candidate = item.get("recommended_candidate") if isinstance(item.get("recommended_candidate"), dict) else {}
        lines.append(
            "| {priority} | {size} | {tmdbid} | {season} | {expected} | {title} | {candidate} | {candidate_size} | {score} | {reasons} | {blockers} |".format(
                priority=item.get("priority") or "",
                size=_human_size(int(item.get("size_bytes") or 0)),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                expected=_episode_cell(item.get("expected_episodes")) or item.get("expected_count") or "",
                title=_escape_cell(str(item.get("title") or "")),
                candidate=_escape_cell(str(candidate.get("title") or "")),
                candidate_size=_human_size(int(candidate.get("size_bytes") or 0)) if candidate else "",
                score=candidate.get("score", "") if candidate else "",
                reasons=_escape_cell(", ".join(_string_list(candidate.get("reasons"))) if candidate else ""),
                blockers=_escape_cell(", ".join(_string_list(candidate.get("blockers"))) if candidate else ""),
            )
        )
    lines.extend(
        [
            "",
            "## Search Details",
            "",
            "| Priority | Search OK | Results | Warnings | Source path sample |",
            "| ---: | --- | ---: | --- | --- |",
        ]
    )
    for item in plan.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {priority} | {ok} | {count} | {warnings} | {source_path} |".format(
                priority=item.get("priority") or "",
                ok=str(bool(item.get("search_ok"))),
                count=item.get("search_result_count") or 0,
                warnings=_escape_cell(", ".join(_string_list(item.get("warnings")))),
                source_path=_escape_cell(_first(item.get("source_paths"))),
            )
        )
    lines.append("")
    lines.append("Next gate: preview the recommended share, browse the exact folder, verify episode coverage and size before any receive/organize action.")
    return "\n".join(lines)


def _first(value: object) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return ""


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _episode_cell(value: object) -> str:
    episodes = _int_list(value)
    if not episodes:
        return ""
    ranges: List[str] = []
    start = previous = episodes[0]
    for episode in episodes[1:]:
        if episode == previous + 1:
            previous = episode
            continue
        ranges.append(f"{start}-{previous}" if start != previous else str(start))
        start = previous = episode
    ranges.append(f"{start}-{previous}" if start != previous else str(start))
    return ",".join(ranges)


def _human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"
