from __future__ import annotations

import csv
import io
import json
import re
import shlex
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .cleanup_verify import audit_strm_nfo_language, verify_strm_paths
from .emby import delete_stale_emby_paths, notify_and_verify_emby_media_updated
from .hlink_cleanup import cleanup_empty_hlink_root, execute_cloud_hlink_cleanup, preview_cloud_hlink_cleanup
from .moviepilot import scrape_mp_strm_path
from .mv3 import cleanup_mv3_cloud_duplicate_videos
from .reporting import human_size
from .transfer_plan import DEFAULT_CLOUD_ROOT, DEFAULT_STRM_ROOT


AUTO_TRANSFER = "auto_ready_for_transfer_preview"
AUTO_CLEANUP = "auto_ready_for_validation_cleanup"
MANUAL_REVIEW = "manual_review"
SKIPPED = "skipped"


@dataclass
class BatchFinalizeActions:
    verify_strm: Callable[..., Dict[str, object]] = verify_strm_paths
    cloud_duplicate_cleanup: Callable[..., Dict[str, object]] = cleanup_mv3_cloud_duplicate_videos
    scrape_mp_strm: Callable[..., Dict[str, object]] = scrape_mp_strm_path
    audit_nfo_language: Callable[..., Dict[str, object]] = audit_strm_nfo_language
    emby_media_updated: Callable[..., Dict[str, object]] = notify_and_verify_emby_media_updated
    emby_delete_stale: Callable[..., Dict[str, object]] = delete_stale_emby_paths
    cleanup_preview: Callable[..., Dict[str, object]] = preview_cloud_hlink_cleanup
    cleanup_execute: Callable[..., Dict[str, object]] = execute_cloud_hlink_cleanup
    empty_hlink_root_cleanup: Callable[..., Dict[str, object]] = cleanup_empty_hlink_root


def build_batch_plan(
    *,
    cloud_report: Dict[str, object],
    transfer_plan: Optional[Dict[str, object]] = None,
    share_search_plan: Optional[Dict[str, object]] = None,
    share_search_plans: Optional[Sequence[Dict[str, object]]] = None,
    cleanup_preview_reports: Optional[Sequence[Dict[str, object]]] = None,
    scan_report: Optional[Dict[str, object]] = None,
    cloud_root: str = DEFAULT_CLOUD_ROOT,
    mv3_strm_root: str = DEFAULT_STRM_ROOT,
    host_strm_root: str = "",
    emby_strm_root: str = "",
    env_file: str = "",
    min_candidate_score: int = 60,
    max_auto_size_delta: float = 0.35,
    required_target_prefix: str = "/已整理",
    forbidden_target_prefixes: Optional[Sequence[str]] = None,
    limit: int = 0,
) -> Dict[str, object]:
    """Build a readonly batch state-machine plan from existing scan/search reports."""

    effective_share_search_plan = merge_share_search_plans(
        ([share_search_plan] if share_search_plan else []) + list(share_search_plans or [])
    )
    cloud_items = [item for item in cloud_report.get("items", []) if isinstance(item, dict)]
    transfer_by_key = _items_by_identity((transfer_plan or {}).get("items", []))
    share_by_key = _items_by_identity((effective_share_search_plan or {}).get("items", []))
    cleanup_by_key = _cleanup_previews_by_identity(cleanup_preview_reports or [])
    scan_by_key = _scan_candidates_by_identity((scan_report or {}).get("candidates", []))
    forbidden = [str(item) for item in (forbidden_target_prefixes or []) if str(item)]

    rows: List[Dict[str, object]] = []
    for item in cloud_items:
        key = _identity_key(item)
        transfer_item = transfer_by_key.get(key, {})
        share_item = share_by_key.get(key, {})
        cleanup_preview = cleanup_by_key.get(key, {})
        scan_candidates = scan_by_key.get(key, [])
        rows.append(
            _batch_item(
                item,
                transfer_item,
                share_item,
                cleanup_preview,
                scan_candidates,
                env_file=env_file,
                cloud_root=cloud_root,
                mv3_strm_root=mv3_strm_root,
                host_strm_root=host_strm_root,
                emby_strm_root=emby_strm_root,
                min_candidate_score=min_candidate_score,
                max_auto_size_delta=max_auto_size_delta,
                required_target_prefix=required_target_prefix,
                forbidden_target_prefixes=forbidden,
            )
        )

    rows.sort(key=_batch_sort_key)
    total_rows = len(rows)
    if limit > 0:
        rows = rows[:limit]

    counts = Counter(str(row.get("bucket") or "") for row in rows)
    return {
        "mode": "readonly-batch-state-plan",
        "source_modes": {
            "scan": (scan_report or {}).get("mode", ""),
            "cloud": cloud_report.get("mode", ""),
            "transfer": (transfer_plan or {}).get("mode", ""),
            "share_search": (effective_share_search_plan or {}).get("mode", ""),
        },
        "total_items_before_limit": total_rows,
        "planned_items": len(rows),
        "bucket_counts": dict(sorted(counts.items())),
        "settings": {
            "cloud_root": cloud_root,
            "mv3_strm_root": mv3_strm_root,
            "host_strm_root": host_strm_root,
            "emby_strm_root": emby_strm_root,
            "min_candidate_score": min_candidate_score,
            "max_auto_size_delta": max_auto_size_delta,
            "required_target_prefix": required_target_prefix,
            "forbidden_target_prefixes": forbidden,
            "share_search_plan_count": int((effective_share_search_plan or {}).get("input_plan_count") or 0),
            "cleanup_preview_report_count": len(cleanup_preview_reports or []),
        },
        "items": rows,
        "auto_transfer_items": [row for row in rows if row.get("bucket") == AUTO_TRANSFER],
        "auto_validation_cleanup_items": [row for row in rows if row.get("bucket") == AUTO_CLEANUP],
        "manual_review_items": [row for row in rows if row.get("bucket") == MANUAL_REVIEW],
        "skipped_items": [row for row in rows if row.get("bucket") == SKIPPED],
        "warnings": _batch_warnings(cloud_report, transfer_plan, effective_share_search_plan),
        "safety": (
            "readonly batch state plan only; no MV3 receive, organize transfer, STRM generation, "
            "MoviePilot scrape, Emby refresh, qBittorrent action, hlink deletion, source deletion, "
            "cloud media write, or filesystem deletion is performed"
        ),
    }


def merge_share_search_plans(plans: Sequence[Dict[str, object]]) -> Optional[Dict[str, object]]:
    valid_plans = [plan for plan in plans if isinstance(plan, dict)]
    if not valid_plans:
        return None

    chosen_by_key: Dict[Tuple[int, int], Dict[str, object]] = {}
    duplicate_counts: Counter = Counter()
    warnings: List[str] = []
    source_modes: List[str] = []
    available_items = 0

    for plan_index, plan in enumerate(valid_plans, start=1):
        mode = str(plan.get("mode") or "")
        if mode:
            source_modes.append(mode)
        available_items = max(available_items, int(plan.get("available_items") or 0))
        raw_warnings = plan.get("warnings")
        if isinstance(raw_warnings, list):
            warnings.extend(str(item) for item in raw_warnings if str(item))

        for item in plan.get("items", []):
            if not isinstance(item, dict):
                continue
            key = _identity_key(item)
            if key == (0, 0):
                continue
            duplicate_counts[key] += 1
            enriched = dict(item)
            enriched["merged_from_plan_index"] = plan_index
            existing = chosen_by_key.get(key)
            if existing is None or _share_plan_item_rank(enriched) > _share_plan_item_rank(existing):
                chosen_by_key[key] = enriched

    items = [dict(item) for item in chosen_by_key.values()]
    for item in items:
        key = _identity_key(item)
        item["merged_duplicate_count"] = int(duplicate_counts.get(key, 0))
    items.sort(key=lambda item: (int(item.get("priority") or 999999), int(item.get("tmdbid") or 0), int(item.get("season") or 0)))
    return {
        "mode": "readonly-mv3-share-search-plan-merged",
        "source_modes": sorted(set(source_modes)),
        "input_plan_count": len(valid_plans),
        "available_items": available_items,
        "planned_items": len(items),
        "ready_items": sum(1 for item in items if isinstance(item.get("recommended_candidate"), dict) and item.get("recommended_candidate")),
        "items": items,
        "warnings": sorted(set(warnings)),
        "safety": (
            "merged readonly MV3 resource-search plans only; no share receive, organize transfer, STRM generation, "
            "qBittorrent action, hlink deletion, or filesystem deletion is performed"
        ),
    }


def render_batch_plan(plan: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(plan, ensure_ascii=False, indent=2)
    if output_format == "csv":
        return _render_csv(plan)
    return _render_markdown(plan)


def build_batch_review_report(
    batch_plan: Dict[str, object],
    *,
    share_preview_reports: Optional[Sequence[Dict[str, object]]] = None,
    finalize_run_reports: Optional[Sequence[Dict[str, object]]] = None,
) -> Dict[str, object]:
    """Build a readonly human-review report from batch state and run reports."""

    preview_by_key = _review_preview_by_identity(share_preview_reports or [])
    finalize_by_key = _review_finalize_by_identity(finalize_run_reports or [])
    rows: List[Dict[str, object]] = []

    for index, item in enumerate(batch_plan.get("items", []), start=1):
        if not isinstance(item, dict):
            continue
        key = _review_identity_key(item)
        rows.append(
            _batch_review_row(
                index,
                item,
                preview_by_key.get(key, {}),
                finalize_by_key.get(key, {}),
            )
        )

    decision_counts = Counter(str(row.get("decision") or "") for row in rows)
    bucket_counts = Counter(str(row.get("bucket") or "") for row in rows)
    return {
        "mode": "readonly-batch-human-review-report",
        "source_mode": batch_plan.get("mode", ""),
        "total_items": len(rows),
        "decision_counts": dict(sorted(decision_counts.items())),
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "input_report_counts": {
            "share_preview": len(share_preview_reports or []),
            "finalize_run": len(finalize_run_reports or []),
        },
        "items": rows,
        "safety": (
            "readonly human-review report only; no scan, MV3 receive, organize transfer, STRM generation, "
            "MoviePilot scrape, Emby refresh, qBittorrent action, hlink deletion, source deletion, "
            "cloud media write, or filesystem deletion is performed"
        ),
    }


def render_batch_review_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    if output_format == "csv":
        return _render_review_csv(report)
    return _render_review_markdown(report)


def build_batch_finalize_plan(
    batch_plan: Dict[str, object],
    *,
    env_file: str = "",
    cloud_root: str = "",
    host_strm_root: str = "",
    service_strm_root: str = "",
    required_target_prefix: str = "",
    forbidden_target_prefixes: Optional[Sequence[str]] = None,
    limit: int = 0,
) -> Dict[str, object]:
    """Build a dry-run state-machine plan for STRM scrape, Emby verify, and cleanup gates."""

    settings = batch_plan.get("settings") if isinstance(batch_plan.get("settings"), dict) else {}
    effective_cloud_root = cloud_root or str(settings.get("cloud_root") or DEFAULT_CLOUD_ROOT)
    effective_host_strm_root = host_strm_root or str(settings.get("host_strm_root") or "")
    effective_service_strm_root = service_strm_root or str(settings.get("emby_strm_root") or "")
    forbidden = [str(item) for item in (forbidden_target_prefixes or settings.get("forbidden_target_prefixes") or []) if str(item)]
    rows: List[Dict[str, object]] = []

    for index, item in enumerate(batch_plan.get("items", []), start=1):
        if not isinstance(item, dict):
            continue
        row = _finalize_plan_row(
            index,
            item,
            env_file=env_file,
            cloud_root=effective_cloud_root,
            host_strm_root=effective_host_strm_root,
            service_strm_root=effective_service_strm_root,
            required_target_prefix=required_target_prefix,
            forbidden_target_prefixes=forbidden,
        )
        rows.append(row)
        if limit > 0 and sum(1 for candidate in rows if candidate.get("status") == "planned_finalize") >= limit:
            break

    return {
        "mode": "readonly-batch-finalize-plan",
        "source_mode": batch_plan.get("mode", ""),
        "planned_items": len(rows),
        "finalize_ready_items": sum(1 for row in rows if row.get("status") == "planned_finalize"),
        "skipped_items": sum(1 for row in rows if str(row.get("status") or "").startswith("skipped")),
        "settings": {
            "env_file": env_file,
            "cloud_root": effective_cloud_root,
            "host_strm_root": effective_host_strm_root,
            "service_strm_root": effective_service_strm_root,
            "required_target_prefix": required_target_prefix,
            "forbidden_target_prefixes": forbidden,
            "limit": limit,
        },
        "items": rows,
        "safety": (
            "readonly batch finalize plan only; generated commands are ordered gates for STRM verification, "
            "MoviePilot STRM-side scrape, NFO audit, Emby local update, cleanup preview, and approval-gated cleanup. "
            "No command is executed by this plan, and destructive cleanup commands intentionally omit approval flags."
        ),
    }


def render_batch_finalize_plan(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        "# Batch Finalize Plan",
        "",
        f"- Mode: `{report.get('mode', '')}`",
        f"- Planned rows: `{report.get('planned_items', 0)}`",
        f"- Ready: `{report.get('finalize_ready_items', 0)}`",
        f"- Skipped: `{report.get('skipped_items', 0)}`",
        "- Safety: readonly plan only; approval flags are absent from cleanup commands.",
        "",
        "| Status | TMDB | S | Episodes | Title | Hlink | Reason |",
        "| --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        reason = ", ".join(_string_list(item.get("skip_reasons")) + _string_list(item.get("blockers")))
        lines.append(
            "| {status} | {tmdbid} | {season} | {episodes} | {title} | {hlink} | {reason} |".format(
                status=item.get("status", ""),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                episodes=item.get("expected_episode_count") or "",
                title=_escape_cell(str(item.get("title") or "")),
                hlink=_escape_cell(str(item.get("hlink_root") or "")),
                reason=_escape_cell(reason),
            )
        )
    return "\n".join(lines)


def run_batch_finalize(
    finalize_plan: Dict[str, object],
    *,
    output_dir: str,
    config: object,
    limit: int = 0,
    title_filters: Optional[Sequence[str]] = None,
    continue_on_error: bool = False,
    execute_scrape: bool = False,
    approve_cloud_duplicate_delete: bool = False,
    approve_emby_stale_delete: bool = False,
    approve_delete: bool = False,
    min_seed_days: int = 7,
    cloud_media_storage: str = "115-default",
    timeout: int = 20,
    scrape_timeout: int = 120,
    nfo_min_chinese_ratio: float = 0.35,
    nfo_sample_limit: int = 50,
    actions: Optional[BatchFinalizeActions] = None,
) -> Dict[str, object]:
    """Execute post-transfer gates from a finalize plan.

    The runner is deliberately gate-first: each item stops at the first failed
    stage, and destructive cleanup requires approve_delete=True.
    """

    actions = actions or BatchFinalizeActions()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filters = [value for value in (title_filters or []) if str(value)]
    candidates = _finalize_run_candidates(finalize_plan, filters)
    if limit > 0:
        candidates = candidates[:limit]

    rows: List[Dict[str, object]] = []
    halted = False
    for item in candidates:
        row = _run_finalize_item(
            item,
            output_dir=output_path,
            config=config,
            execute_scrape=execute_scrape,
            approve_cloud_duplicate_delete=approve_cloud_duplicate_delete,
            approve_emby_stale_delete=approve_emby_stale_delete,
            approve_delete=approve_delete,
            min_seed_days=min_seed_days,
            cloud_media_storage=cloud_media_storage,
            timeout=timeout,
            scrape_timeout=scrape_timeout,
            nfo_min_chinese_ratio=nfo_min_chinese_ratio,
            nfo_sample_limit=nfo_sample_limit,
            actions=actions,
        )
        rows.append(row)
        if row.get("status") not in {"cleanup_executed", "cleanup_waiting_for_approval"} and not continue_on_error:
            halted = True
            break

    status_counts = Counter(str(row.get("status") or "") for row in rows)
    stage_counts = Counter(
        str(stage.get("stage") or "")
        for row in rows
        for stage in row.get("stages", [])
        if isinstance(stage, dict)
    )
    return {
        "mode": "batch-finalize-run",
        "source_mode": finalize_plan.get("mode", ""),
        "ok": all(row.get("status") in {"cleanup_executed", "cleanup_waiting_for_approval"} for row in rows) and not halted,
        "halted": halted,
        "planned_items": len(candidates),
        "processed_items": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "stage_counts": dict(sorted(stage_counts.items())),
        "settings": {
            "output_dir": str(output_path),
            "limit": limit,
            "title_filters": filters,
            "continue_on_error": continue_on_error,
            "execute_scrape": execute_scrape,
            "approve_cloud_duplicate_delete": approve_cloud_duplicate_delete,
            "approve_emby_stale_delete": approve_emby_stale_delete,
            "approve_delete": approve_delete,
            "min_seed_days": min_seed_days,
            "cloud_media_storage": cloud_media_storage,
            "timeout": timeout,
            "scrape_timeout": scrape_timeout,
            "nfo_min_chinese_ratio": nfo_min_chinese_ratio,
            "nfo_sample_limit": nfo_sample_limit,
        },
        "items": rows,
        "safety": (
            "batch finalize runner executes ordered gates only. MoviePilot scraping requires execute_scrape=true; "
            "qB/hlink cleanup requires approve_delete=true and a fresh ready cloud-hlink cleanup preview."
        ),
    }


def render_batch_finalize_run(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        "# Batch Finalize Run",
        "",
        f"- Mode: `{report.get('mode', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Halted: `{bool(report.get('halted'))}`",
        f"- Processed: `{report.get('processed_items', 0)}` / `{report.get('planned_items', 0)}`",
        f"- Status counts: `{report.get('status_counts', {})}`",
        "- Safety: cleanup runs only with explicit approval after all gates pass.",
        "",
        "| Status | TMDB | S | Episodes | Title | Last stage | Blockers |",
        "| --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        stages = item.get("stages") if isinstance(item.get("stages"), list) else []
        last_stage = ""
        if stages and isinstance(stages[-1], dict):
            last_stage = str(stages[-1].get("stage") or "")
        lines.append(
            "| {status} | {tmdbid} | {season} | {episodes} | {title} | {stage} | {blockers} |".format(
                status=item.get("status", ""),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                episodes=item.get("expected_episode_count") or "",
                title=_escape_cell(str(item.get("title") or "")),
                stage=_escape_cell(last_stage),
                blockers=_escape_cell(", ".join(_string_list(item.get("blockers")))),
            )
        )
    return "\n".join(lines)


def _finalize_run_candidates(finalize_plan: Dict[str, object], title_filters: Sequence[str]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    lowered_filters = [item.lower() for item in title_filters]
    for item in finalize_plan.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("status") != "planned_finalize":
            continue
        title = str(item.get("title") or "")
        if lowered_filters and not any(value in title.lower() for value in lowered_filters):
            continue
        rows.append(item)
    return rows


def _run_finalize_item(
    item: Dict[str, object],
    *,
    output_dir: Path,
    config: object,
    execute_scrape: bool,
    approve_cloud_duplicate_delete: bool,
    approve_emby_stale_delete: bool,
    approve_delete: bool,
    min_seed_days: int,
    cloud_media_storage: str,
    timeout: int,
    scrape_timeout: int,
    nfo_min_chinese_ratio: float,
    nfo_sample_limit: int,
    actions: BatchFinalizeActions,
) -> Dict[str, object]:
    title = str(item.get("title") or "")
    tmdbid = int(item.get("tmdbid") or 0)
    season = int(item.get("season") or 0)
    expected_count = int(item.get("expected_episode_count") or 0)
    expected_episodes = _int_list(item.get("expected_episodes"))
    expected_min = min(expected_episodes) if expected_episodes else 1
    expected_max = max(expected_episodes) if expected_episodes else expected_count
    hlink_root = str(item.get("hlink_root") or "").rstrip("/")
    strm_root = str(item.get("strm_root") or "").rstrip("/")
    service_root = str(item.get("service_strm_root") or strm_root).rstrip("/")
    planned_required_prefix = str(item.get("required_target_prefix") or "")
    forbidden_prefixes = _string_list(item.get("forbidden_target_prefixes"))
    planned_cloud_title_path = str(item.get("cloud_title_path") or "").rstrip("/")
    derived_required_prefix = _cloud_target_prefix_from_strm_root(strm_root)
    derived_cloud_title_path = _cloud_title_path_from_strm_root(strm_root)
    required_prefix = derived_required_prefix or planned_required_prefix
    cloud_title_path = derived_cloud_title_path or planned_cloud_title_path
    cloud_season_path = derived_required_prefix or str(item.get("cloud_media_path") or "").rstrip("/") or required_prefix
    if cloud_season_path and not _cloud_path_looks_like_season(cloud_season_path):
        cloud_season_path = f"{cloud_season_path}/Season {season}"
    report_prefix = str((item.get("command_context") or {}).get("report_prefix") if isinstance(item.get("command_context"), dict) else "") or _report_prefix(title, tmdbid, season)

    row: Dict[str, object] = {
        "status": "running",
        "title": title,
        "tmdbid": tmdbid,
        "season": season,
        "expected_episode_count": expected_count,
        "hlink_root": hlink_root,
        "strm_root": strm_root,
        "service_strm_root": service_root,
        "cloud_title_path": cloud_title_path,
        "cloud_season_path": cloud_season_path,
        "required_target_prefix": required_prefix,
        "planned_cloud_title_path": planned_cloud_title_path,
        "planned_required_target_prefix": planned_required_prefix,
        "stages": [],
        "blockers": [],
        "warnings": [],
    }

    if not _append_stage(
        row,
        _stage_report_path(output_dir, report_prefix, "01-strm-verify"),
        "strm_verify",
        actions.verify_strm(
            title=title,
            strm_roots=[strm_root],
            expected_episode_count=expected_count,
            expected_episode_min=expected_min,
            expected_episode_max=expected_max,
            required_target_prefix=required_prefix,
            forbidden_target_prefixes=forbidden_prefixes,
        ),
    ):
        row["status"] = "failed_strm_verify"
        return row

    if cloud_season_path and _config_value(config, "mv3_base_url") and _config_value(config, "mv3_token"):
        duplicate_preview = actions.cloud_duplicate_cleanup(
            _config_value(config, "mv3_base_url"),
            _config_value(config, "mv3_token"),
            season_path=cloud_season_path,
            strm_root=strm_root,
            expected_episode_count=expected_count,
            storage=cloud_media_storage,
            timeout=timeout,
            approve_delete=False,
            expected_delete_count=-1,
        )
        if not _append_stage(
            row,
            _stage_report_path(output_dir, report_prefix, "02-cloud-duplicate-preview"),
            "mv3_cloud_duplicate_video_cleanup_preview",
            duplicate_preview,
        ):
            row["status"] = "failed_cloud_duplicate_preview"
            return row
        duplicate_count = _duplicate_delete_count(duplicate_preview)
        row["cloud_duplicate_video_count"] = duplicate_count
        if duplicate_count > 0:
            if not approve_cloud_duplicate_delete:
                row["status"] = "cloud_duplicate_cleanup_waiting_for_approval"
                row["blockers"] = sorted(set(_string_list(row.get("blockers")) + ["cloud_duplicate_delete_approval_required"]))
                return row
            duplicate_execute = actions.cloud_duplicate_cleanup(
                _config_value(config, "mv3_base_url"),
                _config_value(config, "mv3_token"),
                season_path=cloud_season_path,
                strm_root=strm_root,
                expected_episode_count=expected_count,
                storage=cloud_media_storage,
                timeout=timeout,
                approve_delete=True,
                expected_delete_count=duplicate_count,
            )
            if not _append_stage(
                row,
                _stage_report_path(output_dir, report_prefix, "03-cloud-duplicate-execute"),
                "mv3_cloud_duplicate_video_cleanup_execute",
                duplicate_execute,
            ):
                row["status"] = "failed_cloud_duplicate_execute"
                return row
            duplicate_verify = actions.cloud_duplicate_cleanup(
                _config_value(config, "mv3_base_url"),
                _config_value(config, "mv3_token"),
                season_path=cloud_season_path,
                strm_root=strm_root,
                expected_episode_count=expected_count,
                storage=cloud_media_storage,
                timeout=timeout,
                approve_delete=False,
                expected_delete_count=-1,
            )
            if not _append_stage(
                row,
                _stage_report_path(output_dir, report_prefix, "04-cloud-duplicate-postcheck"),
                "mv3_cloud_duplicate_video_cleanup_postcheck",
                duplicate_verify,
            ):
                row["status"] = "failed_cloud_duplicate_postcheck"
                return row
            post_duplicate_count = _duplicate_delete_count(duplicate_verify)
            row["cloud_duplicate_video_count_after_cleanup"] = post_duplicate_count
            if post_duplicate_count > 0:
                row["status"] = "failed_cloud_duplicate_postcheck"
                row["blockers"] = sorted(set(_string_list(row.get("blockers")) + ["cloud_duplicate_videos_remain"]))
                return row
            if not _append_stage(
                row,
                _stage_report_path(output_dir, report_prefix, "05-strm-verify-after-cloud-duplicate-cleanup"),
                "strm_verify_after_cloud_duplicate_cleanup",
                actions.verify_strm(
                    title=title,
                    strm_roots=[strm_root],
                    expected_episode_count=expected_count,
                    expected_episode_min=expected_min,
                    expected_episode_max=expected_max,
                    required_target_prefix=required_prefix,
                    forbidden_target_prefixes=forbidden_prefixes,
                ),
            ):
                row["status"] = "failed_strm_verify_after_cloud_duplicate_cleanup"
                return row

    if execute_scrape:
        if not _config_value(config, "mp_base_url") or not _config_value(config, "mp_token"):
            return _finish_missing_credentials(row, "mp_credentials_required", "failed_mp_scrape")
        scrape_report = actions.scrape_mp_strm(
            _config_value(config, "mp_base_url"),
            _config_value(config, "mp_token"),
            strm_path=strm_root,
            mp_path=service_root,
            storage="local",
            item_type="dir",
            timeout=scrape_timeout,
        )
    else:
        scrape_report = {
            "mode": "mp-scrape-strm-result",
            "ok": True,
            "skipped": True,
            "reason": "execute_scrape_not_requested",
            "strm_path": strm_root,
            "mp_path": service_root,
            "safety": "MoviePilot scrape skipped because execute_scrape was not requested",
        }
    if not _append_stage(row, _stage_report_path(output_dir, report_prefix, "02-mp-scrape-strm"), "mp_scrape_strm", scrape_report):
        row["status"] = "failed_mp_scrape"
        return row

    if not _append_stage(
        row,
        _stage_report_path(output_dir, report_prefix, "03-nfo-language"),
        "strm_nfo_language_audit",
        actions.audit_nfo_language(
            strm_roots=[strm_root],
            min_chinese_ratio=nfo_min_chinese_ratio,
            sample_limit=nfo_sample_limit,
            expected_nfo_count=expected_count,
        ),
    ):
        row["status"] = "failed_nfo_language"
        return row

    if not _config_value(config, "emby_base_url") or not _config_value(config, "emby_key"):
        return _finish_missing_credentials(row, "emby_credentials_required", "failed_emby_media_updated")
    if not _append_stage(
        row,
        _stage_report_path(output_dir, report_prefix, "04-emby-media-updated"),
        "emby_media_updated_verify",
        actions.emby_media_updated(
            _config_value(config, "emby_base_url"),
            _config_value(config, "emby_key"),
            title=title,
            updated_paths=[service_root],
            stale_path_prefixes=[],
            strm_path_prefixes=[service_root],
            update_type="Created",
            expected_strm_records=0,
            expected_episode_count=expected_count,
            expected_episode_min=expected_min,
            expected_episode_max=expected_max,
            library_db_path=_config_value(config, "emby_library_db_path"),
            timeout=timeout,
        ),
    ):
        row["status"] = "failed_emby_media_updated"
        return row

    emby_stale_prefixes = _emby_stale_path_prefixes(hlink_root)
    if approve_emby_stale_delete and emby_stale_prefixes and _config_value(config, "emby_library_db_path"):
        for stale_prefix in emby_stale_prefixes:
            stale_delete = actions.emby_delete_stale(
                _config_value(config, "emby_base_url"),
                _config_value(config, "emby_key"),
                title=title,
                stale_path_prefixes=[stale_prefix],
                stale_host_prefix=stale_prefix,
                delete_scope="season" if _cloud_path_looks_like_season(stale_prefix) else "root",
                allow_season_duplicate_replacement=False,
                strm_filesystem_roots=[],
                required_target_prefix="",
                forbidden_target_prefixes=[],
                strm_path_prefixes=[_series_service_root(service_root)],
                expected_episode_count=expected_count,
                expected_episode_min=expected_min,
                expected_episode_max=expected_max,
                library_db_path=_config_value(config, "emby_library_db_path"),
                timeout=timeout,
            )
            if not _append_stage(
                row,
                _stage_report_path(output_dir, report_prefix, f"04-emby-delete-stale-{_safe_stage_suffix(stale_prefix)}"),
                "emby_delete_stale_paths",
                stale_delete,
            ):
                if _string_list(stale_delete.get("blockers")) == ["stale_root_item_not_found"]:
                    continue
                row["status"] = "failed_emby_delete_stale"
                return row
        if not _append_stage(
            row,
            _stage_report_path(output_dir, report_prefix, "04-emby-media-updated-after-stale-delete"),
            "emby_media_updated_verify_after_stale_delete",
            actions.emby_media_updated(
                _config_value(config, "emby_base_url"),
                _config_value(config, "emby_key"),
                title=title,
                updated_paths=[service_root],
                stale_path_prefixes=_emby_stale_path_prefixes(hlink_root, include_season=False),
                strm_path_prefixes=[_series_service_root(service_root)],
                update_type="Created",
                expected_strm_records=0,
                expected_episode_count=expected_count,
                expected_episode_min=expected_min,
                expected_episode_max=expected_max,
                library_db_path=_config_value(config, "emby_library_db_path"),
                timeout=timeout,
            ),
        ):
            row["status"] = "failed_emby_media_updated_after_stale_delete"
            return row

    if not _config_value(config, "qb_base_url"):
        return _finish_missing_credentials(row, "qb_credentials_required", "failed_cleanup_preview")
    cleanup_preview = actions.cleanup_preview(
        title=title.split(" (", 1)[0].strip() or title,
        hlink_root=hlink_root,
        strm_root=strm_root,
        expected_tmdbid=tmdbid,
        expected_episode_count=expected_count,
        expected_episode_min=expected_min,
        expected_episode_max=expected_max,
        qb_base_url=_config_value(config, "qb_base_url"),
        qb_user=_config_value(config, "qb_user"),
        qb_pass=_config_value(config, "qb_pass"),
        path_aliases=getattr(config, "path_aliases", {}) or {},
        min_seed_days=min_seed_days,
        required_target_prefix=required_prefix,
        forbidden_target_prefixes=forbidden_prefixes,
        mv3_base_url=_config_value(config, "mv3_base_url"),
        mv3_token=_config_value(config, "mv3_token"),
        cloud_media_path=cloud_title_path,
        cloud_media_storage=cloud_media_storage,
    )
    if not _append_stage(
        row,
        _stage_report_path(output_dir, report_prefix, "05-cloud-hlink-cleanup-preview"),
        "cloud_hlink_cleanup_preview",
        cleanup_preview,
        ok_key="ready_for_execute",
    ):
        row["status"] = "failed_cleanup_preview"
        return row

    if not approve_delete:
        row["status"] = "cleanup_waiting_for_approval"
        return row

    execute_report = actions.cleanup_execute(
        cleanup_preview,
        _config_value(config, "qb_base_url"),
        _config_value(config, "qb_user"),
        _config_value(config, "qb_pass"),
        path_aliases=getattr(config, "path_aliases", {}) or {},
        mv3_base_url=_config_value(config, "mv3_base_url"),
        mv3_token=_config_value(config, "mv3_token"),
        timeout=timeout,
    )
    if not _append_stage(
        row,
        _stage_report_path(output_dir, report_prefix, "06-cloud-hlink-cleanup-execute"),
        "cloud_hlink_cleanup_execute",
        execute_report,
    ):
        row["status"] = "failed_cleanup_execute"
        return row
    parent_hlink_root = str(PurePosixPath(hlink_root).parent) if hlink_root else ""
    if parent_hlink_root and parent_hlink_root != hlink_root:
        if not _append_stage(
            row,
            _stage_report_path(output_dir, report_prefix, "07-hlink-empty-root-cleanup"),
            "hlink_empty_root_cleanup",
            actions.empty_hlink_root_cleanup(
                title=title,
                hlink_root=parent_hlink_root,
                expected_tmdbid=tmdbid,
                approve_delete=True,
            ),
        ):
            row["status"] = "failed_empty_hlink_root_cleanup"
            return row
    row["status"] = "cleanup_executed"
    return row


def _append_stage(
    row: Dict[str, object],
    output_path: Path,
    stage: str,
    report: Dict[str, object],
    *,
    ok_key: str = "ok",
) -> bool:
    _write_json(output_path, report)
    ok = bool(report.get(ok_key))
    blockers = _string_list(report.get("blockers"))
    warnings = _string_list(report.get("warnings"))
    if stage == "cloud_hlink_cleanup_preview":
        _append_cleanup_preview_diagnostics(row, report)
    row.setdefault("stages", []).append(
        {
            "stage": stage,
            "ok": ok,
            "output": str(output_path),
            "mode": report.get("mode", ""),
            "blockers": blockers,
            "warnings": warnings,
        }
    )
    row["blockers"] = sorted(set(_string_list(row.get("blockers")) + blockers))
    row["warnings"] = sorted(set(_string_list(row.get("warnings")) + warnings))
    return ok


def _append_cleanup_preview_diagnostics(row: Dict[str, object], report: Dict[str, object]) -> None:
    filesystem = report.get("filesystem") if isinstance(report.get("filesystem"), dict) else {}
    source_roots = filesystem.get("source_roots") if isinstance(filesystem.get("source_roots"), list) else []
    samples: List[str] = []
    blocked_roots: List[Dict[str, object]] = []
    for source_root in source_roots:
        if not isinstance(source_root, dict):
            continue
        sample = _string_list(source_root.get("unlinked_video_sample"))
        if sample:
            samples.extend(sample)
        if bool(source_root.get("blocked")):
            blocked_roots.append(
                {
                    "path": str(source_root.get("path") or ""),
                    "video_count": int(source_root.get("video_count") or 0),
                    "linked_hlink_video_count": int(source_root.get("linked_hlink_video_count") or 0),
                    "unlinked_video_sample": sample,
                }
            )
    if samples:
        row["cleanup_unlinked_video_sample"] = sorted(set(samples))
    if blocked_roots:
        row["cleanup_blocked_source_roots"] = blocked_roots


def _finish_missing_credentials(row: Dict[str, object], blocker: str, status: str) -> Dict[str, object]:
    row["status"] = status
    row["blockers"] = sorted(set(_string_list(row.get("blockers")) + [blocker]))
    row.setdefault("stages", []).append({"stage": "configuration", "ok": False, "blockers": [blocker]})
    return row


def _duplicate_delete_count(report: Dict[str, object]) -> int:
    delete_plan = report.get("delete_plan") if isinstance(report.get("delete_plan"), dict) else {}
    return int(delete_plan.get("duplicate_video_count") or 0)


def _cloud_path_looks_like_season(path: str) -> bool:
    return bool(re.search(r"(?i)/(?:Season\s*0?\d+|第\s*\d+\s*季)$", str(path or "").rstrip("/")))


def _series_service_root(service_root: str) -> str:
    path = str(service_root or "").rstrip("/")
    if _cloud_path_looks_like_season(path):
        return path.rsplit("/", 1)[0]
    return path


def _emby_stale_path_prefixes(hlink_root: str, *, include_season: bool = True) -> List[str]:
    service_root = _service_hlink_root(hlink_root)
    if not service_root:
        return []
    if _cloud_path_looks_like_season(service_root):
        series_root = service_root.rsplit("/", 1)[0]
        return [service_root, series_root] if include_season else [series_root]
    return [f"{service_root}/Season 1", service_root] if include_season else [service_root]


def _service_hlink_root(hlink_root: str) -> str:
    path = str(hlink_root or "").rstrip("/")
    path = re.sub(r"^/volume(\d+)/volume\1/", r"/volume\1/", path)
    return path


def _safe_stage_suffix(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z一-龥]+", "-", value).strip("-")
    return slug[-80:] or "stale"


def _stage_report_path(output_dir: Path, report_prefix: str, stage_name: str) -> Path:
    return output_dir / f"{report_prefix}-{stage_name}.json"


def _write_json(path: Path, report: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _config_value(config: object, name: str) -> str:
    return str(getattr(config, name, "") or "")


def _batch_item(
    cloud_item: Dict[str, object],
    transfer_item: Dict[str, object],
    share_item: Dict[str, object],
    cleanup_preview: Dict[str, object],
    scan_candidates: List[Dict[str, object]],
    *,
    env_file: str,
    cloud_root: str,
    mv3_strm_root: str,
    host_strm_root: str,
    emby_strm_root: str,
    min_candidate_score: int,
    max_auto_size_delta: float,
    required_target_prefix: str,
    forbidden_target_prefixes: Sequence[str],
) -> Dict[str, object]:
    title = str(cloud_item.get("title") or transfer_item.get("title") or "")
    tmdbid = int(cloud_item.get("tmdbid") or transfer_item.get("tmdbid") or 0)
    season = int(cloud_item.get("season") or transfer_item.get("season") or 0)
    expected_count = int(cloud_item.get("expected_count") or transfer_item.get("expected_count") or 0)
    size_bytes = int(cloud_item.get("size_bytes") or transfer_item.get("size_bytes") or 0)
    source_paths = _string_list(transfer_item.get("source_paths")) or _string_list(cloud_item.get("source_paths"))
    status = str(cloud_item.get("status") or transfer_item.get("source_status") or "")
    recommended = share_item.get("recommended_candidate") if isinstance(share_item.get("recommended_candidate"), dict) else {}
    share_candidates = share_item.get("candidates") if isinstance(share_item.get("candidates"), list) else []
    candidate_diagnostics = _candidate_diagnostics(share_item, recommended, share_candidates, season, title)
    strm_root = _strm_root_from_cloud_item(cloud_item, host_strm_root)
    cloud_media_path = _cloud_media_path(cloud_root, title, tmdbid, season)

    blockers: List[str] = []
    review_reasons: List[str] = []
    bucket = MANUAL_REVIEW
    next_actions: List[Dict[str, object]] = []

    if status == "cloud_strm_complete":
        if not strm_root:
            review_reasons.append("cloud_complete_but_strm_root_unknown")
        elif cleanup_preview and not _cleanup_preview_ready(cleanup_preview):
            review_reasons.append("cleanup_preview_not_ready")
            blockers.extend(_string_list(cleanup_preview.get("blockers")))
            blockers.extend(_string_list(cleanup_preview.get("execution_blockers")))
        else:
            bucket = AUTO_CLEANUP
            next_actions = _cleanup_validation_commands(
                title=title,
                tmdbid=tmdbid,
                season=season,
                expected_count=expected_count,
                strm_root=strm_root,
                emby_strm_root=_map_strm_root(strm_root, host_strm_root, emby_strm_root),
                source_paths=source_paths,
                env_file=env_file,
                required_target_prefix=required_target_prefix,
                forbidden_target_prefixes=forbidden_target_prefixes,
            )
    elif status == "cloud_strm_not_found":
        candidate_score = int(recommended.get("score") or 0)
        candidate_blockers = _string_list(recommended.get("blockers"))
        size_delta = recommended.get("size_delta_ratio")
        if not transfer_item:
            review_reasons.append("missing_transfer_plan_row")
        if not recommended:
            review_reasons.append("no_recommended_mv3_share_candidate")
        if recommended and candidate_score < min_candidate_score:
            review_reasons.append("recommended_candidate_score_below_minimum")
        if recommended and candidate_blockers:
            review_reasons.extend(candidate_blockers)
        if recommended and _candidate_has_explicit_wrong_season(recommended, season):
            review_reasons.append("season_mismatch")
        if recommended:
            review_reasons.extend(_candidate_identity_blockers(title, recommended))
        if recommended and size_delta is None:
            review_reasons.append("remote_size_unknown")
        if isinstance(size_delta, (int, float)) and float(size_delta) > max_auto_size_delta:
            review_reasons.append("remote_size_not_similar_enough")
        if tmdbid <= 0 or season <= 0:
            review_reasons.append("missing_identity")
        if expected_count <= 0:
            review_reasons.append("missing_expected_episode_count")
        if not source_paths:
            review_reasons.append("missing_source_paths")
        if not review_reasons:
            bucket = AUTO_TRANSFER
            next_actions = _transfer_preview_commands(
                title=title,
                tmdbid=tmdbid,
                season=season,
                expected_count=expected_count,
                recommended=recommended,
                source_paths=source_paths,
                env_file=env_file,
                cloud_root=cloud_root,
                mv3_strm_root=mv3_strm_root,
                host_strm_root=host_strm_root,
                required_target_prefix=required_target_prefix,
                forbidden_target_prefixes=forbidden_target_prefixes,
            )
    elif status == "needs_identity_review":
        review_reasons.append("identity_or_season_requires_review")
    else:
        bucket = SKIPPED
        blockers.append(f"unsupported_cloud_status:{status or 'unknown'}")

    if bucket == MANUAL_REVIEW and not review_reasons:
        review_reasons.append("manual_review_required")

    return {
        "bucket": bucket,
        "state": _state_for_bucket(bucket),
        "title": title,
        "tmdbid": tmdbid,
        "season": season,
        "cloud_status": status,
        "size_bytes": size_bytes,
        "size": human_size(size_bytes),
        "expected_episode_count": expected_count,
        "expected_episodes": _int_list(cloud_item.get("expected_episodes")),
        "source_paths": source_paths,
        "source_titles": _string_list(transfer_item.get("titles")) or _string_list(cloud_item.get("titles")),
        "scan_candidate_count": len(scan_candidates),
        "recommended_candidate": recommended,
        "candidate_count": len(share_candidates),
        "candidate_diagnostics": candidate_diagnostics,
        "merged_duplicate_count": int(share_item.get("merged_duplicate_count") or 0),
        "cleanup_preview_ready": _cleanup_preview_ready(cleanup_preview) if cleanup_preview else None,
        "cleanup_preview_blockers": _string_list(cleanup_preview.get("blockers")) + _string_list(cleanup_preview.get("execution_blockers")) if cleanup_preview else [],
        "strm_root": strm_root,
        "cloud_media_path": cloud_media_path,
        "review_reasons": sorted(set(review_reasons)),
        "blockers": sorted(set(blockers)),
        "next_actions": next_actions,
    }


def _transfer_preview_commands(
    *,
    title: str,
    tmdbid: int,
    season: int,
    expected_count: int,
    recommended: Dict[str, object],
    source_paths: List[str],
    env_file: str,
    cloud_root: str,
    mv3_strm_root: str,
    host_strm_root: str,
    required_target_prefix: str,
    forbidden_target_prefixes: Sequence[str],
) -> List[Dict[str, object]]:
    keyword = str(recommended.get("search_keyword") or title)
    selection = int(recommended.get("search_index") or 1)
    env = _env_arg(env_file)
    title_contains = title.split(" (", 1)[0].strip() or title
    cloud_media_path = _cloud_media_path(cloud_root, title, tmdbid, season)
    verify_strm_root = host_strm_root or mv3_strm_root
    host_strm_path = _host_strm_path_from_cloud(cloud_media_path, verify_strm_root)
    forbidden_args = " ".join(f'--forbidden-target-prefix "{value}"' for value in forbidden_target_prefixes)
    return [
        {
            "stage": "share_preview",
            "command": (
                f'PYTHONPATH=src python3 -m series_cloud_archiver mv3-share-preview {env}'
                f'--keyword "{keyword}" --selection-index {selection} '
                f"--expected-episode-count {expected_count} --expected-episode-min 1 --expected-episode-max {expected_count} "
                f'--expected-title-contains "{title_contains}" --format json --output <preview-report.json>'
            ),
        },
        {
            "stage": "share_receive_dry_run_only",
            "command": (
                f'PYTHONPATH=src python3 -m series_cloud_archiver mv3-share-receive-one {env}'
                f'--keyword "{keyword}" --selection-index {selection} --receive-selected-folder '
                f"--verified-folder-browse-report <preview-report.json> "
                f"--expected-episode-count {expected_count} --expected-episode-min 1 --expected-episode-max {expected_count} "
                f'--expected-title-contains "{title_contains}" --target-path "/未整理" '
                f"--format json --output <receive-report.json>"
            ),
        },
        {
            "stage": "organize_generate_strm_dry_run_gate",
            "command": (
                f'PYTHONPATH=src python3 -m series_cloud_archiver mv3-organize-transfer-from-browse {env}'
                f"--browse-report <cloud-browse-report.json> --target-dir /已整理 --strm-dir {mv3_strm_root} "
                f"--tmdb-id {tmdbid} --expected-episode-count {expected_count} "
                f"--expected-episode-min 1 --expected-episode-max {expected_count} "
                f"--format json --output <organize-report.json>"
            ),
        },
        {
            "stage": "strm_verify",
            "command": (
                f'PYTHONPATH=src python3 -m series_cloud_archiver strm-verify --title "{title}" '
                f'--strm-root "{host_strm_path}" --expected-episode-count {expected_count} '
                f"--expected-episode-min 1 --expected-episode-max {expected_count} "
                f'--required-target-prefix "{required_target_prefix}" {forbidden_args} '
                f"--format json --output <strm-verify.json>"
            ),
        },
        {
            "stage": "cleanup_preview_after_all_green",
            "command": (
                f'PYTHONPATH=src python3 -m series_cloud_archiver mp-cleanup-preview {env}'
                f'--title "{title_contains}" --expected-tmdbid {tmdbid} --expected-season {season} '
                f"--format json --output <mp-cleanup-preview.json>"
            ),
            "source_paths": source_paths,
        },
    ]


def _cleanup_validation_commands(
    *,
    title: str,
    tmdbid: int,
    season: int,
    expected_count: int,
    strm_root: str,
    emby_strm_root: str,
    source_paths: List[str],
    env_file: str,
    required_target_prefix: str,
    forbidden_target_prefixes: Sequence[str],
) -> List[Dict[str, object]]:
    env = _env_arg(env_file)
    forbidden_args = " ".join(f'--forbidden-target-prefix "{value}"' for value in forbidden_target_prefixes)
    title_contains = title.split(" (", 1)[0].strip() or title
    emby_root = emby_strm_root or strm_root
    return [
        {
            "stage": "strm_verify",
            "command": (
                f'PYTHONPATH=src python3 -m series_cloud_archiver strm-verify --title "{title}" '
                f'--strm-root "{strm_root}" --expected-episode-count {expected_count} '
                f"--expected-episode-min 1 --expected-episode-max {expected_count} "
                f'--required-target-prefix "{required_target_prefix}" {forbidden_args} '
                f"--format json --output <strm-verify.json>"
            ),
        },
        {
            "stage": "strm_nfo_language_audit",
            "command": (
                f'PYTHONPATH=src python3 -m series_cloud_archiver strm-nfo-language-audit '
                f'--strm-root "{strm_root}" --expected-nfo-count {expected_count} '
                f'--format json --output <nfo-language-audit.json>'
            ),
        },
        {
            "stage": "emby_local_update_verify",
            "command": (
                f'PYTHONPATH=src python3 -m series_cloud_archiver emby-media-updated {env}'
                f'--title "{title}" --updated-path "{emby_root}" --strm-path-prefix "{emby_root}" '
                f"--expected-strm-records {expected_count + 1} "
                f"--expected-episode-count {expected_count} --expected-episode-min 1 --expected-episode-max {expected_count} "
                f"--format json --output <emby-verify.json>"
            ),
        },
        {
            "stage": "cleanup_preview_after_all_green",
            "command": (
                f'PYTHONPATH=src python3 -m series_cloud_archiver mp-cleanup-preview {env}'
                f'--title "{title_contains}" --expected-tmdbid {tmdbid} --expected-season {season} '
                f"--format json --output <mp-cleanup-preview.json>"
            ),
            "source_paths": source_paths,
        },
    ]


def _finalize_plan_row(
    index: int,
    item: Dict[str, object],
    *,
    env_file: str,
    cloud_root: str,
    host_strm_root: str,
    service_strm_root: str,
    required_target_prefix: str,
    forbidden_target_prefixes: Sequence[str],
) -> Dict[str, object]:
    title = str(item.get("title") or "")
    tmdbid = int(item.get("tmdbid") or 0)
    season = int(item.get("season") or 0)
    expected_count = int(item.get("expected_episode_count") or item.get("expected_count") or 0)
    expected_episodes = _int_list(item.get("expected_episodes"))
    hlink_root = _first_hlink_path(_string_list(item.get("source_paths")))
    cloud_season_path = str(item.get("cloud_media_path") or "")
    planned_cloud_title_path = _cloud_title_path_from_item(item, cloud_root)
    strm_root = str(item.get("strm_root") or "") or _host_strm_path_from_cloud_title(planned_cloud_title_path, host_strm_root)
    derived_cloud_season_path = _cloud_target_prefix_from_strm_root(strm_root)
    cloud_title_path = _cloud_title_path_from_strm_root(strm_root) or planned_cloud_title_path
    cloud_required_prefix = required_target_prefix or derived_cloud_season_path or cloud_season_path or cloud_title_path
    service_root = _map_strm_root(strm_root, host_strm_root, service_strm_root)

    blockers: List[str] = []
    skip_reasons: List[str] = []
    if not title:
        blockers.append("title_required")
    if tmdbid <= 0:
        blockers.append("tmdb_id_required")
    if season <= 0:
        blockers.append("season_required")
    if expected_count <= 0:
        blockers.append("expected_episode_count_required")
    if not hlink_root:
        blockers.append("hlink_root_required")
    if not strm_root:
        blockers.append("strm_root_required")
    if not service_root:
        blockers.append("service_strm_root_required")
    if not cloud_title_path:
        blockers.append("cloud_title_path_required")
    bucket = str(item.get("bucket") or "")
    if bucket != AUTO_CLEANUP:
        skip_reasons.append(f"not_ready_for_finalize:{bucket or 'unknown'}")
    if bucket not in {AUTO_CLEANUP, MANUAL_REVIEW, AUTO_TRANSFER}:
        skip_reasons.append("unsupported_batch_bucket")

    status = "planned_finalize" if not blockers and not skip_reasons else "skipped_finalize"
    command_context = {
        "report_prefix": _report_prefix(title, tmdbid, season),
        "env_file": env_file,
        "title_contains": title.split(" (", 1)[0].strip() or title,
    }
    commands = (
        _finalize_commands(
            title=title,
            tmdbid=tmdbid,
            season=season,
            expected_count=expected_count,
            expected_episodes=expected_episodes,
            hlink_root=hlink_root,
            strm_root=strm_root,
            service_root=service_root,
            cloud_title_path=cloud_title_path,
            cloud_required_prefix=cloud_required_prefix,
            forbidden_target_prefixes=forbidden_target_prefixes,
            env_file=env_file,
            report_prefix=str(command_context["report_prefix"]),
        )
        if status == "planned_finalize"
        else []
    )

    return {
        "source_index": index,
        "status": status,
        "title": title,
        "tmdbid": tmdbid,
        "season": season,
        "expected_episode_count": expected_count,
        "expected_episodes": expected_episodes,
        "hlink_root": hlink_root,
        "strm_root": strm_root,
        "service_strm_root": service_root,
        "cloud_title_path": cloud_title_path,
        "cloud_media_path": cloud_season_path,
        "required_target_prefix": cloud_required_prefix,
        "forbidden_target_prefixes": list(forbidden_target_prefixes),
        "commands": commands,
        "command_context": command_context,
        "skip_reasons": sorted(set(skip_reasons)),
        "blockers": sorted(set(blockers)),
        "approval_required_after_gates": "--approve-delete",
        "safety": "plan row only; commands must be run in order, and cleanup execute still requires an explicit approval flag not included here",
    }


def _finalize_commands(
    *,
    title: str,
    tmdbid: int,
    season: int,
    expected_count: int,
    expected_episodes: Sequence[int],
    hlink_root: str,
    strm_root: str,
    service_root: str,
    cloud_title_path: str,
    cloud_required_prefix: str,
    forbidden_target_prefixes: Sequence[str],
    env_file: str,
    report_prefix: str,
) -> List[Dict[str, object]]:
    env = _env_arg_q(env_file)
    title_q = _q(title)
    title_contains_q = _q(title.split(" (", 1)[0].strip() or title)
    strm_q = _q(strm_root)
    service_q = _q(service_root)
    hlink_q = _q(hlink_root)
    cloud_title_q = _q(cloud_title_path)
    required_q = _q(cloud_required_prefix)
    forbidden_args = " ".join(f"--forbidden-target-prefix {_q(value)}" for value in forbidden_target_prefixes)
    preview_report = f"{report_prefix}-cleanup-preview.json"
    expected_hash_placeholder = "<full-qb-hash-from-cleanup-preview>"
    return [
        {
            "stage": "strm_verify",
            "output": f"{report_prefix}-strm-verify.json",
            "command": (
                f"PYTHONPATH=src python3 -m series_cloud_archiver strm-verify --title {title_q} "
                f"--strm-root {strm_q} --expected-episode-count {expected_count} "
                f"--expected-episode-min 1 --expected-episode-max {expected_count} "
                f"--required-target-prefix {required_q} {forbidden_args} "
                f"--format json --output {report_prefix}-strm-verify.json"
            ),
        },
        {
            "stage": "mp_scrape_strm",
            "output": f"{report_prefix}-mp-scrape.json",
            "command": (
                f"PYTHONPATH=src python3 -m series_cloud_archiver mp-scrape-strm {env}"
                f"--strm-path {strm_q} --mp-path {service_q} --storage local --type dir "
                f"--approve-scrape --format json --output {report_prefix}-mp-scrape.json"
            ),
        },
        {
            "stage": "strm_nfo_language_audit",
            "output": f"{report_prefix}-nfo-language.json",
            "command": (
                f"PYTHONPATH=src python3 -m series_cloud_archiver strm-nfo-language-audit "
                f"--strm-root {strm_q} --expected-nfo-count {expected_count} "
                f"--format json --output {report_prefix}-nfo-language.json"
            ),
        },
        {
            "stage": "emby_media_updated_verify",
            "output": f"{report_prefix}-emby-media-updated.json",
            "command": (
                f"PYTHONPATH=src python3 -m series_cloud_archiver emby-media-updated {env}"
                f"--title {title_q} --updated-path {service_q} --update-type Created "
                f"--strm-path-prefix {service_q} --expected-episode-count {expected_count} "
                f"--expected-episode-min 1 --expected-episode-max {expected_count} "
                f"--format json --output {report_prefix}-emby-media-updated.json"
            ),
        },
        {
            "stage": "cloud_hlink_cleanup_preview",
            "output": preview_report,
            "command": (
                f"PYTHONPATH=src python3 -m series_cloud_archiver cloud-hlink-cleanup-preview {env}"
                f"--title {title_contains_q} --expected-tmdbid {tmdbid} --hlink-root {hlink_q} "
                f"--strm-root {strm_q} --expected-episode-count {expected_count} "
                f"--expected-episode-min 1 --expected-episode-max {expected_count} "
                f"--required-target-prefix {required_q} {forbidden_args} "
                f"--cloud-media-path {cloud_title_q} --cloud-media-storage 115-default "
                f"--format json --output {preview_report}"
            ),
        },
        {
            "stage": "cloud_hlink_cleanup_execute_approval_required",
            "requires": [preview_report, "cleanup preview ready_for_execute=true", "human approval"],
            "approval_flag_required": "--approve-delete",
            "command": (
                f"PYTHONPATH=src python3 -m series_cloud_archiver cloud-hlink-cleanup-execute {env}"
                f"--preview-report {preview_report} --expected-title {title_contains_q} "
                f"--expected-tmdbid {tmdbid} --expected-hlink-root {hlink_q} "
                f"--expected-qb-hash {expected_hash_placeholder} "
                f"--format json --output {report_prefix}-cleanup-execute.json "
                "# approval required before execution"
            ),
        },
    ]


def _items_by_identity(raw_items: object) -> Dict[Tuple[int, int], Dict[str, object]]:
    result: Dict[Tuple[int, int], Dict[str, object]] = {}
    if not isinstance(raw_items, list):
        return result
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        key = _identity_key(item)
        if key != (0, 0):
            result[key] = item
    return result


def _cleanup_previews_by_identity(raw_items: Sequence[Dict[str, object]]) -> Dict[Tuple[int, int], Dict[str, object]]:
    result: Dict[Tuple[int, int], Dict[str, object]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        tmdbid = int(item.get("expected_tmdbid") or item.get("tmdbid") or 0)
        season = int(item.get("expected_season") or item.get("season") or 0)
        key = (tmdbid, season)
        if key == (0, 0):
            continue
        existing = result.get(key)
        if existing is None or _cleanup_preview_rank(item) > _cleanup_preview_rank(existing):
            result[key] = item
    return result


def _cleanup_preview_rank(item: Dict[str, object]) -> Tuple[int, int]:
    return (
        1 if _cleanup_preview_ready(item) else 0,
        int((item.get("summary") or {}).get("records_matched") or 0) if isinstance(item.get("summary"), dict) else 0,
    )


def _cleanup_preview_ready(item: Dict[str, object]) -> bool:
    if not item:
        return False
    if item.get("ready_for_execute") is not None:
        return bool(item.get("ready_for_execute"))
    return bool(item.get("ready_for_manual_cleanup_approval") or item.get("ok"))


def _candidate_has_explicit_wrong_season(candidate: Dict[str, object], expected_season: int) -> bool:
    if expected_season <= 0:
        return False
    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("title", "name")
        if str(candidate.get(key) or "")
    )
    seasons = _explicit_seasons_from_text(text)
    return bool(seasons and expected_season not in seasons)


def _candidate_identity_blockers(expected_title: str, candidate: Dict[str, object]) -> List[str]:
    remote_title = str(candidate.get("title") or candidate.get("name") or "")
    if _candidate_has_chinese_subtitle_drift(expected_title, remote_title):
        return ["possible_chinese_subtitle_mismatch"]
    return []


def _candidate_has_chinese_subtitle_drift(expected_title: str, remote_title: str) -> bool:
    expected = _first_chinese_run(_strip_identity_suffix(expected_title))
    if len(expected) < 2:
        return False
    remote = re.sub(r"\s+", "", remote_title or "")
    index = remote.find(expected)
    if index < 0:
        return False
    suffix = _candidate_title_suffix(remote[index + len(expected) :])
    if not suffix or _candidate_suffix_is_metadata(suffix):
        return False
    return bool(re.match(r"(?:\d{1,4}[\s:：\-—_]*[\u4e00-\u9fff]|[\u4e00-\u9fff]{1,12})", suffix))


def _candidate_title_suffix(value: str) -> str:
    text = re.sub(r"^[\s:：,，\-—_【】\[\]（）()]+", "", value or "")
    text = re.sub(r"^(?:19|20)\d{2}[)）]?", "", text)
    return re.sub(r"^[\s:：,，\-—_【】\[\]（）()]+", "", text)


def _candidate_suffix_is_metadata(value: str) -> bool:
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


def _candidate_diagnostics(
    share_item: Dict[str, object],
    recommended: Dict[str, object],
    candidates: List[object],
    expected_season: int,
    expected_title: str,
) -> Dict[str, object]:
    candidate_rows = [candidate for candidate in candidates if isinstance(candidate, dict)]
    best = _best_candidate_for_diagnostics(recommended, candidate_rows)
    blocker_counts: Counter = Counter()
    reason_counts: Counter = Counter()
    for candidate in candidate_rows:
        blocker_counts.update(_candidate_diagnostic_blockers(candidate, expected_season, expected_title))
        reason_counts.update(_string_list(candidate.get("reasons")))

    return {
        "search_ok": bool(share_item.get("search_ok")) if share_item else False,
        "search_result_count": int(share_item.get("search_result_count") or 0) if share_item else 0,
        "search_warnings": _string_list(share_item.get("warnings")) if share_item else [],
        "recommended_candidate_present": bool(recommended),
        "best_candidate": _candidate_diagnostic_summary(best, expected_season, expected_title) if best else {},
        "candidate_score_max": int(best.get("score") or 0) if best else 0,
        "candidate_blocker_counts": dict(sorted(blocker_counts.items())),
        "candidate_reason_counts": dict(sorted(reason_counts.items())),
        "top_candidates": [_candidate_diagnostic_summary(candidate, expected_season, expected_title) for candidate in candidate_rows[:3]],
    }


def _best_candidate_for_diagnostics(recommended: Dict[str, object], candidates: List[Dict[str, object]]) -> Dict[str, object]:
    if recommended:
        return recommended
    if not candidates:
        return {}
    return sorted(candidates, key=_candidate_diagnostic_rank, reverse=True)[0]


def _candidate_diagnostic_rank(candidate: Dict[str, object]) -> Tuple[int, int, float, int]:
    blockers = _string_list(candidate.get("blockers"))
    size_delta = candidate.get("size_delta_ratio")
    size_fit = 1.0 - float(size_delta) if isinstance(size_delta, (int, float)) else -1.0
    return (
        int(candidate.get("score") or 0),
        -len(blockers),
        size_fit,
        -int(candidate.get("search_index") or 0),
    )


def _candidate_diagnostic_summary(candidate: Dict[str, object], expected_season: int, expected_title: str) -> Dict[str, object]:
    blockers = _candidate_diagnostic_blockers(candidate, expected_season, expected_title)
    return {
        "search_index": int(candidate.get("search_index") or 0),
        "search_keyword": str(candidate.get("search_keyword") or ""),
        "title": str(candidate.get("title") or ""),
        "score": int(candidate.get("score") or 0),
        "size": str(candidate.get("size") or ""),
        "size_bytes": int(candidate.get("size_bytes") or 0),
        "size_delta_ratio": candidate.get("size_delta_ratio"),
        "reasons": _string_list(candidate.get("reasons")),
        "blockers": blockers,
    }


def _candidate_diagnostic_blockers(candidate: Dict[str, object], expected_season: int, expected_title: str) -> List[str]:
    blockers = _string_list(candidate.get("blockers"))
    if _candidate_has_explicit_wrong_season(candidate, expected_season) and "season_mismatch" not in blockers:
        blockers.append("season_mismatch")
    for blocker in _candidate_identity_blockers(expected_title, candidate):
        if blocker not in blockers:
            blockers.append(blocker)
    return blockers


def _explicit_seasons_from_text(text: str) -> List[int]:
    seasons = set()
    for pattern in (
        r"(?i)\bS0?(\d{1,2})(?=E|\b)",
        r"(?i)\bSeason\s*0?(\d{1,2})\b",
        r"第\s*0?(\d{1,2})\s*季",
    ):
        for value in re.findall(pattern, text or ""):
            season = int(value)
            if 0 < season <= 99:
                seasons.add(season)
    return sorted(seasons)


def _share_plan_item_rank(item: Dict[str, object]) -> Tuple[int, int, int, float]:
    candidate = item.get("recommended_candidate") if isinstance(item.get("recommended_candidate"), dict) else {}
    blockers = _string_list(candidate.get("blockers")) if candidate else []
    size_delta = candidate.get("size_delta_ratio") if candidate else None
    size_fit = 1.0 - float(size_delta) if isinstance(size_delta, (int, float)) else -1.0
    return (
        1 if candidate else 0,
        1 if candidate and not blockers else 0,
        int(candidate.get("score") or 0) if candidate else 0,
        size_fit,
    )


def _scan_candidates_by_identity(raw_items: object) -> Dict[Tuple[int, int], List[Dict[str, object]]]:
    result: Dict[Tuple[int, int], List[Dict[str, object]]] = {}
    if not isinstance(raw_items, list):
        return result
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        tmdbid, season = _scan_identity(item)
        if tmdbid and season:
            result.setdefault((tmdbid, season), []).append(item)
    return result


def _scan_identity(item: Dict[str, object]) -> Tuple[int, int]:
    for source_key in ("manual_completion", "mp"):
        source = item.get(source_key)
        if isinstance(source, dict):
            tmdbid = int(source.get("tmdbid") or 0)
            season = int(source.get("season") or 0)
            if tmdbid and season:
                return tmdbid, season
    tmdbid = _tmdbid_from_text(str(item.get("title") or "") + " " + str(item.get("path") or ""))
    seasons = item.get("seasons")
    season = int(seasons[0]) if isinstance(seasons, list) and len(seasons) == 1 and str(seasons[0]).isdigit() else 0
    return tmdbid, season


def _identity_key(item: Dict[str, object]) -> Tuple[int, int]:
    return int(item.get("tmdbid") or 0), int(item.get("season") or 0)


def _state_for_bucket(bucket: str) -> str:
    return {
        AUTO_TRANSFER: "planned_share_preview_then_transfer",
        AUTO_CLEANUP: "planned_validation_then_cleanup",
        MANUAL_REVIEW: "held_for_manual_review",
        SKIPPED: "skipped",
    }.get(bucket, "unknown")


def _batch_sort_key(row: Dict[str, object]) -> Tuple[int, int, str]:
    rank = {AUTO_CLEANUP: 0, AUTO_TRANSFER: 1, MANUAL_REVIEW: 2, SKIPPED: 3}.get(str(row.get("bucket") or ""), 9)
    return rank, -int(row.get("size_bytes") or 0), str(row.get("title") or "")


def _batch_warnings(
    cloud_report: Dict[str, object],
    transfer_plan: Optional[Dict[str, object]],
    share_search_plan: Optional[Dict[str, object]],
) -> List[str]:
    warnings: List[str] = []
    for report in (cloud_report, transfer_plan or {}, share_search_plan or {}):
        raw = report.get("warnings") if isinstance(report, dict) else []
        if isinstance(raw, list):
            warnings.extend(str(item) for item in raw if str(item))
    if not transfer_plan:
        warnings.append("transfer_plan_missing_or_generated_without_saved_report")
    if not share_search_plan:
        warnings.append("share_search_plan_missing_auto_transfer_will_require_search")
    return sorted(set(warnings))


def _strm_root_from_cloud_item(item: Dict[str, object], host_strm_root: str) -> str:
    samples = _string_list(item.get("strm_paths_sample"))
    if not samples:
        return ""
    path = samples[0]
    if path.lower().endswith(".strm"):
        root = str(PurePosixPath(path).parent)
    else:
        root = path
    if host_strm_root and root.startswith("/strm/"):
        return host_strm_root.rstrip("/") + root[len("/strm") :]
    return root


def _cloud_media_path(cloud_root: str, title: str, tmdbid: int, season: int) -> str:
    root = (cloud_root or DEFAULT_CLOUD_ROOT).rstrip("/")
    clean_title = _strip_identity_suffix(title).strip() or title or "unknown"
    suffix = f" {{tmdbid={tmdbid}}}" if tmdbid else ""
    season_segment = f"Season {season:02d}" if season else "Season XX"
    return f"{root}/{clean_title}{suffix}/{season_segment}"


def _cloud_title_path_from_item(item: Dict[str, object], cloud_root: str) -> str:
    existing = str(item.get("cloud_media_path") or "").rstrip("/")
    for season_pattern in (r"/Season\s*0?\d+$", r"/S0?\d+$", r"/第\s*\d+\s*季$"):
        if re.search(season_pattern, existing, flags=re.IGNORECASE):
            return re.sub(season_pattern, "", existing, flags=re.IGNORECASE)
    title = str(item.get("title") or "")
    tmdbid = int(item.get("tmdbid") or 0)
    root = (cloud_root or DEFAULT_CLOUD_ROOT).rstrip("/")
    clean_title = _strip_identity_suffix(title).strip() or title or "unknown"
    suffix = f" {{tmdbid={tmdbid}}}" if tmdbid else ""
    return f"{root}/{clean_title}{suffix}" if root else ""


def _cloud_target_prefix_from_strm_root(strm_root: str, cloud_root: str = DEFAULT_CLOUD_ROOT) -> str:
    if not strm_root:
        return ""
    normalized = str(strm_root).rstrip("/")
    marker = "/strm/"
    if marker not in normalized:
        return ""
    suffix = normalized.split(marker, 1)[1].strip("/")
    if not suffix:
        return ""
    root_name = PurePosixPath(cloud_root.rstrip("/") or "/").name
    if root_name and suffix == root_name:
        suffix = ""
    elif root_name and suffix.startswith(root_name + "/"):
        suffix = suffix[len(root_name) + 1 :]
    return f"{cloud_root.rstrip('/')}/{suffix}"


def _cloud_title_path_from_strm_root(strm_root: str, cloud_root: str = DEFAULT_CLOUD_ROOT) -> str:
    cloud_path = _cloud_target_prefix_from_strm_root(strm_root, cloud_root=cloud_root)
    if not cloud_path:
        return ""
    for season_pattern in (r"/Season\s*0?\d+$", r"/S0?\d+$", r"/第\s*\d+\s*季$"):
        if re.search(season_pattern, cloud_path, flags=re.IGNORECASE):
            return re.sub(season_pattern, "", cloud_path, flags=re.IGNORECASE)
    return str(PurePosixPath(cloud_path).parent)


def _host_strm_path_from_cloud(cloud_media_path: str, mv3_strm_root: str) -> str:
    suffix = cloud_media_path.strip("/")
    for prefix in ("已整理/", "未整理/"):
        if suffix.startswith(prefix):
            suffix = suffix[len(prefix) :]
            break
    return f"{mv3_strm_root.rstrip('/')}/{suffix}"


def _host_strm_path_from_cloud_title(cloud_title_path: str, host_strm_root: str) -> str:
    if not cloud_title_path or not host_strm_root:
        return ""
    suffix = cloud_title_path.strip("/")
    for prefix in ("已整理/", "未整理/"):
        if suffix.startswith(prefix):
            suffix = suffix[len(prefix) :]
            break
    return f"{host_strm_root.rstrip('/')}/{suffix}"


def _map_strm_root(path: str, host_strm_root: str, emby_strm_root: str) -> str:
    if host_strm_root and emby_strm_root:
        left = host_strm_root.rstrip("/")
        if path == left:
            return emby_strm_root.rstrip("/")
        if path.startswith(left + "/"):
            return emby_strm_root.rstrip("/") + path[len(left) :]
    return path


def _review_identity_key(item: Dict[str, object]) -> Tuple[int, int]:
    return int(item.get("tmdbid") or 0), int(item.get("season") or 0)


def _review_preview_by_identity(reports: Sequence[Dict[str, object]]) -> Dict[Tuple[int, int], Dict[str, object]]:
    result: Dict[Tuple[int, int], Dict[str, object]] = {}
    for report_index, report in enumerate(reports, start=1):
        if not isinstance(report, dict):
            continue
        for item in report.get("items", []):
            if not isinstance(item, dict):
                continue
            key = _review_identity_key(item)
            if key == (0, 0):
                continue
            enriched = dict(item)
            enriched["preview_report_index"] = report_index
            existing = result.get(key)
            if existing is None or _review_preview_rank(enriched) > _review_preview_rank(existing):
                result[key] = enriched
    return result


def _review_preview_rank(item: Dict[str, object]) -> Tuple[int, int, int, int]:
    status = str(item.get("status") or "")
    return (
        3 if status == "preview_ready_for_receive" else 2 if status == "preview_blocked" else 1 if status == "planned_preview" else 0,
        int(item.get("preview_episode_count") or 0),
        int(item.get("candidate_score") or 0),
        -int(item.get("source_index") or 0),
    )


def _review_finalize_by_identity(reports: Sequence[Dict[str, object]]) -> Dict[Tuple[int, int], Dict[str, object]]:
    result: Dict[Tuple[int, int], Dict[str, object]] = {}
    for report_index, report in enumerate(reports, start=1):
        if not isinstance(report, dict):
            continue
        for item in report.get("items", []):
            if not isinstance(item, dict):
                continue
            key = _review_identity_key(item)
            if key == (0, 0):
                continue
            enriched = dict(item)
            enriched["finalize_report_index"] = report_index
            existing = result.get(key)
            if existing is None or _review_finalize_rank(enriched) > _review_finalize_rank(existing):
                result[key] = enriched
    return result


def _review_finalize_rank(item: Dict[str, object]) -> Tuple[int, int, int]:
    status = str(item.get("status") or "")
    status_rank = {
        "cleanup_executed": 5,
        "cleanup_waiting_for_approval": 4,
        "failed_cleanup_preview": 3,
    }.get(status, 2 if status.startswith("failed_") else 1)
    stages = item.get("stages") if isinstance(item.get("stages"), list) else []
    ok_stages = sum(1 for stage in stages if isinstance(stage, dict) and bool(stage.get("ok")))
    return status_rank, ok_stages, -int(item.get("finalize_report_index") or 0)


def _batch_review_row(
    source_index: int,
    item: Dict[str, object],
    preview_item: Dict[str, object],
    finalize_item: Dict[str, object],
) -> Dict[str, object]:
    diagnostics = item.get("candidate_diagnostics") if isinstance(item.get("candidate_diagnostics"), dict) else {}
    best_candidate = diagnostics.get("best_candidate") if isinstance(diagnostics.get("best_candidate"), dict) else {}
    recommended = item.get("recommended_candidate") if isinstance(item.get("recommended_candidate"), dict) else {}
    decision = _review_decision(item, preview_item, finalize_item)
    reasons = sorted(
        set(
            _string_list(item.get("review_reasons"))
            + _string_list(item.get("blockers"))
            + _string_list(item.get("cleanup_preview_blockers"))
            + _string_list(finalize_item.get("blockers"))
            + _review_preview_reasons(preview_item, decision)
        )
    )
    next_action = _review_next_action(decision, reasons)
    return {
        "source_index": source_index,
        "decision": decision,
        "next_action": next_action,
        "bucket": item.get("bucket", ""),
        "state": item.get("state", ""),
        "title": item.get("title", ""),
        "tmdbid": item.get("tmdbid", ""),
        "season": item.get("season", ""),
        "cloud_status": item.get("cloud_status", ""),
        "size": item.get("size", ""),
        "size_bytes": int(item.get("size_bytes") or 0),
        "expected_episode_count": item.get("expected_episode_count", ""),
        "expected_episodes": _episode_cell(item.get("expected_episodes")),
        "reason_summary": "; ".join(reasons),
        "review_reasons": "; ".join(_string_list(item.get("review_reasons"))),
        "blockers": "; ".join(_string_list(item.get("blockers"))),
        "candidate_count": item.get("candidate_count", ""),
        "search_result_count": diagnostics.get("search_result_count", "") if diagnostics else "",
        "search_warnings": "; ".join(_string_list(diagnostics.get("search_warnings"))) if diagnostics else "",
        "recommended_candidate_title": recommended.get("title", "") if recommended else "",
        "recommended_candidate_score": recommended.get("score", "") if recommended else "",
        "recommended_candidate_size_delta_ratio": recommended.get("size_delta_ratio", "") if recommended else "",
        "best_candidate_title": best_candidate.get("title", "") if best_candidate else "",
        "best_candidate_score": best_candidate.get("score", "") if best_candidate else "",
        "best_candidate_size_delta_ratio": best_candidate.get("size_delta_ratio", "") if best_candidate else "",
        "best_candidate_blockers": "; ".join(_string_list(best_candidate.get("blockers"))) if best_candidate else "",
        "preview_status": preview_item.get("status", "") if preview_item else "",
        "preview_episode_count": preview_item.get("preview_episode_count", "") if preview_item else "",
        "preview_missing_expected": _episode_cell(preview_item.get("preview_missing_expected")) if preview_item else "",
        "preview_unexpected_episodes": _episode_cell(preview_item.get("preview_unexpected_episodes")) if preview_item else "",
        "preview_blockers": "; ".join(_string_list(preview_item.get("preview_blockers"))) if preview_item else "",
        "finalize_status": finalize_item.get("status", "") if finalize_item else "",
        "finalize_last_stage": _review_last_stage(finalize_item),
        "finalize_blockers": "; ".join(_string_list(finalize_item.get("blockers"))) if finalize_item else "",
        "finalize_cleanup_unlinked_videos": " | ".join(_string_list(finalize_item.get("cleanup_unlinked_video_sample"))) if finalize_item else "",
        "finalize_cleanup_blocked_source_roots": _blocked_source_roots_cell(finalize_item.get("cleanup_blocked_source_roots")) if finalize_item else "",
        "cloud_media_path": item.get("cloud_media_path", ""),
        "strm_root": item.get("strm_root", ""),
        "source_paths": " | ".join(_string_list(item.get("source_paths"))),
    }


def _review_decision(item: Dict[str, object], preview_item: Dict[str, object], finalize_item: Dict[str, object]) -> str:
    finalize_status = str(finalize_item.get("status") or "")
    if finalize_status == "cleanup_executed":
        return "done_cleanup_executed"
    if finalize_status == "cleanup_waiting_for_approval":
        return "ready_for_cleanup_approval"
    if finalize_status:
        return "blocked_after_finalize_gates"

    preview_status = str(preview_item.get("status") or "")
    if preview_status == "preview_ready_for_receive":
        return "ready_for_receive_plan"
    if preview_status == "preview_blocked":
        return "manual_review_preview_blocked"

    bucket = str(item.get("bucket") or "")
    if bucket == AUTO_CLEANUP:
        return "ready_for_finalize_gates"
    if bucket == AUTO_TRANSFER:
        return "ready_for_share_preview"
    if bucket == MANUAL_REVIEW:
        return "manual_review_required"
    return "skipped"


def _review_preview_reasons(preview_item: Dict[str, object], decision: str) -> List[str]:
    if not preview_item:
        return []
    status = str(preview_item.get("status") or "")
    if status == "preview_blocked":
        return _string_list(preview_item.get("preview_blockers"))
    if decision.startswith("manual_review") and status == "skipped_preview":
        return _string_list(preview_item.get("skip_reasons"))
    return []


def _review_next_action(decision: str, reasons: Sequence[str]) -> str:
    if decision == "done_cleanup_executed":
        return "已完成清理，保留报告归档"
    if decision == "ready_for_cleanup_approval":
        return "复核 finalize 报告后，可进入显式清理审批"
    if decision == "blocked_after_finalize_gates":
        return "先处理 finalize 阶段阻断，再重新运行 finalize"
    if decision == "ready_for_receive_plan":
        return "生成 receive plan，审批后由批量 runner 接收并整理"
    if decision == "manual_review_preview_blocked":
        return "人工核对分享内容、缺失集和候选标题"
    if decision == "ready_for_finalize_gates":
        return "运行 batch-finalize-plan/run，只刮削 STRM 并验证 Emby"
    if decision == "ready_for_share_preview":
        return "运行 batch-share-preview，再决定是否接收"
    if "identity_or_season_requires_review" in reasons:
        return "先补 TMDB/季号身份映射，再重新 cloud-check/batch-plan"
    if "no_recommended_mv3_share_candidate" in reasons:
        return "继续扩展 MV3 搜索或人工指定分享候选"
    if "episode_coverage_unclear" in reasons:
        return "先做只读分享预览确认集数"
    if "possible_chinese_subtitle_mismatch" in reasons or "season_mismatch" in reasons:
        return "候选疑似错剧或错季，人工确认前不要转存"
    if "remote_size_not_similar_enough" in reasons or "size_far_from_local" in reasons:
        return "体积差异较大，人工确认版本/清晰度后再处理"
    return "保留本地，等待更多证据"


def _review_last_stage(item: Dict[str, object]) -> str:
    stages = item.get("stages") if isinstance(item.get("stages"), list) else []
    if not stages:
        return ""
    last = stages[-1]
    return str(last.get("stage") or "") if isinstance(last, dict) else ""


def _episode_cell(value: object) -> str:
    episodes = _int_list(value)
    if not episodes:
        return ""
    ranges: List[str] = []
    start = episodes[0]
    previous = episodes[0]
    for episode in episodes[1:]:
        if episode == previous + 1:
            previous = episode
            continue
        ranges.append(f"{start}-{previous}" if start != previous else str(start))
        start = previous = episode
    ranges.append(f"{start}-{previous}" if start != previous else str(start))
    suffix = f" ({len(episodes)}集)" if len(episodes) > 20 else ""
    return ",".join(ranges) + suffix


def _blocked_source_roots_cell(value: object) -> str:
    if not isinstance(value, list):
        return ""
    parts: List[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        video_count = int(item.get("video_count") or 0)
        linked_count = int(item.get("linked_hlink_video_count") or 0)
        if path:
            parts.append(f"{path} ({linked_count}/{video_count} linked)")
    return " | ".join(parts)


def _strip_identity_suffix(value: str) -> str:
    import re

    text = re.sub(r"\s*\{tmdbid=\d+\}", "", value or "", flags=re.IGNORECASE)
    return " ".join(text.split())


def _tmdbid_from_text(text: str) -> int:
    import re

    match = re.search(r"\{tmdbid=(\d+)\}", text or "", re.IGNORECASE)
    return int(match.group(1)) if match else 0


def _string_list(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _first_hlink_path(paths: Sequence[str]) -> str:
    for path in paths:
        if "/hlink/" in path.replace("\\", "/"):
            return str(path).rstrip("/")
    return str(paths[0]).rstrip("/") if paths else ""


def _int_list(value: object) -> List[int]:
    if not isinstance(value, list):
        return []
    return [int(item) for item in value if isinstance(item, int) or str(item).isdigit()]


def _env_arg(env_file: str) -> str:
    return f'--env-file "{env_file}" ' if env_file else ""


def _env_arg_q(env_file: str) -> str:
    return f"--env-file {_q(env_file)} " if env_file else ""


def _q(value: object) -> str:
    return shlex.quote(str(value))


def _report_prefix(title: str, tmdbid: int, season: int) -> str:
    slug = re.sub(r"[^0-9A-Za-z一-龥]+", "-", _strip_identity_suffix(title)).strip("-")
    if not slug:
        slug = "series"
    return f"{slug}-{tmdbid}-s{season:02d}"


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _render_markdown(plan: Dict[str, object]) -> str:
    lines = [
        "# Series Cloud Archiver Batch Plan",
        "",
        f"- Mode: `{plan.get('mode', '')}`",
        f"- Planned items: `{plan.get('planned_items', 0)}` / `{plan.get('total_items_before_limit', 0)}`",
        f"- Bucket counts: `{plan.get('bucket_counts', {})}`",
        "- Safety: readonly state plan only; no cloud write, scrape, Emby refresh, qB action, hlink/source deletion, or filesystem deletion is performed.",
        "",
    ]
    warnings = plan.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
        lines.append("")

    lines.extend(
        [
            "## Items",
            "",
            "| Bucket | Size | TMDB | S | Episodes | Title | Reason |",
            "| --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for item in plan.get("items", []):
        if not isinstance(item, dict):
            continue
        reason = ", ".join(_string_list(item.get("review_reasons")) + _string_list(item.get("blockers")))
        lines.append(
            "| {bucket} | {size} | {tmdbid} | {season} | {episodes} | {title} | {reason} |".format(
                bucket=item.get("bucket", ""),
                size=item.get("size", ""),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                episodes=item.get("expected_episode_count") or "",
                title=str(item.get("title") or "").replace("|", "\\|"),
                reason=reason.replace("|", "\\|"),
            )
        )
    lines.append("")
    lines.append("## Next")
    lines.append("")
    lines.append("Run generated next-action commands only as dry-runs first. Approved write/delete flags are intentionally absent from this report.")
    return "\n".join(lines)


def _render_csv(plan: Dict[str, object]) -> str:
    fieldnames = [
        "bucket",
        "state",
        "title",
        "tmdbid",
        "season",
        "size",
        "expected_episode_count",
        "review_reasons",
        "blockers",
        "candidate_count",
        "merged_duplicate_count",
        "recommended_candidate_title",
        "recommended_candidate_score",
        "recommended_candidate_size_delta_ratio",
        "best_candidate_title",
        "best_candidate_score",
        "best_candidate_size_delta_ratio",
        "best_candidate_blockers",
        "candidate_blocker_counts",
        "candidate_reason_counts",
        "search_ok",
        "search_result_count",
        "search_warnings",
        "cleanup_preview_ready",
        "cleanup_preview_blockers",
        "cloud_media_path",
        "strm_root",
        "source_paths",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for item in plan.get("items", []):
        if not isinstance(item, dict):
            continue
        candidate = item.get("recommended_candidate") if isinstance(item.get("recommended_candidate"), dict) else {}
        diagnostics = item.get("candidate_diagnostics") if isinstance(item.get("candidate_diagnostics"), dict) else {}
        best_candidate = diagnostics.get("best_candidate") if isinstance(diagnostics.get("best_candidate"), dict) else {}
        writer.writerow(
            {
                "bucket": item.get("bucket", ""),
                "state": item.get("state", ""),
                "title": item.get("title", ""),
                "tmdbid": item.get("tmdbid", ""),
                "season": item.get("season", ""),
                "size": item.get("size", ""),
                "expected_episode_count": item.get("expected_episode_count", ""),
                "review_reasons": "; ".join(_string_list(item.get("review_reasons"))),
                "blockers": "; ".join(_string_list(item.get("blockers"))),
                "candidate_count": item.get("candidate_count", ""),
                "merged_duplicate_count": item.get("merged_duplicate_count", ""),
                "recommended_candidate_title": candidate.get("title", "") if candidate else "",
                "recommended_candidate_score": candidate.get("score", "") if candidate else "",
                "recommended_candidate_size_delta_ratio": candidate.get("size_delta_ratio", "") if candidate else "",
                "best_candidate_title": best_candidate.get("title", "") if best_candidate else "",
                "best_candidate_score": best_candidate.get("score", "") if best_candidate else "",
                "best_candidate_size_delta_ratio": best_candidate.get("size_delta_ratio", "") if best_candidate else "",
                "best_candidate_blockers": "; ".join(_string_list(best_candidate.get("blockers"))) if best_candidate else "",
                "candidate_blocker_counts": _counter_cell(diagnostics.get("candidate_blocker_counts")),
                "candidate_reason_counts": _counter_cell(diagnostics.get("candidate_reason_counts")),
                "search_ok": diagnostics.get("search_ok", "") if diagnostics else "",
                "search_result_count": diagnostics.get("search_result_count", "") if diagnostics else "",
                "search_warnings": "; ".join(_string_list(diagnostics.get("search_warnings"))) if diagnostics else "",
                "cleanup_preview_ready": item.get("cleanup_preview_ready", ""),
                "cleanup_preview_blockers": "; ".join(_string_list(item.get("cleanup_preview_blockers"))),
                "cloud_media_path": item.get("cloud_media_path", ""),
                "strm_root": item.get("strm_root", ""),
                "source_paths": " | ".join(_string_list(item.get("source_paths"))),
            }
        )
    return output.getvalue().rstrip("\r\n")


def _render_review_markdown(report: Dict[str, object]) -> str:
    lines = [
        "# Batch Human Review Report",
        "",
        f"- Mode: `{report.get('mode', '')}`",
        f"- Total items: `{report.get('total_items', 0)}`",
        f"- Decision counts: `{report.get('decision_counts', {})}`",
        f"- Bucket counts: `{report.get('bucket_counts', {})}`",
        "- Safety: readonly report only; no scan, network call, write, or delete action is performed.",
        "",
        "| Decision | Size | TMDB | S | Episodes | Title | Reason | Next action |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {decision} | {size} | {tmdbid} | {season} | {episodes} | {title} | {reason} | {next_action} |".format(
                decision=item.get("decision", ""),
                size=item.get("size", ""),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                episodes=item.get("expected_episode_count") or "",
                title=_escape_cell(str(item.get("title") or "")),
                reason=_escape_cell(str(item.get("reason_summary") or "")),
                next_action=_escape_cell(str(item.get("next_action") or "")),
            )
        )
    return "\n".join(lines)


def _render_review_csv(report: Dict[str, object]) -> str:
    fieldnames = [
        "decision",
        "next_action",
        "bucket",
        "state",
        "title",
        "tmdbid",
        "season",
        "cloud_status",
        "size",
        "size_bytes",
        "expected_episode_count",
        "expected_episodes",
        "reason_summary",
        "review_reasons",
        "blockers",
        "candidate_count",
        "search_result_count",
        "search_warnings",
        "recommended_candidate_title",
        "recommended_candidate_score",
        "recommended_candidate_size_delta_ratio",
        "best_candidate_title",
        "best_candidate_score",
        "best_candidate_size_delta_ratio",
        "best_candidate_blockers",
        "preview_status",
        "preview_episode_count",
        "preview_missing_expected",
        "preview_unexpected_episodes",
        "preview_blockers",
        "finalize_status",
        "finalize_last_stage",
        "finalize_blockers",
        "finalize_cleanup_unlinked_videos",
        "finalize_cleanup_blocked_source_roots",
        "cloud_media_path",
        "strm_root",
        "source_paths",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for item in report.get("items", []):
        if isinstance(item, dict):
            writer.writerow({name: item.get(name, "") for name in fieldnames})
    return output.getvalue().rstrip("\r\n")


def _counter_cell(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    parts = []
    for key, count in sorted(value.items(), key=lambda item: str(item[0])):
        if not str(key):
            continue
        parts.append(f"{key}:{int(count or 0)}")
    return "; ".join(parts)
