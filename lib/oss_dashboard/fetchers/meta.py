"""Fetcher for metadata about this run."""

from datetime import datetime, timezone

from oss_dashboard.github_client import GitHubClient
from oss_dashboard.models import Config, Meta, Result


def add_meta_to_result(
    result: Result, client: GitHubClient, config: Config
) -> Result:
    """Add metadata to the result.

    Args:
        result: Current result object
        client: GitHub client (unused)
        config: Configuration (unused)

    Returns:
        Updated result with metadata
    """
    result.meta = Meta(created_at=datetime.now(timezone.utc).isoformat())
    return result
