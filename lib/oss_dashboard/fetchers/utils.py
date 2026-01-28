"""Utility functions for fetchers."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from oss_dashboard.constants import EXCLUDED_REPO_PREFIXES
from oss_dashboard.github_client import GitHubClient
from oss_dashboard.models import Config


@lru_cache(maxsize=1)
def load_excluded_repos(config_dir: str | None = None) -> tuple[str, ...]:
    """Load the list of excluded repositories.

    Args:
        config_dir: Directory containing excluded_repos.json

    Returns:
        Tuple of excluded repository names
    """
    if config_dir is None:
        path = Path(__file__).parent.parent
    else:
        path = Path(config_dir)

    excluded_file = path / "excluded_repos.json"
    if excluded_file.exists():
        with open(excluded_file) as f:
            return tuple(json.load(f))
    return ()


def should_exclude_repo(repo_name: str, config: Config) -> bool:
    """Check if a repository should be excluded.

    Args:
        repo_name: Repository name
        config: Configuration

    Returns:
        True if the repository should be excluded
    """
    excluded = load_excluded_repos()
    return repo_name in excluded or repo_name.startswith(
        EXCLUDED_REPO_PREFIXES
    )


def query_repo_names(
    client: GitHubClient, config: Config
) -> list[dict[str, Any]]:
    """Query repository names for the organization.

    Args:
        client: GitHub client
        config: Configuration

    Returns:
        List of repository info dictionaries
    """
    query = """
    query ($cursor: String, $organization: String!) {
        organization(login:$organization) {
            repositories(privacy:PUBLIC, first:100, isFork:false, isArchived:false, after: $cursor) {
                pageInfo {
                    hasNextPage
                    endCursor
                }
                nodes {
                    name
                    isArchived
                    isFork
                }
            }
        }
    }
    """ # noqa: E501

    all_repos = []
    for result in client.graphql_paginate(
        query,
        {"organization": config.organization},
        ["organization", "repositories"],
    ):
        nodes = result["organization"]["repositories"]["nodes"]
        for repo in nodes:
            if repo is None:
                continue

            # Apply filters
            is_archived = repo.get("isArchived", False)
            is_fork = repo.get("isFork", False)

            if is_archived and not config.include_archived:
                continue
            if is_fork and not config.include_forks:
                continue
            if should_exclude_repo(repo["name"], config):
                continue

            all_repos.append(repo)

    return all_repos
