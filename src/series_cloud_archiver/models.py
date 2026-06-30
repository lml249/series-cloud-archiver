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
class MPSubscriptionEvidence:
    name: str
    year: str
    media_type: str
    tmdbid: int
    season: int
    total_episode: int
    history_date: str
    current_subscription_found: bool
    matched: bool


@dataclass
class ManualCompletionEvidence:
    title: str
    path: str
    tmdbid: int = 0
    season: int = 0
    confirmed_at: str = ""
    note: str = ""
    matched: bool = False


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
    episode_numbers: List[int] = field(default_factory=list)
    qb: Optional[QBTorrentEvidence] = None
    emby: Optional[EmbyEvidence] = None
    mp: Optional[MPSubscriptionEvidence] = None
    manual_completion: Optional[ManualCompletionEvidence] = None

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


@dataclass
class CloudCheckItem:
    status: str
    title: str
    tmdbid: int
    season: int
    size_bytes: int
    candidate_count: int
    expected_count: int
    expected_episodes: List[int]
    cloud_episode_count: int
    cloud_episodes: List[int]
    missing_episodes: List[int]
    extra_cloud_episodes: List[int]
    reasons: List[str]
    blockers: List[str]
    titles: List[str]
    source_paths: List[str]
    source_qb_hashes: List[str]
    search_keywords: List[str]
    strm_paths_sample: List[str]
    strm_target_prefixes: List[str] = field(default_factory=list)
    strm_target_prefix: str = ""


@dataclass
class CloudCheckReport:
    mode: str
    strm_roots: List[str]
    total_candidate_groups: int
    status_counts: Dict[str, int]
    items: List[CloudCheckItem]
    warnings: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "mode": self.mode,
            "strm_roots": self.strm_roots,
            "total_candidate_groups": self.total_candidate_groups,
            "status_counts": self.status_counts,
            "warnings": self.warnings,
            "items": [asdict(item) for item in self.items],
        }
