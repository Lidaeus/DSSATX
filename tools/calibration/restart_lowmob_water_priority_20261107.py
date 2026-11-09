"""Increase water-gradient priority and revise two approved parameter ranges."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pyemu
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.input_manifest import verify_manifest_integrity
from tools.calibration import run_final_spring_morris98_mobilization_trial_20261107 as previous

trial = previous.trial
native = previous.native
gradient = previous.gradient
PARENT = previous.RUN
ID = "eggplant_26sp_final_cal25sp_old_val_lowmob_water10_80x4_8agents_20261107"
RUN = ROOT / "workspace/runs" / ID
WORKERS = 8
WATER_BUDGET = 10


def prepare():
    path = PARENT/"design.json"
    parent = trial.read(path)
    assert trial.read(PARENT/"sealed_design.json")["sha256"] == native.sha(path)
    assert trial.read(PARENT/"pipeline_status.json")["status"] == "completed"
    for filename,digest in parent["source_hashes"].items():
        assert native.sha(Path(filename)) == digest, filename
    for season,ds in parent["datasets"].items():
        assert verify_manifest_integrity(ds["path"]).manifest_sha256 == ds["manifest_sha256"]
        shutil.copytree(PARENT/f"{season}_inputs",RUN/f"{season}_inputs")

    b = pd.read_csv(parent["frozen_bounds"])
    old_bounds = b.copy()
    b.loc[b.native_name.eq("XSWBAR(3)"),["lower","basis"]] = [.22,"user_requested_lower_0.22"]
    b.loc[b.native_name.eq("PROSHI"),["lower","upper","init","basis"]] = [
        .10,.20,.15,"user_requested_nominal_0.10_to_0.20_with_inherited_protein_order"]
    pd.DataFrame([dict(parameter=n,previous_lower=old_bounds.loc[old_bounds.native_name.eq(n),"lower"].item(),
        previous_upper=old_bounds.loc[old_bounds.native_name.eq(n),"upper"].item(),
        lower=b.loc[b.native_name.eq(n),"lower"].item(),upper=b.loc[b.native_name.eq(n),"upper"].item())
        for n in ("XSWBAR(3)","PROSHI")]).to_csv(RUN/"range_changes.csv",index=False)
    shell_floor = max(b.loc[b.native_name.isin(["PROSHG","PROSHF"]),"init"])
    assert shell_floor == .145
    assert b.loc[b.native_name.isin(["PROSHG","PROSHF"]),"status"].eq("fixed").all()
    b.to_csv(RUN/"approved_trial_bounds.csv",index=False)
    subprocess.run([sys.executable,"-X","utf8",str(ROOT/"tools/freeze_bounds.py"),
        "--proposal",str(RUN/"approved_trial_bounds.csv"),"--crop","eggplant","--bounds-id",ID,
        "--notes","User-requested XSWBAR3 and PROSHI intervals; existing shell protein order remains enforced."],
        cwd=ROOT,check=True)
    frozen = Path(parent["frozen_bounds"]).with_name(ID+".csv")

    obs = pd.read_csv(PARENT/"calibration_observations.csv")
    policy = pd.read_csv(PARENT/"objective_policy.csv")
    target = policy.family.eq(gradient.WATER)
    assert target.sum()==1 and policy.loc[target,"budget"].item()==2
    policy.loc[target,"budget"] = WATER_BUDGET
    water = obs.family.eq(gradient.WATER)
    assert water.sum()==4 and np.isclose(obs.loc[water,"final_weight"].pow(2).sum(),2)
    obs.loc[water,["final_weight","budget_multiplier"]] *= np.sqrt(WATER_BUDGET/2)
    assert len(obs)==511 and np.isclose(obs.final_weight.pow(2).sum(),97)
    assert np.isclose(obs.loc[water,"final_weight"].pow(2).sum(),WATER_BUDGET)
    policy.to_csv(RUN/"objective_policy.csv",index=False)
    obs.to_csv(RUN/"calibration_observations.csv",index=False)
    copied = ["locked_validation_observations.csv","calibration_diagnostic_observations.csv","fixed_input_audit.csv"]
    for name in copied:
        shutil.copy2(PARENT/name,RUN/name)
    fixed = [Path(__file__),path,frozen,PARENT/"joint/joint.pst",RUN/"range_changes.csv",
        RUN/"objective_policy.csv",RUN/"calibration_observations.csv",*(RUN/name for name in copied)]
    for season in parent["datasets"]:
        fixed.extend((RUN/f"{season}_inputs").iterdir())
    hashes = {p:h for p,h in parent["source_hashes"].items() if not Path(p).is_relative_to(PARENT)}
    hashes.update({str(p):native.sha(p) for p in fixed})
    design = parent | dict(run_id=ID,parent_trial=PARENT.name,parent_design_sha256=native.sha(path),
        workers=WORKERS,bounds_id=ID,frozen_bounds=str(frozen),objective_budget=97,water_gradient_budget=WATER_BUDGET,
        proshi_feasibility=dict(nominal_lower=.10,nominal_upper=.20,
            required_lower=shell_floor,fixed_PROSHG=.145,fixed_PROSHF=.1095),
        source_hashes=hashes)
    bounds = pd.read_csv(frozen).rename(columns={"name":"registry_name","native_name":"name"})
    trial.values_for(bounds,dict(zip(bounds.name,bounds.init)))
    native.write(RUN/"design.json",design)
    return design,bounds,obs.fillna("")


def make_case(design,b,obs,params,outputs):
    work = RUN/"joint"
    work.mkdir()
    for name in ("parameters.tpl","objectives.ins"):
        shutil.copy2(PARENT/"joint"/name,work/name)
    params.to_csv(work/"initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work/"parameters.csv",index_label="name")
    trial.write_outputs(work/"FormalObjectives.OUT",obs.obsnme,outputs.loc["base"])
    pst = pyemu.Pst(str(PARENT/"joint/joint.pst"))
    assert pst.observation_data.obsnme.tolist()==obs.obsnme.tolist()
    for row in b.itertuples():
        pst.parameter_data.loc[row.pest_name,["parval1","parlbnd","parubnd"]] = [
            params.loc["base",row.pest_name],row.lower,row.upper]
    pst.observation_data["weight"] = obs.set_index("obsnme").final_weight
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(__file__)}" --forward "{RUN}"']
    pst.write(str(work/"joint.pst"),version=1)
    actual = pyemu.Pst(str(work/"joint.pst"))
    assert (actual.npar_adj,actual.nnz_obs,actual.control_data.noptmax)==(58,511,4)
    assert actual.pestpp_options==pst.pestpp_options
    np.testing.assert_allclose(actual.observation_data.weight,obs.final_weight,rtol=1e-8)
    np.testing.assert_allclose(actual.parameter_data.loc[b.pest_name,["parlbnd","parubnd"]],b[["lower","upper"]],rtol=1e-9)
    manifest = yaml.safe_load((PARENT/"joint/run_manifest.yaml").read_text(encoding="utf8"))
    manifest.update(run_id=ID,parent_trial=PARENT.name,design=str(RUN/"design.json"),bounds_id=ID,
                    agents=WORKERS,objective_budget=97,water_gradient_budget=WATER_BUDGET,
                    proshi_feasibility=design["proshi_feasibility"])
    (work/"run_manifest.yaml").write_text(yaml.safe_dump(manifest,sort_keys=False),encoding="utf8")


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN/"design.json").exists() or (RUN/"joint").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    try:
        trial.status(RUN,"preparing")
        design,b,obs = prepare()
        trial.WORKERS = WORKERS
        trial.DATES = design["anthesis_dates"]
        params,outputs,base = trial.initial_ensemble(RUN,b,obs,trial.contexts(RUN,design,b)["26SP"])
        design.update(initial_members=len(params),initial_ensemble_base=base)
        native.write(RUN/"design.json",design)
        native.write(RUN/"sealed_design.json",dict(sha256=native.sha(RUN/"design.json")))
        make_case(design,b,obs,params,outputs)
        trial.status(RUN,"running",phase="pest_ies",initial_members=len(params),n_targets=len(obs),agents=WORKERS)
        with (RUN/"parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable,"-X","utf8",str(ROOT/"tools/parallel/run_parallel.py"),
                "--run-dir",str(RUN/"joint"),"--case","joint","--mode","ies",
                "--n-agents",str(WORKERS),"--wait"],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        if trial.read(RUN/"joint/run_status.json")["status"]!="completed":
            raise RuntimeError("PEST++ did not complete")
        for ds in design["datasets"].values():
            assert verify_manifest_integrity(ds["path"]).manifest_sha256==ds["manifest_sha256"]
        trial.status(RUN,"postprocessing")
        trial.finalize(RUN,b,obs,design,params)
        gradient.RUN = RUN
        gradient.save_gradient_diagnostics(design)
    except Exception as exc:
        state = trial.read(RUN/"pipeline_status.json")
        trial.status(RUN,"failed",phase=state["status"],error=f"{type(exc).__name__}: {exc}")
        raise


if __name__=="__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--forward",type=Path)
    args = parser.parse_args()
    gradient.sa98_joint40.SIGNED.add(gradient.NITROGEN_OPERATOR)
    if args.forward is None:
        main()
    else:
        trial.forward(args.forward)
