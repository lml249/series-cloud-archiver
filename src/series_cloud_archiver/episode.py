from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Set

from .models import EpisodeSignal


VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".m4v",
    ".ts",
    ".m2ts",
    ".wmv",
    ".flv",
    ".webm",
    ".rmvb",
}

SEASON_EPISODE_PATTERNS = [
    re.compile(r"(?i)\bS(?P<season>\d{1,2})[ ._-]*E(?P<episode>\d{1,3})\b"),
    re.compile(r"(?i)\b(?P<season>\d{1,2})x(?P<episode>\d{1,3})\b"),
]

EPISODE_PATTERNS = [
    re.compile(r"(?i)\bE(?P<episode>\d{1,3})\b"),
    re.compile(r"(?i)\bEP(?P<episode>\d{1,3})\b"),
    re.compile(r"第\s*(?P<episode>\d{1,3})\s*[集话話]"),
]

COMPLETE_PATTERNS = [
    (re.compile(r"(?i)\bcomplete\b"), "complete"),
    (re.compile(r"(?i)\b全\s*(?P<count>\d{1,4})\s*集\b"), "all-episodes"),
    (re.compile(r"(?i)\bE(?P<start>\d{1,3})\s*[-~_]\s*E?(?P<end>\d{1,3})\b"), "episode-range"),
    (re.compile(r"(?i)\bS(?P<start>\d{1,2})\s*[-~_]\s*S?(?P<end>\d{1,2})\b"), "season-range"),
    (re.compile(r"(?i)完结|全集|全剧|完整版"), "cn-complete"),
]


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def episode_signal(names: Iterable[str]) -> EpisodeSignal:
    seasons: Set[int] = set()
    episodes: Set[int] = set()
    markers: List[str] = []
    inferred_count = 0

    for name in names:
        for pattern in SEASON_EPISODE_PATTERNS:
            for match in pattern.finditer(name):
                seasons.add(int(match.group("season")))
                episodes.add(int(match.group("episode")))

        for pattern in EPISODE_PATTERNS:
            for match in pattern.finditer(name):
                episodes.add(int(match.group("episode")))

        for pattern, marker in COMPLETE_PATTERNS:
            match = pattern.search(name)
            if not match:
                continue
            if marker not in markers:
                markers.append(marker)
            groups = match.groupdict()
            if groups.get("count"):
                inferred_count = max(inferred_count, int(groups["count"]))
            if groups.get("start") and groups.get("end") and "E" in match.group(0).upper():
                start = int(groups["start"])
                end = int(groups["end"])
                if end >= start:
                    inferred_count = max(inferred_count, end - start + 1)

    return EpisodeSignal(
        seasons=sorted(seasons),
        episodes=sorted(episodes),
        complete_markers=markers,
        inferred_episode_count=inferred_count,
    )

