"""Unit tests for oss_dashboard.atlas_logs.atlas_names."""

import pytest

from oss_dashboard.atlas_logs.atlas_names import display_name


@pytest.mark.parametrize(
    "key, expected",
    [
        ("allen_mouse", "Allen Adult Mouse Brain Atlas"),
        ("whs_sd_rat", "Waxholm Space Atlas of the Sprague Dawley Rat Brain"),
        ("columbia_cuttlefish", "Columbia Cuttlefish Atlas"),
        ("kim_mouse_isotropic", "Enhanced and Unified Mouse Brain Atlas v2"),
        ("kim_mouse", "Enhanced and Unified Mouse Brain Atlas"),
        ("allen_human", "Allen Human Brain Atlas"),
        ("allen_cord", "3D version of the Allen Mouse Spinal Cord Atlas"),
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
            "lambada_dev_mouse_p3",
            "LAMBADA Developmental Mouse Brain Atlas (P3)",
        ),
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
            "kim_dev_mouse_mri_t2",
            "Kim Lab Developmental CCF v001 (P56, MRI T2)",
        ),
    ],
)
def test_display_name_numbered_series(key, expected):
    assert display_name(key) == expected


def test_display_name_falls_back_for_unmapped_keys():
    # Atlases genuinely absent from BrainGlobe's public docs table (as of
    # 2026-09-11) must not get a fabricated official-sounding name.
    assert display_name("african_molerat") == "African Molerat"
    assert display_name("example_mouse") == "Example Mouse"
    assert display_name("hoops_dragon") == "Hoops Dragon"


def test_display_name_falls_back_for_unclassified():
    assert display_name("unclassified") == "Unclassified"


def test_all_real_manifest_atlases_get_a_name():
    """Every distinct atlas-manifest key currently in the committed
    summary must resolve to a non-empty, title-cased-or-better name (i.e.
    display_name never raises and never just echoes a raw snake_case key
    unless that key genuinely has no verified name)."""
    from pathlib import Path

    import pandas as pd

    from oss_dashboard.atlas_logs.constants import ATLAS_PARQUET_PATH

    if not Path(ATLAS_PARQUET_PATH).exists():
        pytest.skip("no committed atlas_usage.parquet in this checkout")

    frame = pd.read_parquet(ATLAS_PARQUET_PATH)
    keys = frame.loc[frame["resource"] == "atlas-manifest", "atlas"].unique()
    for key in keys:
        name = display_name(key)
        assert name
        assert "_" not in name
        assert key not in name  # never the raw key echoed back
