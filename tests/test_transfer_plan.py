import json
import tempfile
import unittest
from pathlib import Path

from series_cloud_archiver.cli import main
from series_cloud_archiver.transfer_plan import (
    plan_mv3_offline_manifest,
    plan_mv3_preview_manifest,
    plan_mv3_share_search_from_transfer_plan,
    plan_mv3_transfers_from_cloud_report,
    render_mv3_offline_manifest,
    render_mv3_preview_manifest,
    render_mv3_share_search_plan,
    render_mv3_transfer_plan,
)


class TransferPlanTest(unittest.TestCase):
    def test_plans_not_found_items_with_identity_by_size(self) -> None:
        report = {
            "mode": "readonly-cloud-check",
            "items": [
                {
                    "status": "cloud_strm_complete",
                    "title": "Already Cloud",
                    "tmdbid": 1,
                    "season": 1,
                    "size_bytes": 999,
                },
                {
                    "status": "cloud_strm_not_found",
                    "title": "Small Show",
                    "tmdbid": 2,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 10,
                    "candidate_count": 1,
                    "titles": ["Small.Show.S01"],
                    "source_paths": ["/example/media/Small.Show.S01"],
                    "missing_episodes": [1, 2],
                    "blockers": ["no_matching_strm_tmdb_season"],
                },
                {
                    "status": "cloud_strm_not_found",
                    "title": "Big Show",
                    "tmdbid": 3,
                    "season": 2,
                    "size_bytes": 200,
                    "expected_count": 12,
                    "candidate_count": 2,
                    "titles": ["Big.Show.S02"],
                    "source_paths": ["/example/media/Big.Show.S02"],
                    "missing_episodes": [1],
                    "blockers": ["no_matching_strm_tmdb_season"],
                },
                {
                    "status": "needs_identity_review",
                    "title": "Unknown Season",
                    "tmdbid": 4,
                    "season": 0,
                    "size_bytes": 300,
                },
            ],
        }

        plan = plan_mv3_transfers_from_cloud_report(report)

        self.assertEqual(plan["mode"], "readonly-mv3-transfer-plan")
        self.assertEqual(plan["total_planned"], 2)
        self.assertEqual([item["title"] for item in plan["items"]], ["Big Show", "Small Show"])
        self.assertEqual(plan["total_size_bytes"], 300)

    def test_renders_markdown_with_safety_note(self) -> None:
        plan = {
            "mode": "readonly-mv3-transfer-plan",
            "source_mode": "readonly-cloud-check",
            "included_statuses": ["cloud_strm_not_found"],
            "total_planned": 1,
            "total_size_bytes": 100,
            "status_counts": {"cloud_strm_not_found": 1},
            "items": [
                {
                    "title": "Demo",
                    "tmdbid": 123,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 2,
                    "candidate_count": 1,
                    "titles": ["Demo.S01"],
                    "source_paths": ["/example/media/Demo.S01"],
                }
            ],
            "warnings": [],
        }

        markdown = render_mv3_transfer_plan(plan, "markdown")

        self.assertIn("MV3 Transfer Plan", markdown)
        self.assertIn("no MV3 transfer", markdown)
        self.assertIn("Demo", markdown)

    def test_builds_preview_manifest_with_execution_blockers(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "Demo/Show",
                    "tmdbid": 123,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 2,
                    "candidate_count": 1,
                    "titles": ["Demo.Show.S01"],
                    "source_paths": ["/example/media/Demo.Show.S01"],
                    "blockers": ["no_matching_strm_tmdb_season"],
                },
                {
                    "title": "Second",
                    "tmdbid": 456,
                    "season": 2,
                    "size_bytes": 50,
                    "expected_count": 8,
                    "candidate_count": 1,
                    "titles": ["Second.S02"],
                    "source_paths": ["/example/media/Second.S02"],
                },
            ],
        }
        instances = {
            "summary": {"failed_paths": ["/api/v1/media-transfer/libraries?instance=emby-default"]},
            "probes": [
                {
                    "path": "/api/v1/cloud-drive/instances",
                    "sample": {
                        "instances": [
                            {
                                "slug": "115-default",
                                "name": "115",
                                "mount_path": {"/已整理/series": "/已整理/series"},
                                "share_transfer_default_path": "/未整理",
                            }
                        ]
                    },
                },
                {"path": "/api/v1/media-transfer/instances", "sample": [{"slug": "emby-default", "name": "Emby"}]},
            ],
        }
        capabilities = {
            "categories": {
                "preview_or_search_post": [
                    {
                        "method": "POST",
                        "path": "/api/v1/media-transfer/preview",
                        "request_schema": {"ref": "PreviewRequest", "required": ["source_library_id"]},
                    }
                ]
            }
        }

        manifest = plan_mv3_preview_manifest(transfer_plan, instances, capabilities, limit=1)

        self.assertEqual(manifest["mode"], "readonly-mv3-preview-manifest")
        self.assertEqual(manifest["planned_items"], 1)
        self.assertEqual(manifest["mv3_context"]["media_transfer_instance"], "emby-default")
        self.assertEqual(manifest["mv3_context"]["cloud_root"], "/已整理/series")
        item = manifest["items"][0]
        self.assertEqual(item["proposed_cloud_destination"], "/已整理/series/Demo Show {tmdbid=123}/Season 01")
        self.assertEqual(item["mv3_preview_call"]["body_template"]["instance"], "emby-default")
        self.assertIn("mv3_libraries_probe_unavailable", item["execution_blockers"])
        self.assertIn("POST /api/v1/media-transfer/execute", manifest["forbidden_endpoints"])

    def test_preview_manifest_does_not_duplicate_tmdb_suffix(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "沉默的荣耀 (2025) {tmdbid=281538}",
                    "tmdbid": 281538,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 39,
                    "candidate_count": 1,
                    "titles": ["沉默的荣耀 (2025) {tmdbid=281538}"],
                    "source_paths": ["/example/media/沉默的荣耀"],
                    "blockers": ["no_matching_strm_tmdb_season"],
                },
            ],
        }

        manifest = plan_mv3_preview_manifest(transfer_plan, limit=1)

        self.assertEqual(
            manifest["items"][0]["proposed_cloud_destination"],
            "/已整理/series/沉默的荣耀 (2025) {tmdbid=281538}/Season 01",
        )

    def test_renders_preview_manifest_markdown(self) -> None:
        manifest = {
            "mode": "readonly-mv3-preview-manifest",
            "source_mode": "readonly-mv3-transfer-plan",
            "available_items": 1,
            "planned_items": 1,
            "total_size_bytes": 100,
            "mv3_context": {"media_transfer_instance": "emby-default", "cloud_root": "/已整理/series"},
            "forbidden_endpoints": ["POST /api/v1/media-transfer/execute"],
            "warnings": [],
            "items": [
                {
                    "priority": 1,
                    "size_bytes": 100,
                    "title": "Demo",
                    "tmdbid": 123,
                    "season": 1,
                    "expected_count": 2,
                    "proposed_cloud_destination": "/已整理/series/Demo {tmdbid=123}/Season 01",
                    "mv3_preview_call": {"method": "POST", "path": "/api/v1/media-transfer/preview"},
                    "execution_blockers": ["requires_manual_approval_before_execute"],
                    "source_paths": ["/example/media/Demo"],
                }
            ],
        }

        markdown = render_mv3_preview_manifest(manifest, "markdown")

        self.assertIn("MV3 Preview Manifest", markdown)
        self.assertIn("readonly manifest only", markdown)
        self.assertIn("/已整理/series/Demo", markdown)

    def test_cli_writes_preview_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transfer_plan = tmp_path / "transfer.json"
            output = tmp_path / "preview.json"
            transfer_plan.write_text(
                json.dumps(
                    {
                        "mode": "readonly-mv3-transfer-plan",
                        "items": [
                            {
                                "title": "Demo",
                                "tmdbid": 123,
                                "season": 1,
                                "size_bytes": 100,
                                "expected_count": 2,
                                "candidate_count": 1,
                                "titles": ["Demo.S01"],
                                "source_paths": ["/example/media/Demo.S01"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            code = main(
                [
                    "plan-mv3-preview",
                    "--transfer-plan",
                    str(transfer_plan),
                    "--limit",
                    "1",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["planned_items"], 1)

    def test_builds_offline_manifest_without_leaking_magnets(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "Demo",
                    "tmdbid": 123,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 2,
                    "candidate_count": 1,
                    "titles": ["Demo.S01"],
                    "source_paths": ["/example/media/Demo.S01"],
                }
            ],
        }
        qb_torrents = [
            {
                "name": "Demo.S01",
                "hash": "abc",
                "state": "stalledUP",
                "content_path": "/example/media/Demo.S01",
                "size": 100,
                "progress": 1,
                "seeding_time": 8 * 86400,
                "magnet_uri": "magnet:?xt=urn:btih:abc&secret=private",
            }
        ]
        instances = {
            "probes": [
                {
                    "path": "/api/v1/cloud-drive/instances",
                    "sample": {"instances": [{"slug": "115-default", "name": "115", "mount_path": {"/已整理/series": "/已整理/series"}}]},
                }
            ]
        }

        manifest = plan_mv3_offline_manifest(transfer_plan, qb_torrents, instances, limit=1)
        rendered = render_mv3_offline_manifest(manifest, "json")

        self.assertEqual(manifest["planned_items"], 1)
        self.assertEqual(manifest["items"][0]["qb_match_count"], 1)
        self.assertEqual(manifest["items"][0]["qb_magnet_available_count"], 1)
        self.assertEqual(manifest["items"][0]["qb_seed_age_ok_count"], 1)
        self.assertEqual(manifest["items"][0]["mv3_offline_call"]["body_template"]["urls"], "[REDACTED_MAGNET_URIS_FROM_QB]")
        self.assertNotIn("magnet:?", rendered)
        self.assertIn("POST /api/v1/files/115/offline/add", manifest["forbidden_endpoints"])

    def test_offline_manifest_matches_normalized_hlink_title_to_qb(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "沉默的荣耀",
                    "tmdbid": 123456,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 39,
                    "candidate_count": 1,
                    "titles": ["沉默的荣耀 (2025) {tmdbid=123456}"],
                    "source_paths": ["/example/library-host/hlink/TV/沉默的荣耀 (2025) {tmdbid=123456}"],
                }
            ],
        }
        qb_torrents = [
            {
                "name": "沉默的荣耀.Silent.Honor.S01.2025.2160p.WEB-DL.H265.AAC-ADWeb",
                "hash": "abc",
                "state": "stalledUP",
                "content_path": "/example/qb-view/TV/沉默的荣耀.Silent.Honor.S01.2025.2160p.WEB-DL.H265.AAC-ADWeb",
                "size": 100,
                "progress": 1,
                "seeding_time": 8 * 86400,
                "magnet_uri": "magnet:?xt=urn:btih:abc&secret=private",
            }
        ]
        instances = {
            "probes": [
                {
                    "path": "/api/v1/cloud-drive/instances",
                    "sample": {"instances": [{"slug": "115-default", "name": "115", "mount_path": {"/已整理/series": "/已整理/series"}}]},
                }
            ]
        }

        manifest = plan_mv3_offline_manifest(transfer_plan, qb_torrents, instances, limit=1)

        self.assertEqual(manifest["items"][0]["qb_match_count"], 1)
        self.assertEqual(manifest["items"][0]["qb_magnet_available_count"], 1)

    def test_offline_manifest_rejects_same_title_wrong_year_without_tv_signal(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "海市蜃楼 (2025) {tmdbid=302726}",
                    "tmdbid": 302726,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 24,
                    "candidate_count": 1,
                    "titles": ["海市蜃楼 (2025) {tmdbid=302726}"],
                    "source_paths": ["/example/library-host/hlink/TV/海市蜃楼 (2025) {tmdbid=302726}"],
                }
            ],
        }
        qb_torrents = [
            {
                "name": "海市蜃楼.2018.1080p.国西双语.简繁中字",
                "hash": "wrong",
                "state": "stalledUP",
                "content_path": "/example/qb-view/TV/海市蜃楼.2018.1080p.国西双语.简繁中字",
                "size": 100,
                "progress": 1,
                "seeding_time": 8 * 86400,
                "magnet_uri": "magnet:?xt=urn:btih:wrong",
            }
        ]

        manifest = plan_mv3_offline_manifest(transfer_plan, qb_torrents, limit=1)

        self.assertEqual(manifest["items"][0]["qb_match_count"], 0)
        self.assertIn("missing_qb_torrent_match", manifest["items"][0]["execution_blockers"])

    def test_renders_offline_manifest_markdown(self) -> None:
        manifest = {
            "mode": "readonly-mv3-offline-manifest",
            "source_mode": "readonly-mv3-transfer-plan",
            "available_items": 1,
            "planned_items": 1,
            "total_size_bytes": 100,
            "mv3_context": {"cloud_drive_slug": "115-default", "cloud_root": "/已整理/series"},
            "min_seed_days": 7,
            "forbidden_endpoints": ["POST /api/v1/files/115/offline/add"],
            "warnings": [],
            "items": [
                {
                    "priority": 1,
                    "size_bytes": 100,
                    "title": "Demo",
                    "tmdbid": 123,
                    "season": 1,
                    "expected_count": 2,
                    "qb_match_count": 1,
                    "qb_magnet_available_count": 1,
                    "qb_seed_age_ok_count": 1,
                    "proposed_cloud_destination": "/已整理/series/Demo {tmdbid=123}/Season 01",
                    "execution_blockers": ["requires_manual_approval_before_offline_add"],
                }
            ],
        }

        markdown = render_mv3_offline_manifest(manifest, "markdown")

        self.assertIn("MV3 Offline Manifest", markdown)
        self.assertIn("magnet URIs are not written", markdown)
        self.assertIn("Demo", markdown)

    def test_cli_writes_offline_manifest_from_cached_qb_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            transfer_plan = tmp_path / "transfer.json"
            qb_report = tmp_path / "qb.json"
            output = tmp_path / "offline.json"
            transfer_plan.write_text(
                json.dumps(
                    {
                        "mode": "readonly-mv3-transfer-plan",
                        "items": [
                            {
                                "title": "Demo",
                                "tmdbid": 123,
                                "season": 1,
                                "size_bytes": 100,
                                "expected_count": 2,
                                "candidate_count": 1,
                                "titles": ["Demo.S01"],
                                "source_paths": ["/example/media/Demo.S01"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            qb_report.write_text(
                json.dumps({"torrents": [{"name": "Demo.S01", "content_path": "/example/media/Demo.S01", "magnet_uri": "magnet:?x"}]}),
                encoding="utf-8",
            )

            code = main(
                [
                    "plan-mv3-offline",
                    "--transfer-plan",
                    str(transfer_plan),
                    "--qb-report",
                    str(qb_report),
                    "--limit",
                    "1",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["planned_items"], 1)
            self.assertNotIn("magnet:?", output.read_text(encoding="utf-8"))

    def test_builds_share_search_plan_by_size_and_episode_fit(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "八千里路云和月",
                    "tmdbid": 289624,
                    "season": 1,
                    "size_bytes": 40 * 1024**3,
                    "expected_count": 40,
                    "source_paths": ["/example/library-host/hlink/TV/八千里路云和月"],
                }
            ],
        }
        search_reports = {
            "八千里路云和月": {
                "ok": True,
                "result_count": 2,
                "items": [
                    {
                        "index": 1,
                        "title": "八千里路云和月 S01E01-E40 完结",
                        "size": "41.7 GiB",
                        "share_code_available": True,
                    },
                    {
                        "index": 2,
                        "title": "八千里路云和月 S01E01-E10",
                        "size": "8 GiB",
                        "share_code_available": True,
                    },
                ],
            }
        }

        plan = plan_mv3_share_search_from_transfer_plan(transfer_plan, search_reports, limit=1)

        self.assertEqual(plan["mode"], "readonly-mv3-share-search-plan")
        self.assertEqual(plan["ready_items"], 1)
        recommended = plan["items"][0]["recommended_candidate"]
        self.assertEqual(recommended["search_index"], 1)
        self.assertIn("size_similar", recommended["reasons"])
        self.assertIn("episode_count_covers_expected", recommended["reasons"])

    def test_share_search_plan_can_start_from_offset(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {"title": "第一部", "season": 1, "size_bytes": 1, "expected_count": 1},
                {"title": "第二部", "season": 1, "size_bytes": 2, "expected_count": 1},
                {"title": "第三部", "season": 1, "size_bytes": 3, "expected_count": 1},
            ],
        }
        search_reports = {"第二部": {"ok": True, "result_count": 0, "items": []}}

        plan = plan_mv3_share_search_from_transfer_plan(
            transfer_plan,
            search_reports,
            limit=1,
            offset=1,
        )

        self.assertEqual(plan["planned_items"], 1)
        self.assertEqual(plan["offset"], 1)
        self.assertEqual(plan["items"][0]["priority"], 2)
        self.assertEqual(plan["items"][0]["title"], "第二部")

    def test_share_search_plan_reads_chinese_episode_ranges_and_title_size(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "四喜",
                    "tmdbid": 273131,
                    "season": 1,
                    "size_bytes": int(1.1 * 1024**4),
                    "expected_count": 36,
                    "source_paths": ["/example/library-host/hlink/TV/四喜"],
                }
            ],
        }
        search_reports = {
            "四喜": {
                "ok": True,
                "result_count": 1,
                "items": [
                    {
                        "index": 1,
                        "title": "🎬 四喜 全36集 1.24T",
                        "size": "",
                        "share_code_available": True,
                    }
                ],
            }
        }

        plan = plan_mv3_share_search_from_transfer_plan(transfer_plan, search_reports, limit=1)

        recommended = plan["items"][0]["recommended_candidate"]
        self.assertEqual(recommended["search_index"], 1)
        self.assertIn("complete_marker", recommended["reasons"])
        self.assertIn("size_similar", recommended["reasons"])

    def test_renders_share_search_plan_markdown(self) -> None:
        plan = {
            "mode": "readonly-mv3-share-search-plan",
            "source_mode": "readonly-mv3-transfer-plan",
            "available_items": 1,
            "planned_items": 1,
            "ready_items": 1,
            "total_size_bytes": 100,
            "items": [
                {
                    "priority": 1,
                    "title": "Demo",
                    "tmdbid": 123,
                    "season": 1,
                    "expected_count": 2,
                    "size_bytes": 100,
                    "search_ok": True,
                    "search_result_count": 1,
                    "recommended_candidate": {
                        "title": "Demo S01E01-E02",
                        "size_bytes": 110,
                        "score": 90,
                        "reasons": ["title_contains"],
                        "blockers": [],
                    },
                    "source_paths": ["/example/Demo"],
                    "warnings": [],
                }
            ],
        }

        markdown = render_mv3_share_search_plan(plan, "markdown")

        self.assertIn("MV3 Share Search Plan", markdown)
        self.assertIn("readonly MV3 resource-search", markdown)
        self.assertIn("Demo S01E01-E02", markdown)


if __name__ == "__main__":
    unittest.main()
