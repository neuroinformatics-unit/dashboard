"""CLI entry point: ``python -m oss_dashboard.atlas_logs``."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import yaml
from dotenv import load_dotenv

from oss_dashboard.atlas_logs.constants import S3_MAX_WORKERS
from oss_dashboard.atlas_logs.pipeline import run


def _load_atlas_config() -> dict:
    config_file = Path(__file__).resolve().parents[1] / "config.yml"
    with open(config_file) as handle:
        config = yaml.safe_load(handle) or {}
    return config.get("atlasLogs", {})


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m oss_dashboard.atlas_logs",
        description=(
            "Fetch new BrainGlobe atlas S3 access-log objects and append "
            "per-day/atlas/country totals to the committed Parquet summary."
        ),
    )
    parser.add_argument(
        "--local-dir",
        type=Path,
        help="Parse log files from this directory instead of S3 "
        "(for backfills). The fetch cursor is still honoured and updated.",
    )
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help="Ignore the cursor and existing summary; reprocess everything.",
    )
    parser.add_argument(
        "--max-objects",
        type=int,
        default=None,
        help="Stop after this many log objects (useful for testing).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=S3_MAX_WORKERS,
        help=(
            "Parallel S3 downloads (default: %(default)s). Access logs are "
            "many small objects, so fetching them is latency-bound."
        ),
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Debug logging."
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    load_dotenv()

    atlas_config = _load_atlas_config()
    bucket = atlas_config.get("bucket", "")
    region = atlas_config.get("region", "us-west-2")
    prefix = atlas_config.get("prefix", "") or ""

    if args.local_dir is None and not bucket:
        parser.error(
            "config.yml is missing atlasLogs.bucket and --local-dir was "
            "not given; nothing to read."
        )

    result = run(
        bucket=bucket,
        region=region,
        prefix=prefix,
        local_dir=args.local_dir,
        full_rebuild=args.full_rebuild,
        max_objects=args.max_objects,
        max_workers=args.workers,
    )

    print(
        f"\nProcessed {result['objects']:,} log objects "
        f"({result['lines_parsed']:,} lines, "
        f"{result['lines_skipped']:,} unparsable).\n"
        f"{result['downloads']:,} downloads, "
        f"{result['bytes_sent'] / 1e12:.3f} TB served.\n"
        f"Summaries: {result['atlas_rows']:,} atlas rows, "
        f"{result['country_rows']:,} country rows, "
        f"{result['tool_rows']:,} tool rows.\n"
        f"Cursor: {result['last_key'] or '(none)'}"
    )


if __name__ == "__main__":
    main()
