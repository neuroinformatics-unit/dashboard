"""Unit tests for oss_dashboard.atlas_logs.tool_names."""

import pytest

from oss_dashboard.atlas_logs.tool_names import display_tool


@pytest.mark.parametrize(
    "tool",
    ["other", "other web viewer", "bot / crawler", "unknown"],
)
def test_display_tool_merges_catch_all_categories(tool):
    assert display_tool(tool) == "other/unknown"


@pytest.mark.parametrize(
    "tool",
    [
        "brainglobe-atlasapi",
        "neuroglancer",
        "pinpoint",
        "brainrender",
        "local / dev viewer",
        "python script",
        "node.js",
        "curl / wget",
        "aws-cli",
        "aws-sdk (other language)",
        "object_store (rust)",
        "browser (direct)",
    ],
)
def test_display_tool_leaves_recognised_clients_unchanged(tool):
    assert display_tool(tool) == tool


def test_all_classify_client_outcomes_are_handled():
    """Every string classify_client() can return must either pass through
    unchanged or land in "other/unknown" - never silently drop a category
    classify_client actually produces (e.g. a typo in the merge set)."""
    from oss_dashboard.atlas_logs.parser import (
        _REFERER_TOOLS,
        classify_client,
    )

    referer_tools = {tool for _, tool in _REFERER_TOOLS}
    user_agents = [
        ("brainrender", "brainrender/1.0"),
        ("-", "aiobotocore/3.9.0"),
        ("-", "pooch/1.8.0"),
        ("-", "aws-cli/2.0"),
        ("-", "aws-sdk-go/1.55.5"),
        ("-", "object_store/0.10"),
        ("-", "python-requests/2.32"),
        ("-", "node-fetch/1.0"),
        ("-", "curl/8.0"),
        ("-", "Googlebot/2.1"),
        ("-", "Mozilla/5.0"),
        ("-", "-"),
        ("-", "some-unrecognised-client/1.0"),
        ("http://localhost:8000/", "Mozilla/5.0"),
        ("https://example.com/", "Mozilla/5.0"),
    ]
    outcomes = referer_tools | {
        classify_client(referer, ua) for referer, ua in user_agents
    }
    for tool in outcomes:
        assert (
            display_tool(tool) == tool or display_tool(tool) == "other/unknown"
        )
