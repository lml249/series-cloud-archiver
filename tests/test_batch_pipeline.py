import json
import tempfile
import unittest
from pathlib import Path

from series_cloud_archiver.batch_pipeline import (
    BatchPipelineActions,
    render_batch_pipeline_report,
    run_batch_pipeline,
)
from series_cloud_archiver.batch_runner import BatchFinalizeActions
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
                    "source_paths": ["/example/local-tv/干净剧 (2025) {tmdbid=456}/Season 01"],
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

    def _cloud_complete_report(self) -> dict:
        return {
            "mode": "readonly-cloud-check",
            "items": [
                {
                    "status": "cloud_strm_complete",
                    "title": "兄弟连 (2001) {tmdbid=4613}",
                    "tmdbid": 4613,
                    "season": 1,
                    "size_bytes": 1_000_000_000,
                    "expected_count": 10,
                    "expected_episodes": list(range(1, 11)),
                    "source_paths": ["/example/local-tv/兄弟连 (2001) {tmdbid=4613}/Season 01"],
                    "strm_paths_sample": [
                        "/example/host/strm/series/兄弟连 (2001) {tmdbid=4613}/Season 1/兄弟连 S01E01.strm"
                    ],
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
                host_strm_root="/example/host/strm",
                mp_strm_root="/example/mp/strm",
                emby_strm_root="/example/service/strm",
            )
            run_dir = Path(report["run_dir"])
            finalize_plan = json.loads((run_dir / "12-finalize-plan.json").read_text(encoding="utf-8"))

            self.assertTrue((run_dir / "05-batch-plan.json").exists())
            self.assertTrue((run_dir / "06-share-preview.json").exists())
            self.assertTrue((run_dir / "07-receive-plan.json").exists())
            self.assertTrue((run_dir / "12-finalize-plan.json").exists())
            self.assertTrue((run_dir / "14-review.json").exists())
            self.assertEqual(report["summary"]["batch_plan"]["auto_transfer_items"], 1)
            self.assertEqual(report["summary"]["share_preview"]["executable_preview_items"], 1)
            self.assertEqual(report["settings"]["cloud_root"], "/已整理/series")
            self.assertEqual(report["settings"]["mp_strm_root"], "/example/mp/strm")
            self.assertEqual(finalize_plan["settings"]["mp_strm_root"], "/example/mp/strm")
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

    def test_pipeline_marks_empty_generated_scan_as_failed(self) -> None:
        def empty_scan(_config):
            return {
                "mode": "dry-run",
                "media_roots": ["/missing/media/root"],
                "min_seed_days": 7,
                "total_series": 0,
                "status_counts": {},
                "warnings": [],
                "candidates": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="empty-scan",
                config=ScanConfig(media_roots=["/missing/media/root"]),
                actions=BatchPipelineActions(scan=empty_scan),
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["failed_phase_count"], 1)
        self.assertIn("scan_returned_no_series_check_media_roots", report["warnings"])
        self.assertEqual(report["phases"][0]["name"], "scan")
        self.assertEqual(report["phases"][0]["status"], "failed")

    def test_pipeline_writes_extra_source_media_plan_after_finalize_blocker(self) -> None:
        def ok_report(mode, **extra):
            return {"mode": mode, "ok": True, "ready_for_execute": True, "blockers": [], "warnings": [], **extra}

        def cleanup_preview(**_kwargs):
            return {
                "mode": "cloud-hlink-cleanup-preview",
                "ok": False,
                "ready_for_execute": False,
                "blockers": ["source_root_check_failed"],
                "warnings": [],
                "filesystem": {
                    "source_roots": [
                        {
                            "path": "/volume-example/source-tv/兄弟连",
                            "blocked": True,
                            "video_count": 12,
                            "linked_hlink_video_count": 10,
                            "unlinked_video_sample": [
                                "/volume-example/source-tv/兄弟连/Band.of.Brothers.SP1.We.Stand.Alone.mkv",
                            ],
                        }
                    ]
                },
            }

        actions = BatchFinalizeActions(
            verify_strm=lambda **kwargs: ok_report("strm-verify", expected=kwargs),
            cloud_duplicate_cleanup=lambda *args, **kwargs: ok_report(
                "mv3-cloud-duplicate-video-cleanup-result",
                delete_plan={"duplicate_video_count": 0},
            ),
            scrape_mp_strm=lambda *args, **kwargs: ok_report("mp-scrape-strm-result"),
            audit_nfo_language=lambda **kwargs: ok_report("strm-nfo-language-audit"),
            emby_media_updated=lambda *args, **kwargs: ok_report("emby-media-updated"),
            cleanup_preview=cleanup_preview,
        )

        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="finalize-extra",
                config=ScanConfig(
                    media_roots=[],
                    mp_base_url="http://mp.local",
                    mp_token="mp-token",
                    qb_base_url="http://qb.local",
                    mv3_base_url="http://mv3.local",
                    mv3_token="mv3-token",
                    emby_base_url="http://emby.local",
                    emby_key="emby-key",
                ),
                env_file="/safe/.env",
                cloud_report=self._cloud_complete_report(),
                host_strm_root="/example/host/strm",
                emby_strm_root="/example/service/strm",
                run_finalize_stage=True,
                execute_scrape=True,
                actions=BatchPipelineActions(finalize_actions=actions),
            )
            run_dir = Path(report["run_dir"])
            extra = json.loads((run_dir / "15-extra-source-media-plan.json").read_text(encoding="utf-8"))

        self.assertFalse(report["ok"])
        self.assertEqual(extra["planned_items"], 1)
        self.assertEqual(extra["items"][0]["media_kind"], "special")
        self.assertIn("mv3-organize-scan-source", extra["items"][0]["commands"][0]["command"])
        self.assertEqual(report["summary"]["extra_source_media"]["planned_items"], 1)

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
                    "/example/host/strm",
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

    def test_cli_batch_pipeline_returns_nonzero_for_empty_generated_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "state.json"
            env_file.write_text("", encoding="utf-8")

            exit_code = main(
                [
                    "batch-pipeline",
                    "--env-file",
                    str(env_file),
                    "--media-root",
                    str(tmp_path / "missing"),
                    "--strm-root",
                    str(tmp_path / "strm"),
                    "--output-dir",
                    str(tmp_path / "runs"),
                    "--run-id",
                    "empty-cli",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertNotEqual(exit_code, 0)
        self.assertFalse(payload["ok"])
        self.assertIn("scan_returned_no_series_check_media_roots", payload["warnings"])
