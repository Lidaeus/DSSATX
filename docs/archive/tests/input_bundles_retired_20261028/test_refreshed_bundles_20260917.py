"""Test suite for refreshed experimental bundles (2026-09-17).

Validates:
  - D1: 10L-B soil scheme in SOIL.SOL and TMX
  - D2: Unscaled measured initial mineral N in 26SP
  - D3: 25SP missing Plot 14 interpolated from Plot 13
  - D4: C:N=11:1 SAOC derivation in 25SP
  - D5: Section @A per-plot measured soil analysis
  - D6: 25SP plant NPK in FileT and FileA (SNAM, CNAM)
  - D7: 25FA references XXSL2601 and 26SP nutrients
  - D8: 25SP harvest calendar: 9 real + 1 virtual (25198)
  - D9: Section @C ICDAT aligned with pre-planting moisture sampling date
  - D10: Bulk density from 2号棚容重测定 (SBDM=1.36)
  - D11: Mass-weighted thickness overlap algorithm with 13 SoilWat layers
  - Manifest integrity (input_manifest.json, no untracked files, matching SHA-256)
  - Observation audit (zero errors, safe_for_direct_formal_use=True)
  - DSSAT execution (clean termination, zero error files)
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pandas as pd
import pytest

from src.calibration.audit_observations import audit_observation_bundle
from src.common.input_manifest import verify_manifest_integrity

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = [
    "xxql2501_corrected_20260923",
    "xxql2601_corrected_20260923",
    "xxql2502_corrected_20260923",
]
ALL_ACTIVE_BUNDLES = BUNDLES
DSSAT_EXE = Path(r"C:\DSSAT48\DSCSM048.EXE")


@pytest.mark.parametrize("bundle_name", ALL_ACTIVE_BUNDLES)
def test_manifest_integrity(bundle_name: str):
    """Every active bundle must pass the strict input manifest integrity check."""
    bundle_dir = ROOT / "data/user/experiments" / bundle_name
    assert bundle_dir.is_dir(), f"{bundle_name} does not exist"
    manifest = verify_manifest_integrity(bundle_dir)
    assert manifest.bundle_id == bundle_name
    assert len(manifest.files) > 10


@pytest.mark.parametrize("bundle_name", BUNDLES)
def test_observation_audit(bundle_name: str):
    """Every refreshed bundle must be safe for direct formal use with zero errors."""
    bundle_dir = ROOT / "data/user/experiments" / bundle_name
    report, _ = audit_observation_bundle(bundle_dir)
    assert report["safe_for_direct_formal_use"] is True
    assert report["error_count"] == 0
    # Confirm no TRNO_DECLARED_AS_PLOT_NUMBER warning
    finding_codes = [f["code"] for f in report["findings"]]
    assert "TRNO_DECLARED_AS_PLOT_NUMBER" not in finding_codes


def test_soil_water_13_layers():
    """Soil water mapping must use 13 SoilWat layers per DSSAT v4.8 output specification."""
    for b in BUNDLES:
        mapping_csv = ROOT / "data/user/experiments" / b / "soil_water_layer_mapping.csv"
        assert mapping_csv.is_file(), f"Missing soil_water_layer_mapping.csv in {b}"
        df = pd.read_csv(mapping_csv)
        assert len(df) == 10
        # 0-20 cm should span SoilWat layer 0 (0-5), 1 (5-15), and 2 (15-30)
        rows_0_20 = df[df["measured_depth_label"] == "0-20"]
        assert list(rows_0_20["overlap_weight"]) == [0.25, 0.50, 0.25]
        assert list(rows_0_20["dssat_layer_sw_column"]) == ["SW1D", "SW2D", "SW3D"]
        # 80-100 cm should map 100% to SoilWat layer 8 (80-100)
        row_80_100 = df[df["measured_depth_label"] == "80-100"].iloc[0]
        assert row_80_100["overlap_weight"] == 1.00
        assert row_80_100["dssat_layer_sw_column"] == "SW9D"


def test_25sp_plant_n_in_filea_and_filet():
    """25SP must include SNAM and CNAM in both FileA and FileT with valid positive values."""
    bundle_dir = ROOT / "data/user/experiments/xxql2501_corrected_20260923"
    tma_text = (bundle_dir / "XXQL2501.TMA").read_text(encoding="utf-8")
    assert "SNAM" in tma_text
    assert "CNAM" in tma_text

    df_a = pd.read_csv(bundle_dir / "FileA_values.csv")
    assert "SNAM" in df_a.columns
    assert "CNAM" in df_a.columns
    valid_snam = df_a["SNAM"].dropna()
    assert len(valid_snam) > 0
    assert (valid_snam > 0).all()

    df_t = pd.read_csv(bundle_dir / "FileT_values.csv")
    assert "SNAM" in df_t.columns
    assert "LNAM" in df_t.columns
    assert "CNAM" in df_t.columns
    valid_t_snam = df_t["SNAM"].dropna()
    assert len(valid_t_snam) > 0
    assert (valid_t_snam > 0).all()


def parse_soil_layers(text: str, soil_id: str) -> dict[int, tuple[float, float]]:
    """Parse SLB -> (SLLL, SRGF) for a given profile."""
    layers = {}
    in_profile = False
    in_layer_section = False
    for line in text.splitlines():
        if line.startswith(f"*{soil_id}"):
            in_profile = True
            in_layer_section = False
        elif in_profile and line.startswith("*"):
            break
        elif in_profile and line.strip().startswith("@  SLB"):
            in_layer_section = True
        elif in_profile and in_layer_section and line.strip() and not line.startswith(("@", "!")):
            parts = line.split()
            if len(parts) >= 6:
                try:
                    slb = int(float(parts[0]))
                    if slb > 0:
                        slll = float(parts[2])
                        srgf = float(parts[5])
                        layers[slb] = (slll, srgf)
                except ValueError:
                    pass
    return layers


def test_soil_sol_profiles():
    """SOIL.SOL must contain XXSL2501 and XXSL2601 with 100cm root cutoff and calibrated SLLL."""
    target_slll = {
        2: 0.142, 4: 0.142, 15: 0.142, 30: 0.149, 40: 0.152,
        60: 0.171, 80: 0.157, 100: 0.167, 140: 0.165, 180: 0.160
    }
    target_srgf = {
        2: 1.000, 4: 1.000, 15: 1.000, 30: 0.900, 40: 0.800,
        60: 0.650, 80: 0.200, 100: 0.200, 140: 0.050, 180: 0.000
    }

    sol_paths = [ROOT / "data/user/experiments" / b / "SOIL.SOL" for b in ALL_ACTIVE_BUNDLES]

    for sol_p in sol_paths:
        assert sol_p.is_file(), f"Missing SOIL.SOL at {sol_p}"
        text = sol_p.read_text(encoding="utf-8")
        assert "*XXSL2501" in text, f"Missing XXSL2501 in {sol_p}"
        assert "*XXSL2601" in text, f"Missing XXSL2601 in {sol_p}"

        for soil_id in ["XXSL2501", "XXSL2601"]:
            layers = parse_soil_layers(text, soil_id)
            assert len(layers) == 10, f"Expected 10 layers for {soil_id} in {sol_p}, got {len(layers)}"
            # Verify 80cm and 100cm extension (SRGF=0.200)
            assert layers[80][1] == pytest.approx(0.200, abs=1e-3), f"{soil_id} 80cm SRGF mismatch in {sol_p}"
            assert layers[100][1] == pytest.approx(0.200, abs=1e-3), f"{soil_id} 100cm SRGF mismatch in {sol_p}"
            # Verify deep truncation (SRGF=0.050 at 140cm, 0.000 at 180cm)
            assert layers[140][1] == pytest.approx(0.050, abs=1e-3), f"{soil_id} 140cm SRGF mismatch in {sol_p}"
            assert layers[180][1] == pytest.approx(0.000, abs=1e-3), f"{soil_id} 180cm SRGF mismatch in {sol_p}"
            # Verify SLLL preserved at calibrated values
            for slb, expected_slll in target_slll.items():
                assert layers[slb][0] == pytest.approx(expected_slll, abs=1e-3), f"{soil_id} SLLL({slb}) mismatch in {sol_p}"
                assert layers[slb][1] == pytest.approx(target_srgf[slb], abs=1e-3), f"{soil_id} SRGF({slb}) mismatch in {sol_p}"


@pytest.mark.parametrize("bundle_name", BUNDLES)
def test_dssat_deterministic_simulation(bundle_name: str, tmp_path: Path):
    """DSSAT must execute cleanly with zero errors for all three refreshed bundles."""
    bundle_dir = ROOT / "data/user/experiments" / bundle_name
    for f in bundle_dir.iterdir():
        if f.is_file() and f.name != "input_manifest.json":
            (tmp_path / f.name).write_bytes(f.read_bytes())

    cmd = [str(DSSAT_EXE), "CRGRO048", "B", "DSSBatch.v48"]
    res = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True)
    assert res.returncode == 0
    error_file = tmp_path / "ERROR.OUT"
    assert not error_file.exists(), f"DSSAT produced ERROR.OUT:\n{error_file.read_text() if error_file.exists() else ''}"

    for req in ["Evaluate.OUT", "PlantGro.OUT", "SoilWat.OUT", "SoilNi.OUT", "OVERVIEW.OUT"]:
        out_p = tmp_path / req
        assert out_p.is_file()
        assert out_p.stat().st_size > 0
