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

OUT = ROOT / 'workspace/reports/e02_targeted_pressure_relief_grid_20260901'
SCRATCH = OUT / 'scratch_runs'
OUT.mkdir(parents=True, exist_ok=True)
SCRATCH.mkdir(parents=True, exist_ok=True)

CHAMP_CSV = ROOT / 'workspace/runs/e02_formal_v46_page25_unified_20260901/page25_champion_params.csv'
base_params = pd.read_csv(CHAMP_CSV).set_index('name')['value'].to_dict()

BASE_DESIGN_FILE = ROOT / 'workspace/reports/e02_v46_dias2026_double_n_20260831/design_all22_double_n.json'
b25 = ROOT / 'data/user/experiments/xxql2501_page25_double_n_20260901'
b26 = ROOT / 'data/user/experiments/xxql2601_page25_double_n_20260901'

N_PAIRS = profile.N_PAIRS

def signed_metric(obs: pd.Series, sim: pd.Series) -> float:
    o = pd.to_numeric(obs, errors='coerce').to_numpy(float)
    s = pd.to_numeric(sim, errors='coerce').to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s)
    o, s = o[ok], s[ok]
    if len(o) < 2: return float('nan')
    sst = float(np.square(o - o.mean()).sum())
    return 1.0 - float(np.square(s - o).sum()) / sst if sst > 0 else float('nan')

def run_grid_case(case_id, mod_dict):
    run_dir = SCRATCH / case_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    p_dict = dict(base_params)
    p_dict.update(mod_dict)
    
    param_records = [{'name': k, 'value': v} for k, v in p_dict.items()]
    pd.DataFrame(param_records).to_csv(run_dir / 'params.csv', index=False)
    
    design = json.loads(BASE_DESIGN_FILE.read_text(encoding='utf-8'))
    design['design_id'] = f'grid_{case_id}'
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
    for sid, tns in [('25SP', [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]), ('26SP', list(range(1, 13)))]:
        sdir = run_dir / '_seasons' / sid
        filex = next(sdir.glob('*.TMX'))
        batch = sdir / 'analysis_batch.v48'
        batch.write_text('\n'.join(f'{filex.resolve()} {tn} 1 0 0 0' for tn in tns) + '\n', encoding='utf-8')
        deterministic_process_compare(sid, str(batch), var_names=['L#SD', 'LAID', 'LWAD', 'SWAD', 'CHTD'], run_dir=str(sdir))
        deterministic_harvest_compare(sid, str(batch), run_dir=str(sdir))
        
        h = pd.read_csv(sdir / f'{sid}_deterministic_harvest_compare.csv')
        p = pd.read_csv(sdir / f'{sid}_deterministic_process_compare.csv')
        
        out_row[f'{sid}_fresh_cum_nse'] = signed_metric(h['OBS_FRESH_CUM'], h['SIM_FRESH_CUM'])
        out_row[f'{sid}_chtd_nse'] = signed_metric(p['OBS_CHTD'], p['SIM_CHTD'])
        out_row[f'{sid}_lai_nse'] = signed_metric(p['OBS_LAID'], p['SIM_LAID'])
        out_row[f'{sid}_lwad_nse'] = signed_metric(p['OBS_LWAD'], p['SIM_LWAD'])
        out_row[f'{sid}_swad_nse'] = signed_metric(p['OBS_SWAD'], p['SIM_SWAD'])
        
        # RMSE
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
    )
    return out_row

# Targeted grid combinations:
grid_cases = []

# Module 1: Specific Leaf Area (SLAVR) & Leaf Appearance (TRIFL)
for slavr in [190.0, 230.0, 260.0]:
    for trifl in [0.65, 0.75, 0.85]:
        for sizlf in [260.0, 315.0]:
            grid_cases.append({
                'name': f'canopy_sl_{slavr:.0f}_tr_{trifl:.2f}_sz_{sizlf:.0f}',
                'params': {'SLAVR': slavr, 'TRIFL': trifl, 'SIZLF': sizlf}
            })

# Module 2: Phenology (EM-FL) & Fruit Partition (XFRT, SHLAG)
for em_fl in [18.0, 20.0, 22.0, 24.0]:
    for xfrt in [0.88, 0.91, 0.93]:
        for shlag in [12.0, 15.0, 18.0]:
            grid_cases.append({
                'name': f'source_sink_ef_{em_fl:.1f}_xf_{xfrt:.2f}_sh_{shlag:.0f}',
                'params': {'EM-FL': em_fl, 'XFRT': xfrt, 'SHLAG': shlag}
            })

# Module 3: Nitrogen Uptake (RTNO3) & Photosynthesis Critical N (FNPGN2, LNREF)
for rtno3 in [0.018, 0.024, 0.030]:
    for fn2 in [4.50, 4.90, 5.20]:
        for lnref in [3.80, 4.20, 4.50]:
            grid_cases.append({
                'name': f'nitrogen_rt_{rtno3:.3f}_fn2_{fn2:.2f}_ln_{lnref:.2f}',
                'params': {'RTNO3': rtno3, 'FNPGN2': fn2, 'LNREF': lnref}
            })

# Module 4: Integrated Synergy Combinations
for slavr in [230.0, 260.0]:
    for em_fl in [19.0, 21.0]:
        for xfrt in [0.91, 0.93]:
            for fn2 in [4.90, 5.20]:
                for rtno3 in [0.020, 0.024]:
                    grid_cases.append({
                        'name': f'synergy_sl_{slavr:.0f}_ef_{em_fl:.0f}_xf_{xfrt:.2f}_fn_{fn2:.2f}_rt_{rtno3:.3f}',
                        'params': {'SLAVR': slavr, 'EM-FL': em_fl, 'XFRT': xfrt, 'FNPGN2': fn2, 'RTNO3': rtno3, 'TRIFL': 0.75}
                    })

print(f'Constructed {len(grid_cases)} targeted grid cases. Running simulations...')
results = []
for idx, gc in enumerate(grid_cases, 1):
    c_name = gc['name']
    c_params = gc['params']
    r = run_grid_case(c_name, c_params)
    if r:
        results.append(r)
        y25 = r['25SP_fresh_cum_nse']
        y26 = r['26SP_fresh_cum_nse']
        h25 = r['25SP_chtd_nse']
        h26 = r['26SP_chtd_nse']
        l25 = r['25SP_lai_nse']
        l26 = r['26SP_lai_nse']
        score = r['composite_score']
        print(f'[{idx:02d}/{len(grid_cases):02d}] {c_name} -> Y25:{y25:.3f}, Y26:{y26:.3f}, H25:{h25:.3f}, H26:{h26:.3f}, L25:{l25:.3f}, L26:{l26:.3f}, Score:{score:.2f}', flush=True)

df = pd.DataFrame(results)
df.sort_values('composite_score', ascending=False).to_csv(OUT / 'targeted_grid_scorecard.csv', index=False)
print('\n======================================================')
print('TARGETED GRID EXPERIMENT RESULTS (Top 10 Overall)')
print('======================================================')
top10 = df.sort_values('composite_score', ascending=False).head(10)
cols = ['case_id', '25SP_fresh_cum_nse', '26SP_fresh_cum_nse', '25SP_chtd_nse', '26SP_chtd_nse', '25SP_lai_nse', '26SP_lai_nse', 'composite_score']
print(top10[cols].to_string(index=False))
