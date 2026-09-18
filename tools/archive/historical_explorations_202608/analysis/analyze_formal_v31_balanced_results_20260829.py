"""Analyze the v31 balanced formal calibration and its all-22 replay."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "workspace/runs/e02_formal_v31_balanced_official_200x6_20260829"
CASE = "e02_formal_v31_balanced_200x6_20260829"
DET = RUN / "best_member_deterministic_20260829"
OUT = RUN / "result_summary_20260829"
CALIBRATION_TN = {"25SP": {2, 5, 10, 13}, "26SP": {1, 3, 9, 12}}


def metrics(y: pd.Series, p: pd.Series) -> dict[str, float | int]:
    y = pd.to_numeric(y, errors="coerce")
    p = pd.to_numeric(p, errors="coerce")
    ok = y.notna() & p.notna() & (y > -90) & (p > -90)
    y = y.loc[ok].to_numpy(float)
    p = p.loc[ok].to_numpy(float)
    if not len(y):
        return {key: np.nan for key in ("n", "rmse", "rrmse_pct", "mae", "bias", "nse", "d_index", "r2")}
    error = p - y
    sst = float(np.sum((y - y.mean()) ** 2))
    dden = float(np.sum((np.abs(p - y.mean()) + np.abs(y - y.mean())) ** 2))
    return {
        "n": len(y),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "rrmse_pct": float(100 * np.sqrt(np.mean(error ** 2)) / np.mean(np.abs(y))) if np.mean(np.abs(y)) else np.nan,
        "mae": float(np.mean(np.abs(error))),
        "bias": float(np.mean(error)),
        "nse": float(1 - np.sum(error ** 2) / sst) if sst > 0 else np.nan,
        "d_index": float(1 - np.sum(error ** 2) / dden) if dden > 0 else np.nan,
        "r2": float(np.corrcoef(y, p)[0, 1] ** 2) if len(y) > 1 and np.std(y) > 0 and np.std(p) > 0 else np.nan,
    }


def analyze_run() -> dict:
    phi_csv = RUN / f"{CASE}.phi.actual.csv"
    if not phi_csv.is_file():
        raise FileNotFoundError(f"Phi file missing: {phi_csv}")
    
    df_phi = pd.read_csv(phi_csv)
    last_iter_num = df_phi["iteration"].max()
    last_row = df_phi[df_phi["iteration"] == last_iter_num].iloc[0]
    meta_cols = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
    real_cols = [c for c in df_phi.columns if c not in meta_cols]
    best_real = min(real_cols, key=lambda r: float(last_row[r]))
    min_phi = float(last_row[best_real])
    
    pst = pyemu.Pst(str(RUN / f"{CASE}.pst"))
    p_df = pst.parameter_data
    par_post = pd.read_csv(RUN / f"{CASE}.{last_iter_num}.par.csv")
    r_col = [c for c in par_post.columns if "real" in c.lower()][0]
    
    active_params = p_df[p_df["partrans"] != "fixed"].index.tolist()
    edge_records = []
    for p in active_params:
        if p not in par_post.columns:
            continue
        lb = float(p_df.loc[p, "parlbnd"])
        ub = float(p_df.loc[p, "parubnd"])
        init = float(p_df.loc[p, "parval1"])
        vals = par_post[p].to_numpy()
        b_val = float(par_post[par_post[r_col].astype(str) == str(best_real)][p].values[0])
        rng = ub - lb
        dist_lb = (b_val - lb) / rng if rng > 0 else 0
        dist_ub = (ub - b_val) / rng if rng > 0 else 0
        
        status = "OK"
        if dist_lb < 0.03:
            status = "Near Lower Bound"
        elif dist_ub < 0.03:
            status = "Near Upper Bound"
        edge_records.append({
            "param": p,
            "group": p_df.loc[p, "pargp"],
            "lower": lb,
            "upper": ub,
            "best": b_val,
            "median": float(np.median(vals)),
            "status": status
        })
    df_edge = pd.DataFrame(edge_records)
    
    summary = {
        "best_member": str(best_real),
        "best_iteration": int(last_iter_num),
        "best_phi": min_phi,
        "initial_mean_phi": float(df_phi.iloc[0]["mean"]),
        "final_mean_phi": float(last_row["mean"]),
        "active_parameters": len(active_params),
        "edge_hits": df_edge[df_edge["status"] != "OK"].to_dict(orient="records"),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "calibration_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    df_edge.to_csv(OUT / "parameter_edge_audit.csv", index=False)
    return summary


if __name__ == "__main__":
    res = analyze_run()
    print(json.dumps(res, indent=2))
