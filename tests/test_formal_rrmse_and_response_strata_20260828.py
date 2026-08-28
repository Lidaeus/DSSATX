from pathlib import Path

import pytest

from src.calibration.build_pest_multiseason import (
    _objective_bucket,
    _objective_weight_spec,
)


ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "configs/runs/e02_from_scratch_water_n_mapping_20260826.csv"


RUNS = [
    {"global_run": 1, "season_id": "25SP", "treatment": 2},
    {"global_run": 2, "season_id": "25SP", "treatment": 5},
    {"global_run": 3, "season_id": "25SP", "treatment": 10},
    {"global_run": 4, "season_id": "25SP", "treatment": 13},
]


def test_terminal_yield_accepts_season_rrmse_contract() -> None:
    mode, value, _ = _objective_weight_spec(
        {"HARVEST_DRY_TOTAL": {"terminal_weighting": "season_rrmse", "rrmse_lambda": 25}},
        "HARVEST_DRY_TOTAL",
    )
    assert mode == "season_rrmse"
    assert value == pytest.approx(25.0)


def test_n_response_uses_water_stratum() -> None:
    specs = {
        "N_RESPONSE": {
            "weighting": "season_nse",
            "nse_lambda": 1.0,
            "sst_scope": "season_x_response_stratum",
            "mapping_csv": str(MAPPING),
        }
    }
    assert _objective_bucket("25SP_NRESPS_R1_H1", "N_RESPONSE", RUNS, specs) == (
        "25SP", "N_RESPONSE", "W3"
    )
    assert _objective_bucket("25SP_NRESPS_R3_H1", "N_RESPONSE", RUNS, specs) == (
        "25SP", "N_RESPONSE", "W1"
    )


def test_w_response_uses_nitrogen_stratum() -> None:
    specs = {
        "W_RESPONSE": {
            "weighting": "season_nse",
            "nse_lambda": 0.5,
            "sst_scope": "season_x_response_stratum",
            "mapping_csv": str(MAPPING),
        }
    }
    assert _objective_bucket("25SP_WRESPS_R1_H1", "W_RESPONSE", RUNS, specs) == (
        "25SP", "W_RESPONSE", "N3"
    )
    assert _objective_bucket("25SP_WRESPS_R2_H1", "W_RESPONSE", RUNS, specs) == (
        "25SP", "W_RESPONSE", "N0"
    )
