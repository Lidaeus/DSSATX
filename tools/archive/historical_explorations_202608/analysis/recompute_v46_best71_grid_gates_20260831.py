"""Recompute v46 best71 grid guards from existing deterministic outputs.

This does not rerun DSSAT.  It refreshes only the W_RESPONSE fields and gate
columns after the water-stratum definition was corrected to the formal N0/N3
contract (25SP W3-W1, 26SP W2-W1).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.grid_v46_best71_nitrogen_20260831 as grid


def signed_metric(obs: list[float], sim: list[float]) -> float:
    o = np.asarray(obs, dtype=float)
    s = np.asarray(sim, dtype=float)
    if len(o) < 2:
        return float("nan")
    sst = float(np.square(o - o.mean()).sum())
    return 1.0 - float(np.square(s - o).sum()) / sst if sst > 0 else float("nan")


def main() -> int:
    out = grid.OUT
    path = out / "grid_results.csv"
    df = pd.read_csv(path)
    for i, row in df.iterrows():
        case_dir = out / "scratch_runs" / str(row["case"])
        records: list[dict[str, object]] = []
        for season in ("25SP", "26SP"):
            hpath = case_dir / "_seasons" / season / f"{season}_deterministic_harvest_compare.csv"
            h = pd.read_csv(hpath)
            rec = grid.water_records(h, season)
            records.extend(rec)
            df.loc[i, f"{season}_w_response_nse"] = signed_metric(
                [float(x["obs"]) for x in rec], [float(x["sim"]) for x in rec]
            )
        df.loc[i, "w_records_json"] = json.dumps(records, ensure_ascii=False)
    baseline = df.iloc[0]
    for season in ("25SP", "26SP"):
        df[f"{season}_n_error_reduction_pct"] = 100.0 * (
            float(baseline[f"{season}_n_mean_abs_error"]) - df[f"{season}_n_mean_abs_error"].astype(float)
        ) / float(baseline[f"{season}_n_mean_abs_error"])
    df["yield_guard_pass"] = (
        df["25SP_terminal_rrmse_pct"].astype(float).le(25.0)
        & df["26SP_terminal_rrmse_pct"].astype(float).le(25.0)
    )
    df["protected_fit_pass"] = (
        df["25SP_fresh_cum_nse"].astype(float).ge(float(baseline["25SP_fresh_cum_nse"]) - 0.05)
        & df["26SP_fresh_cum_nse"].astype(float).ge(float(baseline["26SP_fresh_cum_nse"]) - 0.05)
        & df["25SP_lai_nse"].astype(float).ge(float(baseline["25SP_lai_nse"]) - 0.05)
        & df["26SP_lai_nse"].astype(float).ge(float(baseline["26SP_lai_nse"]) - 0.05)
        & df["25SP_w_response_nse"].astype(float).ge(float(baseline["25SP_w_response_nse"]) - 0.05)
        & df["26SP_w_response_nse"].astype(float).ge(float(baseline["26SP_w_response_nse"]) - 0.05)
    )
    df["grid_gate_pass"] = (
        df["25SP_n_direction_pass"].astype(bool)
        & df["26SP_n_error_reduction_pct"].astype(float).ge(30.0)
        & df["n_response_layers_improved_vs_baseline"].astype(int).ge(3)
        & df["yield_guard_pass"]
        & df["protected_fit_pass"]
    )
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(df[["case", "25SP_w_response_nse", "26SP_w_response_nse", "grid_gate_pass"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
