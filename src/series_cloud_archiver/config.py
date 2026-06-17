from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def load_env_file(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    env_path = Path(path)
    if not env_path.exists():
        raise FileNotFoundError(str(env_path))

    values: Dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def _get(values: Dict[str, str], key: str, default: str = "") -> str:
    return os.environ.get(key, values.get(key, default))


def _split_csv(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass
class ScanConfig:
    media_roots: List[str]
    output_format: str = "markdown"
    min_seed_days: int = 7
    min_age_days: int = 1
    max_depth: int = 3
    top: int = 100
    qb_base_url: str = ""
    qb_user: str = ""
    qb_pass: str = ""
    emby_base_url: str = ""
    emby_key: str = ""
    mode: str = "dry-run"
    include_qb: bool = True
    include_emby: bool = False
    path_aliases: Dict[str, str] = field(default_factory=dict)
    exclude_names: List[str] = field(
        default_factory=lambda: [
            "#recycle",
            "@eaDir",
            "@tmp",
            ".deletedByTMM",
            "sample",
            "samples",
            "trailer",
            "trailers",
            "extras",
        ]
    )


def config_from_env(env_file: Optional[str], media_roots: Iterable[str]) -> ScanConfig:
    values = load_env_file(env_file)
    roots = list(media_roots) or _split_csv(_get(values, "ARCHIVER_MEDIA_ROOTS"))
    return ScanConfig(
        media_roots=roots,
        output_format=_get(values, "ARCHIVER_OUTPUT_FORMAT", "markdown"),
        min_seed_days=int(_get(values, "MIN_SEED_DAYS", "7")),
        min_age_days=int(_get(values, "ARCHIVER_MIN_AGE_DAYS", "1")),
        max_depth=int(_get(values, "ARCHIVER_MAX_DEPTH", "3")),
        top=int(_get(values, "ARCHIVER_TOP", "100")),
        qb_base_url=_get(values, "QB_BASE_URL"),
        qb_user=_get(values, "QB_USERNAME"),
        qb_pass=_get(values, "QB_PASSWORD"),
        emby_base_url=_get(values, "EMBY_BASE_URL"),
        emby_key=_get(values, "EMBY_API_KEY"),
        mode=_get(values, "ARCHIVER_MODE", "dry-run"),
        include_qb=_get(values, "ARCHIVER_INCLUDE_QB", "true").lower() != "false",
        include_emby=_get(values, "ARCHIVER_INCLUDE_EMBY", "false").lower() == "true",
        path_aliases=_parse_aliases(_get(values, "ARCHIVER_PATH_ALIASES")),
    )


def db_path_from_env(env_file: Optional[str]) -> str:
    values = load_env_file(env_file)
    return _get(values, "ARCHIVER_DB_PATH", "data/series-cloud-archiver.sqlite3")


def _parse_aliases(value: str) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for item in _split_csv(value):
        if "=" not in item:
            continue
        left, right = item.split("=", 1)
        left = left.strip().rstrip("/")
        right = right.strip().rstrip("/")
        if left and right:
            aliases[left] = right
    return aliases
