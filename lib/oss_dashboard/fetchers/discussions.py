"""Fetcher for discussion data and metrics."""

from typing import Any

from oss_dashboard.fetchers.utils import should_exclude_repo
from oss_dashboard.github_client import GitHubClient
from oss_dashboard.models import Config, Result


def _query_for_discussions(
    client: GitHubClient, config: Config
) -> list[dict[str, Any]]:
    """Query discussion counts for all repositories.

    Args:
        client: GitHub client
        config: Configuration

    Returns:
        List of repository discussion data
    """
    query = """
    query($cursor: String, $organization: String!) {
        organization(login:$organization){
            repositories(privacy:PUBLIC, first:100, isFork:false, isArchived:false, after: $cursor) {
                totalCount
                pageInfo {
                    hasNextPage
                    endCursor
                }
                nodes {
                    name
                    discussions {
                        totalCount
                    }
                }
            }
        }
    }
    """ # noqa: E501

    all_repos = []
    for page_result in client.graphql_paginate(
        query,
        {"organization": config.organization},
        ["organization", "repositories"],
    ):
        nodes = page_result["organization"]["repositories"]["nodes"]
        all_repos.extend([n for n in nodes if n is not None])

    return all_repos


def add_discussion_data(
    result: Result, client: GitHubClient, config: Config
) -> Result:
    """Add discussion counts to the result.

    Args:
        result: Current result object
        client: GitHub client
        config: Configuration

    Returns:
        Updated result with discussion counts
    """
    data_result = _query_for_discussions(client, config)

    for repo in data_result:
        repo_name = repo["name"]
        if should_exclude_repo(repo_name, config):
            continue

        if repo_name not in result.repositories:
            continue

        discussions_count = repo.get("discussions", {}).get("totalCount", 0)
        result.repositories[repo_name].discussions_count = discussions_count

    return result
