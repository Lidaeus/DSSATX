"""Original-scale diagnostics for the three-season default-initial-N E02 run."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.reporting import diagnostic_three_season_best_member as base  # noqa: E402
from tools.reporting import diagnostic_v6_three_season_best_member as diag  # noqa: E402


DESIGN = ROOT / "configs/runs/eggplant_e02_joint62_three_season_defaultn_v1_20260730.json"
BOUNDS = (
    ROOT
    / "data/parameter_registry/bounds_frozen/eggplant/"
    "eggplant_e02_joint62_v6_touchrelax_slpf096_20260729.csv"
)


def _seasons(design_path: Path = DESIGN) -> list[dict]:
    return json.loads(design_path.read_text(encoding="utf-8"))["seasons"]


def _best_member(phi_path: Path) -> tuple[int, str, float, pd.DataFrame]:
    phi = pd.read_csv(phi_path)
    final_iteration = int(pd.to_numeric(phi["iteration"]).max())
    final = phi.loc[pd.to_numeric(phi["iteration"]) == final_iteration].iloc[0]
    member_columns = [
        column
        for column in phi.columns
        if str(column).isdigit() and np.isfinite(pd.to_numeric(final[column], errors="coerce"))
    ]
    if not member_columns:
        raise ValueError("No realization columns in actual-Phi file")
    member = min(member_columns, key=lambda column: float(final[column]))
    progression = phi[["iteration", "mean", "standard_deviation", "min", "max"]].copy()
    return final_iteration, str(member), float(final[member]), progression


def _touch_summary(
    ensemble_path: Path,
    bounds_path: Path,
    *,
    best_member: str,
) -> pd.DataFrame:
    ensemble = pd.read_csv(ensemble_path)
    real_col = next(
        column
        for column in ensemble.columns
        if str(column).lower() in {"real_name", "realization"}
    )
    bounds = pd.read_csv(bounds_path, encoding="utf-8-sig")
    by_name = {str(column).upper(): column for column in ensemble.columns if column != real_col}
    best_mask = (
        ensemble[real_col].astype(str).str.replace(r"\.0$", "", regex=True)
        == str(best_member)
    )
    if int(best_mask.sum()) != 1:
        raise ValueError(f"Best member {best_member} not unique in final ensemble")
    records = []
    for _, bound in bounds.iterrows():
        if str(bound.get("status", "")).strip().lower() != "active":
            continue
        name = str(bound["name"]).upper()
        column = by_name.get(name)
        if column is None:
            continue
        values = pd.to_numeric(ensemble[column], errors="coerce").dropna()
        lower = float(bound["lower"])
        upper = float(bound["upper"])
        span = upper - lower
        tolerance = 0.05 * span
        lower_touch = 100.0 * float((values <= lower + tolerance).mean())
        upper_touch = 100.0 * float((values >= upper - tolerance).mean())
        records.append(
            {
                "name": name,
                "lower": lower,
                "upper": upper,
                "q05": float(values.quantile(0.05)),
                "q50": float(values.quantile(0.50)),
                "q95": float(values.quantile(0.95)),
                "mean": float(values.mean()),
                "lower_touch_pct": lower_touch,
                "upper_touch_pct": upper_touch,
                "touch_pct": max(lower_touch, upper_touch),
                "best": float(ensemble.loc[best_mask, column].iloc[0]),
            }
        )
    return pd.DataFrame(records).sort_values(
        ["touch_pct", "name"], ascending=[False, True]
    )


def _overall_metrics(comparison: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variable, group in comparison.groupby("variable", sort=False):
        obs = group["observed"].to_numpy(float)
        sim = group["simulated"].to_numpy(float)
        residual = sim - obs
        denom = float(np.sum((obs - obs.mean()) ** 2))
        rows.append(
            {
                "season": "ALL",
                "variable": variable,
                "n": len(group),
                "rmse": float(np.sqrt(np.mean(residual**2))),
                "rrmse_pct": (
                    float(100 * np.sqrt(np.mean(residual**2)) / np.mean(np.abs(obs)))
                    if np.mean(np.abs(obs))
                    else np.nan
                ),
                "nse": (
                    float(1 - np.sum(residual**2) / denom) if denom > 0 else np.nan
                ),
                "r2": (
                    float(np.corrcoef(obs, sim)[0, 1] ** 2)
                    if len(group) > 1 and np.std(obs) > 0 and np.std(sim) > 0
                    else np.nan
                ),
                "bias": float(residual.mean()),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--design", type=Path, default=DESIGN)
    parser.add_argument("--bounds", type=Path, default=BOUNDS)
    parser.add_argument("--iteration", type=int)
    parser.add_argument("--member")
    parser.add_argument(
        "--initial-n-label",
        default="uniform FileX SNO3=1.0 and SNH4=0.5",
    )
    parser.add_argument("--reuse-rerun", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    case = run_dir.name
    phi_path = run_dir / f"{case}.phi.actual.csv"
    final_iteration, member, best_phi, progression = _best_member(phi_path)
    if args.iteration is not None:
        phi = pd.read_csv(phi_path)
        selected = phi.loc[
            pd.to_numeric(phi["iteration"], errors="coerce").eq(args.iteration)
        ]
        if len(selected) != 1:
            raise ValueError(f"Iteration {args.iteration} not unique in Phi file")
        selected_row = selected.iloc[0]
        final_iteration = int(args.iteration)
        member_columns = [
            column
            for column in phi.columns
            if str(column).isdigit()
            and np.isfinite(pd.to_numeric(selected_row[column], errors="coerce"))
        ]
        if args.member is None:
            member = min(member_columns, key=lambda column: float(selected_row[column]))
        else:
            member = str(args.member)
            if member not in member_columns:
                raise ValueError(
                    f"Member {member} is unavailable at iteration {final_iteration}"
                )
        best_phi = float(selected_row[member])
    ensemble = run_dir / f"{case}.{final_iteration}.par.csv"
    params = out_dir / f"best_member_{member}_parameters.csv"
    base._export_member(ensemble, member, params)

    design_path = args.design.resolve()
    bounds_path = args.bounds.resolve()
    seasons = _seasons(design_path)
    diag.SEASONS = seasons
    deterministic_prefix = f"{case}_best{member}"
    status_path = out_dir / "multiseason_run_status.json"
    if not (args.reuse_rerun and status_path.exists()):
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "src/calibration/run_multiseason.py"),
                "--design",
                str(design_path),
                "--param-csv",
                str(params),
                "--prefix",
                deterministic_prefix,
                "--harvest-var",
                "CHPDT",
                "--keep-nitrogen-outputs",
            ],
            cwd=out_dir,
            check=True,
        )

    comparison, trajectory = base._collect(
        out_dir, deterministic_prefix, seasons
    )
    comparison = diag.add_plant_n(comparison, out_dir)
    comparison.to_csv(out_dir / "comparison_original_scale.csv", index=False)
    trajectory.to_csv(out_dir / "simulation_trajectory.csv", index=False)
    metrics = diag.metrics(comparison, out_dir)
    metrics = pd.concat([metrics, _overall_metrics(comparison)], ignore_index=True)
    metrics.to_csv(out_dir / "metrics_by_season_variable.csv", index=False)

    touch = _touch_summary(ensemble, bounds_path, best_member=member)
    touch.to_csv(out_dir / "posterior_bounds_touch_summary.csv", index=False)
    progression.to_csv(out_dir / "phi_progression.csv", index=False)
    summary = {
        "run_id": case,
        "engineering_status": json.loads(
            (run_dir / "run_status.json").read_text(encoding="utf-8")
        ).get("engineering_status"),
        "final_iteration": final_iteration,
        "best_member": member,
        "best_actual_phi": best_phi,
        "n_parameters_adjustable": int(
            pyemu.Pst(str(run_dir / f"{case}.pst")).npar_adj
        ),
        "n_observations_active": int(
            pyemu.Pst(str(run_dir / f"{case}.pst")).nnz_obs
        ),
        "calibration_seasons": [season["season_id"] for season in seasons],
        "filex_initial_mineral_n": args.initial_n_label,
        "metrics_file": "metrics_by_season_variable.csv",
        "touch_file": "posterior_bounds_touch_summary.csv",
        "residual_definition": "simulated - observed",
        "rrmse_denominator": "mean absolute observed value",
        "note": (
            "All metrics are computed after deterministic rerun on the original "
            "observation scale. 26SP is calibration, not independent validation."
        ),
    }
    (out_dir / "analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(metrics.to_string(index=False))
    print("\nTop posterior boundary concentrations:")
    print(touch.head(15).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
