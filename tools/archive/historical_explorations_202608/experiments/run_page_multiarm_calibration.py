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

ANCHOR = (profile.BASE / 'best_member_71_params.csv').resolve()
OUT = (ROOT / 'workspace/reports/e02_page_multiarm_experiments_20260901').resolve()
SCRATCH = OUT / 'scratch_runs'
OUT.mkdir(parents=True, exist_ok=True)
SCRATCH.mkdir(parents=True, exist_ok=True)

N_PAIRS = profile.N_PAIRS
W_PAIRS = {
    '25SP': {'N0': (5, 13), 'N3': (2, 10)},
    '26SP': {'N0': (11, 12), 'N3': (2, 3)},
}

def signed_metric(obs: pd.Series, sim: pd.Series) -> float:
    o = pd.to_numeric(obs, errors='coerce').to_numpy(float)
    s = pd.to_numeric(sim, errors='coerce').to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s)
    o, s = o[ok], s[ok]
    if len(o) < 2:
        return float('nan')
    sst = float(np.square(o - o.mean()).sum())
    return 1.0 - float(np.square(s - o).sum()) / sst if sst > 0 else float('nan')

def run_arm_case(arm_name, page, case_name, changes):
    run_path = SCRATCH / f'{arm_name}_{case_name}'
    run_path.mkdir(parents=True, exist_ok=True)
    
    # Write params
    base_df = pd.read_csv(ANCHOR)
    param_map = base_df.set_index('name')['value'].to_dict()
    param_map.update(changes)
    param_csv = run_path / 'params.csv'
    pd.DataFrame([{'name': k, 'value': v} for k, v in param_map.items()]).to_csv(param_csv, index=False)
    
    # Setup design.json pointing to arm bundles
    b25 = ROOT / f'data/user/experiments/xxql2501_page{page}_double_n_20260901'
    b26 = ROOT / f'data/user/experiments/xxql2601_page{page}_double_n_20260901'
    
    base_design_p = ROOT / 'workspace/reports/e02_v46_dias2026_double_n_20260831/design_all22_double_n.json'
    design = json.loads(base_design_p.read_text(encoding='utf-8'))
    design['design_id'] = f'arm_{arm_name}_{case_name}'
    for s in design['seasons']:
        if s['season_id'] == '25SP':
            s['bundle_path'] = str(b25.resolve())
        elif s['season_id'] == '26SP':
            s['bundle_path'] = str(b26.resolve())
            
    design_file = run_path / 'design.json'
    design_file.write_text(json.dumps(design, indent=2), encoding='utf-8')
    
    cmd = [
        sys.executable,
        str(ROOT / 'src/calibration/run_multiseason.py'),
        '--design', str(design_file),
        '--param-csv', str(param_csv),
        '--prefix', 'det',
        '--harvest-var', 'CHFPW',
    ]
    res = subprocess.run(cmd, cwd=str(run_path), capture_output=True, text=True, encoding='utf-8', errors='replace')
    if res.returncode != 0:
        print(f'[ERROR] Simulation failed for {arm_name}/{case_name}: {res.stderr}')
        return None
        
    from src.reporting.analyze_results import deterministic_process_compare, deterministic_harvest_compare
    for sid, tns in [('25SP', [2, 3, 4, 5, 9, 10, 11, 12, 13, 14]), ('26SP', list(range(1, 13)))]:
        sdir = run_path / '_seasons' / sid
        filex = next(sdir.glob('*.TMX'))
        batch = sdir / 'analysis_batch.v48'
        batch.write_text(
            '\n'.join(f'{filex.resolve()} {int(tn)} 1 0 0 0' for tn in tns) + '\n',
            encoding='utf-8',
        )
        deterministic_process_compare(
            sid, str(batch),
            var_names=['L#SD', 'LAID', 'LWAD', 'SWAD', 'CHTD'],
            run_dir=str(sdir),
        )
        deterministic_harvest_compare(sid, str(batch), run_dir=str(sdir))
    return run_path

def response_records(h: pd.DataFrame, season: str, pairs: dict[str, dict[str, tuple[int, int]]]) -> list[dict[str, object]]:
    terminal = h.sort_values(['TN', 'DATE', 'HNO']).groupby('TN', as_index=False).tail(1).set_index('TN')
    records = []
    for level, water_pairs in pairs.items():
        for water, (hi, lo) in water_pairs.items():
            if hi in terminal.index and lo in terminal.index:
                records.append({
                    'season': season, 'level': level, 'water': water,
                    'obs': float(terminal.loc[hi, 'OBS_FRESH_CUM'] - terminal.loc[lo, 'OBS_FRESH_CUM']),
                    'sim': float(terminal.loc[hi, 'SIM_FRESH_CUM'] - terminal.loc[lo, 'SIM_FRESH_CUM']),
                })
    return records

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

base_pro = {
    'PROLFF': 0.105, 'PROLFG': 0.210, 'PROLFI': 0.260,
    'PROSTF': 0.060, 'PROSTG': 0.125, 'PROSTI': 0.200,
    'PRORTF': 0.050, 'PRORTG': 0.119, 'PRORTI': 0.150,
    'PROSHF': 0.105, 'PROSHG': 0.145, 'PROSHI': 0.205,
    'NSTFAC': 0.70, 'RTNH4': 0.033,
    'NMOBMX': 0.35, 'NVSMOB': 0.80, 'SENRTE': 2.50,
}

# Parameter grid exploring physiological adaptation under different seedling ages:
param_combos = {}
for rtno3 in [0.018, 0.024, 0.030]:
    for fn1 in [1.50, 1.80]:
        for fn2 in [4.50, 4.90]:
            for lnref in [4.00, 4.30]:
                for xfrt_delta in [-0.03, 0.0, +0.03]:
                    c_name = f'rt_{rtno3:.3f}_fn1_{fn1:.2f}_fn2_{fn2:.2f}_ln_{lnref:.2f}_dxfr_{xfrt_delta:+.2f}'
                    ch = dict(base_pro)
                    ch['RTNO3'] = rtno3
                    ch['FNPGN1'] = fn1
                    ch['FNPGN2'] = fn2
                    ch['LNREF'] = lnref
                    ch['NSLOPE'] = 0.25
                    ch['XFRT'] = 0.880 + xfrt_delta
                    param_combos[c_name] = ch

arms = {
    'Arm_PAGE25': 25,
    'Arm_PAGE30': 30,
    'Arm_PAGE60': 60,
}

def main():
    print(f'Starting Multi-Arm Experiment across {len(arms)} Arms ({len(param_combos)} parameter combos per arm)...')
    all_rows = []
    
    for arm_name, page in arms.items():
        print(f'\n========================================')
        print(f'Running {arm_name} (PAGE = {page})')
        print(f'========================================')
        
        for idx, (case_name, changes) in enumerate(param_combos.items(), 1):
            run_p = run_arm_case(arm_name, page, case_name, changes)
            if not run_p:
                continue
            res = {
                'arm': arm_name,
                'page': page,
                'case': case_name,
                **changes,
            }
            
            sdir25 = run_p / '_seasons/25SP'
            h25 = pd.read_csv(sdir25 / '25SP_deterministic_harvest_compare.csv')
            p25 = pd.read_csv(sdir25 / '25SP_deterministic_process_compare.csv')
            sdir26 = run_p / '_seasons/26SP'
            h26 = pd.read_csv(sdir26 / '26SP_deterministic_harvest_compare.csv')
            p26 = pd.read_csv(sdir26 / '26SP_deterministic_process_compare.csv')
            
            phi_dict = compute_relaxed_harvest_phi(h25, h26)
            res.update(phi_dict)
            
            n_records = []
            for sid, h, p in [('25SP', h25, p25), ('26SP', h26, p26)]:
                terminal = h.sort_values(['TN', 'DATE', 'HNO']).groupby('TN', as_index=False).tail(1)
                nrec = response_records(h, sid, N_PAIRS[sid])
                n_records.extend(nrec)
                
                # Metrics
                res[f'{sid}_fresh_cum_nse'] = signed_metric(h['OBS_FRESH_CUM'], h['SIM_FRESH_CUM'])
                res[f'{sid}_chtd_nse'] = signed_metric(p['OBS_CHTD'], p['SIM_CHTD'])
                res[f'{sid}_lai_nse'] = signed_metric(p['OBS_LAID'], p['SIM_LAID'])
                res[f'{sid}_lwad_nse'] = signed_metric(p['OBS_LWAD'], p['SIM_LWAD'])
                res[f'{sid}_swad_nse'] = signed_metric(p['OBS_SWAD'], p['SIM_SWAD'])
                
                # RMSE
                for var, df, o_col, s_col in [
                    ('fresh_cum', h, 'OBS_FRESH_CUM', 'SIM_FRESH_CUM'),
                    ('chtd', p, 'OBS_CHTD', 'SIM_CHTD'),
                    ('lai', p, 'OBS_LAID', 'SIM_LAID'),
                ]:
                    sub_ok = df.dropna(subset=[o_col, s_col])
                    sub_ok = sub_ok[(sub_ok[o_col] > -90) & (sub_ok[s_col] > -90)]
                    err = sub_ok[s_col].to_numpy() - sub_ok[o_col].to_numpy()
                    res[f'{sid}_{var}_rmse'] = float(np.sqrt(np.mean(err**2)))
                    
                obs_t = terminal['OBS_FRESH_CUM'].to_numpy(float)
                sim_t = terminal['SIM_FRESH_CUM'].to_numpy(float)
                res[f'{sid}_terminal_rrmse_pct'] = 100.0 * float(np.sqrt(np.mean(np.square(sim_t - obs_t)))) / float(np.mean(np.abs(obs_t)))
                res[f'{sid}_n_mean_abs_error'] = float(np.mean([abs(float(x['sim']) - float(x['obs'])) for x in nrec]))
                
            # Comprehensive fitness index combining Yield, CHTD, LAI, and Phi
            # CHTD weight: encourage positive NSE in both seasons
            res['composite_score'] = (
                res['25SP_fresh_cum_nse'] * 25.0
                + res['26SP_fresh_cum_nse'] * 25.0
                + max(res['25SP_chtd_nse'], -1.0) * 15.0
                + max(res['26SP_chtd_nse'], -1.0) * 15.0
                + max(res['25SP_lai_nse'], -1.0) * 10.0
                - (res['phi_harvest_total_relaxed'] / 50.0)
            )
            
            all_rows.append(res)
            pd.DataFrame(all_rows).to_csv(OUT / 'page_multiarm_results_raw.csv', index=False, encoding='utf-8-sig')
            
            phi_val = res['phi_harvest_total_relaxed']
            y25 = res['25SP_fresh_cum_nse']
            y26 = res['26SP_fresh_cum_nse']
            h25_nse = res['25SP_chtd_nse']
            h26_nse = res['26SP_chtd_nse']
            print(f'[{arm_name} {idx:02d}/{len(param_combos):02d}] {case_name} -> Y25:{y25:.3f}, Y26:{y26:.3f}, H25:{h25_nse:.3f}, H26:{h26_nse:.3f}, Phi:{phi_val:.1f}', flush=True)

    df = pd.DataFrame(all_rows)
    df.sort_values('composite_score', ascending=False).to_csv(OUT / 'page_multiarm_scorecard.csv', index=False, encoding='utf-8-sig')
    
    print('\n======================================================')
    print('PAGE MULTI-ARM EXPERIMENT SUMMARY (Top 5 per Arm)')
    print('======================================================')
    for arm_name in arms.keys():
        arm_sub = df[df['arm'] == arm_name].sort_values('composite_score', ascending=False).head(5)
        cols = ['arm', 'case', '25SP_fresh_cum_nse', '26SP_fresh_cum_nse', '25SP_chtd_nse', '26SP_chtd_nse', '25SP_lai_nse', 'phi_harvest_total_relaxed', 'composite_score']
        print(f'\n--- {arm_name} ---')
        print(arm_sub[cols].to_string(index=False))

if __name__ == '__main__':
    main()
