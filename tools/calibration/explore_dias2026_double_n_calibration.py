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
OUT = (ROOT / 'workspace/reports/e02_v46_dias2026_double_n_20260831').resolve()
DESIGN = (OUT / 'design_all22_double_n.json').resolve()
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

def run_case(case_name, changes):
    run_path = SCRATCH / case_name
    run_path.mkdir(parents=True, exist_ok=True)
    
    base_df = pd.read_csv(ANCHOR)
    param_map = base_df.set_index('name')['value'].to_dict()
    param_map.update(changes)
    param_csv = run_path / 'params.csv'
    pd.DataFrame([{'name': k, 'value': v} for k, v in param_map.items()]).to_csv(param_csv, index=False)
    
    base_design = json.loads(DESIGN.read_text(encoding='utf-8'))
    base_design['design_id'] = f'det_dn_{case_name}'
    design_file = run_path / 'design.json'
    design_file.write_text(json.dumps(base_design, indent=2), encoding='utf-8')
    
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
        print(f'[ERROR] Simulation failed for {case_name}: {res.stderr}')
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

def water_records(h: pd.DataFrame, season: str) -> list[dict[str, object]]:
    terminal = h.sort_values(['TN', 'DATE', 'HNO']).groupby('TN', as_index=False).tail(1).set_index('TN')
    records = []
    for level, (hi, lo) in W_PAIRS[season].items():
        if hi in terminal.index and lo in terminal.index:
            records.append({
                'season': season, 'level': level,
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

cases = {'baseline_best71_double_n': {}}

# Systematic search space adapted for doubled initial soil N:
# With doubled initial N, root uptake rate (RTNO3) and leaf photosynthesis threshold (FNPGN1/2, LNREF)
# may shift to accommodate higher baseline mineral nitrogen supply.
for rtno3 in [0.018, 0.022, 0.026, 0.030]:
    for fn1 in [1.40, 1.60, 1.80]:
        for fn2 in [4.30, 4.60, 4.90]:
            for lnref in [4.00, 4.30]:
                for xfrt_delta in [-0.03, 0.0, +0.03]:
                    case = f'dn_rt_{rtno3:.3f}_fn1_{fn1:.2f}_fn2_{fn2:.2f}_ln_{lnref:.2f}_dxfr_{xfrt_delta:+.2f}'
                    ch = dict(base_pro)
                    ch['RTNO3'] = rtno3
                    ch['FNPGN1'] = fn1
                    ch['FNPGN2'] = fn2
                    ch['LNREF'] = lnref
                    ch['NSLOPE'] = 0.25
                    ch['XFRT'] = 0.880 + xfrt_delta
                    cases[case] = ch

def main():
    print(f'Total doubled-N calibration cases to test: {len(cases)}')
    rows = []
    for idx, (case_name, changes) in enumerate(cases.items(), 1):
        run_p = run_case(case_name, changes)
        if not run_p:
            continue
        result = {'case': case_name, **changes, 'status': 'success'}
        n_records = []
        w_records = []
        sdir25 = run_p / '_seasons/25SP'
        h25 = pd.read_csv(sdir25 / '25SP_deterministic_harvest_compare.csv')
        p25 = pd.read_csv(sdir25 / '25SP_deterministic_process_compare.csv')
        sdir26 = run_p / '_seasons/26SP'
        h26 = pd.read_csv(sdir26 / '26SP_deterministic_harvest_compare.csv')
        p26 = pd.read_csv(sdir26 / '26SP_deterministic_process_compare.csv')
        
        phi_dict = compute_relaxed_harvest_phi(h25, h26)
        result.update(phi_dict)
        
        for season, h, p in [('25SP', h25, p25), ('26SP', h26, p26)]:
            terminal = h.sort_values(['TN', 'DATE', 'HNO']).groupby('TN', as_index=False).tail(1)
            nrec = response_records(h, season, N_PAIRS[season])
            wrec = water_records(h, season)
            n_records.extend(nrec)
            w_records.extend(wrec)
            result[f'{season}_fresh_cum_nse'] = signed_metric(h['OBS_FRESH_CUM'], h['SIM_FRESH_CUM'])
            result[f'{season}_lai_nse'] = signed_metric(p['OBS_LAID'], p['SIM_LAID'])
            result[f'{season}_lwad_nse'] = signed_metric(p['OBS_LWAD'], p['SIM_LWAD'])
            obs = terminal['OBS_FRESH_CUM'].to_numpy(float)
            sim = terminal['SIM_FRESH_CUM'].to_numpy(float)
            result[f'{season}_terminal_rrmse_pct'] = 100.0 * float(np.sqrt(np.mean(np.square(sim - obs)))) / float(np.mean(np.abs(obs)))
            result[f'{season}_terminal_pbias_pct'] = 100.0 * float(np.sum(sim - obs)) / float(np.sum(obs))
            result[f'{season}_n_mean_abs_error'] = float(np.mean([abs(float(x['sim']) - float(x['obs'])) for x in nrec]))
            result[f'{season}_n_direction_pass'] = bool(
                all(np.mean([float(x['sim']) for x in nrec if x['level'] == level]) > 0 for level in ('N1', 'N2'))
            )
            result[f'{season}_w_response_nse'] = signed_metric(
                pd.Series([x['obs'] for x in wrec]), pd.Series([x['sim'] for x in wrec])
            )
            
        result['n_records_json'] = json.dumps(n_records, ensure_ascii=False)
        result['w_records_json'] = json.dumps(w_records, ensure_ascii=False)
        rows.append(result)
        pd.DataFrame(rows).to_csv(OUT / 'dias_double_n_results.csv', index=False, encoding='utf-8-sig')
        phi_val = result['phi_harvest_total_relaxed']
        mae26 = result['26SP_n_mean_abs_error']
        mae25 = result['25SP_n_mean_abs_error']
        print(f'[{idx:03d}/{len(cases):03d}] {case_name} -> Phi_rel: {phi_val:.2f}, 26SP N MAE: {mae26:.1f}, 25SP: {mae25:.1f}', flush=True)

    df = pd.DataFrame(rows)
    baseline = df.iloc[0]
    df.sort_values(['phi_harvest_total_relaxed', '26SP_n_mean_abs_error'], ascending=[True, True]).to_csv(OUT / 'dias_double_n_scorecard.csv', index=False, encoding='utf-8-sig')
    print('\nTop 15 Doubled-N Calibration Candidates (Sorted by Relaxed Phi):')
    print(df[['case', 'phi_harvest_total_relaxed', '25SP_fresh_cum_nse', '26SP_fresh_cum_nse', '25SP_n_mean_abs_error', '26SP_n_mean_abs_error']].head(15).to_string(index=False))

if __name__ == '__main__':
    main()
