"""Map atlas keys (as derived by ``classify_key``) to human-readable names.

This is a display-only concern: the summary Parquet keeps the raw key, and
this module maps it to the atlas's full name for the dashboard page.

The dashboard counts atlases from their ``atlas/atlases/<name>_<res>um/``
manifest keys (``resource == "atlas-manifest"``): brainglobe-atlasapi always
fetches an atlas's ``manifest.json`` first, and that folder name is the
canonical brainglobe-atlasapi atlas key (minus the resolution suffix, which
``classify_key`` strips), e.g. ``demba_allen_seg_dev_mouse_p21``. So this
map is keyed by those manifest names - *not* by the annotation-set folder
names, which differ in places (e.g. ``demba-p21-mouse``).

Names are sourced from BrainGlobe's public atlas table:
https://brainglobe.info/documentation/brainglobe-atlasapi/usage/atlas-details.html
(checked 2026-11-11). Keys seen in the bucket but not listed there (demo or
unlisted atlases) fall back to a formatted version of the key rather than a
guessed name.
"""

from __future__ import annotations

import re

# Exact matches, sourced from the BrainGlobe atlas-details page.
_NAMES: dict[str, str] = {
    "allen_mouse": "Allen Adult Mouse Brain Atlas",
    "allen_mouse_bluebrain_barrels": "BlueBrain Barrel Cortex Atlas",
    "allen_human": "Allen Human Brain Atlas",
    "allen_cord": "3D version of the Allen Mouse Spinal Cord Atlas",
    "australian_mouse": "Australian Mouse Brain Atlas",
    "azba_zfish": "AZBA: A 3D Adult Zebrafish Brain Atlas",
    "carea_mouse": "CArea Mouse Atlas",
    "ccfv1_mouse": "Allen CCFv1 Mouse Brain Atlas",
    "ccfv2_dev_mouse": "Allen CCFv2 Developmental Mouse Brain Atlas",
    "ccfv2_fiber_mouse": "Allen CCFv2 Mouse Fiber Tracts Atlas",
    "ccfv2_mouse": "Allen CCFv2 Mouse Brain Atlas",
    "ccfv3augmented_mouse": "CCFv3 Augmented Mouse Atlas",
    "columbia_cuttlefish": "Columbia Cuttlefish Atlas",
    "csl_cat": "Cat Brain Atlas",
    "danionella_cerebrum_mixed": "Danionella Cerebrum Brain Atlas",
    "dorr_mouse_mri": "Dorr MRI Mouse Atlas",
    "drosophila_wingdisc_instar3": "Drosophila Wing Disc Instar3 Atlas",
    "duke_mouse": "Duke Mouse Brain Atlas",
    "eurasian_blackcap": "Eurasian Blackcap Atlas",
    "hoops_tawny_dragon": "Hoops Tawny Dragon Brain Atlas",
    "kim_mouse": "Enhanced and Unified Mouse Brain Atlas",
    "kim_mouse_isotropic": "Enhanced and Unified Mouse Brain Atlas v2",
    "kocher_bumblebee": "Kocher Bumblebee Brain Atlas",
    "mpin_zfish": "Max Planck Zebrafish Brain Atlas",
    "nadkarni_mri_mouselemur": "MRI Mouse Lemur Brain Atlas",
    "osten_mouse": "Smoothed Version of the Kim et al. Mouse Reference Atlas",
    "perens_lsfm_mouse": "Gubra's LSFM Mouse Brain Atlas",
    "perens_multimodal_lsfm": "Gubra's LSFM Mouse Brain Atlas v2",
    "perens_stereotaxic_mri_mouse": "Gubra's MRI Mouse Brain Atlas",
    "prairie_vole": "Prairie Vole Brain Atlas",
    "princeton_mouse": "Princeton Mouse Brain Atlas",
    "sju_cavefish": "Blind Mexican Cavefish Brain Atlas",
    "swc_female_rat": "SWC Female Rat Brain Atlas",
    "unam_axolotl": "UNAM Axolotl Brain Atlas",
    "whs_sd_rat": "Waxholm Space Atlas of the Sprague Dawley Rat Brain",
    "whs_sd_swc_female_rat": "Waxholm-Aligned SWC Female Rat Atlas",
}

# Numbered series: (regex on the derived key) -> name template, filled with
# the captured age/stage number. Checked in order; first match wins.
_SERIES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^admba_3d_e(\d+)_5_mouse$"),
        "3D Edge-Aware Refined Atlases (E{0}.5)",
    ),
    (
        re.compile(r"^admba_3d_p(\d+)_mouse$"),
        "3D Edge-Aware Refined Atlases (P{0})",
    ),
    (
        re.compile(r"^demba_allen_seg_dev_mouse_p(\d+)$"),
        "DeMBA Developmental Mouse Brain Atlas (P{0})",
    ),
    (
        re.compile(r"^duke_dev_rat_p(\d+)$"),
        "Duke Developmental Rat Brain Atlas (P{0})",
    ),
    (
        re.compile(r"^lambada_dev_mouse_p(\d+)$"),
        "LAMBADA Developmental Mouse Brain Atlas (P{0})",
    ),
]

# Kim Lab developmental CCF: one atlas per (stage, imaging modality), e.g.
# "kim_dev_mouse_e11-5_mri-adc" or "kim_dev_mouse_p04_lsfm". The unstaged
# ones ("kim_dev_mouse_idisco", "kim_dev_mouse_mri_adc", ...) are the
# separately listed P56 "v001" release. Case-insensitive: the docs page
# writes "mri-T2" where the bucket has "mri-t2".
_KIM_DEV_RE = re.compile(
    r"^kim_dev_mouse_(?:(e)(\d+)-5_|(p)(\d+)_)?"
    r"(lsfm|idisco|stp|mri[-_][a-z0-9]+)$",
    re.IGNORECASE,
)


def _kim_dev(match: re.Match[str]) -> str:
    embryonic, e_day, _, p_day, modality = match.groups()
    modality = modality.lower()
    label = (
        "iDISCO"
        if modality == "idisco"
        else modality.replace("-", " ").replace("_", " ").upper()
    )
    if embryonic:
        return f"Kim Lab Developmental CCF v1.0 (E{int(e_day)}.5, {label})"
    if p_day:
        return f"Kim Lab Developmental CCF v1.0 (P{int(p_day)}, {label})"
    return f"Kim Lab Developmental CCF v001 (P56, {label})"


def _fallback(atlas_key: str) -> str:
    """Format an unmapped key as a readable label, e.g. ``foo_bar`` ->
    ``Foo Bar``. Used only for keys with no verified name (see module
    docstring) - never presented as an official BrainGlobe atlas name."""
    return atlas_key.replace("_", " ").title()


def display_name(atlas_key: str) -> str:
    """Return the human-readable atlas name for a ``classify_key`` result.

    Falls back to a title-cased version of the key for atlases with no
    verified name (demo atlases, or ones not yet listed on BrainGlobe's docs
    page) and for ``"unclassified"``.
    """
    if atlas_key in _NAMES:
        return _NAMES[atlas_key]

    for pattern, template in _SERIES:
        match = pattern.match(atlas_key)
        if match:
            number = match.group(1).lstrip("0") or "0"
            return template.format(number)

    kim = _KIM_DEV_RE.match(atlas_key)
    if kim:
        return _kim_dev(kim)

    return _fallback(atlas_key)
