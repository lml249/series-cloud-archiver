from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from .cloud_check import cloud_check_from_scan_report, load_scan_report, render_cloud_check_report
from .config import config_from_env, db_path_from_env
from .identity import render_identity_overrides, resolve_identity_overrides_from_scan_report
from .orchestrator import evaluate, list_status, plan_cleanup, status_detail
from .reporting import render_report
from .scanner import scan
from .storage import StoredSeries


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
    return parser


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

    parser.error("unknown command")
    return 2
