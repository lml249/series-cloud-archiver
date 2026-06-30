import json
import tempfile
import unittest
from pathlib import Path

from series_cloud_archiver.batch_pipeline import (
    BatchPipelineActions,
    render_batch_pipeline_report,
    run_batch_pipeline,
)
from series_cloud_archiver.config import ScanConfig
from series_cloud_archiver.cli import main


class BatchPipelineTest(unittest.TestCase):
    def _cloud_report(self) -> dict:
        return {
            "mode": "readonly-cloud-check",
            "items": [
                {
                    "status": "cloud_strm_not_found",
                    "title": "干净剧 (2025) {tmdbid=456}",
                    "tmdbid": 456,
                    "season": 1,
                    "size_bytes": 1_000_000_000,
                    "expected_count": 10,
                    "source_paths": ["/volume3/hlink/TV/干净剧 (2025) {tmdbid=456}/Season 01"],
                }
            ],
        }

    def _share_search_plan(self) -> dict:
        return {
            "mode": "readonly-mv3-share-search-plan",
            "items": [
                {
                    "title": "干净剧 (2025) {tmdbid=456}",
                    "tmdbid": 456,
                    "season": 1,
                    "recommended_candidate": {
                        "search_index": 2,
                        "search_keyword": "干净剧",
                        "title": "干净剧 S01E01-E10 完结",
                        "score": 85,
                        "size_delta_ratio": 0.1,
                        "blockers": [],
                    },
                    "candidates": [{"score": 85}],
                }
            ],
        }

    def test_pipeline_writes_resumable_dry_run_reports_without_mv3_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="dry-run",
                config=ScanConfig(media_roots=[]),
                env_file="/safe/.env",
                cloud_report=self._cloud_report(),
                share_search_plans=[self._share_search_plan()],
                host_strm_root="/volume4/volume4/mv3/strm",
                emby_strm_root="/volume4/mv3/strm",
            )
            run_dir = Path(report["run_dir"])

            self.assertTrue((run_dir / "05-batch-plan.json").exists())
            self.assertTrue((run_dir / "06-share-preview.json").exists())
            self.assertTrue((run_dir / "07-receive-plan.json").exists())
            self.assertTrue((run_dir / "12-finalize-plan.json").exists())
            self.assertTrue((run_dir / "14-review.json").exists())
            self.assertEqual(report["summary"]["batch_plan"]["auto_transfer_items"], 1)
            self.assertEqual(report["summary"]["share_preview"]["executable_preview_items"], 1)
            self.assertEqual(report["settings"]["cloud_root"], "/已整理/series")
            self.assertEqual(report["settings"]["organize_target_dir"], "/已整理")
            self.assertEqual(report["settings"]["approve_delete"], False)
            rendered = render_batch_pipeline_report(report, "markdown")
            self.assertIn("Batch Pipeline", rendered)
            self.assertIn("batch-plan", rendered)

    def test_pipeline_executes_share_search_when_requested(self) -> None:
        calls = []

        def fake_search(_base_url, _token, keyword, channels=None, timeout=60):
            calls.append((keyword, channels, timeout))
            return {
                "ok": True,
                "result_count": 1,
                "items": [
                    {
                        "index": 1,
                        "title": f"{keyword} S01E01-E10 完结",
                        "size": "1GB",
                        "share_code_available": True,
                    }
                ],
            }

        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="search",
                config=ScanConfig(media_roots=[], mv3_base_url="http://mv3.local", mv3_token="token"),
                cloud_report=self._cloud_report(),
                execute_share_search=True,
                share_search_limit=1,
                actions=BatchPipelineActions(share_search=fake_search),
            )
            share_search = json.loads((Path(report["run_dir"]) / "04-share-search.json").read_text(encoding="utf-8"))

        self.assertTrue(calls)
        self.assertEqual(share_search["planned_items"], 1)
        self.assertEqual(report["summary"]["batch_plan"]["auto_transfer_items"], 1)

    def test_cli_batch_pipeline_writes_json_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            env_file.write_text("", encoding="utf-8")
            cloud = tmp_path / "cloud.json"
            share = tmp_path / "share.json"
            output = tmp_path / "state.json"
            cloud.write_text(json.dumps(self._cloud_report(), ensure_ascii=False), encoding="utf-8")
            share.write_text(json.dumps(self._share_search_plan(), ensure_ascii=False), encoding="utf-8")

            exit_code = main(
                [
                    "batch-pipeline",
                    "--env-file",
                    str(env_file),
                    "--cloud-report",
                    str(cloud),
                    "--share-search-plan",
                    str(share),
                    "--output-dir",
                    str(tmp_path / "runs"),
                    "--run-id",
                    "cli",
                    "--host-strm-root",
                    "/volume4/volume4/mv3/strm",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            state_file_exists = Path(payload["state_file"]).exists()

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "batch-pipeline-state")
        self.assertEqual(payload["summary"]["batch_plan"]["auto_transfer_items"], 1)
        self.assertTrue(state_file_exists)
