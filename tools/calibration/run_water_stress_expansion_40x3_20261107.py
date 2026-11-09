"""Explore broader official water-stress and carbon/nitrogen mobilization domains."""
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
sys.path.insert(0,str(ROOT))
from src.common.input_manifest import verify_manifest_integrity
from tools.calibration import restart_lowmob_water_priority_20261107 as prior

trial, native, gradient = prior.trial, prior.native, prior.gradient
PARENT = prior.RUN
ID = "eggplant_final_springs_water_stress_expanded_40x3_8agents_20261107"
RUN = ROOT/"workspace/runs"/ID
MEMBERS, UPDATES, WORKERS = 40, 3, 8
# Each proposal gives lower, upper, initial value and its process rationale.
REVISIONS = {
    "RWUMX": (.003,.060,.020,"Explore lower root water supply to distinguish W1 from W2"),
    "RWUEP1": (.8,3.,2.,"Broaden supply-demand threshold for leaf expansion"),
    "XSWBAR(3)": (.10,.90,.60,"Broaden soil-water response transition for reproductive growth"),
    "YSWBAR(3)": (.05,.95,.35,"Allow stronger reproductive reduction at the middle soil-water node"),
    "DSWBAR": (1.,30.,10.,"Explore soil depth used in the reproductive water response"),
    "NSTFAC": (.35,.98,.80,"Broaden nitrogen limitation of photosynthesis"),
    "RTNO3": (.003,.050,.012,"Broaden nitrate uptake per unit root length"),
    "RNO3C": (1.5,4.,2.5,"Broaden carbon cost of nitrate assimilation"),
    "NMOBMX": (.0005,.15,.020,"Extend both low and high nitrogen remobilization capacity"),
    "CMOBMX": (.0001,.05,.005,"Extend both low and high carbon reserve mobilization"),
    "NVSMOB": (.05,.80,.30,"Broaden relative vegetative nitrogen mobilization"),
    "PROLFF": (.04,.23,.11,"Broaden leaf protein floor while respecting fixed and active protein order"),
    "PROSHI": (.145,.20,.17,"Match lower bound to fixed PROSHG and remove infeasible nominal interval"),
}


def prepare():
    parent_path = PARENT/"design.json"
    parent = trial.read(parent_path)
    assert trial.read(PARENT/"sealed_design.json")["sha256"]==native.sha(parent_path)
    assert trial.read(PARENT/"pipeline_status.json")["status"]=="completed"
    for p,h in parent["source_hashes"].items():
        assert native.sha(Path(p))==h,p
    for season,ds in parent["datasets"].items():
        assert verify_manifest_integrity(ds["path"]).manifest_sha256==ds["manifest_sha256"]
        shutil.copytree(PARENT/f"{season}_inputs",RUN/f"{season}_inputs")
    b = pd.read_csv(parent["frozen_bounds"])
    changed = []
    for name,(lo,hi,initial,rationale) in REVISIONS.items():
        index, = b.index[b.native_name.eq(name)]
        old = b.loc[index].copy()
        assert old.status=="active"
        b.loc[index,["lower","upper","init","basis"]] = [lo,hi,initial,rationale]
        changed.append(dict(parameter=name,previous_lower=old.lower,previous_upper=old.upper,
                            lower=lo,upper=hi,init=initial,rationale=rationale))
    assert b.loc[b.native_name.eq("PROSHI"),"lower"].item() >= max(
        b.loc[b.native_name.isin(["PROSHG","PROSHF"]),"init"])
    assert b.loc[b.native_name.eq("PROLFF"),"upper"].item() <= b.loc[b.native_name.eq("PROLFG"),"lower"].item()
    assert set(b.loc[b.status.eq("active"),"native_name"])==set(parent["active_parameters"])
    b.to_csv(RUN/"approved_trial_bounds.csv",index=False)
    pd.DataFrame(changed).to_csv(RUN/"range_changes.csv",index=False)
    subprocess.run([sys.executable,"-X","utf8",str(ROOT/"tools/freeze_bounds.py"),
        "--proposal",str(RUN/"approved_trial_bounds.csv"),"--crop","eggplant","--bounds-id",ID,
        "--notes","User approved small 40x3 official-model water-gradient and remobilization domain exploration."],
        cwd=ROOT,check=True)
    frozen = Path(parent["frozen_bounds"]).with_name(ID+".csv")
    files=["calibration_observations.csv","objective_policy.csv","locked_validation_observations.csv",
           "calibration_diagnostic_observations.csv","fixed_input_audit.csv"]
    for name in files:
        shutil.copy2(PARENT/name,RUN/name)
    obs = pd.read_csv(RUN/"calibration_observations.csv").fillna("")
    assert len(obs)==511 and np.isclose(obs.final_weight.pow(2).sum(),97)
    assert np.isclose(obs.loc[obs.family.eq(gradient.WATER),"final_weight"].pow(2).sum(),10)

    pg = native.read_daily_output(PARENT/"selected_deterministic/PlantGro.OUT","26SP")
    metadata = pd.read_csv(Path(parent["datasets"]["26SP"]["path"])/"treatment_metadata.csv").set_index("treatment")
    stresses = []
    for tn,q in pg.groupby(level="trno"):
        stresses.append(dict(trno=tn,water=metadata.loc[tn,"water_level"],nitrogen=metadata.loc[tn,"nitrogen_level"],
            WSPD_max=q.WSPD.max(),WSGD_max=q.WSGD.max(),NSTD_max=q.NSTD.max(),
            WSPD_days=int(q.WSPD.gt(0).sum()),WSGD_days=int(q.WSGD.gt(0).sum())))
    pd.DataFrame(stresses).to_csv(RUN/"parent_daily_stress_audit.csv",index=False)

    fixed=[Path(__file__),parent_path,frozen,PARENT/"joint/joint.pst",RUN/"range_changes.csv",
           PARENT/"selected_deterministic/PlantGro.OUT",RUN/"parent_daily_stress_audit.csv",*(RUN/n for n in files)]
    for season in parent["datasets"]:
        fixed.extend((RUN/f"{season}_inputs").iterdir())
    hashes={p:h for p,h in parent["source_hashes"].items() if not Path(p).is_relative_to(PARENT)}
    hashes.update({str(p):native.sha(p) for p in fixed})
    design = parent | dict(run_id=ID,parent_trial=PARENT.name,parent_design_sha256=native.sha(parent_path),
        members=MEMBERS,updates=UPDATES,workers=WORKERS,bounds_id=ID,frozen_bounds=str(frozen),
        exploratory_range_changes=list(REVISIONS),source_hashes=hashes,
        proshi_feasibility=dict(nominal_lower=.145,nominal_upper=.20,required_lower=.145,
                               fixed_PROSHG=.145,fixed_PROSHF=.1095))
    design.pop("mobilization_limits",None)
    design.pop("mobilization_diagnostic_source",None)
    bounds=pd.read_csv(frozen).rename(columns={"name":"registry_name","native_name":"name"})
    trial.values_for(bounds,dict(zip(bounds.name,bounds.init)))
    native.write(RUN/"design.json",design)
    return design,bounds,obs


def make_case(design,b,obs,params,outputs):
    work=RUN/"joint"
    work.mkdir()
    for name in ("parameters.tpl","objectives.ins"):
        shutil.copy2(PARENT/"joint"/name,work/name)
    params.to_csv(work/"initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work/"parameters.csv",index_label="name")
    trial.write_outputs(work/"FormalObjectives.OUT",obs.obsnme,outputs.loc["base"])
    pst=pyemu.Pst(str(PARENT/"joint/joint.pst"))
    for row in b.itertuples():
        pst.parameter_data.loc[row.pest_name,["parval1","parlbnd","parubnd"]] = [
            params.loc["base",row.pest_name],row.lower,row.upper]
    pst.control_data.noptmax=UPDATES
    pst.pestpp_options["ies_num_reals"]=MEMBERS
    pst.model_command=[f'"{sys.executable}" -X utf8 "{Path(__file__)}" --forward "{RUN}"']
    pst.write(str(work/"joint.pst"),version=1)
    check=pyemu.Pst(str(work/"joint.pst"))
    assert (check.npar_adj,check.nnz_obs,check.control_data.noptmax)==(58,511,3)
    assert int(check.pestpp_options["ies_num_reals"])==40
    np.testing.assert_allclose(check.observation_data.weight,obs.final_weight,rtol=1e-8)
    np.testing.assert_allclose(check.parameter_data.loc[b.pest_name,["parlbnd","parubnd"]],b[["lower","upper"]],rtol=1e-9)
    manifest=yaml.safe_load((PARENT/"joint/run_manifest.yaml").read_text(encoding="utf8"))
    for key in ("mobilization_limits",):
        manifest.pop(key,None)
    manifest.update(run_id=ID,design=str(RUN/"design.json"),parent_trial=PARENT.name,bounds_id=ID,
                    ies_num_reals=MEMBERS,noptmax=UPDATES,agents=WORKERS,proshi_feasibility=design["proshi_feasibility"])
    (work/"run_manifest.yaml").write_text(yaml.safe_dump(manifest,sort_keys=False),encoding="utf8")


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN/"design.json").exists() or (RUN/"joint").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    try:
        trial.status(RUN,"preparing")
        design,b,obs=prepare()
        trial.DATES=design["anthesis_dates"]
        params,outputs,base=trial.initial_ensemble(RUN,b,obs,trial.contexts(RUN,design,b)["26SP"])
        design.update(initial_members=len(params),initial_ensemble_base=base)
        native.write(RUN/"design.json",design)
        native.write(RUN/"sealed_design.json",dict(sha256=native.sha(RUN/"design.json")))
        make_case(design,b,obs,params,outputs)
        trial.status(RUN,"running",phase="pest_ies",initial_members=len(params),n_targets=len(obs),agents=WORKERS)
        with (RUN/"parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable,"-X","utf8",str(ROOT/"tools/parallel/run_parallel.py"),
                "--run-dir",str(RUN/"joint"),"--case","joint","--mode","ies","--n-agents",str(WORKERS),"--wait"],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        if trial.read(RUN/"joint/run_status.json")["status"]!="completed":
            raise RuntimeError("PEST++ did not complete")
        for ds in design["datasets"].values():
            assert verify_manifest_integrity(ds["path"]).manifest_sha256==ds["manifest_sha256"]
        trial.status(RUN,"postprocessing")
        trial.finalize(RUN,b,obs,design,params)
        gradient.RUN=RUN
        gradient.save_gradient_diagnostics(design)
    except Exception as exc:
        state=trial.read(RUN/"pipeline_status.json")
        trial.status(RUN,"failed",phase=state["status"],error=f"{type(exc).__name__}: {exc}")
        raise


if __name__=="__main__":
    trial.MEMBERS,trial.UPDATES,trial.WORKERS=MEMBERS,UPDATES,WORKERS
    parser=argparse.ArgumentParser()
    parser.add_argument("--forward",type=Path)
    args=parser.parse_args()
    gradient.sa98_joint40.SIGNED.add(gradient.NITROGEN_OPERATOR)
    if args.forward is None:
        main()
    else:
        trial.forward(args.forward)
