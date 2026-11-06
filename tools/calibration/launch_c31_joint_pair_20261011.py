"""Freeze and execute approved 42/67-parameter joint cases sequentially."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pyemu
from scipy.stats import qmc
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration import joint_n_objectives as model
from src.calibration import single_season_n as legacy

REVIEW = ROOT / "configs/calibration_proposals/eggplant_26sp_n012_c31_joint_review_20261011"
IDS = ["eggplant_26sp_n012_c31_joint42_20261011", "eggplant_26sp_n012_c31_joint67_20261011"]
PAIR = ROOT / "workspace/runs/eggplant_26sp_n012_c31_joint_pair_20261011"
AUTH = "整体准许上述方案；先后运行现行42个自由参数版、类似C31批次的67个自由参数版；确认正常运行即可，不必持续监测。"


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def paths(run_id):
    return ROOT/"configs/runs"/run_id, ROOT/"workspace/runs"/run_id


def logged(command, log, cwd=ROOT):
    with Path(log).open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Process failed ({result.returncode}): {log}")


def prepare():
    if PAIR.exists() or any(paths(x)[0].exists() or paths(x)[1].exists() for x in IDS):
        raise FileExistsError("Never overwrite an existing approved pair")
    receipt = json.loads((REVIEW/"review_receipt.json").read_text(encoding="utf-8"))
    for name, digest in receipt["artifact_hashes"].items():
        if legacy.sha(REVIEW/name) != digest:
            raise ValueError("Review artifact changed")
    proposal = json.loads((REVIEW/"proposal.json").read_text(encoding="utf-8"))
    for rel, digest in proposal["source_hashes"].items():
        if legacy.sha(ROOT/rel) != digest:
            raise ValueError(f"Reviewed source changed: {rel}")
    PAIR.mkdir(parents=True)
    original = json.loads((ROOT/"configs/runs/eggplant_26sp_n012_formal_20261011_r3/design.json").read_text(encoding="utf-8"))
    existing = pd.read_csv(ROOT/"data/parameter_registry/bounds_frozen/eggplant/eggplant_26sp_n012_formal_20261011.csv").fillna("")
    historical = pd.read_csv(ROOT/"data/parameter_registry/bounds_frozen/eggplant/eggplant_full_gen_final_calib_scheme1_tb1_200x6_20260927.csv").fillna("")
    historical.name = historical.name.str.upper()
    historical = historical.set_index("name", drop=False)
    c31 = ROOT/"workspace/runs"/proposal["c31_reference_run"]
    active67 = {x.upper() for x in pyemu.Pst(str(c31/(c31.name+".pst"))).adj_par_names}
    active42 = set(original["eligible_active_parameters"])
    assert len(active67) == 67 and len(active42) == 42
    target = pd.read_csv(REVIEW/"proposed_calibration_targets.csv").fillna("")
    target["final_weight"] = target.proposed_weight
    target["obsnme"] = [f"j26_{i:04d}" for i in range(len(target))]
    target["approved"] = True
    target["execution_enabled"] = True
    runtime = list(original["runtime_hashes"]) + ["src/calibration/joint_n_objectives.py", "src/dssat/forward_joint.py", "tools/calibration/launch_c31_joint_pair_20261011.py"]
    difference = []
    for count, run_id, active in [(42, IDS[0], active42), (67, IDS[1], active67)]:
        config, run = paths(run_id)
        config.mkdir(parents=True); run.mkdir(parents=True)
        bounds = existing.copy().set_index("name", drop=False)
        for name in sorted(active-set(existing[existing.status.eq("active")].name)):
            h = historical.loc[name]
            if name not in bounds.index:
                bounds.loc[name] = {col: h.get(col, "") for col in bounds.columns}
            bounds.loc[name, ["lower", "upper", "init"]] = [h.lower, h.upper, (h.lower+h.upper)/2]
        for name in bounds.index:
            bounds.loc[name, "status"] = "active" if name in active else "fixed"
            if name not in active:
                bounds.loc[name, ["lower", "upper"]] = bounds.loc[name, "init"]
            bounds.loc[name, "file"] = f"TMGRO048.{bounds.loc[name,'location']}.base"
        bounds = bounds.reset_index(drop=True)
        bounds.to_csv(config/"bounds_proposal.csv", index=False)
        logged([sys.executable, str(ROOT/"tools/freeze_bounds.py"), "--proposal", str(config/"bounds_proposal.csv"),
                "--crop", "eggplant", "--bounds-id", run_id, "--notes", f"User approved direct joint {count}-parameter version; latest inputs remain fixed"], run/"freeze_bounds.log")
        frozen = ROOT/"data/parameter_registry/bounds_frozen/eggplant"/(run_id+".csv")
        target.to_csv(config/"calibration_observations.csv", index=False)
        shutil.copy2(ROOT/"configs/runs/eggplant_26sp_n012_formal_20261011_r3/locked_evaluation_observations.csv", config/"locked_evaluation_observations.csv")
        shutil.copy2(REVIEW/"proposed_objective_policy.csv", config/"approved_objective_policy.csv")
        design = dict(schema="formal_joint_n_v1", design_id=run_id, approved=True, executable=True,
                      approval=dict(user_statement=AUTH, recorded_at=stamp(), review_sha256=legacy.sha(REVIEW/"proposal.json")),
                      status="approved_preflight_pending", runtime_preflight_passed=False,
                      datasets=proposal["datasets"], bounds_id=run_id, bounds_sha256=legacy.sha(frozen),
                      active_parameters=sorted(active), active_parameter_count=count,
                      calibration_observations_sha256=legacy.sha(config/"calibration_observations.csv"),
                      evaluation_catalog_sha256=legacy.sha(config/"locked_evaluation_observations.csv"),
                      runtime_hashes={rel:legacy.sha(ROOT/rel) for rel in runtime},
                      dssat_executable=original["dssat_executable"], dssat_executable_sha256=original["dssat_executable_sha256"],
                      noptmax=6, ies_num_reals=200, workers=6, seed=20261011,
                      staged_calibration=False, phi_budget_total=100, target_count=492,
                      parameter_start="frozen midpoints, no earlier fitted-member warm start",
                      scope="genotype only; soil, initial state, management, TAV/AMP=20/6 fixed",
                      c31_activation_reference_sha256=legacy.sha(c31/(c31.name+".pst")),
                      joint_method="Sobol full frozen domain; physical and native-output feasibility only",
                      uncertainty_interpretation="feasibility-conditioned optimization ensemble, not Bayesian posterior",
                      selection_rule="minimum complete 492-row fixed calibration Phi, no validation selection")
        legacy.write_json(config/"design.json", design)
        model.load_design(config/"design.json", require_preflight=False)
        initial = model.validate_parameters(dict(zip(bounds.name,bounds.init)), bounds)
        pd.DataFrame(initial.items(),columns=["name","value"]).to_csv(run/"initial_parameters.csv",index=False)
        compared = model.evaluate(config/"design.json",run/"initial_parameters.csv",run/"preflight/baseline",preflight=True)
        phi = float(np.square((compared.simulated-compared.observed)*compared.final_weight).sum())
        legacy.write_json(run/"preflight/report.json",dict(status="forward_preflight_passed",target_count=len(compared),phi=phi,
                           active_parameter_injection_count=count, input_and_binary_hashes_verified=True,
                           signed_contrasts_allowed=True, no_activation_filter=True))
        design.update(runtime_preflight_passed=True,status="approved_ready")
        legacy.write_json(config/"design.json",design)
        legacy.write_json(config/"frozen_configuration_receipt.json",dict(design_sha256=legacy.sha(config/"design.json"),recorded_at=stamp()))
        model.load_design(config/"design.json")
        difference.append(dict(run_id=run_id,n_active=count,active_parameters=sorted(active),initial_phi=phi))
    legacy.write_json(PAIR/"approval_receipt.json",dict(user_statement=AUTH,recorded_at=stamp(),sequence=IDS,
                      common_targets_sha256=legacy.sha(paths(IDS[0])[0]/"calibration_observations.csv"),
                      parameters=difference,added_in_67=sorted(active67-active42),fixed_in_67=sorted(active42-active67),
                      second_case_uses_first_solution=False))
    legacy.write_json(PAIR/"sequence_status.json",dict(status="prepared",sequence=IDS,completed=[],user_monitoring="startup confirmation only"))
    print("Both joint cases passed baseline and injection preflight",flush=True)


def screen_one(run_id, ordinal, values):
    config,run=paths(run_id); folder=run/"initial_feasibility"/f"candidate_{ordinal:04d}"
    folder.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(values.items(),columns=["name","value"]).to_csv(folder/"parameters.csv",index=False)
    try:
        comparison=model.evaluate(config/"design.json",folder/"parameters.csv",folder)
        # Feasibility never ranks residuals or accesses the validation catalog.
        return dict(ordinal=ordinal,accepted=True,parameters=values,output_sha256=legacy.sha(folder/"FormalObjectives.OUT"))
    except Exception as error:
        return dict(ordinal=ordinal,accepted=False,error=str(error))


def initial_ensemble(run_id):
    config,run=paths(run_id);design,bounds,obs=model.load_design(config/"design.json")
    engine=qmc.Sobol(d=len(design["active_parameters"]),scramble=True,seed=design["seed"])
    points=engine.random_base2(11)
    initial=dict(zip(bounds.name,bounds.init)); byname=bounds.set_index("name")
    accepted=[dict(name="base",parameters=initial)]; attempts=[]; candidates=[]
    for ordinal,point in enumerate(points):
        values=initial.copy()
        for name,u in zip(design["active_parameters"],point):
            row=byname.loc[name]; values[name]=float(row.lower+u*(row.upper-row.lower))
        try:
            values=model.validate_parameters(values,bounds)
        except ValueError as error:
            attempts.append(dict(ordinal=ordinal,accepted=False,phase="physical_order",error=str(error)))
            continue
        candidates.append((ordinal,values))
    # Fixed-size ordered batches ensure deterministic accepted Sobol members
    # independent of worker completion order.
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for offset in range(0,len(candidates),12):
            batch=list(pool.map(lambda pair:screen_one(run_id,*pair),candidates[offset:offset+12]))
            for result in batch:
                attempts.append({k:v for k,v in result.items() if k!="parameters"})
                if result["accepted"] and len(accepted)<200:
                    accepted.append(dict(name=f"sobol_{result['ordinal']:04d}",parameters=result["parameters"]))
            legacy.write_json(run/"initial_feasibility_status.json",dict(status="screening",accepted=len(accepted),
                              target=200,evaluated=len([x for x in attempts if x.get("phase")!="physical_order"]),updated_at=stamp()))
            if len(accepted)==200:
                break
    pd.DataFrame(attempts).to_csv(run/"initial_feasibility_audit.csv",index=False)
    if len(accepted)!=200:
        raise RuntimeError("Unable to establish 200 feasible members in approved Sobol domain; no automatic prior change")
    ensemble=pd.DataFrame([{k.lower():v for k,v in x["parameters"].items()} for x in accepted],index=[x["name"] for x in accepted])
    legacy.write_json(run/"initial_feasibility_status.json",dict(status="completed",accepted=200,screening_used_observed_residuals=False,
                      seed=design["seed"],updated_at=stamp()))
    return ensemble


def build_case(run_id,ensemble):
    config,run=paths(run_id);design,bounds,obs=model.load_design(config/"design.json")
    work=run/"joint";work.mkdir()
    (work/"parameters.tpl").write_text("ptf ~\nname,value\n"+"".join(f"{r.name},~ {r.name.lower():<20} ~\n" for r in bounds.itertuples()),encoding="ascii")
    shutil.copy2(run/"initial_parameters.csv",work/"parameters.csv")
    (work/"objectives.ins").write_text("pif ~\n"+"".join(f"l1 w !{r.obsnme}!\n" for r in obs.itertuples()),encoding="ascii")
    pst=pyemu.Pst.from_io_files([str(work/"parameters.tpl")],[str(work/"parameters.csv")],
                              [str(work/"objectives.ins")],[str(work/"FormalObjectives.OUT")],pst_path=".")
    for row in bounds.itertuples():
        pst.parameter_data.loc[row.name.lower(),["partrans","parval1","parlbnd","parubnd","pargp"]]=[
            "none" if row.status=="active" else "fixed",row.init,row.lower,row.upper,row.pargp.lower()]
    for row in obs.itertuples():
        pst.observation_data.loc[row.obsnme,["obsval","weight","obgnme"]]=[row.observed,row.final_weight,row.family.lower()]
    pst.model_command=[f'"{sys.executable}" -X utf8 "{ROOT / "src/calibration/joint_n_objectives.py"}" --design "{config / "design.json"}" --param-csv parameters.csv']
    pst.control_data.noptmax=6
    pst.pestpp_options=dict(ies_num_reals=200,ies_include_base=True,ies_no_noise=True,ies_save_binary=False,
                           ies_bad_phi_sigma=1e300,ies_initial_lambda=10.,ies_lambda_mults=[.1,1.,10.],
                           lambda_scale_fac=[.25,.5],ies_par_en="initial_ensemble.csv",rand_seed=design["seed"],
                           ies_drop_conflicts=False,ies_pdc_sigma_distance=0.,ies_subset_size=30,
                           panther_agent_no_ping_timeout_secs=600)
    ensemble.to_csv(work/"initial_ensemble.csv")
    pst.write(str(work/"joint.pst"),version=1)
    reloaded=pyemu.Pst(str(work/"joint.pst"))
    if reloaded.npar_adj!=design["active_parameter_count"] or reloaded.nnz_obs!=492:
        raise ValueError("PST differs from approved joint design")
    manifest=dict(run_id=run_id,mode="eggplant_stage2",design_schema="formal_joint_n_v1",created_at=stamp(),
                  bounds_id=design["bounds_id"],bounds_sha256=design["bounds_sha256"],
                  design_sha256=legacy.sha(config/"design.json"),n_params=len(bounds),n_params_active=reloaded.npar_adj,
                  n_obs=492,n_obs_positive=492,noptmax=6,ies_num_reals=200,agents=6,batch_file="DSSBatch.v48",
                  harvest_var="CHPDT",scientific_status="science_pending",scenario_type="actual_trial_calibration",
                  initial_ensemble_sha256=legacy.sha(work/"initial_ensemble.csv"),
                  input_manifest_sha256=next(d["bundle_manifest_sha256"] for d in design["datasets"] if d["season_id"]=="26SP"))
    (work/"run_manifest.yaml").write_text(yaml.safe_dump(manifest,sort_keys=False),encoding="utf-8")
    return work


def finalize(run_id):
    config,run=paths(run_id);design,bounds,obs=model.load_design(config/"design.json");work=run/"joint"
    candidates=[]
    for file in work.glob("joint.*.obs.csv"):
        iteration=file.name.removeprefix("joint.").removesuffix(".obs.csv")
        parfile=work/f"joint.{iteration}.par.csv"
        if not iteration.isdigit() or not parfile.exists():continue
        outputs=pd.read_csv(file,index_col=0);pars=pd.read_csv(parfile,index_col=0)
        outputs.index=outputs.index.astype(str);pars.index=pars.index.astype(str)
        for real in outputs.index.intersection(pars.index):
            values=outputs.loc[real,obs.obsnme].to_numpy(dtype=float)
            if not np.isfinite(values).all():continue
            # Contrasts can be negative; all primitive/penalty targets cannot.
            if np.any(values[~obs.variable.isin(model.SIGNED).to_numpy()]<0):continue
            phi=float(np.square((values-obs.observed.to_numpy())*obs.final_weight.to_numpy()).sum())
            candidates.append((phi,int(iteration),real,str(parfile)))
    if not candidates:raise RuntimeError("No complete joint candidate")
    best=min(candidates,key=lambda x:(x[0],x[1],x[2]))
    chosen=pd.read_csv(best[3],index_col=0);chosen.index=chosen.index.astype(str)
    values={r.name:float(chosen.loc[best[2],r.name.lower()]) for r in bounds.itertuples()}
    model.validate_parameters(values,bounds)
    pd.DataFrame(values.items(),columns=["name","value"]).to_csv(run/"final_parameters.csv",index=False)
    comparison=model.evaluate(config/"design.json",run/"final_parameters.csv",run/"selected_deterministic")
    checked=float(np.square((comparison.simulated-comparison.observed)*comparison.final_weight).sum())
    if not np.isclose(checked,best[0],rtol=1e-6,atol=1e-7):raise ValueError("Deterministic Phi reproduction failed")
    pd.DataFrame(candidates,columns=["phi","iteration","realization","parameter_file"]).to_csv(run/"selection_audit.csv",index=False)
    legacy.write_json(run/"selection.json",dict(phi=checked,iteration=best[1],realization=best[2],validation_used=False))
    # Evaluation follows selection and never feeds back to either calibration.
    evaluation=pd.read_csv(config/"locked_evaluation_observations.csv").fillna("")
    if legacy.sha(config/"locked_evaluation_observations.csv")!=design["evaluation_catalog_sha256"]:raise ValueError("Evaluation catalog changed")
    compared=[]
    for dataset in design["datasets"]:
        treatments=[tn for role,tns in dataset["roles"].items() if role!="calibration" for tn in tns]
        if treatments:
            native=model.simulate(run/"evaluation"/dataset["season_id"],dataset,treatments,values,executable_sha256=design["dssat_executable_sha256"])
            compared.append(legacy.extract_evaluation_observations(native,evaluation[evaluation.season_id.eq(dataset["season_id"])]))
    pd.concat(compared,ignore_index=True).to_csv(run/"evaluation_comparison.csv",index=False)
    return checked


def controller():
    state=dict(status="running",sequence=IDS,completed=[],controller_pid=os.getpid(),started_at=stamp())
    legacy.write_json(PAIR/"sequence_status.json",state)
    for run_id in IDS:
        config,run=paths(run_id)
        state.update(current_run=run_id,phase="initial_feasibility_screen",updated_at=stamp())
        legacy.write_json(PAIR/"sequence_status.json",state)
        legacy.write_json(run/"pipeline_status.json",dict(status="running",phase=state["phase"],started_at=stamp(),controller_pid=os.getpid()))
        try:
            ensemble=initial_ensemble(run_id);work=build_case(run_id,ensemble)
            state.update(phase="ies",updated_at=stamp());legacy.write_json(PAIR/"sequence_status.json",state)
            legacy.write_json(run/"pipeline_status.json",dict(status="running",phase="ies",controller_pid=os.getpid(),updated_at=stamp()))
            logged([sys.executable,"-X","utf8",str(ROOT/"tools/parallel/run_parallel.py"),"--run-dir",str(work),
                    "--case","joint","--mode","ies","--n-agents","6","--wait"],run/"parallel_controller.log")
            outcome=json.loads((work/"run_status.json").read_text(encoding="utf-8"))
            if outcome.get("status")!="completed":raise RuntimeError(f"PEST process did not complete: {outcome}")
            if "analysis complete" not in (work/"joint.rec").read_text(errors="replace").lower():raise RuntimeError("PEST completion marker absent")
            # Both comparisons are user-authorized independently. An ensemble
            # retention gate failure is recorded and does not silently change
            # bounds or prevent the separate 67-parameter experiment.
            phi=finalize(run_id)
            success=dict(run_id=run_id,status="completed_pending_scientific_review",phi=phi,
                         engineering_status=outcome.get("engineering_status"),finished_at=stamp())
            legacy.write_json(run/"pipeline_status.json",success);state["completed"].append(success)
        except Exception as error:
            failure=dict(run_id=run_id,status="failed",error=str(error),failed_at=stamp())
            legacy.write_json(run/"pipeline_status.json",failure);state["completed"].append(failure)
            # Independent second case still executes on unchanged approved data.
        legacy.write_json(PAIR/"sequence_status.json",state)
    state.update(status="completed" if all(x["status"].startswith("completed") for x in state["completed"]) else "completed_with_failure",
                 phase="finished",finished_at=stamp())
    legacy.write_json(PAIR/"sequence_status.json",state)


def launch():
    state=json.loads((PAIR/"sequence_status.json").read_text(encoding="utf-8"))
    if state["status"]!="prepared":raise RuntimeError("Pair already launched")
    for run_id in IDS:model.load_design(paths(run_id)[0]/"design.json")
    with (PAIR/"controller.stdout.log").open("w",encoding="utf-8") as out,(PAIR/"controller.stderr.log").open("w",encoding="utf-8") as err:
        process=subprocess.Popen([sys.executable,"-X","utf8",str(Path(__file__).resolve()),"--controller"],cwd=ROOT,stdout=out,stderr=err,
                                 creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    legacy.write_json(PAIR/"launch_receipt.json",dict(pid=process.pid,launched_at=stamp(),sequence=IDS,user_statement=AUTH,
                      monitoring_requested=False,second_case_auto_start=True))
    print(f"Sequential joint pair launched, PID={process.pid}",flush=True)


def resume_preflight():
    """Repair only the unlaunched preparation after a native injection failure."""
    if (PAIR/"launch_receipt.json").exists() or (PAIR/"sequence_status.json").exists():
        raise RuntimeError("Cannot revise a launched/prepared sequence")
    details=[]
    for run_id in IDS:
        config,run=paths(run_id)
        path=config/"design.json";design=json.loads(path.read_text(encoding="utf-8"))
        shutil.copy2(path,run/"preflight_design_before_p_injection_repair.json")
        design["runtime_hashes"]["src/dssat/forward_joint.py"]=legacy.sha(ROOT/"src/dssat/forward_joint.py")
        design["runtime_hashes"]={rel:legacy.sha(ROOT/rel) for rel in design["runtime_hashes"]}
        design["runtime_preflight_passed"]=False
        design["preparation_repair"]="C31 phosphorus anchors now explicitly injected and independently read back; source inputs/bounds/targets unchanged"
        legacy.write_json(path,design)
        model.load_design(path,require_preflight=False)
        comparison=model.evaluate(path,run/"initial_parameters.csv",run/"preflight/baseline",preflight=True)
        phi=float(np.square((comparison.simulated-comparison.observed)*comparison.final_weight).sum())
        legacy.write_json(run/"preflight/report.json",dict(status="forward_preflight_passed",target_count=492,phi=phi,
                          active_parameter_injection_count=design["active_parameter_count"],signed_contrasts_allowed=True,no_activation_filter=True))
        design.update(runtime_preflight_passed=True,status="approved_ready")
        legacy.write_json(path,design);legacy.write_json(config/"frozen_configuration_receipt.json",dict(design_sha256=legacy.sha(path),recorded_at=stamp()))
        model.load_design(path)
        details.append(dict(run_id=run_id,n_active=design["active_parameter_count"],active_parameters=design["active_parameters"],initial_phi=phi))
    active42=set(details[0]["active_parameters"]);active67=set(details[1]["active_parameters"])
    legacy.write_json(PAIR/"approval_receipt.json",dict(user_statement=AUTH,recorded_at=stamp(),sequence=IDS,parameters=details,
                      common_targets_sha256=legacy.sha(paths(IDS[0])[0]/"calibration_observations.csv"),
                      added_in_67=sorted(active67-active42),fixed_in_67=sorted(active42-active67),second_case_uses_first_solution=False))
    legacy.write_json(PAIR/"sequence_status.json",dict(status="prepared",sequence=IDS,completed=[],user_monitoring="startup confirmation only"))
    print("Both cases passed repaired forward/injection preflight",flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--prepare",action="store_true");parser.add_argument("--launch",action="store_true");parser.add_argument("--controller",action="store_true");parser.add_argument("--resume-preflight",action="store_true")
    args=parser.parse_args()
    if args.prepare:prepare()
    elif args.resume_preflight:resume_preflight()
    elif args.launch:launch()
    elif args.controller:controller()
    else:parser.error("Select --prepare, --launch or --controller")


if __name__=="__main__":main()
