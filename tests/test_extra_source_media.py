import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from series_cloud_archiver.cli import main
from series_cloud_archiver.extra_source_media import (
    build_extra_source_media_local_path_summary,
    build_extra_source_media_summary,
    build_extra_source_media_plan,
    render_extra_source_media_plan,
    render_extra_source_media_run,
    render_extra_source_media_summary,
    run_extra_source_media_plan,
)


class ExtraSourceMediaPlanTest(unittest.TestCase):
    def _finalize_report(self) -> dict:
        return {
            "mode": "batch-finalize-run",
            "items": [
                {
                    "status": "failed_cleanup_preview",
                    "title": "兄弟连 (2001) {tmdbid=4613} Season 01",
                    "tmdbid": 4613,
                    "season": 1,
                    "blockers": ["source_root_check_failed"],
                    "cleanup_unlinked_video_sample": [
                        "/volume-example/source-tv/兄弟连/Band.of.Brothers.SP1.We.Stand.Alone.mkv",
                        "/volume-example/source-tv/兄弟连/Band.of.Brothers.SP2.The.Making.mkv",
                    ],
                    "cleanup_blocked_source_roots": [
                        {
                            "path": "/volume-example/source-tv/兄弟连",
                            "video_count": 12,
                            "linked_hlink_video_count": 10,
                            "unlinked_video_sample": [
                                "/volume-example/source-tv/兄弟连/Band.of.Brothers.SP1.We.Stand.Alone.mkv",
                            ],
                        }
                    ],
                }
            ]
            + [
                {
                    "status": "failed_cleanup_preview",
                    "title": "怪奇物语",
                    "tmdbid": 66732,
                    "season": 5,
                    "blockers": ["source_root_check_failed"],
                    "cleanup_unlinked_video_sample": [
                        "/volume-example/source-tv/怪奇物语/Stranger.Things.S01E01.mkv",
                    ],
                }
            ],
        }

    def test_plan_promotes_unlinked_specials_to_readonly_mv3_scan_commands(self) -> None:
        report = build_extra_source_media_plan(
            self._finalize_report(),
            env_file="/safe/.env",
            target_dir="/已整理",
            strm_dir="/strm",
        )

        self.assertEqual(report["planned_items"], 3)
        self.assertEqual(report["ready_for_mv3_scan_items"], 3)
        first = report["items"][0]
        self.assertEqual(first["suggested_season"], 0)
        self.assertEqual(first["media_kind"], "special")
        self.assertIn("mv3-organize-scan-source", first["commands"][0]["command"])
        self.assertIn("--local-source --file", first["commands"][0]["command"])
        self.assertEqual(first["commands"][1]["stage"], "confirmed_local_mapping_required")
        self.assertIn("mv3-organize-transfer-from-local-map", first["commands"][1]["command"])
        self.assertFalse(first["commands"][1]["command"].startswith("PYTHONPATH=src"))
        rendered = render_extra_source_media_plan(report, "csv")
        self.assertIn("Band.of.Brothers.SP2.The.Making.mkv", rendered)

    def test_plan_can_filter_one_finalize_item(self) -> None:
        report = build_extra_source_media_plan(
            self._finalize_report(),
            title="兄弟连 (2001) {tmdbid=4613} Season 01",
            tmdbid=4613,
            season=1,
        )

        self.assertEqual(report["planned_items"], 2)
        self.assertTrue(all(item["tmdbid"] == 4613 for item in report["items"]))
        self.assertEqual(report["settings"]["tmdbid"], 4613)
        rendered = render_extra_source_media_plan(report, "csv")
        self.assertNotIn("Stranger.Things", rendered)

    def test_cli_writes_extra_source_media_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            finalize = tmp_path / "finalize.json"
            output = tmp_path / "extra.json"
            finalize.write_text(json.dumps(self._finalize_report(), ensure_ascii=False), encoding="utf-8")

            exit_code = main(
                [
                    "extra-source-media-plan",
                    "--finalize-run-report",
                    str(finalize),
                    "--env-file",
                    "/safe/.env",
                    "--title",
                    "兄弟连 (2001) {tmdbid=4613} Season 01",
                    "--tmdbid",
                    "4613",
                    "--season",
                    "1",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "readonly-extra-source-media-plan")
        self.assertEqual(payload["planned_items"], 2)
        self.assertEqual(payload["settings"]["season"], 1)

    def test_run_defaults_to_dry_run_and_skips_transfer_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "scan"
            plan = build_extra_source_media_plan(
                self._finalize_report(),
                title="兄弟连 (2001) {tmdbid=4613} Season 01",
                tmdbid=4613,
                season=1,
            )
            calls = []

            run = run_extra_source_media_plan(
                plan,
                output_dir=str(output_dir),
                execute_readonly=False,
                command_runner=lambda *args, **kwargs: calls.append((args, kwargs)),
            )

        self.assertTrue(run["ok"])
        self.assertEqual(run["selected_items"], 2)
        self.assertEqual(run["planned_commands"], 4)
        self.assertEqual(run["executed_commands"], 0)
        self.assertEqual(run["status_counts"], {"planned": 2, "skipped": 2})
        self.assertEqual(calls, [])
        self.assertTrue(all("--approve-transfer" not in item["command"] for item in run["items"] if item["status"] != "skipped"))

    def test_run_executes_only_mv3_scan_source_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "scan"
            plan = build_extra_source_media_plan(
                self._finalize_report(),
                env_file="/safe/.env",
                title="兄弟连 (2001) {tmdbid=4613} Season 01",
                tmdbid=4613,
                season=1,
            )
            calls = []

            def fake_runner(argv, **kwargs):
                calls.append((argv, kwargs))
                output_path = Path(argv[argv.index("--output") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(
                        {
                            "mode": "readonly-mv3-organize-scan-source",
                            "ok": True,
                            "summary": {"total": 1, "candidate": 1, "in_library": 0, "episode_count": 1},
                            "warnings": ["single_file_scan"],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

            run = run_extra_source_media_plan(
                plan,
                output_dir=str(output_dir),
                execute_readonly=True,
                cwd="/example/app",
                command_runner=fake_runner,
            )

        self.assertTrue(run["ok"])
        self.assertEqual(run["planned_commands"], 4)
        self.assertEqual(run["executed_commands"], 2)
        self.assertEqual(run["status_counts"], {"executed": 2, "skipped": 2})
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[0][:4] == ["python3", "-m", "series_cloud_archiver", "mv3-organize-scan-source"] for call in calls))
        self.assertTrue(all(str(output_dir) in item["command"] for item in run["items"] if item["stage"] == "mv3_organize_scan_source"))
        self.assertEqual(run["items"][0]["diagnostic_summary"]["candidate"], 1)
        self.assertIn("readonly-extra-source-media-run", render_extra_source_media_run(run, "json"))

    def test_cli_writes_extra_source_media_run_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_path = tmp_path / "extra-plan.json"
            output = tmp_path / "extra-run.json"
            plan_path.write_text(
                json.dumps(
                    build_extra_source_media_plan(
                        self._finalize_report(),
                        title="兄弟连 (2001) {tmdbid=4613} Season 01",
                        tmdbid=4613,
                        season=1,
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "extra-source-media-run",
                    "--plan",
                    str(plan_path),
                    "--output-dir",
                    str(tmp_path / "scan"),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "readonly-extra-source-media-run")
        self.assertEqual(payload["planned_commands"], 4)
        self.assertEqual(payload["executed_commands"], 0)

    def test_summary_blocks_empty_scan_source_results(self) -> None:
        run = {
            "mode": "readonly-extra-source-media-run",
            "selected_items": 1,
            "executed_commands": 1,
            "output_dir": "/example/output",
            "items": [
                {
                    "status": "executed",
                    "executed": True,
                    "title": "9号秘事",
                    "tmdbid": 61746,
                    "main_season": 1,
                    "suggested_season": 3,
                    "episode": 1,
                    "diagnostic_ok": True,
                    "diagnostic_summary": {"total": 0, "candidate": 0, "in_library": 0},
                    "diagnostic_warnings": ["no_scan_items_found"],
                }
            ],
        }

        summary = build_extra_source_media_summary([run])

        self.assertEqual(summary["blocked_items"], 1)
        self.assertEqual(summary["items"][0]["status"], "source_not_visible_to_mv3_or_empty")
        self.assertEqual(summary["items"][0]["cleanup_gate"], "blocked")
        self.assertIn("不能作为已清理证据", render_extra_source_media_summary(summary, "markdown"))

    def test_local_path_summary_marks_existing_empty_scan_as_mapping_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Demo.S01E01.mkv"
            source.write_text("video", encoding="utf-8")
            run = {
                "mode": "readonly-extra-source-media-run",
                "selected_items": 1,
                "executed_commands": 1,
                "items": [
                    {
                        "status": "executed",
                        "executed": True,
                        "title": "示例剧",
                        "tmdbid": 123,
                        "main_season": 1,
                        "suggested_season": 1,
                        "episode": 1,
                        "source_path": str(source),
                        "diagnostic_ok": True,
                        "diagnostic_summary": {"total": 0, "candidate": 0, "in_library": 0},
                        "diagnostic_warnings": ["no_scan_items_found"],
                    }
                ],
            }

            summary = build_extra_source_media_local_path_summary([run])

        self.assertEqual(summary["mode"], "readonly-extra-source-media-local-path-summary")
        self.assertEqual(summary["items"][0]["status"], "local_source_exists_but_mv3_scan_empty")
        self.assertEqual(summary["items"][0]["cleanup_gate"], "blocked")
        self.assertEqual(summary["items"][0]["local_path_existing_count"], 1)
        self.assertIn("local_source_exists_but_mv3_scan_empty", render_extra_source_media_summary(summary, "csv"))

    def test_local_path_summary_detects_cross_season_extra_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Demo.S03E01.mkv"
            source.write_text("video", encoding="utf-8")
            run = {
                "mode": "readonly-extra-source-media-run",
                "selected_items": 1,
                "executed_commands": 1,
                "items": [
                    {
                        "status": "executed",
                        "executed": True,
                        "title": "示例剧",
                        "tmdbid": 123,
                        "main_season": 1,
                        "suggested_season": 3,
                        "episode": 1,
                        "source_path": str(source),
                        "diagnostic_summary": {"total": 0, "candidate": 0, "in_library": 0},
                        "diagnostic_warnings": ["no_scan_items_found"],
                    }
                ],
            }

            summary = build_extra_source_media_local_path_summary([run])

        self.assertEqual(summary["items"][0]["status"], "extra_source_belongs_to_other_season")
        self.assertEqual(summary["items"][0]["cleanup_gate"], "blocked")
        self.assertEqual(summary["items"][0]["cross_season_item_count"], 1)
        self.assertIn("其它 season", summary["items"][0]["next_action"])

    def test_summary_clears_when_all_scan_candidates_are_in_library(self) -> None:
        run = {
            "mode": "readonly-extra-source-media-run",
            "selected_items": 1,
            "executed_commands": 1,
            "items": [
                {
                    "status": "executed",
                    "executed": True,
                    "title": "示例剧",
                    "tmdbid": 123,
                    "main_season": 1,
                    "suggested_season": 1,
                    "episode": 1,
                    "diagnostic_ok": True,
                    "diagnostic_summary": {"total": 1, "candidate": 1, "in_library": 1},
                    "diagnostic_warnings": ["all_scan_items_marked_in_library"],
                }
            ],
        }

        summary = build_extra_source_media_summary([run])

        self.assertEqual(summary["clear_items"], 1)
        self.assertEqual(summary["items"][0]["status"], "extra_source_already_in_library")
        self.assertEqual(summary["items"][0]["cleanup_gate"], "clear")
        self.assertIn("extra_source_already_in_library", render_extra_source_media_summary(summary, "csv"))

    def test_cli_writes_extra_source_media_summary_from_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_dir = tmp_path / "runs"
            run_dir.mkdir()
            source = tmp_path / "Demo.S02E03.mkv"
            source.write_text("video", encoding="utf-8")
            output = tmp_path / "summary.json"
            (run_dir / "one.run.json").write_text(
                json.dumps(
                    {
                        "mode": "readonly-extra-source-media-run",
                        "selected_items": 1,
                        "executed_commands": 1,
                        "items": [
                            {
                                "status": "executed",
                                "executed": True,
                                "title": "示例剧",
                                "tmdbid": 123,
                                "main_season": 1,
                                "suggested_season": 2,
                                "episode": 3,
                                "source_path": str(source),
                                "diagnostic_summary": {"total": 0, "candidate": 0, "in_library": 0},
                                "diagnostic_warnings": ["no_scan_items_found"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "extra-source-media-summary",
                    "--run-dir",
                    str(run_dir),
                    "--check-local-paths",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "readonly-extra-source-media-local-path-summary")
        self.assertEqual(payload["items"][0]["status"], "extra_source_belongs_to_other_season")
        self.assertEqual(payload["items"][0]["suggested_seasons"], "2")
        self.assertEqual(payload["items"][0]["episodes"], "3")


if __name__ == "__main__":
    unittest.main()
