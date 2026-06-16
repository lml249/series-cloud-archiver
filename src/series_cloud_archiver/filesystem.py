from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence

from .episode import episode_signal, is_video_file
from .models import FileSystemSeries


def _is_excluded(path: Path, exclude_names: Sequence[str]) -> bool:
    lowered = path.name.lower()
    return any(lowered == item.lower() for item in exclude_names)


def _iter_video_files(root: Path, max_depth: int, exclude_names: Sequence[str]) -> Iterator[Path]:
    base_depth = len(root.parts)
    for current, dirs, files in os.walk(str(root)):
        current_path = Path(current)
        dirs[:] = [
            name
            for name in dirs
            if not _is_excluded(current_path / name, exclude_names)
            and len((current_path / name).parts) - base_depth <= max_depth
        ]
        for file_name in files:
            path = current_path / file_name
            if is_video_file(path):
                yield path


def scan_series_roots(
    roots: Iterable[str],
    max_depth: int,
    min_age_days: int,
    exclude_names: Sequence[str],
) -> List[FileSystemSeries]:
    now = os.path.getmtime("/") if Path("/").exists() else 0
    now = max(now, __import__("time").time())
    results: List[FileSystemSeries] = []

    for root_value in roots:
        root = Path(root_value)
        if not root.exists():
            continue

        direct_children = [child for child in root.iterdir() if child.is_dir() and not _is_excluded(child, exclude_names)]
        scan_targets = direct_children or [root]

        for target in scan_targets:
            videos = list(_iter_video_files(target, max_depth=max_depth, exclude_names=exclude_names))
            if not videos:
                continue
            total_size = 0
            latest_mtime = 0.0
            names = [target.name]
            for video in videos:
                try:
                    stat = video.stat()
                except OSError:
                    continue
                total_size += stat.st_size
                latest_mtime = max(latest_mtime, stat.st_mtime)
                names.append(video.name)
            if not total_size:
                continue
            age_days = max(0.0, (now - latest_mtime) / 86400.0)
            if age_days < min_age_days:
                continue
            results.append(
                FileSystemSeries(
                    title=target.name,
                    path=str(target),
                    size_bytes=total_size,
                    video_count=len(videos),
                    latest_mtime=latest_mtime,
                    age_days=age_days,
                    signal=episode_signal(names),
                )
            )
    return results

