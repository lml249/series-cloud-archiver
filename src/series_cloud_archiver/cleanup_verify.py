from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .episode import episode_signal
from .moviepilot import MPTransferHistoryRecord, MoviePilotClient
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


def verify_mp_cleanup_from_services(
    mp_base_url: str,
    mp_token: str,
    title: str,
    expected_title: str = "",
    expected_tmdbid: int = 0,
    expected_hash_prefix: str = "",
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
    elif expected_hash_prefix:
        warnings.append("qb_not_configured")

    report = build_mp_cleanup_verification(
        title=title,
        mp_records=mp_records,
        qb_torrents=qb_torrents,
        expected_title=expected_title,
        expected_tmdbid=expected_tmdbid,
        expected_hash_prefix=expected_hash_prefix,
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

    matched_mp_records = _filter_mp_records(mp_records, expected_title, expected_tmdbid, expected_hash_prefix)
    if matched_mp_records:
        blockers.append("mp_transfer_history_still_present")

    qb_matches = _matching_qb_torrents(qb_torrents or [], expected_hash_prefix)
    if expected_hash_prefix and qb_matches:
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
    expected_hash_prefix: str,
) -> List[MPTransferHistoryRecord]:
    filtered: List[MPTransferHistoryRecord] = []
    for record in records:
        if expected_title and record.title != expected_title:
            continue
        if expected_tmdbid and record.tmdbid and record.tmdbid != expected_tmdbid:
            continue
        if expected_hash_prefix and not record.download_hash.lower().startswith(expected_hash_prefix):
            continue
        filtered.append(record)
    return filtered


def _matching_qb_torrents(torrents: Sequence[Dict[str, object]], hash_prefix: str) -> List[Dict[str, object]]:
    if not hash_prefix:
        return []
    matches: List[Dict[str, object]] = []
    for item in torrents:
        torrent_hash = str(item.get("hash") or "").lower()
        if not torrent_hash.startswith(hash_prefix):
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


def _path_exists_row(path: str) -> Dict[str, object]:
    return {"path": path, "exists": Path(path).exists()}


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
    normalized_target = _normalize_target(target)
    normalized_required = _normalize_target(required_target_prefix)
    normalized_forbidden = [_normalize_target(item) for item in forbidden_target_prefixes if item]
    target_prefix_mismatch = bool(normalized_required and not normalized_target.startswith(normalized_required))
    forbidden_target = any(normalized_target.startswith(item) for item in normalized_forbidden)
    return {
        "file": str(path),
        "target": target,
        "target_prefix_mismatch": target_prefix_mismatch,
        "forbidden_target": forbidden_target,
    }


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
