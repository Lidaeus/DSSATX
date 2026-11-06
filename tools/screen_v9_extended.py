#!/usr/bin/env python3
"""Extended evaluation of V9 Iteration 5 candidates to find the true champion.

Criteria required:
1. Strict monotonic compliance:
   - 26SP W2 (N3 - N0) >= 8000 kg/ha
   - 26SP W1 (N3 - N0) > 0
   - 25SP W3 (N3 - N0) > 0
   - 25SP W1 (N3 - N0) > 0  (NO INVERSION!)
   - total_pen_mono == 0.0
2. 25FA blind test NRMSE <= 25.0% (cross-season generalization)
3. 25SP W1 drought underestimation substantially relieved (mean terminal bias > -25%)
4. Low LAIX peak bias (|bias| < 1.0)
5. Lowest combined Spring Pooled NRMSE / highest d-index
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.run_dssat import prepare_run_directory
from tools.eval_full_gen98 import evaluate_run, calc_metrics
from src.reporting.analyze_results import _read_plantgro_vars_by_run

RUN_V9 = PROJECT_ROOT / "workspace" / "runs" / "full_genetic_98pct_v9_20260917"
CALIB_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_calib.v48"
VALID_BATCH = PROJECT_ROOT / "data" / "templates" / "batch" / "DSSBatch_valid.v48"
BATCH_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh" / "DSSBatch.v48"
BUNDLE_25FA = PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2502_v20260917_refresh"


def get_candidates(run_dir: Path, n_top: int = 25):
    phi_csv = run_dir / "full_gen98_v9.phi.actual.csv"
    phi_df = pd.read_csv(phi_csv)
    iter5_row = phi_df[phi_df["iteration"] == 5].iloc[0]
    par5_csv = run_dir / "full_gen98_v9.5.par.csv"
    df_par5 = pd.read_csv(par5_csv)

    recs = []
    meta = {"iteration", "total_runs", "mean", "standard_deviation", "std", "min", "max", "base"}
    for col in phi_df.columns:
        if col not in meta:
            try:
                v = float(iter5_row[col])
                if np.isfinite(v) and v < 1e8:
                    recs.append((str(col), v))
            except Exception:
                pass
    recs.sort(key=lambda x: x[1])

    chosen = []
    chosen_ids = set()
    for r_id, phi_v in recs[:n_top]:
        chosen.append((r_id, df_par5, f"iter5_real{r_id}", phi_v))
        chosen_ids.add(r_id)

    # ensure real22 is included for comparison
    if "22" not in chosen_ids:
        for r_id, phi_v in recs:
            if r_id == "22":
                chosen.append((r_id, df_par5, f"iter5_real{r_id}", phi_v))
                break

    return chosen


def build_param_csv(real_id: str, df_par: pd.DataFrame, out_path: Path):
    sub = df_par[df_par["real_name"].astype(str) == str(real_id)]
    if sub.empty:
        raise ValueError(f"Realization {real_id} not found")
    row = sub.iloc[0]
    items = []
    for col in df_par.columns:
        if col != "real_name":
            items.append({"name": col, "value": row[col]})
    df_out = pd.DataFrame(items)
    df_out.to_csv(out_path, index=False)
    return df_out


def run_batch(batch_path: Path, param_csv: Path, out_dir: Path, input_dir: Path = None):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    prep_args = ["--batch", str(batch_path)]
    if input_dir:
        prep_args.extend(["--input-dir", str(input_dir)])
    batch_dest = prepare_run_directory(out_dir, prep_args)
    cmd = [
        sys.executable,
        "-m",
        "src.dssat.run_dssat",
        "--param-csv",
        str(param_csv.resolve()),
        "--batch",
        batch_dest.name,
        "--harvest-var",
        "CHPDT",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        raise RuntimeError(f"DSSAT execution failed in {out_dir}: {res.stderr[-500:]}")
    df_h, df_eval = evaluate_run(batch_path, out_dir)
    return df_h, df_eval


def main():
    candidates = get_candidates(RUN_V9, n_top=25)
    print(f"Screening {len(candidates)} candidates from Iteration 5...")

    results = []
    scratch_base = PROJECT_ROOT / "scratch" / "screen_v9"
    scratch_base.mkdir(parents=True, exist_ok=True)

    for idx, (cid, df_par_source, tag, phi_val) in enumerate(candidates):
        print(f"[{idx+1}/{len(candidates)}] Testing {tag} (Phi={phi_val:.2f})...")
        p_csv = RUN_V9 / f"candidate_{tag}_params.csv"
        build_param_csv(cid, df_par_source, p_csv)

        # 1. Calibration (8 runs)
        calib_dir = scratch_base / f"cand_{tag}_calib"
        df_h_c, df_eval_c = run_batch(CALIB_BATCH, p_csv, calib_dir)
        rmse_c, nrmse_c, d_c, r2_c = calc_metrics(df_h_c["OBS_FRESH_CUM"], df_h_c["SIM_FRESH_CUM"])

        # 2. Validation (15 runs)
        valid_dir = scratch_base / f"cand_{tag}_valid"
        df_h_v, df_eval_v = run_batch(VALID_BATCH, p_csv, valid_dir)
        rmse_v, nrmse_v, d_v, r2_v = calc_metrics(df_h_v["OBS_FRESH_CUM"], df_h_v["SIM_FRESH_CUM"])

        # 3. Pooled Spring (23 runs)
        df_h_spring = pd.concat([df_h_c, df_h_v], ignore_index=True)
        rmse_sp, nrmse_sp, d_sp, r2_sp = calc_metrics(df_h_spring["OBS_FRESH_CUM"], df_h_spring["SIM_FRESH_CUM"])

        # 4. 25FA Blind Test (12 runs)
        fa_dir = scratch_base / f"cand_{tag}_25fa"
        df_h_fa, df_eval_fa = run_batch(BATCH_25FA, p_csv, fa_dir, input_dir=BUNDLE_25FA)
        rmse_fa, nrmse_fa, d_fa, r2_fa = calc_metrics(df_h_fa["OBS_FRESH_CUM"], df_h_fa["SIM_FRESH_CUM"])

        # 5. Gradients
        last_c = df_h_c.sort_values("DATE").groupby("RUN").last()["SIM_FRESH_CUM"].to_dict()
        w2_26_gap = last_c.get(5, 0) - last_c.get(7, 0)  # 26SP W2: Trt 2 - Trt 11
        w1_26_gap = last_c.get(6, 0) - last_c.get(8, 0)  # 26SP W1: Trt 3 - Trt 12
        w3_25_gap = last_c.get(1, 0) - last_c.get(2, 0)  # 25SP W3: Trt 2 - Trt 5
        w1_25_gap = last_c.get(3, 0) - last_c.get(4, 0)  # 25SP W1: Trt 10 - Trt 13

        pen_25_w3 = max(0.0, -w3_25_gap)
        pen_25_w1 = max(0.0, -w1_25_gap)
        pen_26_w2 = max(0.0, -w2_26_gap)
        pen_26_w1 = max(0.0, -w1_26_gap)
        total_pen = pen_25_w3 + pen_25_w1 + pen_26_w2 + pen_26_w1

        # 6. 25SP W1 drought bias
        df_all_h = pd.concat([
            df_h_c.assign(batch="Calibration"),
            df_h_v.assign(batch="Validation"),
        ], ignore_index=True)
        w1_25sp_biases = []
        for tn in [10, 11, 12, 13]:
            sub_tn = df_all_h[(df_all_h["EXCODE"] == "XXQL2501") & (df_all_h["TN"] == tn)]
            if not sub_tn.empty:
                last_row = sub_tn.sort_values("DATE").iloc[-1]
                obs = float(last_row["OBS_FRESH_CUM"])
                sim = float(last_row["SIM_FRESH_CUM"])
                w1_25sp_biases.append((sim - obs) / obs * 100.0)
        mean_w1_25sp_bias_pct = np.mean(w1_25sp_biases) if w1_25sp_biases else np.nan

        # 7. LAIX Peak Bias
        laix_biases = []
        for df_ev in [df_eval_c, df_eval_v]:
            if not df_ev.empty and "LAIXM" in df_ev.columns and "LAIXS" in df_ev.columns:
                m = pd.to_numeric(df_ev["LAIXM"], errors="coerce")
                s = pd.to_numeric(df_ev["LAIXS"], errors="coerce")
                mask = np.isfinite(m) & np.isfinite(s) & (m > 0)
                if mask.any():
                    laix_biases.extend((s[mask] - m[mask]).tolist())
        mean_laix_bias = np.mean(laix_biases) if laix_biases else np.nan

        # Key parameters
        p_df = pd.read_csv(p_csv)
        p_vals = dict(zip(p_df["name"].str.lower(), p_df["value"]))

        res = {
            "candidate": tag,
            "real_id": cid,
            "phi": phi_val,
            "calib_nrmse": nrmse_c,
            "calib_d_index": d_c,
            "valid_nrmse": nrmse_v,
            "valid_d_index": d_v,
            "spring_pooled_nrmse": nrmse_sp,
            "spring_pooled_d_index": d_sp,
            "spring_pooled_r2": r2_sp,
            "25FA_nrmse": nrmse_fa,
            "25FA_d_index": d_fa,
            "25FA_r2": r2_fa,
            "26SP_W2_gap": w2_26_gap,
            "26SP_W1_gap": w1_26_gap,
            "25SP_W3_gap": w3_25_gap,
            "25SP_W1_gap": w1_25_gap,
            "total_pen_mono": total_pen,
            "mean_w1_25sp_bias_pct": mean_w1_25sp_bias_pct,
            "mean_laix_bias": mean_laix_bias,
            "lnref": p_vals.get("lnref", np.nan),
            "frlff": p_vals.get("frlff", np.nan),
            "slavr": p_vals.get("slavr", np.nan),
            "tb1": p_vals.get("tb1", np.nan),
            "tm1": p_vals.get("tm1", np.nan),
            "fnpgn2": p_vals.get("fnpgn2", np.nan),
            "nstfac": p_vals.get("nstfac", np.nan),
            "sizlf": p_vals.get("sizlf", np.nan),
            "xfrt": p_vals.get("xfrt", np.nan),
            "icns_26sp": p_vals.get("icns_26sp", np.nan),
        }
        results.append(res)
        print(f"  -> Spring: {nrmse_sp:.2f}%, 25FA: {nrmse_fa:.2f}%, 25SP_W1_gap: {w1_25_gap:+.1f}, Pen: {total_pen:.1f}, LAIX: {mean_laix_bias:+.2f}")

    df = pd.DataFrame(results)
    out_csv = RUN_V9 / "extended_candidate_screening_top25.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nAll results saved to {out_csv}")


if __name__ == "__main__":
    main()
