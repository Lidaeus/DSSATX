"""Run the second 80x4 trial with the four user-approved range changes."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import subprocess
import sys

import pandas as pd
import yaml
from scipy.stats import qmc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.input_manifest import verify_calibrated_input_bundle
from tools.calibration import run_dual_morris98_trial_20261105 as trial

PARENT = ROOT / "workspace/runs" / trial.ID
ID = "eggplant_26sp_cal25sp_val_dual_morris98_80x4_range2_20261105"
RUN = ROOT / "workspace/runs" / ID
RANGES = {"XFPHT": (25., 60.), "XFINT": (.12, .40),
          "PROLFI": (.27, .36), "PROLFG": (.15, .26)}
OBS_FILES = ("calibration_observations.csv", "locked_validation_observations.csv", "objective_policy.csv")


def prepare():
    old_design = PARENT / "design.json"
    parent = trial.read(old_design)
    assert trial.read(PARENT / "sealed_design.json")["sha256"] == trial.native.sha(old_design)
    assert trial.read(PARENT / "pipeline_status.json")["status"] == "completed"
    assert (parent["members"], parent["updates"], parent["seed"]) == (trial.MEMBERS, trial.UPDATES, trial.SEED)
    hashes = parent["source_hashes"]
    for path, digest in hashes.items():
        assert trial.native.sha(Path(path)) == digest, path
    current = trial.read(trial.INDEX)["bundles"]
    for season, ds in parent["datasets"].items():
        assert current[season]["bundle_id"] == ds["bundle_id"]
        assert current[season]["manifest_sha256"] == ds["manifest_sha256"]
        assert verify_calibrated_input_bundle(ds["path"]).manifest_sha256 == ds["manifest_sha256"]
    for name in OBS_FILES:
        shutil.copy2(PARENT / name, RUN / name)
    for season in parent["datasets"]:
        shutil.copytree(PARENT / f"{season}_inputs", RUN / f"{season}_inputs")

    old_bounds = Path(parent["frozen_bounds"])
    b = pd.read_csv(old_bounds).set_index("native_name", drop=False)
    changes = []
    for name, (lo, hi) in RANGES.items():
        row = b.loc[name]
        assert row.status == "active" and lo <= row.init <= hi
        changes.append(dict(parameter=name, prior_lower=row.lower, prior_upper=row.upper,
                            lower=lo, upper=hi, init=row.init))
        b.loc[name, ["lower", "upper", "basis"]] = [lo, hi, "User-approved range update after paired grid"]
    assert b.loc["XMAGE","upper"] < b.loc["XFPHT","lower"]
    assert b.loc["PROLFG","upper"] < b.loc["PROLFI","lower"]
    proposal = RUN / "approved_trial_bounds.csv"
    b.to_csv(proposal, index=False)
    pd.DataFrame(changes).to_csv(RUN / "range_changes.csv", index=False)
    subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/freeze_bounds.py"),
                    "--proposal", str(proposal), "--crop", "eggplant", "--bounds-id", ID,
                    "--notes", "User authorized XFPHT 25-60; XFINT .12-.40; PROLFI .27-.36; PROLFG .15-.26"],
                   cwd=ROOT, check=True)
    frozen = old_bounds.with_name(ID + ".csv")
    sealed = {}
    for path,digest in hashes.items():
        src = Path(path)
        if src == old_bounds:
            continue
        if src.is_relative_to(PARENT):
            src = RUN / src.relative_to(PARENT)
            assert trial.native.sha(src) == digest
        sealed[str(src)] = digest
    for file in (frozen, Path(__file__), RUN/"range_changes.csv"):
        sealed[str(file)] = trial.native.sha(file)
    design = parent | dict(bounds_id=ID, frozen_bounds=str(frozen), parent_trial=PARENT.name,
                           parent_design_sha256=trial.native.sha(old_design), range_changes=changes,
                           source_hashes=sealed)
    design.pop("initial_members")
    design.pop("initial_ensemble_base")
    trial.native.write(RUN/"design.json", design)
    return design


def load_inputs(design):
    b = pd.read_csv(design["frozen_bounds"]).rename(columns={"name":"registry_name","native_name":"name"})
    obs = pd.read_csv(RUN/"calibration_observations.csv").fillna("")
    return b, obs


def initialize(design):
    global BOUNDS, OBS, CONTEXT
    BOUNDS, OBS = load_inputs(design)
    CONTEXT = trial.contexts(RUN,design,BOUNDS)["26SP"]


def screen(task):
    name, vector = task
    try:
        values = trial.values_for(BOUNDS,vector)
        with TemporaryDirectory(prefix=name+"_",dir=RUN/"initial_feasibility") as tmp:
            work = Path(tmp)
            try:
                result = trial.evaluate(RUN,work,CONTEXT,values,OBS)
            except (ValueError, KeyError, AssertionError, trial.native.NativeRunError):
                shutil.copytree(work,RUN/"initial_feasibility"/name)
                raise
        dates = result.loc[result.variable.eq("ADAP"),"simulated"]
        return dict(candidate=name,accepted=True,values=values,output=result.pest_output.to_numpy(),
                    phi=float(result.phi_contribution.sum()),anthesis_min=float(dates.min()),anthesis_max=float(dates.max()))
    except (ValueError, KeyError, AssertionError, trial.native.NativeRunError) as exc:
        return dict(candidate=name,accepted=False,reason=f"{type(exc).__name__}: {exc}")


def preflight(design,b,obs):
    center = dict(zip(b.name,b.init))
    active = b[b.status.eq("active")]
    points = qmc.Sobol(len(active),scramble=True,seed=trial.SEED).random_base2(9)
    candidates = [("center",center)] + [
        (f"global_{i:04d}",center | dict(zip(active.name,active.lower+p*(active.upper-active.lower))))
        for i,p in enumerate(points)
    ]
    (RUN/"initial_feasibility").mkdir()
    accepted,audit,seen = [],[],set()
    with ProcessPoolExecutor(max_workers=trial.WORKERS,initializer=initialize,initargs=(design,)) as pool:
        for start in range(0,len(candidates),trial.WORKERS):
            for row in pool.map(screen,candidates[start:start+trial.WORKERS]):
                if row["accepted"]:
                    vector = tuple(row["values"].values())
                    if vector in seen:
                        row.update(accepted=False,reason="Duplicate serialized vector")
                    elif len(accepted)==trial.MEMBERS:
                        row.update(accepted=False,reason="Eligible after ensemble filled")
                    else:
                        seen.add(vector)
                        accepted.append(row)
                audit.append({k:v for k,v in row.items() if k not in {"values","output"}})
            pd.DataFrame(audit).to_csv(RUN/"initial_feasibility_audit.csv",index=False)
            trial.status(RUN,"preflight",accepted=len(accepted),attempted=len(audit))
            if len(accepted)==trial.MEMBERS:
                break
            if len(audit)>=18 and not accepted and len({row["reason"] for row in audit})==1:
                raise RuntimeError(audit[0]["reason"])
    if len(accepted)!=trial.MEMBERS:
        raise RuntimeError(f"Only {len(accepted)}/{trial.MEMBERS} feasible members")
    names = ["base"]+[row["candidate"] for row in accepted[1:]]
    params = pd.DataFrame([row["values"] for row in accepted],index=names).rename(
        columns=dict(zip(b.name,b.pest_name)))
    outputs = pd.DataFrame([row["output"] for row in accepted],index=names,columns=obs.obsnme)
    return params,outputs,accepted[0]["candidate"]


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN/"design.json").exists() or (RUN/"joint").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    try:
        trial.status(RUN,"preparing")
        design = prepare()
        b,obs = load_inputs(design)
        params,outputs,base = preflight(design,b,obs)
        design.update(initial_members=len(params),initial_ensemble_base=base)
        trial.native.write(RUN/"design.json",design)
        trial.native.write(RUN/"sealed_design.json",dict(sha256=trial.native.sha(RUN/"design.json")))
        trial.make_case(RUN,b,obs,params,outputs)
        manifest_path = RUN/"joint/run_manifest.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest.update(run_id=ID,bounds_id=ID,parent_trial=PARENT.name)
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
