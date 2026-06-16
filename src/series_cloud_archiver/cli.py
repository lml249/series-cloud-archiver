from __future__ import annotations

import argparse
from pathlib import Path
from typing import List, Optional

from .config import config_from_env
from .reporting import render_report
from .scanner import scan


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
    scan_parser.add_argument("--emby", action="store_true", help="Use Emby evidence when configured")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "scan":
        config = config_from_env(args.env_file, args.media_root)
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
        if args.emby:
            config.include_emby = True

        report = scan(config)
        rendered = render_report(report, config.output_format)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        else:
            print(rendered)
        return 0

    parser.error("unknown command")
    return 2
