import json
import tempfile
import unittest
from pathlib import Path
from typing import List, Optional

from series_cloud_archiver.cli import main
from series_cloud_archiver.finalize_remediation import (
    build_finalize_remediation_plan,
    render_finalize_remediation_plan,
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


if __name__ == "__main__":
    unittest.main()
