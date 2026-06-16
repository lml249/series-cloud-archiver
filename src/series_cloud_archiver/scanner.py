from __future__ import annotations

from collections import Counter
from typing import List, Optional

from .config import ScanConfig
from .emby import fetch_emby_evidence, match_emby
from .filesystem import scan_series_roots
from .models import EmbyEvidence, FileSystemSeries, QBTorrentEvidence, ScanCandidate, ScanReport
from .qbittorrent import UP_STATES, fetch_qb_evidence, match_torrent


def _looks_complete(series: FileSystemSeries) -> bool:
    signal = series.signal
    if signal.complete_markers:
        return True
    if signal.inferred_episode_count and series.video_count >= signal.inferred_episode_count:
        return True
    if len(signal.episodes) >= 8 and max(signal.episodes) - min(signal.episodes) + 1 == len(signal.episodes):
        return True
    if series.video_count >= 20 and not signal.seasons:
        return True
    return False


def _score(series: FileSystemSeries, qb: Optional[QBTorrentEvidence], emby: Optional[EmbyEvidence], min_seed_days: int) -> int:
    score = 0
    if _looks_complete(series):
        score += 40
    if qb and qb.progress >= 0.999:
        score += 20
    if qb and qb.seed_days >= min_seed_days:
        score += 20
    if emby and emby.matched:
        score += 10
    if series.age_days >= min_seed_days:
        score += 10
    return score


def classify(
    series: FileSystemSeries,
    qb: Optional[QBTorrentEvidence],
    emby: Optional[EmbyEvidence],
    config: ScanConfig,
) -> ScanCandidate:
    reasons: List[str] = []
    blockers: List[str] = []

    if _looks_complete(series):
        reasons.append("filesystem_looks_complete")
    else:
        blockers.append("needs_completion_evidence")

    if series.age_days >= config.min_seed_days:
        reasons.append("filesystem_old_enough")
    else:
        blockers.append("recent_files")

    if config.include_qb and config.qb_base_url:
        if qb:
            reasons.append("qb_match_found")
            if qb.progress >= 0.999:
                reasons.append("qb_download_complete")
            else:
                blockers.append("qb_download_incomplete")
            if qb.seed_days >= config.min_seed_days:
                reasons.append("qb_seed_age_ok")
            else:
                blockers.append("qb_seed_age_short")
            if qb.state in UP_STATES:
                reasons.append("qb_seeding_state")
        else:
            blockers.append("needs_qb_match")
    else:
        reasons.append("qb_not_configured_readonly_scan")

    if config.include_emby and config.emby_base_url and config.emby_key:
        if emby and emby.matched:
            reasons.append("emby_match_found")
        else:
            blockers.append("needs_emby_match")

    if blockers:
        if "needs_completion_evidence" in blockers:
            status = "needs_metadata_review"
        elif any(blocker.startswith("qb_") or blocker == "needs_qb_match" for blocker in blockers):
            status = "blocked_qb_evidence"
        elif "recent_files" in blockers:
            status = "waiting_file_age"
        else:
            status = "needs_review"
    else:
        status = "candidate_for_cloud_check"

    return ScanCandidate(
        title=series.title,
        path=series.path,
        size_bytes=series.size_bytes,
        video_count=series.video_count,
        age_days=round(series.age_days, 2),
        score=_score(series, qb, emby, config.min_seed_days),
        status=status,
        reasons=reasons,
        blockers=blockers,
        complete_markers=series.signal.complete_markers,
        seasons=series.signal.seasons,
        episode_sample=series.signal.episodes[:10],
        qb=qb,
        emby=emby,
    )


def scan(config: ScanConfig) -> ScanReport:
    warnings: List[str] = []
    series_items = scan_series_roots(
        config.media_roots,
        max_depth=config.max_depth,
        min_age_days=config.min_age_days,
        exclude_names=config.exclude_names,
    )

    qb_items: List[QBTorrentEvidence] = []
    if config.include_qb and config.qb_base_url:
        try:
            qb_items = fetch_qb_evidence(config.qb_base_url, config.qb_user, config.qb_pass)
        except Exception as exc:  # noqa: BLE001 - surfaced as scan warning, never fatal
            warnings.append(f"qbittorrent_unavailable: {exc}")

    emby_items: List[EmbyEvidence] = []
    if config.include_emby and config.emby_base_url and config.emby_key:
        try:
            emby_items = fetch_emby_evidence(config.emby_base_url, config.emby_key)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"emby_unavailable: {exc}")

    candidates = [
        classify(
            series,
            match_torrent(series, qb_items) if qb_items else None,
            match_emby(series, emby_items) if emby_items else None,
            config,
        )
        for series in series_items
    ]
    candidates.sort(key=lambda item: (item.status != "candidate_for_cloud_check", -item.score, -item.size_bytes, item.title))
    counts = Counter(candidate.status for candidate in candidates)
    if config.top > 0:
        candidates = candidates[: config.top]
    return ScanReport(
        mode=config.mode,
        media_roots=config.media_roots,
        min_seed_days=config.min_seed_days,
        total_series=len(series_items),
        status_counts=dict(sorted(counts.items())),
        candidates=candidates,
        warnings=warnings,
    )
