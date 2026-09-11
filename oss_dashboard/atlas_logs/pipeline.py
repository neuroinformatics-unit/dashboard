"""Fetch new access-log objects, aggregate them, and update the summary.

Incrementality is a single cursor: the largest log-object key processed so
far, stored in ``atlas_usage_state.json``. S3 server-access-log keys are
``YYYY-MM-DD-HH-MM-SS-<hash>`` and sort by delivery time, so on the next
run we simply list everything after that key (``StartAfter``). Late-arriving
logs whose key sorts *below* the cursor are the only blind spot; a
``--full-rebuild`` reprocesses everything from scratch.
"""

from __future__ import annotations

import gzip
import itertools
import logging
from collections import deque
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from oss_dashboard.atlas_logs.constants import (
    ATLAS_KEY,
    ATLAS_PARQUET_PATH,
    COUNTRY_KEY,
    COUNTRY_PARQUET_PATH,
    DOWNLOAD_OPERATIONS,
    OK_STATUSES,
    S3_MAX_WORKERS,
    STATE_PATH,
    TOOL_KEY,
    TOOL_PARQUET_PATH,
)
from oss_dashboard.atlas_logs.geoip import CountryLookup, load_country_lookup
from oss_dashboard.atlas_logs.parser import (
    classify_client,
    classify_key,
    parse_line,
)
from oss_dashboard.atlas_logs.store import (
    Counts,
    counts_to_frame,
    load_state,
    load_summary,
    merge_summary,
    write_state,
    write_summary,
)

logger = logging.getLogger(__name__)

ObjectSource = Iterator[tuple[str, str]]


def _decode(raw: bytes) -> str:
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def iter_local_objects(
    directory: Path, start_after: str, limit: int | None
) -> ObjectSource:
    """Yield ``(key, text)`` for local log files sorted past the cursor."""
    files = sorted(
        p for p in directory.iterdir() if p.is_file() and p.name != ".DS_Store"
    )
    count = 0
    for path in files:
        if path.name <= start_after:
            continue
        yield path.name, _decode(path.read_bytes())
        count += 1
        if limit is not None and count >= limit:
            return


def iter_s3_objects(
    bucket: str,
    region: str,
    prefix: str,
    start_after: str,
    limit: int | None,
    max_workers: int = S3_MAX_WORKERS,
) -> ObjectSource:
    """Yield ``(key, text)`` for S3 objects listed after ``start_after``.

    Access logs are many small objects, so a serial GET-per-object is
    latency-bound (~4 objects/s). The bodies are therefore fetched through a
    thread pool. Only a bounded window of downloads is ever in flight, so
    neither the key listing nor the bodies are fully materialised in memory,
    and results are still yielded in key order.
    """
    import boto3
    from botocore.config import Config as BotoConfig

    # boto3 clients are thread-safe for API calls, but the default connection
    # pool (10) would throttle the workers, so size it to match.
    client = boto3.client(
        "s3",
        region_name=region,
        config=BotoConfig(
            max_pool_connections=max_workers,
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    )

    def iter_keys() -> Iterator[str]:
        paginator = client.get_paginator("list_objects_v2")
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if start_after:
            kwargs["StartAfter"] = start_after
        for page in paginator.paginate(**kwargs):
            for obj in page.get("Contents", []):
                yield obj["Key"]

    def fetch(key: str) -> tuple[str, str]:
        body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        return key, _decode(body)

    keys = iter_keys()
    if limit is not None:
        keys = itertools.islice(keys, limit)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        in_flight: deque[Future[tuple[str, str]]] = deque(
            pool.submit(fetch, key)
            for key in itertools.islice(keys, max_workers * 2)
        )
        while in_flight:
            yield in_flight.popleft().result()
            next_key = next(keys, None)
            if next_key is not None:
                in_flight.append(pool.submit(fetch, next_key))


def _bump(counts: Counts, key: tuple[str, ...], nbytes: int) -> None:
    bucket = counts.setdefault(key, [0, 0])
    bucket[0] += 1
    bucket[1] += nbytes


def accumulate(
    text: str,
    atlas_counts: Counts,
    country_counts: Counts,
    tool_counts: Counts,
    country_lookup: CountryLookup,
) -> tuple[int, int]:
    """Fold an object's lines into the three count maps.

    Keyed by ``(date, atlas, resource)``, ``(date, country)`` and
    ``(date, tool)`` respectively - the breakdowns are kept separate, not
    crossed. Returns ``(parsed, skipped)``.
    """
    parsed = 0
    skipped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        record = parse_line(line)
        if record is None:
            skipped += 1
            continue
        parsed += 1

        if (
            record.operation not in DOWNLOAD_OPERATIONS
            or record.http_status not in OK_STATUSES
        ):
            continue

        atlas, resource = classify_key(record.key)
        country = country_lookup.lookup(record.remote_ip)
        tool = classify_client(record.referer, record.user_agent)

        _bump(atlas_counts, (record.date, atlas, resource), record.bytes_sent)
        _bump(country_counts, (record.date, country), record.bytes_sent)
        _bump(tool_counts, (record.date, tool), record.bytes_sent)

    return parsed, skipped


def run(
    *,
    bucket: str,
    region: str,
    prefix: str = "",
    local_dir: Path | None = None,
    full_rebuild: bool = False,
    max_objects: int | None = None,
    max_workers: int = S3_MAX_WORKERS,
    atlas_path: Path = ATLAS_PARQUET_PATH,
    country_path: Path = COUNTRY_PARQUET_PATH,
    tool_path: Path = TOOL_PARQUET_PATH,
    state_path: Path = STATE_PATH,
    country_lookup: CountryLookup | None = None,
) -> dict:
    """Run one incremental (or full) update of the atlas-usage summaries."""
    state: dict[str, Any] = {"last_key": "", "objects_processed": 0}
    if not full_rebuild:
        state = load_state(state_path)
    start_after: str = state.get("last_key", "") or ""
    prev_objects = int(state.get("objects_processed", 0) or 0)

    missing = Path("/nonexistent")
    atlas_existing = load_summary(
        missing if full_rebuild else atlas_path, ATLAS_KEY
    )
    country_existing = load_summary(
        missing if full_rebuild else country_path, COUNTRY_KEY
    )
    tool_existing = load_summary(
        missing if full_rebuild else tool_path, TOOL_KEY
    )

    if country_lookup is None:
        country_lookup = load_country_lookup()

    source: ObjectSource
    if local_dir is not None:
        source = iter_local_objects(Path(local_dir), start_after, max_objects)
    else:
        source = iter_s3_objects(
            bucket, region, prefix, start_after, max_objects, max_workers
        )

    atlas_counts: Counts = {}
    country_counts: Counts = {}
    tool_counts: Counts = {}
    last_key = start_after
    n_objects = 0
    total_parsed = 0
    total_skipped = 0

    for key, text in source:
        parsed, skipped = accumulate(
            text, atlas_counts, country_counts, tool_counts, country_lookup
        )
        total_parsed += parsed
        total_skipped += skipped
        n_objects += 1
        if key > last_key:
            last_key = key
        if n_objects % 5000 == 0:
            logger.info("Processed %d objects...", n_objects)

    atlas_merged = merge_summary(
        atlas_existing, counts_to_frame(atlas_counts, ATLAS_KEY), ATLAS_KEY
    )
    country_merged = merge_summary(
        country_existing,
        counts_to_frame(country_counts, COUNTRY_KEY),
        COUNTRY_KEY,
    )
    tool_merged = merge_summary(
        tool_existing, counts_to_frame(tool_counts, TOOL_KEY), TOOL_KEY
    )
    write_summary(atlas_merged, atlas_path)
    write_summary(country_merged, country_path)
    write_summary(tool_merged, tool_path)
    write_state(
        last_key,
        objects_processed=prev_objects + n_objects,
        lines_parsed=total_parsed,
        lines_skipped=total_skipped,
        path=state_path,
    )

    downloads = int(atlas_merged["requests"].sum()) if len(atlas_merged) else 0
    result = {
        "objects": n_objects,
        "lines_parsed": total_parsed,
        "lines_skipped": total_skipped,
        "atlas_rows": len(atlas_merged),
        "country_rows": len(country_merged),
        "tool_rows": len(tool_merged),
        "last_key": last_key,
        "downloads": downloads,
        "bytes_sent": (
            int(atlas_merged["bytes_sent"].sum()) if len(atlas_merged) else 0
        ),
    }
    logger.info("Run complete: %s", result)
    return result
