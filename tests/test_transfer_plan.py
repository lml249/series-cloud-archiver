import unittest

from series_cloud_archiver.transfer_plan import plan_mv3_transfers_from_cloud_report, render_mv3_transfer_plan


class TransferPlanTest(unittest.TestCase):
    def test_plans_not_found_items_with_identity_by_size(self) -> None:
        report = {
            "mode": "readonly-cloud-check",
            "items": [
                {
                    "status": "cloud_strm_complete",
                    "title": "Already Cloud",
                    "tmdbid": 1,
                    "season": 1,
                    "size_bytes": 999,
                },
                {
                    "status": "cloud_strm_not_found",
                    "title": "Small Show",
                    "tmdbid": 2,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 10,
                    "candidate_count": 1,
                    "titles": ["Small.Show.S01"],
                    "source_paths": ["/example/media/Small.Show.S01"],
                    "missing_episodes": [1, 2],
                    "blockers": ["no_matching_strm_tmdb_season"],
                },
                {
                    "status": "cloud_strm_not_found",
                    "title": "Big Show",
                    "tmdbid": 3,
                    "season": 2,
                    "size_bytes": 200,
                    "expected_count": 12,
                    "candidate_count": 2,
                    "titles": ["Big.Show.S02"],
                    "source_paths": ["/example/media/Big.Show.S02"],
                    "missing_episodes": [1],
                    "blockers": ["no_matching_strm_tmdb_season"],
                },
                {
                    "status": "needs_identity_review",
                    "title": "Unknown Season",
                    "tmdbid": 4,
                    "season": 0,
                    "size_bytes": 300,
                },
            ],
        }

        plan = plan_mv3_transfers_from_cloud_report(report)

        self.assertEqual(plan["mode"], "readonly-mv3-transfer-plan")
        self.assertEqual(plan["total_planned"], 2)
        self.assertEqual([item["title"] for item in plan["items"]], ["Big Show", "Small Show"])
        self.assertEqual(plan["total_size_bytes"], 300)

    def test_renders_markdown_with_safety_note(self) -> None:
        plan = {
            "mode": "readonly-mv3-transfer-plan",
            "source_mode": "readonly-cloud-check",
            "included_statuses": ["cloud_strm_not_found"],
            "total_planned": 1,
            "total_size_bytes": 100,
            "status_counts": {"cloud_strm_not_found": 1},
            "items": [
                {
                    "title": "Demo",
                    "tmdbid": 123,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 2,
                    "candidate_count": 1,
                    "titles": ["Demo.S01"],
                    "source_paths": ["/example/media/Demo.S01"],
                }
            ],
            "warnings": [],
        }

        markdown = render_mv3_transfer_plan(plan, "markdown")

        self.assertIn("MV3 Transfer Plan", markdown)
        self.assertIn("no MV3 transfer", markdown)
        self.assertIn("Demo", markdown)


if __name__ == "__main__":
    unittest.main()
