#!/usr/bin/env python3
"""Master Launcher & Evaluator for formal calibration v45:
- 25SP calibration scope: W3N2 (TN3), W3N0 (TN5), W1N2 (TN11), W1N0 (TN13)
- 26SP calibration scope: W2N2 (TN5), W2N0 (TN11), W1N2 (TN6), W1N0 (TN12)
- Parameters: PROLFF [0.18, 0.22], PROSTF [0.08, 0.12], NVSMOB [0.32, 0.45], NMOBMX [0.08, 0.15],
              FNPGN1 [1.10, 1.45], FNPGN2 [4.10, 4.45], LFMAX [1.85, 2.20], SFDUR [35, 42], KCAN [0.35, 0.55], etc.
- 10x N_RESPONSE budget, 3x Yield budget, Scheme 4 soil, 80 reals x 6 iters, 6 agents.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PYTHON = sys.executable
RUN_ID = "e02_formal_v45_nitrogen_synergy_two_seasons_20260830"
RUN_DIR = PROJECT_ROOT / "workspace/runs" / RUN_ID
DESIGN_FILE = PROJECT_ROOT / "configs/runs" / f"{RUN_ID}.json"
PREFIX = "e02_v45"
BOUNDS_ID = "eggplant_e02_v45_nitrogen_synergy_bounds"

ENV = os.environ.copy()
ENV["PYTHONPATH"] = str(PROJECT_ROOT)

from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare


def step1_build_pest():
    print(f"\n==================== [STEP 1] BUILDING PEST++ CASE: {RUN_ID} ====================")
    if RUN_DIR.exists():
        shutil.rmtree(RUN_DIR)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        PYTHON,
        str(PROJECT_ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--prefix", PREFIX,
        "--bounds-id", BOUNDS_ID,
        "--bounds-crop", "eggplant",
        "--multiseason-design", str(DESIGN_FILE),
        "--noptmax", "6",
        "--ies-num-reals", "80",
        "--batch", "DSSBatch.v48",
        "--harvest-var", "CHFPW",
        "--param-review-mode", "off",
        "--out-dir", str(RUN_DIR),
        "--input-dir", "data/user/experiments/xxql2501_user_ic_scheme4_20260830",
    ]
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=ENV, capture_output=True, text=True)
    if res.returncode != 0:
        print("[BUILD ERROR]\n", res.stderr)
        print("[BUILD STDOUT]\n", res.stdout)
        sys.exit(1)
    print(f"[OK] PEST case built at {RUN_DIR}")


def step2_run_parallel():
    print(f"\n==================== [STEP 2] RUNNING PARALLEL PEST++ IES (6 AGENTS, 80 REALS X 6 ITERS) ====================")
    cmd = [
        PYTHON,
        str(PROJECT_ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(RUN_DIR),
        "--case", PREFIX,
        "--mode", "ies",
        "--n-agents", "6",
        "--wait",
    ]
    t0 = time.time()
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=ENV)
    elapsed = time.time() - t0
    print(f"[OK] Calibration finished in {elapsed/60.0:.2f} minutes.")


def step3_extract_best_member() -> tuple[str, Path]:
    print("\n==================== [STEP 3] EXTRACTING BEST CALIBRATED PARAMETER MEMBER ====================")
    df_phi = pd.read_csv(RUN_DIR / f"{PREFIX}.phi.actual.csv")
    max_iter = int(df_phi["iteration"].max())
    row = df_phi[df_phi["iteration"] == max_iter].iloc[0]
    
    meta_cols = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
    real_cols = [c for c in df_phi.columns if c not in meta_cols]
    
    scores = {c: float(row[c]) for c in real_cols if pd.notna(row[c])}
    best_real = min(scores, key=scores.get)
    best_phi = scores[best_real]
    print(f"[OK] Best member at iteration {max_iter}: Member #{best_real} (Phi = {best_phi:.4f})")
    
    # Extract parameter vector from par CSV
    par_files = list(RUN_DIR.glob(f"*.{max_iter}.par.csv"))
    if not par_files:
        par_files = list(RUN_DIR.glob("*.par.csv"))
    df_par = pd.read_csv(par_files[0])
    
    m_col = "real_name" if "real_name" in df_par.columns else "name"
    p_row = df_par[df_par[m_col].astype(str) == str(best_real)]
    if p_row.empty:
        p_row = df_par.iloc[0:1]
        
    cols = [c for c in df_par.columns if c not in ["real_name", "name", "iteration"]]
    params_dict = {c: float(p_row[c].values[0]) for c in cols}
    
    det_dir = RUN_DIR / f"best_member_{best_real}_two_season_deterministic_20260830"
    det_dir.mkdir(parents=True, exist_ok=True)
    
    par_df = pd.DataFrame([{"name": k, "value": v} for k, v in params_dict.items()])
    param_csv_out = det_dir / f"best_member_{best_real}_params.csv"
    par_df.to_csv(param_csv_out, index=False)
    print(f"[OK] Saved best member parameters to {param_csv_out}")
    return best_real, param_csv_out


def step4_replay_deterministic(best_member: str, param_csv: Path):
    print("\n==================== [STEP 4] RUNNING DETERMINISTIC SIMULATION REPLAY (ALL 22 TMTS) ====================")
    det_dir = param_csv.parent
    
    base_design = json.loads(DESIGN_FILE.read_text(encoding="utf-8"))
    replay_design = dict(base_design)
    replay_design["design_id"] = f"{RUN_ID}_all_22_replay"
    replay_design["seasons"] = [
        {
            "season_id": "25SP", "experiment_code": "XXQL2501",
            "bundle_path": "data/user/experiments/xxql2501_user_ic_scheme4_20260830",
            "role": "calibration", "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]
        },
        {
            "season_id": "26SP", "experiment_code": "XXQL2601",
            "bundle_path": "data/user/experiments/xxql2601_formal_scheme4_soil_20260830",
            "role": "calibration", "treatments": list(range(1, 13))
        }
    ]
    replay_design["diagnostic_only"] = {"25SP": [], "26SP": []}
    replay_design_file = det_dir / "replay_all_design.json"
    replay_design_file.write_text(json.dumps(replay_design, indent=2), encoding="utf-8")
    
    cmd = [
        PYTHON,
        str(PROJECT_ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(replay_design_file),
        "--param-csv", str(param_csv),
        "--prefix", f"best{best_member}_det",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    res = subprocess.run(cmd, cwd=str(det_dir), env=ENV, capture_output=True, text=True)
    if res.returncode != 0 and not (det_dir / "_seasons/25SP/PlantGro.OUT").exists():
        print("[REPLAY ERROR]\n", res.stderr)
        sys.exit(1)
        
    full_tmts = {
        "25SP": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
        "26SP": list(range(1, 13)),
    }
    
    for sid, tmts in full_tmts.items():
        s_dir = det_dir / "_seasons" / sid
        filex = next(s_dir.glob("*.TMX"))
        batch = s_dir / "analysis_batch.v48"
        batch.write_text(
            "\n".join(f"{filex.resolve()} {int(tn)} 1 0 0 0" for tn in tmts) + "\n",
            encoding="utf-8",
        )
        deterministic_harvest_compare(sid, str(batch), run_dir=str(s_dir))
        deterministic_process_compare(sid, str(batch), var_names=["LAID", "LWAD", "SWAD", "CWAD"], run_dir=str(s_dir))
        
    print(f"[OK] Deterministic simulation replay complete for both seasons.")


def step5_generate_full_scorecard(best_member: str, param_csv: Path):
    print("\n==================== [STEP 5] GENERATING FULL REPORT & SCORECARD ====================")
    det_dir = param_csv.parent
    h25_file = det_dir / "_seasons/25SP/25SP_deterministic_harvest_compare.csv"
    h26_file = det_dir / "_seasons/26SP/26SP_deterministic_harvest_compare.csv"
    p25_file = det_dir / "_seasons/25SP/25SP_deterministic_process_compare.csv"
    p26_file = det_dir / "_seasons/26SP/26SP_deterministic_process_compare.csv"
    
    df_h25 = pd.read_csv(h25_file)
    df_h26 = pd.read_csv(h26_file)
    df_p25 = pd.read_csv(p25_file)
    df_p26 = pd.read_csv(p26_file)
    
    mapping = pd.read_csv(PROJECT_ROOT / "configs/runs/e02_mapping_25sp_w3w1_26sp_w2w1_n2n0_20260830.csv")
    
    def _stats(obs, sim):
        ok = np.isfinite(obs) & np.isfinite(sim) & (obs != -99) & (sim != -99)
        o, s = obs[ok], sim[ok]
        sst = np.sum((o - o.mean()) ** 2)
        nse = float(1.0 - np.sum((s - o) ** 2) / sst) if sst > 0 else np.nan
        rrmse = float(100.0 * np.sqrt(np.mean((s - o) ** 2)) / np.mean(np.abs(o))) if len(o) > 0 else np.nan
        r2 = float(np.corrcoef(o, s)[0, 1] ** 2) if len(o) > 1 else np.nan
        d_idx = float(1.0 - np.sum((s - o)**2) / np.sum((np.abs(s - o.mean()) + np.abs(o - o.mean()))**2)) if sst > 0 else np.nan
        return r2, nse, d_idx, rrmse

    def _summarize_season(df_h, sid):
        max_hno = df_h["HNO"].max()
        sub_term = df_h[df_h["HNO"] == max_hno].set_index("TN")
        m_sub = mapping[mapping["season_id"] == sid].set_index("treatment")
        records = []
        for tn in sorted(sub_term.index):
            obs_f = sub_term.loc[tn, "OBS_FRESH_CUM"]
            sim_f = sub_term.loc[tn, "SIM_FRESH_CUM"]
            obs_d = sub_term.loc[tn, "OBS_DRY_CUM"]
            sim_d = sub_term.loc[tn, "SIM_DRY_CUM"]
            w = m_sub.loc[tn, "water_level"] if tn in m_sub.index else "?"
            n = m_sub.loc[tn, "nitrogen_level"] if tn in m_sub.index else "?"
            n_kg = m_sub.loc[tn, "nitrogen_kg_ha"] if tn in m_sub.index else np.nan
            role = m_sub.loc[tn, "objective_role"] if tn in m_sub.index else "?"
            records.append({
                "Season": sid, "TN": tn, "Water": w, "N_Level": n, "Fert_N_kg": n_kg, "Role": role,
                "OBS_Fresh_Yield": obs_f, "SIM_Fresh_Yield": sim_f,
                "Fresh_Error_kg": round(sim_f - obs_f, 1),
                "Fresh_PBIAS_pct": round(100.0 * (sim_f - obs_f) / obs_f, 2),
                "OBS_Dry_Yield": obs_d, "SIM_Dry_Yield": sim_d,
                "Dry_Error_kg": round(sim_d - obs_d, 1),
                "Dry_PBIAS_pct": round(100.0 * (sim_d - obs_d) / obs_d, 2),
            })
        return pd.DataFrame(records)

    sum25 = _summarize_season(df_h25, "25SP")
    sum26 = _summarize_season(df_h26, "26SP")
    
    print("\n========================== 25SP TREATMENT YIELD SCORECARD ==========================")
    print(sum25[["TN", "Water", "N_Level", "Fert_N_kg", "Role", "OBS_Fresh_Yield", "SIM_Fresh_Yield", "Fresh_Error_kg", "Fresh_PBIAS_pct", "OBS_Dry_Yield", "SIM_Dry_Yield", "Dry_PBIAS_pct"]].to_string(index=False))
    
    print("\n========================== 26SP TREATMENT YIELD SCORECARD ==========================")
    print(sum26[["TN", "Water", "N_Level", "Fert_N_kg", "Role", "OBS_Fresh_Yield", "SIM_Fresh_Yield", "Fresh_Error_kg", "Fresh_PBIAS_pct", "OBS_Dry_Yield", "SIM_Dry_Yield", "Dry_PBIAS_pct"]].to_string(index=False))
    
    def _metrics_df(sid, df_h, df_p):
        r2_f, nse_f, d_f, rrmse_f = _stats(df_h["OBS_FRESH_CUM"].to_numpy(float), df_h["SIM_FRESH_CUM"].to_numpy(float))
        r2_d, nse_d, d_d, rrmse_d = _stats(df_h["OBS_DRY_CUM"].to_numpy(float), df_h["SIM_DRY_CUM"].to_numpy(float))
        r2_l, nse_l, d_l, rrmse_l = _stats(df_p["OBS_LAID"].to_numpy(float), df_p["SIM_LAID"].to_numpy(float))
        r2_lw, nse_lw, d_lw, rrmse_lw = _stats(df_p["OBS_LWAD"].to_numpy(float), df_p["SIM_LWAD"].to_numpy(float))
        r2_sw, nse_sw, d_sw, rrmse_sw = _stats(df_p["OBS_SWAD"].to_numpy(float), df_p["SIM_SWAD"].to_numpy(float))
        return pd.DataFrame([
            {"Season": sid, "Variable": "Fresh Fruit Yield (FRESH_CUM)", "R2": round(r2_f, 4), "NSE": round(nse_f, 4), "d_index": round(d_f, 4), "RRMSE_%": round(rrmse_f, 2)},
            {"Season": sid, "Variable": "Dry Fruit Yield (DRY_CUM)", "R2": round(r2_d, 4), "NSE": round(nse_d, 4), "d_index": round(d_d, 4), "RRMSE_%": round(rrmse_d, 2)},
            {"Season": sid, "Variable": "Canopy LAI (LAID)", "R2": round(r2_l, 4), "NSE": round(nse_l, 4), "d_index": round(d_l, 4), "RRMSE_%": round(rrmse_l, 2)},
            {"Season": sid, "Variable": "Leaf Dry Mass (LWAD)", "R2": round(r2_lw, 4), "NSE": round(nse_lw, 4), "d_index": round(d_lw, 4), "RRMSE_%": round(rrmse_lw, 2)},
            {"Season": sid, "Variable": "Stem Dry Mass (SWAD)", "R2": round(r2_sw, 4), "NSE": round(nse_sw, 4), "d_index": round(d_sw, 4), "RRMSE_%": round(rrmse_sw, 2)},
        ])

    m_df25 = _metrics_df("25SP", df_h25, df_p25)
    m_df26 = _metrics_df("26SP", df_h26, df_p26)
    
    print("\n========================== 25SP OVERALL METRICS SCORECARD ==========================")
    print(m_df25.to_string(index=False))
    
    print("\n========================== 26SP OVERALL METRICS SCORECARD ==========================")
    print(m_df26.to_string(index=False))
    
    # N-Response evaluation (N2 - N0 and N3 - N0)
    w3_25_n2n0_sim = sum25.loc[sum25["TN"] == 3, "SIM_Fresh_Yield"].values[0] - sum25.loc[sum25["TN"] == 5, "SIM_Fresh_Yield"].values[0]
    w3_25_n2n0_obs = sum25.loc[sum25["TN"] == 3, "OBS_Fresh_Yield"].values[0] - sum25.loc[sum25["TN"] == 5, "OBS_Fresh_Yield"].values[0]
    w1_25_n2n0_sim = sum25.loc[sum25["TN"] == 11, "SIM_Fresh_Yield"].values[0] - sum25.loc[sum25["TN"] == 13, "SIM_Fresh_Yield"].values[0]
    w1_25_n2n0_obs = sum25.loc[sum25["TN"] == 11, "OBS_Fresh_Yield"].values[0] - sum25.loc[sum25["TN"] == 13, "OBS_Fresh_Yield"].values[0]

    w2_26_n2n0_sim = sum26.loc[sum26["TN"] == 5, "SIM_Fresh_Yield"].values[0] - sum26.loc[sum26["TN"] == 11, "SIM_Fresh_Yield"].values[0]
    w2_26_n2n0_obs = sum26.loc[sum26["TN"] == 5, "OBS_Fresh_Yield"].values[0] - sum26.loc[sum26["TN"] == 11, "OBS_Fresh_Yield"].values[0]
    w1_26_n2n0_sim = sum26.loc[sum26["TN"] == 6, "SIM_Fresh_Yield"].values[0] - sum26.loc[sum26["TN"] == 12, "SIM_Fresh_Yield"].values[0]
    w1_26_n2n0_obs = sum26.loc[sum26["TN"] == 6, "OBS_Fresh_Yield"].values[0] - sum26.loc[sum26["TN"] == 12, "OBS_Fresh_Yield"].values[0]

    w3_25_n3n0_sim = sum25.loc[sum25["TN"] == 2, "SIM_Fresh_Yield"].values[0] - sum25.loc[sum25["TN"] == 5, "SIM_Fresh_Yield"].values[0]
    w3_25_n3n0_obs = sum25.loc[sum25["TN"] == 2, "OBS_Fresh_Yield"].values[0] - sum25.loc[sum25["TN"] == 5, "OBS_Fresh_Yield"].values[0]
    w1_25_n3n0_sim = sum25.loc[sum25["TN"] == 10, "SIM_Fresh_Yield"].values[0] - sum25.loc[sum25["TN"] == 13, "SIM_Fresh_Yield"].values[0]
    w1_25_n3n0_obs = sum25.loc[sum25["TN"] == 10, "OBS_Fresh_Yield"].values[0] - sum25.loc[sum25["TN"] == 13, "OBS_Fresh_Yield"].values[0]

    w3_26_n3n0_sim = sum26.loc[sum26["TN"] == 1, "SIM_Fresh_Yield"].values[0] - sum26.loc[sum26["TN"] == 9, "SIM_Fresh_Yield"].values[0]
    w3_26_n3n0_obs = sum26.loc[sum26["TN"] == 1, "OBS_Fresh_Yield"].values[0] - sum26.loc[sum26["TN"] == 9, "OBS_Fresh_Yield"].values[0]
    w2_26_n3n0_sim = sum26.loc[sum26["TN"] == 2, "SIM_Fresh_Yield"].values[0] - sum26.loc[sum26["TN"] == 11, "SIM_Fresh_Yield"].values[0]
    w2_26_n3n0_obs = sum26.loc[sum26["TN"] == 2, "OBS_Fresh_Yield"].values[0] - sum26.loc[sum26["TN"] == 11, "OBS_Fresh_Yield"].values[0]
    w1_26_n3n0_sim = sum26.loc[sum26["TN"] == 3, "SIM_Fresh_Yield"].values[0] - sum26.loc[sum26["TN"] == 12, "SIM_Fresh_Yield"].values[0]
    w1_26_n3n0_obs = sum26.loc[sum26["TN"] == 3, "OBS_Fresh_Yield"].values[0] - sum26.loc[sum26["TN"] == 12, "OBS_Fresh_Yield"].values[0]

    print("\n========================== NITROGEN RESPONSE CONTRASTS (N2 - N0) ==========================")
    print(f"25SP W3 (TN 3 [W3N2] - TN 5 [W3N0])  -> Sim: {w3_25_n2n0_sim:+7.1f} kg/ha | Obs: {w3_25_n2n0_obs:+7.1f} kg/ha")
    print(f"25SP W1 (TN 11 [W1N2] - TN 13 [W1N0]) -> Sim: {w1_25_n2n0_sim:+7.1f} kg/ha | Obs: {w1_25_n2n0_obs:+7.1f} kg/ha")
    print(f"26SP W2 (TN 5 [W2N2] - TN 11 [W2N0]) -> Sim: {w2_26_n2n0_sim:+7.1f} kg/ha | Obs: {w2_26_n2n0_obs:+7.1f} kg/ha")
    print(f"26SP W1 (TN 6 [W1N2] - TN 12 [W1N0]) -> Sim: {w1_26_n2n0_sim:+7.1f} kg/ha | Obs: {w1_26_n2n0_obs:+7.1f} kg/ha")

    print("\n========================== NITROGEN RESPONSE CONTRASTS (N3 - N0) ==========================")
    print(f"25SP W3 (TN 2 [W3N3] - TN 5 [W3N0])  -> Sim: {w3_25_n3n0_sim:+7.1f} kg/ha | Obs: {w3_25_n3n0_obs:+7.1f} kg/ha")
    print(f"25SP W1 (TN 10 [W1N3] - TN 13 [W1N0]) -> Sim: {w1_25_n3n0_sim:+7.1f} kg/ha | Obs: {w1_25_n3n0_obs:+7.1f} kg/ha")
    print(f"26SP W3 (TN 1 [W3N3] - TN 9 [W3N0])  -> Sim: {w3_26_n3n0_sim:+7.1f} kg/ha | Obs: {w3_26_n3n0_obs:+7.1f} kg/ha")
    print(f"26SP W2 (TN 2 [W2N3] - TN 11 [W2N0]) -> Sim: {w2_26_n3n0_sim:+7.1f} kg/ha | Obs: {w2_26_n3n0_obs:+7.1f} kg/ha")
    print(f"26SP W1 (TN 3 [W1N3] - TN 12 [W1N0]) -> Sim: {w1_26_n3n0_sim:+7.1f} kg/ha | Obs: {w1_26_n3n0_obs:+7.1f} kg/ha")
    
    out_rep_dir = PROJECT_ROOT / "workspace/reports/calibration_v45_formal_summary_20260830"
    out_rep_dir.mkdir(parents=True, exist_ok=True)
    sum25.to_csv(out_rep_dir / "25SP_treatment_yield_scorecard.csv", index=False)
    sum26.to_csv(out_rep_dir / "26SP_treatment_yield_scorecard.csv", index=False)
    m_df25.to_csv(out_rep_dir / "25SP_overall_metrics.csv", index=False)
    m_df26.to_csv(out_rep_dir / "26SP_overall_metrics.csv", index=False)
    print(f"\n[OK] Summary files saved to {out_rep_dir}")


def main():
    step1_build_pest()
    step2_run_parallel()
    best_member, param_csv = step3_extract_best_member()
    step4_replay_deterministic(best_member, param_csv)
    step5_generate_full_scorecard(best_member, param_csv)


if __name__ == "__main__":
    main()
