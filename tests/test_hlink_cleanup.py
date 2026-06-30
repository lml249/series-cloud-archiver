import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.hlink_cleanup import (
    cleanup_empty_hlink_root,
    execute_cloud_hlink_orphan_multiseason_cleanup,
    execute_cloud_hlink_orphan_cleanup,
    execute_cloud_hlink_cleanup,
    execute_cloud_source_orphan_cleanup,
    preview_cloud_hlink_orphan_multiseason_cleanup,
    preview_cloud_hlink_orphan_cleanup,
    preview_cloud_hlink_cleanup,
    preview_cloud_source_orphan_cleanup,
)
from series_cloud_archiver.models import QBTorrentEvidence


def write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CloudHlinkCleanupTest(unittest.TestCase):
    def test_preview_requires_strm_and_qb_seed_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "qb" / "TV" / "Silent.Honor.S01"
            source_file = source / "Silent.Honor.S01E01.mkv"
            write(source_file)
            hlink_root = tmp_path / "hlink" / "TV" / "沉默的荣耀 (2025) {tmdbid=281538}"
            hlink_file = hlink_root / "Season 01" / "沉默的荣耀 S01E01.mkv"
            hlink_file.parent.mkdir(parents=True)
            os.link(source_file, hlink_file)
            strm_root = tmp_path / "strm" / "series" / "沉默的荣耀 (2025) {tmdbid=281538}" / "Season 01"
            write(strm_root / "沉默的荣耀 S01E01.strm", "/已整理/series/沉默的荣耀 (2025) {tmdbid=281538}/Season 01/E01.mkv")
            torrent = QBTorrentEvidence(
                name="沉默的荣耀.Silent.Honor.S01.2025.2160p.WEB-DL-HHWEB",
                hash="feedface00001234567890",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(source),
                progress=1.0,
                seeding_time_seconds=86400 * 8,
                seed_days=8.0,
                size_bytes=source_file.stat().st_size,
            )

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[torrent]):
                report = preview_cloud_hlink_cleanup(
                    "沉默的荣耀",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=281538,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                    required_target_prefix="/已整理/series/沉默的荣耀 (2025) {tmdbid=281538}",
                )

        self.assertTrue(report["ok"])
        self.assertTrue(report["ready_for_execute"])
        self.assertEqual(report["qbittorrent"]["hashes"], ["feedface00001234567890"])
        self.assertEqual(report["hlink"]["video_count"], 1)

    def test_preview_blocks_when_cloud_media_has_metadata_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "qb" / "TV" / "Show.S01"
            source_file = source / "Show.S01E01.mkv"
            write(source_file)
            hlink_root = tmp_path / "hlink" / "TV" / "Show"
            hlink_file = hlink_root / "Season 01" / "Show.S01E01.mkv"
            hlink_file.parent.mkdir(parents=True)
            os.link(source_file, hlink_file)
            strm_root = tmp_path / "strm" / "series" / "Show" / "Season 01"
            write(strm_root / "Show.S01E01.strm", "/已整理/series/Show/Season 1/Show.S01E01.mkv")
            torrent = QBTorrentEvidence(
                name="Show.S01",
                hash="feedface00001234567890",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(source),
                progress=1.0,
                seeding_time_seconds=86400 * 8,
                seed_days=8.0,
                size_bytes=source_file.stat().st_size,
            )
            cloud_report = {
                "ok": False,
                "blockers": ["cloud_media_metadata_sidecar_present"],
                "warnings": [],
                "scan": {"metadata_sidecar_file_count": 1},
            }

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[torrent]), patch(
                "series_cloud_archiver.hlink_cleanup.verify_mv3_cloud_media_sidecars", return_value=cloud_report
            ):
                report = preview_cloud_hlink_cleanup(
                    "Show",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                    required_target_prefix="/已整理/series/Show",
                    mv3_base_url="http://mv3.example",
                    mv3_token="token",
                    cloud_media_path="/已整理/series/Show",
                )

        self.assertFalse(report["ok"])
        self.assertFalse(report["ready_for_execute"])
        self.assertIn("cloud_media_metadata_sidecar_present", report["blockers"])
        self.assertEqual(report["cloud_media"]["scan"]["metadata_sidecar_file_count"], 1)

    def test_preview_blocks_when_qb_seed_time_is_too_short(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "hlink" / "TV" / "Show"
            write(hlink_root / "Show S01E01.mkv")
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            write(strm_root / "Show S01E01.strm")
            torrent = QBTorrentEvidence(
                name="Show.S01",
                hash="abc",
                state="stalledUP",
                save_path=str(tmp_path),
                content_path=str(hlink_root),
                progress=1.0,
                seeding_time_seconds=3600,
                seed_days=1 / 24,
                size_bytes=1,
            )

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[torrent]):
                report = preview_cloud_hlink_cleanup(
                    "Show",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                )

        self.assertFalse(report["ok"])
        self.assertIn("qb_seed_days_below_minimum", report["blockers"])

    def test_preview_blocks_when_qb_source_contains_unlinked_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "qb" / "TV" / "Show.S01"
            write(source / "Show.S01E01.mkv")
            write(source / "Show.S01E02.mkv")
            hlink_root = tmp_path / "hlink" / "TV" / "Show"
            hlink_file = hlink_root / "Season 01" / "Show S01E01.mkv"
            hlink_file.parent.mkdir(parents=True)
            os.link(source / "Show.S01E01.mkv", hlink_file)
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            write(strm_root / "Show S01E01.strm")
            torrent = QBTorrentEvidence(
                name="Show.S01",
                hash="feedface00001234567890",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(source),
                progress=1.0,
                seeding_time_seconds=86400 * 8,
                seed_days=8.0,
                size_bytes=2,
            )

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[torrent]):
                report = preview_cloud_hlink_cleanup(
                    "Show",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                )

        self.assertFalse(report["ok"])
        self.assertIn("source_root_check_failed", report["blockers"])
        self.assertEqual(report["filesystem"]["source_roots"][0]["linked_hlink_video_count"], 1)

    def test_preview_allows_duplicate_episode_formats_when_unique_episodes_are_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "qb" / "TV" / "Show.S01"
            e01 = source / "Show.S01E01.mkv"
            e02a = source / "Show.S01E02.1080p.mkv"
            e02b = source / "Show.S01E02.2160p.mkv"
            write(e01)
            write(e02a)
            write(e02b)
            hlink_root = tmp_path / "hlink" / "TV" / "Show" / "Season 01"
            hlink_root.mkdir(parents=True)
            os.link(e01, hlink_root / "Show.S01E01.mkv")
            os.link(e02a, hlink_root / "Show.S01E02.1080p.mkv")
            os.link(e02b, hlink_root / "Show.S01E02.2160p.mkv")
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            write(strm_root / "Show.S01E01.strm")
            write(strm_root / "Show.S01E02.strm")
            torrent = QBTorrentEvidence(
                name="Show.S01",
                hash="feedface00001234567890",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(source),
                progress=1.0,
                seeding_time_seconds=86400 * 8,
                seed_days=8.0,
                size_bytes=e01.stat().st_size + e02a.stat().st_size + e02b.stat().st_size,
            )

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[torrent]):
                report = preview_cloud_hlink_cleanup(
                    "Show",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=1,
                    expected_episode_count=2,
                    expected_episode_min=1,
                    expected_episode_max=2,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                )

        self.assertTrue(report["ok"])
        self.assertTrue(report["ready_for_execute"])
        self.assertNotIn("hlink_video_count_mismatch", report["blockers"])
        self.assertIn("hlink_duplicate_episode_files", report["warnings"])
        self.assertEqual(report["filesystem"]["hlink_episode_coverage"]["episodes"], [1, 2])
        self.assertEqual(report["filesystem"]["hlink_episode_coverage"]["duplicate_episode_pairs"], [{"season": 1, "episode": 2, "count": 2}])

    def test_preview_blocks_unknown_hlink_episode_even_when_file_count_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "qb" / "TV" / "Show.S01"
            source_file = source / "Show.Special.mkv"
            write(source_file)
            hlink_root = tmp_path / "hlink" / "TV" / "Show" / "Season 01"
            hlink_root.mkdir(parents=True)
            os.link(source_file, hlink_root / "Show.Special.mkv")
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            write(strm_root / "Show.S01E01.strm")
            torrent = QBTorrentEvidence(
                name="Show.S01",
                hash="feedface00001234567890",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(source),
                progress=1.0,
                seeding_time_seconds=86400 * 8,
                seed_days=8.0,
                size_bytes=source_file.stat().st_size,
            )

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[torrent]):
                report = preview_cloud_hlink_cleanup(
                    "Show",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                )

        self.assertFalse(report["ok"])
        self.assertIn("hlink_episode_signal_missing", report["blockers"])

    def test_preview_blocks_hlink_extra_episode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "qb" / "TV" / "Show.S01"
            e01 = source / "Show.S01E01.mkv"
            e02 = source / "Show.S01E02.mkv"
            write(e01)
            write(e02)
            hlink_root = tmp_path / "hlink" / "TV" / "Show" / "Season 01"
            hlink_root.mkdir(parents=True)
            os.link(e01, hlink_root / "Show.S01E01.mkv")
            os.link(e02, hlink_root / "Show.S01E02.mkv")
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            write(strm_root / "Show.S01E01.strm")
            torrent = QBTorrentEvidence(
                name="Show.S01",
                hash="feedface00001234567890",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(source),
                progress=1.0,
                seeding_time_seconds=86400 * 8,
                seed_days=8.0,
                size_bytes=e01.stat().st_size + e02.stat().st_size,
            )

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[torrent]):
                report = preview_cloud_hlink_cleanup(
                    "Show",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                )

        self.assertFalse(report["ok"])
        self.assertIn("hlink_unexpected_episodes_present", report["blockers"])

    def test_preview_does_not_inode_scan_unrelated_qb_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "hlink" / "TV" / "Show"
            write(hlink_root / "Show S01E01.mkv")
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            write(strm_root / "Show S01E01.strm")
            unrelated = tmp_path / "qb" / "TV" / "Other"
            unrelated.mkdir(parents=True)
            torrent = QBTorrentEvidence(
                name="Other.S01",
                hash="feedface00001234567890",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(unrelated),
                progress=1.0,
                seeding_time_seconds=86400 * 8,
                seed_days=8.0,
                size_bytes=1,
            )

            original_rglob = Path.rglob

            def guarded_rglob(path: Path, pattern: str):
                if path == unrelated:
                    raise AssertionError("unrelated torrent should not be scanned")
                return original_rglob(path, pattern)

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[torrent]), patch(
                "series_cloud_archiver.hlink_cleanup.Path.rglob", new=guarded_rglob
            ):
                report = preview_cloud_hlink_cleanup(
                    "Show",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                )

        self.assertFalse(report["ok"])
        self.assertIn("qb_match_required", report["blockers"])

    def test_preview_can_match_english_qb_release_by_size_and_inode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "qb" / "TV" / "Squid.Game.S01.2160p.Netflix.WEB-DL-HHWEB"
            source.mkdir(parents=True)
            hlink_root = tmp_path / "hlink" / "TV" / "鱿鱼游戏 (2021) {tmdbid=93405}" / "Season 01"
            hlink_root.mkdir(parents=True)
            total_size = 0
            for episode in range(1, 10):
                source_file = source / f"Squid.Game.S01E{episode:02d}.mkv"
                source_file.write_bytes(bytes([episode]) * (8 * 1024 * 1024))
                total_size += source_file.stat().st_size
                os.link(source_file, hlink_root / f"鱿鱼游戏 S01E{episode:02d}.mkv")
            strm_root = tmp_path / "strm" / "series" / "鱿鱼游戏 (2021) {tmdbid=93405}" / "Season 1"
            for episode in range(1, 10):
                write(
                    strm_root / f"鱿鱼游戏 S01E{episode:02d}.strm",
                    f"/已整理/series/鱿鱼游戏 (2021) {{tmdbid=93405}}/Season 1/E{episode:02d}.mkv",
                )
            english_release = QBTorrentEvidence(
                name="Squid.Game.S01.2160p.Netflix.WEB-DL.DDP.5.1.Atmos.HDR.H.265-HHWEB",
                hash="d22710358e62f176e5b5d77f0eb7550679349500",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(source),
                progress=1.0,
                seeding_time_seconds=86400 * 70,
                seed_days=70.0,
                size_bytes=total_size,
            )

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[english_release]):
                report = preview_cloud_hlink_cleanup(
                    "鱿鱼游戏",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=93405,
                    expected_episode_count=9,
                    expected_episode_min=1,
                    expected_episode_max=9,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                    required_target_prefix="/已整理/series/鱿鱼游戏 (2021) {tmdbid=93405}/Season 1",
                )

        self.assertTrue(report["ok"])
        self.assertTrue(report["ready_for_execute"])
        self.assertEqual(report["qbittorrent"]["hashes"], ["d22710358e62f176e5b5d77f0eb7550679349500"])
        self.assertEqual(report["filesystem"]["hlink_coverage"]["linked_hlink_inode_count"], 9)

    def test_preview_blocks_when_qb_matches_only_part_of_hlink_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "qb" / "TV" / "Show.E01"
            source_file = source / "Show.S01E01.mkv"
            write(source_file)
            hlink_root = tmp_path / "hlink" / "TV" / "Show"
            hlink_file = hlink_root / "Season 01" / "Show S01E01.mkv"
            hlink_file.parent.mkdir(parents=True)
            os.link(source_file, hlink_file)
            write(hlink_root / "Season 01" / "Show S01E02.mkv")
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            write(strm_root / "Show S01E01.strm")
            write(strm_root / "Show S01E02.strm")
            torrent = QBTorrentEvidence(
                name="Show.S01E01",
                hash="feedface00001234567890",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(source),
                progress=1.0,
                seeding_time_seconds=86400 * 8,
                seed_days=8.0,
                size_bytes=source_file.stat().st_size,
            )

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[torrent]):
                report = preview_cloud_hlink_cleanup(
                    "Show",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=1,
                    expected_episode_count=2,
                    expected_episode_min=1,
                    expected_episode_max=2,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                )

        self.assertFalse(report["ok"])
        self.assertIn("source_hlink_coverage_incomplete", report["blockers"])
        self.assertEqual(report["filesystem"]["hlink_coverage"]["missing_hlink_inode_count"], 1)

    def test_preview_prefers_inode_match_when_title_match_is_wrong_season(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            season1_source = tmp_path / "qb" / "TV" / "庆余年.Joy.of.Life.S01"
            season2_source = tmp_path / "qb" / "TV" / "Joy.of.Life.S02"
            write(season1_source / "Joy.of.Life.S01E01.mp4")
            season2_file = season2_source / "Joy.of.Life.S02E01.mkv"
            write(season2_file)
            hlink_root = tmp_path / "hlink" / "TV" / "庆余年 (2019)" / "Season 2"
            hlink_file = hlink_root / "庆余年 - S02E01.mkv"
            hlink_file.parent.mkdir(parents=True)
            os.link(season2_file, hlink_file)
            strm_root = tmp_path / "strm" / "series" / "庆余年 (2019) {tmdbid=95842}" / "Season 02"
            write(strm_root / "庆余年 S02E01.strm", "/已整理/series/庆余年1-2/庆余年 第二季 (2024) 杜比视界/庆余年 S02E01.mp4")
            wrong_title_match = QBTorrentEvidence(
                name="庆余年.Joy.of.Life.S01",
                hash="1111111111111111111111111111111111111111",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(season1_source),
                progress=1.0,
                seeding_time_seconds=86400 * 30,
                seed_days=30.0,
                size_bytes=1,
            )
            right_inode_match = QBTorrentEvidence(
                name="Joy.of.Life.S02",
                hash="2222222222222222222222222222222222222222",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(season2_source),
                progress=1.0,
                seeding_time_seconds=86400 * 30,
                seed_days=30.0,
                size_bytes=1,
            )

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[wrong_title_match, right_inode_match]):
                report = preview_cloud_hlink_cleanup(
                    "庆余年",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=95842,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                    required_target_prefix="/已整理/series/庆余年1-2/庆余年 第二季 (2024) 杜比视界",
                )

        self.assertTrue(report["ok"])
        self.assertEqual(report["qbittorrent"]["hashes"], ["2222222222222222222222222222222222222222"])
        self.assertEqual(report["filesystem"]["hlink_coverage"]["missing_hlink_inode_count"], 0)

    def test_preview_does_not_scan_parent_when_release_folder_contains_dots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "qb" / "TV" / "Evil.Hunter.S01.2026.2160p.WEB-DL"
            source_file = source / "Evil.Hunter.S01E01.mkv"
            write(source_file)
            unrelated = tmp_path / "qb" / "TV" / "Other.Show.S01.2026.2160p.WEB-DL"
            unrelated_file = unrelated / "Other.Show.S01E01.mkv"
            write(unrelated_file)
            hlink_root = tmp_path / "hlink" / "TV" / "除恶 (2026) {tmdbid=281495}"
            hlink_file = hlink_root / "Season 01" / "除恶 - S01E01.mkv"
            hlink_file.parent.mkdir(parents=True)
            os.link(source_file, hlink_file)
            strm_root = tmp_path / "strm" / "series" / "除恶 (2026) {tmdbid=281495}" / "Season 01"
            write(strm_root / "除恶 S01E01.strm", "/已整理/series/除恶 (2026) {tmdbid=281495}/Season 01/E01.mkv")
            right_match = QBTorrentEvidence(
                name="除恶.Evil.Hunter.S01.2026.2160p.WEB-DL",
                hash="1111111111111111111111111111111111111111",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(source),
                progress=1.0,
                seeding_time_seconds=86400 * 30,
                seed_days=30.0,
                size_bytes=source_file.stat().st_size,
            )
            unrelated_match = QBTorrentEvidence(
                name="Other.Show.S01.2026.2160p.WEB-DL",
                hash="2222222222222222222222222222222222222222",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(unrelated),
                progress=1.0,
                seeding_time_seconds=86400 * 30,
                seed_days=30.0,
                size_bytes=unrelated_file.stat().st_size,
            )

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[right_match, unrelated_match]):
                report = preview_cloud_hlink_cleanup(
                    "除恶 (2026) {tmdbid=281495}",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=281495,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                    required_target_prefix="/已整理/series",
                )

        self.assertTrue(report["ok"])
        self.assertEqual(report["qbittorrent"]["hashes"], ["1111111111111111111111111111111111111111"])

    def test_preview_still_supports_single_file_torrent_content_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_file = tmp_path / "qb" / "TV" / "Show.S01E01.mkv"
            write(source_file)
            hlink_root = tmp_path / "hlink" / "TV" / "Show"
            hlink_file = hlink_root / "Show S01E01.mkv"
            hlink_file.parent.mkdir(parents=True)
            os.link(source_file, hlink_file)
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            write(strm_root / "Show S01E01.strm")
            torrent = QBTorrentEvidence(
                name="Show.S01E01",
                hash="feedface00001234567890",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(source_file),
                progress=1.0,
                seeding_time_seconds=86400 * 8,
                seed_days=8.0,
                size_bytes=source_file.stat().st_size,
            )

            with patch("series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[torrent]):
                report = preview_cloud_hlink_cleanup(
                    "Show",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    min_seed_days=7,
                )

        self.assertTrue(report["ok"])
        self.assertEqual(report["qbittorrent"]["hashes"], ["feedface00001234567890"])

    def test_execute_deletes_approved_qb_hash_and_explicit_hlink_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "hlink" / "TV" / "Show"
            write(hlink_root / "Show S01E01.mkv")
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            write(strm_root / "Show S01E01.strm")
            preview = {
                "mode": "cloud-hlink-cleanup-preview",
                "title": "Show",
                "ready_for_execute": True,
                "blockers": [],
                "warnings": [],
                "expected": {"tmdbid": 1, "episode_count": 1, "episode_min": 1, "episode_max": 1},
                "hlink": {"path": str(hlink_root)},
                "strm": {"strm": {"roots": [{"path": str(strm_root)}]}},
                "qbittorrent": {"hashes": ["feedface00001234567890"]},
            }

            class FakeClient:
                calls = []

                def __init__(self, base_url, user="", qb_pass="", timeout=20):
                    pass

                def login(self):
                    pass

                def delete_torrents(self, hashes, delete_files=True):
                    self.calls.append((hashes, delete_files))
                    return {"http_status": 200, "ok": True, "response": ""}

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", FakeClient), patch(
                "series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[]
            ):
                report = execute_cloud_hlink_cleanup(preview, "http://qb.example")

        self.assertTrue(report["ok"])
        self.assertFalse(hlink_root.exists())
        self.assertEqual(FakeClient.calls, [(["feedface00001234567890"], True)])

    def test_cli_requires_approval_before_hlink_cleanup_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            preview_file = tmp_path / "preview.json"
            env_file.write_text("QB_BASE_URL=http://qb.example\n", encoding="utf-8")
            preview_file.write_text(
                json.dumps(
                    {
                        "mode": "cloud-hlink-cleanup-preview",
                        "title": "Show",
                        "expected": {"tmdbid": 1},
                        "hlink": {"path": "/example/hlink/Show"},
                        "qbittorrent": {"hashes": ["feedface00001234567890"]},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit):
                main(
                    [
                        "cloud-hlink-cleanup-execute",
                        "--env-file",
                        str(env_file),
                        "--preview-report",
                        str(preview_file),
                        "--expected-title",
                        "Show",
                        "--expected-tmdbid",
                        "1",
                        "--expected-hlink-root",
                        "/example/hlink/Show",
                        "--expected-qb-hash",
                        "feedface00001234567890",
                    ]
                )

    def test_empty_root_cleanup_deletes_root_with_only_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "庆余年 (2019)"
            write(hlink_root / "tvshow.nfo", "<tvshow />")
            write(hlink_root / "poster.jpg", "jpg")
            write(hlink_root / "Season 01" / "season01-poster.jpg", "jpg")

            report = cleanup_empty_hlink_root(
                "庆余年",
                str(hlink_root),
                expected_tmdbid=95842,
                approve_delete=True,
            )

        self.assertTrue(report["ok"])
        self.assertFalse(hlink_root.exists())
        self.assertEqual(report["hlink"]["video_count"], 0)
        self.assertEqual(report["hlink"]["non_video_count"], 3)
        self.assertEqual(report["delete"]["ok"], True)

    def test_empty_root_cleanup_blocks_when_videos_remain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "庆余年 (2019)"
            write(hlink_root / "Season 02" / "庆余年 - S02E01.mkv")
            write(hlink_root / "poster.jpg", "jpg")

            report = cleanup_empty_hlink_root(
                "庆余年",
                str(hlink_root),
                expected_tmdbid=95842,
                approve_delete=True,
            )

            self.assertFalse(report["ok"])
            self.assertTrue(hlink_root.exists())
            self.assertIn("hlink_root_contains_video_files", report["blockers"])
            self.assertEqual(report["hlink"]["video_count"], 1)

    def test_empty_root_cleanup_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "庆余年 (2019)"
            write(hlink_root / "tvshow.nfo", "<tvshow />")

            report = cleanup_empty_hlink_root(
                "庆余年",
                str(hlink_root),
                expected_tmdbid=95842,
                approve_delete=False,
            )

            self.assertFalse(report["ok"])
            self.assertTrue(hlink_root.exists())
            self.assertIn("approval_required", report["blockers"])
            self.assertEqual(report["delete"], {})

    def test_cli_empty_root_cleanup_returns_nonzero_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "庆余年 (2019)"
            report_file = tmp_path / "empty-root.json"
            write(hlink_root / "tvshow.nfo", "<tvshow />")

            status = main(
                [
                    "hlink-empty-root-cleanup",
                    "--title",
                    "庆余年",
                    "--expected-tmdbid",
                    "95842",
                    "--hlink-root",
                    str(hlink_root),
                    "--format",
                    "json",
                    "--output",
                    str(report_file),
                ]
            )
            report = json.loads(report_file.read_text(encoding="utf-8"))

            self.assertEqual(status, 1)
            self.assertTrue(hlink_root.exists())
            self.assertIn("approval_required", report["blockers"])

    def test_orphan_preview_allows_hlink_when_qb_has_no_linked_torrent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "人民的名义 (2017)"
            write(hlink_root / "Season 01" / "人民的名义 - S01E01.mp4")
            write(hlink_root / "poster.jpg", "jpg")
            strm_root = tmp_path / "volume4" / "mv3" / "strm" / "series" / "人民的名义 (2017) {tmdbid=71100}" / "Season 01"
            write(strm_root / "人民的名义.S01E01.strm", "https://mv3/redirect?path=/已整理/series/人民的名义/人民的名义.S01E01.mp4")

            class EmptyClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return []

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", EmptyClient):
                report = preview_cloud_hlink_orphan_cleanup(
                    "人民的名义",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=71100,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    required_target_prefix="/已整理/series",
                )

        self.assertTrue(report["ok"])
        self.assertTrue(report["ready_for_execute"])
        self.assertEqual(report["qbittorrent"]["linked_count"], 0)
        self.assertEqual(report["hlink"]["video_count"], 1)

    def test_orphan_preview_blocks_when_qb_still_links_hlink_inode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "qb" / "TV" / "Show"
            source_file = source / "Show.S01E01.mkv"
            write(source_file)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "Show"
            hlink_file = hlink_root / "Season 01" / "Show - S01E01.mkv"
            hlink_file.parent.mkdir(parents=True)
            os.link(source_file, hlink_file)
            strm_root = tmp_path / "strm" / "series" / "Show" / "Season 01"
            write(strm_root / "Show.S01E01.strm", "/已整理/series/Show/Show.S01E01.mkv")
            torrent = QBTorrentEvidence(
                name="Unrelated.Release.Name",
                hash="3333333333333333333333333333333333333333",
                state="stalledUP",
                save_path=str(tmp_path / "qb" / "TV"),
                content_path=str(source),
                progress=1.0,
                seeding_time_seconds=86400 * 30,
                seed_days=30.0,
                size_bytes=source_file.stat().st_size,
            )

            class FakeClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return [
                        {
                            "name": torrent.name,
                            "hash": torrent.hash,
                            "state": torrent.state,
                            "save_path": str(tmp_path / "qb" / "TV"),
                            "content_path": str(source),
                            "progress": torrent.progress,
                            "seeding_time": torrent.seeding_time_seconds,
                            "size": torrent.size_bytes,
                        }
                    ]

                def torrent_files(self, _torrent_hash):
                    return [{"name": "Show/Show.S01E01.mkv", "size": source_file.stat().st_size}]

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", FakeClient):
                report = preview_cloud_hlink_orphan_cleanup(
                    "Show",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    required_target_prefix="/已整理/series",
                )

        self.assertFalse(report["ok"])
        self.assertIn("qb_linked_torrent_present", report["blockers"])
        self.assertEqual(report["qbittorrent"]["hashes"], ["3333333333333333333333333333333333333333"])

    def test_orphan_preview_ignores_broad_qb_content_path_when_file_list_is_unlinked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            qb_root = tmp_path / "volume3" / "TV"
            other_file = qb_root / "Other.Show" / "Other.S01E01.mkv"
            write(other_file)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "Show"
            write(hlink_root / "Season 01" / "Show - S01E01.mkv")
            strm_root = tmp_path / "strm" / "series" / "Show" / "Season 01"
            write(strm_root / "Show.S01E01.strm", "/已整理/series/Show/Show.S01E01.mkv")

            class FakeClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return [
                        {
                            "name": "Other.Show.S01",
                            "hash": "4444444444444444444444444444444444444444",
                            "state": "stalledUP",
                            "save_path": str(qb_root),
                            "content_path": str(qb_root),
                            "progress": 1.0,
                            "seeding_time": 86400 * 30,
                            "size": other_file.stat().st_size,
                        }
                    ]

                def torrent_files(self, _torrent_hash):
                    return [{"name": "Other.Show/Other.S01E01.mkv", "size": other_file.stat().st_size}]

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", FakeClient):
                report = preview_cloud_hlink_orphan_cleanup(
                    "Show",
                    str(hlink_root),
                    str(strm_root),
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    required_target_prefix="/已整理/series",
                )

        self.assertTrue(report["ok"])
        self.assertEqual(report["qbittorrent"]["linked_count"], 0)

    def test_orphan_execute_rechecks_qb_and_deletes_explicit_hlink_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "人民的名义 (2017)"
            write(hlink_root / "Season 01" / "人民的名义 - S01E01.mp4")
            strm_root = tmp_path / "strm" / "series" / "人民的名义 (2017) {tmdbid=71100}" / "Season 01"
            write(strm_root / "人民的名义.S01E01.strm", "/已整理/series/人民的名义/人民的名义.S01E01.mp4")
            preview = {
                "mode": "cloud-hlink-orphan-cleanup-preview",
                "title": "人民的名义",
                "ready_for_execute": True,
                "blockers": [],
                "warnings": [],
                "expected": {
                    "tmdbid": 71100,
                    "episode_count": 1,
                    "episode_min": 1,
                    "episode_max": 1,
                    "required_target_prefix": "/已整理/series",
                    "forbidden_target_prefixes": [],
                },
                "hlink": {"path": str(hlink_root)},
                "strm": {"strm": {"roots": [{"path": str(strm_root)}]}},
                "qbittorrent": {"hashes": [], "linked_count": 0},
            }

            class EmptyClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return []

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", EmptyClient):
                report = execute_cloud_hlink_orphan_cleanup(preview, "http://qb.example")

        self.assertTrue(report["ok"])
        self.assertFalse(hlink_root.exists())
        self.assertTrue(report["current_precheck"]["ok"])
        self.assertTrue(report["verification"]["ok"])

    def test_multiseason_orphan_preview_allows_cloud_extra_episode_when_local_is_covered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "广告狂人 (2007)"
            write(hlink_root / "Season 01" / "广告狂人 - S01E01.mkv")
            write(hlink_root / "Season 01" / "广告狂人 - S01E02.mkv")
            write(hlink_root / "Season 02" / "广告狂人 - S02E01.mkv")
            write(hlink_root / "Season 02" / "广告狂人 - S02E03.mkv")
            strm_root = tmp_path / "volume4" / "mv3" / "strm" / "series" / "广告狂人 (2007) {tmdbid=1104}"
            write(strm_root / "Season 01" / "广告狂人.S01E01.strm", "/已整理/series/美剧【广告狂人】/Season 01/E01.mkv")
            write(strm_root / "Season 01" / "广告狂人.S01E02.strm", "/已整理/series/美剧【广告狂人】/Season 01/E02.mkv")
            write(strm_root / "Season 02" / "广告狂人.S02E01.strm", "/已整理/series/美剧【广告狂人】/Season 02/E01.mkv")
            write(strm_root / "Season 02" / "广告狂人.S02E02.strm", "/已整理/series/美剧【广告狂人】/Season 02/E02.mkv")
            write(strm_root / "Season 02" / "广告狂人.S02E03.strm", "/已整理/series/美剧【广告狂人】/Season 02/E03.mkv")

            class EmptyClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return []

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", EmptyClient):
                report = preview_cloud_hlink_orphan_multiseason_cleanup(
                    "广告狂人",
                    str(hlink_root),
                    [
                        {
                            "season": 1,
                            "strm_root": str(strm_root / "Season 01"),
                            "expected_episode_count": 2,
                            "expected_episode_min": 1,
                            "expected_episode_max": 2,
                        },
                        {
                            "season": 2,
                            "strm_root": str(strm_root / "Season 02"),
                            "expected_episodes": [1, 3],
                        },
                    ],
                    expected_tmdbid=1104,
                    qb_base_url="http://qb.example",
                    required_target_prefix="/已整理/series/美剧【广告狂人】",
                    cloud_media_path="",
                )

        self.assertTrue(report["ok"])
        self.assertTrue(report["ready_for_execute"])
        self.assertEqual(report["hlink"]["video_count"], 4)
        self.assertEqual(report["filesystem"]["hlink_strm_coverage"]["missing"], [])
        self.assertEqual(report["strm_seasons"][1]["episodes"], [1, 2, 3])

    def test_multiseason_orphan_preview_counts_double_episode_hlink_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "广告狂人 (2007)"
            write(hlink_root / "Season 05" / "广告狂人 - S05E01-E02 - 第 1-2 集.mkv")
            write(hlink_root / "Season 05" / "广告狂人 - S05E03 - 第 3 集.mkv")
            strm_root = tmp_path / "volume4" / "mv3" / "strm" / "series" / "广告狂人 (2007) {tmdbid=1104}" / "Season 05"
            write(strm_root / "广告狂人.S05E01.strm", "/已整理/series/美剧【广告狂人】/S05/E01.mkv")
            write(strm_root / "广告狂人.S05E02.strm", "/已整理/series/美剧【广告狂人】/S05/E02.mkv")
            write(strm_root / "广告狂人.S05E03.strm", "/已整理/series/美剧【广告狂人】/S05/E03.mkv")

            class EmptyClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return []

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", EmptyClient):
                report = preview_cloud_hlink_orphan_multiseason_cleanup(
                    "广告狂人",
                    str(hlink_root),
                    [{"season": 5, "strm_root": str(strm_root), "expected_episodes": [1, 2, 3]}],
                    expected_tmdbid=1104,
                    qb_base_url="http://qb.example",
                    required_target_prefix="/已整理/series/美剧【广告狂人】",
                )

        self.assertTrue(report["ok"])
        self.assertEqual(report["hlink_episodes"]["unmatched_count"], 0)
        self.assertEqual(report["hlink_episodes"]["seasons"][0]["episodes"], [1, 2, 3])
        self.assertEqual(report["filesystem"]["hlink_strm_coverage"]["missing"], [])

    def test_multiseason_orphan_preview_blocks_when_strm_lacks_local_episode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "广告狂人 (2007)"
            write(hlink_root / "Season 02" / "广告狂人 - S02E03.mkv")
            strm_root = tmp_path / "volume4" / "mv3" / "strm" / "series" / "广告狂人 (2007) {tmdbid=1104}" / "Season 02"
            write(strm_root / "广告狂人.S02E01.strm", "/已整理/series/美剧【广告狂人】/Season 02/E01.mkv")

            class EmptyClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return []

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", EmptyClient):
                report = preview_cloud_hlink_orphan_multiseason_cleanup(
                    "广告狂人",
                    str(hlink_root),
                    [{"season": 2, "strm_root": str(strm_root), "expected_episodes": [1, 3]}],
                    expected_tmdbid=1104,
                    qb_base_url="http://qb.example",
                    required_target_prefix="/已整理/series/美剧【广告狂人】",
                )

        self.assertFalse(report["ok"])
        self.assertIn("strm_expected_episodes_missing", report["blockers"])
        self.assertIn("strm_missing_hlink_episodes", report["blockers"])
        self.assertEqual(report["filesystem"]["hlink_strm_coverage"]["missing"], [{"season": 2, "episodes": [3]}])

    def test_multiseason_orphan_preview_blocks_when_qb_still_links_any_hlink_inode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "qb" / "TV" / "Mad.Men.S01"
            source_file = source / "Mad.Men.S01E01.mkv"
            write(source_file)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "广告狂人 (2007)"
            hlink_file = hlink_root / "Season 01" / "广告狂人 - S01E01.mkv"
            hlink_file.parent.mkdir(parents=True)
            os.link(source_file, hlink_file)
            strm_root = tmp_path / "strm" / "series" / "广告狂人" / "Season 01"
            write(strm_root / "广告狂人.S01E01.strm", "/已整理/series/美剧【广告狂人】/Season 01/E01.mkv")

            class FakeClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return [
                        {
                            "name": "Mad.Men.S01",
                            "hash": "6666666666666666666666666666666666666666",
                            "state": "stalledUP",
                            "save_path": str(tmp_path / "qb" / "TV"),
                            "content_path": str(source),
                            "progress": 1.0,
                            "seeding_time": 86400 * 30,
                            "size": source_file.stat().st_size,
                        }
                    ]

                def torrent_files(self, _torrent_hash):
                    return [{"name": "Mad.Men.S01/Mad.Men.S01E01.mkv", "size": source_file.stat().st_size}]

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", FakeClient):
                report = preview_cloud_hlink_orphan_multiseason_cleanup(
                    "广告狂人",
                    str(hlink_root),
                    [{"season": 1, "strm_root": str(strm_root), "expected_episode_count": 1, "expected_episode_min": 1, "expected_episode_max": 1}],
                    expected_tmdbid=1104,
                    qb_base_url="http://qb.example",
                    required_target_prefix="/已整理/series/美剧【广告狂人】",
                )

        self.assertFalse(report["ok"])
        self.assertIn("qb_linked_torrent_present", report["blockers"])
        self.assertEqual(report["qbittorrent"]["hashes"], ["6666666666666666666666666666666666666666"])

    def test_multiseason_orphan_execute_rechecks_and_deletes_explicit_hlink_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "广告狂人 (2007)"
            write(hlink_root / "Season 01" / "广告狂人 - S01E01.mkv")
            strm_root = tmp_path / "volume4" / "mv3" / "strm" / "series" / "广告狂人 (2007) {tmdbid=1104}" / "Season 01"
            write(strm_root / "广告狂人.S01E01.strm", "/已整理/series/美剧【广告狂人】/Season 01/E01.mkv")
            preview = {
                "mode": "cloud-hlink-orphan-multiseason-cleanup-preview",
                "title": "广告狂人",
                "ready_for_execute": True,
                "blockers": [],
                "warnings": [],
                "expected": {
                    "tmdbid": 1104,
                    "seasons": [
                        {
                            "season": 1,
                            "strm_root": str(strm_root),
                            "expected_episode_count": 1,
                            "expected_episode_min": 1,
                            "expected_episode_max": 1,
                            "expected_episodes": [],
                        }
                    ],
                    "required_target_prefix": "/已整理/series/美剧【广告狂人】",
                    "forbidden_target_prefixes": [],
                },
                "hlink": {"path": str(hlink_root)},
                "qbittorrent": {"hashes": [], "linked_count": 0},
            }

            class EmptyClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return []

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", EmptyClient):
                report = execute_cloud_hlink_orphan_multiseason_cleanup(preview, "http://qb.example")

        self.assertTrue(report["ok"])
        self.assertFalse(hlink_root.exists())
        self.assertTrue(report["current_precheck"]["ok"])
        self.assertTrue(report["verification"]["ok"])

    def test_cli_parses_multiseason_orphan_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            report_file = tmp_path / "preview.json"
            env_file.write_text("QB_BASE_URL=http://qb.example\n", encoding="utf-8")
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "广告狂人 (2007)"
            write(hlink_root / "Season 05" / "广告狂人 - S05E01.mkv")
            write(hlink_root / "Season 05" / "广告狂人 - S05E03.mkv")
            strm_root = tmp_path / "volume4" / "mv3" / "strm" / "series" / "广告狂人" / "Season 05"
            write(strm_root / "广告狂人.S05E01.strm", "/已整理/series/美剧【广告狂人】/Season 05/E01.mkv")
            write(strm_root / "广告狂人.S05E02.strm", "/已整理/series/美剧【广告狂人】/Season 05/E02.mkv")
            write(strm_root / "广告狂人.S05E03.strm", "/已整理/series/美剧【广告狂人】/Season 05/E03.mkv")

            class EmptyClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return []

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", EmptyClient):
                status = main(
                    [
                        "cloud-hlink-orphan-multiseason-cleanup-preview",
                        "--env-file",
                        str(env_file),
                        "--title",
                        "广告狂人",
                        "--expected-tmdbid",
                        "1104",
                        "--hlink-root",
                        str(hlink_root),
                        "--season",
                        f"5:{strm_root}:episodes=1,3",
                        "--required-target-prefix",
                        "/已整理/series/美剧【广告狂人】",
                        "--format",
                        "json",
                        "--output",
                        str(report_file),
                    ]
                )
            report = json.loads(report_file.read_text(encoding="utf-8"))

        self.assertEqual(status, 0)
        self.assertTrue(report["ok"])
        self.assertEqual(report["expected"]["seasons"][0]["expected_episodes"], [1, 3])

    def test_cli_requires_approval_before_orphan_hlink_cleanup_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            preview_file = tmp_path / "orphan-preview.json"
            env_file.write_text("QB_BASE_URL=http://qb.example\n", encoding="utf-8")
            preview_file.write_text(
                json.dumps(
                    {
                        "mode": "cloud-hlink-orphan-cleanup-preview",
                        "title": "Show",
                        "expected": {"tmdbid": 1},
                        "hlink": {"path": "/example/hlink/Show"},
                        "qbittorrent": {"hashes": [], "linked_count": 0},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit):
                main(
                    [
                        "cloud-hlink-orphan-cleanup-execute",
                        "--env-file",
                        str(env_file),
                        "--preview-report",
                        str(preview_file),
                        "--expected-title",
                        "Show",
                        "--expected-tmdbid",
                        "1",
                        "--expected-hlink-root",
                        "/example/hlink/Show",
                    ]
                )

    def test_source_orphan_preview_allows_untracked_source_with_complete_strm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_root = tmp_path / "volume3" / "TV" / "Breaking.Bad.S01"
            write(source_root / "Breaking.Bad.S01E01.mkv")
            write(source_root / "Breaking.Bad.S01E02.mkv")
            strm_root = tmp_path / "volume4" / "mv3" / "strm" / "series" / "绝命毒师 (2008) {tmdbid=1396}" / "Season 01"
            write(strm_root / "绝命毒师.S01E01.strm", "/已整理/series/绝命毒师 (2008) {tmdbid=1396}/Season 01/E01.mkv")
            write(strm_root / "绝命毒师.S01E02.strm", "/已整理/series/绝命毒师 (2008) {tmdbid=1396}/Season 01/E02.mkv")

            class EmptyClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return []

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", EmptyClient), patch(
                "series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[]
            ):
                report = preview_cloud_source_orphan_cleanup(
                    "绝命毒师",
                    str(source_root),
                    str(strm_root),
                    expected_tmdbid=1396,
                    expected_episode_count=2,
                    expected_episode_min=1,
                    expected_episode_max=2,
                    qb_base_url="http://qb.example",
                    required_target_prefix="/已整理/series/绝命毒师 (2008) {tmdbid=1396}/Season",
                )

        self.assertTrue(report["ok"])
        self.assertTrue(report["ready_for_execute"])
        self.assertEqual(report["source"]["video_count"], 2)
        self.assertEqual(report["qbittorrent"]["linked_count"], 0)

    def test_source_orphan_preview_blocks_when_qb_content_path_matches_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_root = tmp_path / "volume3" / "TV" / "Breaking.Bad.S01"
            source_file = source_root / "Breaking.Bad.S01E01.mkv"
            write(source_file)
            strm_root = tmp_path / "strm" / "series" / "绝命毒师" / "Season 01"
            write(strm_root / "绝命毒师.S01E01.strm", "/已整理/series/绝命毒师/Season 01/E01.mkv")
            torrent = QBTorrentEvidence(
                name="Breaking.Bad.S01",
                hash="5555555555555555555555555555555555555555",
                state="stalledUP",
                save_path=str(tmp_path / "volume3" / "TV"),
                content_path=str(source_root),
                progress=1.0,
                seeding_time_seconds=86400 * 30,
                seed_days=30.0,
                size_bytes=source_file.stat().st_size,
            )

            class FakeClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return [
                        {
                            "name": torrent.name,
                            "hash": torrent.hash,
                            "state": torrent.state,
                            "save_path": torrent.save_path,
                            "content_path": torrent.content_path,
                            "progress": torrent.progress,
                            "seeding_time": torrent.seeding_time_seconds,
                            "size": torrent.size_bytes,
                        }
                    ]

                def torrent_files(self, _torrent_hash):
                    return [{"name": "Breaking.Bad.S01/Breaking.Bad.S01E01.mkv", "size": source_file.stat().st_size}]

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", FakeClient), patch(
                "series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[torrent]
            ):
                report = preview_cloud_source_orphan_cleanup(
                    "绝命毒师",
                    str(source_root),
                    str(strm_root),
                    expected_tmdbid=1396,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    required_target_prefix="/已整理/series",
                )

        self.assertFalse(report["ok"])
        self.assertIn("qb_linked_torrent_present", report["blockers"])
        self.assertEqual(report["qbittorrent"]["hashes"], ["5555555555555555555555555555555555555555"])

    def test_source_orphan_execute_rechecks_and_deletes_explicit_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_root = tmp_path / "volume3" / "TV" / "Breaking.Bad.S01"
            write(source_root / "Breaking.Bad.S01E01.mkv")
            strm_root = tmp_path / "strm" / "series" / "绝命毒师" / "Season 01"
            write(strm_root / "绝命毒师.S01E01.strm", "/已整理/series/绝命毒师/Season 01/E01.mkv")
            preview = {
                "mode": "cloud-source-orphan-cleanup-preview",
                "title": "绝命毒师",
                "ready_for_execute": True,
                "blockers": [],
                "warnings": [],
                "expected": {
                    "tmdbid": 1396,
                    "episode_count": 1,
                    "episode_min": 1,
                    "episode_max": 1,
                    "required_target_prefix": "/已整理/series",
                    "forbidden_target_prefixes": [],
                },
                "source": {"path": str(source_root)},
                "strm": {"strm": {"roots": [{"path": str(strm_root)}]}},
                "qbittorrent": {"hashes": [], "linked_count": 0},
            }

            class EmptyClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=15):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return []

            with patch("series_cloud_archiver.hlink_cleanup.QBClient", EmptyClient), patch(
                "series_cloud_archiver.hlink_cleanup.fetch_qb_evidence", return_value=[]
            ):
                report = execute_cloud_source_orphan_cleanup(preview, "http://qb.example")

        self.assertTrue(report["ok"])
        self.assertFalse(source_root.exists())
        self.assertTrue(report["current_precheck"]["ok"])
        self.assertTrue(report["verification"]["ok"])

    def test_cli_requires_approval_before_source_orphan_cleanup_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            preview_file = tmp_path / "source-preview.json"
            env_file.write_text("QB_BASE_URL=http://qb.example\n", encoding="utf-8")
            preview_file.write_text(
                json.dumps(
                    {
                        "mode": "cloud-source-orphan-cleanup-preview",
                        "title": "Show",
                        "expected": {"tmdbid": 1},
                        "source": {"path": "/example/source/Show.S01"},
                        "qbittorrent": {"hashes": [], "linked_count": 0},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit):
                main(
                    [
                        "cloud-source-orphan-cleanup-execute",
                        "--env-file",
                        str(env_file),
                        "--preview-report",
                        str(preview_file),
                        "--expected-title",
                        "Show",
                        "--expected-tmdbid",
                        "1",
                        "--expected-source-root",
                        "/example/source/Show.S01",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
