#!/usr/bin/env bash
set -euo pipefail

python -m oss_dashboard.atlas_logs

# Pull requests only render with existing data - never push from a PR run.
if [ "$GITHUB_EVENT_NAME" = "pull_request" ]; then
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add oss_dashboard/data/atlas_usage.parquet \
        oss_dashboard/data/atlas_usage_by_country.parquet \
        oss_dashboard/data/atlas_usage_by_tool.parquet \
        oss_dashboard/data/atlas_usage_state.json
git diff --cached --quiet || git commit -m "Update atlas usage data [skip ci]"
git push
