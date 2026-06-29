import json
import tempfile
import unittest
from pathlib import Path

from series_cloud_archiver.batch_runner import (
    AUTO_CLEANUP,
    AUTO_TRANSFER,
    MANUAL_REVIEW,
    build_batch_plan,
    merge_share_search_plans,
    render_batch_plan,
)
from series_cloud_archiver.cli import main


class BatchRunnerTest(unittest.TestCase):
    def test_complete_cloud_strm_item_gets_validation_cleanup_commands(self) -> None:
        plan = build_batch_plan(
            cloud_report={
                "mode": "readonly-cloud-check",
                "items": [
                    {
                        "status": "cloud_strm_complete",
                        "title": "演示剧 (2024) {tmdbid=123}",
                        "tmdbid": 123,
                        "season": 1,
                        "size_bytes": 100,
                        "expected_count": 2,
                        "strm_paths_sample": ["/volume4/volume4/mv3/strm/series/演示剧 (2024) {tmdbid=123}/Season 1/演示剧 - S01E01.strm"],
                        "source_paths": ["/volume3/volume3/hlink/TV/演示剧 (2024) {tmdbid=123}"],
                    }
                ],
            },
            host_strm_root="/volume4/volume4/mv3/strm",
            emby_strm_root="/volume4/mv3/strm",
            env_file="/safe/.env",
        )

        item = plan["items"][0]

        self.assertEqual(item["bucket"], AUTO_CLEANUP)
        self.assertEqual(item["cloud_media_path"], "/已整理/series/演示剧 (2024) {tmdbid=123}/Season 01")
        commands = "\n".join(action["command"] for action in item["next_actions"])
        self.assertIn("/volume4/volume4/mv3/strm/series/演示剧 (2024) {tmdbid=123}/Season 1", commands)
        self.assertIn("/volume4/mv3/strm/series/演示剧 (2024) {tmdbid=123}/Season 1", commands)
        self.assertNotIn("--approve-delete", commands)
        self.assertNotIn("--approve-mp-cleanup", commands)
        self.assertNotIn("/已整理/series/series", commands)

    def test_not_found_with_good_share_candidate_gets_transfer_preview_bucket(self) -> None:
        plan = build_batch_plan(
            cloud_report={
                "mode": "readonly-cloud-check",
                "items": [
                    {
                        "status": "cloud_strm_not_found",
                        "title": "干净剧 (2025) {tmdbid=456}",
                        "tmdbid": 456,
                        "season": 1,
                        "size_bytes": 1000,
                        "expected_count": 10,
                        "source_paths": ["/volume3/volume3/hlink/TV/干净剧 (2025) {tmdbid=456}/Season 01"],
                    }
                ],
            },
            transfer_plan={
                "mode": "readonly-mv3-transfer-plan",
                "items": [
                    {
                        "title": "干净剧 (2025) {tmdbid=456}",
                        "tmdbid": 456,
                        "season": 1,
                        "size_bytes": 1000,
                        "expected_count": 10,
                        "source_paths": ["/volume3/volume3/hlink/TV/干净剧 (2025) {tmdbid=456}/Season 01"],
                    }
                ],
            },
            share_search_plan={
                "mode": "readonly-mv3-share-search-plan",
                "items": [
                    {
                        "title": "干净剧 (2025) {tmdbid=456}",
                        "tmdbid": 456,
                        "season": 1,
                        "recommended_candidate": {
                            "search_index": 2,
                            "search_keyword": "干净剧",
                            "score": 85,
                            "size_delta_ratio": 0.1,
                            "blockers": [],
                        },
                        "candidates": [{"score": 85}],
                    }
                ],
            },
            cloud_root="/已整理/series",
            mv3_strm_root="/strm",
            host_strm_root="/volume4/volume4/mv3/strm",
            env_file="/safe/.env",
        )

        item = plan["items"][0]

        self.assertEqual(item["bucket"], AUTO_TRANSFER)
        self.assertEqual(item["cloud_media_path"], "/已整理/series/干净剧 (2025) {tmdbid=456}/Season 01")
        commands = "\n".join(action["command"] for action in item["next_actions"])
        self.assertIn("--selection-index 2", commands)
        self.assertIn("/volume4/volume4/mv3/strm/series/干净剧 (2025) {tmdbid=456}/Season 01", commands)
        self.assertNotIn("--approve-receive", commands)
        self.assertNotIn("--approve-transfer", commands)

    def test_not_found_with_wrong_season_share_candidate_requires_review(self) -> None:
        plan = build_batch_plan(
            cloud_report={
                "items": [
                    {
                        "status": "cloud_strm_not_found",
                        "title": "怪奇物语",
                        "tmdbid": 66732,
                        "season": 4,
                        "size_bytes": 1000,
                        "expected_count": 9,
                        "source_paths": ["/volume3/hlink/TV/怪奇物语/Season 04"],
                    }
                ],
            },
            transfer_plan={
                "items": [
                    {
                        "title": "怪奇物语",
                        "tmdbid": 66732,
                        "season": 4,
                        "size_bytes": 1000,
                        "expected_count": 9,
                        "source_paths": ["/volume3/hlink/TV/怪奇物语/Season 04"],
                    }
                ],
            },
            share_search_plan={
                "items": [
                    {
                        "title": "怪奇物语",
                        "tmdbid": 66732,
                        "season": 4,
                        "recommended_candidate": {
                            "search_index": 15,
                            "title": "怪奇物语：1985故事集 S01E01-E10",
                            "score": 80,
                            "size_delta_ratio": 0.06,
                            "blockers": [],
                        },
                    }
                ],
            },
        )

        item = plan["items"][0]

        self.assertEqual(item["bucket"], MANUAL_REVIEW)
        self.assertIn("season_mismatch", item["review_reasons"])

    def test_complete_cloud_item_with_blocked_cleanup_preview_requires_review(self) -> None:
        plan = build_batch_plan(
            cloud_report={
                "items": [
                    {
                        "status": "cloud_strm_complete",
                        "title": "兄弟连",
                        "tmdbid": 4613,
                        "season": 1,
                        "size_bytes": 100,
                        "expected_count": 10,
                        "strm_paths_sample": ["/volume4/volume4/mv3/strm/series/兄弟连 (2001) {tmdbid=4613}/Season 01/兄弟连 - S01E01.strm"],
                        "source_paths": ["/volume3/hlink/TV/兄弟连 (2001) {tmdbid=4613}/Season 01"],
                    }
                ],
            },
            cleanup_preview_reports=[
                {
                    "mode": "readonly-mp-cleanup-preview",
                    "ok": False,
                    "ready_for_manual_cleanup_approval": False,
                    "expected_tmdbid": 4613,
                    "expected_season": 1,
                    "blockers": ["no_matching_mp_transfer_history"],
                }
            ],
        )

        item = plan["items"][0]

        self.assertEqual(item["bucket"], MANUAL_REVIEW)
        self.assertIn("cleanup_preview_not_ready", item["review_reasons"])
        self.assertIn("no_matching_mp_transfer_history", item["blockers"])
        self.assertEqual(item["cleanup_preview_ready"], False)

    def test_far_size_candidate_is_manual_review(self) -> None:
        plan = build_batch_plan(
            cloud_report={
                "items": [
                    {
                        "status": "cloud_strm_not_found",
                        "title": "大体积剧 (2023) {tmdbid=789}",
                        "tmdbid": 789,
                        "season": 1,
                        "size_bytes": 100,
                        "expected_count": 12,
                        "source_paths": ["/volume3/volume3/hlink/TV/大体积剧 (2023) {tmdbid=789}"],
                    }
                ]
            },
            transfer_plan={
                "items": [
                    {
                        "title": "大体积剧 (2023) {tmdbid=789}",
                        "tmdbid": 789,
                        "season": 1,
                        "size_bytes": 100,
                        "expected_count": 12,
                        "source_paths": ["/volume3/volume3/hlink/TV/大体积剧 (2023) {tmdbid=789}"],
                    }
                ]
            },
            share_search_plan={
                "items": [
                    {
                        "title": "大体积剧 (2023) {tmdbid=789}",
                        "tmdbid": 789,
                        "season": 1,
                        "recommended_candidate": {
                            "search_index": 1,
                            "score": 90,
                            "size_delta_ratio": 0.9,
                            "blockers": [],
                        },
                    }
                ]
            },
        )

        item = plan["items"][0]

        self.assertEqual(item["bucket"], MANUAL_REVIEW)
        self.assertIn("remote_size_not_similar_enough", item["review_reasons"])

    def test_merges_multiple_share_search_plans_and_keeps_best_duplicate(self) -> None:
        plan = build_batch_plan(
            cloud_report={
                "items": [
                    {
                        "status": "cloud_strm_not_found",
                        "title": "分段剧 (2024) {tmdbid=111}",
                        "tmdbid": 111,
                        "season": 1,
                        "size_bytes": 1000,
                        "expected_count": 8,
                        "source_paths": ["/volume3/hlink/TV/分段剧/Season 01"],
                    },
                    {
                        "status": "cloud_strm_not_found",
                        "title": "另一部 (2024) {tmdbid=222}",
                        "tmdbid": 222,
                        "season": 1,
                        "size_bytes": 2000,
                        "expected_count": 6,
                        "source_paths": ["/volume3/hlink/TV/另一部/Season 01"],
                    },
                ]
            },
            transfer_plan={
                "items": [
                    {
                        "title": "分段剧 (2024) {tmdbid=111}",
                        "tmdbid": 111,
                        "season": 1,
                        "size_bytes": 1000,
                        "expected_count": 8,
                        "source_paths": ["/volume3/hlink/TV/分段剧/Season 01"],
                    },
                    {
                        "title": "另一部 (2024) {tmdbid=222}",
                        "tmdbid": 222,
                        "season": 1,
                        "size_bytes": 2000,
                        "expected_count": 6,
                        "source_paths": ["/volume3/hlink/TV/另一部/Season 01"],
                    },
                ]
            },
            share_search_plans=[
                {
                    "mode": "readonly-mv3-share-search-plan",
                    "items": [
                        {
                            "title": "分段剧 (2024) {tmdbid=111}",
                            "tmdbid": 111,
                            "season": 1,
                            "priority": 1,
                            "recommended_candidate": {
                                "search_index": 1,
                                "search_keyword": "分段剧",
                                "score": 62,
                                "size_delta_ratio": 0.4,
                                "blockers": ["remote_size_not_similar_enough"],
                            },
                        }
                    ],
                },
                {
                    "mode": "readonly-mv3-share-search-plan",
                    "items": [
                        {
                            "title": "分段剧 (2024) {tmdbid=111}",
                            "tmdbid": 111,
                            "season": 1,
                            "priority": 1,
                            "recommended_candidate": {
                                "search_index": 3,
                                "search_keyword": "分段剧 完整",
                                "score": 88,
                                "size_delta_ratio": 0.08,
                                "blockers": [],
                            },
                        },
                        {
                            "title": "另一部 (2024) {tmdbid=222}",
                            "tmdbid": 222,
                            "season": 1,
                            "priority": 2,
                            "recommended_candidate": {
                                "search_index": 2,
                                "search_keyword": "另一部",
                                "score": 85,
                                "size_delta_ratio": 0.1,
                                "blockers": [],
                            },
                        },
                    ],
                },
            ],
        )

        self.assertEqual(plan["settings"]["share_search_plan_count"], 2)
        self.assertEqual(plan["bucket_counts"], {AUTO_TRANSFER: 2})
        first = next(item for item in plan["items"] if item["tmdbid"] == 111)
        self.assertEqual(first["recommended_candidate"]["search_index"], 3)
        self.assertEqual(first["recommended_candidate"]["search_keyword"], "分段剧 完整")
        self.assertEqual(first["merged_duplicate_count"], 2)

    def test_merge_share_search_plans_records_duplicates_on_item(self) -> None:
        merged = merge_share_search_plans(
            [
                {"items": [{"tmdbid": 1, "season": 1, "recommended_candidate": {"score": 10, "blockers": []}}]},
                {"items": [{"tmdbid": 1, "season": 1, "recommended_candidate": {"score": 20, "blockers": []}}]},
            ]
        )

        self.assertIsNotNone(merged)
        self.assertEqual(merged["input_plan_count"], 2)
        self.assertEqual(merged["items"][0]["recommended_candidate"]["score"], 20)
        self.assertEqual(merged["items"][0]["merged_duplicate_count"], 2)

    def test_renders_batch_plan_csv_for_manual_review(self) -> None:
        plan = build_batch_plan(
            cloud_report={
                "items": [
                    {
                        "status": "cloud_strm_not_found",
                        "title": "待复核",
                        "tmdbid": 123,
                        "season": 1,
                        "size_bytes": 100,
                        "expected_count": 2,
                    }
                ]
            }
        )

        rendered = render_batch_plan(plan, "csv")

        self.assertIn("bucket,state,title,tmdbid,season", rendered.splitlines()[0])
        self.assertIn("待复核", rendered)
        self.assertIn("missing_transfer_plan_row", rendered)
        self.assertIn("no_recommended_mv3_share_candidate", rendered)
        self.assertIn("missing_source_paths", rendered)

    def test_manual_review_includes_share_candidate_diagnostics(self) -> None:
        plan = build_batch_plan(
            cloud_report={
                "items": [
                    {
                        "status": "cloud_strm_not_found",
                        "title": "怪奇物语",
                        "tmdbid": 66732,
                        "season": 4,
                        "size_bytes": 1000,
                        "expected_count": 9,
                        "source_paths": ["/volume3/hlink/TV/怪奇物语/Season 04"],
                    }
                ]
            },
            transfer_plan={
                "items": [
                    {
                        "title": "怪奇物语",
                        "tmdbid": 66732,
                        "season": 4,
                        "size_bytes": 1000,
                        "expected_count": 9,
                        "source_paths": ["/volume3/hlink/TV/怪奇物语/Season 04"],
                    }
                ]
            },
            share_search_plan={
                "items": [
                    {
                        "title": "怪奇物语",
                        "tmdbid": 66732,
                        "season": 4,
                        "search_ok": True,
                        "search_result_count": 2,
                        "warnings": ["no_candidate_passed_recommendation_gate"],
                        "recommended_candidate": {},
                        "candidates": [
                            {
                                "search_index": 8,
                                "search_keyword": "怪奇物语 Season 04",
                                "title": "怪奇物语：1985故事集 S01E01-E10",
                                "score": 80,
                                "size_delta_ratio": 0.06,
                                "reasons": ["search_keyword_contains", "size_similar"],
                                "blockers": [],
                            },
                            {
                                "search_index": 9,
                                "search_keyword": "怪奇物语 Season 04",
                                "title": "Stranger Things Season 4 sample",
                                "score": 50,
                                "size_delta_ratio": 0.8,
                                "reasons": ["season_matches"],
                                "blockers": ["title_not_matched", "size_far_from_local"],
                            },
                        ],
                    }
                ]
            },
        )

        item = plan["items"][0]
        diagnostics = item["candidate_diagnostics"]

        self.assertEqual(item["bucket"], MANUAL_REVIEW)
        self.assertEqual(diagnostics["candidate_score_max"], 80)
        self.assertEqual(diagnostics["best_candidate"]["title"], "怪奇物语：1985故事集 S01E01-E10")
        self.assertIn("season_mismatch", diagnostics["best_candidate"]["blockers"])
        self.assertEqual(diagnostics["candidate_blocker_counts"]["season_mismatch"], 1)
        self.assertEqual(diagnostics["candidate_blocker_counts"]["title_not_matched"], 1)
        self.assertEqual(diagnostics["candidate_reason_counts"]["size_similar"], 1)

        rendered = render_batch_plan(plan, "csv")
        header = rendered.splitlines()[0]
        self.assertIn("best_candidate_title", header)
        self.assertIn("candidate_blocker_counts", header)
        self.assertIn("怪奇物语：1985故事集 S01E01-E10", rendered)
        self.assertIn("season_mismatch:1", rendered)
        self.assertIn("no_candidate_passed_recommendation_gate", rendered)

    def test_cli_writes_batch_plan_from_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cloud = tmp_path / "cloud.json"
            share_a = tmp_path / "share-a.json"
            share_b = tmp_path / "share-b.json"
            output = tmp_path / "batch.json"
            cloud.write_text(
                json.dumps(
                    {
                        "mode": "readonly-cloud-check",
                        "items": [
                            {
                                "status": "needs_identity_review",
                                "title": "未知剧",
                                "tmdbid": 0,
                                "season": 0,
                                "size_bytes": 100,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            share_a.write_text(json.dumps({"mode": "readonly-mv3-share-search-plan", "items": []}), encoding="utf-8")
            share_b.write_text(json.dumps({"mode": "readonly-mv3-share-search-plan", "items": []}), encoding="utf-8")
            cleanup_preview = tmp_path / "cleanup-preview.json"
            cleanup_preview.write_text(json.dumps({"expected_tmdbid": 1, "expected_season": 1, "ok": False}), encoding="utf-8")

            exit_code = main(
                [
                    "batch-plan",
                    "--cloud-report",
                    str(cloud),
                    "--share-search-plan",
                    str(share_a),
                    "--share-search-plan",
                    str(share_b),
                    "--cleanup-preview-report",
                    str(cleanup_preview),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["mode"], "readonly-batch-state-plan")
        self.assertEqual(data["settings"]["share_search_plan_count"], 2)
        self.assertEqual(data["settings"]["cleanup_preview_report_count"], 1)
        self.assertEqual(data["items"][0]["bucket"], MANUAL_REVIEW)
