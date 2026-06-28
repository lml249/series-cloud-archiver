import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.config import ScanConfig
from series_cloud_archiver.cleanup_verify import (
    audit_strm_nfo_language,
    build_mp_cleanup_verification,
    cleanup_duplicate_strm_root,
    render_duplicate_strm_cleanup,
    render_mp_cleanup_verification,
    render_strm_nfo_language_audit,
    render_strm_verification,
    verify_strm_paths,
)
from series_cloud_archiver.emby import (
    EmbyClient,
    cancel_emby_running_task,
    delete_stale_emby_paths,
    inspect_emby_task_status,
    notify_and_verify_emby_media_updated,
    refresh_and_verify_emby_item,
    refresh_and_verify_emby_library,
    render_emby_item_refresh_report,
    render_emby_media_updated_report,
    render_emby_refresh_verify_report,
    render_emby_task_cancel_report,
    render_emby_task_status_report,
    verify_emby_library_paths,
)
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
from series_cloud_archiver.qbittorrent import QBClient, audit_dotqb_files, match_torrent
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

    def test_dotqb_audit_classifies_temp_complete_missing_and_orphan_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            host_root = Path(tmp) / "host" / "volume3" / "TV"
            host_root.mkdir(parents=True)
            (host_root / "Incomplete" / "E01.mkv.!qB").parent.mkdir(parents=True)
            (host_root / "Incomplete" / "E01.mkv.!qB").write_bytes(b"incomplete")
            (host_root / "Complete" / "E02.mkv.!qB").parent.mkdir(parents=True)
            (host_root / "Complete" / "E02.mkv.!qB").write_bytes(b"complete")
            (host_root / "Missing" / "E03.mkv.!qB").parent.mkdir(parents=True)
            (host_root / "Missing" / "E03.mkv.!qB").write_bytes(b"missing")
            (host_root / "Orphan" / "E04.mkv.!qB").parent.mkdir(parents=True)
            (host_root / "Orphan" / "E04.mkv.!qB").write_bytes(b"orphan")

            class Response:
                status = 200

                def __init__(self, payload):
                    self.payload = payload

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return json.dumps(self.payload).encode("utf-8")

            class Opener:
                def open(self, request, timeout):
                    url = request.full_url
                    if url.endswith("/api/v2/auth/login"):
                        return Response("Ok.")
                    if url.endswith("/api/v2/torrents/info"):
                        return Response(
                            [
                                {"hash": "aaa111", "name": "Incomplete", "state": "pausedDL", "progress": 0.5, "save_path": "/example/qb-view/TV"},
                                {"hash": "bbb222", "name": "Complete", "state": "stalledUP", "progress": 1.0, "save_path": "/example/qb-view/TV"},
                                {"hash": "ccc333", "name": "Missing", "state": "missingFiles", "progress": 0.0, "save_path": "/example/qb-view/TV"},
                            ]
                        )
                    if url.endswith("/api/v2/app/preferences"):
                        return Response({"save_path": "/example/qb-view/TV", "temp_path_enabled": False, "incomplete_files_ext": True})
                    if "/api/v2/torrents/files?" in url:
                        if "aaa111" in url:
                            return Response([{"name": "Incomplete/E01.mkv", "size": 10, "progress": 0.5, "priority": 1}])
                        if "bbb222" in url:
                            return Response([{"name": "Complete/E02.mkv", "size": 10, "progress": 1.0, "priority": 1}])
                        if "ccc333" in url:
                            return Response([{"name": "Missing/E03.mkv", "size": 10, "progress": 0.0, "priority": 1}])
                    return Response({})

            with patch("series_cloud_archiver.qbittorrent.QBClient.login", lambda self: None):
                with patch("series_cloud_archiver.qbittorrent.QBClient.__init__", lambda self, base_url, user="", qb_pass="", timeout=15: setattr(self, "base_url", base_url.rstrip("/")) or setattr(self, "opener", Opener()) or setattr(self, "timeout", timeout)):
                    report = audit_dotqb_files(
                        "http://qb.example",
                        scan_roots=[str(host_root)],
                        path_aliases={"/example/qb-view/TV": str(host_root)},
                    )

            self.assertEqual(report["dot_qb_total_count"], 4)
            self.assertEqual(report["dot_qb_categories"]["incomplete_task_temp_file"], 1)
            self.assertEqual(report["dot_qb_categories"]["complete_task_with_dotqb"], 1)
            self.assertEqual(report["dot_qb_categories"]["qb_missing_with_dotqb"], 1)
            self.assertEqual(report["dot_qb_categories"]["orphan_not_in_qb"], 1)
            self.assertEqual(report["scan_roots"], [str(host_root)])

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

    def test_match_torrent_does_not_match_shared_save_parent(self) -> None:
        series = FileSystemSeries(
            title="Breaking.Bad.S01.2008.1080p.BluRay.x264.DTS-ADE",
            path="/example/library-view/TV/Breaking.Bad.S01.2008.1080p.BluRay.x264.DTS-ADE",
            size_bytes=10,
            video_count=7,
            latest_mtime=0,
            age_days=10,
            signal=EpisodeSignal(seasons=[1], episodes=[1, 2, 3, 4, 5, 6, 7]),
        )
        wrong_torrent = QBTorrentEvidence(
            name="Bloodhounds.S02.2023.2160p.NF.WEB-DL.DDP5.1.Atmos.HDR.H.265-HHWEB",
            hash="wrong",
            state="stalledUP",
            save_path="/example/qb-view/TV/",
            content_path="/example/qb-view/TV/Bloodhounds.S02.2023.2160p.NF.WEB-DL.DDP5.1.Atmos.HDR.H.265-HHWEB",
            progress=1.0,
            seeding_time_seconds=86400 * 8,
            seed_days=8.0,
            size_bytes=10,
        )
        right_torrent = QBTorrentEvidence(
            name="Breaking.Bad.S01.2008.1080p.BluRay.x264.DTS-ADE",
            hash="right",
            state="stalledUP",
            save_path="/example/qb-view/TV/",
            content_path="/example/qb-view/TV/Breaking.Bad.S01.2008.1080p.BluRay.x264.DTS-ADE",
            progress=1.0,
            seeding_time_seconds=86400 * 8,
            seed_days=8.0,
            size_bytes=10,
        )

        aliases = {"/example/library-view": "/example/qb-view"}

        self.assertIsNone(match_torrent(series, [wrong_torrent], aliases))
        self.assertIs(match_torrent(series, [wrong_torrent, right_torrent], aliases), right_torrent)

    def test_match_torrent_uses_normalized_hlink_title(self) -> None:
        series = FileSystemSeries(
            title="沉默的荣耀 (2025) {tmdbid=123456}",
            path="/example/library-host/hlink/TV/沉默的荣耀 (2025) {tmdbid=123456}",
            size_bytes=10,
            video_count=39,
            latest_mtime=0,
            age_days=10,
            signal=EpisodeSignal(seasons=[1], episodes=list(range(1, 40))),
        )
        torrent = QBTorrentEvidence(
            name="沉默的荣耀.Silent.Honor.S01.2025.2160p.WEB-DL.H265.AAC-ADWeb",
            hash="right",
            state="stalledUP",
            save_path="/example/qb-view/TV/",
            content_path="/example/qb-view/TV/沉默的荣耀.Silent.Honor.S01.2025.2160p.WEB-DL.H265.AAC-ADWeb",
            progress=1.0,
            seeding_time_seconds=86400 * 8,
            seed_days=8.0,
            size_bytes=10,
        )

        self.assertIs(match_torrent(series, [torrent], {"/example/library-host": "/example/qb-view"}), torrent)

    def test_match_torrent_title_tokens_stay_conservative(self) -> None:
        series = FileSystemSeries(
            title="沉默的荣耀 (2025) {tmdbid=123456}",
            path="/example/library-host/hlink/TV/沉默的荣耀 (2025) {tmdbid=123456}",
            size_bytes=10,
            video_count=39,
            latest_mtime=0,
            age_days=10,
            signal=EpisodeSignal(seasons=[1], episodes=list(range(1, 40))),
        )
        wrong_torrent = QBTorrentEvidence(
            name="荣耀乒乓.Ping.Pong.Life.S01.2021.1080p.WEB-DL.H264",
            hash="wrong",
            state="stalledUP",
            save_path="/example/qb-view/TV/",
            content_path="/example/qb-view/TV/荣耀乒乓.Ping.Pong.Life.S01.2021.1080p.WEB-DL.H264",
            progress=1.0,
            seeding_time_seconds=86400 * 8,
            seed_days=8.0,
            size_bytes=10,
        )

        self.assertIsNone(match_torrent(series, [wrong_torrent], {"/example/library-host": "/example/qb-view"}))

    def test_match_torrent_rejects_same_title_wrong_year_without_tv_signal(self) -> None:
        series = FileSystemSeries(
            title="海市蜃楼 (2025) {tmdbid=302726}",
            path="/example/library-host/hlink/TV/海市蜃楼 (2025) {tmdbid=302726}",
            size_bytes=10,
            video_count=24,
            latest_mtime=0,
            age_days=10,
            signal=EpisodeSignal(seasons=[1], episodes=list(range(1, 25))),
        )
        movie_torrent = QBTorrentEvidence(
            name="海市蜃楼.2018.1080p.国西双语.简繁中字",
            hash="wrong",
            state="stalledUP",
            save_path="/example/qb-view/TV/",
            content_path="/example/qb-view/TV/海市蜃楼.2018.1080p.国西双语.简繁中字",
            progress=1.0,
            seeding_time_seconds=86400 * 8,
            seed_days=8.0,
            size_bytes=10,
        )

        self.assertIsNone(match_torrent(series, [movie_torrent], {"/example/library-host": "/example/qb-view"}))


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

    def test_emby_refresh_verify_cli_can_trigger_without_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "emby.json"
            env_file.write_text("EMBY_BASE_URL=http://emby.example\nEMBY_API_KEY=token\n", encoding="utf-8")

            class FakeClient:
                waited = False

                def __init__(self, base_url, api_key, timeout=20):
                    pass

                def refresh_library(self):
                    return {"http_status": 204, "ok": True, "response": {}}

                def task_by_key(self, key):
                    return {"Key": key, "Name": "Scan media library", "State": "Running", "LastExecutionResult": {"Status": "Completed"}}

                def wait_for_task(self, key, poll_seconds=10.0, max_wait_seconds=900):
                    FakeClient.waited = True
                    return {"key": key, "timed_out": True, "final_task": {"Key": key}, "polls": []}

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
                        "--strm-path-prefix",
                        "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}",
                        "--expected-episode-count",
                        "1",
                        "--expected-episode-min",
                        "1",
                        "--expected-episode-max",
                        "1",
                        "--no-wait",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertFalse(FakeClient.waited)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["refresh"]["wait_skipped"])
            self.assertEqual(payload["refresh"]["task"]["state"], "Running")
            self.assertNotIn("emby_refresh_task_timeout", payload["blockers"])

    def test_emby_refresh_verify_cli_returns_nonzero_when_verification_fails(self) -> None:
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
                    return []

            with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
                code = main(
                    [
                        "emby-refresh-verify",
                        "--env-file",
                        str(env_file),
                        "--title",
                        "楚汉传奇",
                        "--strm-path-prefix",
                        "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}",
                        "--expected-episode-count",
                        "1",
                        "--expected-episode-min",
                        "1",
                        "--expected-episode-max",
                        "1",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 1)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertIn("emby_strm_records_missing", payload["blockers"])

    def test_notify_and_verify_emby_media_updated_posts_paths_without_full_scan(self) -> None:
        calls = []

        class FakeClient:
            def __init__(self, base_url, api_key, timeout=20):
                self.base_url = base_url
                self.api_key = api_key
                self.timeout = timeout

            def notify_media_updated(self, paths, update_type="Created"):
                calls.append({"paths": paths, "update_type": update_type})
                return {"http_status": 204, "ok": True, "response": {}}

            def refresh_library(self):
                raise AssertionError("media-updated notification must not request a full library scan")

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
            report = notify_and_verify_emby_media_updated(
                "http://emby.example",
                "token",
                title="楚汉传奇",
                updated_paths=["/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}"],
                stale_path_prefixes=["/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}"],
                strm_path_prefixes=["/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}"],
                expected_episode_count=2,
                expected_episode_min=1,
                expected_episode_max=2,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(calls, [{"paths": ["/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}"], "update_type": "Created"}])
        self.assertEqual(report["verification"]["strm"]["episodes"], [1, 2])
        self.assertIn("no full-library scan", render_emby_media_updated_report(report, "markdown"))

    def test_emby_media_updated_cli_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "emby-media-updated.json"
            env_file.write_text("EMBY_BASE_URL=http://emby.example\nEMBY_API_KEY=token\n", encoding="utf-8")

            class FakeClient:
                def __init__(self, base_url, api_key, timeout=20):
                    pass

                def notify_media_updated(self, paths, update_type="Created"):
                    return {"http_status": 204, "ok": True, "response": {"paths": paths, "update_type": update_type}}

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
                        "emby-media-updated",
                        "--env-file",
                        str(env_file),
                        "--title",
                        "楚汉传奇",
                        "--updated-path",
                        "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}",
                        "--strm-path-prefix",
                        "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}",
                        "--expected-episode-count",
                        "1",
                        "--expected-episode-min",
                        "1",
                        "--expected-episode-max",
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
            self.assertEqual(payload["notify"]["paths"], ["/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}"])

    def test_emby_media_updated_blocks_cloud_media_scrape_path(self) -> None:
        calls = []

        class FakeClient:
            def __init__(self, base_url, api_key, timeout=20):
                pass

            def notify_media_updated(self, paths, update_type="Created"):
                calls.append({"paths": paths, "update_type": update_type})
                raise AssertionError("cloud media paths must not be sent to Emby media-updated")

            def items_by_search(self, search_term):
                return []

        with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
            report = notify_and_verify_emby_media_updated(
                "http://emby.example",
                "token",
                title="甄嬛传",
                updated_paths=["/已整理/series/甄嬛传 (2011) {tmdbid=50878}"],
                stale_path_prefixes=[],
                strm_path_prefixes=["/example/strm/series/甄嬛传 (2011) {tmdbid=50878}"],
            )

        self.assertFalse(report["ok"])
        self.assertEqual(calls, [])
        self.assertIn("emby_updated_path_must_be_strm_side", report["blockers"])
        self.assertIn("cloud_media_paths_are_transfer_and_strm_only", report["warnings"])
        self.assertEqual(report["notify"]["request"]["blocked_paths"], ["/已整理/series/甄嬛传 (2011) {tmdbid=50878}"])

    def test_emby_refresh_verify_blocks_cloud_media_strm_prefix(self) -> None:
        calls = []

        class FakeClient:
            def __init__(self, base_url, api_key, timeout=20):
                pass

            def refresh_library(self):
                calls.append("refresh_library")
                raise AssertionError("cloud media paths must not be used as STRM verification prefixes")

            def task_by_key(self, key):
                calls.append("task_by_key")
                return {}

            def items_by_search(self, search_term):
                return []

        with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
            report = refresh_and_verify_emby_library(
                "http://emby.example",
                "token",
                title="甄嬛传",
                stale_path_prefixes=[],
                strm_path_prefixes=["/已整理/series/甄嬛传 (2011) {tmdbid=50878}"],
            )

        self.assertFalse(report["ok"])
        self.assertEqual(calls, [])
        self.assertIn("emby_strm_path_prefix_must_be_strm_side", report["blockers"])
        self.assertEqual(report["refresh"]["request"]["blocked_strm_path_prefixes"], ["/已整理/series/甄嬛传 (2011) {tmdbid=50878}"])

    def test_refresh_and_verify_emby_item_uses_item_refresh_without_full_scan(self) -> None:
        calls = []

        class FakeClient:
            def __init__(self, base_url, api_key, timeout=20):
                self.base_url = base_url
                self.api_key = api_key
                self.timeout = timeout

            def refresh_item(
                self,
                item_id,
                recursive=True,
                metadata_refresh_mode="Default",
                image_refresh_mode="Default",
                replace_all_metadata=False,
                replace_all_images=False,
            ):
                calls.append(
                    {
                        "item_id": item_id,
                        "recursive": recursive,
                        "metadata_refresh_mode": metadata_refresh_mode,
                        "image_refresh_mode": image_refresh_mode,
                        "replace_all_metadata": replace_all_metadata,
                        "replace_all_images": replace_all_images,
                    }
                )
                return {"http_status": 204, "ok": True, "response": {}}

            def refresh_library(self):
                raise AssertionError("item refresh must not request a full library scan")

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
            report = refresh_and_verify_emby_item(
                "http://emby.example",
                "token",
                title="楚汉传奇",
                item_id="7",
                stale_path_prefixes=["/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}"],
                strm_path_prefixes=["/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}"],
                metadata_refresh_mode="FullRefresh",
                image_refresh_mode="Default",
                replace_all_metadata=True,
                expected_episode_count=2,
                expected_episode_min=1,
                expected_episode_max=2,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(
            calls,
            [
                {
                    "item_id": "7",
                    "recursive": True,
                    "metadata_refresh_mode": "FullRefresh",
                    "image_refresh_mode": "Default",
                    "replace_all_metadata": True,
                    "replace_all_images": False,
                }
            ],
        )
        self.assertIn("Emby item refresh", render_emby_item_refresh_report(report, "markdown"))

    def test_emby_item_refresh_cli_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "emby-item-refresh.json"
            env_file.write_text("EMBY_BASE_URL=http://emby.example\nEMBY_API_KEY=token\n", encoding="utf-8")

            class FakeClient:
                def __init__(self, base_url, api_key, timeout=20):
                    pass

                def refresh_item(
                    self,
                    item_id,
                    recursive=True,
                    metadata_refresh_mode="Default",
                    image_refresh_mode="Default",
                    replace_all_metadata=False,
                    replace_all_images=False,
                ):
                    return {"http_status": 204, "ok": True, "response": {"item_id": item_id, "recursive": recursive}}

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
                        "emby-item-refresh-verify",
                        "--env-file",
                        str(env_file),
                        "--title",
                        "楚汉传奇",
                        "--item-id",
                        "7",
                        "--strm-path-prefix",
                        "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}",
                        "--expected-episode-count",
                        "1",
                        "--expected-episode-min",
                        "1",
                        "--expected-episode-max",
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
            self.assertEqual(payload["refresh"]["item_id"], "7")

    def test_emby_item_refresh_blocks_cloud_media_strm_prefix(self) -> None:
        calls = []

        class FakeClient:
            def __init__(self, base_url, api_key, timeout=20):
                pass

            def refresh_item(
                self,
                item_id,
                recursive=True,
                metadata_refresh_mode="Default",
                image_refresh_mode="Default",
                replace_all_metadata=False,
                replace_all_images=False,
            ):
                calls.append(item_id)
                raise AssertionError("cloud media paths must not be refreshed as the scraping target")

            def items_by_search(self, search_term):
                return []

        with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
            report = refresh_and_verify_emby_item(
                "http://emby.example",
                "token",
                title="甄嬛传",
                item_id="7",
                stale_path_prefixes=[],
                strm_path_prefixes=["/已整理/series/甄嬛传 (2011) {tmdbid=50878}"],
            )

        self.assertFalse(report["ok"])
        self.assertEqual(calls, [])
        self.assertIn("emby_strm_path_prefix_must_be_strm_side", report["blockers"])
        self.assertIn("cloud_media_paths_are_transfer_and_strm_only", report["warnings"])
        self.assertEqual(report["refresh"]["request"]["blocked_strm_path_prefixes"], ["/已整理/series/甄嬛传 (2011) {tmdbid=50878}"])

    def test_emby_client_uses_token_header_without_query_api_key(self) -> None:
        seen = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self):
                return b'{"Items":[]}'

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = request.headers
            seen["timeout"] = timeout
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            items = EmbyClient("http://emby.example", "secret-key", timeout=7).series_items()

        self.assertEqual(items, [])
        self.assertIn("IncludeItemTypes=Series", seen["url"])
        self.assertNotIn("secret-key", seen["url"])
        self.assertNotIn("api_key=", seen["url"])
        self.assertEqual(seen["headers"].get("X-emby-token"), "secret-key")
        self.assertEqual(seen["timeout"], 7)

    def test_emby_client_posts_media_updated_json_with_token_header(self) -> None:
        seen = {}

        class FakeResponse:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self):
                return b""

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = request.headers
            seen["body"] = request.data.decode("utf-8")
            seen["method"] = request.get_method()
            seen["timeout"] = timeout
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            result = EmbyClient("http://emby.example", "secret-key", timeout=7).notify_media_updated(
                ["/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}"],
                update_type="Created",
            )

        self.assertTrue(result["ok"])
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["url"], "http://emby.example/emby/Library/Media/Updated")
        self.assertNotIn("secret-key", seen["url"])
        self.assertEqual(seen["headers"].get("X-emby-token"), "secret-key")
        self.assertEqual(json.loads(seen["body"]), {"Updates": [{"Path": "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}", "UpdateType": "Created"}]})

    def test_emby_client_posts_item_refresh_json_with_token_header(self) -> None:
        seen = {}

        class FakeResponse:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self):
                return b""

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = request.headers
            seen["body"] = request.data.decode("utf-8")
            seen["method"] = request.get_method()
            seen["timeout"] = timeout
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            result = EmbyClient("http://emby.example", "secret-key", timeout=7).refresh_item(
                "library item",
                recursive=True,
                metadata_refresh_mode="FullRefresh",
                replace_all_metadata=True,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(seen["method"], "POST")
        self.assertIn("/emby/Items/library%20item/Refresh?", seen["url"])
        self.assertIn("Recursive=true", seen["url"])
        self.assertIn("MetadataRefreshMode=FullRefresh", seen["url"])
        self.assertNotIn("secret-key", seen["url"])
        self.assertEqual(seen["headers"].get("X-emby-token"), "secret-key")
        self.assertEqual(
            json.loads(seen["body"]),
            {
                "Recursive": True,
                "MetadataRefreshMode": "FullRefresh",
                "ImageRefreshMode": "Default",
                "ReplaceAllMetadata": True,
                "ReplaceAllImages": False,
            },
        )

    def test_emby_client_cancels_running_task_with_token_header(self) -> None:
        seen = {}

        class FakeResponse:
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self):
                return b""

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["headers"] = request.headers
            seen["method"] = request.get_method()
            seen["timeout"] = timeout
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            result = EmbyClient("http://emby.example", "secret-key", timeout=7).cancel_running_task("task id")

        self.assertTrue(result["ok"])
        self.assertEqual(seen["method"], "DELETE")
        self.assertEqual(seen["url"], "http://emby.example/emby/ScheduledTasks/Running/task%20id")
        self.assertNotIn("secret-key", seen["url"])
        self.assertEqual(seen["headers"].get("X-emby-token"), "secret-key")
        self.assertEqual(seen["timeout"], 7)

    def test_emby_task_status_reports_matching_task(self) -> None:
        class FakeClient:
            def __init__(self, base_url, api_key, timeout=20):
                self.base_url = base_url
                self.api_key = api_key
                self.timeout = timeout

            def scheduled_tasks(self):
                return [
                    {
                        "Id": "refresh-id",
                        "Key": "RefreshLibrary",
                        "Name": "Scan media library",
                        "State": "Running",
                        "CurrentProgressPercentage": 90,
                        "LastExecutionResult": {"Status": "Cancelled"},
                    }
                ]

        with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
            report = inspect_emby_task_status("http://emby.example", "token")

        self.assertTrue(report["ok"])
        self.assertEqual(report["tasks"][0]["id"], "refresh-id")
        self.assertEqual(report["tasks"][0]["state"], "Running")
        self.assertIn("readonly scheduled task status", render_emby_task_status_report(report, "markdown"))

    def test_emby_task_cancel_only_cancels_running_matching_task(self) -> None:
        calls = []

        class FakeClient:
            def __init__(self, base_url, api_key, timeout=20):
                pass

            def scheduled_tasks(self):
                if calls:
                    return [{"Id": "refresh-id", "Key": "RefreshLibrary", "Name": "Scan media library", "State": "Idle"}]
                return [{"Id": "refresh-id", "Key": "RefreshLibrary", "Name": "Scan media library", "State": "Running"}]

            def cancel_running_task(self, task_id):
                calls.append(task_id)
                return {"http_status": 204, "ok": True, "response": {}}

        with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
            report = cancel_emby_running_task("http://emby.example", "token", task_key="RefreshLibrary")

        self.assertTrue(report["ok"])
        self.assertEqual(calls, ["refresh-id"])
        self.assertEqual(report["selected_task"]["id"], "refresh-id")
        self.assertEqual(report["after"][0]["state"], "Idle")
        self.assertIn("approved scheduled task cancel", render_emby_task_cancel_report(report, "markdown"))

    def test_emby_task_cancel_blocks_idle_task(self) -> None:
        class FakeClient:
            def __init__(self, base_url, api_key, timeout=20):
                pass

            def scheduled_tasks(self):
                return [{"Id": "refresh-id", "Key": "RefreshLibrary", "Name": "Scan media library", "State": "Idle"}]

            def cancel_running_task(self, task_id):
                raise AssertionError("idle tasks must not be cancelled")

        with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
            report = cancel_emby_running_task("http://emby.example", "token", task_key="RefreshLibrary")

        self.assertFalse(report["ok"])
        self.assertIn("emby_running_task_not_found", report["blockers"])

    def test_emby_task_status_cli_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "emby-task-status.json"
            env_file.write_text("EMBY_BASE_URL=http://emby.example\nEMBY_API_KEY=token\n", encoding="utf-8")

            class FakeClient:
                def __init__(self, base_url, api_key, timeout=20):
                    pass

                def scheduled_tasks(self):
                    return [{"Id": "refresh-id", "Key": "RefreshLibrary", "Name": "Scan media library", "State": "Running"}]

            with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
                code = main(
                    [
                        "emby-task-status",
                        "--env-file",
                        str(env_file),
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["tasks"][0]["id"], "refresh-id")

    def test_emby_refresh_error_redacts_echoed_api_key(self) -> None:
        class FakeHTTPError(Exception):
            code = 500

            def read(self):
                return b"failed url=http://emby.example/emby/Library/Refresh?api_key=secret-key token=also-secret"

        def fake_urlopen(_request, timeout):
            raise FakeHTTPError()

        with patch("urllib.request.urlopen", fake_urlopen), patch("urllib.error.HTTPError", FakeHTTPError):
            result = EmbyClient("http://emby.example", "secret-key").refresh_library()

        rendered = json.dumps(result, ensure_ascii=False)
        self.assertFalse(result["ok"])
        self.assertIn("[REDACTED]", rendered)
        self.assertNotIn("secret-key", rendered)
        self.assertNotIn("also-secret", rendered)

    def test_verify_emby_library_paths_reads_sqlite_uri_with_special_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "emby?library#1.db"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE MediaItems (
                        Id TEXT,
                        type TEXT,
                        Name TEXT,
                        SeriesName TEXT,
                        Path TEXT,
                        IndexNumber INTEGER,
                        ParentIndexNumber INTEGER
                    )
                    """
                )
                connection.execute(
                    "INSERT INTO MediaItems VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        "episode-strm-1",
                        "Episode",
                        "第1集",
                        "楚汉传奇",
                        "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E01.strm",
                        1,
                        1,
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            class FakeClient:
                def items_by_search(self, _search_term):
                    raise AssertionError("sqlite path should be used before Emby API search")

            report = verify_emby_library_paths(
                FakeClient(),
                title="楚汉传奇",
                stale_path_prefixes=["/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}"],
                strm_path_prefixes=["/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}"],
                expected_episode_count=1,
                expected_episode_min=1,
                expected_episode_max=1,
                library_db_path=str(db_path),
            )

        self.assertEqual(report["method"], "sqlite_library_db")
        self.assertEqual(report["totals"]["strm_records"], 1)
        self.assertEqual(report["blockers"], [])

    def test_delete_stale_emby_paths_only_deletes_missing_stale_root_when_strm_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "library.db"
            stale_host = tmp_path / "missing" / "楚汉传奇 (2012) {tmdbid=41146}"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE MediaItems (
                        Id TEXT,
                        type TEXT,
                        Name TEXT,
                        SeriesName TEXT,
                        Path TEXT,
                        IndexNumber INTEGER,
                        ParentIndexNumber INTEGER
                    )
                    """
                )
                rows = [
                    ("local-series", "Series", "楚汉传奇", None, "/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}", None, None),
                    ("local-season", "Season", "Season 01", None, "/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}/Season 01", None, None),
                    ("local-episode", "Episode", "第1集", "楚汉传奇", "/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E01.mkv", 1, 1),
                    ("strm-series", "Series", "楚汉传奇", None, "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}", None, None),
                    ("strm-episode-1", "Episode", "第1集", "楚汉传奇", "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E01.strm", 1, 1),
                    ("strm-episode-2", "Episode", "第2集", "楚汉传奇", "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E02.strm", 2, 1),
                ]
                connection.executemany("INSERT INTO MediaItems VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
                connection.commit()
            finally:
                connection.close()

            calls = []

            class FakeClient:
                def __init__(self, base_url, api_key, timeout=20):
                    pass

                def items_by_search(self, _search_term):
                    raise AssertionError("sqlite path should be used")

                def delete_item(self, item_id):
                    calls.append(item_id)
                    return {"http_status": 204, "ok": True, "response": {}}

            with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
                report = delete_stale_emby_paths(
                    "http://emby.example",
                    "token",
                    title="楚汉传奇",
                    stale_path_prefixes=["/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}"],
                    stale_host_prefix=str(stale_host),
                    strm_path_prefixes=["/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}"],
                    expected_episode_count=2,
                    expected_episode_min=1,
                    expected_episode_max=2,
                    library_db_path=str(db_path),
                )

        self.assertTrue(report["ok"])
        self.assertEqual(calls, ["local-series"])
        self.assertEqual(report["stale_rows_count"], 3)
        self.assertEqual(report["delete_results"][0]["id"], "local-series")

    def test_delete_stale_emby_paths_can_delete_one_missing_stale_season(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "library.db"
            stale_host = tmp_path / "missing" / "唐朝诡事录 (2022) {tmdbid=211089}" / "Season 03"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE MediaItems (
                        Id TEXT,
                        type TEXT,
                        Name TEXT,
                        SeriesName TEXT,
                        Path TEXT,
                        IndexNumber INTEGER,
                        ParentIndexNumber INTEGER
                    )
                    """
                )
                rows = [
                    ("local-series", "Series", "唐朝诡事录", None, "/example/hlink/TV/唐朝诡事录 (2022) {tmdbid=211089}", None, None),
                    ("local-season-1", "Season", "Season 01", None, "/example/hlink/TV/唐朝诡事录 (2022) {tmdbid=211089}/Season 01", None, None),
                    ("local-season-3", 7, "Season 03", None, "/example/hlink/TV/唐朝诡事录 (2022) {tmdbid=211089}/Season 03", None, None),
                    ("local-episode-3-1", "Episode", "第1集", "唐朝诡事录", "/example/hlink/TV/唐朝诡事录 (2022) {tmdbid=211089}/Season 03/Tang S03E01.mkv", 1, 3),
                    ("strm-series", "Series", "唐朝诡事录", None, "/example/strm/series/唐朝诡事录 (2022) {tmdbid=211089}", None, None),
                    ("strm-season-3", "Season", "Season 03", None, "/example/strm/series/唐朝诡事录 (2022) {tmdbid=211089}/Season 03", None, None),
                    ("strm-episode-3-1", "Episode", "第1集", "唐朝诡事录", "/example/strm/series/唐朝诡事录 (2022) {tmdbid=211089}/Season 03/Tang S03E01.strm", 1, 3),
                    ("strm-episode-3-2", "Episode", "第2集", "唐朝诡事录", "/example/strm/series/唐朝诡事录 (2022) {tmdbid=211089}/Season 03/Tang S03E02.strm", 2, 3),
                ]
                connection.executemany("INSERT INTO MediaItems VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
                connection.commit()
            finally:
                connection.close()

            calls = []

            class FakeClient:
                def __init__(self, base_url, api_key, timeout=20):
                    pass

                def items_by_search(self, _search_term):
                    raise AssertionError("sqlite path should be used")

                def delete_item(self, item_id):
                    calls.append(item_id)
                    return {"http_status": 204, "ok": True, "response": {}}

            with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
                report = delete_stale_emby_paths(
                    "http://emby.example",
                    "token",
                    title="唐朝诡事录",
                    stale_path_prefixes=["/example/hlink/TV/唐朝诡事录 (2022) {tmdbid=211089}/Season 03"],
                    stale_host_prefix=str(stale_host),
                    delete_scope="season",
                    strm_path_prefixes=["/example/strm/series/唐朝诡事录 (2022) {tmdbid=211089}/Season 03"],
                    expected_episode_count=2,
                    expected_episode_min=1,
                    expected_episode_max=2,
                    library_db_path=str(db_path),
                )

        self.assertTrue(report["ok"])
        self.assertEqual(report["delete_scope"], "season")
        self.assertEqual(calls, ["local-season-3"])
        self.assertEqual(report["stale_rows_count"], 2)
        self.assertEqual(report["root_items"][0]["id"], "local-season-3")

    def test_delete_stale_emby_paths_blocks_when_host_path_still_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "library.db"
            stale_host = tmp_path / "楚汉传奇 (2012) {tmdbid=41146}"
            stale_host.mkdir()
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE MediaItems (
                        Id TEXT,
                        type TEXT,
                        Name TEXT,
                        SeriesName TEXT,
                        Path TEXT,
                        IndexNumber INTEGER,
                        ParentIndexNumber INTEGER
                    )
                    """
                )
                rows = [
                    ("local-series", "Series", "楚汉传奇", None, "/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}", None, None),
                    ("strm-episode-1", "Episode", "第1集", "楚汉传奇", "/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}/Season 01/楚汉传奇 S01E01.strm", 1, 1),
                ]
                connection.executemany("INSERT INTO MediaItems VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
                connection.commit()
            finally:
                connection.close()

            class FakeClient:
                def __init__(self, base_url, api_key, timeout=20):
                    pass

                def items_by_search(self, _search_term):
                    raise AssertionError("sqlite path should be used")

                def delete_item(self, _item_id):
                    raise AssertionError("delete should be blocked")

            with patch("series_cloud_archiver.emby.EmbyClient", FakeClient):
                report = delete_stale_emby_paths(
                    "http://emby.example",
                    "token",
                    title="楚汉传奇",
                    stale_path_prefixes=["/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}"],
                    stale_host_prefix=str(stale_host),
                    strm_path_prefixes=["/example/strm/series/楚汉传奇 (2012) {tmdbid=41146}"],
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    library_db_path=str(db_path),
                )

        self.assertFalse(report["ok"])
        self.assertIn("stale_host_path_still_exists", report["blockers"])
        self.assertEqual(report["delete_results"], [])


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
        self.assertEqual(report["source_check_paths"], ["/example/source/King.War/King.War.S01E01.mkv", "/example/source/King.War/King.War.S01E02.mkv"])
        self.assertEqual(report["destination_roots"], ["/example/hlink/TV/楚汉传奇 (2012) {tmdbid=41146}"])
        self.assertEqual(report["qb_targets"][0]["hash_prefix"], "feedface0000")
        self.assertIn("DELETE /api/v1/history/transfer?deletesrc=true&deletedest=true", rendered)

    def test_mp_cleanup_preview_can_filter_one_season(self) -> None:
        records = [
            MPTransferHistoryRecord(
                id=1,
                title="唐朝诡事录",
                media_type="电视剧",
                seasons="S01",
                episodes="E01",
                src="/example/source/Tang.S01/Tang.S01E01.mkv",
                dest="/example/hlink/TV/唐朝诡事录 (2022) {tmdbid=211089}/Season 01/Tang S01E01.mkv",
                mode="link",
                status=True,
                downloader="20099",
                download_hash="aaaabbbbcccc1111",
                tmdbid=211089,
            ),
            MPTransferHistoryRecord(
                id=31,
                title="唐朝诡事录",
                media_type="电视剧",
                seasons="S03",
                episodes="E01",
                src="/example/source/Tang.S03/Tang.S03E01.mkv",
                dest="/example/hlink/TV/唐朝诡事录 (2022) {tmdbid=211089}/Season 03/Tang S03E01.mkv",
                mode="link",
                status=True,
                downloader="20099",
                download_hash="feedface00001111",
                tmdbid=211089,
            ),
            MPTransferHistoryRecord(
                id=32,
                title="唐朝诡事录",
                media_type="电视剧",
                seasons="S03",
                episodes="E02",
                src="/example/source/Tang.S03/Tang.S03E02.mkv",
                dest="/example/hlink/TV/唐朝诡事录 (2022) {tmdbid=211089}/Season 03/Tang S03E02.mkv",
                mode="link",
                status=True,
                downloader="20099",
                download_hash="feedface00001111",
                tmdbid=211089,
            ),
        ]

        report = build_mp_cleanup_preview(
            "唐朝诡事录",
            records,
            expected_title="唐朝诡事录",
            expected_tmdbid=211089,
            expected_season=3,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["expected_season"], 3)
        self.assertEqual(report["mp_delete_plan"]["record_ids"], [31, 32])
        self.assertEqual(report["summary"]["records_found"], 3)
        self.assertEqual(report["summary"]["records_matched"], 2)
        self.assertEqual(report["destination_roots"], ["/example/hlink/TV/唐朝诡事录 (2022) {tmdbid=211089}/Season 03"])
        self.assertEqual([item["season_numbers"] for item in report["records"]], [[3], [3]])

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

    def test_mp_cleanup_execute_can_approve_explicit_non_contiguous_episodes(self) -> None:
        preview = build_mp_cleanup_preview(
            "雨霖铃",
            [
                MPTransferHistoryRecord(
                    id=21,
                    title="雨霖铃",
                    episodes="E01",
                    mode="link",
                    status=True,
                    download_hash="feedface00001234567890",
                    tmdbid=254486,
                ),
                MPTransferHistoryRecord(
                    id=22,
                    title="雨霖铃",
                    episodes="E03",
                    mode="link",
                    status=True,
                    download_hash="feedface00001234567890",
                    tmdbid=254486,
                ),
                MPTransferHistoryRecord(
                    id=23,
                    title="雨霖铃",
                    episodes="E21",
                    mode="link",
                    status=True,
                    download_hash="feedface00001234567890",
                    tmdbid=254486,
                ),
            ],
            expected_title="雨霖铃",
            expected_tmdbid=254486,
            expected_hash_prefix="feedface0000",
        )

        class FakeClient:
            def __init__(self):
                self.calls = []

            def delete_transfer_history(self, history_id, deletesrc=True, deletedest=True):
                self.calls.append((history_id, deletesrc, deletedest))
                return {"http_status": 200, "ok": True, "response": {"success": True}}

        blocked = execute_mp_cleanup_from_preview(
            FakeClient(),
            preview,
            expected_title="雨霖铃",
            expected_tmdbid=254486,
            expected_hash_prefix="feedface0000",
            expected_record_count=3,
            expected_episode_count=3,
            expected_episode_min=1,
            expected_episode_max=21,
        )
        self.assertFalse(blocked["ok"])
        self.assertIn("preview_episode_gap_detected", blocked["blockers"])

        client = FakeClient()
        report = execute_mp_cleanup_from_preview(
            client,
            preview,
            expected_title="雨霖铃",
            expected_tmdbid=254486,
            expected_hash_prefix="feedface0000",
            expected_record_count=3,
            expected_episode_count=3,
            expected_episode_min=1,
            expected_episode_max=21,
            expected_episodes=[1, 3, 21],
        )

        self.assertTrue(report["ok"])
        self.assertEqual(client.calls, [(21, True, True), (22, True, True), (23, True, True)])
        self.assertEqual(report["expected"]["episodes"], [1, 3, 21])

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

    def test_mp_cleanup_execute_can_allow_multiple_hashes_and_source_roots(self) -> None:
        preview = build_mp_cleanup_preview(
            "八千里路云和月",
            [
                MPTransferHistoryRecord(
                    id=10,
                    title="八千里路云和月",
                    episodes="E01",
                    src="/example/qb-view/TV/source-a/E01.mkv",
                    dest="/example/library-host/hlink/TV/八千里路云和月 (2026) {tmdbid=289624}/Season 01/E01.mkv",
                    mode="link",
                    status=True,
                    download_hash="aaaabbbbcccc1111",
                    tmdbid=289624,
                ),
                MPTransferHistoryRecord(
                    id=11,
                    title="八千里路云和月",
                    episodes="E02",
                    src="/example/qb-view/TV/source-b/E02.mkv",
                    dest="/example/library-host/hlink/TV/八千里路云和月 (2026) {tmdbid=289624}/Season 01/E02.mkv",
                    mode="link",
                    status=True,
                    download_hash="ddddffffeeee2222",
                    tmdbid=289624,
                ),
            ],
            expected_title="八千里路云和月",
            expected_tmdbid=289624,
        )

        class FakeClient:
            def __init__(self):
                self.calls = []

            def delete_transfer_history(self, history_id, deletesrc=True, deletedest=True):
                self.calls.append((history_id, deletesrc, deletedest))
                return {"http_status": 200, "ok": True, "response": {"success": True}}

        blocked = execute_mp_cleanup_from_preview(
            FakeClient(),
            preview,
            expected_title="八千里路云和月",
            expected_tmdbid=289624,
            expected_hash_prefix="",
            expected_record_count=2,
            expected_episode_count=2,
            expected_episode_min=1,
            expected_episode_max=2,
        )
        self.assertFalse(blocked["ok"])
        self.assertIn("preview_has_warnings", blocked["blockers"])

        client = FakeClient()
        report = execute_mp_cleanup_from_preview(
            client,
            preview,
            expected_title="八千里路云和月",
            expected_tmdbid=289624,
            expected_hash_prefix="",
            expected_record_count=2,
            expected_episode_count=2,
            expected_episode_min=1,
            expected_episode_max=2,
            allow_multiple_hashes=True,
            allow_multiple_source_roots=True,
        )

        self.assertTrue(report["ok"])
        self.assertEqual(client.calls, [(10, True, True), (11, True, True)])
        self.assertTrue(report["expected"]["allow_multiple_hashes"])
        self.assertTrue(report["expected"]["allow_multiple_source_roots"])
        self.assertEqual(report["expected"]["hash_prefixes"], [])

        missing_hash = execute_mp_cleanup_from_preview(
            FakeClient(),
            preview,
            expected_title="八千里路云和月",
            expected_tmdbid=289624,
            expected_hash_prefix="",
            expected_hash_prefixes=["aaaabbbbcccc", "feedface0000"],
            expected_record_count=2,
            expected_episode_count=2,
            expected_episode_min=1,
            expected_episode_max=2,
            allow_multiple_hashes=True,
            allow_multiple_source_roots=True,
        )
        self.assertFalse(missing_hash["ok"])
        self.assertIn("expected_hash_prefix_not_found", missing_hash["blockers"])

        exact_hashes = execute_mp_cleanup_from_preview(
            client,
            preview,
            expected_title="八千里路云和月",
            expected_tmdbid=289624,
            expected_hash_prefix="",
            expected_hash_prefixes=["aaaabbbbcccc", "ddddffffeeee"],
            expected_record_count=2,
            expected_episode_count=2,
            expected_episode_min=1,
            expected_episode_max=2,
            allow_multiple_hashes=True,
            allow_multiple_source_roots=True,
        )
        self.assertTrue(exact_hashes["ok"])
        self.assertEqual(exact_hashes["expected"]["hash_prefixes"], ["aaaabbbbcccc", "ddddffffeeee"])

    def test_mp_cleanup_execute_blocks_multiple_destination_roots_even_with_allowances(self) -> None:
        preview = build_mp_cleanup_preview(
            "八千里路云和月",
            [
                MPTransferHistoryRecord(
                    id=10,
                    title="八千里路云和月",
                    episodes="E01",
                    src="/example/qb-view/TV/source-a/E01.mkv",
                    dest="/example/library-host/hlink/TV/八千里路云和月 (2026) {tmdbid=289624}/Season 01/E01.mkv",
                    mode="link",
                    status=True,
                    download_hash="aaaabbbbcccc1111",
                    tmdbid=289624,
                ),
                MPTransferHistoryRecord(
                    id=11,
                    title="八千里路云和月",
                    episodes="E02",
                    src="/example/qb-view/TV/source-b/E02.mkv",
                    dest="/example/library-host/hlink/TV/八千里路云和月 副本/Season 01/E02.mkv",
                    mode="link",
                    status=True,
                    download_hash="ddddffffeeee2222",
                    tmdbid=289624,
                ),
            ],
            expected_title="八千里路云和月",
            expected_tmdbid=289624,
        )

        class FakeClient:
            def delete_transfer_history(self, history_id, deletesrc=True, deletedest=True):
                raise AssertionError("delete should be blocked before API call")

        report = execute_mp_cleanup_from_preview(
            FakeClient(),
            preview,
            expected_title="八千里路云和月",
            expected_tmdbid=289624,
            expected_hash_prefix="",
            expected_record_count=2,
            expected_episode_count=2,
            expected_episode_min=1,
            expected_episode_max=2,
            allow_multiple_hashes=True,
            allow_multiple_source_roots=True,
        )

        self.assertFalse(report["ok"])
        self.assertIn("destination_root_count_mismatch", report["blockers"])

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

    def test_mp_cleanup_verify_cli_returns_nonzero_when_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "verify.json"
            env_file.write_text("MP_BASE_URL=http://mp.example\nMP_API_TOKEN=token\n", encoding="utf-8")

            with patch("series_cloud_archiver.cleanup_verify.MoviePilotClient") as fake_client_class:
                fake_client = fake_client_class.return_value
                fake_client.transfer_history.return_value = [
                    MPTransferHistoryRecord(
                        id=10,
                        title="楚汉传奇",
                        episodes="E01",
                        status=True,
                        download_hash="feedface00001234567890",
                        tmdbid=41146,
                    )
                ]
                code = main(
                    [
                        "mp-cleanup-verify",
                        "--env-file",
                        str(env_file),
                        "--title",
                        "楚汉传奇",
                        "--expected-title",
                        "楚汉传奇",
                        "--expected-tmdbid",
                        "41146",
                        "--expected-hash-prefix",
                        "feedface0000",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 1)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertIn("mp_transfer_history_still_present", payload["blockers"])

    def test_strm_verify_checks_episode_coverage_and_target_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strm_root = Path(tmp) / "strm" / "series" / "校园之外 (2026) {tmdbid=273240}" / "Season 01"
            strm_root.mkdir(parents=True)
            for index in range(1, 3):
                (strm_root / f"校园之外 S01E{index:02d}.strm").write_text(
                    f"/已整理/series/校园之外 (2026) {{tmdbid=273240}}/Season 1/E{index:02d}.mkv",
                    encoding="utf-8",
                )

            report = verify_strm_paths(
                "校园之外",
                [str(strm_root)],
                expected_episode_count=2,
                expected_episode_min=1,
                expected_episode_max=2,
                required_target_prefix="/已整理/series/校园之外 (2026) {tmdbid=273240}",
                forbidden_target_prefixes=["/series", "/已整理/series/series"],
            )
            rendered = render_strm_verification(report, "markdown")

            self.assertTrue(report["ok"])
            self.assertEqual(report["strm"]["combined"]["episodes"], [1, 2])
            self.assertIn("Required target prefix", rendered)

    def test_strm_verify_checks_redirect_url_path_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strm_root = Path(tmp) / "strm" / "series" / "校园之外 (2026) {tmdbid=273240}" / "Season 01"
            strm_root.mkdir(parents=True)
            (strm_root / "校园之外 S01E01.strm").write_text(
                "https://mv3.example/redirect?path=/已整理/series/校园之外%20(2026)%20%7Btmdbid%3D273240%7D/Season%201/E01.mkv&pickcode=secret",
                encoding="utf-8",
            )

            report = verify_strm_paths(
                "校园之外",
                [str(strm_root)],
                expected_episode_count=1,
                expected_episode_min=1,
                expected_episode_max=1,
                required_target_prefix="/已整理/series/校园之外 (2026) {tmdbid=273240}",
                forbidden_target_prefixes=["/series"],
            )

            self.assertTrue(report["ok"])
            sample = report["strm"]["roots"][0]["sample_files"][0]
            self.assertIn("校园之外", sample)

    def test_strm_verify_blocks_wrong_target_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strm_root = Path(tmp) / "strm" / "series" / "校园之外 (2026) {tmdbid=273240}" / "Season 01"
            strm_root.mkdir(parents=True)
            (strm_root / "校园之外 S01E01.strm").write_text(
                "/series/校园之外 (2026) {tmdbid=273240}/Season 1/E01.mkv",
                encoding="utf-8",
            )

            report = verify_strm_paths(
                "校园之外",
                [str(strm_root)],
                expected_episode_count=1,
                expected_episode_min=1,
                expected_episode_max=1,
                required_target_prefix="/已整理/series/校园之外 (2026) {tmdbid=273240}",
                forbidden_target_prefixes=["/series"],
            )

            self.assertFalse(report["ok"])
            self.assertIn("strm_target_prefix_mismatch", report["blockers"])
            self.assertIn("strm_forbidden_target_prefix", report["blockers"])

    def test_strm_nfo_language_audit_accepts_chinese_nfo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strm_root = Path(tmp) / "strm" / "series" / "心理测量者 (2012) {tmdbid=43865}" / "Season 01"
            strm_root.mkdir(parents=True)
            (strm_root / "心理测量者 S01E01.nfo").write_text(
                "<episodedetails><title>犯罪系数</title><plot><![CDATA[新人监视官常守朱来到公安局刑事课，第一次面对西比拉系统下的真实案件。]]></plot></episodedetails>",
                encoding="utf-8",
            )

            report = audit_strm_nfo_language([str(strm_root)])
            rendered = render_strm_nfo_language_audit(report, "markdown")

            self.assertTrue(report["ok"])
            self.assertEqual(report["summary"]["nfo_count"], 1)
            self.assertIn("NFO files", rendered)

    def test_strm_nfo_language_audit_blocks_english_plot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strm_root = Path(tmp) / "strm" / "series" / "Demo (2026) {tmdbid=1}" / "Season 01"
            strm_root.mkdir(parents=True)
            (strm_root / "Demo S01E01.nfo").write_text(
                "<episodedetails><title>Pilot</title><plot>A detective investigates a strange case in a city full of secrets and lies.</plot></episodedetails>",
                encoding="utf-8",
            )

            report = audit_strm_nfo_language([str(strm_root)], min_chinese_ratio=0.35)

            self.assertFalse(report["ok"])
            self.assertIn("strm_nfo_language_not_chinese", report["blockers"])
            self.assertEqual(report["summary"]["suspect_english_count"], 1)

    def test_strm_nfo_language_audit_cli_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strm_root = Path(tmp) / "strm" / "series" / "Demo (2026) {tmdbid=1}" / "Season 01"
            strm_root.mkdir(parents=True)
            (strm_root / "Demo S01E01.nfo").write_text(
                "<episodedetails><title>第一集</title><plot>这是一段中文剧情简介，用于确认 STRM 侧 NFO 已经是中文内容。</plot></episodedetails>",
                encoding="utf-8",
            )
            output = Path(tmp) / "nfo-language.json"

            code = main(
                [
                    "strm-nfo-language-audit",
                    "--strm-root",
                    str(strm_root),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["nfo_count"], 1)

    def test_duplicate_strm_cleanup_previews_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            correct = tmp_path / "strm" / "series" / "岁月有情时 (2026) {tmdbid=272681}" / "Season 1"
            duplicate = tmp_path / "strm" / "series" / "series" / "岁月有情时 (2026) {tmdbid=272681}" / "Season 1"
            for root in (correct, duplicate):
                root.mkdir(parents=True)
                for index in range(1, 3):
                    (root / f"岁月有情时 - S01E{index:02d}.strm").write_text(
                        f"https://mv3.example/redirect?path=/已整理/series/岁月有情时 (2026) {{tmdbid=272681}}/Season 1/E{index:02d}.mkv",
                        encoding="utf-8",
                    )

            report = cleanup_duplicate_strm_root(
                "岁月有情时",
                str(correct),
                str(duplicate),
                expected_episode_count=2,
                expected_episode_min=1,
                expected_episode_max=2,
                required_target_prefix="/已整理/series/岁月有情时 (2026) {tmdbid=272681}",
            )
            rendered = render_duplicate_strm_cleanup(report, "markdown")

            self.assertTrue(report["ok"])
            self.assertTrue(report["ready_for_delete"])
            self.assertFalse(report["delete_executed"])
            self.assertTrue(duplicate.exists())
            self.assertIn("Ready for delete", rendered)

    def test_duplicate_strm_cleanup_deletes_only_approved_duplicate_strm_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            correct = tmp_path / "strm" / "series" / "岁月有情时 (2026) {tmdbid=272681}" / "Season 1"
            duplicate = tmp_path / "strm" / "series" / "series" / "岁月有情时 (2026) {tmdbid=272681}" / "Season 1"
            for root in (correct, duplicate):
                root.mkdir(parents=True)
                for index in range(1, 3):
                    (root / f"岁月有情时 - S01E{index:02d}.strm").write_text(
                        f"/已整理/series/岁月有情时 (2026) {{tmdbid=272681}}/Season 1/E{index:02d}.mkv",
                        encoding="utf-8",
                    )

            report = cleanup_duplicate_strm_root(
                "岁月有情时",
                str(correct),
                str(duplicate),
                expected_episode_count=2,
                expected_episode_min=1,
                expected_episode_max=2,
                required_target_prefix="/已整理/series/岁月有情时 (2026) {tmdbid=272681}",
                approve_delete=True,
            )

            self.assertTrue(report["ok"])
            self.assertTrue(report["delete_executed"])
            self.assertFalse(duplicate.exists())
            self.assertTrue(correct.exists())
            self.assertEqual(len(report["filesystem"]["deleted_files"]), 2)

    def test_duplicate_strm_cleanup_blocks_non_strm_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            correct = tmp_path / "strm" / "series" / "岁月有情时 (2026) {tmdbid=272681}" / "Season 1"
            duplicate = tmp_path / "strm" / "series" / "series" / "岁月有情时 (2026) {tmdbid=272681}" / "Season 1"
            for root in (correct, duplicate):
                root.mkdir(parents=True)
                (root / "岁月有情时 - S01E01.strm").write_text(
                    "/已整理/series/岁月有情时 (2026) {tmdbid=272681}/Season 1/E01.mkv",
                    encoding="utf-8",
                )
            (duplicate / "poster.jpg").write_bytes(b"image")

            report = cleanup_duplicate_strm_root(
                "岁月有情时",
                str(correct),
                str(duplicate),
                expected_episode_count=1,
                expected_episode_min=1,
                expected_episode_max=1,
                required_target_prefix="/已整理/series/岁月有情时 (2026) {tmdbid=272681}",
                approve_delete=True,
            )

            self.assertFalse(report["ok"])
            self.assertFalse(report["delete_executed"])
            self.assertTrue(duplicate.exists())
            self.assertIn("duplicate_root_contains_non_strm_files", report["blockers"])

    def test_cli_writes_duplicate_strm_cleanup_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output = tmp_path / "duplicate-cleanup.json"
            correct = tmp_path / "strm" / "series" / "岁月有情时 (2026) {tmdbid=272681}" / "Season 1"
            duplicate = tmp_path / "strm" / "series" / "series" / "岁月有情时 (2026) {tmdbid=272681}" / "Season 1"
            for root in (correct, duplicate):
                root.mkdir(parents=True)
                (root / "岁月有情时 - S01E01.strm").write_text(
                    "/已整理/series/岁月有情时 (2026) {tmdbid=272681}/Season 1/E01.mkv",
                    encoding="utf-8",
                )

            code = main(
                [
                    "strm-duplicate-cleanup",
                    "--title",
                    "岁月有情时",
                    "--correct-root",
                    str(correct),
                    "--duplicate-root",
                    str(duplicate),
                    "--expected-episode-count",
                    "1",
                    "--expected-episode-min",
                    "1",
                    "--expected-episode-max",
                    "1",
                    "--required-target-prefix",
                    "/已整理/series/岁月有情时 (2026) {tmdbid=272681}",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ready_for_delete"])
            self.assertFalse(payload["delete_executed"])

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
