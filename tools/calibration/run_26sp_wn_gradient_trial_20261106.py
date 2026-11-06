"""Run the 2026 spring-only trial with revised W2-W1 and N2-N0 objectives."""

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
from src.common.input_manifest import verify_calibrated_input_bundle
from tools.calibration import run_both_springs_c31_trial_20261106 as dual

trial, native = dual.trial, dual.native
PARENT = dual.PARENT
DRAFT = ROOT / "workspace/runs/both_springs_wn_perturbation_20261106"
ID = "eggplant_26sp_cal25sp_val_wn_gradient_cmobmx_80x4_20261106"
RUN = ROOT / "workspace/runs" / ID
BOUNDS_ID = ID
GRADIENTS = {
    # Keep the established signed-difference extractor identifiers; the exact
    # contrast is defined by the explicit high and low treatment IDs.
    "W2_W1_FRESH_CONTRAST": ("W_FRESH_CONTRAST", "W2_W1_SIGNED_CONTRAST"),
    "N2_N0_FRESH_CONTRAST": ("N_ADJACENT_FRESH_CONTRAST", "N2_N0_SIGNED_CONTRAST"),
}


def freeze_bounds(design):
    source = Path(design["frozen_bounds"])
    b = pd.read_csv(source)
    selector = b.native_name.eq("CMOBMX")
    assert b.loc[selector, "status"].item() == "active"
    b.loc[selector, ["init", "lower", "upper", "basis"]] = [
        .022, .015, .040, "Both-spring single-factor gradient screen, 2026-11-06"]
    proposal = RUN / "approved_trial_bounds.csv"
    b.to_csv(proposal, index=False)
    frozen = source.with_name(f"{BOUNDS_ID}.csv")
    if frozen.exists():
        pd.testing.assert_frame_equal(pd.read_csv(frozen), b)
        assert frozen.with_suffix(".yaml").is_file()
    else:
        subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/freeze_bounds.py"),
                        "--proposal", str(proposal), "--crop", "eggplant", "--bounds-id", BOUNDS_ID,
                        "--notes", "2026-only W2-W1 and N2-N0 trial; CMOBMX interval from paired perturbation."],
                       cwd=ROOT, check=True)
    return frozen


def prepare():
    parent_file = PARENT / "design.json"
    design = trial.read(parent_file)
    assert trial.read(PARENT / "sealed_design.json")["sha256"] == native.sha(parent_file)
    assert trial.read(PARENT / "pipeline_status.json")["status"] == "completed"
    assert (design["members"], design["updates"], design["target_count"]) == (80, 4, 617)
    for file, digest in design["source_hashes"].items():
        assert native.sha(Path(file)) == digest, file
    trial.DATES = design["anthesis_dates"]
    index = trial.read(trial.INDEX)["bundles"]
    payloads = []
    for season, ds in design["datasets"].items():
        bundle = verify_calibrated_input_bundle(ds["path"])
        assert bundle.manifest_sha256 == ds["manifest_sha256"]
        assert index[season] == dict(bundle_id=bundle.bundle_id, manifest_sha256=bundle.manifest_sha256)
        assert ds["role"] == ("calibration" if season == "26SP" else "validation")
        target = RUN / f"{season}_inputs"
        shutil.copytree(PARENT / target.name, target)
        payloads.extend((*target.iterdir(), bundle.manifest_path))

    prior = pd.read_csv(PARENT / "calibration_observations.csv")
    removed = {"W_SIGNED_CONTRAST", "N_ADJACENT_SIGNED_CONTRAST",
               "LEAF_N_CONCENTRATION", "STEM_N_CONCENTRATION"}
    ordinary = prior.loc[~prior.family.isin(removed)].copy()
    gradients_file = DRAFT / "proposed_gradient_targets.csv"
    gradients = pd.read_csv(gradients_file).query('season_id == "26SP"').copy()
    assert len(gradients) == 7 and set(gradients.variable) == set(GRADIENTS)
    meta = pd.read_csv(Path(design["datasets"]["26SP"]["path"]) / "treatment_metadata.csv").set_index("treatment")
    fresh = prior[prior.family.eq("FINAL_FRESH_YIELD")].set_index("trno")
    for row in gradients.itertuples():
        hi, lo = meta.loc[row.trno], meta.loc[row.paired_trno]
        if row.family == "W2_W1_SIGNED_CONTRAST":
            assert (hi.water_level, lo.water_level) == ("W2", "W1") and hi.nitrogen_level == lo.nitrogen_level
        else:
            assert (hi.nitrogen_level, lo.nitrogen_level) == ("N2", "N0") and hi.water_level == lo.water_level
        a, b = fresh.loc[row.trno], fresh.loc[row.paired_trno]
        assert a.date == b.date == row.date and np.isclose(a.observed-b.observed, row.observed)
    gradients[["budget_multiplier", "final_weight"]] *= np.sqrt(2)
    gradients.to_csv(RUN / "gradient_objectives.csv", index=False)
    gradients["variable"] = gradients.variable.map({k: v[0] for k, v in GRADIENTS.items()})
    obs = pd.concat([ordinary, gradients], ignore_index=True).fillna("")
    assert len(obs) == 511 and obs.obsnme.is_unique and obs.season_id.eq("26SP").all()
    assert np.isclose(obs.final_weight.pow(2).sum(), 89)
    assert not obs.variable.isin(["ADAP", "FRUIT_N_PCT", "LEAF_N_PCT", "STEM_N_PCT"]).any()
    obs.to_csv(RUN / "calibration_observations.csv", index=False)
    priors = pd.read_csv(PARENT / "objective_policy.csv")
    zeros = priors[priors.family.isin(["LEAF_N_CONCENTRATION", "STEM_N_CONCENTRATION",
                                     "FRUIT_N_CONCENTRATION", "ANTHESIS"])].copy()
    zeros = zeros.assign(budget=0., n_targets=0, diagnostic_only=True)
    policies = priors[priors.family.isin(ordinary.family)].copy()
    for var, (_, family) in GRADIENTS.items():
        g = pd.read_csv(RUN / "gradient_objectives.csv").query("family == @family")
        old_family = "W_SIGNED_CONTRAST" if var.startswith("W2") else "N_ADJACENT_SIGNED_CONTRAST"
        row = priors[priors.family.eq(old_family)].assign(
            family=family, variable=var, n_targets=len(g), budget=g.final_weight.pow(2).sum())
        policies = pd.concat([policies, row], ignore_index=True)
    pd.concat([policies, zeros], ignore_index=True).to_csv(RUN / "objective_policy.csv", index=False)

    for name in ("locked_validation_observations.csv", "anthesis_diagnostic_observations.csv"):
        shutil.copy2(PARENT / name, RUN / name)
    diagnostics = prior.loc[prior.variable.isin(["LEAF_N_PCT", "STEM_N_PCT"])].assign(
        final_weight=0., budget_multiplier=0.)
    diagnostics.to_csv(RUN / "organ_n_diagnostic_observations.csv", index=False)
    frozen = freeze_bounds(design)
    sources = [*payloads, *RUN.glob("*.csv"), Path(__file__), parent_file,
               PARENT / "joint/joint.pst", gradients_file, frozen, frozen.with_suffix(".yaml")]
    hashes = {p: h for p, h in design["source_hashes"].items() if not Path(p).is_relative_to(PARENT)}
    hashes.update({str(p): native.sha(p) for p in sources})
    design.update(run_id=ID, parent_trial=PARENT.name, parent_design_sha256=native.sha(parent_file),
                  target_count=len(obs), objective_budget=89, target_count_by_season={"26SP": len(obs)},
                  objective_budget_by_season={"26SP": 89}, source_hashes=hashes,
                  frozen_bounds=str(frozen), bounds_id=BOUNDS_ID,
                  gradient_policy={"water": "W2-W1 within each nitrogen level", "nitrogen": "N2-N0 within each water level"},
                  diagnostic_only=["ADAP", "LEAF_N_PCT", "STEM_N_PCT", "FRUIT_N_PCT"])
    design.pop("initial_members", None)
    design.pop("initial_ensemble_base", None)
    native.write(RUN / "design.json", design)
    return design, dual.bounds(design), obs


def make_case(design, b, obs, params, outputs):
    work = RUN / "joint"
    work.mkdir()
    shutil.copy2(PARENT / "joint/parameters.tpl", work / "parameters.tpl")
    params.to_csv(work / "initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work / "parameters.csv", index_label="name")
    (work / "objectives.ins").write_text("pif ~\n" + "".join(f"l1 w !{n}!\n" for n in obs.obsnme), encoding="ascii")
    trial.write_outputs(work / "FormalObjectives.OUT", obs.obsnme, outputs.loc["base"])
    pst = pyemu.Pst(str(PARENT / "joint/joint.pst"))
    inherited = pst.observation_data
    new = pd.DataFrame({
        "obsnme": obs.obsnme, "obsval": 0., "weight": obs.final_weight, "obgnme": obs.family.str.lower(),
    }).set_index("obsnme", drop=False)
    common = new.index.intersection(inherited.index)
    np.testing.assert_allclose(new.loc[common, "weight"], inherited.loc[common, "weight"])
    pst.observation_data = new
    pst.parameter_data.loc[b.pest_name, "parval1"] = params.loc["base", b.pest_name]
    pst.parameter_data.loc[b.pest_name, "parlbnd"] = b.set_index("pest_name").lower
    pst.parameter_data.loc[b.pest_name, "parubnd"] = b.set_index("pest_name").upper
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(trial.__file__)}" --forward "{RUN}"']
    pst.write(str(work / "joint.pst"), version=1)
    actual = pyemu.Pst(str(work / "joint.pst"))
    assert (actual.npar_adj, actual.nnz_obs, actual.control_data.noptmax) == (58, 511, 4)
    assert set(actual.adj_par_names) == set(b.loc[b.status.eq("active"), "pest_name"])
    np.testing.assert_allclose(actual.observation_data.loc[obs.obsnme, "weight"], obs.final_weight)
    for column, values in [("parlbnd", b.lower), ("parubnd", b.upper)]:
        np.testing.assert_allclose(actual.parameter_data.loc[b.pest_name, column], values)
    manifest = yaml.safe_load((PARENT / "joint/run_manifest.yaml").read_text(encoding="utf-8"))
    manifest.pop("sasc_default_marker", None)
    manifest.update(run_id=ID, parent_trial=PARENT.name, bounds_id=BOUNDS_ID, n_obs=len(obs),
                    design=str(RUN / "design.json"), calibration_seasons=["26SP"], validation_seasons=["25SP"],
                    gradient_policy=design["gradient_policy"], diagnostic_only=design["diagnostic_only"])
    (work / "run_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN / "design.json").exists():
        raise FileExistsError(RUN)
    try:
        trial.status(RUN, "preparing")
        design, b, obs = prepare()
        params, outputs, base = trial.initial_ensemble(RUN, b, obs, trial.contexts(RUN, design, b)["26SP"])
        design.update(initial_members=len(params), initial_ensemble_base=base)
        native.write(RUN / "design.json", design)
        native.write(RUN / "sealed_design.json", dict(sha256=native.sha(RUN / "design.json")))
        make_case(design, b, obs, params, outputs)
        trial.status(RUN, "running", phase="pest_ies", initial_members=len(params), n_targets=len(obs))
        with (RUN / "parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/parallel/run_parallel.py"),
                "--run-dir", str(RUN / "joint"), "--case", "joint", "--mode", "ies",
                "--n-agents", str(design["workers"]), "--wait"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        assert trial.read(RUN / "joint/run_status.json")["status"] == "completed"
        trial.status(RUN, "postprocessing")
        trial.finalize(RUN, b, obs, design, params)
    except Exception as exc:
        phase = trial.read(RUN / "pipeline_status.json")["status"]
        trial.status(RUN, "failed", phase=phase, error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
