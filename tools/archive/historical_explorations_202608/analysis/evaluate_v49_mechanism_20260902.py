"""Deterministic v49 scores and stage diagnostics; no plotting or promotion."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/analysis"))
from tools.calibration.run_v49_mechanism_multiarm_20260902 import (
    OUT, ARMS, ITERATIONS, paths, deterministic, anchor_values, parse_outputs, dump,
)
from render_arm_d_best17_diagnostics_20260820 import (
    build_season_harvest_compare, build_season_process_compare, compute_metrics,
)
from audit_v46_best71_early_nstress_20260831 import parse_plantgro


def score(o, s):
    o, s = np.asarray(o, float), np.asarray(s, float)
    valid = np.isfinite(o) & np.isfinite(s) & (o != -99) & (s != -99)
    return {"n": int(valid.sum()), **compute_metrics(o[valid], s[valid])}


def mechanism_diagnostics(dest, params):
    """Use actual daily stress outputs and explicit approximations, not RNITP fiction."""
    rows = []
    for season in ("25SP", "26SP"):
        sdir = dest / "_seasons" / season
        pg = parse_plantgro(sdir / "PlantGro.OUT")
        assert pg.groupby("global_run").DAP.apply(lambda x: x.diff().dropna().eq(1).all()).all()
        pg["SWFAC_from_daily_WSPD"] = 1 - pg.WSPD
        pg["TURFAC_from_daily_WSGD"] = 1 - pg.WSGD
        pg["NSTRES_from_daily_NSTD"] = 1 - pg.NSTD
        # LN%D is total-mass PCNL, not structural-mass RNITP. Since reserves
        # reduce the RNITP denominator, PCNL>=FNPGN2 provides only a lower-
        # bound saturation screen; a lower PCNL does not prove curve coverage.
        pg["PCNL_ge_FNPGN2_lower_bound"] = pg["LN%D"] >= round(params["fnpgn2"], 2)
        sw = parse_plantgro(sdir / "SoilWat.OUT")
        inp = (sdir / "DSSAT48.INP").read_text(encoding="utf-8", errors="replace").splitlines()
        start = next(i for i, line in enumerate(inp) if line.startswith("*SOIL"))
        layers = []
        for line in inp[start + 4:]:
            if not line.strip():
                break
            # Effective DSSAT soil layer fields, not arbitrary SOL profile.
            layers.append((float(line[:6]), float(line[12:18]), float(line[18:24])))
        expected = [c for c in sw if re.fullmatch(r"SW\d+D", c)]
        assert len(layers) == len(expected), "effective layer / SW output mismatch"
        depth = round(params["dswbar"], 3)
        actual, potential, top = np.zeros(len(sw)), 0., 0.
        for i, (bottom, ll, dul) in enumerate(layers, 1):
            dz = max(0., min(bottom, depth) - top)
            if dz > 0:
                actual += (sw[f"SW{i}D"].to_numpy(float) - ll) * dz
                potential += (dul - ll) * dz
            top = bottom
        assert potential > 0
        sw["SWBAR_from_rounded_daily_output"] = np.clip(actual / potential, 0, 1)
        pg = pg.merge(sw[["global_run", "YEAR", "DOY", "SWBAR_from_rounded_daily_output"]],
                      on=["global_run", "YEAR", "DOY"], how="left", validate="one_to_one")
        assert pg.SWBAR_from_rounded_daily_output.notna().all()
        pg.to_csv(dest / f"{season}_mechanism_daily.csv", index=False)
        for run, group in pg.groupby("global_run"):
            for variable in ("SWFAC_from_daily_WSPD", "TURFAC_from_daily_WSGD", "SWBAR_from_rounded_daily_output", "LN%D", "NSTD"):
                series = group[variable]
                rows.append({"season": season, "local_run": run, "variable": variable,
                             "min": series.min(), "p10": series.quantile(.1), "median": series.median(),
                             "p90": series.quantile(.9), "max": series.max(), "n": len(series),
                             "pcnl_ge_fnpgn2_fraction": group.PCNL_ge_FNPGN2_lower_bound.mean()})
    pd.DataFrame(rows).to_csv(dest / "mechanism_ranges.csv", index=False)
    dump(dest / "mechanism_caveats.json", {
        "SWBAR": "ratio of depth-integrated SW-LL to DUL-LL to DSWBAR, clipped0..1; reconstructed from rounded daily OUTPUT and effective DSSAT48.INP layers. Not exact within-day PODS state.",
        "PCNL": "LN%D is PCNL, not RNITP. PCNL>=FNPGN2 is a one-sided saturation indicator only. No AGEFAC reconstructed without structural carbon reserves.",
        "source": ["https://github.com/DSSAT/dssat-csm-os/blob/develop/Plant/CROPGRO/PODS.for", "https://github.com/DSSAT/dssat-csm-os/blob/develop/Plant/CROPGRO/Opgrow.for"],
        "version_caveat": "mechanism reference is open source develop; production remains unchanged official local4.8.5 executable"})


def evaluate(arm, dest, params):
    case, run, _, _ = paths(arm)
    metrics = []
    for season in ("25SP", "26SP"):
        sdir = dest / "_seasons" / season
        harvest = build_season_harvest_compare(sdir, season)
        for variable in ("FRESH_INC", "FRESH_CUM", "DRY_CUM"):
            metrics.append({"season": season, "variable": variable, **score(harvest[f"OBS_{variable}"], harvest[f"SIM_{variable}"])})
        terminal = harvest.sort_values("DATE").groupby("TN").tail(1)
        terminal_metric = score(terminal.OBS_FRESH_CUM, terminal.SIM_FRESH_CUM)
        terminal_metric.pop("nse", None)  # terminal treatments: RRMSE, not NSE
        metrics.append({"season": season, "variable": "FRESH_TERMINAL", **terminal_metric})
        process = build_season_process_compare(sdir, season)
        assert process.SIM_DATE_GAP_DAYS.eq(0).all(), "process date mismatch"
        for variable in ("LAID", "LWAD", "SWAD", "CHTD"):
            oc, sc = f"OBS_{variable}", f"SIM_{variable}"
            valid = process.loc[process[oc].ne(-99) & process[sc].ne(-99)].copy()
            dates = sorted(valid.DATE.unique())
            for phase, days in {"all": dates, "early": dates[:1], "middle": dates[1:-2], "late": dates[-2:]}.items():
                g = valid[valid.DATE.isin(days)]
                if len(g):
                    metrics.append({"season": season, "variable": variable if phase == "all" else f"{variable}_{phase}", **score(g[oc], g[sc])})
    simulated = parse_outputs(run, case, dest)
    pst = pyemu.Pst(str(run / f"{case}.pst"))
    residual_phi = ((simulated - pst.observation_data.obsval) * pst.observation_data.weight) ** 2
    registry = pd.read_csv(run / f"{case}_observation_registry.csv").set_index("obsnme")
    registry.index = registry.index.str.lower()
    registry["simulated"] = simulated
    registry["actual_phi"] = residual_phi
    mapping = pd.read_csv(ROOT / "configs/runs/e02_mapping_26sp_w2_w1_20260830.csv")
    meta = mapping.set_index(["season_id", "treatment"])
    for token, dim in (("NRESPS", "water_level"), ("WRESPS", "nitrogen_level")):
        frame = registry[registry.sim_token.eq(token)].copy()
        frame["stratum"] = [meta.loc[(r.season_id, int(r.treatment)), dim] for r in frame.itertuples()]
        for (season, stratum), g in frame.groupby(["season_id", "stratum"]):
            metrics.append({"season": season, "variable": f"{token}_{stratum}", **score(g.raw_obsval, g.simulated)})
    registry.to_csv(dest / "objective_residuals.csv")
    registry.groupby(["season_id", "sim_token"]).actual_phi.sum().to_csv(dest / "phi_by_season_token.csv")
    result = pd.DataFrame(metrics)
    result.to_csv(dest / "fit_metrics.csv", index=False)
    mechanism_diagnostics(dest, params)
    return result


def guard(candidate, reference):
    a = candidate.set_index(["season", "variable"])
    b = reference.set_index(["season", "variable"])
    checks = []
    for season in ("25SP", "26SP"):
        for variable in ("FRESH_CUM", "LAID"):
            delta = a.loc[(season, variable), "nse"] - b.loc[(season, variable), "nse"]
            checks.append({"season": season, "metric": variable + "_nse", "delta": delta, "pass": bool(delta >= -.03)})
        rrmse = a.loc[(season, "FRESH_TERMINAL"), "rrmse_pct"]
        delta = rrmse - b.loc[(season, "FRESH_TERMINAL"), "rrmse_pct"]
        checks.append({"season": season, "metric": "terminal_rrmse_pct", "value": rrmse, "delta": delta, "pass": bool(rrmse <= 25 and delta <= 3)})
    return {"scale_canopy_pass": all(x["pass"] for x in checks), "checks": checks,
            "promotion": "NOT automatic; also inspect N/W strata, non-N0 gradient, and stage scores"}


def mechanism_gate(arm, candidate, reference):
    a = candidate.set_index(["season", "variable"])
    b = reference.set_index(["season", "variable"])
    response_rows = []
    for key in a.index:
        if key[1].startswith(("NRESPS_", "WRESPS_")):
            response_rows.append({"season": key[0], "variable": key[1],
                 "rmse_improvement_fraction": 1 - a.loc[key, "rmse"] / b.loc[key, "rmse"]})
    n26 = [r["rmse_improvement_fraction"] for r in response_rows if r["season"] == "26SP" and r["variable"].startswith("NRESPS_")]
    water = [r["rmse_improvement_fraction"] for r in response_rows if r["variable"].startswith("WRESPS_")]
    n_improved = sum(r["rmse_improvement_fraction"] > 0 for r in response_rows if r["variable"].startswith("NRESPS_"))
    late = 1 - a.loc[("26SP", "LAID_late"), "rmse"] / b.loc[("26SP", "LAID_late"), "rmse"]
    target = None
    if arm.startswith(("B_", "C_", "D_")):
        target = bool(np.mean(n26) >= .15 and n_improved >= 3 and min(water) >= -.10)
    elif arm.startswith("E_"):
        target = bool(late >= .15 and a.loc[("25SP", "LAID_early"), "rmse"] <= 1.1 * b.loc[("25SP", "LAID_early"), "rmse"])
    elif arm.startswith(("F_", "G_")):
        target = bool(np.mean(water) >= .15 and min(n26) >= -.10)
    return {"mechanism_target_pass": target, "response_changes": response_rows,
            "26SP_late_LAI_rmse_improvement_fraction": late,
            "note": "Exploratory gate, not independent validation. Inspect non-N0 signed gradients and CV phi before promotion."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arm", choices=list(ARMS))
    p.add_argument("--anchor", action="store_true")
    args = p.parse_args()
    if args.anchor:
        evaluate("A_ic_control", OUT / "A_ic_control/anchor", anchor_values())
        return
    arm = args.arm
    case, run, _, _ = paths(arm)
    phi = pd.read_csv(run / f"{case}.phi.actual.csv").iloc[-1]
    par = pd.read_csv(run / f"{case}.{ITERATIONS}.par.csv", index_col=0)
    par.index = par.index.astype(str)
    candidates = [name for name in par.index if name in phi.index and np.isfinite(float(phi[name]))]
    member = min(candidates, key=lambda name: float(phi[name]))
    values = {name.lower(): float(v) for name, v in par.loc[member].items()}
    dest, _ = deterministic(arm, "lowest_phi", values)
    metrics = evaluate(arm, dest, values)
    references = {"fixed_member55": OUT / "A_ic_control/anchor/fit_metrics.csv"}
    if arm != "A_ic_control":
        references["IC_only_A"] = OUT / "A_ic_control/lowest_phi/fit_metrics.csv"
    gates = {name: {**guard(metrics, pd.read_csv(file)), **mechanism_gate(arm, metrics, pd.read_csv(file))} for name, file in references.items()}
    dump(OUT / arm / "candidate_summary.json", {"member": member, "iteration": ITERATIONS,
         "ensemble_phi": float(phi[member]), "gates": gates, "deterministic_dir": str(dest)})
    summaries = []
    for label in ARMS:
        source = OUT / label / "candidate_summary.json"
        if source.exists():
            summaries.append({"arm": label, **json.loads(source.read_text(encoding="utf-8"))})
    dump(OUT / "results_summary.json", summaries)


if __name__ == "__main__":
    main()
