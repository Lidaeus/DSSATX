from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pandas as pd

from src.calibration.experiment_spec import ExperimentSpec


ROOT = Path(__file__).resolve().parents[1]


def test_e02_55_specs_use_55_active_lai_safe_bounds() -> None:
    bounds = pd.read_csv(
        ROOT
        / "data/parameter_registry/bounds_frozen/eggplant"
        / "eggplant_e01_lai_safe_v1_20260728.csv"
    )
    assert int(bounds["status"].eq("active").sum()) == 55

    for season in ("25sp", "25fa", "26sp"):
        spec = json.loads(
            (
                ROOT
                / "configs/experiments/specs"
                / f"E02_single55_{season}.json"
            ).read_text(encoding="utf-8")
        )
        assert spec["bounds_id"] == "eggplant_e01_lai_safe_v1_20260728"
        assert spec["execution"] == {
            "ies_num_reals": 200,
            "noptmax": 4,
            "seed": 20260723,
            "min_retention_rate": 0.95,
        }
        loaded = ExperimentSpec.load(
            ROOT
            / "configs/experiments/specs"
            / f"E02_single55_{season}.json"
        )
        assert loaded.bounds_active_count == 55
        assert loaded.parameter_set.declared_count == 55


def test_e02_55_policy_activates_full_crop_contract_and_dry_harvest() -> None:
    path = ROOT / "configs/runs/e02_55_multitarget_dryharvest_v2.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    active = {
        row["group"]
        for row in rows
        if row["phi_role"] == "calibration"
    }
    assert active == {
        "PDAPM", "ADAPM", "LAIXM", "LAIDM", "LWADM",
        "SWADM", "CHTDM", "CNAMM", "CHPDTM", "HPODWM", "SOIL_WATER",
    }
    assert next(row for row in rows if row["group"] == "MDAPM")[
        "phi_role"
    ] == "diagnostic_only"
    assert next(row for row in rows if row["group"] == "CHFPWM")[
        "phi_role"
    ] == "diagnostic_only"


def test_tmt_reader_preserves_single_harvest_dry_mass(tmp_path: Path) -> None:
    from src.calibration.build_pest import _read_tmt_harvest_events

    tmt = tmp_path / "TEST.TMT"
    tmt.write_text(
        "@TRNO DATE CHFPW HPODW CHPDT\n"
        " 2 25140 4710 229 229\n"
        " 2 25146 14518 477 706\n",
        encoding="utf-8",
    )
    events = _read_tmt_harvest_events(tmt)[2]
    assert [event["hpodw"] for event in events] == [229.0, 477.0]


def test_laix_can_be_an_active_measured_to_simulated_pair() -> None:
    from src.calibration.observation_policy import FORCED_DIAGNOSTIC_ROOTS

    assert "LAIXM" not in FORCED_DIAGNOSTIC_ROOTS
    assert "HWAMM" in FORCED_DIAGNOSTIC_ROOTS


def test_soil_water_budget_is_explicit_and_count_corrected() -> None:
    policy = pd.read_csv(ROOT / "configs/runs/t10_dryonly_group_policy_v1.csv")
    soil_budget = float(
        policy.loc[policy["group"].eq("SOIL_WATER"), "phi_budget"].iloc[0]
    )
    assert soil_budget == 1.0
    for n_obs in (32, 80, 120):
        multiplier = math.sqrt(soil_budget / n_obs)
        assert multiplier < 0.2


def test_e02_55_static_family_budgets_match_scientific_contract() -> None:
    policy = pd.read_csv(ROOT / "configs/runs/t10_dryonly_group_policy_v1.csv")
    budgets = dict(zip(policy["group"], policy["phi_budget"]))
    assert budgets["PHENO"] == 0.10
    assert budgets["CANOPY"] == 1.0
    assert budgets["BIOMASS"] == 1.0
    assert budgets["PLANT_N"] == 1.0
    assert budgets["HARVEST_DRY"] == 1.25
    assert budgets["SOIL_WATER"] == 1.0


def test_chtd_bundle_observations_use_dssat_metre_unit() -> None:
    for season, excode in (
        ("xxql2501_actual_trial_calibration_v2_20260726", "XXQL2501"),
        ("xxql2502_actual_trial_calibration_v2_20260726", "XXQL2502"),
        ("xxql2601_actual_trial_calibration_v2_20260726", "XXQL2601"),
    ):
        bundle = ROOT / "data/user/experiments" / season
        uncertainty = pd.read_csv(bundle / "observation_uncertainty.csv")
        chtd = uncertainty.loc[uncertainty["variable"].eq("CHTD")]
        assert not chtd.empty
        assert float(chtd["value"].max()) < 5.0
        assert float(chtd["raw_sd"].max()) < 1.0

        lines = (bundle / f"{excode}.TMT").read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        header = next(line for line in lines if line.startswith("@TRNO"))
        columns = header[1:].split()
        chtd_idx = columns.index("CHTD")
        values = []
        for line in lines[lines.index(header) + 1 :]:
            fields = line.split()
            if len(fields) == len(columns):
                value = float(fields[chtd_idx])
                if value != -99.0:
                    values.append(value)
        assert values
        assert max(values) < 5.0


def test_observation_specific_sigma_overrides_group_fallback() -> None:
    from src.calibration.build_pest import _build_ins_and_obs

    frame = pd.DataFrame(
        [{
            "@RUN": 1,
            "TN": 2,
            "DATE": 25120,
            "LAIDM": 1.2,
            "LAIDS": -99.0,
            "LAIDM_SIGMA": 0.25,
            "LAIDM_SIGMA_SOURCE": "replicate_sd:sd/sqrt(n)",
            "LAIDM_REPLICATE_SD": 0.5,
            "LAIDM_N_REPLICATES": 4,
        }]
    )
    observations, _ = _build_ins_and_obs(
        frame, {"LAID"}, set(), "PestTmtGrow.OUT", {"LAIDM_D25120": 9.0}
    )
    assert len(observations) == 1
    assert observations[0]["sigma"] == 0.25
    assert observations[0]["weight"] == 4.0
    assert observations[0]["replicate_sd"] == 0.5
    assert observations[0]["n_replicates"] == 4
