import os
import subprocess
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()
