"""Constants used throughout the oss_dashboard package."""

# Time conversions
MS_PER_DAY = 86_400_000

# Default lookback period
DEFAULT_DAYS_LOOKBACK = 365

# GitHub API retry settings
MAX_CONTRIBUTOR_RETRIES = 20
CONTRIBUTOR_RETRY_SLEEP_SECONDS = 10
RATE_LIMIT_SLEEP_SECONDS = 60

# PePy API rate limiting
PEPY_RATE_LIMIT_REQUESTS = 8
PEPY_RATE_LIMIT_SLEEP_SECONDS = 80
PEPY_MAX_RETRIES = 2

# File download settings
CHUNK_SIZE = 8192

# Repository exclusion prefixes
EXCLUDED_REPO_PREFIXES = ("slides-", "course-")
