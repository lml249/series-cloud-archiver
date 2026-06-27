import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.hlink_cleanup import execute_cloud_hlink_cleanup, preview_cloud_hlink_cleanup
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


if __name__ == "__main__":
    unittest.main()
