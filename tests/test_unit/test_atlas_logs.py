"""Unit tests for the ``oss_dashboard.atlas_logs`` pipeline."""

import ipaddress

import pandas as pd
import pytest

from oss_dashboard.atlas_logs.constants import (
    ATLAS_KEY,
    COUNTRY_KEY,
    TOOL_KEY,
)
from oss_dashboard.atlas_logs.geoip import CountryLookup
from oss_dashboard.atlas_logs.parser import (
    classify_client,
    classify_key,
    event_date,
    parse_line,
)
from oss_dashboard.atlas_logs.pipeline import accumulate, run
from oss_dashboard.atlas_logs.store import (
    counts_to_frame,
    load_state,
    load_summary,
    merge_summary,
)

SAMPLE = (
    "OWNERHASH brainglobe [12/Aug/2026:14:48:48 +0000] 8.8.8.8 - REQ1 "
    "REST.GET.OBJECT "
    "atlas/annotation-sets/allen_mouse-annotation/3_0/s0/c/1/2/3 "
    '"GET /atlas/annotation-sets/allen_mouse-annotation/3_0/s0/c/1/2/3 '
    'HTTP/1.1" 200 - 58549 58549 51 51 "-" "aiobotocore/3.9.0" - h - '
    "TLS_AES_128_GCM_SHA256 - brainglobe.s3.amazonaws.com TLSv1.3 - - -"
)


def _line(
    operation="REST.GET.OBJECT",
    key="atlas/x",
    status="200",
    bytes_="10",
    referer="-",
    user_agent="ua",
):
    return (
        f"OWNER brainglobe [12/Aug/2026:14:48:48 +0000] 8.8.8.8 - REQ "
        f'{operation} {key} "GET /{key} HTTP/1.1" {status} - {bytes_} '
        f'20 5 5 "{referer}" "{user_agent}" - - - - -'
    )


def test_parse_line_extracts_needed_fields():
    record = parse_line(SAMPLE)
    assert record is not None
    assert record.date == "2026-08-12"
    assert record.remote_ip == "8.8.8.8"
    assert record.operation == "REST.GET.OBJECT"
    assert record.key.startswith(
        "atlas/annotation-sets/allen_mouse-annotation"
    )
    assert record.http_status == 200
    assert record.bytes_sent == 58549
    assert record.referer == "-"
    assert record.user_agent.startswith("aiobotocore/3.9.0")


def test_parse_line_captures_referer_and_user_agent():
    record = parse_line(
        _line(referer="https://neuroglancer-demo.appspot.com/", user_agent="M")
    )
    assert record is not None
    assert record.referer == "https://neuroglancer-demo.appspot.com/"
    assert record.user_agent == "M"


def test_parse_line_without_referer_tail_still_parses():
    # Truncated line: everything through bytes_sent, nothing after.
    core = (
        "OWNER brainglobe [12/Aug/2026:14:48:48 +0000] 8.8.8.8 - REQ "
        'REST.GET.OBJECT atlas/x "GET /x HTTP/1.1" 200 - 123'
    )
    record = parse_line(core)
    assert record is not None
    assert record.bytes_sent == 123
    assert record.referer == "-"
    assert record.user_agent == "-"


def test_parse_line_handles_bare_dash_request_uri():
    # Internal pseudo-operations (e.g. REST.COPY.OBJECT_GET/_PUT, used for
    # x-amz-copy-source permission checks) have no HTTP request at all, so
    # AWS writes a bare "-" instead of a quoted request-uri. Seen for real
    # against brainglobe-logs on 2026-09-04 (a bulk-scraper role probing
    # copy permissions, all 403s) - never for REST.GET.OBJECT.
    line = (
        "OWNER brainglobe [04/Sep/2026:00:20:15 +0000] 34.221.23.144 "
        "arn:aws:sts::093240468649:assumed-role/some-role/session "
        "REQ REST.COPY.OBJECT_GET atlas/x - 403 AccessDenied - - - -"
    )
    record = parse_line(line)
    assert record is not None
    assert record.operation == "REST.COPY.OBJECT_GET"
    assert record.http_status == 403
    assert record.bytes_sent == 0


def test_parse_line_handles_missing_values():
    record = parse_line(_line(status="-", bytes_="-"))
    assert record is not None
    assert record.http_status is None
    assert record.bytes_sent == 0


def test_parse_line_rejects_junk():
    assert parse_line("not a log line") is None
    assert parse_line("") is None


def test_event_date():
    assert event_date("12/Aug/2026:14:48:48 +0000") == "2026-08-12"
    assert event_date("01/Jan/2025:00:00:00 +0000") == "2025-01-01"


@pytest.mark.parametrize(
    "key, expected",
    [
        (
            "atlas/annotation-sets/allen_mouse-annotation/3_0/x",
            ("allen_mouse", "annotation"),
        ),
        (
            "atlas/templates/allen-adult-mouse-stpt-template/3_0/x",
            ("allen_adult_mouse_stpt", "template"),
        ),
        (
            "atlas/terminologies/allen_mouse-terminology/1/x",
            ("allen_mouse", "terminology"),
        ),
        (
            "atlas/atlases/allen_mouse_25um.tar.gz",
            ("allen_mouse", "packaged-atlas"),
        ),
        (
            "atlas/atlases/admba_3d_p14_mouse_16.752um.tar.gz",
            ("admba_3d_p14_mouse", "packaged-atlas"),
        ),
        (
            "atlas/atlases/last_versions.conf",
            ("unclassified", "other"),
        ),
        ("ng_state_files/allen_mouse.json", ("allen_mouse", "ng-state")),
        ("atlas/", ("unclassified", "other")),
        ("-", ("unclassified", "other")),
        ("wp-admin/admin-ajax.php", ("unclassified", "other")),
    ],
)
def test_classify_key(key, expected):
    assert classify_key(key) == expected


@pytest.mark.parametrize(
    "referer, user_agent, expected",
    [
        ("https://neuroglancer-demo.appspot.com/", "Mozilla", "neuroglancer"),
        ("https://pinpoint.allenneuraldynamics.org/", "Mozilla", "pinpoint"),
        ("http://localhost:9000/", "Mozilla", "local / dev viewer"),
        ("https://kennethjyang.github.io/", "Mozilla", "other web viewer"),
        (
            "-",
            "aiobotocore/3.9.0 md/Botocore#1.43 lang/python#3.12",
            "brainglobe-atlasapi",
        ),
        ("-", "python-requests/2.34.2", "python script"),
        ("-", "curl/8.4.0", "curl / wget"),
        ("-", "aws-cli/2.15.0 Python/3.11", "aws-cli"),
        ("-", "aws-sdk-go/1.55.5 (go1.22)", "aws-sdk (other language)"),
        ("-", "object_store/0.11.0", "object_store (rust)"),
        ("-", "node", "node.js"),
        ("-", "brainrender-track-export/1.0", "brainrender"),
        ("-", "Mozilla/5.0 (Macintosh)", "browser (direct)"),
        ("-", "-", "unknown"),
        ("-", "facebookexternalhit/1.1", "bot / crawler"),
        ("-", "Mozilla/5.0 (compatible; Googlebot/2.1)", "bot / crawler"),
    ],
)
def test_classify_client(referer, user_agent, expected):
    assert classify_client(referer, user_agent) == expected


def _lookup():
    def as_int(text):
        return int(ipaddress.ip_address(text))

    v4 = (
        [as_int("1.0.0.0"), as_int("8.8.8.0")],
        [as_int("1.0.0.255"), as_int("8.8.8.255")],
        ["AU", "US"],
    )
    v6 = (
        [as_int("2001:200::")],
        [as_int("2001:218:ffff:ffff:ffff:ffff:ffff:ffff")],
        ["JP"],
    )
    return CountryLookup(v4, v6)


def test_country_lookup():
    lookup = _lookup()
    assert lookup.lookup("8.8.8.8") == "US"
    assert lookup.lookup("1.0.0.5") == "AU"
    assert lookup.lookup("9.9.9.9") == "??"
    assert lookup.lookup("2001:200::1") == "JP"
    assert lookup.lookup("not-an-ip") == "??"


def test_accumulate_counts_only_successful_downloads():
    lookup = _lookup()
    text = "\n".join(
        [
            _line(
                key="atlas/annotation-sets/allen_mouse-annotation/3_0/a",
                bytes_="100",
                user_agent="aiobotocore/3.9.0 lang/python#3.12",
            ),
            _line(
                key="atlas/annotation-sets/allen_mouse-annotation/3_0/b",
                bytes_="50",
                referer="https://pinpoint.allenneuraldynamics.org/",
                user_agent="Mozilla/5.0",
            ),
            _line(operation="REST.PUT.OBJECT", key="atlas/x"),  # not a GET
            _line(status="404", key="atlas/x"),  # failed
            "garbage line",  # unparsable
        ]
    )
    atlas_counts: dict = {}
    country_counts: dict = {}
    tool_counts: dict = {}
    parsed, skipped = accumulate(
        text, atlas_counts, country_counts, tool_counts, lookup
    )

    assert parsed == 4
    assert skipped == 1
    # the three breakdowns are independent, not crossed
    assert atlas_counts == {
        ("2026-08-12", "allen_mouse", "annotation"): [2, 150]
    }
    assert country_counts == {("2026-08-12", "US"): [2, 150]}
    assert tool_counts == {
        ("2026-08-12", "brainglobe-atlasapi"): [1, 100],
        ("2026-08-12", "pinpoint"): [1, 50],
    }


def test_merge_summary_sums_repeated_keys():
    existing = counts_to_frame(
        {("2026-08-12", "allen_mouse", "annotation"): [10, 1000]}, ATLAS_KEY
    )
    new_rows = counts_to_frame(
        {
            ("2026-08-12", "allen_mouse", "annotation"): [5, 500],
            ("2026-08-13", "kim_mouse", "template"): [3, 300],
        },
        ATLAS_KEY,
    )
    merged = merge_summary(existing, new_rows, ATLAS_KEY)

    row = merged[
        (merged["date"] == "2026-08-12") & (merged["atlas"] == "allen_mouse")
    ].iloc[0]
    assert row["requests"] == 15
    assert row["bytes_sent"] == 1500
    assert merged["requests"].sum() == 18
    assert list(merged["date"]) == ["2026-08-12", "2026-08-13"]


def test_run_over_local_dir(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "2026-08-12-00-00-00-AAAA").write_text(
        "\n".join(
            _line(
                key="atlas/annotation-sets/allen_mouse-annotation/3_0/a",
                bytes_="100",
                user_agent="aiobotocore/3.9.0",
            )
            for _ in range(3)
        )
    )
    (logs / "2026-08-12-01-00-00-BBBB").write_text(
        _line(
            key="atlas/templates/kim-mouse-template/1/t",
            bytes_="7",
            referer="https://neuroglancer-demo.appspot.com/",
            user_agent="Mozilla/5.0",
        )
    )

    atlas_path = tmp_path / "atlas_usage.parquet"
    country_path = tmp_path / "atlas_usage_by_country.parquet"
    tool_path = tmp_path / "atlas_usage_by_tool.parquet"
    state = tmp_path / "atlas_usage_state.json"
    kwargs = dict(
        bucket="",
        region="us-west-2",
        local_dir=logs,
        atlas_path=atlas_path,
        country_path=country_path,
        tool_path=tool_path,
        state_path=state,
        country_lookup=_lookup(),
    )

    result = run(**kwargs)

    assert result["objects"] == 2
    assert result["downloads"] == 4
    assert result["last_key"] == "2026-08-12-01-00-00-BBBB"

    atlas = load_summary(atlas_path, ATLAS_KEY)
    assert set(atlas["atlas"]) == {"allen_mouse", "kim_mouse"}
    assert set(atlas["resource"]) == {"annotation", "template"}
    assert "country" not in atlas.columns
    assert atlas["bytes_sent"].sum() == 307

    country = load_summary(country_path, COUNTRY_KEY)
    assert list(country.columns) == [
        "date",
        "country",
        "requests",
        "bytes_sent",
    ]
    assert country["requests"].sum() == 4  # every download, once
    assert set(country["country"]) == {"US"}

    tool = load_summary(tool_path, TOOL_KEY)
    assert list(tool.columns) == ["date", "tool", "requests", "bytes_sent"]
    assert dict(zip(tool["tool"], tool["requests"])) == {
        "brainglobe-atlasapi": 3,
        "neuroglancer": 1,
    }

    saved_state = load_state(state)
    assert saved_state["last_key"] == "2026-08-12-01-00-00-BBBB"
    assert saved_state["objects_processed"] == 2

    # A second run with the cursor in place sees nothing new.
    again = run(**kwargs)
    assert again["objects"] == 0
    assert again["downloads"] == 4  # unchanged cumulative total


def test_run_full_rebuild_ignores_existing(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "2026-08-12-00-00-00-AAAA").write_text(
        _line(
            key="atlas/annotation-sets/allen_mouse-annotation/3_0/a",
            bytes_="100",
        )
    )
    atlas_path = tmp_path / "atlas_usage.parquet"
    country_path = tmp_path / "atlas_usage_by_country.parquet"
    tool_path = tmp_path / "atlas_usage_by_tool.parquet"
    state = tmp_path / "atlas_usage_state.json"
    common = dict(
        bucket="",
        region="us-west-2",
        local_dir=logs,
        atlas_path=atlas_path,
        country_path=country_path,
        tool_path=tool_path,
        state_path=state,
        country_lookup=_lookup(),
    )

    run(**common)
    run(**common)  # cursor now past the only file
    rebuilt = run(full_rebuild=True, **common)

    assert rebuilt["downloads"] == 1
    assert load_summary(atlas_path, ATLAS_KEY)["requests"].sum() == 1
    assert load_summary(country_path, COUNTRY_KEY)["requests"].sum() == 1
    assert load_summary(tool_path, TOOL_KEY)["requests"].sum() == 1


def test_load_summary_missing_file_is_empty(tmp_path):
    atlas = load_summary(tmp_path / "nope.parquet", ATLAS_KEY)
    assert atlas.empty
    assert list(atlas.columns) == [
        "date",
        "atlas",
        "resource",
        "requests",
        "bytes_sent",
    ]
    assert isinstance(atlas, pd.DataFrame)

    country = load_summary(tmp_path / "nope2.parquet", COUNTRY_KEY)
    assert list(country.columns) == [
        "date",
        "country",
        "requests",
        "bytes_sent",
    ]
