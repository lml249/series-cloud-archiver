import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from series_cloud_archiver.cli import main
from series_cloud_archiver.transfer_wrong_root_remediation import (
    build_transfer_wrong_root_repair_plan,
    render_transfer_wrong_root_repair_plan,
    run_transfer_wrong_root_repair_plan,
)


class TransferWrongRootRemediationTest(unittest.TestCase):
    def test_plan_selects_only_unrecognized_transfer_failures(self) -> None:
        report = build_transfer_wrong_root_repair_plan(self._review_report(), env_file="/safe/.env")

        self.assertEqual(report["planned_items"], 1)
        self.assertEqual(report["ready_items"], 1)
        self.assertEqual(report["skipped_non_matching_items"], 2)
        row = report["items"][0]
        self.assertEqual(row["status"], "ready_for_wrong_root_repair")
        self.assertEqual(row["title"], "法证先锋 (2008) {tmdbid=286997}")
        self.assertEqual(row["wrong_cloud_season_path"], "/已整理/未识别/法证先锋 (2008) {tmdbid=286997}/Season 2")
        self.assertEqual(row["correct_cloud_season_path"], "/已整理/series/法证先锋 (2008) {tmdbid=286997}/Season 02")
        self.assertEqual(row["source_strm_season_root"], "/host/mv3/strm/未识别/法证先锋 (2008) {tmdbid=286997}/Season 2")
        self.assertEqual(row["target_strm_season_root"], "/host/mv3/strm/series/法证先锋 (2008) {tmdbid=286997}/Season 02")
        commands = "\n".join(str(command["command"]) for command in row["commands"])
        self.assertIn("mv3-repair-wrong-root-direct-season-pair", commands)
        self.assertIn("strm-root-relocate", commands)
        self.assertNotIn("--approve-repair", commands)
        self.assertNotIn("--approve-move", commands)
        self.assertIn("ready_for_wrong_root_repair", render_transfer_wrong_root_repair_plan(report, "csv"))

    def test_plan_blocks_ambiguous_paths(self) -> None:
        review = self._review_report()
        review["items"][0]["cloud_media_path"] = "/已整理/series/法证先锋 (2008) {tmdbid=286997}/Season 2"

        report = build_transfer_wrong_root_repair_plan(review, env_file="/safe/.env")
        row = report["items"][0]

        self.assertEqual(row["status"], "manual_review_required")
        self.assertIn("wrong_cloud_root_not_under_unrecognized_category", row["blockers"])
        self.assertEqual(row["commands"], [])

    def test_run_default_only_plans_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_transfer_wrong_root_repair_plan(self._review_report(), env_file="/safe/.env")
            run = run_transfer_wrong_root_repair_plan(
                plan,
                output_dir=str(Path(tmp) / "reports"),
                command_runner=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not execute")),
            )

        self.assertTrue(run["ok"])
        self.assertEqual(run["planned_commands"], 2)
        self.assertEqual(run["executed_commands"], 0)
        self.assertEqual(run["status_counts"], {"planned": 2})

    def test_run_execute_dry_run_only_runs_cloud_pair_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_transfer_wrong_root_repair_plan(self._review_report(), env_file="/safe/.env")
            calls = []

            def fake_runner(argv, **kwargs):
                calls.append(argv)
                output_path = Path(argv[argv.index("--output") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps({"mode": "mv3-wrong-root-direct-season-pair-repair", "ok": True, "dry_run": True}),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

            run = run_transfer_wrong_root_repair_plan(
                plan,
                output_dir=str(Path(tmp) / "reports"),
                execute_dry_run=True,
                cwd="/example/app",
                command_runner=fake_runner,
            )

        self.assertTrue(run["ok"])
        self.assertEqual(run["planned_commands"], 2)
        self.assertEqual(run["executed_commands"], 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("mv3-repair-wrong-root-direct-season-pair", calls[0])
        self.assertNotIn("--approve-repair", calls[0])
        self.assertTrue(any(item["status"] == "deferred" for item in run["items"]))

    def test_run_execute_approved_sequences_pair_then_relocate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_transfer_wrong_root_repair_plan(self._review_report(), env_file="/safe/.env")
            calls = []

            def fake_runner(argv, **kwargs):
                calls.append(argv)
                output_path = Path(argv[argv.index("--output") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                subcommand = argv[3]
                approved = "--approve-repair" in argv or "--approve-move" in argv
                payload = {"mode": subcommand, "ok": True, "dry_run": not approved}
                if subcommand == "mv3-repair-wrong-root-direct-season-pair":
                    payload["write_executed"] = approved
                    payload["post_verify"] = {"strm": {"wrong_target_count": 0, "correct_target_count": 30}}
                if subcommand == "strm-root-relocate":
                    payload["move_executed"] = approved
                    payload["post_verify"] = {"target": {"file_count": 30, "verify": {"ok": True}}}
                output_path.write_text(json.dumps(payload), encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

            run = run_transfer_wrong_root_repair_plan(
                plan,
                output_dir=str(Path(tmp) / "reports"),
                execute_approved=True,
                cwd="/example/app",
                command_runner=fake_runner,
            )

        self.assertTrue(run["ok"])
        self.assertEqual(run["executed_commands"], 3)
        self.assertEqual([call[3] for call in calls], [
            "mv3-repair-wrong-root-direct-season-pair",
            "strm-root-relocate",
            "strm-root-relocate",
        ])
        self.assertIn("--approve-repair", calls[0])
        self.assertNotIn("--approve-move", calls[1])
        self.assertIn("--approve-move", calls[2])

    def test_run_execute_approved_skips_relocate_when_pair_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = build_transfer_wrong_root_repair_plan(self._review_report(), env_file="/safe/.env")
            calls = []

            def fake_runner(argv, **kwargs):
                calls.append(argv)
                output_path = Path(argv[argv.index("--output") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps({"mode": "mv3-wrong-root-direct-season-pair-repair", "ok": False, "blockers": ["wrong_media_count_mismatch"]}),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")

            run = run_transfer_wrong_root_repair_plan(
                plan,
                output_dir=str(Path(tmp) / "reports"),
                execute_approved=True,
                command_runner=fake_runner,
            )

        self.assertFalse(run["ok"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(item["status"] == "dependency_skipped" for item in run["items"]))

    def test_cli_writes_plan_and_run_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            review_path = tmp_path / "review.json"
            plan_path = tmp_path / "plan.json"
            run_path = tmp_path / "run.json"
            review_path.write_text(json.dumps(self._review_report(), ensure_ascii=False), encoding="utf-8")

            plan_code = main(
                [
                    "mv3-transfer-wrong-root-repair-plan",
                    "--review-report",
                    str(review_path),
                    "--env-file",
                    "/safe/.env",
                    "--format",
                    "json",
                    "--output",
                    str(plan_path),
                ]
            )
            run_code = main(
                [
                    "mv3-transfer-wrong-root-repair-run",
                    "--plan",
                    str(plan_path),
                    "--output-dir",
                    str(tmp_path / "diagnostics"),
                    "--format",
                    "json",
                    "--output",
                    str(run_path),
                ]
            )
            plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
            run_payload = json.loads(run_path.read_text(encoding="utf-8"))

        self.assertEqual(plan_code, 0)
        self.assertEqual(run_code, 0)
        self.assertEqual(plan_payload["mode"], "readonly-mv3-transfer-wrong-root-repair-plan")
        self.assertEqual(run_payload["mode"], "mv3-transfer-wrong-root-repair-run")
        self.assertEqual(run_payload["executed_commands"], 0)

    def _review_report(self) -> dict:
        return {
            "mode": "readonly-batch-human-review-report",
            "items": [
                {
                    "decision": "manual_review_transfer_failed",
                    "title": "法证先锋 (2006) {tmdbid=286997} Season 02",
                    "tmdbid": 286997,
                    "season": 2,
                    "expected_episode_count": 30,
                    "expected_episodes": "1-30 (30集)",
                    "reason_summary": "review_decision_blocked:manual_review_transfer_failed; strm_written_to_unrecognized_root",
                    "review_reasons": "strm_written_to_unrecognized_root",
                    "blockers": "strm_written_to_unrecognized_root",
                    "cloud_media_path": "/已整理/未识别/法证先锋 (2008) {tmdbid=286997}/Season 2",
                    "strm_root": "/host/mv3/strm/未识别/法证先锋 (2008) {tmdbid=286997}/Season 2",
                    "source_paths": "/volume3/hlink/TV/法证先锋/Season 02",
                },
                {
                    "decision": "manual_review_transfer_failed",
                    "title": "怪奇物语 (2016) {tmdbid=66732} Season 03",
                    "tmdbid": 66732,
                    "season": 3,
                    "expected_episode_count": 8,
                    "reason_summary": "no_recommended_mv3_share_candidate",
                    "cloud_media_path": "/已整理/series/怪奇物语 (2016) {tmdbid=66732}/Season 03",
                    "strm_root": "",
                },
                {
                    "decision": "done_cleanup_verified",
                    "title": "南部档案",
                    "tmdbid": 278605,
                    "season": 1,
                },
            ],
        }


if __name__ == "__main__":
    unittest.main()
