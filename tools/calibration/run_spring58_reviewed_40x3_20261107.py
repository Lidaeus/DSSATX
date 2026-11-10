"""Run the approved 58-parameter bounds using the previous trial's locked inputs."""

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
from tools.calibration import run_water_stress_expansion_40x3_20261107 as previous

trial, native, gradient = previous.trial, previous.native, previous.gradient
PARENT = previous.RUN
ID = "eggplant_final_springs_58_reviewed_bounds_40x3_8agents_20261107"
RUN = ROOT / "workspace/runs" / ID
PROPOSAL = ROOT / "data/parameter_registry/bounds_proposals/eggplant/eggplant_spring58_water_stress_40x3_review_20261107.csv"
MEMBERS, UPDATES, WORKERS = 40, 3, 8


def prepare():
    parent_path = PARENT / "design.json"
    parent = trial.read(parent_path)
    assert trial.read(PARENT / "sealed_design.json")["sha256"] == native.sha(parent_path)
    assert trial.read(PARENT / "pipeline_status.json")["status"] == "completed"
    for path, digest in parent["source_hashes"].items():
        assert native.sha(Path(path)) == digest, path
    for season, dataset in parent["datasets"].items():
        assert verify_manifest_integrity(dataset["path"]).manifest_sha256 == dataset["manifest_sha256"]
        shutil.copytree(PARENT / f"{season}_inputs", RUN / f"{season}_inputs")

    proposal_copy = RUN / "approved_trial_bounds.csv"
    shutil.copy2(PROPOSAL, proposal_copy)
    subprocess.run([
        sys.executable, "-X", "utf8", str(ROOT / "tools/freeze_bounds.py"),
        "--proposal", str(proposal_copy), "--crop", "eggplant", "--bounds-id", ID,
        "--notes", "User approved the reviewed spring 58-parameter bounds and a 40x3 trial.",
    ], cwd=ROOT, check=True)
    frozen = Path(parent["frozen_bounds"]).with_name(ID + ".csv")
    bounds = pd.read_csv(frozen).rename(columns={"name": "registry_name", "native_name": "name"})
    old = pd.read_csv(parent["frozen_bounds"]).set_index("native_name")
    active = bounds[bounds.status.eq("active")].set_index("name")
    assert set(active.index) == set(parent["active_parameters"]) and len(active) == 58
    assert bounds.loc[bounds.status.eq("fixed"), "init"].tolist() == old.loc[old.status.eq("fixed"), "init"].tolist()
    changes = active[["lower", "upper", "init"]].join(
        old[["lower", "upper"]].rename(columns={"lower": "previous_lower", "upper": "previous_upper"})
    )
    changes = changes[changes.lower.ne(changes.previous_lower) | changes.upper.ne(changes.previous_upper)]
    assert len(changes) == 11
    changes.to_csv(RUN / "range_changes.csv", index_label="parameter")

    best = PARENT / "best_calibration_parameters.csv"
    selection = trial.read(PARENT / "selection.json")
    assert native.sha(best) == selection["parameters_sha256"]
    assert trial.values_for(bounds, dict(zip(bounds.name, bounds.init))) == pd.read_csv(best).set_index("name").value.to_dict()
    files = ["calibration_observations.csv", "objective_policy.csv", "locked_validation_observations.csv",
             "calibration_diagnostic_observations.csv", "fixed_input_audit.csv"]
    for name in files:
        shutil.copy2(PARENT / name, RUN / name)
    obs = pd.read_csv(RUN / "calibration_observations.csv").fillna("")
    assert len(obs) == 511 and np.isclose(obs.final_weight.pow(2).sum(), 97)

    sealed = [Path(__file__), PROPOSAL, proposal_copy, frozen, parent_path, best,
              PARENT / "joint/joint.pst", RUN / "range_changes.csv", *(RUN / name for name in files)]
    for season in parent["datasets"]:
        sealed.extend((RUN / f"{season}_inputs").iterdir())
    hashes = {p: h for p, h in parent["source_hashes"].items() if not Path(p).is_relative_to(PARENT)}
    hashes.update({str(path): native.sha(path) for path in sealed})
    design = parent | dict(
        run_id=ID, parent_trial=PARENT.name, parent_design_sha256=native.sha(parent_path),
        members=MEMBERS, updates=UPDATES, workers=WORKERS, bounds_id=ID, frozen_bounds=str(frozen),
        bounds_proposal=str(PROPOSAL), exploratory_range_changes=changes.index.tolist(), source_hashes=hashes,
        initial_parameter_source=str(best), proshi_feasibility=parent["proshi_feasibility"] | {"nominal_upper": .190},
    )
    native.write(RUN / "design.json", design)
    return design, bounds, obs, selection["phi"]


def make_case(design, bounds, obs, params, outputs):
    work = RUN / "joint"
    work.mkdir()
    for name in ("parameters.tpl", "objectives.ins"):
        shutil.copy2(PARENT / "joint" / name, work / name)
    params.to_csv(work / "initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work / "parameters.csv", index_label="name")
    trial.write_outputs(work / "FormalObjectives.OUT", obs.obsnme, outputs.loc["base"])
    pst = pyemu.Pst(str(PARENT / "joint/joint.pst"))
    assert pst.observation_data.obsnme.tolist() == obs.obsnme.tolist()
    for row in bounds.itertuples():
        pst.parameter_data.loc[row.pest_name, ["parval1", "parlbnd", "parubnd"]] = [
            params.loc["base", row.pest_name], row.lower, row.upper
        ]
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(previous.__file__)}" --forward "{RUN}"']
    pst.write(str(work / "joint.pst"), version=1)
    actual = pyemu.Pst(str(work / "joint.pst"))
    assert (actual.npar_adj, actual.nnz_obs, actual.control_data.noptmax) == (58, 511, UPDATES)
    assert int(actual.pestpp_options["ies_num_reals"]) == MEMBERS
    assert actual.pestpp_options == pst.pestpp_options
    np.testing.assert_allclose(actual.observation_data.weight, obs.final_weight, rtol=1e-8)
    np.testing.assert_allclose(
        actual.parameter_data.loc[bounds.pest_name, ["parlbnd", "parubnd"]], bounds[["lower", "upper"]], rtol=1e-9
    )
    manifest = yaml.safe_load((PARENT / "joint/run_manifest.yaml").read_text(encoding="utf8"))
    manifest.update(run_id=ID, parent_trial=PARENT.name, design=str(RUN / "design.json"), bounds_id=ID,
                    proshi_feasibility=design["proshi_feasibility"], bounds_proposal=str(PROPOSAL))
    (work / "run_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf8")


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN / "pipeline_status.json").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    trial.MEMBERS, trial.UPDATES, trial.WORKERS = MEMBERS, UPDATES, WORKERS
    gradient.sa98_joint40.SIGNED.add(gradient.NITROGEN_OPERATOR)
    try:
        trial.status(RUN, "preparing")
        design, bounds, obs, parent_phi = prepare()
        trial.DATES = design["anthesis_dates"]
        ctx = trial.contexts(RUN, design, bounds)["26SP"]
        params, outputs, base = trial.initial_ensemble(RUN, bounds, obs, ctx)
        base_phi = float(np.square(outputs.loc["base"].to_numpy() * obs.final_weight.to_numpy()).sum())
        assert base == "center" and np.isclose(base_phi, parent_phi, rtol=1e-6), (base, base_phi, parent_phi)
        design.update(initial_members=len(params), initial_ensemble_base=base, initial_base_phi=base_phi)
        native.write(RUN / "design.json", design)
        native.write(RUN / "sealed_design.json", dict(sha256=native.sha(RUN / "design.json")))
        make_case(design, bounds, obs, params, outputs)
        trial.status(RUN, "running", phase="pest_ies", initial_members=len(params), n_targets=len(obs),
                     agents=WORKERS, initial_base_phi=base_phi)
        with (RUN / "parallel_controller.log").open("wb") as log:
            subprocess.run([
                sys.executable, "-X", "utf8", str(ROOT / "tools/parallel/run_parallel.py"),
                "--run-dir", str(RUN / "joint"), "--case", "joint", "--mode", "ies",
                "--n-agents", str(WORKERS), "--wait",
            ], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if trial.read(RUN / "joint/run_status.json")["status"] != "completed":
            raise RuntimeError("PEST++ did not complete")
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
