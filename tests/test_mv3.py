import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.mv3 import MV3Client, probe_mv3, render_mv3_probe_report


class MV3ProbeTest(unittest.TestCase):
    def test_client_sends_api_key_header_without_query_token(self) -> None:
        seen = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return b"{}"

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["api_key"] = request.headers.get("X-api-key")
            seen["authorization"] = request.headers.get("Authorization")
            seen["timeout"] = timeout
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            MV3Client("http://mv3.example", "secret-token").get("/api/v1/config")

        self.assertEqual(seen["url"], "http://mv3.example/api/v1/config")
        self.assertEqual(seen["api_key"], "secret-token")
        self.assertIsNone(seen["authorization"])
        self.assertEqual(seen["timeout"], 10)

    def test_reports_missing_configuration_without_network(self) -> None:
        report = probe_mv3("", "")

        self.assertFalse(report["configured"])
        self.assertFalse(report["reachable"])
        self.assertIn("mv3_base_url_not_configured", report["warnings"])

    def test_extracts_openapi_summary_from_readonly_get(self) -> None:
        payload = {
            "openapi": "3.0.0",
            "info": {"title": "MediaVault", "version": "1.0"},
            "paths": {
                "/api/search": {"get": {}},
                "/api/transfer": {"post": {}},
                "/api/delete": {"delete": {}},
            },
        }

        def fake_get(_self, path):
            if path == "/openapi.json":
                return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")
            return 404, {"Content-Type": "application/json"}, b"{}"

        with patch.object(MV3Client, "get", fake_get):
            report = probe_mv3("http://mv3.example", "token", paths=["/openapi.json"])

        self.assertTrue(report["configured"])
        self.assertTrue(report["reachable"])
        self.assertEqual(report["openapi_summary"]["path_count"], 3)
        self.assertIn({"method": "GET", "path": "/api/search"}, report["openapi_summary"]["safe_get_paths_sample"])
        self.assertIn({"method": "DELETE", "path": "/api/delete"}, report["openapi_summary"]["sensitive_method_hints_sample"])

    def test_renders_markdown_safety_note(self) -> None:
        markdown = render_mv3_probe_report(
            {
                "mode": "readonly-mv3-probe",
                "configured": False,
                "reachable": False,
                "token_configured": False,
                "probes": [],
                "warnings": [],
            },
            "markdown",
        )

        self.assertIn("MV3 Probe", markdown)
        self.assertIn("readonly GET probe", markdown)

    def test_cli_writes_mv3_check_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "mv3-check.json"
            env_file.write_text("MV3_BASE_URL=\nMV3_API_TOKEN=\n", encoding="utf-8")

            code = main(["mv3-check", "--env-file", str(env_file), "--format", "json", "--output", str(output)])

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(payload["configured"])


if __name__ == "__main__":
    unittest.main()
