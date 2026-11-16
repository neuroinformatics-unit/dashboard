"""Unit tests for oss_dashboard.atlas_logs.atlas_names."""

import pytest
import requests

from oss_dashboard.atlas_logs import atlas_names
from oss_dashboard.atlas_logs.atlas_names import (
    display_name,
    parse_atlas_details,
)

# Excerpt in the shape of BrainGlobe's atlas-details.md.
_PAGE = """\
# Available atlases
Use the key (e.g. `example_mouse_100um`).

## Mouse
### [Allen Adult Mouse Brain Atlas](https://doi.org/10.1016/x)
Prose mentioning `kim_mouse_25um` is not a bullet.

Available versions:
* `allen_mouse_10um` - 10μm resolution
* `allen_mouse_25um` - 25μm resolution

### [Drosophila wing disc instar3 atlas.](https://example.org)
* `drosophila_wingdisc_instar3_0.5um`

### Virtual Fly Brain JRC2018Unisex VNC atlas
* `vfb_jrc2018u_vnc_fly_0.4um`

### [DeMBA Developmental Mouse Brain Atlas](https://example.org)
* `demba_allen_seg_dev_mouse_p4_20um`
* `demba_allen_seg_dev_mouse_p21_20um`

### [3D Edge-Aware Refined Atlases Derived from the Allen Developing \
Mouse Brain Atlases](https://example.org)
* `admba_3d_e11_5_mouse_16um`
* `admba_3d_p56_mouse_25um`

### [Duke Developmental Rat Brain Atlas](https://example.org)
* `duke_dev_rat_p00_50um`
* `duke_dev_rat_p24_50um`

### [Kim Lab Developmental CCF v1.0](https://example.org)
* `kim_dev_mouse_e11-5_mri-adc_31.5um`
* `kim_dev_mouse_p04_lsfm_20um`

### [Kim Lab Developmental CCF v001 (P56)](https://example.org)
* `kim_dev_mouse_idisco_10um`
* `kim_dev_mouse_mri-T2_10um`
* `kim_dev_mouse_mri_t2_10um`
"""


@pytest.fixture(autouse=True)
def _offline_docs(monkeypatch):
    names = parse_atlas_details(_PAGE)
    monkeypatch.setattr(atlas_names, "_docs_names", lambda: names)


@pytest.mark.parametrize(
    "key, expected",
    [
        ("allen_mouse", "Allen Adult Mouse Brain Atlas"),
        ("drosophila_wingdisc_instar3", "Drosophila wing disc instar3 atlas"),
        ("vfb_jrc2018u_vnc_fly", "Virtual Fly Brain JRC2018Unisex VNC atlas"),
    ],
)
def test_display_name_exact_matches(key, expected):
    assert display_name(key) == expected


@pytest.mark.parametrize(
    "key, expected",
    [
        ("admba_3d_e11_5_mouse", "3D Edge-Aware Refined Atlases (E11.5)"),
        ("admba_3d_p56_mouse", "3D Edge-Aware Refined Atlases (P56)"),
        (
            "demba_allen_seg_dev_mouse_p21",
            "DeMBA Developmental Mouse Brain Atlas (P21)",
        ),
        (
            "demba_allen_seg_dev_mouse_p4",
            "DeMBA Developmental Mouse Brain Atlas (P4)",
        ),
        ("duke_dev_rat_p00", "Duke Developmental Rat Brain Atlas (P0)"),
        ("duke_dev_rat_p24", "Duke Developmental Rat Brain Atlas (P24)"),
        (
            "kim_dev_mouse_e11-5_mri-adc",
            "Kim Lab Developmental CCF v1.0 (E11.5, MRI ADC)",
        ),
        (
            "kim_dev_mouse_p04_lsfm",
            "Kim Lab Developmental CCF v1.0 (P4, LSFM)",
        ),
        (
            "kim_dev_mouse_idisco",
            "Kim Lab Developmental CCF v001 (P56, iDISCO)",
        ),
        (
            "kim_dev_mouse_mri-t2",
            "Kim Lab Developmental CCF v001 (P56, MRI T2)",
        ),
    ],
)
def test_display_name_numbered_series(key, expected):
    assert display_name(key) == expected


def test_prose_mentions_are_not_keys():
    assert "kim_mouse" not in parse_atlas_details(_PAGE)
    assert "example_mouse" not in parse_atlas_details(_PAGE)


def test_display_name_falls_back_to_atlas_key():
    # Atlases absent from BrainGlobe's docs page keep their atlas name
    # rather than getting a fabricated official-sounding one.
    assert display_name("african_molerat") == "african_molerat"
    assert display_name("example_mouse") == "example_mouse"
    assert display_name("unclassified") == "unclassified"


def test_fetch_failure_falls_back(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError

    monkeypatch.undo()  # use the real (cached) _docs_names, not the fixture
    monkeypatch.setattr(atlas_names.requests, "get", boom)
    atlas_names._docs_names.cache_clear()
    try:
        assert display_name("allen_mouse") == "allen_mouse"
    finally:
        atlas_names._docs_names.cache_clear()
