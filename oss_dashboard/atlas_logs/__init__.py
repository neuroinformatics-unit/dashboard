"""Incremental analytics for the public BrainGlobe atlas S3 bucket.

The public atlas data is served from an AWS S3 bucket with server access
logging enabled. Those raw access logs are delivered to a dedicated log
bucket. This package reads *new* log objects on each run (tracked with a
cursor), parses them, maps client IPs to countries, and appends
per-day / per-atlas / per-country totals to a Parquet file that is
committed to the repository and rendered by ``atlas-usage.qmd``.

Entry point::

    python -m oss_dashboard.atlas_logs            # incremental S3 fetch
    python -m oss_dashboard.atlas_logs --local-dir ~/data/brainglobe-logs
    python -m oss_dashboard.atlas_logs --full-rebuild
"""

from oss_dashboard.atlas_logs.constants import (
    ATLAS_PARQUET_PATH,
    COUNTRY_PARQUET_PATH,
    STATE_PATH,
    TOOL_PARQUET_PATH,
)
from oss_dashboard.atlas_logs.parser import (
    classify_client,
    classify_key,
    event_date,
    parse_line,
)
from oss_dashboard.atlas_logs.pipeline import run

__all__ = [
    "ATLAS_PARQUET_PATH",
    "COUNTRY_PARQUET_PATH",
    "TOOL_PARQUET_PATH",
    "STATE_PATH",
    "classify_client",
    "classify_key",
    "event_date",
    "parse_line",
    "run",
]
