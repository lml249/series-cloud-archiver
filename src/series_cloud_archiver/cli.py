from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from .cloud_check import cloud_check_from_scan_report, load_scan_report, render_cloud_check_report
from .cloud_cleanup import (
    execute_cloud_complete_cleanup_plan,
    plan_cloud_complete_cleanup,
    render_cloud_complete_cleanup_execute,
    render_cloud_complete_cleanup_plan,
)
from .cleanup_verify import (
    render_mp_cleanup_verification,
    render_strm_verification,
    verify_mp_cleanup_from_services,
    verify_strm_paths,
)
from .config import config_from_env, db_path_from_env
from .dotqb_cleanup import cleanup_orphan_dotqb_roots, render_dotqb_orphan_cleanup
from .emby import (
    delete_stale_emby_paths,
    refresh_and_verify_emby_library,
    render_emby_delete_stale_paths_report,
    render_emby_refresh_verify_report,
)
from .identity import render_identity_overrides, resolve_identity_overrides_from_scan_report
from .moviepilot import (
    execute_mp_cleanup_from_preview_report,
    render_mp_cleanup_execute_report,
    mp_cleanup_preview_from_transfer_history,
    render_mp_cleanup_preview,
)
from .mv3 import (
    add_mv3_offline_task,
    browse_mv3_cloud_folder,
    ensure_mv3_115_path,
    check_mv3_offline_task,
    execute_mv3_organize_transfer_from_browse_report,
    generate_mv3_strm,
    inspect_mv3_capabilities,
    inspect_mv3_instances,
    list_mv3_strm_records,
    materialize_mv3_strm_records,
    probe_mv3,
    regenerate_mv3_strm_records,
    render_mv3_capabilities_report,
    render_mv3_cloud_browse_report,
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
    render_mv3_strm_records_report,
    render_mv3_strm_records_regenerate_report,
    render_mv3_wrong_root_repair_report,
    preview_mv3_share,
    receive_mv3_share,
    repair_mv3_wrong_root,
    scan_mv3_organize_source,
    search_mv3_resources,
)
from .orchestrator import evaluate, list_status, plan_cleanup, status_detail
from .qbittorrent import audit_dotqb_files, fetch_qb_torrents, render_dotqb_audit_report
from .reporting import render_report
from .scanner import scan
from .storage import StoredSeries
from .transfer_plan import (
    DEFAULT_CLOUD_ROOT,
    load_cloud_check_report,
    load_mv3_transfer_plan,
    load_optional_json_report,
    plan_mv3_offline_manifest,
    plan_mv3_preview_manifest,
    plan_mv3_share_search_from_transfer_plan,
    plan_mv3_transfers_from_cloud_report,
    render_mv3_offline_manifest,
    render_mv3_preview_manifest,
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

    mp_cleanup_parser = subcommands.add_parser("mp-cleanup-preview", help="Readonly MoviePilot cleanup preview from transfer history")
    mp_cleanup_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    mp_cleanup_parser.add_argument("--title", required=True, help="MoviePilot transfer history title to query")
    mp_cleanup_parser.add_argument("--expected-title", default="", help="Safety filter: exact MP title expected")
    mp_cleanup_parser.add_argument("--expected-tmdbid", type=int, default=0, help="Safety filter: expected TMDB ID when present in MP")
    mp_cleanup_parser.add_argument("--expected-hash-prefix", default="", help="Safety filter: expected qB hash prefix")
    mp_cleanup_parser.add_argument("--keep-source", action="store_true", help="Preview without deletesrc=true")
    mp_cleanup_parser.add_argument("--keep-dest", action="store_true", help="Preview without deletedest=true")
    mp_cleanup_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    mp_cleanup_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    mp_cleanup_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    mp_cleanup_exec_parser = subcommands.add_parser("mp-cleanup-execute", help="Execute approved MoviePilot cleanup from a validated preview report")
    mp_cleanup_exec_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    mp_cleanup_exec_parser.add_argument("--preview-report", required=True, help="JSON report from mp-cleanup-preview")
    mp_cleanup_exec_parser.add_argument("--expected-title", required=True, help="Safety check: exact title expected")
    mp_cleanup_exec_parser.add_argument("--expected-tmdbid", type=int, required=True, help="Safety check: expected TMDB ID")
    mp_cleanup_exec_parser.add_argument("--expected-hash-prefix", required=True, help="Safety check: qB hash prefix")
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
    mp_cleanup_exec_parser.add_argument("--continue-on-error", action="store_true", help="Continue deleting remaining MP records if one record fails")
    mp_cleanup_exec_parser.add_argument("--allow-multiple-hashes", action="store_true", help="Allow preview warning multiple_download_hashes when all other episode/title/TMDB gates pass")
    mp_cleanup_exec_parser.add_argument("--allow-multiple-source-roots", action="store_true", help="Allow preview warning multiple_source_roots when destination root is unique and all other gates pass")
    mp_cleanup_exec_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    mp_cleanup_exec_parser.add_argument("--approve-mp-cleanup", action="store_true", help="Required: actually send MoviePilot DELETE requests")
    mp_cleanup_exec_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    mp_cleanup_exec_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    mp_cleanup_verify_parser = subcommands.add_parser("mp-cleanup-verify", help="Readonly post-cleanup verification for MP/qB/filesystem/STRM")
    mp_cleanup_verify_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    mp_cleanup_verify_parser.add_argument("--title", required=True, help="MoviePilot transfer history title to query")
    mp_cleanup_verify_parser.add_argument("--expected-title", default="", help="Safety filter: exact MP title expected")
    mp_cleanup_verify_parser.add_argument("--expected-tmdbid", type=int, default=0, help="Safety filter: expected TMDB ID when present in MP")
    mp_cleanup_verify_parser.add_argument("--expected-hash-prefix", default="", help="Safety filter: qB hash prefix that should be gone")
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

    emby_refresh_parser = subcommands.add_parser("emby-refresh-verify", help="Trigger Emby library refresh and verify stale local paths are gone")
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
    emby_refresh_parser.add_argument("--no-wait", action="store_true", help="Trigger Emby refresh but do not wait for the full library scan to finish")
    emby_refresh_parser.add_argument("--poll-seconds", type=float, default=10.0, help="Seconds between refresh task polls")
    emby_refresh_parser.add_argument("--max-wait-seconds", type=int, default=900, help="Maximum seconds to wait for Emby scan completion")
    emby_refresh_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    emby_refresh_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    emby_refresh_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    emby_delete_parser = subcommands.add_parser("emby-delete-stale-paths", help="Delete approved stale Emby root items after STRM replacement verifies")
    emby_delete_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    emby_delete_parser.add_argument("--title", required=True, help="Series title for reporting")
    emby_delete_parser.add_argument("--stale-path-prefix", action="append", required=True, help="Old Emby/container path prefix that should be removed; can be repeated")
    emby_delete_parser.add_argument("--stale-host-prefix", required=True, help="Host path for the same stale root; must no longer exist. Comma-separated when multiple stale prefixes are used")
    emby_delete_parser.add_argument("--strm-path-prefix", action="append", required=True, help="Replacement STRM Emby/container path prefix; can be repeated")
    emby_delete_parser.add_argument("--expected-episode-count", type=int, required=True, help="Expected distinct STRM episode count")
    emby_delete_parser.add_argument("--expected-episode-min", type=int, required=True, help="Expected first STRM episode number")
    emby_delete_parser.add_argument("--expected-episode-max", type=int, required=True, help="Expected last STRM episode number")
    emby_delete_parser.add_argument("--library-db", default="", help="Optional Emby library.db path for exact readonly precheck")
    emby_delete_parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds")
    emby_delete_parser.add_argument("--approve-delete", action="store_true", help="Required: actually call Emby delete for stale root item ids")
    emby_delete_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    emby_delete_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

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
    identity_parser.add_argument("--scan-report", required=True, help="JSON report from scan/evaluate")
    identity_parser.add_argument("--output", required=True, help="Write identity override JSON to file")
    identity_parser.add_argument("--top", type=int, default=None, help="Maximum missing-identity candidates to resolve")

    transfer_parser = subcommands.add_parser("plan-mv3-transfer", help="Create a readonly MV3 transfer queue from cloud-check JSON")
    transfer_parser.add_argument("--cloud-report", required=True, help="JSON report from cloud-check")
    transfer_parser.add_argument("--status", action="append", default=[], help="Source status to include; defaults to cloud_strm_not_found")
    transfer_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    transfer_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")
    transfer_parser.add_argument("--top", type=int, default=0, help="Maximum transfer rows in report")

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
    offline_parser.add_argument("--min-seed-days", type=int, default=7, help="Minimum qB seed days to mark seed OK")
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
    share_search_plan_parser.add_argument("--max-candidates", type=int, default=5, help="Maximum ranked search candidates per row")
    share_search_plan_parser.add_argument("--channel", action="append", default=[], help="Optional channel filter; can be repeated")
    share_search_plan_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    share_search_plan_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    share_search_plan_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    share_preview_parser = subcommands.add_parser("mv3-share-preview", help="Preview one MV3 resource share without receiving it")
    share_preview_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    share_preview_parser.add_argument("--keyword", required=True, help="Search keyword")
    share_preview_parser.add_argument("--selection-index", type=int, default=1, help="1-based search result to parse/browse")
    share_preview_parser.add_argument("--browse-cid", default="", help="Optional share folder cid to browse instead of the share root")
    share_preview_parser.add_argument("--expected-title-contains", default="", help="Safety check: selected title must contain this text")
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
    share_receive_parser.add_argument("--receive-all-files", action="store_true", help="Receive every file in the current browsed share folder instead of one selected item")
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
    organize_transfer_parser.add_argument("--mode", choices=["move", "copy"], default="move", help="MV3 transfer mode")
    organize_transfer_parser.add_argument("--local-target", action="store_true", help="Treat target as local instead of cloud")
    organize_transfer_parser.add_argument("--background", action="store_true", help="Ask MV3 to run transfer in background")
    organize_transfer_parser.add_argument("--timeout", type=int, default=180, help="Per-request timeout in seconds")
    organize_transfer_parser.add_argument("--approve-transfer", action="store_true", help="Required: actually send one MV3 organize transfer request")
    organize_transfer_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    organize_transfer_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

    strm_generate_parser = subcommands.add_parser("mv3-strm-generate", help="Execute one approved MV3 STRM generation request")
    strm_generate_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    strm_generate_parser.add_argument("--source-dir", required=True, help="Cloud source media directory, e.g. /已整理/series/Demo/Season 1")
    strm_generate_parser.add_argument("--target-dir", required=True, help="Local/MV3 STRM output dir, e.g. /strm-root")
    strm_generate_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    strm_generate_parser.add_argument("--local-source", action="store_true", help="Treat source as local instead of cloud")
    strm_generate_parser.add_argument("--overwrite", action="store_true", help="Allow MV3 to overwrite existing STRM files")
    strm_generate_parser.add_argument("--full", action="store_true", help="Disable incremental mode")
    strm_generate_parser.add_argument("--organize", action="store_true", help="Ask MV3 to organize while generating STRM")
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
    strm_materialize_parser.add_argument("--overwrite", action="store_true", help="Allow overwriting existing STRM files")
    strm_materialize_parser.add_argument("--timeout", type=int, default=60, help="Per-request timeout in seconds")
    strm_materialize_parser.add_argument("--approve-write", action="store_true", help="Required: actually write STRM files from MV3 record content")
    strm_materialize_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    strm_materialize_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

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

    wrong_root_parser = subcommands.add_parser("mv3-repair-wrong-root", help="Dry-run or repair MV3 cloud files placed under a duplicated wrong root")
    wrong_root_parser.add_argument("--env-file", required=True, help="Local env file; never commit real values")
    wrong_root_parser.add_argument("--wrong-root", default="/已整理/series/series", help="Wrong duplicated cloud root")
    wrong_root_parser.add_argument("--correct-root", default="/已整理/series", help="Correct cloud series root")
    wrong_root_parser.add_argument("--strm-root", required=True, help="Local/DSM STRM series root used for target verification")
    wrong_root_parser.add_argument("--storage", default="115-default", help="MV3 cloud storage slug")
    wrong_root_parser.add_argument("--title-filter", default="", help="Optional substring filter for one title")
    wrong_root_parser.add_argument("--limit", type=int, default=1000, help="Maximum cloud folder items to request")
    wrong_root_parser.add_argument("--timeout", type=int, default=120, help="Per-request timeout in seconds")
    wrong_root_parser.add_argument("--approve-move", action="store_true", help="Allow moving media from wrong root to correct root when checks pass")
    wrong_root_parser.add_argument("--approve-delete-duplicates", action="store_true", help="Allow deleting duplicate wrong-root season folders when checks pass")
    wrong_root_parser.add_argument("--approve-delete-empty", action="store_true", help="Allow deleting empty wrong-root folders after checks pass")
    wrong_root_parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    wrong_root_parser.add_argument("--output", default=None, help="Write report to file instead of stdout")

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


def _parse_int_list_args(values: List[str]) -> List[int]:
    items = set()
    for value in values:
        for part in str(value or "").split(","):
            token = part.strip()
            if not token:
                continue
            items.add(int(token))
    return sorted(item for item in items if item > 0)


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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

    if args.command == "evaluate":
        config = apply_scan_overrides(config_from_env(args.env_file, args.media_root), args)
        db_path = args.db or db_path_from_env(args.env_file)
        report = evaluate(config, db_path)
        rendered = render_report(report, config.output_format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            include_deletesrc=not args.keep_source,
            include_deletedest=not args.keep_dest,
            timeout=args.timeout,
        )
        rendered = render_mp_cleanup_preview(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

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
            expected_hash_prefix=args.expected_hash_prefix,
            expected_record_count=args.expected_record_count,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            expected_episodes=args.expected_episodes,
            include_deletesrc=not args.keep_source,
            include_deletedest=not args.keep_dest,
            timeout=args.timeout,
            continue_on_error=args.continue_on_error,
            allow_multiple_hashes=args.allow_multiple_hashes,
            allow_multiple_source_roots=args.allow_multiple_source_roots,
        )
        rendered = render_mp_cleanup_execute_report(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

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
            expected_hash_prefix=args.expected_hash_prefix,
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            no_wait=args.no_wait,
            poll_seconds=args.poll_seconds,
            max_wait_seconds=args.max_wait_seconds,
            timeout=args.timeout,
        )
        rendered = render_emby_refresh_verify_report(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            strm_path_prefixes=args.strm_path_prefix,
            expected_episode_count=args.expected_episode_count,
            expected_episode_min=args.expected_episode_min,
            expected_episode_max=args.expected_episode_max,
            library_db_path=args.library_db or config.emby_library_db_path,
            timeout=args.timeout,
        )
        rendered = render_emby_delete_stale_paths_report(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "cloud-check":
        config = config_from_env(args.env_file, [])
        roots = args.strm_root or config.strm_roots
        top = args.top if args.top is not None else config.top
        output_format = args.format or config.output_format
        identity_file = args.identity_file if args.identity_file is not None else config.identity_file
        report = cloud_check_from_scan_report(load_scan_report(args.scan_report), roots, top=top, identity_file=identity_file)
        rendered = render_cloud_check_report(report, output_format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

    if args.command == "identity-resolve":
        config = config_from_env(args.env_file, [])
        if not config.mp_base_url or not config.mp_token:
            parser.error("identity-resolve requires MP_BASE_URL and MP_API_TOKEN")
        top = args.top if args.top is not None else 0
        payload = resolve_identity_overrides_from_scan_report(
            load_scan_report(args.scan_report),
            config.mp_base_url,
            config.mp_token,
            top=top,
            output_path=args.output,
            progress=print,
        )
        print(render_identity_overrides({"summary": payload["summary"], "warnings": payload["warnings"]}))
        return 0

    if args.command == "plan-mv3-transfer":
        statuses = args.status or ["cloud_strm_not_found"]
        plan = plan_mv3_transfers_from_cloud_report(load_cloud_check_report(args.cloud_report), statuses=statuses, top=args.top)
        rendered = render_mv3_transfer_plan(plan, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            min_seed_days=args.min_seed_days,
        )
        rendered = render_mv3_offline_manifest(manifest, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

    if args.command == "plan-mv3-share-search":
        config = config_from_env(args.env_file, [])
        if not config.mv3_base_url or not config.mv3_token:
            parser.error("plan-mv3-share-search requires MV3_BASE_URL and MV3_API_TOKEN")
        transfer_plan = load_mv3_transfer_plan(args.transfer_plan)
        raw_items = [item for item in transfer_plan.get("items", []) if isinstance(item, dict)]
        selected_items = raw_items[: args.limit if args.limit > 0 else len(raw_items)]
        search_reports = {}
        for item in selected_items:
            title = str(item.get("title") or "")
            if not title:
                continue
            search_reports[title] = search_mv3_resources(
                config.mv3_base_url,
                config.mv3_token,
                title,
                channels=args.channel,
                timeout=args.timeout,
            )
        plan = plan_mv3_share_search_from_transfer_plan(
            transfer_plan,
            search_reports,
            limit=args.limit,
            max_candidates=args.max_candidates,
        )
        rendered = render_mv3_share_search_plan(plan, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            channels=args.channel,
            expected_title_contains=args.expected_title_contains,
            timeout=args.timeout,
        )
        rendered = render_mv3_share_preview_report(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            receive_all_files=args.receive_all_files,
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            mode=args.mode,
            is_cloud_target=not args.local_target,
            background=args.background,
            source_path_override=args.source_path_override,
            timeout=args.timeout,
        )
        rendered = render_mv3_organize_transfer_report(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

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
            timeout=args.timeout,
        )
        rendered = render_mv3_strm_generate_report(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            keyword=args.keyword,
            overwrite=args.overwrite,
            timeout=args.timeout,
        )
        rendered = render_mv3_strm_records_materialize_report(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

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
            approve_move=args.approve_move,
            approve_delete_duplicates=args.approve_delete_duplicates,
            approve_delete_empty=args.approve_delete_empty,
            limit=args.limit,
            timeout=args.timeout,
        )
        rendered = render_mv3_wrong_root_repair_report(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0 if report.get("ok") else 1

    if args.command == "mv3-check":
        config = config_from_env(args.env_file, [])
        report = probe_mv3(config.mv3_base_url, config.mv3_token, paths=args.path or None)
        rendered = render_mv3_probe_report(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

    if args.command == "mv3-capabilities":
        config = config_from_env(args.env_file, [])
        report = inspect_mv3_capabilities(config.mv3_base_url, config.mv3_token, include_all=args.include_all)
        rendered = render_mv3_capabilities_report(report, args.format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
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
    destination = str(selected.get("proposed_cloud_destination") or "")
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
        "proposed_cloud_destination": destination,
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
