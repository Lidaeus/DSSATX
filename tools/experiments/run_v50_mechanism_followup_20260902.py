"""Small deterministic follow-up, never IES, never overwrite historical runs."""
from __future__ import annotations
import argparse
import itertools
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.calibration.run_v49_mechanism_multiarm_20260902 import (
    OUT as OLD, anchor_values, paths, logged, parse_outputs, dump, sha,
)
from tools.analysis.evaluate_v49_mechanism_20260902 import evaluate, guard, mechanism_gate
from src.common.param_registry import PHYSICAL_BOUNDS

OUT = ROOT / "workspace/reports/v50_mechanism_followup_20260902"


def member(arm, iteration, number):
    case, run, _, _ = paths(arm)
    frame = pd.read_csv(run / f"{case}.{iteration}.par.csv", index_col=0)
    frame.index = frame.index.astype(str)
    return {str(k).lower(): float(v) for k, v in frame.loc[str(number)].items()}


def plan():
    control = member("A_ic_control", 3, 47)
    tasks = []
    for arm, iteration, number in [("E_canopy", 2, 3), ("E_canopy", 3, 56), ("D_leaf_n_photo", 2, 20)]:
        tasks.append(dict(label=f"replay_{arm[0]}_i{iteration}_m{number}", arm=arm,
                          kind="replay", iteration=iteration, member=number,
                          values=member(arm, iteration, number)))
    def probe(label, changes):
        tasks.append(dict(label=label, arm="A_ic_control", kind="probe", changes=changes,
                          values={**control, **changes}))
    probe("control_A47", {})
    for x in (.35, .50, .70):
        probe(f"nstfac_{x:.2f}", {"nstfac": x})
    for a, b in itertools.product((.9, 1.35, 1.8), (2.6, 3.3, 4.2)):
        probe(f"photo_{a:.2f}_{b:.2f}", {"fnpgn1": a, "fnpgn2": b})
    probe("uptake_01107", {"rtno3": .01107})
    for a in (.9, 1.35, 1.8):
        probe(f"photo_uptake_{a:.2f}_3.30", {"fnpgn1": a, "fnpgn2": 3.3, "rtno3": .01107})
    for t in tasks:
        v = t["values"]
        assert set(v) == set(anchor_values())
        assert all(.4 <= v[k] <= .8 for k in ("icns_25sp", "icns_26sp"))
        if t["kind"] == "probe":
            assert all(v[k] == control[k] for k in v if k not in t["changes"])
            for k, value in t["changes"].items():
                lo, hi = PHYSICAL_BOUNDS[k.upper()]
                assert lo <= value <= hi, (k, value)
        assert v["fnpgn1"] < v["fnpgn2"]
    return tasks


def verify_seal():
    seal = json.loads((OLD / "execution_seal.json").read_text(encoding="utf-8"))
    for item in seal["files"]:
        assert sha(Path(item["path"])) == item["sha256"], item["path"]


def gradients(dest):
    """Raw non-N0 gradients, never monotonic projection; paired on actual date."""
    meta = pd.read_csv(ROOT / "configs/runs/e02_mapping_26sp_w2_w1_20260830.csv")
    meta = meta[meta.season_id.eq("26SP")][["treatment", "water_level", "nitrogen_level"]]
    rows, spread, excluded = [], [], []
    sdir = dest / "_seasons/26SP"
    for variable, filename in [("FRESH_CUM", "harvest"), ("LAID", "process")]:
        frame = pd.read_csv(sdir / f"26SP_deterministic_{filename}_compare.csv")
        frame = frame.merge(meta, left_on="TN", right_on="treatment", validate="many_to_one")
        assert not frame.water_level.isna().any()
        for (water, date), group in frame.groupby(["water_level", "DATE"]):
            g = group[group.nitrogen_level.isin(["N1", "N2", "N3"])].set_index("nitrogen_level")
            assert set(g.index) == {"N1", "N2", "N3"} and len(g) == 3
            o, s = g[f"OBS_{variable}"], g[f"SIM_{variable}"]
            if not np.isfinite(s).all() or (s == -99).any():
                raise ValueError("Invalid simulated gradient pair")
            if not np.isfinite(o).all() or (o == -99).any():
                excluded.append(dict(variable=variable, water=water, date=date,
                                     reason="missing observed nonN0 value; no imputation"))
                continue
            for high, low in [("N2", "N1"), ("N3", "N2"), ("N3", "N1")]:
                observed, simulated = o[high]-o[low], s[high]-s[low]
                rows.append(dict(variable=variable, water=water, date=date, contrast=f"{high}-{low}",
                                 observed=observed, simulated=simulated, residual=simulated-observed))
            spread.append(dict(variable=variable, water=water, date=date,
                               observed_cv_pct=100*o.std(ddof=0)/o.mean(),
                               simulated_cv_pct=100*s.std(ddof=0)/s.mean(),
                               observed_monotone=bool(o.N1 <= o.N2 <= o.N3),
                               simulated_monotone=bool(s.N1 <= s.N2 <= s.N3)))
    pd.DataFrame(rows).to_csv(dest / "26SP_nonN0_gradients.csv", index=False)
    pd.DataFrame(spread).to_csv(dest / "26SP_nonN0_spread.csv", index=False)
    pd.DataFrame(excluded).to_csv(dest / "26SP_gradient_exclusions.csv", index=False)


def injection_audit(dest, values):
    result = []
    for season in ("25SP", "26SP"):
        lines = (dest / f"_seasons/{season}/TMGRO048.SPE").read_text().splitlines()
        curve = next(l for l in lines if "FNPGN(4)" in l).split()
        stress = next(l for l in lines if "XPODF," in l).split()
        uptake = next(l for l in lines if "RTNO3,RTNH4" in l).split()
        for name, actual, decimals in [("fnpgn1", float(curve[0]), 2), ("fnpgn2", float(curve[1]), 2),
                                       ("nstfac", float(stress[1]), 3), ("rtno3", float(uptake[0]), 4)]:
            tolerance = .5 * 10**(-decimals) + 1e-9
            assert abs(actual-values[name]) <= tolerance, (name, actual, values[name])
            result.append(dict(season=season, name=name, requested=values[name], actual=actual))
    pd.DataFrame(result).to_csv(dest / "injection_audit.csv", index=False)


def execute(task, resume_analysis=False):
    dest = OUT / task["label"]
    if (dest / "completed.json").exists():
        assert json.loads((dest / "task.json").read_text()) == task
        return
    existed = dest.exists()
    if existed and not resume_analysis:
        raise FileExistsError(f"Inspect incomplete run before resuming: {dest}")
    verify_seal()
    if existed:
        assert json.loads((dest / "task.json").read_text()) == task
        assert (dest / "parsed_observations.csv").exists()
    else:
        dest.mkdir(parents=True)
        dump(dest / "task.json", task)
    values, arm = task["values"], task["arm"]
    pd.DataFrame(values.items(), columns=["name", "value"]).to_csv(dest / "params.csv", index=False)
    case, run, design, _ = paths(arm)
    if not existed:
        logged([sys.executable, str(ROOT / "src/calibration/run_multiseason.py"), "--design", str(design),
            "--param-csv", str(dest / "params.csv"), "--prefix", task["label"], "--harvest-var", "CHFPW",
            "--keep-nitrogen-outputs", "--keep-soil-water", "--observation-transform-config",
                str(run / f"{case}.observation_transforms.json")], dest / "run.log", cwd=dest)
    predicted = parse_outputs(run, case, dest)
    predicted.to_csv(dest / "parsed_observations.csv")
    injection_audit(dest, values)
    fit = evaluate(arm, dest, values)
    gradients(dest)
    checks = {}
    for label, refdir in [("v48_55", OLD / "A_ic_control/anchor"), ("A47", OLD / "A_ic_control/lowest_phi")]:
        ref = pd.read_csv(refdir / "fit_metrics.csv")
        checks[label] = {**guard(fit, ref), **mechanism_gate("E_canopy" if arm == "E_canopy" else "D_leaf_n_photo", fit, ref)}
    difference = None
    if task["kind"] == "replay":
        obs = pd.read_csv(run / f"{case}.{task['iteration']}.obs.csv", index_col=0)
        obs.index = obs.index.astype(str)
        expected = obs.loc[str(task["member"]), predicted.index].astype(float)
        difference = float((predicted-expected).abs().max())
        np.testing.assert_allclose(predicted, expected, atol=5.1e-5, rtol=1e-8)
    if task["label"] == "control_A47":
        expected = parse_outputs(run, case, OLD / "A_ic_control/lowest_phi")
        np.testing.assert_allclose(predicted, expected, atol=1e-9, rtol=0)
    verify_seal()
    dump(dest / "completed.json", dict(status="completed", checks=checks, replay_max_difference=difference,
                                       n_observations=len(predicted), scientific_promotion=False,
                                       execution_script_sha256=sha(Path(__file__))))
    print("COMPLETED " + task["label"], flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", action="store_true")
    p.add_argument("--resume-analysis", action="store_true", help="Re-analyze inspected complete model outputs only")
    args = p.parse_args()
    tasks = plan()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = OUT / "plan.json"
    payload = dict(tasks=tasks, mode="deterministic_only_no_IES", reference_bounds="existing frozen v49",
                   profile_exception="NSTFAC .50/.70 are explicit deterministic physical-bound probes, not new IES bounds",
                   source_script_sha256=sha(Path(__file__)), weight_change=False,
                   initial_n_scale="relative to existing bundles, 26SP already x0.34, floors preserved")
    if manifest.exists():
        previous = json.loads(manifest.read_text())
        assert {k:v for k,v in previous.items() if k != "source_script_sha256"} == {k:v for k,v in payload.items() if k != "source_script_sha256"}
    else:
        dump(manifest, payload)
    if args.run:
        for task in tasks:
            execute(task, args.resume_analysis)
        dump(OUT / "status.json", dict(status="completed", runs=len(tasks), official_exe_sha256=sha(ROOT / "DSCSM048.EXE")))
    else:
        print(f"VALIDATED PLAN: {len(tasks)} two-season deterministic runs")


if __name__ == "__main__":
    main()
