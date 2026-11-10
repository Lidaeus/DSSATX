"""Replay the exact preflight ensemble with explicit Panther timeout controls."""

from pathlib import Path
import re
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
from tools.calibration import run_spring56_eco_columns_removed_200x4_20261107 as original

trial, native, gradient = original.trial, original.native, original.gradient
SOURCE = original.RUN
RUN = SOURCE.with_name("eggplant_final_springs_56_eco_columns_removed_timeoutfix_200x4_8agents_20261108")
TIMEOUT_OPTIONS = {"overdue_giveup_fac": "100", "overdue_resched_fac": "100", "overdue_giveup_minutes": "10"}


def prepare():
    source_design = SOURCE / "design.json"
    design = trial.read(source_design)
    assert trial.read(SOURCE / "sealed_design.json")["sha256"] == native.sha(source_design)
    assert trial.read(SOURCE / "pipeline_status.json")["status"] == "failed"
    for name, digest in design["source_hashes"].items():
        assert native.sha(Path(name)) == digest, name

    copied = []
    for season, dataset in design["datasets"].items():
        assert verify_manifest_integrity(dataset["path"]).manifest_sha256 == dataset["manifest_sha256"]
        payload = RUN / f"{season}_inputs"
        shutil.copytree(SOURCE / payload.name, payload)
        copied.extend(payload.iterdir())
    for name in ("calibration_observations.csv", "locked_validation_observations.csv", "objective_policy.csv",
                 "calibration_diagnostic_observations.csv", "fixed_input_audit.csv", "initial_feasibility_audit.csv"):
        shutil.copy2(SOURCE / name, RUN / name)
        copied.append(RUN / name)

    work = RUN / "joint"
    work.mkdir()
    for name in ("parameters.tpl", "parameters.csv", "objectives.ins", "FormalObjectives.OUT", "initial_ensemble.csv"):
        shutil.copy2(SOURCE / "joint" / name, work / name)
        copied.append(work / name)
    obs = pd.read_csv(RUN / "calibration_observations.csv").fillna("")
    bounds = pd.read_csv(design["frozen_bounds"]).rename(columns={"name": "registry_name", "native_name": "name"})
    params = pd.read_csv(work / "initial_ensemble.csv", index_col=0)
    base = pd.read_csv(work / "FormalObjectives.OUT", sep=r"\s+", names=["obsnme", "value"])
    assert params.shape == (200, 124) and params.index.is_unique and set(params.columns) == set(bounds.pest_name)
    assert base.obsnme.tolist() == obs.obsnme.tolist()
    assert np.isclose(np.square(base.value * obs.final_weight).sum(), design["initial_base_phi"], rtol=1e-9)

    old_pst = SOURCE / "joint/joint.pst"
    pst = pyemu.Pst(str(old_pst))
    old_options = pst.pestpp_options.copy()
    pst.pestpp_options.update(TIMEOUT_OPTIONS)
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(original.__file__)}" --forward "{RUN}"']
    pst.write(str(work / "joint.pst"), version=1)
    actual = pyemu.Pst(str(work / "joint.pst"))
    prior = pyemu.Pst(str(old_pst))
    assert (actual.npar_adj, actual.nnz_obs, actual.control_data.noptmax) == (56, 511, 4)
    assert actual.pestpp_options == old_options | TIMEOUT_OPTIONS
    pd.testing.assert_frame_equal(actual.parameter_data, prior.parameter_data)
    pd.testing.assert_frame_equal(actual.observation_data, prior.observation_data)

    # parameters.csv and FormalObjectives.OUT are working files and may be
    # rewritten by the manager or a worker. Seal the inputs that stay static.
    stable = [path for path in copied if path.name not in {"parameters.csv", "FormalObjectives.OUT"}]
    stable.extend((Path(__file__), source_design, old_pst, work / "joint.pst"))
    design["source_hashes"].update({str(path): native.sha(path) for path in stable})
    design.update(run_id=RUN.name, parent_trial=SOURCE.name, parent_design_sha256=native.sha(source_design),
                  timeout_options=TIMEOUT_OPTIONS, initial_ensemble_source=str(SOURCE / "joint/initial_ensemble.csv"))
    native.write(RUN / "design.json", design)
    native.write(RUN / "sealed_design.json", {"sha256": native.sha(RUN / "design.json")})
    manifest = yaml.safe_load((SOURCE / "joint/run_manifest.yaml").read_text(encoding="utf-8"))
    manifest.update(run_id=RUN.name, parent_trial=SOURCE.name, design=str(RUN / "design.json"),
                    timeout_options=TIMEOUT_OPTIONS, initial_ensemble_source=design["initial_ensemble_source"])
    (work / "run_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return design, bounds, obs, params


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN / "pipeline_status.json").exists():
        raise FileExistsError(f"Existing retry {RUN}")
    trial.MEMBERS, trial.UPDATES, trial.WORKERS = original.MEMBERS, original.UPDATES, original.WORKERS
    gradient.sa98_joint40.SIGNED.add(gradient.NITROGEN_OPERATOR)
    original.configure_runner()
    try:
        trial.status(RUN, "preparing")
        design, bounds, obs, params = prepare()
        trial.DATES = design["anthesis_dates"]
        trial.status(RUN, "running", phase="pest_ies", initial_members=len(params), agents=original.WORKERS,
                     timeout_options=TIMEOUT_OPTIONS)
        with (RUN / "parallel_controller.log").open("wb") as log:
            subprocess.run([
                sys.executable, "-X", "utf8", str(ROOT / "tools/parallel/run_parallel.py"),
                "--run-dir", str(RUN / "joint"), "--case", "joint", "--mode", "ies",
                "--n-agents", str(original.WORKERS), "--wait",
            ], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if trial.read(RUN / "joint/run_status.json")["status"] != "completed":
            raise RuntimeError("PEST++ did not complete")
        rec = (RUN / "joint/joint.rec").read_text(errors="replace")
        for key, value in TIMEOUT_OPTIONS.items():
            match = re.search(rf"(?m)^{key}:\s*([\deE.+-]+)", rec)
            if not match or float(match[1]) != float(value) or f"resetting {key}" in rec:
                raise RuntimeError(f"PEST++ did not honor {key}")
        for dataset in design["datasets"].values():
            assert verify_manifest_integrity(dataset["path"]).manifest_sha256 == dataset["manifest_sha256"]
        trial.status(RUN, "postprocessing")
        trial.finalize(RUN, bounds, obs, design, params)
        gradient.RUN = RUN
        gradient.save_gradient_diagnostics(design)
    except Exception as exc:
        state = trial.read(RUN / "pipeline_status.json")
        trial.status(RUN, "failed", phase=state["status"], error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
