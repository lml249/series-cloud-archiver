import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class CliEntrypointTest(unittest.TestCase):
    def test_cli_module_entrypoint_runs_main(self) -> None:
        env = {**os.environ, "PYTHONPATH": "src"}
        result = subprocess.run(
            [sys.executable, "-m", "series_cloud_archiver.cli", "--help"],
            cwd=os.getcwd(),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("series-cloud-archiver", result.stdout)
        self.assertIn("dotqb-orphan-cleanup", result.stdout)

    def test_cloud_check_json_defaults_to_full_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            strm_root = tmp_path / "strm"
            scan_report = tmp_path / "scan.json"
            output = tmp_path / "cloud.json"
            candidates = []
            for tmdbid in (101, 102):
                touch = strm_root / "series" / f"Demo {tmdbid} {{tmdbid={tmdbid}}}" / "Season 01" / "Demo S01E01.strm"
                touch.parent.mkdir(parents=True, exist_ok=True)
                touch.write_text("http://example.invalid/redacted", encoding="utf-8")
                candidates.append(
                    {
                        "title": f"Demo {tmdbid}",
                        "status": "candidate_for_cloud_check",
                        "size_bytes": 1024,
                        "video_count": 1,
                        "episode_numbers": [1],
                        "manual_completion": {
                            "matched": True,
                            "tmdbid": tmdbid,
                            "season": 1,
                        },
                    }
                )
            scan_report.write_text(json.dumps({"candidates": candidates}), encoding="utf-8")

            env = {**os.environ, "PYTHONPATH": "src", "ARCHIVER_TOP": "1"}
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "series_cloud_archiver",
                    "cloud-check",
                    "--scan-report",
                    str(scan_report),
                    "--strm-root",
                    str(strm_root),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ],
                cwd=os.getcwd(),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["status_counts"], {"cloud_strm_complete": 2})
            self.assertEqual(len(payload["items"]), 2)

    def test_share_search_checkpoint_updates_after_each_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transfer_plan = tmp_path / "transfer-plan.json"
            output = tmp_path / "share-search.json"
            checkpoint = tmp_path / "checkpoint.json"
            transfer_plan.write_text(
                json.dumps(
                    {
                        "mode": "readonly-mv3-transfer-plan",
                        "items": [
                            {"title": "第一部", "season": 1, "size_bytes": 100, "expected_count": 1},
                            {"title": "第二部", "season": 1, "size_bytes": 100, "expected_count": 1},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            writes = []

            def fake_search(_base_url, _token, keyword, channels=None, timeout=60):
                writes.append(checkpoint.exists())
                return {
                    "ok": True,
                    "result_count": 1,
                    "items": [
                        {
                            "index": 1,
                            "title": f"{keyword} S01E01 完结",
                            "size": "100B",
                            "share_code_available": True,
                        }
                    ],
                }

            class FakeConfig:
                mv3_base_url = "http://mv3.example"
                mv3_token = "token"

            from series_cloud_archiver import cli

            with patch.object(cli, "config_from_env", return_value=FakeConfig()), patch.object(cli, "search_mv3_resources", side_effect=fake_search):
                code = cli.main(
                    [
                        "plan-mv3-share-search",
                        "--env-file",
                        str(tmp_path / ".env"),
                        "--transfer-plan",
                        str(transfer_plan),
                        "--limit",
                        "2",
                        "--checkpoint-output",
                        str(checkpoint),
                        "--checkpoint-each",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(writes, [False, True])
            checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            output_payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(checkpoint_payload["checkpoint"]["completed_items"], 2)
            self.assertTrue(checkpoint_payload["checkpoint"]["complete"])
            self.assertEqual(output_payload["planned_items"], 2)
            self.assertEqual(output_payload["ready_items"], 2)

    def test_cli_output_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            output = tmp_path / "new" / "date" / "preview.json"

            class FakeConfig:
                mv3_base_url = "http://mv3.example"
                mv3_token = "token"

            from series_cloud_archiver import cli

            with patch.object(cli, "config_from_env", return_value=FakeConfig()), patch.object(
                cli,
                "preview_mv3_share",
                return_value={"mode": "readonly-mv3-share-preview", "ok": True, "warnings": []},
            ):
                code = cli.main(
                    [
                        "mv3-share-preview",
                        "--env-file",
                        str(tmp_path / ".env"),
                        "--keyword",
                        "Demo",
                        "--expected-title-contains",
                        "Demo",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(output.exists())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["ok"], True)

    def test_batch_share_preview_dry_run_does_not_require_mv3_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            batch_plan = tmp_path / "batch-plan.json"
            output = tmp_path / "batch-preview.json"
            batch_plan.write_text(
                json.dumps(
                    {
                        "mode": "readonly-batch-state-plan",
                        "items": [
                            {
                                "bucket": "manual_review",
                                "title": "折腰",
                                "tmdbid": 246,
                                "season": 1,
                                "expected_episode_count": 2,
                                "candidate_diagnostics": {
                                    "best_candidate": {
                                        "search_index": 1,
                                        "search_keyword": "折腰",
                                        "title": "折腰 4K",
                                        "score": 65,
                                        "blockers": ["episode_coverage_unclear"],
                                    }
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            env = {**os.environ, "PYTHONPATH": "src"}
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "series_cloud_archiver",
                    "batch-share-preview",
                    "--env-file",
                    str(tmp_path / ".env"),
                    "--batch-plan",
                    str(batch_plan),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ],
                cwd=os.getcwd(),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "readonly-batch-mv3-share-preview")
            self.assertEqual(payload["executable_preview_items"], 1)
            self.assertIn("mv3-share-preview", payload["items"][0]["command"])


if __name__ == "__main__":
    unittest.main()
