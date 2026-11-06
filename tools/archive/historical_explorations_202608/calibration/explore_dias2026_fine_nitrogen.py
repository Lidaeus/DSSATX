from pathlib import Path
import json
import pandas as pd
import numpy as np
import subprocess
import sys

ROOT = Path('D:/Tomato_Cal')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.calibration.profile_v46_best71_nitrogen_20260831 as profile

ANCHOR = (profile.BASE / 'best_member_71_params.csv').resolve()
DESIGN = (profile.OUT / 'design_all22.json').resolve()
OUT = (ROOT / 'workspace/reports/e02_v46_dias2026_fine_20260831').resolve()
SCRATCH = OUT / 'scratch_runs'
OUT.mkdir(parents=True, exist_ok=True)
SCRATCH.mkdir(parents=True, exist_ok=True)

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
    base_design['design_id'] = f'det_dias_{case_name}'
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

N_PAIRS = profile.N_PAIRS
W_PAIRS = {
    '25SP': {'N0': (5, 13), 'N3': (2, 10)},
    '26SP': {'N0': (11, 12), 'N3': (2, 3)},
}

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

# Construct fine-grained exploration cases
dias_base = {
    'PROLFF': 0.105, 'PROLFG': 0.210, 'PROLFI': 0.260,
    'PROSTF': 0.060, 'PROSTG': 0.125, 'PROSTI': 0.200,
    'PRORTF': 0.050, 'PRORTG': 0.119, 'PRORTI': 0.150,
    'PROSHF': 0.105, 'PROSHG': 0.145, 'PROSHI': 0.205,
    'NSTFAC': 0.70, 'RTNH4': 0.033,
    'NMOBMX': 0.35, 'NVSMOB': 0.80, 'SENRTE': 2.50,
}

test_cases = {'baseline_best71': {}}

# Explore RTNO3 (0.018, 0.022, 0.025) x FNPGN1 (1.60, 1.80, 2.00) x FNPGN2 (4.40, 4.80, 5.20) x LNREF (3.8, 4.4) x NSLOPE (0.15, 0.25)
for rtno3 in [0.018, 0.022, 0.025]:
    for fn1 in [1.60, 1.80, 2.00]:
        for fn2 in [4.40, 4.80, 5.20]:
            for lnref in [3.81, 4.40]:
                for nslope in [0.15, 0.25]:
                    case = f'dias_rt_{rtno3:.3f}_fn1_{fn1:.2f}_fn2_{fn2:.2f}_ln_{lnref:.2f}_ns_{nslope:.2f}'
                    ch = dict(dias_base)
                    ch['RTNO3'] = rtno3
                    ch['FNPGN1'] = fn1
                    ch['FNPGN2'] = fn2
                    ch['LNREF'] = lnref
                    ch['NSLOPE'] = nslope
                    test_cases[case] = ch

print(f'Total fine cases to test: {len(test_cases)}')

mapping = pd.read_csv('configs/runs/e02_mapping_25sp_w3w1_26sp_w2w1_n2n0_20260830.csv')

rows = []
for idx, (case_name, changes) in enumerate(test_cases.items(), 1):
    run_p = run_case(case_name, changes)
    if not run_p:
        continue
    result = {'case': case_name, **changes, 'status': 'success'}
    n_records = []
    w_records = []
    for season in ('25SP', '26SP'):
        sdir = run_p / f'_seasons/{season}'
        h = pd.read_csv(sdir / f'{season}_deterministic_harvest_compare.csv')
        p = pd.read_csv(sdir / f'{season}_deterministic_process_compare.csv')
        terminal = h.sort_values(['TN', 'DATE', 'HNO']).groupby('TN', as_index=False).tail(1)
        nrec = response_records(h, season, N_PAIRS[season])
        wrec = water_records(h, season)
        n_records.extend(nrec)
        w_records.extend(wrec)
        result[f'{season}_fresh_cum_nse'] = signed_metric(h['OBS_FRESH_CUM'], h['SIM_FRESH_CUM'])
        result[f'{season}_lai_nse'] = signed_metric(p['OBS_LAID'], p['SIM_LAID'])
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
    pd.DataFrame(rows).to_csv(OUT / 'dias_fine_results.csv', index=False, encoding='utf-8-sig')
    print(f'[{idx:03d}/{len(test_cases):03d}] {case_name} -> 26SP N MAE: {result['26SP_n_mean_abs_error']:.1f}, 25SP: {result['25SP_n_mean_abs_error']:.1f}', flush=True)

df = pd.DataFrame(rows)
baseline = df.iloc[0]
for season in ('25SP', '26SP'):
    df[f'{season}_n_error_reduction_pct'] = 100.0 * (float(baseline[f'{season}_n_mean_abs_error']) - df[f'{season}_n_mean_abs_error'].astype(float)) / float(baseline[f'{season}_n_mean_abs_error'])
base_records = {
    (rec['season'], rec['level'], rec['water']): abs(float(rec['sim']) - float(rec['obs']))
    for rec in json.loads(baseline['n_records_json'])
}
improvements = []
for _, row in df.iterrows():
    improvements.append(sum(
        abs(float(rec['sim']) - float(rec['obs'])) < base_records[(rec['season'], rec['level'], rec['water'])]
        for rec in json.loads(row['n_records_json'])
        if (rec['season'], rec['level'], rec['water']) in base_records
    ))
df['n_response_layers_improved_vs_baseline'] = improvements
df['yield_guard_pass'] = (
    df['25SP_terminal_rrmse_pct'].astype(float).le(25.0)
    & df['26SP_terminal_rrmse_pct'].astype(float).le(25.0)
)
df['protected_fit_pass'] = (
    df['25SP_fresh_cum_nse'].astype(float).ge(float(baseline['25SP_fresh_cum_nse']) - 0.05)
    & df['26SP_fresh_cum_nse'].astype(float).ge(float(baseline['26SP_fresh_cum_nse']) - 0.05)
    & df['25SP_lai_nse'].astype(float).ge(float(baseline['25SP_lai_nse']) - 0.05)
    & df['26SP_lai_nse'].astype(float).ge(float(baseline['26SP_lai_nse']) - 0.05)
    & df['25SP_w_response_nse'].astype(float).ge(float(baseline['25SP_w_response_nse']) - 0.05)
    & df['26SP_w_response_nse'].astype(float).ge(float(baseline['26SP_w_response_nse']) - 0.05)
)
df['synergy_gate_pass'] = (
    df['25SP_n_direction_pass'].astype(bool)
    & df['26SP_n_error_reduction_pct'].astype(float).ge(30.0)
    & df['n_response_layers_improved_vs_baseline'].astype(int).ge(3)
    & df['yield_guard_pass']
    & df['protected_fit_pass']
)
df.sort_values(['synergy_gate_pass', '26SP_n_error_reduction_pct'], ascending=[False, False]).to_csv(OUT / 'dias_fine_scorecard.csv', index=False, encoding='utf-8-sig')
print('\nTop 15 Fine Dias Candidates:')
print(df[['case', '25SP_n_mean_abs_error', '26SP_n_mean_abs_error', '26SP_n_error_reduction_pct', 'n_response_layers_improved_vs_baseline', '25SP_fresh_cum_nse', '26SP_fresh_cum_nse', 'synergy_gate_pass']].head(15).to_string(index=False))
