from datetime import datetime
import json

import pandas as pd

from oss_dashboard.constants import MS_PER_DAY


def snake_to_title(name: str) -> str:
    """Convert snake_case to Title Case with spaces."""
    return name.replace("_", " ").title()


def format_data(data_path: str) -> pd.DataFrame:
    """Format JSON data for display in the dashboard."""
    with open(data_path) as f:
        data_json = json.load(f)
        data = data_json["repositories"]

    data = pd.DataFrame.from_dict(data, orient="index")
    data = data.reset_index(drop=True)
    date_accessed = datetime.fromisoformat(data_json["meta"]["created_at"])

    cols_to_keep = [
        "repository_name",
        "stars_count",
        "monthly_download_count",
        "total_download_count",
        "conda_monthly_downloads",
        "conda_total_downloads",
        "collaborators_count",
        "watchers_count",
        "open_issues_count",
        "closed_issues_count",
        "open_pull_requests_count",
        "merged_pull_requests_count",
        "forks_count",
        "open_issues_median_age",
        "open_issues_average_age",
        "closed_issues_median_age",
        "closed_issues_average_age",
        "issues_response_median_age",
        "issues_response_average_age",
        "topics",
        "license_name",
    ]

    rename_map = {
        "repository_name": "name",
        "license_name": "license",
        "stars_count": "stars",
        "monthly_download_count": "monthly downloads",
        "total_download_count": "total downloads",
        "conda_monthly_downloads": "conda monthly downloads",
        "conda_total_downloads": "conda total downloads",
        "collaborators_count": "collaborators",
        "watchers_count": "watchers",
        "open_issues_count": "open issues",
        "closed_issues_count": "closed issues",
        "open_pull_requests_count": "open PRs",
        "merged_pull_requests_count": "merged PRs",
        "forks_count": "forks",
    }

    data = data[cols_to_keep]
    data = data.rename(columns=rename_map)

    # Format topics as comma-separated list or empty string
    data["topics"] = data["topics"].apply(lambda x: ", ".join(x) if x else "")

    # Convert age columns from milliseconds to days
    age_cols = [
        "open_issues_median_age",
        "open_issues_average_age",
        "closed_issues_median_age",
        "closed_issues_average_age",
        "issues_response_median_age",
        "issues_response_average_age",
    ]
    for col in age_cols:
        days = data[col] / MS_PER_DAY
        data[col] = days.apply(
            lambda x: "<1 day" if x < 1 else f"{round(x)} days"
        )

    data.columns = [snake_to_title(col) for col in data.columns]

    return data, date_accessed
