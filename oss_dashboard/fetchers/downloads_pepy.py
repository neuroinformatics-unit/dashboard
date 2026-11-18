"""Fetcher for PyPI download statistics.

Daily download counts come from pypistats (generous rate limit, ~180 days
of history). The all-time total comes from PePy, which throttles heavily,
so it is cached on disk and only re-fetched every
``PEPY_REFRESH_DAYS``. Between refreshes the total is advanced by adding
the pypistats daily counts after the date the cached total covers.
"""

import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any

import requests

from oss_dashboard.constants import (
    PEPY_MAX_RETRIES,
    PEPY_RATE_LIMIT_REQUESTS,
    PEPY_RATE_LIMIT_SLEEP_SECONDS,
    PEPY_REFRESH_DAYS,
    PYPISTATS_MAX_RETRIES,
)
from oss_dashboard.fetchers.utils import (
    load_pypi_aliases,
    query_repo_names,
)
from oss_dashboard.github_client import GitHubClient
from oss_dashboard.models import Config, Result

logger = logging.getLogger(__name__)

_PEPY_CACHE_PATH = Path.home() / ".dashboard" / "pepy_totals.json"


def _load_cache() -> dict[str, dict[str, Any]]:
    """Load cached PePy totals, keyed by PyPI project name."""
    if not _PEPY_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_PEPY_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read PePy cache: %s", exc)
        return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    """Persist cached PePy totals to disk."""
    try:
        _PEPY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PEPY_CACHE_PATH.write_text(
            json.dumps(cache, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("Could not save PePy cache: %s", exc)


def _fetch_downloads(project_name: str, api_key: str) -> requests.Response:
    """Fetch download data from PePy API.

    Args:
        project_name: Project name on PyPI
        api_key: PePy API key

    Returns:
        Response object
    """
    return requests.get(
        f"https://api.pepy.tech/api/v2/projects/{project_name}",
        headers={"X-Api-Key": api_key},
    )


def _fetch_pypistats_daily(project_name: str) -> dict[str, int] | None:
    """Fetch daily downloads (including mirrors) from pypistats.

    The ``with_mirrors`` category matches PePy's numbers.

    Args:
        project_name: Project name on PyPI

    Returns:
        Mapping of ISO date to download count, or None if the project is
        not on PyPI or could not be fetched.
    """
    url = f"https://pypistats.org/api/packages/{project_name}/overall"
    for _ in range(PYPISTATS_MAX_RETRIES):
        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as exc:
            logger.warning("pypistats error for %s: %s", project_name, exc)
            time.sleep(5)
            continue
        if response.status_code == HTTPStatus.NOT_FOUND:
            return None
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            time.sleep(int(response.headers.get("retry-after", 5)))
            continue
        if not response.ok:
            logger.warning(
                "pypistats returned %s for %s",
                response.status_code,
                project_name,
            )
            return None
        return {
            row["date"]: row["downloads"]
            for row in response.json()["data"]
            if row["category"] == "with_mirrors"
        }
    return None


class _PepyClient:
    """Fetches PePy totals while respecting its rate limit."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.num_requests = 0

    def fetch_total(self, project_name: str) -> dict[str, Any] | None:
        """Fetch the all-time total and the last day it includes.

        Args:
            project_name: Project name on PyPI

        Returns:
            Cache entry ``{"total", "through", "fetched_at"}`` or None.
        """
        for _ in range(PEPY_MAX_RETRIES):
            if self.num_requests >= PEPY_RATE_LIMIT_REQUESTS:
                logger.info(
                    "Sleeping %ds to avoid PePy rate limit",
                    PEPY_RATE_LIMIT_SLEEP_SECONDS,
                )
                time.sleep(PEPY_RATE_LIMIT_SLEEP_SECONDS)
                self.num_requests = 0
            self.num_requests += 1

            try:
                response = _fetch_downloads(project_name, self.api_key)
            except requests.RequestException as exc:
                logger.warning("PePy error for %s: %s", project_name, exc)
                self.num_requests = PEPY_RATE_LIMIT_REQUESTS
                continue
            if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                logger.warning("PePy rate limited for %s", project_name)
                self.num_requests = PEPY_RATE_LIMIT_REQUESTS
                continue
            if not response.ok:
                return None

            data = response.json()
            downloads = data.get("downloads") or {}
            if not downloads:
                return None
            return {
                "total": data.get("total_downloads", 0),
                "through": max(downloads),
                "fetched_at": date.today().isoformat(),
            }
        return None


def _is_stale(entry: dict[str, Any] | None, today: date) -> bool:
    """Return True if a cache entry is missing or due for a refresh."""
    if entry is None:
        return True
    fetched_at = date.fromisoformat(entry["fetched_at"])
    return (today - fetched_at).days >= PEPY_REFRESH_DAYS


def _current_total(entry: dict[str, Any], daily: dict[str, int]) -> int:
    """Advance a cached total by the daily downloads after it.

    Args:
        entry: Cache entry with ``total`` and ``through`` (ISO date)
        daily: Mapping of ISO date to download count

    Returns:
        Total downloads up to the latest day in ``daily``.
    """
    return entry["total"] + sum(
        count for day, count in daily.items() if day > entry["through"]
    )


def _process_download_numbers(daily: dict[str, int]) -> dict[str, int]:
    """Calculate daily/weekly/monthly download counts.

    Args:
        daily: Mapping of ISO date to download count

    Returns:
        Dictionary with monthly, weekly and daily download counts
    """
    # Download results begin on previous day
    current_date = datetime.now() - timedelta(days=1)
    end_date_month = (current_date - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date_week = (current_date - timedelta(days=7)).strftime("%Y-%m-%d")

    return {
        "monthly": sum(n for d, n in daily.items() if d > end_date_month),
        "weekly": sum(n for d, n in daily.items() if d > end_date_week),
        "daily": daily.get(current_date.strftime("%Y-%m-%d"), 0),
    }


def add_downloads_pepy(
    result: Result, client: GitHubClient, config: Config
) -> Result:
    """Add PyPI download statistics to the result.

    Args:
        result: Current result object
        client: GitHub client
        config: Configuration

    Returns:
        Updated result with download statistics
    """
    api_key = os.environ.get("PEPY_API_KEY")
    if not api_key:
        logger.warning("PEPY_API_KEY not set, skipping PyPI downloads")
        return result

    aliases = load_pypi_aliases()
    cache = _load_cache()
    pepy = _PepyClient(api_key)
    today = date.today()

    for repo in query_repo_names(client, config):
        repo_name = repo["name"]
        if repo_name not in result.repositories:
            continue
        # pypistats only accepts PEP 503 normalized names
        project_name = re.sub(
            r"[-_.]+", "-", aliases.get(repo_name, repo_name)
        ).lower()

        daily = _fetch_pypistats_daily(project_name)
        if daily is None:
            logger.debug("%s not found on pypistats, skipping", repo_name)
            continue

        entry = cache.get(project_name)
        if _is_stale(entry, today):
            fresh = pepy.fetch_total(project_name)
            if fresh is not None:
                entry = cache[project_name] = fresh

        repository = result.repositories[repo_name]
        if entry is not None:
            repository.total_download_count = _current_total(entry, daily)
        counts = _process_download_numbers(daily)
        repository.monthly_download_count = counts["monthly"]
        repository.weekly_download_count = counts["weekly"]
        repository.daily_download_count = counts["daily"]

    _save_cache(cache)
    return result
