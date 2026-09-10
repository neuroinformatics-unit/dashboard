# Open Source Software Metrics Dashboard

A dashboard to get an overview of your organization's open source repository health.

The dashboard fetches data from the GitHub API and displays it in a Quarto-powered site. It provides the following information about your repositories:

- Repository metadata (license, topics, stars, forks, watchers)
- Issue and PR counts (open, closed, merged)
- Metrics around response times for issues
- Download statistics from PyPI and Conda
- BrainGlobe atlas download statistics, from the atlas bucket's S3 access logs (the "Atlas usage" page)

## Configuration

Edit `oss_dashboard/config.yml` to configure the dashboard:

```yaml
---
# Organizations to pull metrics from (can be a single string or array)
organization: ['org-name-1', 'org-name-2']

# Start date to pull metrics from (ISO 8601 format)
since: '2024-01-01'

# GitHub Pages base path (for relative asset paths)
basePath: '/dashboard'
```

## Environment Variables

Create a `.env` file in the root of the project with the following variables:

```sh
GRAPHQL_TOKEN=your_github_token
PEPY_API_KEY=your_pepy_api_key
```

The `GRAPHQL_TOKEN` requires the following GitHub scopes:
- `read:org`
- `read:repo`
- `read:project`

> [!NOTE]
> To fetch contributor counts, the token must belong to an organization admin.

Get a PEPY API key from [pepy.tech](https://www.pepy.tech/pepy-api) for PyPI download statistics.

For the **Atlas usage** page, the fetcher reads S3 server access logs from the
bucket configured under `atlasLogs` in `config.yml` and needs AWS credentials
with `s3:ListBucket` / `s3:GetObject` on that bucket:

```sh
AWS_ACCESS_KEY_ID=your_key_id
AWS_SECRET_ACCESS_KEY=your_secret
```

## Installation

```sh
pip install ".[dev]"
```

## Usage

### Fetch Data

```sh
python -m oss_dashboard.main
```

This fetches metrics for all configured organizations and writes JSON files to `oss_dashboard/data/`.

### Update atlas usage statistics

```sh
python -m oss_dashboard.atlas_logs                 # incremental: only new S3 logs
python -m oss_dashboard.atlas_logs --local-dir DIR # parse already-downloaded logs
python -m oss_dashboard.atlas_logs --full-rebuild  # reprocess everything
```

This appends per-day totals (successful `REST.GET.OBJECT` downloads only) to
three committed Parquet summaries, kept separate so no dimension inflates
another: `atlas_usage.parquet` (`date × atlas × resource`),
`atlas_usage_by_country.parquet` (`date × country`) and
`atlas_usage_by_tool.parquet` (`date × tool`, where the tool —
brainglobe-atlasapi, neuroglancer, Pinpoint, direct download, … — is inferred
from the request's `Referer` and `User-Agent`). Progress is tracked with a
cursor in `atlas_usage_state.json`. All files live in `oss_dashboard/data/`
and are committed to the repo; CI updates them daily.

### Render Dashboard

Requires [Quarto](https://quarto.org/) to be installed.

```sh
quarto render
```

This creates a static HTML site in the `build` directory.
