"""Type definitions for the org metrics dashboard."""

from dataclasses import asdict, dataclass, field
from typing import Any


def dataclass_to_dict(obj: Any) -> dict[str, Any]:
    """Convert a dataclass to dict."""
    return asdict(obj)


@dataclass
class RepositoryResult:
    """Repository metrics data."""

    # Repo metadata
    repository_name: str = ""
    repo_name_with_owner: str = ""
    license_name: str = ""
    topics: list[str] = field(default_factory=list)

    # Counts
    projects_v2_count: int = 0
    discussions_count: int = 0
    forks_count: int = 0
    total_issues_count: int = 0
    open_issues_count: int = 0
    closed_issues_count: int = 0
    total_pull_requests_count: int = 0
    open_pull_requests_count: int = 0
    closed_pull_requests_count: int = 0
    merged_pull_requests_count: int = 0
    watchers_count: int = 0
    stars_count: int = 0
    collaborators_count: int = 0
    total_download_count: int = 0
    monthly_download_count: int = 0
    weekly_download_count: int = 0
    daily_download_count: int = 0
    contributors_count: int = 0
    conda_total_downloads: int = 0
    conda_monthly_downloads: int = 0

    # Flags
    discussions_enabled: bool = False
    projects_enabled: bool = False
    issues_enabled: bool = False

    # Calculated metrics
    open_issues_average_age: float = 0.0
    open_issues_median_age: float = 0.0
    closed_issues_average_age: float = 0.0
    closed_issues_median_age: float = 0.0
    issues_response_average_age: float = 0.0
    issues_response_median_age: float = 0.0

    def to_dict(self) -> dict:
        return dataclass_to_dict(self)


@dataclass
class OrgInfo:
    """Organization information."""

    login: str = ""
    name: str = ""
    description: str | None = None
    created_at: str = ""
    repositories_count: int = 0

    def to_dict(self) -> dict:
        return dataclass_to_dict(self)


@dataclass
class Meta:
    """Metadata about this run."""

    created_at: str = ""

    def to_dict(self) -> dict:
        return dataclass_to_dict(self)


@dataclass
class Result:
    """Complete result structure."""

    meta: Meta = field(default_factory=Meta)
    org_info: OrgInfo = field(default_factory=OrgInfo)
    repositories: dict[str, RepositoryResult] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dataclass_to_dict(self)


@dataclass
class Config:
    """Configuration for fetchers."""

    organization: str = ""
    include_forks: bool = False
    include_archived: bool = False
    since: str | None = None
