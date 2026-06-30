import json
import tempfile
import unittest
from pathlib import Path

from series_cloud_archiver.cli import main
from series_cloud_archiver.extra_source_media import build_extra_source_media_plan, render_extra_source_media_plan


class ExtraSourceMediaPlanTest(unittest.TestCase):
    def _finalize_report(self) -> dict:
        return {
            "mode": "batch-finalize-run",
            "items": [
                {
                    "status": "failed_cleanup_preview",
                    "title": "兄弟连 (2001) {tmdbid=4613} Season 01",
                    "tmdbid": 4613,
                    "season": 1,
                    "blockers": ["source_root_check_failed"],
                    "cleanup_unlinked_video_sample": [
                        "/volume3/volume3/TV/兄弟连/Band.of.Brothers.SP1.We.Stand.Alone.mkv",
                        "/volume3/volume3/TV/兄弟连/Band.of.Brothers.SP2.The.Making.mkv",
                    ],
                    "cleanup_blocked_source_roots": [
                        {
                            "path": "/volume3/volume3/TV/兄弟连",
                            "video_count": 12,
                            "linked_hlink_video_count": 10,
                            "unlinked_video_sample": [
                                "/volume3/volume3/TV/兄弟连/Band.of.Brothers.SP1.We.Stand.Alone.mkv",
                            ],
                        }
                    ],
                }
            ],
        }

    def test_plan_promotes_unlinked_specials_to_readonly_mv3_scan_commands(self) -> None:
        report = build_extra_source_media_plan(
            self._finalize_report(),
            env_file="/safe/.env",
            target_dir="/已整理",
            strm_dir="/strm",
        )

        self.assertEqual(report["planned_items"], 2)
        self.assertEqual(report["ready_for_mv3_scan_items"], 2)
        first = report["items"][0]
        self.assertEqual(first["suggested_season"], 0)
        self.assertEqual(first["media_kind"], "special")
        self.assertIn("mv3-organize-scan-source", first["commands"][0]["command"])
        self.assertIn("--local-source --file", first["commands"][0]["command"])
        self.assertEqual(first["commands"][1]["stage"], "season00_mapping_required")
        self.assertFalse(first["commands"][1]["command"].startswith("PYTHONPATH=src"))
        rendered = render_extra_source_media_plan(report, "csv")
        self.assertIn("Band.of.Brothers.SP2.The.Making.mkv", rendered)

    def test_cli_writes_extra_source_media_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            finalize = tmp_path / "finalize.json"
            output = tmp_path / "extra.json"
            finalize.write_text(json.dumps(self._finalize_report(), ensure_ascii=False), encoding="utf-8")

            exit_code = main(
                [
                    "extra-source-media-plan",
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
        self.assertEqual(payload["mode"], "readonly-extra-source-media-plan")
        self.assertEqual(payload["planned_items"], 2)


if __name__ == "__main__":
    unittest.main()
