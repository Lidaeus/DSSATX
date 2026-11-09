"""Fit the final 2026 spring bundle with W2−W1 and N2−N0 yield objectives."""
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
from src.calibration import sa98_joint40
from src.common.input_manifest import verify_calibrated_input_bundle, verify_manifest_integrity
from tools.calibration import run_cold_spring_c31_trial_20261106 as previous

trial = previous.trial
native = trial.native
PARENT = previous.RUN
ID = "eggplant_26sp_final_cal25sp_old_val_c31pst_gradient_80x4_20261106"
RUN = ROOT / "workspace/runs" / ID
CALIBRATION = ROOT / "data/user/experiments/xxql2601_final_20261105"
WATER = "W2_W1_SIGNED_CONTRAST"
NITROGEN = "N2_N0_SIGNED_CONTRAST"
NITROGEN_OPERATOR = "N2_N0_FRESH_CONTRAST"


def gradient_pairs(bundle):
    metadata = pd.read_csv(bundle / "treatment_metadata.csv")
    mapping = metadata.pivot(index="water_level", columns="nitrogen_level", values="treatment")
    assert mapping.columns.tolist() == ["N0", "N1", "N2", "N3"] and not mapping.isna().any().any()
    return {
        WATER: [(n, mapping.loc["W2", n], mapping.loc["W1", n]) for n in mapping.columns]
        if {"W1", "W2"}.issubset(mapping.index) else [],
        NITROGEN: [(w, mapping.loc[w, "N2"], mapping.loc[w, "N0"]) for w in mapping.index],
    }


def build_objectives(catalogs, datasets):
    policy = pd.read_csv(PARENT / "objective_policy.csv")
    inherited = pd.read_csv(PARENT / "calibration_observations.csv")
    core = inherited[~inherited.variable.isin(
        ["LEAF_N_PCT", "STEM_N_PCT", "W_FRESH_CONTRAST", "N_ADJACENT_FRESH_CONTRAST"])].copy()
    # Match each retained target against the selected 2026 bundle before reusing its weights.
    keys = ["trno", "date", "variable", "depth_label"]
    columns = ["observed", "raw_sd", "n_rep"]
    source = catalogs["26SP"][keys + columns].fillna({"depth_label": ""})
    joined = core.fillna({"depth_label": ""}).merge(source, on=keys, validate="many_to_one",
        suffixes=("", "_source"), how="left", indicator=True)
    assert joined._merge.eq("both").all()
    for column in columns:
        np.testing.assert_allclose(joined[column], joined[f"{column}_source"], rtol=0, atol=1e-10)
    # Independently verify the measured water layer bounds and overlap mapping.
    water = core[core.variable.eq("VWC")].sort_values(keys)
    water_source = catalogs["26SP"][catalogs["26SP"].variable.eq("VWC")].sort_values(keys)
    geometry = ["depth_top_cm", "depth_bottom_cm", "dssat_layer_weights"]
    pd.testing.assert_frame_equal(water[geometry].reset_index(drop=True),
                                  water_source[geometry].reset_index(drop=True), check_dtype=False)

    pairs = gradient_pairs(Path(datasets["26SP"]["path"]))
    fresh = catalogs["26SP"].query("variable == 'CHFPW'").sort_values("date").groupby("trno").tail(1).set_index("trno")
    groups = [
        (WATER, "W_SIGNED_CONTRAST", "W_FRESH_CONTRAST", "W2-W1"),
        (NITROGEN, "N_ADJACENT_SIGNED_CONTRAST", NITROGEN_OPERATOR, "N2-N0"),
    ]
    targets = [core]
    for family, prior, variable, difference in groups:
        p = policy.loc[policy.family.eq(prior)].iloc[0]
        rows = []
        for context, hi, lo in pairs[family]:
            a, b = fresh.loc[hi], fresh.loc[lo]
            assert a.date == b.date
            rows.append(a.to_dict() | dict(trno=hi, paired_trno=lo, variable=variable,
                contrast=difference, contrast_context=context, observed=a.observed-b.observed,
                raw_sd=np.hypot(a.raw_sd, b.raw_sd), obsnme=f"{difference.replace('-', '_').lower()}_{context.lower()}"))
        q = pd.DataFrame(rows)
        q["sigma_eff"] = np.sqrt(q.raw_sd**2/p.n_eff + p.floor**2 + (p.cv*q.observed.abs())**2)
        targets.append(q.assign(family=family, loss=p.loss, huber_delta=p.huber_delta,
            final_weight=np.sqrt(p.budget/len(q)), budget_multiplier=np.sqrt(p.budget/len(q))))
        policy.loc[policy.family.eq(prior), ["family","variable","n_targets"]] = [family, variable, len(q)]
    disabled = policy.variable.isin(["LEAF_N_PCT", "STEM_N_PCT"])
    policy.loc[disabled, ["budget", "n_targets", "diagnostic_only"]] = [0, 0, True]
    obs = pd.concat(targets, ignore_index=True)
    assert len(obs) == 511 and obs.obsnme.is_unique and np.isclose(obs.final_weight.pow(2).sum(), 89)
    assert obs.season_id.eq("26SP").all() and obs.role.eq("calibration").all()
    positive = policy[policy.budget.gt(0)].set_index("family")
    np.testing.assert_allclose(obs.groupby("family").final_weight.apply(lambda w: w.pow(2).sum()).loc[positive.index],
                               positive.budget)
    np.testing.assert_array_equal(obs.groupby("family").size().loc[positive.index], positive.n_targets)
    obs.to_csv(RUN / "calibration_observations.csv", index=False)
    policy.to_csv(RUN / "objective_policy.csv", index=False)
    return obs.fillna("")


def prepare():
    path = PARENT / "design.json"
    parent = trial.read(path)
    assert trial.read(PARENT / "sealed_design.json")["sha256"] == native.sha(path)
    assert trial.read(PARENT / "pipeline_status.json")["status"] == "completed"
    for p, digest in parent["source_hashes"].items():
        assert native.sha(Path(p)) == digest, p
    slpf = {"25SP": .92, "26SP": .89}
    trial.DATES = parent["anthesis_dates"]
    datasets, catalogs = {}, {}
    for season, prior in parent["datasets"].items():
        bundle = CALIBRATION if season == "26SP" else Path(prior["path"])
        m = verify_calibrated_input_bundle(bundle) if season == "26SP" else verify_manifest_integrity(bundle)
        if season == "25SP":
            assert m.manifest_sha256 == prior["manifest_sha256"]
        catalogs[season] = trial.observation_catalog(bundle, season)
        assert set(catalogs[season].trno) == set(prior["treatments"])
        assert catalogs[season].loc[catalogs[season].variable.eq("ADAP"), "observed"].eq(37).all()
        payload = RUN / f"{season}_inputs"
        native.model_payload(bundle, payload, slpf[season])
        if season == "25SP":
            original = PARENT / payload.name
            changed = [f.name for f in payload.iterdir() if native.sha(f) != native.sha(original / f.name)]
            assert changed == ["SOIL.SOL"], changed
            assert (original/"SOIL.SOL").read_bytes().replace(b" .900 ", b" .920 ", 1) == (payload/"SOIL.SOL").read_bytes()
        datasets[season] = prior | dict(path=str(bundle), bundle_id=m.bundle_id, manifest_sha256=m.manifest_sha256)
    obs = build_objectives(catalogs, datasets)
    catalogs["25SP"].to_csv(RUN / "locked_validation_observations.csv", index=False)
    diag = catalogs["26SP"][catalogs["26SP"].variable.isin(["ADAP", "LEAF_N_PCT", "STEM_N_PCT", "FRUIT_N_PCT"])]
    diag.assign(final_weight=0.).to_csv(RUN / "calibration_diagnostic_observations.csv", index=False)
    fixed = [Path(__file__), path, Path(parent["frozen_bounds"]), PARENT / "joint/joint.pst",
             PARENT / "calibration_observations.csv", PARENT / "objective_policy.csv",
             *(RUN / f for f in ("calibration_observations.csv", "objective_policy.csv",
                                "locked_validation_observations.csv", "calibration_diagnostic_observations.csv"))]
    for season in datasets:
        fixed.extend((RUN / f"{season}_inputs").iterdir())
    hashes = {str(p):h for p,h in parent["source_hashes"].items() if not Path(p).is_relative_to(PARENT)}
    hashes.update({str(p):native.sha(p) for p in fixed})
    design = parent | dict(run_id=ID, parent_trial=PARENT.name, parent_design_sha256=native.sha(path),
        datasets=datasets, SLPF=slpf, target_count=len(obs), objective_budget=89,
        gradients={WATER:"final fresh yield W2-W1 within each nitrogen level",
                   NITROGEN:"final fresh yield N2-N0 within each water level"},
        diagnostic_only=["ADAP","LEAF_N_PCT","STEM_N_PCT","FRUIT_N_PCT"], source_hashes=hashes)
    b = pd.read_csv(design["frozen_bounds"]).rename(columns={"name":"registry_name","native_name":"name"})
    assert set(b.loc[b.status.eq("active"),"name"]) == set(design["active_parameters"])
    native.write(RUN / "design.json", design)
    return design, b, obs


def save_gradient_diagnostics(design):
    fit = pd.read_csv(RUN / "calibration_comparison.csv")
    rows = fit.loc[fit.family.isin([WATER,NITROGEN]),
        ["season_id","role","family","contrast","contrast_context","trno","paired_trno","date","observed","simulated"]]
    val = pd.read_csv(RUN / "validation_comparison.csv")
    fresh = val[val.variable.eq("CHFPW")].sort_values("date").groupby("trno").tail(1).set_index("trno")
    pairs = gradient_pairs(Path(design["datasets"]["25SP"]["path"]))
    validation = []
    for family, difference in [(WATER,"W2-W1"), (NITROGEN,"N2-N0")]:
        for context, hi, lo in pairs[family]:
            a, b = fresh.loc[hi], fresh.loc[lo]
            assert a.date == b.date
            validation.append(dict(season_id="25SP",role="validation",family=family,
                contrast=difference,contrast_context=context,trno=hi,paired_trno=lo,date=a.date,
                observed=a.observed-b.observed,simulated=a.simulated-b.simulated))
    matched = pd.concat([rows,pd.DataFrame(validation)], ignore_index=True)
    matched["error_sim_minus_obs"] = matched.simulated-matched.observed
    matched.to_csv(RUN / "gradient_comparison.csv", index=False)
    metrics = []
    for (season,family), group in matched.groupby(["season_id","family"]):
        err = group.error_sim_minus_obs.dropna()
        metrics.append(dict(season_id=season,family=family,n=len(err),
            rmse_kg_ha=np.sqrt(err.pow(2).mean()),mae_kg_ha=err.abs().mean(),bias_kg_ha=err.mean(),
            availability="matched" if len(err)==len(group) else "simulation_unmatched"))
    if not pairs[WATER]:
        metrics.append(dict(season_id="25SP",family=WATER,n=0,availability="W2 treatment unavailable"))
    pd.DataFrame(metrics).to_csv(RUN / "gradient_metrics.csv",index=False)


def make_case(design, obs, params, outputs):
    work = RUN / "joint"
    work.mkdir()
    shutil.copy2(PARENT / "joint/parameters.tpl", work / "parameters.tpl")
    params.to_csv(work / "initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work / "parameters.csv", index_label="name")
    (work / "objectives.ins").write_text(
        "pif ~\n" + "".join(f"l1 w !{name}!\n" for name in obs.obsnme), encoding="ascii")
    trial.write_outputs(work / "FormalObjectives.OUT", obs.obsnme, outputs.loc["base"])
    pst = pyemu.Pst(str(PARENT / "joint/joint.pst"))
    pst.parameter_data["parval1"] = params.loc["base", pst.parameter_data.index]
    pst.observation_data = obs.assign(obsval=0., weight=obs.final_weight, obgnme=obs.family.str.lower()).set_index(
        "obsnme", drop=False)[["obsnme", "obsval", "weight", "obgnme"]]
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(__file__)}" --forward "{RUN}"']
    pst.write(str(work / "joint.pst"), version=1)
    actual = pyemu.Pst(str(work / "joint.pst"))
    assert (actual.npar_adj, actual.nnz_obs, actual.control_data.noptmax) == (58, 511, 4)
    assert actual.pestpp_options == pst.pestpp_options
    assert actual.observation_data.obsnme.tolist() == obs.obsnme.tolist()
    np.testing.assert_allclose(actual.observation_data.weight, obs.final_weight, rtol=1e-8)
    manifest = yaml.safe_load((PARENT / "joint/run_manifest.yaml").read_text(encoding="utf-8"))
    manifest.update(run_id=ID, n_obs=len(obs), design=str(RUN / "design.json"), parent_trial=PARENT.name,
                    objective_budget=design["objective_budget"], gradients=design["gradients"])
    (work / "run_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN / "design.json").exists() or (RUN / "joint").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    try:
        trial.status(RUN, "preparing")
        design, b, obs = prepare()
        params, outputs, base = trial.initial_ensemble(RUN, b, obs, trial.contexts(RUN, design, b)["26SP"])
        design.update(initial_members=len(params), initial_ensemble_base=base)
        native.write(RUN / "design.json", design)
        native.write(RUN / "sealed_design.json", dict(sha256=native.sha(RUN / "design.json")))
        make_case(design, obs, params, outputs)
        trial.status(RUN, "running", phase="pest_ies", initial_members=len(params), n_targets=len(obs))
        with (RUN / "parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/parallel/run_parallel.py"),
                "--run-dir", str(RUN / "joint"), "--case", "joint", "--mode", "ies",
                "--n-agents", str(design["workers"]), "--wait"], cwd=ROOT, stdout=log,
                stderr=subprocess.STDOUT, check=True)
        if trial.read(RUN / "joint/run_status.json")["status"] != "completed":
            raise RuntimeError("PEST++ did not complete")
        for dataset in design["datasets"].values():
            assert verify_manifest_integrity(dataset["path"]).manifest_sha256 == dataset["manifest_sha256"]
        trial.status(RUN, "postprocessing")
        trial.finalize(RUN, b, obs, design, params)
        save_gradient_diagnostics(design)
    except Exception as exc:
        state = trial.read(RUN / "pipeline_status.json")
        trial.status(RUN, "failed", phase=state["status"], error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--forward", type=Path)
    args = parser.parse_args()
    # Use the existing signed yield operator with the new target variable.
    sa98_joint40.SIGNED.add(NITROGEN_OPERATOR)
    if args.forward is None:
        main()
    else:
        trial.forward(args.forward)
