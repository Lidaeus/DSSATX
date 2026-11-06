"""Build, Launch, and Evaluate Multi-Arm v32 Parallel Exploration Experiments.

Arms:
- Arm A: Baseline Rebalanced Control (Moderate rebalance)
- Arm B: Sink Duration & Remobilization Breakthrough (Focus on H3 & duration)
- Arm C: Nitrogen Stress Mitigation & Uptake Dynamics (Focus on N0 resilience)
- Arm D: Condensed 25-Parameter Integrated Synergy (Core physiological active set)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.evaluate_fixedsoil_official_best189_20260813 as evaluation

OFFICIAL = ROOT / "DSCSM048.EXE"
LIVE = ROOT / "workspace/DSCSM048.EXE"
BACKUP = ROOT / "workspace/DSCSM048.EXE.before_multiarm_v32_20260829"

ARMS = [
    {
        "arm_id": "arma",
        "name": "Arm A: Baseline Rebalanced Control",
        "bounds_id": "eggplant_e02_v32_arm_a_baseline_bounds",
        "group_policy": "e02_from_scratch_group_policy_v32_arma",
        "case": "e02_multiarm_v32_arma_20260829",
        "run_id": "e02_multiarm_v32_arma_60x4_20260829",
        "port": 4020,
    },
    {
        "arm_id": "armb",
        "name": "Arm B: Sink Duration & Remobilization Breakthrough",
        "bounds_id": "eggplant_e02_v32_arm_b_sink_filling_bounds",
        "group_policy": "e02_from_scratch_group_policy_v32_armb",
        "case": "e02_multiarm_v32_armb_20260829",
        "run_id": "e02_multiarm_v32_armb_60x4_20260829",
        "port": 4030,
    },
    {
        "arm_id": "armc",
        "name": "Arm C: Nitrogen Stress Mitigation & Uptake",
        "bounds_id": "eggplant_e02_v32_arm_c_nitrogen_resilience_bounds",
        "group_policy": "e02_from_scratch_group_policy_v32_armc",
        "case": "e02_multiarm_v32_armc_20260829",
        "run_id": "e02_multiarm_v32_armc_60x4_20260829",
        "port": 4040,
    },
    {
        "arm_id": "armd",
        "name": "Arm D: Condensed 25-Parameter Integrated Synergy",
        "bounds_id": "eggplant_e02_v32_arm_d_condensed_integrated_bounds",
        "group_policy": "e02_from_scratch_group_policy_v32_armd",
        "case": "e02_multiarm_v32_armd_20260829",
        "run_id": "e02_multiarm_v32_armd_60x4_20260829",
        "port": 4050,
    },
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_arm(arm: dict[str, Any]) -> None:
    run_dir = ROOT / "workspace/runs" / arm["run_id"]
    cfg_json = ROOT / "configs/runs" / f"{arm['run_id']}.json"
    cmd = [
        sys.executable,
        str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--prefix", arm["case"],
        "--bounds-id", arm["bounds_id"],
        "--bounds-crop", "eggplant",
        "--multiseason-design", str(cfg_json),
        "--noptmax", "4",
        "--ies-num-reals", "60",
        "--batch", "DSSBatch.v48",
        "--harvest-var", "CHPDT",
        "--param-review-mode", "off",
        "--out-dir", str(run_dir),
    ]
    print(f"\n[BUILD] Building PEST setup for {arm['name']}...")
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error building {arm['arm_id']}:\n{res.stderr}")
        raise RuntimeError(f"Build failed for {arm['arm_id']}")
    print(f"[BUILD] {arm['name']} built successfully at {run_dir.name}")


def run_arm(arm: dict[str, Any]) -> None:
    run_dir = ROOT / "workspace/runs" / arm["run_id"]
    pst = run_dir / f"{arm['case']}.pst"
    if not pst.is_file():
        raise FileNotFoundError(pst)

    receipt = {
        "schema_version": 1,
        "arm_id": arm["arm_id"],
        "name": arm["name"],
        "case": arm["case"],
        "run_dir": str(run_dir),
        "launched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dssat_variant": "official DSSAT v4.8",
        "official_exe_sha256": sha256(OFFICIAL),
        "bounds_id": arm["bounds_id"],
        "realizations": 60,
        "noptmax": 4,
        "agents": 6,
        "port": arm["port"],
    }
    (run_dir / "arm_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    cmd = [
        sys.executable,
        str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir),
        "--case", arm["case"],
        "--mode", "ies",
        "--n-agents", "6",
        "--port", str(arm["port"]),
        "--wait",
    ]
    print(f"\n[RUN] Launching PEST++ IES for {arm['name']} on port {arm['port']}...")
    res = subprocess.run(cmd, cwd=ROOT, check=False)
    if res.returncode != 0:
        print(f"Warning: {arm['name']} exited with code {res.returncode}")
    else:
        print(f"[RUN] {arm['name']} calibration finished successfully!")


def evaluate_arm(arm: dict[str, Any]) -> dict[str, Any]:
    run_dir = ROOT / "workspace/runs" / arm["run_id"]
    case = arm["case"]
    phi_csv = run_dir / f"{case}.phi.actual.csv"
    if not phi_csv.is_file():
        return {"arm_id": arm["arm_id"], "name": arm["name"], "status": "failed"}

    phi_df = pd.read_csv(phi_csv, index_col=0)
    member_cols = [c for c in phi_df.columns if str(c).isdigit()]
    candidates = []
    for iteration in phi_df.index:
        values = pd.to_numeric(phi_df.loc[iteration, member_cols], errors="coerce")
        for member, val in values.items():
            if pd.notna(val):
                candidates.append((float(val), int(iteration), str(member)))
    if not candidates:
        return {"arm_id": arm["arm_id"], "name": arm["name"], "status": "no_valid_phi"}

    best_phi, best_iter, best_member = min(candidates)
    det_root = run_dir / f"best_member_{best_member}_two_season_deterministic_20260829"
    out_root = ROOT / "figture" / f"e02_multiarm_v32_{arm['arm_id']}_best{best_member}_20260829"

    evaluation.RUN_DIR = run_dir
    evaluation.DET_ROOT = det_root
    evaluation.OUT_ROOT = out_root
    evaluation.FIGURE = ROOT / "figture"
    evaluation.CASE = case
    evaluation.BEST_MEMBER = best_member
    evaluation.SOURCE_ITERATION = best_iter
    evaluation.BEST_PHI = best_phi
    evaluation.CALIBRATION_STATE = "completed_engineering_validated"
    evaluation.ARTIFACT_TYPE = f"multiarm_v32_{arm['arm_id']}_deterministic"
    evaluation.SPE = ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.OBS_REGISTRY = run_dir / f"{case}_observation_registry.csv"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.SEASONS = [
        {
            "season_id": "25SP",
            "excode": "XXQL2501",
            "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
            "bundle": ROOT / "data/user/experiments/xxql2501_formal_armab_rrmse_20260828",
        },
        {
            "season_id": "26SP",
            "excode": "XXQL2601",
            "treatments": list(range(1, 13)),
            "bundle": ROOT / "data/user/experiments/xxql2601_formal_armab_rrmse_26spncal_20260828",
        },
    ]
    evaluation.CALIBRATION_TREATMENTS = {
        "25SP": [2, 5, 10, 13],
        "26SP": [1, 3, 9, 12],
    }
    evaluation.DIAGNOSTIC_TREATMENTS = {
        "25SP": [3, 4, 9, 11, 12, 14],
        "26SP": [2, 4, 5, 6, 7, 8, 10, 11],
    }

    evaluation.main()

    # Extract score metrics
    metrics_summary: dict[str, Any] = {
        "arm_id": arm["arm_id"],
        "name": arm["name"],
        "best_member": best_member,
        "best_iteration": best_iter,
        "best_phi": best_phi,
    }

    # Harvest metrics
    h26_file = det_root / "_seasons/26SP/26SP_deterministic_harvest_compare.csv"
    if h26_file.exists():
        df_h26 = pd.read_csv(h26_file)
        h3_sub = df_h26[df_h26["HNO"] == 3]
        if not h3_sub.empty:
            metrics_summary["26SP_H3_sim_inc"] = float(h3_sub["SIM_DRY_INC"].mean())
            metrics_summary["26SP_H3_gap"] = float((h3_sub["SIM_DRY_INC"] - h3_sub["OBS_DRY_INC"]).mean())

        h5_sub = df_h26.sort_values(by=["TN", "HNO"]).groupby("TN").last().reset_index()
        y = h5_sub["OBS_DRY_CUM"].to_numpy(float)
        p = h5_sub["SIM_DRY_CUM"].to_numpy(float)
        err = p - y
        rmse = float(np.sqrt(np.mean(err**2)))
        rrmse = float(100 * rmse / np.mean(y)) if np.mean(y) > 0 else np.nan
        metrics_summary["26SP_term_dry_rrmse_pct"] = rrmse
        metrics_summary["26SP_term_dry_bias"] = float(np.mean(err))

        n0_sub = h5_sub[h5_sub["TN"].isin([9, 11, 12])]
        n1_sub = h5_sub[h5_sub["TN"].isin([7, 8, 10])]
        n3_sub = h5_sub[h5_sub["TN"].isin([1, 2, 3])]
        if not n0_sub.empty:
            metrics_summary["26SP_N0_sim_mean"] = float(n0_sub["SIM_DRY_CUM"].mean())
            metrics_summary["26SP_N0_bias_pct"] = float(((n0_sub["SIM_DRY_CUM"] - n0_sub["OBS_DRY_CUM"]) / n0_sub["OBS_DRY_CUM"] * 100).mean())
        if not n1_sub.empty:
            metrics_summary["26SP_N1_sim_mean"] = float(n1_sub["SIM_DRY_CUM"].mean())
        if not n3_sub.empty:
            metrics_summary["26SP_N3_sim_mean"] = float(n3_sub["SIM_DRY_CUM"].mean())

    h25_file = det_root / "_seasons/25SP/25SP_deterministic_harvest_compare.csv"
    if h25_file.exists():
        df_h25 = pd.read_csv(h25_file)
        h_end25 = df_h25.sort_values(by=["TN", "HNO"]).groupby("TN").last().reset_index()
        y25 = h_end25["OBS_DRY_CUM"].to_numpy(float)
        p25 = h_end25["SIM_DRY_CUM"].to_numpy(float)
        err25 = p25 - y25
        rmse25 = float(np.sqrt(np.mean(err25**2)))
        rrmse25 = float(100 * rmse25 / np.mean(y25)) if np.mean(y25) > 0 else np.nan
        metrics_summary["25SP_term_dry_rrmse_pct"] = rrmse25
        metrics_summary["25SP_term_dry_bias"] = float(np.mean(err25))

    # Process metrics
    for season in ("25SP", "26SP"):
        proc_file = det_root / f"_seasons/{season}/{season}_deterministic_process_compare.csv"
        if proc_file.exists():
            df_p = pd.read_csv(proc_file)
            for var in ("LAID", "LWAD", "SWAD"):
                if f"OBS_{var}" in df_p.columns and f"SIM_{var}" in df_p.columns:
                    y_v = pd.to_numeric(df_p[f"OBS_{var}"], errors="coerce").to_numpy(float)
                    p_v = pd.to_numeric(df_p[f"SIM_{var}"], errors="coerce").to_numpy(float)
                    ok = ~np.isnan(y_v) & ~np.isnan(p_v) & (y_v > -90) & (p_v > -90)
                    if ok.sum() > 3:
                        y_v = y_v[ok]
                        p_v = p_v[ok]
                        sst = float(np.sum((y_v - y_v.mean())**2))
                        metrics_summary[f"{season}_{var}_NSE"] = float(1 - np.sum((p_v - y_v)**2) / sst) if sst > 0 else np.nan

    return metrics_summary


def main():
    if not OFFICIAL.is_file() or not LIVE.is_file():
        raise FileNotFoundError("Official or workspace DSSAT executable is missing")
    if BACKUP.exists():
        raise FileExistsError(f"Stale executable backup: {BACKUP}")

    LIVE.replace(BACKUP)
    shutil.copy2(OFFICIAL, LIVE)
    try:
        scorecards: list[dict[str, Any]] = []

        for arm in ARMS:
            run_dir = ROOT / "workspace/runs" / arm["run_id"]
            phi_csv = run_dir / f"{arm['case']}.phi.actual.csv"
            if not phi_csv.is_file():
                # 1. Build
                build_arm(arm)
                # 2. Run
                run_arm(arm)
            else:
                print(f"\n[SKIP] {arm['name']} already finished calibration, evaluating...")
            # 3. Evaluate & Deterministic Replay
            scores = evaluate_arm(arm)
            scorecards.append(scores)

        df_scores = pd.DataFrame(scorecards)
        out_summary = ROOT / "workspace/reports/multiarm_v32_scorecard_summary.csv"
        out_summary.parent.mkdir(parents=True, exist_ok=True)
        df_scores.to_csv(out_summary, index=False)
        print("\n=======================================================")
        print("          MULTI-ARM v32 EXPLORATION SCORECARD          ")
        print("=======================================================")
        print(df_scores.to_string(index=False))
        print(f"\nScorecard summary saved to: {out_summary}")

    finally:
        if LIVE.exists():
            LIVE.unlink()
        BACKUP.replace(LIVE)


if __name__ == "__main__":
    main()
