"""Repeat 80x4 with original anthesis and C31 pre-tightening bounds."""
from pathlib import Path
import shutil
import subprocess
import sys

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.input_manifest import verify_calibrated_input_bundle
from tools.calibration import restart_dual_morris98_trial_ranges_20261105 as prior
from tools.calibration.grid_dual_morris98_bounds_20261105 import round_field

trial = prior.trial
INITIALIZE_PRIOR_WORKER = prior.initialize
PARENT = prior.RUN
ID = "eggplant_26sp_cal25sp_val_dual_morris98_80x4_c31initial_20261106"
RUN = ROOT/"workspace/runs"/ID
C31 = ROOT/"workspace/runs/full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927"
DATES = {"25SP":"2025-04-22","26SP":"2026-04-20"}


def freeze_bounds(parent):
    manifest = yaml.safe_load((C31/"run_manifest.yaml").read_text(encoding="utf-8"))
    source = Path(manifest["bounds_csv"])
    assert trial.native.sha(source)==manifest["bounds_sha256"]
    history = pd.read_csv(source).assign(key=lambda x:x.name.str.lower()).set_index("key")
    b = pd.read_csv(parent["frozen_bounds"])
    rows = []
    for i,p in b[b.status.eq("active")].iterrows():
        key = p.pest_name
        lo, hi, init = p.lower,p.upper,p.init
        old = history.loc[key] if key in history.index else None
        if old is None or old.status!="active" or old.upper<=old.lower:
            basis = "Current interval; no adjustable C31 interval"
        else:
            lo,hi = old.lower,old.upper
            basis = "C31 frozen pre-tightening interval"
        if p.native_name=="PROSHI":
            lo = max(lo, float(b.loc[b.native_name.eq("PROSHG"),"init"].item()))
            basis = "C31 interval clipped by fixed PROSHG"
        if not lo<=init<=hi:
            init = round_field((lo+hi)/2)
        assert lo<=init<=hi
        b.loc[i,["init","lower","upper","basis"]] = [init,lo,hi,basis]
        rows.append(dict(parameter=p.native_name,previous_lower=p.lower,previous_upper=p.upper,
                         c31_status=old.status if old is not None else "not_listed",
                         c31_lower=old.lower if old is not None else None,
                         c31_upper=old.upper if old is not None else None,
                         lower=lo,upper=hi,init=init,basis=basis))
    audit = pd.DataFrame(rows)
    assert len(audit)==58 and audit.basis.str.startswith("C31").sum()==47
    audit.to_csv(RUN/"range_source_audit.csv",index=False)
    b.to_csv(RUN/"approved_trial_bounds.csv",index=False)
    subprocess.run([sys.executable,"-X","utf8",str(ROOT/"tools/freeze_bounds.py"),
                    "--proposal",str(RUN/"approved_trial_bounds.csv"),"--crop","eggplant",
                    "--bounds-id",ID,"--notes",
                    "User approved 80x4, original ADAT and SASC; use C31 frozen ranges where compatible"],
                   cwd=ROOT,check=True)
    return source.with_name(ID+".csv"),source


def prepare():
    path = PARENT/"design.json"
    parent = trial.read(path)
    assert trial.read(PARENT/"sealed_design.json")["sha256"]==trial.native.sha(path)
    assert (parent["members"],parent["updates"],parent["target_count"],parent["SASC"])==(80,4,629,-99)
    for name,digest in parent["source_hashes"].items():
        assert trial.native.sha(Path(name))==digest, name
    assert parent["SLPF"]=={"25SP":.90,"26SP":.89}
    datasets, catalogs, revisions = {}, {}, {}
    for season,ds in parent["datasets"].items():
        revised = verify_calibrated_input_bundle(ds["path"])
        assert revised.manifest_sha256==ds["manifest_sha256"]
        revision = revised.raw["anthesis_revision"]
        source = revised.directory.with_name(revision["parent_bundle"])
        original = verify_calibrated_input_bundle(source)
        assert original.manifest_sha256==revision["parent_manifest_sha256"]
        datasets[season] = ds | dict(path=str(source),bundle_id=original.bundle_id,
                                     manifest_sha256=original.manifest_sha256)
        catalogs[season] = trial.observation_catalog(source,season)
        trial.native.model_payload(source,RUN/f"{season}_inputs",parent["SLPF"][season])
        old_payload = PARENT/f"{season}_inputs"
        new_payload = RUN/f"{season}_inputs"
        changed = [p.name for p in old_payload.iterdir() if p.read_bytes()!=(new_payload/p.name).read_bytes()]
        assert len(changed)==1 and changed[0].endswith(".TMA"),changed
        revisions[season] = dict(bundle=original.bundle_id,restored_ADAT=revision["old_adat"],date=DATES[season])
    policy = pd.read_csv(PARENT/"objective_policy.csv")
    obs = trial.objectives(catalogs["26SP"],Path(datasets["26SP"]["path"]),policy)
    old_obs = pd.read_csv(PARENT/"calibration_observations.csv").fillna("")
    pd.testing.assert_frame_equal(obs.loc[~obs.variable.eq("ADAP")].fillna(""),
                                  old_obs.loc[~old_obs.variable.eq("ADAP")],check_dtype=False)
    assert obs.loc[obs.variable.eq("ADAP"),"observed"].eq(37).all()
    val = catalogs["25SP"]
    assert val.loc[val.variable.eq("ADAP"),"observed"].eq(37).all()
    obs.to_csv(RUN/"calibration_observations.csv",index=False)
    val.to_csv(RUN/"locked_validation_observations.csv",index=False)
    shutil.copy2(PARENT/"objective_policy.csv",RUN/"objective_policy.csv")
    frozen,c31 = freeze_bounds(parent)
    drop = {*prior.OBS_FILES,"range_changes.csv"}
    hashes = {p:h for p,h in parent["source_hashes"].items()
              if not Path(p).is_relative_to(PARENT) and Path(p)!=Path(parent["frozen_bounds"])}
    assert all(not Path(p).is_relative_to(PARENT) or Path(p).name in drop
               or Path(p).parent.name in {"25SP_inputs","26SP_inputs"} for p in parent["source_hashes"])
    files = [frozen,c31,Path(__file__),Path(round_field.__code__.co_filename),RUN/"range_source_audit.csv"]
    files.extend(RUN/name for name in prior.OBS_FILES)
    for season in datasets:
        files.extend((RUN/f"{season}_inputs").iterdir())
    hashes.update({str(f):trial.native.sha(f) for f in files})
    design = parent | dict(datasets=datasets,parent_trial=PARENT.name,
        parent_design_sha256=trial.native.sha(path),anthesis_dates=DATES,anthesis_dap={"25SP":37,"26SP":37},
        original_input_revision=revisions,SASC=-99,bounds_id=ID,frozen_bounds=str(frozen),
        c31_initial_bounds_source=str(c31),source_hashes=hashes)
    for key in ("range_changes","initial_members","initial_ensemble_base"):
        design.pop(key,None)
    trial.native.write(RUN/"design.json",design)
    return design


def initialize(design):
    prior.RUN = RUN
    INITIALIZE_PRIOR_WORKER(design)


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN/"design.json").exists() or (RUN/"joint").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    try:
        trial.DATES = DATES
        trial.status(RUN,"preparing")
        design = prepare()
        prior.RUN = RUN
        b,obs = prior.load_inputs(design)
        try:
            prior.initialize = initialize
            params,outputs,base = prior.preflight(design,b,obs)
        finally:
            prior.initialize = INITIALIZE_PRIOR_WORKER
        design.update(initial_members=len(params),initial_ensemble_base=base)
        trial.native.write(RUN/"design.json",design)
        trial.native.write(RUN/"sealed_design.json",dict(sha256=trial.native.sha(RUN/"design.json")))
        trial.make_case(RUN,b,obs,params,outputs)
        manifest_path = RUN/"joint/run_manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest.update(run_id=ID,bounds_id=ID,parent_trial=PARENT.name,anthesis_dates=DATES,
                        sasc_default_marker=-99,c31_initial_bounds_source=design["c31_initial_bounds_source"])
        manifest_path.write_text(yaml.safe_dump(manifest,sort_keys=False),encoding="utf-8")
        trial.status(RUN,"running",phase="pest_ies",initial_members=len(params))
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
