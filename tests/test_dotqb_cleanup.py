import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.dotqb_cleanup import cleanup_orphan_dotqb_roots


def touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class DotqbOrphanCleanupTest(unittest.TestCase):
    def test_deletes_only_orphan_dotqb_files_after_service_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source" / "Show.S01"
            dotqb = source / "Show.S01E01.mkv.!qB"
            touch(dotqb)
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            touch(strm_root / "Show S01E01.strm")
            missing_dest = tmp_path / "missing-hlink"

            class FakeMP:
                def __init__(self, base_url, token, timeout=20):
                    pass

                def transfer_history(self, title):
                    return []

            with patch("series_cloud_archiver.dotqb_cleanup.MoviePilotClient", FakeMP), patch(
                "series_cloud_archiver.dotqb_cleanup.fetch_qb_torrents", return_value=[]
            ):
                report = cleanup_orphan_dotqb_roots(
                    "http://mp.example",
                    "token",
                    "Show",
                    source_roots=[str(source)],
                    destination_roots=[str(missing_dest)],
                    strm_roots=[str(strm_root)],
                    expected_tmdbid=123,
                    expected_hash_prefixes=["feedface0000"],
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                )

        self.assertTrue(report["ok"])
        self.assertFalse(source.exists())
        self.assertEqual(len(report["filesystem"]["deleted_files"]), 1)

    def test_blocks_when_normal_file_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source" / "Show.S01"
            touch(source / "Show.S01E01.mkv.!qB")
            touch(source / "Show.S01E02.mkv")
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            touch(strm_root / "Show S01E01.strm")

            class FakeMP:
                def __init__(self, base_url, token, timeout=20):
                    pass

                def transfer_history(self, title):
                    return []

            with patch("series_cloud_archiver.dotqb_cleanup.MoviePilotClient", FakeMP), patch(
                "series_cloud_archiver.dotqb_cleanup.fetch_qb_torrents", return_value=[]
            ):
                report = cleanup_orphan_dotqb_roots(
                    "http://mp.example",
                    "token",
                    "Show",
                    source_roots=[str(source)],
                    destination_roots=[str(tmp_path / "missing-hlink")],
                    strm_roots=[str(strm_root)],
                    expected_tmdbid=123,
                    expected_hash_prefixes=["feedface0000"],
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                )

            self.assertFalse(report["ok"])
            self.assertTrue((source / "Show.S01E01.mkv.!qB").exists())
            self.assertIn("source_root_not_safe_dotqb_orphan", report["blockers"])

    def test_blocks_when_qb_hash_still_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "source" / "Show.S01"
            touch(source / "Show.S01E01.mkv.!qB")
            strm_root = tmp_path / "strm" / "Show" / "Season 01"
            touch(strm_root / "Show S01E01.strm")

            class FakeMP:
                def __init__(self, base_url, token, timeout=20):
                    pass

                def transfer_history(self, title):
                    return []

            qb_torrents = [{"name": "Show", "hash": "feedface00001234567890", "state": "stalledUP"}]
            with patch("series_cloud_archiver.dotqb_cleanup.MoviePilotClient", FakeMP), patch(
                "series_cloud_archiver.dotqb_cleanup.fetch_qb_torrents", return_value=qb_torrents
            ):
                report = cleanup_orphan_dotqb_roots(
                    "http://mp.example",
                    "token",
                    "Show",
                    source_roots=[str(source)],
                    destination_roots=[str(tmp_path / "missing-hlink")],
                    strm_roots=[str(strm_root)],
                    expected_tmdbid=123,
                    expected_hash_prefixes=["feedface0000"],
                    expected_episode_count=1,
                    expected_episode_min=1,
                    expected_episode_max=1,
                    qb_base_url="http://qb.example",
                )

            self.assertFalse(report["ok"])
            self.assertTrue((source / "Show.S01E01.mkv.!qB").exists())
            self.assertIn("qb_torrent_hash_still_present", report["blockers"])

    def test_cli_requires_approval_before_dotqb_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            env_file.write_text("MP_BASE_URL=http://mp.example\nMP_API_TOKEN=token\nQB_BASE_URL=http://qb.example\n", encoding="utf-8")

            with self.assertRaises(SystemExit):
                main(
                    [
                        "dotqb-orphan-cleanup",
                        "--env-file",
                        str(env_file),
                        "--title",
                        "Show",
                        "--expected-tmdbid",
                        "123",
                        "--expected-hash-prefix",
                        "feedface0000",
                        "--source-root",
                        str(tmp_path / "source"),
                        "--destination-root",
                        str(tmp_path / "dest"),
                        "--strm-root",
                        str(tmp_path / "strm"),
                        "--expected-episode-count",
                        "1",
                        "--expected-episode-min",
                        "1",
                        "--expected-episode-max",
                        "1",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
