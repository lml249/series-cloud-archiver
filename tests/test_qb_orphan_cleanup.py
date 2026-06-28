import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.moviepilot import MPTransferHistoryRecord
from series_cloud_archiver.qb_orphan_cleanup import (
    execute_qb_orphan_torrent_cleanup,
    preview_qb_orphan_torrent_cleanup,
)


FULL_HASH = "54e6fafc796dedce402f91cbc8b69d55d6bb3dc0"


def write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class QbOrphanTorrentCleanupTest(unittest.TestCase):
    def test_preview_allows_missing_local_roots_with_complete_strm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_root = tmp_path / "volume3" / "TV" / "Echoes.of.a.Thousand.Moons.S01"
            hlink_root = tmp_path / "volume3" / "hlink" / "TV" / "八千里路云和月 (2026)"
            strm_root = tmp_path / "volume4" / "mv3" / "strm" / "series" / "八千里路云和月 (2026) {tmdbid=289624}" / "Season 01"
            write(strm_root / "八千里路云和月.S01E01.strm", "/已整理/series/八千里路云和月/Season 01/E01.mkv")
            write(strm_root / "八千里路云和月.S01E02.strm", "/已整理/series/八千里路云和月/Season 01/E02.mkv")

            class FakeClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=20):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return [
                        {
                            "name": "[八千里路云和月].Echoes.of.a.Thousand.Moons.S01.2026.1080p",
                            "hash": FULL_HASH,
                            "state": "stalledUP",
                            "save_path": "/example-qb/TV",
                            "content_path": "/example-qb/TV/Echoes.of.a.Thousand.Moons.S01",
                            "progress": 1.0,
                            "seeding_time": 86400 * 30,
                            "size": 1024,
                        }
                    ]

                def torrent_files(self, _torrent_hash):
                    return [
                        {"name": "Echoes.of.a.Thousand.Moons.S01/E01.mkv", "size": 1},
                        {"name": "Echoes.of.a.Thousand.Moons.S01/E02.mkv", "size": 1},
                    ]

            with patch("series_cloud_archiver.qb_orphan_cleanup.QBClient", FakeClient):
                report = preview_qb_orphan_torrent_cleanup(
                    "八千里路云和月",
                    [FULL_HASH],
                    [str(source_root)],
                    [str(hlink_root)],
                    [str(strm_root)],
                    expected_tmdbid=289624,
                    expected_episode_count=2,
                    expected_episode_min=1,
                    expected_episode_max=2,
                    qb_base_url="http://qb.example",
                    path_aliases={"/example-qb/TV": str(tmp_path / "volume3" / "TV")},
                    required_target_prefix="/已整理/series/八千里路云和月",
                )

        self.assertTrue(report["ok"])
        self.assertTrue(report["ready_for_execute"])
        self.assertEqual(report["qbittorrent"]["matched_count"], 1)
        self.assertEqual(report["filesystem"]["source_roots"][0]["exists"], False)
        self.assertIn("mp_transfer_history_check_skipped", report["warnings"])

    def test_preview_blocks_cloud_media_strm_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cloud_root = tmp_path / "已整理" / "series" / "Show" / "Season 01"
            write(cloud_root / "Show.S01E01.strm", "/已整理/series/Show/E01.mkv")

            class EmptyClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=20):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return []

            with patch("series_cloud_archiver.qb_orphan_cleanup.QBClient", EmptyClient):
                report = preview_qb_orphan_torrent_cleanup(
                    "Show",
                    [FULL_HASH],
                    [str(tmp_path / "source" / "Show")],
                    [str(tmp_path / "hlink" / "Show")],
                    [str(cloud_root)],
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                )

        self.assertFalse(report["ok"])
        self.assertIn("strm_root_must_be_strm_side", report["blockers"])

    def test_preview_blocks_when_moviepilot_history_still_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            strm_root = tmp_path / "strm" / "series" / "Show" / "Season 01"
            write(strm_root / "Show.S01E01.strm", "/已整理/series/Show/E01.mkv")

            class FakeClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=20):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return [
                        {
                            "name": "Show.S01",
                            "hash": FULL_HASH,
                            "state": "stalledUP",
                            "save_path": "/source",
                            "content_path": "/source/Show.S01",
                            "progress": 1.0,
                            "seeding_time": 86400 * 30,
                            "size": 1,
                        }
                    ]

                def torrent_files(self, _torrent_hash):
                    return [{"name": "Show.S01/Show.S01E01.mkv", "size": 1}]

            record = MPTransferHistoryRecord(id=1, title="Show", tmdbid=1, status=True)
            with patch("series_cloud_archiver.qb_orphan_cleanup.QBClient", FakeClient), patch(
                "series_cloud_archiver.qb_orphan_cleanup.MoviePilotClient.transfer_history", return_value=[record]
            ):
                report = preview_qb_orphan_torrent_cleanup(
                    "Show",
                    [FULL_HASH],
                    [str(tmp_path / "source" / "Show.S01")],
                    [str(tmp_path / "hlink" / "Show")],
                    [str(strm_root)],
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    mp_base_url="http://mp.example",
                    mp_token="token",
                    path_aliases={"/source": str(tmp_path / "source")},
                    required_target_prefix="/已整理/series/Show",
                )

        self.assertFalse(report["ok"])
        self.assertIn("mp_transfer_history_still_present_use_mp_cleanup", report["blockers"])

    def test_preview_requires_full_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            strm_root = tmp_path / "strm" / "series" / "Show" / "Season 01"
            write(strm_root / "Show.S01E01.strm", "/已整理/series/Show/E01.mkv")

            report = preview_qb_orphan_torrent_cleanup(
                "Show",
                ["54e6fafc"],
                [str(tmp_path / "source" / "Show")],
                [str(tmp_path / "hlink" / "Show")],
                [str(strm_root)],
                expected_tmdbid=1,
                expected_episode_count=1,
                expected_episode_min=1,
                expected_episode_max=1,
                qb_base_url="",
            )

        self.assertFalse(report["ok"])
        self.assertIn("expected_qb_hash_must_be_full", report["blockers"])

    def test_preview_blocks_when_qb_only_points_at_shared_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            strm_root = tmp_path / "strm" / "series" / "Show" / "Season 01"
            write(strm_root / "Show.S01E01.strm", "/已整理/series/Show/E01.mkv")

            class FakeClient:
                def __init__(self, base_url, user="", qb_pass="", timeout=20):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    return [
                        {
                            "name": "Show.S01",
                            "hash": FULL_HASH,
                            "state": "stalledUP",
                            "save_path": "/example-source",
                            "content_path": "/example-source",
                            "progress": 1.0,
                            "seeding_time": 86400 * 30,
                            "size": 1,
                        }
                    ]

                def torrent_files(self, _torrent_hash):
                    return []

            with patch("series_cloud_archiver.qb_orphan_cleanup.QBClient", FakeClient):
                report = preview_qb_orphan_torrent_cleanup(
                    "Show",
                    [FULL_HASH],
                    [str(tmp_path / "source" / "Show.S01")],
                    [str(tmp_path / "hlink" / "Show")],
                    [str(strm_root)],
                    expected_tmdbid=1,
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                    path_aliases={"/example-source": str(tmp_path / "source")},
                    required_target_prefix="/已整理/series/Show",
                )

        self.assertFalse(report["ok"])
        self.assertIn("qb_content_outside_expected_source_root", report["blockers"])

    def test_execute_deletes_qb_task_without_deleting_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_root = tmp_path / "source" / "Show.S01"
            hlink_root = tmp_path / "hlink" / "Show"
            strm_root = tmp_path / "strm" / "series" / "Show" / "Season 01"
            write(strm_root / "Show.S01E01.strm", "/已整理/series/Show/E01.mkv")
            preview = {
                "mode": "qb-orphan-torrent-cleanup-preview",
                "title": "Show",
                "ready_for_execute": True,
                "blockers": [],
                "warnings": [],
                "expected": {
                    "tmdbid": 1,
                    "qb_hashes": [FULL_HASH],
                    "source_roots": [str(source_root)],
                    "hlink_roots": [str(hlink_root)],
                    "strm_roots": [str(strm_root)],
                    "episode_count": 1,
                    "episode_min": 1,
                    "episode_max": 1,
                    "expected_title_contains": "Show",
                    "min_seed_days": 7,
                    "required_target_prefix": "/已整理/series/Show",
                    "forbidden_target_prefixes": [],
                },
            }

            class FakeClient:
                calls = []
                deleted = False

                def __init__(self, base_url, user="", qb_pass="", timeout=20):
                    pass

                def login(self):
                    pass

                def torrents(self):
                    if self.deleted:
                        return []
                    return [
                        {
                            "name": "Show.S01",
                            "hash": FULL_HASH,
                            "state": "stalledUP",
                            "save_path": "/source",
                            "content_path": "/source/Show.S01",
                            "progress": 1.0,
                            "seeding_time": 86400 * 30,
                            "size": 1,
                        }
                    ]

                def torrent_files(self, _torrent_hash):
                    return [{"name": "Show.S01/Show.S01E01.mkv", "size": 1}]

                def delete_torrents(self, hashes, delete_files=True):
                    type(self).calls.append((hashes, delete_files))
                    type(self).deleted = True
                    return {"http_status": 200, "ok": True, "response": ""}

            FakeClient.calls = []
            FakeClient.deleted = False
            with patch("series_cloud_archiver.qb_orphan_cleanup.QBClient", FakeClient):
                report = execute_qb_orphan_torrent_cleanup(
                    preview,
                    "http://qb.example",
                    path_aliases={"/source": str(tmp_path / "source")},
                )

        self.assertTrue(report["ok"])
        self.assertEqual(FakeClient.calls, [([FULL_HASH], False)])
        self.assertEqual(report["delete_files"], False)

    def test_cli_requires_approval_before_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            preview_file = tmp_path / "preview.json"
            env_file.write_text("QB_BASE_URL=http://qb.example\n", encoding="utf-8")
            preview_file.write_text(
                json.dumps(
                    {
                        "mode": "qb-orphan-torrent-cleanup-preview",
                        "title": "Show",
                        "expected": {
                            "tmdbid": 1,
                            "qb_hashes": [FULL_HASH],
                            "source_roots": ["/source/Show"],
                            "hlink_roots": ["/hlink/Show"],
                            "strm_roots": ["/strm/Show"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(SystemExit):
                main(
                    [
                        "qb-orphan-torrent-cleanup-execute",
                        "--env-file",
                        str(env_file),
                        "--preview-report",
                        str(preview_file),
                        "--expected-title",
                        "Show",
                        "--expected-tmdbid",
                        "1",
                        "--expected-qb-hash",
                        FULL_HASH,
                        "--expected-source-root",
                        "/source/Show",
                        "--expected-hlink-root",
                        "/hlink/Show",
                        "--expected-strm-root",
                        "/strm/Show",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
