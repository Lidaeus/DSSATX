"""Repeat the 80x4 trial with a 0.70 stable-carbon ratio in both seasons."""
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
from tools.reporting.scan_25sp_sasc_20261105 import write_sasc

trial = prior.trial
INITIALIZE_PRIOR_WORKER = prior.initialize
PARENT = prior.RUN
ID = "eggplant_26sp_cal25sp_val_dual_morris98_80x4_sasc70_20261105"
RUN = ROOT/"workspace/runs"/ID
SASC_RATIO = .70


def prepare():
    path = PARENT/"design.json"
    parent = trial.read(path)
    assert trial.read(PARENT/"sealed_design.json")["sha256"]==trial.native.sha(path)
    assert trial.read(PARENT/"pipeline_status.json")["status"]=="completed"
    assert parent["SASC"]==-99 and parent["SLPF"]=={"25SP":.90,"26SP":.89}
    assert (parent["members"],parent["updates"],parent["target_count"])==(80,4,629)
    for name,digest in parent["source_hashes"].items():
        assert trial.native.sha(Path(name))==digest, name
    hashes = dict(parent["source_hashes"])
    current = trial.read(trial.INDEX)["bundles"]
    rows, payloads = [], {}
    for name in prior.OBS_FILES:
        src = PARENT/name
        shutil.copy2(src,RUN/name)
        hashes[str(RUN/name)] = hashes.pop(str(src))
        assert trial.native.sha(RUN/name)==hashes[str(RUN/name)]
    for season, ds in parent["datasets"].items():
        assert current[season]["bundle_id"]==ds["bundle_id"]
        assert current[season]["manifest_sha256"]==ds["manifest_sha256"]
        assert verify_calibrated_input_bundle(ds["path"]).manifest_sha256==ds["manifest_sha256"]
        src, dst = PARENT/f"{season}_inputs", RUN/f"{season}_inputs"
        shutil.copytree(src,dst)
        filex, = src.glob("*.TMX")
        expected_layers = 10 * len(ds["treatments"])
        layers = write_sasc(filex,dst/filex.name,SASC_RATIO,expected_layers=expected_layers)
        assert {row["trno"] for row in layers}==set(ds["treatments"])
        rows.extend(dict(season=season,SASC_ratio=SASC_RATIO,**row) for row in layers)
        for f in src.iterdir():
            old_hash = hashes.pop(str(f))
            new_hash = trial.native.sha(dst/f.name)
            if f!=filex:
                assert new_hash==old_hash,f
            hashes[str(dst/f.name)] = new_hash
        payloads[season] = dict(layers=expected_layers,input_tmx_sha256=trial.native.sha(filex),
                                working_tmx_sha256=trial.native.sha(dst/filex.name))
    audit = RUN/"sasc_layer_audit.csv"
    pd.DataFrame(rows).to_csv(audit,index=False)
    for file in (audit, Path(__file__), ROOT/"tools/reporting/scan_25sp_sasc_20261105.py"):
        hashes[str(file)] = trial.native.sha(file)
    design = parent | dict(parent_trial=PARENT.name,parent_design_sha256=trial.native.sha(path),
        SASC=SASC_RATIO,SASC_ratio_by_season={s:SASC_RATIO for s in payloads},
        SASC_rule="SASC = SAOC * ratio, written to two decimals",SASC_payload_audit=payloads,source_hashes=hashes)
    design.pop("initial_members")
    design.pop("initial_ensemble_base")
    trial.native.write(RUN/"design.json",design)
    return design


def initialize(design):
    # Spawned Windows workers need the new run path before the shared
    # preflight evaluator opens observations and its writable work directory.
    prior.RUN = RUN
    INITIALIZE_PRIOR_WORKER(design)


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN/"design.json").exists() or (RUN/"joint").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    try:
        trial.status(RUN,"preparing")
        design = prepare()
        prior.RUN = RUN
        b,obs = prior.load_inputs(design)
        # Reuse the same Sobol stream, constraints, and complete-output screen.
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
        manifest.update(run_id=ID,bounds_id=design["bounds_id"],parent_trial=PARENT.name,
                        sasc_ratio_by_season=design["SASC_ratio_by_season"])
        manifest_path.write_text(yaml.safe_dump(manifest,sort_keys=False),encoding="utf-8")
        trial.status(RUN,"running",phase="pest_ies",initial_members=len(params))
        with (RUN/"parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable,"-X","utf8",str(ROOT/"tools/parallel/run_parallel.py"),
                "--run-dir",str(RUN/"joint"),"--case","joint","--mode","ies",
                "--n-agents",str(trial.WORKERS),"--wait"],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
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
