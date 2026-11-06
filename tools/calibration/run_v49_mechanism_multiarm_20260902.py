"""Paired local mechanism experiments; no edits to source bundles or old runs.

prepare -> build/audit -> deterministic preflight -> sequential six-worker queue.
All non-arm parameters, including soil and seedling parameters, use v48 #55.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu
from scipy.stats import qmc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.param_registry import assert_valid_frozen_bounds

TAG = "v49_mechanism_20260902"
OUT = ROOT / "workspace/reports" / TAG
BASE_DESIGN = ROOT / "configs/runs/e02_formal_v48_n_gradient_water2x_20260902.json"
BASE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v48_n_gradient_water2x_formal_20260902.csv"
ANCHOR = ROOT / "workspace/reports/e02_formal_v48_20260902_candidates/lowest_phi_params.csv"
OLD_CASE = "e02_formal_v48_n_gradient_water2x_200x4_20260902"
OLD_RUN = ROOT / "workspace/runs" / (OLD_CASE + "_r2")
OBS = ROOT / "configs/runs/e02_formal_v47_free_nscale_observation_policy_20260901.csv"
COMMON = {"icns_25sp": (0.4, 0.8), "icns_26sp": (0.4, 0.8)}
ARMS = {
    "A_ic_control": {},
    "B_n_uptake": {"rtno3": (0.008, 0.035), "rtnh4": (0.015, 0.05)},
    "C_n_demand": {"nstfac": (0.15, 0.35), "prolfi": (0.20, 0.28), "prolfg": (0.13, 0.20)},
    "D_leaf_n_photo": {"fnpgn1": (0.9, 1.8), "fnpgn2": (2.2, 4.2)},
    "E_canopy": {"slavr": (185., 240.), "lfmax": (1.6, 2.), "frlff": (0.15, 0.5), "senrte": (1.5, 4.5)},
    "F_water_podset": {"swfac_rec": (0.3, 1.), "yswfac_mid": (0., 1.)},
    "G_water_fill": {"trfac_xmid": (0.1, 0.7), "ytrfac_max": (0., 0.3)},
}
NEW_DEFAULTS = {"swfac_rec": 1., "yswfac_mid": 1., "trfac_xmid": .5, "ytrfac_max": 0.}
REALS, ITERATIONS, SEED = 60, 3, 20260902


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paths(arm):
    case = f"e02_v49_{arm.lower()}_60x3_20260902"
    bounds_id = f"eggplant_e02_v49_{arm.lower()}_20260902"
    return case, ROOT / "workspace/runs" / case, ROOT / "configs/runs" / (case + ".json"), bounds_id


def logged(cmd, log, cwd=ROOT):
    log.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1",
           "DSSAT_CUSTOM_EXE": str(ROOT / "DSCSM048.EXE"),
           "DSSAT_SPE_BASE": str(ROOT / "data/templates/genotype/TMGRO048.SPE.base")}
    with log.open("w", encoding="utf-8") as handle:
        result = subprocess.run(cmd, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"exit {result.returncode}: {log}")


def anchor_values():
    frame = pd.read_csv(ANCHOR)
    return {**dict(zip(frame.name.str.lower(), frame.value)), **NEW_DEFAULTS}


def make_bounds(arm):
    base = pd.read_csv(BASE_BOUNDS).fillna("")
    base.name = base.name.str.lower()
    anchor = anchor_values()
    for name, val in NEW_DEFAULTS.items():
        base.loc[len(base)] = {**{c: "" for c in base.columns}, "name": name,
            "init": val, "lower": 0., "upper": 1., "status": "fixed",
            "location": "SPE", "file": "TMGRO048.SPE.base", "pargp": "SPE_WaterResponse", "mode": "both"}
    base["init"] = base.name.map(anchor)
    if base.init.isna().any() or base.name.duplicated().any():
        raise ValueError("missing or duplicate anchor parameters")
    base["status"] = "fixed"
    base["source_lower"] = base["lower"]
    base["source_upper"] = base["upper"]
    base["lower"] = base["init"]
    base["upper"] = base["init"]
    base["review_note"] = "v49: fixed to v48 iteration4 member55 except explicit arm whitelist"
    active = {**COMMON, **ARMS[arm]}
    for name, (lower, upper) in active.items():
        mask = base.name.eq(name)
        assert mask.sum() == 1 and lower <= anchor[name] <= upper
        base.loc[mask, ["lower", "upper", "status"]] = [lower, upper, "active"]
    return base


def prepare():
    if (OUT / "suite_manifest.json").exists():
        raise FileExistsError("suite already prepared; use --build or --run, do not overwrite")
    records = []
    for arm in ARMS:
        case, run, design_path, bounds_id = paths(arm)
        if run.exists() and any(run.iterdir()):
            raise FileExistsError(run)
        bounds = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / (bounds_id + ".csv")
        proposal = ROOT / "data/parameter_registry/bounds_proposals" / (bounds_id + ".csv")
        frame = make_bounds(arm)
        if bounds.exists():
            pd.testing.assert_frame_equal(pd.read_csv(bounds).fillna(""), frame.reset_index(drop=True), check_dtype=False)
        proposal.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(proposal, index=False)
        assert_valid_frozen_bounds(proposal)
        frame.to_csv(bounds, index=False)
        assert_valid_frozen_bounds(bounds)
        design = json.loads(BASE_DESIGN.read_text(encoding="utf-8"))
        for obsolete in ("bounds_id_after_approval", "approval_blockers", "prepared_from_proposal", "seasonal_parameterization_after_approval"):
            design.pop(obsolete, None)
        design.update(design_id=case, bounds_id=bounds_id, bounds_proposal=str(proposal.relative_to(ROOT)),
                      bounds_sha256=sha(bounds), source_design=str(BASE_DESIGN.relative_to(ROOT)),
                      source_design_id=json.loads(BASE_DESIGN.read_text(encoding="utf-8"))["design_id"],
                      source_run=str(OLD_RUN.relative_to(ROOT)),
                      purpose=f"v49 local mechanism arm {arm}; source/sink and non-arm parameters fixed")
        design["parameter_anchor"] = {"iteration": 4, "member": 55, "parameter_csv": str(ANCHOR.relative_to(ROOT)), "sha256": sha(ANCHOR), "selection": "explicit v48 member55, not a science promotion"}
        design["pest_ies"] = {"num_reals": REALS, "noptmax": ITERATIONS, "agents": 6, "random_seed": SEED,
                              "initial_ensemble": "paired per-parameter LHS: 59 stochastic rows plus base"}
        design["initial_nitrogen_scaling"]["bounds"] = [.4, .8]
        design["initial_nitrogen_scaling"]["interpretation"] = "multipliers of existing bundles, not original measured profiles; 26SP base already x0.34; floors remain"
        design["acceptance"] = {"prebuild": ["exact arm active whitelist", "all other values member55", "objective identical to v48", "paired ICNS priors and observation noise", "actual instruction smoke"],
                                "science": ["compare with both fixed member55 and A", "fresh cumulative NSE loss <=0.03 each season", "terminal fresh RRMSE <=25% and increase <=3 percentage points", "LAI NSE loss <=0.03 each season", "no automatic promotion; mechanism-specific residual and stage review"]}
        seedling = design.get("seedling_parameterization", {})
        seedling["implementation_gate"] = "implemented and regression tested; PAGE/PENV fixed to member55 in v49"
        for term in seedling.get("terms", []):
            term["init"] = anchor_values()[term["name"].lower()]
            term["status"] = "fixed"
        seedling["expected_initial_projection"] = {s: {p: round(anchor_values()[f"{p.lower()}_{s.lower()}"]) for p in ("PAGE", "PENV")} for s in ("25SP", "26SP")}
        design["active_parameters"] = {**COMMON, **ARMS[arm]}
        dump(design_path, design)
        records.append({"arm": arm, "case": case, "run_dir": str(run), "bounds": str(bounds), "bounds_sha256": sha(bounds), "design": str(design_path), "design_sha256": sha(design_path), "active": design["active_parameters"]})
    dump(OUT / "suite_manifest.json", {"anchor": str(ANCHOR), "anchor_sha256": sha(ANCHOR), "arms": records,
         "execution": "sequential arms, six agents total", "executable_sha256": sha(ROOT / "DSCSM048.EXE")})


def paired_prior(pst):
    data = {}
    for name, row in pst.parameter_data.iterrows():
        if row.partrans == "fixed":
            data[name] = np.full(REALS, float(row.parval1))
        else:
            seed = SEED + int(hashlib.sha256(name.encode()).hexdigest()[:6], 16)
            u = qmc.LatinHypercube(d=1, seed=seed).random(REALS - 1)[:, 0]
            # Space-filling local search, including exact anchor as base.
            lo, hi = float(row.parlbnd), float(row.parubnd)
            values = np.exp(np.log(lo) + u * (np.log(hi) - np.log(lo))) if row.partrans == "log" else lo + u * (hi - lo)
            data[name] = np.r_[values, float(row.parval1)]
    frame = pd.DataFrame(data, index=[str(i) for i in range(REALS - 1)] + ["base"])
    frame.index.name = "real_name"
    return frame


def build():
    reference = pyemu.Pst(str(OLD_RUN / f"{OLD_CASE}.pst"))
    shared_ic = shared_noise = None
    for arm in ARMS:
        case, run, design, bounds_id = paths(arm)
        if (run / "v49_preflight_audit.json").exists():
            continue
        if run.exists() and any(run.iterdir()):
            raise FileExistsError(f"incomplete build requires inspection, not overwrite: {run}")
        # Legacy discovery does not discover fixed soil scalars. Explicitly
        # inject all non-arm values without collapsing this arm's active terms.
        fixed_csv = OUT / arm / "fixed_anchor_params.csv"
        fixed_csv.parent.mkdir(parents=True, exist_ok=True)
        frozen = make_bounds(arm)
        frozen.loc[frozen.status.eq("fixed"), ["name", "init"]].rename(columns={"init": "value"}).to_csv(fixed_csv, index=False)
        logged([sys.executable, str(ROOT / "src/calibration/build_pest.py"), "--mode", "eggplant_stage2",
                "--prefix", case, "--bounds-id", bounds_id, "--bounds-crop", "eggplant",
                "--multiseason-design", str(design), "--observation-policy-csv", str(OBS), "--fixed-from", str(fixed_csv),
                "--noptmax", str(ITERATIONS), "--ies-num-reals", str(REALS), "--random-seed", str(SEED),
                "--batch", "DSSBatch.v48", "--harvest-var", "CHFPW", "--param-review-mode", "off", "--out-dir", str(run)], OUT / arm / "build.log")
        pst = pyemu.Pst(str(run / f"{case}.pst"))
        expected = {**COMMON, **ARMS[arm]}
        active = pst.parameter_data[pst.parameter_data.partrans.ne("fixed")]
        assert set(pst.parameter_data.index) == set(anchor_values()), "incomplete parameter injection contract"
        assert set(active.index) == set(expected), (arm, list(active.index))
        for name, limits in expected.items():
            np.testing.assert_allclose(active.loc[name, ["parlbnd", "parubnd"]].astype(float), limits, rtol=1e-8)
        fixed = pst.parameter_data[pst.parameter_data.partrans.eq("fixed")]
        for name, row in fixed.iterrows():
            np.testing.assert_allclose(row.parval1, anchor_values()[name], rtol=1e-8, atol=1e-10)
        columns = ["obsval", "weight", "obgnme"]
        pd.testing.assert_frame_equal(reference.observation_data[columns].sort_index(), pst.observation_data[columns].sort_index(), check_exact=False, rtol=1e-9)
        prior = paired_prior(pst)
        prior.to_csv(run / "paired_prior.csv")
        ic = prior[list(COMMON)]
        noise_file = run / pst.pestpp_options["ies_observation_ensemble"]
        noise = pd.read_csv(noise_file, index_col=0).sort_index(axis=1)
        if shared_ic is not None:
            pd.testing.assert_frame_equal(ic, shared_ic)
            pd.testing.assert_frame_equal(noise, shared_noise)
        shared_ic, shared_noise = ic, noise
        pst.pestpp_options["ies_parameter_ensemble"] = "paired_prior.csv"
        pst.pestpp_options["ies_include_base"] = True
        pst.write(str(run / f"{case}.pst"), version=1)
        dump(run / "v49_preflight_audit.json", {"arm": arm, "active": expected, "fixed_count": len(fixed),
             "objective_matches_v48": True, "seed": SEED, "prior_sha256": sha(run / "paired_prior.csv"),
             "noise_sha256": sha(noise_file), "pst_sha256": sha(run / f"{case}.pst")})
        print(f"BUILT {arm}: {len(active)} active, {len(fixed)} fixed", flush=True)


def parse_outputs(run, case, det):
    pst = pyemu.Pst(str(run / f"{case}.pst"))
    frames = []
    for _, row in pst.model_output_data.iterrows():
        parsed = pyemu.pst.pst_utils.InstructionFile(str(run / row.pest_file)).read_output_file(str(det / row.model_file))
        if parsed is None:
            raise RuntimeError(row.model_file)
        frames.append(parsed)
    values = pd.concat(frames).obsval
    assert values.index.is_unique and set(values.index) == set(pst.observation_data.index)
    assert np.isfinite(values.to_numpy(float)).all()
    return values.reindex(pst.observation_data.index)


def deterministic(arm, label, values):
    case, run, design, _ = paths(arm)
    dest = OUT / arm / label
    if dest.exists():
        raise FileExistsError(dest)
    dest.mkdir(parents=True)
    params = dest / "params.csv"
    pd.DataFrame({"name": list(values), "value": list(values.values())}).to_csv(params, index=False)
    logged([sys.executable, str(ROOT / "src/calibration/run_multiseason.py"), "--design", str(design),
            "--param-csv", str(params), "--prefix", label, "--harvest-var", "CHFPW",
            "--keep-nitrogen-outputs", "--keep-soil-water", "--observation-transform-config",
            str(run / f"{case}.observation_transforms.json")], dest / "run.log", cwd=dest)
    values = parse_outputs(run, case, dest)
    values.to_csv(dest / "parsed_observations.csv")
    return dest, values


def smoke():
    base_dir = OUT / "A_ic_control/anchor"
    if (base_dir / "parsed_observations.csv").exists():
        case, run, _, _ = paths("A_ic_control")
        base = parse_outputs(run, case, base_dir)
    else:
        base_dir, base = deterministic("A_ic_control", "anchor", anchor_values())
    old_values = parse_outputs(OLD_RUN, OLD_CASE, ROOT / "workspace/reports/e02_formal_v48_20260902_candidates/run_lowest_phi")
    # Historical deterministic replay deliberately wrote raw harvest values;
    # current PEST smoke must use its declared log observation transform.
    registry = pd.read_csv(OLD_RUN / f"{OLD_CASE}_observation_registry.csv").set_index("obsnme")
    registry.index = registry.index.str.lower()
    for name in old_values.index:
        row = registry.loc[name]
        if str(row.get("transform", "raw")).lower() == "log":
            old_values.loc[name] = np.log((old_values.loc[name] + float(row.get("transform_offset", 0.))) / float(row.get("transform_reference", 1.)))
    np.testing.assert_allclose(base.reindex(old_values.index), old_values, rtol=1e-7, atol=1e-6)
    # All designs have the same observable contract, not just the dose family.
    for arm in ARMS:
        case, run, _, _ = paths(arm)
        values = parse_outputs(run, case, base_dir)
        np.testing.assert_allclose(base, values, rtol=0, atol=0)
    probes = []
    for arm, ranges in ARMS.items():
        if not ranges:
            continue
        values = anchor_values()
        values.update({name: (lo + hi) / 2 for name, (lo, hi) in ranges.items()})
        dest, predicted = deterministic(arm, "midpoint_probe", values)
        change = float(np.max(np.abs(predicted - base)))
        probes.append({"arm": arm, "max_observation_change": change, "changed": change > 1e-8, "path": str(dest)})
    dump(OUT / "smoke_audit.json", {"anchor_matches_v48": True, "n_observations": len(base), "probes": probes})
    print("SMOKE PASSED", flush=True)


def run_queue():
    if not (OUT / "execution_seal.json").exists():
        raise RuntimeError("sealed preflight required")
    seal = json.loads((OUT / "execution_seal.json").read_text(encoding="utf-8"))
    state_path = OUT / "queue_status.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"arms": {}}
    for i, arm in enumerate(ARMS):
        for item in seal["files"]:
            if sha(Path(item["path"])) != item["sha256"]:
                raise RuntimeError(f"preflight input changed: {item['path']}")
        screen_path = OUT / "water_curve_screen.json"
        screen = json.loads(screen_path.read_text(encoding="utf-8")) if screen_path.exists() else {}
        if arm in screen.get("deferred_arms", []):
            state["arms"][arm] = {"status": "deferred_negligible_effect", "reason": "paired boundary effects below practical screening tolerance; see water_curve_screen.json"}
            dump(state_path, state)
            continue
        if state["arms"].get(arm, {}).get("status") == "completed":
            continue
        case, run, _, _ = paths(arm)
        # Never restart an existing manager/history implicitly.
        if (run / f"{case}.phi.actual.csv").exists():
            raise FileExistsError(f"existing run needs explicit resume inspection: {run}")
        state.update(status="running", current_arm=arm, pid=os.getpid())
        state["arms"][arm] = {"status": "running", "run_dir": str(run), "port": 4260 + i}
        dump(state_path, state)
        try:
            logged([sys.executable, str(ROOT / "tools/parallel/run_parallel.py"), "--run-dir", str(run),
                    "--case", case, "--mode", "ies", "--n-agents", "6", "--port", str(4260 + i), "--wait"], OUT / arm / "parallel.log")
            phi = pd.read_csv(run / f"{case}.phi.actual.csv")
            if not (run / f"{case}.{ITERATIONS}.par.csv").exists():
                raise RuntimeError("requested final iteration absent; inspect early termination before proceeding")
            logged([sys.executable, str(ROOT / "tools/analysis/evaluate_v49_mechanism_20260902.py"), "--arm", arm], OUT / arm / "evaluation.log")
            state["arms"][arm].update(status="completed", final_min_phi=float(phi.iloc[-1]["min"]))
            dump(state_path, state)
        except Exception as exc:
            state.update(status="failed", error=str(exc))
            state["arms"][arm]["status"] = "failed"
            dump(state_path, state)
            raise
    state.update(status="completed", current_arm=None)
    dump(state_path, state)


def screen_water():
    comparisons = []
    for label, scale in (("anchor", None), ("low_ic", .4), ("high_ic", .8)):
        control = anchor_values()
        if scale is not None:
            control.update({name: scale for name in COMMON})
        if label == "anchor":
            case, run, _, _ = paths("A_ic_control")
            baseline = parse_outputs(run, case, OUT / "A_ic_control/anchor")
        else:
            path = OUT / "A_ic_control" / label
            case, run, _, _ = paths("A_ic_control")
            if (path / "parsed_observations.csv").exists():
                baseline = parse_outputs(run, case, path)
            else:
                _, baseline = deterministic("A_ic_control", label, control)
        probe = {**control, "swfac_rec": 1., "yswfac_mid": 0.}
        path = OUT / "F_water_podset" / ("boundary_" + label)
        case, run, _, _ = paths("F_water_podset")
        if (path / "parsed_observations.csv").exists():
            modified = parse_outputs(run, case, path)
        else:
            _, modified = deterministic("F_water_podset", "boundary_" + label, probe)
        pst = pyemu.Pst(str(run / f"{case}.pst"))
        effect_sse = float(np.sum(((modified - baseline) * pst.observation_data.weight) ** 2))
        comparisons.append({"initial_n": label, "maximum_observation_change": float(np.max(np.abs(modified - baseline))), "weighted_change_sse": effect_sse})
    deferred = ["F_water_podset"] if all(r["weighted_change_sse"] <= 1e-6 for r in comparisons) else []
    dump(OUT / "water_curve_screen.json", {"paired_probes": comparisons, "deferred_arms": deferred,
         "practical_effect_screen": "sum((weight * change_in_prediction)^2) <=1e-6 in all paired boundary probes",
         "interpretation": "Negligible effect is conditional on tested initial-N corners and fixed anchor, not proof of global insensitivity."})


def seal_preflight():
    if not (OUT / "smoke_audit.json").is_file() or not (OUT / "water_curve_screen.json").is_file():
        raise RuntimeError("deterministic preflight required")
    if not (OUT / "A_ic_control/anchor/fit_metrics.csv").is_file():
        raise RuntimeError("anchor evaluation required")
    files = [ANCHOR, ROOT / "DSCSM048.EXE", Path(__file__),
             ROOT / "tools/analysis/evaluate_v49_mechanism_20260902.py",
             ROOT / "src/calibration/run_multiseason.py", ROOT / "src/calibration/run_dssat.py",
             ROOT / "src/calibration/nitrogen_response.py", ROOT / "src/dssat/array_expander.py"]
    shared = None
    for arm in ARMS:
        case, run, design, bounds_id = paths(arm)
        pst_file = run / (case + ".pst")
        pst = pyemu.Pst(str(pst_file))
        prior = pd.read_csv(run / "paired_prior.csv", index_col=0)
        prior.index = prior.index.astype(str)
        assert len(prior) == REALS and prior.index.is_unique
        assert set(prior.columns) == set(anchor_values())
        noise = pd.read_csv(run / f"{case}.observation_ensemble.csv", index_col=0)
        noise.index = noise.index.astype(str)
        noise = noise.loc[[str(i) for i in range(REALS - 1)]].copy()
        noise.loc["base"] = pst.observation_data.loc[noise.columns, "obsval"].to_numpy(float)
        assert noise.index.equals(prior.index)
        if shared is not None:
            pd.testing.assert_frame_equal(noise, shared)
        shared = noise
        for name, row in pst.parameter_data.iterrows():
            v = prior[name]
            assert v.between(float(row.parlbnd) - 1e-10, float(row.parubnd) + 1e-10).all()
            if row.partrans == "fixed":
                np.testing.assert_allclose(v, anchor_values()[name], rtol=1e-8)
        noise.to_csv(run / "paired_noise.csv")
        pst.pestpp_options["ies_observation_ensemble"] = "paired_noise.csv"
        pst.write(str(pst_file), version=1)
        files += [pst_file, design, run / "paired_prior.csv", run / "paired_noise.csv",
                  ROOT / "data/parameter_registry/bounds_frozen/eggplant" / (bounds_id + ".csv")]
    files += list((ROOT / "data/templates/genotype").glob("TMGRO048.*.base"))
    dump(OUT / "execution_seal.json", {"status": "preflight_passed", "files": [{"path": str(p), "sha256": sha(p)} for p in files],
         "realizations": "59 stochastic + base =60; paired ICNS samples and observation noise by realization ID",
         "anchor_reproduction": "1432 outputs match v48 after applying its declared observation transform"})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepare", action="store_true")
    p.add_argument("--build", action="store_true")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--run", action="store_true")
    p.add_argument("--screen-water", action="store_true")
    p.add_argument("--seal", action="store_true")
    args = p.parse_args()
    if args.prepare: prepare()
    if args.build: build()
    if args.smoke: smoke()
    if args.screen_water: screen_water()
    if args.seal: seal_preflight()
    if args.run: run_queue()


if __name__ == "__main__":
    main()
