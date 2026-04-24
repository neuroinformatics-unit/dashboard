"""Fetcher for repository data and metrics."""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from github import RateLimitExceededException

from oss_dashboard.constants import RATE_LIMIT_SLEEP_SECONDS
from oss_dashboard.fetchers.utils import should_exclude_repo
from oss_dashboard.github_client import GitHubClient
from oss_dashboard.models import Config, RepositoryResult, Result

logger = logging.getLogger(__name__)

_COLLABORATORS_CACHE_DIR = Path.home() / ".dashboard" / "collaborators_cache"


def _cache_path(org: str) -> Path:
    _COLLABORATORS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _COLLABORATORS_CACHE_DIR / f"collaborators_cache_{org}.json"


def _load_collaborators_cache(org: str) -> dict[str, dict]:
    """Load the collaborators cache for an org from disk.

    Returns:
        Mapping of repo name to
        ``{"collaborators": list[str], "cached_at": ISO str}``
    """
    path = _cache_path(org)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read collaborators cache: %s", exc)
        return {}


def _save_collaborators_cache(
    org: str, cache: dict[str, dict]
) -> None:
    """Persist the collaborators cache for an org to disk."""
    path = _cache_path(org)
    try:
        path.write_text(
            json.dumps(cache, indent=2), encoding="utf-8"
        )
        logger.debug("Collaborators cache saved to %s", path)
    except OSError as exc:
        logger.warning("Could not save collaborators cache: %s", exc)


def _parse_cached_at(entry: dict) -> str | None:
    """Return the ISO timestamp from a cache entry, or None if invalid."""
    cached_at_str = entry.get("cached_at")
    if not cached_at_str:
        return None
    try:
        datetime.fromisoformat(cached_at_str)
        return cached_at_str
    except ValueError:
        return None


def _count_collaborators_via_commits(
    client: GitHubClient,
    org: str,
    repo_name: str,
    since: str | None = None,
) -> set[str]:
    """Collect unique collaborators from default branch commit history.

    Iterates all commits on the default branch via GraphQL and collects
    distinct authors by GitHub login.  Uses ``authors(first: 100)`` to
    cover both the primary author and all ``Co-authored-by:`` trailer
    entries, including large merge commits.  Authors without a linked
    GitHub account are skipped.

    Args:
        client: GitHub API client
        org: Organisation login
        repo_name: Repository name
        since: Optional ISO 8601 timestamp; only commits after this date are
            fetched.  When omitted, the full history is traversed.

    Returns:
        Set of collaborator logins
    """
    query = """
    query (
        $org: String!, $repo: String!, $cursor: String, $since: GitTimestamp
    ) {
        repository(owner: $org, name: $repo) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor, since: $since) {
                            pageInfo {
                                hasNextPage
                                endCursor
                            }
                            nodes {
                                authors(first: 100) {
                                    nodes {
                                        user {
                                            login
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    """
    unique_authors: set[str] = set()
    cursor: str | None = None
    has_next_page = True

    while has_next_page:
        try:
            result = client.graphql(
                query,
                {
                    "org": org,
                    "repo": repo_name,
                    "cursor": cursor,
                    "since": since,
                },
            )
        except RateLimitExceededException:
            logger.warning(
                "Rate limit hit, sleeping %ds", RATE_LIMIT_SLEEP_SECONDS
            )
            time.sleep(RATE_LIMIT_SLEEP_SECONDS)
            continue

        if not isinstance(result, dict):
            logger.warning(
                "Invalid GraphQL response while fetching collaborators "
                "for %s/%s; expected dict but got %s",
                org,
                repo_name,
                type(result).__name__,
            )
            return set()
        branch_ref = (result.get("repository") or {}).get(
            "defaultBranchRef"
        )
        if not branch_ref:
            break

        target = branch_ref.get("target") or {}
        history = target.get("history")
        if not history:
            logger.debug(
                "No commit history available for %s/%s default branch target",
                org,
                repo_name,
            )
            break
        for commit in history.get("nodes") or []:
            if not commit:
                continue
            for author in (commit.get("authors", {}).get("nodes") or []):
                if not author:
                    continue
                user = author.get("user")
                login = user.get("login") if user else None
                if login:
                    unique_authors.add(login)

        page_info = history.get("pageInfo", {})
        has_next_page = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")

    return unique_authors


def _fetch_all_collaborators(
    client: GitHubClient,
    org: str,
    repos: list[dict[str, Any]],
    cache: dict[str, dict],
) -> dict[str, int]:
    """Fetch collaborator counts for all repositories.

    Uses commit history on the default branch via GraphQL to collect
    distinct authors.  The cache acts as a historical record: if an entry
    exists for a repo, only commits since ``cached_at`` are fetched and
    any newly discovered authors are merged in.  On the first run for a
    repo the full history is traversed.

    Args:
        client: GitHub API client
        org: Organisation login
        repos: List of repo dicts (must contain ``"name"`` key)
        cache: Mutable cache dict updated in place

    Returns:
        Mapping of repo name to collaborator count
    """
    counts: dict[str, int] = {}
    now = datetime.now(tz=timezone.utc).isoformat()

    logger.info(
        "Fetching collaborators for %d repositories", len(repos)
    )

    for repo in repos:
        repo_name = repo["name"]
        entry = cache.get(repo_name, {})
        since = _parse_cached_at(entry)
        known_collaborators: set[str] = set(entry.get("collaborators", []))

        if since:
            logger.debug("%s: fetching commits since %s", repo_name, since)
        else:
            logger.debug("%s: fetching full commit history", repo_name)

        new_collaborators = _count_collaborators_via_commits(
            client, org, repo_name, since=since
        )
        all_collaborators = known_collaborators | new_collaborators
        cache[repo_name] = {
            "collaborators": sorted(all_collaborators),
            "cached_at": now,
        }
        counts[repo_name] = len(all_collaborators)
        logger.debug("%s: %d collaborators", repo_name, len(all_collaborators))

    return counts


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
    """  # noqa: E501

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

    # Fetch collaborator counts (cached by repo, refreshed incrementally)
    cache = _load_collaborators_cache(config.organization)
    collaborators_map = _fetch_all_collaborators(
        client, config.organization, all_repos, cache
    )
    _save_collaborators_cache(config.organization, cache)

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
            collaborators_count=collaborators_map.get(repo_name, 0),
            issues_enabled=repo.get("hasIssuesEnabled", False),
            projects_enabled=repo.get("hasProjectsEnabled", False),
            discussions_enabled=repo.get("hasDiscussionsEnabled", False),
            projects_v2_count=repo.get("projectsV2", {}).get("totalCount", 0),
        )

    return result
