import tempfile
import unittest
import json
from pathlib import Path
from typing import List

from series_cloud_archiver.cloud_check import cloud_check_from_scan_report


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("http://example.invalid/redacted", encoding="utf-8")


def candidate(title: str, tmdbid: int, season: int, episodes: List[int]) -> dict:
    return {
        "title": title,
        "status": "candidate_for_cloud_check",
        "size_bytes": 1024,
        "video_count": len(episodes),
        "episode_numbers": episodes,
        "manual_completion": {
            "title": title,
            "tmdbid": tmdbid,
            "season": season,
            "matched": True,
        },
    }


class CloudCheckTest(unittest.TestCase):
    def test_marks_complete_when_strm_episodes_cover_expected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm"
            touch(root / "series" / "Demo Show (2026) {tmdbid=123}" / "Season 01" / "Demo Show S01E01.strm")
            touch(root / "series" / "Demo Show (2026) {tmdbid=123}" / "Season 01" / "Demo Show S01E02.strm")
            report = {"candidates": [candidate("Demo Show", 123, 1, [1, 2])]}

            result = cloud_check_from_scan_report(report, [str(root)])

            self.assertEqual(result.status_counts, {"cloud_strm_complete": 1})
            self.assertEqual(result.items[0].missing_episodes, [])

    def test_marks_incomplete_when_strm_episode_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm"
            touch(root / "series" / "Demo Show (2026) {tmdbid=123}" / "Season 01" / "Demo Show S01E01.strm")
            report = {"candidates": [candidate("Demo Show", 123, 1, [1, 2])]}

            result = cloud_check_from_scan_report(report, [str(root)])

            self.assertEqual(result.status_counts, {"cloud_strm_incomplete": 1})
            self.assertEqual(result.items[0].missing_episodes, [2])

    def test_merges_same_tmdb_season_before_checking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm"
            touch(root / "series" / "Demo Show (2026) {tmdbid=123}" / "Season 01" / "Demo Show S01E01.strm")
            touch(root / "series" / "Demo Show (2026) {tmdbid=123}" / "Season 01" / "Demo Show S01E02.strm")
            report = {
                "candidates": [
                    candidate("Demo Show 1080p", 123, 1, [1]),
                    candidate("Demo Show 2160p", 123, 1, [2]),
                ]
            }

            result = cloud_check_from_scan_report(report, [str(root)])

            self.assertEqual(result.total_candidate_groups, 1)
            self.assertEqual(result.items[0].candidate_count, 2)
            self.assertEqual(result.items[0].status, "cloud_strm_complete")

    def test_can_use_title_season_match_when_candidate_lacks_tmdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm"
            touch(root / "series" / "西部世界 (2016) {tmdbid=63247}" / "Season 02" / "Westworld.2016.S02E01.strm")
            touch(root / "series" / "西部世界 (2016) {tmdbid=63247}" / "Season 02" / "Westworld.2016.S02E02.strm")
            report = {
                "candidates": [
                    {
                        "title": "Westworld 2016 S02 2160p UHD BluRay Remux",
                        "status": "candidate_for_cloud_check",
                        "size_bytes": 1024,
                        "video_count": 2,
                        "episode_numbers": [1, 2],
                        "seasons": [2],
                    }
                ]
            }

            result = cloud_check_from_scan_report(report, [str(root)])

            self.assertEqual(result.status_counts, {"cloud_strm_complete": 1})
            self.assertIn("strm_title_season_match", result.items[0].reasons)

    def test_does_not_treat_episode_sample_as_complete_episode_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm"
            touch(root / "series" / "Demo Show (2026) {tmdbid=123}" / "Season 01" / "Demo Show S01E01.strm")
            touch(root / "series" / "Demo Show (2026) {tmdbid=123}" / "Season 01" / "Demo Show S01E02.strm")
            report = {
                "candidates": [
                    {
                        "title": "Demo Show",
                        "status": "candidate_for_cloud_check",
                        "size_bytes": 1024,
                        "video_count": 12,
                        "episode_sample": [1, 2],
                        "manual_completion": {
                            "title": "Demo Show",
                            "tmdbid": 123,
                            "season": 1,
                            "matched": True,
                        },
                    }
                ]
            }

            result = cloud_check_from_scan_report(report, [str(root)])

            self.assertEqual(result.status_counts, {"cloud_strm_incomplete": 1})
            self.assertEqual(result.items[0].expected_count, 12)

    def test_identity_file_can_supply_tmdb_season_and_expected_episodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "strm"
            touch(root / "series" / "基地 (2021) {tmdbid=93740}" / "Season 01" / "Foundation S01E01.strm")
            touch(root / "series" / "基地 (2021) {tmdbid=93740}" / "Season 01" / "Foundation S01E02.strm")
            identity_file = tmp_path / "identity.json"
            identity_file.write_text(
                json.dumps(
                    {
                        "identity_overrides": [
                            {
                                "match_title": "Foundation.S01.2021",
                                "title": "基地",
                                "tmdbid": 93740,
                                "season": 1,
                                "expected_episodes": [1, 2],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = {
                "candidates": [
                    {
                        "title": "Foundation.S01.2021",
                        "status": "candidate_for_cloud_check",
                        "size_bytes": 1024,
                        "video_count": 10,
                        "episode_sample": [1, 2],
                    }
                ]
            }

            result = cloud_check_from_scan_report(report, [str(root)], identity_file=str(identity_file))

            self.assertEqual(result.status_counts, {"cloud_strm_complete": 1})
            self.assertEqual(result.items[0].tmdbid, 93740)
            self.assertEqual(result.items[0].expected_count, 2)

    def test_identity_expected_episodes_are_not_masked_by_partial_local_episodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "strm"
            touch(root / "series" / "基地 (2021) {tmdbid=93740}" / "Season 01" / "Foundation S01E01.strm")
            touch(root / "series" / "基地 (2021) {tmdbid=93740}" / "Season 01" / "Foundation S01E02.strm")
            identity_file = tmp_path / "identity.json"
            identity_file.write_text(
                json.dumps(
                    {
                        "identity_overrides": [
                            {
                                "match_title": "Foundation.S01.2021",
                                "title": "基地",
                                "tmdbid": 93740,
                                "season": 1,
                                "expected_episodes": [1, 2, 3],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = {
                "candidates": [
                    {
                        "title": "Foundation.S01.2021",
                        "status": "candidate_for_cloud_check",
                        "size_bytes": 1024,
                        "video_count": 2,
                        "episode_numbers": [1, 2],
                    }
                ]
            }

            result = cloud_check_from_scan_report(report, [str(root)], identity_file=str(identity_file))

            self.assertEqual(result.status_counts, {"cloud_strm_incomplete": 1})
            self.assertEqual(result.items[0].expected_episodes, [1, 2, 3])
            self.assertEqual(result.items[0].missing_episodes, [3])


if __name__ == "__main__":
    unittest.main()
