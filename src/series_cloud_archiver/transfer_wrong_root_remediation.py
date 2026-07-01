from __future__ import annotations

import csv
import io
import json
import os
import re
import shlex
import subprocess
import time
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple


JsonDict = Dict[str, object]
CommandRunner = Callable[..., object]

WRONG_ROOT_REPAIR_COMMANDS = {
    "mv3-repair-wrong-root-direct-season-pair",
    "strm-root-relocate",
}

APPROVAL_FLAGS = {
    "mv3-repair-wrong-root-direct-season-pair": "--approve-repair",
    "strm-root-relocate": "--approve-move",
}


def build_transfer_wrong_root_repair_plan(
    review_report: JsonDict,
    *,
    env_file: str = "",
    cloud_media_storage: str = "115-default",
    wrong_cloud_category: str = "/已整理/未识别",
    correct_cloud_category: str = "/已整理/series",
    wrong_strm_segment: str = "未识别",
    correct_strm_segment: str = "series",
    timeout: int = 120,
    limit: int = 1000,
) -> JsonDict:
    rows: List[JsonDict] = []
    skipped_rows = 0
    for item in review_report.get("items", []) if isinstance(review_report.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        row = _plan_item_from_review(
            item,
            env_file=env_file,
            cloud_media_storage=cloud_media_storage,
            wrong_cloud_category=wrong_cloud_category,
            correct_cloud_category=correct_cloud_category,
            wrong_strm_segment=wrong_strm_segment,
            correct_strm_segment=correct_strm_segment,
            timeout=timeout,
            limit=limit,
        )
        if row:
            rows.append(row)
        else:
            skipped_rows += 1

    status_counts = Counter(str(row.get("status") or "") for row in rows)
    return {
        "mode": "readonly-mv3-transfer-wrong-root-repair-plan",
        "source_mode": str(review_report.get("mode") or ""),
        "ok": True,
        "planned_items": len(rows),
        "ready_items": sum(1 for row in rows if row.get("status") == "ready_for_wrong_root_repair"),
        "manual_review_items": sum(1 for row in rows if row.get("status") != "ready_for_wrong_root_repair"),
        "skipped_non_matching_items": skipped_rows,
        "status_counts": dict(sorted(status_counts.items())),
        "items": rows,
        "settings": {
            "env_file": env_file,
            "cloud_media_storage": cloud_media_storage,
            "wrong_cloud_category": _normalize_cloud_path(wrong_cloud_category),
            "correct_cloud_category": _normalize_cloud_path(correct_cloud_category),
            "wrong_strm_segment": wrong_strm_segment,
            "correct_strm_segment": correct_strm_segment,
            "timeout": timeout,
            "limit": limit,
        },
        "safety": (
            "readonly plan only; it consumes a batch-review report and emits dry-run commands for rows already "
            "blocked as manual_review_transfer_failed with strm_written_to_unrecognized_root. It does not move "
            "cloud media, write STRM, scrape metadata, refresh Emby, touch qBittorrent, or delete hlink/source files."
        ),
    }


def render_transfer_wrong_root_repair_plan(report: JsonDict, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    if output_format == "csv":
        return _render_plan_csv(report)
    lines = [
        "# MV3 Transfer Wrong-Root Repair Plan",
        "",
        f"- Ready: `{report.get('ready_items', 0)}` / `{report.get('planned_items', 0)}`",
        f"- Manual review: `{report.get('manual_review_items', 0)}`",
        f"- Status counts: `{report.get('status_counts', {})}`",
        "- Safety: plan only; generated commands omit approval flags.",
        "",
        "| Status | TMDB | S | Title | Wrong Cloud | Correct Cloud | Source STRM | Target STRM | Blockers |",
        "| --- | ---: | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for item in report.get("items", []) if isinstance(report.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {status} | {tmdbid} | {season} | {title} | {wrong} | {correct} | {source} | {target} | {blockers} |".format(
                status=_escape_cell(str(item.get("status") or "")),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                title=_escape_cell(str(item.get("title") or "")),
                wrong=_escape_cell(str(item.get("wrong_cloud_season_path") or "")),
                correct=_escape_cell(str(item.get("correct_cloud_season_path") or "")),
                source=_escape_cell(str(item.get("source_strm_season_root") or "")),
                target=_escape_cell(str(item.get("target_strm_season_root") or "")),
                blockers=_escape_cell("; ".join(_strings(item.get("blockers")))),
            )
        )
    return "\n".join(lines)


def run_transfer_wrong_root_repair_plan(
    plan_report: JsonDict,
    *,
    output_dir: str,
    titles: Optional[Sequence[str]] = None,
    limit: int = 0,
    execute_dry_run: bool = False,
    execute_approved: bool = False,
    cwd: str = "",
    process_timeout: int = 600,
    command_runner: Optional[CommandRunner] = None,
) -> JsonDict:
    output_base = Path(output_dir)
    output_base.mkdir(parents=True, exist_ok=True)
    title_filters = [str(item) for item in (titles or []) if str(item)]
    runner = command_runner or subprocess.run
    rows: List[JsonDict] = []
    selected_items = 0
    if execute_dry_run and execute_approved:
        return {
            "mode": "mv3-transfer-wrong-root-repair-run",
            "source_mode": str(plan_report.get("mode") or ""),
            "ok": False,
            "execute_dry_run": execute_dry_run,
            "execute_approved": execute_approved,
            "selected_items": 0,
            "planned_commands": 0,
            "executed_commands": 0,
            "runner_error_count": 0,
            "unsafe_blocked_count": 1,
            "status_counts": {"unsafe_blocked": 1},
            "items": [
                {
                    "status": "unsafe_blocked",
                    "stage": "mode_selection",
                    "safety_blockers": ["execute_dry_run_and_execute_approved_are_mutually_exclusive"],
                }
            ],
            "output_dir": str(output_base),
        }

    for item_index, item in enumerate(plan_report.get("items", []) if isinstance(plan_report.get("items"), list) else []):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        review_title = str(item.get("review_title") or "")
        if title_filters and not any(token in title or token in review_title for token in title_filters):
            continue
        if item.get("status") != "ready_for_wrong_root_repair":
            rows.append(_skip_item_row(item, item_index, "item_not_ready_for_wrong_root_repair"))
            continue
        if limit > 0 and selected_items >= limit:
            break
        selected_items += 1

        if execute_approved:
            rows.extend(
                _run_approved_item(
                    item,
                    item_index=item_index,
                    output_base=output_base,
                    cwd=cwd,
                    process_timeout=process_timeout,
                    runner=runner,
                )
            )
            continue

        commands = _commands_for_item(item)
        for command_index, command_item in enumerate(commands):
            if not isinstance(command_item, dict):
                continue
            stage = str(command_item.get("stage") or "")
            if execute_dry_run and stage != "cloud_wrong_root_pair_dry_run":
                rows.append(_deferred_row(item, command_item, item_index, command_index, output_base))
                continue
            rows.append(
                _run_wrong_root_command(
                    item,
                    command_item,
                    item_index=item_index,
                    command_index=command_index,
                    output_base=output_base,
                    execute=execute_dry_run,
                    approved=False,
                    cwd=cwd,
                    process_timeout=process_timeout,
                    runner=runner,
                )
            )

    status_counts = Counter(str(row.get("status") or "") for row in rows)
    stage_counts = Counter(str(row.get("stage") or "") for row in rows)
    diagnostic_counts = Counter(str(row.get("diagnostic_ok")) for row in rows if row.get("executed"))
    runner_error_count = sum(1 for row in rows if bool(row.get("runner_error")))
    unsafe_blocked_count = sum(1 for row in rows if row.get("status") == "unsafe_blocked")
    failed_count = sum(1 for row in rows if row.get("status") in {"diagnostic_failed", "timeout", "runner_error", "dependency_skipped"})
    return {
        "mode": "mv3-transfer-wrong-root-repair-run",
        "source_mode": str(plan_report.get("mode") or ""),
        "ok": runner_error_count == 0 and unsafe_blocked_count == 0 and failed_count == 0,
        "execute_dry_run": execute_dry_run,
        "execute_approved": execute_approved,
        "selected_items": selected_items,
        "planned_commands": len(rows),
        "executed_commands": sum(1 for row in rows if bool(row.get("executed"))),
        "runner_error_count": runner_error_count,
        "unsafe_blocked_count": unsafe_blocked_count,
        "failed_count": failed_count,
        "status_counts": dict(sorted(status_counts.items())),
        "stage_counts": dict(sorted(stage_counts.items())),
        "diagnostic_ok_counts": dict(sorted(diagnostic_counts.items())),
        "output_dir": str(output_base),
        "items": rows,
        "settings": {
            "titles": title_filters,
            "limit": limit,
            "cwd": cwd,
            "process_timeout": process_timeout,
        },
        "safety": (
            "runner is allowlisted to mv3-repair-wrong-root-direct-season-pair and strm-root-relocate only. "
            "Default mode executes nothing; --execute-dry-run runs only the cloud/STRM rewrite dry-run. "
            "--execute-approved first approves the cloud move plus STRM target rewrite, then performs a post-repair "
            "STRM relocate dry-run before moving the STRM-side folder. It never scrapes, refreshes Emby, touches "
            "qBittorrent, or deletes hlink/source files."
        ),
    }


def render_transfer_wrong_root_repair_run(report: JsonDict, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    if output_format == "csv":
        return _render_run_csv(report)
    lines = [
        "# MV3 Transfer Wrong-Root Repair Run",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Execute dry-run: `{bool(report.get('execute_dry_run'))}`",
        f"- Execute approved: `{bool(report.get('execute_approved'))}`",
        f"- Selected items: `{report.get('selected_items', 0)}`",
        f"- Planned commands: `{report.get('planned_commands', 0)}`",
        f"- Executed commands: `{report.get('executed_commands', 0)}`",
        f"- Status counts: `{report.get('status_counts', {})}`",
        "",
        "| Status | Diagnostic OK | Stage | TMDB | S | Title | Output | Blockers |",
        "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
    ]
    for item in report.get("items", []) if isinstance(report.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {status} | {diagnostic} | {stage} | {tmdbid} | {season} | {title} | {output} | {blockers} |".format(
                status=_escape_cell(str(item.get("status") or "")),
                diagnostic=_escape_cell(str(item.get("diagnostic_ok") if "diagnostic_ok" in item else "")),
                stage=_escape_cell(str(item.get("stage") or "")),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                title=_escape_cell(str(item.get("title") or "")),
                output=_escape_cell(str(item.get("output") or "")),
                blockers=_escape_cell("; ".join(_strings(item.get("diagnostic_blockers")) + _strings(item.get("safety_blockers")))),
            )
        )
    return "\n".join(lines)


def _plan_item_from_review(
    item: JsonDict,
    *,
    env_file: str,
    cloud_media_storage: str,
    wrong_cloud_category: str,
    correct_cloud_category: str,
    wrong_strm_segment: str,
    correct_strm_segment: str,
    timeout: int,
    limit: int,
) -> Optional[JsonDict]:
    decision = str(item.get("decision") or "")
    text = " ; ".join(
        str(item.get(key) or "")
        for key in ("reason_summary", "review_reasons", "blockers", "transfer_blockers")
    )
    if decision != "manual_review_transfer_failed" or "strm_written_to_unrecognized_root" not in text:
        return None

    review_title = str(item.get("title") or "")
    tmdbid = _int_value(item.get("tmdbid") or item.get("tmdb_id"))
    season = _int_value(item.get("season") or item.get("season_number"))
    expected_count = _int_value(item.get("expected_episode_count"))
    expected_min, expected_max = _episode_range(item, expected_count)
    wrong_cloud_season = _normalize_cloud_path(str(item.get("cloud_media_path") or ""))
    source_strm_season = _normalize_host_path(str(item.get("strm_root") or ""))
    wrong_cloud_title = _cloud_title_path(wrong_cloud_season)
    correct_cloud_title = _replace_cloud_category(wrong_cloud_title, wrong_cloud_category, correct_cloud_category)
    correct_cloud_season = _cloud_join(correct_cloud_title, f"Season {season:02d}") if season > 0 and correct_cloud_title else ""
    source_strm_title = _season_parent(source_strm_season)
    target_strm_season_raw = _replace_strm_segment(source_strm_season, wrong_strm_segment, correct_strm_segment)
    target_strm_title = _season_parent(target_strm_season_raw)
    target_strm_season = _host_join(target_strm_title, f"Season {season:02d}") if target_strm_title and season > 0 else target_strm_season_raw
    title = PurePosixPath(correct_cloud_title).name if correct_cloud_title else _strip_report_season(review_title)
    wrong_strm_title = _season_parent(source_strm_season)
    blockers: List[str] = []

    if tmdbid <= 0:
        blockers.append("tmdbid_required")
    if season <= 0:
        blockers.append("season_required")
    if expected_count <= 0:
        blockers.append("expected_episode_count_required")
    if expected_min <= 0 or expected_max <= 0 or expected_min > expected_max:
        blockers.append("expected_episode_range_required")
    if not wrong_cloud_season:
        blockers.append("wrong_cloud_season_path_required")
    if wrong_cloud_season and not _is_season_path(wrong_cloud_season):
        blockers.append("cloud_media_path_must_be_season_path")
    if not source_strm_season:
        blockers.append("source_strm_season_root_required")
    if source_strm_season and not _is_season_path(source_strm_season):
        blockers.append("strm_root_must_be_season_path")
    if not _path_has_prefix(wrong_cloud_title, wrong_cloud_category):
        blockers.append("wrong_cloud_root_not_under_unrecognized_category")
    if not correct_cloud_title or correct_cloud_title == wrong_cloud_title:
        blockers.append("correct_cloud_root_not_derived")
    if not _path_has_segment(source_strm_season, wrong_strm_segment):
        blockers.append("source_strm_root_not_under_unrecognized_segment")
    if not target_strm_season or target_strm_season == source_strm_season:
        blockers.append("target_strm_root_not_derived")
    if not title or title in {wrong_strm_segment, correct_strm_segment}:
        blockers.append("title_required")
    if wrong_strm_title and target_strm_title and wrong_strm_title == target_strm_title:
        blockers.append("strm_title_roots_must_differ")

    status = "ready_for_wrong_root_repair" if not blockers else "manual_review_required"
    row: JsonDict = {
        "status": status,
        "next_action": (
            "先跑 runner 的 --execute-dry-run 固化错根修复预检；通过后再小批量 --execute-approved"
            if status == "ready_for_wrong_root_repair"
            else "人工复核路径、集数和错根证据；不能自动移动云盘或 STRM"
        ),
        "title": title,
        "review_title": review_title,
        "tmdbid": tmdbid,
        "season": season,
        "expected_episode_count": expected_count,
        "expected_episode_min": expected_min,
        "expected_episode_max": expected_max,
        "wrong_cloud_title_path": wrong_cloud_title,
        "wrong_cloud_season_path": wrong_cloud_season,
        "correct_cloud_title_path": correct_cloud_title,
        "correct_cloud_season_path": correct_cloud_season,
        "source_strm_title_root": source_strm_title,
        "source_strm_season_root": source_strm_season,
        "target_strm_title_root": target_strm_title,
        "target_strm_season_root": target_strm_season,
        "required_target_prefix": correct_cloud_season,
        "forbidden_target_prefixes": [wrong_cloud_season],
        "source_paths": _split_paths_cell(item.get("source_paths")),
        "blockers": sorted(set(blockers)),
        "review_reason_summary": str(item.get("reason_summary") or ""),
        "commands": [],
    }
    if status == "ready_for_wrong_root_repair":
        row["commands"] = _build_commands(
            title=title,
            tmdbid=tmdbid,
            season=season,
            env_file=env_file,
            storage=cloud_media_storage,
            wrong_cloud_title=wrong_cloud_title,
            correct_cloud_title=correct_cloud_title,
            source_strm_title=source_strm_title,
            source_strm_season=source_strm_season,
            target_strm_season=target_strm_season,
            correct_cloud_season=correct_cloud_season,
            wrong_cloud_season=wrong_cloud_season,
            expected_count=expected_count,
            expected_min=expected_min,
            expected_max=expected_max,
            timeout=timeout,
            limit=limit,
        )
    return row


def _build_commands(
    *,
    title: str,
    tmdbid: int,
    season: int,
    env_file: str,
    storage: str,
    wrong_cloud_title: str,
    correct_cloud_title: str,
    source_strm_title: str,
    source_strm_season: str,
    target_strm_season: str,
    correct_cloud_season: str,
    wrong_cloud_season: str,
    expected_count: int,
    expected_min: int,
    expected_max: int,
    timeout: int,
    limit: int,
) -> List[JsonDict]:
    env = f"--env-file {_q(env_file)} " if env_file else ""
    prefix = _safe_prefix(title, tmdbid, season)
    pair = (
        f"PYTHONPATH=src python3 -m series_cloud_archiver mv3-repair-wrong-root-direct-season-pair {env}"
        f"--wrong-root {_q(wrong_cloud_title)} --correct-root {_q(correct_cloud_title)} "
        f"--strm-root {_q(source_strm_title)} --season {season} --storage {_q(storage)} "
        f"--title-filter {_q(title)} --expected-episode-count {expected_count} "
        f"--expected-episode-min {expected_min} --expected-episode-max {expected_max} "
        f"--expected-rewrite-count {expected_count} --limit {limit} --timeout {timeout} "
        f"--format json --output {_q(prefix + '-cloud-pair-dry-run.json')}"
    )
    relocate = (
        "PYTHONPATH=src python3 -m series_cloud_archiver strm-root-relocate "
        f"--title {_q(title)} --source-root {_q(source_strm_season)} --target-root {_q(target_strm_season)} "
        f"--expected-episode-count {expected_count} --expected-episode-min {expected_min} --expected-episode-max {expected_max} "
        f"--required-target-prefix {_q(correct_cloud_season)} --forbidden-target-prefix {_q(wrong_cloud_season)} "
        f"--format json --output {_q(prefix + '-strm-relocate-dry-run.json')}"
    )
    return [
        {
            "stage": "cloud_wrong_root_pair_dry_run",
            "command": pair,
            "approved_stage": "cloud_wrong_root_pair_approved",
            "approval_flag": "--approve-repair",
        },
        {
            "stage": "strm_root_relocate_after_pair",
            "command": relocate,
            "approved_stage": "strm_root_relocate_approved",
            "approval_flag": "--approve-move",
            "depends_on": "cloud_wrong_root_pair_approved",
        },
    ]


def _commands_for_item(item: JsonDict) -> List[JsonDict]:
    return [command for command in item.get("commands", []) if isinstance(command, dict)] if isinstance(item.get("commands"), list) else []


def _run_approved_item(
    item: JsonDict,
    *,
    item_index: int,
    output_base: Path,
    cwd: str,
    process_timeout: int,
    runner: CommandRunner,
) -> List[JsonDict]:
    commands = _commands_for_item(item)
    if len(commands) < 2:
        return [_skip_item_row(item, item_index, "approved_run_requires_pair_and_relocate_commands")]
    pair = dict(commands[0])
    pair["stage"] = str(pair.get("approved_stage") or "cloud_wrong_root_pair_approved")
    pair["command"] = _add_approval_flag(str(pair.get("command") or ""), "mv3-repair-wrong-root-direct-season-pair")
    pair_row = _run_wrong_root_command(
        item,
        pair,
        item_index=item_index,
        command_index=0,
        output_base=output_base,
        execute=True,
        approved=True,
        cwd=cwd,
        process_timeout=process_timeout,
        runner=runner,
    )
    rows = [pair_row]
    if not _row_success(pair_row, require_write=True):
        rows.append(_dependency_skipped_row(item, commands[1], item_index, 1, output_base, "cloud_wrong_root_pair_approved_failed"))
        return rows

    relocate_dry = dict(commands[1])
    relocate_dry["stage"] = "strm_root_relocate_post_pair_dry_run"
    relocate_dry_row = _run_wrong_root_command(
        item,
        relocate_dry,
        item_index=item_index,
        command_index=1,
        output_base=output_base,
        execute=True,
        approved=False,
        cwd=cwd,
        process_timeout=process_timeout,
        runner=runner,
    )
    rows.append(relocate_dry_row)
    if not _row_success(relocate_dry_row):
        rows.append(_dependency_skipped_row(item, commands[1], item_index, 2, output_base, "strm_root_relocate_post_pair_dry_run_failed"))
        return rows

    relocate = dict(commands[1])
    relocate["stage"] = str(relocate.get("approved_stage") or "strm_root_relocate_approved")
    relocate["command"] = _add_approval_flag(str(relocate.get("command") or ""), "strm-root-relocate")
    rows.append(
        _run_wrong_root_command(
            item,
            relocate,
            item_index=item_index,
            command_index=2,
            output_base=output_base,
            execute=True,
            approved=True,
            cwd=cwd,
            process_timeout=process_timeout,
            runner=runner,
        )
    )
    return rows


def _run_wrong_root_command(
    plan_item: JsonDict,
    command_item: JsonDict,
    *,
    item_index: int,
    command_index: int,
    output_base: Path,
    execute: bool,
    approved: bool,
    cwd: str,
    process_timeout: int,
    runner: CommandRunner,
) -> JsonDict:
    title = str(plan_item.get("title") or "")
    tmdbid = int(plan_item.get("tmdbid") or 0)
    season = int(plan_item.get("season") or 0)
    stage = str(command_item.get("stage") or "")
    raw_command = str(command_item.get("command") or "")
    output_path = output_base / _command_output_name(title, tmdbid, season, stage, command_index)
    row: JsonDict = {
        "status": "planned",
        "executed": False,
        "stage": stage,
        "title": title,
        "tmdbid": tmdbid,
        "season": season,
        "item_index": item_index,
        "command_index": command_index,
        "output": str(output_path),
        "original_command": raw_command,
        "command": "",
        "approved": approved,
        "returncode": None,
        "diagnostic_ok": None,
        "diagnostic_blockers": [],
        "diagnostic_warnings": [],
        "runner_error": "",
        "safety_blockers": [],
    }
    safety = _safe_command_tokens(raw_command, output_path, approved=approved)
    if safety.get("skip_reason"):
        row["status"] = "skipped"
        row["skip_reason"] = str(safety.get("skip_reason") or "")
        row["command"] = safety.get("command", "")
        return row
    if safety.get("blockers"):
        row["status"] = "unsafe_blocked"
        row["safety_blockers"] = safety.get("blockers", [])
        row["command"] = safety.get("command", "")
        return row
    argv = [str(item) for item in safety.get("argv", []) if str(item)]
    row["command"] = safety.get("command", "")
    if not execute:
        return row

    started = time.time()
    try:
        completed = runner(
            argv,
            cwd=cwd or None,
            text=True,
            capture_output=True,
            timeout=process_timeout,
            env={**os.environ, "PYTHONPATH": _py_path(cwd)},
        )
    except subprocess.TimeoutExpired as exc:
        row["status"] = "timeout"
        row["executed"] = True
        row["runner_error"] = f"timeout_after_{process_timeout}s"
        row["stdout"] = _truncate_output(str(getattr(exc, "stdout", "") or ""))
        row["stderr"] = _truncate_output(str(getattr(exc, "stderr", "") or ""))
        row["duration_seconds"] = round(time.time() - started, 3)
        return row
    except Exception as exc:  # pragma: no cover - exercised with injected runners.
        row["status"] = "runner_error"
        row["executed"] = True
        row["runner_error"] = f"{type(exc).__name__}: {exc}"
        row["duration_seconds"] = round(time.time() - started, 3)
        return row

    row["executed"] = True
    row["returncode"] = int(getattr(completed, "returncode", 0))
    row["stdout"] = _truncate_output(str(getattr(completed, "stdout", "") or ""))
    row["stderr"] = _truncate_output(str(getattr(completed, "stderr", "") or ""))
    row["duration_seconds"] = round(time.time() - started, 3)
    diagnostic = _load_command_output(output_path)
    if diagnostic:
        row["diagnostic_ok"] = bool(diagnostic.get("ok"))
        row["diagnostic_blockers"] = _strings(diagnostic.get("blockers"))
        row["diagnostic_warnings"] = _strings(diagnostic.get("warnings"))
        row["diagnostic_mode"] = str(diagnostic.get("mode") or "")
        row["diagnostic_summary"] = _diagnostic_summary(diagnostic)
    row["status"] = "executed" if row["returncode"] == 0 else "diagnostic_failed"
    return row


def _safe_command_tokens(command: str, output_path: Path, *, approved: bool) -> JsonDict:
    blockers: List[str] = []
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return {"blockers": [f"command_parse_failed:{exc}"], "argv": [], "command": command}
    if len(tokens) < 5 or tokens[:3] != ["PYTHONPATH=src", "python3", "-m"]:
        return {"skip_reason": "non_executable_note", "argv": tokens, "command": command}
    if tokens[3] != "series_cloud_archiver":
        blockers.append("unsupported_module")
    subcommand = tokens[4] if len(tokens) > 4 else ""
    if subcommand not in WRONG_ROOT_REPAIR_COMMANDS:
        blockers.append(f"unsupported_subcommand:{subcommand}")
    approval_tokens = [token for token in tokens if token.startswith("--approve-")]
    expected_approval = APPROVAL_FLAGS.get(subcommand, "")
    if approved:
        for token in approval_tokens:
            if token != expected_approval:
                blockers.append(f"unexpected_approval_flag:{token}")
        if expected_approval and expected_approval not in approval_tokens:
            blockers.append(f"approval_flag_required:{expected_approval}")
    elif approval_tokens:
        blockers.append("approval_flag_forbidden")
    if "--output" in tokens:
        index = tokens.index("--output")
        if index + 1 >= len(tokens):
            blockers.append("output_value_required")
        else:
            tokens[index + 1] = str(output_path)
    else:
        tokens.extend(["--output", str(output_path)])
    if "--format" in tokens:
        index = tokens.index("--format")
        if index + 1 < len(tokens):
            tokens[index + 1] = "json"
        else:
            blockers.append("format_value_required")
    else:
        tokens.extend(["--format", "json"])
    argv = ["python3", "-m", "series_cloud_archiver"] + tokens[4:]
    return {"blockers": sorted(set(blockers)), "argv": argv, "command": shlex.join(argv)}


def _row_success(row: JsonDict, *, require_write: bool = False) -> bool:
    if row.get("status") != "executed" or row.get("returncode") != 0 or row.get("diagnostic_ok") is not True:
        return False
    if not require_write:
        return True
    summary = row.get("diagnostic_summary") if isinstance(row.get("diagnostic_summary"), dict) else {}
    return bool(summary.get("write_executed") or summary.get("move_executed"))


def _skip_item_row(item: JsonDict, item_index: int, reason: str) -> JsonDict:
    return {
        "status": "skipped",
        "executed": False,
        "stage": "item_selection",
        "title": str(item.get("title") or ""),
        "tmdbid": int(item.get("tmdbid") or 0),
        "season": int(item.get("season") or 0),
        "item_index": item_index,
        "command_index": -1,
        "skip_reason": reason,
    }


def _deferred_row(
    item: JsonDict,
    command_item: JsonDict,
    item_index: int,
    command_index: int,
    output_base: Path,
) -> JsonDict:
    title = str(item.get("title") or "")
    tmdbid = int(item.get("tmdbid") or 0)
    season = int(item.get("season") or 0)
    stage = str(command_item.get("stage") or "")
    return {
        "status": "deferred",
        "executed": False,
        "stage": stage,
        "title": title,
        "tmdbid": tmdbid,
        "season": season,
        "item_index": item_index,
        "command_index": command_index,
        "output": str(output_base / _command_output_name(title, tmdbid, season, stage, command_index)),
        "skip_reason": "requires_successful_cloud_wrong_root_pair_execute_first",
        "command": str(command_item.get("command") or ""),
    }


def _dependency_skipped_row(
    item: JsonDict,
    command_item: JsonDict,
    item_index: int,
    command_index: int,
    output_base: Path,
    reason: str,
) -> JsonDict:
    row = _deferred_row(item, command_item, item_index, command_index, output_base)
    row["status"] = "dependency_skipped"
    row["skip_reason"] = reason
    return row


def _add_approval_flag(command: str, subcommand: str) -> str:
    flag = APPROVAL_FLAGS[subcommand]
    tokens = shlex.split(command)
    if flag not in tokens:
        tokens.append(flag)
    return shlex.join(tokens)


def _diagnostic_summary(report: JsonDict) -> JsonDict:
    summary: JsonDict = {
        "write_executed": bool(report.get("write_executed")),
        "move_executed": bool(report.get("move_executed")),
        "dry_run": bool(report.get("dry_run")),
    }
    precheck = report.get("precheck") if isinstance(report.get("precheck"), dict) else {}
    post = report.get("post_verify") if isinstance(report.get("post_verify"), dict) else {}
    if isinstance(precheck.get("strm"), dict):
        summary["pre_strm_wrong_target_count"] = precheck["strm"].get("wrong_target_count")
        summary["pre_strm_correct_target_count"] = precheck["strm"].get("correct_target_count")
    if isinstance(post.get("strm"), dict):
        summary["post_strm_wrong_target_count"] = post["strm"].get("wrong_target_count")
        summary["post_strm_correct_target_count"] = post["strm"].get("correct_target_count")
    if isinstance(precheck.get("source"), dict):
        summary["source_strm_file_count"] = precheck["source"].get("file_count")
    if isinstance(post.get("target"), dict):
        target = post["target"]
        summary["target_strm_file_count"] = target.get("file_count")
        verify = target.get("verify") if isinstance(target.get("verify"), dict) else {}
        summary["target_verify_ok"] = verify.get("ok")
    return summary


def _render_plan_csv(report: JsonDict) -> str:
    output = io.StringIO()
    fieldnames = [
        "status",
        "title",
        "review_title",
        "tmdbid",
        "season",
        "expected_episode_count",
        "wrong_cloud_season_path",
        "correct_cloud_season_path",
        "source_strm_season_root",
        "target_strm_season_root",
        "blockers",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for item in report.get("items", []) if isinstance(report.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        writer.writerow({key: _csv_value(item.get(key)) for key in fieldnames})
    return output.getvalue().strip()


def _render_run_csv(report: JsonDict) -> str:
    output = io.StringIO()
    fieldnames = [
        "status",
        "diagnostic_ok",
        "stage",
        "title",
        "tmdbid",
        "season",
        "output",
        "returncode",
        "diagnostic_blockers",
        "safety_blockers",
        "runner_error",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for item in report.get("items", []) if isinstance(report.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        writer.writerow({key: _csv_value(item.get(key)) for key in fieldnames})
    return output.getvalue().strip()


def _csv_value(value: object) -> object:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value if value is not None else ""


def _load_command_output(path: Path) -> JsonDict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _command_output_name(title: str, tmdbid: int, season: int, stage: str, command_index: int) -> str:
    prefix = _safe_prefix(title, tmdbid, season)
    safe_stage = re.sub(r"[^0-9A-Za-z_-]+", "-", stage).strip("-") or f"command-{command_index + 1:02d}"
    return f"{prefix}-{command_index + 1:02d}-{safe_stage}.json"


def _safe_prefix(title: str, tmdbid: int, season: int) -> str:
    slug = re.sub(r"[^0-9A-Za-z一-龥]+", "-", f"{title}-{tmdbid}-s{season:02d}").strip("-")
    return slug[-120:] or "wrong-root-repair"


def _py_path(cwd: str) -> str:
    return str(Path(cwd or ".") / "src") if cwd else "src"


def _truncate_output(value: str, limit: int = 4000) -> str:
    return value if len(value) <= limit else value[:limit] + "...[TRUNCATED]"


def _normalize_cloud_path(path: str) -> str:
    segments = [segment for segment in str(path or "").strip().strip("/").split("/") if segment]
    return "/" + "/".join(segments) if segments else ""


def _normalize_host_path(path: str) -> str:
    value = str(path or "").strip().rstrip("/")
    return re.sub(r"/+", "/", value)


def _cloud_join(parent: str, name: str) -> str:
    parent_path = _normalize_cloud_path(parent)
    clean_name = str(name or "").strip().strip("/")
    if not clean_name:
        return parent_path
    return f"{parent_path}/{clean_name}" if parent_path else f"/{clean_name}"


def _cloud_title_path(path: str) -> str:
    clean = _normalize_cloud_path(path)
    return clean.rsplit("/", 1)[0] if _is_season_path(clean) else clean


def _season_parent(path: str) -> str:
    clean = _normalize_host_path(path)
    return clean.rsplit("/", 1)[0] if _is_season_path(clean) else clean


def _host_join(parent: str, name: str) -> str:
    clean_parent = _normalize_host_path(parent)
    clean_name = str(name or "").strip().strip("/")
    if not clean_name:
        return clean_parent
    return f"{clean_parent}/{clean_name}" if clean_parent else f"/{clean_name}"


def _is_season_path(path: str) -> bool:
    tail = str(path or "").rstrip("/").rsplit("/", 1)[-1]
    return bool(re.match(r"(?i)^(?:Season\s*0?\d+|S0?\d+|第\s*\d+\s*季)$", tail))


def _replace_cloud_category(path: str, wrong_category: str, correct_category: str) -> str:
    normalized_path = _normalize_cloud_path(path)
    wrong = _normalize_cloud_path(wrong_category).rstrip("/")
    correct = _normalize_cloud_path(correct_category).rstrip("/")
    if not normalized_path or not wrong or not correct:
        return ""
    if normalized_path == wrong:
        return correct
    prefix = wrong + "/"
    if normalized_path.startswith(prefix):
        return correct + "/" + normalized_path[len(prefix) :]
    return ""


def _replace_strm_segment(path: str, wrong_segment: str, correct_segment: str) -> str:
    clean = _normalize_host_path(path)
    parts = clean.split("/")
    replaced = False
    for index, part in enumerate(parts):
        if part == wrong_segment:
            parts[index] = correct_segment
            replaced = True
            break
    return "/".join(parts) if replaced else ""


def _path_has_prefix(path: str, prefix: str) -> bool:
    normalized_path = _normalize_cloud_path(path)
    normalized_prefix = _normalize_cloud_path(prefix)
    return bool(normalized_path and normalized_prefix and (normalized_path == normalized_prefix or normalized_path.startswith(normalized_prefix.rstrip("/") + "/")))


def _path_has_segment(path: str, segment: str) -> bool:
    return str(segment or "") in [part for part in _normalize_host_path(path).split("/") if part]


def _episode_range(item: JsonDict, expected_count: int) -> Tuple[int, int]:
    episodes = _episode_numbers(item.get("expected_episodes"))
    if episodes:
        return min(episodes), max(episodes)
    return (1 if expected_count else 0, expected_count)


def _episode_numbers(value: object) -> List[int]:
    if isinstance(value, list):
        return sorted({_int_value(item) for item in value if _int_value(item) > 0})
    if not isinstance(value, str):
        return []
    text = value.strip()
    range_match = re.search(r"(\d{1,3})\s*-\s*(\d{1,3})", text)
    if range_match:
        start, end = int(range_match.group(1)), int(range_match.group(2))
        if start <= end:
            return list(range(start, end + 1))
    numbers = [int(match) for match in re.findall(r"\b(\d{1,3})\b", text)]
    count_match = re.search(r"\((\d{1,3})\s*集\)", text)
    if count_match and len(numbers) == 2 and numbers[1] == int(count_match.group(1)):
        return [numbers[0]]
    return sorted(set(numbers))


def _split_paths_cell(value: object) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        return [part.strip() for part in value.split("|") if part.strip()]
    return []


def _strip_report_season(title: str) -> str:
    return re.sub(r"\s+Season\s+0?\d+\s*$", "", str(title or ""), flags=re.IGNORECASE).strip()


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _strings(value: object) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [value]
    return []


def _q(value: object) -> str:
    return shlex.quote(str(value))


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
