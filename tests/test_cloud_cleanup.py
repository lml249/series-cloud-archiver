import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.cloud_cleanup import (
    execute_cloud_complete_cleanup_plan,
    plan_cloud_complete_cleanup,
    render_cloud_complete_cleanup_execute,
    render_cloud_complete_cleanup_plan,
)


def touch_strm(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("http://example.invalid/stream", encoding="utf-8")


def cloud_complete_item(strm_root: Path) -> dict:
    return {
        "status": "cloud_strm_complete",
        "title": "沉默的荣耀",
        "tmdbid": 281538,
        "season": 1,
        "size_bytes": 1024,
        "expected_count": 2,
        "expected_episodes": [1, 2],
        "cloud_episode_count": 2,
        "cloud_episodes": [1, 2],
        "source_paths": ["/example-host/hlink/TV/沉默的荣耀 (2025) {tmdbid=281538}"],
        "strm_paths_sample": [str(strm_root / "沉默的荣耀 S01E01.strm")],
    }


def ready_preview() -> dict:
    return {
        "mode": "readonly-mp-cleanup-preview",
        "title": "沉默的荣耀",
        "expected_title": "沉默的荣耀",
        "expected_tmdbid": 281538,
        "expected_hash_prefix": "",
        "ok": True,
        "ready_for_manual_cleanup_approval": True,
        "summary": {
            "records_found": 2,
            "records_matched": 2,
            "episode_count": 2,
            "episode_min": 1,
            "episode_max": 2,
            "missing_in_range": [],
            "download_hash_count": 1,
            "downloader_count": 1,
            "source_root_count": 1,
            "destination_root_count": 1,
        },
        "mp_delete_plan": {"query": {"deletesrc": True, "deletedest": True}},
        "qb_targets": [{"hash_prefix": "feedface0000", "downloader": "20099"}],
        "source_roots": ["/example-service/TV/Silent.Honor.S01"],
        "destination_roots": ["/example-service/hlink/TV/沉默的荣耀 (2025) {tmdbid=281538}"],
        "records": [
            {"id": 10, "title": "沉默的荣耀", "tmdbid": 281538, "episodes": "E01", "episode_number": 1, "hash_prefix": "feedface0000", "status": True},
            {"id": 11, "title": "沉默的荣耀", "tmdbid": 281538, "episodes": "E02", "episode_number": 2, "hash_prefix": "feedface0000", "status": True},
        ],
        "warnings": [],
        "blockers": [],
    }


class CloudCompleteCleanupTest(unittest.TestCase):
    def test_plans_ready_cloud_complete_item_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm" / "series" / "沉默的荣耀 (2025) {tmdbid=281538}" / "Season 1"
            touch_strm(root / "沉默的荣耀 S01E01.strm")
            touch_strm(root / "沉默的荣耀 S01E02.strm")
            report = {"mode": "readonly-cloud-check", "items": [cloud_complete_item(root)]}

            with patch("series_cloud_archiver.cloud_cleanup.mp_cleanup_preview_from_transfer_history", return_value=ready_preview()) as preview:
                plan = plan_cloud_complete_cleanup(
                    report,
                    "http://mp.example",
                    "token",
                    path_aliases={"/example-host": "/example-service"},
                )

        self.assertEqual(plan["mode"], "cloud-complete-cleanup-plan")
        self.assertEqual(plan["ready_items"], 1)
        self.assertTrue(plan["items"][0]["ready_for_execute"])
        self.assertEqual(plan["items"][0]["source_roots_host"], ["/example-host/TV/Silent.Honor.S01"])
        self.assertEqual(plan["items"][0]["destination_roots_host"], ["/example-host/hlink/TV/沉默的荣耀 (2025) {tmdbid=281538}"])
        self.assertEqual(preview.call_count, 1)
        self.assertIn("readonly batch plan only", render_cloud_complete_cleanup_plan(plan, "markdown"))

    def test_plan_blocks_when_mp_records_do_not_cover_cloud_episodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm" / "series" / "沉默的荣耀 (2025) {tmdbid=281538}" / "Season 1"
            touch_strm(root / "沉默的荣耀 S01E01.strm")
            touch_strm(root / "沉默的荣耀 S01E02.strm")
            bad_preview = ready_preview()
            bad_preview["summary"] = {**bad_preview["summary"], "records_matched": 1, "episode_count": 1, "episode_max": 1}
            report = {"items": [cloud_complete_item(root)]}

            with patch("series_cloud_archiver.cloud_cleanup.mp_cleanup_preview_from_transfer_history", return_value=bad_preview):
                plan = plan_cloud_complete_cleanup(report, "http://mp.example", "token")

        self.assertEqual(plan["ready_items"], 0)
        self.assertFalse(plan["items"][0]["ready_for_execute"])
        self.assertIn("mp_record_count_mismatch", plan["items"][0]["execution_blockers"])
        self.assertIn("mp_episode_count_mismatch", plan["items"][0]["execution_blockers"])

    def test_execute_skips_not_ready_items_before_moviepilot_delete(self) -> None:
        plan = {
            "mode": "cloud-complete-cleanup-plan",
            "items": [{"title": "沉默的荣耀", "ready_for_execute": False, "execution_blockers": ["mp_record_count_mismatch"]}],
        }

        with patch("series_cloud_archiver.cloud_cleanup.execute_mp_cleanup_from_preview_report") as execute:
            report = execute_cloud_complete_cleanup_plan(plan, "http://mp.example", "token")

        self.assertFalse(report["ok"])
        self.assertEqual(execute.call_count, 0)
        self.assertIn("cleanup_item_not_ready", report["results"][0]["blockers"])

    def test_execute_runs_mp_cleanup_then_verifies(self) -> None:
        plan = {
            "mode": "cloud-complete-cleanup-plan",
            "items": [
                {
                    "title": "沉默的荣耀",
                    "tmdbid": 281538,
                    "season": 1,
                    "ready_for_execute": True,
                    "mp_preview": ready_preview(),
                    "expected_hash_prefix": "feedface0000",
                    "expected_episode_count": 2,
                    "expected_episode_min": 1,
                    "expected_episode_max": 2,
                    "expected_episodes": [1, 2],
                    "source_roots_host": ["/example-host/TV/Silent.Honor.S01"],
                    "destination_roots_host": ["/example-host/hlink/TV/沉默的荣耀 (2025) {tmdbid=281538}"],
                    "strm_root": "/example-cloud/mv3/strm/series/沉默的荣耀 (2025) {tmdbid=281538}/Season 1",
                }
            ],
        }
        execute_report = {"ok": True, "blockers": [], "summary": {"success_count": 2}}
        verify_report = {"ok": True, "blockers": []}

        with patch("series_cloud_archiver.cloud_cleanup.execute_mp_cleanup_from_preview_report", return_value=execute_report) as execute, patch(
            "series_cloud_archiver.cloud_cleanup.verify_mp_cleanup_from_services", return_value=verify_report
        ) as verify:
            report = execute_cloud_complete_cleanup_plan(plan, "http://mp.example", "token", qb_base_url="http://qb.example")

        self.assertTrue(report["ok"])
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(verify.call_count, 1)
        self.assertTrue(report["results"][0]["ok"])
        self.assertIn("approved batch MoviePilot cleanup", render_cloud_complete_cleanup_execute(report, "markdown"))

    def test_cli_writes_cloud_complete_cleanup_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "strm" / "series" / "沉默的荣耀 (2025) {tmdbid=281538}" / "Season 1"
            touch_strm(root / "沉默的荣耀 S01E01.strm")
            touch_strm(root / "沉默的荣耀 S01E02.strm")
            env_file = tmp_path / ".env"
            env_file.write_text("MP_BASE_URL=http://mp.example\nMP_API_TOKEN=token\nARCHIVER_PATH_ALIASES=/example-host=/example-service\n", encoding="utf-8")
            cloud_report = tmp_path / "cloud.json"
            output = tmp_path / "plan.json"
            cloud_report.write_text(json.dumps({"items": [cloud_complete_item(root)]}, ensure_ascii=False), encoding="utf-8")

            with patch("series_cloud_archiver.cloud_cleanup.mp_cleanup_preview_from_transfer_history", return_value=ready_preview()):
                code = main(
                    [
                        "plan-cloud-complete-cleanup",
                        "--env-file",
                        str(env_file),
                        "--cloud-report",
                        str(cloud_report),
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["ready_items"], 1)


if __name__ == "__main__":
    unittest.main()
