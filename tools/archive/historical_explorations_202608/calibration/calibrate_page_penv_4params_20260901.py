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

RUN_NAME = 'e02_formal_v46_seedling_4param_cal_20260901'
RUN_DIR = ROOT / f'workspace/runs/{RUN_NAME}'
OUT_FIG = ROOT / f'figture/{RUN_NAME}'
REPORT_DIR = ROOT / f'workspace/reports/{RUN_NAME}'
SCRATCH = RUN_DIR / 'scratch_runs'

RUN_DIR.mkdir(parents=True, exist_ok=True)
OUT_FIG.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)
SCRATCH.mkdir(parents=True, exist_ok=True)

# 1. Base 0831 params
BASE_RUN_0831 = ROOT / 'workspace/runs/e02_formal_v46_dias2026_double_n_20260831'
champ_0831_csv = BASE_RUN_0831 / 'dias2026_double_n_champion_params.csv'
base_params_df = pd.read_csv(champ_0831_csv)
base_params_df.to_csv(RUN_DIR / 'base_params.csv', index=False)

# 2. Source bundles
src_b25 = ROOT / 'data/user/experiments/xxql2501_scheme4_double_n_20260831'
src_b26 = ROOT / 'data/user/experiments/xxql2601_page25_double_n_imputed_lai_20260901'

BASE_DESIGN_FILE = ROOT / 'workspace/reports/e02_v46_dias2026_double_n_20260831/design_all22_double_n.json'
base_design = json.loads(BASE_DESIGN_FILE.read_text(encoding='utf-8'))

def update_tmx_seedling(tmx_path: Path, pdate: str, plwt: str, page_val: int, penv_val: float):
    lines = tmx_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    new_lines = []
    in_p = False
    for l in lines:
        if l.startswith('*PLANTING DETAILS'):
            in_p = True
            new_lines.append(l)
        elif in_p and l.startswith('*'):
            in_p = False
            new_lines.append(l)
        elif in_p and l.startswith(f' 2 {pdate}'):
            new_l = f' 2 {pdate}   -99   2.7   2.7     T     R    90    90     8  {plwt}    {int(page_val):>2}    {int(round(penv_val)):>2}   -99   -99                        Eggplant'
            new_lines.append(new_l)
        else:
            new_lines.append(l)
    tmx_path.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')

def signed_metric(obs: pd.Series, sim: pd.Series) -> float:
    o = pd.to_numeric(obs, errors='coerce').to_numpy(float)
    s = pd.to_numeric(sim, errors='coerce').to_numpy(float)
    ok = np.isfinite(o) & np.isfinite(s) & (o > -90.0) & (s > -90.0)
    o, s = o[ok], s[ok]
    if len(o) < 2: return float('nan')
    sst = float(np.square(o - o.mean()).sum())
    return 1.0 - float(np.square(s - o).sum()) / sst if sst > 0 else float('nan')

def compute_0831_standard_phi(h25: pd.DataFrame, h26: pd.DataFrame, p25: pd.DataFrame, p26: pd.DataFrame) -> dict[str, float]:
    phi_inc_25 = 0.0
    for hno in range(1, 10):
        sub = h25[h25['HNO'] == hno]
        err = sub['SIM_FRESH_INC'] - sub['OBS_FRESH_INC']
        sigma = 400.0
        w = 0.3227 / sigma
        phi_inc_25 += float(np.sum((err * w)**2))
        
    phi_inc_26 = 0.0
    for hno in range(1, 6):
        sub = h26[h26['HNO'] == hno]
        err = sub['SIM_FRESH_INC'] - sub['OBS_FRESH_INC']
        sigma = 700.0
        w = 0.4330 / sigma
        phi_inc_26 += float(np.sum((err * w)**2))
        
    term25 = h25.sort_values(['TN', 'HNO']).groupby('TN').tail(1)
    err_term_25 = term25['SIM_FRESH_CUM'] - term25['OBS_FRESH_CUM']
    phi_term_25 = float(np.sum((err_term_25 * 0.000216)**2))
    
    term26 = h26.sort_values(['TN', 'HNO']).groupby('TN').tail(1)
    err_term_26 = term26['SIM_FRESH_CUM'] - term26['OBS_FRESH_CUM']
    phi_term_26 = float(np.sum((err_term_26 * 0.000205)**2))
    
    phi_proc_25 = 0.0
    for var, w_val in [('CHTD', 1.0), ('LAID', 0.8), ('LWAD', 0.002), ('SWAD', 0.002)]:
        sub = p25.dropna(subset=[f'OBS_{var}', f'SIM_{var}'])
        sub = sub[(sub[f'OBS_{var}'] > -90) & (sub[f'SIM_{var}'] > -90)]
        err = sub[f'SIM_{var}'] - sub[f'OBS_{var}']
        phi_proc_25 += float(np.sum((err * w_val)**2))
        
    phi_proc_26 = 0.0
    for var, w_val in [('CHTD', 1.0), ('LAID', 0.8), ('LWAD', 0.002), ('SWAD', 0.002)]:
        sub = p26.dropna(subset=[f'OBS_{var}', f'SIM_{var}'])
        sub = sub[(sub[f'OBS_{var}'] > -90) & (sub[f'SIM_{var}'] > -90)]
        err = sub[f'SIM_{var}'] - sub[f'OBS_{var}']
        phi_proc_26 += float(np.sum((err * w_val)**2))
        
    phi_total = phi_inc_25 + phi_inc_26 + phi_term_25 + phi_term_26 + phi_proc_25 + phi_proc_26
    return {
        'phi_inc_25': phi_inc_25, 'phi_inc_26': phi_inc_26,
        'phi_term_25': phi_term_25, 'phi_term_26': phi_term_26,
        'phi_proc_25': phi_proc_25, 'phi_proc_26': phi_proc_26,
        'phi_total_0831': phi_total,
    }

def run_seedling_combination(case_id, page25, penv25, page26, penv26):
    run_dir = SCRATCH / case_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    b25_c = run_dir / 'xxql2501'
    b26_c = run_dir / 'xxql2601'
    if b25_c.exists(): shutil.rmtree(b25_c)
    if b26_c.exists(): shutil.rmtree(b26_c)
    shutil.copytree(src_b25, b25_c)
    shutil.copytree(src_b26, b26_c)
    
    update_tmx_seedling(b25_c / 'XXQL2501.TMX', '25075', ' 9.5', page25, penv25)
    update_tmx_seedling(b26_c / 'XXQL2601.TMX', '26075', ' 9.4', page26, penv26)
    
    design = dict(base_design)
    design['design_id'] = f'cal_{case_id}'
    design['water_response_objective']['enabled'] = False
    design['nitrogen_response_objective']['enabled'] = False
    for s in design['seasons']:
        if s['season_id'] == '25SP': s['bundle_path'] = str(b25_c.resolve())
        elif s['season_id'] == '26SP': s['bundle_path'] = str(b26_c.resolve())
    (run_dir / 'design.json').write_text(json.dumps(design, indent=2), encoding='utf-8')
    
    cmd = [
        sys.executable, str(ROOT / 'src/calibration/run_multiseason.py'),
        '--design', str(run_dir / 'design.json'),
        '--param-csv', str(RUN_DIR / 'base_params.csv'),
        '--prefix', 'det', '--harvest-var', 'CHFPW',
    ]
    res = subprocess.run(cmd, cwd=str(run_dir), capture_output=True, text=True)
    if res.returncode != 0:
        return None
        
    from src.reporting.analyze_results import deterministic_process_compare, deterministic_harvest_compare
    out_row = {'case_id': case_id, 'PAGE_25SP': page25, 'PENV_25SP': penv25, 'PAGE_26SP': page26, 'PENV_26SP': penv26}
    
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

    phi_dict = compute_0831_standard_phi(h25, h26, p25, p26)
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

    out_row['objective_score'] = (
        out_row['25SP_fresh_cum_nse'] * 25.0
        + out_row['26SP_fresh_cum_nse'] * 25.0
        + max(out_row['25SP_chtd_nse'], -1.0) * 20.0
        + max(out_row['26SP_chtd_nse'], -1.0) * 20.0
        + max(out_row['25SP_lai_nse'], -1.0) * 15.0
        + max(out_row['26SP_lai_nse'], -1.0) * 15.0
        - (out_row['phi_total_0831'] / 100.0)
    )
    return out_row

def main():
    print('1. Stage 1: Coarse Grid Scan for 4 Seedling Parameters (PAGE: 24..60, PENV: 8..20)...')
    coarse_grid = []
    for p25 in [24, 28, 34, 42, 50, 60]:
        for e25 in [8, 12, 16, 20]:
            for p26 in [24, 28, 34, 42, 50, 60]:
                for e26 in [8, 12, 16, 20]:
                    cid = f'p25_{p25}_e25_{e25}_p26_{p26}_e26_{e26}'
                    coarse_grid.append((cid, p25, e25, p26, e26))

    print(f'Total coarse combinations: {len(coarse_grid)}. Running evaluation...')
    results = []
    for idx, (cid, p25, e25, p26, e26) in enumerate(coarse_grid, 1):
        r = run_seedling_combination(cid, p25, e25, p26, e26)
        if r:
            results.append(r)
            if idx % 100 == 0 or idx == len(coarse_grid):
                top_s = max(x['objective_score'] for x in results)
                print(f'[{idx:04d}/{len(coarse_grid):04d}] Done. Top score so far: {top_s:.2f}', flush=True)

    df_c = pd.DataFrame(results)
    top_coarse = df_c.sort_values('objective_score', ascending=False).head(5)
    print('\nTop 5 Coarse Candidates:')
    print(top_coarse[['case_id', 'PAGE_25SP', 'PENV_25SP', 'PAGE_26SP', 'PENV_26SP', '25SP_fresh_cum_nse', '26SP_fresh_cum_nse', '25SP_chtd_nse', '26SP_chtd_nse', 'objective_score']].to_string(index=False))

    best_p25 = int(top_coarse.iloc[0]['PAGE_25SP'])
    best_e25 = int(top_coarse.iloc[0]['PENV_25SP'])
    best_p26 = int(top_coarse.iloc[0]['PAGE_26SP'])
    best_e26 = int(top_coarse.iloc[0]['PENV_26SP'])

    print(f'\n2. Stage 2: Fine Grid Zoom around (p25={best_p25}, e25={best_e25}, p26={best_p26}, e26={best_e26})...')
    fine_grid = []
    p25_range = sorted(list(set(np.clip([best_p25 - 4, best_p25 - 2, best_p25, best_p25 + 2, best_p25 + 4], 24, 60))))
    e25_range = sorted(list(set(np.clip([best_e25 - 3, best_e25 - 1, best_e25, best_e25 + 1, best_e25 + 3], 8, 20))))
    p26_range = sorted(list(set(np.clip([best_p26 - 4, best_p26 - 2, best_p26, best_p26 + 2, best_p26 + 4], 24, 60))))
    e26_range = sorted(list(set(np.clip([best_e26 - 3, best_e26 - 1, best_e26, best_e26 + 1, best_e26 + 3], 8, 20))))

    for p25 in p25_range:
        for e25 in e25_range:
            for p26 in p26_range:
                for e26 in e26_range:
                    cid = f'fine_p25_{p25}_e25_{e25}_p26_{p26}_e26_{e26}'
                    fine_grid.append((cid, p25, e25, p26, e26))

    print(f'Total fine combinations: {len(fine_grid)}. Running fine search...')
    for idx, (cid, p25, e25, p26, e26) in enumerate(fine_grid, 1):
        r = run_seedling_combination(cid, p25, e25, p26, e26)
        if r:
            results.append(r)

    df_all = pd.DataFrame(results)
    df_all.sort_values('objective_score', ascending=False).to_csv(REPORT_DIR / 'seedling_4param_calibration_scorecard.csv', index=False)

    champion = df_all.sort_values('objective_score', ascending=False).iloc[0]
    champ_p25 = int(champion['PAGE_25SP'])
    champ_e25 = int(champion['PENV_25SP'])
    champ_p26 = int(champion['PAGE_26SP'])
    champ_e26 = int(champion['PENV_26SP'])

    print('\n======================================================')
    print('4-PARAMETER SEEDLING CALIBRATION COMPLETED!')
    print(f'Champion Case: {champion["case_id"]}')
    print(f'25SP Seedling: PAGE = {champ_p25} days, PENV = {champ_e25} degC')
    print(f'26SP Seedling: PAGE = {champ_p26} days, PENV = {champ_e26} degC')
    print(f'25SP: Fresh Yield NSE={champion["25SP_fresh_cum_nse"]:.3f} (RMSE={champion["25SP_fresh_cum_rmse"]:6.1f}), CHTD NSE={champion["25SP_chtd_nse"]:.3f} (RMSE={champion["25SP_chtd_rmse"]:.2f}), LAI NSE={champion["25SP_lai_nse"]:.3f}')
    print(f'26SP: Fresh Yield NSE={champion["26SP_fresh_cum_nse"]:.3f} (RMSE={champion["26SP_fresh_cum_rmse"]:6.1f}), CHTD NSE={champion["26SP_chtd_nse"]:.3f} (RMSE={champion["26SP_chtd_rmse"]:.2f}), LAI NSE={champion["26SP_lai_nse"]:.3f}')
    print(f'Total Phi: {champion["phi_total_0831"]:.2f}, Composite Score: {champion["objective_score"]:.3f}')
    print('======================================================')

    final_b25 = ROOT / f'data/user/experiments/xxql2501_page{champ_p25}_penv{champ_e25}_double_n_20260901'
    final_b26 = ROOT / f'data/user/experiments/xxql2601_page{champ_p26}_penv{champ_e26}_double_n_imputed_lai_20260901'
    if final_b25.exists(): shutil.rmtree(final_b25)
    if final_b26.exists(): shutil.rmtree(final_b26)
    shutil.copytree(src_b25, final_b25)
    shutil.copytree(src_b26, final_b26)
    update_tmx_seedling(final_b25 / 'XXQL2501.TMX', '25075', ' 9.5', champ_p25, champ_e25)
    update_tmx_seedling(final_b26 / 'XXQL2601.TMX', '26075', ' 9.4', champ_p26, champ_e26)
    print(f'Exported calibrated season bundles:\n  -> {final_b25.name}\n  -> {final_b26.name}')

if __name__ == '__main__':
    main()
