"""Fit one shared set of official genetic coefficients to both spring seasons."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import pyemu
from scipy.stats import qmc
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.input_manifest import verify_calibrated_input_bundle
from tools.calibration import run_dual_morris98_trial_20261105 as trial

ID = "eggplant_dual_spring_cal_morris98_80x4_c31initial_noadat_20261106"
PARENT = ROOT / "workspace/runs/eggplant_26sp_cal25sp_val_dual_morris98_80x4_c31initial_noadat_20261106"
RUN = ROOT / "workspace/runs" / ID
SEASONS = ("25SP", "26SP")
native = trial.native


def spring_2025_objectives(catalog, metadata, policy):
    """Apply the inherited loss and family budgets on the available 2025 strata."""
    fresh = catalog[catalog.variable.eq("CHFPW")].sort_values("date").groupby("trno").tail(1).set_index("trno")
    mapping = metadata.pivot(index="water_level", columns="nitrogen_level", values="treatment")
    assert mapping.index.tolist() == ["W1", "W3"] and mapping.columns.tolist() == ["N0", "N1", "N2", "N3"]
    pairs = {
        "W_SIGNED_CONTRAST": list(zip(mapping.loc["W3"], mapping.loc["W1"])),
        "N_ADJACENT_SIGNED_CONTRAST": [
            (hi, lo) for levels in mapping.to_numpy() for lo, hi in zip(levels[:-1], levels[1:])
        ],
    }
    groups = []
    for item in policy[policy.budget.gt(0)].itertuples():
        if item.family in pairs:
            rows = []
            for hi, lo in pairs[item.family]:
                a, b = fresh.loc[hi], fresh.loc[lo]
                assert a.date == b.date
                rows.append(a.to_dict() | dict(trno=hi, paired_trno=lo, variable=item.variable,
                                              observed=a.observed-b.observed, raw_sd=np.hypot(a.raw_sd,b.raw_sd)))
            group = pd.DataFrame(rows)
            strata = ["trno", "paired_trno"]
        else:
            group = catalog[catalog.variable.eq(item.variable)].copy()
            last = group.date.eq(group.groupby("trno").date.transform("max"))
            if item.family.startswith("FINAL_"):
                group = group[last].copy()
            if item.family == "HARVEST_DRY_CUMULATIVE_EARLY":
                group = group[~last].copy()
            strata = ["trno", "depth_label"] if item.variable == "VWC" else ["trno"]
        blocks = group.groupby(strata)
        group["sigma_eff"] = np.sqrt(
            group.raw_sd**2/item.n_eff + item.floor**2 + (item.cv*group.observed.abs())**2)
        group["budget_multiplier"] = np.sqrt(
            item.budget / (blocks.ngroups * blocks["observed"].transform("size")))
        assert len(group) and np.isclose(group.budget_multiplier.pow(2).sum(), item.budget), item.family
        groups.append(group.assign(family=item.family, loss=item.loss, huber_delta=item.huber_delta,
                                   final_weight=group.budget_multiplier))
    return pd.concat(groups, ignore_index=True)


def prepare():
    path = PARENT / "design.json"
    parent = trial.read(path)
    assert trial.read(PARENT / "sealed_design.json")["sha256"] == native.sha(path)
    assert trial.read(PARENT / "pipeline_status.json")["status"] == "completed"
    assert (parent["members"], parent["updates"], parent["target_count"]) == (80, 4, 617)
    assert parent["anthesis_in_objective"] is False
    for filename, digest in parent["source_hashes"].items():
        assert native.sha(Path(filename)) == digest, filename

    hashes = {}
    datasets = {}
    diagnostics = []
    trial.DATES = parent["anthesis_dates"]
    for season in SEASONS:
        ds = parent["datasets"][season]
        bundle = Path(ds["path"])
        assert verify_calibrated_input_bundle(bundle).manifest_sha256 == ds["manifest_sha256"]
        payload = RUN / f"{season}_inputs"
        shutil.copytree(PARENT / payload.name, payload)
        for file in payload.iterdir():
            hashes[str(file)] = native.sha(file)
            assert hashes[str(file)] == parent["source_hashes"][str(PARENT / payload.name / file.name)]
        datasets[season] = ds | {"role": "calibration"}
        diagnostics.append(trial.observation_catalog(bundle, season).assign(role="diagnostic"))

    policy = pd.read_csv(PARENT / "objective_policy.csv")
    metadata = pd.read_csv(Path(datasets["25SP"]["path"]) / "treatment_metadata.csv")
    prior_catalog = pd.read_csv(PARENT / "locked_validation_observations.csv")
    targets25 = spring_2025_objectives(prior_catalog, metadata, policy)
    targets26 = pd.read_csv(PARENT / "calibration_observations.csv")
    obs = pd.concat([targets25, targets26], ignore_index=True).assign(role="calibration")
    obs["obsnme"] = [f"s{season[:2]}_{i:04d}" for i, season in enumerate(obs.season_id)]
    obs[["final_weight", "budget_multiplier"]] /= np.sqrt(2)
    assert obs.variable.isin(["ADAP", "FRUIT_N_PCT"]).sum() == 0
    assert np.isfinite(obs.sigma_eff).all() and obs.sigma_eff.gt(0).all()
    assert obs.final_weight.gt(0).all() and obs.obsnme.is_unique
    budgets = obs.assign(budget=obs.final_weight.pow(2)).groupby(["season_id", "family"]).agg(
        budget=("budget", "sum"), n_targets=("obsnme", "size")).reset_index()
    merged = budgets.merge(policy.drop(columns=["budget", "n_targets"]), on="family")
    for season in SEASONS:
        actual = budgets[budgets.season_id.eq(season)].set_index("family").budget
        expected = policy[policy.budget.gt(0)].set_index("family").budget / 2
        np.testing.assert_allclose(actual.loc[expected.index], expected)
    assert (len(targets25), len(targets26)) == (426, 617)
    obs.to_csv(RUN / "calibration_observations.csv", index=False)
    pd.concat(diagnostics, ignore_index=True).to_csv(RUN / "diagnostic_observations.csv", index=False)
    merged.to_csv(RUN / "objective_policy.csv", index=False)

    frozen = Path(parent["frozen_bounds"])
    for filename in (frozen, trial.EXE, Path(__file__), Path(trial.__file__),
                     Path(native.__file__), PARENT / "joint/joint.pst", PARENT / "joint/initial_ensemble.csv",
                     PARENT / "joint/joint.0.obs.csv", RUN / "calibration_observations.csv",
                     RUN / "diagnostic_observations.csv", RUN / "objective_policy.csv"):
        hashes[str(filename)] = native.sha(filename)
    for filename, digest in parent["source_hashes"].items():
        if Path(filename).is_relative_to(ROOT / "src"):
            hashes[filename] = digest
    design = {key: parent[key] for key in (
        "stage", "bounds_id", "frozen_bounds", "members", "updates", "seed", "workers",
        "active_parameters", "anthesis_dates", "anthesis_dap", "SLPF", "SASC", "ICNS",
    )} | dict(
        run_id=ID, datasets=datasets, parent_trial=PARENT.name, parent_design_sha256=native.sha(path),
        target_count=len(obs), targets_by_season={"25SP": len(targets25), "26SP": len(targets26)},
        objective_budget=97, objective_budget_by_season=dict.fromkeys(SEASONS, 48.5),
        anthesis_in_objective=False, independent_validation=False,
        initial_ensemble_policy="Replay prior ensemble in both seasons; replace infeasible vectors from the same Sobol sequence",
        source_hashes=hashes,
    )
    native.write(RUN / "design.json", design)
    native.write(RUN / "sealed_design.json", dict(sha256=native.sha(RUN / "design.json")))
    b = pd.read_csv(frozen).rename(columns={"name": "registry_name", "native_name": "name"})
    assert set(b.loc[b.status.eq("active"), "name"]) == set(design["active_parameters"])
    return design, b, obs.fillna("")


def compare(run, work, contexts, values, obs):
    frames = []
    for season in SEASONS:
        out = work / season
        out.mkdir()
        targets = obs[obs.season_id.eq(season)]
        frames.append(trial.evaluate(run, out, contexts[season], values, targets))
    return pd.concat(frames, ignore_index=True).set_index("obsnme", drop=False).loc[obs.obsnme]


def screen(design, b, obs, contexts):
    previous = pd.read_csv(PARENT / "joint/initial_ensemble.csv", index_col=0)
    previous_outputs = pd.read_csv(PARENT / "joint/joint.0.obs.csv", index_col=0)
    assert len(previous) == design["members"] and previous.index[0] == "base"
    n25 = design["targets_by_season"]["25SP"]
    active = b[b.status.eq("active")]
    center = dict(zip(b.name, b.init))
    samples = qmc.Sobol(len(active), scramble=True, seed=design["seed"]).random_base2(9)
    inherited = [(name, dict(zip(b.name, row.loc[b.pest_name]))) for name, row in previous.iterrows()]
    replacements = [
        (f"global_{i:04d}", center | dict(zip(active.name, active.lower + p*(active.upper-active.lower))))
        for i, p in enumerate(samples) if f"global_{i:04d}" not in previous.index
    ]

    def evaluate_candidate(task):
        name, vector = task
        try:
            values = trial.values_for(b, vector)
            with TemporaryDirectory(prefix="screen_", dir=RUN) as temp:
                result = compare(RUN, Path(temp), contexts, values, obs)
            return name, values, result.pest_output.to_numpy(), ""
        except (ValueError, KeyError, AssertionError, native.NativeRunError, subprocess.TimeoutExpired) as exc:
            return name, None, None, f"{type(exc).__name__}: {exc}"

    accepted, audit, vectors = [], [], set()
    with ThreadPoolExecutor(max_workers=design["workers"]) as pool:
        candidates = inherited + replacements
        for start in range(0, len(candidates), design["workers"]):
            for name, values, output, error in pool.map(
                evaluate_candidate, candidates[start:start+design["workers"]]
            ):
                prior = name in previous.index
                if values is not None and prior:
                    np.testing.assert_allclose(output[n25:], previous_outputs.loc[name], rtol=5e-6, atol=1e-9)
                if values is not None:
                    vector = tuple(values.values())
                    if vector in vectors:
                        error = "Duplicate serialized vector"
                    elif len(accepted) == design["members"]:
                        error = "Ensemble already full"
                    else:
                        accepted.append((name, values, output))
                        vectors.add(vector)
                audit.append(dict(candidate=name, inherited=prior, accepted=not error, reason=error))
            pd.DataFrame(audit).to_csv(RUN / "initial_feasibility_audit.csv", index=False)
            trial.status(RUN, "preflight", accepted=len(accepted), attempted=len(audit))
            if len(accepted) == design["members"]:
                break
            if len(audit) >= 18 and not accepted and len({row["reason"] for row in audit}) == 1:
                raise RuntimeError(audit[0]["reason"])
    if len(accepted) != design["members"]:
        raise RuntimeError(f"Only {len(accepted)} paired feasible vectors")
    base = accepted[0][0]
    index = ["base"] + [row[0] for row in accepted[1:]]
    params = pd.DataFrame([row[1] for row in accepted], index=index).rename(columns=dict(zip(b.name,b.pest_name)))
    outputs = pd.DataFrame([row[2] for row in accepted], index=index, columns=obs.obsnme)
    native.write(RUN / "initial_ensemble_replay.json", dict(
        members=len(index), base_candidate=base,
        inherited=sum(row["accepted"] and row["inherited"] for row in audit),
        replacements=sum(row["accepted"] and not row["inherited"] for row in audit)))
    return params, outputs


def make_case(design, obs, params, outputs):
    work = RUN / "joint"
    work.mkdir()
    source = PARENT / "joint"
    shutil.copy2(source / "parameters.tpl", work / "parameters.tpl")
    params.to_csv(work / "initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work / "parameters.csv", index_label="name")
    (work / "objectives.ins").write_text(
        "pif ~\n" + "".join(f"l1 w !{name}!\n" for name in obs.obsnme), encoding="ascii")
    trial.write_outputs(work / "FormalObjectives.OUT", obs.obsnme, outputs.loc["base"])
    pst = pyemu.Pst(str(source / "joint.pst"))
    pst.parameter_data["parval1"] = params.loc["base", pst.parameter_data.index]
    pst.observation_data = obs.assign(
        obsval=0.0, weight=obs.final_weight,
        obgnme=obs.season_id.str.lower()+"_"+obs.family.str.lower()
    ).set_index("obsnme", drop=False)[["obsnme", "obsval", "weight", "obgnme"]]
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(__file__)}" --forward "{RUN}"']
    pst.write(str(work / "joint.pst"), version=1)
    actual = pyemu.Pst(str(work / "joint.pst"))
    assert actual.npar_adj == 58 and actual.nnz_obs == len(obs) and actual.control_data.noptmax == design["updates"]
    assert actual.pestpp_options == pst.pestpp_options
    assert actual.observation_data.obsnme.tolist() == obs.obsnme.tolist()
    np.testing.assert_allclose(actual.observation_data.weight, obs.final_weight, rtol=1e-8)
    manifest = yaml.safe_load((source / "run_manifest.yaml").read_text(encoding="utf-8"))
    manifest.update(run_id=ID, design=str(RUN / "design.json"), n_obs=len(obs),
                    parent_trial=PARENT.name, calibration_seasons=list(SEASONS), independent_validation=False)
    (work / "run_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def forward(run):
    work = Path.cwd()
    output = work / "FormalObjectives.OUT"
    output.unlink(missing_ok=True)
    try:
        design = trial.read(run / "design.json")
        assert trial.read(run / "sealed_design.json")["sha256"] == native.sha(run / "design.json")
        for filename, digest in design["source_hashes"].items():
            assert native.sha(Path(filename)) == digest, filename
        b = pd.read_csv(design["frozen_bounds"]).rename(columns={"name": "registry_name", "native_name": "name"})
        raw = pd.read_csv(work / "parameters.csv").set_index("name").value
        values = trial.values_for(b, dict(zip(b.name, raw.loc[b.pest_name])))
        obs = pd.read_csv(run / "calibration_observations.csv").fillna("")
        contexts = trial.contexts(run, design, b, SEASONS)
        with TemporaryDirectory(prefix="paired_", dir=work) as temp:
            result = compare(run, Path(temp), contexts, values, obs)
        trial.write_outputs(output, obs.obsnme, result.pest_output)
    except Exception as exc:
        with (work / "forward_failures.jsonl").open("a", encoding="utf-8") as log:
            print(json.dumps(dict(error=f"{type(exc).__name__}: {exc}")), file=log)
        raise


def finalize(design, b, obs, params, contexts):
    work = RUN / "joint"
    rounds, boundaries, candidates = [], [], []
    active = b[b.status.eq("active")].set_index("pest_name")
    for iteration in range(design["updates"] + 1):
        par_path, obs_path = (work / f"joint.{iteration}.{suffix}.csv" for suffix in ("par", "obs"))
        if not par_path.is_file() or not obs_path.is_file():
            rounds.append(dict(iteration=iteration, retained=0, passed=False))
            continue
        par = pd.read_csv(par_path, index_col=0)
        outputs = pd.read_csv(obs_path, index_col=0)
        ids = params.index.intersection(par.index).intersection(outputs.index)
        y = outputs.loc[ids, obs.obsnme].to_numpy()
        valid = np.isfinite(y).all(axis=1) & np.isfinite(par.loc[ids, b.pest_name]).all(axis=1)
        ids = ids[valid]
        phi = pd.Series(np.square(y[valid]*obs.final_weight.to_numpy()).sum(axis=1), index=ids)
        passed = len(ids)/design["members"] >= .98
        rounds.append(dict(iteration=iteration, retained=len(ids), passed=passed,
                           min_phi=phi.min(), median_phi=phi.median()))
        if passed:
            name = phi.idxmin()
            candidates.append((float(phi.loc[name]), iteration, name, par.loc[name, b.pest_name]))
        if iteration >= design["updates"]-1 and len(ids):
            positions = (par.loc[ids, active.index]-active.lower)/(active.upper-active.lower)
            for name, x in positions.items():
                boundaries.append(dict(iteration=iteration, parameter=active.loc[name, "name"], members=len(x),
                    near_lower=x.le(.02).mean(), near_upper=x.ge(.98).mean(),
                    severe_lower=x.le(.005).mean(), severe_upper=x.ge(.995).mean()))
    pd.DataFrame(rounds).to_csv(RUN / "round_quality.csv", index=False)
    pd.DataFrame(boundaries).to_csv(RUN / "parameter_boundary_round3_4.csv", index=False)
    if not any(row["passed"] and row["iteration"] > 0 for row in rounds):
        raise RuntimeError("No updated round met the retention gate")
    score, iteration, member, raw = min(candidates, key=lambda row: row[:3])
    values = trial.values_for(b, dict(zip(b.name, raw)))
    out = RUN / "selected_deterministic"
    out.mkdir()
    compared = compare(RUN, out, contexts, values, obs)
    phi = float(compared.phi_contribution.sum())
    if not np.isclose(phi, score, rtol=1e-6, atol=1e-8):
        raise ValueError(f"Deterministic Phi differs: {score} vs {phi}")
    compared.to_csv(RUN / "calibration_comparison.csv", index=False)
    best = RUN / "best_calibration_parameters.csv"
    pd.Series(values, name="value").to_csv(best, index_label="name")
    diag = pd.read_csv(RUN / "diagnostic_observations.csv").fillna("")
    pd.concat([trial.extract(out / season, diag[diag.season_id.eq(season)], strict=False)
               for season in SEASONS]).to_csv(RUN / "diagnostic_comparison.csv", index=False)
    by_season = compared.groupby("season_id").phi_contribution.sum().to_dict()
    native.write(RUN / "selection.json", dict(iteration=iteration, member=member, phi=phi,
        phi_by_season=by_season, calibration_seasons=list(SEASONS), independent_validation=False,
        parameters_sha256=native.sha(best)))
    engineering = trial.read(work / "run_status.json").get("engineering_status")
    trial.status(RUN, "completed", selected_phi=phi, selected_iteration=iteration, selected_member=member,
        retained=rounds[-1]["retained"], all_rounds_passed=all(row["passed"] for row in rounds),
        engineering_status=engineering, scientific_status="science_pending_trial")


def controller():
    RUN.mkdir(exist_ok=True)
    if (RUN / "design.json").exists() or (RUN / "joint").exists():
        raise FileExistsError(f"Existing trial {RUN}")
    try:
        trial.status(RUN, "preparing")
        design, b, obs = prepare()
        contexts = trial.contexts(RUN, design, b, SEASONS)
        params, outputs = screen(design, b, obs, contexts)
        make_case(design, obs, params, outputs)
        trial.status(RUN, "running", phase="pest_ies", initial_members=len(params), n_targets=len(obs))
        with (RUN / "parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/parallel/run_parallel.py"),
                "--run-dir", str(RUN / "joint"), "--case", "joint", "--mode", "ies",
                "--n-agents", str(design["workers"]), "--wait"], cwd=ROOT, stdout=log,
                stderr=subprocess.STDOUT, check=True)
        if trial.read(RUN / "joint/run_status.json")["status"] != "completed":
            raise RuntimeError("PEST++ did not complete")
        trial.status(RUN, "postprocessing")
        finalize(design, b, obs, params, contexts)
    except Exception as exc:
        previous = trial.read(RUN / "pipeline_status.json")
        trial.status(RUN, "failed", phase=previous["status"], error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--forward", type=Path)
    args = cli.parse_args()
    if args.forward is None:
        controller()
    else:
        forward(args.forward)
