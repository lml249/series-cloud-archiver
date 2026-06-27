from __future__ import annotations

import json
import shutil
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .cleanup_verify import verify_strm_paths
from .episode import episode_signal, is_video_file
from .models import EpisodeSignal, FileSystemSeries
from .qbittorrent import QBClient, fetch_qb_evidence, match_torrent


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
) -> Dict[str, object]:
    aliases = _normalize_aliases(path_aliases or {})
    blockers: List[str] = []
    warnings: List[str] = []
    hlink_check = _hlink_root_check(hlink_root)
    if not hlink_check.get("exists"):
        blockers.append("hlink_root_missing")
    if hlink_check.get("non_video_count"):
        warnings.append("hlink_root_contains_non_video_files")
    if hlink_check.get("video_count") != expected_episode_count and expected_episode_count:
        blockers.append("hlink_video_count_mismatch")

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
        },
        "ok": not blockers,
        "ready_for_execute": not blockers,
        "hlink": hlink_check,
        "strm": strm_report,
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
        },
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "safety": "readonly preview only; no qBittorrent action and no filesystem deletion is performed",
    }


def execute_cloud_hlink_cleanup(
    preview: Dict[str, object],
    qb_base_url: str,
    qb_user: str = "",
    qb_pass: str = "",
    path_aliases: Optional[Dict[str, str]] = None,
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
        "qb_delete": delete_result,
        "hlink_delete": removed_hlink,
        "verification": verification,
        "blockers": sorted(set(blockers)),
        "warnings": preview.get("warnings", []) if isinstance(preview.get("warnings"), list) else [],
        "safety": "approved cleanup; qBittorrent delete is called for validated hashes with deleteFiles=true, then only the explicit hlink root is removed",
    }


def render_cloud_hlink_cleanup(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    hlink = report.get("hlink") if isinstance(report.get("hlink"), dict) else {}
    qb = report.get("qbittorrent") if isinstance(report.get("qbittorrent"), dict) else {}
    lines = [
        "# Cloud Hlink Cleanup",
        "",
        f"- Title: `{report.get('title', '')}`",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Ready: `{bool(report.get('ready_for_execute', report.get('ok')))}`",
        f"- hlink root: `{hlink.get('path', '')}`",
        f"- hlink videos: `{hlink.get('video_count', 0)}`",
        f"- qB matches: `{qb.get('matched_count', 0)}`",
        f"- qB hashes: `{qb.get('hashes', [])}`",
        "- Safety: preview is readonly; execute only mutates approved qB hashes and the explicit hlink root.",
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


def _candidate_torrents_for_inode_check(torrents: Iterable[object], series: FileSystemSeries) -> List[object]:
    wanted = _title_token_set(series.title)
    if not wanted:
        return []
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
        if wanted.intersection(tokens):
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
    if root and Path(_map_path(root, aliases)).suffix:
        root = str(PurePosixPath(root).parent)
    if not root and save_path and name:
        root = str(PurePosixPath(save_path) / name)
    return _map_path(root, aliases) if root else ""


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


def _is_narrow_hlink_root(path: Path) -> bool:
    name = path.name.strip()
    if not name or name in {"TV", "Movies", "Movie", "hlink", "downloads", "download"}:
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
