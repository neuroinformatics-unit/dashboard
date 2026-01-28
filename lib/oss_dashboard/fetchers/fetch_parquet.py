"""Fetcher for Conda download statistics from AWS parquet files."""

import json
import logging
from datetime import datetime
from pathlib import Path

import duckdb
import requests

from oss_dashboard.constants import CHUNK_SIZE
from oss_dashboard.fetchers.utils import query_repo_names
from oss_dashboard.github_client import GitHubClient
from oss_dashboard.models import Config, Result

logger = logging.getLogger(__name__)


def _download_parquet_file(url: str, output_path: Path) -> bool:
    """Download a parquet file from URL.

    Args:
        url: URL to download from
        output_path: Path to save file

    Returns:
        True if download successful, False otherwise
    """
    try:
        response = requests.get(url, stream=True)
        if not response.ok:
            return False

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)
        return True
    except requests.RequestException as e:
        logger.warning("Error downloading %s: %s", url, e)
        return False


def _check_url_exists(url: str) -> bool:
    """Check if a URL exists.

    Args:
        url: URL to check

    Returns:
        True if URL exists (2xx status)
    """
    try:
        response = requests.head(url)
        return response.ok
    except requests.RequestException:
        return False


def add_conda_data(
    result: Result,
    client: GitHubClient,
    config: Config,
    start_year: int = 2018,
) -> Result:
    """Add Conda download statistics to the result.

    Args:
        result: Current result object
        client: GitHub client
        config: Configuration
        start_year: Year to start downloading data from

    Returns:
        Updated result with Conda download statistics
    """
    repos = query_repo_names(client, config)
    base_dir = Path.home() / ".dashboard"
    base_dir.mkdir(exist_ok=True)

    packages = [repo["name"] for repo in repos]

    # Handle legacy package mappings for brainglobe
    legacy_packages_map: dict[str, str] = {}
    if config.organization == "brainglobe":
        legacy_file = Path(__file__).parent / "brainglobe_legacy.json"
        if legacy_file.exists():
            with open(legacy_file) as f:
                legacy_packages = json.load(f)
                for key, value in legacy_packages.items():
                    if isinstance(value, str):
                        legacy_packages_map[key] = value
                packages.extend(legacy_packages_map.keys())

    curr_year = datetime.now().year
    last_month = 1

    # Download parquet files
    for year in range(start_year, curr_year + 1):
        for month in range(1, 13):
            file_name = base_dir / f"{year}-{month:02d}.parquet"

            if not file_name.exists():
                url = (f"https://anaconda-package-data.s3.amazonaws.com/"
                       f"conda/monthly/{year}/{year}-{month:02d}.parquet")

                # Check if URL exists
                if not _check_url_exists(url):
                    last_month = month - 1 if month > 1 else 12
                    curr_year = year
                    break

                logger.info("Downloading %s", url)
                if not _download_parquet_file(url, file_name):
                    logger.warning("Failed to download %s", url)
                    last_month = month - 1 if month > 1 else 12
                    curr_year = year
                    break
        else:
            continue
        break

    # Query with DuckDB
    con = duckdb.connect(":memory:")
    formatted_packages = ", ".join(f"'{pkg}'" for pkg in packages)

    try:
        # Get total downloads
        total_downloads = con.execute(
            f"""
            SELECT pkg_name, SUM(counts)::INTEGER AS total
            FROM '{base_dir}/*.parquet'
            WHERE pkg_name IN ({formatted_packages})
            GROUP BY pkg_name
            """
        ).fetchall()

        # Get last month downloads
        if last_month == 12:
            curr_year -= 1
            last_month = 12

        last_month_file = base_dir / f"{curr_year}-{last_month:02d}.parquet"
        if last_month_file.exists():
            last_month_downloads = con.execute(
                f"""
                SELECT pkg_name, SUM(counts)::INTEGER AS total
                FROM '{last_month_file}'
                WHERE pkg_name IN ({formatted_packages})
                GROUP BY pkg_name
                """
            ).fetchall()
        else:
            last_month_downloads = []

    except duckdb.Error as e:
        logger.error("Error querying parquet files: %s", e)
        return result
    finally:
        con.close()

    # Process total downloads
    for pkg_name, total in total_downloads:
        # Map legacy package names
        if pkg_name in legacy_packages_map:
            pkg_name = legacy_packages_map[pkg_name]

        if pkg_name not in result.repositories:
            continue

        result.repositories[pkg_name].conda_total_downloads += total

    # Process monthly downloads
    for pkg_name, total in last_month_downloads:
        # Map legacy package names
        if pkg_name in legacy_packages_map:
            pkg_name = legacy_packages_map[pkg_name]

        if pkg_name not in result.repositories:
            continue

        result.repositories[pkg_name].conda_monthly_downloads += total

    return result
