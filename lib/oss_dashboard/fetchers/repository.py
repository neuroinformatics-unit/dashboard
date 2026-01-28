"""Fetcher for repository data and metrics."""

import json
import logging
import time
from http import HTTPStatus
from typing import Any

from oss_dashboard.constants import (
    CONTRIBUTOR_RETRY_SLEEP_SECONDS,
    MAX_CONTRIBUTOR_RETRIES,
)
from oss_dashboard.fetchers.utils import should_exclude_repo
from oss_dashboard.github_client import GitHubClient
from oss_dashboard.models import Config, RepositoryResult, Result

logger = logging.getLogger(__name__)


def _fetch_all_contributors(
    client: GitHubClient, org: str, repos: list[dict[str, Any]]
) -> dict[str, int]:
    """Fetch contributor counts for all repositories using REST API.

    Uses the /repos/{org}/{repo}/stats/contributors endpoint.
    Handles 202 responses by polling until data is ready.
    """
    contributors_map: dict[str, int] = {}
    pending_repos: list[str] = []

    logger.info("Fetching contributors for %d repositories", len(repos))
    for repo in repos:
        repo_name = repo["name"]
        url = f"/repos/{org}/{repo_name}/stats/contributors"
        status, data = client.rest_request("GET", url)
        data_dict = json.loads(data) if data else None

        if status == HTTPStatus.OK and data_dict:
            contributors_map[repo_name] = len(data_dict)
            logger.debug("%s: %d contributors", repo_name, len(data_dict))
        elif status == HTTPStatus.ACCEPTED:
            pending_repos.append(repo_name)
            logger.debug("%s: computing...", repo_name)
        else:
            contributors_map[repo_name] = 0
            logger.warning("%s: error (%s)", repo_name, status)

    retries_remaining = MAX_CONTRIBUTOR_RETRIES

    while pending_repos and retries_remaining > 0:
        logger.info(
            "Waiting %ds for %d repos",
            CONTRIBUTOR_RETRY_SLEEP_SECONDS,
            len(pending_repos),
        )
        time.sleep(CONTRIBUTOR_RETRY_SLEEP_SECONDS)

        still_pending: list[str] = []
        for repo_name in pending_repos:
            url = f"/repos/{org}/{repo_name}/stats/contributors"
            status, data = client.rest_request("GET", url)

            if status == HTTPStatus.OK and data:
                contributors_map[repo_name] = len(data)
                logger.debug("%s: %d contributors", repo_name, len(data))
            elif status == HTTPStatus.ACCEPTED:
                still_pending.append(repo_name)
            else:
                contributors_map[repo_name] = 0

        pending_repos = still_pending
        retries_remaining -= 1

    for repo_name in pending_repos:
        logger.warning("%s: timed out, setting to 0", repo_name)
        contributors_map[repo_name] = 0

    return contributors_map


def add_repositories_to_result(
    result: Result, client: GitHubClient, config: Config
) -> Result:
    """Add repository information to the result.

    Args:
        result: Current result object
        client: GitHub client
        config: Configuration

    Returns:
        Updated result with repository info
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
                    nameWithOwner
                    forkCount
                    stargazerCount
                    isFork
                    isArchived
                    hasIssuesEnabled
                    hasProjectsEnabled
                    hasDiscussionsEnabled
                    projectsV2 {
                        totalCount
                    }
                    discussions {
                        totalCount
                    }
                    licenseInfo {
                        name
                    }
                    watchers {
                        totalCount
                    }
                    repositoryTopics(first: 20) {
                        nodes {
                            topic {
                                name
                            }
                        }
                    }
                }
            }
        }
    }
    """ # noqa: E501

    all_repos: list[dict[str, Any]] = []
    for page_result in client.graphql_paginate(
        query,
        {"organization": config.organization},
        ["organization", "repositories"],
    ):
        nodes = page_result["organization"]["repositories"]["nodes"]
        for repo in nodes:
            if repo is None:
                continue

            is_archived = repo.get("isArchived", False)
            is_fork = repo.get("isFork", False)

            if is_archived and not config.include_archived:
                continue
            if is_fork and not config.include_forks:
                continue
            if should_exclude_repo(repo["name"], config):
                continue

            all_repos.append(repo)

    # Fetch contributor counts using REST API
    contributors_map = _fetch_all_contributors(
        client, config.organization, all_repos
    )

    # Build repository results
    for repo in all_repos:
        repo_name = repo["name"]
        topics = []
        if repo.get("repositoryTopics", {}).get("nodes"):
            topics = [
                node["topic"]["name"]
                for node in repo["repositoryTopics"]["nodes"]
                if node and node.get("topic")
            ]

        license_name = "No License"
        if repo.get("licenseInfo") and repo["licenseInfo"].get("name"):
            license_name = repo["licenseInfo"]["name"]

        result.repositories[repo_name] = RepositoryResult(
            repository_name=repo_name,
            repo_name_with_owner=repo.get("nameWithOwner", ""),
            license_name=license_name,
            topics=topics,
            forks_count=repo.get("forkCount", 0),
            watchers_count=repo.get("watchers", {}).get("totalCount", 0),
            stars_count=repo.get("stargazerCount", 0),
            collaborators_count=contributors_map.get(repo_name, 0),
            issues_enabled=repo.get("hasIssuesEnabled", False),
            projects_enabled=repo.get("hasProjectsEnabled", False),
            discussions_enabled=repo.get("hasDiscussionsEnabled", False),
            projects_v2_count=repo.get("projectsV2", {}).get("totalCount", 0),
        )

    return result
