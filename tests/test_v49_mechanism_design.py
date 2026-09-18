from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.calibration.build_pest import _parse_filex_seedling_params
from src.common.param_registry import assert_valid_frozen_bounds
from tools.calibration.run_v49_mechanism_multiarm_20260902 import ARMS, COMMON, make_bounds, anchor_values, paired_prior


@pytest.mark.parametrize("name", ["PAGE_25SP", "PENV_26SP", "ICNS_25SP"])
def test_fixed_filex_terms(tmp_path, name):
    path = tmp_path / "bounds.csv"
    pd.DataFrame([dict(name=name, location="IC", init=.6, lower=.6, upper=.6, status="fixed")]).to_csv(path, index=False)
    assert _parse_filex_seedling_params(path)[0]["status"] == "fixed"
    frame = pd.read_csv(path)
    frame["status"] = "active"
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError):
        _parse_filex_seedling_params(path)


@pytest.mark.parametrize("arm", list(ARMS))
def test_frozen_arm_whitelist(tmp_path, arm):
    frame = make_bounds(arm)
    assert set(frame.loc[frame.status.eq("active"), "name"]) == set(COMMON) | set(ARMS[arm])
    fixed = frame[frame.status.eq("fixed")]
    np.testing.assert_allclose(fixed.init, fixed.name.map(anchor_values()))
    path = tmp_path / "bounds.csv"
    frame.to_csv(path, index=False)
    assert_valid_frozen_bounds(path)


def test_shared_ic_prior_independent_of_arm():
    import pyemu
    priors = []
    for arm in ("A_ic_control", "E_canopy"):
        b = make_bounds(arm).set_index("name")
        pst = pyemu.Pst.from_par_obs_names(par_names=list(b.index), obs_names=["o"])
        for key, source in (("parval1", "init"), ("parlbnd", "lower"), ("parubnd", "upper")):
            pst.parameter_data[key] = b[source]
        pst.parameter_data["partrans"] = b.status.map({"fixed": "fixed", "active": "none"})
        priors.append(paired_prior(pst)[list(COMMON)])
    pd.testing.assert_frame_equal(*priors)
    assert priors[0].ge(.4).all().all() and priors[0].le(.8).all().all()


def test_soil_water_keep_forwarded():
    text = (Path(__file__).resolve().parents[1] / "src/calibration/run_multiseason.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("--keep-soil-water"' in text
    assert 'result_args.append("--keep-soil-water")' in text
