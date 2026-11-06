"""Repeat the C31-initial trial with anthesis excluded from Phi."""
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pyemu
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.input_manifest import verify_calibrated_input_bundle
from tools.calibration import restart_dual_morris98_trial_c31_initial_20261106 as parent_trial

trial = parent_trial.trial
PARENT = parent_trial.RUN
ID = "eggplant_26sp_cal25sp_val_dual_morris98_80x4_c31initial_noadat_20261106"
RUN = ROOT/"workspace/runs"/ID


def prepare():
    path = PARENT/"design.json"
    parent = trial.read(path)
    assert trial.read(PARENT/"sealed_design.json")["sha256"]==trial.native.sha(path)
    assert trial.read(PARENT/"pipeline_status.json")["status"]=="completed"
    assert (parent["members"],parent["updates"],parent["target_count"])==(80,4,629)
    for name,digest in parent["source_hashes"].items():
        assert trial.native.sha(Path(name))==digest, name
    for season, ds in parent["datasets"].items():
        assert verify_calibrated_input_bundle(ds["path"]).manifest_sha256==ds["manifest_sha256"]
        shutil.copytree(PARENT/f"{season}_inputs",RUN/f"{season}_inputs")
    shutil.copy2(PARENT/"locked_validation_observations.csv",RUN/"locked_validation_observations.csv")
    all_obs = pd.read_csv(PARENT/"calibration_observations.csv").fillna("")
    excluded = all_obs.variable.eq("ADAP")
    assert excluded.sum()==12 and all_obs.loc[excluded,"family"].eq("ANTHESIS").all()
    obs = all_obs.loc[~excluded].copy()
    assert len(obs)==617 and np.isclose((obs.final_weight**2).sum(),97)
    obs.to_csv(RUN/"calibration_observations.csv",index=False)
    all_obs.loc[excluded].assign(final_weight=0.,budget_multiplier=0.).to_csv(
        RUN/"anthesis_diagnostic_observations.csv",index=False)
    policy = pd.read_csv(PARENT/"objective_policy.csv")
    policy.loc[policy.family.eq("ANTHESIS"),["budget","n_targets","diagnostic_only"]] = [0,0,True]
    assert policy.budget.sum()==97
    policy.to_csv(RUN/"objective_policy.csv",index=False)
    hashes = {}
    for name,digest in parent["source_hashes"].items():
        f = Path(name)
        if f.parent in {PARENT/"25SP_inputs",PARENT/"26SP_inputs"}:
            f = RUN/f.relative_to(PARENT)
            assert trial.native.sha(f)==digest
        elif f.parent==PARENT and f.name in {"calibration_observations.csv","locked_validation_observations.csv","objective_policy.csv"}:
            f = RUN/f.name
            digest = trial.native.sha(f)
        hashes[str(f)] = digest
    for f in (Path(__file__),RUN/"anthesis_diagnostic_observations.csv",PARENT/"joint/joint.pst",
              PARENT/"joint/initial_ensemble.csv",PARENT/"joint/joint.0.obs.csv"):
        hashes[str(f)] = trial.native.sha(f)
    design = parent | dict(parent_trial=PARENT.name,parent_design_sha256=trial.native.sha(path),
        target_count=len(obs),anthesis_in_objective=False,anthesis_diagnostic_count=int(excluded.sum()),
        objective_budget=97,initial_ensemble_policy="Reuse identical input parameters; replay base before IES",
        source_hashes=hashes)
    trial.native.write(RUN/"design.json",design)
    trial.native.write(RUN/"sealed_design.json",dict(sha256=trial.native.sha(RUN/"design.json")))
    b = pd.read_csv(design["frozen_bounds"]).rename(columns={"name":"registry_name","native_name":"name"})
    return design,b,obs


def make_case(design,b,obs):
    work = RUN/"joint"
    work.mkdir()
    src = PARENT/"joint"
    shutil.copy2(src/"parameters.tpl",work/"parameters.tpl")
    shutil.copy2(src/"initial_ensemble.csv",work/"initial_ensemble.csv")
    params = pd.read_csv(work/"initial_ensemble.csv",index_col=0)
    outputs = pd.read_csv(src/"joint.0.obs.csv",index_col=0)
    assert len(params)==len(outputs)==80 and set(params.index)==set(outputs.index)
    assert np.isfinite(outputs.loc[:,obs.obsnme]).all().all()
    params.loc["base"].rename("value").to_csv(work/"parameters.csv",index_label="name")
    (work/"objectives.ins").write_text(
        "pif ~\n"+"".join(f"l1 w !{name}!\n" for name in obs.obsnme),encoding="ascii")
    pst = pyemu.Pst(str(src/"joint.pst"))
    pst.observation_data = pst.observation_data.loc[obs.obsnme].copy()
    groups = set(pst.observation_data.obgnme)
    assert "anthesis" not in groups and pst.nnz_obs==len(obs)
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(trial.__file__)}" --forward "{RUN}"']
    pst.write(str(work/"joint.pst"),version=1)
    actual = pyemu.Pst(str(work/"joint.pst"))
    assert actual.npar_adj==58 and actual.nnz_obs==617 and actual.control_data.noptmax==4
    assert actual.pestpp_options==pst.pestpp_options
    np.testing.assert_allclose(actual.observation_data.loc[obs.obsnme,"weight"],obs.final_weight,rtol=1e-8)
    manifest = yaml.safe_load((src/"run_manifest.yaml").read_text(encoding="utf-8"))
    manifest.update(run_id=ID,design=str(RUN/"design.json"),n_obs=617,anthesis_in_objective=False,
                    parent_trial=PARENT.name)
    (work/"run_manifest.yaml").write_text(yaml.safe_dump(manifest,sort_keys=False),encoding="utf-8")
    # All inputs and initial parameter vectors match the prior trial. Replay
    # the base under the revised operator and check the 617 retained outputs.
    raw = params.loc["base",b.pest_name]
    values = trial.values_for(b,dict(zip(b.name,raw)))
    ctx = trial.contexts(RUN,design,b)["26SP"]
    with TemporaryDirectory(prefix="base_replay_",dir=RUN) as tmp:
        result = trial.evaluate(RUN,Path(tmp),ctx,values,obs)
    # PEST++ writes the archived ensemble with six significant digits.
    np.testing.assert_allclose(result.pest_output,outputs.loc["base",obs.obsnme],rtol=5e-6,atol=1e-9)
    trial.write_outputs(work/"FormalObjectives.OUT",obs.obsnme,result.pest_output)
    trial.native.write(RUN/"initial_ensemble_replay.json",dict(
        initial_members=len(params),n_compared=len(obs),base_reproduced=True,
        max_encoded_difference=float(np.abs(result.pest_output.to_numpy()-outputs.loc["base",obs.obsnme]).max())))
    return params


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN/"design.json").exists() or (RUN/"joint").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    try:
        trial.status(RUN,"preparing")
        design,b,obs = prepare()
        trial.DATES = design["anthesis_dates"]
        params = make_case(design,b,obs)
        trial.status(RUN,"running",phase="pest_ies",initial_members=len(params),n_targets=len(obs))
        with (RUN/"parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable,"-X","utf8",str(ROOT/"tools/parallel/run_parallel.py"),
                "--run-dir",str(RUN/"joint"),"--case","joint","--mode","ies",
                "--n-agents",str(trial.WORKERS),"--wait"],cwd=ROOT,stdout=log,
                stderr=subprocess.STDOUT,check=True)
        if trial.read(RUN/"joint/run_status.json")["status"]!="completed":
            raise RuntimeError("PEST++ did not complete")
        trial.status(RUN,"postprocessing")
        trial.finalize(RUN,b,obs,design,params)
    except Exception as exc:
        previous = trial.read(RUN/"pipeline_status.json")
        trial.status(RUN,"failed",phase=previous["status"],error=f"{type(exc).__name__}: {exc}")
        raise


if __name__=="__main__":
    main()
