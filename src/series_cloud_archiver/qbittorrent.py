from __future__ import annotations

import json
from pathlib import Path
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple

from .models import FileSystemSeries, QBTorrentEvidence


UP_STATES = {
    "uploading",
    "stalledUP",
    "pausedUP",
    "queuedUP",
    "forcedUP",
    "checkingUP",
}


class QBClient:
    def __init__(self, base_url: str, user: str = "", qb_pass: str = "", timeout: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.qb_pass = qb_pass
        self.timeout = timeout
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def login(self) -> None:
        if not self.user and not self.qb_pass:
            return
        body = urllib.parse.urlencode({"username": self.user, "password": self.qb_pass}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/v2/auth/login",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            payload = response.read().decode("utf-8", "replace").strip()
        if payload.rstrip(".").lower() != "ok":
            raise RuntimeError("qBittorrent login failed")

    def torrents(self) -> List[Dict[str, object]]:
        request = urllib.request.Request(f"{self.base_url}/api/v2/torrents/info")
        with self.opener.open(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    def torrent_files(self, torrent_hash: str) -> List[Dict[str, object]]:
        query = urllib.parse.urlencode({"hash": torrent_hash})
        request = urllib.request.Request(f"{self.base_url}/api/v2/torrents/files?{query}")
        with self.opener.open(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))

    def preferences(self) -> Dict[str, object]:
        request = urllib.request.Request(f"{self.base_url}/api/v2/app/preferences")
        with self.opener.open(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        return payload if isinstance(payload, dict) else {}


def fetch_qb_evidence(base_url: str, user: str = "", qb_pass: str = "") -> List[QBTorrentEvidence]:
    items = fetch_qb_torrents(base_url, user, qb_pass)
    evidence: List[QBTorrentEvidence] = []
    for item in items:
        seeding_seconds = int(item.get("seeding_time") or 0)
        evidence.append(
            QBTorrentEvidence(
                name=str(item.get("name") or ""),
                hash=str(item.get("hash") or ""),
                state=str(item.get("state") or ""),
                save_path=str(item.get("save_path") or ""),
                content_path=str(item.get("content_path") or ""),
                progress=float(item.get("progress") or 0.0),
                seeding_time_seconds=seeding_seconds,
                seed_days=seeding_seconds / 86400.0,
                size_bytes=int(item.get("size") or item.get("total_size") or 0),
            )
        )
    return evidence


def fetch_qb_torrents(base_url: str, user: str = "", qb_pass: str = "") -> List[Dict[str, object]]:
    client = QBClient(base_url=base_url, user=user, qb_pass=qb_pass)
    client.login()
    return client.torrents()


def audit_dotqb_files(
    base_url: str,
    user: str = "",
    qb_pass: str = "",
    scan_roots: Optional[List[str]] = None,
    path_aliases: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    dotqb_suffix: str = ".!qB",
) -> Dict[str, object]:
    client = QBClient(base_url=base_url, user=user, qb_pass=qb_pass, timeout=timeout)
    client.login()
    torrents = client.torrents()
    preferences = client.preferences()
    aliases = {key.rstrip("/"): value.rstrip("/") for key, value in (path_aliases or {}).items() if key and value}
    file_index: Dict[str, Dict[str, object]] = {}
    torrent_summaries: List[Dict[str, object]] = []

    for torrent in torrents:
        files = client.torrent_files(str(torrent.get("hash") or ""))
        summary, paths = _dotqb_torrent_summary(torrent, files, aliases, dotqb_suffix)
        torrent_summaries.append(summary)
        for host_path in paths:
            file_index[host_path] = summary
            file_index[host_path + dotqb_suffix] = summary

    host_scan_roots = _dotqb_scan_roots(scan_roots, torrents, preferences, aliases)
    dotqb_items = _scan_dotqb_files(host_scan_roots, dotqb_suffix)
    audited_items = [_dotqb_item_summary(item, file_index, aliases, dotqb_suffix) for item in dotqb_items]
    categories: Dict[str, int] = {}
    for item in audited_items:
        category = str(item.get("category") or "unknown")
        categories[category] = categories.get(category, 0) + 1

    by_parent = _dotqb_group_by(audited_items, "parent")
    by_torrent = _dotqb_group_by(audited_items, "torrent_key")
    state_counts: Dict[str, int] = {}
    for torrent in torrent_summaries:
        state = str(torrent.get("state") or "")
        state_counts[state] = state_counts.get(state, 0) + 1

    missing_torrents = [
        torrent
        for torrent in torrent_summaries
        if str(torrent.get("state") or "") == "missingFiles" or "miss" in str(torrent.get("state") or "").lower() or "error" in str(torrent.get("state") or "").lower()
    ]
    incomplete_torrents = [torrent for torrent in torrent_summaries if float(torrent.get("progress") or 0.0) < 0.999]
    complete_with_dotqb = [torrent for torrent in torrent_summaries if float(torrent.get("progress") or 0.0) >= 0.999 and int(torrent.get("file_dot_qb_count") or 0) > 0]

    return {
        "mode": "readonly-qb-dotqb-audit",
        "ok": True,
        "configured": bool(base_url),
        "total_torrents": len(torrents),
        "state_counts": dict(sorted(state_counts.items())),
        "missing_count": len(missing_torrents),
        "incomplete_count": len(incomplete_torrents),
        "complete_with_dotqb_count": len(complete_with_dotqb),
        "qb_preferences": {
            "save_path": preferences.get("save_path"),
            "temp_path_enabled": preferences.get("temp_path_enabled"),
            "temp_path": preferences.get("temp_path"),
            "incomplete_files_ext": preferences.get("incomplete_files_ext"),
        },
        "path_aliases": aliases,
        "scan_roots": host_scan_roots,
        "dotqb_suffix": dotqb_suffix,
        "dot_qb_total_count": len(audited_items),
        "dot_qb_total_bytes": sum(int(item.get("size_bytes") or 0) for item in audited_items),
        "dot_qb_categories": dict(sorted(categories.items())),
        "dot_qb_top_parents": by_parent[:80],
        "dot_qb_by_torrent": by_torrent[:120],
        "orphan_items": [item for item in audited_items if item.get("category") == "orphan_not_in_qb"][:100],
        "complete_task_with_dotqb_items": [item for item in audited_items if item.get("category") == "complete_task_with_dotqb"][:100],
        "missing_torrents": missing_torrents[:100],
        "incomplete_torrents": incomplete_torrents[:120],
        "classification_rules": {
            "incomplete_task_temp_file": "qB still references the file and torrent progress is below 99.9%; usually an unfinished temporary file",
            "qb_missing_with_dotqb": "qB reports missingFiles/error but a .!qB file still exists at the expected path; needs manual review before cleanup",
            "complete_task_with_dotqb": "qB reports the torrent complete but the host still has .!qB suffix file; likely stale or inconsistent and needs recheck",
            "orphan_not_in_qb": "the .!qB file was not matched to any current qB file entry; candidate for later cleanup after review",
        },
        "safety": "readonly qB Web API and filesystem scan only; no qB action and no file write/delete/move is performed",
    }


def render_dotqb_audit_report(report: Dict[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2)
    lines = [
        "# qB .!qB Audit",
        "",
        f"- OK: `{bool(report.get('ok'))}`",
        f"- Total torrents: `{report.get('total_torrents', 0)}`",
        f"- Missing torrents: `{report.get('missing_count', 0)}`",
        f"- Incomplete torrents: `{report.get('incomplete_count', 0)}`",
        f"- .!qB files: `{report.get('dot_qb_total_count', 0)}`",
        f"- .!qB bytes: `{report.get('dot_qb_total_bytes', 0)}`",
        "- Safety: readonly only; no qB or filesystem mutation was performed.",
        "",
        "## Categories",
        "",
    ]
    categories = report.get("dot_qb_categories") if isinstance(report.get("dot_qb_categories"), dict) else {}
    for category, count in sorted(categories.items()):
        lines.append(f"- `{category}`: `{count}`")
    lines.extend(["", "## Top Parents", "", "| Count | Size | Parent |", "| ---: | ---: | --- |"])
    for row in report.get("dot_qb_top_parents", []):
        if not isinstance(row, dict):
            continue
        lines.append(f"| {row.get('count', 0)} | {_format_bytes(int(row.get('bytes') or 0))} | {_escape_md(str(row.get('key') or ''))} |")
    lines.extend(["", "## Orphans", "", "| Size | Path |", "| ---: | --- |"])
    for item in report.get("orphan_items", []):
        if not isinstance(item, dict):
            continue
        lines.append(f"| {_format_bytes(int(item.get('size_bytes') or 0))} | {_escape_md(str(item.get('host_path') or ''))} |")
    return "\n".join(lines)


def _path_variants(path: str, aliases: Dict[str, str]) -> List[str]:
    normalized = path.rstrip("/")
    variants = {normalized}
    for left, right in aliases.items():
        left = left.rstrip("/")
        right = right.rstrip("/")
        if normalized == left or normalized.startswith(left + "/"):
            variants.add(right + normalized[len(left) :])
        if normalized == right or normalized.startswith(right + "/"):
            variants.add(left + normalized[len(right) :])
    return sorted(variants)


def _dotqb_torrent_summary(
    torrent: Dict[str, object],
    files: List[Dict[str, object]],
    aliases: Dict[str, str],
    dotqb_suffix: str,
) -> Tuple[Dict[str, object], List[str]]:
    save_path = str(torrent.get("save_path") or "").rstrip("/")
    host_paths: List[str] = []
    file_samples = []
    exists_count = 0
    dotqb_count = 0
    missing_without_dotqb_count = 0
    for item in files:
        rel_path = str(item.get("name") or "").strip("/")
        container_path = str(PurePosixPath(save_path) / rel_path) if save_path and rel_path else rel_path
        host_path = _map_path(container_path, aliases)
        host_paths.append(host_path)
        exists = Path(host_path).exists()
        dotqb_exists = Path(host_path + dotqb_suffix).exists()
        if exists:
            exists_count += 1
        if dotqb_exists:
            dotqb_count += 1
        if not exists and not dotqb_exists:
            missing_without_dotqb_count += 1
        if len(file_samples) < 8:
            file_samples.append(
                {
                    "name": rel_path,
                    "container_path": container_path,
                    "host_path": host_path,
                    "exists": exists,
                    "dot_qb_exists": dotqb_exists,
                    "progress": round(float(item.get("progress") or 0.0), 6),
                    "priority": int(item.get("priority") or 0),
                    "size_bytes": int(item.get("size") or 0),
                }
            )
    content_path = str(torrent.get("content_path") or "")
    content_host_path = _map_path(content_path, aliases)
    return (
        {
            "name": str(torrent.get("name") or ""),
            "hash_prefix": str(torrent.get("hash") or "")[:12],
            "state": str(torrent.get("state") or ""),
            "progress": round(float(torrent.get("progress") or 0.0), 6),
            "save_path": save_path,
            "host_save_path": _map_path(save_path, aliases),
            "content_path": content_path,
            "host_content_path": content_host_path,
            "content_exists": Path(content_host_path).exists(),
            "content_dot_qb_exists": Path(content_host_path + dotqb_suffix).exists(),
            "size_bytes": int(torrent.get("size") or torrent.get("total_size") or 0),
            "seeding_time_days": round(float(torrent.get("seeding_time") or 0) / 86400.0, 2),
            "num_files": len(files),
            "file_exists_count": exists_count,
            "file_dot_qb_count": dotqb_count,
            "file_missing_without_dot_qb_count": missing_without_dotqb_count,
            "files_sample": file_samples,
        },
        host_paths,
    )


def _dotqb_scan_roots(
    scan_roots: Optional[List[str]],
    torrents: List[Dict[str, object]],
    preferences: Dict[str, object],
    aliases: Dict[str, str],
) -> List[str]:
    roots = set()
    for root in scan_roots or []:
        if root:
            explicit_root = root.rstrip("/")
            roots.add(explicit_root if Path(explicit_root).exists() else _map_path(explicit_root, aliases))
    if not roots:
        for key in ("save_path", "temp_path"):
            value = preferences.get(key)
            if isinstance(value, str) and value.startswith("/"):
                roots.add(_map_path(value.rstrip("/"), aliases))
        for torrent in torrents:
            save_path = str(torrent.get("save_path") or "").rstrip("/")
            if save_path.startswith("/"):
                roots.add(_map_path(save_path, aliases))
    return sorted(root for root in roots if root and Path(root).exists())


def _scan_dotqb_files(scan_roots: List[str], dotqb_suffix: str) -> List[Dict[str, object]]:
    items = []
    pattern = f"*{dotqb_suffix}"
    seen = set()
    for root in scan_roots:
        for path in Path(root).rglob(pattern):
            path_text = str(path)
            if path_text in seen:
                continue
            seen.add(path_text)
            try:
                stat = path.stat()
            except OSError:
                continue
            items.append({"host_path": path_text, "parent": str(path.parent), "size_bytes": stat.st_size})
    return items


def _dotqb_item_summary(
    item: Dict[str, object],
    file_index: Dict[str, Dict[str, object]],
    aliases: Dict[str, str],
    dotqb_suffix: str,
) -> Dict[str, object]:
    host_path = str(item.get("host_path") or "")
    base_host_path = host_path[: -len(dotqb_suffix)] if host_path.endswith(dotqb_suffix) else host_path
    owner = file_index.get(host_path) or file_index.get(base_host_path)
    container_path = _unmap_path(host_path, aliases)
    base_exists = Path(base_host_path).exists()
    category = "orphan_not_in_qb"
    torrent_key = "orphan_not_in_qb"
    if owner:
        torrent_key = str(owner.get("hash_prefix") or "") or "matched_no_hash"
        state = str(owner.get("state") or "")
        progress = float(owner.get("progress") or 0.0)
        if state == "missingFiles" or "miss" in state.lower() or "error" in state.lower():
            category = "qb_missing_with_dotqb"
        elif progress >= 0.999:
            category = "complete_task_with_dotqb"
        else:
            category = "incomplete_task_temp_file"
    return {
        "host_path": host_path,
        "base_host_path": base_host_path,
        "container_path": container_path,
        "base_exists": base_exists,
        "size_bytes": int(item.get("size_bytes") or 0),
        "parent": str(item.get("parent") or ""),
        "category": category,
        "matched_to_qb": bool(owner),
        "torrent_key": torrent_key,
        "torrent": {
            "hash_prefix": str(owner.get("hash_prefix") or "") if owner else "",
            "name": str(owner.get("name") or "") if owner else "",
            "state": str(owner.get("state") or "") if owner else "",
            "progress": float(owner.get("progress") or 0.0) if owner else None,
        },
    }


def _dotqb_group_by(items: List[Dict[str, object]], key_name: str) -> List[Dict[str, object]]:
    groups: Dict[str, Dict[str, object]] = {}
    for item in items:
        key = str(item.get(key_name) or "")
        if key_name == "torrent_key" and key:
            torrent = item.get("torrent") if isinstance(item.get("torrent"), dict) else {}
            key = key if key != "orphan_not_in_qb" else "orphan_not_in_qb"
            label = str(torrent.get("name") or "") if torrent else ""
        else:
            label = key
        row = groups.setdefault(key, {"key": key, "label": label, "count": 0, "bytes": 0, "categories": {}, "sample": []})
        row["count"] = int(row["count"]) + 1
        row["bytes"] = int(row["bytes"]) + int(item.get("size_bytes") or 0)
        categories = row["categories"] if isinstance(row.get("categories"), dict) else {}
        category = str(item.get("category") or "unknown")
        categories[category] = int(categories.get(category) or 0) + 1
        row["categories"] = categories
        if len(row["sample"]) < 5 and isinstance(row["sample"], list):
            row["sample"].append(item)
    return sorted(groups.values(), key=lambda row: (int(row.get("count") or 0), int(row.get("bytes") or 0)), reverse=True)


def _map_path(path: str, aliases: Dict[str, str]) -> str:
    text = str(path or "").rstrip("/")
    for source, target in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        source = source.rstrip("/")
        target = target.rstrip("/")
        if text == source or text.startswith(source + "/"):
            return target + text[len(source) :]
    return text


def _unmap_path(path: str, aliases: Dict[str, str]) -> str:
    text = str(path or "").rstrip("/")
    for source, target in sorted(aliases.items(), key=lambda item: len(item[1]), reverse=True):
        source = source.rstrip("/")
        target = target.rstrip("/")
        if text == target or text.startswith(target + "/"):
            return source + text[len(target) :]
    return text


def _format_bytes(size: int) -> str:
    value = float(size)
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    return f"{int(value)} {unit}" if unit == "B" else f"{value:.2f} {unit}"


def _escape_md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _torrent_content_paths(torrent: QBTorrentEvidence) -> List[str]:
    paths = set()
    content_path = torrent.content_path.rstrip("/")
    if content_path:
        paths.add(content_path)
    save_path = torrent.save_path.rstrip("/")
    name = torrent.name.strip().strip("/")
    if save_path and name:
        paths.add(str(PurePosixPath(save_path) / name))
    return sorted(paths)


def match_torrent(
    series: FileSystemSeries,
    torrents: List[QBTorrentEvidence],
    path_aliases: Optional[Dict[str, str]] = None,
) -> Optional[QBTorrentEvidence]:
    aliases = path_aliases or {}
    series_path = series.path.rstrip("/")
    series_variants = _path_variants(series_path, aliases)
    best: Optional[QBTorrentEvidence] = None
    best_score = 0
    for torrent in torrents:
        paths = []
        for path in _torrent_content_paths(torrent):
            paths.extend(_path_variants(path, aliases))
        score = 0
        if any(variant in paths for variant in series_variants):
            score = 100
        elif any(
            path
            and (
                variant.startswith(path + "/")
                or path.startswith(variant + "/")
            )
            for path in paths
            for variant in series_variants
        ):
            score = 80
        elif torrent.name and torrent.name.lower() in series.title.lower():
            score = 40
        elif series.title.lower() in torrent.name.lower():
            score = 35
        if score > best_score:
            best_score = score
            best = torrent
    return best
