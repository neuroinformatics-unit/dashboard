"""Map ``classify_client()`` outcomes to the labels shown on the dashboard.

This is a display-only concern, mirroring ``atlas_names.py``: the summary
Parquet keeps whatever ``classify_client`` produced (see
``atlas_logs/parser.py``), and this module only decides how that value is
grouped for the dashboard page.
"""

from __future__ import annotations

# These four classify_client() outcomes are all "not a recognised client",
# just via different fallback paths (no Referer/User-Agent, an unrecognised
# one, or a bot/crawler) - lump them together rather than showing four
# near-empty catch-all rows.
_MERGED_AS_OTHER_UNKNOWN = frozenset(
    {"other", "other web viewer", "bot / crawler", "unknown"}
)


def display_tool(tool: str) -> str:
    """Return the dashboard label for a ``classify_client()`` outcome."""
    if tool in _MERGED_AS_OTHER_UNKNOWN:
        return "other/unknown"
    return tool
