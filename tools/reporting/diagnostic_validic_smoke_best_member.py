"""Report and plot the best member from the valid-IC N0-N2 smoke run.

The smoke case calibrates 25SP/25FA on N0-N2 only.  This diagnostic replays
the selected posterior member over all available treatments in 25SP, 25FA and
26SP, so the N3-N0 contrasts and three-season trajectories are predictions,
not additional calibration targets.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.reporting import diagnostic_three_season_best_member as base  # noqa: E402


CONFIG = ROOT / "configs/runs/eggplant_e02_joint61_25sp25fa_validic_n012_no_nresponse_v1_20260801.json"
SEASONS = [
    {
        "season_id": "25SP", "experiment_code": "XXQL2501",
        "bundle_path": "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801",
        "bundle_manifest_sha256": "767904430a07626bcdf94ef1aefd5ffaff6b9ac50fdddaf7fd600b1353422977",
        "role": "calibration", "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
    },
    {
        "season_id": "25FA", "experiment_code": "XXQL2502",
        "bundle_path": "data/user/experiments/xxql2502_layermean_ic_valid_n012_v1_20260801",
        "bundle_manifest_sha256": "1152cc534029ee9980e1b68b23a895e0a180a75604e3067a766a4a39de1ea1f2",
        "role": "calibration", "treatments": list(range(1, 13)),
    },
    {
        "season_id": "26SP", "experiment_code": "XXQL2601",
        "bundle_path": "data/user/experiments/xxql2601_layermean_ic_valid_n012_v1_20260801",
        "bundle_manifest_sha256": "64a0174acc4ee0c3a99ad1092ff98b8449c4",  # replaced from manifest below
        "role": "calibration", "treatments": list(range(1, 13)),
    },
]

# Explicit high/low-water cells from the frozen experiment treatment contract.
N_RESPONSE_CELLS = {
    "25SP": {"high": {3: 2, 2: 3, 1: 4, 0: 5}, "low": {3: 10, 2: 11, 1: 12, 0: 13}},
    "25FA": {"high": {3: 3, 2: 4, 1: 7, 0: 9}, "low": {3: 1, 2: 6, 1: 10, 0: 12}},
    "26SP": {"high": {3: 3, 2: 6, 1: 10, 0: 9}, "low": {3: 1, 2: 4, 1: 7, 0: 12}},
}


def _best_member(run_dir: Path, case: str) -> tuple[str, float, int]:
    phi = pd.read_csv(run_dir / f"{case}.phi.actual.csv")
    final = phi.loc[phi["iteration"].eq(phi["iteration"].max())].iloc[0]
    realizations = [c for c in phi.columns if c not in {"iteration", "total_runs", "mean", "standard_deviation", "min", "max", "base"}]
    member = min(realizations, key=lambda c: float(final[c]))
    return str(member), float(final[member]), int(final["iteration"])


def _write_design(out: Path) -> Path:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["design_id"] = "diagnostic_validic_smoke_best_member_three_season_20260801"
    payload["shared_parameter_scope"] = "Best posterior member from valid-IC N0-N2 smoke; autumn offsets applied only to 25FA"
    # Ensure the 26SP manifest hash is taken from the actual bundle, not copied text.
    for season in SEASONS:
        manifest = ROOT / season["bundle_path"] / "input_manifest.json"
        payload_season = next(x for x in SEASONS if x["season_id"] == season["season_id"])
        payload_season["bundle_manifest_sha256"] = base._sha256(manifest)
    payload["seasons"] = SEASONS
    path = out / "diagnostic_validic_smoke_three_season_design.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _metrics_by_season_and_all(comparison: pd.DataFrame, out: Path) -> pd.DataFrame:
    result = base._write_metrics(comparison, out)
    result.to_csv(out / "best_member_metrics_by_season_and_overall.csv", index=False)
    return result


def _terminal_yields(comparison: pd.DataFrame, trajectory: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for season in SEASONS:
        sid = season["season_id"]
        for tn in season["treatments"]:
            sim = trajectory[(trajectory["season"] == sid) & (trajectory["variable"] == "DRY_CUM") & (trajectory["treatment"].astype(str) == str(tn))]
            obs = comparison[(comparison["season"] == sid) & (comparison["variable"] == "DRY_CUM") & (comparison["treatment"].astype(str) == str(tn))]
            if sim.empty:
                continue
            s = sim.sort_values("time").iloc[-1]
            o = obs.sort_values("time").iloc[-1] if not obs.empty else None
            rows.append({"season": sid, "treatment": int(tn), "simulated_final_dry_yield": float(s["simulated"]),
                         "observed_final_dry_yield": float(o["observed"]) if o is not None else np.nan})
    return pd.DataFrame(rows)


def _n_response(terminal: pd.DataFrame, out: Path) -> pd.DataFrame:
    rows = []
    for sid, cells in N_RESPONSE_CELLS.items():
        sub = terminal[terminal["season"] == sid].set_index("treatment")
        for water, mapping in cells.items():
            for level in (3, 2, 1):
                high_tn = mapping[level]
                n0_tn = mapping[0]
                if high_tn not in sub.index or n0_tn not in sub.index:
                    continue
                rows.append({
                    "season": sid, "water_level": water, "contrast": f"N{level}-N0",
                    "nitrogen_level": level, "n_level_treatment": high_tn, "n0_treatment": n0_tn,
                    "simulated_difference": float(sub.loc[high_tn, "simulated_final_dry_yield"] - sub.loc[n0_tn, "simulated_final_dry_yield"]),
                    "observed_difference": float(sub.loc[high_tn, "observed_final_dry_yield"] - sub.loc[n0_tn, "observed_final_dry_yield"]),
                })
    frame = pd.DataFrame(rows)
    frame.to_csv(out / "best_member_n_response_contrasts.csv", index=False)
    return frame


def _posterior_boundary(run_dir: Path, case: str, out: Path) -> pd.DataFrame:
    pst = __import__("pyemu").Pst(str(run_dir / f"{case}.pst"))
    par = pd.read_csv(run_dir / f"{case}.1.par.csv")
    real_col = next(c for c in par.columns if str(c).lower() in {"real_name", "realization"})
    rows = []
    for p in pst.parameter_data.itertuples():
        if str(p.partrans).lower() == "fixed":
            continue
        name = str(p.parnme)
        col = next((c for c in par.columns if str(c).lower() == name.lower()), None)
        if col is None:
            continue
        vals = pd.to_numeric(par[col], errors="coerce").dropna().to_numpy(float)
        lo, hi = float(p.parlbnd), float(p.parubnd)
        width = hi - lo
        tol = max(0.05 * width, 1e-12)
        low = float(np.mean(vals <= lo + tol))
        high = float(np.mean(vals >= hi - tol))
        rows.append({"parameter": name, "lower": lo, "upper": hi, "posterior_n": len(vals),
                     "near_lower_pct": 100 * low, "near_upper_pct": 100 * high,
                     "touch_any_pct": 100 * np.mean((vals <= lo + tol) | (vals >= hi - tol))})
    result = pd.DataFrame(rows).sort_values("touch_any_pct", ascending=False)
    result.to_csv(out / "best_member_posterior_boundary_proportions.csv", index=False)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--member", default="auto")
    ap.add_argument("--reuse-rerun", action="store_true")
    args = ap.parse_args()
    run_dir, out = args.run_dir.resolve(), args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    member, phi, iteration = _best_member(run_dir, args.case) if args.member == "auto" else (str(args.member), np.nan, -1)
    design = _write_design(out)
    param_path = out / f"best_member_{member}_parameters.csv"
    base._export_member(run_dir / f"{args.case}.1.par.csv", member, param_path)
    status = out / "multiseason_run_status.json"
    prefix = "diagnostic_validic_smoke_best_member_three_season"
    if not (args.reuse_rerun and status.is_file()):
        subprocess.run([sys.executable, str(ROOT / "src/calibration/run_multiseason.py"), "--design", str(design),
                        "--param-csv", str(param_path), "--prefix", prefix, "--harvest-var", "CHPDT",
                        "--keep-nitrogen-outputs"], cwd=out, check=True)
    comparison, trajectory = base._collect(out, prefix, SEASONS)
    comparison.to_csv(out / "best_member_comparison_original_scale.csv", index=False)
    trajectory.to_csv(out / "best_member_simulation_trajectory.csv", index=False)
    metrics = _metrics_by_season_and_all(comparison, out)
    calibration_treatments = {"25SP": {3, 4, 5, 9, 11, 12, 13, 14},
                              "25FA": {4, 5, 6, 7, 8, 9, 10, 11, 12}}
    calibration_comparison = comparison[
        comparison.apply(
            lambda row: row["season"] == "26SP"
            or int(row["treatment"]) in calibration_treatments.get(row["season"], set()),
            axis=1,
        )
    ].copy()
    calibration_metrics = _metrics_by_season_and_all(calibration_comparison, out)
    calibration_metrics.to_csv(out / "best_member_metrics_calibration_n012_and_26sp.csv", index=False)
    terminal = _terminal_yields(comparison, trajectory)
    contrasts = _n_response(terminal, out)
    bounds = _posterior_boundary(run_dir, args.case, out)
    figures = []
    for season in SEASONS:
        sid = season["season_id"]
        yield_path = out / f"diagnostic_{sid.lower()}_cumulative_dry_yield_dynamics.png"
        lai_path = out / f"diagnostic_{sid.lower()}_lai_dynamics.png"
        base._facet_dynamics(comparison, trajectory, season=season, variable="DRY_CUM",
                             title="cumulative dry yield", ylabel="kg ha−1", out_path=yield_path)
        base._facet_dynamics(comparison, trajectory, season=season, variable="LAID",
                             title="leaf area development", ylabel="LAI (m² m−²)", out_path=lai_path)
        figures.extend([yield_path, lai_path])
    manifest = {"artifact_type": "run_diagnostics", "source_calibration": str(run_dir), "source_case": args.case,
                "best_member": member, "best_member_final_actual_phi": phi, "best_member_iteration": iteration,
                "figures": [p.name for p in figures], "note": "N3-N0 contrasts and 26SP are deterministic predictions; N3 was excluded from calibration Phi."}
    (out / "diagnostic_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"best_member={member}, iteration={iteration}, actual_phi={phi}")
    print("\nMetrics:")
    print(metrics.to_string(index=False))
    print("\nN response contrasts:")
    print(contrasts.to_string(index=False))
    print("\nPosterior boundary proportions (top 15):")
    print(bounds.head(15).to_string(index=False))
    print(f"\nDiagnostics written to: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
