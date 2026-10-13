#!/usr/bin/env python3
"""Refine Champion Search around TRIFL 0.86-0.89 and SFDUR 30.0-33.0."""

import copy
from pathlib import Path
import sys
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CRITICAL_N_DIR = PROJECT_ROOT / "subprojects" / "critical_n"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from subprojects.critical_n.scripts.cross_season_evaluator import BIN_CNC, CrossSeasonSandbox
from subprojects.critical_n.scripts.explore_targeted_enhancements import evaluate_params

comp_cat = pd.read_csv(PROJECT_ROOT / "workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/result_review_20261013/comparison_all_roles.csv")
base_params = dict(zip(pd.read_csv(CRITICAL_N_DIR / "reports/stage_r4_best_parameters.csv")["name"], pd.read_csv(CRITICAL_N_DIR / "reports/stage_r4_best_parameters.csv")["value"]))

sandboxes = {s: CrossSeasonSandbox(CRITICAL_N_DIR / "runs/search_sandboxes" / s, s, BIN_CNC) for s in ["26SP", "25SP", "25FA"]}

combos = []
for trifl in [0.86, 0.87, 0.88, 0.89]:
    for sfdur in [30.5, 31.5, 32.5]:
        for xfrt in [0.922, 0.9267]:
            p = copy.deepcopy(base_params)
            p["TRIFL"] = trifl
            p["SFDUR"] = sfdur
            p["XFRT"] = xfrt
            lbl = f"TR_{trifl}_SF_{sfdur}_X_{xfrt}"
            combos.append((lbl, p))

print(f"Refinement: {len(combos)} combos")
for idx, (lbl, cand) in enumerate(combos):
    res = evaluate_params(sandboxes, cand, comp_cat)
    y26 = res["26SP"]["term_yield_nrmse"]
    d26 = res["26SP"]["term_yield_d"]
    y25 = res["25SP"]["all_yield_nrmse"]
    nse25 = res["25SP"]["all_yield_nse"]
    lw25 = res["25SP"]["lwad_nse"]
    yfa = res["25FA"]["all_yield_nrmse"]
    nsefa = res["25FA"]["all_yield_nse"]
    dfa = res["25FA"]["all_yield_d"]
    swfa = res["25FA"]["swad_nse"]
    print(f"[{idx+1:2d}] {lbl}: 26SP={y26:5.2f}% (d={d26:.3f}) | 25SP y_nrmse={y25:5.2f}%, nse={nse25:5.2f}, lw={lw25:5.2f} | 25FA y_nrmse={yfa:5.1f}%, nse={nsefa:6.2f}, d={dfa:5.3f}, sw={swfa:5.2f}")
