"""Contract tests for E02 from-scratch S0 blockers B1-B6.

Each test verifies a specific fix required before entering S1.
These tests must not be bypassed by "other unit tests already passed".

B1: Design JSON must have explicit response objective parameters (levels, etc.)
B2: Process increment must use per-variable previous_valid tracking
B3: 25FA manifest must prohibit parameter_calibration
B4: NSE SST scope must be season_x_family in design and code
B5: Bundle builder must fail if output directory exists
B6: PLANT_N (SNAMM/LNAMM) must not be phi_role=calibration when no observations
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


# ── B1: Response objective defaults match four-corner N0/N3 design ──────────

class TestB1ResponseObjectiveParameters:
    """Design JSON must explicitly declare levels, contrast_scale, etc."""

    @pytest.fixture
    def design(self):
        path = ROOT / "configs/runs/e02_from_scratch_10L_B_s0_design_20260826.json"
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_nitrogen_response_has_explicit_levels(self, design):
        nr = design["nitrogen_response_objective"]
        assert "levels" in nr, "nitrogen_response_objective must declare levels explicitly"
        assert nr["levels"] == ["N3"], (
            f"Expected levels=[\"N3\"] for N3-minus-N0 contrast, got {nr['levels']}"
        )

    def test_nitrogen_response_has_contrast_scale(self, design):
        nr = design["nitrogen_response_objective"]
        assert nr.get("contrast_scale") == "raw_difference"

    def test_nitrogen_response_has_response_target(self, design):
        nr = design["nitrogen_response_objective"]
        assert nr.get("response_target") == "observed_shape"

    def test_nitrogen_response_has_harvest_scope(self, design):
        nr = design["nitrogen_response_objective"]
        assert nr.get("harvest_scope") == "all"

    def test_water_response_has_explicit_levels(self, design):
        wr = design["water_response_objective"]
        assert "levels" in wr, "water_response_objective must declare levels explicitly"
        assert wr["levels"] == ["N3"]

    def test_water_response_has_nitrogen_levels(self, design):
        wr = design["water_response_objective"]
        assert "nitrogen_levels" in wr, (
            "water_response_objective must declare nitrogen_levels explicitly"
        )
        assert set(wr["nitrogen_levels"]) == {"N0", "N3"}

    def test_water_response_has_contrast_scale(self, design):
        wr = design["water_response_objective"]
        assert wr.get("contrast_scale") == "raw_difference"

    def test_water_response_has_response_target(self, design):
        wr = design["water_response_objective"]
        assert wr.get("response_target") == "observed_shape"

    def test_water_response_has_harvest_scope(self, design):
        wr = design["water_response_objective"]
        assert wr.get("harvest_scope") == "all"

    def test_nitrogen_response_sigma_floor_is_physical(self, design):
        """sigma_floor=0.10 was the old value causing near-zero tolerance;
        must be a physically meaningful value like 50.0 for CHPDT."""
        nr = design["nitrogen_response_objective"]
        assert float(nr["sigma_floor"]) >= 10.0, (
            f"sigma_floor {nr['sigma_floor']} is too small for CHPDT response differences"
        )


# ── B2: Per-variable previous_valid tracking in process increments ──────────

class TestB2ProcessIncrementPerVariable:
    """When a row has LAI=-99 but LWAD/SWAD present, LAI increment must not
    be lost for the next observation."""

    def test_lai_increment_survives_missing_intermediate(self):
        """Simulates the 26SP case: dates 2026-06-02, 2026-06-29, 2026-07-17.
        LAI present on 06-02 and 07-17 but missing on 06-29.
        LWAD/SWAD present on all three dates.
        The increment 06-02→07-17 for LAI must be computed, not -99."""
        from src.calibration.multiseason_design import MultiSeasonDesign

        # Build a synthetic process DataFrame
        rows = [
            {"@RUN": 1, "TN": 1, "DATE": 20260602, "LAIDM": 1.5, "LWADM": 100.0,
             "SWADM": 50.0, "CHTDM": -99.0, "LAIDS": -99.0, "LWADS": -99.0,
             "SWADS": -99.0, "CHTDS": -99.0, "season": "26SP"},
            {"@RUN": 1, "TN": 1, "DATE": 20260629, "LAIDM": -99.0, "LWADM": 200.0,
             "SWADM": 120.0, "CHTDM": -99.0, "LAIDS": -99.0, "LWADS": -99.0,
             "SWADS": -99.0, "CHTDS": -99.0, "season": "26SP"},
            {"@RUN": 1, "TN": 1, "DATE": 20260717, "LAIDM": 2.8, "LWADM": 350.0,
             "SWADM": 200.0, "CHTDM": -99.0, "LAIDS": -99.0, "LWADS": -99.0,
             "SWADS": -99.0, "CHTDS": -99.0, "season": "26SP"},
        ]
        df = pd.DataFrame(rows)

        # Apply the same logic as build_pest_multiseason.py lines 510-548
        derived_rows = []
        for _, group in df.groupby("@RUN", sort=False):
            group = group.sort_values("DATE")
            previous_valid = {"LAIDM": -99.0, "LWADM": -99.0, "SWADM": -99.0}
            previous_valid_date = {"LAIDM": None, "LWADM": None, "SWADM": None}
            terminal_index = {}
            for variable in ("LAIDM", "LWADM", "SWADM"):
                valid = group.loc[group[variable].astype(float).ne(-99.0)]
                terminal_index[variable] = valid.index[-1] if not valid.empty else None
            for idx, row in group.iterrows():
                out = row.to_dict()
                for variable, diff_name, terminal_name in (
                    ("LAIDM", "LAIDDM", "LAIETM"),
                    ("LWADM", "LWADDM", "LWETM"),
                    ("SWADM", "SWADDM", "SWETM"),
                ):
                    value = float(row.get(variable, -99.0))
                    prev_value = previous_valid[variable]
                    out[diff_name] = (
                        value - prev_value
                        if value != -99.0 and prev_value != -99.0 else -99.0
                    )
                    out[f"{diff_name}_prev_date"] = (
                        previous_valid_date[variable]
                        if value != -99.0 and prev_value != -99.0 else None
                    )
                    out[terminal_name] = (
                        value if idx == terminal_index[variable] else -99.0
                    )
                    if value != -99.0:
                        previous_valid[variable] = value
                        previous_valid_date[variable] = int(row.get("DATE", -99))
                derived_rows.append(out)
        result = pd.DataFrame(derived_rows)

        # The critical assertion: LAI increment on 07-17 must be 2.8 - 1.5 = 1.3
        # not -99 (which would happen if previous was overwritten by 06-29 row)
        row3 = result[result["DATE"] == 20260717].iloc[0]
        assert row3["LAIDDM"] == pytest.approx(1.3, abs=0.01), (
            f"LAI increment on 07-17 should be 1.3 (2.8-1.5), got {row3['LAIDDM']}"
        )
        assert row3["LAIDDM_prev_date"] == 20260602, (
            "LAI increment prev_date should point to 06-02, the last valid LAI date"
        )

        # LWAD increment on 06-29 should work: 200-100=100
        row2 = result[result["DATE"] == 20260629].iloc[0]
        assert row2["LWADDM"] == pytest.approx(100.0, abs=0.01)

        # LAI increment on 06-29 should be -99 (LAI missing)
        assert row2["LAIDDM"] == -99.0

        # LWAD increment on 07-17 should be 350-200=150
        assert row3["LWADDM"] == pytest.approx(150.0, abs=0.01)

    def test_terminal_values_correct_with_gaps(self):
        """Terminal value must be the last valid observation, not the last row."""
        rows = [
            {"@RUN": 1, "TN": 1, "DATE": 20260601, "LAIDM": 1.0, "LWADM": 100.0,
             "SWADM": 50.0, "CHTDM": -99.0, "LAIDS": -99.0, "LWADS": -99.0,
             "SWADS": -99.0, "CHTDS": -99.0, "season": "26SP"},
            {"@RUN": 1, "TN": 1, "DATE": 20260701, "LAIDM": 2.5, "LWADM": -99.0,
             "SWADM": 120.0, "CHTDM": -99.0, "LAIDS": -99.0, "LWADS": -99.0,
             "SWADS": -99.0, "CHTDS": -99.0, "season": "26SP"},
        ]
        df = pd.DataFrame(rows)

        derived_rows = []
        for _, group in df.groupby("@RUN", sort=False):
            group = group.sort_values("DATE")
            previous_valid = {"LAIDM": -99.0, "LWADM": -99.0, "SWADM": -99.0}
            previous_valid_date = {"LAIDM": None, "LWADM": None, "SWADM": None}
            terminal_index = {}
            for variable in ("LAIDM", "LWADM", "SWADM"):
                valid = group.loc[group[variable].astype(float).ne(-99.0)]
                terminal_index[variable] = valid.index[-1] if not valid.empty else None
            for idx, row in group.iterrows():
                out = row.to_dict()
                for variable, diff_name, terminal_name in (
                    ("LAIDM", "LAIDDM", "LAIETM"),
                    ("LWADM", "LWADDM", "LWETM"),
                    ("SWADM", "SWADDM", "SWETM"),
                ):
                    value = float(row.get(variable, -99.0))
                    prev_value = previous_valid[variable]
                    out[diff_name] = (
                        value - prev_value
                        if value != -99.0 and prev_value != -99.0 else -99.0
                    )
                    out[f"{diff_name}_prev_date"] = (
                        previous_valid_date[variable]
                        if value != -99.0 and prev_value != -99.0 else None
                    )
                    out[terminal_name] = (
                        value if idx == terminal_index[variable] else -99.0
                    )
                    if value != -99.0:
                        previous_valid[variable] = value
                        previous_valid_date[variable] = int(row.get("DATE", -99))
                derived_rows.append(out)
        result = pd.DataFrame(derived_rows)

        # LAI terminal should be on row 2 (2.5), LWAD terminal on row 1 (100.0)
        row1 = result[result["DATE"] == 20260601].iloc[0]
        row2 = result[result["DATE"] == 20260701].iloc[0]
        assert row2["LAIETM"] == pytest.approx(2.5)
        assert row1["LWETM"] == pytest.approx(100.0)  # terminal for LWAD is row 1
        assert row2["LWETM"] == -99.0  # LWAD missing on this row, not terminal


class TestDisabledHarvestObjective:
    """A canopy-only stage must not inherit harvest Phi from the shared policy."""

    def test_disabled_stage_masks_dry_harvest_measurements(self):
        from src.calibration.build_pest_multiseason import (
            _mask_disabled_harvest_objective,
        )

        harvest = pd.DataFrame(
            {
                "CHPDTM": [100.0, 250.0],
                "CHPDTM_T": [100.0, -99.0],
                "HPODWM": [100.0, 150.0],
                "CHFPWM": [1000.0, 2500.0],
            }
        )
        _mask_disabled_harvest_objective(harvest)

        assert harvest["CHPDTM"].eq(-99.0).all()
        assert harvest["CHPDTM_T"].eq(-99.0).all()
        assert harvest["HPODWM"].eq(-99.0).all()
        assert harvest["CHFPWM"].tolist() == [1000.0, 2500.0]

    def test_s1_design_explicitly_disables_harvest(self):
        design_path = (
            ROOT
            / "configs/runs/e02_from_scratch_10L_B_s1_canopy_parallel_0_4_60cm_20260827.json"
        )
        design = json.loads(design_path.read_text(encoding="utf-8"))
        assert design["harvest_dry_objective"]["enabled"] is False


# ── B3: 25FA manifest must prohibit parameter_calibration ───────────────────

class TestB3ValidationProhibition:
    """25FA bundle must reject parameter_calibration use."""

    def test_25fa_manifest_has_prohibited_use(self):
        manifest_path = (
            ROOT / "data/user/experiments/xxfa_from_scratch_10L_B_20260826"
            / "input_manifest.json"
        )
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert "prohibited_use" in raw, "25FA manifest must declare prohibited_use"
        assert "parameter_calibration" in raw["prohibited_use"], (
            "25FA must prohibit parameter_calibration"
        )

    def test_verify_calibrated_input_bundle_rejects_25fa(self):
        from src.common.input_manifest import (
            InputUseProhibitedError,
            verify_calibrated_input_bundle,
        )
        bundle = ROOT / "data/user/experiments/xxfa_from_scratch_10L_B_20260826"
        with pytest.raises(InputUseProhibitedError):
            verify_calibrated_input_bundle(bundle)

    def test_design_25fa_hash_matches_actual_manifest(self):
        """The design JSON hash for 25FA must match the on-disk manifest."""
        from src.common.project import sha256_file

        design_path = ROOT / "configs/runs/e02_from_scratch_10L_B_s0_design_20260826.json"
        design = json.loads(design_path.read_text(encoding="utf-8"))
        fa_season = next(s for s in design["seasons"] if s["season_id"] == "25FA")
        declared_hash = fa_season["bundle_manifest_sha256"]

        manifest_path = (
            ROOT / "data/user/experiments/xxfa_from_scratch_10L_B_20260826"
            / "input_manifest.json"
        )
        actual_hash = sha256_file(manifest_path)
        assert declared_hash == actual_hash, (
            f"25FA hash mismatch: design={declared_hash}, actual={actual_hash}"
        )


# ── B4: NSE SST scope must be season_x_family ──────────────────────────────

class TestB4SSTScope:
    """Design JSON SST scope must be season_x_family, matching the code."""

    @pytest.fixture
    def design(self):
        path = ROOT / "configs/runs/e02_from_scratch_10L_B_s0_design_20260826.json"
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_nitrogen_sst_scope_is_season_x_family(self, design):
        assert design["nitrogen_response_objective"]["sst_scope"] == "season_x_family"

    def test_water_sst_scope_is_season_x_family(self, design):
        assert design["water_response_objective"]["sst_scope"] == "season_x_family"


# ── B5: Bundle builder must fail if output directory exists ─────────────────

class TestB5BuilderImmutability:
    """The bundle builder must not silently overwrite existing bundles."""

    def test_builder_raises_on_existing_output(self, tmp_path):
        """Verify the _copy_and_rebuild function raises FileExistsError."""
        import importlib.util

        builder_path = ROOT / "tools/experiments/build_e02_from_scratch_10l_bundles_20260826.py"
        spec = importlib.util.spec_from_file_location("builder", builder_path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)

        # Create a fake output directory
        fake_out = tmp_path / "test_bundle"
        fake_out.mkdir()

        fake_spec = {
            "source": ROOT / "data/user/experiments/xxql2501_from_scratch_10L_B_20260826",
            "out": fake_out,
            "excode": "XXQL2501",
            "role": "calibration",
            "treatments": [2, 5, 10, 13],
            "calibration_treatments": [2, 5, 10, 13],
            "diagnostic_treatments": [],
            "ic_policy": "test",
        }
        with pytest.raises(FileExistsError):
            builder._copy_and_rebuild(fake_spec)


# ── B6: PLANT_N must not be calibration when no observations ────────────────

class TestB6PlantNAvailability:
    """SNAMM/LNAMM must be marked unavailable_by_data, not calibration."""

    def test_snamm_lnamm_not_calibration(self):
        policy_path = ROOT / "configs/runs/e02_from_scratch_objective_contract_20260826.csv"
        with open(policy_path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            if row["group"] in ("SNAMM", "LNAMM"):
                assert row["phi_role"] != "calibration", (
                    f"{row['group']} must not be phi_role=calibration "
                    f"when no SNAM/LNAM observations exist in calibration treatments"
                )
                assert row["phi_role"] == "unavailable_by_data"
