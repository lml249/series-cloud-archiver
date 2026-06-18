import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.config import ScanConfig
from series_cloud_archiver.cleanup_verify import build_mp_cleanup_verification, render_mp_cleanup_verification
from series_cloud_archiver.emby import refresh_and_verify_emby_library, render_emby_refresh_verify_report, verify_emby_library_paths
from series_cloud_archiver.episode import episode_signal
from series_cloud_archiver.models import FileSystemSeries, EpisodeSignal, QBTorrentEvidence
from series_cloud_archiver.moviepilot import (
    MPSubscriptionRecord,
    MPTransferHistoryRecord,
    build_mp_cleanup_preview,
    build_mp_subscription_evidence,
    execute_mp_cleanup_from_preview,
    match_mp_subscription,
    render_mp_cleanup_execute_report,
    render_mp_cleanup_preview,
)
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

    def test_manual_completion_file_can_prove_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "TV"
            show = root / "Demo.Show.S01.2026.1080p"
            touch(show / "Demo.Show.S01E01.mkv")
            manual_file = tmp_path / "manual-completions.json"
            manual_file.write_text(
                """
                {
                  "manual_completions": [
                    {
                      "title": "Demo Show",
                      "tmdbid": 123,
                      "season": 1,
                      "paths": ["%s"],
                      "confirmed_at": "2026-06-17"
                    }
                  ]
                }
                """
                % str(show),
                encoding="utf-8",
            )

            report = scan(
                ScanConfig(
                    media_roots=[str(root)],
                    include_qb=False,
                    min_seed_days=0,
                    min_age_days=0,
                    max_depth=2,
                    manual_completion_file=str(manual_file),
                )
            )

            self.assertEqual(report.candidates[0].status, "candidate_for_cloud_check")
            self.assertIn("manual_completion_confirmed", report.candidates[0].reasons)
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


class EmbyRefreshVerifyTest(unittest.TestCase):
    def test_verify_emby_library_paths_blocks_stale_local_records(self) -> None:
        class FakeEmbyClient:
            def items_by_search(self, search_term):
                return [
                    {
                        "Id": "series-local",
                        "Name": "楚汉传奇",
                        "Path": "/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}",
                    },
                    {
                        "Id": "episode-local",
                        "Name": "第1集",
                        "Type": "Episode",
                        "IndexNumber": 1,
                        "Path": "/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E01.mkv",
                    },
                    {
                        "Id": "episode-strm-1",
                        "Name": "第1集",
                        "Type": "Episode",
                        "IndexNumber": 1,
                        "Path": "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E01.strm",
                    },
                    {
                        "Id": "episode-strm-2",
                        "Name": "第2集",
                        "Type": "Episode",
                        "IndexNumber": 2,
                        "Path": "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E02.strm",
                    },
                ]

        report = verify_emby_library_paths(
            FakeEmbyClient(),
            title="楚汉传奇",
            stale_path_prefixes=["/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}"],
            strm_path_prefixes=["/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}"],
            expected_episode_count=2,
            expected_episode_min=1,
            expected_episode_max=2,
        )

        self.assertFalse(not report["blockers"])
        self.assertIn("emby_stale_path_records_present", report["blockers"])
        self.assertEqual(report["totals"]["stale_records"], 2)
        self.assertEqual(report["strm"]["episode_count"], 2)

    def test_refresh_and_verify_emby_library_uses_refresh_task_and_renders(self) -> None:
        class FakeClient:
            def __init__(self, base_url, api_key, timeout=20):
                self.base_url = base_url
                self.api_key = api_key
                self.timeout = timeout

            def refresh_library(self):
                return {"http_status": 204, "ok": True, "response": {}}

            def wait_for_task(self, key, poll_seconds=10.0, max_wait_seconds=900):
                return {
                    "key": key,
                    "timed_out": False,
                    "final_task": {
                        "Key": key,
                        "Name": "Scan media library",
                        "State": "Idle",
                        "LastExecutionResult": {"Status": "Completed"},
                    },
                    "polls": [{"state": "Running"}, {"state": "Idle"}],
                }

            def items_by_search(self, search_term):
                return [
                    {
                        "Id": "episode-strm-1",
                        "Type": "Episode",
                        "IndexNumber": 1,
                        "Path": "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E01.strm",
                    },
                    {
                        "Id": "episode-strm-2",
                        "Type": "Episode",
                        "IndexNumber": 2,
                        "Path": "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E02.strm",
                    },
                ]

        with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
            report = refresh_and_verify_emby_library(
                "http://emby.example",
                "token",
                title="楚汉传奇",
                stale_path_prefixes=["/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}"],
                strm_path_prefixes=["/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}"],
                expected_episode_count=2,
                expected_episode_min=1,
                expected_episode_max=2,
                poll_seconds=0,
                max_wait_seconds=1,
            )
        rendered = render_emby_refresh_verify_report(report, "markdown")

        self.assertTrue(report["ok"])
        self.assertEqual(report["refresh"]["task"]["last_status"], "Completed")
        self.assertEqual(report["verification"]["totals"]["stale_records"], 0)
        self.assertIn("Refresh last status: `Completed`", rendered)

    def test_emby_refresh_verify_cli_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "emby.json"
            env_file.write_text("EMBY_BASE_URL=http://emby.example\nEMBY_API_KEY=token\n", encoding="utf-8")

            class FakeClient:
                def __init__(self, base_url, api_key, timeout=20):
                    pass

                def refresh_library(self):
                    return {"http_status": 204, "ok": True, "response": {}}

                def wait_for_task(self, key, poll_seconds=10.0, max_wait_seconds=900):
                    return {
                        "key": key,
                        "timed_out": False,
                        "final_task": {"Key": key, "Name": "Scan media library", "State": "Idle", "LastExecutionResult": {"Status": "Completed"}},
                        "polls": [],
                    }

                def items_by_search(self, search_term):
                    return [
                        {
                            "Id": "episode-strm-1",
                            "Type": "Episode",
                            "IndexNumber": 1,
                            "Path": "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E01.strm",
                        }
                    ]

            with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
                code = main(
                    [
                        "emby-refresh-verify",
                        "--env-file",
                        str(env_file),
                        "--title",
                        "楚汉传奇",
                        "--stale-path-prefix",
                        "/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}",
                        "--strm-path-prefix",
                        "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}",
                        "--expected-episode-count",
                        "1",
                        "--expected-episode-min",
                        "1",
                        "--expected-episode-max",
                        "1",
                        "--poll-seconds",
                        "0",
                        "--max-wait-seconds",
                        "1",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["verification"]["totals"]["stale_records"], 0)


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

    def test_mp_cleanup_preview_groups_transfer_history_safely(self) -> None:
        records = [
            MPTransferHistoryRecord(
                id=1,
                title="楚汉传奇",
                year="2012",
                media_type="电视剧",
                seasons="S01",
                episodes="E01",
                src="/example/source/King.War/King.War.S01E01.mkv",
                dest="/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E01.mkv",
                mode="link",
                status=True,
                downloader="20099",
                download_hash="feedface00001234567890",
                tmdbid=41146,
            ),
            MPTransferHistoryRecord(
                id=2,
                title="楚汉传奇",
                year="2012",
                media_type="电视剧",
                seasons="S01",
                episodes="E02",
                src="/example/source/King.War/King.War.S01E02.mkv",
                dest="/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E02.mkv",
                mode="link",
                status=True,
                downloader="20099",
                download_hash="feedface00001234567890",
                tmdbid=41146,
            ),
        ]

        report = build_mp_cleanup_preview(
            "楚汉传奇",
            records,
            expected_title="楚汉传奇",
            expected_tmdbid=41146,
            expected_hash_prefix="feedface0000",
        )
        rendered = render_mp_cleanup_preview(report, "markdown")

        self.assertTrue(report["ok"])
        self.assertTrue(report["ready_for_manual_cleanup_approval"])
        self.assertEqual(report["summary"]["records_matched"], 2)
        self.assertEqual(report["summary"]["episode_count"], 2)
        self.assertEqual(report["summary"]["missing_in_range"], [])
        self.assertEqual(report["source_roots"], ["/example/source/King.War"])
        self.assertEqual(report["destination_roots"], ["/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}"])
        self.assertEqual(report["qb_targets"][0]["hash_prefix"], "feedface0000")
        self.assertIn("DELETE /api/v1/history/transfer?deletesrc=true&deletedest=true", rendered)

    def test_mp_cleanup_preview_blocks_when_expected_hash_is_absent(self) -> None:
        report = build_mp_cleanup_preview(
            "楚汉传奇",
            [
                MPTransferHistoryRecord(
                    id=1,
                    title="楚汉传奇",
                    episodes="E01",
                    download_hash="feedface1111",
                    status=True,
                    tmdbid=41146,
                )
            ],
            expected_title="楚汉传奇",
            expected_tmdbid=41146,
            expected_hash_prefix="feedface0000",
        )

        self.assertFalse(report["ok"])
        self.assertIn("no_matching_mp_transfer_history", report["blockers"])

    def test_mp_cleanup_execute_uses_validated_preview_ids(self) -> None:
        preview = build_mp_cleanup_preview(
            "楚汉传奇",
            [
                MPTransferHistoryRecord(
                    id=10,
                    title="楚汉传奇",
                    episodes="E01",
                    src="/example/source/King.War/King.War.S01E01.mkv",
                    dest="/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E01.mkv",
                    mode="link",
                    status=True,
                    downloader="20099",
                    download_hash="feedface00001234567890",
                    tmdbid=41146,
                ),
                MPTransferHistoryRecord(
                    id=11,
                    title="楚汉传奇",
                    episodes="E02",
                    src="/example/source/King.War/King.War.S01E02.mkv",
                    dest="/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E02.mkv",
                    mode="link",
                    status=True,
                    downloader="20099",
                    download_hash="feedface00001234567890",
                    tmdbid=41146,
                ),
            ],
            expected_title="楚汉传奇",
            expected_tmdbid=41146,
            expected_hash_prefix="feedface0000",
        )

        class FakeClient:
            def __init__(self):
                self.calls = []

            def delete_transfer_history(self, history_id, deletesrc=True, deletedest=True):
                self.calls.append((history_id, deletesrc, deletedest))
                return {"http_status": 200, "ok": True, "response": {"success": True}}

        client = FakeClient()
        report = execute_mp_cleanup_from_preview(
            client,
            preview,
            expected_title="楚汉传奇",
            expected_tmdbid=41146,
            expected_hash_prefix="feedface0000",
            expected_record_count=2,
            expected_episode_count=2,
            expected_episode_min=1,
            expected_episode_max=2,
        )
        rendered = render_mp_cleanup_execute_report(report, "markdown")

        self.assertTrue(report["ok"])
        self.assertEqual(client.calls, [(10, True, True), (11, True, True)])
        self.assertEqual(report["summary"]["success_count"], 2)
        self.assertIn("Attempted: `2`", rendered)

    def test_mp_cleanup_execute_blocks_before_delete_on_mismatch(self) -> None:
        preview = build_mp_cleanup_preview(
            "楚汉传奇",
            [
                MPTransferHistoryRecord(
                    id=10,
                    title="楚汉传奇",
                    episodes="E01",
                    mode="link",
                    status=True,
                    download_hash="feedface00001234567890",
                    tmdbid=41146,
                )
            ],
            expected_title="楚汉传奇",
            expected_tmdbid=41146,
            expected_hash_prefix="feedface0000",
        )

        class FakeClient:
            def delete_transfer_history(self, history_id, deletesrc=True, deletedest=True):
                raise AssertionError("delete should be blocked before API call")

        report = execute_mp_cleanup_from_preview(
            FakeClient(),
            preview,
            expected_title="楚汉传奇",
            expected_tmdbid=41146,
            expected_hash_prefix="feedface0000",
            expected_record_count=2,
            expected_episode_count=2,
            expected_episode_min=1,
            expected_episode_max=2,
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["summary"]["attempted_count"], 0)
        self.assertIn("record_count_mismatch", report["blockers"])

    def test_mp_cleanup_verify_passes_after_records_paths_and_qb_are_gone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strm_root = Path(tmp) / "strm" / "楚汉传奇 (2012) {tmdbid=41146}" / "Season 01"
            for index in range(1, 4):
                (strm_root / f"楚汉传奇 S01E{index:02d}.strm").parent.mkdir(parents=True, exist_ok=True)
                (strm_root / f"楚汉传奇 S01E{index:02d}.strm").write_text("http://example.invalid/stream", encoding="utf-8")

            report = build_mp_cleanup_verification(
                "楚汉传奇",
                mp_records=[],
                qb_torrents=[],
                expected_title="楚汉传奇",
                expected_tmdbid=41146,
                expected_hash_prefix="feedface0000",
                source_roots=[str(Path(tmp) / "missing-source")],
                destination_roots=[str(Path(tmp) / "missing-hlink")],
                strm_roots=[str(strm_root)],
                expected_episode_count=3,
                expected_episode_min=1,
                expected_episode_max=3,
            )
            rendered = render_mp_cleanup_verification(report, "markdown")

            self.assertTrue(report["ok"])
            self.assertEqual(report["mp_transfer_history"]["records_matched"], 0)
            self.assertEqual(report["qbittorrent"]["matched_count"], 0)
            self.assertEqual(report["strm"]["combined"]["missing_in_range"], [])
            self.assertIn("MP transfer records matched after cleanup: `0`", rendered)

    def test_mp_cleanup_verify_blocks_when_cleanup_left_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_root = Path(tmp) / "source"
            source_root.mkdir()
            strm_root = Path(tmp) / "strm"
            strm_root.mkdir()
            (strm_root / "Demo S01E01.strm").write_text("stream", encoding="utf-8")
            report = build_mp_cleanup_verification(
                "楚汉传奇",
                mp_records=[
                    MPTransferHistoryRecord(
                        id=10,
                        title="楚汉传奇",
                        episodes="E01",
                        status=True,
                        download_hash="feedface00001234567890",
                        tmdbid=41146,
                    )
                ],
                qb_torrents=[
                    {
                        "name": "楚汉传奇",
                        "hash": "feedface00001234567890",
                        "state": "missingFiles",
                    }
                ],
                expected_title="楚汉传奇",
                expected_tmdbid=41146,
                expected_hash_prefix="feedface0000",
                source_roots=[str(source_root)],
                destination_roots=[],
                strm_roots=[str(strm_root)],
                expected_episode_count=2,
                expected_episode_min=1,
                expected_episode_max=2,
            )

            self.assertFalse(report["ok"])
            self.assertIn("mp_transfer_history_still_present", report["blockers"])
            self.assertIn("qb_torrent_still_present", report["blockers"])
            self.assertIn("source_root_still_exists", report["blockers"])
            self.assertIn("strm_episode_count_mismatch", report["blockers"])

    def test_history_match_respects_explicit_season(self) -> None:
        evidence = build_mp_subscription_evidence(
            current=[],
            history=[
                MPSubscriptionRecord(
                    name="Demo Show",
                    year="2026",
                    media_type="电视剧",
                    tmdbid=123,
                    season=2,
                    total_episode=10,
                    date="2026-06-17 08:00:00",
                )
            ],
        )
        series = FileSystemSeries(
            title="Demo.Show.S03.2026.1080p",
            path="/example/library/Demo.Show.S03.2026.1080p",
            size_bytes=10,
            video_count=10,
            latest_mtime=0,
            age_days=10,
            signal=EpisodeSignal(),
        )

        self.assertIsNone(match_mp_subscription(series, evidence))


if __name__ == "__main__":
    unittest.main()
