"""Deterministic diagnostics for the 25SP+26SP valid-IC spring run."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.reporting import diagnostic_three_season_best_member as base  # noqa: E402

SEASONS = [
    {
        "season_id": "25SP", "experiment_code": "XXQL2501",
        "bundle_path": "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801",
        "role": "calibration", "treatments": [3, 4, 5, 9, 11, 12, 13, 14],
    },
    {
        "season_id": "26SP", "experiment_code": "XXQL2601",
        "bundle_path": "data/user/experiments/xxql2601_layermean_ic_valid_n012_v1_20260801",
        "role": "calibration", "treatments": [4, 5, 6, 7, 8, 9, 10, 11, 12],
    },
]
CONFIG = ROOT / "configs/runs/eggplant_e02_joint61_25sp26sp_layermeanic_n012_no_nresponse_v1_20260801.json"


def _best_member(run_dir: Path, case: str):
    phi = pd.read_csv(run_dir / f"{case}.phi.actual.csv")
    final_iter = phi["iteration"].max()
    row = phi.loc[phi["iteration"].eq(final_iter)].iloc[0]
    cols = [c for c in phi.columns if c not in {"iteration", "total_runs", "mean", "standard_deviation", "min", "max", "base"}]
    member = min(cols, key=lambda c: float(row[c]))
    return str(member), float(row[member]), int(final_iter)


def _write_design(out: Path) -> Path:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    for season in payload["seasons"]:
        manifest = ROOT / season["bundle_path"] / "input_manifest.json"
        season["bundle_manifest_sha256"] = base._sha256(manifest)
    path = out / "diagnostic_joint_spring_design.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _posterior_boundary(run_dir: Path, case: str, out: Path, iteration: int):
    import pyemu
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    par = pd.read_csv(run_dir / f"{case}.{iteration}.par.csv")
    rows = []
    for p in pst.parameter_data.itertuples():
        if str(p.partrans).lower() == "fixed":
            continue
        col = next((c for c in par.columns if str(c).lower() == str(p.parnme).lower()), None)
        if col is None:
            continue
        vals = pd.to_numeric(par[col], errors="coerce").dropna().to_numpy(float)
        lo, hi = float(p.parlbnd), float(p.parubnd)
        tol = max(0.05 * (hi - lo), 1e-12)
        near_low = vals <= lo + tol
        near_high = vals >= hi - tol
        rows.append({"parameter": p.parnme, "lower": lo, "upper": hi,
                     "posterior_n": len(vals), "near_lower_pct": 100 * near_low.mean(),
                     "near_upper_pct": 100 * near_high.mean(),
                     "touch_any_pct": 100 * (near_low | near_high).mean()})
    frame = pd.DataFrame(rows).sort_values("touch_any_pct", ascending=False)
    frame.to_csv(out / "best_member_posterior_boundary_proportions.csv", index=False)
    return frame


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--case", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--reuse-rerun", action="store_true")
    args = ap.parse_args()
    run_dir, out = args.run_dir.resolve(), args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    member, phi, iteration = _best_member(run_dir, args.case)
    design = _write_design(out)
    param_path = out / f"best_member_{member}_parameters.csv"
    base._export_member(run_dir / f"{args.case}.{iteration}.par.csv", member, param_path)
    prefix = "diagnostic_joint_spring_best_member"
    status = out / "multiseason_run_status.json"
    if not (args.reuse_rerun and status.is_file()):
        subprocess.run([sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                        "--design", str(design), "--param-csv", str(param_path),
                        "--prefix", prefix, "--harvest-var", "CHPDT",
                        "--keep-nitrogen-outputs"], cwd=out, check=True)
    comparison, trajectory = base._collect(out, prefix, SEASONS)
    comparison.to_csv(out / "best_member_comparison_original_scale.csv", index=False)
    trajectory.to_csv(out / "best_member_simulation_trajectory.csv", index=False)
    metrics = base._write_metrics(comparison, out)
    metrics.to_csv(out / "best_member_metrics_by_season_and_overall.csv", index=False)
    boundary = _posterior_boundary(run_dir, args.case, out, iteration)
    figures = []
    for season in SEASONS:
        sid = season["season_id"]
        for var, title, ylabel in [("DRY_CUM", "cumulative dry yield", "kg ha-1"),
                                   ("LAID", "leaf area development", "LAI")]:
            path = out / f"diagnostic_{sid.lower()}_{'cumulative_dry_yield' if var == 'DRY_CUM' else 'lai'}_dynamics.png"
            base._facet_dynamics(comparison, trajectory, season=season, variable=var,
                                 title=title, ylabel=ylabel, out_path=path)
            figures.append(path.name)
    manifest = {"source_calibration": str(run_dir), "best_member": member,
                "best_member_final_actual_phi": phi, "best_member_iteration": iteration,
                "figures": figures}
    (out / "diagnostic_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"best_member={member}, iteration={iteration}, actual_phi={phi}")
    print(metrics.to_string(index=False))
    print("\nPosterior boundary proportions (top 15):")
    print(boundary.head(15).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
