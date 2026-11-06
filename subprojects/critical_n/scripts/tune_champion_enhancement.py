#!/usr/bin/env python3
"""Fine-grained Optimization Search for True Champion Stage R4+ Enhancement.

Investigates combinations around:
- TRIFL: [0.82, 0.84, 0.86, 0.88]
- SFDUR: [28.0, 30.0, 32.0, 34.0]
- XFRT: [0.910, 0.918, 0.9267]
- FRSTMF: [0.84, 0.86]
- SLAVR: [168.0, 172.0]
- RTNO3 / RWUMX: [0.00644, 0.0080]
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
from subprojects.critical_n.scripts.explore_targeted_enhancements import evaluate_params


def main():
    check_production_safety()
    comp_cat = pd.read_csv(PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/result_review_20261013/comparison_all_roles.csv")
    base_params = dict(zip(pd.read_csv(CRITICAL_N_DIR / "reports/stage_r4_best_parameters.csv")["name"], pd.read_csv(CRITICAL_N_DIR / "reports/stage_r4_best_parameters.csv")["value"]))

    sandboxes = {}
    sb_dir = CRITICAL_N_DIR / "runs/search_sandboxes"
    for s in ["26SP", "25SP", "25FA"]:
        sandboxes[s] = CrossSeasonSandbox(sb_dir / s, s, BIN_CNC)

    # Candidate grid (24 focused combos)
    combos = []
    for trifl in [0.83, 0.85, 0.87]:
        for sfdur in [29.0, 31.0]:
            for xfrt in [0.918, 0.9267]:
                for frstmf in [0.855, 0.860]:
                    p = copy.deepcopy(base_params)
                    p["TRIFL"] = trifl
                    p["SFDUR"] = sfdur
                    p["XFRT"] = xfrt
                    p["FRSTMF"] = frstmf
                    lbl = f"TR_{trifl}_SF_{sfdur}_X_{xfrt}_FR_{frstmf}"
                    combos.append((lbl, p))

    print(f"Total combos to evaluate: {len(combos)}")

    results = []
    for idx, (lbl, cand) in enumerate(combos):
        t0 = time.time()
        res = evaluate_params(sandboxes, cand, comp_cat)
        el = time.time() - t0

        y_26 = res["26SP"]["term_yield_nrmse"]
        d_26 = res["26SP"]["term_yield_d"]
        dry_26 = res["26SP"]["all_dry_nrmse"]

        y_25sp = res["25SP"]["all_yield_nrmse"]
        nse_25sp = res["25SP"]["all_yield_nse"]
        lw_25sp = res["25SP"]["lwad_nse"]

        y_25fa = res["25FA"]["all_yield_nrmse"]
        nse_25fa = res["25FA"]["all_yield_nse"]
        d_25fa = res["25FA"]["all_yield_d"]
        sw_25fa = res["25FA"]["swad_nse"]

        # Gate: 26SP terminal yield NRMSE must be < 6.0%, 25SP yield NSE must be >= 0.65, 25SP LWAD NSE >= 0.85
        gate_pass = (y_26 < 6.0) and (nse_25sp >= 0.65) and (lw_25sp >= 0.85)

        # Composite score balancing all 3 seasons:
        # Lower is better
        score = (
            y_26 * 2.0
            + dry_26 * 0.5
            + y_25sp * 0.5
            - nse_25sp * 15.0
            - lw_25sp * 10.0
            + y_25fa * 0.1
            - nse_25fa * 3.0
            - d_25fa * 15.0
            - sw_25fa * 5.0
        )

        rec = {
            "label": lbl,
            "params": cand,
            "score": score,
            "gate_pass": gate_pass,
            "y_26": y_26,
            "d_26": d_26,
            "dry_26": dry_26,
            "y_25sp": y_25sp,
            "nse_25sp": nse_25sp,
            "lw_25sp": lw_25sp,
            "y_25fa": y_25fa,
            "nse_25fa": nse_25fa,
            "d_25fa": d_25fa,
            "sw_25fa": sw_25fa,
            "res": res,
        }
        results.append(rec)
        print(f"[{idx+1:2d}/{len(combos)}] {lbl} (gate={'PASS' if gate_pass else 'FAIL'} | score={score:6.2f}): 26SP={y_26:5.2f}% | 25SP y_nse={nse_25sp:5.2f} (lw={lw_25sp:5.2f}) | 25FA y_nse={nse_25fa:6.2f} (d={d_25fa:5.3f}, sw={sw_25fa:5.2f})")

    # Filter to gate_pass and sort by score
    valid = [r for r in results if r["gate_pass"]]
    valid.sort(key=lambda x: x["score"])

    print("\n" + "=" * 90)
    print("TOP 5 ENHANCED CHAMPIONS (ALL GATES PASSED):")
    print("=" * 90)
    for i, r in enumerate(valid[:5]):
        print(f"#{i+1}: {r['label']} | Score={r['score']:.2f}")
        print(f"    26SP: term_yield_nrmse={r['y_26']:.2f}%, d={r['d_26']:.3f}, dry_nrmse={r['dry_26']:.2f}%")
        print(f"    25SP: yield_nrmse={r['y_25sp']:.2f}%, yield_nse={r['nse_25sp']:.3f}, lwad_nse={r['lw_25sp']:.3f}")
        print(f"    25FA: yield_nrmse={r['y_25fa']:.2f}%, yield_nse={r['nse_25fa']:.3f}, yield_d={r['d_25fa']:.3f}, swad_nse={r['sw_25fa']:.3f}")
        p = r["params"]
        print(f"    Params: TRIFL={p['TRIFL']}, SFDUR={p['SFDUR']}, XFRT={p['XFRT']}, FRSTMF={p['FRSTMF']}, SLAVR={p['SLAVR']}")

    # Save search results to csv
    summary_df = pd.DataFrame([{
        "label": r["label"],
        "gate_pass": r["gate_pass"],
        "score": r["score"],
        "TRIFL": r["params"]["TRIFL"],
        "SFDUR": r["params"]["SFDUR"],
        "XFRT": r["params"]["XFRT"],
        "FRSTMF": r["params"]["FRSTMF"],
        "SLAVR": r["params"]["SLAVR"],
        "26SP_term_yield_nrmse": r["y_26"],
        "26SP_term_yield_d": r["d_26"],
        "26SP_dry_yield_nrmse": r["dry_26"],
        "25SP_yield_nrmse": r["y_25sp"],
        "25SP_yield_nse": r["nse_25sp"],
        "25SP_lwad_nse": r["lw_25sp"],
        "25FA_yield_nrmse": r["y_25fa"],
        "25FA_yield_nse": r["nse_25fa"],
        "25FA_yield_d": r["d_25fa"],
        "25FA_swad_nse": r["sw_25fa"],
    } for r in results])
    summary_df.to_csv(CRITICAL_N_DIR / "reports/champion_search_summary.csv", index=False)
    print("\nSaved search summary to reports/champion_search_summary.csv")


if __name__ == "__main__":
    main()
