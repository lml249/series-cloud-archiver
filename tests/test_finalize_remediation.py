import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional

from series_cloud_archiver.cli import main
from series_cloud_archiver.finalize_remediation import (
    build_finalize_cleanup_remediation_plan,
    build_finalize_expected_update_plan,
    build_finalize_remediation_plan,
    render_finalize_cleanup_remediation_plan,
    render_finalize_expected_update_plan,
    render_finalize_remediation_plan,
    render_finalize_remediation_run,
    run_finalize_cleanup_remediation_plan,
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
        self.assertIn("缺少原始 finalize-run report 路径", commands_by_title["兄弟连"])
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
        brother = [item for item in payload["items"] if item["title"] == "兄弟连"][0]
        self.assertIn("extra-source-media-plan", brother["commands"][0]["command"])
        self.assertIn(str(finalize), brother["commands"][0]["command"])

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

    def test_run_executes_extra_source_media_plan_readonly_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            finalize_path = tmp_path / "finalize.json"
            output_dir = tmp_path / "diagnostics"
            finalize_report = self._finalize_report()
            finalize_report["_source_path"] = str(finalize_path)
            finalize_path.write_text(json.dumps(finalize_report, ensure_ascii=False), encoding="utf-8")
            plan = build_finalize_remediation_plan(
                self._review_report(),
                [finalize_report],
                env_file="/safe/.env",
                cloud_media_storage="115-default",
            )
            calls = []

            def fake_runner(argv, **kwargs):
                calls.append((argv, kwargs))
                output_path = Path(argv[argv.index("--output") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(
                        {
                            "mode": "readonly-extra-source-media-plan",
                            "ok": True,
                            "planned_items": 1,
                            "status_counts": {"ready_for_mv3_scan": 1},
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

            run = run_finalize_remediation_plan(
                plan,
                output_dir=str(output_dir),
                categories=["extra_source_media"],
                execute_readonly=True,
                cwd="/example/app",
                command_runner=fake_runner,
            )

        self.assertTrue(run["ok"])
        self.assertEqual(run["planned_commands"], 1)
        self.assertEqual(run["executed_commands"], 1)
        self.assertEqual(run["items"][0]["status"], "executed")
        self.assertEqual(calls[0][0][:4], ["python3", "-m", "series_cloud_archiver", "extra-source-media-plan"])
        self.assertIn(str(finalize_path), calls[0][0])

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

    def test_expected_update_plan_promotes_contiguous_strm_cloud_evidence(self) -> None:
        plan = self._plan_report()
        strm_report = {
            "mode": "strm-verify",
            "title": "罚罪2",
            "ok": False,
            "expected": {
                "episode_count": 10,
                "episode_min": 1,
                "episode_max": 10,
            },
            "strm": {
                "roots": [
                    {
                        "path": "/example/host/strm/series/罚罪2 {tmdbid=301001}/Season 01",
                        "episode_count": 12,
                        "episodes": list(range(1, 13)),
                        "missing_in_range": [],
                        "duplicate_episodes": [],
                        "target_prefix_mismatch_count": 0,
                        "forbidden_target_count": 0,
                    }
                ],
                "combined": {
                    "episode_count": 12,
                    "episode_min": 1,
                    "episode_max": 12,
                    "missing_in_range": [],
                    "episodes": list(range(1, 13)),
                },
            },
            "blockers": ["strm_episode_count_mismatch"],
        }
        cloud_report = {
            "mode": "mv3-cloud-duplicate-video-cleanup-result",
            "season_path": "/已整理/series/罚罪2 {tmdbid=301001}/Season 01",
            "strm_root": "/example/host/strm/series/罚罪2 {tmdbid=301001}/Season 01",
            "summary": {
                "episode_count": 12,
                "episodes": list(range(1, 13)),
                "missing_in_range": [],
                "duplicate_episodes": [],
                "protected_strm_target_count": 12,
                "strm_file_count": 12,
            },
            "delete_plan": {"duplicate_video_count": 0},
        }

        report = build_finalize_expected_update_plan(plan, [strm_report, cloud_report])
        ready = [item for item in report["items"] if item["title"] == "罚罪2"][0]

        self.assertEqual(report["ready_items"], 1)
        self.assertEqual(ready["status"], "ready_for_expected_update")
        self.assertEqual(ready["new_expected_episode_count"], 12)
        self.assertEqual(ready["new_expected_episodes"], list(range(1, 13)))
        self.assertEqual(ready["identity_override"]["expected_episodes"], list(range(1, 13)))
        self.assertIn("ready_for_expected_update", render_finalize_expected_update_plan(report, "csv"))

    def test_expected_update_plan_requires_cloud_evidence(self) -> None:
        plan = self._plan_report()
        strm_report = {
            "mode": "strm-verify",
            "title": "罚罪2",
            "strm": {
                "roots": [{"episode_count": 12, "episodes": list(range(1, 13))}],
                "combined": {"episode_count": 12, "episodes": list(range(1, 13))},
            },
        }

        report = build_finalize_expected_update_plan(plan, [strm_report])
        row = [item for item in report["items"] if item["title"] == "罚罪2"][0]

        self.assertEqual(row["status"], "manual_review_required")
        self.assertIn("cloud_diagnostic_missing", row["blockers"])

    def test_cli_writes_finalize_expected_update_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan_path = tmp_path / "plan.json"
            diagnostics = tmp_path / "diagnostics"
            diagnostics.mkdir()
            output = tmp_path / "expected.json"
            plan_path.write_text(json.dumps(self._plan_report(), ensure_ascii=False), encoding="utf-8")
            (diagnostics / "strm.json").write_text(
                json.dumps(
                    {
                        "mode": "strm-verify",
                        "title": "罚罪2",
                        "strm": {
                            "roots": [
                                {
                                    "path": "/example/host/strm/series/罚罪2 {tmdbid=301001}/Season 01",
                                    "episode_count": 12,
                                    "episodes": list(range(1, 13)),
                                }
                            ],
                            "combined": {"episode_count": 12, "episodes": list(range(1, 13))},
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (diagnostics / "cloud.json").write_text(
                json.dumps(
                    {
                        "mode": "mv3-cloud-duplicate-video-cleanup-result",
                        "season_path": "/已整理/series/罚罪2 {tmdbid=301001}/Season 01",
                        "summary": {
                            "episode_count": 12,
                            "episodes": list(range(1, 13)),
                            "protected_strm_target_count": 12,
                            "strm_file_count": 12,
                        },
                        "delete_plan": {"duplicate_video_count": 0},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "finalize-remediation-expected-update-plan",
                    "--plan",
                    str(plan_path),
                    "--diagnostic-dir",
                    str(diagnostics),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "readonly-finalize-remediation-expected-update-plan")
        self.assertEqual(payload["ready_items"], 1)

    def test_cleanup_remediation_plan_classifies_failed_cleanup_preview_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report = build_finalize_cleanup_remediation_plan(
                self._cleanup_finalize_report(tmp_path),
                env_file="/safe/.env",
                cloud_media_storage="115-default",
            )

        self.assertEqual(report["planned_items"], 4)
        categories = {item["title"]: item["category"] for item in report["items"]}
        self.assertEqual(categories["qB孤儿"], "qb_orphan_preview_candidate")
        self.assertEqual(categories["空壳目录"], "empty_hlink_root_review")
        self.assertEqual(categories["已消失"], "local_already_absent_no_qb_match")
        self.assertEqual(categories["错季残留"], "source_or_wrong_season_review")

        commands_by_title = {
            item["title"]: "\n".join(str(command.get("command", "")) for command in item["commands"])
            for item in report["items"]
        }
        self.assertIn("qb-orphan-torrent-cleanup-preview", commands_by_title["qB孤儿"])
        self.assertIn("--expected-qb-hash 0123456789abcdef0123456789abcdef01234567", commands_by_title["qB孤儿"])
        self.assertIn("--source-root /example/source/qb-orphan", commands_by_title["qB孤儿"])
        self.assertIn("--hlink-root /example/hlink/qb-orphan", commands_by_title["qB孤儿"])
        self.assertNotIn("--approve-delete", commands_by_title["qB孤儿"])
        self.assertIn("hlink-empty-root-cleanup", commands_by_title["空壳目录"])
        self.assertNotIn("--approve-delete", commands_by_title["空壳目录"])
        self.assertIn("no-hash-local-absent-verify", commands_by_title["已消失"])
        self.assertIn("--source-root /example/source/missing", commands_by_title["已消失"])
        self.assertIn("--hlink-root /example/hlink/missing", commands_by_title["已消失"])
        self.assertEqual(commands_by_title["错季残留"], "")

        rendered_csv = render_finalize_cleanup_remediation_plan(report, "csv")
        self.assertIn("qb_orphan_preview_candidate", rendered_csv)
        self.assertIn("readonly-finalize-cleanup-remediation-plan", render_finalize_cleanup_remediation_plan(report, "json"))

    def test_cleanup_remediation_plan_does_not_emit_qb_preview_without_required_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            preview = tmp_path / "cleanup.json"
            preview.write_text(
                json.dumps(
                    self._cleanup_preview(
                        blockers=["hlink_root_missing"],
                        hlink={"path": "", "exists": False, "video_count": 0, "non_video_count": 0},
                        source_roots=[],
                        qb_matches=[{"hash": "f" * 40, "name": "路径不足.S01"}],
                    ),
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            finalize = {
                "mode": "batch-finalize-run",
                "items": [
                    self._cleanup_finalize_item(
                        "路径不足",
                        400005,
                        1,
                        str(preview),
                        hlink_root="",
                        source_paths=[],
                    )
                ],
            }

            report = build_finalize_cleanup_remediation_plan(finalize, env_file="/safe/.env")

        self.assertEqual(report["items"][0]["category"], "manual_cleanup_review")
        self.assertEqual(report["items"][0]["commands"], [])

    def test_cli_writes_finalize_cleanup_remediation_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            finalize = tmp_path / "finalize.json"
            output = tmp_path / "cleanup-remediation.json"
            finalize.write_text(json.dumps(self._cleanup_finalize_report(tmp_path), ensure_ascii=False), encoding="utf-8")

            exit_code = main(
                [
                    "finalize-cleanup-remediation-plan",
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
        self.assertEqual(payload["mode"], "readonly-finalize-cleanup-remediation-plan")
        self.assertEqual(payload["planned_items"], 4)

    def test_cleanup_remediation_run_executes_allowlisted_preview_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output_dir = tmp_path / "diagnostics"
            plan = build_finalize_cleanup_remediation_plan(self._cleanup_finalize_report(tmp_path), env_file="/safe/.env")
            calls = []

            def fake_runner(argv, **kwargs):
                calls.append((argv, kwargs))
                output_path = Path(argv[argv.index("--output") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                mode = argv[3]
                ok = mode in {"qb-orphan-torrent-cleanup-preview", "no-hash-local-absent-verify"}
                output_path.write_text(
                    json.dumps({"mode": mode, "ok": ok, "blockers": ["approval_required"] if mode == "hlink-empty-root-cleanup" else []}),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 0 if ok else 1, stdout="", stderr="")

            run = run_finalize_cleanup_remediation_plan(
                plan,
                output_dir=str(output_dir),
                categories=["qb_orphan_preview_candidate", "empty_hlink_root_review", "local_already_absent_no_qb_match"],
                execute_readonly=True,
                cwd="/example/app",
                command_runner=fake_runner,
            )

        self.assertTrue(run["ok"])
        self.assertEqual(run["mode"], "readonly-finalize-cleanup-remediation-run")
        self.assertEqual(run["planned_commands"], 3)
        self.assertEqual(run["executed_commands"], 3)
        self.assertEqual(run["status_counts"], {"diagnostic_failed": 1, "executed": 2})
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0][:3], ["python3", "-m", "series_cloud_archiver"])
        self.assertTrue(all(str(output_dir) in item["command"] for item in run["items"]))
        self.assertTrue(any(item["stage"] == "hlink_empty_root_review" and item["status"] == "diagnostic_failed" for item in run["items"]))
        self.assertTrue(any(item["stage"] == "qb_orphan_preview_readonly" and item["status"] == "executed" for item in run["items"]))
        self.assertTrue(any(item["stage"] == "no_hash_local_absent_verify_readonly" and item["status"] == "executed" for item in run["items"]))

    def test_cleanup_remediation_run_blocks_approval_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = build_finalize_cleanup_remediation_plan(self._cleanup_finalize_report(tmp_path), env_file="/safe/.env")
            plan["items"][0]["commands"][0]["command"] += " --approve-delete"

            run = run_finalize_cleanup_remediation_plan(
                plan,
                output_dir=str(tmp_path / "diagnostics"),
                categories=["qb_orphan_preview_candidate"],
                execute_readonly=True,
                command_runner=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not execute")),
            )

        self.assertFalse(run["ok"])
        self.assertEqual(run["unsafe_blocked_count"], 1)
        self.assertIn("approval_flag_forbidden", run["items"][0]["safety_blockers"])

    def test_cli_writes_finalize_cleanup_remediation_run_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            plan = tmp_path / "cleanup-plan.json"
            output = tmp_path / "cleanup-run.json"
            plan.write_text(
                json.dumps(build_finalize_cleanup_remediation_plan(self._cleanup_finalize_report(tmp_path), env_file="/safe/.env"), ensure_ascii=False),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "finalize-cleanup-remediation-run",
                    "--plan",
                    str(plan),
                    "--output-dir",
                    str(tmp_path / "diagnostics"),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "readonly-finalize-cleanup-remediation-run")
        self.assertEqual(payload["planned_commands"], 3)
        self.assertEqual(payload["executed_commands"], 0)

    def _plan_report(self) -> dict:
        return build_finalize_remediation_plan(
            self._review_report(),
            [self._finalize_report()],
            env_file="/safe/.env",
            cloud_media_storage="115-default",
        )

    def _cleanup_finalize_report(self, tmp_path: Path) -> dict:
        rows = [
            (
                "qB孤儿",
                400001,
                1,
                self._cleanup_preview(
                    blockers=["hlink_root_missing"],
                    hlink={"path": "/example/hlink/qb-orphan", "exists": False, "video_count": 0, "non_video_count": 0},
                    source_roots=[{"path": "/example/source/qb-orphan", "exists": False, "video_count": 0, "blocked": False}],
                    qb_matches=[{"hash": "0123456789abcdef0123456789abcdef01234567", "name": "qB孤儿.S01"}],
                ),
            ),
            (
                "空壳目录",
                400002,
                1,
                self._cleanup_preview(
                    blockers=["qb_match_required"],
                    hlink={"path": "/example/hlink/empty", "exists": True, "video_count": 0, "non_video_count": 1},
                    source_roots=[],
                    qb_matches=[],
                ),
            ),
            (
                "已消失",
                400003,
                1,
                self._cleanup_preview(
                    blockers=["hlink_root_missing", "qb_match_required"],
                    hlink={"path": "/example/hlink/missing", "exists": False, "video_count": 0, "non_video_count": 0},
                    source_roots=[{"path": "/example/source/missing", "exists": False, "video_count": 0, "blocked": False}],
                    qb_matches=[],
                ),
            ),
            (
                "错季残留",
                400004,
                4,
                self._cleanup_preview(
                    blockers=["source_root_check_failed"],
                    hlink={"path": "/example/hlink/wrong-season", "exists": True, "video_count": 0, "non_video_count": 0},
                    source_roots=[
                        {
                            "path": "/example/source/wrong-season-s03",
                            "exists": True,
                            "video_count": 6,
                            "blocked": True,
                            "reason": "source_contains_unlinked_videos",
                        }
                    ],
                    qb_matches=[{"hash": "abcdefabcdefabcdefabcdefabcdefabcdefabcd", "name": "Wrong.Season.S03"}],
                ),
            ),
        ]
        items = []
        for title, tmdbid, season, preview_payload in rows:
            preview = tmp_path / f"{tmdbid}-cleanup.json"
            preview.write_text(json.dumps(preview_payload, ensure_ascii=False), encoding="utf-8")
            items.append(self._cleanup_finalize_item(title, tmdbid, season, str(preview)))
        return {"mode": "batch-finalize-run", "items": items}

    def _cleanup_finalize_item(
        self,
        title: str,
        tmdbid: int,
        season: int,
        cleanup_output: str,
        hlink_root: str = "/example/hlink/default",
        source_paths: Optional[List[str]] = None,
    ) -> dict:
        return {
            "title": title,
            "tmdbid": tmdbid,
            "season": season,
            "status": "failed_cleanup_preview",
            "blockers": ["cleanup_preview_failed"],
            "expected_episode_count": 10,
            "expected_episodes": list(range(1, 11)),
            "strm_root": f"/example/host/strm/series/{title} {{tmdbid={tmdbid}}}/Season {season:02d}",
            "required_target_prefix": f"/已整理/series/{title} {{tmdbid={tmdbid}}}",
            "cloud_season_path": f"/已整理/series/{title} {{tmdbid={tmdbid}}}/Season {season:02d}",
            "hlink_root": hlink_root,
            "source_paths": source_paths if source_paths is not None else [f"/example/source/{title}/Season {season:02d}"],
            "stages": [{"stage": "cloud_hlink_cleanup_preview", "output": cleanup_output}],
        }

    def _cleanup_preview(
        self,
        *,
        blockers: List[str],
        hlink: dict,
        source_roots: List[dict],
        qb_matches: List[dict],
    ) -> dict:
        return {
            "mode": "cloud-hlink-cleanup-preview",
            "title": "cleanup",
            "expected": {
                "tmdbid": 1,
                "episode_count": 10,
                "episode_min": 1,
                "episode_max": 10,
                "required_target_prefix": "/已整理/series/cleanup",
                "cloud_media_path": "/已整理/series/cleanup",
            },
            "hlink": hlink,
            "filesystem": {"source_roots": source_roots},
            "qbittorrent": {"matches": qb_matches, "matched_count": len(qb_matches)},
            "blockers": blockers,
            "warnings": [],
        }


if __name__ == "__main__":
    unittest.main()
