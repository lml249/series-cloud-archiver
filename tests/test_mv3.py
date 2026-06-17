import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.mv3 import (
    MV3Client,
    inspect_mv3_capabilities,
    inspect_mv3_instances,
    probe_mv3,
    render_mv3_capabilities_report,
    render_mv3_instances_report,
    render_mv3_probe_report,
)


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

    def test_inspects_openapi_capabilities_without_calling_write_paths(self) -> None:
        payload = {
            "openapi": "3.0.0",
            "info": {"title": "MediaVault", "version": "3.2.0-5"},
            "components": {
                "schemas": {
                    "PreviewRequest": {
                        "type": "object",
                        "required": ["items"],
                        "properties": {"items": {"type": "array"}, "target": {"type": "string"}},
                    },
                    "ExecuteRequest": {
                        "type": "object",
                        "required": ["items"],
                        "properties": {"items": {"type": "array"}},
                    },
                }
            },
            "paths": {
                "/api/v1/cloud-drive/instances": {"get": {"summary": "List instances"}},
                "/api/v1/media-transfer/preview": {
                    "post": {
                        "summary": "Preview transfer",
                        "requestBody": {
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/PreviewRequest"}}}
                        },
                    }
                },
                "/api/v1/media-transfer/execute": {
                    "post": {
                        "summary": "Execute transfer",
                        "requestBody": {
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ExecuteRequest"}}}
                        },
                    }
                },
                "/api/v1/resource-search/hdhive/unlock": {"post": {"summary": "Unlock Hdhive"}},
                "/api/v1/resource-search/hdhive/oauth/logout": {"post": {"summary": "Hdhive Oauth Logout"}},
                "/api/v1/organize/recognize": {"post": {"summary": "Recognize"}},
                "/api/v1/strm/records/clear-all": {"delete": {"summary": "Clear all"}},
                "/api/v1/health": {"get": {"summary": "Health"}},
            },
        }
        called_paths = []

        def fake_get(_self, path):
            called_paths.append(path)
            return 200, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")

        with patch.object(MV3Client, "get", fake_get):
            report = inspect_mv3_capabilities("http://mv3.example", "token")

        self.assertEqual(called_paths, ["/openapi.json"])
        self.assertTrue(report["reachable"])
        self.assertEqual(report["openapi"]["version"], "3.2.0-5")
        self.assertEqual(len(report["categories"]["readonly_get"]), 1)
        self.assertEqual(len(report["categories"]["preview_or_search_post"]), 1)
        self.assertEqual(len(report["categories"]["transfer_or_write_post"]), 4)
        self.assertEqual(len(report["categories"]["destructive_or_cleanup"]), 1)
        self.assertEqual(report["categories"]["preview_or_search_post"][0]["request_schema"]["ref"], "PreviewRequest")

    def test_renders_capability_markdown(self) -> None:
        markdown = render_mv3_capabilities_report(
            {
                "mode": "readonly-mv3-capabilities",
                "configured": True,
                "reachable": True,
                "token_configured": True,
                "openapi": {"source_path": "/openapi.json", "title": "MediaVault", "version": "3.2.0-5"},
                "categories": {
                    "readonly_get": [{"method": "GET", "path": "/api/v1/cloud-drive/instances", "summary": "", "request_schema": {}}],
                    "preview_or_search_post": [],
                    "transfer_or_write_post": [],
                    "destructive_or_cleanup": [],
                    "other_relevant": [],
                },
                "warnings": [],
            },
            "markdown",
        )

        self.assertIn("MV3 Capabilities", markdown)
        self.assertIn("Readonly GET", markdown)
        self.assertIn("/api/v1/cloud-drive/instances", markdown)

    def test_cli_writes_mv3_capabilities_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "mv3-capabilities.json"
            env_file.write_text("MV3_BASE_URL=\nMV3_API_TOKEN=\n", encoding="utf-8")

            code = main(["mv3-capabilities", "--env-file", str(env_file), "--format", "json", "--output", str(output)])

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(payload["configured"])

    def test_inspects_instances_with_redacted_samples(self) -> None:
        payloads = {
            "/api/v1/cloud-drive/instances": {
                "code": 0,
                "message": "ok",
                "data": [
                    {
                        "slug": "default",
                        "name": "115",
                        "cookie": "UID=private-cookie",
                        "direct_url": "https://example.test/private",
                        "root": "/cloud/media",
                    }
                ],
            },
            "/api/v1/strm/config": {
                "code": 0,
                "message": "ok",
                "data": {"enabled": True, "output_dir": "/strm", "api_key": "private-key"},
            },
        }
        called_paths = []

        def fake_get(_self, path):
            called_paths.append(path)
            return 200, {"Content-Type": "application/json"}, json.dumps(payloads.get(path, {})).encode("utf-8")

        with patch.object(MV3Client, "get", fake_get):
            report = inspect_mv3_instances("http://mv3.example", "token", paths=list(payloads.keys()))

        rendered = render_mv3_instances_report(report, "json")
        self.assertEqual(called_paths, list(payloads.keys()))
        self.assertTrue(report["reachable"])
        self.assertEqual(report["summary"]["ok_count"], 2)
        self.assertIn("[REDACTED]", rendered)
        self.assertNotIn("private-cookie", rendered)
        self.assertNotIn("private-key", rendered)
        self.assertNotIn("https://example.test/private", rendered)

    def test_instance_probe_expands_media_transfer_libraries_by_instance(self) -> None:
        payloads = {
            "/api/v1/media-transfer/instances": [{"slug": "emby-default", "name": "Emby"}],
            "/api/v1/media-transfer/libraries?instance=emby-default": [{"id": "tv", "name": "TV"}],
        }
        called_paths = []

        def fake_get(_self, path):
            called_paths.append(path)
            return 200, {"Content-Type": "application/json"}, json.dumps(payloads.get(path, {})).encode("utf-8")

        with patch.object(MV3Client, "get", fake_get):
            report = inspect_mv3_instances("http://mv3.example", "token", paths=None)

        self.assertIn("/api/v1/media-transfer/instances", called_paths)
        self.assertIn("/api/v1/media-transfer/libraries?instance=emby-default", called_paths)
        self.assertEqual(report["summary"]["failed_count"], 0)

    def test_instance_probe_can_retry_failed_get_once(self) -> None:
        attempts = {"count": 0}

        def fake_get(_self, path):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise TimeoutError("slow")
            return 200, {"Content-Type": "application/json"}, json.dumps({"data": [{"id": "tv"}]}).encode("utf-8")

        with patch.object(MV3Client, "get", fake_get):
            report = inspect_mv3_instances(
                "http://mv3.example",
                "token",
                paths=["/api/v1/media-transfer/libraries?instance=emby-default"],
                timeout=30,
                retry_failed_once=True,
            )

        self.assertTrue(report["reachable"])
        self.assertEqual(report["summary"]["failed_count"], 0)
        self.assertEqual(report["probes"][0]["attempts"], 2)
        self.assertEqual(report["probes"][0]["previous_error"], "slow")
        self.assertIn("instance_probe_retry:/api/v1/media-transfer/libraries?instance=emby-default:slow", report["warnings"])

    def test_renders_instance_markdown(self) -> None:
        markdown = render_mv3_instances_report(
            {
                "mode": "readonly-mv3-instance-probe",
                "configured": True,
                "reachable": True,
                "token_configured": True,
                "summary": {"ok_count": 1, "failed_count": 0},
                "warnings": [],
                "probes": [
                    {
                        "path": "/api/v1/cloud-drive/instances",
                        "ok": True,
                        "status": 200,
                        "payload_shape": "list",
                        "payload_count": 1,
                        "json_keys": ["code", "data"],
                        "sample": [{"slug": "default"}],
                    }
                ],
            },
            "markdown",
        )

        self.assertIn("MV3 Instance Probe", markdown)
        self.assertIn("Sanitized Samples", markdown)
        self.assertIn("/api/v1/cloud-drive/instances", markdown)

    def test_cli_writes_mv3_instances_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "mv3-instances.json"
            env_file.write_text("MV3_BASE_URL=\nMV3_API_TOKEN=\n", encoding="utf-8")

            code = main(
                [
                    "mv3-instances",
                    "--env-file",
                    str(env_file),
                    "--timeout",
                    "30",
                    "--retry-failed-once",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(payload["configured"])


if __name__ == "__main__":
    unittest.main()
