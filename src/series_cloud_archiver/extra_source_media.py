from __future__ import annotations

import csv
import io
import json
import re
import shlex
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

from .episode import VIDEO_EXTENSIONS


JsonDict = Dict[str, object]


def build_extra_source_media_plan(
    finalize_run_report: JsonDict,
    *,
    env_file: str = "",
    target_dir: str = "/已整理",
    strm_dir: str = "/strm",
    storage: str = "115-default",
    timeout: int = 120,
    title: str = "",
    tmdbid: int = 0,
    season: int = 0,
) -> JsonDict:
    """Build a readonly follow-up plan for source videos not covered by hlink.

    These rows are intentionally not treated as cleanup approvals. They are
    unresolved local source media that must be migrated or explicitly excluded
    before the original qB/source/hlink cleanup gate can pass.
    """

    rows: List[JsonDict] = []
    seen: set[Tuple[str, str, int, int]] = set()
    for item in finalize_run_report.get("items", []) if isinstance(finalize_run_report.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        if "source_root_check_failed" not in _strings(item.get("blockers")):
            continue
        item_title = str(item.get("title") or "")
        item_tmdbid = int(item.get("tmdbid") or 0)
        main_season = int(item.get("season") or 0)
        if title and item_title != title:
            continue
        if tmdbid and item_tmdbid != tmdbid:
            continue
        if season and main_season != season:
            continue
        unlinked_paths = _unlinked_video_paths(item)
        for source_path in unlinked_paths:
            media = _media_row(
                title=item_title,
                tmdbid=item_tmdbid,
                main_season=main_season,
                source_path=source_path,
                env_file=env_file,
                target_dir=target_dir,
                strm_dir=strm_dir,
                storage=storage,
                timeout=timeout,
            )
            key = (str(media.get("title")), source_path, int(media.get("suggested_season") or 0), int(media.get("episode") or 0))
            if key in seen:
                continue
            seen.add(key)
            rows.append(media)

    status_counts: Dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "mode": "readonly-extra-source-media-plan",
        "source_mode": str(finalize_run_report.get("mode") or ""),
        "ok": True,
        "planned_items": len(rows),
        "ready_for_mv3_scan_items": status_counts.get("ready_for_mv3_scan", 0),
        "manual_review_items": status_counts.get("manual_review_required", 0),
        "status_counts": status_counts,
        "items": rows,
        "settings": {
            "target_dir": target_dir,
            "strm_dir": strm_dir,
            "storage": storage,
            "timeout": timeout,
            "title": title,
            "tmdbid": tmdbid,
            "season": season,
        },
        "safety": (
            "readonly follow-up plan only; it promotes source videos that blocked cleanup into MV3 scan-source command "
            "templates. It does not transfer, organize, generate STRM, scrape, refresh Emby, touch qBittorrent, "
            "or delete hlink/source files."
        ),
    }


def render_extra_source_media_plan(report: JsonDict, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    if output_format == "csv":
        return _render_csv(report)
    lines = [
        "# Extra Source Media Plan",
        "",
        f"- Planned items: `{report.get('planned_items', 0)}`",
        f"- Ready for MV3 scan: `{report.get('ready_for_mv3_scan_items', 0)}`",
        f"- Manual review: `{report.get('manual_review_items', 0)}`",
        "- Safety: readonly plan only; no transfer, STRM generation, scraping, Emby refresh, qB action, or deletion is performed.",
        "",
        "| Status | TMDB | S | E | Kind | Title | Source | Next action |",
        "| --- | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for item in report.get("items", []) if isinstance(report.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {status} | {tmdbid} | {season} | {episode} | {kind} | {title} | {source} | {next_action} |".format(
                status=_escape_cell(str(item.get("status") or "")),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("suggested_season") or "",
                episode=item.get("episode") or "",
                kind=_escape_cell(str(item.get("media_kind") or "")),
                title=_escape_cell(str(item.get("title") or "")),
                source=_escape_cell(str(item.get("source_path") or "")),
                next_action=_escape_cell(str(item.get("next_action") or "")),
            )
        )
    return "\n".join(lines)


def _media_row(
    *,
    title: str,
    tmdbid: int,
    main_season: int,
    source_path: str,
    env_file: str,
    target_dir: str,
    strm_dir: str,
    storage: str,
    timeout: int,
) -> JsonDict:
    name = PurePosixPath(source_path).name
    season, episode = _season_episode_from_name(name)
    media_kind = _media_kind_from_name(name)
    suggested_season = season if season is not None else (0 if media_kind == "special" else main_season)
    blockers: List[str] = []
    review_reasons: List[str] = []
    if tmdbid <= 0:
        blockers.append("tmdb_id_required")
    if not source_path:
        blockers.append("source_path_required")
    if media_kind == "unknown":
        review_reasons.append("episode_signal_missing")
    if suggested_season < 0:
        review_reasons.append("season_signal_invalid")

    status = "ready_for_mv3_scan" if not blockers else "manual_review_required"
    if review_reasons:
        status = "manual_review_required"
    commands: List[JsonDict] = []
    if status == "ready_for_mv3_scan":
        commands = _commands(
            source_path=source_path,
            title=title,
            tmdbid=tmdbid,
            suggested_season=suggested_season,
            episode=episode or 0,
            media_kind=media_kind,
            env_file=env_file,
            target_dir=target_dir,
            strm_dir=strm_dir,
            storage=storage,
            timeout=timeout,
        )

    return {
        "status": status,
        "title": title,
        "tmdbid": tmdbid,
        "main_season": main_season,
        "suggested_season": suggested_season,
        "episode": episode or 0,
        "media_kind": media_kind,
        "source_path": source_path,
        "file_name": name,
        "review_reasons": sorted(set(review_reasons)),
        "blockers": sorted(set(blockers)),
        "commands": commands,
        "next_action": _next_action(status, media_kind),
    }


def _commands(
    *,
    source_path: str,
    title: str,
    tmdbid: int,
    suggested_season: int,
    episode: int,
    media_kind: str,
    env_file: str,
    target_dir: str,
    strm_dir: str,
    storage: str,
    timeout: int,
) -> List[JsonDict]:
    report_prefix = _safe_prefix(title, tmdbid, suggested_season, source_path)
    env = f"--env-file {_q(env_file)} " if env_file else ""
    scan_report = f"{report_prefix}-mv3-organize-scan-source.json"
    commands: List[JsonDict] = [
        {
            "stage": "mv3_organize_scan_source",
            "output": scan_report,
            "command": (
                f"PYTHONPATH=src python3 -m series_cloud_archiver mv3-organize-scan-source {env}"
                f"--source-path {_q(source_path)} --local-source --file --storage {_q(storage)} "
                f"--timeout {int(timeout)} --format json --output {_q(scan_report)}"
            ),
        }
    ]
    if media_kind == "special":
        commands.append(
            {
                "stage": "confirmed_local_mapping_required",
                "requires": [
                    "scan-source report",
                    "confirmed TMDB Season 00 episode number",
                    "human approval",
                ],
                "command": (
                    "确认这个特辑对应的 TMDB Season 00 集号后，写入 confirmed local mapping JSON，"
                    "再用 mv3-organize-transfer-from-local-map --approve-transfer 让 MV3 copy 到 /已整理 并生成 STRM"
                ),
            }
        )
        return commands
    expected_count = 1 if episode > 0 else 0
    expected_min = episode if episode > 0 else 0
    expected_max = episode if episode > 0 else 0
    commands.append(
        {
            "stage": "mv3_organize_transfer_from_scan_approval_required",
            "requires": [
                scan_report,
                "scan-source confirms the file is the expected extra/special video",
                "human approval",
            ],
            "approval_flag_required": "--approve-transfer",
            "command": (
                f"PYTHONPATH=src python3 -m series_cloud_archiver mv3-organize-transfer-from-scan {env}"
                f"--scan-report {_q(scan_report)} --target-dir {_q(target_dir)} --strm-dir {_q(strm_dir)} "
                f"--tmdb-id {tmdbid} --expected-episode-count {expected_count} "
                f"--expected-episode-min {expected_min} --expected-episode-max {expected_max} "
                f"--mode copy --local-source --timeout {int(timeout)} "
                f"--format json --output {_q(report_prefix + '-mv3-organize-transfer.json')} "
                "# approval required before execution"
            ),
        }
    )
    return commands


def _unlinked_video_paths(item: JsonDict) -> List[str]:
    paths: List[str] = []
    paths.extend(_strings(item.get("cleanup_unlinked_video_sample")))
    for root in item.get("cleanup_blocked_source_roots", []) if isinstance(item.get("cleanup_blocked_source_roots"), list) else []:
        if isinstance(root, dict):
            paths.extend(_strings(root.get("unlinked_video_sample")))
    return sorted({path for path in paths if path and PurePosixPath(path).suffix.lower() in VIDEO_EXTENSIONS})


def _season_episode_from_name(name: str) -> Tuple[Optional[int], Optional[int]]:
    patterns = [
        re.compile(r"(?i)\bS(?P<season>\d{1,2})[ ._-]*E(?P<episode>\d{1,3})\b"),
        re.compile(r"(?i)\b(?P<season>\d{1,2})x(?P<episode>\d{1,3})\b"),
    ]
    for pattern in patterns:
        match = pattern.search(name)
        if match:
            return int(match.group("season")), int(match.group("episode"))
    sp_match = re.search(r"(?i)(?:^|[\s._\-\[\(])SP(?P<episode>\d{1,3})(?=$|[\s._\-\]\)])", name)
    if sp_match:
        return 0, int(sp_match.group("episode"))
    episode_match = re.search(r"(?i)(?:^|[\s._\-\[\(])E(?:P)?(?P<episode>\d{1,3})(?=$|[\s._\-\]\)])", name)
    if episode_match:
        return None, int(episode_match.group("episode"))
    return None, None


def _media_kind_from_name(name: str) -> str:
    if re.search(r"(?i)(?:^|[\s._\-\[\(])SP\d{0,3}(?=$|[\s._\-\]\)])", name):
        return "special"
    if re.search(r"(?i)\b(?:special|making|featurette|behind[ ._-]*the[ ._-]*scenes|we[ ._-]*stand[ ._-]*alone)\b", name):
        return "special"
    if _season_episode_from_name(name)[1] is not None:
        return "episode"
    return "unknown"


def _next_action(status: str, media_kind: str) -> str:
    if status == "ready_for_mv3_scan":
        if media_kind == "special":
            return "先用 MV3 scan-source 识别特辑，再确认 Season 00/集号映射后转云盘并生成 STRM"
        return "先用 MV3 scan-source 验证额外视频，再确认是否应纳入云端 STRM"
    return "人工确认这条额外视频的剧集/季/集归属后再继续"


def _safe_prefix(title: str, tmdbid: int, season: int, source_path: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z一-龥]+", "-", f"{title}-{tmdbid}-s{season:02d}-{PurePosixPath(source_path).stem}").strip("-")
    return slug[-120:] or "extra-source-media"


def _render_csv(report: JsonDict) -> str:
    fieldnames = [
        "status",
        "title",
        "tmdbid",
        "main_season",
        "suggested_season",
        "episode",
        "media_kind",
        "source_path",
        "review_reasons",
        "blockers",
        "next_action",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for item in report.get("items", []) if isinstance(report.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        row["review_reasons"] = "; ".join(_strings(item.get("review_reasons")))
        row["blockers"] = "; ".join(_strings(item.get("blockers")))
        writer.writerow({name: row.get(name, "") for name in fieldnames})
    return output.getvalue().rstrip("\r\n")


def _strings(value: object) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [value]
    return []


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _q(value: object) -> str:
    return shlex.quote(str(value))
