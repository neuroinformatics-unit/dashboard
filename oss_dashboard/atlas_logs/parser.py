"""Parse AWS S3 *server access log* lines and classify the object keys.

The server access log format is space separated, with ``[...]`` around the
timestamp and ``"..."`` around a handful of free-text fields. Fields are
appended over time, so we only pin down the fixed leading portion (up to
``bytes_sent``) and ignore the rest. Missing values are written as ``-``.

Reference:
https://docs.aws.amazon.com/AmazonS3/latest/userguide/LogFormat.html
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Everything up to and including ``bytes_sent`` has no quoted-space
# ambiguity except ``request_uri``, which is normally a whole "..." token -
# except for a handful of internal pseudo-operations (observed:
# REST.COPY.OBJECT_GET/_PUT, used for x-amz-copy-source permission checks)
# that have no HTTP request at all, so AWS writes a bare "-" instead of a
# quoted string. Accept either. These are never REST.GET.OBJECT, so they
# don't affect download counts either way - this is about not
# mis-classifying a valid log line as unparsable.
# The referer/user-agent tail is optional: if a weird line does not have it
# we still keep the row (with referer/user_agent unknown) rather than drop it.
_LINE_RE = re.compile(
    r"^\S+ "  # bucket owner
    r"(?P<bucket>\S+) "
    r"\[(?P<time>[^\]]+)\] "
    r"(?P<remote_ip>\S+) "
    r"\S+ "  # requester
    r"(?P<request_id>\S+) "
    r"(?P<operation>\S+) "
    r"(?P<key>\S+) "
    r'(?:"[^"]*"|-) '  # request-uri, or "-" when there was no HTTP request
    r"(?P<http_status>\S+) "
    r"\S+ "  # error code
    r"(?P<bytes_sent>\S+)"
    r"(?: "
    r"\S+ \S+ \S+ "  # object size, total time, turn-around time
    r'"(?P<referer>[^"]*)" '
    r'"(?P<user_agent>[^"]*)"'
    r")?"
)

_MONTHS = {
    "Jan": "01",
    "Feb": "02",
    "Mar": "03",
    "Apr": "04",
    "May": "05",
    "Jun": "06",
    "Jul": "07",
    "Aug": "08",
    "Sep": "09",
    "Oct": "10",
    "Nov": "11",
    "Dec": "12",
}

# Suffixes attached to the third key segment for each atlas resource kind.
_RESOURCE_SUFFIXES = {
    "-annotation": "annotation",
    "-template": "template",
    "-terminology": "terminology",
    "-reference": "reference",
    "-meshes": "meshes",
}

# Trailing resolution token on packaged-atlas names, e.g. "allen_mouse_25um"
# or "admba_3d_p14_mouse_16.752um" -> strip so versions of one atlas collapse.
_RESOLUTION_RE = re.compile(r"_\d+(?:\.\d+)?um$")
_ARCHIVE_EXTENSIONS = (".tar.gz", ".tar", ".tgz", ".zip", ".conf", ".json")

# Non-atlas objects that live under atlas/atlases/.
_ATLASES_NON_ATLAS = {"last_versions"}

# Which client fetched the data, inferred from the Referer (strong signal:
# the web viewers set it) then the User-Agent. Order matters.
_REFERER_TOOLS = (
    ("neuroglancer", "neuroglancer"),
    ("pinpoint", "pinpoint"),
)
_LOCALHOST_RE = re.compile(r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)[:/]")
_SELF_REFERER = "brainglobe.s3"


@dataclass(frozen=True)
class LogRecord:
    """The fields of one access-log line that the summary needs."""

    date: str  # ISO date, e.g. "2026-08-12"
    remote_ip: str
    operation: str
    key: str
    http_status: int | None
    bytes_sent: int
    referer: str = "-"
    user_agent: str = "-"


def event_date(time_field: str) -> str:
    """Convert ``12/Aug/2026:14:48:48 +0000`` to ``2026-08-12``."""
    day, month, rest = time_field.split("/", 2)
    year = rest[:4]
    return f"{year}-{_MONTHS[month]}-{day}"


def parse_line(line: str) -> LogRecord | None:
    """Parse one access-log line, or return ``None`` if it does not match."""
    match = _LINE_RE.match(line)
    if match is None:
        return None

    raw_status = match["http_status"]
    raw_bytes = match["bytes_sent"]

    return LogRecord(
        date=event_date(match["time"]),
        remote_ip=match["remote_ip"],
        operation=match["operation"],
        key=match["key"],
        http_status=int(raw_status) if raw_status.isdigit() else None,
        bytes_sent=int(raw_bytes) if raw_bytes.isdigit() else 0,
        referer=match["referer"] or "-",
        user_agent=match["user_agent"] or "-",
    )


def classify_client(referer: str, user_agent: str) -> str:
    """Infer which tool made the request from its Referer and User-Agent.

    The browser-based viewers (neuroglancer, Pinpoint) set a recognisable
    Referer. Requests with no/self Referer are library or command-line
    clients and are told apart by User-Agent - notably ``aiobotocore`` /
    ``botocore`` (``s3fs`` + ``zarr``), which is how ``brainglobe-atlasapi``
    reads the OME-Zarr atlases.
    """
    ref = referer.lower()
    ua = user_agent.lower()

    for needle, tool in _REFERER_TOOLS:
        if needle in ref:
            return tool
    if _LOCALHOST_RE.match(ref):
        return "local / dev viewer"
    if ref.startswith(("http://", "https://")) and _SELF_REFERER not in ref:
        return "other web viewer"

    # Specific tools first - some library UAs contain "bot" (aiobotocore!),
    # so the generic bot check has to come after them.
    if "brainrender" in ua:
        return "brainrender"
    if any(s in ua for s in ("aiobotocore", "botocore", "boto3", "s3fs")):
        return "brainglobe-atlasapi"
    if "pooch" in ua:
        return "brainglobe-atlasapi"
    if ua.startswith("aws-cli"):
        return "aws-cli"
    if "aws-sdk" in ua:
        return "aws-sdk (other language)"
    if "object_store" in ua:
        return "object_store (rust)"
    if any(s in ua for s in ("python-requests", "urllib", "aiohttp", "httpx")):
        return "python script"
    if ua.startswith(("node", "undici")) or "node-fetch" in ua:
        return "node.js"
    if ua.startswith(("curl/", "wget/")):
        return "curl / wget"
    if any(
        s in ua
        for s in ("bot", "crawler", "spider", "slurp", "facebookexternalhit")
    ) or ua.startswith("google-"):
        return "bot / crawler"
    if "mozilla" in ua:
        return "browser (direct)"
    if ua in ("-", ""):
        return "unknown"
    return "other"


def classify_key(key: str) -> tuple[str, str]:
    """Map an S3 object key to ``(atlas, resource)``.

    The ``atlas`` is the BrainGlobe atlas name; ``resource`` is what kind of
    object it is (``annotation``, ``template``, ``reference``, ``terminology``,
    ``packaged-atlas``, ``ng-state``, ...). One atlas has several resources,
    each under its own key namespace - only ``annotation`` names use the
    canonical atlas identifier, so the dashboard counts atlases from those.

    Examples (key -> result)::

        atlas/annotation-sets/allen_mouse-annotation/3_0/a
            -> ("allen_mouse", "annotation")
        atlas/templates/allen-adult-mouse-stpt-template/3_0/t
            -> ("allen_adult_mouse_stpt", "template")
        atlas/atlases/allen_mouse_25um.tar.gz
            -> ("allen_mouse", "packaged-atlas")
        ng_state_files/allen_mouse.json
            -> ("allen_mouse", "ng-state")

    Anything that is not atlas data is ``("unclassified", "other")``.
    """
    if not key or key == "-":
        return "unclassified", "other"

    parts = key.split("/")

    if parts[0] == "ng_state_files" and len(parts) >= 2 and parts[1]:
        return parts[1].removesuffix(".json"), "ng-state"

    if parts[0] == "atlas" and len(parts) >= 3 and parts[2]:
        collection, name = parts[1], parts[2]

        if collection == "atlases":
            stem = name
            for ext in _ARCHIVE_EXTENSIONS:
                stem = stem.removesuffix(ext)
            stem = _RESOLUTION_RE.sub("", stem)
            if not stem or stem in _ATLASES_NON_ATLAS:
                return "unclassified", "other"
            return stem, "packaged-atlas"

        for suffix, resource in _RESOURCE_SUFFIXES.items():
            if name.endswith(suffix):
                atlas = name[: -len(suffix)].replace("-", "_")
                return atlas, resource

        return name.replace("-", "_"), collection

    return "unclassified", "other"
