import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
