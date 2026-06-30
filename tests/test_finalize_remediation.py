import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional

from series_cloud_archiver.cli import main
from series_cloud_archiver.finalize_remediation import (
    build_finalize_remediation_plan,
    render_finalize_remediation_plan,
    render_finalize_remediation_run,
    run_finalize_remediation_plan,
)


class FinalizeRemediationPlanTest(unittest.TestCase):
    def _review_report(self) -> dict:
        return {
            "mode": "readonly-batch-review-report",
            "items": [
                self._review_item("罚罪2", 301001, 1, "failed_strm_verify", "strm_missing_expected"),
                self._review_item("庆余年", 123456, 2, "failed_cloud_duplicate_preview", "cloud_duplicate_delete_approval_required"),
                self._review_item("云盘缺季", 301002, 1, "failed_cloud_check", "cloud_season_path_not_found"),
                self._review_item("兄弟连", 4613, 1, "failed_cleanup_preview", "source_root_check_failed"),
                self._review_item("MP残留", 301003, 1, "failed_cleanup_preview", "mp_transfer_history_still_present_use_mp_cleanup; qb_torrent_not_found"),
                {
                    "decision": "done_already_cleaned_noop",
                    "title": "已完成",
                    "tmdbid": 301004,
                    "season": 1,
                },
            ],
        }

    def _review_item(self, title: str, tmdbid: int, season: int, finalize_status: str, blockers: str) -> dict:
        return {
            "decision": "blocked_after_finalize_gates",
            "title": title,
            "tmdbid": tmdbid,
            "season": season,
            "expected_episode_count": 10,
            "expected_episodes": "1-10",
            "finalize_status": finalize_status,
            "finalize_blockers": blockers,
            "cloud_media_path": f"/已整理/series/{title} {{tmdbid={tmdbid}}}/Season {season:02d}",
            "strm_root": f"/example/host/strm/series/{title} {{tmdbid={tmdbid}}}/Season {season:02d}",
            "source_paths": f"/example/source-tv/{title}/Season {season:02d}",
        }

    def _finalize_report(self) -> dict:
        return {
            "mode": "batch-finalize-run",
            "items": [
                self._finalize_item("罚罪2", 301001, 1, "failed_strm_verify", ["strm_missing_expected"]),
                self._finalize_item("庆余年", 123456, 2, "failed_cloud_duplicate_preview", ["cloud_duplicate_delete_approval_required"]),
                self._finalize_item("云盘缺季", 301002, 1, "failed_cloud_check", ["cloud_season_path_not_found"]),
                self._finalize_item("兄弟连", 4613, 1, "failed_cleanup_preview", ["source_root_check_failed"]),
                self._finalize_item(
                    "MP残留",
                    301003,
                    1,
                    "failed_cleanup_preview",
                    ["mp_transfer_history_still_present_use_mp_cleanup", "qb_torrent_not_found"],
                    source_qb_hashes=["abcdef1234567890"],
                ),
            ],
        }

    def _finalize_item(
        self,
        title: str,
        tmdbid: int,
        season: int,
        status: str,
        blockers: List[str],
        source_qb_hashes: Optional[List[str]] = None,
    ) -> dict:
        return {
            "title": title,
            "tmdbid": tmdbid,
            "season": season,
            "status": status,
            "blockers": blockers,
            "expected_episode_count": 10,
            "expected_episodes": list(range(1, 11)),
            "strm_root": f"/example/host/strm/series/{title} {{tmdbid={tmdbid}}}/Season {season:02d}",
            "cloud_season_path": f"/已整理/series/{title} {{tmdbid={tmdbid}}}/Season {season:02d}",
            "hlink_root": f"/example/hlink-tv/{title}/Season {season:02d}",
            "source_paths": [f"/example/source-tv/{title}/Season {season:02d}"],
            "source_qb_hashes": source_qb_hashes or [],
            "stages": [{"stage": "strm_verify", "output": f"{title}-strm.json"}],
        }

    def test_plan_groups_finalize_blockers_into_readonly_remediation_categories(self) -> None:
        report = build_finalize_remediation_plan(
            self._review_report(),
            [self._finalize_report()],
            env_file="/safe/.env",
            cloud_media_storage="115-default",
        )

        self.assertEqual(report["planned_items"], 5)
        categories = {item["title"]: item["category"] for item in report["items"]}
        self.assertEqual(categories["罚罪2"], "strm_mismatch")
        self.assertEqual(categories["庆余年"], "cloud_duplicate_delete_review")
        self.assertEqual(categories["云盘缺季"], "cloud_path_missing")
        self.assertEqual(categories["兄弟连"], "extra_source_media")
        self.assertEqual(categories["MP残留"], "mp_history_or_qb_mismatch")

        commands_by_title = {
            item["title"]: "\n".join(str(command.get("command", "")) for command in item["commands"])
            for item in report["items"]
        }
        self.assertIn("strm-verify", commands_by_title["罚罪2"])
        self.assertIn("mv3-cloud-search", commands_by_title["云盘缺季"])
        self.assertIn("extra-source-media-plan", commands_by_title["兄弟连"])
        self.assertIn("qb-orphan-torrent-cleanup-preview", commands_by_title["MP残留"])
        self.assertIn("mp-cleanup-preview", commands_by_title["MP残留"])
        self.assertNotIn("--approve-delete", commands_by_title["庆余年"])

        rendered_csv = render_finalize_remediation_plan(report, "csv")
        self.assertIn("cloud_duplicate_delete_review", rendered_csv)
        self.assertIn("readonly-finalize-remediation-plan", render_finalize_remediation_plan(report, "json"))

    def test_cli_writes_finalize_remediation_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            review = tmp_path / "review.json"
            finalize = tmp_path / "finalize.json"
            output = tmp_path / "remediation.json"
            review.write_text(json.dumps(self._review_report(), ensure_ascii=False), encoding="utf-8")
            finalize.write_text(json.dumps(self._finalize_report(), ensure_ascii=False), encoding="utf-8")

            exit_code = main(
                [
                    "finalize-remediation-plan",
                    "--review-report",
                    str(review),
                    "--finalize-run-report",
                    str(finalize),
                    "--env-file",
                    "/safe/.env",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "readonly-finalize-remediation-plan")
        self.assertEqual(payload["planned_items"], 5)

    def test_run_defaults_to_dry_run_and_rewrites_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "diagnostics"
            calls = []

            def fake_runner(*args, **kwargs):
                calls.append((args, kwargs))
                raise AssertionError("dry-run must not execute")

            run = run_finalize_remediation_plan(
                self._plan_report(),
                output_dir=str(output_dir),
                categories=["strm_mismatch"],
                execute_readonly=False,
                command_runner=fake_runner,
            )

        self.assertTrue(run["ok"])
        self.assertEqual(run["planned_commands"], 2)
        self.assertEqual(run["executed_commands"], 0)
        self.assertEqual(calls, [])
        for item in run["items"]:
            self.assertIn(str(output_dir), item["command"])
            self.assertNotIn("--approve-delete", item["command"])

    def test_run_executes_allowlisted_readonly_command_and_loads_diagnostic_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "diagnostics"
            calls = []

            def fake_runner(argv, **kwargs):
                calls.append((argv, kwargs))
                output_path = Path(argv[argv.index("--output") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(
                        {
                            "mode": "strm-verify",
                            "ok": False,
                            "blockers": ["strm_episode_count_mismatch"],
                            "warnings": ["strm_duplicate_episode_files"],
                            "strm": {"combined": {"episode_count": 1, "episodes": [1], "missing_in_range": []}},
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 1, stdout="checked", stderr="")

            run = run_finalize_remediation_plan(
                self._plan_report(),
                output_dir=str(output_dir),
                categories=["strm_mismatch"],
                stages=["strm_verify_readonly"],
                execute_readonly=True,
                cwd="/example/app",
                command_runner=fake_runner,
            )

        self.assertTrue(run["ok"])
        self.assertEqual(run["planned_commands"], 1)
        self.assertEqual(run["executed_commands"], 1)
        self.assertEqual(run["items"][0]["status"], "diagnostic_failed")
        self.assertFalse(run["items"][0]["diagnostic_ok"])
        self.assertEqual(run["items"][0]["diagnostic_blockers"], ["strm_episode_count_mismatch"])
        self.assertEqual(calls[0][0][:3], ["python3", "-m", "series_cloud_archiver"])
        self.assertEqual(calls[0][1]["cwd"], "/example/app")
        self.assertEqual(calls[0][1]["env"]["PYTHONPATH"], "/example/app/src")
        rendered = render_finalize_remediation_run(run, "csv")
        self.assertIn("strm_episode_count_mismatch", rendered)

    def test_run_blocks_approval_flags_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan_report()
            plan["items"][0]["commands"][0]["command"] += " --approve-delete"

            run = run_finalize_remediation_plan(
                plan,
                output_dir=str(Path(tmp) / "output"),
                categories=["strm_mismatch"],
                execute_readonly=True,
                command_runner=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not execute")),
            )

        self.assertFalse(run["ok"])
        self.assertEqual(run["unsafe_blocked_count"], 1)
        blocked = [item for item in run["items"] if item["status"] == "unsafe_blocked"][0]
        self.assertIn("approval_flag_forbidden", blocked["safety_blockers"])

    def test_run_skips_non_executable_notes_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = run_finalize_remediation_plan(
                self._plan_report(),
                output_dir=str(Path(tmp) / "output"),
                categories=["cloud_duplicate_delete_review"],
                execute_readonly=True,
                command_runner=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, stdout="", stderr=""),
            )

        self.assertTrue(run["ok"])
        self.assertEqual(run["status_counts"]["skipped"], 1)

    def test_cli_writes_finalize_remediation_run_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "plan.json"
            output = tmp_path / "run.json"
            plan.write_text(json.dumps(self._plan_report(), ensure_ascii=False), encoding="utf-8")

            exit_code = main(
                [
                    "finalize-remediation-run",
                    "--plan",
                    str(plan),
                    "--output-dir",
                    str(tmp_path / "diagnostics"),
                    "--category",
                    "strm_mismatch",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "readonly-finalize-remediation-run")
        self.assertEqual(payload["planned_commands"], 2)
        self.assertEqual(payload["executed_commands"], 0)

    def _plan_report(self) -> dict:
        return build_finalize_remediation_plan(
            self._review_report(),
            [self._finalize_report()],
            env_file="/safe/.env",
            cloud_media_storage="115-default",
        )


if __name__ == "__main__":
    unittest.main()
