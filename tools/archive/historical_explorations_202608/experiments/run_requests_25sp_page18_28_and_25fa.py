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

OUT = ROOT / 'workspace/reports/e02_requests_page_and_25fa_20260901'
SCRATCH = OUT / 'scratch_runs'
OUT.mkdir(parents=True, exist_ok=True)
SCRATCH.mkdir(parents=True, exist_ok=True)

CHAMP_CSV = ROOT / 'workspace/runs/e02_formal_v46_page25_unified_20260901/page25_champion_params.csv'
champ_params = pd.read_csv(CHAMP_CSV)

BASE_DESIGN_FILE = ROOT / 'workspace/reports/e02_v46_dias2026_double_n_20260831/design_all22_double_n.json'

def calc_metrics(df, obs_col, sim_col):
    ok = df[obs_col].notna() & df[sim_col].notna() & (df[obs_col] > -90) & (df[sim_col] > -90)
    sub = df[ok]
    o = sub[obs_col].to_numpy(float)
    s = sub[sim_col].to_numpy(float)
    if len(o) < 2:
        return {'n': len(o), 'rmse': np.nan, 'nrmse_pct': np.nan, 'mae': np.nan, 'bias': np.nan, 'nse': np.nan, 'd_index': np.nan, 'r2': np.nan}
    err = s - o
    rmse = float(np.sqrt(np.mean(err**2)))
    nrmse = float(rmse / np.mean(o)) if np.mean(o) != 0 else 0.0
    mae = float(np.mean(np.abs(err)))
    bias = float(np.mean(err))
    sst = float(np.sum((o - np.mean(o))**2))
    nse = float(1.0 - np.sum(err**2) / sst) if sst > 0 else np.nan
    denom_d = float(np.sum((np.abs(s - np.mean(o)) + np.abs(o - np.mean(o)))**2))
    d_index = float(1.0 - np.sum(err**2) / denom_d) if denom_d > 0 else np.nan
    r2 = float(np.corrcoef(o, s)[0, 1]**2) if len(o) > 2 and np.std(o) > 1e-6 and np.std(s) > 1e-6 else np.nan
    return {'n': len(o), 'rmse': rmse, 'nrmse_pct': nrmse * 100.0, 'mae': mae, 'bias': bias, 'nse': nse, 'd_index': d_index, 'r2': r2}

src_b25 = ROOT / 'data/user/experiments/xxql2501_scheme4_double_n_20260831'
src_b26 = ROOT / 'data/user/experiments/xxql2601_page25_double_n_20260901'

def build_25sp_bundle(page, dst_dir):
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    shutil.copytree(src_b25, dst_dir)
    tmx_p = dst_dir / 'XXQL2501.TMX'
    lines = tmx_p.read_text(encoding='utf-8', errors='ignore').splitlines()
    new_lines = []
    in_p = False
    for l in lines:
        if l.startswith('*PLANTING DETAILS'):
            in_p = True
            new_lines.append(l)
        elif in_p and l.startswith('*'):
            in_p = False
            new_lines.append(l)
        elif in_p and l.startswith(' 2 25075'):
            new_l = f' 2 25075   -99   2.7   2.7     T     R    90    90     8   9.5    {page:>2}    25   -99   -99                        Eggplant'
            new_lines.append(new_l)
        else:
            new_lines.append(l)
    tmx_p.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')

page_list = [18, 25, 28, 30, 60]
part1_results = []

for page_val in page_list:
    run_path = SCRATCH / f'25sp_page_{page_val}'
    run_path.mkdir(parents=True, exist_ok=True)
    
    b25_target = run_path / f'xxql2501_p{page_val}'
    build_25sp_bundle(page_val, b25_target)
    
    champ_params.to_csv(run_path / 'params.csv', index=False)
    
    design = json.loads(BASE_DESIGN_FILE.read_text(encoding='utf-8'))
    design['design_id'] = f'eval_25sp_p{page_val}'
    for s in design['seasons']:
        if s['season_id'] == '25SP':
            s['bundle_path'] = str(b25_target.resolve())
        elif s['season_id'] == '26SP':
            s['bundle_path'] = str(src_b26.resolve())
            
    (run_path / 'design.json').write_text(json.dumps(design, indent=2), encoding='utf-8')
    
    cmd = [
        sys.executable, str(ROOT / 'src/calibration/run_multiseason.py'),
        '--design', str(run_path / 'design.json'),
        '--param-csv', str(run_path / 'params.csv'),
        '--prefix', 'det', '--harvest-var', 'CHFPW',
    ]
    res = subprocess.run(cmd, cwd=str(run_path), capture_output=True, text=True, encoding='utf-8', errors='replace')
    if res.returncode != 0:
        print(f'[ERROR] 25SP PAGE={page_val} failed: {res.stderr}')
        continue
        
    from src.reporting.analyze_results import deterministic_process_compare, deterministic_harvest_compare
    sdir25 = run_path / '_seasons/25SP'
    filex = next(sdir25.glob('*.TMX'))
    batch = sdir25 / 'analysis_batch.v48'
    batch.write_text('\n'.join(f'{filex.resolve()} {tn} 1 0 0 0' for tn in [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]) + '\n', encoding='utf-8')
    deterministic_process_compare('25SP', str(batch), var_names=['L#SD', 'LAID', 'LWAD', 'SWAD', 'CHTD'], run_dir=str(sdir25))
    deterministic_harvest_compare('25SP', str(batch), run_dir=str(sdir25))
    
    h25 = pd.read_csv(sdir25 / '25SP_deterministic_harvest_compare.csv')
    p25 = pd.read_csv(sdir25 / '25SP_deterministic_process_compare.csv')
    
    row = {'PAGE': page_val}
    for var, df, o_col, s_col in [
        ('CHFPW', h25, 'OBS_FRESH_CUM', 'SIM_FRESH_CUM'),
        ('CHPDT', h25, 'OBS_DRY_CUM', 'SIM_DRY_CUM'),
        ('CHTD', p25, 'OBS_CHTD', 'SIM_CHTD'),
        ('LAID', p25, 'OBS_LAID', 'SIM_LAID'),
        ('LWAD', p25, 'OBS_LWAD', 'SIM_LWAD'),
        ('SWAD', p25, 'OBS_SWAD', 'SIM_SWAD'),
    ]:
        m = calc_metrics(df, o_col, s_col)
        row[f'{var}_rmse'] = m['rmse']
        row[f'{var}_nrmse_pct'] = m['nrmse_pct']
        row[f'{var}_nse'] = m['nse']
        row[f'{var}_d_index'] = m['d_index']
        row[f'{var}_r2'] = m['r2']
    part1_results.append(row)
    
    y_nse = row['CHFPW_nse']
    y_rmse = row['CHFPW_rmse']
    h_nse = row['CHTD_nse']
    h_rmse = row['CHTD_rmse']
    l_nse = row['LAID_nse']
    print(f'25SP PAGE={page_val:2d} -> Yield NSE: {y_nse:6.3f}, Yield RMSE: {y_rmse:6.1f}, CHTD NSE: {h_nse:6.3f}, CHTD RMSE: {h_rmse:5.2f}, LAI NSE: {l_nse:6.3f}')

df_part1 = pd.DataFrame(part1_results)
df_part1.to_csv(OUT / '25sp_page_gradient_scorecard.csv', index=False)

# ====================================================================
# PART 2: 25FA FORWARD SIMULATION & DIAGNOSTICS
# ====================================================================
print('\n======================================================')
print('RUNNING 25FA WITH CURRENT GENETIC PARAMETERS')
print('======================================================')

b25fa_src = ROOT / 'data/user/experiments/XXQL2502'
run_25fa_path = SCRATCH / '25fa_evaluation'
run_25fa_path.mkdir(parents=True, exist_ok=True)
b25fa_target = run_25fa_path / 'xxql2502_bundle'
if b25fa_target.exists():
    shutil.rmtree(b25fa_target)
shutil.copytree(b25fa_src, b25fa_target)

champ_params.to_csv(run_25fa_path / 'params.csv', index=False)

design_25fa = json.loads(BASE_DESIGN_FILE.read_text(encoding='utf-8'))
design_25fa['design_id'] = 'eval_25fa_current_params'
design_25fa['seasons'] = [
    {
        'season_id': '25FA',
        'excode': 'XXQL2502',
        'bundle_path': str(b25fa_target.resolve()),
        'treatments': list(range(1, 13)),
    },
    {
        'season_id': '26SP',
        'excode': 'XXQL2601',
        'bundle_path': str(src_b26.resolve()),
        'treatments': list(range(1, 13)),
    }
]
(run_25fa_path / 'design.json').write_text(json.dumps(design_25fa, indent=2), encoding='utf-8')

cmd_fa = [
    sys.executable, str(ROOT / 'src/calibration/run_multiseason.py'),
    '--design', str(run_25fa_path / 'design.json'),
    '--param-csv', str(run_25fa_path / 'params.csv'),
    '--prefix', 'det_fa', '--harvest-var', 'CHFPW',
]
res_fa = subprocess.run(cmd_fa, cwd=str(run_25fa_path), capture_output=True, text=True, encoding='utf-8', errors='replace')
if res_fa.returncode != 0:
    print(f'[ERROR] 25FA simulation failed: {res_fa.stderr}')
    print(f'STDOUT: {res_fa.stdout}')
else:
    from src.reporting.analyze_results import deterministic_process_compare, deterministic_harvest_compare
    sdir_fa = run_25fa_path / '_seasons/25FA'
    filex_fa = next(sdir_fa.glob('*.TMX'))
    batch_fa = sdir_fa / 'analysis_batch.v48'
    batch_fa.write_text('\n'.join(f'{filex_fa.resolve()} {tn} 1 0 0 0' for tn in range(1, 13)) + '\n', encoding='utf-8')
    deterministic_process_compare('25FA', str(batch_fa), var_names=['L#SD', 'LAID', 'LWAD', 'SWAD', 'CHTD'], run_dir=str(sdir_fa))
    deterministic_harvest_compare('25FA', str(batch_fa), run_dir=str(sdir_fa))
    
    h_fa = pd.read_csv(sdir_fa / '25FA_deterministic_harvest_compare.csv')
    p_fa = pd.read_csv(sdir_fa / '25FA_deterministic_process_compare.csv')
    
    fa_metrics = []
    for var_label, df_src, o_col, s_col, u_str in [
        ('Fresh Cum Yield (CHFPW)', h_fa, 'OBS_FRESH_CUM', 'SIM_FRESH_CUM', 'kg/ha'),
        ('Dry Cum Yield (CHPDT)', h_fa, 'OBS_DRY_CUM', 'SIM_DRY_CUM', 'kg/ha'),
        ('Fresh Inc Harvest (HFPOW)', h_fa, 'OBS_FRESH_INC', 'SIM_FRESH_INC', 'kg/ha'),
        ('Dry Inc Harvest (HPODW)', h_fa, 'OBS_DRY_INC', 'SIM_DRY_INC', 'kg/ha'),
        ('Canopy Height (CHTD)', p_fa, 'OBS_CHTD', 'SIM_CHTD', 'm'),
        ('Leaf Area Index (LAID)', p_fa, 'OBS_LAID', 'SIM_LAID', 'm2/m2'),
        ('Leaf Dry Biomass (LWAD)', p_fa, 'OBS_LWAD', 'SIM_LWAD', 'g/m2'),
        ('Stem Dry Biomass (SWAD)', p_fa, 'OBS_SWAD', 'SIM_SWAD', 'g/m2'),
    ]:
        m = calc_metrics(df_src, o_col, s_col)
        m['variable'] = var_label
        m['unit'] = u_str
        fa_metrics.append(m)
        v_n = m['n']
        v_rmse = m['rmse']
        v_nrmse = m['nrmse_pct']
        v_nse = m['nse']
        v_d = m['d_index']
        v_r2 = m['r2']
        print(f'25FA {var_label:<25}: n={v_n:2d}, RMSE={v_rmse:7.2f} {u_str}, NRMSE={v_nrmse:5.1f}%, NSE={v_nse:6.3f}, d={v_d:5.3f}, R2={v_r2:5.3f}')

    df_fa = pd.DataFrame(fa_metrics)
    df_fa.to_csv(OUT / '25fa_simulation_metrics.csv', index=False)
    print('\nSuccessfully exported 25FA simulation metrics.')
