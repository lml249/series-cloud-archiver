from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional


DEFAULT_TRANSFER_STATUSES = ["cloud_strm_not_found"]
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


def plan_mv3_preview_manifest(
    transfer_plan: Dict[str, object],
    instances_report: Optional[Dict[str, object]] = None,
    capabilities_report: Optional[Dict[str, object]] = None,
    limit: int = 10,
    cloud_root: str = "/series",
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
    cloud_root: str = "/series",
    min_seed_days: int = 7,
) -> Dict[str, object]:
    raw_items = [item for item in transfer_plan.get("items", []) if isinstance(item, dict)]
    selected_items = raw_items[: limit if limit > 0 else len(raw_items)]
    context = _mv3_offline_context(instances_report, cloud_root)
    items = [
        _offline_manifest_item(index, item, qb_torrents, context, min_seed_days)
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


def _transfer_item(item: Dict[str, object]) -> Dict[str, object]:
    return {
        "source_status": str(item.get("status") or ""),
        "title": str(item.get("title") or ""),
        "tmdbid": int(item.get("tmdbid") or 0),
        "season": int(item.get("season") or 0),
        "size_bytes": int(item.get("size_bytes") or 0),
        "candidate_count": int(item.get("candidate_count") or 0),
        "expected_count": int(item.get("expected_count") or 0),
        "missing_episodes": _int_list(item.get("missing_episodes")),
        "titles": _string_list(item.get("titles")),
        "source_paths": _string_list(item.get("source_paths")),
        "blockers": _string_list(item.get("blockers")),
    }


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
    normalized_cloud_root = (cloud_root or "/series").rstrip("/") or "/series"
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
    destination = _proposed_cloud_destination(context.get("cloud_root", "/series"), item)
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


def _proposed_cloud_destination(cloud_root: object, item: Dict[str, object]) -> str:
    root = str(cloud_root or "/series").rstrip("/") or "/series"
    title = _safe_cloud_segment(str(item.get("title") or "unknown"))
    tmdbid = int(item.get("tmdbid") or 0)
    season = int(item.get("season") or 0)
    season_segment = f"Season {season:02d}" if season > 0 else "Season XX"
    return f"{root}/{title} {{tmdbid={tmdbid}}}/{season_segment}"


def _safe_cloud_segment(value: str) -> str:
    cleaned = value.replace("/", " ").replace("\\", " ").strip()
    return " ".join(cleaned.split()) or "unknown"


def _mv3_offline_context(instances_report: Optional[Dict[str, object]], cloud_root: str) -> Dict[str, object]:
    warnings: List[str] = []
    cloud_drive = _first_cloud_drive(instances_report)
    mount_paths = {}
    if isinstance(cloud_drive, dict) and isinstance(cloud_drive.get("mount_path"), dict):
        mount_paths = {str(key): str(value) for key, value in cloud_drive["mount_path"].items()}
    normalized_cloud_root = (cloud_root or "/series").rstrip("/") or "/series"
    if mount_paths and normalized_cloud_root not in mount_paths and normalized_cloud_root not in mount_paths.values():
        warnings.append(f"cloud_root_not_in_mv3_mount_paths:{normalized_cloud_root}")
    if not cloud_drive:
        warnings.append("mv3_cloud_drive_not_found")
    return {
        "cloud_root": normalized_cloud_root,
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
) -> Dict[str, object]:
    matches = _match_qb_torrents_for_transfer_item(item, qb_torrents)
    magnet_count = sum(1 for torrent in matches if str(torrent.get("magnet_uri") or ""))
    seed_ok_count = sum(1 for torrent in matches if int(torrent.get("seeding_time") or 0) >= min_seed_days * 86400)
    destination = _proposed_cloud_destination(context.get("cloud_root", "/series"), item)
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
                "wp_path": destination,
                "wp_path_id": "[OPTIONAL_TARGET_FOLDER_ID]",
            },
        },
        "post_offline_strm_generate_call": {
            "method": MV3_STRM_GENERATE_ENDPOINT["method"],
            "path": MV3_STRM_GENERATE_ENDPOINT["path"],
            "body_template": {
                "storage": context.get("cloud_drive_slug") or "[REQUIRES_MV3_CLOUD_DRIVE]",
                "source_dir": destination,
                "target_dir": destination,
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
        if any(title and (title in name or name in title) for title in wanted_titles):
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
                expected=item.get("expected_count") or "",
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
                expected=item.get("expected_count") or "",
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
            "| Priority | Size | TMDB ID | Season | Expected | qB Matches | Magnets | Seed OK | Title | Proposed cloud destination | Blockers |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {priority} | {size} | {tmdbid} | {season} | {expected} | {matches} | {magnets} | {seed_ok} | {title} | {destination} | {blockers} |".format(
                priority=item.get("priority") or "",
                size=_human_size(int(item.get("size_bytes") or 0)),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                expected=item.get("expected_count") or "",
                matches=item.get("qb_match_count") or 0,
                magnets=item.get("qb_magnet_available_count") or 0,
                seed_ok=item.get("qb_seed_age_ok_count") or 0,
                title=_escape_cell(str(item.get("title") or "")),
                destination=_escape_cell(str(item.get("proposed_cloud_destination") or "")),
                blockers=_escape_cell(", ".join(_string_list(item.get("execution_blockers")))),
            )
        )
    lines.append("")
    lines.append(
        "Next gate: choose one approved row with qB magnet coverage, run a single MV3 offline-add probe only after explicit approval, then wait for cloud completion before generating STRM."
    )
    return "\n".join(lines)


def _first(value: object) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return ""


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"
