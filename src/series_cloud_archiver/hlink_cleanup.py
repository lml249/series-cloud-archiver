from __future__ import annotations

import json
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .cleanup_verify import verify_strm_paths
from .episode import episode_signal, is_video_file
from .models import EpisodeSignal, FileSystemSeries
from .mv3 import verify_mv3_cloud_media_sidecars
from .qbittorrent import QBClient, fetch_qb_evidence, match_torrent


MIN_SIZE_ONLY_INODE_MATCH_BYTES = 64 * 1024 * 1024


def preview_cloud_hlink_cleanup(
    title: str,
    hlink_root: str,
    strm_root: str,
    expected_tmdbid: int = 0,
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
    qb_base_url: str = "",
    qb_user: str = "",
    qb_pass: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
    min_seed_days: int = 7,
    required_target_prefix: str = "",
    forbidden_target_prefixes: Optional[Sequence[str]] = None,
    mv3_base_url: str = "",
    mv3_token: str = "",
    cloud_media_path: str = "",
    cloud_media_folder_id: str = "",
    cloud_media_storage: str = "115-default",
) -> Dict[str, object]:
    aliases = _normalize_aliases(path_aliases or {})
    blockers: List[str] = []
    warnings: List[str] = []
    hlink_check = _hlink_root_check(hlink_root)
    if not hlink_check.get("exists"):
        blockers.append("hlink_root_missing")
    if hlink_check.get("non_video_count"):
        warnings.append("hlink_root_contains_non_video_files")
    hlink_episode_coverage = _single_season_hlink_episode_coverage(
        hlink_root,
        expected_episode_count,
        expected_episode_min,
        expected_episode_max,
    )
    blockers.extend(str(blocker) for blocker in hlink_episode_coverage.get("blockers", []) if blocker)
    warnings.extend(str(warning) for warning in hlink_episode_coverage.get("warnings", []) if warning)

    strm_report = verify_strm_paths(
        title,
        [strm_root],
        expected_episode_count=expected_episode_count,
        expected_episode_min=expected_episode_min,
        expected_episode_max=expected_episode_max,
        required_target_prefix=required_target_prefix,
        forbidden_target_prefixes=forbidden_target_prefixes or [],
    )
    if not strm_report.get("ok"):
        blockers.extend(str(blocker) for blocker in strm_report.get("blockers", []) if blocker)
    warnings.extend(str(warning) for warning in strm_report.get("warnings", []) if warning)

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

    qb_matches: List[Dict[str, object]] = []
    qb_error = ""
    if not qb_base_url:
        blockers.append("qb_base_url_required")
    else:
        try:
            torrents = fetch_qb_evidence(qb_base_url, qb_user, qb_pass)
            fs_series = _filesystem_series_from_hlink(title, hlink_root, hlink_check)
            seen_hashes: Set[str] = set()
            best = match_torrent(fs_series, torrents, aliases)
            if best:
                best_row = _qb_evidence_row(best, hlink_root, aliases)
                qb_matches.append(best_row)
                if best_row.get("hash"):
                    seen_hashes.add(str(best_row.get("hash")))
            candidates = _candidate_torrents_for_inode_check(torrents, fs_series)
            qb_matches.extend(_inode_qb_matches(candidates, hlink_check, aliases, seen_hashes))
            if qb_matches and not _matches_cover_hlink(qb_matches, hlink_check):
                # Title matching can choose the wrong season when the real qB task uses
                # an English release name. Fall back to inode matching across qB roots,
                # then discard title-only matches that do not link to this hlink root.
                qb_matches.extend(_inode_qb_matches(torrents, hlink_check, aliases, seen_hashes))
                qb_matches = _prefer_linked_qb_matches(qb_matches, hlink_check)
        except Exception as exc:  # pragma: no cover - exercised by integration
            qb_error = f"{type(exc).__name__}:{exc}"
            blockers.append("qb_torrent_check_failed")
    qb_hashes = sorted({str(row.get("hash") or "") for row in qb_matches if row.get("hash")})
    if not qb_matches:
        blockers.append("qb_match_required")
    if any(float(row.get("progress") or 0.0) < 0.999 for row in qb_matches):
        blockers.append("qb_torrent_not_complete")
    if any(float(row.get("seed_days") or 0.0) < min_seed_days for row in qb_matches):
        blockers.append("qb_seed_days_below_minimum")

    source_checks = [_source_match_check(row, hlink_check) for row in qb_matches]
    if any(check.get("blocked") for check in source_checks):
        blockers.append("source_root_check_failed")
    hlink_coverage = _hlink_source_coverage(source_checks, hlink_check)
    if qb_matches and hlink_check.get("exists") and not hlink_coverage.get("complete"):
        blockers.append("source_hlink_coverage_incomplete")

    return {
        "mode": "cloud-hlink-cleanup-preview",
        "title": title,
        "expected": {
            "tmdbid": expected_tmdbid,
            "episode_count": expected_episode_count,
            "episode_min": expected_episode_min,
            "episode_max": expected_episode_max,
            "min_seed_days": min_seed_days,
            "required_target_prefix": required_target_prefix,
            "forbidden_target_prefixes": list(forbidden_target_prefixes or []),
            "cloud_media_path": cloud_media_path,
            "cloud_media_folder_id": cloud_media_folder_id,
            "cloud_media_storage": cloud_media_storage,
        },
        "ok": not blockers,
        "ready_for_execute": not blockers,
        "hlink": hlink_check,
        "strm": strm_report,
        "cloud_media": cloud_media_report,
        "qbittorrent": {
            "configured": bool(qb_base_url),
            "error": qb_error,
            "matched_count": len(qb_matches),
            "hashes": qb_hashes,
            "matches": qb_matches,
        },
        "filesystem": {
            "source_roots": source_checks,
            "hlink_coverage": hlink_coverage,
            "hlink_episode_coverage": hlink_episode_coverage,
        },
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": "readonly preview only; no qBittorrent action and no filesystem deletion is performed",
    }


def preview_cloud_hlink_orphan_cleanup(
    title: str,
    hlink_root: str,
    strm_root: str,
    expected_tmdbid: int = 0,
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
    qb_base_url: str = "",
    qb_user: str = "",
    qb_pass: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
    required_target_prefix: str = "",
    forbidden_target_prefixes: Optional[Sequence[str]] = None,
    mv3_base_url: str = "",
    mv3_token: str = "",
    cloud_media_path: str = "",
    cloud_media_folder_id: str = "",
    cloud_media_storage: str = "115-default",
) -> Dict[str, object]:
    aliases = _normalize_aliases(path_aliases or {})
    blockers: List[str] = []
    warnings: List[str] = []
    hlink_check = _hlink_root_check(hlink_root)
    if not hlink_check.get("exists"):
        blockers.append("hlink_root_missing")
    if hlink_check.get("non_video_count"):
        warnings.append("hlink_root_contains_non_video_files")
    hlink_episode_coverage = _single_season_hlink_episode_coverage(
        hlink_root,
        expected_episode_count,
        expected_episode_min,
        expected_episode_max,
    )
    blockers.extend(str(blocker) for blocker in hlink_episode_coverage.get("blockers", []) if blocker)
    warnings.extend(str(warning) for warning in hlink_episode_coverage.get("warnings", []) if warning)

    strm_report = verify_strm_paths(
        title,
        [strm_root],
        expected_episode_count=expected_episode_count,
        expected_episode_min=expected_episode_min,
        expected_episode_max=expected_episode_max,
        required_target_prefix=required_target_prefix,
        forbidden_target_prefixes=forbidden_target_prefixes or [],
    )
    if not strm_report.get("ok"):
        blockers.extend(str(blocker) for blocker in strm_report.get("blockers", []) if blocker)
    warnings.extend(str(warning) for warning in strm_report.get("warnings", []) if warning)

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

    qb_matches: List[Dict[str, object]] = []
    qb_error = ""
    qb_scanned_count = 0
    if not qb_base_url:
        blockers.append("qb_base_url_required")
    else:
        try:
            qb_scan = _precise_qb_file_inode_matches(qb_base_url, qb_user, qb_pass, hlink_check, aliases)
            qb_scanned_count = int(qb_scan.get("scanned_count") or 0)
            qb_matches = qb_scan.get("matches", []) if isinstance(qb_scan.get("matches"), list) else []
        except Exception as exc:  # pragma: no cover - exercised by integration
            qb_error = f"{type(exc).__name__}:{exc}"
            blockers.append("qb_torrent_check_failed")
    if qb_matches:
        blockers.append("qb_linked_torrent_present")

    source_checks = [_precise_qb_source_check(row) for row in qb_matches]
    hlink_coverage = _hlink_source_coverage(source_checks, hlink_check)

    return {
        "mode": "cloud-hlink-orphan-cleanup-preview",
        "title": title,
        "expected": {
            "tmdbid": expected_tmdbid,
            "episode_count": expected_episode_count,
            "episode_min": expected_episode_min,
            "episode_max": expected_episode_max,
            "required_target_prefix": required_target_prefix,
            "forbidden_target_prefixes": list(forbidden_target_prefixes or []),
            "cloud_media_path": cloud_media_path,
            "cloud_media_folder_id": cloud_media_folder_id,
            "cloud_media_storage": cloud_media_storage,
        },
        "ok": not blockers,
        "ready_for_execute": not blockers,
        "hlink": hlink_check,
        "strm": strm_report,
        "cloud_media": cloud_media_report,
        "qbittorrent": {
            "configured": bool(qb_base_url),
            "error": qb_error,
            "scanned_count": qb_scanned_count,
            "linked_count": len(qb_matches),
            "hashes": sorted({str(row.get("hash") or "") for row in qb_matches if row.get("hash")}),
            "matches": qb_matches,
        },
        "filesystem": {
            "source_roots": source_checks,
            "hlink_coverage": hlink_coverage,
            "hlink_episode_coverage": hlink_episode_coverage,
        },
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": "readonly preview only; verifies STRM replacement and scans qBittorrent's per-torrent file lists by inode before allowing hlink-only cleanup",
    }


def preview_cloud_hlink_orphan_multiseason_cleanup(
    title: str,
    hlink_root: str,
    season_specs: Sequence[Dict[str, object]],
    expected_tmdbid: int = 0,
    qb_base_url: str = "",
    qb_user: str = "",
    qb_pass: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
    required_target_prefix: str = "",
    forbidden_target_prefixes: Optional[Sequence[str]] = None,
    mv3_base_url: str = "",
    mv3_token: str = "",
    cloud_media_path: str = "",
    cloud_media_folder_id: str = "",
    cloud_media_storage: str = "115-default",
) -> Dict[str, object]:
    aliases = _normalize_aliases(path_aliases or {})
    blockers: List[str] = []
    warnings: List[str] = []
    specs, spec_blockers = _normalize_multiseason_specs(season_specs)
    blockers.extend(spec_blockers)
    if not specs:
        blockers.append("season_spec_required")

    hlink_check = _hlink_root_check(hlink_root)
    if not hlink_check.get("exists"):
        blockers.append("hlink_root_missing")
    if hlink_check.get("non_video_count"):
        warnings.append("hlink_root_contains_non_video_files")

    hlink_episodes = _hlink_episode_map(hlink_root)
    if hlink_episodes.get("unmatched_count"):
        blockers.append("hlink_episode_signal_missing")
    if hlink_episodes.get("duplicate_episode_pairs"):
        warnings.append("hlink_duplicate_episode_files")

    specs_by_season = {int(spec.get("season") or 0): spec for spec in specs}
    strm_seasons: List[Dict[str, object]] = []
    strm_episode_sets: Dict[int, Set[int]] = {}
    for spec in specs:
        season = int(spec.get("season") or 0)
        expected_episodes = [int(item) for item in spec.get("expected_episodes", []) if int(item) > 0] if isinstance(spec.get("expected_episodes"), list) else []
        verify_count = 0 if expected_episodes else int(spec.get("expected_episode_count") or 0)
        verify_min = 0 if expected_episodes else int(spec.get("expected_episode_min") or 0)
        verify_max = 0 if expected_episodes else int(spec.get("expected_episode_max") or 0)
        strm_report = verify_strm_paths(
            title,
            [str(spec.get("strm_root") or "")],
            expected_episode_count=verify_count,
            expected_episode_min=verify_min,
            expected_episode_max=verify_max,
            required_target_prefix=required_target_prefix,
            forbidden_target_prefixes=forbidden_target_prefixes or [],
        )
        combined = strm_report.get("strm", {}).get("combined", {}) if isinstance(strm_report.get("strm"), dict) else {}
        strm_episodes = sorted({int(item) for item in combined.get("episodes", []) if isinstance(item, int) and int(item) > 0}) if isinstance(combined.get("episodes"), list) else []
        strm_episode_sets[season] = set(strm_episodes)
        missing_expected = [episode for episode in expected_episodes if episode not in strm_episode_sets[season]]
        if missing_expected:
            blockers.append("strm_expected_episodes_missing")
        if not strm_report.get("ok"):
            blockers.extend(str(blocker) for blocker in strm_report.get("blockers", []) if blocker)
        warnings.extend(str(warning) for warning in strm_report.get("warnings", []) if warning)
        strm_seasons.append(
            {
                "season": season,
                "strm_root": str(spec.get("strm_root") or ""),
                "expected_episode_count": int(spec.get("expected_episode_count") or 0),
                "expected_episode_min": int(spec.get("expected_episode_min") or 0),
                "expected_episode_max": int(spec.get("expected_episode_max") or 0),
                "expected_episodes": expected_episodes,
                "missing_expected_episodes": missing_expected,
                "episodes": strm_episodes,
                "report": strm_report,
            }
        )

    hlink_missing_in_strm: List[Dict[str, object]] = []
    hlink_season_not_covered: List[int] = []
    for season_row in hlink_episodes.get("seasons", []) if isinstance(hlink_episodes.get("seasons"), list) else []:
        if not isinstance(season_row, dict):
            continue
        season = int(season_row.get("season") or 0)
        episodes = [int(item) for item in season_row.get("episodes", []) if int(item) > 0] if isinstance(season_row.get("episodes"), list) else []
        if season not in specs_by_season:
            hlink_season_not_covered.append(season)
            continue
        missing = [episode for episode in episodes if episode not in strm_episode_sets.get(season, set())]
        if missing:
            hlink_missing_in_strm.append({"season": season, "episodes": missing})
    if hlink_season_not_covered:
        blockers.append("hlink_season_not_covered_by_strm_specs")
    if hlink_missing_in_strm:
        blockers.append("strm_missing_hlink_episodes")

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

    qb_matches: List[Dict[str, object]] = []
    qb_error = ""
    qb_scanned_count = 0
    if not qb_base_url:
        blockers.append("qb_base_url_required")
    else:
        try:
            qb_scan = _precise_qb_file_inode_matches(qb_base_url, qb_user, qb_pass, hlink_check, aliases)
            qb_scanned_count = int(qb_scan.get("scanned_count") or 0)
            qb_matches = qb_scan.get("matches", []) if isinstance(qb_scan.get("matches"), list) else []
        except Exception as exc:  # pragma: no cover - exercised by integration
            qb_error = f"{type(exc).__name__}:{exc}"
            blockers.append("qb_torrent_check_failed")
    if qb_matches:
        blockers.append("qb_linked_torrent_present")

    source_checks = [_precise_qb_source_check(row) for row in qb_matches]
    hlink_coverage = _hlink_source_coverage(source_checks, hlink_check)
    hlink_strm_coverage = {
        "complete": not hlink_missing_in_strm and not hlink_season_not_covered and not hlink_episodes.get("unmatched_count"),
        "missing": hlink_missing_in_strm,
        "uncovered_seasons": sorted(set(hlink_season_not_covered)),
    }

    return {
        "mode": "cloud-hlink-orphan-multiseason-cleanup-preview",
        "title": title,
        "expected": {
            "tmdbid": expected_tmdbid,
            "seasons": specs,
            "required_target_prefix": required_target_prefix,
            "forbidden_target_prefixes": list(forbidden_target_prefixes or []),
            "cloud_media_path": cloud_media_path,
            "cloud_media_folder_id": cloud_media_folder_id,
            "cloud_media_storage": cloud_media_storage,
        },
        "ok": not blockers,
        "ready_for_execute": not blockers,
        "hlink": hlink_check,
        "hlink_episodes": hlink_episodes,
        "strm_seasons": strm_seasons,
        "cloud_media": cloud_media_report,
        "qbittorrent": {
            "configured": bool(qb_base_url),
            "error": qb_error,
            "scanned_count": qb_scanned_count,
            "linked_count": len(qb_matches),
            "hashes": sorted({str(row.get("hash") or "") for row in qb_matches if row.get("hash")}),
            "matches": qb_matches,
        },
        "filesystem": {
            "source_roots": source_checks,
            "hlink_coverage": hlink_coverage,
            "hlink_strm_coverage": hlink_strm_coverage,
        },
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": "readonly multiseason hlink-only preview; verifies each STRM season, checks every local hlink episode is covered by STRM, confirms cloud media has no metadata sidecars, and scans qBittorrent file lists by inode before allowing one explicit hlink root cleanup",
    }


def preview_cloud_source_orphan_cleanup(
    title: str,
    source_root: str,
    strm_root: str,
    expected_tmdbid: int = 0,
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
    qb_base_url: str = "",
    qb_user: str = "",
    qb_pass: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
    required_target_prefix: str = "",
    forbidden_target_prefixes: Optional[Sequence[str]] = None,
    mv3_base_url: str = "",
    mv3_token: str = "",
    cloud_media_path: str = "",
    cloud_media_folder_id: str = "",
    cloud_media_storage: str = "115-default",
) -> Dict[str, object]:
    aliases = _normalize_aliases(path_aliases or {})
    blockers: List[str] = []
    warnings: List[str] = []
    source_check = _source_root_check(source_root)
    if not source_check.get("exists"):
        blockers.append("source_root_missing")
    if source_check.get("non_video_count"):
        warnings.append("source_root_contains_non_video_files")
    if source_check.get("video_count") != expected_episode_count and expected_episode_count:
        blockers.append("source_video_count_mismatch")
    if source_check.get("exists") and not source_check.get("narrow"):
        blockers.append("source_root_not_narrow")
    if expected_episode_count and int(source_check.get("video_count") or 0) > 0:
        expected_episodes = set(range(expected_episode_min, expected_episode_max + 1))
        source_episodes = {int(item) for item in source_check.get("episodes", []) if int(item) > 0} if isinstance(source_check.get("episodes"), list) else set()
        if not source_episodes:
            blockers.append("source_episode_signal_missing")
        elif source_episodes != expected_episodes:
            blockers.append("source_episode_set_mismatch")

    strm_report = verify_strm_paths(
        title,
        [strm_root],
        expected_episode_count=expected_episode_count,
        expected_episode_min=expected_episode_min,
        expected_episode_max=expected_episode_max,
        required_target_prefix=required_target_prefix,
        forbidden_target_prefixes=forbidden_target_prefixes or [],
    )
    if not strm_report.get("ok"):
        blockers.extend(str(blocker) for blocker in strm_report.get("blockers", []) if blocker)
    warnings.extend(str(warning) for warning in strm_report.get("warnings", []) if warning)

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

    inode_matches: List[Dict[str, object]] = []
    path_matches: List[Dict[str, object]] = []
    qb_error = ""
    qb_scanned_count = 0
    if not qb_base_url:
        blockers.append("qb_base_url_required")
    else:
        try:
            qb_scan = _precise_qb_file_inode_matches(qb_base_url, qb_user, qb_pass, source_check, aliases)
            qb_scanned_count = int(qb_scan.get("scanned_count") or 0)
            inode_matches = qb_scan.get("matches", []) if isinstance(qb_scan.get("matches"), list) else []
            path_scan = _qb_source_path_matches(qb_base_url, qb_user, qb_pass, source_root, aliases)
            qb_scanned_count = max(qb_scanned_count, int(path_scan.get("scanned_count") or 0))
            path_matches = path_scan.get("matches", []) if isinstance(path_scan.get("matches"), list) else []
        except Exception as exc:  # pragma: no cover - exercised by integration
            qb_error = f"{type(exc).__name__}:{exc}"
            blockers.append("qb_torrent_check_failed")
    qb_matches = _merge_qb_match_rows(inode_matches + path_matches)
    if qb_matches:
        blockers.append("qb_linked_torrent_present")

    return {
        "mode": "cloud-source-orphan-cleanup-preview",
        "title": title,
        "expected": {
            "tmdbid": expected_tmdbid,
            "episode_count": expected_episode_count,
            "episode_min": expected_episode_min,
            "episode_max": expected_episode_max,
            "required_target_prefix": required_target_prefix,
            "forbidden_target_prefixes": list(forbidden_target_prefixes or []),
            "cloud_media_path": cloud_media_path,
            "cloud_media_folder_id": cloud_media_folder_id,
            "cloud_media_storage": cloud_media_storage,
        },
        "ok": not blockers,
        "ready_for_execute": not blockers,
        "source": source_check,
        "strm": strm_report,
        "cloud_media": cloud_media_report,
        "qbittorrent": {
            "configured": bool(qb_base_url),
            "error": qb_error,
            "scanned_count": qb_scanned_count,
            "linked_count": len(qb_matches),
            "hashes": sorted({str(row.get("hash") or "") for row in qb_matches if row.get("hash")}),
            "matches": qb_matches,
        },
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": "readonly preview only; verifies STRM replacement, checks cloud media has no metadata sidecars, and scans qBittorrent before allowing one explicit orphan source root cleanup",
    }


def execute_cloud_hlink_cleanup(
    preview: Dict[str, object],
    qb_base_url: str,
    qb_user: str = "",
    qb_pass: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
    mv3_base_url: str = "",
    mv3_token: str = "",
    timeout: int = 20,
) -> Dict[str, object]:
    blockers: List[str] = []
    if preview.get("mode") != "cloud-hlink-cleanup-preview":
        blockers.append("preview_mode_not_supported")
    if not preview.get("ready_for_execute"):
        blockers.append("preview_not_ready_for_execute")
    if preview.get("blockers"):
        blockers.append("preview_has_blockers")
    if not qb_base_url:
        blockers.append("qb_base_url_required")

    qb = preview.get("qbittorrent") if isinstance(preview.get("qbittorrent"), dict) else {}
    hashes = [str(item) for item in qb.get("hashes", []) if str(item)] if isinstance(qb.get("hashes"), list) else []
    if not hashes:
        blockers.append("qb_hash_required")
    hlink = preview.get("hlink") if isinstance(preview.get("hlink"), dict) else {}
    hlink_root = str(hlink.get("path") or "")
    if not hlink_root:
        blockers.append("hlink_root_required")

    expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
    cloud_media_path = str(expected.get("cloud_media_path") or "")
    cloud_media_folder_id = str(expected.get("cloud_media_folder_id") or "")
    cloud_media_storage = str(expected.get("cloud_media_storage") or "115-default")
    current_cloud_media: Dict[str, object] = {"skipped": True}
    if (cloud_media_path or cloud_media_folder_id) and not blockers:
        if not mv3_base_url or not mv3_token:
            current_cloud_media = {"skipped": True, "reason": "mv3_credentials_required"}
            blockers.append("mv3_credentials_required_for_cloud_media_sidecar_verify")
        else:
            try:
                current_cloud_media = verify_mv3_cloud_media_sidecars(
                    mv3_base_url,
                    mv3_token,
                    path=cloud_media_path,
                    folder_id=cloud_media_folder_id,
                    storage=cloud_media_storage,
                )
            except Exception as exc:  # pragma: no cover - exercised by integration
                current_cloud_media = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
                blockers.append("cloud_media_sidecar_verify_failed")
            if current_cloud_media and not current_cloud_media.get("ok"):
                blockers.extend(str(blocker) for blocker in current_cloud_media.get("blockers", []) if blocker)

    delete_result: Dict[str, object] = {}
    removed_hlink: Dict[str, object] = {}
    aliases = _normalize_aliases(path_aliases or {})
    if not blockers:
        try:
            client = QBClient(qb_base_url, qb_user, qb_pass, timeout=timeout)
            client.login()
            delete_result = client.delete_torrents(hashes, delete_files=True)
            if not delete_result.get("ok"):
                blockers.append("qb_delete_failed")
        except Exception as exc:  # pragma: no cover - exercised by integration
            delete_result = {"ok": False, "error": f"{type(exc).__name__}:{exc}"}
            blockers.append("qb_delete_failed")

    if not blockers:
        removed_hlink = _remove_hlink_root(hlink_root)
        if not removed_hlink.get("ok"):
            blockers.append("hlink_delete_failed")

    verification = _verify_after_execute(preview, qb_base_url, qb_user, qb_pass, aliases) if not blockers else {}
    if verification and not verification.get("ok"):
        blockers.extend(str(blocker) for blocker in verification.get("blockers", []) if blocker)

    return {
        "mode": "cloud-hlink-cleanup-execute",
        "title": preview.get("title", ""),
        "ok": not blockers,
        "approved": True,
        "current_cloud_media": current_cloud_media,
        "qb_delete": delete_result,
        "hlink_delete": removed_hlink,
        "verification": verification,
        "blockers": sorted(set(blockers)),
        "warnings": preview.get("warnings", []) if isinstance(preview.get("warnings"), list) else [],
        "safety": "approved cleanup; qBittorrent delete is called for validated hashes with deleteFiles=true, then only the explicit hlink root is removed",
    }


def execute_cloud_hlink_orphan_cleanup(
    preview: Dict[str, object],
    qb_base_url: str,
    qb_user: str = "",
    qb_pass: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
    mv3_base_url: str = "",
    mv3_token: str = "",
) -> Dict[str, object]:
    blockers: List[str] = []
    if preview.get("mode") != "cloud-hlink-orphan-cleanup-preview":
        blockers.append("preview_mode_not_supported")
    if not preview.get("ready_for_execute"):
        blockers.append("preview_not_ready_for_execute")
    if preview.get("blockers"):
        blockers.append("preview_has_blockers")
    if not qb_base_url:
        blockers.append("qb_base_url_required")

    hlink = preview.get("hlink") if isinstance(preview.get("hlink"), dict) else {}
    expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
    strm_report = preview.get("strm") if isinstance(preview.get("strm"), dict) else {}
    strm_roots = [root.get("path") for root in strm_report.get("strm", {}).get("roots", [])] if isinstance(strm_report.get("strm"), dict) else []
    hlink_root = str(hlink.get("path") or "")
    strm_root = str(strm_roots[0] or "") if strm_roots else ""
    if not hlink_root:
        blockers.append("hlink_root_required")
    if not strm_root:
        blockers.append("strm_root_required")

    current_precheck: Dict[str, object] = {}
    removed_hlink: Dict[str, object] = {}
    verification: Dict[str, object] = {}
    if not blockers:
        current_precheck = preview_cloud_hlink_orphan_cleanup(
            str(preview.get("title") or ""),
            hlink_root,
            strm_root,
            expected_tmdbid=int(expected.get("tmdbid") or 0),
            expected_episode_count=int(expected.get("episode_count") or 0),
            expected_episode_min=int(expected.get("episode_min") or 0),
            expected_episode_max=int(expected.get("episode_max") or 0),
            qb_base_url=qb_base_url,
            qb_user=qb_user,
            qb_pass=qb_pass,
            path_aliases=path_aliases,
            required_target_prefix=str(expected.get("required_target_prefix") or ""),
            forbidden_target_prefixes=expected.get("forbidden_target_prefixes") if isinstance(expected.get("forbidden_target_prefixes"), list) else [],
            mv3_base_url=mv3_base_url,
            mv3_token=mv3_token,
            cloud_media_path=str(expected.get("cloud_media_path") or ""),
            cloud_media_folder_id=str(expected.get("cloud_media_folder_id") or ""),
            cloud_media_storage=str(expected.get("cloud_media_storage") or "115-default"),
        )
        if not current_precheck.get("ready_for_execute"):
            blockers.append("current_precheck_not_ready_for_execute")

    if not blockers:
        removed_hlink = _remove_hlink_root(hlink_root)
        if not removed_hlink.get("ok"):
            blockers.append("hlink_delete_failed")

    if not blockers:
        verification = _verify_after_orphan_execute(preview)
        if not verification.get("ok"):
            blockers.extend(str(blocker) for blocker in verification.get("blockers", []) if blocker)

    return {
        "mode": "cloud-hlink-orphan-cleanup-execute",
        "title": preview.get("title", ""),
        "ok": not blockers,
        "approved": True,
        "current_precheck": current_precheck,
        "hlink_delete": removed_hlink,
        "verification": verification,
        "blockers": sorted(set(blockers)),
        "warnings": preview.get("warnings", []) if isinstance(preview.get("warnings"), list) else [],
        "safety": "approved hlink-only cleanup; qBittorrent file lists are scanned by inode immediately before deleting only the explicit hlink root",
    }


def execute_cloud_hlink_orphan_multiseason_cleanup(
    preview: Dict[str, object],
    qb_base_url: str,
    qb_user: str = "",
    qb_pass: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
    mv3_base_url: str = "",
    mv3_token: str = "",
) -> Dict[str, object]:
    blockers: List[str] = []
    if preview.get("mode") != "cloud-hlink-orphan-multiseason-cleanup-preview":
        blockers.append("preview_mode_not_supported")
    if not preview.get("ready_for_execute"):
        blockers.append("preview_not_ready_for_execute")
    if preview.get("blockers"):
        blockers.append("preview_has_blockers")
    if not qb_base_url:
        blockers.append("qb_base_url_required")

    hlink = preview.get("hlink") if isinstance(preview.get("hlink"), dict) else {}
    expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
    hlink_root = str(hlink.get("path") or "")
    season_specs = expected.get("seasons") if isinstance(expected.get("seasons"), list) else []
    if not hlink_root:
        blockers.append("hlink_root_required")
    if not season_specs:
        blockers.append("season_spec_required")

    current_precheck: Dict[str, object] = {}
    removed_hlink: Dict[str, object] = {}
    verification: Dict[str, object] = {}
    if not blockers:
        current_precheck = preview_cloud_hlink_orphan_multiseason_cleanup(
            str(preview.get("title") or ""),
            hlink_root,
            season_specs,
            expected_tmdbid=int(expected.get("tmdbid") or 0),
            qb_base_url=qb_base_url,
            qb_user=qb_user,
            qb_pass=qb_pass,
            path_aliases=path_aliases,
            required_target_prefix=str(expected.get("required_target_prefix") or ""),
            forbidden_target_prefixes=expected.get("forbidden_target_prefixes") if isinstance(expected.get("forbidden_target_prefixes"), list) else [],
            mv3_base_url=mv3_base_url,
            mv3_token=mv3_token,
            cloud_media_path=str(expected.get("cloud_media_path") or ""),
            cloud_media_folder_id=str(expected.get("cloud_media_folder_id") or ""),
            cloud_media_storage=str(expected.get("cloud_media_storage") or "115-default"),
        )
        if not current_precheck.get("ready_for_execute"):
            blockers.append("current_precheck_not_ready_for_execute")

    if not blockers:
        removed_hlink = _remove_hlink_root(hlink_root)
        if not removed_hlink.get("ok"):
            blockers.append("hlink_delete_failed")

    if not blockers:
        verification = _verify_after_multiseason_orphan_execute(preview)
        if not verification.get("ok"):
            blockers.extend(str(blocker) for blocker in verification.get("blockers", []) if blocker)

    return {
        "mode": "cloud-hlink-orphan-multiseason-cleanup-execute",
        "title": preview.get("title", ""),
        "ok": not blockers,
        "approved": True,
        "current_precheck": current_precheck,
        "hlink_delete": removed_hlink,
        "verification": verification,
        "blockers": sorted(set(blockers)),
        "warnings": preview.get("warnings", []) if isinstance(preview.get("warnings"), list) else [],
        "safety": "approved multiseason hlink-only cleanup; qBittorrent file lists are scanned by inode immediately before deleting only the explicit hlink root; cloud media is never scraped or deleted",
    }


def execute_cloud_source_orphan_cleanup(
    preview: Dict[str, object],
    qb_base_url: str,
    qb_user: str = "",
    qb_pass: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
    mv3_base_url: str = "",
    mv3_token: str = "",
) -> Dict[str, object]:
    blockers: List[str] = []
    if preview.get("mode") != "cloud-source-orphan-cleanup-preview":
        blockers.append("preview_mode_not_supported")
    if not preview.get("ready_for_execute"):
        blockers.append("preview_not_ready_for_execute")
    if preview.get("blockers"):
        blockers.append("preview_has_blockers")
    if not qb_base_url:
        blockers.append("qb_base_url_required")

    source = preview.get("source") if isinstance(preview.get("source"), dict) else {}
    expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
    strm_report = preview.get("strm") if isinstance(preview.get("strm"), dict) else {}
    strm_roots = [root.get("path") for root in strm_report.get("strm", {}).get("roots", [])] if isinstance(strm_report.get("strm"), dict) else []
    source_root = str(source.get("path") or "")
    strm_root = str(strm_roots[0] or "") if strm_roots else ""
    if not source_root:
        blockers.append("source_root_required")
    if not strm_root:
        blockers.append("strm_root_required")

    current_precheck: Dict[str, object] = {}
    removed_source: Dict[str, object] = {}
    verification: Dict[str, object] = {}
    if not blockers:
        current_precheck = preview_cloud_source_orphan_cleanup(
            str(preview.get("title") or ""),
            source_root,
            strm_root,
            expected_tmdbid=int(expected.get("tmdbid") or 0),
            expected_episode_count=int(expected.get("episode_count") or 0),
            expected_episode_min=int(expected.get("episode_min") or 0),
            expected_episode_max=int(expected.get("episode_max") or 0),
            qb_base_url=qb_base_url,
            qb_user=qb_user,
            qb_pass=qb_pass,
            path_aliases=path_aliases,
            required_target_prefix=str(expected.get("required_target_prefix") or ""),
            forbidden_target_prefixes=expected.get("forbidden_target_prefixes") if isinstance(expected.get("forbidden_target_prefixes"), list) else [],
            mv3_base_url=mv3_base_url,
            mv3_token=mv3_token,
            cloud_media_path=str(expected.get("cloud_media_path") or ""),
            cloud_media_folder_id=str(expected.get("cloud_media_folder_id") or ""),
            cloud_media_storage=str(expected.get("cloud_media_storage") or "115-default"),
        )
        if not current_precheck.get("ready_for_execute"):
            blockers.append("current_precheck_not_ready_for_execute")

    if not blockers:
        removed_source = _remove_source_root(source_root)
        if not removed_source.get("ok"):
            blockers.append("source_delete_failed")

    if not blockers:
        verification = _verify_after_source_orphan_execute(preview)
        if not verification.get("ok"):
            blockers.extend(str(blocker) for blocker in verification.get("blockers", []) if blocker)

    return {
        "mode": "cloud-source-orphan-cleanup-execute",
        "title": preview.get("title", ""),
        "ok": not blockers,
        "approved": True,
        "current_precheck": current_precheck,
        "source_delete": removed_source,
        "verification": verification,
        "blockers": sorted(set(blockers)),
        "warnings": preview.get("warnings", []) if isinstance(preview.get("warnings"), list) else [],
        "safety": "approved source-only cleanup; qBittorrent is rechecked immediately before deleting only the explicit orphan source root; STRM, cloud media, hlink, and Emby are not modified",
    }


def cleanup_empty_hlink_root(title: str, hlink_root: str, expected_tmdbid: int = 0, approve_delete: bool = False) -> Dict[str, object]:
    blockers: List[str] = []
    hlink_check = _hlink_root_check(hlink_root)
    if not hlink_check.get("exists"):
        blockers.append("hlink_root_missing")
    if int(hlink_check.get("video_count") or 0) > 0:
        blockers.append("hlink_root_contains_video_files")
    if not approve_delete:
        blockers.append("approval_required")

    delete_result: Dict[str, object] = {}
    if not blockers:
        delete_result = _remove_hlink_root(hlink_root)
        if not delete_result.get("ok"):
            blockers.append("hlink_delete_failed")

    return {
        "mode": "hlink-empty-root-cleanup",
        "title": title,
        "expected": {"tmdbid": expected_tmdbid},
        "ok": not blockers,
        "approved": approve_delete,
        "hlink": hlink_check,
        "delete": delete_result,
        "blockers": sorted(set(blockers)),
        "warnings": [],
        "safety": "approved cleanup only for one explicit hlink root that contains no video files; qBittorrent, STRM, cloud files, and Emby are not modified",
    }


def _verify_after_source_orphan_execute(preview: Dict[str, object]) -> Dict[str, object]:
    blockers: List[str] = []
    source = preview.get("source") if isinstance(preview.get("source"), dict) else {}
    expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
    strm_report = preview.get("strm") if isinstance(preview.get("strm"), dict) else {}
    strm_roots = [root.get("path") for root in strm_report.get("strm", {}).get("roots", [])] if isinstance(strm_report.get("strm"), dict) else []
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
    source_exists = Path(str(source.get("path") or "")).exists()
    if source_exists:
        blockers.append("source_root_still_exists")
    return {
        "ok": not blockers,
        "strm": strm_verify,
        "source_exists": source_exists,
        "blockers": sorted(set(blockers)),
    }


def _verify_after_orphan_execute(preview: Dict[str, object]) -> Dict[str, object]:
    blockers: List[str] = []
    hlink = preview.get("hlink") if isinstance(preview.get("hlink"), dict) else {}
    expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
    strm_report = preview.get("strm") if isinstance(preview.get("strm"), dict) else {}
    strm_roots = [root.get("path") for root in strm_report.get("strm", {}).get("roots", [])] if isinstance(strm_report.get("strm"), dict) else []
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
    hlink_exists = Path(str(hlink.get("path") or "")).exists()
    if hlink_exists:
        blockers.append("hlink_root_still_exists")
    return {
        "ok": not blockers,
        "strm": strm_verify,
        "hlink_exists": hlink_exists,
        "blockers": sorted(set(blockers)),
    }


def _verify_after_multiseason_orphan_execute(preview: Dict[str, object]) -> Dict[str, object]:
    blockers: List[str] = []
    hlink = preview.get("hlink") if isinstance(preview.get("hlink"), dict) else {}
    expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
    specs = expected.get("seasons") if isinstance(expected.get("seasons"), list) else []
    strm_verifications: List[Dict[str, object]] = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        expected_episodes = [int(item) for item in spec.get("expected_episodes", []) if int(item) > 0] if isinstance(spec.get("expected_episodes"), list) else []
        verify_count = 0 if expected_episodes else int(spec.get("expected_episode_count") or 0)
        verify_min = 0 if expected_episodes else int(spec.get("expected_episode_min") or 0)
        verify_max = 0 if expected_episodes else int(spec.get("expected_episode_max") or 0)
        strm_verify = verify_strm_paths(
            str(preview.get("title") or ""),
            [str(spec.get("strm_root") or "")],
            expected_episode_count=verify_count,
            expected_episode_min=verify_min,
            expected_episode_max=verify_max,
            required_target_prefix=str(expected.get("required_target_prefix") or ""),
            forbidden_target_prefixes=expected.get("forbidden_target_prefixes") if isinstance(expected.get("forbidden_target_prefixes"), list) else [],
        )
        combined = strm_verify.get("strm", {}).get("combined", {}) if isinstance(strm_verify.get("strm"), dict) else {}
        episodes = set(int(item) for item in combined.get("episodes", []) if isinstance(item, int) and int(item) > 0) if isinstance(combined.get("episodes"), list) else set()
        missing_expected = [episode for episode in expected_episodes if episode not in episodes]
        if missing_expected:
            blockers.append("strm_expected_episodes_missing")
        if not strm_verify.get("ok"):
            blockers.extend(str(blocker) for blocker in strm_verify.get("blockers", []) if blocker)
        strm_verifications.append({"season": int(spec.get("season") or 0), "missing_expected_episodes": missing_expected, "report": strm_verify})
    hlink_exists = Path(str(hlink.get("path") or "")).exists()
    if hlink_exists:
        blockers.append("hlink_root_still_exists")
    return {
        "ok": not blockers,
        "strm_seasons": strm_verifications,
        "hlink_exists": hlink_exists,
        "blockers": sorted(set(blockers)),
    }


def render_cloud_hlink_cleanup(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    hlink = report.get("hlink") if isinstance(report.get("hlink"), dict) else {}
    source = report.get("source") if isinstance(report.get("source"), dict) else {}
    qb = report.get("qbittorrent") if isinstance(report.get("qbittorrent"), dict) else {}
    cloud_media = report.get("cloud_media") if isinstance(report.get("cloud_media"), dict) else {}
    current_cloud_media = report.get("current_cloud_media") if isinstance(report.get("current_cloud_media"), dict) else {}
    cloud_scan = cloud_media.get("scan") if isinstance(cloud_media.get("scan"), dict) else {}
    if not cloud_scan and isinstance(current_cloud_media.get("scan"), dict):
        cloud_scan = current_cloud_media.get("scan")
    lines = [
        "# Cloud Hlink Cleanup",
        "",
        f"- Title: `{report.get('title', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Ready: `{bool(report.get('ready_for_execute', report.get('ok')))}`",
        f"- hlink root: `{hlink.get('path', '')}`",
        f"- hlink videos: `{hlink.get('video_count', 0)}`",
        f"- source root: `{source.get('path', '')}`",
        f"- source videos: `{source.get('video_count', 0)}`",
        f"- qB matches: `{qb.get('matched_count', 0)}`",
        f"- qB hashes: `{qb.get('hashes', [])}`",
        f"- Cloud metadata sidecars: `{cloud_scan.get('metadata_sidecar_file_count', 0)}`",
        "- Safety: preview is readonly; execute only mutates approved qB hashes and the explicit hlink root.",
    ]
    strm_seasons = report.get("strm_seasons")
    if isinstance(strm_seasons, list) and strm_seasons:
        lines.extend(["", "## STRM Seasons", "", "| Season | Root | Episodes | Missing expected |", "| ---: | --- | ---: | --- |"])
        for item in strm_seasons:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {season} | {root} | {count} | {missing} |".format(
                    season=item.get("season", ""),
                    root=str(item.get("strm_root") or ""),
                    count=len(item.get("episodes", [])) if isinstance(item.get("episodes"), list) else 0,
                    missing=str(item.get("missing_expected_episodes", [])),
                )
            )
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    return "\n".join(lines)


def _normalize_multiseason_specs(season_specs: Sequence[Dict[str, object]]) -> Tuple[List[Dict[str, object]], List[str]]:
    blockers: List[str] = []
    rows: List[Dict[str, object]] = []
    seen: Set[int] = set()
    for raw in season_specs:
        if not isinstance(raw, dict):
            blockers.append("season_spec_invalid")
            continue
        try:
            season = int(raw.get("season") or 0)
            expected_episode_count = int(raw.get("expected_episode_count") or raw.get("episode_count") or 0)
            expected_episode_min = int(raw.get("expected_episode_min") or raw.get("episode_min") or 0)
            expected_episode_max = int(raw.get("expected_episode_max") or raw.get("episode_max") or 0)
            expected_episodes = sorted({int(item) for item in raw.get("expected_episodes", []) if int(item) > 0}) if isinstance(raw.get("expected_episodes"), list) else []
        except (TypeError, ValueError):
            blockers.append("season_spec_invalid")
            continue
        strm_root = str(raw.get("strm_root") or raw.get("root") or "").strip()
        if season <= 0:
            blockers.append("season_spec_season_required")
        if season in seen:
            blockers.append("season_spec_duplicate_season")
        if not strm_root:
            blockers.append("season_spec_strm_root_required")
        if expected_episodes:
            if not expected_episode_count:
                expected_episode_count = len(expected_episodes)
            if not expected_episode_min:
                expected_episode_min = min(expected_episodes)
            if not expected_episode_max:
                expected_episode_max = max(expected_episodes)
        elif expected_episode_count and expected_episode_min and expected_episode_max:
            possible_count = expected_episode_max - expected_episode_min + 1
            if possible_count < expected_episode_count:
                blockers.append("season_spec_episode_range_invalid")
        rows.append(
            {
                "season": season,
                "strm_root": strm_root,
                "expected_episode_count": expected_episode_count,
                "expected_episode_min": expected_episode_min,
                "expected_episode_max": expected_episode_max,
                "expected_episodes": expected_episodes,
            }
        )
        seen.add(season)
    return rows, sorted(set(blockers))


def _single_season_hlink_episode_coverage(
    hlink_root: str,
    expected_episode_count: int,
    expected_episode_min: int,
    expected_episode_max: int,
) -> Dict[str, object]:
    expected: Set[int] = set()
    if expected_episode_min and expected_episode_max and expected_episode_min <= expected_episode_max:
        expected = set(range(expected_episode_min, expected_episode_max + 1))
    elif expected_episode_count:
        expected = set(range(1, expected_episode_count + 1))

    hlink_episodes = _hlink_episode_map(hlink_root)
    rows = hlink_episodes.get("rows") if isinstance(hlink_episodes.get("rows"), list) else []
    episodes = sorted({int(row.get("episode") or 0) for row in rows if isinstance(row, dict) and int(row.get("episode") or 0) > 0})
    seasons = sorted({int(row.get("season") or 0) for row in rows if isinstance(row, dict) and int(row.get("season") or 0) > 0})
    duplicate_pairs = hlink_episodes.get("duplicate_episode_pairs") if isinstance(hlink_episodes.get("duplicate_episode_pairs"), list) else []

    blockers: List[str] = []
    warnings: List[str] = []
    if expected_episode_count and not rows:
        blockers.append("hlink_episode_signal_missing")
    if hlink_episodes.get("unmatched_count"):
        blockers.append("hlink_episode_signal_missing")
    if len(seasons) > 1:
        blockers.append("hlink_multiple_seasons_detected")

    missing = [episode for episode in sorted(expected) if episode not in episodes]
    unexpected = [episode for episode in episodes if expected and episode not in expected]
    if missing:
        blockers.append("hlink_expected_episodes_missing")
    if unexpected:
        blockers.append("hlink_unexpected_episodes_present")
    if expected_episode_count and not expected and len(episodes) != expected_episode_count:
        blockers.append("hlink_episode_count_mismatch")
    if duplicate_pairs:
        warnings.append("hlink_duplicate_episode_files")

    return {
        "complete": bool(expected) and not blockers and set(episodes) == expected,
        "expected_episodes": sorted(expected),
        "episodes": episodes,
        "seasons": seasons,
        "video_count": int(hlink_episodes.get("row_count") or 0),
        "episode_count": len(episodes),
        "missing_episodes": missing,
        "unexpected_episodes": unexpected,
        "unmatched_count": int(hlink_episodes.get("unmatched_count") or 0),
        "unmatched_sample": hlink_episodes.get("unmatched_sample", []) if isinstance(hlink_episodes.get("unmatched_sample"), list) else [],
        "duplicate_episode_pairs": duplicate_pairs,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
    }


def _hlink_episode_map(hlink_root: str) -> Dict[str, object]:
    root = Path(hlink_root)
    if not root.exists():
        return {"seasons": [], "rows": [], "unmatched_count": 0, "unmatched_sample": [], "duplicate_episode_pairs": []}
    rows: List[Dict[str, object]] = []
    unmatched: List[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not is_video_file(path):
            continue
        rel = str(path.relative_to(root))
        signal = episode_signal([rel])
        season = _season_number_from_relative_path(rel, signal.seasons)
        episodes = [int(item) for item in signal.episodes if int(item) > 0]
        if not season or not episodes:
            unmatched.append(str(path))
            continue
        for episode in episodes:
            rows.append({"path": str(path), "season": season, "episode": episode})

    season_rows: Dict[int, List[Dict[str, object]]] = {}
    for row in rows:
        season_rows.setdefault(int(row["season"]), []).append(row)
    duplicate_pairs: List[Dict[str, object]] = []
    seasons = []
    for season, items in sorted(season_rows.items()):
        counts: Dict[int, int] = {}
        for item in items:
            episode = int(item["episode"])
            counts[episode] = counts.get(episode, 0) + 1
        duplicate_pairs.extend({"season": season, "episode": episode, "count": count} for episode, count in sorted(counts.items()) if count > 1)
        seasons.append(
            {
                "season": season,
                "video_count": len(items),
                "episode_count": len(counts),
                "episodes": sorted(counts),
                "sample_files": [str(item.get("path") or "") for item in items[:8]],
            }
        )
    return {
        "seasons": seasons,
        "rows": rows[:300],
        "row_count": len(rows),
        "unmatched_count": len(unmatched),
        "unmatched_sample": unmatched[:20],
        "duplicate_episode_pairs": duplicate_pairs[:50],
    }


def _season_number_from_relative_path(rel_path: str, signal_seasons: Sequence[int]) -> int:
    seasons = sorted({int(item) for item in signal_seasons if int(item) > 0})
    if len(seasons) == 1:
        return seasons[0]
    normalized = str(rel_path or "").replace("\\", "/")
    patterns = [
        re.compile(r"(?i)(?:^|/)Season[ ._-]*(\d{1,2})(?:/|$)"),
        re.compile(r"(?i)(?:^|/)S(\d{1,2})(?:/|$)"),
        re.compile(r"第\s*(\d{1,2})\s*季"),
    ]
    for pattern in patterns:
        match = pattern.search(normalized)
        if match:
            return int(match.group(1))
    return seasons[0] if seasons else 0


def _verify_after_execute(
    preview: Dict[str, object],
    qb_base_url: str,
    qb_user: str,
    qb_pass: str,
    aliases: Dict[str, str],
) -> Dict[str, object]:
    blockers: List[str] = []
    hlink = preview.get("hlink") if isinstance(preview.get("hlink"), dict) else {}
    expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
    strm_report = preview.get("strm") if isinstance(preview.get("strm"), dict) else {}
    strm_roots = [root.get("path") for root in strm_report.get("strm", {}).get("roots", [])] if isinstance(strm_report.get("strm"), dict) else []
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
    if Path(str(hlink.get("path") or "")).exists():
        blockers.append("hlink_root_still_exists")
    filesystem = preview.get("filesystem") if isinstance(preview.get("filesystem"), dict) else {}
    source_roots = filesystem.get("source_roots") if isinstance(filesystem.get("source_roots"), list) else []
    source_checks = []
    for item in source_roots:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if not path:
            continue
        check = _source_root_check(path)
        source_checks.append(check)
        if int(check.get("video_count") or 0) > 0:
            blockers.append("source_root_still_contains_video_files")
    qb_hashes = set(str(item) for item in (preview.get("qbittorrent", {}) or {}).get("hashes", []) if str(item)) if isinstance(preview.get("qbittorrent"), dict) else set()
    remaining = []
    try:
        for item in fetch_qb_evidence(qb_base_url, qb_user, qb_pass):
            if item.hash in qb_hashes:
                remaining.append(_qb_evidence_row(item, str(hlink.get("path") or ""), aliases))
    except Exception as exc:  # pragma: no cover - exercised by integration
        blockers.append("qb_verify_failed")
        remaining.append({"error": f"{type(exc).__name__}:{exc}"})
    if remaining:
        blockers.append("qb_torrent_still_present")
    return {
        "ok": not blockers,
        "strm": strm_verify,
        "hlink_exists": Path(str(hlink.get("path") or "")).exists(),
        "source_roots": source_checks,
        "qb_remaining": remaining,
        "blockers": sorted(set(blockers)),
    }


def _hlink_root_check(hlink_root: str) -> Dict[str, object]:
    root = Path(hlink_root)
    if not root.exists():
        return {"path": hlink_root, "exists": False, "video_count": 0, "file_count": 0, "episodes": [], "sample_files": []}
    files = [item for item in root.rglob("*") if item.is_file()]
    videos = [item for item in files if is_video_file(item)]
    signal = episode_signal(str(item.relative_to(root)) for item in videos)
    inode_rows = []
    for item in videos:
        try:
            stat = item.stat()
        except OSError:
            continue
        inode_rows.append({"path": str(item), "device": stat.st_dev, "inode": stat.st_ino, "size_bytes": stat.st_size})
    return {
        "path": hlink_root,
        "exists": True,
        "file_count": len(files),
        "video_count": len(videos),
        "non_video_count": len(files) - len(videos),
        "episodes": signal.episodes,
        "seasons": signal.seasons,
        "total_bytes": sum(int(row["size_bytes"]) for row in inode_rows),
        "sample_files": [str(item) for item in videos[:8]],
        "inodes": inode_rows,
    }


def _source_root_check(source_root: str) -> Dict[str, object]:
    root = Path(source_root)
    if not root.exists():
        return {"path": source_root, "exists": False, "narrow": False, "video_count": 0, "file_count": 0, "episodes": [], "sample_files": [], "inodes": []}
    files = [item for item in root.rglob("*") if item.is_file()]
    videos = [item for item in files if is_video_file(item)]
    signal = episode_signal(str(item.relative_to(root)) for item in videos)
    inode_rows = []
    for item in videos:
        try:
            stat = item.stat()
        except OSError:
            continue
        inode_rows.append({"path": str(item), "device": stat.st_dev, "inode": stat.st_ino, "size_bytes": stat.st_size})
    return {
        "path": source_root,
        "exists": True,
        "narrow": _is_narrow_source_root(root),
        "file_count": len(files),
        "video_count": len(videos),
        "non_video_count": len(files) - len(videos),
        "episodes": signal.episodes,
        "seasons": signal.seasons,
        "total_bytes": sum(int(row["size_bytes"]) for row in inode_rows),
        "sample_files": [str(item) for item in videos[:8]],
        "inodes": inode_rows,
    }


def _filesystem_series_from_hlink(title: str, hlink_root: str, hlink_check: Dict[str, object]) -> FileSystemSeries:
    signal = EpisodeSignal(
        seasons=[int(item) for item in hlink_check.get("seasons", []) if int(item) > 0] if isinstance(hlink_check.get("seasons"), list) else [],
        episodes=[int(item) for item in hlink_check.get("episodes", []) if int(item) > 0] if isinstance(hlink_check.get("episodes"), list) else [],
    )
    return FileSystemSeries(
        title=title or Path(hlink_root).name,
        path=hlink_root,
        size_bytes=int(hlink_check.get("total_bytes") or 0),
        video_count=int(hlink_check.get("video_count") or 0),
        latest_mtime=0,
        age_days=999,
        signal=signal,
    )


def _inode_qb_matches(
    torrents: Iterable[object],
    hlink_check: Dict[str, object],
    aliases: Dict[str, str],
    seen_hashes: Set[str],
) -> List[Dict[str, object]]:
    wanted = {
        (int(row.get("device") or 0), int(row.get("inode") or 0))
        for row in hlink_check.get("inodes", [])
        if isinstance(row, dict)
    }
    if not wanted:
        return []
    rows = []
    for torrent in torrents:
        torrent_hash = str(getattr(torrent, "hash", "") or "")
        if torrent_hash in seen_hashes:
            continue
        host_root = _host_content_root(torrent, aliases)
        if not host_root:
            continue
        try:
            for file_path in Path(host_root).rglob("*"):
                if not file_path.is_file() or not is_video_file(file_path):
                    continue
                stat = file_path.stat()
                if (stat.st_dev, stat.st_ino) in wanted:
                    rows.append(_qb_evidence_row(torrent, str(hlink_check.get("path") or ""), aliases))
                    seen_hashes.add(torrent_hash)
                    break
        except OSError:
            continue
    return rows


def _matches_cover_hlink(matches: Sequence[Dict[str, object]], hlink_check: Dict[str, object]) -> bool:
    if not matches:
        return False
    source_checks = [_source_match_check(row, hlink_check) for row in matches]
    return bool(_hlink_source_coverage(source_checks, hlink_check).get("complete"))


def _prefer_linked_qb_matches(matches: Sequence[Dict[str, object]], hlink_check: Dict[str, object]) -> List[Dict[str, object]]:
    pairs = [(row, _source_match_check(row, hlink_check)) for row in matches]
    linked = [(row, check) for row, check in pairs if _linked_hlink_video_count(check) > 0]
    if not linked:
        return list(matches)
    return [row for row, _check in linked]


def _linked_hlink_video_count(check: Dict[str, object]) -> int:
    if check.get("linked_hlink_video_count") is not None:
        return int(check.get("linked_hlink_video_count") or 0)
    linked_inodes = check.get("linked_hlink_inodes")
    if isinstance(linked_inodes, list):
        return len([inode for inode in linked_inodes if inode])
    return 0


def _precise_qb_file_inode_matches(
    qb_base_url: str,
    qb_user: str,
    qb_pass: str,
    hlink_check: Dict[str, object],
    aliases: Dict[str, str],
) -> Dict[str, object]:
    wanted = {
        (int(row.get("device") or 0), int(row.get("inode") or 0))
        for row in hlink_check.get("inodes", [])
        if isinstance(row, dict)
    }
    if not wanted:
        return {"scanned_count": 0, "matches": []}
    client = QBClient(qb_base_url, qb_user, qb_pass)
    client.login()
    torrents = client.torrents()
    rows: List[Dict[str, object]] = []
    for torrent in torrents:
        linked_files: List[Dict[str, object]] = []
        torrent_hash = str(torrent.get("hash") or "")
        try:
            files = client.torrent_files(torrent_hash)
        except Exception:
            files = []
        for host_path in _qb_file_host_paths(torrent, files, aliases):
            path = Path(host_path)
            if not path.is_file() or not is_video_file(path):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if (stat.st_dev, stat.st_ino) not in wanted:
                continue
            linked_files.append(
                {
                    "path": str(path),
                    "inode": _inode_key(stat.st_dev, stat.st_ino),
                    "size_bytes": stat.st_size,
                }
            )
        if not linked_files:
            continue
        rows.append(_precise_qb_match_row(torrent, linked_files))
    return {"scanned_count": len(torrents), "matches": rows}


def _qb_file_host_paths(torrent: Dict[str, object], files: Sequence[Dict[str, object]], aliases: Dict[str, str]) -> List[str]:
    save_path = str(torrent.get("save_path") or "").rstrip("/")
    content_path = str(torrent.get("content_path") or "").rstrip("/")
    paths: List[str] = []
    if files:
        for item in files:
            rel_path = str(item.get("name") or "").strip("/")
            if not rel_path:
                continue
            paths.append(_map_path(str(PurePosixPath(save_path) / rel_path) if save_path else rel_path, aliases))
        return paths
    if content_path and Path(_map_path(content_path, aliases)).suffix:
        paths.append(_map_path(content_path, aliases))
    return paths


def _precise_qb_match_row(torrent: Dict[str, object], linked_files: Sequence[Dict[str, object]]) -> Dict[str, object]:
    seeding_seconds = int(torrent.get("seeding_time") or 0)
    torrent_hash = str(torrent.get("hash") or "")
    return {
        "name": str(torrent.get("name") or ""),
        "hash": torrent_hash,
        "hash_prefix": torrent_hash[:12],
        "state": str(torrent.get("state") or ""),
        "progress": float(torrent.get("progress") or 0.0),
        "seed_days": seeding_seconds / 86400.0,
        "size_bytes": int(torrent.get("size") or torrent.get("total_size") or 0),
        "save_path": str(torrent.get("save_path") or ""),
        "content_path": str(torrent.get("content_path") or ""),
        "host_content_path": "",
        "host_content_root": "",
        "linked_hlink_video_count": len(linked_files),
        "linked_hlink_inodes": sorted({str(item.get("inode") or "") for item in linked_files if item.get("inode")}),
        "linked_files_sample": list(linked_files[:10]),
    }


def _precise_qb_source_check(match: Dict[str, object]) -> Dict[str, object]:
    return {
        "path": str(match.get("content_path") or match.get("save_path") or ""),
        "hash_prefix": match.get("hash_prefix", ""),
        "exists": True,
        "kind": "qb_file_list",
        "blocked": True,
        "reason": "qb_file_list_contains_hlink_inode",
        "video_count": int(match.get("linked_hlink_video_count") or 0),
        "linked_hlink_video_count": int(match.get("linked_hlink_video_count") or 0),
        "linked_hlink_inodes": match.get("linked_hlink_inodes", []) if isinstance(match.get("linked_hlink_inodes"), list) else [],
        "linked_files_sample": match.get("linked_files_sample", []) if isinstance(match.get("linked_files_sample"), list) else [],
        "unlinked_video_sample": [],
    }


def _qb_source_path_matches(
    qb_base_url: str,
    qb_user: str,
    qb_pass: str,
    source_root: str,
    aliases: Dict[str, str],
) -> Dict[str, object]:
    rows: List[Dict[str, object]] = []
    source_variants = _path_variants(source_root, aliases)
    torrents = fetch_qb_evidence(qb_base_url, qb_user, qb_pass)
    for torrent in torrents:
        content_path = str(getattr(torrent, "content_path", "") or "")
        if not content_path:
            continue
        content_variants = _path_variants(content_path, aliases)
        if not any(_path_is_same_or_inside(candidate, root) for root in source_variants for candidate in content_variants):
            continue
        row = _qb_evidence_row(torrent, source_root, aliases)
        row["match_reason"] = "content_path_matches_source_root"
        rows.append(row)
    return {"scanned_count": len(torrents), "matches": rows}


def _merge_qb_match_rows(matches: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    merged: Dict[str, Dict[str, object]] = {}
    for row in matches:
        key = str(row.get("hash") or row.get("name") or json.dumps(row, sort_keys=True, ensure_ascii=False))
        if key not in merged:
            merged[key] = dict(row)
            continue
        existing = merged[key]
        reasons = {str(existing.get("match_reason") or "")}
        reasons.add(str(row.get("match_reason") or "inode_matches_source_root"))
        existing["match_reason"] = ",".join(sorted(reason for reason in reasons if reason))
    return list(merged.values())


def _candidate_torrents_for_inode_check(torrents: Iterable[object], series: FileSystemSeries) -> List[object]:
    wanted = _title_token_set(series.title)
    series_size = int(series.size_bytes or 0)
    candidates = []
    for torrent in torrents:
        text = " ".join(
            [
                str(getattr(torrent, "name", "") or ""),
                str(getattr(torrent, "content_path", "") or ""),
                str(getattr(torrent, "save_path", "") or ""),
            ]
        )
        tokens = _title_token_set(text)
        torrent_size = int(getattr(torrent, "size_bytes", 0) or 0)
        if wanted and wanted.intersection(tokens):
            candidates.append(torrent)
        elif series_size >= MIN_SIZE_ONLY_INODE_MATCH_BYTES and torrent_size == series_size:
            candidates.append(torrent)
    return candidates


def _title_token_set(value: str) -> Set[str]:
    import re

    tokens = set()
    for token in re.findall(r"[a-z]+|[0-9]+|[\u4e00-\u9fff]+", str(value).casefold()):
        if len(token) > 1 or re.search(r"[\u4e00-\u9fff]", token):
            tokens.add(token)
    return tokens


def _qb_evidence_row(torrent: object, hlink_root: str, aliases: Dict[str, str]) -> Dict[str, object]:
    content_path = str(getattr(torrent, "content_path", "") or "")
    host_content_path = _map_path(content_path, aliases) if content_path else ""
    host_root = _host_content_root(torrent, aliases)
    return {
        "name": str(getattr(torrent, "name", "") or ""),
        "hash": str(getattr(torrent, "hash", "") or ""),
        "hash_prefix": str(getattr(torrent, "hash", "") or "")[:12],
        "state": str(getattr(torrent, "state", "") or ""),
        "progress": float(getattr(torrent, "progress", 0.0) or 0.0),
        "seed_days": float(getattr(torrent, "seed_days", 0.0) or 0.0),
        "size_bytes": int(getattr(torrent, "size_bytes", 0) or 0),
        "save_path": str(getattr(torrent, "save_path", "") or ""),
        "content_path": content_path,
        "host_content_path": host_content_path,
        "host_content_root": host_root,
        "hlink_root": hlink_root,
    }


def _source_match_check(match: Dict[str, object], hlink_check: Dict[str, object]) -> Dict[str, object]:
    content_path = str(match.get("host_content_path") or match.get("host_content_root") or "")
    wanted = {
        (int(row.get("device") or 0), int(row.get("inode") or 0))
        for row in hlink_check.get("inodes", [])
        if isinstance(row, dict)
    }
    path = Path(content_path)
    if not content_path:
        return {"path": content_path, "hash_prefix": match.get("hash_prefix", ""), "exists": False, "blocked": True, "reason": "source_content_path_empty", "linked_hlink_inodes": []}
    if not path.exists():
        return {"path": content_path, "hash_prefix": match.get("hash_prefix", ""), "exists": False, "blocked": True, "reason": "source_content_path_missing", "linked_hlink_inodes": []}
    if path.is_file():
        try:
            stat = path.stat()
        except OSError:
            return {"path": content_path, "hash_prefix": match.get("hash_prefix", ""), "exists": True, "blocked": True, "reason": "source_content_stat_failed", "linked_hlink_inodes": []}
        linked = (stat.st_dev, stat.st_ino) in wanted
        linked_inode = _inode_key(stat.st_dev, stat.st_ino) if linked else ""
        return {
            "path": content_path,
            "hash_prefix": match.get("hash_prefix", ""),
            "exists": True,
            "kind": "file",
            "blocked": not (is_video_file(path) and linked),
            "video_count": 1 if is_video_file(path) else 0,
            "linked_hlink_video_count": 1 if linked else 0,
            "linked_hlink_inodes": [linked_inode] if linked_inode else [],
            "unlinked_video_sample": [] if linked else [content_path],
        }
    files = [item for item in path.rglob("*") if item.is_file() and is_video_file(item)]
    linked = 0
    linked_inodes: Set[str] = set()
    unlinked_sample: List[str] = []
    for item in files:
        try:
            stat = item.stat()
        except OSError:
            continue
        if (stat.st_dev, stat.st_ino) in wanted:
            linked += 1
            linked_inodes.add(_inode_key(stat.st_dev, stat.st_ino))
        elif len(unlinked_sample) < 10:
            unlinked_sample.append(str(item))
    blocked = not files or bool(unlinked_sample) or linked != len(files)
    return {
        "path": content_path,
        "hash_prefix": match.get("hash_prefix", ""),
        "exists": True,
        "kind": "directory",
        "blocked": blocked,
        "video_count": len(files),
        "linked_hlink_video_count": linked,
        "linked_hlink_inodes": sorted(linked_inodes),
        "unlinked_video_sample": unlinked_sample,
    }


def _hlink_source_coverage(source_checks: Sequence[Dict[str, object]], hlink_check: Dict[str, object]) -> Dict[str, object]:
    wanted_rows = {}
    for row in hlink_check.get("inodes", []):
        if not isinstance(row, dict):
            continue
        key = _inode_key(int(row.get("device") or 0), int(row.get("inode") or 0))
        if key:
            wanted_rows[key] = row
    linked = {
        str(inode)
        for check in source_checks
        for inode in (check.get("linked_hlink_inodes", []) if isinstance(check.get("linked_hlink_inodes"), list) else [])
        if str(inode)
    }
    missing = sorted(set(wanted_rows) - linked)
    return {
        "complete": bool(wanted_rows) and not missing,
        "hlink_video_count": int(hlink_check.get("video_count") or 0),
        "hlink_inode_count": len(wanted_rows),
        "linked_hlink_inode_count": len(set(wanted_rows).intersection(linked)),
        "missing_hlink_inode_count": len(missing),
        "missing_hlink_video_sample": [str(wanted_rows[key].get("path") or "") for key in missing[:10]],
    }


def _inode_key(device: int, inode: int) -> str:
    return f"{int(device)}:{int(inode)}" if device and inode else ""


def _host_content_root(torrent: object, aliases: Dict[str, str]) -> str:
    content_path = str(getattr(torrent, "content_path", "") or "").rstrip("/")
    save_path = str(getattr(torrent, "save_path", "") or "").rstrip("/")
    name = str(getattr(torrent, "name", "") or "").strip("/")
    root = content_path
    host_root = _map_path(root, aliases) if root else ""
    if root and _looks_like_single_video_content(host_root):
        root = str(PurePosixPath(root).parent)
    if not root and save_path and name:
        root = str(PurePosixPath(save_path) / name)
    return _map_path(root, aliases) if root else ""


def _looks_like_single_video_content(host_path: str) -> bool:
    path = Path(host_path)
    if path.is_file():
        return is_video_file(path)
    if path.exists():
        return False
    return path.suffix.lower() in {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".m2ts", ".wmv", ".flv", ".webm", ".rmvb"}


def _remove_hlink_root(hlink_root: str) -> Dict[str, object]:
    root = Path(hlink_root)
    if not root.exists():
        return {"path": hlink_root, "ok": True, "already_missing": True}
    if not _is_narrow_hlink_root(root):
        return {"path": hlink_root, "ok": False, "error": "hlink_root_not_narrow"}
    try:
        shutil.rmtree(root)
    except OSError as exc:
        return {"path": hlink_root, "ok": False, "error": f"{type(exc).__name__}:{exc}"}
    return {"path": hlink_root, "ok": not root.exists()}


def _remove_source_root(source_root: str) -> Dict[str, object]:
    root = Path(source_root)
    if not root.exists():
        return {"path": source_root, "ok": True, "already_missing": True}
    if not _is_narrow_source_root(root):
        return {"path": source_root, "ok": False, "error": "source_root_not_narrow"}
    try:
        shutil.rmtree(root)
    except OSError as exc:
        return {"path": source_root, "ok": False, "error": f"{type(exc).__name__}:{exc}"}
    return {"path": source_root, "ok": not root.exists()}


def _is_narrow_hlink_root(path: Path) -> bool:
    name = path.name.strip()
    if not name or name in {"TV", "Movies", "Movie", "hlink", "downloads", "download"}:
        return False
    return len(path.parts) >= 4


def _is_narrow_source_root(path: Path) -> bool:
    name = path.name.strip()
    if not name or name in {"TV", "Movies", "Movie", "hlink", "downloads", "download", "volume3", "volume4"}:
        return False
    return len(path.parts) >= 4


def _normalize_aliases(path_aliases: Dict[str, str]) -> Dict[str, str]:
    return {key.rstrip("/"): value.rstrip("/") for key, value in path_aliases.items() if key and value}


def _map_path(path: str, aliases: Dict[str, str]) -> str:
    normalized = str(path or "").rstrip("/")
    for source, target in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if normalized == source or normalized.startswith(source + "/"):
            return target + normalized[len(source) :]
    for source, target in sorted(aliases.items(), key=lambda item: len(item[1]), reverse=True):
        if normalized == target or normalized.startswith(target + "/"):
            return source + normalized[len(target) :]
    return normalized


def _path_variants(path: str, aliases: Dict[str, str]) -> Set[str]:
    normalized = str(path or "").rstrip("/")
    if not normalized:
        return set()
    variants = {normalized}
    for source, target in aliases.items():
        if normalized == source or normalized.startswith(source + "/"):
            variants.add(target + normalized[len(source) :])
        if normalized == target or normalized.startswith(target + "/"):
            variants.add(source + normalized[len(target) :])
    return {item.rstrip("/") for item in variants if item}


def _path_is_same_or_inside(candidate: str, root: str) -> bool:
    normalized_candidate = str(candidate or "").rstrip("/")
    normalized_root = str(root or "").rstrip("/")
    return bool(normalized_candidate and normalized_root and (normalized_candidate == normalized_root or normalized_candidate.startswith(normalized_root + "/")))
