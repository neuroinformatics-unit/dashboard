"""Map atlas keys (as derived by ``classify_key``) to human-readable names.

This is a display-only concern: the summary Parquet keeps the raw key (it's
what ``classify_key`` derives from the S3 object path, e.g. ``allen_mouse``),
and this module maps that key to the atlas's full name for the dashboard
page. The two intentionally differ in places - ``classify_key`` strips the
``-annotation`` suffix from whatever the raw S3 folder is named, which does
not always match BrainGlobe's current canonical atlas key (e.g. the raw
folder for the DeMBA series is ``demba-p21-mouse``, while the current
brainglobe-atlasapi key is ``demba_allen_seg_dev_mouse_p21``) - so this map
is keyed by the *derived* string actually seen in the data, not by
brainglobe-atlasapi's own key.

Names are sourced from BrainGlobe's public atlas table:
https://brainglobe.info/documentation/brainglobe-atlasapi/usage/atlas-details.html
(checked 2026-09-11). A few keys seen in the log data are not listed there
at all (demo/tutorial or older/unlisted atlases) - those fall back to a
formatted version of the key rather than a guessed name.
"""

from __future__ import annotations

import re

# Exact matches, sourced from the BrainGlobe atlas-details page.
_NAMES: dict[str, str] = {
    "allen_mouse": "Allen Adult Mouse Brain Atlas",
    "allen_mouse_bluebrain_barrels": "BlueBrain Barrel Cortex Atlas",
    "allen_adult_human": "Allen Human Brain Atlas",
    "allen_spinal_cord_adult_mouse": (
        "3D version of the Allen Mouse Spinal Cord Atlas"
    ),
    "australian_mouse": "Australian Mouse Brain Atlas",
    "azba_zfish": "AZBA: A 3D Adult Zebrafish Brain Atlas",
    "carea_mouse": "CArea Mouse Atlas",
    "ccfv2_dev_mouse": "Allen CCFv2 Developmental Mouse Brain Atlas",
    "ccfv2_fiber_mouse": "Allen CCFv2 Mouse Fiber Tracts Atlas",
    "ccfv2_mouse": "Allen CCFv2 Mouse Brain Atlas",
    "ccfv3augmented_mouse": "CCFv3 Augmented Mouse Atlas",
    "columbia_cuttlefish": "Columbia Cuttlefish Atlas",
    "csl_cat": "Cat Brain Atlas",
    "dorr_mouse_mri": "Dorr MRI Mouse Atlas",
    "drosophila_wingdisc_instar3": "Drosophila Wing Disc Instar3 Atlas",
    "duke_mouse": "Duke Mouse Brain Atlas",
    "eurasian_blackcap": "Eurasian Blackcap Atlas",
    "hoops_tawny_dragon": "Hoops Tawny Dragon Brain Atlas",
    # Raw folder omits "dev_"; same author/species/age as the current
    # brainglobe-atlasapi "kim_dev_mouse_e../p.." keys.
    "kim_e11_5_mouse": "Kim Lab Developmental CCF v1.0 (E11.5)",
    "kim_e13_5_mouse": "Kim Lab Developmental CCF v1.0 (E13.5)",
    "kim_e15_5_mouse": "Kim Lab Developmental CCF v1.0 (E15.5)",
    "kim_e18_5_mouse": "Kim Lab Developmental CCF v1.0 (E18.5)",
    "kim_p4_mouse": "Kim Lab Developmental CCF v1.0 (P4)",
    "kim_p14_mouse": "Kim Lab Developmental CCF v1.0 (P14)",
    "kim_p56_mouse": "Kim Lab Developmental CCF v1.0 (P56)",
    "kim_mouse_isotropic": "Enhanced and Unified Mouse Brain Atlas v2",
    # Raw folder is "kim-adult-mouse"; matches the current "kim_mouse" key.
    "kim_adult_mouse": "Enhanced and Unified Mouse Brain Atlas",
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
        re.compile(r"^admba_e(\d+)_5_mouse$"),
        "3D Edge-Aware Refined Atlases (E{0}.5)",
    ),
    (
        re.compile(r"^admba_p(\d+)_mouse$"),
        "3D Edge-Aware Refined Atlases (P{0})",
    ),
    (
        re.compile(r"^demba_p(\d+)_mouse$"),
        "DeMBA Developmental Mouse Brain Atlas (P{0})",
    ),
    (
        re.compile(r"^duke_dev_rat_p(\d+)$"),
        "Duke Developmental Rat Brain Atlas (P{0})",
    ),
]


def _fallback(atlas_key: str) -> str:
    """Format an unmapped key as a readable label, e.g. ``foo_bar`` ->
    ``Foo Bar``. Used only for keys with no verified name (see module
    docstring) - never presented as an official BrainGlobe atlas name."""
    return atlas_key.replace("_", " ").title()


def display_name(atlas_key: str) -> str:
    """Return the human-readable atlas name for a ``classify_key`` result.

    Falls back to a title-cased version of the key for the small number of
    atlases with no verified name (demo atlases, or ones not yet listed on
    BrainGlobe's docs page) and for ``"unclassified"``.
    """
    if atlas_key in _NAMES:
        return _NAMES[atlas_key]

    for pattern, template in _SERIES:
        match = pattern.match(atlas_key)
        if match:
            number = match.group(1).lstrip("0") or "0"
            return template.format(number)

    return _fallback(atlas_key)
