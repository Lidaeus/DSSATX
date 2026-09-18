"""tools/sensitivity/run_nitrogen_synergy_grid_20260830.py

Comprehensive parameter grid exploration under true measured soil background
with amplified nitrogen response weighting.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
)

BASE_MEMBER_CSV = ROOT / "workspace/runs/e02_formal_v40_3x_yield_200x4_20260830/best_member_125_two_season_deterministic_20260830/best_member_125_params.csv"
OUTPUT_DIR = ROOT / "workspace/reports/nitrogen_grid_scan_20260830"

SEASONS = [
    {
        "season_id": "25SP",
        "excode": "XXQL2501",
        "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
        "bundle": str((ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830").resolve()),
    },
    {
        "season_id": "26SP",
        "excode": "XXQL2601",
        "treatments": list(range(1, 13)),
        "bundle": str((ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830").resolve()),
    },
]


def load_base_params() -> pd.DataFrame:
    if not BASE_MEMBER_CSV.exists():
        raise FileNotFoundError(f"Base member params not found at {BASE_MEMBER_CSV}")
    return pd.read_csv(BASE_MEMBER_CSV)


def evaluate_param_set(params_df: pd.DataFrame, work_dir: Path) -> dict[str, float]:
    work_dir.mkdir(parents=True, exist_ok=True)
    param_file = work_dir / "params.csv"
    params_df.to_csv(param_file, index=False)

    design_payload = {
        "schema_version": 1,
        "design_id": "n_grid_eval",
        "cultivar_identity": "TM0008",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "purpose": "nitrogen grid deterministic exploration",
        "seasons": [
            {
                "season_id": s["season_id"],
                "experiment_code": s["excode"],
                "role": "calibration",
                "bundle_path": s["bundle"],
                "treatments": s["treatments"],
            }
            for s in SEASONS
        ],
    }
    design_json = work_dir / "design.json"
    design_json.write_text(json.dumps(design_payload, indent=2), encoding="utf-8")

    cmd = [
        sys.executable,
        str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(design_json.resolve()),
        "--param-csv", str(param_file.resolve()),
        "--prefix", "ngrid_det",
        "--harvest-var", "CHPDT",
        "--keep-nitrogen-outputs",
    ]
    res = subprocess.run(cmd, cwd=work_dir, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Run failed in {work_dir}: {res.stderr[:200]}", file=sys.stderr)
        return {"error": 1.0}

    # Generate comparison tables
    for season in SEASONS:
        sid = season["season_id"]
        season_dir = work_dir / "_seasons" / sid
        if not season_dir.exists():
            continue
        filex_matches = list(season_dir.glob("*.TMX"))
        if not filex_matches:
            continue
        filex = filex_matches[0]
        batch = season_dir / "analysis_batch.v48"
        batch.write_text(
            "\n".join(f"{filex.resolve()} {int(tn)} 1 0 0 0" for tn in season["treatments"]) + "\n",
            encoding="utf-8",
        )
        deterministic_process_compare(
            sid, str(batch),
            var_names=["L#SD", "LAID", "LWAD", "SWAD", "CHTD"],
            run_dir=str(season_dir),
        )
        deterministic_harvest_compare(sid, str(batch), run_dir=str(season_dir))

    metrics_out: dict[str, float] = {}

    # 1. 25SP metrics
    h25_csv = work_dir / "_seasons/25SP/25SP_deterministic_harvest_compare.csv"
    if h25_csv.exists():
        df25 = pd.read_csv(h25_csv)
        h_end25 = df25.sort_values(by=["TN", "HNO"]).groupby("TN").last().reset_index()
        
        y25 = h_end25["OBS_DRY_CUM"].to_numpy(float)
        p25 = h_end25["SIM_DRY_CUM"].to_numpy(float)
        rmse25 = float(np.sqrt(np.mean((p25 - y25) ** 2)))
        rrmse25 = float(100 * rmse25 / np.mean(y25)) if np.mean(y25) > 0 else np.nan
        
        metrics_out["25SP_term_dry_rrmse_pct"] = rrmse25
        metrics_out["25SP_term_dry_obs_mean"] = float(np.mean(y25))
        metrics_out["25SP_term_dry_sim_mean"] = float(np.mean(p25))
        
        # TN2=W3N3, TN5=W3N0, TN10=W1N3, TN13=W1N0
        s_w3n3 = float(h_end25[h_end25["TN"] == 2]["SIM_DRY_CUM"].values[0]) if (h_end25["TN"] == 2).any() else np.nan
        s_w3n0 = float(h_end25[h_end25["TN"] == 5]["SIM_DRY_CUM"].values[0]) if (h_end25["TN"] == 5).any() else np.nan
        s_w1n3 = float(h_end25[h_end25["TN"] == 10]["SIM_DRY_CUM"].values[0]) if (h_end25["TN"] == 10).any() else np.nan
        s_w1n0 = float(h_end25[h_end25["TN"] == 13]["SIM_DRY_CUM"].values[0]) if (h_end25["TN"] == 13).any() else np.nan
        
        metrics_out["25SP_W3N3_dry_sim"] = s_w3n3
        metrics_out["25SP_W3N0_dry_sim"] = s_w3n0
        metrics_out["25SP_W1N3_dry_sim"] = s_w1n3
        metrics_out["25SP_W1N0_dry_sim"] = s_w1n0
        metrics_out["25SP_W3_N3_minus_N0"] = s_w3n3 - s_w3n0
        metrics_out["25SP_W1_N3_minus_N0"] = s_w1n3 - s_w1n0

    # 2. 26SP metrics
    h26_csv = work_dir / "_seasons/26SP/26SP_deterministic_harvest_compare.csv"
    if h26_csv.exists():
        df26 = pd.read_csv(h26_csv)
        h_end26 = df26.sort_values(by=["TN", "HNO"]).groupby("TN").last().reset_index()
        
        y26 = h_end26["OBS_DRY_CUM"].to_numpy(float)
        p26 = h_end26["SIM_DRY_CUM"].to_numpy(float)
        rmse26 = float(np.sqrt(np.mean((p26 - y26) ** 2)))
        rrmse26 = float(100 * rmse26 / np.mean(y26)) if np.mean(y26) > 0 else np.nan
        
        metrics_out["26SP_term_dry_rrmse_pct"] = rrmse26
        metrics_out["26SP_term_dry_obs_mean"] = float(np.mean(y26))
        metrics_out["26SP_term_dry_sim_mean"] = float(np.mean(p26))
        
        # TN1=W3N3, TN9=W3N0, TN3=W1N3, TN12=W1N0
        s26_w3n3 = float(h_end26[h_end26["TN"] == 1]["SIM_DRY_CUM"].values[0]) if (h_end26["TN"] == 1).any() else np.nan
        s26_w3n0 = float(h_end26[h_end26["TN"] == 9]["SIM_DRY_CUM"].values[0]) if (h_end26["TN"] == 9).any() else np.nan
        s26_w1n3 = float(h_end26[h_end26["TN"] == 3]["SIM_DRY_CUM"].values[0]) if (h_end26["TN"] == 3).any() else np.nan
        s26_w1n0 = float(h_end26[h_end26["TN"] == 12]["SIM_DRY_CUM"].values[0]) if (h_end26["TN"] == 12).any() else np.nan
        
        metrics_out["26SP_W3N3_dry_sim"] = s26_w3n3
        metrics_out["26SP_W3N0_dry_sim"] = s26_w3n0
        metrics_out["26SP_W1N3_dry_sim"] = s26_w1n3
        metrics_out["26SP_W1N0_dry_sim"] = s26_w1n0
        metrics_out["26SP_W3_N3_minus_N0"] = s26_w3n3 - s26_w3n0
        metrics_out["26SP_W1_N3_minus_N0"] = s26_w1n3 - s26_w1n0

    # 3. Process LAI NSE
    for sid in ("25SP", "26SP"):
        proc_csv = work_dir / f"_seasons/{sid}/{sid}_deterministic_process_compare.csv"
        if proc_csv.exists():
            df_p = pd.read_csv(proc_csv)
            for var_name in ("LAID", "LWAD", "SWAD"):
                if f"OBS_{var_name}" in df_p.columns and f"SIM_{var_name}" in df_p.columns:
                    y_v = pd.to_numeric(df_p[f"OBS_{var_name}"], errors="coerce").to_numpy(float)
                    p_v = pd.to_numeric(df_p[f"SIM_{var_name}"], errors="coerce").to_numpy(float)
                    ok = ~np.isnan(y_v) & ~np.isnan(p_v) & (y_v > -90) & (p_v > -90)
                    if ok.sum() > 3:
                        sst = float(np.sum((y_v[ok] - y_v[ok].mean()) ** 2))
                        metrics_out[f"{sid}_{var_name}_NSE"] = float(1 - np.sum((p_v[ok] - y_v[ok]) ** 2) / sst) if sst > 0 else np.nan

    # 4. Overall Multi-Season Composite Score (with amplified N_RESPONSE weight & penalty)
    r25 = metrics_out.get("25SP_term_dry_rrmse_pct", 50.0)
    r26 = metrics_out.get("26SP_term_dry_rrmse_pct", 50.0)
    g25_w3 = metrics_out.get("25SP_W3_N3_minus_N0", -100.0)
    g25_w1 = metrics_out.get("25SP_W1_N3_minus_N0", -100.0)
    g26_w3 = metrics_out.get("26SP_W3_N3_minus_N0", -100.0)
    g26_w1 = metrics_out.get("26SP_W1_N3_minus_N0", -100.0)
    lai25_nse = metrics_out.get("25SP_LAID_NSE", 0.0)
    lai26_nse = metrics_out.get("26SP_LAID_NSE", 0.0)

    # Amplified N_RESPONSE penalty (lambda_pen = 0.20 per kg/ha negative gap, heavy penalty)
    pen_w3_25 = max(0.0, -g25_w3) * 0.20
    pen_w1_25 = max(0.0, -g25_w1) * 0.20
    pen_w3_26 = max(0.0, -g26_w3) * 0.20
    pen_w1_26 = max(0.0, -g26_w1) * 0.20
    
    # Reward for strong positive N response (> 100 kg/ha)
    reward_25 = min(20.0, max(0.0, (g25_w3 + g25_w1) * 0.02))
    reward_26 = min(20.0, max(0.0, (g26_w3 + g26_w1) * 0.02))

    lai_penalty = max(0.0, 1.0 - lai25_nse) * 5.0 + max(0.0, 1.0 - lai26_nse) * 5.0
    
    composite = float((r25 + r26) / 2.0 + pen_w3_25 + pen_w1_25 + pen_w3_26 + pen_w1_26 + lai_penalty - reward_25 - reward_26)
    metrics_out["composite_score"] = composite

    return metrics_out


def create_candidate_profiles() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    # 0. Baseline (Anchor best125)
    candidates.append({
        "scenario_id": "S00_BASELINE",
        "description": "Baseline anchor best125 (v40)",
        "mods": {},
    })

    # Group 1: Nitrogen Stress Sensitivity (NSTFAC)
    for nstfac in [0.35, 0.50, 0.65, 0.75, 0.85]:
        candidates.append({
            "scenario_id": f"G1_NSTFAC_{nstfac:.2f}",
            "description": f"NSTFAC={nstfac:.2f}",
            "mods": {"NSTFAC": nstfac},
        })

    # Group 2: Root N Uptake (RTNO3, RTNH4)
    for no3, nh4 in [(0.045, 0.030), (0.035, 0.022), (0.028, 0.018), (0.020, 0.012)]:
        candidates.append({
            "scenario_id": f"G2_RTNO3_{no3:.3f}_RTNH4_{nh4:.3f}",
            "description": f"RTNO3={no3}, RTNH4={nh4}",
            "mods": {"RTNO3": no3, "RTNH4": nh4},
        })

    # Group 3: Source-Sink & Canopy (XFRT, PODUR, SFDUR, LFMAX)
    for xfrt in [0.90, 0.95, 0.98]:
        candidates.append({
            "scenario_id": f"G3_XFRT_{xfrt:.2f}",
            "description": f"XFRT={xfrt}",
            "mods": {"XFRT": xfrt},
        })
    for podur in [18.0, 24.0, 30.0]:
        candidates.append({
            "scenario_id": f"G3_PODUR_{podur:.1f}",
            "description": f"PODUR={podur}",
            "mods": {"PODUR": podur},
        })
    for lfmax in [1.35, 1.65, 2.00]:
        candidates.append({
            "scenario_id": f"G3_LFMAX_{lfmax:.2f}",
            "description": f"LFMAX={lfmax}",
            "mods": {"LFMAX": lfmax},
        })

    # Group 4: N Remobilization & Photosynthesis (NVSMOB, NMOBMX, FNPGN)
    for nvsmob in [0.25, 0.40, 0.55]:
        candidates.append({
            "scenario_id": f"G4_NVSMOB_{nvsmob:.2f}",
            "description": f"NVSMOB={nvsmob}",
            "mods": {"NVSMOB": nvsmob},
        })
    for nmobmx in [0.05, 0.12, 0.20]:
        candidates.append({
            "scenario_id": f"G4_NMOBMX_{nmobmx:.2f}",
            "description": f"NMOBMX={nmobmx}",
            "mods": {"NMOBMX": nmobmx},
        })
    for f1, f2 in [(1.20, 3.80), (2.00, 4.80), (3.20, 5.90)]:
        candidates.append({
            "scenario_id": f"G4_FNPGN_{f1:.1f}_{f2:.1f}",
            "description": f"FNPGN1={f1}, FNPGN2={f2}",
            "mods": {"FNPGN1": f1, "FNPGN2": f2},
        })

    # Group 5: Synergy Combinations
    # S1: v23 classical transplant
    candidates.append({
        "scenario_id": "G5_SYN_01_v23_classic",
        "description": "v23 classical transplant (NSTFAC=0.79, RTNO3=0.030, XFRT=0.97, PODUR=28, LFMAX=1.40)",
        "mods": {"NSTFAC": 0.79, "RTNO3": 0.030, "RTNH4": 0.019, "XFRT": 0.97, "PODUR": 28.0, "LFMAX": 1.40, "SLAVR": 280.0},
    })
    # S2: High stress + Controlled uptake
    candidates.append({
        "scenario_id": "G5_SYN_02_high_stress_ctrl_uptake",
        "description": "High stress NSTFAC=0.85 + RTNO3=0.022 + NMOBMX=0.08",
        "mods": {"NSTFAC": 0.85, "RTNO3": 0.022, "RTNH4": 0.015, "NMOBMX": 0.08, "NVSMOB": 0.35},
    })
    # S3: Moderate stress + Strong sink
    candidates.append({
        "scenario_id": "G5_SYN_03_mod_stress_strong_sink",
        "description": "NSTFAC=0.75 + RTNO3=0.028 + XFRT=0.95 + PODUR=26",
        "mods": {"NSTFAC": 0.75, "RTNO3": 0.028, "RTNH4": 0.018, "XFRT": 0.95, "PODUR": 26.0, "LFMAX": 1.50},
    })
    # S4: Steep Photosynthesis + High Mobilization
    candidates.append({
        "scenario_id": "G5_SYN_04_steep_photo_high_mob",
        "description": "NSTFAC=0.70 + RTNO3=0.028 + FNPGN=(2.5, 5.2) + NVSMOB=0.45",
        "mods": {"NSTFAC": 0.70, "RTNO3": 0.028, "FNPGN1": 2.50, "FNPGN2": 5.20, "NVSMOB": 0.45, "NMOBMX": 0.15},
    })
    # S5: Full Multi-Mechanism Synergy
    candidates.append({
        "scenario_id": "G5_SYN_05_full_balanced_synergy",
        "description": "Full multi-mechanism synergy (NSTFAC=0.80, RTNO3=0.028, XFRT=0.96, PODUR=28, FNPGN=(2.5, 5.0))",
        "mods": {
            "NSTFAC": 0.80, "RTNO3": 0.028, "RTNH4": 0.018,
            "XFRT": 0.96, "PODUR": 28.0, "SFDUR": 30.0, "LFMAX": 1.45,
            "NVSMOB": 0.35, "NMOBMX": 0.10, "FNPGN1": 2.50, "FNPGN2": 5.00
        },
    })
    # S6: Ultra Stress + High Partitioning
    candidates.append({
        "scenario_id": "G5_SYN_06_ultra_stress_high_part",
        "description": "NSTFAC=0.90 + RTNO3=0.020 + XFRT=0.98 + PODUR=30",
        "mods": {
            "NSTFAC": 0.90, "RTNO3": 0.020, "RTNH4": 0.012,
            "XFRT": 0.98, "PODUR": 30.0, "LFMAX": 1.35, "SLAVR": 290.0,
            "NVSMOB": 0.30, "NMOBMX": 0.08
        },
    })
    # S7: Sensitive N + Mid Partitioning
    candidates.append({
        "scenario_id": "G5_SYN_07_sensitive_n_mid_part",
        "description": "NSTFAC=0.75 + RTNO3=0.025 + XFRT=0.92 + PODUR=24",
        "mods": {
            "NSTFAC": 0.75, "RTNO3": 0.025, "RTNH4": 0.016,
            "XFRT": 0.92, "PODUR": 24.0, "LFMAX": 1.60,
            "NVSMOB": 0.40, "NMOBMX": 0.12
        },
    })
    # S8: Controlled Uptake + v23 Canopy
    candidates.append({
        "scenario_id": "G5_SYN_08_ctrl_uptake_v23_canopy",
        "description": "RTNO3=0.028 + NSTFAC=0.82 + LFMAX=1.38 + SIZLF=300 + SLAVR=295",
        "mods": {
            "NSTFAC": 0.82, "RTNO3": 0.028, "RTNH4": 0.018,
            "LFMAX": 1.38, "SIZLF": 300.0, "SLAVR": 295.0,
            "XFRT": 0.97, "PODUR": 28.0
        },
    })

    return candidates


def main() -> int:
    print("=" * 90)
    print("STARTING NITROGEN SYNERGY PARAMETER GRID SCAN EXPERIMENT")
    print("=" * 90)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base_df = load_base_params()
    candidates = create_candidate_profiles()
    print(f"Loaded {len(base_df)} base parameters. Formatted {len(candidates)} candidate grid scenarios.\n")

    results: list[dict[str, Any]] = []
    t0 = time.time()

    for idx, c in enumerate(candidates, 1):
        sid = c["scenario_id"]
        desc = c["description"]
        mods = c["mods"]
        print(f"[{idx:02d}/{len(candidates):02d}] Evaluating {sid} ({desc})...")

        p_df = base_df.copy()
        for k, v in mods.items():
            mask = p_df["name"].str.upper() == k.upper()
            if mask.any():
                p_df.loc[mask, "value"] = v
            else:
                p_df = pd.concat([p_df, pd.DataFrame([{"name": k, "value": v}])], ignore_index=True)

        work_dir = OUTPUT_DIR / sid
        metrics = evaluate_param_set(p_df, work_dir)

        row: dict[str, Any] = {
            "scenario_id": sid,
            "description": desc,
            **mods,
            **metrics,
        }
        results.append(row)

        g25_w3 = metrics.get("25SP_W3_N3_minus_N0", np.nan)
        g25_w1 = metrics.get("25SP_W1_N3_minus_N0", np.nan)
        r25 = metrics.get("25SP_term_dry_rrmse_pct", np.nan)
        r26 = metrics.get("26SP_term_dry_rrmse_pct", np.nan)
        score = metrics.get("composite_score", np.nan)

        status_flag = "[PASS POSITIVE]" if (g25_w3 > 0 and g25_w1 > 0) else "[INVERTED]"
        print(f"       -> 25SP W3 N3-N0: {g25_w3:+6.1f} kg/ha | W1 N3-N0: {g25_w1:+6.1f} kg/ha {status_flag}")
        print(f"       -> RRMSE 25SP: {r25:5.1f}% | 26SP: {r26:5.1f}% | Composite Score: {score:6.2f}\n")

    df_res = pd.DataFrame(results)
    out_csv = OUTPUT_DIR / "grid_scan_full_results.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\n[COMPLETED] Grid scan finished in {time.time() - t0:.1f}s. Saved to {out_csv}")

    # Ranking and Summary
    print("\n" + "=" * 90)
    print("TOP CANDIDATES RANKED BY COMPOSITE SCORE (WITH POSITIVE 25SP NITROGEN RESPONSE)")
    print("=" * 90)

    # Filter positive 25SP N response
    pos_mask = (df_res["25SP_W3_N3_minus_N0"] > 0) & (df_res["25SP_W1_N3_minus_N0"] > 0)
    df_pos = df_res[pos_mask].sort_values("composite_score", ascending=True)

    if not df_pos.empty:
        cols_show = [
            "scenario_id", "composite_score",
            "25SP_W3_N3_minus_N0", "25SP_W1_N3_minus_N0",
            "26SP_W3_N3_minus_N0", "26SP_W1_N3_minus_N0",
            "25SP_term_dry_rrmse_pct", "26SP_term_dry_rrmse_pct",
            "25SP_LAID_NSE", "26SP_LAID_NSE"
        ]
        cols_show = [c for c in cols_show if c in df_pos.columns]
        print(df_pos[cols_show].head(10).to_string(index=False))
    else:
        print("No candidate achieved strictly positive N response on both W3 and W1 in 25SP. Showing top lowest-penalty candidates:")
        print(df_res.sort_values("composite_score")[["scenario_id", "composite_score", "25SP_W3_N3_minus_N0", "25SP_W1_N3_minus_N0", "25SP_term_dry_rrmse_pct"]].head(10).to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
