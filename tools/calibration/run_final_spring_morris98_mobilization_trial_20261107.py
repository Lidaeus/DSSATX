"""Trial the newly screened coefficients and lower mobilization ceilings."""
import argparse
from decimal import Decimal, ROUND_FLOOR
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
from tools.calibration import run_final_spring_gradient_trial_20261106 as gradient

trial = gradient.trial
native = gradient.native
PARENT = gradient.RUN
ID = "eggplant_26sp_final_cal25sp_old_val_morris98_lowmob_80x4_20261107"
RUN = ROOT / "workspace/runs" / ID
PROPOSAL = ROOT / "configs/calibration_proposals/eggplant_dual_morris98_final_bundles_20261107"
MORRIS = ROOT / "workspace/runs/morris_dual_spring126_r40_final_bundles_sasc_default_20261107"
GRID = ROOT / "workspace/runs/eggplant_global0053_carbon_n_mobilization_grid_20261107"


def freeze(parent, proposal, selected):
    b = pd.read_csv(parent["frozen_bounds"])
    previous_active = set(b.loc[b.status.eq("active"),"native_name"])
    active = set(proposal.index)
    added, removed = active-previous_active, previous_active-active
    assert (added,removed) == ({"YLEAF(4)","NVSMOB","RWUEP1"},{"PORPT","ALPHS","PROSTF"})
    scan = pd.read_csv(GRID/"parameter_scales.csv").query("scale_pct == 3").set_index("parameter")
    limits, rows = {}, []
    for i,row in b.iterrows():
        name = row.native_name
        init,lo,hi,kind = row.init,row.lower,row.upper,row.status
        basis = "inherited"
        if name in added:
            lo,hi = proposal.loc[name,["morris_lower","morris_upper"]].astype(float)
            assert lo <= init <= hi
            kind,basis = "active","new_morris_supplement"
        elif name in removed:
            init = lo = hi = selected[name]
            kind,basis = "fixed","fixed_at_parent_selected"
        elif name in {"NMOBMX","CMOBMX"}:
            requested = float(Decimal(str(selected[name]))/2)
            hi = gradient.previous.representable_edge(requested,ROUND_FLOOR)
            lo = float(scan.loc[name,"actual"])
            assert scan.loc[name,"baseline"] == selected[name] and 0 < lo < hi <= requested < row.lower
            init = (lo+hi)/2
            basis = "actual_3pct_grid_floor_and_half_parent_ceiling"
            limits[name] = dict(parent_selected=selected[name], requested_upper=requested, lower=lo, upper=hi)
        if basis != "inherited":
            b.loc[i,["init","lower","upper","status","basis"]] = [init,lo,hi,kind,basis]
        rows.append(dict(parameter=name,prior_status=row.status,prior_lower=row.lower,prior_upper=row.upper,
            status=kind,init=init,lower=lo,upper=hi,basis=basis))
    assert set(b.loc[b.status.eq("active"),"native_name"]) == active and len(active)==58
    assert b.loc[b.native_name.eq("YLEAF(4)"),"upper"].item()+b.loc[b.native_name.eq("YSTEM(4)"),"init"].item()<=1
    assert set(limits)=={"NMOBMX","CMOBMX"}
    b.to_csv(RUN/"approved_trial_bounds.csv",index=False)
    pd.DataFrame(rows).to_csv(RUN/"range_source_audit.csv",index=False)
    subprocess.run([sys.executable,"-X","utf8",str(ROOT/"tools/freeze_bounds.py"),
        "--proposal",str(RUN/"approved_trial_bounds.csv"),"--crop","eggplant","--bounds-id",ID,
        "--notes","New Morris 52+6, tested floors and half-parent mobilization ceilings."],cwd=ROOT,check=True)
    return Path(parent["frozen_bounds"]).with_name(ID+".csv"),limits


def prepare():
    path = PARENT/"design.json"
    parent = trial.read(path)
    assert trial.read(PARENT/"sealed_design.json")["sha256"] == native.sha(path)
    assert trial.read(PARENT/"pipeline_status.json")["status"]=="completed"
    for p,digest in parent["source_hashes"].items():
        assert native.sha(Path(p))==digest,p
    selection = trial.read(PARENT/"selection.json")
    parameter_file = PARENT/"best_calibration_parameters.csv"
    assert native.sha(parameter_file)==selection["parameters_sha256"] and selection["member"]=="global_0053"
    selected = pd.read_csv(parameter_file).set_index("name").value.to_dict()
    shortlist = PROPOSAL/"proposed_active_parameters.csv"
    proposal_path = PROPOSAL/"proposal.json"
    evidence = trial.read(proposal_path)
    assert native.sha(shortlist)==evidence["artifact_sha256"][shortlist.name] and evidence["run_id"]==MORRIS.name
    proposal = pd.read_csv(shortlist).set_index("parameter")
    assert set(proposal.index)==set(evidence["core_parameters"]+evidence["supplement_parameters"])
    scan_manifest = trial.read(GRID/"experiment_manifest.json")
    assert scan_manifest["completed"]==14 and scan_manifest["baseline_reproduced"]
    assert native.sha(GRID/"parameter_scales.csv")==scan_manifest["results_sha256"]["parameter_scales.csv"]
    m = trial.read(MORRIS/"run_manifest.json")
    assert trial.read(MORRIS/"campaign_status.json")["status"]=="completed"
    assert m["slpf"]==parent["SLPF"]=={"25SP":.92,"26SP":.89} and m["sasc_marker"]==-99
    assert m["input_bundles"]==parent["datasets"]
    audit = []
    for season,entry in parent["datasets"].items():
        assert verify_manifest_integrity(entry["path"]).manifest_sha256==entry["manifest_sha256"]
        payload = RUN/f"{season}_inputs"
        shutil.copytree(MORRIS/f"{season}_fixed_inputs",payload)
        assert {f.name:native.sha(f) for f in payload.iterdir()}==m["fixed_payload_sha256"][season]
        filex = next(payload.glob("*.TMX"))
        section = filex.read_text(encoding="ascii").split("*SOIL ANALYSIS",1)[1].split("\n*",1)[0]
        layers = [line.split() for line in section.splitlines() if len(line.split())==10 and line.split()[0].isdigit()]
        assert len(layers)==len(entry["treatments"])*10 and {float(row[-1]) for row in layers}=={-99.}
        sol = (payload/"SOIL.SOL").read_text(encoding="ascii").splitlines()
        profile = native.single_line(sol,lambda line:line.startswith("@ SCOM"))+1
        assert float(sol[profile].split()[6])==parent["SLPF"][season]
        audit.append(dict(season=season,bundle=entry["bundle_id"],role=entry["role"],SLPF=parent["SLPF"][season],
            SASC=-99,rows_verified=len(layers),initial_mineral_n_scale=1))
    pd.DataFrame(audit).to_csv(RUN/"fixed_input_audit.csv",index=False)
    observation_files = ["calibration_observations.csv","objective_policy.csv",
        "locked_validation_observations.csv","calibration_diagnostic_observations.csv"]
    for name in observation_files:
        shutil.copy2(PARENT/name,RUN/name)
    obs = pd.read_csv(RUN/"calibration_observations.csv").fillna("")
    assert len(obs)==511 and np.isclose(obs.final_weight.pow(2).sum(),89)
    assert obs.role.eq("calibration").all() and obs.season_id.eq("26SP").all()
    frozen,limits = freeze(parent,proposal,selected)
    fixed = [Path(__file__),path,parameter_file,frozen,proposal_path,shortlist,GRID/"parameter_scales.csv",
             MORRIS/"run_manifest.json",PARENT/"joint/joint.pst",RUN/"fixed_input_audit.csv",RUN/"range_source_audit.csv",
             *(RUN/name for name in observation_files)]
    for season in parent["datasets"]:
        fixed.extend((RUN/f"{season}_inputs").iterdir())
    hashes = {p:h for p,h in parent["source_hashes"].items() if not Path(p).is_relative_to(PARENT)}
    hashes.update({str(p):native.sha(p) for p in fixed})
    design = parent | dict(run_id=ID,parent_trial=PARENT.name,parent_design_sha256=native.sha(path),
        active_parameters=proposal.index.tolist(),activation_source=MORRIS.name,bounds_id=ID,frozen_bounds=str(frozen),
        mobilization_limits=limits,mobilization_diagnostic_source=GRID.name,source_hashes=hashes)
    b = pd.read_csv(frozen).rename(columns={"name":"registry_name","native_name":"name"})
    trial.values_for(b,dict(zip(b.name,b.init)))
    native.write(RUN/"design.json",design)
    return design,b,obs


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
        pst.parameter_data.loc[row.pest_name,["partrans","parval1","parlbnd","parubnd"]] = [
            "none" if row.status=="active" else "fixed",params.loc["base",row.pest_name],row.lower,row.upper]
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(__file__)}" --forward "{RUN}"']
    pst.write(str(work/"joint.pst"),version=1)
    check = pyemu.Pst(str(work/"joint.pst"))
    assert (check.npar_adj,check.nnz_obs,check.control_data.noptmax)==(58,511,4)
    assert set(check.adj_par_names)==set(b.loc[b.status.eq("active"),"pest_name"])
    assert check.pestpp_options==pst.pestpp_options
    np.testing.assert_allclose(check.parameter_data.loc[b.pest_name,["parlbnd","parubnd"]],b[["lower","upper"]],rtol=1e-9)
    manifest = yaml.safe_load((PARENT/"joint/run_manifest.yaml").read_text(encoding="utf-8"))
    manifest.update(run_id=ID,design=str(RUN/"design.json"),parent_trial=PARENT.name,bounds_id=ID,
        activation_source=design["activation_source"],mobilization_limits=design["mobilization_limits"])
    (work/"run_manifest.yaml").write_text(yaml.safe_dump(manifest,sort_keys=False),encoding="utf-8")


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN/"design.json").exists() or (RUN/"joint").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    try:
        trial.status(RUN,"preparing")
        design,b,obs = prepare()
        trial.DATES = design["anthesis_dates"]
        params,outputs,base = trial.initial_ensemble(RUN,b,obs,trial.contexts(RUN,design,b)["26SP"])
        design.update(initial_members=len(params),initial_ensemble_base=base)
        native.write(RUN/"design.json",design)
        native.write(RUN/"sealed_design.json",dict(sha256=native.sha(RUN/"design.json")))
        make_case(design,b,obs,params,outputs)
        trial.status(RUN,"running",phase="pest_ies",initial_members=len(params),n_targets=len(obs))
        with (RUN/"parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable,"-X","utf8",str(ROOT/"tools/parallel/run_parallel.py"),
                "--run-dir",str(RUN/"joint"),"--case","joint","--mode","ies",
                "--n-agents",str(design["workers"]),"--wait"],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
        if trial.read(RUN/"joint/run_status.json")["status"]!="completed":
            raise RuntimeError("PEST++ did not complete")
        for dataset in design["datasets"].values():
            assert verify_manifest_integrity(dataset["path"]).manifest_sha256==dataset["manifest_sha256"]
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
