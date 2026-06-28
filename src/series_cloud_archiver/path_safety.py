from __future__ import annotations

from typing import Sequence


def cloud_media_paths(paths: Sequence[str]) -> list[str]:
    return [path for path in paths if looks_like_cloud_media_path(path)]


def non_strm_side_paths(paths: Sequence[str]) -> list[str]:
    return [path for path in paths if path and not looks_like_strm_side_path(path)]


def looks_like_cloud_media_path(path: str) -> bool:
    normalized = str(path or "").strip().replace("\\", "/").rstrip("/")
    if not normalized:
        return False

    path_parts = [part for part in normalized.split("/") if part]
    lowered = normalized.lower()
    lower_parts = [part.lower() for part in path_parts]

    if "已整理" in path_parts or "未整理" in path_parts:
        return True
    if "/media/cloud-media" in lowered or "/cloud/media" in lowered or "/115/media" in lowered:
        return True
    if "cloud-media" in lower_parts or "115-media" in lower_parts:
        return True
    return False


def looks_like_strm_side_path(path: str) -> bool:
    normalized = str(path or "").strip().replace("\\", "/").rstrip("/")
    if not normalized or looks_like_cloud_media_path(normalized):
        return False

    parts = [part for part in normalized.split("/") if part]
    lower_parts = [part.lower() for part in parts]
    lowered = normalized.lower()
    if "strm" in lower_parts:
        return True
    if any(
        part.startswith("strm-")
        or part.startswith("strm_")
        or part.endswith("-strm")
        or part.endswith("_strm")
        or "-strm-" in part
        or "_strm_" in part
        for part in lower_parts
    ):
        return True
    if "/cloud-strm" in lowered or "/mv3/strm" in lowered:
        return True
    return False
