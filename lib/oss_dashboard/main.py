"""Main entry point for the GitHub organization metrics fetcher."""

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import yaml
from dotenv import load_dotenv

from oss_dashboard.constants import DEFAULT_DAYS_LOOKBACK
from oss_dashboard.fetchers import (
    add_conda_data,
    add_discussion_data,
    add_downloads_pepy,
    add_issue_and_pr_data,
    add_issue_metrics_data,
    add_meta_to_result,
    add_organization_info_to_result,
    add_repositories_to_result,
)
from oss_dashboard.github_client import GitHubClient, check_rate_limit
from oss_dashboard.models import Config, Result

logger = logging.getLogger(__name__)

# Type alias for fetcher functions
Fetcher = Callable[[Result, GitHubClient, Config], Result]


def load_config() -> dict:
    """Load configuration from config.yml.

    Returns:
        Configuration dictionary
    """
    config_file = Path(__file__).parent / "config.yml"
    if config_file.exists():
        with open(config_file) as f:
            return yaml.safe_load(f)
    return {}


def run_pipeline(
    client: GitHubClient, config: Config, *fetchers: Fetcher
) -> Result:
    """Run the fetcher pipeline.

    Args:
        client: GitHub client
        config: Configuration
        *fetchers: Fetcher functions to run

    Returns:
        Final result
    """
    result = Result()

    for fetcher in fetchers:
        logger.info("Running fetcher %s", fetcher.__name__)
        result = fetcher(result, client, config)
        logger.info("Finished %s", fetcher.__name__)

        rate_limit = check_rate_limit(client)
        logger.debug(
            "Rate limit: %d/%d remaining until %s",
            rate_limit["remaining"],
            rate_limit["limit"],
            rate_limit["reset_date"],
        )

    return result


def output_result(result: Result, org_name: str) -> Path:
    """Output result to JSON file.

    Args:
        result: Result object
        org_name: Organization name

    Returns:
        Path to the output file
    """
    destination = Path(__file__).parent / "data" / f"data_{org_name}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)

    with open(destination, "w") as f:
        json.dump(result.to_dict(), f, indent=2)

    logger.info("Wrote result to %s", destination)
    return destination


def main() -> None:
    """Main entry point."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    load_dotenv()

    graphql_token = os.environ.get("GRAPHQL_TOKEN")
    if not graphql_token:
        logger.error("GRAPHQL_TOKEN environment variable is required")
        sys.exit(1)

    pepy_api_key = os.environ.get("PEPY_API_KEY")
    if not pepy_api_key:
        logger.error("PEPY_API_KEY environment variable is required")
        sys.exit(1)

    logger.info("Starting GitHub organization metrics fetcher")

    client = GitHubClient(graphql_token)

    yaml_config = load_config()
    env_organization_name = os.environ.get("ORGANIZATION_NAME")
    config_organization_names = yaml_config.get("organization", [])

    if not env_organization_name and not config_organization_names:
        logger.error("ORGANIZATION_NAME or config.yml organization required")
        sys.exit(1)

    if isinstance(config_organization_names, str):
        config_organization_names = [config_organization_names]

    since_config = yaml_config.get("since")
    if since_config:
        since = datetime.fromisoformat(str(since_config)).isoformat()
    else:
        since = (
            datetime.now(timezone.utc) - timedelta(days=DEFAULT_DAYS_LOOKBACK)
        ).isoformat()

    for org_name in config_organization_names:
        logger.info("Fetching data for organization %s", org_name)

        effective_org_name = env_organization_name or org_name

        config = Config(
            organization=effective_org_name,
            include_forks=yaml_config.get("includeForks", False),
            include_archived=yaml_config.get("includeArchived", False),
            since=since,
        )

        logger.info(
            "Configuration: organization=%s, since=%s",
            config.organization,
            config.since,
        )
        time_start = datetime.now(timezone.utc)

        result = run_pipeline(
            client,
            config,
            add_meta_to_result,
            add_organization_info_to_result,
            add_repositories_to_result,
            add_issue_and_pr_data,
            add_discussion_data,
            add_issue_metrics_data,
            add_downloads_pepy,
            add_conda_data,
        )

        output_result(result, org_name)
        logger.info("Finished fetching data for organization %s", org_name)

        duration = datetime.now(timezone.utc) - time_start
        logger.info("Time taken: %s", duration)


if __name__ == "__main__":
    main()
