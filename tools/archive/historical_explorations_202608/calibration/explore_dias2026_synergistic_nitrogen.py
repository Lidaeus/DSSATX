"""Controlled Dias 2026 synergistic C-N feedback exploration.

Anchored on best_member_71 of v46. Evaluates synergistic coupling of:
- Organ protein/N demand: PROLFG, PROLFI, PROLFF, PROSTG, PROSTI, PROSTF, PRORTG, PRORTI, PRORTF
- N-stress threshold: NSTFAC (0.50, 0.65, 0.75, 0.85)
- Root uptake capacity: RTNO3 (0.020, 0.025, 0.033), RTNH4
- Mobilization & Senescence: NMOBMX, NVSMOB, SENRTE
- Leaf N - Photosynthesis: FNPGN1, FNPGN2
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

import tools.calibration.profile_v46_best71_nitrogen_20260831 as profile
import tools.calibration.profile_n_parameters_determinstic as base
from src.common.input_manifest import verify_manifest_integrity

OUT = ROOT / "workspace/reports/e02_v46_dias2026_synergy_20260831"
SCRATCH = OUT / "scratch_runs"
ANCHOR = profile.BASE / "best_member_71_params.csv"
DESIGN = profile.OUT / "design_all22.json"
BUNDLES = [
    ROOT / "data/user/experiments/xxql2501_formal_scheme4_soil_20260830",
    ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830",
]
N_PAIRS = profile.N_PAIRS
W_PAIRS = {
    "25SP": {"N0": (5, 13), "N3": (2, 10)},
    "26SP": {"N0": (11, 12), "N3": (2, 3)},
}

def signed_metric(obs: pd.Series, sim: pd.Series) -> float:
    o = pd.to_numeric(obs, errors="coerce").to_numpy(float)
    s = pd.to_numeric(sim, errors="coerce").to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s)
    o, s = o[ok], s[ok]
    if len(o) < 2:
        return float("nan")
    sst = float(np.square(o - o.mean()).sum())
    return 1.0 - float(np.square(s - o).sum()) / sst if sst > 0 else float("nan")

def response_records(h: pd.DataFrame, season: str, pairs: dict[str, dict[str, tuple[int, int]]]) -> list[dict[str, object]]:
    terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1).set_index("TN")
    records = []
    for level, water_pairs in pairs.items():
        for water, (hi, lo) in water_pairs.items():
            if hi in terminal.index and lo in terminal.index:
                records.append({
                    "season": season, "level": level, "water": water,
                    "obs": float(terminal.loc[hi, "OBS_FRESH_CUM"] - terminal.loc[lo, "OBS_FRESH_CUM"]),
                    "sim": float(terminal.loc[hi, "SIM_FRESH_CUM"] - terminal.loc[lo, "SIM_FRESH_CUM"]),
                })
    return records

def water_records(h: pd.DataFrame, season: str) -> list[dict[str, object]]:
    terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1).set_index("TN")
    records = []
    for level, (hi, lo) in W_PAIRS[season].items():
        if hi in terminal.index and lo in terminal.index:
            records.append({
                "season": season, "level": level,
                "obs": float(terminal.loc[hi, "OBS_FRESH_CUM"] - terminal.loc[lo, "OBS_FRESH_CUM"]),
                "sim": float(terminal.loc[hi, "SIM_FRESH_CUM"] - terminal.loc[lo, "SIM_FRESH_CUM"]),
            })
    return records

def _check_early_nstress(run_path: Path) -> dict[str, float]:
    p26 = run_path / "_seasons/26SP/PlantGro.OUT"
    if not p26.is_file():
        return {"max_nstd_early": 0.0, "max_pst1a_early": 0.0}
    try:
        lines = p26.read_text(encoding="utf-8", errors="ignore").splitlines()
        header_idx = -1
        for i, ln in enumerate(lines):
            if "@YEAR" in ln or "@  YEAR" in ln:
                header_idx = i
                break
        if header_idx < 0:
            return {"max_nstd_early": 0.0, "max_pst1a_early": 0.0}
        headers = lines[header_idx].replace("@", " ").split()
        data_rows = []
        for ln in lines[header_idx + 1:]:
            if ln.strip().startswith("*") or ln.strip().startswith("@"):
                continue
            parts = ln.split()
            if len(parts) == len(headers):
                data_rows.append(parts)
        df = pd.DataFrame(data_rows, columns=headers)
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        early_df = df[df["DOY"] <= 146]
        max_nstd = float(early_df["NSTD"].max()) if "NSTD" in early_df else 0.0
        max_pst1a = float(early_df["PST1A"].max()) if "PST1A" in early_df else 0.0
        return {"max_nstd_early": max_nstd, "max_pst1a_early": max_pst1a}
    except Exception:
        return {"max_nstd_early": 0.0, "max_pst1a_early": 0.0}

def evaluate_case(case: str, changes: dict[str, float]) -> dict[str, object]:
    res = base._run_deterministic(changes, case)
    run = SCRATCH / case
    result: dict[str, object] = {"case": case, **{k: float(v) for k, v in changes.items()}, "status": "success"}
    n_records: list[dict[str, object]] = []
    w_records: list[dict[str, object]] = []
    for season in ("25SP", "26SP"):
        sdir = run / "_seasons" / season
        h = pd.read_csv(sdir / f"{season}_deterministic_harvest_compare.csv")
        p = pd.read_csv(sdir / f"{season}_deterministic_process_compare.csv")
        terminal = h.sort_values(["TN", "DATE", "HNO"]).groupby("TN", as_index=False).tail(1)
        nrec = response_records(h, season, N_PAIRS[season])
        wrec = water_records(h, season)
        n_records.extend(nrec)
        w_records.extend(wrec)
        result[f"{season}_fresh_cum_nse"] = signed_metric(h["OBS_FRESH_CUM"], h["SIM_FRESH_CUM"])
        result[f"{season}_lai_nse"] = signed_metric(p["OBS_LAID"], p["SIM_LAID"])
        obs = terminal["OBS_FRESH_CUM"].to_numpy(float)
        sim = terminal["SIM_FRESH_CUM"].to_numpy(float)
        result[f"{season}_terminal_rrmse_pct"] = 100.0 * float(np.sqrt(np.mean(np.square(sim - obs)))) / float(np.mean(np.abs(obs)))
        result[f"{season}_terminal_pbias_pct"] = 100.0 * float(np.sum(sim - obs)) / float(np.sum(obs))
        result[f"{season}_n_mean_abs_error"] = float(np.mean([abs(float(x["sim"]) - float(x["obs"])) for x in nrec]))
        result[f"{season}_n_direction_pass"] = bool(
            all(np.mean([float(x["sim"]) for x in nrec if x["level"] == level]) > 0 for level in ("N1", "N2"))
        )
        result[f"{season}_w_response_nse"] = signed_metric(
            pd.Series([x["obs"] for x in wrec]), pd.Series([x["sim"] for x in wrec])
        )
    stress_info = _check_early_nstress(run)
    result.update(stress_info)
    result["n_records_json"] = json.dumps(n_records, ensure_ascii=False)
    result["w_records_json"] = json.dumps(w_records, ensure_ascii=False)
    return result

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    for bundle in BUNDLES:
        verify_manifest_integrity(bundle)
    base.BASE_PARAMS_PATH = ANCHOR
    base.BASE_DESIGN_PATH = DESIGN
    base.SCRATCH_DIR = SCRATCH
    base.OUT_DIR = OUT

    experiments = [("baseline_best71", {})]

    # Dias 2026 C-N Feedback Combinations:
    demand_profiles = {
        "std_pro": {
            "PROLFG": 0.200, "PROLFI": 0.260, "PROLFF": 0.095,
            "PROSTG": 0.130, "PROSTI": 0.220, "PROSTF": 0.060,
            "PRORTG": 0.119, "PRORTI": 0.150, "PRORTF": 0.040,
        },
        "high_pro": {
            "PROLFG": 0.220, "PROLFI": 0.275, "PROLFF": 0.105,
            "PROSTG": 0.136, "PROSTI": 0.240, "PROSTF": 0.065,
            "PRORTG": 0.119, "PRORTI": 0.150, "PRORTF": 0.050,
        },
        "mild_pro": {
            "PROLFG": 0.165, "PROLFI": 0.235, "PROLFF": 0.085,
            "PROSTG": 0.115, "PROSTI": 0.230, "PROSTF": 0.055,
            "PRORTG": 0.118, "PRORTI": 0.150, "PRORTF": 0.035,
        }
    }

    # Set 1: Systematic Demand + Threshold + Uptake combinations
    for d_name, d_dict in demand_profiles.items():
        for nstfac in [0.50, 0.65, 0.75, 0.85]:
            for rtno3 in [0.022, 0.028, 0.033]:
                case = f"{d_name}_nst_{nstfac:.2f}_rtno3_{rtno3:.3f}"
                ch = dict(d_dict)
                ch["NSTFAC"] = nstfac
                ch["RTNO3"] = rtno3
                experiments.append((case, ch))

    # Set 2: Full Dias synergistic feedback sets with FNPGN + Mobilization tuning
    for d_name in ["std_pro", "mild_pro"]:
        d_dict = demand_profiles[d_name]
        for fn1, fn2 in [(1.00, 4.20), (1.20, 4.35), (1.50, 4.50)]:
            for mob_scale in [(0.35, 0.80), (0.45, 0.90)]:
                case = f"dias_{d_name}_fn_{fn1:.2f}_{fn2:.2f}_mob_{mob_scale[0]:.2f}_{mob_scale[1]:.2f}"
                ch = dict(d_dict)
                ch["NSTFAC"] = 0.70
                ch["RTNO3"] = 0.025
                ch["FNPGN1"] = fn1
                ch["FNPGN2"] = fn2
                ch["NMOBMX"] = mob_scale[0]
                ch["NVSMOB"] = mob_scale[1]
                ch["SENRTE"] = 2.50
                experiments.append((case, ch))

    print(f"Total synergistic experiments to evaluate: {len(experiments)}")
    rows = []
    for idx, (case, changes) in enumerate(experiments, 1):
        row = evaluate_case(case, changes)
        rows.append(row)
        pd.DataFrame(rows).to_csv(OUT / "dias_synergy_results.csv", index=False, encoding="utf-8-sig")
        mae = row["26SP_n_mean_abs_error"]
        nstd = row["max_nstd_early"]
        print(f"[{idx:02d}/{len(experiments):02d}] {case} -> 26SP N MAE: {mae:.1f}, Early NSTD: {nstd:.3f}", flush=True)

    df = pd.DataFrame(rows)
    baseline = df.iloc[0]
    for season in ("25SP", "26SP"):
        df[f"{season}_n_error_reduction_pct"] = 100.0 * (float(baseline[f"{season}_n_mean_abs_error"]) - df[f"{season}_n_mean_abs_error"].astype(float)) / float(baseline[f"{season}_n_mean_abs_error"])
    base_records = {
        (rec["season"], rec["level"], rec["water"]): abs(float(rec["sim"]) - float(rec["obs"]))
        for rec in json.loads(baseline["n_records_json"])
    }
    improvements = []
    for _, row in df.iterrows():
        improvements.append(sum(
            abs(float(rec["sim"]) - float(rec["obs"])) < base_records[(rec["season"], rec["level"], rec["water"])]
            for rec in json.loads(row["n_records_json"])
            if (rec["season"], rec["level"], rec["water"]) in base_records
        ))
    df["n_response_layers_improved_vs_baseline"] = improvements
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
    df["synergy_gate_pass"] = (
        df["25SP_n_direction_pass"].astype(bool)
        & df["26SP_n_error_reduction_pct"].astype(float).ge(30.0)
        & df["n_response_layers_improved_vs_baseline"].astype(int).ge(3)
        & df["yield_guard_pass"]
        & df["protected_fit_pass"]
    )
    df.sort_values(["synergy_gate_pass", "26SP_n_error_reduction_pct"], ascending=[False, False]).to_csv(OUT / "dias_synergy_scorecard.csv", index=False, encoding="utf-8-sig")
    print("\nDone. Top candidates:")
    print(df[["case", "25SP_n_mean_abs_error", "26SP_n_mean_abs_error", "26SP_n_error_reduction_pct", "n_response_layers_improved_vs_baseline", "max_nstd_early", "synergy_gate_pass"]].head(15).to_string(index=False))

if __name__ == "__main__":
    main()
