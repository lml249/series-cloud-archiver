from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .models import CloudCheckItem, CloudCheckReport


TMDBID_PATTERN = re.compile(r"\{tmdbid=(?P<tmdbid>\d+)\}", re.IGNORECASE)
SEASON_PATTERNS = [
    re.compile(r"(?i)\bS(?P<season>\d{1,2})\s*E\d{1,3}\b"),
    re.compile(r"(?i)\bSeason\s*(?P<season>\d{1,2})\b"),
    re.compile(r"第\s*(?P<season>\d{1,2})\s*季"),
]
EPISODE_PATTERNS = [
    re.compile(r"(?i)\bS\d{1,2}\s*E(?P<episode>\d{1,3})\b"),
    re.compile(r"(?i)\bE(?P<episode>\d{1,3})\b"),
    re.compile(r"第\s*(?P<episode>\d{1,3})\s*[集话話]"),
]
TECHNICAL_TOKENS = {
    "aac",
    "ac3",
    "adweb",
    "atmos",
    "bluray",
    "chdbits",
    "chdweb",
    "ddp",
    "dovi",
    "dts",
    "dv",
    "fhd",
    "frds",
    "frogweb",
    "h264",
    "h265",
    "hdr",
    "hdr10",
    "hevc",
    "hhweb",
    "hq",
    "nf",
    "ourtv",
    "ptweb",
    "pterweb",
    "remux",
    "truehd",
    "uhd",
    "web",
    "webdl",
    "x264",
    "x265",
}


def load_scan_report(path: str) -> Dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cloud_check_from_scan_report(
    scan_report: Dict[str, object],
    strm_roots: Iterable[str],
    top: int = 0,
) -> CloudCheckReport:
    roots = [root for root in strm_roots if root]
    warnings: List[str] = []
    index = _build_strm_index(roots, warnings)
    groups = _candidate_groups(scan_report)
    items = [_check_group(group, index) for group in groups.values()]
    items.sort(key=lambda item: (item.status != "cloud_strm_complete", -item.size_bytes, item.title))
    counts = Counter(item.status for item in items)
    if top > 0:
        items = items[:top]
    return CloudCheckReport(
        mode="readonly-cloud-check",
        strm_roots=roots,
        total_candidate_groups=len(groups),
        status_counts=dict(sorted(counts.items())),
        items=items,
        warnings=warnings,
    )


def render_cloud_check_report(report: CloudCheckReport, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    return _render_markdown(report)


def _build_strm_index(
    roots: List[str],
    warnings: List[str],
) -> Dict[Tuple[int, int], Dict[str, object]]:
    index: Dict[Tuple[int, int], Dict[str, object]] = {}
    if not roots:
        warnings.append("strm_roots_not_configured")
        return index

    for root_value in roots:
        root = Path(root_value)
        if not root.exists():
            warnings.append(f"strm_root_missing: {root_value}")
            continue
        for current, _dirs, files in os.walk(root):
            current_path = Path(current)
            for file_name in files:
                if not file_name.lower().endswith(".strm"):
                    continue
                path = current_path / file_name
                tmdbid = _tmdbid_from_text(str(path))
                season = _season_from_text(str(path))
                episode = _episode_from_text(file_name)
                if not tmdbid or not season or not episode:
                    continue
                key = (tmdbid, season)
                entry = index.setdefault(key, {"episodes": set(), "paths": [], "tokens": set()})
                entry["episodes"].add(episode)
                entry["tokens"].update(_title_tokens(str(path)))
                paths = entry["paths"]
                if isinstance(paths, list) and len(paths) < 5:
                    paths.append(str(path))
    return index


def _candidate_groups(scan_report: Dict[str, object]) -> Dict[Tuple[object, ...], Dict[str, object]]:
    groups: Dict[Tuple[object, ...], Dict[str, object]] = {}
    for candidate in scan_report.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        if candidate.get("status") != "candidate_for_cloud_check":
            continue
        tmdbid, season = _identity_from_candidate(candidate)
        key: Tuple[object, ...]
        if tmdbid and season:
            key = ("tmdb", tmdbid, season)
        else:
            key = ("title", _compact(str(candidate.get("title") or "")))
        group = groups.setdefault(
            key,
            {
                "title": _display_title(candidate),
                "tmdbid": tmdbid,
                "season": season,
                "size_bytes": 0,
                "titles": set(),
                "expected_episodes": set(),
                "expected_count": 0,
                "candidate_count": 0,
            },
        )
        group["candidate_count"] = int(group["candidate_count"]) + 1
        group["size_bytes"] = int(group["size_bytes"]) + int(candidate.get("size_bytes") or 0)
        group["titles"].add(str(candidate.get("title") or ""))
        if tmdbid and not group["tmdbid"]:
            group["tmdbid"] = tmdbid
        if season and not group["season"]:
            group["season"] = season
        for episode in _episode_numbers(candidate):
            group["expected_episodes"].add(episode)
        total_episode = _total_episode(candidate)
        if total_episode:
            group["expected_count"] = max(int(group["expected_count"]), total_episode)
        group["expected_count"] = max(int(group["expected_count"]), int(candidate.get("video_count") or 0))
    return groups


def _check_group(
    group: Dict[str, object],
    index: Dict[Tuple[int, int], Dict[str, object]],
) -> CloudCheckItem:
    tmdbid = int(group.get("tmdbid") or 0)
    season = int(group.get("season") or 0)
    expected_episodes = sorted(int(item) for item in group["expected_episodes"])
    expected_count = int(group.get("expected_count") or len(expected_episodes))
    reasons: List[str] = []
    blockers: List[str] = []

    if not expected_episodes and expected_count:
        expected_episodes = list(range(1, expected_count + 1))

    cloud_entry, match_method = _find_cloud_entry(group, index)
    cloud_episodes = sorted(cloud_entry["episodes"]) if cloud_entry else []
    strm_paths_sample = list(cloud_entry["paths"]) if cloud_entry else []
    missing = [episode for episode in expected_episodes if episode not in cloud_episodes]
    extra = [episode for episode in cloud_episodes if expected_episodes and episode not in expected_episodes]

    if not season:
        status = "needs_identity_review"
        blockers.append("missing_season")
    elif not cloud_episodes:
        if tmdbid:
            status = "cloud_strm_not_found"
            blockers.append("no_matching_strm_tmdb_season")
        else:
            status = "needs_identity_review"
            blockers.append("missing_tmdb_and_no_safe_title_match")
    elif expected_episodes and missing:
        status = "cloud_strm_incomplete"
        reasons.append(match_method)
        blockers.append("missing_strm_episodes")
    elif expected_episodes:
        status = "cloud_strm_complete"
        reasons.extend([match_method, "strm_episode_coverage_complete"])
    elif expected_count and len(cloud_episodes) >= expected_count:
        status = "cloud_strm_complete"
        reasons.extend([match_method, "strm_episode_count_ok"])
    elif expected_count:
        status = "cloud_strm_incomplete"
        reasons.append(match_method)
        blockers.append("cloud_episode_count_below_expected")
    else:
        status = "cloud_strm_unknown_expected"
        reasons.append(match_method)
        blockers.append("expected_episode_set_unknown")

    return CloudCheckItem(
        status=status,
        title=str(group.get("title") or ""),
        tmdbid=tmdbid,
        season=season,
        size_bytes=int(group.get("size_bytes") or 0),
        candidate_count=int(group.get("candidate_count") or 0),
        expected_count=len(expected_episodes) or expected_count,
        expected_episodes=expected_episodes,
        cloud_episode_count=len(cloud_episodes),
        cloud_episodes=cloud_episodes,
        missing_episodes=missing,
        extra_cloud_episodes=extra,
        reasons=reasons,
        blockers=blockers,
        titles=sorted(title for title in group["titles"] if title),
        strm_paths_sample=strm_paths_sample,
    )


def _identity_from_candidate(candidate: Dict[str, object]) -> Tuple[int, int]:
    manual = candidate.get("manual_completion") if isinstance(candidate.get("manual_completion"), dict) else {}
    mp = candidate.get("mp") if isinstance(candidate.get("mp"), dict) else {}
    tmdbid = int((manual or {}).get("tmdbid") or (mp or {}).get("tmdbid") or _tmdbid_from_text(str(candidate.get("title") or "")) or 0)
    season = int((manual or {}).get("season") or (mp or {}).get("season") or _season_from_text(str(candidate.get("title") or "")) or 0)
    seasons = candidate.get("seasons")
    if not season and isinstance(seasons, list) and len(seasons) == 1:
        season = int(seasons[0])
    return tmdbid, season


def _find_cloud_entry(
    group: Dict[str, object],
    index: Dict[Tuple[int, int], Dict[str, object]],
) -> Tuple[Optional[Dict[str, object]], str]:
    tmdbid = int(group.get("tmdbid") or 0)
    season = int(group.get("season") or 0)
    if tmdbid and season:
        entry = index.get((tmdbid, season))
        return (entry, "strm_tmdb_season_match") if entry else (None, "")

    if not season:
        return None, ""

    wanted_tokens: Set[str] = set()
    wanted_tokens.update(_title_tokens(str(group.get("title") or "")))
    for title in group.get("titles", set()):
        wanted_tokens.update(_title_tokens(str(title)))
    if not wanted_tokens:
        return None, ""

    best: Optional[Dict[str, object]] = None
    best_score = 0.0
    for (_entry_tmdbid, entry_season), entry in index.items():
        if entry_season != season:
            continue
        entry_tokens = entry.get("tokens", set())
        if not isinstance(entry_tokens, set) or not entry_tokens:
            continue
        overlap = wanted_tokens.intersection(entry_tokens)
        if not overlap:
            continue
        score = len(overlap) / max(1, len(wanted_tokens))
        if score > best_score:
            best_score = score
            best = entry

    if best and best_score >= 0.5:
        return best, "strm_title_season_match"
    return None, ""


def _episode_numbers(candidate: Dict[str, object]) -> Set[int]:
    values = candidate.get("episode_numbers") or candidate.get("episode_sample") or []
    if not isinstance(values, list):
        return set()
    return {int(value) for value in values if isinstance(value, int) or str(value).isdigit()}


def _total_episode(candidate: Dict[str, object]) -> int:
    mp = candidate.get("mp") if isinstance(candidate.get("mp"), dict) else {}
    return int((mp or {}).get("total_episode") or 0)


def _display_title(candidate: Dict[str, object]) -> str:
    manual = candidate.get("manual_completion") if isinstance(candidate.get("manual_completion"), dict) else {}
    mp = candidate.get("mp") if isinstance(candidate.get("mp"), dict) else {}
    return str((manual or {}).get("title") or (mp or {}).get("name") or candidate.get("title") or "")


def _title_tokens(text: str) -> Set[str]:
    tokens = set()
    for raw in re.findall(r"[a-zA-Z]+|[0-9]+|[\u4e00-\u9fff]+", text.casefold()):
        token = raw.strip()
        if not token:
            continue
        if token in TECHNICAL_TOKENS:
            continue
        if token.isdigit():
            continue
        if re.fullmatch(r"s\d{1,2}|e\d{1,3}|v\d+", token):
            continue
        if len(token) <= 1 and not re.search(r"[\u4e00-\u9fff]", token):
            continue
        tokens.add(token)
    return tokens


def _tmdbid_from_text(text: str) -> int:
    match = TMDBID_PATTERN.search(text)
    return int(match.group("tmdbid")) if match else 0


def _season_from_text(text: str) -> int:
    for pattern in SEASON_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group("season"))
    return 0


def _episode_from_text(text: str) -> int:
    for pattern in EPISODE_PATTERNS:
        match = pattern.search(text)
        if match:
            return int(match.group("episode"))
    return 0


def _compact(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.casefold())


def _human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}TB"


def _ep_text(values: List[int]) -> str:
    return ", ".join(f"E{value:02d}" for value in values[:20]) + (" ..." if len(values) > 20 else "")


def _render_markdown(report: CloudCheckReport) -> str:
    lines = [
        "# Series Cloud Archiver Cloud STRM Check",
        "",
        f"- Mode: `{report.mode}`",
        f"- STRM roots: `{', '.join(report.strm_roots)}`",
        f"- Candidate groups checked: `{report.total_candidate_groups}`",
        f"- Status counts before row limit: `{report.status_counts}`",
        "- Safety: readonly STRM filename scan only; no transfer, STRM generation, or deletion is performed.",
        "",
    ]
    if report.warnings:
        lines.append("## Warnings")
        lines.append("")
        for warning in report.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    lines.extend(
        [
            "## Cloud STRM Coverage",
            "",
            "| Status | Size | TMDB ID | Season | Expected | Cloud | Missing | Title | Notes |",
            "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for item in report.items:
        notes = ",".join(item.reasons + item.blockers)
        lines.append(
            "| {status} | {size} | {tmdbid} | {season} | {expected} | {cloud} | {missing} | {title} | {notes} |".format(
                status=item.status,
                size=_human_size(item.size_bytes),
                tmdbid=item.tmdbid or "",
                season=item.season or "",
                expected=item.expected_count,
                cloud=item.cloud_episode_count,
                missing=_ep_text(item.missing_episodes),
                title=item.title.replace("|", "\\|"),
                notes=notes.replace("|", "\\|"),
            )
        )
    lines.append("")
    lines.append(
        "Readonly cloud note: `cloud_strm_complete` only means STRM filenames cover the expected episodes. Cleanup still requires Emby seeing STRM-backed episodes, playback probes, qB seed-age gates, and manual approval."
    )
    return "\n".join(lines)
