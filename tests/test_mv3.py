import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.mv3 import (
    MV3Client,
    add_mv3_offline_task,
    browse_mv3_cloud_folder,
    check_mv3_offline_task,
    ensure_mv3_115_path,
    inspect_mv3_capabilities,
    inspect_mv3_instances,
    probe_mv3,
    render_mv3_capabilities_report,
    render_mv3_cloud_browse_report,
    render_mv3_ensure_path_report,
    render_mv3_instances_report,
    render_mv3_offline_add_report,
    render_mv3_offline_status_report,
    render_mv3_organize_scan_report,
    render_mv3_probe_report,
    render_mv3_resource_search_report,
    render_mv3_share_receive_report,
    render_mv3_share_preview_report,
    scan_mv3_organize_source,
    search_mv3_resources,
    preview_mv3_share,
    receive_mv3_share,
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
                wp_path="/已整理/series/Demo",
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
                wp_path="/已整理/series/Missing",
            )

        self.assertFalse(report["ok"])
        self.assertTrue(report["http_ok"])
        self.assertFalse(report["api_success"])
        self.assertEqual(report["response"]["message"], "云盘目录不存在")

    def test_ensure_115_path_reuses_existing_and_creates_missing_folders(self) -> None:
        calls = []
        folders = {
            "0": [{"n": "已整理", "cid": "50"}],
            "50": [{"n": "series", "cid": "100"}],
            "100": [],
            "200": [],
        }

        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(self.payload).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            calls.append((request.get_method(), request.full_url, request.data.decode("utf-8") if request.data else ""))
            if request.get_method() == "GET":
                query = request.full_url.split("?", 1)[1]
                params = dict(part.split("=", 1) for part in query.split("&"))
                return FakeResponse({"data": folders.get(params["cid"], [])})
            body = json.loads(request.data.decode("utf-8"))
            if body["name"] == "Demo":
                folders["100"].append({"n": "Demo", "cid": "200"})
                return FakeResponse({"success": True, "data": {"cid": "200"}})
            folders["200"].append({"n": "Season 01", "cid": "300"})
            return FakeResponse({"success": True, "data": {"cid": "300"}})

        with patch("urllib.request.urlopen", fake_urlopen):
            report = ensure_mv3_115_path("http://mv3.example", "token", "/已整理/series/Demo/Season 01", storage="115-default")

        rendered = render_mv3_ensure_path_report(report, "json")
        self.assertTrue(report["ok"])
        self.assertEqual(report["final_folder_id"], "300")
        self.assertEqual([step["action"] for step in report["steps"]], ["reused", "reused", "created", "created"])
        self.assertEqual(sum(1 for method, _url, _body in calls if method == "POST"), 2)
        self.assertTrue(all("/api/v1/files/115/list" not in url for _method, url, _body in calls))
        self.assertTrue(any("/api/v1/files/115/browse" in url for method, url, _body in calls if method == "GET"))
        self.assertNotIn("token", rendered)

    def test_cloud_browse_uses_cloud_browse_and_reports_episode_gaps(self) -> None:
        seen = []

        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(self.payload).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            seen.append(request.full_url)
            if "/api/v1/files/cloud/info?" in request.full_url:
                return FakeResponse({"success": True, "data": {"file_name": "Demo", "file_id": "folder-1", "is_dir": True}})
            if "/api/v1/files/cloud/browse?" in request.full_url:
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {
                                    "name": "Demo.S01E01.mkv",
                                    "fid": "file-fid-1",
                                    "cid": "parent-folder-1",
                                    "file_id": "file-1",
                                    "is_dir": False,
                                    "size": 1024,
                                    "pc": "private-pickcode",
                                    "uid": "private-user-id",
                                    "fuuid": "private-file-user-id",
                                },
                                {"name": "Demo.S01E03.mkv", "file_id": "file-3", "is_dir": False, "size": 2048},
                            ]
                        },
                    }
                )
            raise AssertionError(f"unexpected url: {request.full_url}")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = browse_mv3_cloud_folder(
                "http://mv3.example",
                "token",
                path="/未整理/Demo",
                storage="115-default",
            )

        rendered = render_mv3_cloud_browse_report(report, "markdown")
        self.assertTrue(report["ok"])
        self.assertEqual(report["folder_id"], "folder-1")
        self.assertEqual(report["summary"]["file_count"], 2)
        self.assertEqual(report["items"][0]["file_id"], "file-fid-1")
        self.assertEqual(report["summary"]["missing_in_range"], [2])
        self.assertIn("episode_gap_detected", report["warnings"])
        self.assertTrue(any("/api/v1/files/cloud/info?" in url for url in seen))
        self.assertTrue(any("/api/v1/files/cloud/browse?" in url for url in seen))
        self.assertTrue(all("/api/v1/files/115/list" not in url for url in seen))
        self.assertIn("Demo.S01E01.mkv", rendered)
        json_report = render_mv3_cloud_browse_report(report, "json")
        self.assertNotIn("private-pickcode", json_report)
        self.assertNotIn("private-user-id", json_report)
        self.assertNotIn("private-file-user-id", json_report)

    def test_offline_status_reports_not_ready_until_task_done_and_folder_has_files(self) -> None:
        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(self.payload).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            if "offline/tasks" in request.full_url:
                return FakeResponse({"tasks": [{"info_hash": "abc", "name": "Demo", "percentDone": 0, "status": 1, "status_text": "等待中"}]})
            if "/info?" in request.full_url:
                return FakeResponse({"file_id": "300", "file_name": "Season 01"})
            return FakeResponse({"count": 0, "data": []})

        with patch("urllib.request.urlopen", fake_urlopen):
            report = check_mv3_offline_task(
                "http://mv3.example",
                "token",
                "abc",
                target_folder_id="300",
                target_path="/已整理/series/Demo/Season 01",
                storage="115-default",
            )

        rendered = render_mv3_offline_status_report(report, "json")
        self.assertTrue(report["task_found"])
        self.assertFalse(report["ready_for_strm"])
        self.assertEqual(report["task"]["status_text"], "等待中")
        self.assertNotIn("token", rendered)

    def test_offline_status_reports_ready_when_done_and_folder_has_files(self) -> None:
        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(self.payload).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            if "offline/tasks" in request.full_url:
                return FakeResponse({"tasks": [{"info_hash": "abc", "name": "Demo", "percentDone": 100, "status": 2, "status_text": "下载成功"}]})
            if "/info?" in request.full_url:
                return FakeResponse({"file_id": "300", "file_name": "Season 01"})
            return FakeResponse({"count": 1, "data": [{"n": "Demo.E01.mkv"}]})

        with patch("urllib.request.urlopen", fake_urlopen):
            report = check_mv3_offline_task(
                "http://mv3.example",
                "token",
                "abc",
                target_folder_id="300",
                target_path="/已整理/series/Demo/Season 01",
                storage="115-default",
            )

        markdown = render_mv3_offline_status_report(report, "markdown")
        self.assertTrue(report["ready_for_strm"])
        self.assertEqual(report["target_folder"]["file_count"], 1)
        self.assertIn("Ready for STRM", markdown)

    def test_resource_search_posts_keyword_and_redacts_sensitive_fields(self) -> None:
        seen = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {
                                    "title": "楚汉传奇 全集",
                                    "channel": "pansou",
                                    "share_url": "https://example.test/s/private",
                                    "image": "https://cdn.example.test/private-cover.jpg",
                                    "receive_code": "abcd",
                                    "share_code": "safe-code",
                                    "size": "150GB",
                                }
                            ]
                        },
                    }
                ).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            report = search_mv3_resources("http://mv3.example", "token", "楚汉传奇", channels=["pansou"])

        rendered = render_mv3_resource_search_report(report, "json")
        self.assertEqual(seen["url"], "http://mv3.example/api/v1/resource-search/search")
        self.assertEqual(seen["body"]["keyword"], "楚汉传奇")
        self.assertEqual(seen["body"]["channels"], ["pansou"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["result_count"], 1)
        self.assertTrue(report["items"][0]["share_code_available"])
        self.assertNotIn("share_code", report["items"][0])
        self.assertNotIn("https://example.test", rendered)
        self.assertNotIn("https://cdn.example.test", rendered)
        self.assertNotIn("abcd", rendered)
        self.assertNotIn("safe-code", rendered)
        markdown = render_mv3_resource_search_report(report, "markdown")
        self.assertIn("Share code available", markdown)
        self.assertNotIn("safe-code", markdown)

    def test_share_preview_parses_and_browses_selected_resource_without_receiving(self) -> None:
        seen = []

        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(self.payload).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            path = request.full_url.replace("http://mv3.example", "")
            body = json.loads(request.data.decode("utf-8"))
            seen.append((path, body))
            if path == "/api/v1/resource-search/search":
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"title": "Other", "share_link": "https://example.test/s/other", "share_code": "other"},
                                {"title": "楚汉传奇", "share_link": "https://example.test/s/private", "share_code": "safe-code"},
                            ]
                        },
                    }
                )
            if path == "/api/v1/share-transfer/parse":
                return FakeResponse({"success": True, "data": {"share_code": "parsed-code", "receive_code": "abcd", "face": "http://avatars.example.test/private.jpg"}})
            if path == "/api/v1/share-transfer/browse":
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"name": "楚汉传奇", "is_dir": True},
                                {"name": "楚汉传奇.E01.mkv", "size": "2147483648", "is_dir": False},
                            ]
                        },
                    }
                )
            raise AssertionError(f"unexpected path: {path}")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = preview_mv3_share(
                "http://mv3.example",
                "token",
                "楚汉传奇",
                selection_index=2,
                expected_title_contains="楚汉",
            )

        rendered = render_mv3_share_preview_report(report, "json")
        self.assertEqual([item[0] for item in seen], ["/api/v1/resource-search/search", "/api/v1/share-transfer/parse", "/api/v1/share-transfer/browse"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["browse"]["item_count"], 2)
        self.assertEqual(report["browse"]["items"][1]["size"], "2.00 GiB")
        self.assertNotIn("receive", [item[0] for item in seen])
        self.assertNotIn("https://example.test", rendered)
        self.assertNotIn("http://avatars.example.test", rendered)
        self.assertNotIn("safe-code", rendered)
        self.assertNotIn("parsed-code", rendered)
        self.assertNotIn("abcd", rendered)

    def test_share_preview_can_browse_nested_share_folder_by_cid(self) -> None:
        seen = []

        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(self.payload).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            path = request.full_url.replace("http://mv3.example", "")
            body = json.loads(request.data.decode("utf-8"))
            seen.append((path, body))
            if path == "/api/v1/resource-search/search":
                return FakeResponse({"success": True, "data": {"items": [{"title": "四喜", "share_link": "https://example.test/s/private"}]}})
            if path == "/api/v1/share-transfer/parse":
                return FakeResponse({"success": True, "data": {"share_code": "parsed-code", "receive_code": "abcd"}})
            if path == "/api/v1/share-transfer/browse":
                self.assertEqual(body["cid"], "folder-1")
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"name": "四喜.S01E01.mkv", "fid": "file-1", "is_dir": False},
                                {"name": "四喜.S01E02.mkv", "fid": "file-2", "is_dir": False},
                            ]
                        },
                    }
                )
            raise AssertionError(f"unexpected path: {path}")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = preview_mv3_share(
                "http://mv3.example",
                "token",
                "四喜",
                selection_index=1,
                browse_cid="folder-1",
                expected_title_contains="四喜",
            )

        rendered = render_mv3_share_preview_report(report, "json")
        self.assertEqual([item[0] for item in seen], ["/api/v1/resource-search/search", "/api/v1/share-transfer/parse", "/api/v1/share-transfer/browse"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["browse_cid"], "folder-1")
        self.assertEqual(report["browse"]["item_count"], 2)
        self.assertNotIn("https://example.test", rendered)
        self.assertNotIn("parsed-code", rendered)
        self.assertNotIn("abcd", rendered)

    def test_share_receive_requires_selected_browse_item_and_redacts_report(self) -> None:
        seen = []

        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(self.payload).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            path = request.full_url.replace("http://mv3.example", "")
            body = json.loads(request.data.decode("utf-8"))
            seen.append((path, body))
            if path == "/api/v1/resource-search/search":
                return FakeResponse({"success": True, "data": {"items": [{"title": "楚汉传奇", "share_link": "https://example.test/s/private"}]}})
            if path == "/api/v1/share-transfer/parse":
                return FakeResponse({"success": True, "data": {"share_code": "parsed-code", "receive_code": "abcd"}})
            if path == "/api/v1/share-transfer/browse":
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"name": "楚汉传奇 (2012)", "cid": "folder-1", "is_dir": True, "s": 282444838302},
                                {"name": "Other", "cid": "folder-2", "is_dir": True},
                            ]
                        },
                    }
                )
            if path == "/api/v1/share-transfer/receive":
                return FakeResponse({"success": True, "data": {"record_id": "record-1", "share_code": "parsed-code"}})
            raise AssertionError(f"unexpected path: {path}")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = receive_mv3_share(
                "http://mv3.example",
                "token",
                "楚汉传奇",
                selection_index=1,
                browse_index=1,
                expected_title_contains="楚汉",
                target_path="/未整理",
                storage="115-default",
            )

        rendered = render_mv3_share_receive_report(report, "json")
        self.assertEqual(
            [item[0] for item in seen],
            [
                "/api/v1/resource-search/search",
                "/api/v1/share-transfer/parse",
                "/api/v1/share-transfer/browse",
                "/api/v1/share-transfer/receive",
            ],
        )
        receive_body = seen[-1][1]
        self.assertEqual(receive_body["file_ids"], ["folder-1"])
        self.assertEqual(receive_body["target_path"], "/未整理")
        self.assertEqual(receive_body["storage"], "115-default")
        self.assertTrue(report["ok"])
        self.assertEqual(report["browse_selection"]["name"], "楚汉传奇 (2012)")
        self.assertEqual(report["browse_selection"]["size"], "263.05 GiB")
        self.assertNotIn("https://example.test", rendered)
        self.assertNotIn("parsed-code", rendered)
        self.assertNotIn("abcd", rendered)

    def test_share_receive_can_select_item_from_nested_share_folder(self) -> None:
        seen = []

        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(self.payload).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            path = request.full_url.replace("http://mv3.example", "")
            body = json.loads(request.data.decode("utf-8"))
            seen.append((path, body))
            if path == "/api/v1/resource-search/search":
                return FakeResponse({"success": True, "data": {"items": [{"title": "四喜", "share_link": "https://example.test/s/private"}]}})
            if path == "/api/v1/share-transfer/parse":
                return FakeResponse({"success": True, "data": {"share_code": "parsed-code", "receive_code": "abcd"}})
            if path == "/api/v1/share-transfer/browse":
                self.assertEqual(body["cid"], "folder-1")
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"name": "四喜 完整版", "cid": "version-1", "is_dir": True, "s": 139694577664},
                                {"name": "四喜 低码版", "cid": "version-2", "is_dir": True},
                            ]
                        },
                    }
                )
            if path == "/api/v1/share-transfer/receive":
                return FakeResponse({"success": True, "data": {"record_id": "record-1"}})
            raise AssertionError(f"unexpected path: {path}")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = receive_mv3_share(
                "http://mv3.example",
                "token",
                "四喜",
                selection_index=1,
                browse_index=1,
                browse_cid="folder-1",
                expected_title_contains="四喜",
                target_path="/未整理",
                storage="115-default",
            )

        rendered = render_mv3_share_receive_report(report, "json")
        self.assertEqual(
            [item[0] for item in seen],
            [
                "/api/v1/resource-search/search",
                "/api/v1/share-transfer/parse",
                "/api/v1/share-transfer/browse",
                "/api/v1/share-transfer/receive",
            ],
        )
        browse_body = seen[2][1]
        receive_body = seen[-1][1]
        self.assertEqual(browse_body["cid"], "folder-1")
        self.assertEqual(receive_body["file_ids"], ["version-1"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["browse_cid"], "folder-1")
        self.assertEqual(report["browse_selection"]["file_id"], "version-1")
        self.assertNotIn("https://example.test", rendered)
        self.assertNotIn("parsed-code", rendered)
        self.assertNotIn("abcd", rendered)

    def test_organize_scan_source_reports_episode_gaps_without_transfer(self) -> None:
        seen = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {
                                    "path": "/未整理/Demo/Demo.S01E01.mp4",
                                    "name": "Demo.S01E01.mp4",
                                    "size": 1024,
                                    "is_cloud_source": True,
                                    "source_file_id": "file-1",
                                    "skip_reason": "",
                                    "in_library": True,
                                },
                                {
                                    "path": "/未整理/Demo/Demo.S01E03.mp4",
                                    "name": "Demo.S01E03.mp4",
                                    "size": 2048,
                                    "is_cloud_source": True,
                                    "source_file_id": "file-3",
                                    "skip_reason": "",
                                    "in_library": True,
                                },
                            ],
                            "summary": {"total": 2, "candidate": 2, "in_library": 2},
                        },
                    }
                ).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            report = scan_mv3_organize_source(
                "http://mv3.example",
                "token",
                "/未整理/Demo",
                source_file_id="folder-1",
            )

        rendered = render_mv3_organize_scan_report(report, "markdown")
        self.assertEqual(seen["url"], "http://mv3.example/api/v1/organize/scan-source")
        self.assertEqual(seen["body"]["sources"][0]["source_path"], "/未整理/Demo")
        self.assertEqual(seen["body"]["sources"][0]["source_file_id"], "folder-1")
        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["episode_count"], 2)
        self.assertEqual(report["summary"]["missing_in_range"], [2])
        self.assertIn("episode_gap_detected", report["warnings"])
        self.assertIn("all_scan_items_marked_in_library", report["warnings"])
        self.assertIn("Demo.S01E01.mp4", rendered)

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

    def test_cli_refuses_ensure_path_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with self.assertRaises(SystemExit):
                main(
                    [
                        "mv3-ensure-115-path",
                        "--env-file",
                        str(env_file),
                        "--target-path",
                        "/已整理/series/Demo",
                    ]
                )

    def test_cli_refuses_mp_cleanup_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            preview = tmp_path / "preview.json"
            env_file.write_text("MP_BASE_URL=http://moviepilot.example\nMP_API_TOKEN=token\n", encoding="utf-8")
            preview.write_text(json.dumps({"mode": "readonly-mp-cleanup-preview"}), encoding="utf-8")

            with self.assertRaises(SystemExit):
                main(
                    [
                        "mp-cleanup-execute",
                        "--env-file",
                        str(env_file),
                        "--preview-report",
                        str(preview),
                        "--expected-title",
                        "Demo",
                        "--expected-tmdbid",
                        "123",
                        "--expected-hash-prefix",
                        "feedface0000",
                        "--expected-record-count",
                        "2",
                        "--expected-episode-count",
                        "2",
                        "--expected-episode-min",
                        "1",
                        "--expected-episode-max",
                        "2",
                    ]
                )

    def test_cli_writes_offline_status_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "status.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __init__(self, payload):
                    self.payload = payload

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    return json.dumps(self.payload).encode("utf-8")

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            def fake_urlopen(request, timeout):
                if "offline/tasks" in request.full_url:
                    return FakeResponse({"tasks": [{"info_hash": "abc", "name": "Demo", "percentDone": 0, "status_text": "等待中"}]})
                if "/info?" in request.full_url:
                    return FakeResponse({"file_id": "300", "file_name": "Season 01"})
                return FakeResponse({"count": 0, "data": []})

            with patch("urllib.request.urlopen", fake_urlopen):
                code = main(
                    [
                        "mv3-offline-status-one",
                        "--env-file",
                        str(env_file),
                        "--info-hash",
                        "abc",
                        "--target-folder-id",
                        "300",
                        "--target-path",
                        "/已整理/series/Demo/Season 01",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(payload["ready_for_strm"])

    def test_cli_writes_resource_search_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "search.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    return b'{"success":true,"data":{"items":[{"title":"Demo"}]}}'

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                code = main(
                    [
                        "mv3-resource-search",
                        "--env-file",
                        str(env_file),
                        "--keyword",
                        "Demo",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["result_count"], 1)

    def test_cli_writes_share_preview_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "preview.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __init__(self, payload):
                    self.payload = payload

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    return json.dumps(self.payload).encode("utf-8")

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            def fake_urlopen(request, timeout):
                path = request.full_url.replace("http://mv3.example", "")
                if path == "/api/v1/resource-search/search":
                    return FakeResponse({"success": True, "data": {"items": [{"title": "Demo", "share_link": "https://example.test/s/private"}]}})
                if path == "/api/v1/share-transfer/parse":
                    return FakeResponse({"success": True, "data": {"share_code": "parsed-code"}})
                if path == "/api/v1/share-transfer/browse":
                    return FakeResponse({"success": True, "data": {"items": [{"name": "Demo.E01.mkv", "is_dir": False}]}})
                raise AssertionError(f"unexpected path: {path}")

            with patch("urllib.request.urlopen", fake_urlopen):
                code = main(
                    [
                        "mv3-share-preview",
                        "--env-file",
                        str(env_file),
                        "--keyword",
                        "Demo",
                        "--expected-title-contains",
                        "Demo",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["browse"]["item_count"], 1)
            self.assertNotIn("https://example.test", output.read_text(encoding="utf-8"))

    def test_cli_writes_share_preview_report_for_nested_cid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "preview.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __init__(self, payload):
                    self.payload = payload

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    return json.dumps(self.payload).encode("utf-8")

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            def fake_urlopen(request, timeout):
                path = request.full_url.replace("http://mv3.example", "")
                body = json.loads(request.data.decode("utf-8"))
                if path == "/api/v1/resource-search/search":
                    return FakeResponse({"success": True, "data": {"items": [{"title": "Demo", "share_link": "https://example.test/s/private"}]}})
                if path == "/api/v1/share-transfer/parse":
                    return FakeResponse({"success": True, "data": {"share_code": "parsed-code"}})
                if path == "/api/v1/share-transfer/browse":
                    self.assertEqual(body["cid"], "folder-1")
                    return FakeResponse({"success": True, "data": {"items": [{"name": "Demo.S01E01.mkv", "fid": "file-1", "is_dir": False}]}})
                raise AssertionError(f"unexpected path: {path}")

            with patch("urllib.request.urlopen", fake_urlopen):
                code = main(
                    [
                        "mv3-share-preview",
                        "--env-file",
                        str(env_file),
                        "--keyword",
                        "Demo",
                        "--expected-title-contains",
                        "Demo",
                        "--browse-cid",
                        "folder-1",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["browse_cid"], "folder-1")
            self.assertEqual(payload["browse"]["item_count"], 1)

    def test_cli_refuses_share_receive_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as caught:
                main(
                    [
                        "mv3-share-receive-one",
                        "--env-file",
                        str(env_file),
                        "--keyword",
                        "Demo",
                        "--expected-title-contains",
                        "Demo",
                    ]
                )

            self.assertNotEqual(caught.exception.code, 0)

    def test_cli_writes_share_receive_report_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "receive.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __init__(self, payload):
                    self.payload = payload

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    return json.dumps(self.payload).encode("utf-8")

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            def fake_urlopen(request, timeout):
                path = request.full_url.replace("http://mv3.example", "")
                if path == "/api/v1/resource-search/search":
                    return FakeResponse({"success": True, "data": {"items": [{"title": "Demo", "share_link": "https://example.test/s/private"}]}})
                if path == "/api/v1/share-transfer/parse":
                    return FakeResponse({"success": True, "data": {"share_code": "parsed-code"}})
                if path == "/api/v1/share-transfer/browse":
                    return FakeResponse({"success": True, "data": {"items": [{"name": "Demo", "cid": "folder-1", "is_dir": True}]}})
                if path == "/api/v1/share-transfer/receive":
                    return FakeResponse({"success": True, "data": {"record_id": "record-1"}})
                raise AssertionError(f"unexpected path: {path}")

            with patch("urllib.request.urlopen", fake_urlopen):
                code = main(
                    [
                        "mv3-share-receive-one",
                        "--env-file",
                        str(env_file),
                        "--keyword",
                        "Demo",
                        "--expected-title-contains",
                        "Demo",
                        "--target-path",
                        "/未整理",
                        "--approve-receive",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["target_path"], "/未整理")

    def test_cli_writes_organize_scan_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "organize-scan.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    return b'{"success":true,"data":{"items":[{"name":"Demo.S01E01.mp4","source_file_id":"file-1"}],"summary":{"total":1,"candidate":1}}}'

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                code = main(
                    [
                        "mv3-organize-scan-source",
                        "--env-file",
                        str(env_file),
                        "--source-path",
                        "/未整理/Demo",
                        "--source-file-id",
                        "folder-1",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["total"], 1)

    def test_cli_writes_cloud_browse_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "cloud-browse.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    return b'{"success":true,"data":{"items":[{"name":"Demo.S01E01.mp4","file_id":"file-1","is_dir":false}]}}'

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                code = main(
                    [
                        "mv3-cloud-browse",
                        "--env-file",
                        str(env_file),
                        "--folder-id",
                        "folder-1",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["item_count"], 1)

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
                                "proposed_cloud_destination": "/已整理/series/Demo",
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
