from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional, Sequence
import urllib.parse
import xml.etree.ElementTree as ET

from .episode import episode_signal
from .moviepilot import MPTransferHistoryRecord, MoviePilotClient, transfer_record_season_numbers
from .path_safety import cloud_media_paths, non_strm_side_paths
from .qbittorrent import fetch_qb_torrents


def verify_strm_paths(
    title: str,
    strm_roots: Sequence[str],
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
    required_target_prefix: str = "",
    forbidden_target_prefixes: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    blockers: List[str] = []
    warnings: List[str] = []
    forbidden_target_prefixes = list(forbidden_target_prefixes or [])
    if (expected_episode_count or expected_episode_min or expected_episode_max) and not strm_roots:
        blockers.append("strm_root_required")

    roots = [_strm_root_row(path, required_target_prefix=required_target_prefix, forbidden_target_prefixes=forbidden_target_prefixes) for path in strm_roots]
    if any(not item["exists"] for item in roots):
        blockers.append("strm_root_missing")

    combined_episodes = sorted(
        {
            episode
            for item in roots
            for episode in item.get("episodes", [])
            if isinstance(episode, int) and episode > 0
        }
    )
    combined_missing = _missing_episode_numbers(combined_episodes)
    combined = {
        "episode_count": len(combined_episodes),
        "episode_min": min(combined_episodes) if combined_episodes else None,
        "episode_max": max(combined_episodes) if combined_episodes else None,
        "missing_in_range": combined_missing,
        "episodes": combined_episodes,
    }
    if expected_episode_count and len(combined_episodes) != expected_episode_count:
        blockers.append("strm_episode_count_mismatch")
    if expected_episode_min and (not combined_episodes or min(combined_episodes) != expected_episode_min):
        blockers.append("strm_episode_min_mismatch")
    if expected_episode_max and (not combined_episodes or max(combined_episodes) != expected_episode_max):
        blockers.append("strm_episode_max_mismatch")
    if combined_missing:
        blockers.append("strm_episode_gap_detected")
    for item in roots:
        if item.get("duplicate_episodes"):
            warnings.append("strm_duplicate_episode_files")
        if item.get("target_prefix_mismatch_count"):
            blockers.append("strm_target_prefix_mismatch")
        if item.get("forbidden_target_count"):
            blockers.append("strm_forbidden_target_prefix")

    return {
        "mode": "strm-verify",
        "title": title,
        "ok": not blockers,
        "expected": {
            "episode_count": expected_episode_count,
            "episode_min": expected_episode_min,
            "episode_max": expected_episode_max,
            "required_target_prefix": required_target_prefix,
            "forbidden_target_prefixes": forbidden_target_prefixes,
        },
        "strm": {
            "roots": roots,
            "combined": combined,
        },
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": "readonly STRM verification only; no MoviePilot request, qBittorrent action, filesystem deletion, or STRM write is performed",
    }


def render_strm_verification(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)

    expected = report.get("expected") if isinstance(report.get("expected"), dict) else {}
    strm = report.get("strm") if isinstance(report.get("strm"), dict) else {}
    combined = strm.get("combined") if isinstance(strm.get("combined"), dict) else {}
    lines = [
        "# STRM Verification",
        "",
        f"- Title: `{report.get('title', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- STRM episode count: `{combined.get('episode_count', 0)}`",
        f"- STRM episode range: `{combined.get('episode_min', '')}-{combined.get('episode_max', '')}`",
        f"- STRM missing in range: `{combined.get('missing_in_range', [])}`",
        f"- Required target prefix: `{expected.get('required_target_prefix', '')}`",
        f"- Forbidden target prefixes: `{expected.get('forbidden_target_prefixes', [])}`",
        "- Safety: readonly STRM verification only; no file changes were made.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)

    roots = strm.get("roots")
    if isinstance(roots, list) and roots:
        lines.extend(
            [
                "",
                "## STRM Roots",
                "",
                "| Path | Exists | Files | Episodes | Missing | Prefix mismatches | Forbidden targets |",
                "| --- | --- | ---: | ---: | --- | ---: | ---: |",
            ]
        )
        for item in roots:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {path} | {exists} | {file_count} | {episode_count} | {missing} | {mismatch} | {forbidden} |".format(
                    path=_escape(str(item.get("path") or "")),
                    exists=item.get("exists"),
                    file_count=item.get("file_count", 0),
                    episode_count=item.get("episode_count", 0),
                    missing=_escape(str(item.get("missing_in_range", []))),
                    mismatch=item.get("target_prefix_mismatch_count", 0),
                    forbidden=item.get("forbidden_target_count", 0),
                )
            )
    return "\n".join(lines)


def audit_strm_nfo_language(
    strm_roots: Sequence[str],
    min_chinese_ratio: float = 0.35,
    sample_limit: int = 50,
) -> Dict[str, object]:
    blockers: List[str] = []
    warnings: List[str] = []
    blocked_cloud_media_roots = cloud_media_paths(strm_roots)
    blocked_non_strm_roots = non_strm_side_paths(strm_roots)
    roots = [_nfo_language_root_row(path, min_chinese_ratio=min_chinese_ratio, sample_limit=sample_limit) for path in strm_roots]
    if not strm_roots:
        blockers.append("strm_root_required")
    if blocked_cloud_media_roots:
        blockers.append("strm_nfo_root_must_be_strm_side")
        warnings.append("cloud_media_paths_are_transfer_and_strm_only")
    if blocked_non_strm_roots:
        blockers.append("strm_nfo_root_must_be_strm_side")
        warnings.append("strm_nfo_roots_must_be_strm_side")
    if any(not item["exists"] for item in roots):
        blockers.append("strm_root_missing")

    total_nfo = sum(int(item.get("nfo_count") or 0) for item in roots)
    suspect_count = sum(int(item.get("suspect_english_count") or 0) for item in roots)
    parse_error_count = sum(int(item.get("parse_error_count") or 0) for item in roots)
    if suspect_count:
        blockers.append("strm_nfo_language_not_chinese")
    if parse_error_count:
        warnings.append("strm_nfo_parse_error")

    return {
        "mode": "strm-nfo-language-audit",
        "ok": not blockers,
        "expected": {
            "min_chinese_ratio": min_chinese_ratio,
            "sample_limit": sample_limit,
            "blocked_cloud_media_roots": blocked_cloud_media_roots,
            "blocked_non_strm_roots": blocked_non_strm_roots,
        },
        "summary": {
            "root_count": len(roots),
            "nfo_count": total_nfo,
            "suspect_english_count": suspect_count,
            "parse_error_count": parse_error_count,
        },
        "roots": roots,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": "readonly STRM-side NFO language audit only; cloud media directories are transfer and STRM-generation sources only and must not be audited as scraping targets; no file changes, scraping, MoviePilot request, qBittorrent action, or deletion is performed",
    }


def render_strm_nfo_language_audit(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)

    expected = report.get("expected") if isinstance(report.get("expected"), dict) else {}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# STRM NFO Language Audit",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- NFO files: `{summary.get('nfo_count', 0)}`",
        f"- Suspect English NFO files: `{summary.get('suspect_english_count', 0)}`",
        f"- Parse errors: `{summary.get('parse_error_count', 0)}`",
        f"- Min Chinese ratio: `{expected.get('min_chinese_ratio', 0)}`",
        f"- Blocked cloud media roots: `{expected.get('blocked_cloud_media_roots', [])}`",
        "- Safety: readonly STRM-side NFO language audit only; cloud media directories are not scraping targets.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)

    roots = report.get("roots")
    if isinstance(roots, list) and roots:
        lines.extend(
            [
                "",
                "## Roots",
                "",
                "| Path | Exists | NFO files | Suspect English | Parse errors |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        for item in roots:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {path} | {exists} | {nfo_count} | {suspect} | {errors} |".format(
                    path=_escape(str(item.get("path") or "")),
                    exists=item.get("exists"),
                    nfo_count=item.get("nfo_count", 0),
                    suspect=item.get("suspect_english_count", 0),
                    errors=item.get("parse_error_count", 0),
                )
            )
            suspects = item.get("suspect_english_samples")
            if isinstance(suspects, list):
                for sample in suspects[:10]:
                    if isinstance(sample, dict):
                        lines.append(
                            "  - `{path}` title_ratio=`{title_ratio}` plot_ratio=`{plot_ratio}`".format(
                                path=sample.get("path", ""),
                                title_ratio=sample.get("title_chinese_ratio", 0),
                                plot_ratio=sample.get("plot_chinese_ratio", 0),
                            )
                        )
    return "\n".join(lines)


def cleanup_duplicate_strm_root(
    title: str,
    correct_root: str,
    duplicate_root: str,
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
    required_target_prefix: str = "",
    approve_delete: bool = False,
) -> Dict[str, object]:
    blockers: List[str] = []
    warnings: List[str] = []
    correct = _strm_root_row(correct_root, required_target_prefix=required_target_prefix)
    duplicate = _strm_root_row(duplicate_root, required_target_prefix=required_target_prefix)

    if not correct["exists"]:
        blockers.append("correct_strm_root_missing")
    if not duplicate["exists"]:
        blockers.append("duplicate_strm_root_missing")
    if correct.get("target_prefix_mismatch_count"):
        blockers.append("correct_strm_target_prefix_mismatch")
    if duplicate.get("target_prefix_mismatch_count"):
        blockers.append("duplicate_strm_target_prefix_mismatch")

    correct_episodes = [item for item in correct.get("episodes", []) if isinstance(item, int)]
    duplicate_episodes = [item for item in duplicate.get("episodes", []) if isinstance(item, int)]
    if expected_episode_count and len(correct_episodes) != expected_episode_count:
        blockers.append("correct_strm_episode_count_mismatch")
    if expected_episode_count and len(duplicate_episodes) != expected_episode_count:
        blockers.append("duplicate_strm_episode_count_mismatch")
    if expected_episode_min and (not correct_episodes or min(correct_episodes) != expected_episode_min):
        blockers.append("correct_strm_episode_min_mismatch")
    if expected_episode_min and (not duplicate_episodes or min(duplicate_episodes) != expected_episode_min):
        blockers.append("duplicate_strm_episode_min_mismatch")
    if expected_episode_max and (not correct_episodes or max(correct_episodes) != expected_episode_max):
        blockers.append("correct_strm_episode_max_mismatch")
    if expected_episode_max and (not duplicate_episodes or max(duplicate_episodes) != expected_episode_max):
        blockers.append("duplicate_strm_episode_max_mismatch")
    if correct.get("missing_in_range"):
        blockers.append("correct_strm_episode_gap_detected")
    if duplicate.get("missing_in_range"):
        blockers.append("duplicate_strm_episode_gap_detected")
    if correct_episodes and duplicate_episodes and correct_episodes != duplicate_episodes:
        blockers.append("duplicate_episode_set_mismatch")
    if correct.get("duplicate_episodes"):
        warnings.append("correct_strm_duplicate_episode_files")
    if duplicate.get("duplicate_episodes"):
        warnings.append("duplicate_strm_duplicate_episode_files")

    duplicate_path = Path(duplicate_root)
    non_strm_files = _non_strm_files(duplicate_path) if duplicate_path.exists() else []
    if non_strm_files:
        blockers.append("duplicate_root_contains_non_strm_files")

    correct_path = Path(correct_root)
    if correct_path.exists() and duplicate_path.exists():
        try:
            if correct_path.resolve() == duplicate_path.resolve():
                blockers.append("duplicate_root_same_as_correct_root")
        except OSError:
            blockers.append("strm_root_resolution_failed")

    ready = not blockers
    deleted_files: List[Dict[str, object]] = []
    deleted_dirs: List[str] = []
    if ready and approve_delete:
        files = sorted(item for item in duplicate_path.rglob("*") if item.is_file() and item.suffix.lower() == ".strm")
        for file_path in files:
            size = file_path.stat().st_size
            file_path.unlink()
            deleted_files.append({"path": str(file_path), "size_bytes": size})
        deleted_dirs = _remove_empty_dirs(duplicate_path)
        if duplicate_path.exists():
            blockers.append("duplicate_root_still_exists_after_delete")

    return {
        "mode": "strm-duplicate-cleanup",
        "title": title,
        "ok": not blockers and (not approve_delete or not duplicate_path.exists()),
        "ready_for_delete": ready,
        "delete_executed": bool(approve_delete and ready),
        "expected": {
            "episode_count": expected_episode_count,
            "episode_min": expected_episode_min,
            "episode_max": expected_episode_max,
            "required_target_prefix": required_target_prefix,
        },
        "correct": correct,
        "duplicate": duplicate,
        "filesystem": {
            "non_strm_files": non_strm_files[:20],
            "deleted_files": deleted_files,
            "deleted_dirs": deleted_dirs,
        },
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": "duplicate STRM cleanup only; verifies the correct STRM root and duplicate STRM root before deleting approved .strm-only duplicate files",
    }


def render_duplicate_strm_cleanup(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)

    correct = report.get("correct") if isinstance(report.get("correct"), dict) else {}
    duplicate = report.get("duplicate") if isinstance(report.get("duplicate"), dict) else {}
    fs = report.get("filesystem") if isinstance(report.get("filesystem"), dict) else {}
    lines = [
        "# Duplicate STRM Cleanup",
        "",
        f"- Title: `{report.get('title', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Ready for delete: `{bool(report.get('ready_for_delete'))}`",
        f"- Delete executed: `{bool(report.get('delete_executed'))}`",
        f"- Correct STRM files: `{correct.get('file_count', 0)}`",
        f"- Duplicate STRM files: `{duplicate.get('file_count', 0)}`",
        f"- Deleted files: `{len(fs.get('deleted_files') if isinstance(fs.get('deleted_files'), list) else [])}`",
        "- Safety: only duplicate `.strm` files are deleted after explicit approval.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)
    lines.extend(
        [
            "",
            "## Roots",
            "",
            "| Role | Path | Exists | Files | Episodes | Missing | Prefix mismatches |",
            "| --- | --- | --- | ---: | ---: | --- | ---: |",
        ]
    )
    for role, item in (("correct", correct), ("duplicate", duplicate)):
        lines.append(
            "| {role} | {path} | {exists} | {files} | {episodes} | {missing} | {mismatches} |".format(
                role=role,
                path=_escape(str(item.get("path") or "")),
                exists=item.get("exists"),
                files=item.get("file_count", 0),
                episodes=item.get("episode_count", 0),
                missing=_escape(str(item.get("missing_in_range", []))),
                mismatches=item.get("target_prefix_mismatch_count", 0),
            )
        )
    return "\n".join(lines)


def verify_mp_cleanup_from_services(
    mp_base_url: str,
    mp_token: str,
    title: str,
    expected_title: str = "",
    expected_tmdbid: int = 0,
    expected_hash_prefix: str = "",
    expected_hash_prefixes: Optional[Iterable[str]] = None,
    expected_season: int = 0,
    source_roots: Optional[Sequence[str]] = None,
    destination_roots: Optional[Sequence[str]] = None,
    strm_roots: Optional[Sequence[str]] = None,
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
    qb_base_url: str = "",
    qb_user: str = "",
    qb_pass: str = "",
    timeout: int = 20,
) -> Dict[str, object]:
    client = MoviePilotClient(mp_base_url, mp_token, timeout=timeout)
    blockers: List[str] = []
    warnings: List[str] = []

    try:
        mp_records = client.transfer_history(title)
    except Exception as exc:  # pragma: no cover - exercised by integration runs
        mp_records = []
        blockers.append("mp_transfer_history_check_failed")
        warnings.append(f"mp_error:{type(exc).__name__}:{exc}")

    qb_torrents: Optional[List[Dict[str, object]]] = None
    if qb_base_url:
        try:
            qb_torrents = fetch_qb_torrents(qb_base_url, qb_user, qb_pass)
        except Exception as exc:  # pragma: no cover - exercised by integration runs
            blockers.append("qb_torrent_check_failed")
            warnings.append(f"qb_error:{type(exc).__name__}:{exc}")
    elif expected_hash_prefix or _normalize_hash_prefixes(expected_hash_prefixes):
        warnings.append("qb_not_configured")

    report = build_mp_cleanup_verification(
        title=title,
        mp_records=mp_records,
        qb_torrents=qb_torrents,
        expected_title=expected_title,
        expected_tmdbid=expected_tmdbid,
        expected_hash_prefix=expected_hash_prefix,
        expected_hash_prefixes=expected_hash_prefixes,
        expected_season=expected_season,
        source_roots=source_roots or [],
        destination_roots=destination_roots or [],
        strm_roots=strm_roots or [],
        expected_episode_count=expected_episode_count,
        expected_episode_min=expected_episode_min,
        expected_episode_max=expected_episode_max,
    )
    report["blockers"] = sorted(set(list(report.get("blockers", [])) + blockers))
    report["warnings"] = list(report.get("warnings", [])) + warnings
    report["ok"] = not report["blockers"]
    return report


def build_mp_cleanup_verification(
    title: str,
    mp_records: Sequence[MPTransferHistoryRecord],
    qb_torrents: Optional[Sequence[Dict[str, object]]] = None,
    expected_title: str = "",
    expected_tmdbid: int = 0,
    expected_hash_prefix: str = "",
    expected_hash_prefixes: Optional[Iterable[str]] = None,
    expected_season: int = 0,
    source_roots: Optional[Sequence[str]] = None,
    destination_roots: Optional[Sequence[str]] = None,
    strm_roots: Optional[Sequence[str]] = None,
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
) -> Dict[str, object]:
    blockers: List[str] = []
    warnings: List[str] = []
    source_roots = source_roots or []
    destination_roots = destination_roots or []
    strm_roots = strm_roots or []
    expected_hash_prefix = expected_hash_prefix.lower()
    normalized_hash_prefixes = _normalize_hash_prefixes(expected_hash_prefixes, expected_hash_prefix)

    matched_mp_records = _filter_mp_records(mp_records, expected_title, expected_tmdbid, normalized_hash_prefixes, expected_season)
    if matched_mp_records:
        blockers.append("mp_transfer_history_still_present")

    qb_matches = _matching_qb_torrents(qb_torrents or [], normalized_hash_prefixes)
    if normalized_hash_prefixes and qb_matches:
        blockers.append("qb_torrent_still_present")

    source_checks = [_path_exists_row(path) for path in source_roots]
    destination_checks = [_path_exists_row(path) for path in destination_roots]
    if any(item["exists"] for item in source_checks):
        blockers.append("source_root_still_exists")
    if any(item["exists"] for item in destination_checks):
        blockers.append("destination_root_still_exists")

    if (expected_episode_count or expected_episode_min or expected_episode_max) and not strm_roots:
        blockers.append("strm_root_required")
    strm_checks = [_strm_root_row(path) for path in strm_roots]
    if any(not item["exists"] for item in strm_checks):
        blockers.append("strm_root_missing")

    combined_episodes = sorted(
        {
            episode
            for item in strm_checks
            for episode in item.get("episodes", [])
            if isinstance(episode, int) and episode > 0
        }
    )
    combined_missing = _missing_episode_numbers(combined_episodes)
    combined = {
        "episode_count": len(combined_episodes),
        "episode_min": min(combined_episodes) if combined_episodes else None,
        "episode_max": max(combined_episodes) if combined_episodes else None,
        "missing_in_range": combined_missing,
        "episodes": combined_episodes,
    }
    if expected_episode_count and len(combined_episodes) != expected_episode_count:
        blockers.append("strm_episode_count_mismatch")
    if expected_episode_min and (not combined_episodes or min(combined_episodes) != expected_episode_min):
        blockers.append("strm_episode_min_mismatch")
    if expected_episode_max and (not combined_episodes or max(combined_episodes) != expected_episode_max):
        blockers.append("strm_episode_max_mismatch")
    if combined_missing:
        blockers.append("strm_episode_gap_detected")
    for item in strm_checks:
        duplicates = item.get("duplicate_episodes")
        if isinstance(duplicates, list) and duplicates:
            warnings.append("strm_duplicate_episode_files")
            break

    report = {
        "mode": "mp-cleanup-verify",
        "title": title,
        "ok": not blockers,
        "expected": {
            "title": expected_title,
            "tmdbid": expected_tmdbid,
            "hash_prefix": expected_hash_prefix,
            "hash_prefixes": normalized_hash_prefixes,
            "season": expected_season,
            "episode_count": expected_episode_count,
            "episode_min": expected_episode_min,
            "episode_max": expected_episode_max,
        },
        "mp_transfer_history": {
            "records_found": len(mp_records),
            "records_matched": len(matched_mp_records),
            "matched_ids": [record.id for record in matched_mp_records],
        },
        "qbittorrent": {
            "configured": qb_torrents is not None,
            "matched_count": len(qb_matches),
            "matches": qb_matches,
        },
        "filesystem": {
            "source_roots": source_checks,
            "destination_roots": destination_checks,
        },
        "strm": {
            "roots": strm_checks,
            "combined": combined,
        },
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "safety": "readonly post-cleanup verification only; no MoviePilot DELETE request, qBittorrent action, source deletion, hlink deletion, or STRM write is performed",
    }
    return report


def render_mp_cleanup_verification(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)

    expected = report.get("expected") if isinstance(report.get("expected"), dict) else {}
    mp_history = report.get("mp_transfer_history") if isinstance(report.get("mp_transfer_history"), dict) else {}
    qb = report.get("qbittorrent") if isinstance(report.get("qbittorrent"), dict) else {}
    filesystem = report.get("filesystem") if isinstance(report.get("filesystem"), dict) else {}
    strm = report.get("strm") if isinstance(report.get("strm"), dict) else {}
    combined = strm.get("combined") if isinstance(strm.get("combined"), dict) else {}
    lines = [
        "# MoviePilot Cleanup Verification",
        "",
        f"- Title: `{report.get('title', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Expected TMDB ID: `{expected.get('tmdbid', 0)}`",
        f"- Expected season: `{expected.get('season', 0)}`",
        f"- Expected hash prefix: `{expected.get('hash_prefix', '')}`",
        f"- MP transfer records matched after cleanup: `{mp_history.get('records_matched', 0)}`",
        f"- qB matched torrents after cleanup: `{qb.get('matched_count', 0)}`",
        f"- STRM episode count: `{combined.get('episode_count', 0)}`",
        f"- STRM episode range: `{combined.get('episode_min', '')}-{combined.get('episode_max', '')}`",
        f"- STRM missing in range: `{combined.get('missing_in_range', [])}`",
        "- Safety: readonly verification only; no delete request was sent.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    warnings = report.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in warnings)

    lines.extend(["", "## Filesystem", ""])
    lines.extend(_render_path_rows("Source roots", filesystem.get("source_roots")))
    lines.extend(_render_path_rows("Destination roots", filesystem.get("destination_roots")))

    roots = strm.get("roots")
    if isinstance(roots, list) and roots:
        lines.extend(["", "## STRM Roots", "", "| Path | Exists | Files | Episodes | Missing |", "| --- | --- | ---: | ---: | --- |"])
        for item in roots:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {path} | {exists} | {file_count} | {episode_count} | {missing} |".format(
                    path=_escape(str(item.get("path") or "")),
                    exists=item.get("exists"),
                    file_count=item.get("file_count", 0),
                    episode_count=item.get("episode_count", 0),
                    missing=_escape(str(item.get("missing_in_range", []))),
                )
            )

    matches = qb.get("matches")
    if isinstance(matches, list) and matches:
        lines.extend(["", "## qB Matches", "", "| Hash | State | Name |", "| --- | --- | --- |"])
        for item in matches:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| {hash_prefix} | {state} | {name} |".format(
                    hash_prefix=_escape(str(item.get("hash_prefix") or "")),
                    state=_escape(str(item.get("state") or "")),
                    name=_escape(str(item.get("name") or "")),
                )
            )
    return "\n".join(lines)


def _filter_mp_records(
    records: Sequence[MPTransferHistoryRecord],
    expected_title: str,
    expected_tmdbid: int,
    expected_hash_prefixes: Sequence[str],
    expected_season: int = 0,
) -> List[MPTransferHistoryRecord]:
    filtered: List[MPTransferHistoryRecord] = []
    for record in records:
        if expected_title and record.title != expected_title:
            continue
        if expected_tmdbid and record.tmdbid and record.tmdbid != expected_tmdbid:
            continue
        if expected_hash_prefixes and not _hash_matches_any_prefix(record.download_hash, expected_hash_prefixes):
            continue
        if expected_season:
            record_seasons = transfer_record_season_numbers(record)
            if record_seasons and expected_season not in record_seasons:
                continue
        filtered.append(record)
    return filtered


def _matching_qb_torrents(torrents: Sequence[Dict[str, object]], hash_prefixes: Sequence[str]) -> List[Dict[str, object]]:
    if not hash_prefixes:
        return []
    matches: List[Dict[str, object]] = []
    for item in torrents:
        torrent_hash = str(item.get("hash") or "").lower()
        if not _hash_matches_any_prefix(torrent_hash, hash_prefixes):
            continue
        matches.append(
            {
                "name": str(item.get("name") or ""),
                "hash_prefix": torrent_hash[:12],
                "state": str(item.get("state") or ""),
                "save_path": str(item.get("save_path") or ""),
                "content_path": str(item.get("content_path") or ""),
            }
        )
    return matches


def _normalize_hash_prefixes(prefixes: Optional[Iterable[str]], fallback: str = "") -> List[str]:
    values: List[str] = []
    if prefixes is None:
        values = []
    elif isinstance(prefixes, str):
        values = [prefixes]
    else:
        values = [str(item) for item in prefixes]
    if fallback:
        values.append(fallback)

    normalized: List[str] = []
    seen = set()
    for value in values:
        for part in str(value or "").split(","):
            token = part.strip().lower()
            if token and token not in seen:
                normalized.append(token)
                seen.add(token)
    return normalized


def _hash_prefix_match(left: str, right: str) -> bool:
    left = str(left or "").lower()
    right = str(right or "").lower()
    return bool(left and right and (left.startswith(right) or right.startswith(left)))


def _hash_matches_any_prefix(value: str, prefixes: Iterable[str]) -> bool:
    return any(_hash_prefix_match(value, prefix) for prefix in prefixes)


def _path_exists_row(path: str) -> Dict[str, object]:
    return {"path": path, "exists": Path(path).exists()}


def _non_strm_files(root: Path) -> List[str]:
    if not root.exists():
        return []
    return sorted(str(item) for item in root.rglob("*") if item.is_file() and item.suffix.lower() != ".strm")


def _remove_empty_dirs(root: Path) -> List[str]:
    deleted: List[str] = []
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
            deleted.append(str(path))
        except OSError:
            pass
    try:
        root.rmdir()
        deleted.append(str(root))
    except OSError:
        pass
    return deleted


def _strm_root_row(
    path: str,
    required_target_prefix: str = "",
    forbidden_target_prefixes: Optional[Sequence[str]] = None,
) -> Dict[str, object]:
    root = Path(path)
    forbidden_target_prefixes = list(forbidden_target_prefixes or [])
    if not root.exists():
        return {
            "path": path,
            "exists": False,
            "file_count": 0,
            "episode_count": 0,
            "episode_min": None,
            "episode_max": None,
            "missing_in_range": [],
            "duplicate_episodes": [],
            "episodes": [],
            "sample_files": [],
            "target_prefix_mismatch_count": 0,
            "target_prefix_mismatch_samples": [],
            "forbidden_target_count": 0,
            "forbidden_target_samples": [],
        }
    files = sorted(item for item in root.rglob("*") if item.is_file() and item.suffix.lower() == ".strm")
    signal = episode_signal([item.name for item in files])
    episodes = signal.episodes
    duplicates = _duplicate_episode_numbers([item.name for item in files])
    target_rows = [_strm_target_row(item, required_target_prefix, forbidden_target_prefixes) for item in files]
    prefix_mismatches = [item for item in target_rows if item["target_prefix_mismatch"]]
    forbidden_targets = [item for item in target_rows if item["forbidden_target"]]
    return {
        "path": path,
        "exists": True,
        "file_count": len(files),
        "episode_count": len(episodes),
        "episode_min": min(episodes) if episodes else None,
        "episode_max": max(episodes) if episodes else None,
        "missing_in_range": _missing_episode_numbers(episodes),
        "duplicate_episodes": duplicates,
        "episodes": episodes,
        "sample_files": [str(item) for item in files[:5]],
        "target_prefix_mismatch_count": len(prefix_mismatches),
        "target_prefix_mismatch_samples": prefix_mismatches[:5],
        "forbidden_target_count": len(forbidden_targets),
        "forbidden_target_samples": forbidden_targets[:5],
    }


def _strm_target_row(path: Path, required_target_prefix: str, forbidden_target_prefixes: Sequence[str]) -> Dict[str, object]:
    target = path.read_text(encoding="utf-8", errors="replace").strip()
    resolved_target = _strm_target_path(target)
    normalized_target = _normalize_target(resolved_target)
    normalized_required = _normalize_target(required_target_prefix)
    normalized_forbidden = [_normalize_target(item) for item in forbidden_target_prefixes if item]
    target_prefix_mismatch = bool(normalized_required and not normalized_target.startswith(normalized_required))
    forbidden_target = any(normalized_target.startswith(item) for item in normalized_forbidden)
    return {
        "file": str(path),
        "target": target,
        "resolved_target": resolved_target,
        "target_prefix_mismatch": target_prefix_mismatch,
        "forbidden_target": forbidden_target,
    }


def _nfo_language_root_row(path: str, min_chinese_ratio: float, sample_limit: int) -> Dict[str, object]:
    root = Path(path)
    if not root.exists():
        return {
            "path": path,
            "exists": False,
            "nfo_count": 0,
            "sample_count": 0,
            "suspect_english_count": 0,
            "parse_error_count": 0,
            "samples": [],
            "suspect_english_samples": [],
        }

    files = sorted(item for item in root.rglob("*") if item.is_file() and item.suffix.lower() == ".nfo")
    samples = [_nfo_language_file_row(item, min_chinese_ratio=min_chinese_ratio) for item in files[: max(0, sample_limit)]]
    suspect_samples = [item for item in samples if item.get("suspect_english")]
    parse_error_count = sum(1 for item in samples if item.get("parse_error"))
    return {
        "path": path,
        "exists": True,
        "nfo_count": len(files),
        "sample_count": len(samples),
        "suspect_english_count": len(suspect_samples),
        "parse_error_count": parse_error_count,
        "samples": samples[:20],
        "suspect_english_samples": suspect_samples[:20],
    }


def _nfo_language_file_row(path: Path, min_chinese_ratio: float) -> Dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed = _parse_nfo_text(text)
    title = parsed.get("title", "")
    plot = parsed.get("plot", "")
    title_ratio = _chinese_ratio(title)
    plot_ratio = _chinese_ratio(plot)
    has_plot_letters = _letter_count(plot) >= 20
    suspect_english = bool(has_plot_letters and plot_ratio < min_chinese_ratio)
    return {
        "path": str(path),
        "title": title[:240],
        "plot": plot[:360],
        "title_chinese_ratio": title_ratio,
        "plot_chinese_ratio": plot_ratio,
        "suspect_english": suspect_english,
        "parse_error": parsed.get("parse_error", ""),
    }


def _parse_nfo_text(text: str) -> Dict[str, str]:
    result = {"title": "", "plot": "", "parse_error": ""}
    try:
        root = ET.fromstring(text)
        result["title"] = _first_xml_text(root, ["title", "originaltitle", "sorttitle"])
        result["plot"] = _first_xml_text(root, ["plot", "outline", "overview"])
        return result
    except ET.ParseError as exc:
        result["parse_error"] = f"xml_parse_error:{exc.__class__.__name__}"

    result["title"] = _first_tag_text(text, ["title", "originaltitle", "sorttitle"])
    result["plot"] = _first_tag_text(text, ["plot", "outline", "overview"])
    return result


def _first_xml_text(root: ET.Element, tags: Sequence[str]) -> str:
    wanted = {tag.casefold() for tag in tags}
    for element in root.iter():
        tag = str(element.tag or "").split("}", 1)[-1].casefold()
        if tag in wanted and element.text:
            return _clean_nfo_text(element.text)
    return ""


def _first_tag_text(text: str, tags: Sequence[str]) -> str:
    for tag in tags:
        match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _clean_nfo_text(match.group(1))
    return ""


def _clean_nfo_text(value: str) -> str:
    text = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", str(value or ""), flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _chinese_ratio(value: str) -> float:
    letters = [char for char in str(value or "") if char.isalpha() or "\u4e00" <= char <= "\u9fff"]
    if not letters:
        return 0.0
    chinese = sum(1 for char in letters if "\u4e00" <= char <= "\u9fff")
    return round(chinese / len(letters), 3)


def _letter_count(value: str) -> int:
    return sum(1 for char in str(value or "") if char.isalpha() or "\u4e00" <= char <= "\u9fff")


def _strm_target_path(target: str) -> str:
    parsed = urllib.parse.urlparse(target)
    if parsed.query:
        query = urllib.parse.parse_qs(parsed.query)
        path_values = query.get("path") or query.get("file") or query.get("target")
        if path_values:
            return urllib.parse.unquote(path_values[0])
    return target


def _normalize_target(value: str) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/")


def _missing_episode_numbers(episodes: Sequence[int]) -> List[int]:
    unique = sorted(set(item for item in episodes if item > 0))
    if not unique:
        return []
    return [item for item in range(unique[0], unique[-1] + 1) if item not in unique]


def _duplicate_episode_numbers(names: Sequence[str]) -> List[int]:
    seen = set()
    duplicates = set()
    for name in names:
        signal = episode_signal([name])
        for episode in signal.episodes:
            if episode in seen:
                duplicates.add(episode)
            seen.add(episode)
    return sorted(duplicates)


def _render_path_rows(label: str, rows) -> List[str]:
    lines = [f"### {label}", "", "| Path | Exists |", "| --- | --- |"]
    if not isinstance(rows, list) or not rows:
        lines.append("|  |  |")
        return lines
    for item in rows:
        if not isinstance(item, dict):
            continue
        lines.append(f"| {_escape(str(item.get('path') or ''))} | {item.get('exists')} |")
    return lines


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
