from __future__ import annotations

import json
from typing import Iterable

from .models import ScanCandidate, ScanReport


def human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"


def render_json(report: ScanReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def _reason_text(candidate: ScanCandidate) -> str:
    parts = []
    if candidate.reasons:
        parts.append("reasons=" + ",".join(candidate.reasons))
    if candidate.blockers:
        parts.append("blockers=" + ",".join(candidate.blockers))
    return "; ".join(parts)


def render_markdown(report: ScanReport) -> str:
    lines = [
        "# Series Cloud Archiver Readonly Scan",
        "",
        f"- Mode: `{report.mode}`",
        f"- Media roots: `{', '.join(report.media_roots)}`",
        f"- Minimum seed days: `{report.min_seed_days}`",
        f"- Total series folders scanned: `{report.total_series}`",
        f"- Status counts before row limit: `{report.status_counts}`",
        "- Safety: readonly scan only; no transfer, STRM generation, or deletion is performed.",
        "",
    ]
    if report.warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in report.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.extend(
        [
            "## Candidates",
            "",
            "| Status | Score | Size | Videos | Age days | Seed days | Title | Notes |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for candidate in report.candidates:
        seed_days = f"{candidate.qb.seed_days:.1f}" if candidate.qb else "n/a"
        lines.append(
            "| {status} | {score} | {size} | {videos} | {age:.1f} | {seed} | {title} | {notes} |".format(
                status=candidate.status,
                score=candidate.score,
                size=human_size(candidate.size_bytes),
                videos=candidate.video_count,
                age=candidate.age_days,
                seed=seed_days,
                title=candidate.title.replace("|", "\\|"),
                notes=_reason_text(candidate).replace("|", "\\|"),
            )
        )
    lines.append("")
    lines.append(
        "Readonly MVP note: `candidate_for_cloud_check` only means the item is worth checking in MV3/cloud. It is not a cleanup candidate until qB seed age, Emby STRM coverage, playback probes, and dry-run approval all pass."
    )
    return "\n".join(lines)


def render_report(report: ScanReport, output_format: str) -> str:
    if output_format == "json":
        return render_json(report)
    return render_markdown(report)
