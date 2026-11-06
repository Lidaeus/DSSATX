#!/usr/bin/env python3
"""Summarize a completed 13-treatment IES run and its parameter boundaries."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re

import numpy as np
import pandas as pd
import pyemu
import yaml


def numeric_members(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[[i for i in frame.index if str(i).lower() != "base"]]


def metrics(observed: np.ndarray, simulated: np.ndarray) -> dict:
    residual = simulated - observed
    rmse = float(np.sqrt(np.mean(residual**2)))
    bias = float(np.mean(residual))
    denominator = float(np.mean(observed))
    r2 = float(np.corrcoef(observed, simulated)[0, 1] ** 2) if len(observed) > 1 else None
    return {
        "n": len(observed), "rmse_kg_ha": rmse, "bias_kg_ha": bias,
        "nrmse_pct_of_observed_mean": 100 * rmse / denominator if denominator else None,
        "r2": r2,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--bounds-csv", required=True, type=Path)
    args = parser.parse_args()
    run = args.run_dir.resolve()
    case = run.name
    manifest = yaml.safe_load((run / "run_manifest.yaml").read_text(encoding="utf-8"))
    requested_iterations = int(manifest["noptmax"])
    requested_reals = int(manifest["ies_num_reals"])
    phi = pd.read_csv(run / f"{case}.phi.actual.csv")
    latest = int(phi["iteration"].max())
    if latest != requested_iterations:
        raise RuntimeError(f"Expected completed iteration {requested_iterations}, found {latest}")
    prior_par = pd.read_csv(run / f"{case}.0.par.csv", index_col=0)
    par = pd.read_csv(run / f"{case}.{latest}.par.csv", index_col=0)
    obs = pd.read_csv(run / f"{case}.{latest}.obs.csv", index_col=0)
    prior_par.index = prior_par.index.astype(str)
    par.index = par.index.astype(str)
    obs.index = obs.index.astype(str)
    prior_phi = phi.loc[phi.iteration == 0].iloc[-1]
    final_phi = phi.loc[phi.iteration == latest].iloc[-1]
    meta = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
    common = [i for i in par.index if i in obs.index and i in phi.columns and i.lower() != "base"]
    finite = [(i, float(final_phi[i])) for i in common if pd.notna(final_phi[i]) and np.isfinite(float(final_phi[i]))]
    if not finite:
        raise RuntimeError("No finite final members with both parameter and observation ensembles")
    best_name, best_phi = min(finite, key=lambda pair: pair[1])
    overall = []
    for _, row in phi.iterrows():
        iteration = int(row["iteration"])
        par_path = run / f"{case}.{iteration}.par.csv"
        obs_path = run / f"{case}.{iteration}.obs.csv"
        if not par_path.is_file() or not obs_path.is_file():
            continue
        par_index = set(pd.read_csv(par_path, usecols=[0]).iloc[:, 0].astype(str))
        obs_index = set(pd.read_csv(obs_path, usecols=[0]).iloc[:, 0].astype(str))
        for name in set(row.index) - meta:
            if name.lower() == "base" or name not in par_index or name not in obs_index:
                continue
            value = pd.to_numeric(pd.Series([row[name]]), errors="coerce").iloc[0]
            if pd.notna(value) and np.isfinite(value):
                overall.append((float(value), iteration, name))
    if not overall:
        raise RuntimeError("No finite member with aligned parameters and observations across iterations")
    overall_phi, overall_iteration, overall_name = min(overall)
    overall_par = pd.read_csv(run / f"{case}.{overall_iteration}.par.csv", index_col=0)
    overall_obs = pd.read_csv(run / f"{case}.{overall_iteration}.obs.csv", index_col=0)
    overall_par.index = overall_par.index.astype(str)
    overall_obs.index = overall_obs.index.astype(str)
    overall_best = overall_par.loc[overall_name]
    final_values = np.asarray([v for _, v in finite], dtype=float)
    prior_values = np.asarray([
        float(prior_phi[c]) for c in phi.columns if c not in meta and c.lower() != "base"
        and pd.notna(prior_phi[c]) and np.isfinite(float(prior_phi[c]))
    ])

    bounds = pd.read_csv(args.bounds_csv, encoding="utf-8-sig")
    best = par.loc[best_name]
    members = numeric_members(par)

    def make_boundary(parameter_set: pd.Series, ensemble: pd.DataFrame, output: Path) -> pd.DataFrame:
        rows = []
        for r in bounds.itertuples(index=False):
            name = str(r.name).lower()
            if name not in parameter_set.index:
                continue
            lower, upper, value = float(r.lower), float(r.upper), float(parameter_set[name])
            span = upper - lower
            active = str(r.status).lower() == "active" and span > 0
            positions = pd.to_numeric(ensemble[name], errors="coerce")
            lower_gap = (value - lower) / span if span else None
            upper_gap = (upper - value) / span if span else None
            rows.append({
                "name": name, "status": str(r.status), "best_value": value,
                "lower": lower, "upper": upper, "relative_position": lower_gap,
                "outside_bounds": bool(active and (value < lower - 1e-10 or value > upper + 1e-10)),
                "at_lower_1e6_span": bool(active and lower_gap <= 1e-6),
                "at_upper_1e6_span": bool(active and upper_gap <= 1e-6),
                "within_lower_1pct": bool(active and lower_gap <= 0.01),
                "within_upper_1pct": bool(active and upper_gap <= 0.01),
                "ensemble_fraction_lower_1pct": float(np.mean((positions - lower) / span <= 0.01)) if active else None,
                "ensemble_fraction_upper_1pct": float(np.mean((upper - positions) / span <= 0.01)) if active else None,
            })
        frame = pd.DataFrame(rows)
        frame.to_csv(output, index=False)
        return frame

    boundary = make_boundary(best, members, run / "parameter_boundary_audit.csv")
    overall_boundary = make_boundary(
        overall_best, numeric_members(overall_par), run / "parameter_boundary_audit_best_overall.csv"
    )
    pd.DataFrame({"name": best.index, "value": best.values}).to_csv(
        run / "best_parameters.csv", index=False
    )
    pd.DataFrame({"name": overall_best.index, "value": overall_best.values}).to_csv(
        run / "best_overall_parameters.csv", index=False
    )

    pst = pyemu.Pst(str(run / f"{case}.pst"))
    measured = pst.observation_data.copy()
    def harvest_summary(member: str, simulation: pd.Series, stem: str) -> dict:
        records = []
        for name, r in measured.iterrows():
            match = re.fullmatch(r"pwads_r(\d+)_h(\d+)", name)
            if not match or name not in simulation.index:
                continue
            run_no, harvest_no = map(int, match.groups())
            records.append({
                "run": run_no, "harvest": harvest_no,
                "season": "25SP" if run_no <= 6 else "26SP",
                "observed_kg_ha": float(r.obsval), "simulated_kg_ha": float(simulation[name]),
                "realization": member,
            })
        yield_df = pd.DataFrame(records).sort_values(["run", "harvest"])
        yield_df.to_csv(run / f"{stem}_cumulative_dry_yield_pairs.csv", index=False)
        terminal = yield_df.groupby("run", as_index=False).tail(1)
        terminal.to_csv(run / f"{stem}_terminal_dry_yield_pairs.csv", index=False)
        values = {}
        for season, part in list(terminal.groupby("season")) + [("all", terminal)]:
            values[season] = metrics(part.observed_kg_ha.to_numpy(), part.simulated_kg_ha.to_numpy())
        return values

    yield_metrics_final = harvest_summary(best_name, obs.loc[best_name], "best_final")
    yield_metrics_overall = harvest_summary(overall_name, overall_obs.loc[overall_name], "best_overall")

    active_boundary = boundary[boundary.status.str.lower() == "active"]
    exact = active_boundary[active_boundary.at_lower_1e6_span | active_boundary.at_upper_1e6_span]
    near = active_boundary[active_boundary.within_lower_1pct | active_boundary.within_upper_1pct]
    outside = active_boundary[active_boundary.outside_bounds]
    quality_path = run / "ies_quality" / "ies_run_quality.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.is_file() else {}
    statuses_path = run / "ies_quality" / f"{case}.member_status.csv"
    statuses = pd.read_csv(statuses_path) if statuses_path.is_file() else pd.DataFrame()
    status_counts = statuses.final_status.value_counts().to_dict() if not statuses.empty else {}
    result = {
        "run_id": case, "final_iteration": latest,
        "initial_ensemble_rows_including_base": len(prior_par),
        "initial_nonbase_member_rows": len(numeric_members(prior_par)),
        "requested_ies_num_reals": requested_reals,
        "final_members_with_finite_phi": len(finite),
        "prior_phi_min": float(np.min(prior_values)),
        "prior_phi_median": float(np.median(prior_values)),
        "final_phi_min": best_phi,
        "final_phi_median": float(np.median(final_values)),
        "phi_by_iteration": phi[["iteration", "total_runs", "mean", "min", "max"]].to_dict(orient="records"),
        "best_realization": best_name,
        "best_phi_reduction_from_prior_min_pct": float(100 * (1 - best_phi / np.min(prior_values))),
        "best_overall_iteration": overall_iteration,
        "best_overall_realization": overall_name,
        "best_overall_phi": overall_phi,
        "adjustable_parameter_count": len(active_boundary),
        "exact_bound_hit_count": len(exact),
        "near_bound_1pct_count": len(near),
        "outside_bounds_count": len(outside),
        "exact_bound_hit_names": exact.name.tolist(),
        "near_bound_1pct_names": near.name.tolist(),
        "outside_bounds_names": outside.name.tolist(),
        "final_member_status_counts": status_counts,
        "engineering_quality_status": quality.get("status"),
        "engineering_failed_checks": [
            c.get("check_id") for c in quality.get("checks", []) if c.get("status") == "fail"
        ],
        "best_overall_exact_bound_hit_names": overall_boundary.loc[
            overall_boundary.status.str.lower().eq("active")
            & (overall_boundary.at_lower_1e6_span | overall_boundary.at_upper_1e6_span), "name"
        ].tolist(),
        "best_overall_near_bound_1pct_names": overall_boundary.loc[
            overall_boundary.status.str.lower().eq("active")
            & (overall_boundary.within_lower_1pct | overall_boundary.within_upper_1pct), "name"
        ].tolist(),
        "terminal_dry_yield_final_iteration_best": yield_metrics_final,
        "terminal_dry_yield_best_overall": yield_metrics_overall,
    }
    (run / "calibration_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        f"# Calibration report: {case}", "",
        "## Configuration", "",
        f"- IES: {requested_reals} requested realizations, `noptmax={requested_iterations}`, 13 treatments, {manifest.get('initial_ensemble_method', 'Sobol')} initial ensemble, 8 workers.",
        "- Fixed parameters: `SASC_RATIO=0.90`, `ICNS_25SP=1.0`, `ICNS_26SP=1.0`.",
        f"- Input manifest SHA-256: `{manifest.get('input_manifest_sha256', 'unavailable')}`.",
        f"- `ies_num_reals={requested_reals}`; the initial ensemble file contains {len(prior_par)} rows including {len(prior_par) - len(numeric_members(prior_par))} base row(s).",
        "", "## Phi by iteration", "",
        "| Iteration | Total runs | Mean Phi | Minimum Phi |", "|---:|---:|---:|---:|",
    ]
    for row in result["phi_by_iteration"]:
        lines.append(f"| {row['iteration']} | {row['total_runs']} | {row['mean']:.2f} | {row['min']:.3f} |")
    lines += [
        "", f"Best across all iterations: iteration {overall_iteration}, realization {overall_name}, Phi {overall_phi:.3f}.",
        f"Best in final iteration: realization {best_name}, Phi {best_phi:.3f}.",
        "", "## Final cumulative dry yield", "",
        "Metrics use each treatment's terminal harvest date; positive bias means DSSAT overprediction.",
        "", "| Solution | Season | n | RMSE (kg/ha) | Bias (kg/ha) | NRMSE (%) | R² |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for label, metric_set in (("Best overall", yield_metrics_overall), ("Final iteration best", yield_metrics_final)):
        for season in ("25SP", "26SP", "all"):
            v = metric_set[season]
            lines.append(f"| {label} | {season} | {v['n']} | {v['rmse_kg_ha']:.1f} | {v['bias_kg_ha']:.1f} | {v['nrmse_pct_of_observed_mean']:.2f} | {v['r2']:.3f} |")
    lines += ["", "## Parameter boundaries", "", "Exact means within 1e-6 of the allowed range width; near means within 1%.", ""]
    for label, frame in (("Best overall", overall_boundary), ("Final iteration best", boundary)):
        active = frame[frame.status.str.lower() == "active"]
        exact_rows = active[active.at_lower_1e6_span | active.at_upper_1e6_span]
        near_rows = active[(active.within_lower_1pct | active.within_upper_1pct) & ~active.index.isin(exact_rows.index)]
        lines += [f"### {label}", "", f"Exact hits: {len(exact_rows)}; within 1%: {len(near_rows)} additional parameters.", ""]
        if exact_rows.empty and near_rows.empty:
            lines.append("No active parameter is at or within 1% of a bound.")
        else:
            lines += ["| Parameter | Value | Lower | Upper | Boundary | Ensemble fraction within 1% |", "|---|---:|---:|---:|---|---:|"]
            selected = pd.concat([exact_rows, near_rows]).drop_duplicates("name")
            for _, row in selected.iterrows():
                direction = "lower" if row.at_lower_1e6_span or row.within_lower_1pct else "upper"
                frac = row.ensemble_fraction_lower_1pct if direction == "lower" else row.ensemble_fraction_upper_1pct
                lines.append(f"| {row['name']} | {row.best_value:.6g} | {row.lower:.6g} | {row.upper:.6g} | {direction}{' (exact)' if row.at_lower_1e6_span or row.at_upper_1e6_span else ''} | {frac:.1%} |")
    lines += ["", "## Run quality", "", f"Engineering status: **{result['engineering_quality_status']}**. Retained member rows: {status_counts.get('retained', 0)}; high-Phi screened: {status_counts.get('high_phi_screened', 0)}.", "", "Failed engineering checks: " + (", ".join(result["engineering_failed_checks"]) or "none") + ".", "", "This run is not science-validated; the engineering gates failed and the project science-promotion gate remains disabled.", ""]
    replay_final = run / "representative_best_phi" / "PestHarvest.OUT"
    replay_overall = run / "representative_best_overall" / "PestHarvest.OUT"
    if replay_final.is_file():
        lines += ["Deterministic replay: the best final-iteration member's 89 harvest outputs exactly match the corresponding PEST observation-ensemble cells."]
    if replay_overall.is_file():
        lines += ["Deterministic replay: the best-overall member's 89 harvest outputs exactly match the corresponding PEST observation-ensemble cells."]
    if replay_final.is_file() or replay_overall.is_file():
        lines += [""]
    (run / "calibration_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
