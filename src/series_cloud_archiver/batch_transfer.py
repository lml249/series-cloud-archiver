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
        "blockers": [],
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
    if not row["receive_ok"]:
        row["status"] = "failed_receive"
        row["blockers"] = _report_blockers(receive_report) or ["receive_failed"]
        return row

    browse_report = actions.browse_cloud(
        _config_value(config, "mv3_base_url"),
        _config_value(config, "mv3_token"),
        path=_received_browse_path(target_path, title, receive_report),
        storage=storage,
        limit=1150,
        timeout=timeout,
    )
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
    row["organize_ok"] = bool(organize_report.get("ok"))
    if not row["organize_ok"]:
        row["status"] = "failed_organize_transfer"
        row["blockers"] = _report_blockers(organize_report) or ["organize_transfer_failed"]
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


def _received_browse_path(target_path: str, title: str, receive_report: Dict[str, object]) -> str:
    selection = receive_report.get("browse_selection") if isinstance(receive_report.get("browse_selection"), dict) else {}
    clean_title = str(selection.get("name") or "").strip() if isinstance(selection, dict) else ""
    clean_title = clean_title or _title_contains(title)
    return f"{target_path.rstrip('/')}/{clean_title}"


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
