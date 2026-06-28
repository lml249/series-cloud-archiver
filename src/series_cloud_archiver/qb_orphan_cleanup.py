from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Set

from .cleanup_verify import verify_strm_paths
from .episode import episode_signal, is_video_file
from .moviepilot import MoviePilotClient
from .mv3 import verify_mv3_cloud_media_sidecars
from .path_safety import cloud_media_paths, non_strm_side_paths
from .qbittorrent import QBClient


FULL_HASH_PATTERN = re.compile(r"(?i)^[a-f0-9]{32,64}$")


def preview_qb_orphan_torrent_cleanup(
    title: str,
    expected_hashes: Sequence[str],
    source_roots: Sequence[str],
    hlink_roots: Sequence[str],
    strm_roots: Sequence[str],
    expected_tmdbid: int = 0,
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
    qb_base_url: str = "",
    qb_user: str = "",
    qb_pass: str = "",
    mp_base_url: str = "",
    mp_token: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
    expected_title_contains: str = "",
    min_seed_days: int = 7,
    required_target_prefix: str = "",
    forbidden_target_prefixes: Optional[Sequence[str]] = None,
    mv3_base_url: str = "",
    mv3_token: str = "",
    cloud_media_path: str = "",
    cloud_media_folder_id: str = "",
    cloud_media_storage: str = "115-default",
    timeout: int = 20,
) -> Dict[str, object]:
    blockers: List[str] = []
    warnings: List[str] = []
    aliases = _normalize_aliases(path_aliases or {})
    hashes = _normalize_hashes(expected_hashes)
    invalid_hashes = [value for value in hashes if not FULL_HASH_PATTERN.match(value)]
    if not hashes:
        blockers.append("expected_qb_hash_required")
    if invalid_hashes:
        blockers.append("expected_qb_hash_must_be_full")
    if not source_roots:
        blockers.append("source_root_required")
    if not hlink_roots:
        blockers.append("hlink_root_required")
    if not strm_roots:
        blockers.append("strm_root_required")

    blocked_cloud_strm_roots = cloud_media_paths(strm_roots)
    blocked_non_strm_roots = non_strm_side_paths(strm_roots)
    if blocked_cloud_strm_roots or blocked_non_strm_roots:
        blockers.append("strm_root_must_be_strm_side")
        warnings.append("cloud_drive_media_is_transfer_and_strm_generation_only")

    strm_report = verify_strm_paths(
        title,
        strm_roots,
        expected_episode_count=expected_episode_count,
        expected_episode_min=expected_episode_min,
        expected_episode_max=expected_episode_max,
        required_target_prefix=required_target_prefix,
        forbidden_target_prefixes=forbidden_target_prefixes or [],
    )
    if not strm_report.get("ok"):
        blockers.extend(str(blocker) for blocker in strm_report.get("blockers", []) if blocker)
    warnings.extend(str(warning) for warning in strm_report.get("warnings", []) if warning)

    source_checks = [_media_root_check(path, require_narrow=True) for path in source_roots]
    hlink_checks = [_media_root_check(path, require_narrow=False) for path in hlink_roots]
    if any(int(item.get("video_count") or 0) > 0 for item in source_checks):
        blockers.append("source_root_contains_video_files")
    if any(item.get("exists") and not item.get("narrow") for item in source_checks):
        blockers.append("source_root_not_narrow")
    if any(int(item.get("video_count") or 0) > 0 for item in hlink_checks):
        blockers.append("hlink_root_contains_video_files")
    if any(item.get("exists") and int(item.get("non_video_count") or 0) > 0 for item in source_checks):
        warnings.append("source_root_contains_sidecar_files")
    if any(item.get("exists") and int(item.get("non_video_count") or 0) > 0 for item in hlink_checks):
        warnings.append("hlink_root_contains_sidecar_files")

    mp_report = _mp_history_absence_check(mp_base_url, mp_token, title, expected_tmdbid, timeout)
    if mp_report.get("error"):
        blockers.append("mp_transfer_history_check_failed")
    if int(mp_report.get("matched_count") or 0) > 0:
        blockers.append("mp_transfer_history_still_present_use_mp_cleanup")
    if not mp_report.get("configured"):
        warnings.append("mp_transfer_history_check_skipped")

    cloud_media_report: Dict[str, object] = {"skipped": True}
    if cloud_media_path or cloud_media_folder_id:
        if not mv3_base_url or not mv3_token:
            blockers.append("mv3_credentials_required_for_cloud_media_sidecar_verify")
            cloud_media_report = {"skipped": True, "reason": "mv3_credentials_required"}
        else:
            try:
                cloud_media_report = verify_mv3_cloud_media_sidecars(
                    mv3_base_url,
                    mv3_token,
                    path=cloud_media_path,
                    folder_id=cloud_media_folder_id,
                    storage=cloud_media_storage,
                )
            except Exception as exc:  # pragma: no cover - exercised by integration
                cloud_media_report = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
                blockers.append("cloud_media_sidecar_verify_failed")
            if cloud_media_report and not cloud_media_report.get("ok"):
                blockers.extend(str(blocker) for blocker in cloud_media_report.get("blockers", []) if blocker)
            warnings.extend(str(warning) for warning in cloud_media_report.get("warnings", []) if warning)

    qb_report = _qb_orphan_task_check(
        qb_base_url,
        qb_user,
        qb_pass,
        hashes,
        title,
        source_roots,
        aliases,
        expected_title_contains=expected_title_contains,
        min_seed_days=min_seed_days,
        timeout=timeout,
    )
    if qb_report.get("error"):
        blockers.append("qb_torrent_check_failed")
    blockers.extend(str(blocker) for blocker in qb_report.get("blockers", []) if blocker)
    warnings.extend(str(warning) for warning in qb_report.get("warnings", []) if warning)

    unique_blockers = sorted(set(blockers))
    unique_warnings = sorted(set(warnings))
    return {
        "mode": "qb-orphan-torrent-cleanup-preview",
        "title": title,
        "ok": not unique_blockers,
        "ready_for_execute": not unique_blockers and len(qb_report.get("matches", []) if isinstance(qb_report.get("matches"), list) else []) == len(hashes),
        "expected": {
            "tmdbid": expected_tmdbid,
            "qb_hashes": hashes,
            "source_roots": list(source_roots),
            "hlink_roots": list(hlink_roots),
            "strm_roots": list(strm_roots),
            "episode_count": expected_episode_count,
            "episode_min": expected_episode_min,
            "episode_max": expected_episode_max,
            "expected_title_contains": expected_title_contains or title,
            "min_seed_days": min_seed_days,
            "required_target_prefix": required_target_prefix,
            "forbidden_target_prefixes": list(forbidden_target_prefixes or []),
            "cloud_media_path": cloud_media_path,
            "cloud_media_folder_id": cloud_media_folder_id,
            "cloud_media_storage": cloud_media_storage,
        },
        "moviepilot": mp_report,
        "qbittorrent": qb_report,
        "filesystem": {
            "source_roots": source_checks,
            "hlink_roots": hlink_checks,
        },
        "strm": strm_report,
        "cloud_media": cloud_media_report,
        "blockers": unique_blockers,
        "warnings": unique_warnings,
        "safety": "readonly preview only; verifies full qB hashes, missing/no-video local roots, STRM-side completeness, optional cloud sidecar absence, and MP history absence before allowing qB task removal",
    }


def execute_qb_orphan_torrent_cleanup(
    preview: Dict[str, object],
    qb_base_url: str,
    qb_user: str = "",
    qb_pass: str = "",
    mp_base_url: str = "",
    mp_token: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
    mv3_base_url: str = "",
    mv3_token: str = "",
    timeout: int = 20,
) -> Dict[str, object]:
    blockers: List[str] = []
    if preview.get("mode") != "qb-orphan-torrent-cleanup-preview":
        blockers.append("preview_mode_not_supported")
    if not preview.get("ready_for_execute"):
        blockers.append("preview_not_ready_for_execute")
    if preview.get("blockers"):
        blockers.append("preview_has_blockers")
    if not qb_base_url:
        blockers.append("qb_base_url_required")

    expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
    hashes = _normalize_hashes(expected.get("qb_hashes", []) if isinstance(expected.get("qb_hashes"), list) else [])
    if not hashes:
        blockers.append("expected_qb_hash_required")

    current_precheck: Dict[str, object] = {}
    delete_result: Dict[str, object] = {}
    verification: Dict[str, object] = {}
    if not blockers:
        current_precheck = preview_qb_orphan_torrent_cleanup(
            str(preview.get("title") or ""),
            hashes,
            expected.get("source_roots") if isinstance(expected.get("source_roots"), list) else [],
            expected.get("hlink_roots") if isinstance(expected.get("hlink_roots"), list) else [],
            expected.get("strm_roots") if isinstance(expected.get("strm_roots"), list) else [],
            expected_tmdbid=int(expected.get("tmdbid") or 0),
            expected_episode_count=int(expected.get("episode_count") or 0),
            expected_episode_min=int(expected.get("episode_min") or 0),
            expected_episode_max=int(expected.get("episode_max") or 0),
            qb_base_url=qb_base_url,
            qb_user=qb_user,
            qb_pass=qb_pass,
            mp_base_url=mp_base_url,
            mp_token=mp_token,
            path_aliases=path_aliases,
            expected_title_contains=str(expected.get("expected_title_contains") or ""),
            min_seed_days=int(expected.get("min_seed_days") or 0),
            required_target_prefix=str(expected.get("required_target_prefix") or ""),
            forbidden_target_prefixes=expected.get("forbidden_target_prefixes") if isinstance(expected.get("forbidden_target_prefixes"), list) else [],
            mv3_base_url=mv3_base_url,
            mv3_token=mv3_token,
            cloud_media_path=str(expected.get("cloud_media_path") or ""),
            cloud_media_folder_id=str(expected.get("cloud_media_folder_id") or ""),
            cloud_media_storage=str(expected.get("cloud_media_storage") or "115-default"),
            timeout=timeout,
        )
        if not current_precheck.get("ready_for_execute"):
            blockers.append("current_precheck_not_ready_for_execute")

    if not blockers:
        try:
            client = QBClient(qb_base_url, qb_user, qb_pass, timeout=timeout)
            client.login()
            delete_result = client.delete_torrents(hashes, delete_files=False)
            if not delete_result.get("ok"):
                blockers.append("qb_delete_failed")
        except Exception as exc:  # pragma: no cover - exercised by integration
            delete_result = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
            blockers.append("qb_delete_failed")

    if not blockers:
        verification = _verify_after_qb_orphan_execute(
            preview,
            qb_base_url,
            qb_user,
            qb_pass,
            path_aliases or {},
            timeout=timeout,
        )
        if not verification.get("ok"):
            blockers.extend(str(blocker) for blocker in verification.get("blockers", []) if blocker)

    unique_blockers = sorted(set(blockers))
    return {
        "mode": "qb-orphan-torrent-cleanup-execute",
        "title": preview.get("title", ""),
        "ok": not unique_blockers,
        "approved": True,
        "delete_files": False,
        "current_precheck": current_precheck,
        "qb_delete": delete_result,
        "verification": verification,
        "blockers": unique_blockers,
        "warnings": preview.get("warnings", []) if isinstance(preview.get("warnings"), list) else [],
        "safety": "approved qB orphan task cleanup only; qB delete is called with deleteFiles=false, so content files are not deleted by qB and scraping/Emby/cloud media are not touched",
    }


def render_qb_orphan_torrent_cleanup(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    qb = report.get("qbittorrent") if isinstance(report.get("qbittorrent"), dict) else {}
    expected = report.get("expected") if isinstance(report.get("expected"), dict) else {}
    delete_result = report.get("qb_delete") if isinstance(report.get("qb_delete"), dict) else {}
    lines = [
        "# qB Orphan Torrent Cleanup",
        "",
        f"- Title: `{report.get('title', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Ready: `{bool(report.get('ready_for_execute', report.get('ok')))}`",
        f"- qB matches: `{qb.get('matched_count', len(qb.get('matches', [])) if isinstance(qb.get('matches'), list) else 0)}`",
        f"- qB hashes: `{expected.get('qb_hashes', [])}`",
        f"- Source roots: `{expected.get('source_roots', [])}`",
        f"- hlink roots: `{expected.get('hlink_roots', [])}`",
        f"- STRM roots: `{expected.get('strm_roots', [])}`",
        f"- deleteFiles: `{report.get('delete_files', False)}`",
        f"- qB delete OK: `{delete_result.get('ok', '')}`",
        "- Safety: qB task cleanup only; qB content deletion, cloud scraping, STRM scraping, and Emby refresh are not performed.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    return "\n".join(lines)


def _qb_orphan_task_check(
    qb_base_url: str,
    qb_user: str,
    qb_pass: str,
    expected_hashes: Sequence[str],
    title: str,
    source_roots: Sequence[str],
    path_aliases: Dict[str, str],
    expected_title_contains: str = "",
    min_seed_days: int = 7,
    timeout: int = 20,
) -> Dict[str, object]:
    blockers: List[str] = []
    warnings: List[str] = []
    if not qb_base_url:
        return {
            "configured": False,
            "matched_count": 0,
            "matches": [],
            "missing_hashes": list(expected_hashes),
            "blockers": ["qb_base_url_required"],
            "warnings": [],
        }
    try:
        client = QBClient(qb_base_url, qb_user, qb_pass, timeout=timeout)
        client.login()
        torrents = client.torrents()
    except Exception as exc:  # pragma: no cover - exercised by integration
        return {
            "configured": True,
            "error": f"{type(exc).__name__}:{exc}",
            "matched_count": 0,
            "matches": [],
            "missing_hashes": list(expected_hashes),
            "blockers": ["qb_torrent_check_failed"],
            "warnings": [],
        }

    by_hash = {str(item.get("hash") or "").lower(): item for item in torrents if str(item.get("hash") or "")}
    matches: List[Dict[str, object]] = []
    missing: List[str] = []
    for expected_hash in expected_hashes:
        torrent = by_hash.get(expected_hash.lower())
        if not torrent:
            missing.append(expected_hash)
            continue
        try:
            files = client.torrent_files(str(torrent.get("hash") or ""))
        except Exception:
            files = []
            warnings.append("qb_torrent_files_unavailable")
        matches.append(_qb_orphan_match_row(torrent, files, source_roots, path_aliases))

    if missing:
        blockers.append("qb_torrent_not_found")
    title_token = expected_title_contains or title
    if title_token:
        folded = title_token.casefold()
        for row in matches:
            haystack = " ".join(
                [
                    str(row.get("name") or ""),
                    str(row.get("content_path") or ""),
                    str(row.get("save_path") or ""),
                    str(row.get("host_content_path") or ""),
                ]
            ).casefold()
            if folded not in haystack:
                blockers.append("qb_torrent_title_mismatch")
                break
    if any(float(row.get("progress") or 0.0) < 0.999 for row in matches):
        blockers.append("qb_torrent_not_complete")
    if min_seed_days and any(float(row.get("seed_days") or 0.0) < min_seed_days for row in matches):
        blockers.append("qb_seed_days_below_minimum")
    if any(not row.get("paths_inside_expected_source_roots") for row in matches):
        blockers.append("qb_content_outside_expected_source_root")

    return {
        "configured": True,
        "scanned_count": len(torrents),
        "matched_count": len(matches),
        "matches": matches,
        "missing_hashes": missing,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
    }


def _qb_orphan_match_row(
    torrent: Dict[str, object],
    files: Sequence[Dict[str, object]],
    source_roots: Sequence[str],
    path_aliases: Dict[str, str],
) -> Dict[str, object]:
    seeding_seconds = int(torrent.get("seeding_time") or 0)
    torrent_hash = str(torrent.get("hash") or "")
    host_paths = _qb_file_host_paths(torrent, files, path_aliases)
    content_path = str(torrent.get("content_path") or "").rstrip("/")
    host_content_path = _map_path(content_path, path_aliases) if content_path else ""
    source_variants = {variant for root in source_roots for variant in _path_variants(root, path_aliases)}
    checked_paths = host_paths or ([host_content_path] if host_content_path else [])
    inside_expected = bool(checked_paths) and all(
        any(_path_is_same_or_child(path, root) for root in source_variants)
        for path in checked_paths
    )
    return {
        "name": str(torrent.get("name") or ""),
        "hash": torrent_hash,
        "hash_prefix": torrent_hash[:12],
        "state": str(torrent.get("state") or ""),
        "progress": float(torrent.get("progress") or 0.0),
        "seed_days": seeding_seconds / 86400.0,
        "size_bytes": int(torrent.get("size") or torrent.get("total_size") or 0),
        "save_path": str(torrent.get("save_path") or ""),
        "content_path": content_path,
        "host_content_path": host_content_path,
        "host_file_count": len(host_paths),
        "host_files_sample": host_paths[:12],
        "paths_inside_expected_source_roots": inside_expected,
    }


def _verify_after_qb_orphan_execute(
    preview: Dict[str, object],
    qb_base_url: str,
    qb_user: str,
    qb_pass: str,
    path_aliases: Dict[str, str],
    timeout: int = 20,
) -> Dict[str, object]:
    blockers: List[str] = []
    expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
    hashes = _normalize_hashes(expected.get("qb_hashes", []) if isinstance(expected.get("qb_hashes"), list) else [])
    remaining: List[Dict[str, object]] = []
    try:
        client = QBClient(qb_base_url, qb_user, qb_pass, timeout=timeout)
        client.login()
        for torrent in client.torrents():
            if str(torrent.get("hash") or "").lower() in hashes:
                remaining.append(_qb_orphan_match_row(torrent, [], [], path_aliases))
    except Exception as exc:  # pragma: no cover - exercised by integration
        blockers.append("qb_verify_failed")
        remaining.append({"error": f"{type(exc).__name__}:{exc}"})
    if remaining:
        blockers.append("qb_torrent_still_present")

    strm_roots = expected.get("strm_roots") if isinstance(expected.get("strm_roots"), list) else []
    strm_verify = verify_strm_paths(
        str(preview.get("title") or ""),
        [str(path) for path in strm_roots if path],
        expected_episode_count=int(expected.get("episode_count") or 0),
        expected_episode_min=int(expected.get("episode_min") or 0),
        expected_episode_max=int(expected.get("episode_max") or 0),
        required_target_prefix=str(expected.get("required_target_prefix") or ""),
        forbidden_target_prefixes=expected.get("forbidden_target_prefixes") if isinstance(expected.get("forbidden_target_prefixes"), list) else [],
    )
    if not strm_verify.get("ok"):
        blockers.extend(str(blocker) for blocker in strm_verify.get("blockers", []) if blocker)

    source_checks = [_media_root_check(str(path), require_narrow=True) for path in (expected.get("source_roots") if isinstance(expected.get("source_roots"), list) else [])]
    hlink_checks = [_media_root_check(str(path), require_narrow=False) for path in (expected.get("hlink_roots") if isinstance(expected.get("hlink_roots"), list) else [])]
    if any(int(item.get("video_count") or 0) > 0 for item in source_checks):
        blockers.append("source_root_contains_video_files")
    if any(int(item.get("video_count") or 0) > 0 for item in hlink_checks):
        blockers.append("hlink_root_contains_video_files")

    return {
        "ok": not blockers,
        "qb_remaining": remaining,
        "strm": strm_verify,
        "filesystem": {"source_roots": source_checks, "hlink_roots": hlink_checks},
        "blockers": sorted(set(blockers)),
    }


def _mp_history_absence_check(
    mp_base_url: str,
    mp_token: str,
    title: str,
    expected_tmdbid: int,
    timeout: int,
) -> Dict[str, object]:
    if not mp_base_url:
        return {"configured": False, "records_found": 0, "matched_count": 0, "matched_ids": []}
    try:
        records = MoviePilotClient(mp_base_url, mp_token, timeout=timeout).transfer_history(title)
    except Exception as exc:  # pragma: no cover - exercised by integration
        return {"configured": True, "error": f"{type(exc).__name__}:{exc}", "records_found": 0, "matched_count": 0, "matched_ids": []}
    matched = [
        record
        for record in records
        if (not expected_tmdbid or record.tmdbid in {0, expected_tmdbid})
        and (not title or record.title == title or title in record.title or record.title in title)
    ]
    return {
        "configured": True,
        "records_found": len(records),
        "matched_count": len(matched),
        "matched_ids": [record.id for record in matched],
    }


def _media_root_check(path: str, require_narrow: bool) -> Dict[str, object]:
    root = Path(path)
    if not root.exists():
        return {
            "path": path,
            "exists": False,
            "narrow": _is_narrow_root(root) if require_narrow else True,
            "file_count": 0,
            "video_count": 0,
            "non_video_count": 0,
            "episodes": [],
            "sample_files": [],
        }
    files = [item for item in root.rglob("*") if item.is_file()]
    videos = [item for item in files if is_video_file(item)]
    signal = episode_signal(str(item.relative_to(root)) for item in videos)
    return {
        "path": path,
        "exists": True,
        "narrow": _is_narrow_root(root) if require_narrow else True,
        "file_count": len(files),
        "video_count": len(videos),
        "non_video_count": len(files) - len(videos),
        "episodes": signal.episodes,
        "seasons": signal.seasons,
        "total_bytes": sum(item.stat().st_size for item in files if item.exists()),
        "sample_files": [str(item) for item in videos[:8]],
    }


def _qb_file_host_paths(torrent: Dict[str, object], files: Sequence[Dict[str, object]], aliases: Dict[str, str]) -> List[str]:
    save_path = str(torrent.get("save_path") or "").rstrip("/")
    content_path = str(torrent.get("content_path") or "").rstrip("/")
    paths: List[str] = []
    for item in files:
        rel_path = str(item.get("name") or "").strip("/")
        if not rel_path:
            continue
        container_path = str(PurePosixPath(save_path) / rel_path) if save_path else rel_path
        paths.append(_map_path(container_path, aliases))
    if not paths and content_path:
        paths.append(_map_path(content_path, aliases))
    return paths


def _normalize_hashes(values: Sequence[str]) -> List[str]:
    hashes: List[str] = []
    for value in values:
        for part in str(value or "").split(","):
            token = part.strip().lower()
            if token and token not in hashes:
                hashes.append(token)
    return hashes


def _normalize_aliases(path_aliases: Dict[str, str]) -> Dict[str, str]:
    return {key.rstrip("/"): value.rstrip("/") for key, value in path_aliases.items() if key and value}


def _path_variants(path: str, aliases: Dict[str, str]) -> Set[str]:
    normalized = str(path or "").rstrip("/")
    if not normalized:
        return set()
    variants = {normalized}
    for left, right in aliases.items():
        for source, target in ((left, right), (right, left)):
            if normalized == source or normalized.startswith(source + "/"):
                variants.add(target + normalized[len(source) :])
    return variants


def _map_path(path: str, aliases: Dict[str, str]) -> str:
    text = str(path or "").rstrip("/")
    for source, target in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        source = source.rstrip("/")
        target = target.rstrip("/")
        if text == source or text.startswith(source + "/"):
            return target + text[len(source) :]
    return text


def _path_is_same_or_child(path: str, parent: str) -> bool:
    return bool(path and parent and (path == parent or path.startswith(parent + "/")))


def _is_narrow_root(path: Path) -> bool:
    name = path.name.strip()
    if not name or name in {"TV", "Movies", "Movie", "hlink", "downloads", "download"}:
        return False
    return len(path.parts) >= 4
