#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["boto3[crt]", "pyarrow"]
# ///
"""Append new raw S3 access logs to a local Parquet mirror.

``uv run scripts/sync_logs.py brainglobe-logs/``

Fetches every log object listed after the newest key already mirrored and
stores its bytes untouched as ``(key, body)`` rows in zstd Parquet files,
the folder ``python -m oss_dashboard.atlas_logs --local-dir <dir>`` reads.
One file per day (``2026-11-03.parquet``; log keys start with their date),
rows in key order, so the folder sorts in key order too. New rows for a day
that already has a file are appended by rewriting it to a temp file and
swapping it in, every ``--batch`` rows, so an interrupted run loses at most
one batch and resumes after the last key written.

Not part of the package: just a local mirror, so a full rebuild doesn't
need to refetch every log from S3.
"""

from __future__ import annotations

import argparse
import itertools
import os
import queue
import threading
from collections import deque
from collections.abc import Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

SCHEMA = pa.schema([("key", pa.string()), ("body", pa.binary())])
Row = tuple[str, bytes]


def last_key(out: Path) -> str:
    """The newest key already mirrored in ``out`` ('' if none)."""
    parts = sorted(out.glob("*.parquet"))
    if not parts:
        return ""
    last = pq.ParquetFile(parts[-1])
    keys = last.read_row_group(last.num_row_groups - 1, columns=["key"])
    return str(keys["key"][-1])


def _append(path: Path, rows: list[Row]) -> None:
    """Append ``rows`` to the day file at ``path``, replacing it in one go."""
    table = pa.table([list(col) for col in zip(*rows)], schema=SCHEMA)
    if path.exists():
        table = pa.concat_tables([pq.read_table(path, schema=SCHEMA), table])
    tmp = path.with_suffix(".partial")
    pq.write_table(
        table,
        tmp,
        compression="zstd",
        row_group_size=10_000,  # bounds the reader's memory per batch
    )
    os.replace(tmp, path)  # only complete files ever match *.parquet


def write(out: Path, rows: Iterable[Row], batch: int = 10_000) -> int:
    """Append ``rows`` (in key order) to per-day Parquet files in ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    written = 0
    for day, day_rows in itertools.groupby(rows, key=lambda r: r[0][:10]):
        while chunk := list(itertools.islice(day_rows, batch)):
            _append(out / f"{day}.parquet", chunk)
            written += len(chunk)
            print(
                f"{written:,} new objects (up to {chunk[-1][0]})", flush=True
            )
    return written


def _keys(client: Any, bucket: str, start_after: str) -> Iterator[str]:
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, StartAfter=start_after):
        for obj in page.get("Contents", []):
            yield obj["Key"]


def _background(items: Iterator[str], size: int = 50_000) -> Iterator[str]:
    """Run ``items`` on its own thread, so listing overlaps fetching."""
    q: queue.Queue[Any] = queue.Queue(size)
    done = object()

    def fill() -> None:
        try:
            for item in items:
                q.put(item)
        except BaseException as error:  # surfaced in the consumer below
            q.put(error)
        q.put(done)

    threading.Thread(target=fill, daemon=True).start()
    while (item := q.get()) is not done:
        if isinstance(item, BaseException):
            raise item
        yield item


def s3_rows(
    client: Any, bucket: str, start_after: str, workers: int = 128
) -> Iterator[Row]:
    """Yield ``(key, body)`` for objects after ``start_after``, in order.

    A sliding window of GETs, taken in key order, so the pool never idles
    waiting on one slow request and rows still come out in key order
    (which is what makes resuming from the last key safe).
    """
    keys = _background(_keys(client, bucket, start_after))

    def fetch(key: str) -> Row:
        return key, client.get_object(Bucket=bucket, Key=key)["Body"].read()

    with ThreadPoolExecutor(workers) as pool:
        in_flight: deque[Future[Row]] = deque(
            pool.submit(fetch, k) for k in itertools.islice(keys, workers * 4)
        )
        while in_flight:
            yield in_flight.popleft().result()
            if (key := next(keys, None)) is not None:
                in_flight.append(pool.submit(fetch, key))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, help="Parquet folder to extend")
    parser.add_argument("--bucket", default="brainglobe-logs")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--workers", type=int, default=128)
    parser.add_argument("--batch", type=int, default=10_000)
    args = parser.parse_args()

    import boto3
    from botocore.config import Config

    s3 = boto3.client(
        "s3",
        region_name=args.region,
        config=Config(
            max_pool_connections=args.workers + 1,
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    )
    start = last_key(args.out)
    rows = s3_rows(s3, args.bucket, start, workers=args.workers)
    total = write(args.out, rows, batch=args.batch)
    print(f"Added {total:,} objects to {args.out}")
