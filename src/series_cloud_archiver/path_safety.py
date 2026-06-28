from __future__ import annotations

from typing import Sequence


def cloud_media_paths(paths: Sequence[str]) -> list[str]:
    return [path for path in paths if looks_like_cloud_media_path(path)]


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
