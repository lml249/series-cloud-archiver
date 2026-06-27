from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Set

from .cleanup_verify import verify_mp_cleanup_from_services, verify_strm_paths
from .moviepilot import execute_mp_cleanup_from_preview_report, mp_cleanup_preview_from_transfer_history


def plan_cloud_complete_cleanup(
    cloud_report: Dict[str, object],
    mp_base_url: str,
    mp_token: str,
    path_aliases: Optional[Dict[str, str]] = None,
    limit: int = 0,
    titles: Optional[Sequence[str]] = None,
    timeout: int = 20,
    required_target_prefix: str = "",
    forbidden_target_prefixes: Optional[Sequence[str]] = None,
    allow_multiple_hashes: bool = False,
    allow_multiple_source_roots: bool = False,
) -> Dict[str, object]:
    title_filter = {item for item in (titles or []) if item}
    aliases = _normalize_aliases(path_aliases or {})
    candidates = [
        item
        for item in cloud_report.get("items", [])
        if isinstance(item, dict)
        and item.get("status") == "cloud_strm_complete"
        and (not title_filter or str(item.get("title") or "") in title_filter)
    ]
    candidates.sort(key=lambda item: (-int(item.get("size_bytes") or 0), str(item.get("title") or ""), int(item.get("season") or 0)))
    total_candidates = len(candidates)
    if limit > 0:
        candidates = candidates[:limit]

    items = [
        _plan_cleanup_item(
            item,
            mp_base_url=mp_base_url,
            mp_token=mp_token,
            path_aliases=aliases,
            timeout=timeout,
            required_target_prefix=required_target_prefix,
            forbidden_target_prefixes=forbidden_target_prefixes or [],
            allow_multiple_hashes=allow_multiple_hashes,
            allow_multiple_source_roots=allow_multiple_source_roots,
        )
        for item in candidates
    ]
    ready_count = sum(1 for item in items if item.get("ready_for_execute"))
    return {
        "mode": "cloud-complete-cleanup-plan",
        "source_mode": cloud_report.get("mode", ""),
        "selected_status": "cloud_strm_complete",
        "total_candidates": total_candidates,
        "planned_items": len(items),
        "ready_items": ready_count,
        "limit": limit,
        "title_filter": sorted(title_filter),
        "allow_multiple_hashes": allow_multiple_hashes,
        "allow_multiple_source_roots": allow_multiple_source_roots,
        "total_size_bytes": sum(int(item.get("size_bytes") or 0) for item in items),
        "path_aliases": aliases,
        "items": items,
        "warnings": list(cloud_report.get("warnings", [])) if isinstance(cloud_report.get("warnings"), list) else [],
        "safety": "readonly batch cleanup plan only; STRM files and MoviePilot transfer history are inspected, but no MoviePilot DELETE, qBittorrent action, or filesystem deletion is performed",
    }


def execute_cloud_complete_cleanup_plan(
    plan: Dict[str, object],
    mp_base_url: str,
    mp_token: str,
    qb_base_url: str = "",
    qb_user: str = "",
    qb_pass: str = "",
    limit: int = 0,
    titles: Optional[Sequence[str]] = None,
    timeout: int = 20,
    continue_on_error: bool = False,
) -> Dict[str, object]:
    title_filter = {item for item in (titles or []) if item}
    blockers: List[str] = []
    if plan.get("mode") != "cloud-complete-cleanup-plan":
        blockers.append("cleanup_plan_mode_not_supported")
    raw_items = [
        item
        for item in plan.get("items", [])
        if isinstance(item, dict)
        and (not title_filter or str(item.get("title") or "") in title_filter)
    ]
    if limit > 0:
        raw_items = raw_items[:limit]

    results: List[Dict[str, object]] = []
    stopped = False
    if not blockers:
        for item in raw_items:
            result = _execute_cleanup_item(
                item,
                mp_base_url=mp_base_url,
                mp_token=mp_token,
                qb_base_url=qb_base_url,
                qb_user=qb_user,
                qb_pass=qb_pass,
                timeout=timeout,
            )
            results.append(result)
            if not result.get("ok") and not continue_on_error:
                stopped = True
                break

    success_count = sum(1 for item in results if item.get("ok"))
    failure_count = sum(1 for item in results if not item.get("ok"))
    skipped_count = sum(1 for item in raw_items if not item.get("ready_for_execute"))
    return {
        "mode": "cloud-complete-cleanup-execute",
        "ok": not blockers and bool(results) and failure_count == 0,
        "approved": True,
        "summary": {
            "selected_count": len(raw_items),
            "attempted_count": len(results),
            "success_count": success_count,
            "failure_count": failure_count,
            "skipped_not_ready_count": skipped_count,
            "stopped_on_failure": stopped,
        },
        "results": results,
        "blockers": blockers,
        "safety": "approved batch MoviePilot cleanup execution; each item is executed only from a ready cloud-complete cleanup plan and then verified through MoviePilot, qBittorrent, filesystem, and STRM checks",
    }


def render_cloud_complete_cleanup_plan(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        "# Cloud Complete Cleanup Plan",
        "",
        f"- Candidates: `{report.get('total_candidates', 0)}`",
        f"- Planned: `{report.get('planned_items', 0)}`",
        f"- Ready: `{report.get('ready_items', 0)}`",
        f"- Size: `{_format_gib(int(report.get('total_size_bytes') or 0))}`",
        "- Safety: readonly batch plan only; no cleanup request was sent.",
        "",
        "| # | Title | Season | Episodes | Size | Ready | Blockers |",
        "| ---: | --- | ---: | --- | ---: | --- | --- |",
    ]
    for index, item in enumerate(report.get("items", []), start=1):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {index} | {title} | {season} | {episodes} | {size} | {ready} | {blockers} |".format(
                index=index,
                title=_escape(str(item.get("title") or "")),
                season=item.get("season") or "",
                episodes=_escape(str(item.get("expected_episodes") or [])),
                size=_format_gib(int(item.get("size_bytes") or 0)),
                ready=item.get("ready_for_execute"),
                blockers=_escape(", ".join(str(blocker) for blocker in item.get("execution_blockers", []))),
            )
        )
    return "\n".join(lines)


def render_cloud_complete_cleanup_execute(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# Cloud Complete Cleanup Execute",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Selected: `{summary.get('selected_count', 0)}`",
        f"- Attempted: `{summary.get('attempted_count', 0)}`",
        f"- Success: `{summary.get('success_count', 0)}`",
        f"- Failure: `{summary.get('failure_count', 0)}`",
        f"- Skipped not ready: `{summary.get('skipped_not_ready_count', 0)}`",
        "- Safety: approved batch MoviePilot cleanup; no direct filesystem or qBittorrent delete is performed by this tool.",
        "",
        "| # | Title | OK | Execute OK | Verify OK | Blockers |",
        "| ---: | --- | --- | --- | --- | --- |",
    ]
    for index, item in enumerate(report.get("results", []), start=1):
        if not isinstance(item, dict):
            continue
        lines.append(
            "| {index} | {title} | {ok} | {execute_ok} | {verify_ok} | {blockers} |".format(
                index=index,
                title=_escape(str(item.get("title") or "")),
                ok=item.get("ok"),
                execute_ok=(item.get("execute") or {}).get("ok") if isinstance(item.get("execute"), dict) else "",
                verify_ok=(item.get("verify") or {}).get("ok") if isinstance(item.get("verify"), dict) else "",
                blockers=_escape(", ".join(str(blocker) for blocker in item.get("blockers", []))),
            )
        )
    return "\n".join(lines)


def _plan_cleanup_item(
    item: Dict[str, object],
    mp_base_url: str,
    mp_token: str,
    path_aliases: Dict[str, str],
    timeout: int,
    required_target_prefix: str,
    forbidden_target_prefixes: Sequence[str],
    allow_multiple_hashes: bool,
    allow_multiple_source_roots: bool,
) -> Dict[str, object]:
    title = str(item.get("title") or "")
    tmdbid = int(item.get("tmdbid") or 0)
    season = int(item.get("season") or 0)
    expected_episodes = _expected_episodes(item)
    expected_count = len(expected_episodes)
    blockers: List[str] = []
    warnings: List[str] = []
    if not title:
        blockers.append("title_required")
    if not tmdbid:
        blockers.append("tmdbid_required")
    if not season:
        blockers.append("season_required")
    if not expected_episodes:
        blockers.append("expected_episodes_required")

    strm_root = _season_root_from_samples(_string_list(item.get("strm_paths_sample")), season)
    if not strm_root:
        blockers.append("strm_season_root_not_found")
    strm_report = verify_strm_paths(
        title,
        [strm_root] if strm_root else [],
        expected_episode_count=expected_count,
        expected_episode_min=min(expected_episodes) if expected_episodes else 0,
        expected_episode_max=max(expected_episodes) if expected_episodes else 0,
        required_target_prefix=required_target_prefix,
        forbidden_target_prefixes=forbidden_target_prefixes,
    )
    if not strm_report.get("ok"):
        blockers.extend(str(blocker) for blocker in strm_report.get("blockers", []) if blocker)
    warnings.extend(str(warning) for warning in strm_report.get("warnings", []) if warning)

    preview = mp_cleanup_preview_from_transfer_history(
        mp_base_url,
        mp_token,
        title=title,
        expected_title=title,
        expected_tmdbid=tmdbid,
        expected_season=season,
        timeout=timeout,
    )
    if not preview.get("ok"):
        blockers.extend(str(blocker) for blocker in preview.get("blockers", []) if blocker)
    preview_warnings = [str(warning) for warning in preview.get("warnings", []) if warning]
    warnings.extend(preview_warnings)
    summary = preview.get("summary") if isinstance(preview.get("summary"), dict) else {}
    if expected_count and int(summary.get("records_matched") or 0) != expected_count:
        blockers.append("mp_record_count_mismatch")
    if expected_count and int(summary.get("episode_count") or 0) != expected_count:
        blockers.append("mp_episode_count_mismatch")
    if expected_episodes and int(summary.get("episode_min") or 0) != min(expected_episodes):
        blockers.append("mp_episode_min_mismatch")
    if expected_episodes and int(summary.get("episode_max") or 0) != max(expected_episodes):
        blockers.append("mp_episode_max_mismatch")
    if summary.get("missing_in_range"):
        blockers.append("mp_episode_gap_detected")
    if int(summary.get("download_hash_count") or 0) != 1 and not allow_multiple_hashes:
        blockers.append("mp_single_hash_required")
    if int(summary.get("source_root_count") or 0) != 1 and not allow_multiple_source_roots:
        blockers.append("mp_single_source_root_required")
    if int(summary.get("destination_root_count") or 0) != 1:
        blockers.append("mp_single_destination_root_required")

    source_roots_service = _string_list(preview.get("source_roots"))
    destination_roots_service = _string_list(preview.get("destination_roots"))
    source_roots_host = [_service_to_host_path(path, path_aliases) for path in source_roots_service]
    destination_roots_host = [_service_to_host_path(path, path_aliases) for path in destination_roots_service]
    cloud_source_paths = _string_list(item.get("source_paths"))
    if cloud_source_paths and destination_roots_host and not set(_normalize_paths(destination_roots_host)).intersection(_normalize_paths(cloud_source_paths)):
        blockers.append("mp_destination_root_not_in_cloud_source_paths")

    qb_targets = [target for target in preview.get("qb_targets", []) if isinstance(target, dict)]
    expected_hash_prefix = str(qb_targets[0].get("hash_prefix") or "") if len(qb_targets) == 1 else ""
    expected_hash_prefixes = [str(target.get("hash_prefix") or "") for target in qb_targets if target.get("hash_prefix")]

    return {
        "title": title,
        "tmdbid": tmdbid,
        "season": season,
        "size_bytes": int(item.get("size_bytes") or 0),
        "expected_episodes": expected_episodes,
        "expected_episode_count": expected_count,
        "expected_episode_min": min(expected_episodes) if expected_episodes else 0,
        "expected_episode_max": max(expected_episodes) if expected_episodes else 0,
        "source_paths": cloud_source_paths,
        "strm_root": strm_root,
        "mp_preview": preview,
        "mp_summary": summary,
        "expected_hash_prefix": expected_hash_prefix,
        "expected_hash_prefixes": expected_hash_prefixes,
        "source_roots_service": source_roots_service,
        "destination_roots_service": destination_roots_service,
        "source_roots_host": source_roots_host,
        "destination_roots_host": destination_roots_host,
        "ready_for_execute": not blockers,
        "execution_blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "allow_multiple_hashes": allow_multiple_hashes,
        "allow_multiple_source_roots": allow_multiple_source_roots,
    }


def _execute_cleanup_item(
    item: Dict[str, object],
    mp_base_url: str,
    mp_token: str,
    qb_base_url: str,
    qb_user: str,
    qb_pass: str,
    timeout: int,
) -> Dict[str, object]:
    blockers: List[str] = []
    if not item.get("ready_for_execute"):
        blockers.append("cleanup_item_not_ready")
    preview = item.get("mp_preview") if isinstance(item.get("mp_preview"), dict) else {}
    if not preview:
        blockers.append("mp_preview_required")
    result: Dict[str, object] = {
        "title": item.get("title", ""),
        "tmdbid": item.get("tmdbid", 0),
        "season": item.get("season", 0),
        "ok": False,
        "execute": {},
        "verify": {},
        "blockers": blockers,
    }
    if blockers:
        return result

    execute_report = execute_mp_cleanup_from_preview_report(
        mp_base_url,
        mp_token,
        preview,
        expected_title=str(item.get("title") or ""),
        expected_tmdbid=int(item.get("tmdbid") or 0),
        expected_hash_prefix=str(item.get("expected_hash_prefix") or ""),
        expected_hash_prefixes=_string_list(item.get("expected_hash_prefixes")),
        expected_season=int(item.get("season") or 0),
        expected_record_count=int(item.get("expected_episode_count") or 0),
        expected_episode_count=int(item.get("expected_episode_count") or 0),
        expected_episode_min=int(item.get("expected_episode_min") or 0),
        expected_episode_max=int(item.get("expected_episode_max") or 0),
        expected_episodes=item.get("expected_episodes") if isinstance(item.get("expected_episodes"), list) else None,
        timeout=timeout,
        allow_multiple_hashes=bool(item.get("allow_multiple_hashes")),
        allow_multiple_source_roots=bool(item.get("allow_multiple_source_roots")),
    )
    result["execute"] = execute_report
    if not execute_report.get("ok"):
        result["blockers"] = sorted(set(blockers + ["mp_cleanup_execute_failed"]))
        return result

    verify_report = verify_mp_cleanup_from_services(
        mp_base_url,
        mp_token,
        title=str(item.get("title") or ""),
        expected_title=str(item.get("title") or ""),
        expected_tmdbid=int(item.get("tmdbid") or 0),
        expected_hash_prefix=str(item.get("expected_hash_prefix") or ""),
        expected_hash_prefixes=_string_list(item.get("expected_hash_prefixes")),
        expected_season=int(item.get("season") or 0),
        source_roots=_string_list(item.get("source_roots_host")),
        destination_roots=_string_list(item.get("destination_roots_host")),
        strm_roots=[str(item.get("strm_root") or "")],
        expected_episode_count=int(item.get("expected_episode_count") or 0),
        expected_episode_min=int(item.get("expected_episode_min") or 0),
        expected_episode_max=int(item.get("expected_episode_max") or 0),
        qb_base_url=qb_base_url,
        qb_user=qb_user,
        qb_pass=qb_pass,
        timeout=timeout,
    )
    verify_blockers = [str(blocker) for blocker in verify_report.get("blockers", [])]
    for prefix in _string_list(item.get("expected_hash_prefixes")):
        if _qb_hash_present(verify_report, prefix):
            verify_blockers.append(f"qb_torrent_still_present:{prefix}")
    result["verify"] = verify_report
    result["ok"] = bool(verify_report.get("ok")) and not verify_blockers
    result["blockers"] = sorted(set(blockers + verify_blockers))
    return result


def _season_root_from_samples(samples: Sequence[str], season: int) -> str:
    for sample in samples:
        root = _season_root_from_sample(sample, season)
        if root:
            return root
    return ""


def _season_root_from_sample(sample: str, season: int) -> str:
    if not sample:
        return ""
    parts = PurePosixPath(sample).parts
    wanted = f"{season:02d}"
    for index, part in enumerate(parts):
        normalized = part.strip().casefold().replace(" ", "")
        if normalized in {f"season{season}", f"season{wanted}"}:
            return str(PurePosixPath(*parts[: index + 1]))
    return str(PurePosixPath(sample).parent)


def _expected_episodes(item: Dict[str, object]) -> List[int]:
    episodes = _int_list(item.get("expected_episodes"))
    if episodes:
        return episodes
    expected_count = int(item.get("expected_count") or 0)
    if expected_count > 0:
        return list(range(1, expected_count + 1))
    return []


def _normalize_aliases(path_aliases: Dict[str, str]) -> Dict[str, str]:
    return {key.rstrip("/"): value.rstrip("/") for key, value in path_aliases.items() if key and value}


def _service_to_host_path(path: str, path_aliases: Dict[str, str]) -> str:
    normalized = str(path or "").rstrip("/")
    for host_prefix, service_prefix in sorted(path_aliases.items(), key=lambda item: len(item[1]), reverse=True):
        if normalized == service_prefix or normalized.startswith(service_prefix + "/"):
            return host_prefix + normalized[len(service_prefix) :]
    return normalized


def _normalize_paths(paths: Sequence[str]) -> Set[str]:
    return {str(path or "").rstrip("/") for path in paths if path}


def _qb_hash_present(verify_report: Dict[str, object], hash_prefix: str) -> bool:
    qb = verify_report.get("qbittorrent") if isinstance(verify_report.get("qbittorrent"), dict) else {}
    matches = qb.get("matches") if isinstance(qb.get("matches"), list) else []
    wanted = hash_prefix.lower()
    return any(str(item.get("hash_prefix") or "").lower().startswith(wanted) for item in matches if isinstance(item, dict))


def _int_list(value: object) -> List[int]:
    if not isinstance(value, list):
        return []
    return sorted({int(item) for item in value if int(item) > 0})


def _string_list(value: object) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _format_gib(size_bytes: int) -> str:
    return f"{size_bytes / 1024 ** 3:.2f} GiB"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
