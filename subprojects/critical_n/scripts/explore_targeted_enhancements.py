#!/usr/bin/env python3
"""Targeted Parameter Exploration for True Stage R4+ Enhancement.

Objectives:
1. Strict 26SP terminal yield NRMSE < 6.0% and correct trend.
2. NO degradation in 25SP validation performance (preserve 25SP fresh yield NRMSE <= 32%, LWAD NSE >= 0.85).
3. Significant improvement in 25FA (reduce negative NSE, improve Willmott d, improve SWAD NSE).
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


def evaluate_params(sandboxes: dict[str, CrossSeasonSandbox], params: dict[str, float], comp_cat: pd.DataFrame) -> dict:
    results = {}
    for season_id in ["26SP", "25SP", "25FA"]:
        sb = sandboxes[season_id]
        sb.run_simulation(params)
        pairs = sb.extract_observations(comp_cat)

        # Terminal fresh yield
        y_pairs = pairs[pairs["variable"] == "CHFPW"]
        term_pairs = y_pairs.sort_values("date").groupby("trno").tail(1)
        m_term = compute_metrics(term_pairs["observed"].to_numpy(), term_pairs["simulated"].to_numpy())
        m_all_y = compute_metrics(y_pairs["observed"].to_numpy(), y_pairs["simulated"].to_numpy())

        # Dry yield
        d_pairs = pairs[pairs["variable"] == "CHPDT"]
        m_all_d = compute_metrics(d_pairs["observed"].to_numpy(), d_pairs["simulated"].to_numpy())

        # LAI
        lai_pairs = pairs[pairs["variable"] == "LAID"]
        m_lai = compute_metrics(lai_pairs["observed"].to_numpy(), lai_pairs["simulated"].to_numpy())

        # LWAD
        lwad_pairs = pairs[pairs["variable"] == "LWAD"]
        m_lwad = compute_metrics(lwad_pairs["observed"].to_numpy(), lwad_pairs["simulated"].to_numpy())

        # SWAD
        swad_pairs = pairs[pairs["variable"] == "SWAD"]
        m_swad = compute_metrics(swad_pairs["observed"].to_numpy(), swad_pairs["simulated"].to_numpy())

        # Leaf N
        ln_pairs = pairs[pairs["variable"] == "LEAF_N_PCT"]
        m_ln = compute_metrics(ln_pairs["observed"].to_numpy(), ln_pairs["simulated"].to_numpy())

        # Terminal LAI for 26SP
        final_lai = np.nan
        if season_id == "26SP":
            t5_lai = lai_pairs[lai_pairs["trno"] == 5]
            if len(t5_lai) > 0:
                final_lai = float(t5_lai.sort_values("date")["simulated"].iloc[-1])

        results[season_id] = {
            "term_yield_nrmse": m_term["nrmse"],
            "term_yield_d": m_term["d"],
            "all_yield_nrmse": m_all_y["nrmse"],
            "all_yield_nse": m_all_y["nse"],
            "all_yield_d": m_all_y["d"],
            "all_dry_nrmse": m_all_d["nrmse"],
            "all_dry_nse": m_all_d["nse"],
            "lai_nrmse": m_lai["nrmse"],
            "lai_nse": m_lai["nse"],
            "lai_d": m_lai["d"],
            "lwad_nrmse": m_lwad["nrmse"],
            "lwad_nse": m_lwad["nse"],
            "swad_nrmse": m_swad["nrmse"],
            "swad_nse": m_swad["nse"],
            "leaf_n_nrmse": m_ln["nrmse"],
            "leaf_n_nse": m_ln["nse"],
            "final_lai": final_lai,
        }
    return results


def main():
    check_production_safety()
    comp_cat = pd.read_csv(PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/result_review_20261013/comparison_all_roles.csv")
    base_params = dict(zip(pd.read_csv(CRITICAL_N_DIR / "reports/stage_r4_best_parameters.csv")["name"], pd.read_csv(CRITICAL_N_DIR / "reports/stage_r4_best_parameters.csv")["value"]))

    sandboxes = {}
    sb_dir = CRITICAL_N_DIR / "runs/search_sandboxes"
    for s in ["26SP", "25SP", "25FA"]:
        sandboxes[s] = CrossSeasonSandbox(sb_dir / s, s, BIN_CNC)

    # 1. Evaluate baseline Stage R4
    base_res = evaluate_params(sandboxes, base_params, comp_cat)
    print("=== BASELINE STAGE R4 ===")
    print(f"  26SP: term_y={base_res['26SP']['term_yield_nrmse']:.2f}% (d={base_res['26SP']['term_yield_d']:.3f}), dry_y={base_res['26SP']['all_dry_nrmse']:.2f}%, lai_nse={base_res['26SP']['lai_nse']:.3f}, final_lai={base_res['26SP']['final_lai']:.2f}")
    print(f"  25SP: yld_nrmse={base_res['25SP']['all_yield_nrmse']:.2f}%, yld_nse={base_res['25SP']['all_yield_nse']:.3f}, lwad_nse={base_res['25SP']['lwad_nse']:.3f}, swad_nse={base_res['25SP']['swad_nse']:.3f}")
    print(f"  25FA: yld_nrmse={base_res['25FA']['all_yield_nrmse']:.2f}%, yld_nse={base_res['25FA']['all_yield_nse']:.3f}, yld_d={base_res['25FA']['all_yield_d']:.3f}, swad_nse={base_res['25FA']['swad_nse']:.3f}")

    # 2. Targeted single-parameter probes
    probes = [
        ("SLAVR_178", {"SLAVR": 178.0}),
        ("SLAVR_188", {"SLAVR": 188.0}),
        ("TB2_11.1", {"TB2": 11.1}),
        ("TB2_11.4", {"TB2": 11.4}),
        ("XFRT_0.91", {"XFRT": 0.910}),
        ("XFRT_0.895", {"XFRT": 0.895}),
        ("FRLFF_0.128", {"FRLFF": 0.128}),
        ("FRLFF_0.135", {"FRLFF": 0.135}),
        ("PGEFF_0.065", {"PGEFF": 0.065}),
        ("PODUR_12.0", {"PODUR": 12.0}),
        ("SFDUR_32.0", {"SFDUR": 32.0}),
        ("RWUMX_0.015", {"RWUMX": 0.015}),
        ("RTNO3_0.009", {"RTNO3": 0.009}),
        ("TRIFL_0.85", {"TRIFL": 0.85}),
    ]

    print("\n--- Running Single Parameter Probes ---")
    probe_results = []
    for label, patch in probes:
        cand = copy.deepcopy(base_params)
        cand.update(patch)
        t0 = time.time()
        res = evaluate_params(sandboxes, cand, comp_cat)
        el = time.time() - t0
        print(f"[{label:14s} | {el:4.1f}s]: 26SP yld={res['26SP']['term_yield_nrmse']:5.2f}% | 25SP yld_nse={res['25SP']['all_yield_nse']:5.2f} (lw={res['25SP']['lwad_nse']:5.2f}) | 25FA yld_nse={res['25FA']['all_yield_nse']:6.2f} (sw={res['25FA']['swad_nse']:5.2f}, d={res['25FA']['all_yield_d']:5.3f})")
        probe_results.append((label, patch, res))

    check_production_safety()


if __name__ == "__main__":
    main()
