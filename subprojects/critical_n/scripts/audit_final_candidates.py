#!/usr/bin/env python3
from pathlib import Path
import copy, pandas as pd, sys
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from subprojects.critical_n.scripts.cross_season_evaluator import BIN_CNC, CrossSeasonSandbox, compute_metrics

comp_cat = pd.read_csv('workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012/result_review_20261013/comparison_all_roles.csv')
base_params = dict(zip(pd.read_csv('subprojects/critical_n/reports/stage_r4_best_parameters.csv')['name'], pd.read_csv('subprojects/critical_n/reports/stage_r4_best_parameters.csv')['value']))
sandboxes = {s: CrossSeasonSandbox(Path('subprojects/critical_n/runs/search_sandboxes') / s, s, BIN_CNC) for s in ['26SP', '25SP', '25FA']}

def full_eval(cand_params, label):
    print(f"\n==================== {label} ====================")
    for s in ['26SP', '25SP', '25FA']:
        sb = sandboxes[s]
        sb.run_simulation(cand_params)
        pairs = sb.extract_observations(comp_cat)
        print(f"--- Season {s} ---")
        for v in ['CHFPW', 'CHPDT', 'LAID', 'LWAD', 'SWAD', 'LEAF_N_PCT', 'STEM_N_PCT', 'VWC']:
            sub = pairs[pairs['variable'] == v]
            if len(sub) > 0:
                m = compute_metrics(sub['observed'].to_numpy(), sub['simulated'].to_numpy())
                print(f"  {v:11s} (n={m['n']:3d}) | NRMSE={m['nrmse']:5.2f}% | NSE={m['nse']:6.3f} | d={m['d']:5.3f} | R2={m['r2']:5.3f}")

cand_a = copy.deepcopy(base_params)
cand_a.update({'TRIFL': 0.825, 'SFDUR': 30.5})
full_eval(cand_a, "Cand_A (TRIFL=0.825, SFDUR=30.5)")

cand_f = copy.deepcopy(base_params)
cand_f.update({'TRIFL': 0.825, 'SFDUR': 30.5, 'SENPOR_LATE': 0.280})
full_eval(cand_f, "Cand_F (TRIFL=0.825, SFDUR=30.5, SENPOR_LATE=0.280)")
