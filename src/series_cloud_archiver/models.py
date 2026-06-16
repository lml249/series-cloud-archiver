from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass
class EpisodeSignal:
    seasons: List[int] = field(default_factory=list)
    episodes: List[int] = field(default_factory=list)
    complete_markers: List[str] = field(default_factory=list)
    inferred_episode_count: int = 0


@dataclass
class FileSystemSeries:
    title: str
    path: str
    size_bytes: int
    video_count: int
    latest_mtime: float
    age_days: float
    signal: EpisodeSignal


@dataclass
class QBTorrentEvidence:
    name: str
    hash: str
    state: str
    save_path: str
    content_path: str
    progress: float
    seeding_time_seconds: int
    seed_days: float
    size_bytes: int


@dataclass
class EmbyEvidence:
    name: str
    item_id: str
    path: str
    episode_count: int
    matched: bool


@dataclass
class ScanCandidate:
    title: str
    path: str
    size_bytes: int
    video_count: int
    age_days: float
    score: int
    status: str
    reasons: List[str]
    blockers: List[str]
    complete_markers: List[str]
    seasons: List[int]
    episode_sample: List[int]
    qb: Optional[QBTorrentEvidence] = None
    emby: Optional[EmbyEvidence] = None

    def to_dict(self) -> Dict[str, object]:
        data = asdict(self)
        return data


@dataclass
class ScanReport:
    mode: str
    media_roots: List[str]
    min_seed_days: int
    total_series: int
    status_counts: Dict[str, int]
    candidates: List[ScanCandidate]
    warnings: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "mode": self.mode,
            "media_roots": self.media_roots,
            "min_seed_days": self.min_seed_days,
            "total_series": self.total_series,
            "status_counts": self.status_counts,
            "warnings": self.warnings,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }

