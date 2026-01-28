"""Fetcher for PyPI download statistics from PePy API."""

import logging
import os
import time
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any

import requests

from oss_dashboard.constants import (
    PEPY_MAX_RETRIES,
    PEPY_RATE_LIMIT_REQUESTS,
    PEPY_RATE_LIMIT_SLEEP_SECONDS,
)
from oss_dashboard.fetchers.utils import query_repo_names
from oss_dashboard.github_client import GitHubClient
from oss_dashboard.models import Config, Result

logger = logging.getLogger(__name__)


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


def _query_projects_for_repositories(
    repositories: list[dict[str, Any]], api_key: str
) -> list[dict[str, Any]]:
    """Query PePy for all repositories.

    Args:
        repositories: List of repository info
        api_key: PePy API key

    Returns:
        List of project results with repo name and PePy data
    """
    project_results = []
    num_requests = 0

    for repo in repositories:
        repo_name = repo["name"]
        retries = PEPY_MAX_RETRIES

        while retries > 0:
            try:
                logger.debug(
                    "Fetching download data for project %s", repo_name
                )

                if num_requests >= PEPY_RATE_LIMIT_REQUESTS:
                    logger.info(
                        "Sleeping %ds to avoid rate limit",
                        PEPY_RATE_LIMIT_SLEEP_SECONDS,
                    )
                    time.sleep(PEPY_RATE_LIMIT_SLEEP_SECONDS)
                    num_requests = 0

                num_requests += 1
                response = _fetch_downloads(repo_name, api_key)

                if response.status_code == HTTPStatus.NOT_FOUND:
                    logger.debug(
                        "Project %s not found on PePy, skipping", repo_name
                    )
                    break

                if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                    logger.warning(
                        "Rate limited for %s, retrying in %ds",
                        repo_name,
                        PEPY_RATE_LIMIT_SLEEP_SECONDS,
                    )
                    retries -= 1
                    num_requests = 0
                    time.sleep(PEPY_RATE_LIMIT_SLEEP_SECONDS)
                    continue

                project_data = response.json()
                if project_data:
                    project_results.append(
                        {"repo_name": repo_name, "data": project_data}
                    )
                break

            except requests.RequestException as e:
                logger.warning(
                    "Error fetching download data for %s: %s", repo_name, e
                )
                retries -= 1
                num_requests = 0
                time.sleep(PEPY_RATE_LIMIT_SLEEP_SECONDS)

    return project_results


def _process_download_numbers(
    project_result: dict[str, Any],
) -> dict[str, int]:
    """Process download numbers to calculate daily/weekly/monthly stats.

    Args:
        project_result: Raw PePy API result

    Returns:
        Dictionary with processed download counts
    """
    current_date = datetime.now()
    # Download results begin on previous day
    current_date = current_date - timedelta(days=1)
    end_date_month = current_date - timedelta(days=30)
    end_date_week = current_date - timedelta(days=7)

    downloads = project_result.get("downloads", {})

    # Collapse version-specific downloads to daily totals
    download_collapsed = {}
    for date_str, versions in downloads.items():
        download_collapsed[date_str] = sum(versions.values())

    # Calculate monthly downloads
    monthly = 0
    for date_str, count in download_collapsed.items():
        date = datetime.strptime(date_str, "%Y-%m-%d")
        if date > end_date_month:
            monthly += count

    # Calculate weekly downloads
    weekly = 0
    for date_str, count in download_collapsed.items():
        date = datetime.strptime(date_str, "%Y-%m-%d")
        if date > end_date_week:
            weekly += count

    # Get daily downloads
    daily_date = current_date.strftime("%Y-%m-%d")
    daily = download_collapsed.get(daily_date, 0)

    return {
        "total": project_result.get("total_downloads", 0),
        "monthly": monthly,
        "weekly": weekly,
        "daily": daily,
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
        logger.warning("PEPY_API_KEY not set, skipping PePy downloads")
        return result

    repos = query_repo_names(client, config)
    output = _query_projects_for_repositories(repos, api_key)

    for project in output:
        repo_name = project["repo_name"]
        if repo_name not in result.repositories:
            continue

        processed = _process_download_numbers(project["data"])
        result.repositories[repo_name].total_download_count = processed[
            "total"
        ]
        result.repositories[repo_name].monthly_download_count = processed[
            "monthly"
        ]
        result.repositories[repo_name].weekly_download_count = processed[
            "weekly"
        ]
        result.repositories[repo_name].daily_download_count = processed[
            "daily"
        ]

    return result
