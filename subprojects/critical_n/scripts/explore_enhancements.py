#!/usr/bin/env python3
"""Exploratory sensitivity analysis and optimization search for Stage R4+ Enhanced parameters.

Evaluates candidates on all 3 seasons (26SP, 25SP, 25FA) to find parameters that:
1. Maintain 26SP terminal fresh yield NRMSE < 6.0% and suppressed late LAI.
2. Significantly improve 25SP and 25FA generalization (reduce 25FA yield overestimation,
   lift 25FA/25SP LAI, reduce negative NSE, increase Willmott d).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import time
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from subprojects.critical_n.scripts.build_and_verify_dssat import check_production_safety
from subprojects.critical_n.scripts.cross_season_evaluator import (
    BIN_CNC,
    compute_metrics,
    CrossSeasonSandbox,
)

def evaluate_candidate(
    sandboxes: dict[str, CrossSeasonSandbox],
    candidate_params: dict[str, float],
    comp_cat: pd.DataFrame,
) -> dict[str, Any]:
    """Evaluates a parameter candidate across 26SP, 25SP, and 25FA."""
    season_results = {}
    
    for season_id in ["26SP", "25SP", "25FA"]:
        sb = sandboxes[season_id]
        sb.run_simulation(candidate_params)
        pairs = sb.extract_observations(comp_cat)
        
        # Fresh yield (CHFPW)
        y_pairs = pairs[pairs["variable"] == "CHFPW"]
        # In 26SP & 25SP & 25FA, terminal yield
        # Terminal yield: last harvest date per treatment
        term_pairs = y_pairs.sort_values("date").groupby("trno").tail(1)
        m_term = compute_metrics(term_pairs["observed"].to_numpy(), term_pairs["simulated"].to_numpy())
        m_all_y = compute_metrics(y_pairs["observed"].to_numpy(), y_pairs["simulated"].to_numpy())
        
        # LAI (LAID)
        lai_pairs = pairs[pairs["variable"] == "LAID"]
        m_lai = compute_metrics(lai_pairs["observed"].to_numpy(), lai_pairs["simulated"].to_numpy())
        
        # Leaf mass (LWAD)
        lwad_pairs = pairs[pairs["variable"] == "LWAD"]
        m_lwad = compute_metrics(lwad_pairs["observed"].to_numpy(), lwad_pairs["simulated"].to_numpy())
        
        # Leaf N (LEAF_N_PCT)
        ln_pairs = pairs[pairs["variable"] == "LEAF_N_PCT"]
        m_ln = compute_metrics(ln_pairs["observed"].to_numpy(), ln_pairs["simulated"].to_numpy())

        # Soil water (VWC)
        vwc_pairs = pairs[pairs["variable"] == "VWC"]
        m_vwc = compute_metrics(vwc_pairs["observed"].to_numpy(), vwc_pairs["simulated"].to_numpy())
        
        season_results[season_id] = {
            "term_yield_nrmse": m_term["nrmse"],
            "term_yield_r2": m_term["r2"],
            "term_yield_nse": m_term["nse"],
            "term_yield_d": m_term["d"],
            "all_yield_nrmse": m_all_y["nrmse"],
            "all_yield_nse": m_all_y["nse"],
            "all_yield_d": m_all_y["d"],
            "lai_nrmse": m_lai["nrmse"],
            "lai_r2": m_lai["r2"],
            "lai_nse": m_lai["nse"],
            "lai_d": m_lai["d"],
            "lwad_nrmse": m_lwad["nrmse"],
            "lwad_nse": m_lwad["nse"],
            "leaf_n_nrmse": m_ln["nrmse"],
            "leaf_n_nse": m_ln["nse"],
            "vwc_nrmse": m_vwc["nrmse"],
            "vwc_nse": m_vwc["nse"],
        }
        
    return season_results


def main():
    check_production_safety()
    comp_cat_path = PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/result_review_20261013/comparison_all_roles.csv"
    comp_cat = pd.read_csv(comp_cat_path)

    r4_params_path = CRITICAL_N_DIR / "reports/stage_r4_best_parameters.csv"
    base_params = dict(zip(pd.read_csv(r4_params_path)["name"], pd.read_csv(r4_params_path)["value"]))

    # Prepare sandboxes for search
    search_dir = CRITICAL_N_DIR / "runs/search_sandboxes"
    sandboxes = {}
    for season_id in ["26SP", "25SP", "25FA"]:
        sb = CrossSeasonSandbox(search_dir / season_id, season_id, BIN_CNC)
        sb.prepare()
        sandboxes[season_id] = sb

    # Evaluate baseline Stage R4
    print("Evaluating Baseline Stage R4...")
    base_res = evaluate_candidate(sandboxes, base_params, comp_cat)
    print("Baseline R4 Results:")
    print("  26SP Terminal Fresh Yield NRMSE:", f"{base_res['26SP']['term_yield_nrmse']:.2f}%", f"d={base_res['26SP']['term_yield_d']:.3f}")
    print("  25SP Terminal Fresh Yield NRMSE:", f"{base_res['25SP']['term_yield_nrmse']:.2f}%", f"LAI NSE={base_res['25SP']['lai_nse']:.3f}")
    print("  25FA Terminal Fresh Yield NRMSE:", f"{base_res['25FA']['term_yield_nrmse']:.2f}%", f"LAI NSE={base_res['25FA']['lai_nse']:.3f}", f"Yield NSE={base_res['25FA']['all_yield_nse']:.3f}")

    # Test parameter variations
    # Exploring:
    # SLAVR: 167.95 -> 180, 195, 210
    # XFRT: 0.9267 -> 0.88, 0.85, 0.82
    # FRSTMF: 0.86 -> 0.83, 0.80
    # SENPOR_LATE: 0.285 -> 0.260, 0.240
    # PGEFF: 0.0624 -> 0.065, 0.068
    results = []

    candidates = []
    
    # Grid of candidate tweaks
    for slavr in [168.0, 185.0, 200.0, 215.0]:
        for xfrt in [0.927, 0.890, 0.860, 0.830]:
            for frstmf in [0.860, 0.830, 0.800]:
                for senpor in [0.285, 0.260, 0.240]:
                    p = copy.deepcopy(base_params)
                    p["SLAVR"] = slavr
                    p["XFRT"] = xfrt
                    p["FRSTMF"] = frstmf
                    # Ensure FRSTMF + FRLFF <= 0.995
                    p["FRLFF"] = min(0.140, max(0.090, 0.995 - frstmf))
                    p["SENPOR_LATE"] = senpor
                    candidates.append((f"SL_{slavr}_X_{xfrt}_FR_{frstmf}_SN_{senpor}", p))

    print(f"\nTotal candidate configurations to evaluate: {len(candidates)}")
    
    # We will screen candidates
    screened = []
    for idx, (label, cand) in enumerate(candidates):
        try:
            t0 = time.time()
            res = evaluate_candidate(sandboxes, cand, comp_cat)
            el = time.time() - t0
            
            # Check 26SP yield constraint: term_yield_nrmse <= 6.5%
            nrmse_26 = res["26SP"]["term_yield_nrmse"]
            nrmse_25sp = res["25SP"]["term_yield_nrmse"]
            nrmse_25fa = res["25FA"]["term_yield_nrmse"]
            nse_25fa_y = res["25FA"]["all_yield_nse"]
            d_25fa_y = res["25FA"]["all_yield_d"]
            lai_nse_25sp = res["25SP"]["lai_nse"]
            lai_nse_25fa = res["25FA"]["lai_nse"]
            
            # Multi-objective composite score
            # Want: 26SP NRMSE small, 25SP NRMSE small, 25FA NRMSE small (or NSE large), LAI NSE high
            # Penalty if 26SP NRMSE > 6.0%
            pen_26 = 10.0 * max(0.0, nrmse_26 - 6.0) ** 2
            
            score = (
                nrmse_26 * 2.0
                + nrmse_25sp * 0.5
                + nrmse_25fa * 0.2
                - 10.0 * lai_nse_25sp
                - 5.0 * lai_nse_25fa
                - 10.0 * nse_25fa_y
                + pen_26
            )
            
            screened.append({
                "label": label,
                "score": score,
                "params": cand,
                "res": res,
                "nrmse_26": nrmse_26,
                "nrmse_25sp": nrmse_25sp,
                "nrmse_25fa": nrmse_25fa,
                "nse_25fa_y": nse_25fa_y,
                "d_25fa_y": d_25fa_y,
                "lai_nse_25sp": lai_nse_25sp,
                "lai_nse_25fa": lai_nse_25fa,
            })
            
            if (idx + 1) % 10 == 0 or idx == 0:
                print(f"[{idx+1}/{len(candidates)}] {label}: 26SP={nrmse_26:.2f}% | 25SP={nrmse_25sp:.2f}% | 25FA={nrmse_25fa:.2f}% (NSE_y={nse_25fa_y:.2f}, LAI_NSE={lai_nse_25fa:.2f}) | Score={score:.2f} ({el:.1f}s)")
        except Exception as e:
            continue

    # Sort by score
    screened.sort(key=lambda x: x["score"])
    print("\n" + "=" * 90)
    print("TOP 10 CANDIDATES:")
    print("=" * 90)
    for i, item in enumerate(screened[:10]):
        print(f"#{i+1} Score={item['score']:.2f} | 26SP Yld={item['nrmse_26']:.2f}% | 25SP Yld={item['nrmse_25sp']:.2f}% | 25FA Yld={item['nrmse_25fa']:.2f}% (NSE={item['nse_25fa_y']:.2f}, d={item['d_25fa_y']:.3f}) | 25SP LAI NSE={item['lai_nse_25sp']:.3f} | 25FA LAI NSE={item['lai_nse_25fa']:.3f}")
        print(f"    Params: SLAVR={item['params']['SLAVR']}, XFRT={item['params']['XFRT']}, FRSTMF={item['params']['FRSTMF']}, FRLFF={item['params']['FRLFF']}, SENPOR={item['params']['SENPOR_LATE']}")

    # Save top candidate summary
    summary_rows = []
    for item in screened[:10]:
        summary_rows.append({
            "label": item["label"],
            "score": item["score"],
            "SLAVR": item["params"]["SLAVR"],
            "XFRT": item["params"]["XFRT"],
            "FRSTMF": item["params"]["FRSTMF"],
            "FRLFF": item["params"]["FRLFF"],
            "SENPOR_LATE": item["params"]["SENPOR_LATE"],
            "26SP_term_yield_nrmse": item["nrmse_26"],
            "25SP_term_yield_nrmse": item["nrmse_25sp"],
            "25FA_term_yield_nrmse": item["nrmse_25fa"],
            "25FA_yield_nse": item["nse_25fa_y"],
            "25FA_yield_d": item["d_25fa_y"],
            "25SP_lai_nse": item["lai_nse_25sp"],
            "25FA_lai_nse": item["lai_nse_25fa"],
        })
    pd.DataFrame(summary_rows).to_csv(CRITICAL_N_DIR / "reports/candidate_search_summary.csv", index=False)
    print("\nCandidate search summary saved to subprojects/critical_n/reports/candidate_search_summary.csv")


if __name__ == "__main__":
    main()
