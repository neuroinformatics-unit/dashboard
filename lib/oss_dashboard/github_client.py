"""GitHub API client wrapper with rate limiting and retry logic."""

import logging
import time
from http import HTTPStatus
from typing import Any, Iterator

from github import Auth, Github, GithubException, RateLimitExceededException

from oss_dashboard.constants import RATE_LIMIT_SLEEP_SECONDS

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub API client with rate limiting and retry support."""

    def __init__(self, token: str):
        """Initialize the GitHub client.

        Args:
            token: GitHub personal access token
        """
        auth = Auth.Token(token)
        self.client = Github(auth=auth, retry=3, per_page=100)

    def get_organization(self, org_name: str):
        """Get organization by name.

        Args:
            org_name: Organization login name

        Returns:
            Organization object
        """
        return self.client.get_organization(org_name)

    def graphql(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict:
        """Execute a GraphQL query.

        Args:
            query: GraphQL query string
            variables: Query variables

        Returns:
            Query result as dictionary
        """
        if variables is None:
            variables = {}
        return self.client.requester.graphql_query(query, variables)[1]["data"]

    def graphql_paginate(
        self,
        query: str,
        variables: dict[str, Any],
        path_to_connection: list[str],
    ) -> Iterator[dict]:
        """Execute a paginated GraphQL query.

        Args:
            query: GraphQL query string with $cursor variable
            variables: Query variables
            path_to_connection: Path to the connection in response

        Yields:
            Combined results from all pages
        """
        cursor = None
        has_next_page = True

        while has_next_page:
            vars_with_cursor = {**variables, "cursor": cursor}

            try:
                result = self.graphql(query, vars_with_cursor)
            except RateLimitExceededException:
                logger.warning(
                    "Rate limit exceeded, waiting %d seconds",
                    RATE_LIMIT_SLEEP_SECONDS,
                )
                time.sleep(RATE_LIMIT_SLEEP_SECONDS)
                continue

            # Navigate to the connection
            data = result
            for key in path_to_connection:
                data = data[key]

            yield result

            page_info = data.get("pageInfo", {})
            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

    def rest_request(
        self, method: str, url: str, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        """Make a REST API request.

        Args:
            method: HTTP method
            url: Request URL (relative to API base)
            headers: Additional headers

        Returns:
            Tuple of (status_code, response_data)
        """
        if headers is None:
            headers = {}

        try:
            status, resp_headers, data = self.client.requester.requestJson(
                method, url, headers=headers
            )
            return status, data
        except GithubException as e:
            logger.error("GitHub API request failed: %s", e)
            return HTTPStatus.INTERNAL_SERVER_ERROR, None


def check_rate_limit(client: GitHubClient) -> dict:
    """Check the current rate limit status.

    Args:
        client: GitHub client instance

    Returns:
        Dictionary with rate limit info
    """
    rate_limit = client.client.get_rate_limit()
    core = rate_limit.rate

    return {
        "limit": core.limit,
        "remaining": core.remaining,
        "reset": core.reset.timestamp(),
        "reset_date": core.reset,
    }
