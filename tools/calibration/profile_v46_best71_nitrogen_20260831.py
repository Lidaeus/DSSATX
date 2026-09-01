"""Stepwise deterministic nitrogen-response profiling from v46 best member 71.

The profile is deliberately causal: all non-nitrogen parameters and both
season bundles remain those of v46; one mechanism family is changed at a time.
Results are screening evidence only and are not promoted to a calibration
bound without the subsequent IES gates.
"""

from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.profile_n_parameters_determinstic as base

BASE = ROOT / "workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/best_member_71_deterministic_20260831"
OUT = ROOT / "workspace/reports/e02_v46_stepwise_nitrogen_20260831"
SCRATCH = OUT / "scratch_runs"
TREATMENTS = {"25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14], "26SP": list(range(1, 13))}
N_PAIRS = {
    "25SP": {"N2": {"W3": (3, 5), "W1": (11, 13)}, "N1": {"W3": (4, 5), "W1": (12, 13)}},
    "26SP": {"N2": {"W3": (4, 9), "W2": (5, 11), "W1": (6, 12)}, "N1": {"W3": (7, 9), "W2": (8, 11), "W1": (10, 12)}},
}


def _terminal_n12(case: str) -> dict[str, object]:
    """Extract the required N2-N0/N1-N0 terminal gate from a completed run."""
    records: list[dict[str, float | str]] = []
    for season, pairs in N_PAIRS.items():
        h = pd.read_csv(SCRATCH / case / "_seasons" / season / f"{season}_deterministic_harvest_compare.csv")
        terminal = h.sort_values(["TN", "HNO"]).groupby("TN", as_index=False).tail(1).set_index("TN")
        for level, water_pairs in pairs.items():
            for water, (hi, lo) in water_pairs.items():
                if hi not in terminal.index or lo not in terminal.index:
                    continue
                records.append({
                    "season": season, "level": level, "water": water,
                    "obs": float(terminal.loc[hi, "OBS_FRESH_CUM"] - terminal.loc[lo, "OBS_FRESH_CUM"]),
                    "sim": float(terminal.loc[hi, "SIM_FRESH_CUM"] - terminal.loc[lo, "SIM_FRESH_CUM"]),
                })
    if not records:
        return {"n12_records": 0, "n12_mean_obs": np.nan, "n12_mean_sim": np.nan,
                "n12_mean_abs_error": np.nan, "n12_direction_pass": False}
    frame = pd.DataFrame(records)
    return {
        "n12_records": int(len(frame)),
        "n12_mean_obs": float(frame["obs"].mean()),
        "n12_mean_sim": float(frame["sim"].mean()),
        "n12_mean_abs_error": float(np.abs(frame["sim"] - frame["obs"]).mean()),
        "n12_direction_pass": bool(frame["sim"].mean() > 0),
        "n12_records_json": json.dumps(records, ensure_ascii=False),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    base.BASE_PARAMS_PATH = BASE / "best_member_71_params.csv"
    base.OUT_DIR = OUT
    base.SCRATCH_DIR = SCRATCH
    base.BASE_DESIGN_PATH = OUT / "design_all22.json"

    design = json.loads((ROOT / "configs/runs/e02_formal_v46_step20_custom26sp_20260831_200x4.json").read_text(encoding="utf-8"))
    for season in design["seasons"]:
        season["treatments"] = TREATMENTS[season["season_id"]]
    design["diagnostic_only"] = {"25SP": [], "26SP": []}
    design["design_id"] = "e02_v46_stepwise_nitrogen_profiles_all22_20260831"
    design["purpose"] = "Deterministic causal nitrogen mechanism profiles from v46 best member 71"
    base.BASE_DESIGN_PATH.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    params = pd.read_csv(base.BASE_PARAMS_PATH)
    params["name"] = params["name"].astype(str).str.upper()
    values = dict(zip(params["name"], pd.to_numeric(params["value"])))
    experiments: list[tuple[str, str, str, dict[str, float]]] = [("baseline", "BASELINE", "best71", {})]

    # Ordered to match the mechanism chain in docs/reference/调整氮响应能力.md.
    for v in [0.55, 0.65, 0.70, 0.80, 0.90]:
        experiments.append((f"nstfac_{v:.2f}", "NSTFAC", str(v), {"NSTFAC": v}))
    for v in [0.025, 0.030, 0.033, 0.040, 0.050]:
        experiments.append((f"rtno3_{v:.3f}", "RTNO3", str(v), {"RTNO3": v}))
    for v in [0.20, 0.30, 0.40, 0.50, 0.60]:
        experiments.append((f"nmobmx_{v:.2f}", "NMOBMX", str(v), {"NMOBMX": v}))
    for v in [0.16, 0.20, 0.21, 0.24, 0.28]:
        experiments.append((f"prolfi_{v:.2f}", "PROLFI", str(v), {"PROLFI": v}))
    for scale in [0.80, 1.00, 1.15]:
        experiments.append((f"growth_n_floor_{scale:.2f}", "PROLFG_PROSTG_PRORTG", str(scale), {
            "PROLFG": values["PROLFG"] * scale,
            "PROSTG": values["PROSTG"] * scale,
            "PRORTG": values["PRORTG"] * scale,
        }))
    for scale in [0.90, 1.00, 1.10]:
        experiments.append((f"target_n_{scale:.2f}", "PROLFI_PROSTI_PRORTI", str(scale), {
            "PROLFI": values["PROLFI"] * scale,
            "PROSTI": values["PROSTI"] * scale,
            "PRORTI": values["PRORTI"] * scale,
        }))
    for f1, f2 in product([0.70, 0.90, 1.10], [3.80, 4.15, 4.50]):
        experiments.append((f"fnpgn_{f1:.2f}_{f2:.2f}", "FNPGN1_FNPGN2", f"{f1}|{f2}", {"FNPGN1": f1, "FNPGN2": f2}))

    rows: list[dict[str, object]] = []
    for idx, (case, family, setting, changes) in enumerate(experiments, 1):
        case_dir = SCRATCH / case
        case_dir.mkdir(parents=True, exist_ok=True)
        candidate = dict(values)
        candidate.update(changes)
        param_csv = case_dir / "params.csv"
        pd.DataFrame([{"name": k, "value": v} for k, v in candidate.items()]).to_csv(param_csv, index=False)
        result_file = case_dir / "profile_result.json"
        if result_file.is_file():
            row = json.loads(result_file.read_text(encoding="utf-8"))
        else:
            result = base._run_deterministic(changes, case)
            result.update(_terminal_n12(case))
            row = {"case": case, "family": family, "setting": setting, **result}
            result_file.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if "n12_mean_abs_error" not in row:
            row.update(_terminal_n12(case))
        row.update({"case": case, "family": family, "setting": setting, "status": "success" if row.get("25SP_W3_diff_sim") is not None else "failed"})
        rows.append(row)
        pd.DataFrame(rows).to_csv(OUT / "profile_results.csv", index=False)
        print(f"[{idx:02d}/{len(experiments):02d}] {case}", flush=True)

    df = pd.DataFrame(rows)
    if df.empty:
        return 1
    ncols = ["25SP_W3_diff_sim", "25SP_W1_diff_sim", "26SP_W3_diff_sim", "26SP_W1_diff_sim"]
    df["n_direction_pass"] = df["n12_direction_pass"]
    df["n_response_abs_error"] = df["n12_mean_abs_error"]
    baseline = df.loc[df.case.eq("baseline")].iloc[0]
    df["n_response_error_delta_vs_baseline"] = df["n_response_abs_error"] - float(baseline["n_response_abs_error"])
    df["protected_fit_pass"] = (
        df["25SP_LAI_NSE"].ge(float(baseline["25SP_LAI_NSE"]) - 0.05)
        & df["26SP_LAI_NSE"].ge(float(baseline["26SP_LAI_NSE"]) - 0.05)
        & df["25SP_FRESH_NSE"].ge(float(baseline["25SP_FRESH_NSE"]) - 0.05)
        & df["26SP_FRESH_NSE"].ge(float(baseline["26SP_FRESH_NSE"]) - 0.05)
    )
    df["screen_pass"] = df["n_direction_pass"] & df["protected_fit_pass"]
    df.sort_values(["screen_pass", "n_response_error_delta_vs_baseline"], ascending=[False, True]).to_csv(OUT / "profile_scorecard.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
