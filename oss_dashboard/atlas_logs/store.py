"""Read/write the committed summary Parquets and the fetch-cursor JSON.

The read/merge/write helpers are generic over the grouping key so the same
code serves both the ``date x atlas x resource`` table and the
``date x country`` table.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from oss_dashboard.atlas_logs.constants import (
    STATE_PATH,
    SUMMARY_MEASURES,
)

logger = logging.getLogger(__name__)

# A run accumulates counts keyed by a tuple of the grouping-key values,
# with ``[requests, bytes_sent]`` as the value.
Counts = dict[tuple[str, ...], list[int]]


def empty_summary(key: list[str]) -> pd.DataFrame:
    """An empty summary frame with the given key columns plus measures."""
    frame = pd.DataFrame({name: pd.Series(dtype="object") for name in key})
    for name in SUMMARY_MEASURES:
        frame[name] = pd.Series(dtype="int64")
    return frame


def load_summary(path: Path, key: list[str]) -> pd.DataFrame:
    """Load a committed summary, or an empty frame if it does not exist."""
    if not path.exists():
        return empty_summary(key)
    return pd.read_parquet(path)


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    """Load the fetch cursor/state, or a fresh dict if there is none."""
    if not path.exists():
        return {"last_key": "", "objects_processed": 0}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def counts_to_frame(counts: Counts, key: list[str]) -> pd.DataFrame:
    """Turn a ``key-tuple -> [requests, bytes]`` map into a DataFrame."""
    if not counts:
        return empty_summary(key)
    rows = [(*k, measures[0], measures[1]) for k, measures in counts.items()]
    return pd.DataFrame(rows, columns=key + SUMMARY_MEASURES)


def merge_summary(
    existing: pd.DataFrame, new_rows: pd.DataFrame, key: list[str]
) -> pd.DataFrame:
    """Concatenate and re-aggregate so repeated keys are summed."""
    combined = pd.concat([existing, new_rows], ignore_index=True)
    if combined.empty:
        return empty_summary(key)
    combined = (
        combined.groupby(key, as_index=False)[SUMMARY_MEASURES]
        .sum()
        .sort_values(key, ignore_index=True)
    )
    for name in SUMMARY_MEASURES:
        combined[name] = combined[name].astype("int64")
    return combined


def write_summary(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    logger.info("Wrote %d summary rows to %s", len(frame), path)


def write_state(
    last_key: str,
    objects_processed: int,
    *,
    lines_parsed: int,
    lines_skipped: int,
    path: Path = STATE_PATH,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_key": last_key,
        "objects_processed": objects_processed,
        "lines_parsed": lines_parsed,
        "lines_skipped": lines_skipped,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")
    logger.info("Wrote fetch state to %s (last_key=%s)", path, last_key)
