"""tools/sensitivity/run_nitrogen_grid_scan_20260830.py

Grid scan and sensitivity exploration script to resolve 25SP N0 > N3 yield inversion
while preserving 26SP accuracy and multi-season crop physiology.
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
            for var in ("LAID", "LWAD", "SWAD"):
                if f"OBS_{var}" in df_p.columns and f"SIM_{var}" in df_p.columns:
                    y_v = pd.to_numeric(df_p[f"OBS_{var}"], errors="coerce").to_numpy(float)
                    p_v = pd.to_numeric(df_p[f"SIM_{var}"], errors="coerce").to_numpy(float)
                    ok = ~np.isnan(y_v) & ~np.isnan(p_v) & (y_v > -90) & (p_v > -90)
                    if ok.sum() > 3:
                        sst = float(np.sum((y_v[ok] - y_v[ok].mean()) ** 2))
                        metrics_out[f"{sid}_{var}_NSE"] = float(1 - np.sum((p_v[ok] - y_v[ok]) ** 2) / sst) if sst > 0 else np.nan

    # 4. Overall Multi-Season Composite Score
    # Score = mean RRMSE + Penalty for 25SP inverted gradients (each kg/ha negative adds penalty)
    r25 = metrics_out.get("25SP_term_dry_rrmse_pct", 50.0)
    r26 = metrics_out.get("26SP_term_dry_rrmse_pct", 50.0)
    g25_w3 = metrics_out.get("25SP_W3_N3_minus_N0", -100.0)
    g25_w1 = metrics_out.get("25SP_W1_N3_minus_N0", -100.0)
    
    # Inversion penalty: if g25_w3 < 0, penalty proportional to gap
    pen_w3 = max(0.0, -g25_w3) * 0.1
    pen_w1 = max(0.0, -g25_w1) * 0.1
    metrics_out["composite_score"] = float((r25 + r26) / 2.0 + pen_w3 + pen_w1)

    return metrics_out


def create_candidate_profiles(base_df: pd.DataFrame) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    # 0. Baseline (Anchor best125)
    candidates.append({
        "scenario_id": "S00_BASELINE",
        "description": "Baseline anchor best125 (v40)",
        "mods": {},
    })

    # Group 1: Single Parameter Sweeps on PROLFF (Leaf Min Protein)
    for v in [0.150, 0.180, 0.210, 0.240]:
        candidates.append({
            "scenario_id": f"S1_PROLFF_{v:.3f}",
            "description": f"PROLFF={v}",
            "mods": {"PROLFF": v},
        })

    # Group 2: Single Parameter Sweeps on PROSTF (Stem Min Protein)
    for v in [0.070, 0.100, 0.130]:
        candidates.append({
            "scenario_id": f"S2_PROSTF_{v:.3f}",
            "description": f"PROSTF={v}",
            "mods": {"PROSTF": v},
        })

    # Group 3: Single Parameter Sweeps on NVSMOB (Fraction Remobilizable N)
    for v in [0.250, 0.400, 0.550]:
        candidates.append({
            "scenario_id": f"S3_NVSMOB_{v:.3f}",
            "description": f"NVSMOB={v}",
            "mods": {"NVSMOB": v},
        })

    # Group 4: Single Parameter Sweeps on NMOBMX (Max N Mining Rate)
    for v in [0.080, 0.150, 0.250]:
        candidates.append({
            "scenario_id": f"S4_NMOBMX_{v:.3f}",
            "description": f"NMOBMX={v}",
            "mods": {"NMOBMX": v},
        })

    # Group 5: Single Parameter Sweeps on FNPGN1 & FNPGN2 (Photosynthesis vs Leaf N)
    for f1, f2 in [(1.20, 3.80), (1.50, 4.20), (1.80, 4.50), (2.00, 4.80)]:
        candidates.append({
            "scenario_id": f"S5_FNPGN_{f1}_{f2}",
            "description": f"FNPGN1={f1}, FNPGN2={f2}",
            "mods": {"FNPGN1": f1, "FNPGN2": f2},
        })

    # Group 6: Single Parameter Sweeps on SENRTE & SENDAY (N Senescence)
    for sr, sd in [(3.50, 0.04), (5.00, 0.06), (7.00, 0.08)]:
        candidates.append({
            "scenario_id": f"S6_SENES_{sr}_{sd}",
            "description": f"SENRTE={sr}, SENDAY={sd}",
            "mods": {"SENRTE": sr, "SENDAY": sd},
        })

    # Group 7: Single Parameter Sweeps on NREXP & NSTFAC (N Stress Exponent)
    for nre, nst in [(0.70, 0.35), (0.90, 0.50), (1.10, 0.65)]:
        candidates.append({
            "scenario_id": f"S7_NSTRESS_{nre}_{nst}",
            "description": f"NREXP={nre}, NSTFAC={nst}",
            "mods": {"NREXP": nre, "NSTFAC": nst},
        })

    # Group 8: Synergistic Multi-Parameter Packages
    synergies = [
        {
            "id": "SYN_A_MODERATE_RESTRICTION",
            "desc": "PROLFF=0.18, PROSTF=0.08, NVSMOB=0.45, NMOBMX=0.15",
            "mods": {"PROLFF": 0.180, "PROSTF": 0.080, "NVSMOB": 0.450, "NMOBMX": 0.150},
        },
        {
            "id": "SYN_B_STRONG_PROTEIN_FLOOR",
            "desc": "PROLFF=0.22, PROSTF=0.10, NVSMOB=0.35, NMOBMX=0.10",
            "mods": {"PROLFF": 0.220, "PROSTF": 0.100, "NVSMOB": 0.350, "NMOBMX": 0.100},
        },
        {
            "id": "SYN_C_PROTEIN_PLUS_FNPGN",
            "desc": "PROLFF=0.20, PROSTF=0.09, NVSMOB=0.40, FNPGN1=1.5, FNPGN2=4.2",
            "mods": {"PROLFF": 0.200, "PROSTF": 0.090, "NVSMOB": 0.400, "FNPGN1": 1.500, "FNPGN2": 4.200},
        },
        {
            "id": "SYN_D_PROTEIN_PLUS_SENESCENCE",
            "desc": "PROLFF=0.20, PROSTF=0.09, NVSMOB=0.40, SENRTE=4.5, SENDAY=0.05",
            "mods": {"PROLFF": 0.200, "PROSTF": 0.090, "NVSMOB": 0.400, "SENRTE": 4.500, "SENDAY": 0.050},
        },
        {
            "id": "SYN_E_FULL_HARMONIZED_REVISION",
            "desc": "PROLFF=0.22, PROSTF=0.10, NVSMOB=0.35, NMOBMX=0.10, FNPGN1=1.5, FNPGN2=4.2, SENRTE=4.5, SENDAY=0.05, NREXP=0.85",
            "mods": {
                "PROLFF": 0.220,
                "PROSTF": 0.100,
                "NVSMOB": 0.350,
                "NMOBMX": 0.100,
                "FNPGN1": 1.500,
                "FNPGN2": 4.200,
                "SENRTE": 4.500,
                "SENDAY": 0.050,
                "NREXP": 0.850,
            },
        },
        {
            "id": "SYN_F_AGGRESSIVE_GRADIENT_CORRECTION",
            "desc": "PROLFF=0.24, PROSTF=0.12, NVSMOB=0.25, NMOBMX=0.06, FNPGN1=1.8, FNPGN2=4.5, SENRTE=5.5, SENDAY=0.06, NREXP=1.00",
            "mods": {
                "PROLFF": 0.240,
                "PROSTF": 0.120,
                "NVSMOB": 0.250,
                "NMOBMX": 0.060,
                "FNPGN1": 1.800,
                "FNPGN2": 4.500,
                "SENRTE": 5.500,
                "SENDAY": 0.060,
                "NREXP": 1.000,
            },
        },
    ]
    for syn in synergies:
        candidates.append({
            "scenario_id": syn["id"],
            "description": syn["desc"],
            "mods": syn["mods"],
        })

    return candidates


def main() -> int:
    start_time = time.time()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base_df = load_base_params()

    candidates = create_candidate_profiles(base_df)
    print(f"Loaded baseline params. Total exploration scenarios to run: {len(candidates)}", flush=True)

    results: list[dict[str, Any]] = []

    for i, sc in enumerate(candidates, start=1):
        sid = sc["scenario_id"]
        desc = sc["description"]
        mods = sc["mods"]
        work_dir = OUTPUT_DIR / sid

        # Apply parameter modifications
        df_cur = base_df.copy()
        for p_name, p_val in mods.items():
            idx = df_cur[df_cur["name"].str.upper() == p_name.upper()].index
            if not idx.empty:
                df_cur.loc[idx, "value"] = float(p_val)
            else:
                df_cur = pd.concat([df_cur, pd.DataFrame([{"name": p_name, "value": float(p_val)}])], ignore_index=True)

        print(f"\n[{i}/{len(candidates)}] Running {sid}: {desc}", flush=True)
        t0 = time.time()
        metrics = evaluate_param_set(df_cur, work_dir)
        elapsed = time.time() - t0

        rec = {
            "scenario_id": sid,
            "description": desc,
            "elapsed_sec": round(elapsed, 2),
            **mods,
            **metrics,
        }
        results.append(rec)

        # Print live feedback
        g25_w3 = metrics.get("25SP_W3_N3_minus_N0", np.nan)
        g25_w1 = metrics.get("25SP_W1_N3_minus_N0", np.nan)
        r25 = metrics.get("25SP_term_dry_rrmse_pct", np.nan)
        r26 = metrics.get("26SP_term_dry_rrmse_pct", np.nan)
        score = metrics.get("composite_score", np.nan)
        print(f"  -> 25SP W3(N3-N0)={g25_w3:>+6.1f} kg/ha | 25SP W1(N3-N0)={g25_w1:>+6.1f} kg/ha | 25SP RRMSE={r25:>5.1f}% | 26SP RRMSE={r26:>5.1f}% | Score={score:>5.1f}", flush=True)

    res_df = pd.DataFrame(results)
    summary_csv = OUTPUT_DIR / "nitrogen_grid_scan_summary.csv"
    res_df.to_csv(summary_csv, index=False)
    print(f"\nSaved all {len(res_df)} scenario evaluations to {summary_csv}")

    # Display Top 10 scenarios ranked by composite score (lowest score is best)
    print("\n" + "=" * 80)
    print("TOP 10 CANDIDATE PROFILES RANKED BY COMPOSITE SCORE:")
    print("=" * 80)
    top10 = res_df.sort_values(by="composite_score", ascending=True).head(10)
    cols_show = ["scenario_id", "composite_score", "25SP_W3_N3_minus_N0", "25SP_W1_N3_minus_N0", "25SP_term_dry_rrmse_pct", "26SP_term_dry_rrmse_pct", "25SP_LAID_NSE", "26SP_LAID_NSE"]
    existing_cols = [c for c in cols_show if c in top10.columns]
    print(top10[existing_cols].to_string(index=False))

    total_time = time.time() - start_time
    print(f"\nTotal Grid Scan completed in {total_time:.1f} seconds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
