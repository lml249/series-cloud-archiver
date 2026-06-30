from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .batch_preview import (
    build_batch_share_preview_plan,
    build_batch_share_receive_plan,
    render_batch_share_preview_report,
    render_batch_share_receive_plan,
)
from .batch_pipeline import render_batch_pipeline_report, run_batch_pipeline
from .batch_runner import (
    build_batch_review_report,
    build_batch_finalize_plan,
    build_batch_plan,
    render_batch_review_report,
    render_batch_finalize_plan,
    render_batch_finalize_run,
    render_batch_plan,
    run_batch_finalize,
)
from .batch_transfer import render_batch_transfer_run, run_batch_transfer
from .cloud_check import cloud_check_from_scan_report, load_scan_report, render_cloud_check_report
from .cloud_cleanup import (
    execute_cloud_complete_cleanup_plan,
    plan_cloud_complete_cleanup,
    render_cloud_complete_cleanup_execute,
    render_cloud_complete_cleanup_plan,
)
from .cleanup_verify import (
    audit_strm_nfo_language,
    cleanup_duplicate_strm_root,
    render_duplicate_strm_cleanup,
    render_strm_target_rewrite,
    render_mp_cleanup_verification,
    render_strm_nfo_language_audit,
    render_strm_verification,
    rewrite_strm_targets,
    verify_mp_cleanup_from_services,
    verify_strm_paths,
)
from .config import config_from_env, db_path_from_env
from .dotqb_cleanup import cleanup_orphan_dotqb_roots, render_dotqb_orphan_cleanup
from .emby import (
    cancel_emby_running_task,
    delete_stale_emby_paths,
    inspect_emby_task_status,
    notify_and_verify_emby_media_updated,
    refresh_and_verify_emby_item,
    refresh_and_verify_emby_library,
    render_emby_delete_stale_paths_report,
    render_emby_item_refresh_report,
    render_emby_media_updated_report,
    render_emby_refresh_verify_report,
    render_emby_task_cancel_report,
    render_emby_task_status_report,
    render_emby_task_wait_verify_report,
    wait_for_emby_task_and_verify_paths,
)
from .hlink_cleanup import (
    cleanup_empty_hlink_root,
    execute_cloud_hlink_orphan_multiseason_cleanup,
    execute_cloud_hlink_orphan_cleanup,
    execute_cloud_hlink_cleanup,
    execute_cloud_source_orphan_cleanup,
    preview_cloud_hlink_orphan_multiseason_cleanup,
    preview_cloud_hlink_orphan_cleanup,
    preview_cloud_hlink_cleanup,
    preview_cloud_source_orphan_cleanup,
    render_cloud_hlink_cleanup,
)
from .identity import (
    render_identity_overrides,
    resolve_identity_overrides_from_cloud_report,
    resolve_identity_overrides_from_scan_report,
)
from .extra_source_media import build_extra_source_media_plan, render_extra_source_media_plan
from .moviepilot import (
    execute_mp_cleanup_from_preview_report,
    render_mp_cleanup_execute_report,
    mp_cleanup_preview_from_transfer_history,
    render_mp_cleanup_preview,
    render_mp_scrape_strm_report,
    scrape_mp_strm_path,
)
from .mv3 import (
    add_mv3_offline_task,
    batch_verify_mv3_cloud_media_sidecars,
    browse_mv3_cloud_folder,
    cleanup_mv3_cloud_duplicate_videos,
    cleanup_mv3_cloud_media_sidecars,
    ensure_mv3_115_path,
    check_mv3_offline_task,
    check_mv3_offline_manifest_status,
    execute_mv3_organize_transfer_from_browse_report,
    execute_mv3_organize_transfer_from_confirmed_local_map,
    execute_mv3_organize_transfer_from_scan_report,
    generate_mv3_strm,
    inspect_mv3_capabilities,
    inspect_mv3_instances,
    index_mv3_cloud_root_for_transfer_plan,
    list_mv3_strm_records,
    materialize_mv3_strm_records,
    normalize_mv3_received_season_folder,
    probe_mv3,
    redirect_mv3_strm_records,
    regenerate_mv3_strm_records,
    render_mv3_capabilities_report,
    render_mv3_cloud_browse_report,
    render_mv3_cloud_duplicate_video_cleanup_report,
    render_mv3_cloud_index_plan_report,
    render_mv3_cloud_media_sidecar_batch_verify_report,
    render_mv3_cloud_media_sidecar_cleanup_report,
    render_mv3_cloud_media_sidecar_verify_report,
    render_mv3_cloud_search_plan_report,
    render_mv3_cloud_search_report,
    render_mv3_ensure_path_report,
    render_mv3_instances_report,
    render_mv3_offline_add_report,
    render_mv3_offline_manifest_status_report,
    render_mv3_offline_status_report,
    render_mv3_organize_transfer_report,
    render_mv3_organize_scan_report,
    render_mv3_probe_report,
    render_mv3_received_season_normalize_report,
    render_mv3_resource_search_report,
    render_mv3_share_receive_report,
    render_mv3_share_preview_report,
    render_mv3_strm_generate_report,
    render_mv3_strm_records_materialize_report,
    render_mv3_strm_records_redirect_report,
    render_mv3_strm_records_report,
    render_mv3_strm_records_regenerate_report,
    render_mv3_wrong_root_direct_season_pair_repair_report,
    render_mv3_wrong_root_repair_report,
    preview_mv3_share,
    receive_mv3_share,
    repair_mv3_wrong_root_direct_season_pair,
    repair_mv3_wrong_root,
    scan_mv3_organize_source,
    search_mv3_cloud_files_for_transfer_plan,
    search_mv3_resources,
    search_mv3_cloud_files,
    verify_mv3_cloud_media_sidecars,
)
from .orchestrator import evaluate, list_status, plan_cleanup, status_detail
from .qb_orphan_cleanup import (
    execute_qb_orphan_torrent_cleanup,
    preview_qb_orphan_torrent_cleanup,
    render_qb_orphan_torrent_cleanup,
)
from .qbittorrent import audit_dotqb_files, fetch_qb_torrents, render_dotqb_audit_report
from .reporting import render_report
from .scanner import scan
from .storage import StoredSeries
from .transfer_plan import (
    DEFAULT_CLOUD_ROOT,
    DEFAULT_STRM_ROOT,
    load_cloud_check_report,
    load_mv3_transfer_plan,
    load_optional_json_report,
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
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="series-cloud-archiver")
    subcommands = parser.add_subparsers(dest="command", required=True)

    scan_parser = subcommands.add_parser("scan", help="Run readonly candidate scan")
    scan_parser.add_argument("--env-file", default=None, help="Local env file; never commit real values")
    scan_parser.add_argument("--media-root", action="append", default=[], help="Media root to scan; can be repeated")
    scan_parser.add_argument("--format", choices=["markdown", "json"], default=None)
    scan_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")
    scan_parser.add_argument("--top", type=int, default=None, help="Maximum rows in report")
    scan_parser.add_argument("--min-age-days", type=int, default=None, help="Ignore folders modified more recently than this")
    scan_parser.add_argument("--min-seed-days", type=int, default=None, help="Minimum qBittorrent seed age for candidate status")
    scan_parser.add_argument("--max-depth", type=int, default=None, help="Maximum scan depth under each series folder")
    scan_parser.add_argument("--no-qb", action="store_true", help="Skip qBittorrent evidence")
    scan_parser.add_argument("--no-mp", action="store_true", help="Skip MoviePilot subscription evidence")
    scan_parser.add_argument("--emby", action="store_true", help="Use Emby evidence when configured")

    eval_parser = subcommands.add_parser("evaluate", help="Scan and store readonly state in SQLite")
    add_scan_args(eval_parser)
    eval_parser.add_argument("--db", default=None, help="SQLite state database path")

    status_parser = subcommands.add_parser("status", help="List stored series states")
    status_parser.add_argument("--env-file", default=None)
    status_parser.add_argument("--db", default=None)
    status_parser.add_argument("--limit", type=int, default=50)
    status_parser.add_argument("--status", default=None)
    status_parser.add_argument("--query", default=None, help="Show detail for one title or path")
    status_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")

    cleanup_parser = subcommands.add_parser("plan-cleanup", help="Create a blocked dry-run cleanup plan")
    cleanup_parser.add_argument("query", help="Series title or path")
    cleanup_parser.add_argument("--env-file", default=None)
    cleanup_parser.add_argument("--db", default=None)
    cleanup_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")

    dotqb_parser = subcommands.add_parser("qb-dotqb-audit", help="Readonly audit of qB .!qB temporary files and missingFiles state")
    dotqb_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    dotqb_parser.add_argument("--scan-root", action="append", default=[], help="Host filesystem root to scan; can be repeated")
    dotqb_parser.add_argument("--path-alias", action="append", default=[], help="Map qB/container path to host path, e.g. /media-qb=/media-host")
    dotqb_parser.add_argument("--timeout", type=int, default=30, help="Per-request timeout in seconds")
    dotqb_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    dotqb_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    dotqb_cleanup_parser = subcommands.add_parser("dotqb-orphan-cleanup", help="Delete approved orphan .!qB files after MP/qB/STRM/hlink gates pass")
    dotqb_cleanup_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    dotqb_cleanup_parser.add_argument("--title", required=True, help="MoviePilot transfer history title to confirm is gone")
    dotqb_cleanup_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Expected TMDB ID")
    dotqb_cleanup_parser.add_argument("--expected-hash-prefix", action="append", required=True, help="Expected qB hash prefix that must be absent; can be repeated or comma-separated")
    dotqb_cleanup_parser.add_argument("--source-root", action="append", required=True, help="Explicit source root containing only orphan .!qB files; can be repeated")
    dotqb_cleanup_parser.add_argument("--destination-root", action="append", required=True, help="hlink/destination root that must already be gone; can be repeated")
    dotqb_cleanup_parser.add_argument("--strm-root", action="append", required=True, help="STRM root that must remain complete; can be repeated")
    dotqb_cleanup_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct STRM episode count")
    dotqb_cleanup_parser.add_argument("--expected-episode-min", type=int, required=True, help="Expected first STRM episode number")
    dotqb_cleanup_parser.add_argument("--expected-episode-max", type=int, required=True, help="Expected last STRM episode number")
    dotqb_cleanup_parser.add_argument("--dotqb-suffix", default=".!qB", help="qB temporary suffix")
    dotqb_cleanup_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    dotqb_cleanup_parser.add_argument("--approve-delete", action="store_true", help="Required: actually delete orphan .!qB files")
    dotqb_cleanup_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    dotqb_cleanup_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    qb_orphan_preview_parser = subcommands.add_parser("qb-orphan-torrent-cleanup-preview", help="Readonly preview for deleting qB tasks whose source/hlink files are already gone but STRM is complete")
    qb_orphan_preview_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    qb_orphan_preview_parser.add_argument("--title", required=True, help="Series title for reporting and MP absence check")
    qb_orphan_preview_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Expected TMDB ID")
    qb_orphan_preview_parser.add_argument("--expected-qb-hash", action="append", required=True, help="Expected full qB hash; can be repeated or comma-separated")
    qb_orphan_preview_parser.add_argument("--source-root", action="append", required=True, help="Explicit source root that must be missing or contain no videos; can be repeated")
    qb_orphan_preview_parser.add_argument("--hlink-root", action="append", required=True, help="Explicit hlink root that must be missing or contain no videos; can be repeated")
    qb_orphan_preview_parser.add_argument("--strm-root", action="append", required=True, help="STRM root that must remain complete; can be repeated")
    qb_orphan_preview_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct STRM episode count")
    qb_orphan_preview_parser.add_argument("--expected-episode-min", type=int, required=True, help="Expected first STRM episode number")
    qb_orphan_preview_parser.add_argument("--expected-episode-max", type=int, required=True, help="Expected last STRM episode number")
    qb_orphan_preview_parser.add_argument("--expected-title-contains", default="", help="Safety check: qB name/path must contain this text; defaults to title")
    qb_orphan_preview_parser.add_argument("--min-seed-days", type=int, default=7, help="Minimum qB seed days")
    qb_orphan_preview_parser.add_argument("--required-target-prefix", default="", help="Every STRM target must start with this prefix")
    qb_orphan_preview_parser.add_argument("--forbidden-target-prefix", action="append", default=[], help="STRM targets must not start with this prefix; can be repeated")
    qb_orphan_preview_parser.add_argument("--cloud-media-path", default="", help="Optional MV3 cloud media path that must not contain NFO/JPG/PNG/WEBP before cleanup")
    qb_orphan_preview_parser.add_argument("--cloud-media-folder-id", default="", help="Optional MV3 cloud media folder id that must not contain NFO/JPG/PNG/WEBP before cleanup")
    qb_orphan_preview_parser.add_argument("--cloud-media-storage", default="115-default", help="MV3 cloud storage slug for cloud media sidecar verification")
    qb_orphan_preview_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    qb_orphan_preview_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    qb_orphan_preview_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    qb_orphan_exec_parser = subcommands.add_parser("qb-orphan-torrent-cleanup-execute", help="Execute approved qB task-only cleanup from a validated orphan preview")
    qb_orphan_exec_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    qb_orphan_exec_parser.add_argument("--preview-report", required=True, help="JSON report from qb-orphan-torrent-cleanup-preview")
    qb_orphan_exec_parser.add_argument("--expected-title", required=True, help="Safety check: title must exactly match preview")
    qb_orphan_exec_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Safety check: expected TMDB ID")
    qb_orphan_exec_parser.add_argument("--expected-qb-hash", action="append", required=True, help="Expected full qB hash from preview; can be repeated or comma-separated")
    qb_orphan_exec_parser.add_argument("--expected-source-root", action="append", required=True, help="Safety check: source roots must exactly match preview; can be repeated")
    qb_orphan_exec_parser.add_argument("--expected-hlink-root", action="append", required=True, help="Safety check: hlink roots must exactly match preview; can be repeated")
    qb_orphan_exec_parser.add_argument("--expected-strm-root", action="append", required=True, help="Safety check: STRM roots must exactly match preview; can be repeated")
    qb_orphan_exec_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    qb_orphan_exec_parser.add_argument("--approve-delete", action="store_true", help="Required: actually remove qB tasks with deleteFiles=false")
    qb_orphan_exec_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    qb_orphan_exec_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    mp_cleanup_parser = subcommands.add_parser("mp-cleanup-preview", help="Readonly MoviePilot cleanup preview from transfer history")
    mp_cleanup_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    mp_cleanup_parser.add_argument("--title", required=True, help="MoviePilot transfer history title to query")
    mp_cleanup_parser.add_argument("--expected-title", default="", help="Safety filter: exact MP title expected")
    mp_cleanup_parser.add_argument("--expected-tmdbid", type=int, default=0, help="Safety filter: expected TMDB ID when present in MP")
    mp_cleanup_parser.add_argument("--expected-hash-prefix", default="", help="Safety filter: expected qB hash prefix")
    mp_cleanup_parser.add_argument("--expected-season", type=int, default=0, help="Safety filter: expected season number, e.g. 3 for S03")
    mp_cleanup_parser.add_argument("--keep-source", action="store_true", help="Preview without deletesrc=true")
    mp_cleanup_parser.add_argument("--keep-dest", action="store_true", help="Preview without deletedest=true")
    mp_cleanup_parser.add_argument("--record-only", action="store_true", help="Preview MP transfer-history record deletion only; requires --keep-source and --keep-dest")
    mp_cleanup_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    mp_cleanup_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    mp_cleanup_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    mp_scrape_strm_parser = subcommands.add_parser("mp-scrape-strm", help="Scrape metadata with MoviePilot for a STRM-side path only")
    mp_scrape_strm_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    mp_scrape_strm_parser.add_argument("--strm-path", required=True, help="Host/DSM STRM-side path for audit and reporting")
    mp_scrape_strm_parser.add_argument("--mp-path", default="", help="MoviePilot container path; defaults to --strm-path")
    mp_scrape_strm_parser.add_argument("--storage", default="local", help="MoviePilot storage slug, usually local")
    mp_scrape_strm_parser.add_argument("--type", choices=["dir", "file"], default="dir", help="MoviePilot FileItem type")
    mp_scrape_strm_parser.add_argument("--timeout", type=int, default=120, help="Per-request timeout in seconds")
    mp_scrape_strm_parser.add_argument("--approve-scrape", action="store_true", help="Required: actually send MoviePilot scrape request")
    mp_scrape_strm_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    mp_scrape_strm_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    mp_cleanup_exec_parser = subcommands.add_parser("mp-cleanup-execute", help="Execute approved MoviePilot cleanup from a validated preview report")
    mp_cleanup_exec_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    mp_cleanup_exec_parser.add_argument("--preview-report", required=True, help="JSON report from mp-cleanup-preview")
    mp_cleanup_exec_parser.add_argument("--expected-title", required=True, help="Safety check: exact title expected")
    mp_cleanup_exec_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Safety check: expected TMDB ID")
    mp_cleanup_exec_parser.add_argument("--expected-hash-prefix", action="append", required=True, help="Safety check: expected qB hash prefix; can be repeated or comma-separated")
    mp_cleanup_exec_parser.add_argument("--expected-season", type=int, default=0, help="Safety check: expected season number, e.g. 3 for S03")
    mp_cleanup_exec_parser.add_argument("--expected-record-count", type=int, required=True, help="Safety check: exact MP history record count")
    mp_cleanup_exec_parser.add_argument("--expected-episode-count", type=int, required=True, help="Safety check: exact episode count")
    mp_cleanup_exec_parser.add_argument("--expected-episode-min", type=int, required=True, help="Safety check: first episode number")
    mp_cleanup_exec_parser.add_argument("--expected-episode-max", type=int, required=True, help="Safety check: last episode number")
    mp_cleanup_exec_parser.add_argument(
        "--expected-episodes",
        type=_parse_episode_list,
        default=[],
        help="Optional exact episode list for non-contiguous cleanup, e.g. 1,3,21 or 1-4,7",
    )
    mp_cleanup_exec_parser.add_argument("--keep-source", action="store_true", help="Execute without deletesrc=true")
    mp_cleanup_exec_parser.add_argument("--keep-dest", action="store_true", help="Execute without deletedest=true")
    mp_cleanup_exec_parser.add_argument("--record-only", action="store_true", help="Delete only MP transfer-history records; requires --keep-source and --keep-dest")
    mp_cleanup_exec_parser.add_argument("--continue-on-error", action="store_true", help="Continue deleting remaining MP records if one record fails")
    mp_cleanup_exec_parser.add_argument("--allow-multiple-hashes", action="store_true", help="Allow preview warning multiple_download_hashes when all other episode/title/TMDB gates pass")
    mp_cleanup_exec_parser.add_argument("--allow-multiple-source-roots", action="store_true", help="Allow preview warning multiple_source_roots when destination root is unique and all other gates pass")
    mp_cleanup_exec_parser.add_argument("--allow-duplicate-episodes", action="store_true", help="Allow duplicate MP records for the same episode, for explicitly verified duplicate release cleanup")
    mp_cleanup_exec_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    mp_cleanup_exec_parser.add_argument("--approve-mp-cleanup", action="store_true", help="Required: actually send MoviePilot DELETE requests")
    mp_cleanup_exec_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    mp_cleanup_exec_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    mp_cleanup_verify_parser = subcommands.add_parser("mp-cleanup-verify", help="Readonly post-cleanup verification for MP/qB/filesystem/STRM")
    mp_cleanup_verify_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    mp_cleanup_verify_parser.add_argument("--title", required=True, help="MoviePilot transfer history title to query")
    mp_cleanup_verify_parser.add_argument("--expected-title", default="", help="Safety filter: exact MP title expected")
    mp_cleanup_verify_parser.add_argument("--expected-tmdbid", type=int, default=0, help="Safety filter: expected TMDB ID when present in MP")
    mp_cleanup_verify_parser.add_argument("--expected-hash-prefix", action="append", default=[], help="Safety filter: qB hash prefix that should be gone; can be repeated or comma-separated")
    mp_cleanup_verify_parser.add_argument("--expected-season", type=int, default=0, help="Safety filter: expected season number, e.g. 3 for S03")
    mp_cleanup_verify_parser.add_argument("--source-root", action="append", default=[], help="Local source root that should no longer exist; can be repeated")
    mp_cleanup_verify_parser.add_argument("--destination-root", action="append", default=[], help="hlink/destination root that should no longer exist; can be repeated")
    mp_cleanup_verify_parser.add_argument("--strm-root", action="append", default=[], help="STRM root that should contain complete episodes; can be repeated")
    mp_cleanup_verify_parser.add_argument("--expected-episode-count", type=int, default=0, help="Expected distinct STRM episode count")
    mp_cleanup_verify_parser.add_argument("--expected-episode-min", type=int, default=0, help="Expected first STRM episode number")
    mp_cleanup_verify_parser.add_argument("--expected-episode-max", type=int, default=0, help="Expected last STRM episode number")
    mp_cleanup_verify_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    mp_cleanup_verify_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    mp_cleanup_verify_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    cloud_cleanup_plan_parser = subcommands.add_parser("plan-cloud-complete-cleanup", help="Build a readonly MP cleanup plan for candidates whose cloud STRM is already complete")
    cloud_cleanup_plan_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    cloud_cleanup_plan_parser.add_argument("--cloud-report", required=True, help="JSON report from cloud-check")
    cloud_cleanup_plan_parser.add_argument("--limit", type=int, default=0, help="Maximum cloud_strm_complete items to plan")
    cloud_cleanup_plan_parser.add_argument("--title", action="append", default=[], help="Only include an exact title; can be repeated")
    cloud_cleanup_plan_parser.add_argument("--required-target-prefix", default="", help="Every STRM target must resolve under this prefix")
    cloud_cleanup_plan_parser.add_argument("--forbidden-target-prefix", action="append", default=[], help="STRM targets must not resolve under this prefix; can be repeated")
    cloud_cleanup_plan_parser.add_argument("--allow-multiple-hashes", action="store_true", help="Allow one season assembled from multiple qB hashes when destination root and episode gates pass")
    cloud_cleanup_plan_parser.add_argument("--allow-multiple-source-roots", action="store_true", help="Allow one season assembled from multiple source roots when destination root and episode gates pass")
    cloud_cleanup_plan_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    cloud_cleanup_plan_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    cloud_cleanup_plan_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    cloud_cleanup_exec_parser = subcommands.add_parser("cloud-complete-cleanup-execute", help="Execute approved MP cleanup from a cloud-complete cleanup plan")
    cloud_cleanup_exec_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    cloud_cleanup_exec_parser.add_argument("--plan", required=True, help="JSON report from plan-cloud-complete-cleanup")
    cloud_cleanup_exec_parser.add_argument("--limit", type=int, default=0, help="Maximum ready items to execute")
    cloud_cleanup_exec_parser.add_argument("--title", action="append", default=[], help="Only execute an exact title; can be repeated")
    cloud_cleanup_exec_parser.add_argument("--continue-on-error", action="store_true", help="Continue after a failed item")
    cloud_cleanup_exec_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    cloud_cleanup_exec_parser.add_argument("--approve-mp-cleanup", action="store_true", help="Required: actually send MoviePilot DELETE requests")
    cloud_cleanup_exec_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    cloud_cleanup_exec_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    hlink_cleanup_preview_parser = subcommands.add_parser("cloud-hlink-cleanup-preview", help="Readonly cleanup preview when cloud STRM is complete but MP history is missing")
    hlink_cleanup_preview_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    hlink_cleanup_preview_parser.add_argument("--title", required=True, help="Series title for reporting")
    hlink_cleanup_preview_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Expected TMDB ID")
    hlink_cleanup_preview_parser.add_argument("--hlink-root", required=True, help="Explicit hlink root to remove after qB source cleanup")
    hlink_cleanup_preview_parser.add_argument("--strm-root", required=True, help="STRM season root that must be complete")
    hlink_cleanup_preview_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct STRM episode count")
    hlink_cleanup_preview_parser.add_argument("--expected-episode-min", type=int, required=True, help="Expected first STRM episode number")
    hlink_cleanup_preview_parser.add_argument("--expected-episode-max", type=int, required=True, help="Expected last STRM episode number")
    hlink_cleanup_preview_parser.add_argument("--min-seed-days", type=int, default=7, help="Minimum qB seed days")
    hlink_cleanup_preview_parser.add_argument("--required-target-prefix", default="", help="Every STRM target must start with this prefix")
    hlink_cleanup_preview_parser.add_argument("--forbidden-target-prefix", action="append", default=[], help="STRM targets must not start with this prefix; can be repeated")
    hlink_cleanup_preview_parser.add_argument("--cloud-media-path", default="", help="MV3 cloud media path that must not contain NFO/JPG/PNG/WEBP before cleanup")
    hlink_cleanup_preview_parser.add_argument("--cloud-media-folder-id", default="", help="MV3 cloud media folder id that must not contain NFO/JPG/PNG/WEBP before cleanup")
    hlink_cleanup_preview_parser.add_argument("--cloud-media-storage", default="115-default", help="MV3 cloud storage slug for cloud media sidecar verification")
    hlink_cleanup_preview_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    hlink_cleanup_preview_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    hlink_cleanup_exec_parser = subcommands.add_parser("cloud-hlink-cleanup-execute", help="Execute approved qB+hlink cleanup from a validated cloud-hlink preview")
    hlink_cleanup_exec_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    hlink_cleanup_exec_parser.add_argument("--preview-report", required=True, help="JSON report from cloud-hlink-cleanup-preview")
    hlink_cleanup_exec_parser.add_argument("--expected-title", required=True, help="Safety check: title must exactly match preview")
    hlink_cleanup_exec_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Safety check: expected TMDB ID")
    hlink_cleanup_exec_parser.add_argument("--expected-hlink-root", required=True, help="Safety check: hlink root must exactly match preview")
    hlink_cleanup_exec_parser.add_argument("--expected-qb-hash", action="append", required=True, help="Expected full qB hash from preview; can be repeated")
    hlink_cleanup_exec_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    hlink_cleanup_exec_parser.add_argument("--approve-delete", action="store_true", help="Required: actually delete qB torrents/files and the explicit hlink root")
    hlink_cleanup_exec_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    hlink_cleanup_exec_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    hlink_orphan_preview_parser = subcommands.add_parser("cloud-hlink-orphan-cleanup-preview", help="Readonly hlink-only cleanup preview when cloud STRM is complete and qB no longer tracks the files")
    hlink_orphan_preview_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    hlink_orphan_preview_parser.add_argument("--title", required=True, help="Series title for reporting")
    hlink_orphan_preview_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Expected TMDB ID")
    hlink_orphan_preview_parser.add_argument("--hlink-root", required=True, help="Explicit orphan hlink root to remove after checks pass")
    hlink_orphan_preview_parser.add_argument("--strm-root", required=True, help="STRM season root that must be complete")
    hlink_orphan_preview_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct STRM episode count")
    hlink_orphan_preview_parser.add_argument("--expected-episode-min", type=int, required=True, help="Expected first STRM episode number")
    hlink_orphan_preview_parser.add_argument("--expected-episode-max", type=int, required=True, help="Expected last STRM episode number")
    hlink_orphan_preview_parser.add_argument("--required-target-prefix", default="", help="Every STRM target must start with this prefix")
    hlink_orphan_preview_parser.add_argument("--forbidden-target-prefix", action="append", default=[], help="STRM targets must not start with this prefix; can be repeated")
    hlink_orphan_preview_parser.add_argument("--cloud-media-path", default="", help="MV3 cloud media path that must not contain NFO/JPG/PNG/WEBP before cleanup")
    hlink_orphan_preview_parser.add_argument("--cloud-media-folder-id", default="", help="MV3 cloud media folder id that must not contain NFO/JPG/PNG/WEBP before cleanup")
    hlink_orphan_preview_parser.add_argument("--cloud-media-storage", default="115-default", help="MV3 cloud storage slug for cloud media sidecar verification")
    hlink_orphan_preview_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    hlink_orphan_preview_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    hlink_orphan_exec_parser = subcommands.add_parser("cloud-hlink-orphan-cleanup-execute", help="Execute approved hlink-only cleanup from a validated orphan preview")
    hlink_orphan_exec_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    hlink_orphan_exec_parser.add_argument("--preview-report", required=True, help="JSON report from cloud-hlink-orphan-cleanup-preview")
    hlink_orphan_exec_parser.add_argument("--expected-title", required=True, help="Safety check: title must exactly match preview")
    hlink_orphan_exec_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Safety check: expected TMDB ID")
    hlink_orphan_exec_parser.add_argument("--expected-hlink-root", required=True, help="Safety check: hlink root must exactly match preview")
    hlink_orphan_exec_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    hlink_orphan_exec_parser.add_argument("--approve-delete", action="store_true", help="Required: actually delete the explicit orphan hlink root")
    hlink_orphan_exec_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    hlink_orphan_exec_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    hlink_orphan_multi_preview_parser = subcommands.add_parser(
        "cloud-hlink-orphan-multiseason-cleanup-preview",
        help="Readonly hlink-only cleanup preview for a multi-season root when cloud STRM is complete and qB no longer tracks the files",
    )
    hlink_orphan_multi_preview_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    hlink_orphan_multi_preview_parser.add_argument("--title", required=True, help="Series title for reporting")
    hlink_orphan_multi_preview_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Expected TMDB ID")
    hlink_orphan_multi_preview_parser.add_argument("--hlink-root", required=True, help="Explicit orphan hlink root to remove after checks pass")
    hlink_orphan_multi_preview_parser.add_argument(
        "--season",
        action="append",
        type=_parse_hlink_multiseason_spec,
        required=True,
        help="Season spec. Use season:strm_root:count:min:max or season:strm_root:episodes=1,3-13; repeat per season",
    )
    hlink_orphan_multi_preview_parser.add_argument("--required-target-prefix", default="", help="Every STRM target must start with this prefix")
    hlink_orphan_multi_preview_parser.add_argument("--forbidden-target-prefix", action="append", default=[], help="STRM targets must not start with this prefix; can be repeated")
    hlink_orphan_multi_preview_parser.add_argument("--cloud-media-path", default="", help="MV3 cloud media path that must not contain NFO/JPG/PNG/WEBP before cleanup")
    hlink_orphan_multi_preview_parser.add_argument("--cloud-media-folder-id", default="", help="MV3 cloud media folder id that must not contain NFO/JPG/PNG/WEBP before cleanup")
    hlink_orphan_multi_preview_parser.add_argument("--cloud-media-storage", default="115-default", help="MV3 cloud storage slug for cloud media sidecar verification")
    hlink_orphan_multi_preview_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    hlink_orphan_multi_preview_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    hlink_orphan_multi_exec_parser = subcommands.add_parser(
        "cloud-hlink-orphan-multiseason-cleanup-execute",
        help="Execute approved hlink-only cleanup from a validated multi-season orphan preview",
    )
    hlink_orphan_multi_exec_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    hlink_orphan_multi_exec_parser.add_argument("--preview-report", required=True, help="JSON report from cloud-hlink-orphan-multiseason-cleanup-preview")
    hlink_orphan_multi_exec_parser.add_argument("--expected-title", required=True, help="Safety check: title must exactly match preview")
    hlink_orphan_multi_exec_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Safety check: expected TMDB ID")
    hlink_orphan_multi_exec_parser.add_argument("--expected-hlink-root", required=True, help="Safety check: hlink root must exactly match preview")
    hlink_orphan_multi_exec_parser.add_argument("--expected-season", action="append", type=int, required=True, help="Safety check: expected season number; repeat per season")
    hlink_orphan_multi_exec_parser.add_argument("--approve-delete", action="store_true", help="Required: actually delete the explicit orphan hlink root")
    hlink_orphan_multi_exec_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    hlink_orphan_multi_exec_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    source_orphan_preview_parser = subcommands.add_parser("cloud-source-orphan-cleanup-preview", help="Readonly source-only cleanup preview when cloud STRM is complete and qB no longer tracks the files")
    source_orphan_preview_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    source_orphan_preview_parser.add_argument("--title", required=True, help="Series title for reporting")
    source_orphan_preview_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Expected TMDB ID")
    source_orphan_preview_parser.add_argument("--source-root", required=True, help="Explicit orphan source root to remove after checks pass")
    source_orphan_preview_parser.add_argument("--strm-root", required=True, help="STRM season root that must be complete")
    source_orphan_preview_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct source/STRM episode count")
    source_orphan_preview_parser.add_argument("--expected-episode-min", type=int, required=True, help="Expected first episode number")
    source_orphan_preview_parser.add_argument("--expected-episode-max", type=int, required=True, help="Expected last episode number")
    source_orphan_preview_parser.add_argument("--required-target-prefix", default="", help="Every STRM target must start with this prefix")
    source_orphan_preview_parser.add_argument("--forbidden-target-prefix", action="append", default=[], help="STRM targets must not start with this prefix; can be repeated")
    source_orphan_preview_parser.add_argument("--cloud-media-path", default="", help="MV3 cloud media path that must not contain NFO/JPG/PNG/WEBP before cleanup")
    source_orphan_preview_parser.add_argument("--cloud-media-folder-id", default="", help="MV3 cloud media folder id that must not contain NFO/JPG/PNG/WEBP before cleanup")
    source_orphan_preview_parser.add_argument("--cloud-media-storage", default="115-default", help="MV3 cloud storage slug for cloud media sidecar verification")
    source_orphan_preview_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    source_orphan_preview_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    source_orphan_exec_parser = subcommands.add_parser("cloud-source-orphan-cleanup-execute", help="Execute approved source-only cleanup from a validated orphan source preview")
    source_orphan_exec_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    source_orphan_exec_parser.add_argument("--preview-report", required=True, help="JSON report from cloud-source-orphan-cleanup-preview")
    source_orphan_exec_parser.add_argument("--expected-title", required=True, help="Safety check: title must exactly match preview")
    source_orphan_exec_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Safety check: expected TMDB ID")
    source_orphan_exec_parser.add_argument("--expected-source-root", required=True, help="Safety check: source root must exactly match preview")
    source_orphan_exec_parser.add_argument("--approve-delete", action="store_true", help="Required: actually delete the explicit orphan source root")
    source_orphan_exec_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    source_orphan_exec_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    hlink_empty_root_parser = subcommands.add_parser("hlink-empty-root-cleanup", help="Delete one approved hlink root only when it contains no video files")
    hlink_empty_root_parser.add_argument("--title", required=True, help="Series title for reporting")
    hlink_empty_root_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Expected TMDB ID")
    hlink_empty_root_parser.add_argument("--hlink-root", required=True, help="Explicit hlink root to remove after all media files are gone")
    hlink_empty_root_parser.add_argument("--approve-delete", action="store_true", help="Required: actually delete the explicit empty-media hlink root")
    hlink_empty_root_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    hlink_empty_root_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    strm_verify_parser = subcommands.add_parser("strm-verify", help="Readonly STRM episode and target-path verification")
    strm_verify_parser.add_argument("--title", required=True, help="Series title for reporting")
    strm_verify_parser.add_argument("--strm-root", action="append", required=True, help="STRM root to verify; can be repeated")
    strm_verify_parser.add_argument("--expected-episode-count", type=int, default=0, help="Expected distinct STRM episode count")
    strm_verify_parser.add_argument("--expected-episode-min", type=int, default=0, help="Expected first STRM episode number")
    strm_verify_parser.add_argument("--expected-episode-max", type=int, default=0, help="Expected last STRM episode number")
    strm_verify_parser.add_argument("--required-target-prefix", default="", help="Every STRM target must start with this prefix")
    strm_verify_parser.add_argument("--forbidden-target-prefix", action="append", default=[], help="STRM targets must not start with this prefix; can be repeated")
    strm_verify_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    strm_verify_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    strm_nfo_parser = subcommands.add_parser("strm-nfo-language-audit", help="Readonly STRM NFO Chinese-language audit")
    strm_nfo_parser.add_argument("--strm-root", action="append", required=True, help="STRM root to scan; can be repeated")
    strm_nfo_parser.add_argument("--min-chinese-ratio", type=float, default=0.35, help="Minimum Chinese-character ratio for plot text")
    strm_nfo_parser.add_argument("--sample-limit", type=int, default=50, help="Maximum NFO files to inspect per root")
    strm_nfo_parser.add_argument("--expected-nfo-count", type=int, default=0, help="Require at least this many STRM-side NFO files")
    strm_nfo_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    strm_nfo_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    strm_target_rewrite_parser = subcommands.add_parser("strm-target-rewrite", help="Dry-run or rewrite local STRM target paths from one cloud prefix to another")
    strm_target_rewrite_parser.add_argument("--title", required=True, help="Series title for reporting")
    strm_target_rewrite_parser.add_argument("--strm-root", required=True, help="One STRM-side root to rewrite")
    strm_target_rewrite_parser.add_argument("--old-target-prefix", required=True, help="Existing cloud media target prefix inside STRM files")
    strm_target_rewrite_parser.add_argument("--new-target-prefix", required=True, help="Replacement organized cloud media target prefix")
    strm_target_rewrite_parser.add_argument("--expected-episode-count", type=int, default=0, help="Expected distinct STRM episode count")
    strm_target_rewrite_parser.add_argument("--expected-episode-min", type=int, default=0, help="Expected first STRM episode number")
    strm_target_rewrite_parser.add_argument("--expected-episode-max", type=int, default=0, help="Expected last STRM episode number")
    strm_target_rewrite_parser.add_argument("--expected-rewrite-count", type=int, default=0, help="Safety check: expected number of STRM files to rewrite")
    strm_target_rewrite_parser.add_argument("--approve-write", action="store_true", help="Required: actually rewrite STRM file contents")
    strm_target_rewrite_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    strm_target_rewrite_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    strm_duplicate_cleanup_parser = subcommands.add_parser("strm-duplicate-cleanup", help="Delete an approved duplicate STRM root after verification")
    strm_duplicate_cleanup_parser.add_argument("--title", required=True, help="Series title for reporting")
    strm_duplicate_cleanup_parser.add_argument("--correct-root", required=True, help="Verified correct STRM root that must remain complete")
    strm_duplicate_cleanup_parser.add_argument("--duplicate-root", required=True, help="Duplicate STRM root to delete after checks pass")
    strm_duplicate_cleanup_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct STRM episode count")
    strm_duplicate_cleanup_parser.add_argument("--expected-episode-min", type=int, required=True, help="Expected first STRM episode number")
    strm_duplicate_cleanup_parser.add_argument("--expected-episode-max", type=int, required=True, help="Expected last STRM episode number")
    strm_duplicate_cleanup_parser.add_argument("--required-target-prefix", required=True, help="Every STRM target must resolve under this cloud prefix")
    strm_duplicate_cleanup_parser.add_argument("--approve-delete", action="store_true", help="Required: actually delete the duplicate STRM root")
    strm_duplicate_cleanup_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    strm_duplicate_cleanup_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    emby_refresh_parser = subcommands.add_parser("emby-refresh-verify", help="Trigger an approved Emby full-library refresh and verify stale local paths are gone")
    emby_refresh_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    emby_refresh_parser.add_argument("--title", required=True, help="Series title for reporting and API fallback search")
    emby_refresh_parser.add_argument("--stale-path-prefix", action="append", default=[], help="Old local/hlink path prefix that should disappear; can be repeated")
    emby_refresh_parser.add_argument("--strm-path-prefix", action="append", default=[], help="STRM path prefix that should remain; can be repeated")
    emby_refresh_parser.add_argument("--expected-strm-records", type=int, default=0, help="Expected Emby records under STRM path, including series/season/episode rows when using library DB")
    emby_refresh_parser.add_argument("--expected-episode-count", type=int, default=0, help="Expected distinct STRM episode count")
    emby_refresh_parser.add_argument("--expected-episode-min", type=int, default=0, help="Expected first STRM episode number")
    emby_refresh_parser.add_argument("--expected-episode-max", type=int, default=0, help="Expected last STRM episode number")
    emby_refresh_parser.add_argument("--library-db", default="", help="Optional Emby library.db path for exact readonly verification")
    emby_refresh_parser.add_argument("--skip-refresh", action="store_true", help="Only verify current Emby state without triggering a new scan")
    emby_refresh_parser.add_argument("--approve-full-library-refresh", action="store_true", help="Required: actually trigger Emby full-library RefreshLibrary; prefer emby-media-updated for STRM-side migrations")
    emby_refresh_parser.add_argument("--no-wait", action="store_true", help="Trigger Emby refresh but do not wait for the full library scan to finish")
    emby_refresh_parser.add_argument("--poll-seconds", type=float, default=10.0, help="Seconds between refresh task polls")
    emby_refresh_parser.add_argument("--max-wait-seconds", type=int, default=900, help="Maximum seconds to wait for Emby scan completion")
    emby_refresh_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    emby_refresh_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    emby_refresh_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    emby_media_updated_parser = subcommands.add_parser("emby-media-updated", help="Notify Emby about specific updated media paths and verify STRM state")
    emby_media_updated_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    emby_media_updated_parser.add_argument("--title", required=True, help="Series title for reporting and API fallback search")
    emby_media_updated_parser.add_argument("--updated-path", action="append", required=True, help="Emby/container path to report as updated; can be repeated")
    emby_media_updated_parser.add_argument("--update-type", default="Created", help="Emby update type, usually Created, Modified, or Deleted")
    emby_media_updated_parser.add_argument("--stale-path-prefix", action="append", default=[], help="Old local/hlink path prefix that should disappear; can be repeated")
    emby_media_updated_parser.add_argument("--strm-path-prefix", action="append", default=[], help="STRM path prefix that should remain; can be repeated")
    emby_media_updated_parser.add_argument("--expected-strm-records", type=int, default=0, help="Expected Emby records under STRM path, including series/season/episode rows when using library DB")
    emby_media_updated_parser.add_argument("--expected-episode-count", type=int, default=0, help="Expected distinct STRM episode count")
    emby_media_updated_parser.add_argument("--expected-episode-min", type=int, default=0, help="Expected first STRM episode number")
    emby_media_updated_parser.add_argument("--expected-episode-max", type=int, default=0, help="Expected last STRM episode number")
    emby_media_updated_parser.add_argument("--library-db", default="", help="Optional Emby library.db path for exact readonly verification")
    emby_media_updated_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    emby_media_updated_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    emby_media_updated_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    emby_item_refresh_parser = subcommands.add_parser("emby-item-refresh-verify", help="Refresh one Emby item recursively and verify STRM state")
    emby_item_refresh_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    emby_item_refresh_parser.add_argument("--title", required=True, help="Series title for reporting and API fallback search")
    emby_item_refresh_parser.add_argument("--item-id", required=True, help="Emby item id to refresh, e.g. a library or series item")
    emby_item_refresh_parser.add_argument("--stale-path-prefix", action="append", default=[], help="Old local/hlink path prefix that should disappear; can be repeated")
    emby_item_refresh_parser.add_argument("--strm-path-prefix", action="append", default=[], help="STRM path prefix that should remain; can be repeated")
    emby_item_refresh_parser.add_argument("--expected-strm-records", type=int, default=0, help="Expected Emby records under STRM path, including series/season/episode rows when using library DB")
    emby_item_refresh_parser.add_argument("--expected-episode-count", type=int, default=0, help="Expected distinct STRM episode count")
    emby_item_refresh_parser.add_argument("--expected-episode-min", type=int, default=0, help="Expected first STRM episode number")
    emby_item_refresh_parser.add_argument("--expected-episode-max", type=int, default=0, help="Expected last STRM episode number")
    emby_item_refresh_parser.add_argument("--library-db", default="", help="Optional Emby library.db path for exact readonly verification")
    emby_item_refresh_parser.add_argument("--metadata-refresh-mode", default="Default", help="Emby metadata refresh mode")
    emby_item_refresh_parser.add_argument("--image-refresh-mode", default="Default", help="Emby image refresh mode")
    emby_item_refresh_parser.add_argument("--not-recursive", action="store_true", help="Refresh only the item itself instead of recursively")
    emby_item_refresh_parser.add_argument("--replace-all-metadata", action="store_true", help="Ask Emby to replace all metadata during refresh")
    emby_item_refresh_parser.add_argument("--replace-all-images", action="store_true", help="Ask Emby to replace all images during refresh")
    emby_item_refresh_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    emby_item_refresh_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    emby_item_refresh_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    emby_delete_parser = subcommands.add_parser("emby-delete-stale-paths", help="Delete approved stale Emby root items after STRM replacement verifies")
    emby_delete_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    emby_delete_parser.add_argument("--title", required=True, help="Series title for reporting")
    emby_delete_parser.add_argument("--stale-path-prefix", action="append", required=True, help="Old Emby/container path prefix that should be removed; can be repeated")
    emby_delete_parser.add_argument("--stale-host-prefix", required=True, help="Host path for the same stale root; must no longer exist. Comma-separated when multiple stale prefixes are used")
    emby_delete_parser.add_argument("--strm-path-prefix", action="append", required=True, help="Replacement STRM Emby/container path prefix; can be repeated")
    emby_delete_parser.add_argument("--delete-scope", choices=["root", "season"], default="root", help="Delete a stale series root or one stale season item")
    emby_delete_parser.add_argument("--allow-season-duplicate-replacement", action="store_true", help="Allow deleting a missing stale local season before Emby has indexed the STRM season, only when STRM filesystem verification passes")
    emby_delete_parser.add_argument("--strm-filesystem-root", action="append", default=[], help="Host filesystem STRM season root used to verify duplicate-season replacement; can be repeated")
    emby_delete_parser.add_argument("--required-target-prefix", default="", help="Every STRM target in --strm-filesystem-root must start with this prefix when duplicate-season replacement is allowed")
    emby_delete_parser.add_argument("--forbidden-target-prefix", action="append", default=[], help="STRM targets in --strm-filesystem-root must not start with this prefix; can be repeated")
    emby_delete_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct STRM episode count")
    emby_delete_parser.add_argument("--expected-episode-min", type=int, required=True, help="Expected first STRM episode number")
    emby_delete_parser.add_argument("--expected-episode-max", type=int, required=True, help="Expected last STRM episode number")
    emby_delete_parser.add_argument("--library-db", default="", help="Optional Emby library.db path for exact readonly precheck")
    emby_delete_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    emby_delete_parser.add_argument("--approve-delete", action="store_true", help="Required: actually call Emby delete for stale root item ids")
    emby_delete_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    emby_delete_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    emby_task_status_parser = subcommands.add_parser("emby-task-status", help="Readonly Emby scheduled task status")
    emby_task_status_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    emby_task_status_parser.add_argument("--task-key", default="RefreshLibrary", help="Emby scheduled task key")
    emby_task_status_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    emby_task_status_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    emby_task_status_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    emby_task_wait_parser = subcommands.add_parser("emby-task-wait-verify", help="Wait for an Emby task to finish and verify STRM/stale paths")
    emby_task_wait_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    emby_task_wait_parser.add_argument("--title", required=True, help="Series title for reporting")
    emby_task_wait_parser.add_argument("--task-key", default="RefreshLibrary", help="Emby scheduled task key")
    emby_task_wait_parser.add_argument("--stale-path-prefix", action="append", default=[], help="Old local/hlink path prefix that should disappear; can be repeated")
    emby_task_wait_parser.add_argument("--strm-path-prefix", action="append", required=True, help="Replacement STRM Emby/container path prefix; can be repeated")
    emby_task_wait_parser.add_argument("--expected-strm-records", type=int, default=0, help="Expected Emby records under STRM path, including series/season/episode rows when using library DB")
    emby_task_wait_parser.add_argument("--expected-episode-count", type=int, default=0, help="Expected distinct episode count under STRM path")
    emby_task_wait_parser.add_argument("--expected-episode-min", type=int, default=0, help="Expected first episode number")
    emby_task_wait_parser.add_argument("--expected-episode-max", type=int, default=0, help="Expected last episode number")
    emby_task_wait_parser.add_argument("--library-db", default="", help="Optional Emby library.db path for exact readonly verification")
    emby_task_wait_parser.add_argument("--poll-seconds", type=float, default=10.0, help="Polling interval while the task is running")
    emby_task_wait_parser.add_argument("--max-wait-seconds", type=int, default=900, help="Maximum seconds to wait for task completion")
    emby_task_wait_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    emby_task_wait_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    emby_task_wait_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    emby_task_cancel_parser = subcommands.add_parser("emby-task-cancel", help="Cancel one approved running Emby scheduled task")
    emby_task_cancel_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    emby_task_cancel_parser.add_argument("--task-key", default="RefreshLibrary", help="Emby scheduled task key")
    emby_task_cancel_parser.add_argument("--task-id", default="", help="Optional exact Emby scheduled task id to cancel")
    emby_task_cancel_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    emby_task_cancel_parser.add_argument("--approve-cancel", action="store_true", help="Required: actually cancel the running task")
    emby_task_cancel_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    emby_task_cancel_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    cloud_parser = subcommands.add_parser("cloud-check", help="Readonly STRM coverage check for cloud candidates")
    cloud_parser.add_argument("--env-file", default=None, help="Local env file; never commit real values")
    cloud_parser.add_argument("--scan-report", required=True, help="JSON report from scan/evaluate")
    cloud_parser.add_argument("--strm-root", action="append", default=[], help="STRM root to scan; can be repeated")
    cloud_parser.add_argument("--identity-file", default=None, help="Optional resolved identity override JSON")
    cloud_parser.add_argument("--format", choices=["markdown", "json"], default=None)
    cloud_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")
    cloud_parser.add_argument("--top", type=int, default=None, help="Maximum rows in report")

    identity_parser = subcommands.add_parser("identity-resolve", help="Resolve missing candidate TMDB identities through MoviePilot")
    identity_parser.add_argument("--env-file", default=None, help="Local env file; never commit real values")
    identity_parser.add_argument("--scan-report", default="", help="JSON report from scan/evaluate")
    identity_parser.add_argument("--cloud-report", default="", help="Optional JSON report from cloud-check; resolves only needs_identity_review rows")
    identity_parser.add_argument("--output", required=True, help="Write identity override JSON to file")
    identity_parser.add_argument("--top", type=int, default=None, help="Maximum missing-identity candidates to resolve")
    identity_parser.add_argument("--timeout", type=int, default=20, help="MoviePilot request timeout in seconds")

    transfer_parser = subcommands.add_parser("plan-mv3-transfer", help="Create a readonly MV3 transfer queue from cloud-check JSON")
    transfer_parser.add_argument("--cloud-report", required=True, help="JSON report from cloud-check")
    transfer_parser.add_argument("--status", action="append", default=[], help="Source status to include; defaults to cloud_strm_not_found")
    transfer_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    transfer_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")
    transfer_parser.add_argument("--top", type=int, default=0, help="Maximum transfer rows in report")

    restored_queue_parser = subcommands.add_parser("mv3-restored-transfer-queue", help="Summarize the readonly transfer queue to resume after MV3 is restored")
    restored_queue_parser.add_argument("--cloud-report", required=True, help="JSON report from cloud-check")
    restored_queue_parser.add_argument("--transfer-plan", default=None, help="Optional JSON report from plan-mv3-transfer")
    restored_queue_parser.add_argument("--historical-scan", default=None, help="Optional historical scan JSON for context samples")
    restored_queue_parser.add_argument("--mv3-report", default=None, help="Optional JSON report from mv3-check")
    restored_queue_parser.add_argument("--top", type=int, default=0, help="Maximum rows per queue section; 0 means all current rows")
    restored_queue_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    restored_queue_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    batch_plan_parser = subcommands.add_parser("batch-plan", help="Build a readonly batch state-machine plan from scan/cloud/MV3 search reports")
    batch_plan_parser.add_argument("--env-file", default=None, help="Local env file; used only for generated command templates")
    batch_plan_parser.add_argument("--scan-report", default=None, help="Optional JSON report from scan")
    batch_plan_parser.add_argument("--cloud-report", default=None, help="Optional JSON report from cloud-check; generated from scan when omitted")
    batch_plan_parser.add_argument("--transfer-plan", default=None, help="Optional JSON report from plan-mv3-transfer; generated from cloud report when omitted")
    batch_plan_parser.add_argument("--share-search-plan", action="append", default=[], help="Optional JSON report from plan-mv3-share-search; can be repeated")
    batch_plan_parser.add_argument("--cleanup-preview-report", action="append", default=[], help="Optional JSON report from mp-cleanup-preview or cloud-complete cleanup plan item; can be repeated")
    batch_plan_parser.add_argument("--media-root", action="append", default=[], help="Media root to scan when --scan-report is omitted")
    batch_plan_parser.add_argument("--strm-root", action="append", default=[], help="STRM root for generated cloud-check when --cloud-report is omitted")
    batch_plan_parser.add_argument("--identity-file", default=None, help="Optional identity override file for generated cloud-check")
    batch_plan_parser.add_argument("--limit", type=int, default=0, help="Maximum rows in batch plan")
    batch_plan_parser.add_argument("--cloud-root", default=DEFAULT_CLOUD_ROOT, help="Cloud media root, usually /已整理/series")
    batch_plan_parser.add_argument("--mv3-strm-root", default=DEFAULT_STRM_ROOT, help="MV3/container STRM root used for command templates")
    batch_plan_parser.add_argument("--host-strm-root", default="", help="Host STRM root, e.g. /example/host/strm")
    batch_plan_parser.add_argument("--emby-strm-root", default="", help="Emby/container STRM root, e.g. /example/service/strm")
    batch_plan_parser.add_argument("--min-candidate-score", type=int, default=60, help="Minimum MV3 search score for auto transfer bucket")
    batch_plan_parser.add_argument("--max-auto-size-delta", type=float, default=0.35, help="Maximum local/remote size delta ratio for auto transfer bucket")
    batch_plan_parser.add_argument("--required-target-prefix", default="/已整理", help="Required STRM target cloud prefix")
    batch_plan_parser.add_argument("--forbidden-target-prefix", action="append", default=[], help="Forbidden STRM target prefix; can be repeated")
    batch_plan_parser.add_argument("--format", choices=["markdown", "json", "csv"], default="markdown")
    batch_plan_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    batch_review_parser = subcommands.add_parser("batch-review-report", help="Build a readonly human-review report from batch state and run reports")
    batch_review_parser.add_argument("--batch-plan", required=True, help="JSON report from batch-plan")
    batch_review_parser.add_argument("--share-preview-report", action="append", default=[], help="Optional JSON report from batch-share-preview; can be repeated")
    batch_review_parser.add_argument("--transfer-run-report", action="append", default=[], help="Optional JSON report from batch-transfer-run; can be repeated")
    batch_review_parser.add_argument("--finalize-run-report", action="append", default=[], help="Optional JSON report from batch-finalize-run; can be repeated")
    batch_review_parser.add_argument("--post-cleanup-report", action="append", default=[], help="Optional JSON report from post-cleanup summary or verification; can be repeated")
    batch_review_parser.add_argument("--format", choices=["markdown", "json", "csv"], default="markdown")
    batch_review_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    extra_source_parser = subcommands.add_parser("extra-source-media-plan", help="Build readonly follow-up plan for source videos that blocked cleanup")
    extra_source_parser.add_argument("--finalize-run-report", required=True, help="JSON report from batch-finalize-run")
    extra_source_parser.add_argument("--env-file", default="", help="Local env file; used only for generated command templates")
    extra_source_parser.add_argument("--target-dir", default="/已整理", help="MV3 organize root, e.g. /已整理")
    extra_source_parser.add_argument("--strm-dir", default="/strm", help="MV3 STRM output root")
    extra_source_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    extra_source_parser.add_argument("--timeout", type=int, default=120)
    extra_source_parser.add_argument("--format", choices=["markdown", "json", "csv"], default="markdown")
    extra_source_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    batch_share_preview_parser = subcommands.add_parser("batch-share-preview", help="Build or execute readonly MV3 share previews from a batch-plan report")
    batch_share_preview_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    batch_share_preview_parser.add_argument("--batch-plan", required=True, help="JSON report from batch-plan")
    batch_share_preview_parser.add_argument(
        "--bucket",
        action="append",
        default=[],
        help="Batch bucket to consider; defaults to auto_ready_for_transfer_preview and manual_review",
    )
    batch_share_preview_parser.add_argument("--min-candidate-score", type=int, default=55, help="Minimum best-candidate score to preview")
    batch_share_preview_parser.add_argument("--allowed-best-blocker", action="append", default=[], help="Best-candidate blocker allowed for readonly preview; defaults to episode_coverage_unclear")
    batch_share_preview_parser.add_argument("--limit", type=int, default=10, help="Maximum planned/executed preview rows")
    batch_share_preview_parser.add_argument("--execute-preview", action="store_true", help="Actually run readonly MV3 share previews; no receive/transfer is performed")
    batch_share_preview_parser.add_argument("--preview-output-dir", default="", help="Directory for per-item preview JSON reports when --execute-preview is used")
    batch_share_preview_parser.add_argument("--max-nested-depth", type=int, default=3, help="Maximum unique nested share folders to browse while previewing")
    batch_share_preview_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug used when browsing the share")
    batch_share_preview_parser.add_argument("--channel", action="append", default=[], help="Optional MV3 resource-search channel; can be repeated")
    batch_share_preview_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    batch_share_preview_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    batch_share_preview_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    batch_share_receive_plan_parser = subcommands.add_parser("batch-share-receive-plan", help="Build approval-gated MV3 share receive commands from a batch-share-preview report")
    batch_share_receive_plan_parser.add_argument("--env-file", required=True, help="Local env file; used only for generated command templates")
    batch_share_receive_plan_parser.add_argument("--batch-share-preview-report", required=True, help="JSON report from batch-share-preview --execute-preview")
    batch_share_receive_plan_parser.add_argument("--target-path", default="/未整理", help="115 receive target path; must stay under /未整理")
    batch_share_receive_plan_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    batch_share_receive_plan_parser.add_argument("--limit", type=int, default=0, help="Maximum approval-required rows; 0 means all")
    batch_share_receive_plan_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    batch_share_receive_plan_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    batch_transfer_run_parser = subcommands.add_parser("batch-transfer-run", help="Run approval-gated MV3 share receive and organize transfer stages from a receive plan")
    batch_transfer_run_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    batch_transfer_run_parser.add_argument("--receive-plan", required=True, help="JSON report from batch-share-receive-plan")
    batch_transfer_run_parser.add_argument("--output-dir", required=True, help="Directory for per-stage JSON reports")
    batch_transfer_run_parser.add_argument("--limit", type=int, default=0, help="Maximum approval-required rows to process; 0 means all")
    batch_transfer_run_parser.add_argument("--title", action="append", default=[], help="Only process titles containing this text; can be repeated")
    batch_transfer_run_parser.add_argument("--target-path", default="/未整理", help="115 staging receive root; must start with /未整理")
    batch_transfer_run_parser.add_argument("--organize-target-dir", default="/已整理", help="MV3 organize root; must be /已整理")
    batch_transfer_run_parser.add_argument("--strm-dir", default="/strm", help="MV3 STRM output root; must be STRM-side")
    batch_transfer_run_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    batch_transfer_run_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    batch_transfer_run_parser.add_argument("--transfer-timeout", type=int, default=180, help="MV3 organize transfer timeout in seconds")
    batch_transfer_run_parser.add_argument("--approve-receive", action="store_true", help="Required: actually receive approved share items to staging")
    batch_transfer_run_parser.add_argument("--approve-transfer", action="store_true", help="Required: actually ask MV3 to organize received items and generate STRM")
    batch_transfer_run_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    batch_transfer_run_parser.add_argument("--output", default=None, help="Write aggregate report to file instead of stdout")

    batch_finalize_parser = subcommands.add_parser("batch-finalize-plan", help="Build readonly post-transfer scrape/Emby/cleanup gate commands from a batch-plan report")
    batch_finalize_parser.add_argument("--env-file", required=True, help="Local env file; used only for generated command templates")
    batch_finalize_parser.add_argument("--batch-plan", required=True, help="JSON report from batch-plan")
    batch_finalize_parser.add_argument("--cloud-root", default="", help="Cloud media title root, defaults to batch-plan setting")
    batch_finalize_parser.add_argument("--host-strm-root", default="", help="Host STRM root, defaults to batch-plan setting")
    batch_finalize_parser.add_argument("--mp-strm-root", default="", help="MoviePilot visible STRM root; defaults to --service-strm-root")
    batch_finalize_parser.add_argument("--service-strm-root", default="", help="Emby visible STRM root, defaults to batch-plan emby_strm_root setting")
    batch_finalize_parser.add_argument("--required-target-prefix", default="", help="Required STRM target prefix; defaults per item to cloud media path")
    batch_finalize_parser.add_argument("--forbidden-target-prefix", action="append", default=[], help="STRM targets must not start with this prefix; can be repeated")
    batch_finalize_parser.add_argument("--limit", type=int, default=0, help="Maximum planned finalize rows; 0 means all")
    batch_finalize_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    batch_finalize_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    batch_finalize_run_parser = subcommands.add_parser("batch-finalize-run", help="Run ordered post-transfer STRM/MP/NFO/Emby/cleanup gates from a finalize plan")
    batch_finalize_run_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    batch_finalize_run_parser.add_argument("--finalize-plan", required=True, help="JSON report from batch-finalize-plan")
    batch_finalize_run_parser.add_argument("--output-dir", required=True, help="Directory for per-stage JSON reports")
    batch_finalize_run_parser.add_argument("--limit", type=int, default=0, help="Maximum planned finalize rows to process; 0 means all")
    batch_finalize_run_parser.add_argument("--title", action="append", default=[], help="Only process titles containing this text; can be repeated")
    batch_finalize_run_parser.add_argument("--continue-on-error", action="store_true", help="Continue to the next item after a gate failure")
    batch_finalize_run_parser.add_argument("--execute-scrape", action="store_true", help="Actually request MoviePilot to scrape STRM-side paths")
    batch_finalize_run_parser.add_argument("--approve-cloud-duplicate-delete", action="store_true", help="Actually delete duplicate cloud videos after STRM target protection verifies")
    batch_finalize_run_parser.add_argument("--approve-emby-stale-delete", action="store_true", help="Actually delete stale Emby local-source items after STRM replacement verifies")
    batch_finalize_run_parser.add_argument("--approve-delete", action="store_true", help="Actually execute qB+hlink cleanup after all gates pass")
    batch_finalize_run_parser.add_argument("--min-seed-days", type=int, default=7, help="Minimum qB seed days for cleanup preview")
    batch_finalize_run_parser.add_argument("--cloud-media-storage", default="115-default", help="MV3 cloud storage slug for cloud sidecar verification")
    batch_finalize_run_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    batch_finalize_run_parser.add_argument("--scrape-timeout", type=int, default=120, help="MoviePilot scrape timeout in seconds")
    batch_finalize_run_parser.add_argument("--nfo-min-chinese-ratio", type=float, default=0.35, help="Minimum Chinese ratio for NFO language audit")
    batch_finalize_run_parser.add_argument("--nfo-sample-limit", type=int, default=50, help="NFO sample limit per STRM root")
    batch_finalize_run_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    batch_finalize_run_parser.add_argument("--output", default=None, help="Write aggregate report to file instead of stdout")

    batch_pipeline_parser = subcommands.add_parser("batch-pipeline", help="Run the resumable batch state machine and write all stage reports")
    batch_pipeline_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    batch_pipeline_parser.add_argument("--output-dir", required=True, help="Root directory for this pipeline run/state")
    batch_pipeline_parser.add_argument("--run-id", default="", help="Optional stable run directory name; defaults to timestamped pipeline-*")
    batch_pipeline_parser.add_argument("--scan-report", default="", help="Optional JSON report from scan")
    batch_pipeline_parser.add_argument("--cloud-report", default="", help="Optional JSON report from cloud-check")
    batch_pipeline_parser.add_argument("--transfer-plan", default="", help="Optional JSON report from plan-mv3-transfer")
    batch_pipeline_parser.add_argument("--share-search-plan", action="append", default=[], help="Optional JSON report from plan-mv3-share-search; can be repeated")
    batch_pipeline_parser.add_argument("--share-preview-report", default="", help="Optional JSON report from a prior batch-pipeline/batch-share-preview execution")
    batch_pipeline_parser.add_argument("--cleanup-preview-report", action="append", default=[], help="Optional cleanup preview JSON; can be repeated")
    batch_pipeline_parser.add_argument("--media-root", action="append", default=[], help="Media root to scan when no scan/cloud report is supplied")
    batch_pipeline_parser.add_argument("--strm-root", action="append", default=[], help="STRM root for cloud-check when cloud report is omitted")
    batch_pipeline_parser.add_argument("--identity-file", default="", help="Optional identity override file for generated cloud-check")
    batch_pipeline_parser.add_argument("--cloud-root", default=DEFAULT_CLOUD_ROOT, help="Cloud media root for planning, usually /已整理/series")
    batch_pipeline_parser.add_argument("--mv3-strm-root", default=DEFAULT_STRM_ROOT, help="MV3/container STRM root")
    batch_pipeline_parser.add_argument("--host-strm-root", default="", help="Host STRM root, e.g. /example/host/strm")
    batch_pipeline_parser.add_argument("--mp-strm-root", default="", help="MoviePilot visible STRM root; defaults to --emby-strm-root")
    batch_pipeline_parser.add_argument("--emby-strm-root", default="", help="Emby visible STRM root")
    batch_pipeline_parser.add_argument("--min-candidate-score", type=int, default=60)
    batch_pipeline_parser.add_argument("--max-auto-size-delta", type=float, default=0.35)
    batch_pipeline_parser.add_argument("--required-target-prefix", default="/已整理")
    batch_pipeline_parser.add_argument("--forbidden-target-prefix", action="append", default=[])
    batch_pipeline_parser.add_argument("--execute-share-search", action="store_true", help="Actually search MV3 resources for transfer rows")
    batch_pipeline_parser.add_argument("--share-search-limit", type=int, default=0)
    batch_pipeline_parser.add_argument("--share-search-offset", type=int, default=0)
    batch_pipeline_parser.add_argument("--share-search-max-candidates", type=int, default=5)
    batch_pipeline_parser.add_argument("--channel", action="append", default=[], help="Optional MV3 channel for share search/preview; can be repeated")
    batch_pipeline_parser.add_argument("--share-search-timeout", type=int, default=60)
    batch_pipeline_parser.add_argument("--execute-preview", action="store_true", help="Actually run readonly MV3 share previews")
    batch_pipeline_parser.add_argument("--preview-limit", type=int, default=10)
    batch_pipeline_parser.add_argument("--preview-bucket", action="append", default=[], help="Batch bucket to preview; defaults to auto transfer and manual review")
    batch_pipeline_parser.add_argument("--preview-min-candidate-score", type=int, default=55)
    batch_pipeline_parser.add_argument("--preview-allowed-best-blocker", action="append", default=[])
    batch_pipeline_parser.add_argument("--preview-storage", default="115-default")
    batch_pipeline_parser.add_argument("--preview-timeout", type=int, default=60)
    batch_pipeline_parser.add_argument("--max-nested-depth", type=int, default=3)
    batch_pipeline_parser.add_argument("--run-transfer-stage", action="store_true", help="Run approval-gated MV3 receive/organize stage")
    batch_pipeline_parser.add_argument("--approve-receive", action="store_true", help="Allow MV3 share receive during transfer stage")
    batch_pipeline_parser.add_argument("--approve-transfer", action="store_true", help="Allow MV3 organize transfer and STRM generation")
    batch_pipeline_parser.add_argument("--transfer-target-path", default="/未整理", help="115 staging receive root; must start with /未整理")
    batch_pipeline_parser.add_argument("--organize-target-dir", default="/已整理", help="MV3 organize root; must be exactly /已整理")
    batch_pipeline_parser.add_argument("--transfer-strm-dir", default=DEFAULT_STRM_ROOT, help="MV3 STRM output root")
    batch_pipeline_parser.add_argument("--transfer-storage", default="115-default")
    batch_pipeline_parser.add_argument("--transfer-timeout", type=int, default=60)
    batch_pipeline_parser.add_argument("--organize-timeout", type=int, default=180)
    batch_pipeline_parser.add_argument("--no-refresh-after-transfer", action="store_true", help="Skip post-transfer cloud-check/batch-plan refresh")
    batch_pipeline_parser.add_argument("--run-finalize-stage", action="store_true", help="Run STRM scrape/Emby/cleanup gates")
    batch_pipeline_parser.add_argument("--finalize-limit", type=int, default=0)
    batch_pipeline_parser.add_argument("--title", action="append", default=[], help="Only finalize titles containing this text")
    batch_pipeline_parser.add_argument("--continue-on-error", action="store_true")
    batch_pipeline_parser.add_argument("--execute-scrape", action="store_true", help="Actually request MoviePilot scrape on STRM-side paths")
    batch_pipeline_parser.add_argument("--approve-cloud-duplicate-delete", action="store_true")
    batch_pipeline_parser.add_argument("--approve-emby-stale-delete", action="store_true")
    batch_pipeline_parser.add_argument("--approve-delete", action="store_true", help="Actually run final qB+hlink cleanup after gates pass")
    batch_pipeline_parser.add_argument("--min-seed-days", type=int, default=7)
    batch_pipeline_parser.add_argument("--cloud-media-storage", default="115-default")
    batch_pipeline_parser.add_argument("--finalize-timeout", type=int, default=20)
    batch_pipeline_parser.add_argument("--scrape-timeout", type=int, default=120)
    batch_pipeline_parser.add_argument("--nfo-min-chinese-ratio", type=float, default=0.35)
    batch_pipeline_parser.add_argument("--nfo-sample-limit", type=int, default=50)
    batch_pipeline_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    batch_pipeline_parser.add_argument("--output", default=None, help="Write aggregate state report to file instead of stdout")

    preview_parser = subcommands.add_parser("plan-mv3-preview", help="Create a readonly MV3 preview manifest from a transfer plan")
    preview_parser.add_argument("--transfer-plan", required=True, help="JSON report from plan-mv3-transfer")
    preview_parser.add_argument("--instances-report", default=None, help="Optional JSON report from mv3-instances")
    preview_parser.add_argument("--capabilities-report", default=None, help="Optional JSON report from mv3-capabilities")
    preview_parser.add_argument("--limit", type=int, default=10, help="Maximum manifest rows")
    preview_parser.add_argument("--cloud-root", default=DEFAULT_CLOUD_ROOT, help="Cloud root used for proposed destinations")
    preview_parser.add_argument("--instance", default="", help="Override MV3 media-transfer instance slug")
    preview_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    preview_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    offline_parser = subcommands.add_parser("plan-mv3-offline", help="Create a readonly MV3 115-offline manifest from qB metadata")
    offline_parser.add_argument("--env-file", default=None, help="Local env file; never commit real values")
    offline_parser.add_argument("--transfer-plan", required=True, help="JSON report from plan-mv3-transfer")
    offline_parser.add_argument("--instances-report", default=None, help="Optional JSON report from mv3-instances")
    offline_parser.add_argument("--qb-report", default=None, help="Optional cached qB torrents JSON; otherwise qB is queried readonly")
    offline_parser.add_argument("--limit", type=int, default=10, help="Maximum manifest rows")
    offline_parser.add_argument("--cloud-root", default=DEFAULT_CLOUD_ROOT, help="Cloud root used for proposed destinations")
    offline_parser.add_argument("--strm-root", default=DEFAULT_STRM_ROOT, help="MV3 STRM-side root used for post-offline STRM generation templates")
    offline_parser.add_argument("--min-seed-days", type=int, default=7, help="Minimum qB seed days to mark seed OK")
    offline_parser.add_argument("--destination-mode", choices=["season", "root"], default="season", help="Offline-add target: exact season destination or cloud root only")
    offline_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    offline_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    offline_add_parser = subcommands.add_parser("mv3-offline-add-one", help="Execute exactly one approved MV3 115 offline-add task")
    offline_add_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    offline_add_parser.add_argument("--manifest", required=True, help="JSON report from plan-mv3-offline")
    offline_add_parser.add_argument("--priority", type=int, required=True, help="Manifest row priority to execute")
    offline_add_parser.add_argument("--expected-title", required=True, help="Safety check: title must exactly match manifest row")
    offline_add_parser.add_argument("--qb-report", default=None, help="Optional cached qB torrents JSON; otherwise qB is queried")
    offline_add_parser.add_argument("--timeout", type=int, default=30, help="Per-request timeout in seconds")
    offline_add_parser.add_argument("--approve-offline-add", action="store_true", help="Required: actually create one MV3 offline task")
    offline_add_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    offline_add_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    ensure_path_parser = subcommands.add_parser("mv3-ensure-115-path", help="Create missing 115 folders for one approved target path")
    ensure_path_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    ensure_path_parser.add_argument("--target-path", required=True, help="Absolute 115 cloud path to ensure")
    ensure_path_parser.add_argument("--storage", default="", help="Override MV3 cloud drive slug; defaults to 115-default when omitted")
    ensure_path_parser.add_argument("--timeout", type=int, default=30, help="Per-request timeout in seconds")
    ensure_path_parser.add_argument("--approve-create-path", action="store_true", help="Required: actually create missing 115 folders")
    ensure_path_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ensure_path_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    offline_status_parser = subcommands.add_parser("mv3-offline-status-one", help="Readonly status check for one MV3 115 offline task")
    offline_status_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    offline_status_parser.add_argument("--info-hash", required=True, help="qB/MV3 offline task info_hash")
    offline_status_parser.add_argument("--target-folder-id", default="", help="Optional 115 target folder id")
    offline_status_parser.add_argument("--target-path", default="", help="Optional 115 target path")
    offline_status_parser.add_argument("--storage", default="", help="Override MV3 cloud drive slug; defaults to 115-default when omitted")
    offline_status_parser.add_argument("--timeout", type=int, default=30, help="Per-request timeout in seconds")
    offline_status_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    offline_status_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    offline_status_plan_parser = subcommands.add_parser("mv3-offline-status-plan", help="Readonly status check for MV3 115 offline tasks from a manifest")
    offline_status_plan_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    offline_status_plan_parser.add_argument("--manifest", required=True, help="JSON report from plan-mv3-offline")
    offline_status_plan_parser.add_argument("--priority", type=int, action="append", default=[], help="Only check one manifest priority; can be repeated")
    offline_status_plan_parser.add_argument("--storage", default="", help="Override MV3 cloud drive slug; defaults to manifest storage or 115-default")
    offline_status_plan_parser.add_argument("--timeout", type=int, default=30, help="Per-request timeout in seconds")
    offline_status_plan_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    offline_status_plan_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    resource_search_parser = subcommands.add_parser("mv3-resource-search", help="Search MV3 resource sources without transferring")
    resource_search_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    resource_search_parser.add_argument("--keyword", required=True, help="Search keyword")
    resource_search_parser.add_argument("--channel", action="append", default=[], help="Optional channel filter; can be repeated")
    resource_search_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    resource_search_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    resource_search_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    share_search_plan_parser = subcommands.add_parser("plan-mv3-share-search", help="Search MV3 shares for transfer-plan rows and rank readonly candidates")
    share_search_plan_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    share_search_plan_parser.add_argument("--transfer-plan", required=True, help="JSON report from plan-mv3-transfer")
    share_search_plan_parser.add_argument("--limit", type=int, default=10, help="Maximum transfer rows to search")
    share_search_plan_parser.add_argument("--offset", type=int, default=0, help="Skip this many transfer rows before searching")
    share_search_plan_parser.add_argument("--max-candidates", type=int, default=5, help="Maximum ranked search candidates per row")
    share_search_plan_parser.add_argument("--channel", action="append", default=[], help="Optional channel filter; can be repeated")
    share_search_plan_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    share_search_plan_parser.add_argument("--checkpoint-output", default=None, help="Write a partial JSON/Markdown report after each searched row")
    share_search_plan_parser.add_argument("--checkpoint-each", action="store_true", help="Keep checkpoint-output updated after every row instead of only at the end")
    share_search_plan_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    share_search_plan_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    share_preview_parser = subcommands.add_parser("mv3-share-preview", help="Preview one MV3 resource share without receiving it")
    share_preview_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    share_preview_parser.add_argument("--keyword", required=True, help="Search keyword")
    share_preview_parser.add_argument("--selection-index", type=int, default=1, help="1-based search result to parse/browse")
    share_preview_parser.add_argument("--browse-cid", default="", help="Optional share folder cid to browse instead of the share root")
    share_preview_parser.add_argument("--browse-limit", type=int, default=1150, help="Maximum share folder items to request")
    share_preview_parser.add_argument("--expected-episode-count", type=int, default=0, help="Readonly safety check: exact distinct episode count")
    share_preview_parser.add_argument("--expected-episode-min", type=int, default=0, help="Readonly safety check: first episode number")
    share_preview_parser.add_argument("--expected-episode-max", type=int, default=0, help="Readonly safety check: last episode number")
    share_preview_parser.add_argument("--expected-episode", action="append", default=[], help="Optional explicit expected episode list/range, comma-separated; can be repeated")
    share_preview_parser.add_argument("--expected-title-contains", default="", help="Safety check: selected title must contain this text")
    share_preview_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug used when browsing the share")
    share_preview_parser.add_argument("--channel", action="append", default=[], help="Optional channel filter; can be repeated")
    share_preview_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    share_preview_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    share_preview_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    share_receive_parser = subcommands.add_parser("mv3-share-receive-one", help="Receive exactly one approved MV3 resource share item")
    share_receive_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    share_receive_parser.add_argument("--keyword", required=True, help="Search keyword")
    share_receive_parser.add_argument("--selection-index", type=int, default=1, help="1-based search result to parse/browse")
    share_receive_parser.add_argument("--browse-index", type=int, default=1, help="1-based browsed share item to receive")
    share_receive_parser.add_argument("--browse-cid", default="", help="Optional share folder cid to browse before selecting --browse-index")
    share_receive_parser.add_argument("--browse-limit", type=int, default=1150, help="Maximum share folder items to request")
    share_receive_parser.add_argument("--receive-all-files", action="store_true", help="Receive every file in the current browsed share folder instead of one selected item")
    share_receive_parser.add_argument("--receive-selected-folder", action="store_true", help="Receive the selected share folder after verifying a nested browse report proves complete episode coverage")
    share_receive_parser.add_argument("--verified-folder-browse-report", default=None, help="JSON report from mv3-share-preview for the selected folder cid; required with --receive-selected-folder")
    share_receive_parser.add_argument("--expected-episode-count", type=int, default=0, help="Safety check for --receive-all-files: exact episode count")
    share_receive_parser.add_argument("--expected-episode-min", type=int, default=0, help="Safety check for --receive-all-files: first episode number")
    share_receive_parser.add_argument("--expected-episode-max", type=int, default=0, help="Safety check for --receive-all-files: last episode number")
    share_receive_parser.add_argument("--expected-title-contains", required=True, help="Safety check: selected title must contain this text")
    share_receive_parser.add_argument("--target-path", default="/未整理", help="115 target path; defaults to /未整理")
    share_receive_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    share_receive_parser.add_argument("--channel", action="append", default=[], help="Optional channel filter; can be repeated")
    share_receive_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    share_receive_parser.add_argument("--approve-receive", action="store_true", help="Required: actually receive one selected share item")
    share_receive_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    share_receive_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    organize_scan_parser = subcommands.add_parser("mv3-organize-scan-source", help="Readonly MV3 organize scan-source preview")
    organize_scan_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    organize_scan_parser.add_argument("--source-path", required=True, help="Source path to scan")
    organize_scan_parser.add_argument("--source-file-id", default="", help="Optional source file/folder id for cloud paths")
    organize_scan_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    organize_scan_parser.add_argument("--local-source", action="store_true", help="Treat source as local instead of cloud")
    organize_scan_parser.add_argument("--file", action="store_true", help="Treat source as a single file instead of a directory")
    organize_scan_parser.add_argument("--timeout", type=int, default=120, help="Per-request timeout in seconds")
    organize_scan_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    organize_scan_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    organize_transfer_parser = subcommands.add_parser("mv3-organize-transfer-from-browse", help="Execute one approved MV3 organize transfer from a complete cloud-browse JSON report")
    organize_transfer_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    organize_transfer_parser.add_argument("--browse-report", required=True, help="JSON report from mv3-cloud-browse")
    organize_transfer_parser.add_argument("--target-dir", required=True, help="MV3 organize root, e.g. /已整理; MV3 adds media categories such as series")
    organize_transfer_parser.add_argument("--strm-dir", required=True, help="MV3 STRM output dir")
    organize_transfer_parser.add_argument("--source-path-override", default="", help="Optional source path when the browse report was created from a folder id")
    organize_transfer_parser.add_argument("--tmdb-id", type=int, required=True, help="Expected TMDB ID")
    organize_transfer_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct episode count")
    organize_transfer_parser.add_argument("--expected-episode-min", type=int, required=True, help="Expected first episode number")
    organize_transfer_parser.add_argument("--expected-episode-max", type=int, required=True, help="Expected last episode number")
    organize_transfer_parser.add_argument("--expected-episode", action="append", default=[], help="Optional explicit expected episode list, comma-separated; can be repeated")
    organize_transfer_parser.add_argument("--mode", choices=["move", "copy"], default="move", help="MV3 transfer mode")
    organize_transfer_parser.add_argument("--local-target", action="store_true", help="Treat target as local instead of cloud")
    organize_transfer_parser.add_argument("--background", action="store_true", help="Ask MV3 to run transfer in background")
    organize_transfer_parser.add_argument("--timeout", type=int, default=180, help="Per-request timeout in seconds")
    organize_transfer_parser.add_argument("--approve-transfer", action="store_true", help="Required: actually send one MV3 organize transfer request")
    organize_transfer_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    organize_transfer_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    organize_transfer_scan_parser = subcommands.add_parser("mv3-organize-transfer-from-scan", help="Execute one approved MV3 organize transfer from a scan-source JSON report")
    organize_transfer_scan_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    organize_transfer_scan_parser.add_argument("--scan-report", required=True, help="JSON report from mv3-organize-scan-source")
    organize_transfer_scan_parser.add_argument("--target-dir", required=True, help="MV3 organize root, e.g. /已整理; MV3 adds media categories such as series")
    organize_transfer_scan_parser.add_argument("--strm-dir", required=True, help="MV3 STRM output dir")
    organize_transfer_scan_parser.add_argument("--tmdb-id", type=int, required=True, help="Expected TMDB ID")
    organize_transfer_scan_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct episode count")
    organize_transfer_scan_parser.add_argument("--expected-episode-min", type=int, required=True, help="Expected first episode number")
    organize_transfer_scan_parser.add_argument("--expected-episode-max", type=int, required=True, help="Expected last episode number")
    organize_transfer_scan_parser.add_argument("--expected-episode", action="append", default=[], help="Optional explicit expected episode list, comma-separated; can be repeated")
    organize_transfer_scan_parser.add_argument("--mode", choices=["move", "copy"], default="copy", help="MV3 transfer mode; use copy for local source extras")
    organize_transfer_scan_parser.add_argument("--local-target", action="store_true", help="Treat target as local instead of cloud")
    organize_transfer_scan_parser.add_argument("--background", action="store_true", help="Ask MV3 to run transfer in background")
    organize_transfer_scan_parser.add_argument("--timeout", type=int, default=180, help="Per-request timeout in seconds")
    organize_transfer_scan_parser.add_argument("--approve-transfer", action="store_true", help="Required: actually send one MV3 organize transfer request")
    organize_transfer_scan_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    organize_transfer_scan_parser.add_argument("--output", default=None, help="Write aggregate report to file instead of stdout")

    organize_transfer_local_map_parser = subcommands.add_parser("mv3-organize-transfer-from-local-map", help="Execute approved MV3 organize transfer from a human-confirmed local media mapping JSON")
    organize_transfer_local_map_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    organize_transfer_local_map_parser.add_argument("--mapping-file", required=True, help="JSON mapping with items containing source_path, tmdb_id/tmdbid, season, and episode")
    organize_transfer_local_map_parser.add_argument("--target-dir", required=True, help="MV3 organize root, e.g. /已整理; MV3 adds media categories such as series")
    organize_transfer_local_map_parser.add_argument("--strm-dir", required=True, help="MV3 STRM output dir")
    organize_transfer_local_map_parser.add_argument("--tmdb-id", type=int, required=True, help="Expected TMDB ID")
    organize_transfer_local_map_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct episode count")
    organize_transfer_local_map_parser.add_argument("--expected-episode-min", type=int, required=True, help="Expected first episode number")
    organize_transfer_local_map_parser.add_argument("--expected-episode-max", type=int, required=True, help="Expected last episode number")
    organize_transfer_local_map_parser.add_argument("--expected-episode", action="append", default=[], help="Optional explicit expected episode list, comma-separated; can be repeated")
    organize_transfer_local_map_parser.add_argument("--mode", choices=["copy"], default="copy", help="Local extras must be copied, never moved")
    organize_transfer_local_map_parser.add_argument("--local-target", action="store_true", help="Treat target as local instead of cloud")
    organize_transfer_local_map_parser.add_argument("--background", action="store_true", help="Ask MV3 to run transfer in background")
    organize_transfer_local_map_parser.add_argument("--timeout", type=int, default=180, help="Per-request timeout in seconds")
    organize_transfer_local_map_parser.add_argument("--approve-transfer", action="store_true", help="Actually send one MV3 organize transfer request; omitted means dry-run only")
    organize_transfer_local_map_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    organize_transfer_local_map_parser.add_argument("--output", default=None, help="Write aggregate report to file instead of stdout")

    strm_generate_parser = subcommands.add_parser("mv3-strm-generate", help="Execute one approved MV3 STRM generation request")
    strm_generate_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    strm_generate_parser.add_argument("--source-dir", required=True, help="Cloud source media directory, e.g. /已整理/series/Demo/Season 1")
    strm_generate_parser.add_argument("--target-dir", required=True, help="Local/MV3 STRM output dir, e.g. /strm-root")
    strm_generate_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    strm_generate_parser.add_argument("--local-source", action="store_true", help="Treat source as local instead of cloud")
    strm_generate_parser.add_argument("--overwrite", action="store_true", help="Allow MV3 to overwrite existing STRM files")
    strm_generate_parser.add_argument("--full", action="store_true", help="Disable incremental mode")
    strm_generate_parser.add_argument("--organize", action="store_true", help="Ask MV3 to organize while generating STRM; always blocked by this project")
    strm_generate_parser.add_argument("--allow-organize", action="store_true", help="Legacy compatibility flag; organize remains blocked. Use mv3-organize-transfer-from-browse first, then generate STRM only")
    strm_generate_parser.add_argument("--openlist", action="store_true", help="Use MV3 openlist mode")
    strm_generate_parser.add_argument("--disable-primary-category", action="store_true", help="Disable MV3 primary category output")
    strm_generate_parser.add_argument("--disable-secondary-category", action="store_true", help="Disable MV3 secondary category output")
    strm_generate_parser.add_argument("--template", default="", help="Optional MV3 STRM template override")
    strm_generate_parser.add_argument("--timeout", type=int, default=180, help="Per-request timeout in seconds")
    strm_generate_parser.add_argument("--approve-generate", action="store_true", help="Required: actually send one MV3 STRM generate request")
    strm_generate_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    strm_generate_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    strm_records_parser = subcommands.add_parser("mv3-strm-records", help="Readonly MV3 STRM record listing")
    strm_records_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    strm_records_parser.add_argument("--keyword", default="", help="Optional MV3 keyword filter")
    strm_records_parser.add_argument("--record-id", action="append", default=[], help="Optional MV3 STRM record id; can be repeated or comma-separated")
    strm_records_parser.add_argument("--source", default="", help="Optional MV3 source filter")
    strm_records_parser.add_argument("--path-dir", default="", help="Optional MV3 path_dir filter")
    strm_records_parser.add_argument("--missing-pickcode", choices=["true", "false"], default=None, help="Optional missing_pickcode filter")
    strm_records_parser.add_argument("--use-regex", choices=["true", "false"], default=None, help="Optional use_regex filter")
    strm_records_parser.add_argument("--page", type=int, default=1, help="Records page")
    strm_records_parser.add_argument("--page-size", type=int, default=100, help="Records per page")
    strm_records_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    strm_records_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    strm_records_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    strm_materialize_parser = subcommands.add_parser("mv3-strm-records-materialize", help="Materialize approved MV3 STRM record content to filesystem")
    strm_materialize_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    strm_materialize_parser.add_argument("--record-id", action="append", required=True, help="MV3 STRM record id; can be repeated or comma-separated")
    strm_materialize_parser.add_argument("--expected-record-id", action="append", required=True, help="Safety check: expected record id; can be repeated or comma-separated")
    strm_materialize_parser.add_argument("--keyword", default="", help="Optional MV3 keyword filter")
    strm_materialize_parser.add_argument("--expected-strm-prefix", required=True, help="Safety check: MV3 strm_path must start with this prefix")
    strm_materialize_parser.add_argument("--expected-source-prefix", required=True, help="Safety check: MV3 source_path must start with this prefix")
    strm_materialize_parser.add_argument("--host-strm-prefix", required=True, help="Map host STRM root to MV3 STRM root, e.g. /host-strm-root=/strm-root")
    strm_materialize_parser.add_argument("--rewrite-strm-prefix", default="", help="Optional safety rewrite old_mv3_prefix=new_mv3_prefix before host path mapping")
    strm_materialize_parser.add_argument("--overwrite", action="store_true", help="Allow overwriting existing STRM files")
    strm_materialize_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    strm_materialize_parser.add_argument("--approve-write", action="store_true", help="Required: actually write STRM files from MV3 record content")
    strm_materialize_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    strm_materialize_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    strm_redirect_parser = subcommands.add_parser("mv3-strm-records-redirect", help="Execute one approved MV3 STRM records prefix redirect")
    strm_redirect_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    strm_redirect_parser.add_argument("--record-id", action="append", required=True, help="MV3 STRM record id; can be repeated or comma-separated")
    strm_redirect_parser.add_argument("--expected-record-id", action="append", required=True, help="Safety check: expected record id; can be repeated or comma-separated")
    strm_redirect_parser.add_argument("--keyword", default="", help="Optional MV3 keyword filter")
    strm_redirect_parser.add_argument("--old-prefix", required=True, help="Safety check and redirect source prefix")
    strm_redirect_parser.add_argument("--new-prefix", required=True, help="Redirect target prefix")
    strm_redirect_parser.add_argument("--expected-source-prefix", required=True, help="Safety check: MV3 source_path must start with this prefix")
    strm_redirect_parser.add_argument("--strm-dir", default="", help="Optional MV3 strm_dir parameter")
    strm_redirect_parser.add_argument("--timeout", type=int, default=180, help="Per-request timeout in seconds")
    strm_redirect_parser.add_argument("--approve-redirect", action="store_true", help="Required: actually send one MV3 STRM record redirect request")
    strm_redirect_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    strm_redirect_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    strm_regenerate_parser = subcommands.add_parser("mv3-strm-records-regenerate", help="Execute one approved MV3 STRM records regenerate request")
    strm_regenerate_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    strm_regenerate_parser.add_argument("--record-id", action="append", required=True, help="MV3 STRM record id; can be repeated or comma-separated")
    strm_regenerate_parser.add_argument("--expected-record-id", action="append", default=[], help="Safety check: expected record id; can be repeated or comma-separated")
    strm_regenerate_parser.add_argument("--timeout", type=int, default=180, help="Per-request timeout in seconds")
    strm_regenerate_parser.add_argument("--approve-regenerate", action="store_true", help="Required: actually send one MV3 STRM record regenerate request")
    strm_regenerate_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    strm_regenerate_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    cloud_browse_parser = subcommands.add_parser("mv3-cloud-browse", help="Readonly MV3 cloud folder browse")
    cloud_browse_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    cloud_browse_parser.add_argument("--folder-id", default="", help="Cloud folder id to browse")
    cloud_browse_parser.add_argument("--path", default="", help="Optional cloud path to resolve before browsing")
    cloud_browse_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    cloud_browse_parser.add_argument("--limit", type=int, default=1150, help="Maximum folder items to request")
    cloud_browse_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    cloud_browse_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    cloud_browse_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    normalize_received_parser = subcommands.add_parser("mv3-normalize-received-season", help="Dry-run or move a received bare season folder under a titled staging folder")
    normalize_received_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    normalize_received_parser.add_argument("--source-path", required=True, help="Bare received season folder path, e.g. /未整理/Season 1")
    normalize_received_parser.add_argument("--title", required=True, help="Canonical series title")
    normalize_received_parser.add_argument("--tmdb-id", type=int, required=True, help="Expected TMDB ID")
    normalize_received_parser.add_argument("--season", type=int, required=True, help="Season number to normalize")
    normalize_received_parser.add_argument("--year", type=int, default=0, help="Optional release year for target title folder")
    normalize_received_parser.add_argument("--staging-root", default="/未整理", help="Receive staging root; must remain /未整理")
    normalize_received_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    normalize_received_parser.add_argument("--limit", type=int, default=1150, help="Maximum cloud folder items to request")
    normalize_received_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    normalize_received_parser.add_argument("--approve-move", action="store_true", help="Required: actually move the received season folder")
    normalize_received_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    normalize_received_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    cloud_search_parser = subcommands.add_parser("mv3-cloud-search", help="Readonly MV3 cloud file search")
    cloud_search_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    cloud_search_parser.add_argument("--keyword", required=True, help="Cloud search keyword")
    cloud_search_parser.add_argument("--cid", default="", help="Optional cloud folder id to search under")
    cloud_search_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    cloud_search_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    cloud_search_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    cloud_search_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    cloud_search_plan_parser = subcommands.add_parser("mv3-cloud-search-plan", help="Readonly MV3 cloud file search for transfer-plan rows")
    cloud_search_plan_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    cloud_search_plan_parser.add_argument("--transfer-plan", required=True, help="JSON report from plan-mv3-transfer")
    cloud_search_plan_parser.add_argument("--offset", type=int, default=0, help="Skip this many transfer rows before searching")
    cloud_search_plan_parser.add_argument("--limit", type=int, default=10, help="Maximum transfer rows to search; 0 means all rows")
    cloud_search_plan_parser.add_argument("--keyword-limit", type=int, default=3, help="Maximum keywords searched per transfer row")
    cloud_search_plan_parser.add_argument("--cid", default="", help="Optional cloud folder id to search under")
    cloud_search_plan_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    cloud_search_plan_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    cloud_search_plan_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    cloud_search_plan_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    cloud_index_plan_parser = subcommands.add_parser("mv3-cloud-index-plan", help="Readonly MV3 cloud root index match for transfer-plan rows")
    cloud_index_plan_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    cloud_index_plan_parser.add_argument("--transfer-plan", required=True, help="JSON report from plan-mv3-transfer")
    cloud_index_plan_parser.add_argument("--root-folder-id", required=True, help="Cloud root folder id to index")
    cloud_index_plan_parser.add_argument("--root-path", default="", help="Optional cloud root path used only for path hints")
    cloud_index_plan_parser.add_argument("--offset", type=int, default=0, help="Skip this many transfer rows before matching")
    cloud_index_plan_parser.add_argument("--limit", type=int, default=0, help="Maximum transfer rows to match; 0 means all rows")
    cloud_index_plan_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    cloud_index_plan_parser.add_argument("--browse-limit", type=int, default=1150, help="Maximum root folder items to request")
    cloud_index_plan_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    cloud_index_plan_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    cloud_index_plan_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    cloud_sidecar_parser = subcommands.add_parser("mv3-cloud-media-sidecar-verify", help="Readonly recursive MV3 cloud media metadata sidecar verification")
    cloud_sidecar_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    cloud_sidecar_parser.add_argument("--folder-id", default="", help="Cloud folder id to verify")
    cloud_sidecar_parser.add_argument("--path", default="", help="Cloud media path to resolve before verifying")
    cloud_sidecar_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    cloud_sidecar_parser.add_argument("--limit", type=int, default=1150, help="Maximum folder items per browse request")
    cloud_sidecar_parser.add_argument("--max-depth", type=int, default=4, help="Maximum recursive folder depth")
    cloud_sidecar_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    cloud_sidecar_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    cloud_sidecar_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    cloud_sidecar_batch_parser = subcommands.add_parser("mv3-cloud-media-sidecar-batch-verify", help="Readonly MV3 cloud media metadata sidecar verification by first-level title folders")
    cloud_sidecar_batch_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    cloud_sidecar_batch_parser.add_argument("--root-folder-id", default="", help="Cloud root folder id to verify")
    cloud_sidecar_batch_parser.add_argument("--root-path", default="", help="Cloud media root path to resolve before verifying")
    cloud_sidecar_batch_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    cloud_sidecar_batch_parser.add_argument("--limit", type=int, default=1150, help="Maximum folder items per browse request")
    cloud_sidecar_batch_parser.add_argument("--max-depth", type=int, default=3, help="Maximum recursive folder depth under each title folder")
    cloud_sidecar_batch_parser.add_argument("--start-index", type=int, default=1, help="1-based first title-folder index to scan")
    cloud_sidecar_batch_parser.add_argument("--title-limit", type=int, default=0, help="Maximum title folders to scan; 0 means all from start-index")
    cloud_sidecar_batch_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    cloud_sidecar_batch_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    cloud_sidecar_batch_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    cloud_sidecar_cleanup_parser = subcommands.add_parser("mv3-cloud-media-sidecar-cleanup", help="Dry-run or delete MV3 cloud media metadata sidecars only")
    cloud_sidecar_cleanup_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    cloud_sidecar_cleanup_parser.add_argument("--folder-id", default="", help="Cloud folder id to clean")
    cloud_sidecar_cleanup_parser.add_argument("--path", default="", help="Cloud media path to resolve before cleaning")
    cloud_sidecar_cleanup_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    cloud_sidecar_cleanup_parser.add_argument("--limit", type=int, default=1150, help="Maximum folder items per browse request")
    cloud_sidecar_cleanup_parser.add_argument("--max-depth", type=int, default=4, help="Maximum recursive folder depth")
    cloud_sidecar_cleanup_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    cloud_sidecar_cleanup_parser.add_argument("--expected-delete-count", type=int, default=-1, help="Safety check: expected metadata sidecar count, required for approved cleanup")
    cloud_sidecar_cleanup_parser.add_argument("--approve-delete", action="store_true", help="Required: actually delete selected cloud metadata sidecars")
    cloud_sidecar_cleanup_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    cloud_sidecar_cleanup_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    cloud_duplicate_cleanup_parser = subcommands.add_parser("mv3-cloud-duplicate-video-cleanup", help="Dry-run or delete duplicate MV3 cloud season videos protected by STRM targets")
    cloud_duplicate_cleanup_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    cloud_duplicate_cleanup_parser.add_argument("--season-path", required=True, help="Cloud season path to inspect, e.g. /已整理/series/Demo/Season 1")
    cloud_duplicate_cleanup_parser.add_argument("--folder-id", default="", help="Optional already-verified MV3 cloud season folder id")
    cloud_duplicate_cleanup_parser.add_argument("--strm-root", required=True, help="Local/DSM STRM season root whose targets must be protected")
    cloud_duplicate_cleanup_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct episode count")
    cloud_duplicate_cleanup_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    cloud_duplicate_cleanup_parser.add_argument("--limit", type=int, default=1150, help="Maximum cloud folder items to request")
    cloud_duplicate_cleanup_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    cloud_duplicate_cleanup_parser.add_argument("--expected-delete-count", type=int, default=-1, help="Safety check: expected duplicate video count, required for approved cleanup")
    cloud_duplicate_cleanup_parser.add_argument("--approve-delete", action="store_true", help="Required: actually delete selected duplicate cloud videos")
    cloud_duplicate_cleanup_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    cloud_duplicate_cleanup_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    wrong_root_parser = subcommands.add_parser("mv3-repair-wrong-root", help="Dry-run or repair MV3 cloud files placed under a duplicated wrong root")
    wrong_root_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    wrong_root_parser.add_argument("--wrong-root", default="/已整理/series/series", help="Wrong duplicated cloud root")
    wrong_root_parser.add_argument("--correct-root", default="/已整理/series", help="Correct cloud series root")
    wrong_root_parser.add_argument("--strm-root", required=True, help="Local/DSM STRM series root used for target verification")
    wrong_root_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    wrong_root_parser.add_argument("--title-filter", default="", help="Optional substring filter for one title")
    wrong_root_parser.add_argument("--season", type=int, default=None, help="Optional season filter for direct season folders under the wrong root")
    wrong_root_parser.add_argument("--limit", type=int, default=1000, help="Maximum cloud folder items to request")
    wrong_root_parser.add_argument("--timeout", type=int, default=120, help="Per-request timeout in seconds")
    wrong_root_parser.add_argument("--approve-move", action="store_true", help="Allow moving media from wrong root to correct root when checks pass")
    wrong_root_parser.add_argument("--approve-delete-duplicates", action="store_true", help="Allow deleting duplicate wrong-root season folders when checks pass")
    wrong_root_parser.add_argument("--approve-delete-empty", action="store_true", help="Allow deleting empty wrong-root folders after checks pass")
    wrong_root_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    wrong_root_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    wrong_root_pair_parser = subcommands.add_parser(
        "mv3-repair-wrong-root-direct-season-pair",
        help="Dry-run or repair one direct wrong-root season by pairing cloud media move with local STRM target rewrite",
    )
    wrong_root_pair_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    wrong_root_pair_parser.add_argument("--wrong-root", required=True, help="Wrong cloud root containing direct Sxx/Season xx folders")
    wrong_root_pair_parser.add_argument("--correct-root", required=True, help="Correct organized cloud title root")
    wrong_root_pair_parser.add_argument("--strm-root", required=True, help="Local/DSM STRM title or season root")
    wrong_root_pair_parser.add_argument("--season", type=int, required=True, help="Season number to repair")
    wrong_root_pair_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    wrong_root_pair_parser.add_argument("--title-filter", default="", help="Optional title fallback when it cannot be derived from roots")
    wrong_root_pair_parser.add_argument("--expected-episode-count", type=int, default=0, help="Expected media/STRM episode count")
    wrong_root_pair_parser.add_argument("--expected-episode-min", type=int, default=0, help="Expected first episode number")
    wrong_root_pair_parser.add_argument("--expected-episode-max", type=int, default=0, help="Expected last episode number")
    wrong_root_pair_parser.add_argument("--expected-rewrite-count", type=int, default=0, help="Safety check: expected STRM files to rewrite")
    wrong_root_pair_parser.add_argument("--approve-repair", action="store_true", help="Required: create target path, move cloud media, and rewrite STRM targets")
    wrong_root_pair_parser.add_argument("--limit", type=int, default=1000, help="Maximum cloud folder items to request")
    wrong_root_pair_parser.add_argument("--timeout", type=int, default=120, help="Per-request timeout in seconds")
    wrong_root_pair_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    wrong_root_pair_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    mv3_parser = subcommands.add_parser("mv3-check", help="Readonly MV3 connectivity and capability probe")
    mv3_parser.add_argument("--env-file", default=None, help="Local env file; never commit real values")
    mv3_parser.add_argument("--path", action="append", default=[], help="Readonly GET path to probe; can be repeated")
    mv3_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    mv3_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    mv3_cap_parser = subcommands.add_parser("mv3-capabilities", help="Readonly MV3 OpenAPI capability report")
    mv3_cap_parser.add_argument("--env-file", default=None, help="Local env file; never commit real values")
    mv3_cap_parser.add_argument("--include-all", action="store_true", help="Include all OpenAPI endpoints, not just media-relevant paths")
    mv3_cap_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    mv3_cap_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    mv3_instances_parser = subcommands.add_parser("mv3-instances", help="Readonly MV3 configured instance and STRM probe")
    mv3_instances_parser.add_argument("--env-file", default=None, help="Local env file; never commit real values")
    mv3_instances_parser.add_argument("--path", action="append", default=[], help="Readonly GET path to inspect; can be repeated")
    mv3_instances_parser.add_argument("--timeout", type=int, default=10, help="Per-request timeout in seconds")
    mv3_instances_parser.add_argument("--retry-failed-once", action="store_true", help="Retry a failed readonly GET once")
    mv3_instances_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    mv3_instances_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")
    return parser


def _parse_episode_list(value: str) -> List[int]:
    episodes = set()
    for part in (value or "").split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text.strip())
            end = int(end_text.strip())
            if start > end:
                raise argparse.ArgumentTypeError(f"invalid descending episode range: {token}")
            episodes.update(range(start, end + 1))
        else:
            episodes.add(int(token))
    return sorted(item for item in episodes if item > 0)


def _parse_hlink_multiseason_spec(value: str) -> Dict[str, object]:
    parts = str(value or "").split(":")
    if len(parts) < 3:
        raise argparse.ArgumentTypeError(
            "season spec must be season:strm_root:count:min:max or season:strm_root:episodes=1,3-13"
        )
    try:
        season = int(parts[0].strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid season number: {parts[0]}") from exc
    strm_root = parts[1].strip()
    if not strm_root:
        raise argparse.ArgumentTypeError("season spec strm_root is required")
    tail = ":".join(parts[2:]).strip()
    if tail.startswith("episodes="):
        episodes = _parse_episode_list(tail.split("=", 1)[1])
        if not episodes:
            raise argparse.ArgumentTypeError("explicit episode list is empty")
        return {
            "season": season,
            "strm_root": strm_root,
            "expected_episode_count": len(episodes),
            "expected_episode_min": min(episodes),
            "expected_episode_max": max(episodes),
            "expected_episodes": episodes,
        }
    if len(parts) != 5:
        raise argparse.ArgumentTypeError(
            "season spec must be season:strm_root:count:min:max or season:strm_root:episodes=1,3-13"
        )
    try:
        count = int(parts[2].strip())
        episode_min = int(parts[3].strip())
        episode_max = int(parts[4].strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid season episode spec: {value}") from exc
    if season <= 0 or count <= 0 or episode_min <= 0 or episode_max <= 0 or episode_min > episode_max:
        raise argparse.ArgumentTypeError(f"invalid season episode spec: {value}")
    return {
        "season": season,
        "strm_root": strm_root,
        "expected_episode_count": count,
        "expected_episode_min": episode_min,
        "expected_episode_max": episode_max,
        "expected_episodes": [],
    }


def _write_text_output(path: str, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text + "\n", encoding="utf-8")


def _share_search_keywords(item: Dict[str, object]) -> List[str]:
    values: List[str] = []
    title = str(item.get("title") or "").strip()
    if title:
        values.append(title)
    for key in ("search_keywords", "titles"):
        raw = item.get(key)
        if isinstance(raw, list):
            values.extend(str(value).strip() for value in raw if str(value).strip())
    merged: List[str] = []
    for value in values:
        if not value or any(value.lower() == existing.lower() for existing in merged):
            continue
        merged.append(value)
        if len(merged) >= 8:
            break
    return merged


def _combined_mv3_search_report(
    mv3_base_url: str,
    mv3_token: str,
    keywords: Sequence[str],
    channels: Optional[List[str]] = None,
    timeout: int = 60,
) -> Dict[str, object]:
    keyword_reports: List[Dict[str, object]] = []
    merged_items: List[Dict[str, object]] = []
    seen = set()
    for keyword in keywords:
        keyword = str(keyword or "").strip()
        if not keyword:
            continue
        report = search_mv3_resources(mv3_base_url, mv3_token, keyword, channels=channels or [], timeout=timeout)
        keyword_reports.append(
            {
                "keyword": keyword,
                "ok": bool(report.get("ok")),
                "result_count": int(report.get("result_count") or 0),
                "warnings": report.get("warnings", []) if isinstance(report.get("warnings"), list) else [],
            }
        )
        for row in report.get("items", []) if isinstance(report.get("items"), list) else []:
            if not isinstance(row, dict):
                continue
            key = (str(row.get("title") or ""), str(row.get("channel") or ""), str(row.get("size") or ""))
            if key in seen:
                continue
            seen.add(key)
            merged = dict(row)
            merged["search_keyword"] = keyword
            merged_items.append(merged)
    return {
        "ok": any(report.get("ok") for report in keyword_reports),
        "result_count": len(merged_items),
        "items": merged_items,
        "keywords": [report["keyword"] for report in keyword_reports],
        "keyword_reports": keyword_reports,
        "warnings": [],
    }


def _parse_int_list_args(values: List[str]) -> List[int]:
    items = set()
    for value in values:
        items.update(_parse_episode_list(str(value or "")))
    return sorted(item for item in items if item > 0)


def _first_string_arg(values: List[str]) -> str:
    for value in values:
        for part in str(value or "").split(","):
            token = part.strip()
            if token:
                return token
    return ""


def _normalize_cli_strings(values: Sequence[object]) -> List[str]:
    items = set()
    for value in values:
        for part in str(value or "").split(","):
            token = part.strip().lower()
            if token:
                items.add(token)
    return sorted(items)


def _normalize_cli_paths(values: Sequence[object]) -> List[str]:
    items = set()
    for value in values:
        token = str(value or "").strip().rstrip("/")
        if token:
            items.add(token)
    return sorted(items)


def _parse_path_alias_args(values: List[str]) -> dict:
    aliases = {}
    for value in values:
        if "=" not in value:
            raise argparse.ArgumentTypeError(f"invalid path alias: {value}")
        left, right = value.split("=", 1)
        left = left.strip().rstrip("/")
        right = right.strip().rstrip("/")
        if left and right:
            aliases[left] = right
    return aliases


def add_scan_args(scan_parser: argparse.ArgumentParser) -> None:
    scan_parser.add_argument("--env-file", default=None, help="Local env file; never commit real values")
    scan_parser.add_argument("--media-root", action="append", default=[], help="Media root to scan; can be repeated")
    scan_parser.add_argument("--format", choices=["markdown", "json"], default=None)
    scan_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")
    scan_parser.add_argument("--top", type=int, default=None, help="Maximum rows in report")
    scan_parser.add_argument("--min-age-days", type=int, default=None, help="Ignore folders modified more recently than this")
    scan_parser.add_argument("--min-seed-days", type=int, default=None, help="Minimum qBittorrent seed age for candidate status")
    scan_parser.add_argument("--max-depth", type=int, default=None, help="Maximum scan depth under each series folder")
    scan_parser.add_argument("--no-qb", action="store_true", help="Skip qBittorrent evidence")
    scan_parser.add_argument("--no-mp", action="store_true", help="Skip MoviePilot subscription evidence")
    scan_parser.add_argument("--emby", action="store_true", help="Use Emby evidence when configured")


def apply_scan_overrides(config, args):
    if args.format:
        config.output_format = args.format
    if args.top is not None:
        config.top = args.top
    if args.min_age_days is not None:
        config.min_age_days = args.min_age_days
    if args.min_seed_days is not None:
        config.min_seed_days = args.min_seed_days
    if args.max_depth is not None:
        config.max_depth = args.max_depth
    if args.no_qb:
        config.include_qb = False
    if args.no_mp:
        config.include_mp = False
    if args.emby:
        config.include_emby = True
    return config


def stored_series_as_dict(series: StoredSeries):
    return {
        "title": series.title,
        "path": series.path,
        "status": series.status,
        "size_bytes": series.size_bytes,
        "video_count": series.video_count,
        "age_days": series.age_days,
        "score": series.score,
        "reasons": series.reasons,
        "blockers": series.blockers,
        "updated_at": series.updated_at,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        config = config_from_env(args.env_file, args.media_root)
        config = apply_scan_overrides(config, args)

        report = scan(config)
        rendered = render_report(report, config.output_format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "evaluate":
        config = apply_scan_overrides(config_from_env(args.env_file, args.media_root), args)
        db_path = args.db or db_path_from_env(args.env_file)
        report = evaluate(config, db_path)
        rendered = render_report(report, config.output_format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "status":
        import json

        db_path = args.db or db_path_from_env(args.env_file)
        if args.query:
            detail = status_detail(db_path, args.query)
            if args.format == "json":
                print(json.dumps(detail, ensure_ascii=False, indent=2))
            else:
                if not detail["found"]:
                    print(f"No series found for `{args.query}`")
                else:
                    series = detail["series"]
                    print(f"# {series['title']}")
                    print("")
                    print(f"- Status: `{series['status']}`")
                    print(f"- Path: `{series['path']}`")
                    print(f"- Score: `{series['score']}`")
                    print(f"- Blockers: `{series['blockers']}`")
                    print("")
                    print("## Recent audit")
                    for event in detail["audit"]:
                        print(f"- {event['event_type']}: {event['message']}")
            return 0

        rows = list_status(db_path, limit=args.limit, status=args.status)
        if args.format == "json":
            print(json.dumps([stored_series_as_dict(row) for row in rows], ensure_ascii=False, indent=2))
        else:
            print("| Status | Score | Videos | Title | Blockers |")
            print("| --- | ---: | ---: | --- | --- |")
            for row in rows:
                print(f"| {row.status} | {row.score} | {row.video_count} | {row.title} | {','.join(row.blockers)} |")
        return 0

    if args.command == "plan-cleanup":
        import json

        db_path = args.db or db_path_from_env(args.env_file)
        plan = plan_cleanup(db_path, args.query)
        if args.format == "json":
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            if not plan.get("found"):
                print(f"No series found for `{args.query}`")
            else:
                print(f"# Cleanup dry-run plan: {plan['series']}")
                print("")
                print(f"- Status: `{plan['status']}`")
                print(f"- Deletion targets: `{plan['deletion_targets']}`")
                print(f"- Blockers: `{plan['blockers']}`")
                print("")
                print("No deletion was performed.")
        return 0

    if args.command == "qb-dotqb-audit":
        config = config_from_env(args.env_file, [])
        if not config.qb_base_url:
            parser.error("qb-dotqb-audit requires QB_BASE_URL")
        report = audit_dotqb_files(
            config.qb_base_url,
            config.qb_user,
            config.qb_pass,
            scan_roots=args.scan_root,
            path_aliases=_parse_path_alias_args(args.path_alias) or config.path_aliases,
            timeout=args.timeout,
        )
        rendered = render_dotqb_audit_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "dotqb-orphan-cleanup":
        if not args.approve_delete:
            parser.error("dotqb-orphan-cleanup requires --approve-delete")
        config = config_from_env(args.env_file, [])
        if not config.mp_base_url or not config.mp_token:
            parser.error("dotqb-orphan-cleanup requires MP_BASE_URL and MP_API_TOKEN")
        if not config.qb_base_url:
            parser.error("dotqb-orphan-cleanup requires QB_BASE_URL")
        report = cleanup_orphan_dotqb_roots(
            config.mp_base_url,
            config.mp_token,
            title=args.title,
            source_roots=args.source_root,
            destination_roots=args.destination_root,
            strm_roots=args.strm_root,
            expected_tmdbid=args.expected_tmdbid,
            expected_hash_prefixes=args.expected_hash_prefix,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            qb_base_url=config.qb_base_url,
            qb_user=config.qb_user,
            qb_pass=config.qb_pass,
            path_aliases=config.path_aliases,
            dotqb_suffix=args.dotqb_suffix,
            timeout=args.timeout,
        )
        rendered = render_dotqb_orphan_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "qb-orphan-torrent-cleanup-preview":
        config = config_from_env(args.env_file, [])
        if not config.qb_base_url:
            parser.error("qb-orphan-torrent-cleanup-preview requires QB_BASE_URL")
        report = preview_qb_orphan_torrent_cleanup(
            title=args.title,
            expected_hashes=args.expected_qb_hash,
            source_roots=args.source_root,
            hlink_roots=args.hlink_root,
            strm_roots=args.strm_root,
            expected_tmdbid=args.expected_tmdbid,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            qb_base_url=config.qb_base_url,
            qb_user=config.qb_user,
            qb_pass=config.qb_pass,
            mp_base_url=config.mp_base_url,
            mp_token=config.mp_token,
            path_aliases=config.path_aliases,
            expected_title_contains=args.expected_title_contains,
            min_seed_days=args.min_seed_days,
            required_target_prefix=args.required_target_prefix,
            forbidden_target_prefixes=args.forbidden_target_prefix,
            mv3_base_url=config.mv3_base_url,
            mv3_token=config.mv3_token,
            cloud_media_path=args.cloud_media_path,
            cloud_media_folder_id=args.cloud_media_folder_id,
            cloud_media_storage=args.cloud_media_storage,
            timeout=args.timeout,
        )
        rendered = render_qb_orphan_torrent_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "qb-orphan-torrent-cleanup-execute":
        if not args.approve_delete:
            parser.error("qb-orphan-torrent-cleanup-execute requires --approve-delete")
        config = config_from_env(args.env_file, [])
        if not config.qb_base_url:
            parser.error("qb-orphan-torrent-cleanup-execute requires QB_BASE_URL")
        preview = load_optional_json_report(args.preview_report)
        if not isinstance(preview, dict):
            parser.error("preview report must be a JSON object")
        preview_expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
        expected_hashes = _normalize_cli_strings(args.expected_qb_hash)
        preview_hashes = _normalize_cli_strings(preview_expected.get("qb_hashes", []) if isinstance(preview_expected.get("qb_hashes"), list) else [])
        expected_source_roots = _normalize_cli_paths(args.expected_source_root)
        preview_source_roots = _normalize_cli_paths(preview_expected.get("source_roots", []) if isinstance(preview_expected.get("source_roots"), list) else [])
        expected_hlink_roots = _normalize_cli_paths(args.expected_hlink_root)
        preview_hlink_roots = _normalize_cli_paths(preview_expected.get("hlink_roots", []) if isinstance(preview_expected.get("hlink_roots"), list) else [])
        expected_strm_roots = _normalize_cli_paths(args.expected_strm_root)
        preview_strm_roots = _normalize_cli_paths(preview_expected.get("strm_roots", []) if isinstance(preview_expected.get("strm_roots"), list) else [])
        if str(preview.get("title") or "") != args.expected_title:
            parser.error("qb-orphan-torrent-cleanup-execute expected title mismatch")
        if int(preview_expected.get("tmdbid") or 0) != args.expected_tmdbid:
            parser.error("qb-orphan-torrent-cleanup-execute expected TMDB ID mismatch")
        if preview_hashes != expected_hashes:
            parser.error("qb-orphan-torrent-cleanup-execute expected qB hashes mismatch")
        if preview_source_roots != expected_source_roots:
            parser.error("qb-orphan-torrent-cleanup-execute expected source roots mismatch")
        if preview_hlink_roots != expected_hlink_roots:
            parser.error("qb-orphan-torrent-cleanup-execute expected hlink roots mismatch")
        if preview_strm_roots != expected_strm_roots:
            parser.error("qb-orphan-torrent-cleanup-execute expected STRM roots mismatch")
        report = execute_qb_orphan_torrent_cleanup(
            preview,
            config.qb_base_url,
            config.qb_user,
            config.qb_pass,
            mp_base_url=config.mp_base_url,
            mp_token=config.mp_token,
            path_aliases=config.path_aliases,
            mv3_base_url=config.mv3_base_url,
            mv3_token=config.mv3_token,
            timeout=args.timeout,
        )
        rendered = render_qb_orphan_torrent_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mp-cleanup-preview":
        config = config_from_env(args.env_file, [])
        if not config.mp_base_url or not config.mp_token:
            parser.error("mp-cleanup-preview requires MP_BASE_URL and MP_API_TOKEN")
        report = mp_cleanup_preview_from_transfer_history(
            config.mp_base_url,
            config.mp_token,
            title=args.title,
            expected_title=args.expected_title,
            expected_tmdbid=args.expected_tmdbid,
            expected_hash_prefix=args.expected_hash_prefix,
            expected_season=args.expected_season,
            include_deletesrc=not args.keep_source,
            include_deletedest=not args.keep_dest,
            record_only=args.record_only,
            timeout=args.timeout,
        )
        rendered = render_mp_cleanup_preview(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mp-scrape-strm":
        if not args.approve_scrape:
            parser.error("mp-scrape-strm requires --approve-scrape")
        config = config_from_env(args.env_file, [])
        if not config.mp_base_url or not config.mp_token:
            parser.error("mp-scrape-strm requires MP_BASE_URL and MP_API_TOKEN")
        report = scrape_mp_strm_path(
            config.mp_base_url,
            config.mp_token,
            strm_path=args.strm_path,
            mp_path=args.mp_path,
            storage=args.storage,
            item_type=args.type,
            timeout=args.timeout,
        )
        rendered = render_mp_scrape_strm_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mp-cleanup-execute":
        if not args.approve_mp_cleanup:
            parser.error("mp-cleanup-execute requires --approve-mp-cleanup")
        config = config_from_env(args.env_file, [])
        if not config.mp_base_url or not config.mp_token:
            parser.error("mp-cleanup-execute requires MP_BASE_URL and MP_API_TOKEN")
        preview = load_optional_json_report(args.preview_report)
        if not isinstance(preview, dict):
            parser.error("preview report must be a JSON object")
        report = execute_mp_cleanup_from_preview_report(
            config.mp_base_url,
            config.mp_token,
            preview,
            expected_title=args.expected_title,
            expected_tmdbid=args.expected_tmdbid,
            expected_hash_prefix=_first_string_arg(args.expected_hash_prefix),
            expected_season=args.expected_season,
            expected_hash_prefixes=args.expected_hash_prefix,
            expected_record_count=args.expected_record_count,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            expected_episodes=args.expected_episodes,
            include_deletesrc=not args.keep_source,
            include_deletedest=not args.keep_dest,
            record_only=args.record_only,
            timeout=args.timeout,
            continue_on_error=args.continue_on_error,
            allow_multiple_hashes=args.allow_multiple_hashes,
            allow_multiple_source_roots=args.allow_multiple_source_roots,
            allow_duplicate_episodes=args.allow_duplicate_episodes,
        )
        rendered = render_mp_cleanup_execute_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mp-cleanup-verify":
        config = config_from_env(args.env_file, [])
        if not config.mp_base_url or not config.mp_token:
            parser.error("mp-cleanup-verify requires MP_BASE_URL and MP_API_TOKEN")
        report = verify_mp_cleanup_from_services(
            config.mp_base_url,
            config.mp_token,
            title=args.title,
            expected_title=args.expected_title,
            expected_tmdbid=args.expected_tmdbid,
            expected_hash_prefix=_first_string_arg(args.expected_hash_prefix),
            expected_hash_prefixes=args.expected_hash_prefix,
            expected_season=args.expected_season,
            source_roots=args.source_root,
            destination_roots=args.destination_root,
            strm_roots=args.strm_root,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            qb_base_url=config.qb_base_url,
            qb_user=config.qb_user,
            qb_pass=config.qb_pass,
            timeout=args.timeout,
        )
        rendered = render_mp_cleanup_verification(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "plan-cloud-complete-cleanup":
        config = config_from_env(args.env_file, [])
        if not config.mp_base_url or not config.mp_token:
            parser.error("plan-cloud-complete-cleanup requires MP_BASE_URL and MP_API_TOKEN")
        report = plan_cloud_complete_cleanup(
            load_cloud_check_report(args.cloud_report),
            config.mp_base_url,
            config.mp_token,
            path_aliases=config.path_aliases,
            limit=args.limit,
            titles=args.title,
            timeout=args.timeout,
            required_target_prefix=args.required_target_prefix,
            forbidden_target_prefixes=args.forbidden_target_prefix,
            allow_multiple_hashes=args.allow_multiple_hashes,
            allow_multiple_source_roots=args.allow_multiple_source_roots,
        )
        rendered = render_cloud_complete_cleanup_plan(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "cloud-complete-cleanup-execute":
        if not args.approve_mp_cleanup:
            parser.error("cloud-complete-cleanup-execute requires --approve-mp-cleanup")
        config = config_from_env(args.env_file, [])
        if not config.mp_base_url or not config.mp_token:
            parser.error("cloud-complete-cleanup-execute requires MP_BASE_URL and MP_API_TOKEN")
        plan = load_optional_json_report(args.plan)
        if not isinstance(plan, dict):
            parser.error("cleanup plan must be a JSON object")
        report = execute_cloud_complete_cleanup_plan(
            plan,
            config.mp_base_url,
            config.mp_token,
            qb_base_url=config.qb_base_url,
            qb_user=config.qb_user,
            qb_pass=config.qb_pass,
            limit=args.limit,
            titles=args.title,
            timeout=args.timeout,
            continue_on_error=args.continue_on_error,
        )
        rendered = render_cloud_complete_cleanup_execute(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "cloud-hlink-cleanup-preview":
        config = config_from_env(args.env_file, [])
        if not config.qb_base_url:
            parser.error("cloud-hlink-cleanup-preview requires QB_BASE_URL")
        report = preview_cloud_hlink_cleanup(
            title=args.title,
            hlink_root=args.hlink_root,
            strm_root=args.strm_root,
            expected_tmdbid=args.expected_tmdbid,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            qb_base_url=config.qb_base_url,
            qb_user=config.qb_user,
            qb_pass=config.qb_pass,
            path_aliases=config.path_aliases,
            min_seed_days=args.min_seed_days,
            required_target_prefix=args.required_target_prefix,
            forbidden_target_prefixes=args.forbidden_target_prefix,
            mv3_base_url=config.mv3_base_url,
            mv3_token=config.mv3_token,
            cloud_media_path=args.cloud_media_path,
            cloud_media_folder_id=args.cloud_media_folder_id,
            cloud_media_storage=args.cloud_media_storage,
        )
        rendered = render_cloud_hlink_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "cloud-hlink-cleanup-execute":
        if not args.approve_delete:
            parser.error("cloud-hlink-cleanup-execute requires --approve-delete")
        config = config_from_env(args.env_file, [])
        if not config.qb_base_url:
            parser.error("cloud-hlink-cleanup-execute requires QB_BASE_URL")
        preview = load_optional_json_report(args.preview_report)
        if not isinstance(preview, dict):
            parser.error("preview report must be a JSON object")
        preview_hlink = preview.get("hlink") if isinstance(preview.get("hlink"), dict) else {}
        preview_qb = preview.get("qbittorrent") if isinstance(preview.get("qbittorrent"), dict) else {}
        preview_expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
        expected_hashes = sorted({str(item).lower() for item in args.expected_qb_hash if str(item)})
        preview_hashes = sorted({str(item).lower() for item in preview_qb.get("hashes", [])}) if isinstance(preview_qb.get("hashes"), list) else []
        if str(preview.get("title") or "") != args.expected_title:
            parser.error("cloud-hlink-cleanup-execute expected title mismatch")
        if int(preview_expected.get("tmdbid") or 0) != args.expected_tmdbid:
            parser.error("cloud-hlink-cleanup-execute expected TMDB ID mismatch")
        if str(preview_hlink.get("path") or "").rstrip("/") != args.expected_hlink_root.rstrip("/"):
            parser.error("cloud-hlink-cleanup-execute expected hlink root mismatch")
        if preview_hashes != expected_hashes:
            parser.error("cloud-hlink-cleanup-execute expected qB hashes mismatch")
        report = execute_cloud_hlink_cleanup(
            preview,
            config.qb_base_url,
            config.qb_user,
            config.qb_pass,
            path_aliases=config.path_aliases,
            mv3_base_url=config.mv3_base_url,
            mv3_token=config.mv3_token,
            timeout=args.timeout,
        )
        rendered = render_cloud_hlink_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "cloud-hlink-orphan-cleanup-preview":
        config = config_from_env(args.env_file, [])
        if not config.qb_base_url:
            parser.error("cloud-hlink-orphan-cleanup-preview requires QB_BASE_URL")
        report = preview_cloud_hlink_orphan_cleanup(
            title=args.title,
            hlink_root=args.hlink_root,
            strm_root=args.strm_root,
            expected_tmdbid=args.expected_tmdbid,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            qb_base_url=config.qb_base_url,
            qb_user=config.qb_user,
            qb_pass=config.qb_pass,
            path_aliases=config.path_aliases,
            required_target_prefix=args.required_target_prefix,
            forbidden_target_prefixes=args.forbidden_target_prefix,
            mv3_base_url=config.mv3_base_url,
            mv3_token=config.mv3_token,
            cloud_media_path=args.cloud_media_path,
            cloud_media_folder_id=args.cloud_media_folder_id,
            cloud_media_storage=args.cloud_media_storage,
        )
        rendered = render_cloud_hlink_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "cloud-hlink-orphan-cleanup-execute":
        if not args.approve_delete:
            parser.error("cloud-hlink-orphan-cleanup-execute requires --approve-delete")
        config = config_from_env(args.env_file, [])
        if not config.qb_base_url:
            parser.error("cloud-hlink-orphan-cleanup-execute requires QB_BASE_URL")
        preview = load_optional_json_report(args.preview_report)
        if not isinstance(preview, dict):
            parser.error("preview report must be a JSON object")
        preview_hlink = preview.get("hlink") if isinstance(preview.get("hlink"), dict) else {}
        preview_expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
        if str(preview.get("title") or "") != args.expected_title:
            parser.error("cloud-hlink-orphan-cleanup-execute expected title mismatch")
        if int(preview_expected.get("tmdbid") or 0) != args.expected_tmdbid:
            parser.error("cloud-hlink-orphan-cleanup-execute expected TMDB ID mismatch")
        if str(preview_hlink.get("path") or "").rstrip("/") != args.expected_hlink_root.rstrip("/"):
            parser.error("cloud-hlink-orphan-cleanup-execute expected hlink root mismatch")
        report = execute_cloud_hlink_orphan_cleanup(
            preview,
            config.qb_base_url,
            config.qb_user,
            config.qb_pass,
            path_aliases=config.path_aliases,
            mv3_base_url=config.mv3_base_url,
            mv3_token=config.mv3_token,
        )
        rendered = render_cloud_hlink_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "cloud-hlink-orphan-multiseason-cleanup-preview":
        config = config_from_env(args.env_file, [])
        if not config.qb_base_url:
            parser.error("cloud-hlink-orphan-multiseason-cleanup-preview requires QB_BASE_URL")
        report = preview_cloud_hlink_orphan_multiseason_cleanup(
            title=args.title,
            hlink_root=args.hlink_root,
            season_specs=args.season,
            expected_tmdbid=args.expected_tmdbid,
            qb_base_url=config.qb_base_url,
            qb_user=config.qb_user,
            qb_pass=config.qb_pass,
            path_aliases=config.path_aliases,
            required_target_prefix=args.required_target_prefix,
            forbidden_target_prefixes=args.forbidden_target_prefix,
            mv3_base_url=config.mv3_base_url,
            mv3_token=config.mv3_token,
            cloud_media_path=args.cloud_media_path,
            cloud_media_folder_id=args.cloud_media_folder_id,
            cloud_media_storage=args.cloud_media_storage,
        )
        rendered = render_cloud_hlink_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "cloud-hlink-orphan-multiseason-cleanup-execute":
        if not args.approve_delete:
            parser.error("cloud-hlink-orphan-multiseason-cleanup-execute requires --approve-delete")
        config = config_from_env(args.env_file, [])
        if not config.qb_base_url:
            parser.error("cloud-hlink-orphan-multiseason-cleanup-execute requires QB_BASE_URL")
        preview = load_optional_json_report(args.preview_report)
        if not isinstance(preview, dict):
            parser.error("preview report must be a JSON object")
        preview_hlink = preview.get("hlink") if isinstance(preview.get("hlink"), dict) else {}
        preview_expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
        preview_seasons = preview_expected.get("seasons") if isinstance(preview_expected.get("seasons"), list) else []
        expected_seasons = sorted({int(item) for item in args.expected_season if int(item) > 0})
        report_seasons = sorted({int(item.get("season") or 0) for item in preview_seasons if isinstance(item, dict) and int(item.get("season") or 0) > 0})
        if str(preview.get("title") or "") != args.expected_title:
            parser.error("cloud-hlink-orphan-multiseason-cleanup-execute expected title mismatch")
        if int(preview_expected.get("tmdbid") or 0) != args.expected_tmdbid:
            parser.error("cloud-hlink-orphan-multiseason-cleanup-execute expected TMDB ID mismatch")
        if str(preview_hlink.get("path") or "").rstrip("/") != args.expected_hlink_root.rstrip("/"):
            parser.error("cloud-hlink-orphan-multiseason-cleanup-execute expected hlink root mismatch")
        if report_seasons != expected_seasons:
            parser.error("cloud-hlink-orphan-multiseason-cleanup-execute expected seasons mismatch")
        report = execute_cloud_hlink_orphan_multiseason_cleanup(
            preview,
            config.qb_base_url,
            config.qb_user,
            config.qb_pass,
            path_aliases=config.path_aliases,
            mv3_base_url=config.mv3_base_url,
            mv3_token=config.mv3_token,
        )
        rendered = render_cloud_hlink_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "cloud-source-orphan-cleanup-preview":
        config = config_from_env(args.env_file, [])
        if not config.qb_base_url:
            parser.error("cloud-source-orphan-cleanup-preview requires QB_BASE_URL")
        report = preview_cloud_source_orphan_cleanup(
            title=args.title,
            source_root=args.source_root,
            strm_root=args.strm_root,
            expected_tmdbid=args.expected_tmdbid,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            qb_base_url=config.qb_base_url,
            qb_user=config.qb_user,
            qb_pass=config.qb_pass,
            path_aliases=config.path_aliases,
            required_target_prefix=args.required_target_prefix,
            forbidden_target_prefixes=args.forbidden_target_prefix,
            mv3_base_url=config.mv3_base_url,
            mv3_token=config.mv3_token,
            cloud_media_path=args.cloud_media_path,
            cloud_media_folder_id=args.cloud_media_folder_id,
            cloud_media_storage=args.cloud_media_storage,
        )
        rendered = render_cloud_hlink_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "cloud-source-orphan-cleanup-execute":
        if not args.approve_delete:
            parser.error("cloud-source-orphan-cleanup-execute requires --approve-delete")
        config = config_from_env(args.env_file, [])
        if not config.qb_base_url:
            parser.error("cloud-source-orphan-cleanup-execute requires QB_BASE_URL")
        preview = load_optional_json_report(args.preview_report)
        if not isinstance(preview, dict):
            parser.error("preview report must be a JSON object")
        preview_source = preview.get("source") if isinstance(preview.get("source"), dict) else {}
        preview_expected = preview.get("expected") if isinstance(preview.get("expected"), dict) else {}
        if str(preview.get("title") or "") != args.expected_title:
            parser.error("cloud-source-orphan-cleanup-execute expected title mismatch")
        if int(preview_expected.get("tmdbid") or 0) != args.expected_tmdbid:
            parser.error("cloud-source-orphan-cleanup-execute expected TMDB ID mismatch")
        if str(preview_source.get("path") or "").rstrip("/") != args.expected_source_root.rstrip("/"):
            parser.error("cloud-source-orphan-cleanup-execute expected source root mismatch")
        report = execute_cloud_source_orphan_cleanup(
            preview,
            config.qb_base_url,
            config.qb_user,
            config.qb_pass,
            path_aliases=config.path_aliases,
            mv3_base_url=config.mv3_base_url,
            mv3_token=config.mv3_token,
        )
        rendered = render_cloud_hlink_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "hlink-empty-root-cleanup":
        report = cleanup_empty_hlink_root(
            title=args.title,
            hlink_root=args.hlink_root,
            expected_tmdbid=args.expected_tmdbid,
            approve_delete=args.approve_delete,
        )
        rendered = render_cloud_hlink_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "strm-verify":
        report = verify_strm_paths(
            title=args.title,
            strm_roots=args.strm_root,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            required_target_prefix=args.required_target_prefix,
            forbidden_target_prefixes=args.forbidden_target_prefix,
        )
        rendered = render_strm_verification(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "strm-nfo-language-audit":
        report = audit_strm_nfo_language(
            strm_roots=args.strm_root,
            min_chinese_ratio=args.min_chinese_ratio,
            sample_limit=args.sample_limit,
            expected_nfo_count=args.expected_nfo_count,
        )
        rendered = render_strm_nfo_language_audit(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "strm-target-rewrite":
        report = rewrite_strm_targets(
            title=args.title,
            strm_root=args.strm_root,
            old_target_prefix=args.old_target_prefix,
            new_target_prefix=args.new_target_prefix,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            expected_rewrite_count=args.expected_rewrite_count,
            approve_write=args.approve_write,
        )
        rendered = render_strm_target_rewrite(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "strm-duplicate-cleanup":
        report = cleanup_duplicate_strm_root(
            title=args.title,
            correct_root=args.correct_root,
            duplicate_root=args.duplicate_root,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            required_target_prefix=args.required_target_prefix,
            approve_delete=args.approve_delete,
        )
        rendered = render_duplicate_strm_cleanup(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "emby-refresh-verify":
        config = config_from_env(args.env_file, [])
        if not config.emby_base_url or not config.emby_key:
            parser.error("emby-refresh-verify requires EMBY_BASE_URL and EMBY_API_KEY")
        report = refresh_and_verify_emby_library(
            config.emby_base_url,
            config.emby_key,
            title=args.title,
            stale_path_prefixes=args.stale_path_prefix,
            strm_path_prefixes=args.strm_path_prefix,
            expected_strm_records=args.expected_strm_records,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            library_db_path=args.library_db or config.emby_library_db_path,
            skip_refresh=args.skip_refresh,
            approve_full_library_refresh=args.approve_full_library_refresh,
            no_wait=args.no_wait,
            poll_seconds=args.poll_seconds,
            max_wait_seconds=args.max_wait_seconds,
            timeout=args.timeout,
        )
        rendered = render_emby_refresh_verify_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "emby-media-updated":
        config = config_from_env(args.env_file, [])
        if not config.emby_base_url or not config.emby_key:
            parser.error("emby-media-updated requires EMBY_BASE_URL and EMBY_API_KEY")
        report = notify_and_verify_emby_media_updated(
            config.emby_base_url,
            config.emby_key,
            title=args.title,
            updated_paths=args.updated_path,
            stale_path_prefixes=args.stale_path_prefix,
            strm_path_prefixes=args.strm_path_prefix,
            update_type=args.update_type,
            expected_strm_records=args.expected_strm_records,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            library_db_path=args.library_db or config.emby_library_db_path,
            timeout=args.timeout,
        )
        rendered = render_emby_media_updated_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "emby-item-refresh-verify":
        config = config_from_env(args.env_file, [])
        if not config.emby_base_url or not config.emby_key:
            parser.error("emby-item-refresh-verify requires EMBY_BASE_URL and EMBY_API_KEY")
        report = refresh_and_verify_emby_item(
            config.emby_base_url,
            config.emby_key,
            title=args.title,
            item_id=args.item_id,
            stale_path_prefixes=args.stale_path_prefix,
            strm_path_prefixes=args.strm_path_prefix,
            recursive=not args.not_recursive,
            metadata_refresh_mode=args.metadata_refresh_mode,
            image_refresh_mode=args.image_refresh_mode,
            replace_all_metadata=args.replace_all_metadata,
            replace_all_images=args.replace_all_images,
            expected_strm_records=args.expected_strm_records,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            library_db_path=args.library_db or config.emby_library_db_path,
            timeout=args.timeout,
        )
        rendered = render_emby_item_refresh_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "emby-delete-stale-paths":
        if not args.approve_delete:
            parser.error("emby-delete-stale-paths requires --approve-delete")
        config = config_from_env(args.env_file, [])
        if not config.emby_base_url or not config.emby_key:
            parser.error("emby-delete-stale-paths requires EMBY_BASE_URL and EMBY_API_KEY")
        report = delete_stale_emby_paths(
            config.emby_base_url,
            config.emby_key,
            title=args.title,
            stale_path_prefixes=args.stale_path_prefix,
            stale_host_prefix=args.stale_host_prefix,
            delete_scope=args.delete_scope,
            allow_season_duplicate_replacement=args.allow_season_duplicate_replacement,
            strm_filesystem_roots=args.strm_filesystem_root,
            required_target_prefix=args.required_target_prefix,
            forbidden_target_prefixes=args.forbidden_target_prefix,
            strm_path_prefixes=args.strm_path_prefix,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            library_db_path=args.library_db or config.emby_library_db_path,
            timeout=args.timeout,
        )
        rendered = render_emby_delete_stale_paths_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "emby-task-status":
        config = config_from_env(args.env_file, [])
        if not config.emby_base_url or not config.emby_key:
            parser.error("emby-task-status requires EMBY_BASE_URL and EMBY_API_KEY")
        report = inspect_emby_task_status(
            config.emby_base_url,
            config.emby_key,
            task_key=args.task_key,
            timeout=args.timeout,
        )
        rendered = render_emby_task_status_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "emby-task-wait-verify":
        config = config_from_env(args.env_file, [])
        if not config.emby_base_url or not config.emby_key:
            parser.error("emby-task-wait-verify requires EMBY_BASE_URL and EMBY_API_KEY")
        report = wait_for_emby_task_and_verify_paths(
            config.emby_base_url,
            config.emby_key,
            title=args.title,
            stale_path_prefixes=args.stale_path_prefix,
            strm_path_prefixes=args.strm_path_prefix,
            task_key=args.task_key,
            expected_strm_records=args.expected_strm_records,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            library_db_path=args.library_db or config.emby_library_db_path,
            poll_seconds=args.poll_seconds,
            max_wait_seconds=args.max_wait_seconds,
            timeout=args.timeout,
        )
        rendered = render_emby_task_wait_verify_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "emby-task-cancel":
        if not args.approve_cancel:
            parser.error("emby-task-cancel requires --approve-cancel")
        config = config_from_env(args.env_file, [])
        if not config.emby_base_url or not config.emby_key:
            parser.error("emby-task-cancel requires EMBY_BASE_URL and EMBY_API_KEY")
        report = cancel_emby_running_task(
            config.emby_base_url,
            config.emby_key,
            task_id=args.task_id,
            task_key=args.task_key,
            timeout=args.timeout,
        )
        rendered = render_emby_task_cancel_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "cloud-check":
        config = config_from_env(args.env_file, [])
        roots = args.strm_root or config.strm_roots
        output_format = args.format or config.output_format
        if args.top is not None:
            top = args.top
        elif output_format == "json":
            top = 0
        else:
            top = config.top
        identity_file = args.identity_file if args.identity_file is not None else config.identity_file
        report = cloud_check_from_scan_report(load_scan_report(args.scan_report), roots, top=top, identity_file=identity_file)
        rendered = render_cloud_check_report(report, output_format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "identity-resolve":
        config = config_from_env(args.env_file, [])
        if not config.mp_base_url or not config.mp_token:
            parser.error("identity-resolve requires MP_BASE_URL and MP_API_TOKEN")
        if not args.scan_report and not args.cloud_report:
            parser.error("identity-resolve requires --scan-report or --cloud-report")
        top = args.top if args.top is not None else 0
        if args.cloud_report:
            payload = resolve_identity_overrides_from_cloud_report(
                load_optional_json_report(args.cloud_report),
                config.mp_base_url,
                config.mp_token,
                top=top,
                output_path=args.output,
                timeout=args.timeout,
                progress=lambda message: print(message, flush=True),
            )
        else:
            payload = resolve_identity_overrides_from_scan_report(
                load_scan_report(args.scan_report),
                config.mp_base_url,
                config.mp_token,
                top=top,
                output_path=args.output,
                timeout=args.timeout,
                progress=lambda message: print(message, flush=True),
            )
        print(render_identity_overrides({"summary": payload["summary"], "warnings": payload["warnings"]}))
        return 0

    if args.command == "plan-mv3-transfer":
        statuses = args.status or ["cloud_strm_not_found"]
        plan = plan_mv3_transfers_from_cloud_report(load_cloud_check_report(args.cloud_report), statuses=statuses, top=args.top)
        rendered = render_mv3_transfer_plan(plan, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-restored-transfer-queue":
        report = plan_mv3_restored_transfer_queue(
            load_cloud_check_report(args.cloud_report),
            transfer_plan=load_optional_json_report(args.transfer_plan),
            historical_scan=load_optional_json_report(args.historical_scan),
            mv3_report=load_optional_json_report(args.mv3_report),
            top=args.top,
        )
        rendered = render_mv3_restored_transfer_queue(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "batch-plan":
        scan_report = load_optional_json_report(args.scan_report) if args.scan_report else None
        if scan_report is None and not args.cloud_report:
            config = config_from_env(args.env_file, args.media_root)
            config.output_format = "json"
            scan_report = scan(config).to_dict()

        cloud_report = load_optional_json_report(args.cloud_report) if args.cloud_report else None
        if cloud_report is None:
            if not isinstance(scan_report, dict):
                parser.error("batch-plan requires --cloud-report or --scan-report/--media-root")
            config = config_from_env(args.env_file, [])
            cloud_report = cloud_check_from_scan_report(
                scan_report,
                args.strm_root or config.strm_roots,
                identity_file=args.identity_file or config.identity_file,
            ).to_dict()

        transfer_plan = load_optional_json_report(args.transfer_plan) if args.transfer_plan else None
        if transfer_plan is None:
            transfer_plan = plan_mv3_transfers_from_cloud_report(cloud_report)

        share_search_plans = [
            plan
            for plan in (load_optional_json_report(path) for path in args.share_search_plan)
            if isinstance(plan, dict)
        ]
        cleanup_preview_reports = [
            plan
            for plan in (load_optional_json_report(path) for path in args.cleanup_preview_report)
            if isinstance(plan, dict)
        ]
        report = build_batch_plan(
            cloud_report=cloud_report,
            transfer_plan=transfer_plan,
            share_search_plans=share_search_plans,
            cleanup_preview_reports=cleanup_preview_reports,
            scan_report=scan_report,
            cloud_root=args.cloud_root,
            mv3_strm_root=args.mv3_strm_root,
            host_strm_root=args.host_strm_root,
            emby_strm_root=args.emby_strm_root,
            env_file=args.env_file or "",
            min_candidate_score=args.min_candidate_score,
            max_auto_size_delta=args.max_auto_size_delta,
            required_target_prefix=args.required_target_prefix,
            forbidden_target_prefixes=args.forbidden_target_prefix,
            limit=args.limit,
        )
        rendered = render_batch_plan(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "batch-review-report":
        batch_plan = load_optional_json_report(args.batch_plan)
        if not isinstance(batch_plan, dict):
            parser.error("batch-review-report requires a valid --batch-plan JSON report")
        share_preview_reports = [
            report
            for report in (load_optional_json_report(path) for path in args.share_preview_report)
            if isinstance(report, dict)
        ]
        transfer_run_reports = [
            report
            for report in (load_optional_json_report(path) for path in args.transfer_run_report)
            if isinstance(report, dict)
        ]
        finalize_run_reports = [
            report
            for report in (load_optional_json_report(path) for path in args.finalize_run_report)
            if isinstance(report, dict)
        ]
        post_cleanup_reports = [
            report
            for report in (load_optional_json_report(path) for path in args.post_cleanup_report)
            if isinstance(report, dict)
        ]
        report = build_batch_review_report(
            batch_plan,
            share_preview_reports=share_preview_reports,
            transfer_run_reports=transfer_run_reports,
            finalize_run_reports=finalize_run_reports,
            post_cleanup_reports=post_cleanup_reports,
        )
        rendered = render_batch_review_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "extra-source-media-plan":
        finalize_report = load_optional_json_report(args.finalize_run_report)
        if not isinstance(finalize_report, dict):
            parser.error("extra-source-media-plan requires a valid --finalize-run-report JSON report")
        report = build_extra_source_media_plan(
            finalize_report,
            env_file=args.env_file,
            target_dir=args.target_dir,
            strm_dir=args.strm_dir,
            storage=args.storage,
            timeout=args.timeout,
        )
        rendered = render_extra_source_media_plan(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "batch-share-preview":
        batch_plan = load_optional_json_report(args.batch_plan)
        if not isinstance(batch_plan, dict):
            parser.error("batch-share-preview requires a valid --batch-plan JSON report")
        config = None
        if args.execute_preview:
            config = config_from_env(args.env_file, [])
            if not config.mv3_base_url or not config.mv3_token:
                parser.error("batch-share-preview --execute-preview requires MV3_BASE_URL and MV3_API_TOKEN")
        report = build_batch_share_preview_plan(
            batch_plan,
            env_file=args.env_file,
            buckets=args.bucket or None,
            min_candidate_score=args.min_candidate_score,
            allowed_best_blockers=args.allowed_best_blocker or None,
            limit=args.limit,
            execute_preview=args.execute_preview,
            base_url=config.mv3_base_url if config else "",
            token=config.mv3_token if config else "",
            channels=args.channel,
            storage=args.storage,
            timeout=args.timeout,
            preview_output_dir=args.preview_output_dir,
            max_nested_depth=args.max_nested_depth,
            preview_func=preview_mv3_share if args.execute_preview else None,
        )
        rendered = render_batch_share_preview_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "batch-share-receive-plan":
        preview_report = load_optional_json_report(args.batch_share_preview_report)
        if not isinstance(preview_report, dict):
            parser.error("batch-share-receive-plan requires a valid --batch-share-preview-report JSON report")
        report = build_batch_share_receive_plan(
            preview_report,
            env_file=args.env_file,
            target_path=args.target_path,
            storage=args.storage,
            limit=args.limit,
        )
        rendered = render_batch_share_receive_plan(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "batch-transfer-run":
        receive_plan = load_optional_json_report(args.receive_plan)
        if not isinstance(receive_plan, dict):
            parser.error("batch-transfer-run requires a valid --receive-plan JSON report")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("batch-transfer-run requires MV3_BASE_URL and MV3_API_TOKEN")
        report = run_batch_transfer(
            receive_plan,
            output_dir=args.output_dir,
            config=config,
            limit=args.limit,
            title_filters=args.title,
            approve_receive=args.approve_receive,
            approve_transfer=args.approve_transfer,
            target_path=args.target_path,
            organize_target_dir=args.organize_target_dir,
            strm_dir=args.strm_dir,
            storage=args.storage,
            timeout=args.timeout,
            transfer_timeout=args.transfer_timeout,
        )
        rendered = render_batch_transfer_run(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "batch-finalize-plan":
        batch_plan = load_optional_json_report(args.batch_plan)
        if not isinstance(batch_plan, dict):
            parser.error("batch-finalize-plan requires a valid --batch-plan JSON report")
        report = build_batch_finalize_plan(
            batch_plan,
            env_file=args.env_file,
            cloud_root=args.cloud_root,
            host_strm_root=args.host_strm_root,
            mp_strm_root=args.mp_strm_root,
            service_strm_root=args.service_strm_root,
            required_target_prefix=args.required_target_prefix,
            forbidden_target_prefixes=args.forbidden_target_prefix,
            limit=args.limit,
        )
        rendered = render_batch_finalize_plan(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "batch-finalize-run":
        finalize_plan = load_optional_json_report(args.finalize_plan)
        if not isinstance(finalize_plan, dict):
            parser.error("batch-finalize-run requires a valid --finalize-plan JSON report")
        config = config_from_env(args.env_file, [])
        report = run_batch_finalize(
            finalize_plan,
            output_dir=args.output_dir,
            config=config,
            limit=args.limit,
            title_filters=args.title,
            continue_on_error=args.continue_on_error,
            execute_scrape=args.execute_scrape,
            approve_cloud_duplicate_delete=args.approve_cloud_duplicate_delete,
            approve_emby_stale_delete=args.approve_emby_stale_delete,
            approve_delete=args.approve_delete,
            min_seed_days=args.min_seed_days,
            cloud_media_storage=args.cloud_media_storage,
            timeout=args.timeout,
            scrape_timeout=args.scrape_timeout,
            nfo_min_chinese_ratio=args.nfo_min_chinese_ratio,
            nfo_sample_limit=args.nfo_sample_limit,
        )
        rendered = render_batch_finalize_run(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "batch-pipeline":
        scan_report = load_optional_json_report(args.scan_report) if args.scan_report else None
        cloud_report = load_optional_json_report(args.cloud_report) if args.cloud_report else None
        transfer_plan = load_optional_json_report(args.transfer_plan) if args.transfer_plan else None
        share_preview_report = load_optional_json_report(args.share_preview_report) if args.share_preview_report else None
        share_search_plans = [
            report
            for report in (load_optional_json_report(path) for path in args.share_search_plan)
            if isinstance(report, dict)
        ]
        cleanup_preview_reports = [
            report
            for report in (load_optional_json_report(path) for path in args.cleanup_preview_report)
            if isinstance(report, dict)
        ]
        config = config_from_env(args.env_file, args.media_root)
        if args.execute_share_search and (not config.mv3_base_url or not config.mv3_token):
            parser.error("batch-pipeline --execute-share-search requires MV3_BASE_URL and MV3_API_TOKEN")
        if args.execute_preview and (not config.mv3_base_url or not config.mv3_token):
            parser.error("batch-pipeline --execute-preview requires MV3_BASE_URL and MV3_API_TOKEN")
        if args.run_transfer_stage and (not config.mv3_base_url or not config.mv3_token):
            parser.error("batch-pipeline --run-transfer-stage requires MV3_BASE_URL and MV3_API_TOKEN")
        report = run_batch_pipeline(
            output_dir=args.output_dir,
            config=config,
            env_file=args.env_file,
            run_id=args.run_id,
            scan_report=scan_report,
            cloud_report=cloud_report,
            transfer_plan=transfer_plan,
            share_search_plans=share_search_plans,
            share_preview_report=share_preview_report if isinstance(share_preview_report, dict) else None,
            cleanup_preview_reports=cleanup_preview_reports,
            media_roots=args.media_root,
            strm_roots=args.strm_root,
            identity_file=args.identity_file,
            cloud_root=args.cloud_root,
            mv3_strm_root=args.mv3_strm_root,
            host_strm_root=args.host_strm_root,
            mp_strm_root=args.mp_strm_root,
            emby_strm_root=args.emby_strm_root,
            min_candidate_score=args.min_candidate_score,
            max_auto_size_delta=args.max_auto_size_delta,
            required_target_prefix=args.required_target_prefix,
            forbidden_target_prefixes=args.forbidden_target_prefix,
            execute_share_search=args.execute_share_search,
            share_search_limit=args.share_search_limit,
            share_search_offset=args.share_search_offset,
            share_search_max_candidates=args.share_search_max_candidates,
            share_search_channels=args.channel,
            share_search_timeout=args.share_search_timeout,
            execute_preview=args.execute_preview,
            preview_limit=args.preview_limit,
            preview_buckets=args.preview_bucket or None,
            preview_min_candidate_score=args.preview_min_candidate_score,
            preview_allowed_best_blockers=args.preview_allowed_best_blocker or None,
            preview_storage=args.preview_storage,
            preview_timeout=args.preview_timeout,
            max_nested_depth=args.max_nested_depth,
            run_transfer_stage=args.run_transfer_stage,
            approve_receive=args.approve_receive,
            approve_transfer=args.approve_transfer,
            transfer_target_path=args.transfer_target_path,
            organize_target_dir=args.organize_target_dir,
            transfer_strm_dir=args.transfer_strm_dir,
            transfer_storage=args.transfer_storage,
            transfer_timeout=args.transfer_timeout,
            organize_timeout=args.organize_timeout,
            refresh_after_transfer=not args.no_refresh_after_transfer,
            run_finalize_stage=args.run_finalize_stage,
            finalize_limit=args.finalize_limit,
            finalize_titles=args.title,
            continue_on_error=args.continue_on_error,
            execute_scrape=args.execute_scrape,
            approve_cloud_duplicate_delete=args.approve_cloud_duplicate_delete,
            approve_emby_stale_delete=args.approve_emby_stale_delete,
            approve_delete=args.approve_delete,
            min_seed_days=args.min_seed_days,
            cloud_media_storage=args.cloud_media_storage,
            finalize_timeout=args.finalize_timeout,
            scrape_timeout=args.scrape_timeout,
            nfo_min_chinese_ratio=args.nfo_min_chinese_ratio,
            nfo_sample_limit=args.nfo_sample_limit,
        )
        rendered = render_batch_pipeline_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "plan-mv3-preview":
        manifest = plan_mv3_preview_manifest(
            load_mv3_transfer_plan(args.transfer_plan),
            instances_report=load_optional_json_report(args.instances_report),
            capabilities_report=load_optional_json_report(args.capabilities_report),
            limit=args.limit,
            cloud_root=args.cloud_root,
            instance=args.instance,
        )
        rendered = render_mv3_preview_manifest(manifest, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "plan-mv3-offline":
        config = config_from_env(args.env_file, [])
        if args.qb_report:
            qb_payload = load_optional_json_report(args.qb_report)
            qb_torrents = qb_payload.get("torrents", qb_payload) if isinstance(qb_payload, dict) else qb_payload
        else:
            if not config.qb_base_url:
                parser.error("plan-mv3-offline requires QB_BASE_URL or --qb-report")
            qb_torrents = fetch_qb_torrents(config.qb_base_url, config.qb_user, config.qb_pass)
        if not isinstance(qb_torrents, list):
            parser.error("qB torrent source must be a JSON list or {'torrents': [...]}")
        manifest = plan_mv3_offline_manifest(
            load_mv3_transfer_plan(args.transfer_plan),
            qb_torrents,
            instances_report=load_optional_json_report(args.instances_report),
            limit=args.limit,
            cloud_root=args.cloud_root,
            strm_root=args.strm_root,
            min_seed_days=args.min_seed_days,
            destination_mode=args.destination_mode,
        )
        rendered = render_mv3_offline_manifest(manifest, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-offline-add-one":
        if not args.approve_offline_add:
            parser.error("mv3-offline-add-one requires --approve-offline-add")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-offline-add-one requires MV3_BASE_URL and MV3_API_TOKEN")
        if args.qb_report:
            qb_payload = load_optional_json_report(args.qb_report)
            qb_torrents = qb_payload.get("torrents", qb_payload) if isinstance(qb_payload, dict) else qb_payload
        else:
            if not config.qb_base_url:
                parser.error("mv3-offline-add-one requires QB_BASE_URL or --qb-report")
            qb_torrents = fetch_qb_torrents(config.qb_base_url, config.qb_user, config.qb_pass)
        if not isinstance(qb_torrents, list):
            parser.error("qB torrent source must be a JSON list or {'torrents': [...]}")
        report = _execute_mv3_offline_add_one(
            load_optional_json_report(args.manifest),
            qb_torrents,
            config.mv3_base_url,
            config.mv3_token,
            priority=args.priority,
            expected_title=args.expected_title,
            timeout=args.timeout,
        )
        rendered = render_mv3_offline_add_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-ensure-115-path":
        if not args.approve_create_path:
            parser.error("mv3-ensure-115-path requires --approve-create-path")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-ensure-115-path requires MV3_BASE_URL and MV3_API_TOKEN")
        storage = args.storage or "115-default"
        report = ensure_mv3_115_path(
            config.mv3_base_url,
            config.mv3_token,
            args.target_path,
            storage=storage,
            timeout=args.timeout,
        )
        rendered = render_mv3_ensure_path_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-offline-status-one":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-offline-status-one requires MV3_BASE_URL and MV3_API_TOKEN")
        storage = args.storage or "115-default"
        report = check_mv3_offline_task(
            config.mv3_base_url,
            config.mv3_token,
            args.info_hash,
            target_folder_id=args.target_folder_id,
            target_path=args.target_path,
            storage=storage,
            timeout=args.timeout,
        )
        rendered = render_mv3_offline_status_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-offline-status-plan":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-offline-status-plan requires MV3_BASE_URL and MV3_API_TOKEN")
        report = check_mv3_offline_manifest_status(
            config.mv3_base_url,
            config.mv3_token,
            load_optional_json_report(args.manifest),
            priorities=args.priority,
            storage=args.storage,
            timeout=args.timeout,
        )
        rendered = render_mv3_offline_manifest_status_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-resource-search":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-resource-search requires MV3_BASE_URL and MV3_API_TOKEN")
        report = search_mv3_resources(
            config.mv3_base_url,
            config.mv3_token,
            args.keyword,
            channels=args.channel,
            timeout=args.timeout,
        )
        rendered = render_mv3_resource_search_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "plan-mv3-share-search":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("plan-mv3-share-search requires MV3_BASE_URL and MV3_API_TOKEN")
        transfer_plan = load_mv3_transfer_plan(args.transfer_plan)
        raw_items = [item for item in transfer_plan.get("items", []) if isinstance(item, dict)]
        start = max(0, args.offset)
        stop = start + args.limit if args.limit > 0 else len(raw_items)
        selected_items = raw_items[start:stop]
        search_reports = {}
        checkpoint_path = args.checkpoint_output or (args.output if args.checkpoint_each else None)
        for item_index, item in enumerate(selected_items, start=1):
            title = str(item.get("title") or "")
            if not title:
                continue
            search_reports[title] = _combined_mv3_search_report(
                config.mv3_base_url,
                config.mv3_token,
                _share_search_keywords(item),
                channels=args.channel,
                timeout=args.timeout,
            )
            if checkpoint_path and args.checkpoint_each:
                partial_plan = plan_mv3_share_search_from_transfer_plan(
                    transfer_plan,
                    search_reports,
                    limit=item_index,
                    max_candidates=args.max_candidates,
                    offset=args.offset,
                )
                partial_plan["checkpoint"] = {
                    "enabled": True,
                    "completed_items": item_index,
                    "planned_items": len(selected_items),
                    "current_title": title,
                    "complete": item_index == len(selected_items),
                }
                _write_text_output(
                    checkpoint_path,
                    render_mv3_share_search_plan(partial_plan, args.format),
                )
        plan = plan_mv3_share_search_from_transfer_plan(
            transfer_plan,
            search_reports,
            limit=args.limit,
            max_candidates=args.max_candidates,
            offset=args.offset,
        )
        if checkpoint_path and not args.checkpoint_each:
            _write_text_output(checkpoint_path, render_mv3_share_search_plan(plan, args.format))
        rendered = render_mv3_share_search_plan(plan, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-share-preview":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-share-preview requires MV3_BASE_URL and MV3_API_TOKEN")
        report = preview_mv3_share(
            config.mv3_base_url,
            config.mv3_token,
            args.keyword,
            selection_index=args.selection_index,
            browse_cid=args.browse_cid,
            browse_limit=args.browse_limit,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            expected_episodes=_parse_int_list_args(args.expected_episode),
            channels=args.channel,
            expected_title_contains=args.expected_title_contains,
            storage=args.storage,
            timeout=args.timeout,
        )
        rendered = render_mv3_share_preview_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-share-receive-one":
        if not args.approve_receive:
            parser.error("mv3-share-receive-one requires --approve-receive")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-share-receive-one requires MV3_BASE_URL and MV3_API_TOKEN")
        report = receive_mv3_share(
            config.mv3_base_url,
            config.mv3_token,
            args.keyword,
            selection_index=args.selection_index,
            browse_index=args.browse_index,
            browse_cid=args.browse_cid,
            browse_limit=args.browse_limit,
            receive_all_files=args.receive_all_files,
            receive_selected_folder=args.receive_selected_folder,
            verified_folder_browse_report=load_optional_json_report(args.verified_folder_browse_report) if args.verified_folder_browse_report else None,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            channels=args.channel,
            expected_title_contains=args.expected_title_contains,
            target_path=args.target_path,
            storage=args.storage,
            timeout=args.timeout,
        )
        rendered = render_mv3_share_receive_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-organize-scan-source":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-organize-scan-source requires MV3_BASE_URL and MV3_API_TOKEN")
        report = scan_mv3_organize_source(
            config.mv3_base_url,
            config.mv3_token,
            args.source_path,
            source_file_id=args.source_file_id,
            storage=args.storage,
            is_cloud_source=not args.local_source,
            is_dir=not args.file,
            timeout=args.timeout,
        )
        rendered = render_mv3_organize_scan_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-organize-transfer-from-browse":
        if not args.approve_transfer:
            parser.error("mv3-organize-transfer-from-browse requires --approve-transfer")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-organize-transfer-from-browse requires MV3_BASE_URL and MV3_API_TOKEN")
        browse_report = load_optional_json_report(args.browse_report)
        if not isinstance(browse_report, dict):
            parser.error("browse report must be a JSON object")
        report = execute_mv3_organize_transfer_from_browse_report(
            config.mv3_base_url,
            config.mv3_token,
            browse_report,
            target_dir=args.target_dir,
            strm_dir=args.strm_dir,
            tmdb_id=args.tmdb_id,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            expected_episodes=_parse_int_list_args(args.expected_episode),
            mode=args.mode,
            is_cloud_target=not args.local_target,
            background=args.background,
            source_path_override=args.source_path_override,
            timeout=args.timeout,
        )
        rendered = render_mv3_organize_transfer_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-organize-transfer-from-scan":
        if not args.approve_transfer:
            parser.error("mv3-organize-transfer-from-scan requires --approve-transfer")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-organize-transfer-from-scan requires MV3_BASE_URL and MV3_API_TOKEN")
        scan_report = load_optional_json_report(args.scan_report)
        if not isinstance(scan_report, dict):
            parser.error("scan report must be a JSON object")
        report = execute_mv3_organize_transfer_from_scan_report(
            config.mv3_base_url,
            config.mv3_token,
            scan_report,
            target_dir=args.target_dir,
            strm_dir=args.strm_dir,
            tmdb_id=args.tmdb_id,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            expected_episodes=_parse_int_list_args(args.expected_episode),
            mode=args.mode,
            is_cloud_target=not args.local_target,
            background=args.background,
            timeout=args.timeout,
        )
        rendered = render_mv3_organize_transfer_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-organize-transfer-from-local-map":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-organize-transfer-from-local-map requires MV3_BASE_URL and MV3_API_TOKEN")
        mapping_report = load_optional_json_report(args.mapping_file)
        if not isinstance(mapping_report, dict):
            parser.error("mapping file must be a JSON object")
        report = execute_mv3_organize_transfer_from_confirmed_local_map(
            config.mv3_base_url,
            config.mv3_token,
            mapping_report,
            target_dir=args.target_dir,
            strm_dir=args.strm_dir,
            tmdb_id=args.tmdb_id,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            expected_episodes=_parse_int_list_args(args.expected_episode),
            mode=args.mode,
            is_cloud_target=not args.local_target,
            background=args.background,
            dry_run=not args.approve_transfer,
            timeout=args.timeout,
        )
        rendered = render_mv3_organize_transfer_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") or report.get("dry_run") and not report.get("blockers") else 1

    if args.command == "mv3-strm-generate":
        if not args.approve_generate:
            parser.error("mv3-strm-generate requires --approve-generate")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-strm-generate requires MV3_BASE_URL and MV3_API_TOKEN")
        report = generate_mv3_strm(
            config.mv3_base_url,
            config.mv3_token,
            source_dir=args.source_dir,
            target_dir=args.target_dir,
            storage=args.storage,
            cloud=not args.local_source,
            incremental=not args.full,
            overwrite=args.overwrite,
            organize=args.organize,
            openlist=args.openlist,
            enable_primary_category=not args.disable_primary_category,
            enable_secondary_category=not args.disable_secondary_category,
            template=args.template,
            allow_organize=args.allow_organize,
            timeout=args.timeout,
        )
        rendered = render_mv3_strm_generate_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-strm-records":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-strm-records requires MV3_BASE_URL and MV3_API_TOKEN")
        report = list_mv3_strm_records(
            config.mv3_base_url,
            config.mv3_token,
            keyword=args.keyword,
            record_ids=_parse_int_list_args(args.record_id),
            source=args.source,
            path_dir=args.path_dir,
            missing_pickcode=None if args.missing_pickcode is None else args.missing_pickcode == "true",
            use_regex=None if args.use_regex is None else args.use_regex == "true",
            page=args.page,
            page_size=args.page_size,
            timeout=args.timeout,
        )
        rendered = render_mv3_strm_records_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-strm-records-materialize":
        if not args.approve_write:
            parser.error("mv3-strm-records-materialize requires --approve-write")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-strm-records-materialize requires MV3_BASE_URL and MV3_API_TOKEN")
        record_ids = _parse_int_list_args(args.record_id)
        expected_record_ids = _parse_int_list_args(args.expected_record_id)
        if record_ids != expected_record_ids:
            parser.error(f"record id safety mismatch: got {record_ids}, expected {expected_record_ids}")
        report = materialize_mv3_strm_records(
            config.mv3_base_url,
            config.mv3_token,
            record_ids=record_ids,
            expected_record_ids=expected_record_ids,
            expected_strm_prefix=args.expected_strm_prefix,
            expected_source_prefix=args.expected_source_prefix,
            host_strm_prefix=args.host_strm_prefix,
            rewrite_strm_prefix=args.rewrite_strm_prefix,
            keyword=args.keyword,
            overwrite=args.overwrite,
            timeout=args.timeout,
        )
        rendered = render_mv3_strm_records_materialize_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-strm-records-redirect":
        if not args.approve_redirect:
            parser.error("mv3-strm-records-redirect requires --approve-redirect")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-strm-records-redirect requires MV3_BASE_URL and MV3_API_TOKEN")
        record_ids = _parse_int_list_args(args.record_id)
        expected_record_ids = _parse_int_list_args(args.expected_record_id)
        if record_ids != expected_record_ids:
            parser.error(f"record id safety mismatch: got {record_ids}, expected {expected_record_ids}")
        report = redirect_mv3_strm_records(
            config.mv3_base_url,
            config.mv3_token,
            record_ids=record_ids,
            expected_record_ids=expected_record_ids,
            old_prefix=args.old_prefix,
            new_prefix=args.new_prefix,
            expected_source_prefix=args.expected_source_prefix,
            keyword=args.keyword,
            strm_dir=args.strm_dir,
            timeout=args.timeout,
        )
        rendered = render_mv3_strm_records_redirect_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-strm-records-regenerate":
        if not args.approve_regenerate:
            parser.error("mv3-strm-records-regenerate requires --approve-regenerate")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-strm-records-regenerate requires MV3_BASE_URL and MV3_API_TOKEN")
        record_ids = _parse_int_list_args(args.record_id)
        expected_record_ids = _parse_int_list_args(args.expected_record_id)
        if expected_record_ids and record_ids != expected_record_ids:
            parser.error(f"record id safety mismatch: got {record_ids}, expected {expected_record_ids}")
        report = regenerate_mv3_strm_records(
            config.mv3_base_url,
            config.mv3_token,
            record_ids=record_ids,
            timeout=args.timeout,
        )
        rendered = render_mv3_strm_records_regenerate_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-cloud-browse":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-cloud-browse requires MV3_BASE_URL and MV3_API_TOKEN")
        report = browse_mv3_cloud_folder(
            config.mv3_base_url,
            config.mv3_token,
            folder_id=args.folder_id,
            path=args.path,
            storage=args.storage,
            limit=args.limit,
            timeout=args.timeout,
        )
        rendered = render_mv3_cloud_browse_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-normalize-received-season":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-normalize-received-season requires MV3_BASE_URL and MV3_API_TOKEN")
        report = normalize_mv3_received_season_folder(
            config.mv3_base_url,
            config.mv3_token,
            source_path=args.source_path,
            title=args.title,
            tmdb_id=args.tmdb_id,
            season=args.season,
            year=args.year,
            staging_root=args.staging_root,
            storage=args.storage,
            limit=args.limit,
            timeout=args.timeout,
            approve_move=args.approve_move,
        )
        rendered = render_mv3_received_season_normalize_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-cloud-search":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-cloud-search requires MV3_BASE_URL and MV3_API_TOKEN")
        report = search_mv3_cloud_files(
            config.mv3_base_url,
            config.mv3_token,
            keyword=args.keyword,
            cid=args.cid,
            storage=args.storage,
            timeout=args.timeout,
        )
        rendered = render_mv3_cloud_search_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-cloud-search-plan":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-cloud-search-plan requires MV3_BASE_URL and MV3_API_TOKEN")
        report = search_mv3_cloud_files_for_transfer_plan(
            config.mv3_base_url,
            config.mv3_token,
            load_mv3_transfer_plan(args.transfer_plan),
            offset=args.offset,
            limit=args.limit,
            keyword_limit=args.keyword_limit,
            cid=args.cid,
            storage=args.storage,
            timeout=args.timeout,
        )
        rendered = render_mv3_cloud_search_plan_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-cloud-index-plan":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-cloud-index-plan requires MV3_BASE_URL and MV3_API_TOKEN")
        report = index_mv3_cloud_root_for_transfer_plan(
            config.mv3_base_url,
            config.mv3_token,
            load_mv3_transfer_plan(args.transfer_plan),
            root_folder_id=args.root_folder_id,
            root_path=args.root_path,
            offset=args.offset,
            limit=args.limit,
            storage=args.storage,
            browse_limit=args.browse_limit,
            timeout=args.timeout,
        )
        rendered = render_mv3_cloud_index_plan_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-cloud-media-sidecar-verify":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-cloud-media-sidecar-verify requires MV3_BASE_URL and MV3_API_TOKEN")
        report = verify_mv3_cloud_media_sidecars(
            config.mv3_base_url,
            config.mv3_token,
            folder_id=args.folder_id,
            path=args.path,
            storage=args.storage,
            limit=args.limit,
            max_depth=args.max_depth,
            timeout=args.timeout,
        )
        rendered = render_mv3_cloud_media_sidecar_verify_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-cloud-media-sidecar-batch-verify":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-cloud-media-sidecar-batch-verify requires MV3_BASE_URL and MV3_API_TOKEN")
        report = batch_verify_mv3_cloud_media_sidecars(
            config.mv3_base_url,
            config.mv3_token,
            root_folder_id=args.root_folder_id,
            root_path=args.root_path,
            storage=args.storage,
            limit=args.limit,
            max_depth=args.max_depth,
            start_index=args.start_index,
            title_limit=args.title_limit,
            timeout=args.timeout,
        )
        rendered = render_mv3_cloud_media_sidecar_batch_verify_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-cloud-media-sidecar-cleanup":
        if args.approve_delete and args.expected_delete_count < 0:
            parser.error("mv3-cloud-media-sidecar-cleanup requires --expected-delete-count with --approve-delete")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-cloud-media-sidecar-cleanup requires MV3_BASE_URL and MV3_API_TOKEN")
        report = cleanup_mv3_cloud_media_sidecars(
            config.mv3_base_url,
            config.mv3_token,
            folder_id=args.folder_id,
            path=args.path,
            storage=args.storage,
            limit=args.limit,
            max_depth=args.max_depth,
            timeout=args.timeout,
            approve_delete=args.approve_delete,
            expected_delete_count=args.expected_delete_count,
        )
        rendered = render_mv3_cloud_media_sidecar_cleanup_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-cloud-duplicate-video-cleanup":
        if args.approve_delete and args.expected_delete_count < 0:
            parser.error("mv3-cloud-duplicate-video-cleanup requires --expected-delete-count with --approve-delete")
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-cloud-duplicate-video-cleanup requires MV3_BASE_URL and MV3_API_TOKEN")
        report = cleanup_mv3_cloud_duplicate_videos(
            config.mv3_base_url,
            config.mv3_token,
            season_path=args.season_path,
            strm_root=args.strm_root,
            expected_episode_count=args.expected_episode_count,
            folder_id=args.folder_id,
            storage=args.storage,
            limit=args.limit,
            timeout=args.timeout,
            approve_delete=args.approve_delete,
            expected_delete_count=args.expected_delete_count,
        )
        rendered = render_mv3_cloud_duplicate_video_cleanup_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-repair-wrong-root":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-repair-wrong-root requires MV3_BASE_URL and MV3_API_TOKEN")
        report = repair_mv3_wrong_root(
            config.mv3_base_url,
            config.mv3_token,
            wrong_root=args.wrong_root,
            correct_root=args.correct_root,
            strm_root=args.strm_root,
            storage=args.storage,
            title_filter=args.title_filter,
            season=args.season,
            approve_move=args.approve_move,
            approve_delete_duplicates=args.approve_delete_duplicates,
            approve_delete_empty=args.approve_delete_empty,
            limit=args.limit,
            timeout=args.timeout,
        )
        rendered = render_mv3_wrong_root_repair_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-repair-wrong-root-direct-season-pair":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("mv3-repair-wrong-root-direct-season-pair requires MV3_BASE_URL and MV3_API_TOKEN")
        report = repair_mv3_wrong_root_direct_season_pair(
            config.mv3_base_url,
            config.mv3_token,
            wrong_root=args.wrong_root,
            correct_root=args.correct_root,
            strm_root=args.strm_root,
            season=args.season,
            storage=args.storage,
            title_filter=args.title_filter,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            expected_rewrite_count=args.expected_rewrite_count,
            approve_repair=args.approve_repair,
            limit=args.limit,
            timeout=args.timeout,
        )
        rendered = render_mv3_wrong_root_direct_season_pair_repair_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-check":
        config = config_from_env(args.env_file, [])
        report = probe_mv3(config.mv3_base_url, config.mv3_token, paths=args.path or None)
        rendered = render_mv3_probe_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-capabilities":
        config = config_from_env(args.env_file, [])
        report = inspect_mv3_capabilities(config.mv3_base_url, config.mv3_token, include_all=args.include_all)
        rendered = render_mv3_capabilities_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    if args.command == "mv3-instances":
        config = config_from_env(args.env_file, [])
        report = inspect_mv3_instances(
            config.mv3_base_url,
            config.mv3_token,
            paths=args.path or None,
            timeout=args.timeout,
            retry_failed_once=args.retry_failed_once,
        )
        rendered = render_mv3_instances_report(report, args.format)
        if args.output:
            _write_text_output(args.output, rendered)
        else:
            print(rendered)
        return 0

    parser.error("unknown command")
    return 2


def _execute_mv3_offline_add_one(
    manifest,
    qb_torrents,
    mv3_base_url: str,
    mv3_token: str,
    priority: int,
    expected_title: str,
    timeout: int = 30,
):
    if not isinstance(manifest, dict):
        raise SystemExit("manifest must be a JSON object")
    items = manifest.get("items")
    if not isinstance(items, list):
        raise SystemExit("manifest items must be a list")
    selected = next((item for item in items if isinstance(item, dict) and int(item.get("priority") or 0) == priority), None)
    if not selected:
        raise SystemExit(f"manifest priority not found: {priority}")
    title = str(selected.get("title") or "")
    if title != expected_title:
        raise SystemExit(f"expected title mismatch: manifest has {title!r}")
    matches = _qb_matches_for_manifest_selection(selected, qb_torrents)
    magnets = [str(item.get("magnet_uri") or "").strip() for item in matches if str(item.get("magnet_uri") or "").strip()]
    if len(magnets) != 1:
        raise SystemExit(f"expected exactly one qB magnet for first execution, got {len(magnets)}")
    context = manifest.get("mv3_context") if isinstance(manifest.get("mv3_context"), dict) else {}
    storage = str(context.get("cloud_drive_slug") or "")
    proposed_destination = str(selected.get("proposed_cloud_destination") or "")
    destination = str(selected.get("offline_wp_path") or proposed_destination)
    if not storage:
        raise SystemExit("manifest missing mv3 cloud drive slug")
    if not destination:
        raise SystemExit("manifest missing proposed cloud destination")
    result = add_mv3_offline_task(
        mv3_base_url,
        mv3_token,
        magnets,
        storage=storage,
        wp_path=destination,
        timeout=timeout,
    )
    result["selection"] = {
        "priority": priority,
        "title": title,
        "tmdbid": selected.get("tmdbid") or 0,
        "season": selected.get("season") or 0,
        "expected_count": selected.get("expected_count") or 0,
        "qb_match_count": len(matches),
        "qb_magnet_count": len(magnets),
        "offline_wp_path": destination,
        "proposed_cloud_destination": proposed_destination,
        "offline_destination_mode": selected.get("offline_destination_mode") or "",
    }
    return result


def _qb_matches_for_manifest_selection(selected, qb_torrents):
    from .transfer_plan import _match_qb_torrents_for_transfer_item

    wanted_hashes = set()
    for item in selected.get("qb_matches", []) if isinstance(selected.get("qb_matches"), list) else []:
        if isinstance(item, dict) and item.get("hash"):
            wanted_hashes.add(str(item.get("hash")).lower())
    if wanted_hashes:
        return [
            torrent
            for torrent in qb_torrents
            if isinstance(torrent, dict) and str(torrent.get("hash") or "").lower() in wanted_hashes
        ]
    return _match_qb_torrents_for_transfer_item(selected, qb_torrents)


if __name__ == "__main__":
    raise SystemExit(main())
