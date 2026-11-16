"""Map atlas keys (as derived by ``classify_key``) to human-readable names.

This is a display-only concern: the summary Parquet keeps the raw key, and
this module maps it to the atlas's full name for the dashboard page.

The dashboard counts atlases from their ``atlas/atlases/<name>_<res>um/``
manifest keys (``resource == "atlas-manifest"``), whose folder name is the
canonical brainglobe-atlasapi atlas key minus the resolution suffix (which
``classify_key`` strips), e.g. ``demba_allen_seg_dev_mouse_p21``.

Names are fetched at render time from the Markdown source of BrainGlobe's
atlas-details page (``_DOCS_URL``), where each atlas is a
``### [Full name](link)`` heading followed by ``* `key_25um` `` bullets.
Series that share one heading (DeMBA, Kim Lab dev CCF, ...) get the stage
and/or imaging modality parsed from the key appended. Keys missing from the
page (demo or unlisted atlases), or every key if the fetch fails, fall back
to the atlas key itself (e.g. ``nmt_arm_sym_macaque``) rather than a
guessed name.
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache

import requests

_DOCS_URL = (
    "https://raw.githubusercontent.com/brainglobe/brainglobe.github.io/main/"
    "docs/source/documentation/brainglobe-atlasapi/usage/atlas-details.md"
)

_HEADING_RE = re.compile(r"^###\s+(?:\[(.+?)\]\(.*\)|(.+?))\s*$")
_KEY_BULLET_RE = re.compile(
    r"^\s*[*-]\s+`([a-z0-9_\-]+?)_\d+(?:\.\d+)?um`", re.IGNORECASE
)
# Stage and modality, only used to tell apart keys that share a heading.
_EMBRYONIC_RE = re.compile(r"_e(\d+)[-_]5(?=_|$)")
_POSTNATAL_RE = re.compile(r"_p(\d+)(?=_|$)")
_MODALITY_RE = re.compile(r"_(lsfm|idisco|stp|mri[-_][a-z0-9]+)$")
# The page's ADMBA heading ("... Derived from the Allen Developing Mouse
# Brain Atlases") is too long for the dashboard table.
_ADMBA_NAME = "3D Edge-Aware Refined Atlases"


def parse_atlas_details(markdown: str) -> dict[str, str]:
    """Parse the atlas-details Markdown into ``{atlas_key: name}``.

    Keys sharing a heading (an age/modality series) get a stage/modality
    suffix so each row of the dashboard table stays distinguishable.
    """
    headings: dict[str, str] = {}
    current = None
    for line in markdown.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            current = (heading.group(1) or heading.group(2)).rstrip(".")
            continue
        bullet = _KEY_BULLET_RE.match(line)
        if bullet and current:
            key = bullet.group(1).lower()
            name = _ADMBA_NAME if key.startswith("admba_3d_") else current
            headings.setdefault(key, name)

    shared = Counter(headings.values())
    return {
        key: _with_suffix(name, key) if shared[name] > 1 else name
        for key, name in headings.items()
    }


def _with_suffix(name: str, key: str) -> str:
    """Append the stage/modality parsed from ``key`` to ``name``, merging
    into a trailing parenthetical, e.g. ``"CCF v001 (P56)"`` + iDISCO ->
    ``"CCF v001 (P56, iDISCO)"``."""
    parts = []
    if embryonic := _EMBRYONIC_RE.search(key):
        parts.append(f"E{int(embryonic.group(1))}.5")
    elif postnatal := _POSTNATAL_RE.search(key):
        parts.append(f"P{int(postnatal.group(1))}")
    if modality := _MODALITY_RE.search(key):
        label = modality.group(1).lower()
        parts.append(
            "iDISCO"
            if label == "idisco"
            else label.replace("-", " ").replace("_", " ").upper()
        )
    if not parts:
        return name
    suffix = ", ".join(parts)
    if name.endswith(")"):
        return f"{name[:-1]}, {suffix})"
    return f"{name} ({suffix})"


@lru_cache(maxsize=1)
def _docs_names() -> dict[str, str]:
    """Fetch and parse the atlas-details page once per process; ``{}`` on
    any network error so the dashboard still renders with atlas keys."""
    try:
        response = requests.get(_DOCS_URL, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        return {}
    return parse_atlas_details(response.text)


def display_name(atlas_key: str) -> str:
    """Return the human-readable atlas name for a ``classify_key`` result.

    Falls back to the atlas key itself (the brainglobe-atlasapi atlas name)
    for atlases not on BrainGlobe's docs page, when it can't be fetched, and
    for ``"unclassified"``.
    """
    return _docs_names().get(atlas_key, atlas_key)
