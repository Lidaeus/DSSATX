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

print("Baseline R4: 26SP yld=5.48%, lai_nse=0.742, lwad_nse=0.827 | 25SP yld_nse=0.669, lw_nse=0.867 | 25FA yld_nse=-14.384, d=0.430")

for tr in [0.792, 0.810, 0.825, 0.840]:
    for sf in [27.14, 29.5, 31.0]:
        cand = copy.deepcopy(base_params)
        cand['TRIFL'] = tr
        cand['SFDUR'] = sf
        res = evaluate_params(sandboxes, cand, comp_cat)
        r26, r25, rfa = res['26SP'], res['25SP'], res['25FA']
        print(f"TR={tr:.3f}, SF={sf:.2f} | 26SP: yld={r26['term_yield_nrmse']:5.2f}%, lai_nse={r26['lai_nse']:5.3f}, lwad_nse={r26['lwad_nse']:5.3f} | 25SP: yld_nse={r25['all_yield_nse']:5.3f}, lw_nse={r25['lwad_nse']:5.3f} | 25FA: yld_nse={rfa['all_yield_nse']:6.3f}, d={rfa['all_yield_d']:5.3f}")
