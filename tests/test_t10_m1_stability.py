"""Regression tests for the conservative numerical profile of T10 M1."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pyemu


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "calibration" / "run_t10_m1_seasonal_offsets.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("t10_m1_launcher", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_m1_stability_profile_keeps_conservative_update_options(tmp_path):
    module = _load_module()
    case = "case"
    pst = pyemu.Pst.from_par_obs_names(["P1"], ["O1"])
    pst.parameter_data.loc["P1", ["parval1", "parlbnd", "parubnd", "partrans"]] = [1.0, 0.0, 2.0, "none"]
    pst.observation_data.loc["O1", ["obsval", "weight"]] = [1.0, 1.0]
    pst.write(tmp_path / f"{case}.pst")

    module._apply_stability_profile(tmp_path, case)
    loaded = pyemu.Pst(str(tmp_path / f"{case}.pst"))
    for name, value in module.M1_IES_STABILITY_PROFILE.items():
        assert str(loaded.pestpp_options[name]).strip().lower() == str(value).strip().lower()

