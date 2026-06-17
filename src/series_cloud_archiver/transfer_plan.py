from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List


DEFAULT_TRANSFER_STATUSES = ["cloud_strm_not_found"]


def load_cloud_check_report(path: str) -> Dict[str, object]:
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
