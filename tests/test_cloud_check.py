import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
