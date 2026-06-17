import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.config import ScanConfig
from series_cloud_archiver.episode import episode_signal
from series_cloud_archiver.models import FileSystemSeries, EpisodeSignal, QBTorrentEvidence
from series_cloud_archiver.moviepilot import MPSubscriptionRecord, build_mp_subscription_evidence, match_mp_subscription
from series_cloud_archiver.qbittorrent import QBClient, match_torrent
from series_cloud_archiver.scanner import scan


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")


class EpisodeSignalTest(unittest.TestCase):
    def test_detects_complete_range(self) -> None:
        signal = episode_signal(["Example.Show.S01.E01-E12.1080p", "Example.Show.S01E01.mkv", "Example.Show.S01E12.mkv"])
        self.assertIn("episode-range", signal.complete_markers)
        self.assertEqual(signal.inferred_episode_count, 12)
        self.assertEqual(signal.episodes, [1, 12])

    def test_detects_chinese_complete_count(self) -> None:
        signal = episode_signal(["中国通史.2013.全100集.国语中字", "第001集.mkv"])
        self.assertIn("all-episodes", signal.complete_markers)
        self.assertEqual(signal.inferred_episode_count, 100)
        self.assertIn(1, signal.episodes)


class ReadonlyScanTest(unittest.TestCase):
    def test_finds_complete_candidate_without_qb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "TV"
            show = root / "Demo.Show.S01.Complete.1080p"
            for index in range(1, 13):
                touch(show / f"Demo.Show.S01E{index:02d}.mkv")

            report = scan(
                ScanConfig(
                    media_roots=[str(root)],
                    include_qb=False,
                    min_seed_days=0,
                    min_age_days=0,
                    max_depth=2,
                )
            )

            self.assertEqual(report.total_series, 1)
            self.assertEqual(report.candidates[0].status, "candidate_for_cloud_check")
            self.assertIn("filesystem_looks_complete", report.candidates[0].reasons)

    def test_blocks_incomplete_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "TV"
            show = root / "Demo.Show.S01.1080p"
            touch(show / "Demo.Show.S01E01.mkv")

            report = scan(
                ScanConfig(
                    media_roots=[str(root)],
                    include_qb=False,
                    min_seed_days=0,
                    min_age_days=0,
                    max_depth=2,
                )
            )

            self.assertEqual(report.total_series, 1)
            self.assertEqual(report.candidates[0].status, "needs_metadata_review")
            self.assertIn("needs_completion_evidence", report.candidates[0].blockers)

    def test_status_counts_are_before_top_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "TV"
            for name in ["A.Show.S01.Complete", "B.Show.S01.Complete"]:
                show = root / name
                for index in range(1, 3):
                    touch(show / f"{name}.S01E{index:02d}.mkv")

            report = scan(
                ScanConfig(
                    media_roots=[str(root)],
                    include_qb=False,
                    min_seed_days=0,
                    min_age_days=0,
                    max_depth=2,
                    top=1,
                )
            )

            self.assertEqual(len(report.candidates), 1)
            self.assertEqual(report.status_counts["candidate_for_cloud_check"], 2)

    def test_mp_subscription_history_can_prove_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "TV"
            show = root / "Demo.Show.S01.2026.1080p"
            for index in [1, 2, 4, 5, 7, 8, 10]:
                touch(show / f"Demo.Show.S01E{index:02d}.mkv")

            with patch(
                "series_cloud_archiver.scanner.fetch_mp_subscription_evidence",
                return_value=build_mp_subscription_evidence(
                    current=[],
                    history=[
                        MPSubscriptionRecord(
                            name="Demo Show",
                            year="2026",
                            media_type="电视剧",
                            tmdbid=123,
                            season=1,
                            total_episode=10,
                            date="2026-06-17 08:00:00",
                        )
                    ],
                ),
            ):
                report = scan(
                    ScanConfig(
                        media_roots=[str(root)],
                        include_qb=False,
                        min_seed_days=0,
                        min_age_days=0,
                        max_depth=2,
                        mp_base_url="http://moviepilot.example",
                        mp_token="example-token",
                    )
                )

            self.assertEqual(report.candidates[0].status, "candidate_for_cloud_check")
            self.assertIn("mp_subscription_history_completed", report.candidates[0].reasons)
            self.assertNotIn("needs_completion_evidence", report.candidates[0].blockers)


class QBittorrentClientTest(unittest.TestCase):
    def test_login_accepts_ok_with_period(self) -> None:
        client = QBClient("http://example.invalid", "user", "pass")

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"Ok."

        class Opener:
            def open(self, request, timeout):
                return Response()

        client.opener = Opener()
        client.login()

    def test_match_torrent_uses_path_alias(self) -> None:
        series = FileSystemSeries(
            title="Demo.Show.S01",
            path="/example/library-host/TV/Demo.Show.S01",
            size_bytes=10,
            video_count=2,
            latest_mtime=0,
            age_days=10,
            signal=EpisodeSignal(),
        )
        torrent = QBTorrentEvidence(
            name="Different Display Name",
            hash="abc",
            state="uploading",
            save_path="/example/qb-view/TV",
            content_path="/example/qb-view/TV/Demo.Show.S01",
            progress=1.0,
            seeding_time_seconds=86400 * 8,
            seed_days=8.0,
            size_bytes=10,
        )

        match = match_torrent(series, [torrent], {"/example/library-host": "/example/qb-view"})
        self.assertIs(match, torrent)


class MoviePilotEvidenceTest(unittest.TestCase):
    def test_history_without_current_subscription_counts_as_completed(self) -> None:
        evidence = build_mp_subscription_evidence(
            current=[],
            history=[
                MPSubscriptionRecord(
                    name="Demo Show",
                    year="2026",
                    media_type="电视剧",
                    tmdbid=123,
                    season=1,
                    total_episode=10,
                    date="2026-06-17 08:00:00",
                )
            ],
        )
        series = FileSystemSeries(
            title="Demo.Show.S01.2026.1080p",
            path="/example/library/Demo.Show.S01.2026.1080p",
            size_bytes=10,
            video_count=7,
            latest_mtime=0,
            age_days=10,
            signal=EpisodeSignal(seasons=[1], episodes=[1, 2, 4, 5, 7, 8, 10]),
        )

        match = match_mp_subscription(series, evidence)

        self.assertIsNotNone(match)
        self.assertTrue(match.matched)
        self.assertFalse(match.current_subscription_found)

    def test_current_subscription_blocks_history_completion_evidence(self) -> None:
        history = MPSubscriptionRecord(
            name="Demo Show",
            year="2026",
            media_type="电视剧",
            tmdbid=123,
            season=1,
            total_episode=10,
            date="2026-06-17 08:00:00",
        )

        evidence = build_mp_subscription_evidence(current=[history], history=[history])

        self.assertEqual(evidence, [])


if __name__ == "__main__":
    unittest.main()
