# Open Source Software Metrics Dashboard

A dashboard showing various Neuroinformatics Unit project metrics. 

The dashboard fetches data from the GitHub, PyPI and AWS and displays it in a Quarto-powered site. It provides the following information:

- Repository metadata (license, topics, stars, forks, watchers)
- Issue and PR counts (open, closed, merged)
- Metrics around response times for issues
- Download statistics from PyPI and Conda
- BrainGlobe atlas download statistics

## Repositories configuration

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

This appends per-day totals (successful `REST.GET.OBJECT` requests, HTTP
200/206, only) to three committed Parquet summaries, kept independent (no
cross-tabs) so no dimension inflates another: `atlas_usage.parquet`
(`date × atlas × resource`), `atlas_usage_by_country.parquet`
(`date × country`, geolocated from the requester's IP) and
`atlas_usage_by_tool.parquet` (`date × tool`). Progress is tracked with a
cursor in `atlas_usage_state.json`. All files live in `oss_dashboard/data/`
and are committed to the repo; CI updates them daily.

Each atlas is served as several resources (an annotation volume, one or more
reference/template images, a terminology, a packaged download, a
neuroglancer state file) under separate S3 key namespaces - only the
annotation keys carry the canonical atlas name, so the atlas breakdown is
built from those (`oss_dashboard/atlas_logs/parser.py::classify_key`).

Atlases are stored as OME-Zarr; each store's group-root `zarr.json` is
fetched once per "open", separately from the (many, size-dependent) chunk
files a client then reads. `classify_key` tags that specific fetch as a
`"<resource>-manifest"` row (`_is_zarr_group_manifest`), giving a request
count that isn't skewed by array size or how much of it was actually read -
used as the atlas popularity proxy on the dashboard. Country and tool have
no resource dimension to carry that same split as separate rows, so they
instead get it as an additional `manifest_requests` measure column,
resource-agnostic across every atlas.

The tool is inferred from each request's `Referer` and `User-Agent`
(`classify_client`): the browser viewers (neuroglancer, Pinpoint) set a
recognisable `Referer`; library/CLI clients are told apart by `User-Agent`,
with `aiobotocore`/`botocore`/`s3fs`/`pooch` attributed to
`brainglobe-atlasapi` (how it reads the OME-Zarr atlases and fetches some
non-Zarr downloads).

### Render Dashboard

Requires [Quarto](https://quarto.org/) to be installed.

```sh
quarto render
```

This creates a static HTML site in the `build` directory.
