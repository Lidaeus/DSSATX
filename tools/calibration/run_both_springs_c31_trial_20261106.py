"""Calibrate the same genetic parameters to both final spring bundles."""

import argparse
from concurrent.futures import ThreadPoolExecutor
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

native = trial.native
PARENT = ROOT / "workspace/runs/eggplant_26sp_cal25sp_val_dual_morris98_80x4_c31initial_finalcn_sasc70_noadat_20261106"
RUN = ROOT / "workspace/runs/eggplant_both_springs_cal_c31initial_finalcn_sasc70_noadat_80x4_20261106"
SEASONS = ("25SP", "26SP")


def bounds(design):
    return pd.read_csv(design["frozen_bounds"]).rename(columns={"name": "registry_name", "native_name": "name"})


def season_targets(catalog, bundle, policy, season):
    meta = pd.read_csv(bundle / "treatment_metadata.csv")
    trts = {(r.water_level, r.nitrogen_level): int(r.treatment) for r in meta.itertuples()}
    waters = sorted(meta.water_level.unique())
    fresh = catalog[catalog.variable.eq("CHFPW")].sort_values("date").groupby("trno").tail(1).set_index("trno")
    contrast_pairs = {
        "W_SIGNED_CONTRAST": [(trts[w, n], trts["W1", n]) for n in ("N0", "N1", "N2", "N3")
                              for w in waters if w != "W1"],
        "N_ADJACENT_SIGNED_CONTRAST": [(trts[w, f"N{i+1}"], trts[w, f"N{i}"])
                                       for w in waters for i in range(3)],
    }
    groups = []
    for p in policy[policy.budget.gt(0)].itertuples():
        if p.family in contrast_pairs:
            rows = []
            for hi, lo in contrast_pairs[p.family]:
                a, b = fresh.loc[hi], fresh.loc[lo]
                assert a.date == b.date
                rows.append(a.to_dict() | dict(trno=hi, paired_trno=lo, variable=p.variable,
                                               observed=a.observed-b.observed, raw_sd=np.hypot(a.raw_sd, b.raw_sd)))
            q = pd.DataFrame(rows)
            strata = ["trno", "paired_trno"]
        else:
            q = catalog[catalog.variable.eq(p.variable)].copy()
            last = q.date.eq(q.groupby("trno").date.transform("max"))
            if p.family.startswith("FINAL_"):
                q = q[last].copy()
            if p.family == "HARVEST_DRY_CUMULATIVE_EARLY":
                q = q[~last].copy()
            strata = ["trno", "depth_label"] if p.variable == "VWC" else ["trno"]
        blocks = q.groupby(strata)
        q["sigma_eff"] = np.sqrt(q.raw_sd**2 / p.n_eff + p.floor**2 + (p.cv*q.observed.abs())**2)
        q["final_weight"] = q["budget_multiplier"] = np.sqrt(
            (p.budget / len(SEASONS)) / (blocks.ngroups * blocks["observed"].transform("size")))
        assert len(q) and np.isclose(q.final_weight.pow(2).sum(), p.budget / len(SEASONS))
        groups.append(q.assign(family=p.family, loss=p.loss, huber_delta=p.huber_delta))
    obs = pd.concat(groups, ignore_index=True)
    assert np.isfinite(obs[["observed", "sigma_eff", "final_weight"]]).all().all()
    assert obs.sigma_eff.gt(0).all() and obs.final_weight.gt(0).all()
    assert np.isclose(obs.final_weight.pow(2).sum(), 48.5)
    return obs.assign(obsnme=[f"s{season[:2]}_{i:04d}" for i in range(len(obs))])


def prepare():
    design = trial.read(PARENT / "design.json")
    assert trial.read(PARENT / "sealed_design.json")["sha256"] == native.sha(PARENT / "design.json")
    assert trial.read(PARENT / "pipeline_status.json")["status"] == "completed"
    for file, digest in design["source_hashes"].items():
        assert native.sha(Path(file)) == digest, file
    assert (design["members"], design["updates"], len(design["active_parameters"])) == (80, 4, 58)
    assert design["SASC_ratio_by_season"] == {s: .7 for s in SEASONS}
    trial.DATES = design["anthesis_dates"]
    index = trial.read(trial.INDEX)["bundles"]
    policy = pd.read_csv(PARENT / "objective_policy.csv")
    observations, catalogs, sources = {}, {}, []
    for s in SEASONS:
        d = design["datasets"][s]
        bundle = Path(d["path"])
        manifest = verify_calibrated_input_bundle(bundle)
        assert index[s] == dict(bundle_id=manifest.bundle_id, manifest_sha256=manifest.manifest_sha256)
        assert manifest.manifest_sha256 == d["manifest_sha256"]
        assert list(d["treatments"]) == sorted(pd.read_csv(bundle / "treatment_metadata.csv").treatment)
        d["role"] = "calibration"
        payload = RUN / f"{s}_inputs"
        shutil.copytree(PARENT / payload.name, payload)
        sources.extend((*payload.iterdir(), manifest.manifest_path))
        catalogs[s] = trial.observation_catalog(bundle, s).assign(role="calibration")
        observations[s] = season_targets(catalogs[s], bundle, policy, s)

    # Verify that the prior 2026 operator survives the change apart from its
    # uniform seasonal scaling and the names used to distinguish observations.
    prior = pd.read_csv(PARENT / "calibration_observations.csv")
    q = observations["26SP"].copy()
    q[["final_weight", "budget_multiplier"]] *= np.sqrt(2)
    pd.testing.assert_frame_equal(q[prior.columns].drop(columns="obsnme").fillna(""),
                                  prior.drop(columns="obsnme").fillna(""), check_dtype=False)
    obs = pd.concat(observations.values(), ignore_index=True)
    assert obs.obsnme.is_unique and not obs.variable.isin(["ADAP", "FRUIT_N_PCT"]).any()
    obs.to_csv(RUN / "calibration_observations.csv", index=False)
    pd.concat(catalogs.values(), ignore_index=True).to_csv(RUN / "diagnostic_observations.csv", index=False)
    (obs.groupby(["season_id", "family"], as_index=False)
        .agg(targets=("obsnme", "size"), budget=("final_weight", lambda w: float(w.pow(2).sum())))
        .to_csv(RUN / "objective_policy_by_season.csv", index=False))
    sources.extend(RUN.glob("*.csv"))
    sources.extend([Path(__file__), PARENT / "design.json", PARENT / "joint/joint.pst",
                    PARENT / "joint/initial_ensemble.csv", PARENT / "objective_policy.csv"])
    hashes = {p: h for p, h in design["source_hashes"].items() if not Path(p).is_relative_to(PARENT)}
    hashes.update({str(p): native.sha(p) for p in sources})
    design.update(run_id=RUN.name, parent_trial=PARENT.name,
                  parent_design_sha256=native.sha(PARENT / "design.json"), source_hashes=hashes,
                  target_count=len(obs), target_count_by_season={s: len(q) for s, q in observations.items()},
                  objective_budget_by_season={s: 48.5 for s in SEASONS}, validation_seasons=[])
    design.pop("initial_members", None)
    design.pop("initial_ensemble_base", None)
    native.write(RUN / "design.json", design)
    return design, bounds(design), obs.fillna("")


def evaluate(run, work, contexts, values, obs):
    frames = []
    for s in SEASONS:
        folder = work / s
        folder.mkdir()
        frames.append(trial.evaluate(run, folder, contexts[s], values, obs[obs.season_id.eq(s)]))
    q = pd.concat(frames, ignore_index=True)
    assert q.obsnme.tolist() == obs.obsnme.tolist() and np.isfinite(q.pest_output).all()
    return q


def initial_ensemble(design, b, obs):
    prior = pd.read_csv(PARENT / "joint/initial_ensemble.csv", index_col=0)
    candidates = [(name, dict(zip(b.name, row[b.pest_name]))) for name, row in prior.iterrows()]
    center = dict(zip(b.name, b.init))
    active = b[b.status.eq("active")]
    sobol = qmc.Sobol(len(active), scramble=True, seed=design["seed"]).random_base2(9)
    candidates += [(f"reserve_{i:04d}", center | dict(zip(active.name, active.lower + p*(active.upper-active.lower))))
                   for i, p in enumerate(sobol)]
    contexts = trial.contexts(RUN, design, b, SEASONS)
    accepted, audit, seen = [], [], set()

    def screen(task):
        name, values = task
        try:
            values = trial.values_for(b, values)
            with TemporaryDirectory(prefix="pre_", dir=RUN) as tmp:
                q = evaluate(RUN, Path(tmp), contexts, values, obs)
            return name, values, q.pest_output.to_numpy(), ""
        except (ValueError, KeyError, AssertionError, native.NativeRunError) as exc:
            return name, None, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=design["workers"]) as pool:
        for i in range(0, len(candidates), design["workers"]):
            for name, values, response, error in pool.map(screen, candidates[i:i+design["workers"]]):
                key = tuple(values.values()) if values else None
                keep = not error and key not in seen and len(accepted) < design["members"]
                if keep:
                    seen.add(key)
                    accepted.append((name, values, response))
                audit.append(dict(candidate=name, accepted=keep, reason=error or (
                    "" if keep else "Duplicate vector or ensemble filled")))
            pd.DataFrame(audit).to_csv(RUN / "initial_feasibility_audit.csv", index=False)
            trial.status(RUN, "preflight", accepted=len(accepted), attempted=len(audit))
            if len(accepted) == design["members"]:
                break
            if len(audit) >= 18 and not accepted and len({row["reason"] for row in audit}) == 1:
                raise RuntimeError(audit[0]["reason"])
    assert len(accepted) == design["members"]
    names = ["base", *[row[0] for row in accepted[1:]]]
    params = pd.DataFrame([row[1] for row in accepted], index=names).rename(columns=dict(zip(b.name, b.pest_name)))
    outputs = pd.DataFrame([row[2] for row in accepted], index=names, columns=obs.obsnme)
    return params, outputs, accepted[0][0]


def build_case(design, b, obs, params, outputs):
    work = RUN / "joint"
    work.mkdir()
    shutil.copy2(PARENT / "joint/parameters.tpl", work / "parameters.tpl")
    params.to_csv(work / "initial_ensemble.csv")
    params.loc["base"].rename("value").to_csv(work / "parameters.csv", index_label="name")
    (work / "objectives.ins").write_text("pif ~\n" + "".join(f"l1 w !{n}!\n" for n in obs.obsnme), encoding="ascii")
    trial.write_outputs(work / "FormalObjectives.OUT", obs.obsnme, outputs.loc["base"])
    pst = pyemu.Pst.from_io_files([str(work / "parameters.tpl")], [str(work / "parameters.csv")],
        [str(work / "objectives.ins")], [str(work / "FormalObjectives.OUT")], pst_path=".")
    prior = pyemu.Pst(str(PARENT / "joint/joint.pst"))
    columns = ["partrans", "parval1", "parlbnd", "parubnd", "pargp"]
    pst.parameter_data.loc[b.pest_name, columns] = prior.parameter_data.loc[b.pest_name, columns]
    pst.parameter_data.loc[b.pest_name, "parval1"] = params.loc["base", b.pest_name]
    for row in obs.itertuples():
        pst.observation_data.loc[row.obsnme, ["obsval", "weight", "obgnme"]] = [
            0., row.final_weight, f"s{row.season_id[:2]}_{row.family.lower()}"]
    pst.model_command = [f'"{sys.executable}" -X utf8 "{Path(__file__)}" --forward "{RUN}"']
    pst.control_data.noptmax = design["updates"]
    pst.pestpp_options = prior.pestpp_options.copy()
    pst.write(str(work / "joint.pst"), version=1)
    check = pyemu.Pst(str(work / "joint.pst"))
    assert (check.npar_adj, check.nnz_obs, check.control_data.noptmax) == (58, len(obs), 4)
    assert set(check.adj_par_names) == set(b[b.status.eq("active")].pest_name)
    np.testing.assert_allclose(check.parameter_data.loc[b.pest_name, "parlbnd"], b.lower)
    np.testing.assert_allclose(check.parameter_data.loc[b.pest_name, "parubnd"], b.upper)
    np.testing.assert_allclose(check.observation_data.loc[obs.obsnme, "weight"], obs.final_weight)
    manifest = yaml.safe_load((PARENT / "joint/run_manifest.yaml").read_text(encoding="utf-8"))
    manifest.pop("sasc_default_marker", None)
    manifest.update(run_id=RUN.name, parent_trial=PARENT.name, n_obs=len(obs), design=str(RUN / "design.json"),
                    calibration_seasons=list(SEASONS), objective_budget_by_season=design["objective_budget_by_season"])
    (work / "run_manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")


def forward(run):
    work = Path.cwd()
    output = work / "FormalObjectives.OUT"
    output.unlink(missing_ok=True)
    design = trial.read(run / "design.json")
    assert trial.read(run / "sealed_design.json")["sha256"] == native.sha(run / "design.json")
    for path, digest in design["source_hashes"].items():
        assert native.sha(Path(path)) == digest, path
    b = bounds(design)
    raw = pd.read_csv(work / "parameters.csv").set_index("name").value
    try:
        values = trial.values_for(b, dict(zip(b.name, raw.loc[b.pest_name])))
        obs = pd.read_csv(run / "calibration_observations.csv").fillna("")
        contexts = trial.contexts(run, design, b, SEASONS)
        with TemporaryDirectory(prefix="model_", dir=work) as tmp:
            q = evaluate(run, Path(tmp), contexts, values, obs)
        trial.write_outputs(output, obs.obsnme, q.pest_output)
    except Exception as exc:
        import json
        with (work / "forward_failures.jsonl").open("a", encoding="utf-8") as log:
            print(json.dumps(dict(error=f"{type(exc).__name__}: {exc}", vector=raw.to_dict())), file=log)
        raise


def finalize(design, b, obs, params):
    from src.calibration.sa98_joint40 import extract
    work = RUN / "joint"
    active = b[b.status.eq("active")].set_index("pest_name")
    rounds, boundary, candidates = [], [], []
    for i in range(design["updates"]+1):
        p = pd.read_csv(work / f"joint.{i}.par.csv", index_col=0)
        o = pd.read_csv(work / f"joint.{i}.obs.csv", index_col=0)
        ids = params.index.intersection(p.index).intersection(o.index)
        valid = np.isfinite(o.loc[ids, obs.obsnme]).all(axis=1) & np.isfinite(p.loc[ids, b.pest_name]).all(axis=1)
        ids = ids[valid]
        phi = np.square(o.loc[ids, obs.obsnme] * obs.set_index("obsnme").final_weight).sum(axis=1)
        passed = len(ids) / design["members"] >= .98
        rounds.append(dict(iteration=i, retained=len(ids), passed=passed, min_phi=phi.min(), median_phi=phi.median()))
        if passed:
            candidates.extend((value, i, name, p.loc[name, b.pest_name]) for name, value in phi.items())
        if i >= design["updates"]-1 and len(ids):
            pos = (p.loc[ids, active.index]-active.lower)/(active.upper-active.lower)
            for name in active.index:
                x = pos[name]
                boundary.append(dict(iteration=i, parameter=active.loc[name, "name"], members=len(ids),
                    near_lower=x.le(.02).mean(), near_upper=x.ge(.98).mean(),
                    severe_lower=x.le(.005).mean(), severe_upper=x.ge(.995).mean()))
    pd.DataFrame(rounds).to_csv(RUN / "round_quality.csv", index=False)
    pd.DataFrame(boundary).to_csv(RUN / "parameter_boundary_round3_4.csv", index=False)
    assert candidates, "No round met 98% member retention"
    score, iteration, member, row = min(candidates, key=lambda x: x[:3])
    values = trial.values_for(b, dict(zip(b.name, row)))
    out = RUN / "selected_deterministic"
    out.mkdir()
    for s in SEASONS:
        d = design["datasets"][s]
        assert verify_calibrated_input_bundle(d["path"]).manifest_sha256 == d["manifest_sha256"]
    compared = evaluate(RUN, out, trial.contexts(RUN, design, b, SEASONS), values, obs)
    phi = float(compared.phi_contribution.sum())
    assert np.isclose(score, phi, rtol=1e-6, atol=1e-8), (score, phi)
    best = RUN / "best_calibration_parameters.csv"
    pd.Series(values, name="value").to_csv(best, index_label="name")
    compared.to_csv(RUN / "calibration_comparison.csv", index=False)
    diagnostics = pd.read_csv(RUN / "diagnostic_observations.csv").fillna("")
    pd.concat([extract(out / s, diagnostics[diagnostics.season_id.eq(s)], strict=False) for s in SEASONS],
              ignore_index=True).to_csv(RUN / "diagnostic_comparison.csv", index=False)
    by_season = {s: float(q.phi_contribution.sum()) for s, q in compared.groupby("season_id")}
    native.write(RUN / "selection.json", dict(iteration=iteration, member=member, phi=phi, phi_by_season=by_season,
                 calibration_seasons=list(SEASONS), validation_seasons=[], parameters_sha256=native.sha(best)))
    trial.status(RUN, "completed", selected_phi=phi, selected_iteration=iteration, selected_member=member,
                 retained=rounds[-1]["retained"], all_rounds_passed=all(r["passed"] for r in rounds),
                 engineering_status=trial.read(work / "run_status.json")["engineering_status"],
                 scientific_status="science_pending_trial")


def main():
    RUN.mkdir(exist_ok=True)
    if (RUN / "design.json").exists():
        raise FileExistsError(RUN)
    try:
        trial.status(RUN, "preparing")
        design, b, obs = prepare()
        params, outputs, base = initial_ensemble(design, b, obs)
        design.update(initial_members=len(params), initial_ensemble_base=base)
        native.write(RUN / "design.json", design)
        native.write(RUN / "sealed_design.json", dict(sha256=native.sha(RUN / "design.json")))
        build_case(design, b, obs, params, outputs)
        trial.status(RUN, "running", phase="pest_ies", initial_members=len(params), n_targets=len(obs))
        with (RUN / "parallel_controller.log").open("wb") as log:
            subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools/parallel/run_parallel.py"),
                "--run-dir", str(RUN / "joint"), "--case", "joint", "--mode", "ies",
                "--n-agents", str(design["workers"]), "--wait"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        assert trial.read(RUN / "joint/run_status.json")["status"] == "completed"
        trial.status(RUN, "postprocessing")
        finalize(design, b, obs, params)
    except Exception as exc:
        phase = trial.read(RUN / "pipeline_status.json")["status"]
        trial.status(RUN, "failed", phase=phase, error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--forward", type=Path)
    args = parser.parse_args()
    if args.forward:
        forward(args.forward)
    else:
        main()
