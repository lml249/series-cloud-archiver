import tempfile
import unittest
import json
from pathlib import Path
from typing import List

from series_cloud_archiver.cloud_check import cloud_check_from_scan_report


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("http://example.invalid/redacted", encoding="utf-8")


def write_strm(path: Path, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(target, encoding="utf-8")


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

    def test_records_real_strm_target_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm"
            for episode in [1, 2]:
                write_strm(
                    root / "series" / "西部世界 (2016) {tmdbid=63247}" / "Season 02" / f"Westworld S02E{episode:02d}.strm",
                    f"https://mv3.example/redirect?path=/organized-root/Westworld%20(2016)/Season%202/Westworld.S02E{episode:02d}.mkv&code=redacted",
                )
            report = {"candidates": [candidate("西部世界", 63247, 2, [1, 2])]}

            result = cloud_check_from_scan_report(report, [str(root)])

            item = result.items[0]
            self.assertEqual(item.status, "cloud_strm_complete")
            self.assertEqual(item.strm_target_prefix, "/organized-root/Westworld (2016)/Season 2")
            self.assertEqual(item.strm_target_prefixes, ["/organized-root/Westworld (2016)/Season 2"])

    def test_carries_source_qb_hashes_from_scan_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm"
            touch(root / "series" / "Demo Show (2026) {tmdbid=123}" / "Season 01" / "Demo Show S01E01.strm")
            row = candidate("Demo Show", 123, 1, [1])
            row["qb"] = {"hash": "ABCDEF123456ABCDEF123456ABCDEF123456ABCD"}
            report = {"candidates": [row]}

            result = cloud_check_from_scan_report(report, [str(root)])

            self.assertEqual(result.items[0].source_qb_hashes, ["abcdef123456abcdef123456abcdef123456abcd"])

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

    def test_title_season_match_requires_meaningful_title_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm"
            for episode in range(1, 27):
                touch(root / "anime" / "诛仙 (2022) {tmdbid=206484}" / "Season 01" / f"诛仙 S01E{episode:02d}.strm")
            report = {
                "candidates": [
                    {
                        "title": "漫长的季节 (2023) Season 01",
                        "status": "candidate_for_cloud_check",
                        "size_bytes": 1024,
                        "video_count": 12,
                        "episode_numbers": list(range(1, 13)),
                        "seasons": [1],
                    }
                ]
            }

            result = cloud_check_from_scan_report(report, [str(root)])

            self.assertEqual(result.status_counts, {"needs_identity_review": 1})
            self.assertEqual(result.items[0].cloud_episode_count, 0)
            self.assertIn("missing_tmdb_and_no_safe_title_match", result.items[0].blockers)

    def test_identity_parent_path_applies_to_split_season_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "strm"
            for episode in range(1, 13):
                touch(root / "series" / "漫长的季节 (2023) {tmdbid=225008}" / "Season 01" / f"漫长的季节 S01E{episode:02d}.strm")
            identity_file = tmp_path / "identity.json"
            identity_file.write_text(
                json.dumps(
                    {
                        "identity_overrides": [
                            {
                                "match_title": "漫长的季节 (2023)",
                                "match_path": "/media/hlink/TV/漫长的季节 (2023)",
                                "title": "漫长的季节",
                                "tmdbid": 225008,
                                "season": 1,
                                "expected_episodes": list(range(1, 13)),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = {
                "candidates": [
                    {
                        "title": "漫长的季节 (2023) Season 01",
                        "path": "/media/hlink/TV/漫长的季节 (2023)/Season 1",
                        "status": "candidate_for_cloud_check",
                        "size_bytes": 1024,
                        "video_count": 12,
                        "episode_numbers": list(range(1, 13)),
                        "seasons": [1],
                    }
                ]
            }

            result = cloud_check_from_scan_report(report, [str(root)], identity_file=str(identity_file))

            self.assertEqual(result.status_counts, {"cloud_strm_complete": 1})
            self.assertEqual(result.items[0].tmdbid, 225008)

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
                        "video_count": 2,
                        "episode_sample": [1, 2],
                    }
                ]
            }

            result = cloud_check_from_scan_report(report, [str(root)], identity_file=str(identity_file))

            self.assertEqual(result.status_counts, {"cloud_strm_complete": 1})
            self.assertEqual(result.items[0].tmdbid, 93740)
            self.assertEqual(result.items[0].expected_count, 2)

    def test_identity_expected_episodes_fill_when_local_episode_numbers_are_unknown(self) -> None:
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
                    }
                ]
            }

            result = cloud_check_from_scan_report(report, [str(root)], identity_file=str(identity_file))

            self.assertEqual(result.status_counts, {"cloud_strm_incomplete": 1})
            self.assertEqual(result.items[0].expected_episodes, [1, 2, 3])
            self.assertEqual(result.items[0].missing_episodes, [3])

    def test_local_episode_numbers_take_precedence_over_inflated_identity_expected_episodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "strm"
            for episode in range(1, 37):
                touch(root / "series" / "折腰 (2025) {tmdbid=296753}" / "Season 01" / f"折腰 S01E{episode:02d}.strm")
            identity_file = tmp_path / "identity.json"
            identity_file.write_text(
                json.dumps(
                    {
                        "identity_overrides": [
                            {
                                "match_title": "折腰 (2025)",
                                "title": "折腰",
                                "tmdbid": 296753,
                                "season": 1,
                                "expected_episodes": list(range(1, 72)),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = {
                "candidates": [
                    {
                        "title": "折腰 (2025)",
                        "status": "candidate_for_cloud_check",
                        "size_bytes": 1024,
                        "video_count": 36,
                        "episode_numbers": list(range(1, 37)),
                    }
                ]
            }

            result = cloud_check_from_scan_report(report, [str(root)], identity_file=str(identity_file))

            self.assertEqual(result.status_counts, {"cloud_strm_complete": 1})
            self.assertEqual(result.items[0].expected_count, 36)
            self.assertEqual(result.items[0].expected_episodes, list(range(1, 37)))
            self.assertEqual(result.items[0].missing_episodes, [])


if __name__ == "__main__":
    unittest.main()
