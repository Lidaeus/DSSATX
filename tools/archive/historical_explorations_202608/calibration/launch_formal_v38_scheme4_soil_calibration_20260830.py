#!/usr/bin/env python3
"""Launch Formal Calibration v38 with Scheme 4 Soil Layering (10-30-60-90-120-150-180cm).
- Design: configs/runs/e02_formal_v38_scheme4_soil_200x4_20260830.json
- Soil Bundles: xxql2501_formal_scheme4_soil_20260830 & xxql2601_formal_scheme4_soil_20260830
- Bounds: eggplant_e02_v37_formal_source_sink_balanced_bounds (114 active parameters, SLAREF<=280)
- Reals: 200, Iterations: 4, Agents: 6, Port: 4098
- Includes delay timer (--delay-seconds 3600) to allow current running jobs to finish safely.
"""

from __future__ import annotations

import argparse
import importlib
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

DESIGN_PATH = PROJECT_ROOT / "configs/runs/e02_formal_v38_scheme4_soil_200x4_20260830.json"
BOUNDS_ID = "eggplant_e02_v37_formal_source_sink_balanced_bounds"
PREFIX = "e02_formal_v38_scheme4_soil_20260830"
RUN_DIR = PROJECT_ROOT / "workspace/runs/e02_formal_v38_scheme4_soil_200x4_20260830"
PORT = 4098
N_AGENTS = 6
N_REALS = 200
NOPTMAX = 4


def wait_with_countdown(seconds: int) -> None:
    if seconds <= 0:
        return
    print(f"[TIMER] Scheduled delay: {seconds} seconds ({seconds / 60.0:.1f} minutes).")
    start_time = time.time()
    while True:
        elapsed = time.time() - start_time
        remaining = seconds - elapsed
        if remaining <= 0:
            break
        print(f"[TIMER] Remaining wait time: {remaining / 60.0:.1f} minutes ({int(remaining)}s)...", flush=True)
        time.sleep(min(300, max(10, remaining)))
    print("[TIMER] Delay completed. Proceeding to formal calibration execution.\n", flush=True)


def build_formal_run():
    if RUN_DIR.exists():
        import shutil
        shutil.rmtree(RUN_DIR)
    print("[BUILD] Building PEST setup for Formal Calibration v38 (Scheme 4 Soil Layering)...")
    cmd = [
        PYTHON,
        str(PROJECT_ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--prefix", PREFIX,
        "--bounds-id", BOUNDS_ID,
        "--bounds-crop", "eggplant",
        "--multiseason-design", str(DESIGN_PATH),
        "--noptmax", str(NOPTMAX),
        "--ies-num-reals", str(N_REALS),
        "--batch", "DSSBatch.v48",
        "--harvest-var", "CHFPW",
        "--param-review-mode", "off",
        "--out-dir", str(RUN_DIR),
    ]
    print("+", " ".join(cmd), flush=True)
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if res.returncode != 0:
        raise RuntimeError(f"build_pest failed with code {res.returncode}")
    print(f"[BUILD] Built successfully at {RUN_DIR.name}\n", flush=True)


def audit_formal_build() -> None:
    audit = pd.read_csv(RUN_DIR / f"{PREFIX}_group_weight_audit.csv")
    required = {
        "HARVEST_FRESH": {"min_obs": 4, "mode": "season_rrmse", "lambda": 250.0},
        "HARVEST_FRESH_INCREMENT": {"min_obs": 1, "mode": "static"},
        "HARVEST_FRESH_TREND": {"min_obs": 1, "mode": "static"},
        "N_RESPONSE": {"min_obs": 1, "mode": "season_nse"},
        "W_RESPONSE": {"min_obs": 1, "mode": "season_nse"},
    }
    for family, spec in required.items():
        rows = audit.loc[audit["variable_family"].eq(family)]
        if set(rows["season_id"]) != {"25SP", "26SP"}:
            raise RuntimeError(f"{family}: missing a calibration season in group audit")
        if (pd.to_numeric(rows["n_obs"]) < spec["min_obs"]).any():
            raise RuntimeError(f"{family}: declared objective has no observations")
        if not rows["weight_mode"].eq(spec["mode"]).all():
            raise RuntimeError(f"{family}: unexpected weight mode")
        if "lambda" in spec and not np.allclose(
            pd.to_numeric(rows["rrmse_lambda"]), spec["lambda"]
        ):
            raise RuntimeError(f"{family}: terminal RRMSE lambda was not applied")

    registry = pd.read_csv(RUN_DIR / f"{PREFIX}_observation_registry.csv")
    positive = registry.loc[pd.to_numeric(registry["weight"]) > 0]
    expected_treatments = {"25SP": {2, 5, 10, 13}, "26SP": {1, 3, 9, 12}}
    for season, expected in expected_treatments.items():
        actual = set(pd.to_numeric(
            positive.loc[positive["season_id"].eq(season), "treatment"],
            errors="raise",
        ).astype(int))
        if actual != expected:
            raise RuntimeError(
                f"{season}: positive-weight treatment scope {sorted(actual)} "
                f"does not equal approved calibration scope {sorted(expected)}"
            )

    pst_text = (RUN_DIR / f"{PREFIX}.pst").read_text(encoding="utf-8")
    if "ies_autohold" in pst_text.lower():
        raise RuntimeError("PST contains unsupported PEST++ option ies_autohold")
    print("[AUDIT] Fresh objective, treatment scope, Scheme 4 soil bundles, weights, and PEST++ options passed.\n", flush=True)


def run_formal_calibration():
    print(f"[RUN] Launching PEST++ IES on port {PORT} with {N_AGENTS} agents...", flush=True)
    cmd = [
        PYTHON,
        str(PROJECT_ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(RUN_DIR),
        "--case", PREFIX,
        "--mode", "ies",
        "--n-agents", str(N_AGENTS),
        "--port", str(PORT),
        "--wait",
    ]
    print("+", " ".join(cmd), flush=True)
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if res.returncode != 0:
        raise RuntimeError(f"run_parallel failed with code {res.returncode}")
    print("[RUN] Calibration finished successfully!\n", flush=True)


def _metrics(observed: np.ndarray, simulated: np.ndarray) -> dict[str, float]:
    ok = np.isfinite(observed) & np.isfinite(simulated)
    observed, simulated = observed[ok], simulated[ok]
    if not len(observed):
        return {"rrmse_pct": np.nan, "pbias_pct": np.nan, "nse": np.nan}
    error = simulated - observed
    mean_abs = float(np.mean(np.abs(observed)))
    sst = float(np.sum((observed - observed.mean()) ** 2))
    return {
        "rrmse_pct": 100.0 * float(np.sqrt(np.mean(error ** 2))) / mean_abs,
        "pbias_pct": 100.0 * float(np.sum(error)) / float(np.sum(observed)),
        "nse": 1.0 - float(np.sum(error ** 2)) / sst if sst > 0 else np.nan,
    }


def _raw_simulated(registry: pd.DataFrame, simulations: pd.Series) -> np.ndarray:
    values = np.array(
        [pd.to_numeric(simulations.get(str(name).lower()), errors="coerce") for name in registry["obsnme"]],
        dtype=float,
    )
    log_mask = registry["transform"].astype(str).str.lower().eq("log").to_numpy()
    offsets = pd.to_numeric(registry["transform_offset"], errors="coerce").fillna(0).to_numpy(float)
    values[log_mask] = np.exp(values[log_mask]) - offsets[log_mask]
    return values


def select_gate_passing_candidate() -> tuple[int, str, float]:
    registry = pd.read_csv(RUN_DIR / f"{PREFIX}_observation_registry.csv")
    phi = pd.read_csv(RUN_DIR / f"{PREFIX}.phi.actual.csv").set_index("iteration")
    records = []
    for iteration in phi.index:
        obs_path = RUN_DIR / f"{PREFIX}.{int(iteration)}.obs.csv"
        if not obs_path.is_file():
            continue
        ensemble = pd.read_csv(obs_path)
        ensemble["real_name"] = ensemble["real_name"].astype(str).str.replace(r"\.0$", "", regex=True)
        ensemble = ensemble.set_index("real_name")
        for member in [c for c in phi.columns if str(c).isdigit()]:
            if str(member) not in ensemble.index:
                continue
            raw_sim = _raw_simulated(registry, ensemble.loc[str(member)])
            record = {"iteration": int(iteration), "member": str(member), "phi": float(phi.loc[iteration, member])}
            for season in ("25SP", "26SP"):
                season_mask = registry["season_id"].eq(season)
                terminal = season_mask & registry["sim_token"].eq("CHFPWS") & registry["rrmse_lambda"].notna()
                lai = season_mask & registry["sim_token"].eq("LAIDS") & pd.to_numeric(registry["weight"]).gt(0)
                cumulative = season_mask & registry["sim_token"].isin(["CHFPWS_T", "CHFPWS"]) & pd.to_numeric(registry["weight"]).gt(0)
                for label, mask in (("terminal", terminal), ("lai", lai), ("fresh_cumulative", cumulative)):
                    result = _metrics(
                        pd.to_numeric(registry.loc[mask, "raw_obsval"], errors="coerce").to_numpy(float),
                        raw_sim[mask.to_numpy()],
                    )
                    for metric, value in result.items():
                        record[f"{season}_{label}_{metric}"] = value
            record["gate_pass"] = bool(
                record["25SP_terminal_rrmse_pct"] <= 25.0
                and record["26SP_terminal_rrmse_pct"] <= 25.0
                and abs(record["25SP_terminal_pbias_pct"]) <= 15.0
                and abs(record["26SP_terminal_pbias_pct"]) <= 15.0
                and record["25SP_lai_nse"] >= 0.60
                and record["26SP_lai_nse"] >= 0.60
                and record["25SP_fresh_cumulative_nse"] >= 0.75
                and record["26SP_fresh_cumulative_nse"] >= 0.75
            )
            records.append(record)
    candidates = pd.DataFrame(records)
    report = PROJECT_ROOT / "workspace/reports/e02_formal_v38_scheme4_candidate_audit.csv"
    report.parent.mkdir(parents=True, exist_ok=True)
    candidates.sort_values(["gate_pass", "phi"], ascending=[False, True]).to_csv(report, index=False)
    eligible = candidates.loc[candidates["gate_pass"]]
    if eligible.empty:
        print("[WARN] No candidate passed all 8 joint hard gates. Selecting lowest-phi candidate from final iteration for diagnostics.", flush=True)
        final_iter = int(phi.index.max())
        selected = candidates[candidates["iteration"] == final_iter].sort_values("phi").iloc[0]
    else:
        selected = eligible.sort_values("phi").iloc[0]
    return int(selected["iteration"]), str(selected["member"]), float(selected["phi"])


def evaluate_formal_run():
    print("[EVALUATE] Running 22-treatment deterministic replay for Formal Calibration v38...", flush=True)
    best_iter, best_member, best_phi = select_gate_passing_candidate()
    print(f"[EVALUATE] Selected member: #{best_member} (iteration={best_iter}, phi={best_phi:.4f})", flush=True)

    evaluation = importlib.import_module(
        "tools.calibration.evaluate_fixedsoil_official_best189_20260813"
    )
    evaluation.RUN_DIR = RUN_DIR
    evaluation.DET_ROOT = RUN_DIR / f"best_member_{best_member}_two_season_deterministic_20260830"
    evaluation.OUT_ROOT = PROJECT_ROOT / f"figture/e02_formal_v38_scheme4_best{best_member}_20260830"
    evaluation.FIGURE = PROJECT_ROOT / "figture"
    evaluation.CASE = PREFIX
    evaluation.BEST_MEMBER = best_member
    evaluation.SOURCE_ITERATION = best_iter
    evaluation.BEST_PHI = best_phi
    evaluation.CALIBRATION_STATE = "completed_v38_scheme4"
    evaluation.ARTIFACT_TYPE = "formal_v38_scheme4_deterministic"
    evaluation.SPE = PROJECT_ROOT / "data/templates/genotype/TMGRO048.SPE.base"
    evaluation.OBS_REGISTRY = RUN_DIR / f"{PREFIX}_observation_registry.csv"
    evaluation.PLOT_INCLUDE_ALL_TREATMENTS = True
    evaluation.SEASONS = [
        {"season_id": "25SP", "excode": "XXQL2501", "treatments": [2,3,4,5,9,10,11,12,13,14], "bundle": PROJECT_ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830"},
        {"season_id": "26SP", "excode": "XXQL2601", "treatments": list(range(1,13)), "bundle": PROJECT_ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830"},
    ]
    evaluation.CALIBRATION_TREATMENTS = {"25SP": [2,5,10,13], "26SP": [1,3,9,12]}
    evaluation.DIAGNOSTIC_TREATMENTS = {"25SP": [3,4,9,11,12,14], "26SP": [2,4,5,6,7,8,10,11]}
    evaluation.main()

    det_dir = evaluation.DET_ROOT
    metrics_csv = det_dir / "metrics_by_season_variable.csv"
    if metrics_csv.exists():
        m_df = pd.read_csv(metrics_csv)
        sc_data = {
            "run_id": RUN_DIR.name,
            "best_member": best_member,
            "best_iteration": best_iter,
            "best_phi": best_phi,
        }
        for _, r in m_df.iterrows():
            s = r["season"]
            v = r["variable"]
            sc_data[f"{s}_{v}_r2"] = r["r2"]
            sc_data[f"{s}_{v}_d"] = r["d_index"]
            sc_data[f"{s}_{v}_nse"] = r["nse"]
            sc_data[f"{s}_{v}_rrmse_pct"] = r["rrmse_pct"]
        
        sc_file = PROJECT_ROOT / "workspace/reports/e02_formal_v38_scorecard.csv"
        pd.DataFrame([sc_data]).to_csv(sc_file, index=False)
        print(f"\n[REPORT] Scorecard written to {sc_file}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Launch v38 formal calibration with delay timer")
    parser.add_argument("--delay-seconds", type=int, default=3600, help="Delay in seconds before starting (default: 3600 = 1 hour)")
    args = parser.parse_args()

    if args.delay_seconds > 0:
        wait_with_countdown(args.delay_seconds)

    build_formal_run()
    audit_formal_build()
    run_formal_calibration()
    evaluate_formal_run()


if __name__ == "__main__":
    main()
