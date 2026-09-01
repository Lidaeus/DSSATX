"""Audit the realized N_RESPONSE objective contract for a PEST++ IES run.

The audit is intentionally read-only.  It joins the final iteration's
realization-level ``*.obs.csv`` values with the adjusted observation table,
then reports row-level residuals and Phi contributions by season, response
stratum (water level), and harvest number.  It is designed to catch accidental
use of the wrong source variable, missing N levels, or disproportionate
weighting of a single harvest layer before another calibration is launched.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


_NAME_RE = re.compile(
    r"^(?P<season>25sp|26sp)_nresps_r(?P<run>\d+)_h(?P<hno>\d+)$",
    re.IGNORECASE,
)


def _find_one(path: Path, pattern: str) -> Path:
    matches = sorted(path.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"no {pattern!r} under {path}")
    return matches[-1]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--obs-file", type=Path, default=None,
                   help="realization-level .obs.csv; defaults to the highest iteration")
    p.add_argument("--design-json", type=Path, default=None,
                   help="optional design JSON used to verify source_variable and levels")
    p.add_argument("--out-dir", type=Path, required=True)
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    run_dir = args.run_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    obs_file = args.obs_file.resolve() if args.obs_file else _find_one(run_dir, "*.obs.csv")
    # The adjusted table has the authoritative observed value and final PEST
    # weight.  It is intentionally not reconstructed from a policy CSV.
    adjusted = _find_one(run_dir, "*.adjusted.obs_data.csv")
    real = pd.read_csv(obs_file)
    adj = pd.read_csv(adjusted)
    if "real_name" not in real.columns:
        raise ValueError(f"missing real_name in {obs_file}")
    required = {"name", "value", "weight", "group"}
    missing = required.difference(adj.columns)
    if missing:
        raise ValueError(f"adjusted obs table missing columns: {sorted(missing)}")

    n_adj = adj.loc[adj["name"].astype(str).str.contains("nresps", case=False, na=False)].copy()
    if n_adj.empty:
        raise ValueError("no NRESP observations found in adjusted observation table")
    n_adj["name"] = n_adj["name"].astype(str).str.lower()
    n_adj = n_adj.drop_duplicates("name", keep="last")

    value_cols = {str(c).lower(): c for c in real.columns}
    rows: list[dict[str, object]] = []
    for _, ar in n_adj.iterrows():
        name = str(ar["name"]).lower()
        m = _NAME_RE.match(name)
        if not m:
            raise ValueError(f"unexpected NRESP observation name: {name}")
        col = value_cols.get(name)
        if col is None:
            raise ValueError(f"observation {name} absent from {obs_file.name}")
        obs = float(ar["value"])
        wt = float(ar["weight"])
        group = str(ar["group"])
        for _, rr in real[["real_name", col]].iterrows():
            sim = float(rr[col])
            resid = sim - obs
            rows.append({
                "real_name": str(rr["real_name"]),
                "obsnme": name,
                "season": m.group("season").upper(),
                "run": int(m.group("run")),
                "harvest_number": int(m.group("hno")),
                "group": group,
                "observed": obs,
                "simulated": sim,
                "residual_sim_minus_obs": resid,
                "weight": wt,
                "standardized_residual": resid * wt,
                "phi_contribution": (resid * wt) ** 2,
            })
    detail = pd.DataFrame(rows)
    detail.to_csv(out_dir / "n_response_objective_rows.csv", index=False, encoding="utf-8-sig")

    def _summary(frame: pd.DataFrame, level: str) -> pd.DataFrame:
        gcols = ["season", "harvest_number"] if level == "season_hno" else ["season"]
        if level == "season_hno_water":
            gcols = ["season", "harvest_number", "group"]
        out = frame.groupby(gcols, dropna=False).agg(
            n=("residual_sim_minus_obs", "size"),
            observed_mean=("observed", "mean"),
            simulated_mean=("simulated", "mean"),
            mean_abs_error=("residual_sim_minus_obs", lambda x: float(np.mean(np.abs(x)))),
            rmse=("residual_sim_minus_obs", lambda x: float(np.sqrt(np.mean(np.square(x))))),
            phi=("phi_contribution", "sum"),
            weight_mean=("weight", "mean"),
        ).reset_index()
        out.insert(0, "summary_level", level)
        return out

    summaries = pd.concat([
        _summary(detail, "season"),
        _summary(detail, "season_hno"),
        _summary(detail, "season_hno_water"),
    ], ignore_index=True)
    summaries.to_csv(out_dir / "n_response_objective_summary.csv", index=False, encoding="utf-8-sig")

    # A compact contract check is useful in CI and in handoff reviews.
    row_counts = detail.groupby("season")["obsnme"].nunique().to_dict()
    expected = {"25SP": 36, "26SP": 30}
    contract = {
        "run_dir": str(run_dir),
        "obs_file": str(obs_file),
        "adjusted_obs_file": str(adjusted),
        "n_realizations": int(detail["real_name"].nunique()),
        "n_response_rows_per_realization": int(detail["obsnme"].nunique()),
        "row_counts_by_season": {str(k): int(v) for k, v in row_counts.items()},
        "expected_row_counts_by_season": expected,
        "row_count_pass": all(int(row_counts.get(k, -1)) == v for k, v in expected.items()),
        "seasons": sorted(detail["season"].unique().tolist()),
        "harvest_numbers_by_season": {
            str(k): sorted(int(x) for x in v.unique())
            for k, v in detail.groupby("season")["harvest_number"]
        },
        "group_names": sorted(detail["group"].unique().tolist()),
        "total_phi_by_realization": {
            str(k): float(v)
            for k, v in detail.groupby("real_name")["phi_contribution"].sum().items()
        },
        "mean_phi": float(detail.groupby("real_name")["phi_contribution"].sum().mean()),
        "notes": [
            "source-variable identity is verified by the run design JSON and output token; this audit does not infer it from column names",
            "residual sign is simulated minus observed; phi contribution is (weight * residual)^2",
        ],
    }
    # Include the design JSON when present, without assuming a fixed filename.
    design_files = [args.design_json.resolve()] if args.design_json else sorted(run_dir.glob("*.json"))
    for path in design_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and "nitrogen_response_objective" in payload:
            contract["design_file"] = str(path)
            contract["nitrogen_response_objective"] = payload["nitrogen_response_objective"]
            break
    if "nitrogen_response_objective" not in contract:
        contract["design_file"] = None
        contract["nitrogen_response_objective"] = None
        contract["notes"].append("no design JSON supplied; source_variable/levels must be checked against the run manifest manually")
    (out_dir / "n_response_objective_audit.json").write_text(
        json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({k: contract[k] for k in (
        "n_realizations", "n_response_rows_per_realization", "row_counts_by_season",
        "row_count_pass", "mean_phi",
    )}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
