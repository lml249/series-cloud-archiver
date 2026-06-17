import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.mv3 import (
    MV3Client,
    add_mv3_offline_task,
    inspect_mv3_capabilities,
    inspect_mv3_instances,
    probe_mv3,
    render_mv3_capabilities_report,
    render_mv3_instances_report,
    render_mv3_offline_add_report,
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

    def test_offline_add_posts_json_and_redacts_magnet(self) -> None:
        seen = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps({"ok": True, "echo": "magnet:?xt=urn:btih:private"}).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["api_key"] = request.headers.get("X-api-key")
            seen["body"] = json.loads(request.data.decode("utf-8"))
            seen["timeout"] = timeout
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            report = add_mv3_offline_task(
                "http://mv3.example",
                "secret-token",
                ["magnet:?xt=urn:btih:private"],
                storage="115-default",
                wp_path="/series/Demo",
                timeout=12,
            )

        rendered = render_mv3_offline_add_report(report, "json")
        self.assertEqual(seen["url"], "http://mv3.example/api/v1/files/115/offline/add")
        self.assertEqual(seen["api_key"], "secret-token")
        self.assertEqual(seen["body"]["urls"], "magnet:?xt=urn:btih:private")
        self.assertEqual(seen["body"]["storage"], "115-default")
        self.assertEqual(seen["timeout"], 12)
        self.assertTrue(report["ok"])
        self.assertTrue(report["http_ok"])
        self.assertTrue(report["api_success"])
        self.assertEqual(report["request"]["urls"], "[REDACTED_MAGNET_URIS]")
        self.assertNotIn("magnet:?", rendered)

    def test_offline_add_treats_business_failure_as_not_ok(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps({"success": False, "message": "云盘目录不存在"}).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
            report = add_mv3_offline_task(
                "http://mv3.example",
                "secret-token",
                ["magnet:?xt=urn:btih:private"],
                storage="115-default",
                wp_path="/series/Missing",
            )

        self.assertFalse(report["ok"])
        self.assertTrue(report["http_ok"])
        self.assertFalse(report["api_success"])
        self.assertEqual(report["response"]["message"], "云盘目录不存在")

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

    def test_cli_refuses_offline_add_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            manifest = tmp_path / "manifest.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")
            manifest.write_text(json.dumps({"items": []}), encoding="utf-8")

            with self.assertRaises(SystemExit):
                main(
                    [
                        "mv3-offline-add-one",
                        "--env-file",
                        str(env_file),
                        "--manifest",
                        str(manifest),
                        "--priority",
                        "1",
                        "--expected-title",
                        "Demo",
                    ]
                )

    def test_cli_executes_one_offline_add_from_manifest_without_leaking_magnet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            manifest = tmp_path / "manifest.json"
            qb_report = tmp_path / "qb.json"
            output = tmp_path / "result.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "mv3_context": {"cloud_drive_slug": "115-default"},
                        "items": [
                            {
                                "priority": 5,
                                "title": "Demo",
                                "tmdbid": 123,
                                "season": 1,
                                "proposed_cloud_destination": "/series/Demo",
                                "titles": ["Demo.S01"],
                                "source_paths": ["/media/Demo.S01"],
                                "qb_matches": [{"hash": "abc"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            qb_report.write_text(
                json.dumps(
                    {
                        "torrents": [
                            {
                                "name": "Demo.S01",
                                "hash": "abc",
                                "content_path": "/media/Demo.S01",
                                "magnet_uri": "magnet:?xt=urn:btih:private",
                                "seeding_time": 9 * 86400,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    return b'{"success":true}'

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            def fake_urlopen(_request, timeout):
                return FakeResponse()

            with patch("urllib.request.urlopen", fake_urlopen):
                code = main(
                    [
                        "mv3-offline-add-one",
                        "--env-file",
                        str(env_file),
                        "--manifest",
                        str(manifest),
                        "--qb-report",
                        str(qb_report),
                        "--priority",
                        "5",
                        "--expected-title",
                        "Demo",
                        "--approve-offline-add",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            text = output.read_text(encoding="utf-8")
            payload = json.loads(text)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["selection"]["title"], "Demo")
            self.assertEqual(payload["request"]["magnet_count"], 1)
            self.assertNotIn("magnet:?", text)


if __name__ == "__main__":
    unittest.main()
