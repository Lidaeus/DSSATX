#!/usr/bin/env python3
from pathlib import Path
import copy, pandas as pd
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from subprojects.critical_n.scripts.cross_season_evaluator import BIN_CNC, CrossSeasonSandbox
from subprojects.critical_n.scripts.explore_targeted_enhancements import evaluate_params

comp_cat = pd.read_csv('workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/result_review_20261013/comparison_all_roles.csv')
base_params = dict(zip(pd.read_csv('subprojects/critical_n/reports/stage_r4_best_parameters.csv')['name'], pd.read_csv('subprojects/critical_n/reports/stage_r4_best_parameters.csv')['value']))
sandboxes = {s: CrossSeasonSandbox(Path('subprojects/critical_n/runs/search_sandboxes') / s, s, BIN_CNC) for s in ['26SP', '25SP', '25FA']}

tests = [
    ("Base_R4", {}),
    ("Prior_Enhanced", {"XFRT": 0.88, "FRLFF": 0.135}),
    ("Cand_A_TR0825_SF305", {"TRIFL": 0.825, "SFDUR": 30.5}),
    ("Cand_B_TR0825_SF305_SN270", {"TRIFL": 0.825, "SFDUR": 30.5, "SENPOR_LATE": 0.270}),
    ("Cand_C_TR0830_SF305_SN275", {"TRIFL": 0.830, "SFDUR": 30.5, "SENPOR_LATE": 0.275}),
    ("Cand_D_TR0820_SF305_X922", {"TRIFL": 0.820, "SFDUR": 30.5, "XFRT": 0.922}),
    ("Cand_E_TR0835_SF310_SN270", {"TRIFL": 0.835, "SFDUR": 31.0, "SENPOR_LATE": 0.270}),
    ("Cand_F_TR0825_SF305_SN280", {"TRIFL": 0.825, "SFDUR": 30.5, "SENPOR_LATE": 0.280}),
    ("Cand_G_TR0820_SF300_SN280", {"TRIFL": 0.820, "SFDUR": 30.0, "SENPOR_LATE": 0.280}),
]

for name, patch in tests:
    cand = copy.deepcopy(base_params)
    cand.update(patch)
    res = evaluate_params(sandboxes, cand, comp_cat)
    r26, r25, rfa = res['26SP'], res['25SP'], res['25FA']
    print(f"{name:26s} | 26SP: yld={r26['term_yield_nrmse']:5.2f}%, lai={r26['lai_nse']:5.3f}, lw={r26['lwad_nse']:5.3f}, sw={r26['swad_nse']:5.3f} | 25SP: yld_nse={r25['all_yield_nse']:5.3f}, lw={r25['lwad_nse']:5.3f} | 25FA: yld_nrmse={rfa['all_yield_nrmse']:5.1f}%, yld_nse={rfa['all_yield_nse']:6.3f}, d={rfa['all_yield_d']:5.3f}")
