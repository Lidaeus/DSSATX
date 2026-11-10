"""Joint operators preserve signed contrasts, missingness and treatment identity."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.calibration import joint_n_objectives as model
from src.calibration import single_season_n as legacy
from src.dssat.forward_joint import inject_phosphorus

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "workspace/runs/eggplant_26sp_n012_formal_20261011_r3/S4_joint_retry3/selected_deterministic/_model"
CATALOG = ROOT / "configs/calibration_proposals/eggplant_26sp_n012_c31_joint_review_20261011/proposed_calibration_targets.csv"


def targets():
    obs = pd.read_csv(CATALOG).fillna("")
    obs["obsnme"] = [f"j26_{i:04d}" for i in range(len(obs))]
    return obs


def test_all_492_exact_date_targets_and_signed_contrasts():
    obs = targets()
    result = model.extract_observations(WORK, obs)
    fresh = legacy.read_native(WORK / "FreshWt.OUT")
    assert len(result) == 492 and result.obsnme.tolist() == obs.obsnme.tolist()
    assert np.isfinite(result.simulated).all()
    assert (result[result.variable.eq("N_FRESH_CONTRAST")].simulated < 0).all()
    assert result[result.variable.eq("ADAP")].simulated.eq(34).all()
    for row in result[result.variable.isin(model.SIGNED | {"N2_SIGN_PENALTY"})].itertuples():
        delta = fresh.loc[(row.trno,row.date),"CHFPW"]-fresh.loc[(int(row.paired_trno),row.date),"CHFPW"]
        expected = max(0.,-delta) if row.variable=="N2_SIGN_PENALTY" else delta
        assert row.simulated == pytest.approx(expected)


def test_invalid_parent_cannot_become_successful_zero_penalty():
    frames={n:legacy.read_native(WORK/f"{n}.OUT") for n in ["PlantGro","PlantN","FreshWt","SoilWat"]}
    obs=targets(); obs=obs[obs.variable.eq("N2_SIGN_PENALTY")].iloc[[0]]
    row=obs.iloc[0]
    frames["FreshWt"].loc[(row.trno,row.date),"CHFPW"]=-99
    with pytest.raises(ValueError,match="contrast parent"):
        model.extract_observations(WORK,obs,native_frames=frames,anthesis={})


def test_response_missing_date_has_no_nearest_date_fallback():
    obs=targets();obs=obs[obs.variable.eq("N_FRESH_CONTRAST")].iloc[[0]].copy()
    obs["date"]="2026-01-01"
    with pytest.raises(KeyError):model.extract_observations(WORK,obs)


def test_missing_anthesis_is_an_error(tmp_path):
    path=tmp_path/"Evaluate.OUT"
    path.write_text("@RUN EXCODE TN ADAPS\n1 XXQL2601TM 4 -99\n")
    with pytest.raises(ValueError,match="anthesis"):model.read_anthesis(path)


def test_cumulative_harvest_is_exact_native_state():
    obs=targets();obs=obs[obs.variable.eq("CHPDT")]
    result=model.extract_observations(WORK,obs)
    native=legacy.read_native(WORK/"FreshWt.OUT")
    for row in result.itertuples():assert row.simulated==native.loc[(row.trno,row.date),"CHPDT"]


def test_phosphorus_anchors_change_only_full_seed_fields(tmp_path):
    import re
    path=tmp_path/"TMGRO048.SPE"
    original=(ROOT/"data/templates/genotype/TMGRO048.SPE.base").read_text()
    path.write_text(original)
    values={"OPTLFP_FS":.0041,"OPTSTP_FS":.0034,"OPTSDP_FS":.0059}
    inject_phosphorus(path,values)
    edited=path.read_text().splitlines();before=original.splitlines()
    changed=[(a,b) for a,b in zip(before,edited) if a!=b]
    assert len(changed)==3
    for old,new in changed:
        assert len(old)==len(new)
        oldnums=re.findall(r"[-+]?\d+\.\d+",old.split("Optimum")[0])
        newnums=re.findall(r"[-+]?\d+\.\d+",new.split("Optimum")[0])
        assert oldnums[:2]==newnums[:2] and oldnums[2]!=newnums[2]
    assert path.read_text().splitlines()[148].split()[2]=="0.0041"
