from __future__ import annotations

import json
from collections import Counter
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

from .reporting import human_size
from .transfer_plan import DEFAULT_CLOUD_ROOT, DEFAULT_STRM_ROOT


AUTO_TRANSFER = "auto_ready_for_transfer_preview"
AUTO_CLEANUP = "auto_ready_for_validation_cleanup"
MANUAL_REVIEW = "manual_review"
SKIPPED = "skipped"


def build_batch_plan(
    *,
    cloud_report: Dict[str, object],
    transfer_plan: Optional[Dict[str, object]] = None,
    share_search_plan: Optional[Dict[str, object]] = None,
    share_search_plans: Optional[Sequence[Dict[str, object]]] = None,
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
    scan_by_key = _scan_candidates_by_identity((scan_report or {}).get("candidates", []))
    forbidden = [str(item) for item in (forbidden_target_prefixes or []) if str(item)]

    rows: List[Dict[str, object]] = []
    for item in cloud_items:
        key = _identity_key(item)
        transfer_item = transfer_by_key.get(key, {})
        share_item = share_by_key.get(key, {})
        scan_candidates = scan_by_key.get(key, [])
        rows.append(
            _batch_item(
                item,
                transfer_item,
                share_item,
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
    return _render_markdown(plan)


def _batch_item(
    cloud_item: Dict[str, object],
    transfer_item: Dict[str, object],
    share_item: Dict[str, object],
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
    strm_root = _strm_root_from_cloud_item(cloud_item, host_strm_root)
    cloud_media_path = _cloud_media_path(cloud_root, title, tmdbid, season)

    blockers: List[str] = []
    review_reasons: List[str] = []
    bucket = MANUAL_REVIEW
    next_actions: List[Dict[str, object]] = []

    if status == "cloud_strm_complete":
        if not strm_root:
            review_reasons.append("cloud_complete_but_strm_root_unknown")
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
        "merged_duplicate_count": int(share_item.get("merged_duplicate_count") or 0),
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
                f'--strm-root "{strm_root}" --format json --output <nfo-language-audit.json>'
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


def _host_strm_path_from_cloud(cloud_media_path: str, mv3_strm_root: str) -> str:
    suffix = cloud_media_path.strip("/")
    for prefix in ("已整理/", "未整理/"):
        if suffix.startswith(prefix):
            suffix = suffix[len(prefix) :]
            break
    return f"{mv3_strm_root.rstrip('/')}/{suffix}"


def _map_strm_root(path: str, host_strm_root: str, emby_strm_root: str) -> str:
    if host_strm_root and emby_strm_root:
        left = host_strm_root.rstrip("/")
        if path == left:
            return emby_strm_root.rstrip("/")
        if path.startswith(left + "/"):
            return emby_strm_root.rstrip("/") + path[len(left) :]
    return path


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


def _int_list(value: object) -> List[int]:
    if not isinstance(value, list):
        return []
    return [int(item) for item in value if isinstance(item, int) or str(item).isdigit()]


def _env_arg(env_file: str) -> str:
    return f'--env-file "{env_file}" ' if env_file else ""


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
