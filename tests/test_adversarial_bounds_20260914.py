"""test_adversarial_bounds_20260914.py — Adversarial challenge suite for eggplant_e02_wnp_s1_s5_20260914.csv.

Authored by Challenger 1 (Parameter Registry & Physical Bounds Adversarial Challenger).
"""

from __future__ import annotations

import math
from pathlib import Path
import pandas as pd
import pytest

from src.common.param_registry import PHYSICAL_BOUNDS

FROZEN_CSV_PATH = Path("data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_wnp_s1_s5_20260914.csv")
STANDARD_COLUMNS = [
    "name", "init", "lower", "upper", "status", "pargp",
    "location", "file", "cultivar", "ecotype", "mode"
]


@pytest.fixture(scope="module")
def bounds_df() -> pd.DataFrame:
    assert FROZEN_CSV_PATH.exists(), f"Frozen CSV missing: {FROZEN_CSV_PATH}"
    df = pd.read_csv(FROZEN_CSV_PATH)
    return df


class TestSchemaAndStructure:
    def test_exact_columns(self, bounds_df: pd.DataFrame):
        assert list(bounds_df.columns) == STANDARD_COLUMNS

    def test_row_counts_and_uniqueness(self, bounds_df: pd.DataFrame):
        assert len(bounds_df) == 154
        names = bounds_df["name"].str.upper()
        duplicates = names[names.duplicated()].tolist()
        assert len(duplicates) == 0, f"Duplicate parameter names found: {duplicates}"

    def test_status_domain(self, bounds_df: pd.DataFrame):
        valid_statuses = {"active", "fixed", "disabled"}
        actual_statuses = set(bounds_df["status"].unique())
        assert actual_statuses.issubset(valid_statuses)
        active_count = len(bounds_df[bounds_df["status"] == "active"])
        assert active_count == 55, f"Expected 55 active parameters, got {active_count}"

    def test_no_missing_numerical_values(self, bounds_df: pd.DataFrame):
        for col in ["init", "lower", "upper"]:
            assert bounds_df[col].isna().sum() == 0, f"NaNs found in {col}"


class TestParameterBoundIntervals:
    def test_lower_le_init_le_upper(self, bounds_df: pd.DataFrame):
        violations = []
        for _, row in bounds_df.iterrows():
            name = str(row["name"]).upper()
            init = float(row["init"])
            lb = float(row["lower"])
            ub = float(row["upper"])
            if not (lb <= init <= ub):
                violations.append((name, lb, init, ub))
        assert len(violations) == 0, f"Parameters with init outside [lower, upper]: {violations}"

    def test_fixed_and_disabled_have_equal_bounds(self, bounds_df: pd.DataFrame):
        non_active = bounds_df[bounds_df["status"].isin(["fixed", "disabled"])]
        mismatches = []
        for _, row in non_active.iterrows():
            name = str(row["name"]).upper()
            init = float(row["init"])
            lb = float(row["lower"])
            ub = float(row["upper"])
            if not (math.isclose(lb, ub, rel_tol=1e-9, abs_tol=1e-9) and
                    math.isclose(init, lb, rel_tol=1e-9, abs_tol=1e-9)):
                mismatches.append((name, row["status"], init, lb, ub))
        assert len(mismatches) == 0, f"Non-active parameters with degenerate bounds: {mismatches}"

    def test_fl_vs_strictly_fixed_at_100(self, bounds_df: pd.DataFrame):
        fl_vs = bounds_df[bounds_df["name"].str.upper() == "FL-VS"].iloc[0]
        assert fl_vs["status"] == "fixed"
        assert math.isclose(float(fl_vs["init"]), 100.0, abs_tol=1e-9)
        assert math.isclose(float(fl_vs["lower"]), 100.0, abs_tol=1e-9)
        assert math.isclose(float(fl_vs["upper"]), 100.0, abs_tol=1e-9)


class TestPhysicalBoundsCompliance:
    def test_all_registered_params_within_physical_bounds(self, bounds_df: pd.DataFrame):
        violations = []
        for _, row in bounds_df.iterrows():
            name = str(row["name"]).upper()
            lb = float(row["lower"])
            ub = float(row["upper"])
            if name in PHYSICAL_BOUNDS:
                plb, pub = PHYSICAL_BOUNDS[name]
                if lb < plb - 1e-6 or ub > pub + 1e-6:
                    violations.append((name, lb, ub, plb, pub))
        assert len(violations) == 0, f"Parameters violating PHYSICAL_BOUNDS: {violations}"

    def test_detect_registry_coverage_gap_for_s3_water(self, bounds_df: pd.DataFrame):
        """Verify YSWBAR_MID and SWBAR_REC are active S3 parameters and covered in PHYSICAL_BOUNDS."""
        active_names = set(bounds_df[bounds_df["status"] == "active"]["name"].str.upper())
        # YSWBAR_MID and SWBAR_REC are in active parameters
        assert "YSWBAR_MID" in active_names
        assert "SWBAR_REC" in active_names
        # Ensure they are now covered in src.common.param_registry:PHYSICAL_BOUNDS
        missing = [p for p in ["YSWBAR_MID", "SWBAR_REC"] if p not in PHYSICAL_BOUNDS]
        assert len(missing) == 0, f"Expected YSWBAR_MID and SWBAR_REC to be covered in PHYSICAL_BOUNDS dictionary, found missing: {missing}"


class TestSoilMoistureHierarchy:
    def test_layer1_slll_sdul_ssat(self, bounds_df: pd.DataFrame):
        slll = bounds_df[bounds_df["name"].str.lower() == "soil_slll_01"].iloc[0]
        sdul = bounds_df[bounds_df["name"].str.lower() == "soil_sdul_01"].iloc[0]
        ssat = bounds_df[bounds_df["name"].str.lower() == "soil_ssat_01"].iloc[0]
        assert float(slll["upper"]) < float(sdul["lower"])
        assert float(sdul["upper"]) < float(ssat["lower"])

    def test_all_8_layers_slll_sdul_ssat(self, bounds_df: pd.DataFrame):
        for i in range(1, 9):
            slll = bounds_df[bounds_df["name"].str.lower() == f"soil_slll_0{i}"].iloc[0]
            sdul = bounds_df[bounds_df["name"].str.lower() == f"soil_sdul_0{i}"].iloc[0]
            ssat = bounds_df[bounds_df["name"].str.lower() == f"soil_ssat_0{i}"].iloc[0]
            assert float(slll["upper"]) <= float(sdul["lower"]), f"Layer {i}: SLLL upper > SDUL lower"
            assert float(sdul["upper"]) <= float(ssat["lower"]), f"Layer {i}: SDUL upper > SSAT lower"


class TestTemperatureOrdering:
    def test_dssat_within_stage_cardinal_order(self, bounds_df: pd.DataFrame):
        """Physiological CROPGRO cardinal temperatures order within each development stage."""
        tb1 = bounds_df[bounds_df["name"].str.lower() == "tb1"].iloc[0]
        to11 = bounds_df[bounds_df["name"].str.lower() == "to11"].iloc[0]
        to21 = bounds_df[bounds_df["name"].str.lower() == "to21"].iloc[0]
        tm1 = bounds_df[bounds_df["name"].str.lower() == "tm1"].iloc[0]

        # Stage 1: TB1 < TO11 <= TO21 < TM1 across full bound intervals
        assert float(tb1["upper"]) < float(to11["lower"])
        assert float(to11["upper"]) < float(to21["lower"])
        assert float(to21["upper"]) < float(tm1["lower"])

        tb2 = bounds_df[bounds_df["name"].str.lower() == "tb2"].iloc[0]
        to12 = bounds_df[bounds_df["name"].str.lower() == "to12"].iloc[0]
        to22 = bounds_df[bounds_df["name"].str.lower() == "to22"].iloc[0]
        tm2 = bounds_df[bounds_df["name"].str.lower() == "tm2"].iloc[0]

        # Stage 2: TB2 < TO12 <= TO22 < TM2 across full bound intervals
        assert float(tb2["upper"]) < float(to12["lower"])
        assert float(to12["upper"]) < float(to22["lower"])
        assert float(to22["upper"]) < float(tm2["lower"])

    def test_prompt_cross_stage_ordering_fails(self, bounds_df: pd.DataFrame):
        """Adversarial challenge: The dispatch/prompt checks 'TB1 < TO11 < TO12 < TM1'.

        In reality, TO11 (stage 1) and TO12 (stage 2) are not ordered TO11 < TO12:
        TO11 init (22.6896) is GREATER than TO12 init (21.5726).
        """
        to11 = bounds_df[bounds_df["name"].str.lower() == "to11"].iloc[0]
        to12 = bounds_df[bounds_df["name"].str.lower() == "to12"].iloc[0]
        # Empirically verify that TO11 init is greater than TO12 init
        assert float(to11["init"]) > float(to12["init"])
        assert float(to11["lower"]) > float(to12["lower"])


class TestSpeciesPhosphorusAndPeanutBaseline:
    def test_true_phosphorus_peanut_baseline_10pct(self, bounds_df: pd.DataFrame):
        """The 3 active organ P parameters (OPTSDP_FS, OPTLFP_FS, OPTSTP_FS) strictly within +-10% of peanut."""
        p_anchors = {
            "OPTSDP_FS": 0.0044,
            "OPTLFP_FS": 0.0022,
            "OPTSTP_FS": 0.0019,
        }
        for name, anchor in p_anchors.items():
            row = bounds_df[bounds_df["name"].str.upper() == name].iloc[0]
            assert row["status"] == "active"
            expected_lower = anchor * 0.9
            expected_upper = anchor * 1.1
            assert math.isclose(float(row["lower"]), expected_lower, rel_tol=1e-3)
            assert math.isclose(float(row["upper"]), expected_upper, rel_tol=1e-3)
            assert math.isclose(float(row["init"]), anchor, rel_tol=1e-3)

    def test_fnpgn_leaf_n_photo_deviation_from_10pct(self, bounds_df: pd.DataFrame):
        """Adversarial challenge: FNPGN1 and FNPGN2 are leaf N effect on PG, NOT phosphorus parameters.

        Their calibration bounds [0.3, 1.4] and [2.0, 4.2] deliberately exceed +-10% of peanut (2.30, 4.72).
        """
        fnpgn1 = bounds_df[bounds_df["name"].str.upper() == "FNPGN1"].iloc[0]
        fnpgn2 = bounds_df[bounds_df["name"].str.upper() == "FNPGN2"].iloc[0]

        # FNPGN1 lower is 0.3, which is far below 2.30 * 0.9 = 2.07
        assert float(fnpgn1["lower"]) == 0.3
        assert float(fnpgn1["lower"]) < 2.30 * 0.9

        # FNPGN2 upper is 4.2, lower is 2.0, differing from peanut 4.72 +- 10% [4.248, 5.192]
        assert float(fnpgn2["lower"]) == 2.0
        assert float(fnpgn2["upper"]) == 4.2
        assert float(fnpgn2["lower"]) < 4.72 * 0.9


class TestStageAllocationAndMorrisCoverage:
    def test_staged_allocation_covers_all_55_active(self, bounds_df: pd.DataFrame):
        active_set = set(bounds_df[bounds_df["status"] == "active"]["name"].str.upper())
        s1 = {'EM-FL', 'EM-V1', 'FL-SH', 'FL-SD', 'TB1', 'TB2', 'TO11', 'TO12', 'TM1', 'TM2', 'LNGSH', 'SFDUR'}
        s2 = {'PGEFF', 'SLAVR', 'SLAREF', 'LFMAX', 'SIZREF', 'TRIFL', 'LNREF', 'RHGHT', 'FRLFF', 'FRSTMF', 'SENRTE'}
        s3 = {'RWDTH', 'RWUMX', 'YSWBAR_MID', 'DSWBAR', 'SWBAR_REC', 'SOIL_SDUL_01', 'SOIL_SLLL_01'}
        s4 = {'PROLFI', 'PROSTI', 'PROLFF', 'PROLFG', 'PRORTI', 'NMOBMX', 'CMOBMX', 'NSTFAC', 'NSLOPE', 'NVSMOB',
              'RTNO3', 'RTNH4', 'FNPGN1', 'FNPGN2', 'OPTSDP_FS', 'OPTLFP_FS', 'OPTSTP_FS'}
        s5 = {'XFRT', 'PM06', 'PORPT', 'VSSINK', 'PODUR', 'THRSH', 'XMAGE', 'FINREF'}

        all_stages = s1 | s2 | s3 | s4 | s5
        assert len(all_stages) == 55
        assert active_set == all_stages

    def test_boundary_saturation_candidates(self, bounds_df: pd.DataFrame):
        """Identifies parameters that touch physical limits, posing boundary pinning risks."""
        touching = []
        for _, row in bounds_df[bounds_df["status"] == "active"].iterrows():
            name = str(row["name"]).upper()
            lb, ub = float(row["lower"]), float(row["upper"])
            if name in PHYSICAL_BOUNDS:
                plb, pub = PHYSICAL_BOUNDS[name]
                if math.isclose(lb, plb, abs_tol=1e-5):
                    touching.append((name, "LOWER_PINNED", lb, plb))
                if math.isclose(ub, pub, abs_tol=1e-5):
                    touching.append((name, "UPPER_PINNED", ub, pub))

        touching_names = {t[0] for t in touching}
        # RTNO3 and RTNH4 hit upper 0.05, XFRT hits upper 1.0, FL-SH hits lower 1.0
        assert "RTNO3" in touching_names
        assert "RTNH4" in touching_names
        assert "XFRT" in touching_names
        assert "FL-SH" in touching_names
