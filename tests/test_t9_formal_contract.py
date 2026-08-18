"""Regression guards for the executable T9 high-dimensional contract."""

from pathlib import Path

import pandas as pd

from src.common.param_registry import PHYSICAL_BOUNDS


ROOT = Path(__file__).resolve().parents[1]
BOUNDS = ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_t9_highdim_v1_20260722.csv"


def test_t9_frozen_parameters_all_have_physical_hard_bounds():
    bounds = pd.read_csv(BOUNDS, encoding="utf-8-sig")
    missing = sorted(set(bounds["name"].astype(str)) - set(PHYSICAL_BOUNDS))
    assert not missing


def test_t9_frozen_contract_has_55_active_and_9_fixed_parameters():
    bounds = pd.read_csv(BOUNDS, encoding="utf-8-sig")
    assert int(bounds["status"].eq("active").sum()) == 55
    assert int(bounds["status"].eq("fixed").sum()) == 9
