from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence


DEFAULT_ALLOWED_BEST_BLOCKERS = ["episode_coverage_unclear"]
AUTO_TRANSFER = "auto_ready_for_transfer_preview"
MANUAL_REVIEW = "manual_review"
DEFAULT_PREVIEW_BUCKETS = [AUTO_TRANSFER, MANUAL_REVIEW]
DEFAULT_REVIEW_PREVIEW_DECISIONS = ["manual_review_required", "ready_for_share_preview"]


PreviewFunc = Callable[..., Dict[str, object]]


def build_batch_share_preview_plan(
    batch_plan: Dict[str, object],
    *,
    env_file: str = "",
    buckets: Optional[Sequence[str]] = None,
    min_candidate_score: int = 55,
    allowed_best_blockers: Optional[Sequence[str]] = None,
    limit: int = 10,
    execute_preview: bool = False,
    base_url: str = "",
    token: str = "",
    channels: Optional[Sequence[str]] = None,
    storage: str = "115-default",
    timeout: int = 60,
    preview_output_dir: str = "",
    max_nested_depth: int = 3,
    review_reports: Optional[Sequence[Dict[str, object]]] = None,
    review_preview_decisions: Optional[Sequence[str]] = None,
    preview_func: Optional[PreviewFunc] = None,
) -> Dict[str, object]:
    """Build or execute readonly MV3 share previews for batch-plan candidates."""

    wanted_buckets = set(str(item) for item in (buckets or DEFAULT_PREVIEW_BUCKETS) if str(item))
    allowed_blockers = set(str(item) for item in (allowed_best_blockers or DEFAULT_ALLOWED_BEST_BLOCKERS) if str(item))
    allowed_review_decisions = set(
        str(item) for item in (review_preview_decisions or DEFAULT_REVIEW_PREVIEW_DECISIONS) if str(item)
    )
    review_by_key = _preview_review_by_identity(review_reports or [])
    rows: List[Dict[str, object]] = []
    executed = 0
    preview_dir = Path(preview_output_dir) if preview_output_dir else None
    if preview_dir:
        preview_dir.mkdir(parents=True, exist_ok=True)

    for index, item in enumerate(batch_plan.get("items", []), start=1):
        if not isinstance(item, dict):
            continue
        row = _preview_row(
            index,
            item,
            env_file=env_file,
            wanted_buckets=wanted_buckets,
            min_candidate_score=min_candidate_score,
            allowed_blockers=allowed_blockers,
            review_item=review_by_key.get(_identity_key(item), {}),
            allowed_review_decisions=allowed_review_decisions,
            storage=storage,
        )
        if execute_preview and row["status"] == "planned_preview":
            if preview_func is None:
                raise ValueError("preview_func is required when execute_preview=True")
            report = _run_preview(
                preview_func,
                base_url,
                token,
                row,
                channels=list(channels or []),
                storage=storage,
                timeout=timeout,
            )
            row["nested_previews"] = []
            row["nested_preview_attempted"] = False
            root_report = report
            depth = 0
            while not bool(report.get("ok")) and depth < max_nested_depth:
                nested = _single_nested_folder(report)
                if not nested:
                    break
                depth += 1
                row["nested_preview_attempted"] = True
                row["nested_preview_cid"] = nested["cid"]
                row["nested_preview_folder_name"] = nested["name"]
                if depth == 1:
                    row["root_preview_report"] = root_report
                row["nested_previews"].append(
                    {
                        "depth": depth,
                        "cid": nested["cid"],
                        "index": nested["index"],
                        "folder_name": nested["name"],
                    }
                )
                report = _run_preview(
                    preview_func,
                    base_url,
                    token,
                    row,
                    channels=list(channels or []),
                    storage=storage,
                    timeout=timeout,
                    browse_cid=str(nested["cid"]),
                )
                row["nested_previews"][-1]["ok"] = bool(report.get("ok"))
                row["nested_previews"][-1]["episode_count"] = int(report.get("episode_count") or 0)
                row["nested_previews"][-1]["blockers"] = _string_list(report.get("blockers"))
            executed += 1
            row["preview_report"] = report
            row["preview_ok"] = bool(report.get("ok"))
            row["preview_blockers"] = _string_list(report.get("blockers"))
            row["preview_episode_count"] = int(report.get("episode_count") or 0)
            row["preview_missing_expected"] = _int_list(report.get("missing_expected"))
            row["preview_unexpected_episodes"] = _int_list(report.get("unexpected_episodes"))
            row["status"] = "preview_ready_for_receive" if bool(report.get("ok")) else "preview_blocked"
            if preview_dir:
                report_path = preview_dir / _preview_report_filename(row)
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                row["preview_report_path"] = str(report_path)

        rows.append(row)
        if limit > 0 and sum(1 for candidate in rows if candidate.get("status") == "planned_preview") >= limit and not execute_preview:
            break
        if limit > 0 and executed >= limit and execute_preview:
            break

    return {
        "mode": "readonly-batch-mv3-share-preview",
        "source_mode": batch_plan.get("mode", ""),
        "planned_items": len(rows),
        "executable_preview_items": sum(1 for row in rows if row.get("status") == "planned_preview"),
        "executed_preview_items": executed,
        "ready_for_receive_items": sum(1 for row in rows if row.get("status") == "preview_ready_for_receive"),
        "blocked_preview_items": sum(1 for row in rows if row.get("status") == "preview_blocked"),
        "skipped_items": sum(1 for row in rows if str(row.get("status") or "").startswith("skipped")),
        "settings": {
            "buckets": sorted(wanted_buckets),
            "min_candidate_score": min_candidate_score,
            "allowed_best_blockers": sorted(allowed_blockers),
            "review_report_count": len(review_reports or []),
            "review_preview_decisions": sorted(allowed_review_decisions),
            "limit": limit,
            "execute_preview": execute_preview,
            "storage": storage,
            "channels": list(channels or []),
            "preview_output_dir": preview_output_dir,
            "max_nested_depth": max_nested_depth,
        },
        "items": rows,
        "safety": (
            "batch MV3 share preview is readonly; no share receive, organize transfer, STRM generation, "
            "MoviePilot scrape, Emby refresh, qBittorrent action, hlink deletion, source deletion, or filesystem deletion is performed"
        ),
    }


def _run_preview(
    preview_func: PreviewFunc,
    base_url: str,
    token: str,
    row: Dict[str, object],
    *,
    channels: List[str],
    storage: str,
    timeout: int,
    browse_cid: str = "",
) -> Dict[str, object]:
    return preview_func(
        base_url,
        token,
        row["keyword"],
        selection_index=int(row["selection_index"] or 1),
        browse_cid=browse_cid,
        expected_episode_count=int(row["expected_episode_count"] or 0),
        expected_episode_min=int(row["expected_episode_min"] or 0),
        expected_episode_max=int(row["expected_episode_max"] or 0),
        expected_episodes=_int_list(row.get("expected_episodes")),
        channels=channels,
        expected_title_contains=str(row.get("expected_title_contains") or ""),
        storage=storage,
        timeout=timeout,
    )


def _single_nested_folder(report: Dict[str, object]) -> Dict[str, str]:
    browse = report.get("browse") if isinstance(report.get("browse"), dict) else {}
    items = browse.get("items") if isinstance(browse.get("items"), list) else []
    material_items = [
        item
        for item in items
        if isinstance(item, dict) and str(item.get("media_kind") or item.get("kind") or "") != "metadata_sidecar"
    ]
    folders = [item for item in material_items if isinstance(item, dict) and str(item.get("kind") or "") == "folder"]
    if len(folders) != 1 or len(material_items) != 1:
        return {}
    folder = folders[0]
    cid = str(folder.get("file_id") or "")
    name = str(folder.get("name") or "")
    index = str(folder.get("index") or "")
    return {"cid": cid, "name": name, "index": index} if cid else {}


def render_batch_share_preview_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        "# Batch MV3 Share Preview",
        "",
        f"- Mode: `{report.get('mode', '')}`",
        f"- Planned rows: `{report.get('planned_items', 0)}`",
        f"- Executable previews: `{report.get('executable_preview_items', 0)}`",
        f"- Executed previews: `{report.get('executed_preview_items', 0)}`",
        f"- Ready for receive: `{report.get('ready_for_receive_items', 0)}`",
        f"- Blocked previews: `{report.get('blocked_preview_items', 0)}`",
        f"- Skipped: `{report.get('skipped_items', 0)}`",
        "- Safety: readonly preview only; no receive/transfer or delete action was performed.",
        "",
        "| Status | Score | TMDB | S | Episodes | Title | Candidate | Reason |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        reason = ", ".join(_string_list(item.get("skip_reasons")) + _string_list(item.get("preview_blockers")))
        lines.append(
            "| {status} | {score} | {tmdbid} | {season} | {episodes} | {title} | {candidate} | {reason} |".format(
                status=item.get("status", ""),
                score=item.get("candidate_score", ""),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                episodes=item.get("expected_episode_count") or "",
                title=_escape_cell(str(item.get("title") or "")),
                candidate=_escape_cell(str(item.get("candidate_title") or "")),
                reason=_escape_cell(reason),
            )
        )
    return "\n".join(lines)


def build_batch_share_receive_plan(
    batch_share_preview_report: Dict[str, object],
    *,
    env_file: str = "",
    target_path: str = "/未整理",
    storage: str = "115-default",
    limit: int = 0,
) -> Dict[str, object]:
    """Build approval-gated MV3 share receive commands from successful previews."""

    rows: List[Dict[str, object]] = []
    for index, item in enumerate(batch_share_preview_report.get("items", []), start=1):
        if not isinstance(item, dict):
            continue
        row = _receive_plan_row(
            index,
            item,
            env_file=env_file,
            target_path=target_path,
            storage=storage,
        )
        rows.append(row)
        if limit > 0 and sum(1 for candidate in rows if candidate.get("status") == "approval_required") >= limit:
            break

    return {
        "mode": "readonly-batch-mv3-share-receive-plan",
        "source_mode": batch_share_preview_report.get("mode", ""),
        "planned_items": len(rows),
        "approval_required_items": sum(1 for row in rows if row.get("status") == "approval_required"),
        "skipped_items": sum(1 for row in rows if str(row.get("status") or "").startswith("skipped")),
        "settings": {
            "target_path": target_path,
            "storage": storage,
            "limit": limit,
        },
        "items": rows,
        "safety": (
            "readonly receive plan only; no share receive, organize transfer, STRM generation, MoviePilot scrape, "
            "Emby refresh, qBittorrent action, hlink deletion, source deletion, or filesystem deletion is performed. "
            "Generated commands still require the explicit --approve-receive flag before MV3 can receive anything."
        ),
    }


def render_batch_share_receive_plan(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        "# Batch MV3 Share Receive Plan",
        "",
        f"- Mode: `{report.get('mode', '')}`",
        f"- Planned rows: `{report.get('planned_items', 0)}`",
        f"- Approval required: `{report.get('approval_required_items', 0)}`",
        f"- Skipped: `{report.get('skipped_items', 0)}`",
        "- Safety: readonly plan only; generated commands require explicit receive approval.",
        "",
        "| Status | Mode | TMDB | S | Episodes | Title | Target | Reason |",
        "| --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for item in report.get("items", []):
        if not isinstance(item, dict):
            continue
        reason = ", ".join(_string_list(item.get("skip_reasons")))
        lines.append(
            "| {status} | {mode} | {tmdbid} | {season} | {episodes} | {title} | {target} | {reason} |".format(
                status=item.get("status", ""),
                mode=item.get("receive_mode", ""),
                tmdbid=item.get("tmdbid") or "",
                season=item.get("season") or "",
                episodes=item.get("expected_episode_count") or "",
                title=_escape_cell(str(item.get("title") or "")),
                target=_escape_cell(str(item.get("target_path") or "")),
                reason=_escape_cell(reason),
            )
        )
    return "\n".join(lines)


def _preview_row(
    index: int,
    item: Dict[str, object],
    *,
    env_file: str,
    wanted_buckets: set[str],
    min_candidate_score: int,
    allowed_blockers: set[str],
    review_item: Dict[str, object],
    allowed_review_decisions: set[str],
    storage: str,
) -> Dict[str, object]:
    diagnostics = item.get("candidate_diagnostics") if isinstance(item.get("candidate_diagnostics"), dict) else {}
    best = diagnostics.get("best_candidate") if isinstance(diagnostics.get("best_candidate"), dict) else {}
    title = str(item.get("title") or "")
    expected_count = int(item.get("expected_episode_count") or 0)
    expected_episodes = _int_list(item.get("expected_episodes"))
    episode_min = min(expected_episodes) if expected_episodes else (1 if expected_count else 0)
    episode_max = max(expected_episodes) if expected_episodes else expected_count
    keyword = str(best.get("search_keyword") or title)
    selection_index = int(best.get("search_index") or 0)
    blockers = set(_string_list(best.get("blockers")))
    skip_reasons: List[str] = []

    if review_item:
        review_decision = str(review_item.get("decision") or "")
        if review_decision and review_decision not in allowed_review_decisions:
            skip_reasons.append(f"review_decision_blocked:{review_decision}")
    if str(item.get("bucket") or "") not in wanted_buckets:
        skip_reasons.append("bucket_not_selected")
    if not best:
        skip_reasons.append("no_best_candidate")
    if best and int(best.get("score") or 0) < min_candidate_score:
        skip_reasons.append("best_candidate_score_below_minimum")
    disallowed = sorted(blocker for blocker in blockers if blocker not in allowed_blockers)
    skip_reasons.extend(f"best_candidate_blocked:{blocker}" for blocker in disallowed)
    if selection_index <= 0:
        skip_reasons.append("missing_selection_index")
    if not keyword:
        skip_reasons.append("missing_search_keyword")
    if expected_count <= 0:
        skip_reasons.append("missing_expected_episode_count")

    status = "planned_preview" if not skip_reasons else "skipped_preview"
    row = {
        "source_index": index,
        "status": status,
        "skip_reasons": sorted(set(skip_reasons)),
        "title": title,
        "tmdbid": int(item.get("tmdbid") or 0),
        "season": int(item.get("season") or 0),
        "expected_episode_count": expected_count,
        "expected_episode_min": episode_min,
        "expected_episode_max": episode_max,
        "expected_episodes": expected_episodes,
        "expected_title_contains": _title_contains(title),
        "keyword": keyword,
        "selection_index": selection_index,
        "candidate_title": str(best.get("title") or ""),
        "candidate_score": int(best.get("score") or 0) if best else 0,
        "candidate_size_delta_ratio": best.get("size_delta_ratio") if best else None,
        "candidate_blockers": sorted(blockers),
        "review_decision": str(review_item.get("decision") or "") if review_item else "",
        "review_next_action": str(review_item.get("next_action") or "") if review_item else "",
        "cloud_media_path": str(item.get("cloud_media_path") or ""),
        "cloud_title_path": str(item.get("cloud_title_path") or ""),
        "required_target_prefix": str(item.get("required_target_prefix") or ""),
        "command": "",
    }
    if status == "planned_preview":
        row["command"] = _preview_command(row, env_file=env_file, storage=storage)
    return row


def _preview_review_by_identity(review_reports: Sequence[Dict[str, object]]) -> Dict[tuple[int, int], Dict[str, object]]:
    result: Dict[tuple[int, int], Dict[str, object]] = {}
    for report_index, report in enumerate(review_reports, start=1):
        for item in report.get("items", []):
            if not isinstance(item, dict):
                continue
            key = _identity_key(item)
            if key == (0, 0):
                continue
            row = dict(item)
            row["review_report_index"] = report_index
            result[key] = row
    return result


def _identity_key(item: Dict[str, object]) -> tuple[int, int]:
    return int(item.get("tmdbid") or item.get("tmdb_id") or 0), int(item.get("season") or item.get("season_number") or 0)


def _preview_command(row: Dict[str, object], *, env_file: str, storage: str) -> str:
    args = [
        "PYTHONPATH=src",
        "python3",
        "-m",
        "series_cloud_archiver",
        "mv3-share-preview",
    ]
    if env_file:
        args.extend(["--env-file", env_file])
    args.extend(
        [
            "--keyword",
            str(row.get("keyword") or ""),
            "--selection-index",
            str(row.get("selection_index") or 1),
            "--expected-episode-count",
            str(row.get("expected_episode_count") or 0),
            "--expected-title-contains",
            str(row.get("expected_title_contains") or ""),
            "--storage",
            storage,
            "--format",
            "json",
            "--output",
            "<preview-report.json>",
        ]
    )
    expected_episodes = _int_list(row.get("expected_episodes"))
    if expected_episodes:
        args.extend(["--expected-episode", ",".join(str(item) for item in expected_episodes)])
    else:
        args.extend(
            [
                "--expected-episode-min",
                str(row.get("expected_episode_min") or 0),
                "--expected-episode-max",
                str(row.get("expected_episode_max") or 0),
            ]
        )
    return " ".join(_shell_quote(part) for part in args)


def _preview_report_filename(row: Dict[str, object]) -> str:
    title = "".join(ch if ch.isalnum() else "-" for ch in str(row.get("title") or "untitled")).strip("-")
    title = title[:40] or "untitled"
    return f"share-preview-{int(row.get('tmdbid') or 0)}-s{int(row.get('season') or 0):02d}-{title}.json"


def _receive_plan_row(
    index: int,
    item: Dict[str, object],
    *,
    env_file: str,
    target_path: str,
    storage: str,
) -> Dict[str, object]:
    skip_reasons: List[str] = []
    if item.get("status") != "preview_ready_for_receive":
        skip_reasons.append("preview_not_ready_for_receive")
    if not item.get("preview_report_path"):
        skip_reasons.append("preview_report_path_missing")

    nested_previews = [row for row in item.get("nested_previews", []) if isinstance(row, dict)]
    receive_mode = ""
    browse_cid = ""
    browse_index = 1
    verified_report = str(item.get("preview_report_path") or "")
    if nested_previews:
        receive_mode = "receive_selected_folder"
        final = nested_previews[-1]
        parent = nested_previews[-2] if len(nested_previews) >= 2 else {}
        browse_cid = str(parent.get("cid") or "")
        browse_index = int(final.get("index") or 1)
        if not str(final.get("cid") or ""):
            skip_reasons.append("selected_folder_cid_missing")
        if not browse_cid and len(nested_previews) >= 2:
            skip_reasons.append("parent_folder_cid_missing")
    else:
        receive_mode = "receive_all_files"
        preview_report = item.get("preview_report") if isinstance(item.get("preview_report"), dict) else {}
        browse_cid = str(preview_report.get("browse_cid") or "")

    expected_count = int(item.get("expected_episode_count") or 0)
    expected_min = int(item.get("expected_episode_min") or 0)
    expected_max = int(item.get("expected_episode_max") or 0)
    if expected_count <= 0:
        skip_reasons.append("missing_expected_episode_count")
    if expected_min <= 0 or expected_max <= 0:
        skip_reasons.append("missing_expected_episode_range")
    if not str(item.get("keyword") or ""):
        skip_reasons.append("missing_search_keyword")
    if int(item.get("selection_index") or 0) <= 0:
        skip_reasons.append("missing_selection_index")
    if not str(target_path or "").startswith("/未整理"):
        skip_reasons.append("target_path_must_start_with_unorganized_root")

    status = "approval_required" if not skip_reasons else "skipped_receive"
    row = {
        "source_index": index,
        "status": status,
        "skip_reasons": sorted(set(skip_reasons)),
        "title": str(item.get("title") or ""),
        "tmdbid": int(item.get("tmdbid") or 0),
        "season": int(item.get("season") or 0),
        "keyword": str(item.get("keyword") or ""),
        "selection_index": int(item.get("selection_index") or 0),
        "browse_cid": browse_cid,
        "browse_index": browse_index,
        "receive_mode": receive_mode,
        "verified_folder_browse_report": verified_report if receive_mode == "receive_selected_folder" else "",
        "target_path": target_path,
        "expected_staging_path": _expected_staging_path(item, target_path, receive_mode),
        "storage": storage,
        "expected_episode_count": expected_count,
        "expected_episode_min": expected_min,
        "expected_episode_max": expected_max,
        "expected_title_contains": str(item.get("expected_title_contains") or ""),
        "cloud_media_path": str(item.get("cloud_media_path") or ""),
        "cloud_title_path": str(item.get("cloud_title_path") or ""),
        "required_target_prefix": str(item.get("required_target_prefix") or ""),
        "approval_flag_required": "--approve-receive",
        "command": "",
    }
    if status == "approval_required":
        row["command"] = _receive_command(row, env_file=env_file)
    return row


def _expected_staging_path(item: Dict[str, object], target_path: str, receive_mode: str) -> str:
    if receive_mode == "receive_selected_folder":
        nested_previews = [row for row in item.get("nested_previews", []) if isinstance(row, dict)]
        if nested_previews:
            folder_name = str(nested_previews[-1].get("folder_name") or "").strip()
            if folder_name:
                return f"{target_path.rstrip('/')}/{folder_name}"
    preview_report = item.get("preview_report") if isinstance(item.get("preview_report"), dict) else {}
    browse = preview_report.get("browse") if isinstance(preview_report.get("browse"), dict) else {}
    selection = preview_report.get("browse_selection") if isinstance(preview_report.get("browse_selection"), dict) else {}
    folder_name = str(selection.get("name") or "").strip()
    if folder_name:
        return f"{target_path.rstrip('/')}/{folder_name}"
    browse_cid = str(preview_report.get("browse_cid") or "")
    for candidate in item.get("nested_previews", []):
        if isinstance(candidate, dict) and str(candidate.get("cid") or "") == browse_cid:
            folder_name = str(candidate.get("folder_name") or "").strip()
            if folder_name:
                return f"{target_path.rstrip('/')}/{folder_name}"
    browse_path = str(browse.get("path") or "").strip()
    if browse_path and browse_path.startswith("/"):
        return f"{target_path.rstrip('/')}/{Path(browse_path).name}"
    return target_path.rstrip("/") or "/"


def _receive_command(row: Dict[str, object], *, env_file: str) -> str:
    args = [
        "PYTHONPATH=src",
        "python3",
        "-m",
        "series_cloud_archiver",
        "mv3-share-receive-one",
    ]
    if env_file:
        args.extend(["--env-file", env_file])
    args.extend(
        [
            "--keyword",
            str(row.get("keyword") or ""),
            "--selection-index",
            str(row.get("selection_index") or 1),
            "--browse-index",
            str(row.get("browse_index") or 1),
            "--expected-episode-count",
            str(row.get("expected_episode_count") or 0),
            "--expected-episode-min",
            str(row.get("expected_episode_min") or 0),
            "--expected-episode-max",
            str(row.get("expected_episode_max") or 0),
            "--expected-title-contains",
            str(row.get("expected_title_contains") or ""),
            "--target-path",
            str(row.get("target_path") or ""),
            "--storage",
            str(row.get("storage") or ""),
            "--format",
            "json",
            "--output",
            "<receive-report.json>",
        ]
    )
    if row.get("browse_cid"):
        args.extend(["--browse-cid", str(row.get("browse_cid") or "")])
    if row.get("receive_mode") == "receive_selected_folder":
        args.append("--receive-selected-folder")
        args.extend(["--verified-folder-browse-report", str(row.get("verified_folder_browse_report") or "")])
    elif row.get("receive_mode") == "receive_all_files":
        args.append("--receive-all-files")
    return " ".join(_shell_quote(part) for part in args) + "  # approval required before execution"


def _title_contains(title: str) -> str:
    text = title.split(" (", 1)[0].strip() or title
    text = text.split("{tmdbid=", 1)[0].strip()
    return text or title


def _string_list(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _int_list(value: object) -> List[int]:
    if not isinstance(value, list):
        return []
    return [int(item) for item in value if isinstance(item, int) or str(item).isdigit()]


def _shell_quote(value: str) -> str:
    if value == "PYTHONPATH=src":
        return value
    return shlex.quote(value)


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|")
