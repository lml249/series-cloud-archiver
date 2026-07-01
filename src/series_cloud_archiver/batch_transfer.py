from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .mv3 import (
    browse_mv3_cloud_folder,
    execute_mv3_organize_transfer_from_browse_report,
    receive_mv3_share,
)


TransferFunc = Callable[..., Dict[str, object]]


@dataclass
class BatchTransferActions:
    receive_share: TransferFunc = receive_mv3_share
    browse_cloud: TransferFunc = browse_mv3_cloud_folder
    organize_transfer: TransferFunc = execute_mv3_organize_transfer_from_browse_report


def run_batch_transfer(
    receive_plan: Dict[str, object],
    *,
    output_dir: str,
    config: object,
    limit: int = 0,
    title_filters: Optional[Sequence[str]] = None,
    approve_receive: bool = False,
    approve_transfer: bool = False,
    target_path: str = "/未整理",
    organize_target_dir: str = "/已整理",
    strm_dir: str = "/strm",
    storage: str = "115-default",
    timeout: int = 60,
    transfer_timeout: int = 180,
    host_strm_root: str = "",
    actions: Optional[BatchTransferActions] = None,
) -> Dict[str, object]:
    actions = actions or BatchTransferActions()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    filters = [str(item) for item in (title_filters or []) if str(item)]
    rows = _transfer_candidates(receive_plan, filters)
    if limit > 0:
        rows = rows[:limit]

    results: List[Dict[str, object]] = []
    for row in rows:
        results.append(
            _run_transfer_item(
                row,
                output_dir=output_path,
                config=config,
                actions=actions,
                approve_receive=approve_receive,
                approve_transfer=approve_transfer,
                target_path=target_path,
                organize_target_dir=organize_target_dir,
                strm_dir=strm_dir,
                storage=storage,
                timeout=timeout,
                transfer_timeout=transfer_timeout,
                host_strm_root=host_strm_root,
            )
        )

    return {
        "mode": "batch-transfer-run",
        "source_mode": receive_plan.get("mode", ""),
        "ok": all(item.get("ok") for item in results) if results else False,
        "planned_items": len(rows),
        "received_items": sum(1 for item in results if item.get("receive_ok")),
        "organized_items": sum(1 for item in results if item.get("organize_ok")),
        "dry_run_items": sum(1 for item in results if item.get("status") == "approval_required"),
        "failed_items": sum(1 for item in results if str(item.get("status") or "").startswith("failed")),
        "settings": {
            "approve_receive": approve_receive,
            "approve_transfer": approve_transfer,
            "target_path": target_path,
            "organize_target_dir": organize_target_dir,
            "strm_dir": strm_dir,
            "storage": storage,
            "limit": limit,
            "host_strm_root": host_strm_root,
            "title_filters": filters,
        },
        "items": results,
        "safety": (
            "batch transfer runner is approval-gated: receive requires approve_receive=True and organize transfer "
            "requires approve_transfer=True. It only receives to the staging root, browses cloud folders, and asks MV3 "
            "to organize videos plus STRM under approved roots. It does not scrape cloud media, refresh Emby, touch "
            "qBittorrent, delete hlinks/source files, or clean local storage."
        ),
    }


def render_batch_transfer_run(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        "# Batch Transfer Run",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Planned: `{report.get('planned_items', 0)}`",
        f"- Received: `{report.get('received_items', 0)}`",
        f"- Organized: `{report.get('organized_items', 0)}`",
        f"- Dry-run approval rows: `{report.get('dry_run_items', 0)}`",
        f"- Failed: `{report.get('failed_items', 0)}`",
        "- Safety: approval-gated receive/organize only; no scrape, Emby refresh, qB action, hlink/source deletion, or local cleanup.",
        "",
        "| Status | Title | TMDB | S | Receive | Browse | Organize | Reason |",
        "| --- | --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {status} | {title} | {tmdbid} | {season} | {receive} | {browse} | {organize} | {reason} |".format(
                status=item.get("status", ""),
                title=_escape_cell(str(item.get("title") or "")),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                receive="ok" if item.get("receive_ok") else "",
                browse="ok" if item.get("browse_ok") else "",
                organize="ok" if item.get("organize_ok") else "",
                reason=_escape_cell(", ".join(_string_list(item.get("blockers")))),
            )
        )
    return "\n".join(lines)


def _transfer_candidates(receive_plan: Dict[str, object], filters: Sequence[str]) -> List[Dict[str, object]]:
    rows = []
    for item in receive_plan.get("items", []):
        if not isinstance(item, dict) or item.get("status") != "approval_required":
            continue
        title = str(item.get("title") or "")
        if filters and not any(value in title for value in filters):
            continue
        rows.append(item)
    return rows


def _run_transfer_item(
    item: Dict[str, object],
    *,
    output_dir: Path,
    config: object,
    actions: BatchTransferActions,
    approve_receive: bool,
    approve_transfer: bool,
    target_path: str,
    organize_target_dir: str,
    strm_dir: str,
    storage: str,
    timeout: int,
    transfer_timeout: int,
    host_strm_root: str,
) -> Dict[str, object]:
    title = str(item.get("title") or "")
    tmdbid = int(item.get("tmdbid") or 0)
    season = int(item.get("season") or 0)
    expected_count = int(item.get("expected_episode_count") or 0)
    expected_min = int(item.get("expected_episode_min") or 0)
    expected_max = int(item.get("expected_episode_max") or 0)
    prefix = _report_prefix(title, tmdbid, season)
    row: Dict[str, object] = {
        "title": title,
        "tmdbid": tmdbid,
        "season": season,
        "expected_episode_count": expected_count,
        "status": "approval_required",
        "ok": False,
        "receive_ok": False,
        "browse_ok": False,
        "organize_ok": False,
        "organize_request_ok": False,
        "organize_recovered_after_request_failure": False,
        "post_verify_ok": False,
        "blockers": [],
        "warnings": [],
        "stage_reports": {},
    }
    blockers = _preflight_blockers(item, target_path, organize_target_dir, strm_dir)
    if blockers:
        row["status"] = "failed_preflight"
        row["blockers"] = blockers
        return row
    if not approve_receive:
        row["blockers"] = ["receive_approval_required"]
        return row

    staging_preflight_report = _browse_expected_staging_preflight(
        actions,
        config,
        item,
        target_path=target_path,
        storage=storage,
        timeout=timeout,
    )
    staging_preflight_path = _stage_report_path(output_dir, prefix, "staging-preflight")
    _write_json(staging_preflight_path, staging_preflight_report)
    row["stage_reports"]["staging_preflight"] = str(staging_preflight_path)
    staging_blockers = _staging_preflight_blockers(staging_preflight_report)
    if staging_blockers:
        row["status"] = "failed_staging_preflight"
        row["blockers"] = staging_blockers
        return row

    receive_report = actions.receive_share(
        _config_value(config, "mv3_base_url"),
        _config_value(config, "mv3_token"),
        str(item.get("keyword") or ""),
        selection_index=int(item.get("selection_index") or 1),
        browse_index=int(item.get("browse_index") or 1),
        browse_cid=str(item.get("browse_cid") or ""),
        receive_all_files=str(item.get("receive_mode") or "") == "receive_all_files",
        receive_selected_folder=str(item.get("receive_mode") or "") == "receive_selected_folder",
        verified_folder_browse_report=_load_json_report(str(item.get("verified_folder_browse_report") or "")),
        expected_episode_count=expected_count,
        expected_episode_min=expected_min,
        expected_episode_max=expected_max,
        channels=[],
        expected_title_contains=str(item.get("expected_title_contains") or title),
        target_path=target_path,
        storage=storage,
        timeout=timeout,
    )
    receive_path = _stage_report_path(output_dir, prefix, "share-receive")
    _write_json(receive_path, receive_report)
    row["stage_reports"]["share_receive"] = str(receive_path)
    row["receive_ok"] = bool(receive_report.get("ok"))
    receive_recovered = False
    if not row["receive_ok"] and _receive_is_idempotent_success(receive_report) and _receive_episode_gate_ok(
        receive_report,
        expected_count=expected_count,
        expected_min=expected_min,
        expected_max=expected_max,
    ):
        row["receive_ok"] = True
        receive_recovered = True
        row["warnings"] = sorted(set(_string_list(row.get("warnings")) + ["receive_already_completed_reused_staging"]))
    if not row["receive_ok"]:
        row["status"] = "failed_receive"
        row["blockers"] = _report_blockers(receive_report) or ["receive_failed"]
        return row
    if receive_recovered:
        row["receive_recovered_after_already_exists"] = True

    browse_report, received_resolution_reports = _browse_received_folder(
        actions,
        config,
        target_path=target_path,
        title=title,
        receive_report=receive_report,
        storage=storage,
        timeout=timeout,
    )
    for index, resolution_report in enumerate(received_resolution_reports, start=1):
        resolution_path = _stage_report_path(output_dir, prefix, f"received-path-resolve-{index:02d}")
        _write_json(resolution_path, resolution_report)
        row["stage_reports"][f"received_path_resolve_{index:02d}"] = str(resolution_path)
    browse_path = _stage_report_path(output_dir, prefix, "received-browse")
    _write_json(browse_path, browse_report)
    row["stage_reports"]["received_browse"] = str(browse_path)
    row["browse_ok"] = bool(browse_report.get("ok"))
    if not row["browse_ok"]:
        row["status"] = "failed_received_browse"
        row["blockers"] = _report_blockers(browse_report) or ["received_browse_failed"]
        return row
    if not approve_transfer:
        row["status"] = "transfer_approval_required"
        row["blockers"] = ["transfer_approval_required"]
        return row

    organize_report = actions.organize_transfer(
        _config_value(config, "mv3_base_url"),
        _config_value(config, "mv3_token"),
        browse_report,
        target_dir=organize_target_dir,
        strm_dir=strm_dir,
        tmdb_id=tmdbid,
        expected_episode_count=expected_count,
        expected_episode_min=expected_min,
        expected_episode_max=expected_max,
        expected_episodes=[],
        mode="move",
        is_cloud_target=True,
        background=False,
        source_path_override="",
        timeout=transfer_timeout,
    )
    organize_path = _stage_report_path(output_dir, prefix, "organize-transfer")
    _write_json(organize_path, organize_report)
    row["stage_reports"]["organize_transfer"] = str(organize_path)
    row["organize_request_ok"] = bool(organize_report.get("ok"))

    organized_browse, organized_resolution_reports = _browse_organized_season(
        actions,
        config,
        item,
        organize_target_dir=organize_target_dir,
        title=title,
        tmdbid=tmdbid,
        season=season,
        storage=storage,
        timeout=timeout,
    )
    for index, resolution_report in enumerate(organized_resolution_reports, start=1):
        resolution_path = _stage_report_path(output_dir, prefix, f"organized-path-resolve-{index:02d}")
        _write_json(resolution_path, resolution_report)
        row["stage_reports"][f"organized_path_resolve_{index:02d}"] = str(resolution_path)

    organized_verify_path = _stage_report_path(output_dir, prefix, "organized-browse-verify")
    _write_json(organized_verify_path, organized_browse)
    row["stage_reports"]["organized_browse_verify"] = str(organized_verify_path)
    row["organized_verify_path"] = str(organized_browse.get("path") or "")

    staging_browse, staging_resolution_reports = _browse_received_staging_after_organize(
        actions,
        config,
        target_path=target_path,
        title=title,
        receive_report=receive_report,
        received_browse_report=browse_report,
        storage=storage,
        timeout=timeout,
    )
    for index, resolution_report in enumerate(staging_resolution_reports, start=1):
        resolution_path = _stage_report_path(output_dir, prefix, f"staging-path-resolve-{index:02d}")
        _write_json(resolution_path, resolution_report)
        row["stage_reports"][f"staging_path_resolve_{index:02d}"] = str(resolution_path)
    staging_verify_path = _stage_report_path(output_dir, prefix, "staging-browse-verify")
    _write_json(staging_verify_path, staging_browse)
    row["stage_reports"]["staging_browse_verify"] = str(staging_verify_path)

    strm_output_report: Dict[str, object] = {}
    if host_strm_root:
        strm_output_report = _verify_transfer_strm_outputs(
            host_strm_root=host_strm_root,
            title=title,
            tmdbid=tmdbid,
            season=season,
            expected_count=expected_count,
            expected_min=expected_min,
            expected_max=expected_max,
        )
        strm_output_path = _stage_report_path(output_dir, prefix, "strm-output-verify")
        _write_json(strm_output_path, strm_output_report)
        row["stage_reports"]["strm_output_verify"] = str(strm_output_path)

    verify_blockers = _post_organize_verify_blockers(
        organized_browse,
        staging_browse,
        strm_output_report=strm_output_report,
        expected_count=expected_count,
        expected_min=expected_min,
        expected_max=expected_max,
    )
    row["post_verify_ok"] = not verify_blockers
    request_blockers = _report_blockers(organize_report)
    if not row["organize_request_ok"] and not verify_blockers:
        row["organize_ok"] = True
        row["organize_recovered_after_request_failure"] = True
        row["warnings"] = sorted(set(_string_list(row.get("warnings")) + request_blockers))
    else:
        row["organize_ok"] = bool(row["organize_request_ok"])

    if verify_blockers:
        row["status"] = "failed_post_organize_verify" if row["organize_request_ok"] else "failed_organize_transfer"
        row["blockers"] = sorted(set((request_blockers or ["organize_transfer_failed"]) + verify_blockers))
        return row

    row["status"] = "organized_requires_finalize"
    row["ok"] = True
    row["required_followup"] = [
        "batch-finalize-plan",
        "batch-finalize-run without delete approval",
        "batch-finalize-run with delete approval only if all gates pass",
    ]
    return row


def _preflight_blockers(item: Dict[str, object], target_path: str, organize_target_dir: str, strm_dir: str) -> List[str]:
    blockers: List[str] = []
    if not target_path.startswith("/未整理"):
        blockers.append("target_path_must_start_with_unorganized_root")
    if organize_target_dir.rstrip("/") != "/已整理":
        blockers.append("organize_target_dir_must_be_finished_root")
    if not strm_dir.startswith("/strm"):
        blockers.append("strm_dir_must_be_strm_side")
    if not int(item.get("tmdbid") or 0):
        blockers.append("missing_tmdbid")
    if int(item.get("expected_episode_count") or 0) <= 0:
        blockers.append("missing_expected_episode_count")
    if not str(item.get("keyword") or ""):
        blockers.append("missing_keyword")
    if int(item.get("selection_index") or 0) <= 0:
        blockers.append("missing_selection_index")
    if str(item.get("receive_mode") or "") not in {"receive_all_files", "receive_selected_folder"}:
        blockers.append("unsupported_receive_mode")
    return sorted(set(blockers))


def _browse_expected_staging_preflight(
    actions: BatchTransferActions,
    config: object,
    item: Dict[str, object],
    *,
    target_path: str,
    storage: str,
    timeout: int,
) -> Dict[str, object]:
    expected_path = str(item.get("expected_staging_path") or "").strip()
    if not expected_path:
        expected_path = _expected_staging_path_from_receive_item(item, target_path)
    if not expected_path:
        return _synthetic_cloud_browse_report(target_path.rstrip("/") or "/", ["expected_staging_path_unresolved"])
    report = actions.browse_cloud(
        _config_value(config, "mv3_base_url"),
        _config_value(config, "mv3_token"),
        path=expected_path,
        storage=storage,
        limit=1150,
        timeout=timeout,
    )
    report["expected_staging_path"] = expected_path
    report["preflight"] = "before_share_receive"
    return report


def _expected_staging_path_from_receive_item(item: Dict[str, object], target_path: str) -> str:
    receive_mode = str(item.get("receive_mode") or "")
    verified = _load_json_report(str(item.get("verified_folder_browse_report") or ""))
    if receive_mode == "receive_selected_folder":
        nested = [row for row in item.get("nested_previews", []) if isinstance(row, dict)]
        if nested:
            folder_name = str(nested[-1].get("folder_name") or "").strip()
            if folder_name:
                return f"{target_path.rstrip('/')}/{folder_name}"
        folder_name = str(verified.get("nested_preview_folder_name") or "").strip()
        if folder_name:
            return f"{target_path.rstrip('/')}/{folder_name}"
    selection = verified.get("browse_selection") if isinstance(verified.get("browse_selection"), dict) else {}
    folder_name = str(selection.get("name") or "").strip()
    if folder_name:
        return f"{target_path.rstrip('/')}/{folder_name}"
    return target_path.rstrip("/") or "/"


def _staging_preflight_blockers(report: Dict[str, object]) -> List[str]:
    if _staging_path_absent(report):
        return []
    blockers = ["staging_target_path_already_exists"]
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    if int(summary.get("video_file_count") or 0) > 0:
        blockers.append("staging_target_video_files_present")
    if int(summary.get("folder_count") or 0) > 0:
        blockers.append("staging_target_folders_present")
    if int(summary.get("file_count") or 0) > 0:
        blockers.append("staging_target_files_present")
    if not str(report.get("folder_id") or ""):
        blockers.append("staging_target_folder_id_missing")
    return sorted(set(blockers))


def _received_browse_path(target_path: str, title: str, receive_report: Dict[str, object]) -> str:
    selection = receive_report.get("browse_selection") if isinstance(receive_report.get("browse_selection"), dict) else {}
    clean_title = str(selection.get("name") or "").strip() if isinstance(selection, dict) else ""
    clean_title = clean_title or _title_contains(title)
    return f"{target_path.rstrip('/')}/{clean_title}"


def _receive_is_idempotent_success(report: Dict[str, object]) -> bool:
    receive = report.get("receive") if isinstance(report.get("receive"), dict) else {}
    message = str(receive.get("api_message") or "")
    return "已接收" in message and ("无需重复" in message or "重复接收" in message)


def _receive_episode_gate_ok(
    report: Dict[str, object],
    *,
    expected_count: int,
    expected_min: int,
    expected_max: int,
) -> bool:
    if expected_count and int(report.get("episode_count") or 0) != expected_count:
        return False
    if expected_min and int(report.get("episode_min") or 0) != expected_min:
        return False
    if expected_max and int(report.get("episode_max") or 0) != expected_max:
        return False
    if _string_list(report.get("missing_expected")):
        return False
    return int(report.get("video_file_count") or 0) >= expected_count > 0


def _browse_received_folder(
    actions: BatchTransferActions,
    config: object,
    *,
    target_path: str,
    title: str,
    receive_report: Dict[str, object],
    storage: str,
    timeout: int,
) -> tuple[Dict[str, object], List[Dict[str, object]]]:
    direct_path = _received_browse_path(target_path, title, receive_report)
    direct_report = actions.browse_cloud(
        _config_value(config, "mv3_base_url"),
        _config_value(config, "mv3_token"),
        path=direct_path,
        storage=storage,
        limit=1150,
        timeout=timeout,
    )
    if direct_report.get("ok") or not _staging_path_absent(direct_report):
        return direct_report, []

    root_path = target_path.rstrip("/") or "/"
    root_report = actions.browse_cloud(
        _config_value(config, "mv3_base_url"),
        _config_value(config, "mv3_token"),
        path=root_path,
        storage=storage,
        limit=1150,
        timeout=timeout,
    )
    resolution_reports = [direct_report, root_report]
    match = _received_folder_match(root_report, receive_report, title)
    if not match:
        return direct_report, resolution_reports

    folder_id = str(match.get("file_id") or "")
    folder_name = str(match.get("name") or "").strip()
    if not folder_id:
        missing_id_report = _synthetic_cloud_browse_report(
            f"{root_path}/{folder_name}" if folder_name else direct_path,
            ["received_folder_id_missing"],
        )
        return missing_id_report, resolution_reports

    resolved_path = f"{root_path}/{folder_name}" if folder_name else direct_path
    resolved_report = actions.browse_cloud(
        _config_value(config, "mv3_base_url"),
        _config_value(config, "mv3_token"),
        folder_id=folder_id,
        storage=storage,
        limit=1150,
        timeout=timeout,
    )
    resolved_report["path"] = resolved_path
    resolved_report["folder_id"] = folder_id
    resolved_report["resolved_from_staging_root"] = {
        "root_path": root_path,
        "folder_id": folder_id,
        "folder_name": folder_name,
        "reason": "direct_path_not_addressable",
    }
    return resolved_report, resolution_reports


def _browse_received_staging_after_organize(
    actions: BatchTransferActions,
    config: object,
    *,
    target_path: str,
    title: str,
    receive_report: Dict[str, object],
    received_browse_report: Dict[str, object],
    storage: str,
    timeout: int,
) -> tuple[Dict[str, object], List[Dict[str, object]]]:
    resolution = (
        received_browse_report.get("resolved_from_staging_root")
        if isinstance(received_browse_report.get("resolved_from_staging_root"), dict)
        else {}
    )
    root_path = str(resolution.get("root_path") or target_path.rstrip("/") or "/")
    folder_id = str(resolution.get("folder_id") or "")
    folder_name = str(resolution.get("folder_name") or "").strip()
    if not folder_id and not folder_name:
        report = actions.browse_cloud(
            _config_value(config, "mv3_base_url"),
            _config_value(config, "mv3_token"),
            path=str(received_browse_report.get("path") or _received_browse_path(target_path, title, receive_report)),
            storage=storage,
            limit=1150,
            timeout=timeout,
        )
        return report, []

    root_report = actions.browse_cloud(
        _config_value(config, "mv3_base_url"),
        _config_value(config, "mv3_token"),
        path=root_path,
        storage=storage,
        limit=1150,
        timeout=timeout,
    )
    match = _received_folder_match(root_report, receive_report, title, expected_folder_id=folder_id, expected_name=folder_name)
    if not match:
        return _synthetic_cloud_browse_report(
            f"{root_path}/{folder_name}" if folder_name else str(received_browse_report.get("path") or ""),
            ["path_info_not_found"],
        ), [root_report]

    matched_folder_id = str(match.get("file_id") or "")
    if not matched_folder_id:
        return _synthetic_cloud_browse_report(
            f"{root_path}/{folder_name}" if folder_name else str(received_browse_report.get("path") or ""),
            ["received_folder_id_missing"],
        ), [root_report]

    report = actions.browse_cloud(
        _config_value(config, "mv3_base_url"),
        _config_value(config, "mv3_token"),
        folder_id=matched_folder_id,
        storage=storage,
        limit=1150,
        timeout=timeout,
    )
    report["path"] = f"{root_path}/{str(match.get('name') or folder_name).strip()}"
    report["folder_id"] = matched_folder_id
    report["resolved_from_staging_root"] = {
        "root_path": root_path,
        "folder_id": matched_folder_id,
        "folder_name": str(match.get("name") or folder_name).strip(),
        "reason": "post_organize_staging_verification",
    }
    return report, [root_report]


def _received_folder_match(
    root_report: Dict[str, object],
    receive_report: Dict[str, object],
    title: str,
    *,
    expected_folder_id: str = "",
    expected_name: str = "",
) -> Optional[Dict[str, object]]:
    if not root_report.get("ok"):
        return None
    folders = [
        item
        for item in root_report.get("items", [])
        if isinstance(item, dict) and str(item.get("kind") or "") == "folder"
    ]
    if expected_folder_id:
        matches = [item for item in folders if str(item.get("file_id") or "") == expected_folder_id]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None
    wanted_names = [expected_name] if expected_name else []
    selection = receive_report.get("browse_selection") if isinstance(receive_report.get("browse_selection"), dict) else {}
    selected_name = str(selection.get("name") or "").strip() if isinstance(selection, dict) else ""
    if selected_name and selected_name not in wanted_names:
        wanted_names.append(selected_name)
    fallback_title = _title_contains(title)
    if fallback_title and fallback_title not in wanted_names:
        wanted_names.append(fallback_title)
    for wanted_name in wanted_names:
        matches = [item for item in folders if str(item.get("name") or "").strip() == wanted_name]
        if len(matches) == 1:
            return matches[0]
    return None


def _synthetic_cloud_browse_report(path: str, warnings: Sequence[str]) -> Dict[str, object]:
    return {
        "mode": "readonly-mv3-cloud-browse",
        "ok": False,
        "path": path,
        "summary": {
            "item_count": 0,
            "folder_count": 0,
            "file_count": 0,
            "video_file_count": 0,
            "metadata_sidecar_file_count": 0,
        },
        "items": [],
        "warnings": sorted(set(str(item) for item in warnings if str(item))),
    }


def _browse_organized_season(
    actions: BatchTransferActions,
    config: object,
    item: Dict[str, object],
    *,
    organize_target_dir: str,
    title: str,
    tmdbid: int,
    season: int,
    storage: str,
    timeout: int,
) -> tuple[Dict[str, object], List[Dict[str, object]]]:
    reports: List[Dict[str, object]] = []
    seen: set[str] = set()
    for path in _organized_season_path_candidates(item, organize_target_dir, title, tmdbid, season):
        if path in seen:
            continue
        seen.add(path)
        report = actions.browse_cloud(
            _config_value(config, "mv3_base_url"),
            _config_value(config, "mv3_token"),
            path=path,
            storage=storage,
            limit=1150,
            timeout=timeout,
        )
        if report.get("ok"):
            return report, reports
        reports.append(report)

    root_path = f"{organize_target_dir.rstrip('/')}/series"
    root_report = actions.browse_cloud(
        _config_value(config, "mv3_base_url"),
        _config_value(config, "mv3_token"),
        path=root_path,
        storage=storage,
        limit=1150,
        timeout=timeout,
    )
    reports.append(root_report)
    title_path = _organized_title_path_from_root(root_report, root_path, tmdbid, title)
    if title_path:
        report = actions.browse_cloud(
            _config_value(config, "mv3_base_url"),
            _config_value(config, "mv3_token"),
            path=f"{title_path}/Season {season}",
            storage=storage,
            limit=1150,
            timeout=timeout,
        )
        return report, reports

    return {
        "mode": "readonly-mv3-cloud-browse",
        "ok": False,
        "path": "",
        "summary": {},
        "items": [],
        "warnings": ["organized_season_path_not_resolved"],
    }, reports


def _organized_season_path_candidates(
    item: Dict[str, object],
    organize_target_dir: str,
    title: str,
    tmdbid: int,
    season: int,
) -> List[str]:
    paths: List[str] = []
    for key in ("organized_season_path", "cloud_media_path", "target_season_path"):
        path = str(item.get(key) or "").strip()
        if path:
            paths.append(path)
    for key in ("organized_title_path", "cloud_title_path", "required_target_prefix"):
        path = str(item.get(key) or "").strip()
        if path:
            paths.append(f"{path.rstrip('/')}/Season {season}")
    paths.append(_organized_season_path(organize_target_dir, title, tmdbid, season))
    candidate_title = str(item.get("candidate_title") or "").strip()
    if candidate_title:
        paths.append(_organized_season_path(organize_target_dir, candidate_title, tmdbid, season))
    return paths


def _organized_season_path(organize_target_dir: str, title: str, tmdbid: int, season: int) -> str:
    root = organize_target_dir.rstrip("/")
    clean_title = _title_contains(title)
    suffix = f" {{tmdbid={tmdbid}}}" if tmdbid else ""
    return f"{root}/series/{clean_title}{suffix}/Season {season}"


def _organized_title_path_from_root(root_report: Dict[str, object], root_path: str, tmdbid: int, title: str) -> str:
    folders = [
        item
        for item in root_report.get("items", [])
        if isinstance(item, dict) and str(item.get("kind") or "") == "folder"
    ]
    tmdb_token = f"{{tmdbid={tmdbid}}}" if tmdbid else ""
    if tmdb_token:
        matches = [item for item in folders if tmdb_token in str(item.get("name") or "")]
        if len(matches) == 1:
            return f"{root_path.rstrip('/')}/{str(matches[0].get('name') or '').strip()}"
    clean_title = _title_contains(title)
    title_matches = [
        item
        for item in folders
        if clean_title and clean_title == _title_contains(str(item.get("name") or ""))
    ]
    if len(title_matches) == 1:
        return f"{root_path.rstrip('/')}/{str(title_matches[0].get('name') or '').strip()}"
    return ""


def _post_organize_verify_blockers(
    organized_browse: Dict[str, object],
    staging_browse: Dict[str, object],
    *,
    strm_output_report: Optional[Dict[str, object]] = None,
    expected_count: int,
    expected_min: int,
    expected_max: int,
) -> List[str]:
    blockers: List[str] = []
    organized_summary = organized_browse.get("summary") if isinstance(organized_browse.get("summary"), dict) else {}
    staging_summary = staging_browse.get("summary") if isinstance(staging_browse.get("summary"), dict) else {}
    organized_episodes = _video_episodes(organized_browse)
    distinct_episodes = sorted(set(organized_episodes))
    duplicate_episodes = sorted(episode for episode in set(organized_episodes) if organized_episodes.count(episode) > 1)
    expected_episodes = set(range(expected_min, expected_max + 1)) if expected_min and expected_max else set()
    missing = sorted(expected_episodes - set(distinct_episodes))
    unexpected = sorted(set(distinct_episodes) - expected_episodes) if expected_episodes else []

    if not organized_browse.get("ok"):
        blockers.append("organized_browse_failed")
    if expected_count and len(distinct_episodes) != expected_count:
        blockers.append("organized_episode_count_mismatch")
    if expected_count and int(organized_summary.get("video_file_count") or 0) != expected_count:
        blockers.append("organized_video_file_count_mismatch")
    if missing:
        blockers.append("organized_episode_range_incomplete")
    if unexpected:
        blockers.append("organized_unexpected_episodes_present")
    if duplicate_episodes:
        blockers.append("organized_duplicate_episodes_present")
    if int(organized_summary.get("metadata_sidecar_file_count") or 0) > 0:
        blockers.append("organized_metadata_sidecars_present")
    if int(staging_summary.get("video_file_count") or 0) > 0:
        blockers.append("staging_video_files_remain")
    if not staging_browse.get("ok") and not _staging_path_absent(staging_browse):
        blockers.append("staging_browse_failed")
    if isinstance(strm_output_report, dict) and strm_output_report.get("enabled"):
        blockers.extend(_string_list(strm_output_report.get("blockers")))
    return sorted(set(blockers))


def _staging_path_absent(report: Dict[str, object]) -> bool:
    warnings = _string_list(report.get("warnings"))
    return "path_info_not_found" in warnings or "no_cloud_items_found" in warnings


def _video_episodes(report: Dict[str, object]) -> List[int]:
    episodes: List[int] = []
    for item in report.get("items", []):
        if not isinstance(item, dict) or str(item.get("media_kind") or "") != "video":
            continue
        episode = item.get("episode")
        if isinstance(episode, int) and episode > 0:
            episodes.append(episode)
    return episodes


def _verify_transfer_strm_outputs(
    *,
    host_strm_root: str,
    title: str,
    tmdbid: int,
    season: int,
    expected_count: int,
    expected_min: int,
    expected_max: int,
) -> Dict[str, object]:
    root = Path(host_strm_root)
    expected_roots = _candidate_strm_season_roots(root, "series", title, tmdbid, season)
    misplaced_roots = _candidate_strm_season_roots(root, "未识别", title, tmdbid, season)
    expected_files = _strm_files_under(expected_roots)
    misplaced_files = _strm_files_under(misplaced_roots)
    expected_episodes = _episodes_from_paths(expected_files)
    misplaced_episodes = _episodes_from_paths(misplaced_files)
    distinct_expected = sorted(set(expected_episodes))
    expected_set = set(range(expected_min, expected_max + 1)) if expected_min and expected_max else set()
    missing = sorted(expected_set - set(distinct_expected)) if expected_set else []
    blockers: List[str] = []
    warnings: List[str] = []

    if not root.exists():
        blockers.append("host_strm_root_missing")
    if misplaced_files:
        blockers.append("strm_written_to_unrecognized_root")
    if expected_count and not expected_files:
        blockers.append("expected_strm_root_missing")
    elif expected_count and len(distinct_expected) != expected_count:
        blockers.append("expected_strm_episode_count_mismatch")
    if missing:
        blockers.append("expected_strm_episode_range_incomplete")
    if expected_episodes and len(expected_episodes) != len(distinct_expected):
        blockers.append("expected_strm_duplicate_episodes_present")
    if misplaced_files:
        warnings.append("misplaced_strm_requires_manual_repair_before_finalize")

    return {
        "mode": "readonly-transfer-strm-output-verify",
        "enabled": True,
        "ok": not blockers,
        "host_strm_root": str(root),
        "expected": {
            "title": title,
            "tmdbid": tmdbid,
            "season": season,
            "episode_count": expected_count,
            "episode_min": expected_min,
            "episode_max": expected_max,
        },
        "expected_roots": [_strm_root_summary(path) for path in expected_roots],
        "misplaced_roots": [_strm_root_summary(path) for path in misplaced_roots],
        "expected_episode_count": len(distinct_expected),
        "expected_episodes": distinct_expected,
        "missing_expected": missing,
        "misplaced_episode_count": len(set(misplaced_episodes)),
        "misplaced_episodes": sorted(set(misplaced_episodes)),
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": (
            "readonly STRM output verification after MV3 transfer; it only scans the host STRM root "
            "to ensure generated STRM files are under the expected series library path and not under 未识别. "
            "It does not scrape, refresh Emby, write STRM/NFO/JPG, touch qBittorrent, or delete files."
        ),
    }


def _candidate_strm_season_roots(root: Path, category: str, title: str, tmdbid: int, season: int) -> List[Path]:
    category_root = root / category
    title_token = _title_contains(title)
    tmdb_token = f"{{tmdbid={tmdbid}}}" if tmdbid else ""
    title_dirs: List[Path] = []
    direct_title = f"{title_token} {tmdb_token}".strip()
    if direct_title:
        title_dirs.append(category_root / direct_title)
    if category_root.exists():
        for child in category_root.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if tmdb_token and tmdb_token in name:
                title_dirs.append(child)
            elif title_token and _title_contains(name) == title_token:
                title_dirs.append(child)

    roots: List[Path] = []
    seen: set[str] = set()
    for title_dir in title_dirs:
        for season_name in (f"Season {season}", f"Season {season:02d}"):
            candidate = title_dir / season_name
            key = str(candidate)
            if key not in seen:
                seen.add(key)
                roots.append(candidate)
    return roots


def _strm_files_under(roots: Sequence[Path]) -> List[Path]:
    files: List[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.glob("*.strm")):
            key = str(path)
            if key not in seen:
                seen.add(key)
                files.append(path)
    return files


def _episodes_from_paths(paths: Sequence[Path]) -> List[int]:
    episodes: List[int] = []
    for path in paths:
        match = re.search(r"[Ss]\d{1,2}[Ee](\d{1,4})", path.name)
        if match:
            episodes.append(int(match.group(1)))
    return sorted(episode for episode in episodes if episode > 0)


def _strm_root_summary(path: Path) -> Dict[str, object]:
    files = _strm_files_under([path])
    episodes = _episodes_from_paths(files)
    return {
        "path": str(path),
        "exists": path.exists(),
        "file_count": len(files),
        "episode_count": len(set(episodes)),
        "episodes": sorted(set(episodes)),
        "sample_files": [str(item) for item in files[:5]],
    }


def _title_contains(title: str) -> str:
    text = title.split(" (", 1)[0].strip() or title
    text = text.split("{tmdbid=", 1)[0].strip()
    return text or title


def _report_blockers(report: Dict[str, object]) -> List[str]:
    return sorted(set(_string_list(report.get("blockers")) + _string_list(report.get("warnings"))))


def _load_json_report(path: str) -> Optional[Dict[str, object]]:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _stage_report_path(output_dir: Path, report_prefix: str, stage_name: str) -> Path:
    return output_dir / f"{report_prefix}-{stage_name}.json"


def _write_json(path: Path, report: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _config_value(config: object, name: str) -> str:
    return str(getattr(config, name, "") or "")


def _report_prefix(title: str, tmdbid: int, season: int) -> str:
    slug = re.sub(r"[^0-9A-Za-z一-龥]+", "-", title).strip("-")
    if not slug:
        slug = "series"
    return f"{slug}-{tmdbid}-s{season:02d}"


def _string_list(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
