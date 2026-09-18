import json
import sys
import subprocess
import shutil
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('D:/Tomato_Cal')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.profile_v46_best71_nitrogen_20260831 as profile

RUN_NAME = 'e02_formal_v46_page28_25_opt_20260901'
RUN_DIR = ROOT / f'workspace/runs/{RUN_NAME}'
REPORT_DIR = ROOT / f'workspace/reports/{RUN_NAME}'
OUT_FIG = ROOT / f'figture/{RUN_NAME}'
SCRATCH = REPORT_DIR / 'scratch_runs'

RUN_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FIG.mkdir(parents=True, exist_ok=True)
SCRATCH.mkdir(parents=True, exist_ok=True)

BASE_DESIGN_FILE = ROOT / 'workspace/reports/e02_v46_dias2026_double_n_20260831/design_all22_double_n.json'
b25 = ROOT / 'data/user/experiments/xxql2501_page28_double_n_20260901'
b26 = ROOT / 'data/user/experiments/xxql2601_page25_double_n_imputed_lai_20260901'

ANCHOR_CSV = (profile.BASE / 'best_member_71_params.csv').resolve()
base_df = pd.read_csv(ANCHOR_CSV)
base_params = base_df.set_index('name')['value'].to_dict()

N_PAIRS = profile.N_PAIRS

def signed_metric(obs: pd.Series, sim: pd.Series) -> float:
    o = pd.to_numeric(obs, errors='coerce').to_numpy(float)
    s = pd.to_numeric(sim, errors='coerce').to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s) & (o > -90.0) & (s > -90.0)
    o, s = o[ok], s[ok]
    if len(o) < 2: return float('nan')
    sst = float(np.square(o - o.mean()).sum())
    return 1.0 - float(np.square(s - o).sum()) / sst if sst > 0 else float('nan')

def compute_relaxed_harvest_phi(h25: pd.DataFrame, h26: pd.DataFrame) -> dict[str, float]:
    phi_inc_25 = 0.0
    for hno, w_mult in [(1, 0.10), (2, 0.20), (3, 1.0), (4, 1.0), (5, 1.0), (6, 1.0), (7, 1.0), (8, 1.0), (9, 1.0)]:
        sub = h25[h25['HNO'] == hno]
        err = sub['SIM_FRESH_INC'] - sub['OBS_FRESH_INC']
        sigma = 400.0
        w = (w_mult * 0.3227) / sigma
        phi_inc_25 += float(np.sum((err * w)**2))
        
    phi_inc_26 = 0.0
    for hno, w_mult in [(1, 0.10), (2, 0.20), (3, 1.0), (4, 1.0), (5, 1.0)]:
        sub = h26[h26['HNO'] == hno]
        err = sub['SIM_FRESH_INC'] - sub['OBS_FRESH_INC']
        sigma = 700.0
        w = (w_mult * 0.4330) / sigma
        phi_inc_26 += float(np.sum((err * w)**2))
        
    term25 = h25.sort_values(['TN', 'HNO']).groupby('TN').tail(1)
    err_term_25 = term25['SIM_FRESH_CUM'] - term25['OBS_FRESH_CUM']
    phi_term_25 = float(np.sum((err_term_25 * 0.000216)**2))
    
    term26 = h26.sort_values(['TN', 'HNO']).groupby('TN').tail(1)
    err_term_26 = term26['SIM_FRESH_CUM'] - term26['OBS_FRESH_CUM']
    phi_term_26 = float(np.sum((err_term_26 * 0.000205)**2))
    
    return {
        'phi_inc_25_relaxed': phi_inc_25,
        'phi_inc_26_relaxed': phi_inc_26,
        'phi_term_25': phi_term_25,
        'phi_term_26': phi_term_26,
        'phi_harvest_total_relaxed': phi_inc_25 + phi_inc_26 + phi_term_25 + phi_term_26,
    }

def run_candidate(case_id, mod_dict):
    run_dir = SCRATCH / case_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    p_dict = dict(base_params)
    p_dict.update({
        'PROLFF': 0.105, 'PROLFG': 0.210, 'PROLFI': 0.260,
        'PROSTF': 0.060, 'PROSTG': 0.125, 'PROSTI': 0.200,
        'PRORTF': 0.050, 'PRORTG': 0.119, 'PRORTI': 0.150,
        'PROSHF': 0.105, 'PROSHG': 0.145, 'PROSHI': 0.205,
        'NSTFAC': 0.70, 'RTNH4': 0.033,
        'NMOBMX': 0.35, 'NVSMOB': 0.80, 'SENRTE': 2.50,
        'NSLOPE': 0.25, 'FNPGN1': 1.80,
    })
    p_dict.update(mod_dict)
    
    param_records = [{'name': k, 'value': v} for k, v in p_dict.items()]
    pd.DataFrame(param_records).to_csv(run_dir / 'params.csv', index=False)
    
    design = json.loads(BASE_DESIGN_FILE.read_text(encoding='utf-8'))
    design['design_id'] = f'cal_{case_id}'
    design['water_response_objective']['enabled'] = False
    design['nitrogen_response_objective']['enabled'] = False
    for s in design['seasons']:
        if s['season_id'] == '25SP':
            s['bundle_path'] = str(b25.resolve())
        elif s['season_id'] == '26SP':
            s['bundle_path'] = str(b26.resolve())
            
    (run_dir / 'design.json').write_text(json.dumps(design, indent=2), encoding='utf-8')
    
    cmd = [
        sys.executable, str(ROOT / 'src/calibration/run_multiseason.py'),
        '--design', str(run_dir / 'design.json'),
        '--param-csv', str(run_dir / 'params.csv'),
        '--prefix', 'det', '--harvest-var', 'CHFPW',
    ]
    res = subprocess.run(cmd, cwd=str(run_dir), capture_output=True, text=True)
    if res.returncode != 0:
        return None
        
    from src.reporting.analyze_results import deterministic_process_compare, deterministic_harvest_compare
    out_row = {'case_id': case_id, **mod_dict}
    
    sdir25 = run_dir / '_seasons/25SP'
    filex25 = next(sdir25.glob('*.TMX'))
    batch25 = sdir25 / 'analysis_batch.v48'
    batch25.write_text('\n'.join(f'{filex25.resolve()} {tn} 1 0 0 0' for tn in [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]) + '\n', encoding='utf-8')
    deterministic_process_compare('25SP', str(batch25), var_names=['L#SD', 'LAID', 'LWAD', 'SWAD', 'CHTD'], run_dir=str(sdir25))
    deterministic_harvest_compare('25SP', str(batch25), run_dir=str(sdir25))
    h25 = pd.read_csv(sdir25 / '25SP_deterministic_harvest_compare.csv')
    p25 = pd.read_csv(sdir25 / '25SP_deterministic_process_compare.csv')

    sdir26 = run_dir / '_seasons/26SP'
    filex26 = next(sdir26.glob('*.TMX'))
    batch26 = sdir26 / 'analysis_batch.v48'
    batch26.write_text('\n'.join(f'{filex26.resolve()} {tn} 1 0 0 0' for tn in range(1, 13)) + '\n', encoding='utf-8')
    deterministic_process_compare('26SP', str(batch26), var_names=['L#SD', 'LAID', 'LWAD', 'SWAD', 'CHTD'], run_dir=str(sdir26))
    deterministic_harvest_compare('26SP', str(batch26), run_dir=str(sdir26))
    h26 = pd.read_csv(sdir26 / '26SP_deterministic_harvest_compare.csv')
    p26 = pd.read_csv(sdir26 / '26SP_deterministic_process_compare.csv')

    phi_dict = compute_relaxed_harvest_phi(h25, h26)
    out_row.update(phi_dict)
    
    for sid, h, p in [('25SP', h25, p25), ('26SP', h26, p26)]:
        out_row[f'{sid}_fresh_cum_nse'] = signed_metric(h['OBS_FRESH_CUM'], h['SIM_FRESH_CUM'])
        out_row[f'{sid}_chtd_nse'] = signed_metric(p['OBS_CHTD'], p['SIM_CHTD'])
        out_row[f'{sid}_lai_nse'] = signed_metric(p['OBS_LAID'], p['SIM_LAID'])
        out_row[f'{sid}_lwad_nse'] = signed_metric(p['OBS_LWAD'], p['SIM_LWAD'])
        out_row[f'{sid}_swad_nse'] = signed_metric(p['OBS_SWAD'], p['SIM_SWAD'])
        
        for var, df, o_col, s_col in [
            ('fresh_cum', h, 'OBS_FRESH_CUM', 'SIM_FRESH_CUM'),
            ('chtd', p, 'OBS_CHTD', 'SIM_CHTD'),
            ('lai', p, 'OBS_LAID', 'SIM_LAID'),
        ]:
            sub_ok = df.dropna(subset=[o_col, s_col])
            sub_ok = sub_ok[(sub_ok[o_col] > -90) & (sub_ok[s_col] > -90)]
            err = sub_ok[s_col].to_numpy() - sub_ok[o_col].to_numpy()
            out_row[f'{sid}_{var}_rmse'] = float(np.sqrt(np.mean(err**2)))

    out_row['composite_score'] = (
        out_row['25SP_fresh_cum_nse'] * 25.0
        + out_row['26SP_fresh_cum_nse'] * 25.0
        + max(out_row['25SP_chtd_nse'], -1.0) * 20.0
        + max(out_row['26SP_chtd_nse'], -1.0) * 20.0
        + max(out_row['25SP_lai_nse'], -1.0) * 15.0
        + max(out_row['26SP_lai_nse'], -1.0) * 15.0
        - (out_row['phi_harvest_total_relaxed'] / 60.0)
    )
    return out_row, p_dict

candidate_list = []
for em_fl in [21.0, 22.0, 23.0, 24.0]:
    for xfrt in [0.915, 0.930, 0.945]:
        for shlag in [15.0, 18.0]:
            for slavr in [190.0, 205.0]:
                for trifl in [0.72, 0.76]:
                    for fn2 in [4.80, 5.00]:
                        for lnref in [4.10, 4.30]:
                            for rtno3 in [0.020, 0.024]:
                                c_id = f'ef_{em_fl:.1f}_xf_{xfrt:.3f}_sh_{shlag:.0f}_sl_{slavr:.0f}_tr_{trifl:.2f}_fn_{fn2:.2f}_ln_{lnref:.2f}_rt_{rtno3:.3f}'
                                candidate_list.append((c_id, {
                                    'EM-FL': em_fl,
                                    'XFRT': xfrt,
                                    'SHLAG': shlag,
                                    'SLAVR': slavr,
                                    'TRIFL': trifl,
                                    'FNPGN2': fn2,
                                    'LNREF': lnref,
                                    'RTNO3': rtno3,
                                }))

print(f'Starting parameter calibration with complete 48/48 LAI observations across {len(candidate_list)} configurations...')

score_rows = []
param_store = {}

for idx, (cid, pmods) in enumerate(candidate_list, 1):
    res_tuple = run_candidate(cid, pmods)
    if res_tuple:
        r, full_p = res_tuple
        score_rows.append(r)
        param_store[cid] = full_p
        y25 = r['25SP_fresh_cum_nse']
        y26 = r['26SP_fresh_cum_nse']
        h25 = r['25SP_chtd_nse']
        h26 = r['26SP_chtd_nse']
        l25 = r['25SP_lai_nse']
        l26 = r['26SP_lai_nse']
        score = r['composite_score']
        print(f'[{idx:03d}/{len(candidate_list):03d}] {cid} -> Y25:{y25:.3f}, Y26:{y26:.3f}, H25:{h25:.3f}, H26:{h26:.3f}, L25:{l25:.3f}, L26:{l26:.3f}, Score:{score:.2f}', flush=True)

df = pd.DataFrame(score_rows)
df.sort_values('composite_score', ascending=False).to_csv(REPORT_DIR / 'calibration_candidates_scorecard.csv', index=False)

champion_row = df.sort_values('composite_score', ascending=False).iloc[0]
champ_id = champion_row['case_id']
champ_pdict = param_store[champ_id]

champ_df = pd.DataFrame([{'name': k, 'value': v} for k, v in champ_pdict.items()])
champ_df.to_csv(RUN_DIR / 'page28_25_champion_params.csv', index=False)

print('\n======================================================')
print(f'CALIBRATION COMPLETED! Champion Case: {champ_id}')
c_score = champion_row['composite_score']
y25_val = champion_row['25SP_fresh_cum_nse']
y25_rmse = champion_row['25SP_fresh_cum_rmse']
h25_val = champion_row['25SP_chtd_nse']
h25_rmse = champion_row['25SP_chtd_rmse']
l25_val = champion_row['25SP_lai_nse']
y26_val = champion_row['26SP_fresh_cum_nse']
y26_rmse = champion_row['26SP_fresh_cum_rmse']
h26_val = champion_row['26SP_chtd_nse']
h26_rmse = champion_row['26SP_chtd_rmse']
l26_val = champion_row['26SP_lai_nse']

print(f'Composite Score: {c_score:.3f}')
print(f'25SP: Fresh Yield NSE={y25_val:.3f} (RMSE={y25_rmse:6.1f}), CHTD NSE={h25_val:.3f} (RMSE={h25_rmse:.2f}), LAI NSE={l25_val:.3f}')
print(f'26SP: Fresh Yield NSE={y26_val:.3f} (RMSE={y26_rmse:6.1f}), CHTD NSE={h26_val:.3f} (RMSE={h26_rmse:.2f}), LAI NSE={l26_val:.3f}')
print('======================================================')
