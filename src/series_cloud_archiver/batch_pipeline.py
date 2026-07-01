from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .batch_preview import (
    build_batch_share_preview_plan,
    build_batch_share_receive_plan,
)
from .batch_runner import (
    AUTO_TRANSFER,
    MANUAL_REVIEW,
    BatchFinalizeActions,
    build_batch_finalize_plan,
    build_batch_plan,
    build_batch_review_report,
    run_batch_finalize,
)
from .batch_transfer import BatchTransferActions, run_batch_transfer
from .cloud_check import cloud_check_from_scan_report
from .config import ScanConfig
from .extra_source_media import build_extra_source_media_plan
from .mv3 import preview_mv3_share, search_mv3_resources
from .scanner import scan
from .transfer_plan import (
    DEFAULT_CLOUD_ROOT,
    DEFAULT_STRM_ROOT,
    plan_mv3_share_search_from_transfer_plan,
    plan_mv3_transfers_from_cloud_report,
    search_keywords_for_item,
)


JsonDict = Dict[str, object]
DEFAULT_SHARE_SEARCH_FALLBACK_CHANNELS = ["pansou"]


@dataclass
class BatchPipelineActions:
    scan: Callable[[ScanConfig], object] = scan
    cloud_check: Callable[..., object] = cloud_check_from_scan_report
    share_search: Callable[..., JsonDict] = search_mv3_resources
    share_preview: Callable[..., JsonDict] = preview_mv3_share
    transfer_actions: Optional[BatchTransferActions] = None
    finalize_actions: Optional[BatchFinalizeActions] = None


def run_batch_pipeline(
    *,
    output_dir: str,
    config: ScanConfig,
    env_file: str = "",
    run_id: str = "",
    scan_report: Optional[JsonDict] = None,
    cloud_report: Optional[JsonDict] = None,
    transfer_plan: Optional[JsonDict] = None,
    share_search_plans: Optional[Sequence[JsonDict]] = None,
    share_preview_report: Optional[JsonDict] = None,
    review_reports: Optional[Sequence[JsonDict]] = None,
    cleanup_preview_reports: Optional[Sequence[JsonDict]] = None,
    media_roots: Optional[Sequence[str]] = None,
    strm_roots: Optional[Sequence[str]] = None,
    identity_file: str = "",
    manual_exclusions: Optional[Sequence[Dict[str, object]]] = None,
    cloud_root: str = DEFAULT_CLOUD_ROOT,
    mv3_strm_root: str = DEFAULT_STRM_ROOT,
    host_strm_root: str = "",
    mp_strm_root: str = "",
    emby_strm_root: str = "",
    min_candidate_score: int = 60,
    max_auto_size_delta: float = 0.35,
    required_target_prefix: str = "/已整理",
    forbidden_target_prefixes: Optional[Sequence[str]] = None,
    execute_share_search: bool = False,
    share_search_limit: int = 0,
    share_search_offset: int = 0,
    share_search_max_candidates: int = 5,
    share_search_channels: Optional[Sequence[str]] = None,
    share_search_timeout: int = 60,
    execute_preview: bool = False,
    preview_limit: int = 10,
    preview_buckets: Optional[Sequence[str]] = None,
    preview_min_candidate_score: int = 55,
    preview_allowed_best_blockers: Optional[Sequence[str]] = None,
    preview_storage: str = "115-default",
    preview_timeout: int = 60,
    max_nested_depth: int = 3,
    run_transfer_stage: bool = False,
    approve_receive: bool = False,
    approve_transfer: bool = False,
    preflight_staging: bool = False,
    transfer_target_path: str = "/未整理",
    organize_target_dir: str = "/已整理",
    transfer_strm_dir: str = DEFAULT_STRM_ROOT,
    transfer_storage: str = "115-default",
    transfer_timeout: int = 60,
    organize_timeout: int = 180,
    refresh_after_transfer: bool = True,
    run_finalize_stage: bool = False,
    finalize_offset: int = 0,
    finalize_limit: int = 0,
    finalize_titles: Optional[Sequence[str]] = None,
    continue_on_error: bool = False,
    execute_scrape: bool = False,
    approve_cloud_duplicate_delete: bool = False,
    approve_emby_stale_delete: bool = False,
    approve_delete: bool = False,
    min_seed_days: int = 7,
    cloud_media_storage: str = "115-default",
    finalize_timeout: int = 20,
    scrape_timeout: int = 120,
    nfo_min_chinese_ratio: float = 0.35,
    nfo_sample_limit: int = 50,
    actions: Optional[BatchPipelineActions] = None,
) -> JsonDict:
    """Run the safe batch state machine and persist every stage report.

    The pipeline does not invent new media operations. It wires the existing
    readonly planners and approval-gated runners together, then writes a state
    file so later runs can resume from concrete JSON reports instead of a
    human-maintained command list.
    """

    actions = actions or BatchPipelineActions()
    pipeline_dir = _pipeline_dir(output_dir, run_id)
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    phases: List[JsonDict] = []
    warnings: List[str] = []
    generated_share_search_plans: List[JsonDict] = []
    provided_share_search_plans = [dict(item) for item in (share_search_plans or []) if isinstance(item, dict)]
    provided_review_reports = [dict(item) for item in (review_reports or []) if isinstance(item, dict)]
    cleanup_reports = [dict(item) for item in (cleanup_preview_reports or []) if isinstance(item, dict)]

    if scan_report is None and cloud_report is None:
        effective_config = _scan_config(config, media_roots)
        effective_config.output_format = "json"
        scan_obj = actions.scan(effective_config)
        scan_report = _as_dict(scan_obj)
        scan_blockers = _scan_phase_blockers(scan_report)
        if scan_blockers:
            warnings.extend(scan_blockers)
            phases.append(_write_phase(pipeline_dir, "01-scan", scan_report, ok=False))
        else:
            phases.append(_write_phase(pipeline_dir, "01-scan", scan_report))
    elif scan_report is not None:
        phases.append(_input_phase("scan", scan_report))
    else:
        phases.append(_skipped_phase("scan", "cloud_report_provided"))

    if cloud_report is None:
        if scan_report is None:
            raise ValueError("cloud_report requires scan_report when it is not provided")
        roots = list(strm_roots or []) or list(getattr(config, "strm_roots", []) or [])
        cloud_obj = actions.cloud_check(
            scan_report,
            roots,
            identity_file=identity_file or getattr(config, "identity_file", ""),
        )
        cloud_report = _as_dict(cloud_obj)
        phases.append(_write_phase(pipeline_dir, "02-cloud-check", cloud_report))
    else:
        phases.append(_input_phase("cloud-check", cloud_report))

    if transfer_plan is None:
        transfer_plan = plan_mv3_transfers_from_cloud_report(cloud_report)
        phases.append(_write_phase(pipeline_dir, "03-transfer-plan", transfer_plan))
    else:
        phases.append(_input_phase("transfer-plan", transfer_plan))

    if execute_share_search:
        if not getattr(config, "mv3_base_url", "") or not getattr(config, "mv3_token", ""):
            raise ValueError("execute_share_search requires MV3_BASE_URL and MV3_API_TOKEN")
        search_reports = _run_share_search_reports(
            transfer_plan,
            config.mv3_base_url,
            config.mv3_token,
            limit=share_search_limit,
            offset=share_search_offset,
            max_candidates=share_search_max_candidates,
            channels=list(share_search_channels or []),
            timeout=share_search_timeout,
            checkpoint_path=pipeline_dir / "04-share-search.checkpoint.json",
            search_func=actions.share_search,
        )
        share_search_plan = plan_mv3_share_search_from_transfer_plan(
            transfer_plan,
            search_reports,
            limit=share_search_limit,
            max_candidates=share_search_max_candidates,
            offset=share_search_offset,
        )
        generated_share_search_plans.append(share_search_plan)
        phases.append(_write_phase(pipeline_dir, "04-share-search", share_search_plan))
    elif provided_share_search_plans:
        phases.append(_input_phase("share-search", {"items": _merged_items(provided_share_search_plans)}))
    else:
        phases.append(_skipped_phase("share-search", "execute_share_search_not_requested"))

    batch_plan = build_batch_plan(
        cloud_report=cloud_report,
        transfer_plan=transfer_plan,
        share_search_plans=provided_share_search_plans + generated_share_search_plans,
        cleanup_preview_reports=cleanup_reports,
        scan_report=scan_report,
        cloud_root=cloud_root,
        mv3_strm_root=mv3_strm_root,
        host_strm_root=host_strm_root,
        emby_strm_root=emby_strm_root,
        env_file=env_file,
        min_candidate_score=min_candidate_score,
        max_auto_size_delta=max_auto_size_delta,
        required_target_prefix=required_target_prefix,
        forbidden_target_prefixes=forbidden_target_prefixes or [],
        manual_exclusions=manual_exclusions or [],
    )
    batch_plan_phase = _write_phase(pipeline_dir, "05-batch-plan", batch_plan)
    phases.append(batch_plan_phase)
    active_batch_plan = batch_plan

    if share_preview_report is not None:
        phase = _write_phase(pipeline_dir, "06-share-preview", share_preview_report)
        phase["status"] = "input"
        phases.append(phase)
    else:
        preview_dir = pipeline_dir / "share-previews"
        share_preview_report = build_batch_share_preview_plan(
            active_batch_plan,
            env_file=env_file,
            buckets=preview_buckets or [AUTO_TRANSFER, MANUAL_REVIEW],
            min_candidate_score=preview_min_candidate_score,
            allowed_best_blockers=preview_allowed_best_blockers,
            limit=preview_limit,
            execute_preview=execute_preview,
            base_url=getattr(config, "mv3_base_url", "") if execute_preview else "",
            token=getattr(config, "mv3_token", "") if execute_preview else "",
            channels=share_search_channels,
            storage=preview_storage,
            timeout=preview_timeout,
            preview_output_dir=str(preview_dir) if execute_preview else "",
            max_nested_depth=max_nested_depth,
            review_reports=provided_review_reports,
            preview_func=actions.share_preview if execute_preview else None,
        )
        phases.append(_write_phase(pipeline_dir, "06-share-preview", share_preview_report))

    receive_plan = build_batch_share_receive_plan(
        share_preview_report,
        env_file=env_file,
        target_path=transfer_target_path,
        storage=transfer_storage,
    )
    phases.append(_write_phase(pipeline_dir, "07-receive-plan", receive_plan))

    transfer_run_report: Optional[JsonDict] = None
    if run_transfer_stage:
        if not getattr(config, "mv3_base_url", "") or not getattr(config, "mv3_token", ""):
            raise ValueError("run_transfer_stage requires MV3_BASE_URL and MV3_API_TOKEN")
        transfer_run_report = run_batch_transfer(
            receive_plan,
            output_dir=str(pipeline_dir / "transfer-stages"),
            config=config,
            approve_receive=approve_receive,
            approve_transfer=approve_transfer,
            preflight_staging=preflight_staging,
            target_path=transfer_target_path,
            organize_target_dir=organize_target_dir,
            strm_dir=transfer_strm_dir,
            storage=transfer_storage,
            timeout=transfer_timeout,
            transfer_timeout=organize_timeout,
            host_strm_root=host_strm_root,
            actions=actions.transfer_actions,
        )
        phases.append(_write_phase(pipeline_dir, "08-transfer-run", transfer_run_report, ok=bool(transfer_run_report.get("ok"))))
    else:
        phases.append(_skipped_phase("transfer-run", "run_transfer_stage_not_requested"))

    if (
        refresh_after_transfer
        and transfer_run_report
        and int(transfer_run_report.get("organized_items") or 0) > 0
        and scan_report is not None
    ):
        roots = list(strm_roots or []) or list(getattr(config, "strm_roots", []) or [])
        post_cloud_obj = actions.cloud_check(
            scan_report,
            roots,
            identity_file=identity_file or getattr(config, "identity_file", ""),
        )
        post_cloud_report = _as_dict(post_cloud_obj)
        phases.append(_write_phase(pipeline_dir, "09-cloud-check-post-transfer", post_cloud_report))
        post_transfer_plan = plan_mv3_transfers_from_cloud_report(post_cloud_report)
        phases.append(_write_phase(pipeline_dir, "10-transfer-plan-post-transfer", post_transfer_plan))
        active_batch_plan = build_batch_plan(
            cloud_report=post_cloud_report,
            transfer_plan=post_transfer_plan,
            share_search_plans=provided_share_search_plans + generated_share_search_plans,
            cleanup_preview_reports=cleanup_reports,
            scan_report=scan_report,
            cloud_root=cloud_root,
            mv3_strm_root=mv3_strm_root,
            host_strm_root=host_strm_root,
            emby_strm_root=emby_strm_root,
            env_file=env_file,
            min_candidate_score=min_candidate_score,
            max_auto_size_delta=max_auto_size_delta,
            required_target_prefix=required_target_prefix,
            forbidden_target_prefixes=forbidden_target_prefixes or [],
            manual_exclusions=manual_exclusions or [],
        )
        phases.append(_write_phase(pipeline_dir, "11-batch-plan-post-transfer", active_batch_plan))
    elif transfer_run_report and int(transfer_run_report.get("organized_items") or 0) > 0:
        warnings.append("post_transfer_refresh_skipped_without_scan_report")

    finalize_plan = build_batch_finalize_plan(
        active_batch_plan,
        env_file=env_file,
        cloud_root=cloud_root,
        host_strm_root=host_strm_root,
        mp_strm_root=mp_strm_root,
        service_strm_root=emby_strm_root,
        required_target_prefix="",
        forbidden_target_prefixes=forbidden_target_prefixes or [],
        manual_exclusions=manual_exclusions or [],
        offset=finalize_offset,
        limit=finalize_limit,
    )
    phases.append(_write_phase(pipeline_dir, "12-finalize-plan", finalize_plan))

    finalize_run_report: Optional[JsonDict] = None
    if run_finalize_stage:
        finalize_run_report = run_batch_finalize(
            finalize_plan,
            output_dir=str(pipeline_dir / "finalize-stages"),
            config=config,
            limit=finalize_limit,
            title_filters=finalize_titles or [],
            manual_exclusions=manual_exclusions or [],
            continue_on_error=continue_on_error,
            execute_scrape=execute_scrape,
            approve_cloud_duplicate_delete=approve_cloud_duplicate_delete,
            approve_emby_stale_delete=approve_emby_stale_delete,
            approve_delete=approve_delete,
            min_seed_days=min_seed_days,
            cloud_media_storage=cloud_media_storage,
            timeout=finalize_timeout,
            scrape_timeout=scrape_timeout,
            nfo_min_chinese_ratio=nfo_min_chinese_ratio,
            nfo_sample_limit=nfo_sample_limit,
            actions=actions.finalize_actions,
        )
        phases.append(_write_phase(pipeline_dir, "13-finalize-run", finalize_run_report, ok=bool(finalize_run_report.get("ok"))))
    else:
        phases.append(_skipped_phase("finalize-run", "run_finalize_stage_not_requested"))

    review_report = build_batch_review_report(
        active_batch_plan,
        share_preview_reports=[share_preview_report],
        transfer_run_reports=[transfer_run_report] if transfer_run_report else [],
        finalize_run_reports=[finalize_run_report] if finalize_run_report else [],
    )
    phases.append(_write_phase(pipeline_dir, "14-review", review_report))

    extra_source_plan: Optional[JsonDict] = None
    if finalize_run_report:
        extra_source_plan = build_extra_source_media_plan(
            finalize_run_report,
            env_file=env_file,
            target_dir=organize_target_dir,
            strm_dir=transfer_strm_dir,
            storage=transfer_storage,
            timeout=organize_timeout,
        )
        phases.append(_write_phase(pipeline_dir, "15-extra-source-media-plan", extra_source_plan))
    else:
        phases.append(_skipped_phase("extra-source-media-plan", "finalize_run_report_not_available"))

    state = _state_report(
        pipeline_dir=pipeline_dir,
        phases=phases,
        batch_plan=active_batch_plan,
        share_preview_report=share_preview_report,
        receive_plan=receive_plan,
        transfer_run_report=transfer_run_report,
        finalize_plan=finalize_plan,
        finalize_run_report=finalize_run_report,
        review_report=review_report,
        extra_source_plan=extra_source_plan,
        warnings=warnings,
        settings={
            "cloud_root": cloud_root,
            "organize_target_dir": organize_target_dir,
            "mv3_strm_root": mv3_strm_root,
            "host_strm_root": host_strm_root,
            "mp_strm_root": mp_strm_root,
            "emby_strm_root": emby_strm_root,
            "required_target_prefix": required_target_prefix,
            "forbidden_target_prefixes": list(forbidden_target_prefixes or []),
            "manual_exclusion_count": len(manual_exclusions or []),
            "execute_share_search": execute_share_search,
            "execute_preview": execute_preview,
            "run_transfer_stage": run_transfer_stage,
            "approve_receive": approve_receive,
            "approve_transfer": approve_transfer,
            "preflight_staging": preflight_staging,
            "run_finalize_stage": run_finalize_stage,
            "finalize_offset": finalize_offset,
            "finalize_limit": finalize_limit,
            "execute_scrape": execute_scrape,
            "approve_cloud_duplicate_delete": approve_cloud_duplicate_delete,
            "approve_emby_stale_delete": approve_emby_stale_delete,
            "approve_delete": approve_delete,
        },
    )
    state_phase = _write_phase(pipeline_dir, "00-pipeline-state", state, name="pipeline-state")
    state["state_file"] = state_phase["output"]
    _write_json(Path(str(state_phase["output"])), state)
    return state


def render_batch_pipeline_report(report: JsonDict, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)

    lines = [
        "# Batch Pipeline",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Run dir: `{report.get('run_dir', '')}`",
        f"- Failed phases: `{report.get('failed_phase_count', 0)}`",
        f"- Approval phases: `{report.get('approval_required_phase_count', 0)}`",
        f"- Auto transfer: `{_summary_value(report, 'batch_plan', 'auto_transfer_items')}`",
        f"- Auto finalize/cleanup: `{_summary_value(report, 'batch_plan', 'auto_validation_cleanup_items')}`",
        f"- Manual review: `{_summary_value(report, 'batch_plan', 'manual_review_items')}`",
        "",
        "| Phase | Status | Output | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for phase in report.get("phases", []):
        if not isinstance(phase, dict):
            continue
        lines.append(
            "| {name} | {status} | {output} | {summary} |".format(
                name=_escape_cell(str(phase.get("name") or "")),
                status=_escape_cell(str(phase.get("status") or "")),
                output=_escape_cell(str(phase.get("output") or "")),
                summary=_escape_cell(_phase_summary_text(phase)),
            )
        )
    warnings = [str(item) for item in report.get("warnings", []) if str(item)] if isinstance(report.get("warnings"), list) else []
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    return "\n".join(lines)


def _run_share_search_reports(
    transfer_plan: JsonDict,
    base_url: str,
    token: str,
    *,
    limit: int,
    offset: int,
    max_candidates: int,
    channels: Sequence[str],
    timeout: int,
    checkpoint_path: Optional[Path] = None,
    search_func: Callable[..., JsonDict],
) -> Dict[str, JsonDict]:
    raw_items = [item for item in transfer_plan.get("items", []) if isinstance(item, dict)]
    start = max(0, offset)
    stop = start + limit if limit > 0 else len(raw_items)
    selected = raw_items[start:stop]
    reports: Dict[str, JsonDict] = {}
    for item_index, item in enumerate(selected, start=1):
        title = str(item.get("title") or "")
        if not title:
            continue
        if checkpoint_path:
            _write_share_search_checkpoint(
                checkpoint_path,
                transfer_plan=transfer_plan,
                search_reports=reports,
                limit=max(item_index - 1, 0),
                offset=offset,
                max_candidates=max_candidates,
                completed_items=max(item_index - 1, 0),
                planned_items=len(selected),
                current_title=title,
                status="in_progress",
            )
        reports[title] = _combined_share_search(
            base_url,
            token,
            _share_search_keywords(item),
            channels=channels,
            timeout=timeout,
            search_func=search_func,
        )
        if checkpoint_path:
            _write_share_search_checkpoint(
                checkpoint_path,
                transfer_plan=transfer_plan,
                search_reports=reports,
                limit=item_index,
                offset=offset,
                max_candidates=max_candidates,
                completed_items=item_index,
                planned_items=len(selected),
                current_title=title,
                status="completed",
            )
    return reports


def _write_share_search_checkpoint(
    path: Path,
    *,
    transfer_plan: JsonDict,
    search_reports: Dict[str, JsonDict],
    limit: int,
    offset: int,
    max_candidates: int,
    completed_items: int,
    planned_items: int,
    current_title: str,
    status: str,
) -> None:
    checkpoint = plan_mv3_share_search_from_transfer_plan(
        transfer_plan,
        search_reports,
        limit=limit,
        max_candidates=max_candidates,
        offset=offset,
    )
    checkpoint["checkpoint"] = {
        "enabled": True,
        "completed_items": completed_items,
        "planned_items": planned_items,
        "current_title": current_title,
        "status": status,
        "complete": completed_items == planned_items,
    }
    _write_json(path, checkpoint)


def _combined_share_search(
    base_url: str,
    token: str,
    keywords: Sequence[str],
    *,
    channels: Sequence[str],
    timeout: int,
    search_func: Callable[..., JsonDict],
) -> JsonDict:
    keyword_reports: List[JsonDict] = []
    merged_items: List[JsonDict] = []
    seen: set[tuple[str, str, str]] = set()
    for keyword in keywords:
        clean_keyword = str(keyword or "").strip()
        if not clean_keyword:
            continue
        report = search_func(base_url, token, clean_keyword, channels=list(channels), timeout=timeout)
        keyword_reports.append(_keyword_search_summary(clean_keyword, report, list(channels), fallback=False, fallback_reason=""))
        _merge_search_items(merged_items, seen, report, clean_keyword)
        if _should_retry_with_fallback(report, channels):
            for fallback_channel in DEFAULT_SHARE_SEARCH_FALLBACK_CHANNELS:
                fallback_channels = [fallback_channel]
                fallback_report = search_func(base_url, token, clean_keyword, channels=fallback_channels, timeout=timeout)
                keyword_reports.append(
                    _keyword_search_summary(
                        clean_keyword,
                        fallback_report,
                        fallback_channels,
                        fallback=True,
                        fallback_reason="initial_search_timeout",
                    )
                )
                _merge_search_items(merged_items, seen, fallback_report, clean_keyword)
    return {
        "ok": any(report.get("ok") for report in keyword_reports),
        "result_count": len(merged_items),
        "items": merged_items,
        "keywords": [str(report["keyword"]) for report in keyword_reports],
        "keyword_reports": keyword_reports,
        "warnings": _combined_search_warnings(keyword_reports),
    }


def _keyword_search_summary(
    keyword: str,
    report: JsonDict,
    channels: Sequence[str],
    *,
    fallback: bool,
    fallback_reason: str,
) -> JsonDict:
    return {
        "keyword": keyword,
        "ok": bool(report.get("ok")),
        "result_count": int(report.get("result_count") or 0),
        "status": int(report.get("status") or 0),
        "channels": [str(channel) for channel in channels if str(channel)],
        "fallback": fallback,
        "fallback_reason": fallback_reason,
        "error_type": str(report.get("error_type") or ""),
        "error": str(report.get("error") or ""),
        "warnings": report.get("warnings", []) if isinstance(report.get("warnings"), list) else [],
    }


def _merge_search_items(
    merged_items: List[JsonDict],
    seen: set[tuple[str, str, str]],
    report: JsonDict,
    keyword: str,
) -> None:
    for row in report.get("items", []) if isinstance(report.get("items"), list) else []:
        if not isinstance(row, dict):
            continue
        key = (str(row.get("title") or ""), str(row.get("channel") or ""), str(row.get("size") or ""))
        if key in seen:
            continue
        seen.add(key)
        merged = dict(row)
        merged["search_keyword"] = keyword
        merged_items.append(merged)


def _should_retry_with_fallback(report: JsonDict, channels: Sequence[str]) -> bool:
    if channels or bool(report.get("ok")):
        return False
    return str(report.get("error_type") or "") == "TimeoutError"


def _combined_search_warnings(keyword_reports: List[JsonDict]) -> List[str]:
    warnings: List[str] = []
    for report in keyword_reports:
        for warning in report.get("warnings", []) if isinstance(report.get("warnings"), list) else []:
            text = str(warning or "")
            if text and text not in warnings:
                warnings.append(text)
        error_type = str(report.get("error_type") or "")
        if error_type:
            text = f"keyword_error:{report.get('keyword')}:{error_type}"
            if text not in warnings:
                warnings.append(text)
        if bool(report.get("fallback")):
            text = f"keyword_fallback:{report.get('keyword')}:{','.join(str(channel) for channel in report.get('channels', []))}"
            if text not in warnings:
                warnings.append(text)
    return warnings


def _share_search_keywords(item: JsonDict) -> List[str]:
    return search_keywords_for_item(item, limit=8)


def _scan_config(config: ScanConfig, media_roots: Optional[Sequence[str]]) -> ScanConfig:
    if not media_roots:
        return config
    copied = ScanConfig(**{field: getattr(config, field) for field in config.__dataclass_fields__})
    copied.media_roots = [str(item) for item in media_roots if str(item)]
    return copied


def _pipeline_dir(output_dir: str, run_id: str) -> Path:
    root = Path(output_dir)
    if run_id:
        clean_run = re.sub(r"[^0-9A-Za-z_.-]+", "-", run_id).strip("-")
        return root / (clean_run or "run")
    if root.name.startswith("pipeline-"):
        return root
    return root / f"pipeline-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _as_dict(value: object) -> JsonDict:
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, dict):
            return payload
    raise TypeError(f"expected JSON object report, got {type(value).__name__}")


def _write_phase(pipeline_dir: Path, stem: str, report: JsonDict, *, name: str = "", ok: Optional[bool] = None) -> JsonDict:
    path = pipeline_dir / f"{stem}.json"
    _write_json(path, report)
    status = "completed" if ok is not False else "failed"
    return {
        "name": name or _phase_name(stem),
        "status": status,
        "ok": ok is not False,
        "output": str(path),
        "summary": _report_summary(report),
    }


def _input_phase(name: str, report: JsonDict) -> JsonDict:
    return {
        "name": name,
        "status": "input",
        "ok": True,
        "summary": _report_summary(report),
    }


def _skipped_phase(name: str, reason: str) -> JsonDict:
    return {
        "name": name,
        "status": "skipped",
        "ok": True,
        "reason": reason,
        "summary": {"reason": reason},
    }


def _state_report(
    *,
    pipeline_dir: Path,
    phases: Sequence[JsonDict],
    batch_plan: JsonDict,
    share_preview_report: JsonDict,
    receive_plan: JsonDict,
    transfer_run_report: Optional[JsonDict],
    finalize_plan: JsonDict,
    finalize_run_report: Optional[JsonDict],
    review_report: JsonDict,
    extra_source_plan: Optional[JsonDict],
    warnings: Sequence[str],
    settings: JsonDict,
) -> JsonDict:
    failed = [phase for phase in phases if phase.get("status") == "failed"]
    approval = [
        phase
        for phase in phases
        if _phase_has_approval_required(phase)
    ]
    return {
        "mode": "batch-pipeline-state",
        "ok": not failed,
        "run_dir": str(pipeline_dir),
        "failed_phase_count": len(failed),
        "approval_required_phase_count": len(approval),
        "phases": list(phases),
        "summary": {
            "batch_plan": _batch_plan_summary(batch_plan),
            "share_preview": _report_summary(share_preview_report),
            "receive_plan": _report_summary(receive_plan),
            "transfer_run": _report_summary(transfer_run_report or {}),
            "finalize_plan": _report_summary(finalize_plan),
            "finalize_run": _report_summary(finalize_run_report or {}),
            "review": _report_summary(review_report),
            "extra_source_media": _report_summary(extra_source_plan or {}),
        },
        "settings": settings,
        "warnings": sorted(set(str(item) for item in warnings if str(item))),
        "safety": (
            "pipeline state only. Cloud receive/organize, MoviePilot scrape, Emby stale deletion, "
            "cloud duplicate deletion, qBittorrent cleanup, hlink deletion, and source deletion run only "
            "when their explicit approval flags are provided; cloud media folders are never scraped by this pipeline."
        ),
    }


def _phase_has_approval_required(phase: JsonDict) -> bool:
    summary = phase.get("summary") if isinstance(phase.get("summary"), dict) else {}
    return any(
        int(summary.get(key) or 0) > 0
        for key in (
            "approval_required_items",
            "dry_run_items",
            "finalize_ready_items",
        )
    )


def _scan_phase_blockers(scan_report: JsonDict) -> List[str]:
    if _string_list(scan_report.get("missing_media_roots")):
        return ["scan_media_roots_missing"]
    if int(scan_report.get("total_series") or 0) <= 0:
        return ["scan_returned_no_series_check_media_roots"]
    if len(scan_report.get("candidates", [])) <= 0:
        return ["scan_returned_no_candidates_check_filters"]
    return []


def _string_list(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _report_summary(report: JsonDict) -> JsonDict:
    keys = [
        "mode",
        "planned_items",
        "total_items",
        "available_items",
        "ready_items",
        "approval_required_items",
        "executable_preview_items",
        "executed_preview_items",
        "ready_for_receive_items",
        "blocked_preview_items",
        "received_items",
        "organized_items",
        "dry_run_items",
        "staging_preflight_items",
        "failed_items",
        "finalize_ready_items",
        "processed_items",
        "skipped_items",
        "ok",
    ]
    summary = {key: report.get(key) for key in keys if key in report}
    for key in ("bucket_counts", "status_counts", "decision_counts"):
        if isinstance(report.get(key), dict):
            summary[key] = report[key]
    return summary


def _batch_plan_summary(report: JsonDict) -> JsonDict:
    summary = _report_summary(report)
    summary.update(
        {
            "auto_transfer_items": len(report.get("auto_transfer_items", [])) if isinstance(report.get("auto_transfer_items"), list) else 0,
            "auto_validation_cleanup_items": len(report.get("auto_validation_cleanup_items", []))
            if isinstance(report.get("auto_validation_cleanup_items"), list)
            else 0,
            "manual_review_items": len(report.get("manual_review_items", [])) if isinstance(report.get("manual_review_items"), list) else 0,
        }
    )
    return summary


def _phase_summary_text(phase: JsonDict) -> str:
    summary = phase.get("summary") if isinstance(phase.get("summary"), dict) else {}
    if not summary:
        return str(phase.get("reason") or "")
    parts = []
    for key, value in summary.items():
        if isinstance(value, (dict, list)):
            continue
        parts.append(f"{key}={value}")
    return ", ".join(parts)


def _summary_value(report: JsonDict, section: str, key: str) -> object:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    target = summary.get(section) if isinstance(summary.get(section), dict) else {}
    return target.get(key, 0) if isinstance(target, dict) else 0


def _phase_name(stem: str) -> str:
    return re.sub(r"^\d+-", "", stem)


def _merged_items(plans: Sequence[JsonDict]) -> List[JsonDict]:
    return [item for plan in plans for item in plan.get("items", []) if isinstance(item, dict)]


def _write_json(path: Path, report: JsonDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
