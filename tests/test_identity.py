import json
import tempfile
import unittest
from pathlib import Path

from series_cloud_archiver.identity import (
    resolve_identity_overrides_from_cloud_report,
    resolve_identity_overrides_from_scan_report,
)


class FakeMoviePilotClient:
    calls = []
    init_kwargs = []

    def __init__(self, base_url, token, **kwargs):
        self.base_url = base_url
        self.token = token
        self.timeout = kwargs.get("timeout")
        self.__class__.init_kwargs.append(kwargs)

    def recognize_file(self, path):
        self.__class__.calls.append(path)
        return {
            "meta_info": {
                "type": "电视剧",
                "name": "Foundation",
                "begin_season": 1,
                "end_season": None,
            },
            "media_info": {
                "type": "电视剧",
                "title": "基地",
                "en_title": "Foundation",
                "year": "2021",
                "tmdb_id": 93740,
                "seasons": {"1": [1, 2, 3]},
            },
        }


class IdentityResolveTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeMoviePilotClient.calls = []
        FakeMoviePilotClient.init_kwargs = []

    def test_resolves_missing_candidate_identity(self) -> None:
        report = {
            "candidates": [
                {
                    "title": "Foundation.S01.2021",
                    "status": "candidate_for_cloud_check",
                    "video_count": 3,
                }
            ]
        }

        import series_cloud_archiver.identity as identity_module

        original = identity_module.MoviePilotClient
        identity_module.MoviePilotClient = FakeMoviePilotClient
        try:
            payload = resolve_identity_overrides_from_scan_report(report, "http://example.invalid", "token")
        finally:
            identity_module.MoviePilotClient = original

        self.assertEqual(payload["summary"]["resolved"], 1)
        record = payload["identity_overrides"][0]
        self.assertEqual(record["tmdbid"], 93740)
        self.assertEqual(record["season"], 1)
        self.assertEqual(record["expected_episodes"], [1, 2, 3])

    def test_scan_report_skips_title_with_tmdbid_and_single_season(self) -> None:
        report = {
            "candidates": [
                {
                    "title": "法证先锋 (2006) {tmdbid=286997} Season 02",
                    "path": "/example/local-tv/法证先锋 (2006) {tmdbid=286997}/Season 02",
                    "status": "candidate_for_cloud_check",
                    "video_count": 30,
                    "seasons": [2],
                },
                {
                    "title": "Foundation.S01.2021",
                    "status": "candidate_for_cloud_check",
                    "video_count": 3,
                },
            ]
        }

        import series_cloud_archiver.identity as identity_module

        original = identity_module.MoviePilotClient
        identity_module.MoviePilotClient = FakeMoviePilotClient
        try:
            payload = resolve_identity_overrides_from_scan_report(report, "http://example.invalid", "token")
        finally:
            identity_module.MoviePilotClient = original

        self.assertEqual(payload["summary"]["input_candidates"], 1)
        self.assertEqual(FakeMoviePilotClient.calls, ["Foundation.S01.2021"])

    def test_cloud_report_resolves_only_identity_review_rows(self) -> None:
        report = {
            "items": [
                {
                    "status": "needs_identity_review",
                    "title": "Foundation.S01.2021",
                    "season": 1,
                    "expected_count": 3,
                    "expected_episodes": [1, 2, 3],
                    "source_paths": ["/example/local-tv/Foundation/Season 1"],
                },
                {
                    "status": "cloud_strm_not_found",
                    "title": "Already Known",
                    "tmdbid": 123,
                    "season": 1,
                    "expected_count": 3,
                },
            ]
        }

        import series_cloud_archiver.identity as identity_module

        original = identity_module.MoviePilotClient
        identity_module.MoviePilotClient = FakeMoviePilotClient
        try:
            payload = resolve_identity_overrides_from_cloud_report(report, "http://example.invalid", "token")
        finally:
            identity_module.MoviePilotClient = original

        self.assertEqual(payload["summary"], {"input_candidates": 1, "attempted": 1, "resolved": 1})
        record = payload["identity_overrides"][0]
        self.assertEqual(record["match_path"], "/example/local-tv/Foundation/Season 1")
        self.assertEqual(record["tmdbid"], 93740)
        self.assertEqual(record["season"], 1)
        self.assertEqual(FakeMoviePilotClient.calls, ["Foundation.S01.2021"])

    def test_keeps_multi_season_pack_for_review(self) -> None:
        report = {
            "candidates": [
                {
                    "title": "Foundation.S01-S03.2021",
                    "status": "candidate_for_cloud_check",
                    "video_count": 30,
                    "seasons": [1, 2, 3],
                }
            ]
        }

        import series_cloud_archiver.identity as identity_module

        original = identity_module.MoviePilotClient
        identity_module.MoviePilotClient = FakeMoviePilotClient
        try:
            payload = resolve_identity_overrides_from_scan_report(report, "http://example.invalid", "token")
        finally:
            identity_module.MoviePilotClient = original

        self.assertEqual(payload["summary"]["resolved"], 1)
        record = payload["identity_overrides"][0]
        self.assertEqual(record["tmdbid"], 93740)
        self.assertEqual(record["season"], 0)
        self.assertEqual(record["confidence"], "needs_season_review")
        self.assertEqual(record["expected_episodes"], [])

    def test_can_persist_progress_to_output_file(self) -> None:
        report = {
            "candidates": [
                {
                    "title": "Foundation.S01.2021",
                    "status": "candidate_for_cloud_check",
                    "video_count": 3,
                }
            ]
        }

        import series_cloud_archiver.identity as identity_module

        original = identity_module.MoviePilotClient
        identity_module.MoviePilotClient = FakeMoviePilotClient
        try:
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "identity.json"
                payload = resolve_identity_overrides_from_scan_report(
                    report,
                    "http://example.invalid",
                    "token",
                    output_path=str(output),
                    progress=lambda _message: None,
                )
                written = json.loads(output.read_text(encoding="utf-8"))
        finally:
            identity_module.MoviePilotClient = original

        self.assertEqual(payload["summary"]["attempted"], 1)
        self.assertEqual(written["summary"]["attempted"], 1)
        self.assertEqual(written["summary"]["resolved"], 1)

    def test_passes_timeout_to_moviepilot_client(self) -> None:
        report = {
            "items": [
                {
                    "status": "needs_identity_review",
                    "title": "Foundation.S01.2021",
                    "season": 1,
                    "expected_count": 3,
                    "expected_episodes": [1, 2, 3],
                    "source_paths": ["/example/local-tv/Foundation/Season 1"],
                }
            ]
        }

        import series_cloud_archiver.identity as identity_module

        original = identity_module.MoviePilotClient
        identity_module.MoviePilotClient = FakeMoviePilotClient
        try:
            payload = resolve_identity_overrides_from_cloud_report(
                report,
                "http://example.invalid",
                "token",
                timeout=7,
            )
        finally:
            identity_module.MoviePilotClient = original

        self.assertEqual(payload["summary"]["resolved"], 1)
        self.assertEqual(FakeMoviePilotClient.init_kwargs, [{"timeout": 7}])


if __name__ == "__main__":
    unittest.main()
