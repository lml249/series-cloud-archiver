import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from series_cloud_archiver.cli import main
from series_cloud_archiver.cloud_check import cloud_check_from_scan_report
from series_cloud_archiver.transfer_plan import (
    plan_mv3_offline_manifest,
    plan_mv3_preview_manifest,
    plan_mv3_restored_transfer_queue,
    plan_mv3_share_search_from_transfer_plan,
    plan_mv3_transfers_from_cloud_report,
    render_mv3_offline_manifest,
    render_mv3_preview_manifest,
    render_mv3_restored_transfer_queue,
    render_mv3_share_search_plan,
    render_mv3_transfer_plan,
    search_keywords_for_item,
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

    def test_cloud_check_carries_search_keywords_from_qb_release_name(self) -> None:
        report = {
            "mode": "dry-run",
            "candidates": [
                {
                    "status": "candidate_for_cloud_check",
                    "title": "长安二十四计 (2025) {tmdbid=254482}",
                    "path": "/media/长安二十四计 (2025) {tmdbid=254482}",
                    "size_bytes": 100,
                    "video_count": 28,
                    "seasons": [1],
                    "episode_numbers": list(range(1, 29)),
                    "mp": {"name": "长安二十四计", "tmdbid": 254482, "season": 1, "total_episode": 0},
                    "qb": {
                        "name": "长安二十四计.The.Vendetta.of.An.S01.2025.2160p.WEB-DL.H265.AAC-HHWEB",
                        "content_path": "/media/local-series/长安二十四计.The.Vendetta.of.An.S01.2025.2160p.WEB-DL.H265.AAC-HHWEB",
                    },
                }
            ],
        }

        cloud = cloud_check_from_scan_report(report, [])
        plan = plan_mv3_transfers_from_cloud_report(cloud.to_dict())
        keywords = plan["items"][0]["search_keywords"]

        self.assertIn("长安二十四计", keywords)
        self.assertIn("The Vendetta of An", keywords)

    def test_transfer_plan_filters_generic_mv3_search_keywords(self) -> None:
        report = {
            "mode": "readonly-cloud-check",
            "items": [
                {
                    "status": "cloud_strm_not_found",
                    "title": "长风渡 (2023) {tmdbid=207004}",
                    "tmdbid": 207004,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 40,
                    "candidate_count": 1,
                    "titles": [
                        "长风渡.The.Destined.S01.2023.2160p.WEB-DL.H265.AAC",
                        "{tmdbid=207004} Season",
                    ],
                    "search_keywords": ["Season 01", "{tmdbid=207004} Season"],
                    "source_paths": ["/example/library/长风渡 (2023) {tmdbid=207004}/Season 01"],
                }
            ],
        }

        plan = plan_mv3_transfers_from_cloud_report(report)
        keywords = plan["items"][0]["search_keywords"]

        self.assertIn("长风渡", keywords)
        self.assertIn("The Destined", keywords)
        self.assertNotIn("Season 01", keywords)
        self.assertFalse(any("{tmdbid=" in keyword for keyword in keywords))
        self.assertFalse(any(keyword.lower().strip() == "season" for keyword in keywords))

    def test_search_keywords_for_item_cleans_cli_execution_inputs(self) -> None:
        keywords = search_keywords_for_item(
            {
                "title": "Demo Show (2020) {tmdbid=1}",
                "season": 1,
                "search_keywords": ["Season 01", "{tmdbid=1} Season", "Demo Show"],
                "titles": ["Demo.Show.S01.2020.1080p.WEB-DL"],
                "source_paths": ["/example/library/Demo Show (2020) {tmdbid=1}/Season 01"],
            }
        )

        self.assertEqual(keywords, ["Demo Show"])

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

    def test_restored_transfer_queue_splits_ready_and_identity_review(self) -> None:
        cloud_report = {
            "mode": "readonly-cloud-check",
            "items": [
                {
                    "status": "cloud_strm_not_found",
                    "title": "Ready Show",
                    "tmdbid": 10,
                    "season": 1,
                    "size_bytes": 200,
                    "expected_count": 8,
                    "source_paths": ["/cloud-check/Ready"],
                    "search_keywords": ["Ready Show"],
                },
                {
                    "status": "needs_identity_review",
                    "title": "Needs Season",
                    "tmdbid": 11,
                    "season": 0,
                    "size_bytes": 300,
                    "expected_count": 12,
                    "blockers": ["missing_season"],
                },
            ],
        }
        transfer_plan = {
            "items": [
                {
                    "title": "Ready Show",
                    "tmdbid": 10,
                    "season": 1,
                    "source_paths": ["/transfer-plan/Ready"],
                    "search_keywords": ["Ready Show", "Ready English"],
                }
            ]
        }
        historical_scan = {
            "candidates": [
                {"status": "candidate_for_cloud_check", "title": "Old Candidate", "path": "/old", "size_bytes": 50, "video_count": 2},
                {"status": "blocked_qb_evidence", "title": "Blocked", "path": "/blocked"},
            ]
        }
        mv3_report = {"configured": True, "reachable": True, "license_status": "required_or_inactive", "warnings": ["mv3_license_required"]}

        report = plan_mv3_restored_transfer_queue(cloud_report, transfer_plan, historical_scan, mv3_report)
        rendered = render_mv3_restored_transfer_queue(report, "markdown")

        self.assertEqual(report["mode"], "readonly-mv3-restored-transfer-queue")
        self.assertEqual(report["summary"]["ready_when_mv3_restored"], 1)
        self.assertEqual(report["summary"]["needs_identity_review"], 1)
        self.assertEqual(report["summary"]["historical_candidate_for_cloud_check"], 1)
        ready = report["ready_when_mv3_restored"][0]
        self.assertEqual(ready["title"], "Ready Show")
        self.assertIn("/transfer-plan/Ready", ready["source_paths"])
        self.assertIn("/cloud-check/Ready", ready["source_paths"])
        self.assertIn("Ready English", ready["search_keywords"])
        self.assertEqual(report["mv3_status"]["license_status"], "required_or_inactive")
        self.assertIn("mv3_not_ready_for_transfer", report["warnings"])
        self.assertIn("Ready When MV3 Restored", rendered)
        self.assertIn("readonly queue only", rendered)

    def test_cli_writes_restored_transfer_queue_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cloud_report = tmp_path / "cloud.json"
            transfer_plan = tmp_path / "transfer.json"
            mv3_report = tmp_path / "mv3.json"
            json_output = tmp_path / "queue.json"
            md_output = tmp_path / "queue.md"
            cloud_report.write_text(
                json.dumps(
                    {
                        "mode": "readonly-cloud-check",
                        "items": [
                            {
                                "status": "cloud_strm_not_found",
                                "title": "Demo",
                                "tmdbid": 123,
                                "season": 1,
                                "size_bytes": 100,
                                "expected_count": 2,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            transfer_plan.write_text(json.dumps({"items": [{"title": "Demo", "tmdbid": 123, "season": 1, "search_keywords": ["Demo"]}]}), encoding="utf-8")
            mv3_report.write_text(json.dumps({"configured": True, "reachable": True, "license_status": "active"}), encoding="utf-8")

            json_status = main(
                [
                    "mv3-restored-transfer-queue",
                    "--cloud-report",
                    str(cloud_report),
                    "--transfer-plan",
                    str(transfer_plan),
                    "--mv3-report",
                    str(mv3_report),
                    "--format",
                    "json",
                    "--output",
                    str(json_output),
                ]
            )
            md_status = main(
                [
                    "mv3-restored-transfer-queue",
                    "--cloud-report",
                    str(cloud_report),
                    "--format",
                    "markdown",
                    "--output",
                    str(md_output),
                ]
            )

            self.assertEqual(json_status, 0)
            self.assertEqual(md_status, 0)
            payload = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["ready_when_mv3_restored"], 1)
            self.assertIn("MV3 Restored Transfer Queue", md_output.read_text(encoding="utf-8"))

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
        self.assertEqual(manifest["items"][0]["post_offline_strm_generate_call"]["body_template"]["source_dir"], "/已整理/series/Demo {tmdbid=123}/Season 01")
        self.assertEqual(manifest["items"][0]["post_offline_strm_generate_call"]["body_template"]["target_dir"], "/strm")
        self.assertNotIn("magnet:?", rendered)
        self.assertIn("POST /api/v1/files/115/offline/add", manifest["forbidden_endpoints"])

    def test_offline_manifest_can_target_cloud_root_for_mv3_organize_flow(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "繁城之下 (2023) {tmdbid=233959}",
                    "tmdbid": 233959,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 12,
                    "candidate_count": 1,
                    "titles": ["繁城之下 (2023) {tmdbid=233959}"],
                    "source_paths": ["/example/media/繁城之下"],
                }
            ],
        }
        qb_torrents = [
            {
                "name": "繁城之下.Ripe.Town.S01.2023.2160p.WEB-DL",
                "hash": "abc",
                "state": "stalledUP",
                "content_path": "/example/media/繁城之下",
                "size": 100,
                "progress": 1,
                "seeding_time": 8 * 86400,
                "magnet_uri": "magnet:?xt=urn:btih:abc&secret=private",
            }
        ]

        manifest = plan_mv3_offline_manifest(
            transfer_plan,
            qb_torrents,
            limit=1,
            cloud_root="/未整理",
            destination_mode="root",
        )

        item = manifest["items"][0]
        self.assertEqual(manifest["destination_mode"], "root")
        self.assertEqual(item["offline_wp_path"], "/未整理")
        self.assertEqual(item["offline_destination_mode"], "root")
        self.assertEqual(item["proposed_cloud_destination"], "/未整理/繁城之下 (2023) {tmdbid=233959}/Season 01")
        self.assertEqual(item["mv3_offline_call"]["body_template"]["wp_path"], "/未整理")

    def test_offline_manifest_uses_strm_side_root_for_generation_template(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "Demo",
                    "tmdbid": 123,
                    "season": 1,
                    "size_bytes": 100,
                    "expected_count": 2,
                    "source_paths": ["/example/media/Demo"],
                }
            ],
        }
        qb_torrents = [{"name": "Demo.S01", "content_path": "/example/media/Demo", "magnet_uri": "magnet:?x", "seeding_time": 9 * 86400}]

        manifest = plan_mv3_offline_manifest(
            transfer_plan,
            qb_torrents,
            cloud_root="/已整理/series",
            strm_root="/example/mv3/strm",
            limit=1,
        )
        blocked = plan_mv3_offline_manifest(
            transfer_plan,
            qb_torrents,
            cloud_root="/已整理/series",
            strm_root="/已整理",
            limit=1,
        )

        call = manifest["items"][0]["post_offline_strm_generate_call"]["body_template"]
        self.assertEqual(call["source_dir"], "/已整理/series/Demo {tmdbid=123}/Season 01")
        self.assertEqual(call["target_dir"], "/example/mv3/strm")
        self.assertIn("strm_root_must_be_strm_side", blocked["items"][0]["execution_blockers"])

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
                    "--strm-root",
                    "/example/mv3/strm",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["planned_items"], 1)
            self.assertEqual(payload["items"][0]["post_offline_strm_generate_call"]["body_template"]["target_dir"], "/example/mv3/strm")
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

    def test_share_search_plan_ignores_4k_when_parsing_title_size(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "一饭封神 (2025) {tmdbid=296217}",
                    "tmdbid": 296217,
                    "season": 1,
                    "size_bytes": int(55.5 * 1024**3),
                    "expected_count": 25,
                    "source_paths": ["/example/library-host/hlink/TV/一饭封神 (2025) {tmdbid=296217}"],
                }
            ],
        }
        search_reports = {
            "一饭封神 (2025) {tmdbid=296217}": {
                "ok": True,
                "result_count": 1,
                "items": [
                    {
                        "index": 7,
                        "title": "📺 一饭封神 (2025) 第1季 更新至第25集 ✨4K WEB-DL AAC 53.92 GB",
                        "size": "",
                        "share_code_available": True,
                        "search_keyword": "一饭封神",
                    }
                ],
            }
        }

        plan = plan_mv3_share_search_from_transfer_plan(transfer_plan, search_reports, limit=1)

        recommended = plan["items"][0]["recommended_candidate"]
        self.assertEqual(plan["ready_items"], 1)
        self.assertEqual(recommended["search_index"], 7)
        self.assertGreater(recommended["size_bytes"], 50 * 1000**3)
        self.assertIn("episode_count_covers_expected", recommended["reasons"])
        self.assertIn("size_similar", recommended["reasons"])
        self.assertNotIn("size_far_from_local", recommended["blockers"])

    def test_share_search_plan_treats_4k_placeholder_size_as_unknown(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "唐诡奇谭之长安县尉",
                    "tmdbid": 305979,
                    "season": 1,
                    "size_bytes": int(2.1 * 1024**3),
                    "expected_count": 56,
                    "source_paths": ["/example/library-host/hlink/TV/唐诡奇谭之长安县尉"],
                }
            ],
        }
        search_reports = {
            "唐诡奇谭之长安县尉": {
                "ok": True,
                "result_count": 1,
                "items": [
                    {
                        "index": 1,
                        "title": "唐诡奇谭之长安县尉（2025）全56集 4K SDR 竖屏微短剧",
                        "size": "",
                        "share_code_available": True,
                    }
                ],
            }
        }

        plan = plan_mv3_share_search_from_transfer_plan(transfer_plan, search_reports, limit=1)

        recommended = plan["items"][0]["recommended_candidate"]
        self.assertEqual(plan["ready_items"], 1)
        self.assertEqual(recommended["size_bytes"], 0)
        self.assertIn("complete_marker", recommended["reasons"])
        self.assertIn("remote_size_unknown", recommended["reasons"])
        self.assertNotIn("size_far_from_local", recommended["blockers"])

    def test_share_search_plan_records_keyword_for_english_result(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "长安二十四计",
                    "tmdbid": 254482,
                    "season": 1,
                    "size_bytes": int(190 * 1024**3),
                    "expected_count": 28,
                    "search_keywords": ["长安二十四计", "The Vendetta of An"],
                    "source_paths": ["/example/长安二十四计"],
                }
            ],
        }
        search_reports = {
            "长安二十四计": {
                "ok": True,
                "result_count": 1,
                "items": [
                    {
                        "index": 1,
                        "title": "The Vendetta of An S01E01-E28 Complete 190GB",
                        "size": "190GB",
                        "share_code_available": True,
                        "search_keyword": "The Vendetta of An",
                    }
                ],
            }
        }

        plan = plan_mv3_share_search_from_transfer_plan(transfer_plan, search_reports, limit=1)

        recommended = plan["items"][0]["recommended_candidate"]
        self.assertEqual(recommended["search_keyword"], "The Vendetta of An")
        self.assertIn("episode_count_covers_expected", recommended["reasons"])

    def test_share_search_plan_blocks_possible_chinese_subtitle_mismatch(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "唐朝诡事录",
                    "tmdbid": 211089,
                    "season": 1,
                    "size_bytes": int(100 * 1024**3),
                    "expected_count": 40,
                    "search_keywords": ["唐朝诡事录", "Horror Stories of Tang Dynasty"],
                }
            ],
        }
        search_reports = {
            "唐朝诡事录": {
                "ok": True,
                "result_count": 1,
                "items": [
                    {
                        "index": 1,
                        "title": "🎬 唐朝诡事录之长安（完结）",
                        "size": "",
                        "share_code_available": True,
                        "search_keyword": "唐朝诡事录",
                    }
                ],
            }
        }

        plan = plan_mv3_share_search_from_transfer_plan(transfer_plan, search_reports, limit=1)

        self.assertEqual(plan["ready_items"], 0)
        self.assertIn("possible_chinese_subtitle_mismatch", plan["items"][0]["candidates"][0]["blockers"])

    def test_share_search_plan_blocks_explicit_wrong_season(self) -> None:
        transfer_plan = {
            "mode": "readonly-mv3-transfer-plan",
            "items": [
                {
                    "title": "怪奇物语",
                    "tmdbid": 66732,
                    "season": 4,
                    "size_bytes": int(43.8 * 1024**3),
                    "expected_count": 9,
                    "search_keywords": ["怪奇物语 Season 04"],
                    "source_paths": ["/example/怪奇物语/Season 04"],
                }
            ],
        }
        search_reports = {
            "怪奇物语": {
                "ok": True,
                "result_count": 1,
                "items": [
                    {
                        "index": 15,
                        "title": "📺 电视剧：怪奇物语：1985故事集 (2026) - S01E01-E10(完结)",
                        "size": "41.19 GB",
                        "share_code_available": True,
                        "search_keyword": "怪奇物语 Season 04",
                    }
                ],
            }
        }

        plan = plan_mv3_share_search_from_transfer_plan(transfer_plan, search_reports, limit=1)

        self.assertEqual(plan["ready_items"], 0)
        candidate = plan["items"][0]["candidates"][0]
        self.assertIn("season_mismatch", candidate["blockers"])
        self.assertEqual(plan["items"][0]["recommended_candidate"], {})

    def test_cli_share_search_uses_all_search_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            plan_file = tmp_path / "plan.json"
            output_file = tmp_path / "share-search.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=secret\n", encoding="utf-8")
            plan_file.write_text(
                json.dumps(
                    {
                        "mode": "readonly-mv3-transfer-plan",
                        "items": [
                            {
                                "title": "长安二十四计 (2025) {tmdbid=254482}",
                                "tmdbid": 254482,
                                "season": 1,
                                "size_bytes": int(190 * 1024**3),
                                "expected_count": 28,
                                "search_keywords": ["Season 01", "{tmdbid=254482} Season", "长安二十四计", "The Vendetta of An"],
                                "titles": ["长安二十四计.The.Vendetta.of.An.S01.2025.2160p.WEB-DL.H265.AAC"],
                                "source_paths": ["/example/library/长安二十四计 (2025) {tmdbid=254482}/Season 01"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            calls = []

            def fake_search(_base_url, _token, keyword, channels=None, timeout=60):
                calls.append(keyword)
                return {
                    "ok": True,
                    "result_count": 1,
                    "items": [
                        {
                            "index": len(calls),
                            "title": "The Vendetta of An S01E01-E28 Complete 190GB" if "Vendetta" in keyword else "unrelated",
                            "size": "190GB" if "Vendetta" in keyword else "",
                            "share_code_available": "Vendetta" in keyword,
                        }
                    ],
                }

            with patch("series_cloud_archiver.cli.search_mv3_resources", side_effect=fake_search):
                status = main(
                    [
                        "plan-mv3-share-search",
                        "--env-file",
                        str(env_file),
                        "--transfer-plan",
                        str(plan_file),
                        "--limit",
                        "1",
                        "--format",
                        "json",
                        "--output",
                        str(output_file),
                    ]
                )

            payload = json.loads(output_file.read_text(encoding="utf-8"))
            self.assertEqual(status, 0)
            self.assertEqual(calls, ["长安二十四计", "The Vendetta of An"])
            self.assertEqual(payload["items"][0]["recommended_candidate"]["search_keyword"], "The Vendetta of An")

    def test_cli_share_search_reports_keyword_timeout_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            plan_file = tmp_path / "plan.json"
            output_file = tmp_path / "share-search.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=secret\n", encoding="utf-8")
            plan_file.write_text(
                json.dumps(
                    {
                        "mode": "readonly-mv3-transfer-plan",
                        "items": [
                            {
                                "title": "东宫",
                                "tmdbid": 86857,
                                "season": 1,
                                "size_bytes": int(80 * 1024**3),
                                "expected_count": 55,
                                "search_keywords": ["东宫"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_search(_base_url, _token, keyword, channels=None, timeout=60):
                return {
                    "ok": False,
                    "status": 0,
                    "error_type": "TimeoutError",
                    "error": "timed out",
                    "result_count": 0,
                    "items": [],
                    "warnings": ["mv3_resource_search_request_failed"],
                }

            with patch("series_cloud_archiver.cli.search_mv3_resources", side_effect=fake_search):
                status = main(
                    [
                        "plan-mv3-share-search",
                        "--env-file",
                        str(env_file),
                        "--transfer-plan",
                        str(plan_file),
                        "--limit",
                        "1",
                        "--format",
                        "json",
                        "--output",
                        str(output_file),
                    ]
                )

            payload = json.loads(output_file.read_text(encoding="utf-8"))
            item = payload["items"][0]
            self.assertEqual(status, 0)
            self.assertEqual(payload["ready_items"], 0)
            self.assertEqual(item["keyword_reports"][0]["error_type"], "TimeoutError")
            self.assertEqual(item["search_errors"][0]["keyword"], "东宫")
            self.assertIn("keyword_error:东宫:TimeoutError", item["warnings"])

    def test_cli_share_search_retries_timeout_with_fallback_channel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            plan_file = tmp_path / "plan.json"
            output_file = tmp_path / "share-search.json"
            env_file.write_text("MV3_BASE_URL=http://mv3.example\nMV3_API_TOKEN=secret\n", encoding="utf-8")
            plan_file.write_text(
                json.dumps(
                    {
                        "mode": "readonly-mv3-transfer-plan",
                        "items": [
                            {
                                "title": "东宫",
                                "tmdbid": 86857,
                                "season": 1,
                                "size_bytes": int(80 * 1024**3),
                                "expected_count": 55,
                                "search_keywords": ["东宫"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            calls = []

            def fake_search(_base_url, _token, keyword, channels=None, timeout=60):
                calls.append((keyword, tuple(channels or [])))
                if not channels:
                    return {
                        "ok": False,
                        "status": 0,
                        "error_type": "TimeoutError",
                        "error": "timed out",
                        "result_count": 0,
                        "items": [],
                        "warnings": ["mv3_resource_search_request_failed"],
                    }
                return {
                    "ok": True,
                    "status": 200,
                    "result_count": 1,
                    "items": [
                        {
                            "index": 1,
                            "title": "东宫 S01E01-E55 完结 80GB",
                            "size": "80GB",
                            "channel": "pansou",
                            "share_code_available": True,
                        }
                    ],
                    "warnings": [],
                }

            with patch("series_cloud_archiver.cli.search_mv3_resources", side_effect=fake_search):
                status = main(
                    [
                        "plan-mv3-share-search",
                        "--env-file",
                        str(env_file),
                        "--transfer-plan",
                        str(plan_file),
                        "--limit",
                        "1",
                        "--format",
                        "json",
                        "--output",
                        str(output_file),
                    ]
                )

            payload = json.loads(output_file.read_text(encoding="utf-8"))
            item = payload["items"][0]
            self.assertEqual(status, 0)
            self.assertEqual(calls, [("东宫", ()), ("东宫", ("pansou",))])
            self.assertEqual(item["keyword_reports"][1]["channels"], ["pansou"])
            self.assertTrue(item["keyword_reports"][1]["fallback"])
            self.assertEqual(item["recommended_candidate"]["channel"], "pansou")
            self.assertIn("keyword_fallback:东宫:pansou", item["warnings"])

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
