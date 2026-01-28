"""Fetcher for issue and pull request data and metrics."""

import logging
from datetime import datetime, timezone
from statistics import median
from typing import Any

from github import GithubException

from oss_dashboard.fetchers.utils import should_exclude_repo
from oss_dashboard.github_client import GitHubClient
from oss_dashboard.models import Config, Result

logger = logging.getLogger(__name__)


def _get_issue_and_pr_data(
    client: GitHubClient, config: Config
) -> list[dict[str, Any]]:
    """Get issue and PR counts for all repositories.

    Args:
        client: GitHub client
        config: Configuration

    Returns:
        List of repository data with issue/PR counts
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
                    totalIssues: issues {
                        totalCount
                    }
                    closedIssues: issues(states:CLOSED) {
                        totalCount
                    }
                    openIssues: issues(states:OPEN) {
                        totalCount
                    }
                    openPullRequests: pullRequests(states:OPEN) {
                        totalCount
                    }
                    totalPullRequests: pullRequests {
                        totalCount
                    }
                    closedPullRequests: pullRequests(states:CLOSED) {
                        totalCount
                    }
                    mergedPullRequests: pullRequests(states:MERGED) {
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


def add_issue_and_pr_data(
    result: Result, client: GitHubClient, config: Config
) -> Result:
    """Add issue and PR counts to the result.

    Args:
        result: Current result object
        client: GitHub client
        config: Configuration

    Returns:
        Updated result with issue/PR counts
    """
    data_result = _get_issue_and_pr_data(client, config)

    for repo in data_result:
        repo_name = repo["name"]
        if should_exclude_repo(repo_name, config):
            continue

        if repo_name not in result.repositories:
            continue

        result.repositories[repo_name].total_issues_count = repo[
            "totalIssues"
        ]["totalCount"]
        result.repositories[repo_name].open_issues_count = repo["openIssues"][
            "totalCount"
        ]
        result.repositories[repo_name].closed_issues_count = repo[
            "closedIssues"
        ]["totalCount"]
        result.repositories[repo_name].total_pull_requests_count = repo[
            "totalPullRequests"
        ]["totalCount"]
        result.repositories[repo_name].open_pull_requests_count = repo[
            "openPullRequests"
        ]["totalCount"]
        result.repositories[repo_name].closed_pull_requests_count = repo[
            "closedPullRequests"
        ]["totalCount"]
        result.repositories[repo_name].merged_pull_requests_count = repo[
            "mergedPullRequests"
        ]["totalCount"]

    return result


def _calculate_ages(issues: list[dict], now: datetime) -> dict[str, float]:
    """Calculate average and median age from a list of issues.

    Args:
        issues: List of issue dicts with 'createdAt' field
        now: Current datetime

    Returns:
        Dictionary with average_age and median_age in milliseconds
    """
    if not issues:
        return {"average_age": 0.0, "median_age": 0.0}

    ages = []
    for issue in issues:
        created_at = datetime.fromisoformat(
            issue["createdAt"].replace("Z", "+00:00")
        )
        age = (now - created_at).total_seconds() * 1000
        ages.append(age)

    return {"average_age": sum(ages) / len(ages), "median_age": median(ages)}


def _fetch_issue_metrics_for_repo(
    client: GitHubClient, config: Config, repo_name: str
) -> dict[str, float]:
    """Fetch issue age metrics for a single repo using GraphQL.

    Fetches both open and closed issues in a single query per page,
    reducing API calls compared to separate REST calls.

    Args:
        client: GitHub client
        config: Configuration
        repo_name: Repository name

    Returns:
        Dict with open/closed average and median ages
    """
    # Query fetches both open and closed issues in one request
    query = """
    query ($organization: String!, $repoName: String!, $openCursor: String, $closedCursor: String) {
        repository(owner: $organization, name: $repoName) {
            openIssues: issues(states: OPEN, first: 100, after: $openCursor) {
                pageInfo {
                    hasNextPage
                    endCursor
                }
                nodes {
                    createdAt
                }
            }
            closedIssues: issues(states: CLOSED, first: 100, after: $closedCursor) {
                pageInfo {
                    hasNextPage
                    endCursor
                }
                nodes {
                    createdAt
                }
            }
        }
    }
    """ # noqa: E501

    now = datetime.now(timezone.utc)
    all_open_issues: list[dict] = []
    all_closed_issues: list[dict] = []

    open_cursor = None
    closed_cursor = None
    open_has_next = True
    closed_has_next = True

    # Paginate until both open and closed are exhausted
    while open_has_next or closed_has_next:
        try:
            data = client.graphql(
                query,
                {
                    "organization": config.organization,
                    "repoName": repo_name,
                    "openCursor": open_cursor if open_has_next else None,
                    "closedCursor": closed_cursor if closed_has_next else None,
                },
            )
        except GithubException as e:
            logger.warning("%s: error fetching issues (%s)", repo_name, e)
            break

        if not data.get("repository"):
            break

        # Process open issues
        if open_has_next:
            open_data = data["repository"]["openIssues"]
            all_open_issues.extend(
                [n for n in open_data["nodes"] if n is not None]
            )
            open_has_next = open_data["pageInfo"]["hasNextPage"]
            open_cursor = open_data["pageInfo"]["endCursor"]

        # Process closed issues
        if closed_has_next:
            closed_data = data["repository"]["closedIssues"]
            all_closed_issues.extend(
                [n for n in closed_data["nodes"] if n is not None]
            )
            closed_has_next = closed_data["pageInfo"]["hasNextPage"]
            closed_cursor = closed_data["pageInfo"]["endCursor"]

    open_ages = _calculate_ages(all_open_issues, now)
    closed_ages = _calculate_ages(all_closed_issues, now)

    return {
        "open_average_age": open_ages["average_age"],
        "open_median_age": open_ages["median_age"],
        "closed_average_age": closed_ages["average_age"],
        "closed_median_age": closed_ages["median_age"],
    }


def _fetch_response_time_for_repo(
    client: GitHubClient, config: Config, repo_name: str
) -> dict[str, float]:
    """Fetch issue response time metrics for a repo.

    Args:
        client: GitHub client
        config: Configuration
        repo_name: Repository name

    Returns:
        Dict with average and median response times
    """
    query = """
    query ($cursor: String, $organization: String!, $repoName: String!, $since: DateTime!) {
        repository(owner: $organization, name: $repoName) {
            issues(first: 100, after: $cursor, filterBy: {since: $since}) {
                pageInfo {
                    hasNextPage
                    endCursor
                }
                nodes {
                    author {
                        login
                    }
                    createdAt
                    comments(first: 10) {
                        nodes {
                            createdAt
                            author {
                                __typename
                                login
                            }
                            isMinimized
                        }
                    }
                }
            }
        }
    }
    """ # noqa: E501

    since = config.since or datetime.now(timezone.utc).isoformat()
    all_issues: list[dict] = []

    for page_result in client.graphql_paginate(
        query,
        {
            "organization": config.organization,
            "repoName": repo_name,
            "since": since,
        },
        ["repository", "issues"],
    ):
        if not page_result.get("repository"):
            break
        nodes = page_result["repository"]["issues"]["nodes"]
        all_issues.extend([n for n in nodes if n is not None])

    if not all_issues:
        return {"average": 0.0, "median": 0.0}

    # Process comments to find first valid response
    response_times = []
    for issue in all_issues:
        author_login = (
            issue.get("author", {}).get("login")
            if issue.get("author")
            else None
        )
        comments = issue.get("comments", {}).get("nodes", [])

        # Find first valid comment (not from author, not bot, not minimized)
        first_valid = None
        for c in comments:
            if (
                c
                and c.get("author")
                and c["author"].get("login") != author_login
                and c["author"].get("__typename") != "Bot"
                and not c.get("isMinimized", False)
            ):
                first_valid = c
                break

        if first_valid:
            created_at = datetime.fromisoformat(
                issue["createdAt"].replace("Z", "+00:00")
            )
            comment_at = datetime.fromisoformat(
                first_valid["createdAt"].replace("Z", "+00:00")
            )
            response_time = (comment_at - created_at).total_seconds() * 1000
            response_times.append(response_time)

    if not response_times:
        return {"average": 0.0, "median": 0.0}

    return {
        "average": sum(response_times) / len(response_times),
        "median": median(response_times),
    }


def add_issue_metrics_data(
    result: Result, client: GitHubClient, config: Config
) -> Result:
    """Add issue metrics (age, response time) to the result.

    Args:
        result: Current result object
        client: GitHub client
        config: Configuration

    Returns:
        Updated result with issue metrics
    """
    repo_names = list(result.repositories.keys())
    logger.info(
        "Calculating issue metrics for %d repositories", len(repo_names)
    )

    for repo_name in repo_names:
        logger.debug("Processing %s", repo_name)

        # Fetch age metrics (fetches open+closed together, halving API calls)
        ages = _fetch_issue_metrics_for_repo(client, config, repo_name)
        result.repositories[repo_name].open_issues_average_age = ages[
            "open_average_age"
        ]
        result.repositories[repo_name].open_issues_median_age = ages[
            "open_median_age"
        ]
        result.repositories[repo_name].closed_issues_average_age = ages[
            "closed_average_age"
        ]
        result.repositories[repo_name].closed_issues_median_age = ages[
            "closed_median_age"
        ]

        # Fetch response time metrics
        response = _fetch_response_time_for_repo(client, config, repo_name)
        result.repositories[repo_name].issues_response_average_age = response[
            "average"
        ]
        result.repositories[repo_name].issues_response_median_age = response[
            "median"
        ]

    return result
