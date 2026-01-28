"""Fetcher for organization data and metrics."""

from oss_dashboard.github_client import GitHubClient
from oss_dashboard.models import Config, OrgInfo, Result


def add_organization_info_to_result(
    result: Result, client: GitHubClient, config: Config
) -> Result:
    """Add organization information to the result.

    Args:
        result: Current result object
        client: GitHub client
        config: Configuration

    Returns:
        Updated result with organization info
    """
    org = client.get_organization(config.organization)

    result.org_info = OrgInfo(
        login=org.login,
        name=org.name or org.login,
        description=org.description,
        created_at=org.created_at.isoformat() if org.created_at else "",
        repositories_count=org.public_repos,
    )

    return result
