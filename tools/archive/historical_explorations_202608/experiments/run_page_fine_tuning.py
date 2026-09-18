import json
import sys
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('D:/Tomato_Cal')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import tools.calibration.profile_v46_best71_nitrogen_20260831 as profile

ANCHOR = (profile.BASE / 'best_member_71_params.csv').resolve()
OUT = (ROOT / 'workspace/reports/e02_page_fine_tuning_20260901').resolve()
SCRATCH = OUT / 'scratch_runs'
OUT.mkdir(parents=True, exist_ok=True)
SCRATCH.mkdir(parents=True, exist_ok=True)

def signed_metric(obs: pd.Series, sim: pd.Series) -> float:
    o = pd.to_numeric(obs, errors='coerce').to_numpy(float)
    s = pd.to_numeric(sim, errors='coerce').to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s)
    o, s = o[ok], s[ok]
    if len(o) < 2: return float('nan')
    sst = float(np.square(o - o.mean()).sum())
    return 1.0 - float(np.square(s - o).sum()) / sst if sst > 0 else float('nan')

def run_test(page, em_fl_delta, shlag_delta, xfrt_delta, rtno3=0.024, fn1=1.80, fn2=4.90, lnref=4.20):
    case_name = f'p{page}_ef{em_fl_delta:+d}_sh{shlag_delta:+d}_xf{xfrt_delta:+.2f}'
    run_path = SCRATCH / case_name
    run_path.mkdir(parents=True, exist_ok=True)
    
    base_df = pd.read_csv(ANCHOR)
    param_map = base_df.set_index('name')['value'].to_dict()
    
    param_map.update({
        'PROLFF': 0.105, 'PROLFG': 0.210, 'PROLFI': 0.260,
        'PROSTF': 0.060, 'PROSTG': 0.125, 'PROSTI': 0.200,
        'PRORTF': 0.050, 'PRORTG': 0.119, 'PRORTI': 0.150,
        'PROSHF': 0.105, 'PROSHG': 0.145, 'PROSHI': 0.205,
        'NSTFAC': 0.70, 'RTNH4': 0.033, 'NMOBMX': 0.35, 'NVSMOB': 0.80, 'SENRTE': 2.50,
        'RTNO3': rtno3, 'FNPGN1': fn1, 'FNPGN2': fn2, 'LNREF': lnref, 'NSLOPE': 0.25,
        'EM-FL': max(float(param_map.get('EM-FL', 24.7)) + em_fl_delta, 15.0),
        'SHLAG': max(float(param_map.get('SHLAG', 18.0)) + shlag_delta, 10.0),
        'XFRT': 0.880 + xfrt_delta,
    })
    
    pd.DataFrame([{'name': k, 'value': v} for k, v in param_map.items()]).to_csv(run_path / 'params.csv', index=False)
    
    b25 = ROOT / f'data/user/experiments/xxql2501_page{page}_double_n_20260901'
    b26 = ROOT / f'data/user/experiments/xxql2601_page{page}_double_n_20260901'
    
    base_design_p = ROOT / 'workspace/reports/e02_v46_dias2026_double_n_20260831/design_all22_double_n.json'
    design = json.loads(base_design_p.read_text(encoding='utf-8'))
    design['design_id'] = f'ft_{case_name}'
    for s in design['seasons']:
        if s['season_id'] == '25SP': s['bundle_path'] = str(b25.resolve())
        elif s['season_id'] == '26SP': s['bundle_path'] = str(b26.resolve())
    (run_path / 'design.json').write_text(json.dumps(design, indent=2), encoding='utf-8')
    
    cmd = [
        sys.executable, str(ROOT / 'src/calibration/run_multiseason.py'),
        '--design', str(run_path / 'design.json'),
        '--param-csv', str(run_path / 'params.csv'),
        '--prefix', 'det', '--harvest-var', 'CHFPW',
    ]
    subprocess.run(cmd, cwd=str(run_path), capture_output=True, text=True)
    
    from src.reporting.analyze_results import deterministic_process_compare, deterministic_harvest_compare
    res = {'page': page, 'case': case_name, 'em_fl_delta': em_fl_delta, 'shlag_delta': shlag_delta, 'xfrt_delta': xfrt_delta}
    for sid, tns in [('25SP', [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]), ('26SP', list(range(1, 13)))]:
        sdir = run_path / '_seasons' / sid
        filex = next(sdir.glob('*.TMX'))
        batch = sdir / 'analysis_batch.v48'
        batch.write_text('\n'.join(f'{filex.resolve()} {tn} 1 0 0 0' for tn in tns) + '\n', encoding='utf-8')
        deterministic_process_compare(sid, str(batch), var_names=['L#SD', 'LAID', 'LWAD', 'SWAD', 'CHTD'], run_dir=str(sdir))
        deterministic_harvest_compare(sid, str(batch), run_dir=str(sdir))
        
        h = pd.read_csv(sdir / f'{sid}_deterministic_harvest_compare.csv')
        p = pd.read_csv(sdir / f'{sid}_deterministic_process_compare.csv')
        res[f'{sid}_fresh_cum_nse'] = signed_metric(h['OBS_FRESH_CUM'], h['SIM_FRESH_CUM'])
        res[f'{sid}_chtd_nse'] = signed_metric(p['OBS_CHTD'], p['SIM_CHTD'])
        res[f'{sid}_lai_nse'] = signed_metric(p['OBS_LAID'], p['SIM_LAID'])
        
    return res

results = []
for page in [25, 30]:
    for ef_d in [-6, -3, 0, +3]:
        for sh_d in [-6, -3, 0]:
            for xf_d in [-0.03, 0.0, +0.03]:
                r = run_test(page, ef_d, sh_d, xf_d)
                results.append(r)
                y25 = r['25SP_fresh_cum_nse']
                y26 = r['26SP_fresh_cum_nse']
                h25 = r['25SP_chtd_nse']
                h26 = r['26SP_chtd_nse']
                c_name = r['case']
                print(f'[PAGE {page}] {c_name} -> Y25:{y25:.3f}, Y26:{y26:.3f}, H25:{h25:.3f}, H26:{h26:.3f}', flush=True)

df = pd.DataFrame(results)
df.to_csv(OUT / 'page_fine_tuning_scorecard.csv', index=False)
print('\nTop 10 Fine-Tuned Configurations:')
df['score'] = df['25SP_fresh_cum_nse']*25 + df['26SP_fresh_cum_nse']*25 + df['25SP_chtd_nse']*25 + df['26SP_chtd_nse']*25
print(df.sort_values('score', ascending=False)[['page', 'case', '25SP_fresh_cum_nse', '26SP_fresh_cum_nse', '25SP_chtd_nse', '26SP_chtd_nse', 'score']].head(10).to_string(index=False))
