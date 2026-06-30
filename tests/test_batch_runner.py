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
    build_batch_review_report,
    merge_share_search_plans,
    render_batch_finalize_plan,
    render_batch_finalize_run,
    render_batch_plan,
    render_batch_review_report,
    run_batch_finalize,
)
from series_cloud_archiver.batch_preview import (
    build_batch_share_preview_plan,
    build_batch_share_receive_plan,
    render_batch_share_preview_report,
    render_batch_share_receive_plan,
)
from series_cloud_archiver.batch_transfer import (
    BatchTransferActions,
    render_batch_transfer_run,
    run_batch_transfer,
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
        self.cloud_duplicate_count = 0

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

    def cloud_duplicate_cleanup(self, *args: object, **kwargs: object) -> dict:
        report = self._ok(
            "mv3-cloud-duplicate-video-cleanup-result",
            args=list(args),
            kwargs=kwargs,
            delete_plan={
                "duplicate_video_count": self.cloud_duplicate_count,
                "expected_delete_count": kwargs.get("expected_delete_count"),
            },
            summary={
                "video_file_count": 36 + self.cloud_duplicate_count,
                "episode_count": 36,
                "duplicate_episodes": list(range(1, self.cloud_duplicate_count + 1)),
            },
        )
        if kwargs.get("approve_delete"):
            self.cloud_duplicate_count = 0
        return report

    def scrape_mp_strm(self, *args: object, **kwargs: object) -> dict:
        return self._ok("mp-scrape-strm-result", args=list(args), kwargs=kwargs)

    def audit_nfo_language(self, **kwargs: object) -> dict:
        return self._ok("strm-nfo-language-audit", expected=kwargs)

    def emby_media_updated(self, *args: object, **kwargs: object) -> dict:
        return self._ok("emby-media-updated", args=list(args), kwargs=kwargs)

    def emby_delete_stale(self, *args: object, **kwargs: object) -> dict:
        return self._ok(
            "emby-delete-stale-paths",
            args=list(args),
            kwargs=kwargs,
            delete_results=[
                {
                    "id": f"emby-{len([call for call in self.calls if call[0] == 'emby-delete-stale-paths'])}",
                    "path": (kwargs.get("stale_path_prefixes") or [""])[0],
                    "ok": True,
                }
            ],
        )

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


class TransferFakeActions:
    def __init__(
        self,
        duplicate_after_organize: bool = False,
        staging_remains: bool = False,
        organized_title_with_year: bool = False,
        organize_fails_after_side_effect: bool = False,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.duplicate_after_organize = duplicate_after_organize
        self.staging_remains = staging_remains
        self.organized_title_with_year = organized_title_with_year
        self.organize_fails_after_side_effect = organize_fails_after_side_effect
        self.organized = False

    def receive_share(self, *args: object, **kwargs: object) -> dict:
        self.calls.append(("receive", {"args": list(args), "kwargs": kwargs}))
        return {
            "mode": "mv3-share-receive-one-result",
            "ok": True,
            "warnings": [],
            "target_path": kwargs.get("target_path"),
            "browse_selection": {"name": "折腰"},
        }

    def browse_cloud(self, *args: object, **kwargs: object) -> dict:
        self.calls.append(("browse", {"args": list(args), "kwargs": kwargs}))
        path = str(kwargs.get("path") or "")
        if path == "/已整理/series":
            return {
                "mode": "readonly-mv3-cloud-browse",
                "ok": True,
                "path": path,
                "summary": {
                    "video_file_count": 0,
                    "metadata_sidecar_file_count": 0,
                },
                "items": [
                    {
                        "kind": "folder",
                        "media_kind": "unknown",
                        "name": "折腰 (2025) {tmdbid=296753}",
                        "file_id": "title-folder",
                    }
                ],
                "warnings": [],
            }
        if self.organized_title_with_year and path == "/已整理/series/折腰 {tmdbid=296753}/Season 1":
            return {
                "mode": "readonly-mv3-cloud-browse",
                "ok": False,
                "path": path,
                "summary": {
                    "video_file_count": 0,
                    "metadata_sidecar_file_count": 0,
                },
                "items": [],
                "warnings": ["path_info_not_found"],
            }
        if path.startswith("/已整理/"):
            episodes = list(range(1, 37))
            if self.duplicate_after_organize:
                episodes = sorted(episodes + [33])
            return {
                "mode": "readonly-mv3-cloud-browse",
                "ok": True,
                "path": path,
                "summary": {
                    "video_file_count": len(episodes),
                    "metadata_sidecar_file_count": 0,
                },
                "items": [
                    {
                        "kind": "file",
                        "media_kind": "video",
                        "name": f"折腰 - S01E{episode:02d}.mkv",
                        "episode": episode,
                        "file_id": f"organized-{index}",
                    }
                    for index, episode in enumerate(episodes, start=1)
                ],
                "warnings": [],
            }
        if path.startswith("/未整理/") and self.organized and not self.staging_remains:
            return {
                "mode": "readonly-mv3-cloud-browse",
                "ok": False,
                "path": path,
                "summary": {
                    "video_file_count": 0,
                    "metadata_sidecar_file_count": 0,
                },
                "items": [],
                "warnings": ["path_info_not_found"],
            }
        if path.startswith("/未整理/") and self.organized and self.staging_remains:
            return {
                "mode": "readonly-mv3-cloud-browse",
                "ok": True,
                "path": path,
                "summary": {
                    "video_file_count": 1,
                    "metadata_sidecar_file_count": 0,
                },
                "items": [
                    {
                        "kind": "file",
                        "media_kind": "video",
                        "name": "折腰 - S01E33.mkv",
                        "episode": 33,
                        "file_id": "staging-leftover",
                    }
                ],
                "warnings": [],
            }
        return {
            "mode": "readonly-mv3-cloud-browse",
            "ok": True,
            "path": path,
            "summary": {
                "video_file_count": 36,
                "metadata_sidecar_file_count": 0,
            },
            "items": [
                {
                    "kind": "file",
                    "media_kind": "video",
                    "name": f"折腰 - S01E{episode:02d}.mkv",
                    "file_id": f"file-{episode}",
                }
                for episode in range(1, 37)
            ],
            "warnings": [],
        }

    def organize_transfer(self, *args: object, **kwargs: object) -> dict:
        self.calls.append(("organize", {"args": list(args), "kwargs": kwargs}))
        self.organized = True
        if self.organize_fails_after_side_effect:
            return {
                "mode": "mv3-organize-transfer-result",
                "ok": False,
                "source_path": "/未整理/折腰",
                "target_dir": kwargs.get("target_dir"),
                "strm_dir": kwargs.get("strm_dir"),
                "blockers": ["mv3_transfer_request_failed"],
                "warnings": ["mv3_transfer_request_failed:timeout:timed out"],
            }
        return {
            "mode": "mv3-organize-transfer-result",
            "ok": True,
            "source_path": "/未整理/折腰",
            "target_dir": kwargs.get("target_dir"),
            "strm_dir": kwargs.get("strm_dir"),
            "blockers": [],
            "warnings": [],
        }


def _batch_finalize_actions(actions: FinalizeFakeActions) -> BatchFinalizeActions:
    return BatchFinalizeActions(
        verify_strm=actions.verify_strm,
        cloud_duplicate_cleanup=actions.cloud_duplicate_cleanup,
        scrape_mp_strm=actions.scrape_mp_strm,
        audit_nfo_language=actions.audit_nfo_language,
        emby_media_updated=actions.emby_media_updated,
        emby_delete_stale=actions.emby_delete_stale,
        cleanup_preview=actions.cleanup_preview,
        cleanup_execute=actions.cleanup_execute,
    )


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
                    "hlink_root": "/example/local-tv/折腰 (2025)/Season 1",
                    "strm_root": "/example/host/strm/series/折腰 (2025) {tmdbid=296753}/Season 1",
                    "service_strm_root": "/example/service/strm/series/折腰 (2025) {tmdbid=296753}/Season 1",
                    "cloud_title_path": "/已整理/series/折腰 (2025) {tmdbid=296753}",
                    "required_target_prefix": "/已整理/series/折腰 (2025) {tmdbid=296753}",
                    "forbidden_target_prefixes": ["/未整理", "/series/series"],
                    "command_context": {"report_prefix": "zheyao-296753-s01"},
                }
            ],
        }

    def _receive_plan(self, preview_report_path: str = "/tmp/preview.json") -> dict:
        return {
            "mode": "readonly-batch-mv3-share-receive-plan",
            "items": [
                {
                    "status": "approval_required",
                    "title": "折腰",
                    "tmdbid": 296753,
                    "season": 1,
                    "keyword": "折腰",
                    "selection_index": 2,
                    "browse_cid": "parent-cid",
                    "browse_index": 1,
                    "receive_mode": "receive_selected_folder",
                    "verified_folder_browse_report": preview_report_path,
                    "target_path": "/未整理",
                    "storage": "115-default",
                    "expected_episode_count": 36,
                    "expected_episode_min": 1,
                    "expected_episode_max": 36,
                    "expected_title_contains": "折腰",
                }
            ],
        }

    def test_batch_transfer_run_default_requires_receive_approval(self) -> None:
        actions = TransferFakeActions()
        with tempfile.TemporaryDirectory() as tmp:
            report = run_batch_transfer(
                self._receive_plan(),
                output_dir=tmp,
                config=FinalizeFakeConfig(),
                actions=BatchTransferActions(
                    receive_share=actions.receive_share,
                    browse_cloud=actions.browse_cloud,
                    organize_transfer=actions.organize_transfer,
                ),
            )

        self.assertEqual(report["planned_items"], 1)
        self.assertFalse(report["ok"])
        self.assertEqual(report["dry_run_items"], 1)
        self.assertEqual(actions.calls, [])
        self.assertEqual(report["items"][0]["status"], "approval_required")
        self.assertIn("receive_approval_required", report["items"][0]["blockers"])
        self.assertIn("Batch Transfer Run", render_batch_transfer_run(report, "markdown"))

    def test_batch_transfer_run_receives_browses_and_organizes_after_approval(self) -> None:
        actions = TransferFakeActions()
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview.json"
            preview.write_text(
                json.dumps({"ok": True, "episodes": list(range(1, 37)), "video_file_count": 36}),
                encoding="utf-8",
            )
            report = run_batch_transfer(
                self._receive_plan(str(preview)),
                output_dir=tmp,
                config=FinalizeFakeConfig(),
                approve_receive=True,
                approve_transfer=True,
                actions=BatchTransferActions(
                    receive_share=actions.receive_share,
                    browse_cloud=actions.browse_cloud,
                    organize_transfer=actions.organize_transfer,
                ),
            )
            stage_files = [
                path
                for path in Path(tmp).glob("*.json")
                if path.name != "preview.json"
            ]

        self.assertTrue(report["ok"])
        self.assertEqual(report["received_items"], 1)
        self.assertEqual(report["organized_items"], 1)
        self.assertEqual([call[0] for call in actions.calls], ["receive", "browse", "organize", "browse", "browse"])
        self.assertEqual(actions.calls[0][1]["kwargs"]["target_path"], "/未整理")
        self.assertEqual(actions.calls[1][1]["kwargs"]["path"], "/未整理/折腰")
        self.assertEqual(actions.calls[2][1]["kwargs"]["target_dir"], "/已整理")
        self.assertEqual(actions.calls[2][1]["kwargs"]["strm_dir"], "/strm")
        self.assertEqual(actions.calls[3][1]["kwargs"]["path"], "/已整理/series/折腰 {tmdbid=296753}/Season 1")
        self.assertEqual(actions.calls[4][1]["kwargs"]["path"], "/未整理/折腰")
        self.assertEqual(report["items"][0]["status"], "organized_requires_finalize")
        self.assertEqual(len(stage_files), 5)

    def test_batch_transfer_run_recovers_when_organize_times_out_but_post_verify_passes(self) -> None:
        actions = TransferFakeActions(organize_fails_after_side_effect=True)
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview.json"
            preview.write_text(
                json.dumps({"ok": True, "episodes": list(range(1, 37)), "video_file_count": 36}),
                encoding="utf-8",
            )
            report = run_batch_transfer(
                self._receive_plan(str(preview)),
                output_dir=tmp,
                config=FinalizeFakeConfig(),
                approve_receive=True,
                approve_transfer=True,
                actions=BatchTransferActions(
                    receive_share=actions.receive_share,
                    browse_cloud=actions.browse_cloud,
                    organize_transfer=actions.organize_transfer,
                ),
            )

        item = report["items"][0]
        self.assertTrue(report["ok"])
        self.assertEqual(report["organized_items"], 1)
        self.assertEqual(item["status"], "organized_requires_finalize")
        self.assertFalse(item["organize_request_ok"])
        self.assertTrue(item["organize_ok"])
        self.assertTrue(item["organize_recovered_after_request_failure"])
        self.assertTrue(item["post_verify_ok"])
        self.assertIn("mv3_transfer_request_failed", item["warnings"])

    def test_batch_transfer_run_resolves_organized_folder_by_tmdbid_when_year_is_added(self) -> None:
        actions = TransferFakeActions(organized_title_with_year=True)
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview.json"
            preview.write_text(
                json.dumps({"ok": True, "episodes": list(range(1, 37)), "video_file_count": 36}),
                encoding="utf-8",
            )
            report = run_batch_transfer(
                self._receive_plan(str(preview)),
                output_dir=tmp,
                config=FinalizeFakeConfig(),
                approve_receive=True,
                approve_transfer=True,
                actions=BatchTransferActions(
                    receive_share=actions.receive_share,
                    browse_cloud=actions.browse_cloud,
                    organize_transfer=actions.organize_transfer,
                ),
            )

        browse_paths = [call[1]["kwargs"]["path"] for call in actions.calls if call[0] == "browse"]
        self.assertTrue(report["ok"])
        self.assertEqual(report["items"][0]["organized_verify_path"], "/已整理/series/折腰 (2025) {tmdbid=296753}/Season 1")
        self.assertIn("/已整理/series", browse_paths)
        self.assertIn("/已整理/series/折腰 (2025) {tmdbid=296753}/Season 1", browse_paths)

    def test_batch_transfer_run_blocks_duplicate_organized_files_and_staging_leftovers(self) -> None:
        actions = TransferFakeActions(duplicate_after_organize=True, staging_remains=True)
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview.json"
            preview.write_text(
                json.dumps({"ok": True, "episodes": list(range(1, 37)), "video_file_count": 36}),
                encoding="utf-8",
            )
            report = run_batch_transfer(
                self._receive_plan(str(preview)),
                output_dir=tmp,
                config=FinalizeFakeConfig(),
                approve_receive=True,
                approve_transfer=True,
                actions=BatchTransferActions(
                    receive_share=actions.receive_share,
                    browse_cloud=actions.browse_cloud,
                    organize_transfer=actions.organize_transfer,
                ),
            )

        item = report["items"][0]
        self.assertFalse(report["ok"])
        self.assertEqual(item["status"], "failed_post_organize_verify")
        self.assertIn("organized_duplicate_episodes_present", item["blockers"])
        self.assertIn("organized_video_file_count_mismatch", item["blockers"])
        self.assertIn("staging_video_files_remain", item["blockers"])

    def test_batch_finalize_plan_builds_ordered_post_transfer_gates(self) -> None:
        batch_plan = {
            "mode": "readonly-batch-state-plan",
            "settings": {
                "cloud_root": "/已整理/series",
                "host_strm_root": "/example/host/strm",
                "emby_strm_root": "/example/service/strm",
                "forbidden_target_prefixes": ["/未整理"],
            },
            "items": [
                {
                    "bucket": AUTO_CLEANUP,
                    "title": "折腰",
                    "tmdbid": 296753,
                    "season": 1,
                    "expected_episode_count": 36,
                    "source_paths": ["/example/local-tv/折腰 (2025)/Season 1"],
                    "cloud_media_path": "/已整理/series/折腰 (2025) {tmdbid=296753}/Season 1",
                    "strm_root": "/example/host/strm/series/折腰 (2025) {tmdbid=296753}/Season 1",
                }
            ],
        }

        report = build_batch_finalize_plan(batch_plan, env_file="/safe/.env")

        self.assertEqual(report["mode"], "readonly-batch-finalize-plan")
        self.assertEqual(report["finalize_ready_items"], 1)
        item = report["items"][0]
        self.assertEqual(item["status"], "planned_finalize")
        self.assertEqual(item["service_strm_root"], "/example/service/strm/series/折腰 (2025) {tmdbid=296753}/Season 1")
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
        self.assertIn("--mp-path '/example/service/strm/series/折腰 (2025) {tmdbid=296753}/Season 1'", commands)
        self.assertIn("--cloud-media-path '/已整理/series/折腰 (2025) {tmdbid=296753}'", commands)
        self.assertIn("# approval required before execution", commands)
        self.assertNotIn("--approve-delete", commands)
        self.assertIn("<full-qb-hash-from-cleanup-preview>", commands)
        rendered = render_batch_finalize_plan(report, "markdown")
        self.assertIn("Batch Finalize Plan", rendered)
        self.assertIn("折腰", rendered)

    def test_batch_finalize_plan_prefers_strm_derived_cloud_prefix(self) -> None:
        batch_plan = {
            "mode": "readonly-batch-state-plan",
            "settings": {
                "cloud_root": "/已整理/series",
                "host_strm_root": "/example/host/strm",
                "emby_strm_root": "/example/service/strm",
            },
            "items": [
                {
                    "bucket": AUTO_CLEANUP,
                    "title": "兄弟连",
                    "tmdbid": 4613,
                    "season": 1,
                    "expected_episode_count": 10,
                    "source_paths": ["/example/local-tv/兄弟连 (2001) {tmdbid=4613}/Season 01"],
                    "cloud_media_path": "/已整理/series/兄弟连 {tmdbid=4613}/Season 01",
                    "strm_root": "/example/host/strm/series/兄弟连 (2001) {tmdbid=4613}/Season 1",
                }
            ],
        }

        report = build_batch_finalize_plan(batch_plan, env_file="/safe/.env")
        item = report["items"][0]

        self.assertEqual(item["cloud_title_path"], "/已整理/series/兄弟连 (2001) {tmdbid=4613}")
        self.assertEqual(item["required_target_prefix"], "/已整理/series/兄弟连 (2001) {tmdbid=4613}/Season 1")

    def test_batch_finalize_plan_skips_manual_review_items(self) -> None:
        batch_plan = {
            "mode": "readonly-batch-state-plan",
            "settings": {
                "cloud_root": "/已整理/series",
                "host_strm_root": "/example/host/strm",
                "emby_strm_root": "/example/service/strm",
            },
            "items": [
                {
                    "bucket": MANUAL_REVIEW,
                    "title": "折腰",
                    "tmdbid": 296753,
                    "season": 1,
                    "expected_episode_count": 36,
                    "source_paths": ["/example/local-tv/折腰 (2025)/Season 1"],
                    "cloud_media_path": "/已整理/series/折腰 (2025) {tmdbid=296753}/Season 1",
                    "strm_root": "/example/host/strm/series/折腰 (2025) {tmdbid=296753}/Season 1",
                }
            ],
        }

        report = build_batch_finalize_plan(batch_plan, env_file="/safe/.env")
        item = report["items"][0]

        self.assertEqual(report["finalize_ready_items"], 0)
        self.assertEqual(item["status"], "skipped_finalize")
        self.assertIn("not_ready_for_finalize:manual_review", item["skip_reasons"])
        self.assertEqual(item["commands"], [])

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
                            "host_strm_root": "/example/host/strm",
                            "emby_strm_root": "/example/service/strm",
                        },
                        "items": [
                            {
                                "bucket": AUTO_CLEANUP,
                                "title": "折腰",
                                "tmdbid": 296753,
                                "season": 1,
                                "expected_episode_count": 36,
                                "source_paths": ["/example/local-tv/折腰 (2025)/Season 1"],
                                "cloud_media_path": "/已整理/series/折腰 (2025) {tmdbid=296753}/Season 1",
                                "strm_root": "/example/host/strm/series/折腰 (2025) {tmdbid=296753}/Season 1",
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
                actions=_batch_finalize_actions(actions),
            )
            stage_files = sorted(Path(tmp).glob("*.json"))

        self.assertTrue(report["ok"])
        self.assertEqual(report["items"][0]["status"], "cleanup_waiting_for_approval")
        self.assertNotIn("cloud-hlink-cleanup-execute", [call[0] for call in actions.calls])
        self.assertEqual(len(stage_files), 6)
        rendered = render_batch_finalize_run(report, "markdown")
        self.assertIn("Batch Finalize Run", rendered)
        self.assertIn("cleanup_waiting_for_approval", rendered)

    def test_batch_finalize_run_waits_for_cloud_duplicate_delete_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actions = FinalizeFakeActions()
            actions.cloud_duplicate_count = 36
            report = run_batch_finalize(
                self._finalize_plan(),
                output_dir=tmp,
                config=FinalizeFakeConfig(path_aliases={}),
                execute_scrape=True,
                approve_delete=False,
                actions=_batch_finalize_actions(actions),
            )

        self.assertFalse(report["ok"])
        item = report["items"][0]
        self.assertEqual(item["status"], "cloud_duplicate_cleanup_waiting_for_approval")
        self.assertEqual(item["cloud_duplicate_video_count"], 36)
        self.assertIn("cloud_duplicate_delete_approval_required", item["blockers"])
        self.assertNotIn("mp-scrape-strm-result", [call[0] for call in actions.calls])

    def test_batch_finalize_run_deletes_cloud_duplicates_and_emby_stale_before_local_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actions = FinalizeFakeActions()
            actions.cloud_duplicate_count = 36
            report = run_batch_finalize(
                self._finalize_plan(),
                output_dir=tmp,
                config=FinalizeFakeConfig(path_aliases={}, emby_library_db_path="/emby/library.db"),
                execute_scrape=True,
                approve_cloud_duplicate_delete=True,
                approve_emby_stale_delete=True,
                approve_delete=False,
                actions=_batch_finalize_actions(actions),
            )

        item = report["items"][0]
        self.assertTrue(report["ok"])
        self.assertEqual(item["status"], "cleanup_waiting_for_approval")
        self.assertEqual(item["cloud_duplicate_video_count_after_cleanup"], 0)
        call_names = [call[0] for call in actions.calls]
        self.assertGreaterEqual(call_names.count("mv3-cloud-duplicate-video-cleanup-result"), 3)
        self.assertEqual(call_names.count("emby-delete-stale-paths"), 2)
        self.assertNotIn("cloud-hlink-cleanup-execute", call_names)
        stale_calls = [call for call in actions.calls if call[0] == "emby-delete-stale-paths"]
        self.assertEqual(stale_calls[0][1]["kwargs"]["delete_scope"], "season")
        self.assertEqual(stale_calls[1][1]["kwargs"]["delete_scope"], "root")
        self.assertEqual(stale_calls[0][1]["kwargs"]["stale_path_prefixes"], ["/example/local-tv/折腰 (2025)/Season 1"])
        self.assertEqual(stale_calls[1][1]["kwargs"]["stale_path_prefixes"], ["/example/local-tv/折腰 (2025)"])

    def test_batch_finalize_run_gate_failure_stops_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actions = FinalizeFakeActions(fail_stage="strm-nfo-language-audit")
            report = run_batch_finalize(
                self._finalize_plan(),
                output_dir=tmp,
                config=FinalizeFakeConfig(path_aliases={}),
                execute_scrape=True,
                approve_delete=True,
                actions=_batch_finalize_actions(actions),
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
                actions=_batch_finalize_actions(actions),
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["items"][0]["status"], "cleanup_executed")
        self.assertIn("cloud-hlink-cleanup-execute", [call[0] for call in actions.calls])

    def test_batch_finalize_run_carries_cleanup_unlinked_video_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actions = FinalizeFakeActions()

            def blocked_cleanup_preview(**kwargs: object) -> dict:
                return {
                    "mode": "cloud-hlink-cleanup-preview",
                    "ok": False,
                    "ready_for_execute": False,
                    "blockers": ["source_root_check_failed"],
                    "warnings": [],
                    "filesystem": {
                        "source_roots": [
                            {
                                "path": "/source/Band.of.Brothers",
                                "blocked": True,
                                "video_count": 12,
                                "linked_hlink_video_count": 10,
                                "unlinked_video_sample": [
                                    "/source/Band.of.Brothers.SP1.We.Stand.Alone.mkv",
                                    "/source/Band.of.Brothers.SP2.The.Making.mkv",
                                ],
                            }
                        ]
                    },
                }

            batch_actions = _batch_finalize_actions(actions)
            batch_actions.cleanup_preview = blocked_cleanup_preview
            report = run_batch_finalize(
                self._finalize_plan(),
                output_dir=tmp,
                config=FinalizeFakeConfig(path_aliases={}),
                execute_scrape=True,
                approve_delete=False,
                actions=batch_actions,
            )

        item = report["items"][0]
        self.assertEqual(item["status"], "failed_cleanup_preview")
        self.assertIn("source_root_check_failed", item["blockers"])
        self.assertIn("SP1.We.Stand.Alone", " ".join(item["cleanup_unlinked_video_sample"]))
        self.assertEqual(item["cleanup_blocked_source_roots"][0]["linked_hlink_video_count"], 10)
        self.assertEqual(item["cleanup_blocked_source_roots"][0]["video_count"], 12)

    def test_batch_finalize_run_uses_strm_paths_for_scrape_and_cloud_path_only_for_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actions = FinalizeFakeActions()
            run_batch_finalize(
                self._finalize_plan(),
                output_dir=tmp,
                config=FinalizeFakeConfig(path_aliases={}),
                execute_scrape=True,
                approve_delete=False,
                actions=_batch_finalize_actions(actions),
            )

        scrape_call = next(call for call in actions.calls if call[0] == "mp-scrape-strm-result")
        self.assertEqual(scrape_call[1]["kwargs"]["strm_path"], "/example/host/strm/series/折腰 (2025) {tmdbid=296753}/Season 1")
        self.assertEqual(scrape_call[1]["kwargs"]["mp_path"], "/example/service/strm/series/折腰 (2025) {tmdbid=296753}/Season 1")
        self.assertNotIn("/已整理", scrape_call[1]["kwargs"]["strm_path"])
        cloud_duplicate_call = next(call for call in actions.calls if call[0] == "mv3-cloud-duplicate-video-cleanup-result")
        self.assertEqual(
            cloud_duplicate_call[1]["kwargs"]["season_path"],
            "/已整理/series/折腰 (2025) {tmdbid=296753}/Season 1",
        )
        cleanup_call = next(call for call in actions.calls if call[0] == "cloud-hlink-cleanup-preview")
        self.assertEqual(cleanup_call[1]["expected"]["cloud_media_path"], "/已整理/series/折腰 (2025) {tmdbid=296753}")

    def test_batch_finalize_run_prefers_strm_derived_prefix_over_stale_plan_prefix(self) -> None:
        plan = self._finalize_plan()
        plan["items"][0]["title"] = "兄弟连"
        plan["items"][0]["tmdbid"] = 4613
        plan["items"][0]["expected_episode_count"] = 10
        plan["items"][0]["expected_episodes"] = list(range(1, 11))
        plan["items"][0]["strm_root"] = "/example/host/strm/series/兄弟连 (2001) {tmdbid=4613}/Season 1"
        plan["items"][0]["service_strm_root"] = "/example/service/strm/series/兄弟连 (2001) {tmdbid=4613}/Season 1"
        plan["items"][0]["cloud_title_path"] = "/已整理/series/兄弟连 {tmdbid=4613}"
        plan["items"][0]["required_target_prefix"] = "/已整理/series/兄弟连 {tmdbid=4613}/Season 01"
        with tempfile.TemporaryDirectory() as tmp:
            actions = FinalizeFakeActions()
            report = run_batch_finalize(
                plan,
                output_dir=tmp,
                config=FinalizeFakeConfig(path_aliases={}),
                execute_scrape=True,
                approve_delete=False,
                actions=_batch_finalize_actions(actions),
            )

        verify_call = next(call for call in actions.calls if call[0] == "strm-verify")
        cleanup_call = next(call for call in actions.calls if call[0] == "cloud-hlink-cleanup-preview")
        self.assertEqual(report["items"][0]["status"], "cleanup_waiting_for_approval")
        self.assertEqual(verify_call[1]["expected"]["required_target_prefix"], "/已整理/series/兄弟连 (2001) {tmdbid=4613}/Season 1")
        self.assertEqual(cleanup_call[1]["expected"]["cloud_media_path"], "/已整理/series/兄弟连 (2001) {tmdbid=4613}")

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
                        "strm_paths_sample": ["/example/host/strm/series/演示剧 (2024) {tmdbid=123}/Season 1/演示剧 - S01E01.strm"],
                        "source_paths": ["/example/local-tv/演示剧 (2024) {tmdbid=123}"],
                    }
                ],
            },
            host_strm_root="/example/host/strm",
            emby_strm_root="/example/service/strm",
            env_file="/safe/.env",
        )

        item = plan["items"][0]

        self.assertEqual(item["bucket"], AUTO_CLEANUP)
        self.assertEqual(item["cloud_media_path"], "/已整理/series/演示剧 (2024) {tmdbid=123}/Season 01")
        commands = "\n".join(action["command"] for action in item["next_actions"])
        self.assertIn("/example/host/strm/series/演示剧 (2024) {tmdbid=123}/Season 1", commands)
        self.assertIn("/example/service/strm/series/演示剧 (2024) {tmdbid=123}/Season 1", commands)
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
                        "source_paths": ["/example/local-tv/干净剧 (2025) {tmdbid=456}/Season 01"],
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
                        "source_paths": ["/example/local-tv/干净剧 (2025) {tmdbid=456}/Season 01"],
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
            host_strm_root="/example/host/strm",
            env_file="/safe/.env",
        )

        item = plan["items"][0]

        self.assertEqual(item["bucket"], AUTO_TRANSFER)
        self.assertEqual(item["cloud_media_path"], "/已整理/series/干净剧 (2025) {tmdbid=456}/Season 01")
        commands = "\n".join(action["command"] for action in item["next_actions"])
        self.assertIn("--selection-index 2", commands)
        self.assertIn("/example/host/strm/series/干净剧 (2025) {tmdbid=456}/Season 01", commands)
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
                        "source_paths": ["/example/local-tv/怪奇物语/Season 04"],
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
                        "source_paths": ["/example/local-tv/怪奇物语/Season 04"],
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

    def test_not_found_with_spinoff_share_candidate_requires_review_even_when_season_matches(self) -> None:
        plan = build_batch_plan(
            cloud_report={
                "items": [
                    {
                        "status": "cloud_strm_not_found",
                        "title": "怪奇物语",
                        "tmdbid": 66732,
                        "season": 1,
                        "size_bytes": 43_000_000_000,
                        "expected_count": 8,
                        "source_paths": ["/example/local-tv/怪奇物语/Season 01"],
                    }
                ],
            },
            transfer_plan={
                "items": [
                    {
                        "title": "怪奇物语",
                        "tmdbid": 66732,
                        "season": 1,
                        "size_bytes": 43_000_000_000,
                        "expected_count": 8,
                        "source_paths": ["/example/local-tv/怪奇物语/Season 01"],
                    }
                ],
            },
            share_search_plan={
                "items": [
                    {
                        "title": "怪奇物语",
                        "tmdbid": 66732,
                        "season": 1,
                        "recommended_candidate": {
                            "search_index": 15,
                            "search_keyword": "怪奇物语",
                            "title": "📺 电视剧：怪奇物语：1985故事集 (2026) - S01E01-E10(完结)",
                            "score": 100,
                            "size_delta_ratio": 0.06,
                            "blockers": [],
                        },
                    }
                ],
            },
        )

        item = plan["items"][0]

        self.assertEqual(item["bucket"], MANUAL_REVIEW)
        self.assertIn("possible_chinese_subtitle_mismatch", item["review_reasons"])
        self.assertIn(
            "possible_chinese_subtitle_mismatch",
            item["candidate_diagnostics"]["best_candidate"]["blockers"],
        )

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
                        "strm_paths_sample": ["/example/host/strm/series/兄弟连 (2001) {tmdbid=4613}/Season 01/兄弟连 - S01E01.strm"],
                        "source_paths": ["/example/local-tv/兄弟连 (2001) {tmdbid=4613}/Season 01"],
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
                        "source_paths": ["/example/local-tv/大体积剧 (2023) {tmdbid=789}"],
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
                        "source_paths": ["/example/local-tv/大体积剧 (2023) {tmdbid=789}"],
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
                        "source_paths": ["/example/local-tv/分段剧/Season 01"],
                    },
                    {
                        "status": "cloud_strm_not_found",
                        "title": "另一部 (2024) {tmdbid=222}",
                        "tmdbid": 222,
                        "season": 1,
                        "size_bytes": 2000,
                        "expected_count": 6,
                        "source_paths": ["/example/local-tv/另一部/Season 01"],
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
                        "source_paths": ["/example/local-tv/分段剧/Season 01"],
                    },
                    {
                        "title": "另一部 (2024) {tmdbid=222}",
                        "tmdbid": 222,
                        "season": 1,
                        "size_bytes": 2000,
                        "expected_count": 6,
                        "source_paths": ["/example/local-tv/另一部/Season 01"],
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
                        "source_paths": ["/example/local-tv/怪奇物语/Season 04"],
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
                        "source_paths": ["/example/local-tv/怪奇物语/Season 04"],
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

    def test_batch_review_report_combines_preview_and_finalize_results(self) -> None:
        batch_plan = {
            "mode": "readonly-batch-state-plan",
            "items": [
                {
                    "bucket": AUTO_CLEANUP,
                    "state": "planned_validation_then_cleanup",
                    "title": "兄弟连",
                    "tmdbid": 4613,
                    "season": 1,
                    "cloud_status": "cloud_strm_complete",
                    "size": "45.5GB",
                    "size_bytes": 48_841_375_069,
                    "expected_episode_count": 10,
                    "expected_episodes": list(range(1, 11)),
                    "source_paths": ["/example/local-tv/兄弟连/Season 01"],
                    "strm_root": "/example/service/strm/series/兄弟连/Season 1",
                    "cloud_media_path": "/已整理/series/兄弟连/Season 1",
                },
                {
                    "bucket": MANUAL_REVIEW,
                    "state": "held_for_manual_review",
                    "title": "长安二十四计",
                    "tmdbid": 254482,
                    "season": 1,
                    "cloud_status": "cloud_strm_not_found",
                    "size": "193.4GB",
                    "size_bytes": 207_625_138_073,
                    "expected_episode_count": 28,
                    "expected_episodes": list(range(1, 29)),
                    "review_reasons": ["episode_coverage_unclear"],
                    "candidate_diagnostics": {
                        "search_result_count": 5,
                        "best_candidate": {
                            "title": "长安二十四计 S01E01-E14",
                            "score": 80,
                            "size_delta_ratio": 0.1,
                            "blockers": ["episode_coverage_unclear"],
                        },
                    },
                },
            ],
        }
        preview_report = {
            "mode": "readonly-batch-mv3-share-preview",
            "items": [
                {
                    "status": "preview_blocked",
                    "title": "长安二十四计",
                    "tmdbid": 254482,
                    "season": 1,
                    "preview_episode_count": 14,
                    "preview_missing_expected": list(range(15, 29)),
                    "preview_blockers": ["episode_count_mismatch"],
                    "candidate_score": 80,
                }
            ],
        }
        finalize_report = {
            "mode": "batch-finalize-run",
            "items": [
                {
                    "status": "failed_cleanup_preview",
                    "title": "兄弟连",
                    "tmdbid": 4613,
                    "season": 1,
                    "blockers": ["source_root_check_failed"],
                    "cleanup_unlinked_video_sample": [
                        "/source/Band.of.Brothers.SP1.We.Stand.Alone.mkv",
                        "/source/Band.of.Brothers.SP2.The.Making.mkv",
                    ],
                    "cleanup_blocked_source_roots": [
                        {
                            "path": "/source/Band.of.Brothers",
                            "video_count": 12,
                            "linked_hlink_video_count": 10,
                            "unlinked_video_sample": [
                                "/source/Band.of.Brothers.SP1.We.Stand.Alone.mkv",
                                "/source/Band.of.Brothers.SP2.The.Making.mkv",
                            ],
                        }
                    ],
                    "stages": [{"stage": "cloud_hlink_cleanup_preview", "ok": False}],
                }
            ],
        }

        report = build_batch_review_report(
            batch_plan,
            share_preview_reports=[preview_report],
            finalize_run_reports=[finalize_report],
        )

        self.assertEqual(report["decision_counts"]["blocked_after_finalize_gates"], 1)
        self.assertEqual(report["decision_counts"]["manual_review_preview_blocked"], 1)
        brother = next(item for item in report["items"] if item["tmdbid"] == 4613)
        changan = next(item for item in report["items"] if item["tmdbid"] == 254482)
        self.assertEqual(brother["decision"], "blocked_after_finalize_gates")
        self.assertIn("source_root_check_failed", brother["reason_summary"])
        self.assertEqual(brother["finalize_last_stage"], "cloud_hlink_cleanup_preview")
        self.assertIn("SP1.We.Stand.Alone", brother["finalize_cleanup_unlinked_videos"])
        self.assertIn("/source/Band.of.Brothers (10/12 linked)", brother["finalize_cleanup_blocked_source_roots"])
        self.assertEqual(changan["decision"], "manual_review_preview_blocked")
        self.assertIn("15-28", changan["preview_missing_expected"])
        rendered = render_batch_review_report(report, "csv")
        self.assertIn("decision,next_action,bucket,state,title", rendered.splitlines()[0])
        self.assertIn("blocked_after_finalize_gates", rendered)
        self.assertIn("manual_review_preview_blocked", rendered)
        self.assertIn("source_root_check_failed", rendered)
        self.assertIn("SP2.The.Making", rendered)

    def test_cli_writes_batch_review_report_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            batch = tmp_path / "batch.json"
            finalize = tmp_path / "finalize.json"
            output = tmp_path / "review.csv"
            batch.write_text(
                json.dumps(
                    {
                        "mode": "readonly-batch-state-plan",
                        "items": [
                            {
                                "bucket": AUTO_CLEANUP,
                                "state": "planned_validation_then_cleanup",
                                "title": "兄弟连",
                                "tmdbid": 4613,
                                "season": 1,
                                "cloud_status": "cloud_strm_complete",
                                "expected_episode_count": 10,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            finalize.write_text(
                json.dumps(
                    {
                        "mode": "batch-finalize-run",
                        "items": [
                            {
                                "status": "failed_cleanup_preview",
                                "title": "兄弟连",
                                "tmdbid": 4613,
                                "season": 1,
                                "blockers": ["source_root_check_failed"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "batch-review-report",
                    "--batch-plan",
                    str(batch),
                    "--finalize-run-report",
                    str(finalize),
                    "--format",
                    "csv",
                    "--output",
                    str(output),
                ]
            )
            rendered = output.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("blocked_after_finalize_gates", rendered)
        self.assertIn("source_root_check_failed", rendered)

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
                    "cloud_media_path": "/已整理/series/折腰 (2025) {tmdbid=246}/Season 1",
                    "cloud_title_path": "/已整理/series/折腰 (2025) {tmdbid=246}",
                    "required_target_prefix": "/已整理/series/折腰 (2025) {tmdbid=246}",
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
        self.assertEqual(ready["cloud_media_path"], "/已整理/series/折腰 (2025) {tmdbid=246}/Season 1")
        self.assertEqual(ready["cloud_title_path"], "/已整理/series/折腰 (2025) {tmdbid=246}")
        self.assertEqual(ready["required_target_prefix"], "/已整理/series/折腰 (2025) {tmdbid=246}")
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
                    "cloud_media_path": "/已整理/series/折腰 (2025) {tmdbid=296753}/Season 1",
                    "cloud_title_path": "/已整理/series/折腰 (2025) {tmdbid=296753}",
                    "required_target_prefix": "/已整理/series/折腰 (2025) {tmdbid=296753}",
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
        self.assertEqual(ready["cloud_media_path"], "/已整理/series/折腰 (2025) {tmdbid=296753}/Season 1")
        self.assertEqual(ready["cloud_title_path"], "/已整理/series/折腰 (2025) {tmdbid=296753}")
        self.assertEqual(ready["required_target_prefix"], "/已整理/series/折腰 (2025) {tmdbid=296753}")
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
