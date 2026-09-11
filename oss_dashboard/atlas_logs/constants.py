"""Paths and tunables for the atlas-log analytics pipeline."""

from pathlib import Path

# Committed, ever-growing summaries + fetch cursor. The atlas, country and
# client-tool breakdowns are kept in separate tables (no cross-tabs) so no
# dimension inflates another.
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
ATLAS_PARQUET_PATH = DATA_DIR / "atlas_usage.parquet"
COUNTRY_PARQUET_PATH = DATA_DIR / "atlas_usage_by_country.parquet"
TOOL_PARQUET_PATH = DATA_DIR / "atlas_usage_by_tool.parquet"
STATE_PATH = DATA_DIR / "atlas_usage_state.json"

# Grouping keys for each summary; measures are additive across runs.
ATLAS_KEY = ["date", "atlas", "resource"]
COUNTRY_KEY = ["date", "country"]
TOOL_KEY = ["date", "tool"]
SUMMARY_MEASURES = ["requests", "bytes_sent"]

# Only object downloads count towards "requests"/"bytes served".
DOWNLOAD_OPERATIONS = frozenset({"REST.GET.OBJECT"})
OK_STATUSES = frozenset({200, 206})

# Access logs arrive as a very large number of small objects, so fetching
# them is latency- rather than bandwidth-bound: one GET at a time runs at
# roughly 4 objects/s. Fetch them through a thread pool instead.
S3_MAX_WORKERS = 32

# Free, CC0/MIT IP->country ranges (no account or key required).
GEOIP_CACHE_DIR = Path.home() / ".dashboard" / "geoip"
GEOIP_MAX_AGE_DAYS = 30
GEOIP_IPV4_URL = (
    "https://cdn.jsdelivr.net/npm/@ip-location-db/"
    "geo-whois-asn-country/geo-whois-asn-country-ipv4.csv"
)
GEOIP_IPV6_URL = (
    "https://cdn.jsdelivr.net/npm/@ip-location-db/"
    "geo-whois-asn-country/geo-whois-asn-country-ipv6.csv"
)

# Placeholder country code for IPs we cannot resolve.
UNKNOWN_COUNTRY = "??"
