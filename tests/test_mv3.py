import json
import socket
import tempfile
import urllib.parse
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.mv3 import (
    MV3Client,
    add_mv3_offline_task,
    browse_mv3_cloud_folder,
    check_mv3_offline_task,
    cleanup_mv3_cloud_duplicate_videos,
    cleanup_mv3_cloud_media_sidecars,
    ensure_mv3_115_path,
    inspect_mv3_capabilities,
    inspect_mv3_instances,
    list_mv3_strm_records,
    materialize_mv3_strm_records,
    probe_mv3,
    redirect_mv3_strm_records,
    render_mv3_capabilities_report,
    render_mv3_cloud_browse_report,
    render_mv3_cloud_duplicate_video_cleanup_report,
    render_mv3_cloud_media_sidecar_cleanup_report,
    render_mv3_cloud_media_sidecar_verify_report,
    render_mv3_ensure_path_report,
    render_mv3_instances_report,
    render_mv3_offline_add_report,
    render_mv3_offline_status_report,
    render_mv3_organize_transfer_report,
    render_mv3_organize_scan_report,
    render_mv3_probe_report,
    render_mv3_resource_search_report,
    render_mv3_share_receive_report,
    render_mv3_share_preview_report,
    render_mv3_strm_generate_report,
    render_mv3_strm_records_materialize_report,
    render_mv3_strm_records_redirect_report,
    render_mv3_strm_records_report,
    render_mv3_strm_records_regenerate_report,
    render_mv3_wrong_root_repair_report,
    repair_mv3_wrong_root,
    scan_mv3_organize_source,
    search_mv3_resources,
    verify_mv3_cloud_media_sidecars,
    preview_mv3_share,
    receive_mv3_share,
    execute_mv3_organize_transfer_from_browse_report,
    generate_mv3_strm,
    regenerate_mv3_strm_records,
)


class MV3WrongRootRepairTest(unittest.TestCase):
    def test_wrong_root_repair_dry_run_plans_duplicate_delete_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strm_root = Path(tmp) / "strm" / "series"
            title = "好好的时光 (2026) {tmdbid=283682}"
            season_dir = strm_root / title / "Season 01"
            season_dir.mkdir(parents=True)
            (season_dir / "好好的时光 - S01E01.strm").write_text("/已整理/series/好好的时光 (2026) {tmdbid=283682}/Season 1/E01.mkv", encoding="utf-8")
            (season_dir / "好好的时光 - S01E02.strm").write_text("/已整理/series/好好的时光 (2026) {tmdbid=283682}/Season 1/E02.mkv", encoding="utf-8")
            calls = []

            def fake_urlopen(request, timeout):
                calls.append((request.get_method(), request.full_url, getattr(request, "data", None)))
                return _fake_mv3_wrong_root_response(request, deleted=False, moved=False)

            with patch("urllib.request.urlopen", fake_urlopen):
                report = repair_mv3_wrong_root(
                    "http://mv3.example",
                    "token",
                    "/已整理/series/series",
                    "/已整理/series",
                    str(strm_root),
                    storage="115-default",
                )

            rendered = render_mv3_wrong_root_repair_report(report, "json")
            self.assertTrue(report["ok"])
            self.assertTrue(report["dry_run"])
            self.assertEqual(report["items"][0]["decision"], "delete_duplicate_wrong_season")
            self.assertEqual(report["items"][0]["action"], "dry_run_delete_duplicate_wrong_season")
            self.assertFalse(any("/api/v1/files/115/delete" in url or "/api/v1/files/115/move" in url for _method, url, _body in calls))
            self.assertNotIn("token", rendered)

    def test_wrong_root_repair_deletes_duplicate_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strm_root = Path(tmp) / "strm" / "series"
            title = "好好的时光 (2026) {tmdbid=283682}"
            season_dir = strm_root / title / "Season 01"
            season_dir.mkdir(parents=True)
            for episode in (1, 2):
                (season_dir / f"好好的时光 - S01E{episode:02d}.strm").write_text(
                    f"/已整理/series/好好的时光 (2026) {{tmdbid=283682}}/Season 1/E{episode:02d}.mkv",
                    encoding="utf-8",
                )
            posted = []
            state = {"deleted": False}

            def fake_urlopen(request, timeout):
                if getattr(request, "data", None):
                    posted.append((request.full_url, json.loads(request.data.decode("utf-8"))))
                    if request.full_url.endswith("/api/v1/files/115/delete"):
                        state["deleted"] = True
                return _fake_mv3_wrong_root_response(request, deleted=state["deleted"], moved=False)

            with patch("urllib.request.urlopen", fake_urlopen):
                report = repair_mv3_wrong_root(
                    "http://mv3.example",
                    "token",
                    "/已整理/series/series",
                    "/已整理/series",
                    str(strm_root),
                    storage="115-default",
                    approve_delete_duplicates=True,
                    approve_delete_empty=True,
                )

            self.assertTrue(report["ok"])
            delete_bodies = [body for url, body in posted if url.endswith("/api/v1/files/115/delete")]
            self.assertTrue(delete_bodies)
            self.assertIn("wrong-season-1", delete_bodies[0]["file_ids"])
            self.assertIn("115-default", delete_bodies[0]["storage"])
            self.assertEqual(report["post_verify"]["wrong_root_child_count"], 0)

    def test_wrong_root_repair_moves_wrong_media_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            strm_root = Path(tmp) / "strm" / "series"
            title = "一笑随歌 (2025) {tmdbid=272484}"
            season_dir = strm_root / title / "Season 01"
            season_dir.mkdir(parents=True)
            for episode in (1, 2):
                (season_dir / f"一笑随歌 - S01E{episode:02d}.strm").write_text(
                    f"/已整理/series/一笑随歌 (2025) {{tmdbid=272484}}/Season 1/E{episode:02d}.mkv",
                    encoding="utf-8",
                )
            posted = []
            state = {"moved": False, "deleted": False}

            def fake_urlopen(request, timeout):
                if getattr(request, "data", None):
                    posted.append((request.full_url, json.loads(request.data.decode("utf-8"))))
                    if request.full_url.endswith("/api/v1/files/115/move"):
                        state["moved"] = True
                    if request.full_url.endswith("/api/v1/files/115/delete"):
                        state["deleted"] = True
                return _fake_mv3_wrong_root_response(request, move_case=True, deleted=state["deleted"], moved=state["moved"])

            with patch("urllib.request.urlopen", fake_urlopen):
                report = repair_mv3_wrong_root(
                    "http://mv3.example",
                    "token",
                    "/已整理/series/series",
                    "/已整理/series",
                    str(strm_root),
                    storage="115-default",
                    approve_move=True,
                    approve_delete_empty=True,
                )

            self.assertTrue(report["ok"])
            move_bodies = [body for url, body in posted if url.endswith("/api/v1/files/115/move")]
            self.assertEqual(move_bodies[0]["file_ids"], ["wrong-file-1", "wrong-file-2"])
            self.assertEqual(move_bodies[0]["target_cid"], "correct-season-1")
            self.assertEqual(report["items"][0]["decision"], "move_wrong_media_to_correct_season")

    def test_cli_writes_wrong_root_repair_dry_run_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "repair.json"
            strm_root = tmp_path / "strm" / "series"
            title = "好好的时光 (2026) {tmdbid=283682}"
            season_dir = strm_root / title / "Season 01"
            season_dir.mkdir(parents=True)
            (season_dir / "好好的时光 - S01E01.strm").write_text("/已整理/series/好好的时光 (2026) {tmdbid=283682}/Season 1/E01.mkv", encoding="utf-8")
            (season_dir / "好好的时光 - S01E02.strm").write_text("/已整理/series/好好的时光 (2026) {tmdbid=283682}/Season 1/E02.mkv", encoding="utf-8")
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with patch("urllib.request.urlopen", lambda request, timeout: _fake_mv3_wrong_root_response(request, deleted=False, moved=False)):
                code = main(
                    [
                        "mv3-repair-wrong-root",
                        "--env-file",
                        str(env_file),
                        "--wrong-root",
                        "/已整理/series/series",
                        "--correct-root",
                        "/已整理/series",
                        "--strm-root",
                        str(strm_root),
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["items"][0]["action"], "dry_run_delete_duplicate_wrong_season")

    def test_cli_refuses_cloud_sidecar_cleanup_approval_without_expected_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with patch("urllib.request.urlopen") as fake_urlopen:
                with self.assertRaises(SystemExit) as caught:
                    main(
                        [
                            "mv3-cloud-media-sidecar-cleanup",
                            "--env-file",
                            str(env_file),
                            "--path",
                            "/已整理/series/Demo",
                            "--approve-delete",
                        ]
                    )

            self.assertNotEqual(caught.exception.code, 0)
            fake_urlopen.assert_not_called()

    def test_cli_writes_cloud_sidecar_cleanup_dry_run_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "cleanup.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with patch("urllib.request.urlopen", lambda request, timeout: _fake_mv3_sidecar_cleanup_response(request, deleted=False)):
                code = main(
                    [
                        "mv3-cloud-media-sidecar-cleanup",
                        "--env-file",
                        str(env_file),
                        "--path",
                        "/已整理/series/Demo",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["delete_plan"]["metadata_sidecar_count"], 2)
            self.assertEqual(payload["delete_plan"]["file_ids"], ["nfo-1", "poster-1"])

    def test_cli_refuses_cloud_duplicate_video_cleanup_approval_without_expected_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            strm_root = tmp_path / "strm"
            strm_root.mkdir()
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with patch("urllib.request.urlopen") as fake_urlopen:
                with self.assertRaises(SystemExit) as caught:
                    main(
                        [
                            "mv3-cloud-duplicate-video-cleanup",
                            "--env-file",
                            str(env_file),
                            "--season-path",
                            "/已整理/series/Demo/Season 1",
                            "--strm-root",
                            str(strm_root),
                            "--expected-episode-count",
                            "2",
                            "--approve-delete",
                        ]
                    )

            self.assertNotEqual(caught.exception.code, 0)
            fake_urlopen.assert_not_called()

    def test_cli_writes_cloud_duplicate_video_cleanup_dry_run_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "duplicate.json"
            strm_root = tmp_path / "strm"
            strm_root.mkdir()
            for episode in (1, 2):
                (strm_root / f"Demo - S01E{episode:02d}.strm").write_text(
                    f"/已整理/series/Demo/Season 1/Demo - S01E{episode:02d}.mkv",
                    encoding="utf-8",
                )
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with patch("urllib.request.urlopen", lambda request, timeout: _fake_mv3_duplicate_video_cleanup_response(request, deleted=False)):
                code = main(
                    [
                        "mv3-cloud-duplicate-video-cleanup",
                        "--env-file",
                        str(env_file),
                        "--season-path",
                        "/已整理/series/Demo/Season 1",
                        "--folder-id",
                        "season-id",
                        "--strm-root",
                        str(strm_root),
                        "--expected-episode-count",
                        "2",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["delete_plan"]["duplicate_video_count"], 2)


def _fake_mv3_wrong_root_response(request, move_case=False, deleted=False, moved=False):
    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def read(self, _limit=-1):
            return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

        @property
        def headers(self):
            return {"Content-Type": "application/json"}

    parsed = urllib.parse.urlparse(request.full_url)
    query = urllib.parse.parse_qs(parsed.query)
    path = query.get("path", [""])[0]
    cid = query.get("cid", [""])[0]
    if parsed.path.endswith("/api/v1/files/115/delete") or parsed.path.endswith("/api/v1/files/115/move"):
        return FakeResponse({"success": True, "message": "ok", "data": None})

    if move_case:
        title = "一笑随歌 (2025) {tmdbid=272484}"
        wrong_title = "wrong-title-move"
        wrong_season = "wrong-season-move"
        correct_title = "correct-title-move"
        correct_season = "correct-season-1"
        wrong_files_before = [
            {"name": "一笑随歌 - S01E01.mkv", "fid": "wrong-file-1", "is_dir": False},
            {"name": "一笑随歌 - S01E02.mkv", "fid": "wrong-file-2", "is_dir": False},
        ]
        wrong_files_after = []
        correct_files_after = [
            {"name": "一笑随歌 - S01E01.mkv", "fid": "wrong-file-1", "is_dir": False},
            {"name": "一笑随歌 - S01E02.mkv", "fid": "wrong-file-2", "is_dir": False},
        ]
        info = {
            "/已整理/series/series": {"name": "series", "cid": "wrong-root", "is_dir": True},
            f"/已整理/series/series/{title}": {"name": title, "cid": wrong_title, "is_dir": True},
            f"/已整理/series/series/{title}/Season 1": {"name": "Season 1", "cid": wrong_season, "is_dir": True},
            f"/已整理/series/{title}": {"name": title, "cid": correct_title, "is_dir": True},
            f"/已整理/series/{title}/Season 1": {"name": "Season 1", "cid": correct_season, "is_dir": True},
        }
        browse = {
            "wrong-root": [] if deleted else [{"name": title, "cid": wrong_title, "is_dir": True}],
            wrong_title: [] if deleted else [{"name": "Season 1", "cid": wrong_season, "is_dir": True}],
            wrong_season: wrong_files_after if moved else wrong_files_before,
            correct_title: [{"name": "Season 1", "cid": correct_season, "is_dir": True}],
            correct_season: correct_files_after if moved else [],
        }
    else:
        title = "好好的时光 (2026) {tmdbid=283682}"
        info = {
            "/已整理/series/series": {"name": "series", "cid": "wrong-root", "is_dir": True},
            f"/已整理/series/series/{title}": {"name": title, "cid": "wrong-title-1", "is_dir": True},
            f"/已整理/series/series/{title}/Season 1": {"name": "Season 1", "cid": "wrong-season-1", "is_dir": True},
            f"/已整理/series/{title}": {"name": title, "cid": "correct-title-1", "is_dir": True},
            f"/已整理/series/{title}/Season 1": {"name": "Season 1", "cid": "correct-season-1", "is_dir": True},
        }
        duplicate_files = [
            {"name": "好好的时光 - S01E01.mkv", "fid": "file-1", "is_dir": False},
            {"name": "好好的时光 - S01E02.mkv", "fid": "file-2", "is_dir": False},
        ]
        browse = {
            "wrong-root": [] if deleted else [{"name": title, "cid": "wrong-title-1", "is_dir": True}],
            "wrong-title-1": [] if deleted else [{"name": "Season 1", "cid": "wrong-season-1", "is_dir": True}],
            "wrong-season-1": [] if deleted else duplicate_files,
            "correct-title-1": [{"name": "Season 1", "cid": "correct-season-1", "is_dir": True}],
            "correct-season-1": duplicate_files,
        }

    if parsed.path.endswith("/api/v1/files/cloud/info"):
        return FakeResponse({"success": True, "data": info.get(path, {})})
    if parsed.path.endswith("/api/v1/files/cloud/browse") or parsed.path.endswith("/api/v1/files/115/browse"):
        return FakeResponse({"success": True, "data": {"items": browse.get(cid, [])}})
    return FakeResponse({"success": True, "data": {}})


def _fake_mv3_sidecar_cleanup_response(request, deleted=False):
    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def read(self, _limit=-1):
            return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

        @property
        def headers(self):
            return {"Content-Type": "application/json"}

    parsed = urllib.parse.urlparse(request.full_url)
    query = urllib.parse.parse_qs(parsed.query)
    cid = query.get("cid", [""])[0]
    if parsed.path.endswith("/api/v1/files/115/delete"):
        return FakeResponse({"success": True, "message": "ok", "data": None})
    if parsed.path.endswith("/api/v1/files/cloud/info"):
        return FakeResponse({"success": True, "data": {"file_name": "Demo", "file_id": "root-id", "is_dir": True}})
    if parsed.path.endswith("/api/v1/files/cloud/browse"):
        if cid == "root-id":
            return FakeResponse({"success": True, "data": {"items": [{"name": "Season 1", "file_id": "season-id", "is_dir": True}]}})
        if cid == "season-id":
            items = [
                {"name": "Demo.S01E01.mkv", "fid": "video-1", "is_dir": False},
                {"name": "Demo.S01E01.ass", "fid": "sub-1", "is_dir": False},
            ]
            if not deleted:
                items.extend(
                    [
                        {"name": "Demo.S01E01.nfo", "fid": "nfo-1", "is_dir": False},
                        {"name": "poster.jpg", "fid": "poster-1", "is_dir": False},
                    ]
                )
            return FakeResponse({"success": True, "data": {"items": items}})
    raise AssertionError(f"unexpected url: {request.full_url}")


def _fake_mv3_duplicate_video_cleanup_response(request, deleted=False, empty_info=False, raw_115_names=False):
    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def read(self, _limit=-1):
            return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

        @property
        def headers(self):
            return {"Content-Type": "application/json"}

    parsed = urllib.parse.urlparse(request.full_url)
    query = urllib.parse.parse_qs(parsed.query)
    cid = query.get("cid", [""])[0]
    if parsed.path.endswith("/api/v1/files/115/delete"):
        return FakeResponse({"success": True, "message": "ok", "data": None})
    if parsed.path.endswith("/api/v1/files/cloud/info"):
        if empty_info:
            return FakeResponse({"success": True, "data": {}})
        return FakeResponse(
            {
                "success": True,
                "data": {
                    "file_name": "Season 1",
                    "parent_id": "season-id",
                    "parent_path": "/已整理/series/Demo/Season 1",
                    "paths": [
                        {"name": "已整理", "cid": "root"},
                        {"name": "series", "cid": "series"},
                        {"name": "Demo", "cid": "title-id"},
                        {"name": "Season 1", "cid": "season-id"},
                    ],
                },
            }
        )
    if parsed.path.endswith("/api/v1/files/cloud/browse"):
        if cid == "season-id":
            name_key = "fn" if raw_115_names else "name"
            items = [
                {name_key: "Demo - S01E01.mkv", "fid": "video-1", "is_dir": False},
                {name_key: "Demo - S01E02.mkv", "fid": "video-2", "is_dir": False},
            ]
            if not deleted:
                items.extend(
                    [
                        {name_key: "Demo - S01E01(1).mkv", "fid": "dup-1", "is_dir": False},
                        {name_key: "Demo - S01E02(1).mkv", "fid": "dup-2", "is_dir": False},
                    ]
                )
            return FakeResponse({"success": True, "data": {"items": items}})
    raise AssertionError(f"unexpected url: {request.full_url}")


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

    def test_cloud_browse_marks_sidecar_subtitles_and_counts_video_episodes(self) -> None:
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
            if "/api/v1/files/cloud/info?" in request.full_url:
                return FakeResponse({"success": True, "data": {"file_name": "DearX", "file_id": "folder-1", "is_dir": True}})
            if "/api/v1/files/cloud/browse?" in request.full_url:
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"name": "Dear.X.S01E01.mkv", "fid": "video-1", "is_dir": False, "s": 1000},
                                {"name": "Dear.X.S01E01.ass", "fid": "sub-1", "is_dir": False, "s": 10},
                                {"name": "Dear.X.S01E02.mkv", "fid": "video-2", "is_dir": False, "s": 1000},
                                {"name": "Dear.X.S01E02.ass", "fid": "sub-2", "is_dir": False, "s": 10},
                            ]
                        },
                    }
                )
            raise AssertionError(f"unexpected url: {request.full_url}")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = browse_mv3_cloud_folder("http://mv3.example", "token", path="/未整理/DearX")

        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["file_count"], 4)
        self.assertEqual(report["summary"]["video_file_count"], 2)
        self.assertEqual(report["summary"]["sidecar_file_count"], 2)
        self.assertEqual(report["summary"]["subtitle_sidecar_file_count"], 2)
        self.assertEqual(report["summary"]["metadata_sidecar_file_count"], 0)
        self.assertEqual(report["summary"]["episode_count"], 2)
        self.assertEqual([item["media_kind"] for item in report["items"]], ["video", "subtitle_sidecar", "video", "subtitle_sidecar"])
        self.assertEqual(report["summary"]["missing_in_range"], [])

    def test_cloud_browse_treats_115_fid_only_root_rows_as_folders(self) -> None:
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
            if "/api/v1/files/cloud/browse?" in request.full_url:
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"fn": "已整理", "fid": "folder-1", "pid": "0", "fc": "0"},
                                {"fn": "根目录.txt", "fid": "file-1", "pid": "0", "fc": "1", "fs": 32, "ico": "txt", "sha1": "abc"},
                            ]
                        },
                    }
                )
            raise AssertionError(f"unexpected url: {request.full_url}")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = browse_mv3_cloud_folder("http://mv3.example", "token", folder_id="0")

        self.assertTrue(report["ok"])
        self.assertEqual(report["summary"]["folder_count"], 1)
        self.assertEqual(report["summary"]["file_count"], 1)
        self.assertEqual([item["kind"] for item in report["items"]], ["folder", "file"])

    def test_cloud_browse_marks_metadata_sidecars_separately(self) -> None:
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
            if "/api/v1/files/cloud/info?" in request.full_url:
                return FakeResponse({"success": True, "data": {"file_name": "Demo", "file_id": "folder-1", "is_dir": True}})
            if "/api/v1/files/cloud/browse?" in request.full_url:
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"name": "Demo.S01E01.mkv", "fid": "video-1", "is_dir": False},
                                {"name": "Demo.S01E01.nfo", "fid": "nfo-1", "is_dir": False},
                                {"name": "poster.jpg", "fid": "jpg-1", "is_dir": False},
                            ]
                        },
                    }
                )
            raise AssertionError(f"unexpected url: {request.full_url}")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = browse_mv3_cloud_folder("http://mv3.example", "token", path="/已整理/series/Demo")

        self.assertEqual(report["summary"]["video_file_count"], 1)
        self.assertEqual(report["summary"]["metadata_sidecar_file_count"], 2)
        self.assertEqual(report["summary"]["metadata_sidecar_samples"], ["Demo.S01E01.nfo", "poster.jpg"])
        self.assertEqual([item["media_kind"] for item in report["items"]], ["video", "metadata_sidecar", "metadata_sidecar"])

    def test_cloud_media_sidecar_verify_blocks_metadata_and_allows_subtitles(self) -> None:
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
            parsed = urllib.parse.urlparse(request.full_url)
            query = urllib.parse.parse_qs(parsed.query)
            if parsed.path.endswith("/api/v1/files/cloud/info"):
                return FakeResponse({"success": True, "data": {"file_name": "Demo", "file_id": "root-id", "is_dir": True}})
            if parsed.path.endswith("/api/v1/files/cloud/browse"):
                cid = query.get("cid", [""])[0]
                if cid == "root-id":
                    return FakeResponse({"success": True, "data": {"items": [{"name": "Season 1", "file_id": "season-id", "is_dir": True}]}})
                if cid == "season-id":
                    return FakeResponse(
                        {
                            "success": True,
                            "data": {
                                "items": [
                                    {"name": "Demo.S01E01.mkv", "fid": "video-1", "is_dir": False},
                                    {"name": "Demo.S01E01.ass", "fid": "sub-1", "is_dir": False},
                                    {"name": "Demo.S01E01.nfo", "fid": "nfo-1", "is_dir": False},
                                ]
                            },
                        }
                    )
            raise AssertionError(f"unexpected url: {request.full_url}")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = verify_mv3_cloud_media_sidecars("http://mv3.example", "token", path="/已整理/series/Demo")

        rendered = render_mv3_cloud_media_sidecar_verify_report(report, "markdown")
        self.assertFalse(report["ok"])
        self.assertIn("cloud_media_metadata_sidecar_present", report["blockers"])
        self.assertEqual(report["scan"]["video_file_count"], 1)
        self.assertEqual(report["scan"]["subtitle_sidecar_file_count"], 1)
        self.assertEqual(report["scan"]["metadata_sidecar_file_count"], 1)
        self.assertIn("/已整理/series/Demo/Season 1/Demo.S01E01.nfo", rendered)

    def test_cloud_media_sidecar_cleanup_dry_run_plans_metadata_only(self) -> None:
        calls = []

        def fake_urlopen(request, timeout):
            calls.append((request.get_method(), request.full_url, getattr(request, "data", None)))
            return _fake_mv3_sidecar_cleanup_response(request, deleted=False)

        with patch("urllib.request.urlopen", fake_urlopen):
            report = cleanup_mv3_cloud_media_sidecars("http://mv3.example", "token", path="/已整理/series/Demo")

        rendered = render_mv3_cloud_media_sidecar_cleanup_report(report, "json")
        self.assertTrue(report["ok"])
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["delete_plan"]["metadata_sidecar_count"], 2)
        self.assertEqual(report["delete_plan"]["file_ids"], ["nfo-1", "poster-1"])
        self.assertFalse(any("/api/v1/files/115/delete" in url for _method, url, _body in calls))
        self.assertNotIn("video-1", json.dumps(report["delete_plan"], ensure_ascii=False))
        self.assertNotIn("sub-1", json.dumps(report["delete_plan"], ensure_ascii=False))
        self.assertNotIn("token", rendered)

    def test_cloud_media_sidecar_cleanup_deletes_only_metadata_with_approval(self) -> None:
        posted = []
        state = {"deleted": False}

        def fake_urlopen(request, timeout):
            if getattr(request, "data", None):
                posted.append((request.full_url, json.loads(request.data.decode("utf-8"))))
                if request.full_url.endswith("/api/v1/files/115/delete"):
                    state["deleted"] = True
            return _fake_mv3_sidecar_cleanup_response(request, deleted=state["deleted"])

        with patch("urllib.request.urlopen", fake_urlopen):
            report = cleanup_mv3_cloud_media_sidecars(
                "http://mv3.example",
                "token",
                path="/已整理/series/Demo",
                approve_delete=True,
                expected_delete_count=2,
            )

        self.assertTrue(report["ok"])
        delete_bodies = [body for url, body in posted if url.endswith("/api/v1/files/115/delete")]
        self.assertEqual(len(delete_bodies), 1)
        self.assertEqual(delete_bodies[0]["file_ids"], ["nfo-1", "poster-1"])
        self.assertEqual(report["post_scan"]["metadata_sidecar_file_count"], 0)
        self.assertEqual(report["post_scan"]["video_file_count"], 1)
        self.assertEqual(report["post_scan"]["subtitle_sidecar_file_count"], 1)

    def test_cloud_media_sidecar_cleanup_blocks_unexpected_delete_count(self) -> None:
        calls = []

        def fake_urlopen(request, timeout):
            calls.append(request.full_url)
            return _fake_mv3_sidecar_cleanup_response(request, deleted=False)

        with patch("urllib.request.urlopen", fake_urlopen):
            report = cleanup_mv3_cloud_media_sidecars(
                "http://mv3.example",
                "token",
                path="/已整理/series/Demo",
                approve_delete=True,
                expected_delete_count=1,
            )

        self.assertFalse(report["ok"])
        self.assertIn("expected_delete_count_mismatch", report["blockers"])
        self.assertEqual(report["operation"], {"skipped": True, "reason": "blocked"})
        self.assertTrue(all("/api/v1/files/115/delete" not in url for url in calls))

    def test_cloud_duplicate_video_cleanup_dry_run_protects_strm_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm" / "Demo" / "Season 1"
            root.mkdir(parents=True)
            for episode in (1, 2):
                (root / f"Demo - S01E{episode:02d}.strm").write_text(
                    f"https://mv3.example/redirect?path=/已整理/series/Demo/Season%201/Demo%20-%20S01E{episode:02d}.mkv&pickcode=secret-{episode}",
                    encoding="utf-8",
                )
            calls = []

            def fake_urlopen(request, timeout):
                calls.append((request.get_method(), request.full_url, getattr(request, "data", None)))
                return _fake_mv3_duplicate_video_cleanup_response(request, deleted=False)

            with patch("urllib.request.urlopen", fake_urlopen):
                report = cleanup_mv3_cloud_duplicate_videos(
                    "http://mv3.example",
                    "token",
                    season_path="/已整理/series/Demo/Season 1",
                    strm_root=str(root),
                    expected_episode_count=2,
                )

            rendered = render_mv3_cloud_duplicate_video_cleanup_report(report, "json")
            self.assertTrue(report["ok"])
            self.assertTrue(report["dry_run"])
            self.assertEqual(report["summary"]["video_file_count"], 4)
            self.assertEqual(report["summary"]["duplicate_episodes"], [1, 2])
            self.assertEqual([item["file_id"] for item in report["delete_plan"]["items"]], ["dup-1", "dup-2"])
            self.assertFalse(any("/api/v1/files/115/delete" in url for _method, url, _body in calls))
            self.assertNotIn("secret-1", rendered)

    def test_cloud_duplicate_video_cleanup_deletes_unreferenced_duplicates_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm" / "Demo" / "Season 1"
            root.mkdir(parents=True)
            for episode in (1, 2):
                (root / f"Demo - S01E{episode:02d}.strm").write_text(
                    f"https://mv3.example/redirect?path=/已整理/series/Demo/Season%201/Demo%20-%20S01E{episode:02d}.mkv&pickcode=secret-{episode}",
                    encoding="utf-8",
                )
            posted = []
            state = {"deleted": False}

            def fake_urlopen(request, timeout):
                if getattr(request, "data", None):
                    posted.append((request.full_url, json.loads(request.data.decode("utf-8"))))
                    if request.full_url.endswith("/api/v1/files/115/delete"):
                        state["deleted"] = True
                return _fake_mv3_duplicate_video_cleanup_response(request, deleted=state["deleted"])

            with patch("urllib.request.urlopen", fake_urlopen):
                report = cleanup_mv3_cloud_duplicate_videos(
                    "http://mv3.example",
                    "token",
                    season_path="/已整理/series/Demo/Season 1",
                    strm_root=str(root),
                    expected_episode_count=2,
                    approve_delete=True,
                    expected_delete_count=2,
                )

            self.assertTrue(report["ok"])
            delete_bodies = [body for url, body in posted if url.endswith("/api/v1/files/115/delete")]
            self.assertEqual(delete_bodies[0]["file_ids"], ["dup-1", "dup-2"])
            self.assertEqual(report["post_verify"]["video_file_count"], 2)
            self.assertEqual(report["post_verify"]["duplicate_episodes"], [])
            self.assertEqual(report["post_verify"]["missing_protected_strm_targets"], [])

    def test_cloud_duplicate_video_cleanup_blocks_unexpected_delete_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm" / "Demo" / "Season 1"
            root.mkdir(parents=True)
            for episode in (1, 2):
                (root / f"Demo - S01E{episode:02d}.strm").write_text(
                    f"/已整理/series/Demo/Season 1/Demo - S01E{episode:02d}.mkv",
                    encoding="utf-8",
                )
            calls = []

            def fake_urlopen(request, timeout):
                calls.append(request.full_url)
                return _fake_mv3_duplicate_video_cleanup_response(request, deleted=False)

            with patch("urllib.request.urlopen", fake_urlopen):
                report = cleanup_mv3_cloud_duplicate_videos(
                    "http://mv3.example",
                    "token",
                    season_path="/已整理/series/Demo/Season 1",
                    strm_root=str(root),
                    expected_episode_count=2,
                    approve_delete=True,
                    expected_delete_count=1,
                )

            self.assertFalse(report["ok"])
            self.assertIn("expected_delete_count_mismatch", report["blockers"])
            self.assertEqual(report["operation"], {"skipped": True, "reason": "blocked"})
            self.assertTrue(all("/api/v1/files/115/delete" not in url for url in calls))

    def test_cloud_duplicate_video_cleanup_accepts_verified_folder_id_when_path_info_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm" / "Demo" / "Season 1"
            root.mkdir(parents=True)
            for episode in (1, 2):
                (root / f"Demo - S01E{episode:02d}.strm").write_text(
                    f"/已整理/series/Demo/Season 1/Demo - S01E{episode:02d}.mkv",
                    encoding="utf-8",
                )

            def fake_urlopen(request, timeout):
                return _fake_mv3_duplicate_video_cleanup_response(request, deleted=False, empty_info=True)

            with patch("urllib.request.urlopen", fake_urlopen):
                report = cleanup_mv3_cloud_duplicate_videos(
                    "http://mv3.example",
                    "token",
                    season_path="/已整理/series/Demo/Season 1",
                    folder_id="season-id",
                    strm_root=str(root),
                    expected_episode_count=2,
                )

            self.assertTrue(report["ok"])
            self.assertEqual(report["folder_id"], "season-id")
            self.assertEqual(report["delete_plan"]["duplicate_video_count"], 2)

    def test_cloud_duplicate_video_cleanup_reads_115_fn_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "strm" / "Demo" / "Season 1"
            root.mkdir(parents=True)
            for episode in (1, 2):
                (root / f"Demo - S01E{episode:02d}.strm").write_text(
                    f"/已整理/series/Demo/Season 1/Demo - S01E{episode:02d}.mkv",
                    encoding="utf-8",
                )

            def fake_urlopen(request, timeout):
                return _fake_mv3_duplicate_video_cleanup_response(request, deleted=False, raw_115_names=True)

            with patch("urllib.request.urlopen", fake_urlopen):
                report = cleanup_mv3_cloud_duplicate_videos(
                    "http://mv3.example",
                    "token",
                    season_path="/已整理/series/Demo/Season 1",
                    strm_root=str(root),
                    expected_episode_count=2,
                )

            self.assertTrue(report["ok"])
            self.assertEqual(report["summary"]["video_file_count"], 4)
            self.assertEqual(report["summary"]["duplicate_episodes"], [1, 2])
            self.assertEqual([item["file_id"] for item in report["delete_plan"]["items"]], ["dup-1", "dup-2"])

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

    def test_resource_search_reports_timeout_without_throwing(self) -> None:
        def fake_urlopen(_request, timeout):
            raise socket.timeout("timed out")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = search_mv3_resources("http://mv3.example", "token", "长风渡", timeout=1)

        rendered = render_mv3_resource_search_report(report, "json")
        self.assertFalse(report["ok"])
        self.assertEqual(report["result_count"], 0)
        self.assertIn("mv3_resource_search_request_failed", report["warnings"])
        self.assertEqual(report["error_type"], "TimeoutError")
        self.assertNotIn("token", rendered)

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
        self.assertEqual(report["browse"]["items"][1]["episode"], 1)
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
        self.assertEqual(report["browse"]["items"][1]["episode"], 2)
        self.assertNotIn("https://example.test", rendered)
        self.assertNotIn("parsed-code", rendered)
        self.assertNotIn("abcd", rendered)

    def test_share_preview_fails_when_browse_returns_no_items(self) -> None:
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
                return FakeResponse({"success": True, "data": {"share_code": "parsed-code", "receive_code": "abcd"}})
            if path == "/api/v1/share-transfer/browse":
                return FakeResponse({"success": False, "data": None, "message": "cannot browse share"})
            raise AssertionError(f"unexpected path: {path}")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = preview_mv3_share(
                "http://mv3.example",
                "token",
                "Demo",
                selection_index=1,
                expected_title_contains="Demo",
            )

        self.assertFalse(report["ok"])
        self.assertTrue(report["parse"]["ok"])
        self.assertFalse(report["browse"]["ok"])
        self.assertEqual(report["browse"]["item_count"], 0)
        self.assertEqual(report["browse"]["api_message"], "cannot browse share")

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

    def test_share_receive_can_receive_all_files_with_episode_gate(self) -> None:
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
                return FakeResponse({"success": True, "data": {"items": [{"title": "凡人歌", "share_link": "https://example.test/s/private"}]}})
            if path == "/api/v1/share-transfer/parse":
                return FakeResponse({"success": True, "data": {"share_code": "parsed-code", "receive_code": "abcd"}})
            if path == "/api/v1/share-transfer/browse":
                self.assertEqual(body["cid"], "folder-1")
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"name": "凡人歌.S01E01.mkv", "fid": "file-1", "ico": "mkv", "s": 100},
                                {"name": "凡人歌.S01E02.mkv", "fid": "file-2", "ico": "mkv", "s": 100},
                                {"name": "凡人歌.S01E03.mkv", "fid": "file-3", "ico": "mkv", "s": 100},
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
                "凡人歌",
                selection_index=1,
                browse_cid="folder-1",
                receive_all_files=True,
                expected_episode_count=3,
                expected_episode_min=1,
                expected_episode_max=3,
                expected_title_contains="凡人歌",
                target_path="/未整理",
                storage="115-default",
            )

        receive_body = seen[-1][1]
        self.assertEqual(receive_body["file_ids"], ["file-1", "file-2", "file-3"])
        self.assertEqual(report["file_id_count"], 3)
        self.assertEqual(report["episodes"], [1, 2, 3])
        self.assertEqual(report["missing_expected"], [])
        self.assertTrue(report["ok"])

    def test_share_receive_all_files_allows_sidecar_subtitles(self) -> None:
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
                return FakeResponse({"success": True, "data": {"items": [{"title": "亲爱的X", "share_link": "https://example.test/s/private"}]}})
            if path == "/api/v1/share-transfer/parse":
                return FakeResponse({"success": True, "data": {"share_code": "parsed-code", "receive_code": "abcd"}})
            if path == "/api/v1/share-transfer/browse":
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"name": "Dear.X.S01E01.mkv", "fid": "video-1", "s": 1000},
                                {"name": "Dear.X.S01E01.ass", "fid": "sub-1", "s": 10},
                                {"name": "Dear.X.S01E02.mkv", "fid": "video-2", "s": 1000},
                                {"name": "Dear.X.S01E02.ass", "fid": "sub-2", "s": 10},
                                {"name": "Dear.X.S01E03.mkv", "fid": "video-3", "s": 1000},
                                {"name": "Dear.X.S01E03.ass", "fid": "sub-3", "s": 10},
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
                "亲爱的X",
                selection_index=1,
                browse_cid="folder-1",
                receive_all_files=True,
                expected_episode_count=3,
                expected_episode_min=1,
                expected_episode_max=3,
                expected_title_contains="亲爱的X",
                target_path="/未整理",
                storage="115-default",
            )

        receive_body = seen[-1][1]
        self.assertEqual(receive_body["file_ids"], ["video-1", "sub-1", "video-2", "sub-2", "video-3", "sub-3"])
        self.assertEqual(report["file_id_count"], 6)
        self.assertEqual(report["selected_item_count"], 6)
        self.assertEqual(report["video_file_count"], 3)
        self.assertEqual(report["sidecar_file_count"], 3)
        self.assertEqual(report["episodes"], [1, 2, 3])
        self.assertEqual(report["missing_expected"], [])
        self.assertNotIn("video_file_count_mismatch", report["warnings"])
        self.assertTrue(report["ok"])

    def test_share_receive_all_files_excludes_metadata_sidecars(self) -> None:
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
                return FakeResponse({"success": True, "data": {"items": [{"title": "云盘只生成STRM", "share_link": "https://example.test/s/private"}]}})
            if path == "/api/v1/share-transfer/parse":
                return FakeResponse({"success": True, "data": {"share_code": "parsed-code", "receive_code": "abcd"}})
            if path == "/api/v1/share-transfer/browse":
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"name": "Cloud.Only.S01E01.mkv", "fid": "video-1", "s": 1000},
                                {"name": "Cloud.Only.S01E01.ass", "fid": "sub-1", "s": 10},
                                {"name": "Cloud.Only.S01E01.nfo", "fid": "nfo-1", "s": 10},
                                {"name": "poster.jpg", "fid": "poster-1", "s": 10},
                                {"name": "Cloud.Only.S01E02.mkv", "fid": "video-2", "s": 1000},
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
                "云盘只生成STRM",
                selection_index=1,
                browse_cid="folder-1",
                receive_all_files=True,
                expected_episode_count=2,
                expected_episode_min=1,
                expected_episode_max=2,
                expected_title_contains="云盘只生成STRM",
                target_path="/未整理",
                storage="115-default",
            )

        receive_body = seen[-1][1]
        self.assertEqual(receive_body["file_ids"], ["video-1", "sub-1", "video-2"])
        self.assertEqual(report["file_id_count"], 3)
        self.assertEqual(report["selected_item_count"], 3)
        self.assertEqual(report["video_file_count"], 2)
        self.assertEqual(report["sidecar_file_count"], 1)
        self.assertEqual(report["excluded_metadata_sidecar_count"], 2)
        self.assertIn("metadata_sidecars_excluded_from_receive", report["warnings"])
        self.assertTrue(report["ok"])

    def test_share_receive_all_files_blocks_incomplete_episode_set(self) -> None:
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
                return FakeResponse({"success": True, "data": {"items": [{"title": "凡人歌", "share_link": "https://example.test/s/private"}]}})
            if path == "/api/v1/share-transfer/parse":
                return FakeResponse({"success": True, "data": {"share_code": "parsed-code", "receive_code": "abcd"}})
            if path == "/api/v1/share-transfer/browse":
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "items": [
                                {"name": "凡人歌.S01E01.mkv", "fid": "file-1", "ico": "mkv", "s": 100},
                                {"name": "凡人歌.S01E03.mkv", "fid": "file-3", "ico": "mkv", "s": 100},
                            ]
                        },
                    }
                )
            if path == "/api/v1/share-transfer/receive":
                raise AssertionError("receive should not be called for incomplete episodes")
            raise AssertionError(f"unexpected path: {path}")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = receive_mv3_share(
                "http://mv3.example",
                "token",
                "凡人歌",
                selection_index=1,
                browse_cid="folder-1",
                receive_all_files=True,
                expected_episode_count=3,
                expected_episode_min=1,
                expected_episode_max=3,
                expected_title_contains="凡人歌",
                target_path="/未整理",
                storage="115-default",
            )

        self.assertNotIn("/api/v1/share-transfer/receive", [item[0] for item in seen])
        self.assertFalse(report["ok"])
        self.assertIn("episode_count_mismatch", report["warnings"])
        self.assertIn("episode_range_incomplete", report["warnings"])
        self.assertEqual(report["missing_expected"], [2])

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
        self.assertEqual(seen["body"]["exclude_extensions"], [".jpeg", ".jpg", ".nfo", ".png", ".webp"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["excluded_extensions"], [".jpeg", ".jpg", ".nfo", ".png", ".webp"])
        self.assertEqual(report["summary"]["episode_count"], 2)
        self.assertEqual(report["summary"]["missing_in_range"], [2])
        self.assertIn("episode_gap_detected", report["warnings"])
        self.assertIn("all_scan_items_marked_in_library", report["warnings"])
        self.assertIn("Demo.S01E01.mp4", rendered)

    def test_organize_transfer_from_browse_report_blocks_incomplete_episode_set(self) -> None:
        browse_report = {
            "path": "/未整理/Demo",
            "items": [
                {"name": "Demo.S01E01.mp4", "kind": "file", "episode": 1, "file_id": "file-1"},
                {"name": "Demo.S01E03.mp4", "kind": "file", "episode": 3, "file_id": "file-3"},
            ],
        }

        report = execute_mv3_organize_transfer_from_browse_report(
            "http://mv3.example",
            "token",
            browse_report,
            target_dir="/已整理",
            strm_dir="/strm",
            tmdb_id=123,
            expected_episode_count=3,
            expected_episode_min=1,
            expected_episode_max=3,
        )

        self.assertFalse(report["ok"])
        self.assertIn("episode_range_incomplete", report["blockers"])
        self.assertEqual(report["transfer"], {"skipped": True})

    def test_organize_transfer_accepts_delimited_episode_numbers(self) -> None:
        seen = {}
        browse_report = {
            "path": "/未整理/沙尘暴",
            "items": [
                {"name": "沙尘暴_01_锅炉里的焦尸.mp4", "kind": "file", "episode": None, "file_id": "file-1"},
                {"name": "沙尘暴_02_迟来的翻供.mp4", "kind": "file", "episode": None, "file_id": "file-2"},
            ],
        }

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return b'{"success":true,"data":{"task_id":"task-1"}}'

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            report = execute_mv3_organize_transfer_from_browse_report(
                "http://mv3.example",
                "token",
                browse_report,
                target_dir="/已整理",
                strm_dir="/strm",
                tmdb_id=272100,
                expected_episode_count=2,
                expected_episode_min=1,
                expected_episode_max=2,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["episodes"], [1, 2])
        self.assertEqual(len(seen["body"]["files"]), 2)

    def test_organize_transfer_does_not_treat_technical_numbers_as_episodes(self) -> None:
        browse_report = {
            "path": "/未整理/Demo",
            "items": [
                {"name": "Demo.2025.2160p.60fps.mkv", "kind": "file", "episode": None, "file_id": "file-1"},
            ],
        }

        report = execute_mv3_organize_transfer_from_browse_report(
            "http://mv3.example",
            "token",
            browse_report,
            target_dir="/已整理",
            strm_dir="/strm",
            tmdb_id=123,
            expected_episode_count=1,
            expected_episode_min=1,
            expected_episode_max=1,
        )

        self.assertFalse(report["ok"])
        self.assertIn("episode_count_mismatch", report["blockers"])
        self.assertIn("episode_range_incomplete", report["blockers"])
        self.assertEqual(report["transfer"], {"skipped": True})

    def test_organize_transfer_from_browse_report_posts_complete_file_list(self) -> None:
        seen = {}
        browse_report = {
            "path": "/未整理/Demo",
            "items": [
                {"name": "Demo.S01E01.mp4", "kind": "file", "episode": 1, "file_id": "file-1"},
                {"name": "Demo.S01E02.mp4", "kind": "file", "episode": 2, "file_id": "file-2"},
            ],
        }

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return b'{"success":true,"data":{"task_id":"task-1"}}'

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            report = execute_mv3_organize_transfer_from_browse_report(
                "http://mv3.example",
                "token",
                browse_report,
                target_dir="/已整理",
                strm_dir="/strm",
                tmdb_id=123,
                expected_episode_count=2,
                expected_episode_min=1,
                expected_episode_max=2,
            )

        rendered = render_mv3_organize_transfer_report(report, "json")
        self.assertTrue(report["ok"])
        self.assertEqual(seen["url"], "http://mv3.example/api/v1/organize/transfer")
        self.assertEqual(seen["body"]["target_dir"], "/已整理")
        self.assertEqual(seen["body"]["strm_dir"], "/strm")
        self.assertEqual(seen["body"]["tmdb_id"], 123)
        self.assertEqual(seen["body"]["mode"], "move")
        self.assertEqual([item["source_file_id"] for item in seen["body"]["files"]], ["file-1", "file-2"])
        self.assertEqual(report["completion_verification"]["status"], "confirmed_success")
        self.assertTrue(report["completion_verification"]["requires_followup_before_cleanup"])
        self.assertNotIn("token", rendered)

    def test_organize_transfer_from_browse_report_ignores_sidecar_subtitles_for_episode_gate(self) -> None:
        seen = {}
        browse_report = {
            "path": "/未整理/DearX",
            "items": [
                {"name": "Dear.X.S01E01.mkv", "kind": "file", "media_kind": "video", "episode": 1, "file_id": "video-1"},
                {"name": "Dear.X.S01E01.ass", "kind": "file", "media_kind": "sidecar", "episode": 1, "file_id": "sub-1"},
                {"name": "Dear.X.S01E02.mkv", "kind": "file", "media_kind": "video", "episode": 2, "file_id": "video-2"},
                {"name": "Dear.X.S01E02.ass", "kind": "file", "media_kind": "sidecar", "episode": 2, "file_id": "sub-2"},
            ],
        }

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return b'{"success":true,"data":{"task_id":"task-1"}}'

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            report = execute_mv3_organize_transfer_from_browse_report(
                "http://mv3.example",
                "token",
                browse_report,
                target_dir="/已整理",
                strm_dir="/strm",
                tmdb_id=256226,
                expected_episode_count=2,
                expected_episode_min=1,
                expected_episode_max=2,
            )

        self.assertTrue(report["ok"])
        self.assertEqual([item["source_file_id"] for item in seen["body"]["files"]], ["video-1", "video-2"])

    def test_organize_transfer_request_never_copies_cloud_metadata_sidecars(self) -> None:
        seen = {}
        browse_report = {
            "path": "/未整理/Demo",
            "items": [
                {"name": "Demo.S01E01.mkv", "kind": "file", "media_kind": "video", "episode": 1, "file_id": "video-1"},
                {"name": "Demo.S01E01.nfo", "kind": "file", "media_kind": "metadata_sidecar", "episode": 1, "file_id": "nfo-1"},
                {"name": "poster.jpg", "kind": "file", "episode": None, "file_id": "poster-1"},
            ],
        }

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return b'{"success":true,"data":{"task_id":"task-1"}}'

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            report = execute_mv3_organize_transfer_from_browse_report(
                "http://mv3.example",
                "token",
                browse_report,
                target_dir="/已整理",
                strm_dir="/strm",
                tmdb_id=123,
                expected_episode_count=1,
                expected_episode_min=1,
                expected_episode_max=1,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(seen["body"]["files"], [{"source_path": "/未整理/Demo/Demo.S01E01.mkv", "source_file_id": "video-1", "is_cloud_source": True, "name": "Demo.S01E01.mkv"}])
        self.assertFalse(seen["body"]["copy_non_media"])
        self.assertEqual(report["excluded_metadata_sidecar_count"], 2)
        self.assertIn("metadata_sidecars_excluded_from_organize_transfer", report["warnings"])
        self.assertEqual([item["name"] for item in report["excluded_metadata_sidecars"]], ["Demo.S01E01.nfo", "poster.jpg"])
        self.assertIn("Excluded metadata sidecars: `2`", render_mv3_organize_transfer_report(report, "markdown"))
        self.assertIn("scraping", report["safety"].lower())

    def test_organize_transfer_reports_timeout_without_throwing(self) -> None:
        browse_report = {
            "path": "/未整理/Demo/Season 1",
            "items": [
                {"name": "Demo.S01E01.mp4", "kind": "file", "episode": 1, "file_id": "file-1"},
            ],
        }

        def fake_urlopen(_request, timeout):
            raise socket.timeout("timed out")

        with patch("urllib.request.urlopen", fake_urlopen):
            report = execute_mv3_organize_transfer_from_browse_report(
                "http://mv3.example",
                "token",
                browse_report,
                target_dir="/已整理",
                strm_dir="/strm",
                tmdb_id=123,
                expected_episode_count=1,
                expected_episode_min=1,
                expected_episode_max=1,
            )

        self.assertFalse(report["ok"])
        self.assertIn("mv3_transfer_request_failed", report["blockers"])
        self.assertIn(report["transfer"]["error_type"], {"TimeoutError", "timeout"})
        self.assertEqual(report["transfer"]["endpoint"]["path"], "/api/v1/organize/transfer")
        self.assertEqual(report["completion_verification"]["status"], "unverified_after_timeout")
        self.assertIn("strm-verify before any cleanup", report["completion_verification"]["required_followup"])
        self.assertTrue(report["completion_verification"]["requires_followup_before_cleanup"])
        self.assertIn("Completion status: `unverified_after_timeout`", render_mv3_organize_transfer_report(report, "markdown"))

    def test_organize_transfer_blocks_media_category_target_dir(self) -> None:
        browse_report = {
            "path": "/未整理/Demo",
            "items": [
                {"name": "Demo.S01E01.mp4", "kind": "file", "episode": 1, "file_id": "file-1"},
            ],
        }

        report = execute_mv3_organize_transfer_from_browse_report(
            "http://mv3.example",
            "token",
            browse_report,
            target_dir="/已整理/series",
            strm_dir="/strm/series",
            tmdb_id=123,
            expected_episode_count=1,
            expected_episode_min=1,
            expected_episode_max=1,
        )

        self.assertFalse(report["ok"])
        self.assertIn("target_dir_should_be_organize_root_not_media_category", report["blockers"])
        self.assertEqual(report["transfer"], {"skipped": True})

    def test_organize_transfer_blocks_media_category_strm_dir(self) -> None:
        browse_report = {
            "path": "/未整理/Demo",
            "items": [
                {"name": "Demo.S01E01.mp4", "kind": "file", "episode": 1, "file_id": "file-1"},
            ],
        }

        report = execute_mv3_organize_transfer_from_browse_report(
            "http://mv3.example",
            "token",
            browse_report,
            target_dir="/已整理",
            strm_dir="/strm/series",
            tmdb_id=123,
            expected_episode_count=1,
            expected_episode_min=1,
            expected_episode_max=1,
        )

        self.assertFalse(report["ok"])
        self.assertIn("strm_dir_should_be_strm_root_not_media_category", report["blockers"])
        self.assertEqual(report["transfer"], {"skipped": True})

    def test_organize_transfer_allows_explicit_non_contiguous_episodes(self) -> None:
        seen = {}
        browse_report = {
            "path": "/未整理/Demo",
            "items": [
                {"name": "Demo.S01E02.mp4", "kind": "file", "episode": 2, "file_id": "file-2"},
                {"name": "Demo.S01E04.mp4", "kind": "file", "episode": 4, "file_id": "file-4"},
            ],
        }

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

        def fake_urlopen(request, timeout):
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            report = execute_mv3_organize_transfer_from_browse_report(
                "http://mv3.example",
                "token",
                browse_report,
                target_dir="/已整理",
                strm_dir="/strm",
                tmdb_id=123,
                expected_episode_count=2,
                expected_episode_min=2,
                expected_episode_max=4,
                expected_episodes=[2, 4],
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["episodes"], [2, 4])
        self.assertEqual(report["expected_episodes"], [2, 4])
        self.assertEqual(report["missing_expected"], [])
        self.assertEqual(report["unexpected_episodes"], [])
        self.assertEqual([item["source_file_id"] for item in seen["body"]["files"]], ["file-2", "file-4"])

    def test_organize_transfer_blocks_unexpected_episode_with_explicit_list(self) -> None:
        browse_report = {
            "path": "/未整理/Demo",
            "items": [
                {"name": "Demo.S01E02.mp4", "kind": "file", "episode": 2, "file_id": "file-2"},
                {"name": "Demo.S01E03.mp4", "kind": "file", "episode": 3, "file_id": "file-3"},
            ],
        }

        report = execute_mv3_organize_transfer_from_browse_report(
            "http://mv3.example",
            "token",
            browse_report,
            target_dir="/已整理",
            strm_dir="/strm",
            tmdb_id=123,
            expected_episode_count=2,
            expected_episode_min=2,
            expected_episode_max=4,
            expected_episodes=[2, 4],
        )

        self.assertFalse(report["ok"])
        self.assertIn("episode_range_incomplete", report["blockers"])
        self.assertIn("unexpected_episodes_present", report["blockers"])
        self.assertEqual(report["missing_expected"], [4])
        self.assertEqual(report["unexpected_episodes"], [3])
        self.assertEqual(report["transfer"], {"skipped": True})

    def test_organize_transfer_allows_source_path_override_for_folder_id_browse_report(self) -> None:
        seen = {}
        browse_report = {
            "folder_id": "folder-1",
            "items": [
                {"name": "Demo.S01E01.mp4", "kind": "file", "episode": 1, "file_id": "file-1"},
            ],
        }

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

        def fake_urlopen(request, timeout):
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            report = execute_mv3_organize_transfer_from_browse_report(
                "http://mv3.example",
                "token",
                browse_report,
                target_dir="/已整理",
                strm_dir="/strm",
                tmdb_id=123,
                expected_episode_count=1,
                expected_episode_min=1,
                expected_episode_max=1,
                source_path_override="/未整理/Demo/Season 1",
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["source_path"], "/未整理/Demo/Season 1")
        self.assertEqual(seen["body"]["files"][0]["source_path"], "/未整理/Demo/Season 1/Demo.S01E01.mp4")

    def test_strm_generate_posts_incremental_request(self) -> None:
        seen = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return b'{"success":true,"data":{"task_id":"strm-task-1"}}'

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
            report = generate_mv3_strm(
                "http://mv3.example",
                "token",
                source_dir="/已整理/series/Demo/Season 1",
                target_dir="/example/strm-root",
                storage="115-default",
                timeout=42,
            )

        rendered = render_mv3_strm_generate_report(report, "json")
        self.assertTrue(report["ok"])
        self.assertEqual(seen["url"], "http://mv3.example/api/v1/strm/generate")
        self.assertEqual(seen["api_key"], "token")
        self.assertEqual(seen["timeout"], 42)
        self.assertEqual(seen["body"]["source_dir"], "/已整理/series/Demo/Season 1")
        self.assertEqual(seen["body"]["target_dir"], "/example/strm-root")
        self.assertTrue(seen["body"]["cloud"])
        self.assertTrue(seen["body"]["incremental"])
        self.assertFalse(seen["body"]["overwrite"])
        self.assertNotIn("token", rendered)

    def test_strm_generate_blocks_organize_by_default(self) -> None:
        with patch("urllib.request.urlopen") as fake_urlopen:
            report = generate_mv3_strm(
                "http://mv3.example",
                "token",
                source_dir="/已整理/series/Demo/Season 1",
                target_dir="/example/strm-root",
                organize=True,
            )

        self.assertFalse(report["ok"])
        self.assertIn("strm_generate_organize_disabled", report["blockers"])
        self.assertTrue(report["request_summary"]["organize"])
        fake_urlopen.assert_not_called()

    def test_strm_generate_allows_organize_with_explicit_override(self) -> None:
        seen = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return b'{"success":true,"data":{"task_id":"strm-task-1"}}'

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            seen["body"] = json.loads(request.data.decode("utf-8"))
            seen["timeout"] = timeout
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            report = generate_mv3_strm(
                "http://mv3.example",
                "token",
                source_dir="/已整理/series/Demo/Season 1",
                target_dir="/example/strm-root",
                organize=True,
                allow_organize=True,
                timeout=42,
            )

        self.assertTrue(report["ok"])
        self.assertTrue(report["allow_organize"])
        self.assertTrue(seen["body"]["organize"])
        self.assertEqual(seen["timeout"], 42)

    def test_strm_records_regenerate_posts_record_ids(self) -> None:
        seen = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return b'{"success":true,"data":{"updated":1}}'

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
            report = regenerate_mv3_strm_records(
                "http://mv3.example",
                "token",
                record_ids=[16868, 16868],
                timeout=42,
            )

        rendered = render_mv3_strm_records_regenerate_report(report, "json")
        self.assertTrue(report["ok"])
        self.assertEqual(seen["url"], "http://mv3.example/api/v1/strm/records/regenerate")
        self.assertEqual(seen["api_key"], "token")
        self.assertEqual(seen["timeout"], 42)
        self.assertEqual(seen["body"], {"record_ids": [16868]})
        self.assertEqual(report["record_ids"], [16868])
        self.assertEqual(report["record_count"], 1)
        self.assertNotIn("token", rendered)

    def test_strm_records_redirect_validates_before_and_after(self) -> None:
        calls = []

        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def record(strm_path):
            return {
                "id": 17058,
                "strm_path": strm_path,
                "source_path": "/已整理/series/岁月有情时 (2026) {tmdbid=272681}/Season 1/岁月有情时 - S01E01.mkv",
            }

        def fake_urlopen(request, timeout):
            calls.append(
                {
                    "url": request.full_url,
                    "api_key": request.headers.get("X-api-key"),
                    "body": json.loads(request.data.decode("utf-8")) if request.data else None,
                    "timeout": timeout,
                }
            )
            if request.get_method() == "GET" and len([call for call in calls if "/api/v1/strm/records?" in call["url"]]) == 1:
                return FakeResponse({"success": True, "data": {"items": [record("/strm/series/series/岁月有情时 (2026) {tmdbid=272681}/Season 1/岁月有情时 - S01E01.strm")]}})
            if request.get_method() == "POST":
                return FakeResponse({"success": True, "data": {"updated": 1}})
            return FakeResponse({"success": True, "data": {"items": [record("/strm/series/岁月有情时 (2026) {tmdbid=272681}/Season 1/岁月有情时 - S01E01.strm")]}})

        with patch("urllib.request.urlopen", fake_urlopen):
            report = redirect_mv3_strm_records(
                "http://mv3.example",
                "token",
                record_ids=[17058],
                expected_record_ids=[17058],
                old_prefix="/strm/series/series",
                new_prefix="/strm/series",
                expected_source_prefix="/已整理/series/岁月有情时 (2026) {tmdbid=272681}",
                keyword="岁月有情时",
                timeout=42,
            )

        rendered = render_mv3_strm_records_redirect_report(report, "json")
        post_call = next(call for call in calls if call["body"])
        self.assertTrue(report["ok"])
        self.assertEqual(post_call["url"], "http://mv3.example/api/v1/strm/records/redirect")
        self.assertEqual(post_call["api_key"], "token")
        self.assertEqual(post_call["timeout"], 42)
        self.assertEqual(post_call["body"]["old_prefix"], "/strm/series/series")
        self.assertEqual(post_call["body"]["new_prefix"], "/strm/series")
        self.assertEqual(post_call["body"]["record_ids"], [17058])
        self.assertEqual(report["before"]["matching_prefix_count"], 1)
        self.assertEqual(report["after"]["matching_prefix_count"], 1)
        self.assertNotIn("token", rendered)

    def test_strm_records_redirect_blocks_before_prefix_mismatch(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                payload = {
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "id": 17058,
                                "strm_path": "/strm/movie/Wrong.strm",
                                "source_path": "/已整理/series/岁月有情时 (2026) {tmdbid=272681}/Season 1/E01.mkv",
                            }
                        ]
                    },
                }
                return json.dumps(payload, ensure_ascii=False).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
            report = redirect_mv3_strm_records(
                "http://mv3.example",
                "token",
                record_ids=[17058],
                expected_record_ids=[17058],
                old_prefix="/strm/series/series",
                new_prefix="/strm/series",
                expected_source_prefix="/已整理/series/岁月有情时 (2026) {tmdbid=272681}",
            )

        self.assertFalse(report["ok"])
        self.assertIn("before_strm_path_prefix_mismatch", report["blockers"])

    def test_strm_records_redirect_blocks_skipped_response(self) -> None:
        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            if request.get_method() == "POST":
                return FakeResponse({"success": True, "data": {"success": 0, "failed": 0, "skipped": 1}})
            return FakeResponse(
                {
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "id": 17058,
                                "strm_path": "/strm/series/series/岁月有情时/Season 1/E01.strm",
                                "source_path": "/已整理/series/岁月有情时/Season 1/E01.mkv",
                            }
                        ]
                    },
                }
            )

        with patch("urllib.request.urlopen", fake_urlopen):
            report = redirect_mv3_strm_records(
                "http://mv3.example",
                "token",
                record_ids=[17058],
                expected_record_ids=[17058],
                old_prefix="/strm/series/series",
                new_prefix="/strm/series",
                expected_source_prefix="/已整理/series/岁月有情时",
            )

        self.assertFalse(report["ok"])
        self.assertIn("mv3_strm_records_redirect_skipped_records", report["blockers"])
        self.assertIn("mv3_strm_records_redirect_no_records_changed", report["blockers"])

    def test_strm_records_redirect_blocks_when_after_path_still_has_old_prefix(self) -> None:
        calls = []

        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            calls.append(request.get_method())
            if request.get_method() == "POST":
                return FakeResponse({"success": True, "data": {"success": 1, "failed": 0, "skipped": 0}})
            return FakeResponse(
                {
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "id": 17058,
                                "strm_path": "/strm/series/series/岁月有情时/Season 1/E01.strm",
                                "source_path": "/已整理/series/岁月有情时/Season 1/E01.mkv",
                            }
                        ]
                    },
                }
            )

        with patch("urllib.request.urlopen", fake_urlopen):
            report = redirect_mv3_strm_records(
                "http://mv3.example",
                "token",
                record_ids=[17058],
                expected_record_ids=[17058],
                old_prefix="/strm/series/series",
                new_prefix="/strm/series",
                expected_source_prefix="/已整理/series/岁月有情时",
            )

        self.assertFalse(report["ok"])
        self.assertIn("after_strm_path_expected_rewrite_mismatch", report["blockers"])
        self.assertEqual(report["after"]["expected_rewrite_match_count"], 0)

    def test_strm_records_lists_and_filters_record_ids(self) -> None:
        seen = {}

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                payload = {
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "id": 16868,
                                "source": "organize",
                                "strm_path": "/example/strm-root/series/八千里路云和月/Season 1/八千里路云和月 - S01E37.strm",
                                "source_path": "/已整理/series/八千里路云和月/Season 1/八千里路云和月 - S01E37.mkv",
                                "strm_content": "https://mv3.example/redirect?path=/已整理/series/八千里路云和月/Season%201/E37.mkv&pickcode=secret",
                            },
                            {
                                "id": 16962,
                                "source": "generate",
                                "strm_path": "/example/strm-root/八千里路云和月 - S01E37.strm",
                                "source_path": "/已整理/series/八千里路云和月/Season 1/八千里路云和月 - S01E37.mkv",
                            },
                        ],
                        "total": 2,
                    },
                }
                return json.dumps(payload, ensure_ascii=False).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["api_key"] = request.headers.get("X-api-key")
            seen["timeout"] = timeout
            return FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            report = list_mv3_strm_records(
                "http://mv3.example",
                "token",
                keyword="八千里路云和月",
                record_ids=[16868],
                page_size=20,
                timeout=42,
            )

        rendered = render_mv3_strm_records_report(report, "json")
        self.assertTrue(report["ok"])
        self.assertIn("/api/v1/strm/records?", seen["url"])
        self.assertIn("keyword=%E5%85%AB%E5%8D%83%E9%87%8C%E8%B7%AF%E4%BA%91%E5%92%8C%E6%9C%88", seen["url"])
        self.assertEqual(seen["api_key"], "token")
        self.assertEqual(seen["timeout"], 42)
        self.assertEqual(report["matched_record_count"], 1)
        self.assertEqual(report["records"][0]["id"], 16868)
        self.assertEqual(report["records"][0]["episode"], 37)
        self.assertIn("pickcode=secret", report["records"][0]["strm_content"])
        self.assertNotIn("token", rendered)
        self.assertNotIn("pickcode=secret", rendered)
        self.assertIn('"strm_content": "[REDACTED]"', rendered)

    def test_strm_records_materialize_writes_record_content_with_prefix_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            host_root = tmp_path / "volume4" / "mv3" / "strm"

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    payload = {
                        "success": True,
                        "data": {
                            "items": [
                                {
                                    "id": 16868,
                                    "source": "organize",
                                    "strm_path": "/example/strm-root/series/八千里路云和月/Season 1/八千里路云和月 - S01E37.strm",
                                    "source_path": "/已整理/series/八千里路云和月/Season 1/八千里路云和月 - S01E37.mkv",
                                    "strm_content": "https://mv3.example/redirect?path=/已整理/series/八千里路云和月/Season%201/E37.mkv&pickcode=secret",
                                }
                            ]
                        },
                    }
                    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                report = materialize_mv3_strm_records(
                    "http://mv3.example",
                    "token",
                    record_ids=[16868],
                    expected_record_ids=[16868],
                    expected_strm_prefix="/example/strm-root/series/八千里路云和月",
                    expected_source_prefix="/已整理/series/八千里路云和月",
                    host_strm_prefix=f"{host_root}=/example/strm-root",
                    keyword="八千里路云和月",
                )

            rendered = render_mv3_strm_records_materialize_report(report, "json")
            output_file = host_root / "series" / "八千里路云和月" / "Season 1" / "八千里路云和月 - S01E37.strm"
            self.assertTrue(report["ok"])
            self.assertTrue(output_file.exists())
            self.assertIn("redirect?path=", output_file.read_text(encoding="utf-8"))
            self.assertEqual(report["writes"][0]["record_id"], 16868)
            self.assertEqual(report["writes"][0]["action"], "written")
            self.assertNotIn("pickcode=secret", rendered)

    def test_strm_records_materialize_blocks_prefix_mismatch(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                payload = {
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "id": 16868,
                                "strm_path": "/example/strm-root/movie/Wrong.strm",
                                "source_path": "/已整理/movie/Wrong.mkv",
                                "strm_content": "https://mv3.example/redirect?path=/已整理/movie/Wrong.mkv",
                            }
                        ]
                    },
                }
                return json.dumps(payload, ensure_ascii=False).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                report = materialize_mv3_strm_records(
                    "http://mv3.example",
                    "token",
                    record_ids=[16868],
                    expected_record_ids=[16868],
                    expected_strm_prefix="/example/strm-root/series/八千里路云和月",
                    expected_source_prefix="/已整理/series/八千里路云和月",
                    host_strm_prefix=f"{tmp}=/example/strm-root",
                )

        self.assertFalse(report["ok"])
        self.assertIn("strm_path_prefix_mismatch", report["blockers"])
        self.assertIn("source_path_prefix_mismatch", report["blockers"])

    def test_strm_records_materialize_can_rewrite_strm_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            host_root = tmp_path / "strm"

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    payload = {
                        "success": True,
                        "data": {
                            "items": [
                                {
                                    "id": 17093,
                                    "strm_path": "/strm/series/series/岁月有情时/Season 1/岁月有情时 - S01E21.strm",
                                    "source_path": "/已整理/series/岁月有情时/Season 1/岁月有情时 - S01E21.mkv",
                                    "strm_content": "https://mv3.example/redirect?path=/已整理/series/岁月有情时/Season%201/E21.mkv",
                                }
                            ]
                        },
                    }
                    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                report = materialize_mv3_strm_records(
                    "http://mv3.example",
                    "token",
                    record_ids=[17093],
                    expected_record_ids=[17093],
                    expected_strm_prefix="/strm/series/岁月有情时",
                    expected_source_prefix="/已整理/series/岁月有情时",
                    host_strm_prefix=f"{host_root}=/strm",
                    rewrite_strm_prefix="/strm/series/series=/strm/series",
                    keyword="岁月有情时",
                )

            output_file = host_root / "series" / "岁月有情时" / "Season 1" / "岁月有情时 - S01E21.strm"
            self.assertTrue(report["ok"])
            self.assertTrue(output_file.exists())
            self.assertEqual(report["writes"][0]["original_strm_path"], "/strm/series/series/岁月有情时/Season 1/岁月有情时 - S01E21.strm")
            self.assertEqual(report["writes"][0]["strm_path"], "/strm/series/岁月有情时/Season 1/岁月有情时 - S01E21.strm")

    def test_strm_records_materialize_blocks_rewrite_prefix_mismatch(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def read(self, _limit=-1):
                payload = {
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "id": 17093,
                                "strm_path": "/strm/movie/Wrong.strm",
                                "source_path": "/已整理/series/岁月有情时/Season 1/岁月有情时 - S01E21.mkv",
                                "strm_content": "https://mv3.example/redirect?path=/已整理/series/岁月有情时/Season%201/E21.mkv",
                            }
                        ]
                    },
                }
                return json.dumps(payload, ensure_ascii=False).encode("utf-8")

            @property
            def headers(self):
                return {"Content-Type": "application/json"}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                report = materialize_mv3_strm_records(
                    "http://mv3.example",
                    "token",
                    record_ids=[17093],
                    expected_record_ids=[17093],
                    expected_strm_prefix="/strm/series/岁月有情时",
                    expected_source_prefix="/已整理/series/岁月有情时",
                    host_strm_prefix=f"{tmp}=/strm",
                    rewrite_strm_prefix="/strm/series/series=/strm/series",
                )

        self.assertFalse(report["ok"])
        self.assertIn("rewrite_strm_prefix_mismatch", report["blockers"])

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

    def test_cli_parses_mp_cleanup_expected_episodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            preview = tmp_path / "preview.json"
            output = tmp_path / "execute.json"
            env_file.write_text("MP_BASE_URL=http://moviepilot.example\nMP_API_TOKEN=token\n", encoding="utf-8")
            preview.write_text(
                json.dumps(
                    {
                        "mode": "readonly-mp-cleanup-preview",
                        "title": "雨霖铃",
                        "ready_for_manual_cleanup_approval": True,
                        "summary": {
                            "records_matched": 3,
                            "episode_count": 3,
                            "episode_min": 1,
                            "episode_max": 21,
                            "missing_in_range": [2],
                        },
                        "mp_delete_plan": {"query": {"deletesrc": True, "deletedest": True}},
                        "records": [
                            {
                                "id": 21,
                                "title": "雨霖铃",
                                "tmdbid": 254486,
                                "episodes": "E01",
                                "episode_number": 1,
                                "status": True,
                                "hash_prefix": "feedface0000",
                            },
                            {
                                "id": 22,
                                "title": "雨霖铃",
                                "tmdbid": 254486,
                                "episodes": "E03",
                                "episode_number": 3,
                                "status": True,
                                "hash_prefix": "beadfeed1111",
                            },
                            {
                                "id": 23,
                                "title": "雨霖铃",
                                "tmdbid": 254486,
                                "episodes": "E21",
                                "episode_number": 21,
                                "status": True,
                                "hash_prefix": "beadfeed1111",
                            },
                        ],
                        "warnings": ["episode_gap_detected"],
                        "blockers": [],
                    }
                ),
                encoding="utf-8",
            )

            with patch("series_cloud_archiver.moviepilot.MoviePilotClient.delete_transfer_history", return_value={"http_status": 200, "ok": True, "response": {"success": True}}):
                main(
                    [
                        "mp-cleanup-execute",
                        "--env-file",
                        str(env_file),
                        "--preview-report",
                        str(preview),
                        "--expected-title",
                        "雨霖铃",
                        "--expected-tmdbid",
                        "254486",
                        "--expected-hash-prefix",
                        "feedface0000",
                        "--expected-hash-prefix",
                        "beadfeed1111",
                        "--expected-record-count",
                        "3",
                        "--expected-episode-count",
                        "3",
                        "--expected-episode-min",
                        "1",
                        "--expected-episode-max",
                        "21",
                        "--expected-episodes",
                        "1,3,21",
                        "--approve-mp-cleanup",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(report["ok"])
            self.assertEqual(report["expected"]["episodes"], [1, 3, 21])
            self.assertEqual(report["expected"]["hash_prefixes"], ["feedface0000", "beadfeed1111"])

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

    def test_cli_refuses_organize_transfer_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            browse_report = tmp_path / "browse.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")
            browse_report.write_text(json.dumps({"path": "/未整理/Demo", "items": []}), encoding="utf-8")

            with self.assertRaises(SystemExit) as caught:
                main(
                    [
                        "mv3-organize-transfer-from-browse",
                        "--env-file",
                        str(env_file),
                        "--browse-report",
                        str(browse_report),
                        "--target-dir",
                        "/已整理",
                        "--strm-dir",
                        "/strm",
                        "--source-path-override",
                        "/未整理/Demo/Season 1",
                        "--tmdb-id",
                        "123",
                        "--expected-episode-count",
                        "1",
                        "--expected-episode-min",
                        "1",
                        "--expected-episode-max",
                        "1",
                    ]
                )

            self.assertNotEqual(caught.exception.code, 0)

    def test_cli_writes_organize_transfer_report_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            browse_report = tmp_path / "browse.json"
            output = tmp_path / "transfer.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")
            browse_report.write_text(
                json.dumps(
                    {
                        "path": "/未整理/Demo",
                        "items": [
                            {"name": "Demo.S01E01.mp4", "kind": "file", "episode": 1, "file_id": "file-1"},
                        ],
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
                    return b'{"success":true,"data":{"task_id":"task-1"}}'

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                code = main(
                    [
                        "mv3-organize-transfer-from-browse",
                        "--env-file",
                        str(env_file),
                        "--browse-report",
                        str(browse_report),
                        "--target-dir",
                        "/已整理",
                        "--strm-dir",
                        "/strm",
                        "--tmdb-id",
                        "123",
                        "--expected-episode-count",
                        "1",
                        "--expected-episode-min",
                        "1",
                        "--expected-episode-max",
                        "1",
                        "--approve-transfer",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["target_dir"], "/已整理")

    def test_cli_parses_organize_transfer_expected_episodes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            browse_report = tmp_path / "browse.json"
            output = tmp_path / "transfer.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")
            browse_report.write_text(
                json.dumps(
                    {
                        "path": "/未整理/Demo",
                        "items": [
                            {"name": "Demo.S01E02.mp4", "kind": "file", "episode": 2, "file_id": "file-2"},
                            {"name": "Demo.S01E04.mp4", "kind": "file", "episode": 4, "file_id": "file-4"},
                        ],
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
                    return b'{"success":true,"data":{"task_id":"task-1"}}'

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                code = main(
                    [
                        "mv3-organize-transfer-from-browse",
                        "--env-file",
                        str(env_file),
                        "--browse-report",
                        str(browse_report),
                        "--target-dir",
                        "/已整理",
                        "--strm-dir",
                        "/strm",
                        "--tmdb-id",
                        "123",
                        "--expected-episode-count",
                        "2",
                        "--expected-episode-min",
                        "2",
                        "--expected-episode-max",
                        "4",
                        "--expected-episode",
                        "2,4",
                        "--approve-transfer",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["expected_episodes"], [2, 4])
            self.assertEqual(payload["episodes"], [2, 4])

    def test_cli_blocks_organize_transfer_to_media_category_target_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            browse_report = tmp_path / "browse.json"
            output = tmp_path / "transfer.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")
            browse_report.write_text(
                json.dumps(
                    {
                        "path": "/未整理/Demo",
                        "items": [
                            {"name": "Demo.S01E01.mp4", "kind": "file", "episode": 1, "file_id": "file-1"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with patch("urllib.request.urlopen") as fake_urlopen:
                code = main(
                    [
                        "mv3-organize-transfer-from-browse",
                        "--env-file",
                        str(env_file),
                        "--browse-report",
                        str(browse_report),
                        "--target-dir",
                        "/已整理/series",
                        "--strm-dir",
                        "/strm",
                        "--tmdb-id",
                        "123",
                        "--expected-episode-count",
                        "1",
                        "--expected-episode-min",
                        "1",
                        "--expected-episode-max",
                        "1",
                        "--approve-transfer",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 1)
            fake_urlopen.assert_not_called()
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertIn("target_dir_should_be_organize_root_not_media_category", payload["blockers"])

    def test_cli_refuses_strm_generate_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as caught:
                main(
                    [
                        "mv3-strm-generate",
                        "--env-file",
                        str(env_file),
                        "--source-dir",
                        "/已整理/series/Demo/Season 1",
                        "--target-dir",
                        "/example/strm-root",
                    ]
                )

            self.assertNotEqual(caught.exception.code, 0)

    def test_cli_writes_strm_generate_report_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "strm-generate.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    return b'{"success":true,"data":{"task_id":"strm-task-1"}}'

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                code = main(
                    [
                        "mv3-strm-generate",
                        "--env-file",
                        str(env_file),
                        "--source-dir",
                        "/已整理/series/Demo/Season 1",
                        "--target-dir",
                        "/example/strm-root",
                        "--approve-generate",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["source_dir"], "/已整理/series/Demo/Season 1")
            self.assertEqual(payload["target_dir"], "/example/strm-root")

    def test_cli_blocks_strm_generate_organize_without_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "strm-generate.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with patch("urllib.request.urlopen") as fake_urlopen:
                code = main(
                    [
                        "mv3-strm-generate",
                        "--env-file",
                        str(env_file),
                        "--source-dir",
                        "/已整理/series/Demo/Season 1",
                        "--target-dir",
                        "/example/strm-root",
                        "--organize",
                        "--approve-generate",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 1)
            fake_urlopen.assert_not_called()
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(payload["ok"])
            self.assertIn("strm_generate_organize_disabled", payload["blockers"])

    def test_cli_refuses_strm_records_regenerate_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as caught:
                main(
                    [
                        "mv3-strm-records-regenerate",
                        "--env-file",
                        str(env_file),
                        "--record-id",
                        "16868",
                    ]
                )

            self.assertNotEqual(caught.exception.code, 0)

    def test_cli_writes_strm_records_regenerate_report_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "strm-regenerate.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    return b'{"success":true,"data":{"updated":1}}'

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                code = main(
                    [
                        "mv3-strm-records-regenerate",
                        "--env-file",
                        str(env_file),
                        "--record-id",
                        "16868",
                        "--expected-record-id",
                        "16868",
                        "--approve-regenerate",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["record_ids"], [16868])
            self.assertEqual(payload["request_summary"]["endpoint"]["path"], "/api/v1/strm/records/regenerate")

    def test_cli_refuses_strm_records_redirect_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as caught:
                main(
                    [
                        "mv3-strm-records-redirect",
                        "--env-file",
                        str(env_file),
                        "--record-id",
                        "17058",
                        "--expected-record-id",
                        "17058",
                        "--old-prefix",
                        "/strm/series/series",
                        "--new-prefix",
                        "/strm/series",
                        "--expected-source-prefix",
                        "/已整理/series/岁月有情时",
                    ]
                )

            self.assertNotEqual(caught.exception.code, 0)

    def test_cli_writes_strm_records_redirect_report_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "strm-redirect.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")
            calls = []

            class FakeResponse:
                status = 200

                def __init__(self, payload):
                    self.payload = payload

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            def record(path):
                return {
                    "id": 17058,
                    "strm_path": path,
                    "source_path": "/已整理/series/岁月有情时/Season 1/E01.mkv",
                }

            def fake_urlopen(request, timeout):
                calls.append(request.full_url)
                if request.get_method() == "POST":
                    return FakeResponse({"success": True, "data": {"updated": 1}})
                get_count = sum(1 for url in calls if "/api/v1/strm/records?" in url)
                if get_count == 1:
                    return FakeResponse({"success": True, "data": {"items": [record("/strm/series/series/岁月有情时/Season 1/E01.strm")]}})
                return FakeResponse({"success": True, "data": {"items": [record("/strm/series/岁月有情时/Season 1/E01.strm")]}})

            with patch("urllib.request.urlopen", fake_urlopen):
                code = main(
                    [
                        "mv3-strm-records-redirect",
                        "--env-file",
                        str(env_file),
                        "--record-id",
                        "17058",
                        "--expected-record-id",
                        "17058",
                        "--old-prefix",
                        "/strm/series/series",
                        "--new-prefix",
                        "/strm/series",
                        "--expected-source-prefix",
                        "/已整理/series/岁月有情时",
                        "--approve-redirect",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["request_summary"]["endpoint"]["path"], "/api/v1/strm/records/redirect")
            self.assertEqual(payload["after"]["matching_prefix_count"], 1)

    def test_cli_writes_strm_records_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "strm-records.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    payload = {
                        "success": True,
                        "data": {
                            "items": [
                                {
                                    "id": 16868,
                                    "source": "organize",
                                    "strm_path": "/example/strm-root/series/八千里路云和月/Season 1/八千里路云和月 - S01E37.strm",
                                    "source_path": "/已整理/series/八千里路云和月/Season 1/八千里路云和月 - S01E37.mkv",
                                }
                            ]
                        },
                    }
                    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                code = main(
                    [
                        "mv3-strm-records",
                        "--env-file",
                        str(env_file),
                        "--keyword",
                        "八千里路云和月",
                        "--record-id",
                        "16868",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["matched_record_count"], 1)
            self.assertEqual(payload["records"][0]["id"], 16868)

    def test_cli_refuses_strm_records_materialize_without_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            with self.assertRaises(SystemExit) as caught:
                main(
                    [
                        "mv3-strm-records-materialize",
                        "--env-file",
                        str(env_file),
                        "--record-id",
                        "16868",
                        "--expected-record-id",
                        "16868",
                        "--expected-strm-prefix",
                        "/example/strm-root/series/八千里路云和月",
                        "--expected-source-prefix",
                        "/已整理/series/八千里路云和月",
                        "--host-strm-prefix",
                        f"{tmp_path}=/example/strm-root",
                    ]
                )

            self.assertNotEqual(caught.exception.code, 0)

    def test_cli_writes_strm_records_materialize_report_with_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "materialize.json"
            host_root = tmp_path / "strm"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    payload = {
                        "success": True,
                        "data": {
                            "items": [
                                {
                                    "id": 16868,
                                    "strm_path": "/example/strm-root/series/八千里路云和月/Season 1/八千里路云和月 - S01E37.strm",
                                    "source_path": "/已整理/series/八千里路云和月/Season 1/八千里路云和月 - S01E37.mkv",
                                    "strm_content": "https://mv3.example/redirect?path=/已整理/series/八千里路云和月/Season%201/E37.mkv&pickcode=secret",
                                }
                            ]
                        },
                    }
                    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                code = main(
                    [
                        "mv3-strm-records-materialize",
                        "--env-file",
                        str(env_file),
                        "--record-id",
                        "16868",
                        "--expected-record-id",
                        "16868",
                        "--keyword",
                        "八千里路云和月",
                        "--expected-strm-prefix",
                        "/example/strm-root/series/八千里路云和月",
                        "--expected-source-prefix",
                        "/已整理/series/八千里路云和月",
                        "--host-strm-prefix",
                        f"{host_root}=/example/strm-root",
                        "--approve-write",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["writes"][0]["record_id"], 16868)
            self.assertNotIn("pickcode=secret", output.read_text(encoding="utf-8"))

    def test_cli_writes_strm_records_materialize_with_rewrite_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            output = tmp_path / "materialize.json"
            host_root = tmp_path / "strm"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=token\n", encoding="utf-8")

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, _exc_type, _exc, _tb):
                    return False

                def read(self, _limit=-1):
                    payload = {
                        "success": True,
                        "data": {
                            "items": [
                                {
                                    "id": 17093,
                                    "strm_path": "/strm/series/series/岁月有情时/Season 1/岁月有情时 - S01E21.strm",
                                    "source_path": "/已整理/series/岁月有情时/Season 1/岁月有情时 - S01E21.mkv",
                                    "strm_content": "https://mv3.example/redirect?path=/已整理/series/岁月有情时/Season%201/E21.mkv",
                                }
                            ]
                        },
                    }
                    return json.dumps(payload, ensure_ascii=False).encode("utf-8")

                @property
                def headers(self):
                    return {"Content-Type": "application/json"}

            with patch("urllib.request.urlopen", lambda _request, timeout: FakeResponse()):
                code = main(
                    [
                        "mv3-strm-records-materialize",
                        "--env-file",
                        str(env_file),
                        "--record-id",
                        "17093",
                        "--expected-record-id",
                        "17093",
                        "--keyword",
                        "岁月有情时",
                        "--expected-strm-prefix",
                        "/strm/series/岁月有情时",
                        "--expected-source-prefix",
                        "/已整理/series/岁月有情时",
                        "--host-strm-prefix",
                        f"{host_root}=/strm",
                        "--rewrite-strm-prefix",
                        "/strm/series/series=/strm/series",
                        "--approve-write",
                        "--format",
                        "json",
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["rewrite_strm_prefix"], "/strm/series/series=/strm/series")

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
