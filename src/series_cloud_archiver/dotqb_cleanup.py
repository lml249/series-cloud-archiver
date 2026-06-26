from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from .cleanup_verify import verify_strm_paths
from .moviepilot import MoviePilotClient
from .qbittorrent import fetch_qb_torrents


def cleanup_orphan_dotqb_roots(
    mp_base_url: str,
    mp_token: str,
    title: str,
    source_roots: Sequence[str],
    destination_roots: Sequence[str],
    strm_roots: Sequence[str],
    expected_tmdbid: int = 0,
    expected_hash_prefixes: Optional[Sequence[str]] = None,
    expected_episode_count: int = 0,
    expected_episode_min: int = 0,
    expected_episode_max: int = 0,
    qb_base_url: str = "",
    qb_user: str = "",
    qb_pass: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
    dotqb_suffix: str = ".!qB",
    timeout: int = 20,
) -> Dict[str, object]:
    blockers: List[str] = []
    warnings: List[str] = []
    aliases = _normalize_aliases(path_aliases or {})
    hash_prefixes = _normalize_hash_prefixes(expected_hash_prefixes or [])
    hash_prefix_list = sorted(hash_prefixes)

    if not source_roots:
        blockers.append("source_root_required")
    if not destination_roots:
        blockers.append("destination_root_required")
    if not strm_roots:
        blockers.append("strm_root_required")
    if not hash_prefixes:
        blockers.append("expected_hash_prefix_required")

    strm_report = verify_strm_paths(
        title,
        strm_roots,
        expected_episode_count=expected_episode_count,
        expected_episode_min=expected_episode_min,
        expected_episode_max=expected_episode_max,
    )
    if not strm_report.get("ok"):
        blockers.extend(str(blocker) for blocker in strm_report.get("blockers", []) if blocker)
    warnings.extend(str(warning) for warning in strm_report.get("warnings", []) if warning)

    mp_records = []
    if mp_base_url:
        try:
            mp_records = MoviePilotClient(mp_base_url, mp_token, timeout=timeout).transfer_history(title)
        except Exception as exc:  # pragma: no cover - exercised in integration
            blockers.append("mp_transfer_history_check_failed")
            warnings.append(f"mp_error:{type(exc).__name__}:{exc}")
    else:
        blockers.append("mp_base_url_required")
    matched_mp = [
        record
        for record in mp_records
        if (not expected_tmdbid or record.tmdbid in {0, expected_tmdbid})
        and (not title or record.title == title)
    ]
    if matched_mp:
        blockers.append("mp_transfer_history_still_present")

    qb_torrents: Optional[List[Dict[str, object]]] = None
    if qb_base_url:
        try:
            qb_torrents = fetch_qb_torrents(qb_base_url, qb_user, qb_pass)
        except Exception as exc:  # pragma: no cover - exercised in integration
            blockers.append("qb_torrent_check_failed")
            warnings.append(f"qb_error:{type(exc).__name__}:{exc}")
    else:
        blockers.append("qb_base_url_required")
    qb_hash_matches = _qb_hash_matches(qb_torrents or [], hash_prefixes)
    qb_path_matches = _qb_path_matches(qb_torrents or [], source_roots, aliases)
    if qb_hash_matches:
        blockers.append("qb_torrent_hash_still_present")
    if qb_path_matches:
        blockers.append("qb_torrent_path_still_present")

    destination_checks = [_path_exists_row(path) for path in destination_roots]
    if any(item["exists"] for item in destination_checks):
        blockers.append("destination_root_still_exists")

    source_checks = [_dotqb_root_check(path, dotqb_suffix) for path in source_roots]
    if any(item.get("blocked") for item in source_checks):
        blockers.append("source_root_not_safe_dotqb_orphan")
    if any(not item.get("exists") for item in source_checks):
        warnings.append("source_root_already_missing")
    if not any(item.get("dotqb_file_count") for item in source_checks):
        blockers.append("dotqb_files_not_found")

    deleted_files: List[Dict[str, object]] = []
    removed_dirs: List[str] = []
    if not blockers:
        for check in source_checks:
            for file_path in check.get("dotqb_files", []):
                path = Path(str(file_path))
                size = path.stat().st_size if path.exists() else 0
                path.unlink()
                deleted_files.append({"path": str(path), "size_bytes": size})
        removed_dirs = _remove_empty_source_dirs(source_roots)

    post_source_checks = [_dotqb_root_check(path, dotqb_suffix) for path in source_roots]
    post_blockers: List[str] = []
    if deleted_files and any(item.get("exists") for item in post_source_checks):
        post_blockers.append("source_root_still_exists_after_dotqb_cleanup")

    all_blockers = sorted(set(blockers + post_blockers))
    return {
        "mode": "dotqb-orphan-cleanup",
        "title": title,
        "ok": not all_blockers and bool(deleted_files),
        "expected": {
            "tmdbid": expected_tmdbid,
            "hash_prefixes": hash_prefix_list,
            "episode_count": expected_episode_count,
            "episode_min": expected_episode_min,
            "episode_max": expected_episode_max,
        },
        "mp_transfer_history": {
            "records_found": len(mp_records),
            "records_matched": len(matched_mp),
            "matched_ids": [record.id for record in matched_mp],
        },
        "qbittorrent": {
            "configured": qb_torrents is not None,
            "hash_matches": qb_hash_matches,
            "path_matches": qb_path_matches,
        },
        "filesystem": {
            "source_roots_before": source_checks,
            "destination_roots": destination_checks,
            "source_roots_after": post_source_checks,
            "deleted_files": deleted_files,
            "removed_dirs": removed_dirs,
        },
        "strm": strm_report,
        "blockers": all_blockers,
        "warnings": sorted(set(warnings)),
        "safety": "approved orphan .!qB cleanup only; deletes files ending with .!qB under explicitly named source roots after MP/qB/hlink/STRM gates pass, and removes only empty directories",
    }


def render_dotqb_orphan_cleanup(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    fs = report.get("filesystem") if isinstance(report.get("filesystem"), dict) else {}
    deleted = fs.get("deleted_files") if isinstance(fs.get("deleted_files"), list) else []
    lines = [
        "# Orphan .!qB Cleanup",
        "",
        f"- Title: `{report.get('title', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Deleted .!qB files: `{len(deleted)}`",
        f"- Deleted bytes: `{sum(int(item.get('size_bytes') or 0) for item in deleted if isinstance(item, dict))}`",
        "- Safety: only `. !qB` orphan files under explicit source roots are deleted after service checks pass.",
    ]
    blockers = report.get("blockers")
    if isinstance(blockers, list) and blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- `{blocker}`" for blocker in blockers)
    return "\n".join(lines)


def _dotqb_root_check(path: str, dotqb_suffix: str) -> Dict[str, object]:
    root = Path(path)
    if not root.exists():
        return {
            "path": path,
            "exists": False,
            "blocked": False,
            "file_count": 0,
            "dotqb_file_count": 0,
            "non_dotqb_files": [],
            "dotqb_files": [],
            "total_bytes": 0,
        }
    blocked = not _is_narrow_source_root(root)
    files = [item for item in root.rglob("*") if item.is_file()]
    dotqb_files = [item for item in files if str(item).endswith(dotqb_suffix)]
    non_dotqb_files = [item for item in files if not str(item).endswith(dotqb_suffix)]
    if non_dotqb_files:
        blocked = True
    return {
        "path": path,
        "exists": True,
        "blocked": blocked,
        "file_count": len(files),
        "dotqb_file_count": len(dotqb_files),
        "non_dotqb_files": [str(item) for item in non_dotqb_files[:20]],
        "dotqb_files": [str(item) for item in dotqb_files],
        "total_bytes": sum(item.stat().st_size for item in files),
    }


def _remove_empty_source_dirs(source_roots: Sequence[str]) -> List[str]:
    removed: List[str] = []
    for raw_root in source_roots:
        root = Path(raw_root)
        if not root.exists():
            continue
        dirs = [item for item in root.rglob("*") if item.is_dir()]
        for directory in sorted(dirs, key=lambda item: len(item.parts), reverse=True):
            try:
                directory.rmdir()
                removed.append(str(directory))
            except OSError:
                pass
        try:
            root.rmdir()
            removed.append(str(root))
        except OSError:
            pass
    return removed


def _is_narrow_source_root(path: Path) -> bool:
    name = path.name.strip()
    if not name or name in {"TV", "Movies", "Movie", "hlink", "downloads", "download"}:
        return False
    return len(path.parts) >= 4


def _qb_hash_matches(torrents: Sequence[Dict[str, object]], hash_prefixes: Set[str]) -> List[Dict[str, object]]:
    matches: List[Dict[str, object]] = []
    for torrent in torrents:
        torrent_hash = str(torrent.get("hash") or "").lower()
        if not any(torrent_hash.startswith(prefix) for prefix in hash_prefixes):
            continue
        matches.append(_qb_row(torrent))
    return matches


def _qb_path_matches(torrents: Sequence[Dict[str, object]], source_roots: Sequence[str], path_aliases: Dict[str, str]) -> List[Dict[str, object]]:
    source_variants = {variant for root in source_roots for variant in _path_variants(root, path_aliases)}
    matches: List[Dict[str, object]] = []
    for torrent in torrents:
        content_paths = _path_variants(str(torrent.get("content_path") or ""), path_aliases)
        save_paths = _path_variants(str(torrent.get("save_path") or ""), path_aliases)
        content_matches = any(_paths_overlap(source, content_path) for source in source_variants for content_path in content_paths)
        save_path_matches = any(_path_is_same_or_child(save_path, source) for source in source_variants for save_path in save_paths)
        if content_matches or save_path_matches:
            matches.append(_qb_row(torrent))
    return matches


def _path_variants(path: str, path_aliases: Dict[str, str]) -> Set[str]:
    normalized = str(path or "").rstrip("/")
    if not normalized:
        return set()
    variants = {normalized}
    for left, right in path_aliases.items():
        for source, target in ((left, right), (right, left)):
            if normalized == source or normalized.startswith(source + "/"):
                variants.add(target + normalized[len(source) :])
    return variants


def _paths_overlap(left: str, right: str) -> bool:
    return bool(left and right and (left == right or left.startswith(right + "/") or right.startswith(left + "/")))


def _path_is_same_or_child(path: str, parent: str) -> bool:
    return bool(path and parent and (path == parent or path.startswith(parent + "/")))


def _qb_row(torrent: Dict[str, object]) -> Dict[str, object]:
    return {
        "name": str(torrent.get("name") or ""),
        "hash_prefix": str(torrent.get("hash") or "")[:12],
        "state": str(torrent.get("state") or ""),
        "save_path": str(torrent.get("save_path") or ""),
        "content_path": str(torrent.get("content_path") or ""),
    }


def _path_exists_row(path: str) -> Dict[str, object]:
    return {"path": path, "exists": Path(path).exists()}


def _normalize_aliases(path_aliases: Dict[str, str]) -> Dict[str, str]:
    return {key.rstrip("/"): value.rstrip("/") for key, value in path_aliases.items() if key and value}


def _normalize_hash_prefixes(values: Sequence[str]) -> Set[str]:
    prefixes: Set[str] = set()
    for value in values:
        for part in str(value or "").split(","):
            token = part.strip().lower()
            if token:
                prefixes.add(token)
    return prefixes
