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

    def _ready_share_preview_report(self) -> dict:
        return {
            "mode": "readonly-batch-mv3-share-preview",
            "planned_items": 1,
            "executable_preview_items": 0,
            "executed_preview_items": 1,
            "ready_for_receive_items": 1,
            "blocked_preview_items": 0,
            "skipped_items": 0,
            "items": [
                {
                    "status": "preview_ready_for_receive",
                    "title": "干净剧 (2025) {tmdbid=456}",
                    "tmdbid": 456,
                    "season": 1,
                    "keyword": "干净剧",
                    "selection_index": 2,
                    "browse_cid": "",
                    "expected_episode_count": 10,
                    "expected_episode_min": 1,
                    "expected_episode_max": 10,
                    "expected_episodes": list(range(1, 11)),
                    "preview_report_path": "/example/outputs/share-preview-clean.json",
                    "preview_report": {
                        "mode": "readonly-mv3-share-preview",
                        "ok": True,
                        "episodes": list(range(1, 11)),
                        "episode_count": 10,
                        "video_file_count": 10,
                        "blockers": [],
                        "missing_expected": [],
                        "unexpected_episodes": [],
                        "browse": {"items": [{"kind": "folder", "name": "干净剧", "file_id": "folder-1"}]},
                    },
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

    def test_pipeline_finalize_offset_limits_ready_finalize_rows(self) -> None:
        cloud_report = self._cloud_complete_report()
        second = json.loads(json.dumps(cloud_report["items"][0]))
        second["title"] = "第二部 (2025) {tmdbid=2468}"
        second["tmdbid"] = 2468
        second["strm_paths_sample"] = [
            "/example/host/strm/series/第二部 (2025) {tmdbid=2468}/Season 1/第二部 S01E01.strm"
        ]
        second["cloud_media_path"] = "/已整理/series/第二部 (2025) {tmdbid=2468}/Season 1"
        cloud_report["items"].append(second)

        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="finalize-offset",
                config=ScanConfig(media_roots=[]),
                env_file="/safe/.env",
                cloud_report=cloud_report,
                host_strm_root="/example/host/strm",
                emby_strm_root="/example/service/strm",
                finalize_offset=1,
                finalize_limit=1,
            )
            finalize_plan = json.loads((Path(report["run_dir"]) / "12-finalize-plan.json").read_text(encoding="utf-8"))

        self.assertEqual(report["settings"]["finalize_offset"], 1)
        self.assertEqual(finalize_plan["settings"]["offset"], 1)
        self.assertEqual(finalize_plan["settings"]["limit"], 1)
        self.assertEqual(finalize_plan["finalize_ready_items"], 1)
        self.assertEqual(finalize_plan["items"][0]["title"], "第二部 (2025) {tmdbid=2468}")

    def test_pipeline_applies_manual_exclusions_to_finalize_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="manual-exclusion",
                config=ScanConfig(media_roots=[]),
                env_file="/safe/.env",
                cloud_report=self._cloud_complete_report(),
                host_strm_root="/example/host/strm",
                emby_strm_root="/example/service/strm",
                manual_exclusions=[
                    {
                        "title": "兄弟连",
                        "tmdbid": 4613,
                        "season": 1,
                        "reason": "manual_exclusion:user_skip",
                    }
                ],
            )
            run_dir = Path(report["run_dir"])
            batch_plan = json.loads((run_dir / "05-batch-plan.json").read_text(encoding="utf-8"))
            finalize_plan = json.loads((run_dir / "12-finalize-plan.json").read_text(encoding="utf-8"))

        self.assertEqual(report["settings"]["manual_exclusion_count"], 1)
        self.assertEqual(batch_plan["items"][0]["bucket"], "manual_exclusion")
        self.assertEqual(finalize_plan["finalize_ready_items"], 0)
        self.assertEqual(finalize_plan["items"][0]["status"], "skipped_finalize")
        self.assertIn("manual_exclusion:user_skip", finalize_plan["items"][0]["skip_reasons"])

    def test_pipeline_reuses_ready_share_preview_report_for_transfer_stage(self) -> None:
        transfer_calls = []

        class TransferActions:
            def receive_share(self, *args, **kwargs):
                transfer_calls.append(("receive", args, kwargs))
                return {
                    "mode": "mv3-share-receive-one-result",
                    "ok": True,
                    "target_path": kwargs.get("target_path"),
                    "browse_selection": {"name": "干净剧"},
                    "warnings": [],
                }

            def browse_cloud(self, *args, **kwargs):
                transfer_calls.append(("browse", args, kwargs))
                path = str(kwargs.get("path") or "")
                if path.startswith("/已整理/series"):
                    return {
                        "mode": "mv3-cloud-browse",
                        "ok": True,
                        "path": path,
                        "summary": {"video_file_count": 10, "metadata_sidecar_file_count": 0},
                        "items": [
                            {"kind": "file", "media_kind": "video", "name": f"干净剧.E{episode:02d}.mkv", "episode": episode}
                            for episode in range(1, 11)
                        ],
                    }
                if path.startswith("/未整理"):
                    return {
                        "mode": "mv3-cloud-browse",
                        "ok": True,
                        "path": path,
                        "summary": {"video_file_count": 0, "metadata_sidecar_file_count": 0},
                        "items": [],
                    }
                return {"mode": "mv3-cloud-browse", "ok": False, "path": path, "summary": {}, "items": [], "warnings": ["not_found"]}

            def organize_transfer(self, *args, **kwargs):
                transfer_calls.append(("organize", args, kwargs))
                return {
                    "mode": "mv3-organize-transfer-result",
                    "ok": True,
                    "source_path": "/未整理/干净剧",
                    "target_dir": kwargs.get("target_dir"),
                    "strm_dir": kwargs.get("strm_dir"),
                    "blockers": [],
                    "warnings": [],
                }

        def fail_preview(*_args, **_kwargs):
            raise AssertionError("share preview should be reused, not executed")

        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="reuse-preview",
                config=ScanConfig(media_roots=[], mv3_base_url="http://mv3.local", mv3_token="token"),
                env_file="/safe/.env",
                cloud_report=self._cloud_report(),
                share_search_plans=[self._share_search_plan()],
                share_preview_report=self._ready_share_preview_report(),
                run_transfer_stage=True,
                approve_receive=True,
                approve_transfer=True,
                refresh_after_transfer=False,
                actions=BatchPipelineActions(share_preview=fail_preview, transfer_actions=TransferActions()),
            )
            run_dir = Path(report["run_dir"])
            copied_preview = json.loads((run_dir / "06-share-preview.json").read_text(encoding="utf-8"))
            receive_plan = json.loads((run_dir / "07-receive-plan.json").read_text(encoding="utf-8"))
            transfer_run = json.loads((run_dir / "08-transfer-run.json").read_text(encoding="utf-8"))

        self.assertEqual(copied_preview["items"][0]["status"], "preview_ready_for_receive")
        self.assertEqual(receive_plan["approval_required_items"], 1)
        self.assertEqual(transfer_run["organized_items"], 1)
        self.assertIn("organize", [call[0] for call in transfer_calls])
        self.assertEqual(next(phase for phase in report["phases"] if phase["name"] == "share-preview")["status"], "input")

    def test_pipeline_review_includes_transfer_failures(self) -> None:
        class FailingTransferActions:
            def receive_share(self, *args, **kwargs):
                return {
                    "mode": "mv3-share-receive-one-result",
                    "ok": True,
                    "target_path": kwargs.get("target_path"),
                    "browse_selection": {"name": "干净剧"},
                    "warnings": [],
                }

            def browse_cloud(self, *args, **kwargs):
                path = str(kwargs.get("path") or "")
                if path.startswith("/未整理"):
                    return {
                        "mode": "mv3-cloud-browse",
                        "ok": True,
                        "path": path,
                        "summary": {"video_file_count": 10, "metadata_sidecar_file_count": 0},
                        "items": [
                            {"kind": "file", "media_kind": "video", "name": f"干净剧.E{episode:02d}.mkv", "episode": episode}
                            for episode in range(1, 11)
                        ],
                    }
                return {
                    "mode": "mv3-cloud-browse",
                    "ok": False,
                    "path": path,
                    "summary": {},
                    "items": [],
                    "warnings": ["path_info_not_found"],
                }

            def organize_transfer(self, *args, **kwargs):
                return {
                    "mode": "mv3-organize-transfer-result",
                    "ok": False,
                    "blockers": ["mv3_transfer_request_failed"],
                    "warnings": ["mv3_transfer_request_failed:timeout:timed out"],
                }

        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="transfer-failed-review",
                config=ScanConfig(media_roots=[], mv3_base_url="http://mv3.local", mv3_token="token"),
                env_file="/safe/.env",
                cloud_report=self._cloud_report(),
                share_search_plans=[self._share_search_plan()],
                share_preview_report=self._ready_share_preview_report(),
                run_transfer_stage=True,
                approve_receive=True,
                approve_transfer=True,
                refresh_after_transfer=False,
                actions=BatchPipelineActions(transfer_actions=FailingTransferActions()),
            )
            run_dir = Path(report["run_dir"])
            review = json.loads((run_dir / "14-review.json").read_text(encoding="utf-8"))

        self.assertEqual(report["summary"]["transfer_run"]["failed_items"], 1)
        self.assertEqual(review["decision_counts"]["manual_review_transfer_failed"], 1)
        item = review["items"][0]
        self.assertEqual(item["decision"], "manual_review_transfer_failed")
        self.assertEqual(item["transfer_status"], "failed_organize_transfer")
        self.assertIn("mv3_transfer_request_failed", item["transfer_blockers"])
        self.assertIn("不要清理本地", item["next_action"])

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

    def test_pipeline_share_search_writes_checkpoint(self) -> None:
        checkpoint_payloads = []

        def fake_search(_base_url, _token, keyword, channels=None, timeout=60):
            checkpoint = run_dir / "04-share-search.checkpoint.json"
            self.assertTrue(checkpoint.exists())
            checkpoint_payloads.append(json.loads(checkpoint.read_text(encoding="utf-8")))
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
            run_dir = Path(tmp) / "search-checkpoint"
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="search-checkpoint",
                config=ScanConfig(media_roots=[], mv3_base_url="http://mv3.local", mv3_token="token"),
                cloud_report=self._cloud_report(),
                execute_share_search=True,
                share_search_limit=1,
                actions=BatchPipelineActions(share_search=fake_search),
            )
            final_checkpoint = json.loads((Path(report["run_dir"]) / "04-share-search.checkpoint.json").read_text(encoding="utf-8"))

        self.assertEqual(checkpoint_payloads[0]["checkpoint"]["status"], "in_progress")
        self.assertEqual(checkpoint_payloads[0]["checkpoint"]["completed_items"], 0)
        self.assertEqual(final_checkpoint["checkpoint"]["status"], "completed")
        self.assertEqual(final_checkpoint["checkpoint"]["completed_items"], 1)
        self.assertTrue(final_checkpoint["checkpoint"]["complete"])

    def test_pipeline_share_search_records_timeout_diagnostics(self) -> None:
        def fake_search(_base_url, _token, keyword, channels=None, timeout=60):
            return {
                "ok": False,
                "status": 0,
                "error_type": "TimeoutError",
                "error": "timed out",
                "result_count": 0,
                "items": [],
                "warnings": ["mv3_resource_search_request_failed"],
            }

        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="search-timeout",
                config=ScanConfig(media_roots=[], mv3_base_url="http://mv3.local", mv3_token="token"),
                cloud_report=self._cloud_report(),
                execute_share_search=True,
                share_search_limit=1,
                actions=BatchPipelineActions(share_search=fake_search),
            )
            share_search = json.loads((Path(report["run_dir"]) / "04-share-search.json").read_text(encoding="utf-8"))

        item = share_search["items"][0]
        self.assertEqual(share_search["ready_items"], 0)
        self.assertEqual(item["keyword_reports"][0]["error_type"], "TimeoutError")
        self.assertEqual(item["search_errors"][0]["error"], "timed out")
        self.assertIn("keyword_error:干净剧:TimeoutError", item["warnings"])

    def test_pipeline_share_search_retries_timeout_with_fallback_channel(self) -> None:
        calls = []

        def fake_search(_base_url, _token, keyword, channels=None, timeout=60):
            calls.append((keyword, tuple(channels or [])))
            if not channels:
                return {
                    "ok": False,
                    "status": 0,
                    "error_type": "TimeoutError",
                    "error": "timed out",
                    "result_count": 0,
                    "items": [],
                    "warnings": ["mv3_resource_search_request_failed"],
                }
            return {
                "ok": True,
                "status": 200,
                "result_count": 1,
                "items": [
                    {
                        "index": 1,
                        "title": f"{keyword} S01E01-E10 完结",
                        "size": "1GB",
                        "channel": "pansou",
                        "share_code_available": True,
                    }
                ],
                "warnings": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="search-fallback",
                config=ScanConfig(media_roots=[], mv3_base_url="http://mv3.local", mv3_token="token"),
                cloud_report=self._cloud_report(),
                execute_share_search=True,
                share_search_limit=1,
                actions=BatchPipelineActions(share_search=fake_search),
            )
            share_search = json.loads((Path(report["run_dir"]) / "04-share-search.json").read_text(encoding="utf-8"))

        item = share_search["items"][0]
        self.assertEqual(calls, [("干净剧", ()), ("干净剧", ("pansou",))])
        self.assertTrue(item["keyword_reports"][1]["fallback"])
        self.assertIn("keyword_fallback:干净剧:pansou", item["warnings"])
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

    def test_pipeline_reports_missing_media_root_as_scan_failure(self) -> None:
        def missing_root_scan(_config):
            return {
                "mode": "dry-run",
                "media_roots": ["/missing/media/root"],
                "min_seed_days": 7,
                "total_series": 0,
                "status_counts": {},
                "warnings": ["media_root_missing:/missing/media/root"],
                "missing_media_roots": ["/missing/media/root"],
                "candidates": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_pipeline(
                output_dir=tmp,
                run_id="missing-root",
                config=ScanConfig(media_roots=["/missing/media/root"]),
                actions=BatchPipelineActions(scan=missing_root_scan),
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["failed_phase_count"], 1)
        self.assertIn("scan_media_roots_missing", report["warnings"])
        self.assertNotIn("scan_returned_no_series_check_media_roots", report["warnings"])
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

    def test_cli_batch_pipeline_reuses_share_preview_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            cloud = tmp_path / "cloud.json"
            share = tmp_path / "share.json"
            preview = tmp_path / "preview.json"
            output = tmp_path / "state.json"
            env_file.write_text("", encoding="utf-8")
            cloud.write_text(json.dumps(self._cloud_report(), ensure_ascii=False), encoding="utf-8")
            share.write_text(json.dumps(self._share_search_plan(), ensure_ascii=False), encoding="utf-8")
            preview.write_text(json.dumps(self._ready_share_preview_report(), ensure_ascii=False), encoding="utf-8")

            exit_code = main(
                [
                    "batch-pipeline",
                    "--env-file",
                    str(env_file),
                    "--cloud-report",
                    str(cloud),
                    "--share-search-plan",
                    str(share),
                    "--share-preview-report",
                    str(preview),
                    "--output-dir",
                    str(tmp_path / "runs"),
                    "--run-id",
                    "cli-reuse-preview",
                    "--host-strm-root",
                    "/example/host/strm",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            copied_preview = json.loads((Path(payload["run_dir"]) / "06-share-preview.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["summary"]["share_preview"]["ready_for_receive_items"], 1)
        self.assertEqual(copied_preview["items"][0]["status"], "preview_ready_for_receive")
        self.assertEqual(next(phase for phase in payload["phases"] if phase["name"] == "share-preview")["status"], "input")

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
        self.assertIn("scan_media_roots_missing", payload["warnings"])
