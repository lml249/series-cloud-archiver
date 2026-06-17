import json
import tempfile
import unittest
from pathlib import Path

from series_cloud_archiver.identity import resolve_identity_overrides_from_scan_report


class FakeMoviePilotClient:
    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token

    def recognize_file(self, path):
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


if __name__ == "__main__":
    unittest.main()
