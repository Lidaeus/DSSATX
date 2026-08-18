"""Export reproducible best-member fit metrics for an IES run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def _metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    y = frame["obs_raw"].to_numpy(float)
    p = frame["pred_raw"].to_numpy(float)
    e = p - y
    den = float(np.sum((y - np.mean(y)) ** 2))
    dden = float(np.sum((np.abs(p - np.mean(y)) + np.abs(y - np.mean(y))) ** 2))
    return {
        "n": int(len(frame)),
        "phi": float(frame["contrib"].sum()),
        "rmse": float(np.sqrt(np.mean(e**2))),
        "mae": float(np.mean(np.abs(e))),
        "bias": float(np.mean(e)),
        "nrmse_mean_abs_observed": float(np.sqrt(np.mean(e**2)) / np.mean(np.abs(y))) if np.mean(np.abs(y)) else None,
        "nse": float(1.0 - np.sum(e**2) / den) if den > 0 else None,
        "d_index": float(1.0 - np.sum(e**2) / dden) if dden > 0 else None,
        "r2": float(np.corrcoef(y, p)[0, 1] ** 2) if len(frame) > 1 and np.std(y) > 0 and np.std(p) > 0 else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--case", required=True)
    args = ap.parse_args()
    run = args.run_dir.resolve()
    phi = pd.read_csv(run / f"{args.case}.phi.actual.csv")
    final = phi.iloc[-1]
    slots = pd.to_numeric(final.iloc[6:], errors="coerce")
    best = str(slots.idxmin())
    registry = pd.read_csv(run / f"{args.case}_observation_registry.csv")
    observations = pd.read_csv(run / f"{args.case}.4.obs.csv")
    member = observations.loc[observations["real_name"].astype(str).eq(best)].iloc[0]
    active = registry.loc[(registry["phi_role"].astype(str).str.lower() == "calibration") & (pd.to_numeric(registry["weight"], errors="coerce") > 0)].copy()
    active["pred_transformed"] = [float(member[str(name).lower()]) for name in active["obsnme"]]
    active["residual_transformed"] = active["pred_transformed"] - active["obsval"]
    active["contrib"] = (active["residual_transformed"] * active["weight"]) ** 2
    active["pred_raw"] = active["pred_transformed"]
    log = active["transform"].astype(str).str.lower().eq("log")
    active.loc[log, "pred_raw"] = np.exp(active.loc[log, "pred_transformed"]) * active.loc[log, "transform_reference"] - active.loc[log, "transform_offset"]
    active["obs_raw"] = active["raw_obsval"]
    rows = [{"scope": "overall", **_metrics(active)}]
    for scope, frame in active.groupby("season_id"):
        rows.append({"scope": str(scope), **_metrics(frame)})
    for scope, frame in active.groupby("sim_token"):
        if not str(scope).startswith("SW"):
            rows.append({"scope": str(scope), **_metrics(frame)})
    treatment_map = {12: "W1N0", 10: "W1N1", 6: "W1N2", 11: "W2N0", 8: "W2N1", 5: "W2N2"}
    for treatment, label in treatment_map.items():
        frame = active.loc[pd.to_numeric(active["treatment"], errors="coerce").eq(treatment)]
        if len(frame):
            rows.append({"scope": label, **_metrics(frame)})
    out_csv = run / "best_member_fit_metrics.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    payload = {
        "case": args.case,
        "best_real_name": best,
        "best_phi": float(slots.min()),
        "final_mean_phi": float(final["mean"]),
        "final_base_phi": float(final["base"]),
        "active_observations": int(len(active)),
        "organ_n_observations_present": bool(active["sim_token"].isin(["LNAMS", "SNAMS"]).any()),
        "metrics_csv": str(out_csv),
    }
    (run / "best_member_fit_metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
