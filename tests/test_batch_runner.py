import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from series_cloud_archiver.batch_runner import (
    AUTO_CLEANUP,
    AUTO_TRANSFER,
    BatchFinalizeActions,
    MANUAL_REVIEW,
    build_batch_finalize_plan,
    build_batch_plan,
    merge_share_search_plans,
    render_batch_finalize_plan,
    render_batch_finalize_run,
    render_batch_plan,
    run_batch_finalize,
)
from series_cloud_archiver.batch_preview import (
    build_batch_share_preview_plan,
    build_batch_share_receive_plan,
    render_batch_share_preview_report,
    render_batch_share_receive_plan,
)
from series_cloud_archiver.cli import main


@dataclass
class FinalizeFakeConfig:
    mp_base_url: str = "http://mp.local"
    mp_token: str = "mp-token"
    qb_base_url: str = "http://qb.local"
    qb_user: str = "qb"
    qb_pass: str = "pass"
    mv3_base_url: str = "http://mv3.local"
    mv3_token: str = "mv3-token"
    emby_base_url: str = "http://emby.local"
    emby_key: str = "emby-key"
    emby_library_db_path: str = ""
    path_aliases: Optional[dict] = None


class FinalizeFakeActions:
    def __init__(self, fail_stage: str = "") -> None:
        self.fail_stage = fail_stage
        self.calls: list[tuple[str, dict]] = []

    def _ok(self, stage: str, **extra: object) -> dict:
        self.calls.append((stage, dict(extra)))
        ok = self.fail_stage != stage
        return {
            "mode": stage,
            "ok": ok,
            "ready_for_execute": ok,
            "blockers": [] if ok else [f"{stage}_failed"],
            "warnings": [],
            **extra,
        }

    def verify_strm(self, **kwargs: object) -> dict:
        return self._ok("strm-verify", expected=kwargs)

    def scrape_mp_strm(self, *args: object, **kwargs: object) -> dict:
        return self._ok("mp-scrape-strm-result", args=list(args), kwargs=kwargs)

    def audit_nfo_language(self, **kwargs: object) -> dict:
        return self._ok("strm-nfo-language-audit", expected=kwargs)

    def emby_media_updated(self, *args: object, **kwargs: object) -> dict:
        return self._ok("emby-media-updated", args=list(args), kwargs=kwargs)

    def cleanup_preview(self, **kwargs: object) -> dict:
        return self._ok(
            "cloud-hlink-cleanup-preview",
            expected={
                "tmdbid": kwargs.get("expected_tmdbid"),
                "cloud_media_path": kwargs.get("cloud_media_path"),
            },
            hlink={"path": kwargs.get("hlink_root")},
            qbittorrent={"hashes": ["abcdef123456"], "matched_count": 1},
        )

    def cleanup_execute(self, *args: object, **kwargs: object) -> dict:
        return self._ok("cloud-hlink-cleanup-execute", args=list(args), kwargs=kwargs)


class BatchRunnerTest(unittest.TestCase):
    def _finalize_plan(self) -> dict:
        return {
            "mode": "readonly-batch-finalize-plan",
            "items": [
                {
                    "status": "planned_finalize",
                    "title": "折腰",
                    "tmdbid": 296753,
                    "season": 1,
                    "expected_episode_count": 36,
                    "expected_episodes": list(range(1, 37)),
                    "hlink_root": "/volume3/volume3/hlink/TV/折腰 (2025)/Season 1",
                    "strm_root": "/volume4/volume4/mv3/strm/series/折腰 (2025) {tmdbid=296753}/Season 1",
                    "service_strm_root": "/volume4/mv3/strm/series/折腰 (2025) {tmdbid=296753}/Season 1",
                    "cloud_title_path": "/已整理/series/折腰 (2025) {tmdbid=296753}",
                    "required_target_prefix": "/已整理/series/折腰 (2025) {tmdbid=296753}",
                    "forbidden_target_prefixes": ["/未整理", "/series/series"],
                    "command_context": {"report_prefix": "zheyao-296753-s01"},
                }
            ],
        }

    def test_batch_finalize_plan_builds_ordered_post_transfer_gates(self) -> None:
        batch_plan = {
            "mode": "readonly-batch-state-plan",
            "settings": {
                "cloud_root": "/已整理/series",
                "host_strm_root": "/volume4/volume4/mv3/strm",
                "emby_strm_root": "/volume4/mv3/strm",
                "forbidden_target_prefixes": ["/未整理"],
            },
            "items": [
                {
                    "bucket": MANUAL_REVIEW,
                    "title": "折腰",
                    "tmdbid": 296753,
                    "season": 1,
                    "expected_episode_count": 36,
                    "source_paths": ["/volume3/volume3/hlink/TV/折腰 (2025)/Season 1"],
                    "cloud_media_path": "/已整理/series/折腰 (2025) {tmdbid=296753}/Season 1",
                    "strm_root": "/volume4/volume4/mv3/strm/series/折腰 (2025) {tmdbid=296753}/Season 1",
                }
            ],
        }

        report = build_batch_finalize_plan(batch_plan, env_file="/safe/.env")

        self.assertEqual(report["mode"], "readonly-batch-finalize-plan")
        self.assertEqual(report["finalize_ready_items"], 1)
        item = report["items"][0]
        self.assertEqual(item["status"], "planned_finalize")
        self.assertEqual(item["service_strm_root"], "/volume4/mv3/strm/series/折腰 (2025) {tmdbid=296753}/Season 1")
        self.assertEqual(item["cloud_title_path"], "/已整理/series/折腰 (2025) {tmdbid=296753}")
        stages = [command["stage"] for command in item["commands"]]
        self.assertEqual(
            stages,
            [
                "strm_verify",
                "mp_scrape_strm",
                "strm_nfo_language_audit",
                "emby_media_updated_verify",
                "cloud_hlink_cleanup_preview",
                "cloud_hlink_cleanup_execute_approval_required",
            ],
        )
        commands = "\n".join(command["command"] for command in item["commands"])
        self.assertIn("--mp-path '/volume4/mv3/strm/series/折腰 (2025) {tmdbid=296753}/Season 1'", commands)
        self.assertIn("--cloud-media-path '/已整理/series/折腰 (2025) {tmdbid=296753}'", commands)
        self.assertIn("# approval required before execution", commands)
        self.assertNotIn("--approve-delete", commands)
        self.assertIn("<full-qb-hash-from-cleanup-preview>", commands)
        rendered = render_batch_finalize_plan(report, "markdown")
        self.assertIn("Batch Finalize Plan", rendered)
        self.assertIn("折腰", rendered)

    def test_cli_writes_batch_finalize_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            batch = tmp_path / "batch.json"
            output = tmp_path / "finalize.json"
            batch.write_text(
                json.dumps(
                    {
                        "mode": "readonly-batch-state-plan",
                        "settings": {
                            "cloud_root": "/已整理/series",
                            "host_strm_root": "/volume4/volume4/mv3/strm",
                            "emby_strm_root": "/volume4/mv3/strm",
                        },
                        "items": [
                            {
                                "bucket": MANUAL_REVIEW,
                                "title": "折腰",
                                "tmdbid": 296753,
                                "season": 1,
                                "expected_episode_count": 36,
                                "source_paths": ["/volume3/volume3/hlink/TV/折腰 (2025)/Season 1"],
                                "cloud_media_path": "/已整理/series/折腰 (2025) {tmdbid=296753}/Season 1",
                                "strm_root": "/volume4/volume4/mv3/strm/series/折腰 (2025) {tmdbid=296753}/Season 1",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "batch-finalize-plan",
                    "--env-file",
                    "/safe/.env",
                    "--batch-plan",
                    str(batch),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(data["finalize_ready_items"], 1)
        self.assertIn("cloud_hlink_cleanup_preview", [item["stage"] for item in data["items"][0]["commands"]])

    def test_batch_finalize_run_default_waits_for_delete_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actions = FinalizeFakeActions()
            report = run_batch_finalize(
                self._finalize_plan(),
                output_dir=tmp,
                config=FinalizeFakeConfig(path_aliases={}),
                execute_scrape=True,
                approve_delete=False,
                actions=BatchFinalizeActions(
                    verify_strm=actions.verify_strm,
                    scrape_mp_strm=actions.scrape_mp_strm,
                    audit_nfo_language=actions.audit_nfo_language,
                    emby_media_updated=actions.emby_media_updated,
                    cleanup_preview=actions.cleanup_preview,
                    cleanup_execute=actions.cleanup_execute,
                ),
            )
            stage_files = sorted(Path(tmp).glob("*.json"))

        self.assertTrue(report["ok"])
        self.assertEqual(report["items"][0]["status"], "cleanup_waiting_for_approval")
        self.assertNotIn("cloud-hlink-cleanup-execute", [call[0] for call in actions.calls])
        self.assertEqual(len(stage_files), 5)
        rendered = render_batch_finalize_run(report, "markdown")
        self.assertIn("Batch Finalize Run", rendered)
        self.assertIn("cleanup_waiting_for_approval", rendered)

    def test_batch_finalize_run_gate_failure_stops_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actions = FinalizeFakeActions(fail_stage="strm-nfo-language-audit")
            report = run_batch_finalize(
                self._finalize_plan(),
                output_dir=tmp,
                config=FinalizeFakeConfig(path_aliases={}),
                execute_scrape=True,
                approve_delete=True,
                actions=BatchFinalizeActions(
                    verify_strm=actions.verify_strm,
                    scrape_mp_strm=actions.scrape_mp_strm,
                    audit_nfo_language=actions.audit_nfo_language,
                    emby_media_updated=actions.emby_media_updated,
                    cleanup_preview=actions.cleanup_preview,
                    cleanup_execute=actions.cleanup_execute,
                ),
            )

        self.assertFalse(report["ok"])
        self.assertTrue(report["halted"])
        self.assertEqual(report["items"][0]["status"], "failed_nfo_language")
        self.assertNotIn("emby-media-updated", [call[0] for call in actions.calls])
        self.assertNotIn("cloud-hlink-cleanup-execute", [call[0] for call in actions.calls])

    def test_batch_finalize_run_requires_delete_approval_to_execute_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actions = FinalizeFakeActions()
            report = run_batch_finalize(
                self._finalize_plan(),
                output_dir=tmp,
                config=FinalizeFakeConfig(path_aliases={}),
                execute_scrape=True,
                approve_delete=True,
                actions=BatchFinalizeActions(
                    verify_strm=actions.verify_strm,
                    scrape_mp_strm=actions.scrape_mp_strm,
                    audit_nfo_language=actions.audit_nfo_language,
                    emby_media_updated=actions.emby_media_updated,
                    cleanup_preview=actions.cleanup_preview,
                    cleanup_execute=actions.cleanup_execute,
                ),
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["items"][0]["status"], "cleanup_executed")
        self.assertIn("cloud-hlink-cleanup-execute", [call[0] for call in actions.calls])

    def test_batch_finalize_run_uses_strm_paths_for_scrape_and_cloud_path_only_for_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actions = FinalizeFakeActions()
            run_batch_finalize(
                self._finalize_plan(),
                output_dir=tmp,
                config=FinalizeFakeConfig(path_aliases={}),
                execute_scrape=True,
                approve_delete=False,
                actions=BatchFinalizeActions(
                    verify_strm=actions.verify_strm,
                    scrape_mp_strm=actions.scrape_mp_strm,
                    audit_nfo_language=actions.audit_nfo_language,
                    emby_media_updated=actions.emby_media_updated,
                    cleanup_preview=actions.cleanup_preview,
                    cleanup_execute=actions.cleanup_execute,
                ),
            )

        scrape_call = next(call for call in actions.calls if call[0] == "mp-scrape-strm-result")
        self.assertEqual(scrape_call[1]["kwargs"]["strm_path"], "/volume4/volume4/mv3/strm/series/折腰 (2025) {tmdbid=296753}/Season 1")
        self.assertEqual(scrape_call[1]["kwargs"]["mp_path"], "/volume4/mv3/strm/series/折腰 (2025) {tmdbid=296753}/Season 1")
        self.assertNotIn("/已整理", scrape_call[1]["kwargs"]["strm_path"])
        cleanup_call = next(call for call in actions.calls if call[0] == "cloud-hlink-cleanup-preview")
        self.assertEqual(cleanup_call[1]["expected"]["cloud_media_path"], "/已整理/series/折腰 (2025) {tmdbid=296753}")

    def test_cli_writes_batch_finalize_run_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "QB_BASE_URL=http://qb.local",
                        "MP_BASE_URL=http://mp.local",
                        "MP_API_TOKEN=token",
                        "EMBY_BASE_URL=http://emby.local",
                        "EMBY_API_KEY=emby",
                    ]
                ),
                encoding="utf-8",
            )
            plan = tmp_path / "finalize.json"
            output = tmp_path / "run.json"
            stages = tmp_path / "stages"
            bad_plan = self._finalize_plan()
            bad_plan["items"][0]["strm_root"] = str(tmp_path / "missing-strm")
            plan.write_text(json.dumps(bad_plan, ensure_ascii=False), encoding="utf-8")
            exit_code = main(
                [
                    "batch-finalize-run",
                    "--env-file",
                    str(env_file),
                    "--finalize-plan",
                    str(plan),
                    "--output-dir",
                    str(stages),
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )
            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 1)
        self.assertEqual(data["items"][0]["status"], "failed_strm_verify")

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


class BatchSharePreviewTest(unittest.TestCase):
    def test_builds_dry_run_preview_plan_for_episode_unclear_candidate(self) -> None:
        batch_plan = {
            "mode": "readonly-batch-state-plan",
            "items": [
                {
                    "bucket": MANUAL_REVIEW,
                    "title": "折腰 (2025) {tmdbid=246}",
                    "tmdbid": 246,
                    "season": 1,
                    "expected_episode_count": 36,
                    "expected_episodes": list(range(1, 37)),
                    "candidate_diagnostics": {
                        "best_candidate": {
                            "search_index": 4,
                            "search_keyword": "折腰",
                            "title": "名称: 折腰 (2025) 4K",
                            "score": 65,
                            "size_delta_ratio": 0.24,
                            "blockers": ["episode_coverage_unclear"],
                        }
                    },
                },
                {
                    "bucket": MANUAL_REVIEW,
                    "title": "怪奇物语",
                    "tmdbid": 66732,
                    "season": 4,
                    "expected_episode_count": 9,
                    "candidate_diagnostics": {
                        "best_candidate": {
                            "search_index": 8,
                            "search_keyword": "怪奇物语 Season 04",
                            "title": "怪奇物语：1985故事集 S01E01-E10",
                            "score": 80,
                            "blockers": ["season_mismatch"],
                        }
                    },
                },
            ],
        }

        report = build_batch_share_preview_plan(batch_plan, env_file="/safe/.env", limit=10)

        self.assertEqual(report["executable_preview_items"], 1)
        ready = report["items"][0]
        blocked = report["items"][1]
        self.assertEqual(ready["status"], "planned_preview")
        self.assertIn("mv3-share-preview", ready["command"])
        self.assertIn("--expected-episode 1,2,3", ready["command"])
        self.assertEqual(blocked["status"], "skipped_preview")
        self.assertIn("best_candidate_blocked:season_mismatch", blocked["skip_reasons"])
        rendered = render_batch_share_preview_report(report, "markdown")
        self.assertIn("Batch MV3 Share Preview", rendered)
        self.assertIn("折腰", rendered)

    def test_execute_preview_calls_readonly_preview_func_and_writes_reports(self) -> None:
        batch_plan = {
            "mode": "readonly-batch-state-plan",
            "items": [
                {
                    "bucket": MANUAL_REVIEW,
                    "title": "巅峰对决",
                    "tmdbid": 111,
                    "season": 1,
                    "expected_episode_count": 4,
                    "candidate_diagnostics": {
                        "best_candidate": {
                            "search_index": 3,
                            "search_keyword": "巅峰对决",
                            "title": "巅峰对决 S01E04",
                            "score": 65,
                            "blockers": ["episode_coverage_unclear"],
                        }
                    },
                }
            ],
        }
        calls = []

        def fake_preview(base_url, token, keyword, **kwargs):
            calls.append((base_url, token, keyword, kwargs))
            return {
                "ok": True,
                "episode_count": 4,
                "episodes": [1, 2, 3, 4],
                "blockers": [],
                "missing_expected": [],
                "unexpected_episodes": [],
            }

        with tempfile.TemporaryDirectory() as tmp:
            report = build_batch_share_preview_plan(
                batch_plan,
                execute_preview=True,
                base_url="http://mv3.example",
                token="token",
                preview_func=fake_preview,
                preview_output_dir=tmp,
            )
            written = list(Path(tmp).glob("share-preview-111-s01-*.json"))

        self.assertEqual(report["executed_preview_items"], 1)
        self.assertEqual(report["ready_for_receive_items"], 1)
        self.assertEqual(report["items"][0]["status"], "preview_ready_for_receive")
        self.assertEqual(report["items"][0]["preview_episode_count"], 4)
        self.assertEqual(calls[0][2], "巅峰对决")
        self.assertEqual(calls[0][3]["selection_index"], 3)
        self.assertEqual(calls[0][3]["expected_episode_count"], 4)
        self.assertEqual(len(written), 1)

    def test_execute_preview_auto_enters_single_nested_folder(self) -> None:
        batch_plan = {
            "mode": "readonly-batch-state-plan",
            "items": [
                {
                    "bucket": MANUAL_REVIEW,
                    "title": "折腰",
                    "tmdbid": 246,
                    "season": 1,
                    "expected_episode_count": 2,
                    "candidate_diagnostics": {
                        "best_candidate": {
                            "search_index": 2,
                            "search_keyword": "折腰",
                            "title": "名称: 折腰 (2025) 4K",
                            "score": 65,
                            "blockers": ["episode_coverage_unclear"],
                        }
                    },
                }
            ],
        }
        calls = []

        def fake_preview(base_url, token, keyword, **kwargs):
            calls.append(kwargs)
            if not kwargs.get("browse_cid"):
                return {
                    "ok": False,
                    "episode_count": 0,
                    "blockers": ["episode_count_mismatch"],
                    "missing_expected": [1, 2],
                    "unexpected_episodes": [],
                    "browse": {
                        "ok": True,
                        "item_count": 1,
                        "items": [
                            {
                                "kind": "folder",
                                "name": "折腰 (2025)",
                                "file_id": "folder-1",
                            }
                        ],
                    },
                }
            if kwargs.get("browse_cid") == "folder-1":
                return {
                    "ok": False,
                    "episode_count": 0,
                    "blockers": ["episode_count_mismatch"],
                    "missing_expected": [1, 2],
                    "unexpected_episodes": [],
                    "browse": {
                        "ok": True,
                        "item_count": 3,
                        "items": [
                            {
                                "kind": "folder",
                                "media_kind": "folder",
                                "name": "Season 1",
                                "file_id": "season-1",
                            },
                            {
                                "kind": "file",
                                "media_kind": "metadata_sidecar",
                                "name": "poster.jpg",
                                "file_id": "poster",
                            },
                            {
                                "kind": "file",
                                "media_kind": "metadata_sidecar",
                                "name": "tvshow.nfo",
                                "file_id": "nfo",
                            },
                        ],
                    },
                }
            return {
                "ok": True,
                "episode_count": 2,
                "episodes": [1, 2],
                "blockers": [],
                "missing_expected": [],
                "unexpected_episodes": [],
                "browse_cid": kwargs.get("browse_cid"),
            }

        report = build_batch_share_preview_plan(
            batch_plan,
            execute_preview=True,
            base_url="http://mv3.example",
            token="token",
            preview_func=fake_preview,
        )

        item = report["items"][0]
        self.assertEqual(report["ready_for_receive_items"], 1)
        self.assertEqual(item["status"], "preview_ready_for_receive")
        self.assertEqual(item["nested_preview_cid"], "season-1")
        self.assertEqual(len(item["nested_previews"]), 2)
        self.assertEqual(item["root_preview_report"]["episode_count"], 0)
        self.assertEqual(calls[0].get("browse_cid"), "")
        self.assertEqual(calls[1].get("browse_cid"), "folder-1")
        self.assertEqual(calls[2].get("browse_cid"), "season-1")

    def test_receive_plan_uses_verified_nested_folder_preview(self) -> None:
        preview_report = {
            "mode": "readonly-batch-mv3-share-preview",
            "items": [
                {
                    "status": "preview_ready_for_receive",
                    "title": "折腰",
                    "tmdbid": 296753,
                    "season": 1,
                    "keyword": "折腰",
                    "selection_index": 2,
                    "expected_episode_count": 36,
                    "expected_episode_min": 1,
                    "expected_episode_max": 36,
                    "expected_title_contains": "折腰",
                    "preview_report_path": "/reports/share-preview-zheyao.json",
                    "nested_previews": [
                        {"depth": 1, "cid": "series-folder", "index": "1", "folder_name": "折腰 (2025)", "ok": False},
                        {"depth": 2, "cid": "season-folder", "index": "1", "folder_name": "Season 1", "ok": True},
                    ],
                },
                {
                    "status": "preview_blocked",
                    "title": "一饭封神",
                    "tmdbid": 296217,
                    "season": 1,
                    "preview_blockers": ["episode_count_mismatch"],
                },
            ],
        }

        plan = build_batch_share_receive_plan(
            preview_report,
            env_file="/safe/.env",
            target_path="/未整理",
        )

        ready = plan["items"][0]
        skipped = plan["items"][1]
        self.assertEqual(plan["approval_required_items"], 1)
        self.assertEqual(ready["status"], "approval_required")
        self.assertEqual(ready["receive_mode"], "receive_selected_folder")
        self.assertEqual(ready["browse_cid"], "series-folder")
        self.assertEqual(ready["browse_index"], 1)
        self.assertEqual(ready["verified_folder_browse_report"], "/reports/share-preview-zheyao.json")
        self.assertIn("--receive-selected-folder", ready["command"])
        self.assertIn("--browse-cid series-folder", ready["command"])
        self.assertIn("--verified-folder-browse-report /reports/share-preview-zheyao.json", ready["command"])
        self.assertNotIn("--approve-receive", ready["command"])
        self.assertIn("approval required", ready["command"])
        self.assertEqual(skipped["status"], "skipped_receive")
        self.assertIn("preview_not_ready_for_receive", skipped["skip_reasons"])

        rendered = render_batch_share_receive_plan(plan, "markdown")
        self.assertIn("Batch MV3 Share Receive Plan", rendered)
        self.assertIn("折腰", rendered)
