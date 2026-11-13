"""Render each management replay with the existing diagnostic-suite functions."""
import argparse
from pathlib import Path

import pandas as pd

from render_retained_diagnostics_20261106 import ROOT, REFERENCE, VERSION, harvest, historical_progress, read, suite
from src.calibration.sa98_joint40 import extract
from src.calibration.single_season_n import read_native
from tools.calibration import run_dual_morris98_trial_20261105 as trial


SEASON = '26SP'
WIDE_COLUMNS = {
    'process': {'LAID': 'LAID', 'LWAD': 'LWAD', 'SWAD': 'SWAD', 'CHTD': 'CHTD'},
    'harvest': {'CHPDT': 'DRY_CUM', 'CHFPW': 'FRESH_CUM', 'HPODW': 'DRY_INC', 'HFPOW': 'FRESH_INC'},
}


def write_wide(pairs, data):
    season_dir = data / '_seasons' / SEASON
    season_dir.mkdir(parents=True, exist_ok=True)
    for kind, variables in WIDE_COLUMNS.items():
        rows = pairs[pairs.variable.isin(variables)].copy()
        assert rows.comparison_status.eq('matched').all() and rows.dap.notna().all()
        rows['DATE'] = pd.to_datetime(rows.date).dt.strftime('%y%j').astype(int)
        rows['variable'] = rows.variable.map(variables)
        keys = ['trno', 'DATE']
        observed = rows.pivot(index=keys, columns='variable', values='observed').add_prefix('OBS_')
        simulated = rows.pivot(index=keys, columns='variable', values='simulated').add_prefix('SIM_')
        wide = observed.join(simulated).reset_index().rename(columns={'trno': 'TN'}).sort_values(['TN', 'DATE'])
        if kind == 'harvest':
            wide['HNO'] = wide.groupby('TN').cumcount() + 1
        wide.to_csv(season_dir / f'{SEASON}_deterministic_{kind}_compare.csv', index=False)


def read_pairs(work, bundle, season_role):
    metadata = pd.read_csv(bundle / 'treatment_metadata.csv').assign(season_id=SEASON, dataset_role=season_role)
    anthesis = pd.read_csv(bundle / 'FileA_values.csv').ADAT.astype(int).unique()
    observed_date, = pd.to_datetime(anthesis.astype(str), format='%y%j').strftime('%Y-%m-%d')
    saved_dates = trial.DATES
    try:
        trial.DATES = {**saved_dates, SEASON: observed_date}
        observations = trial.observation_catalog(bundle, SEASON).assign(role='diagnostic').fillna('')
    finally:
        trial.DATES = saved_dates
    pairs = extract(work, observations, strict=False)
    pairs['diagnostic_visit'] = pairs.date.eq('2026-07-17') & pairs.variable.isin(['LEAF_N_PCT', 'STEM_N_PCT'])
    assert pairs.diagnostic_visit.sum() == 24
    plantgro = read_native(work / 'PlantGro.OUT').reset_index()
    pairs = pairs.merge(plantgro[['trno', 'date', 'DAP']], on=['trno', 'date'], how='left',
                        validate='many_to_one').rename(columns={'DAP': 'dap'})
    pairs.loc[pairs.variable.eq('ADAP'), 'dap'] = pairs.loc[pairs.variable.eq('ADAP'), 'observed']
    pairs['unit'] = pairs.variable.map(suite.UNITS)
    pairs = pairs.merge(metadata, left_on=['season_id', 'trno'], right_on=['season_id', 'treatment'], validate='many_to_one')
    assert set(pairs.trno) == set(metadata.treatment) and pairs.unit.notna().all()
    return pairs, metadata


def render_suite(work, output, pairs, metadata, rounds, bounds, status):
    terminal = pairs[pairs.variable.isin(['CHFPW', 'CHPDT'])].sort_values('date').groupby(['trno', 'variable']).tail(1)
    assert len(terminal) == 24 and terminal.comparison_status.eq('matched').all()
    assert terminal.groupby('variable').date.nunique().eq(1).all()
    data = output / 'data'
    write_wide(pairs, data)
    tables = {'all_observed_simulated_pairs': pairs, 'treatment_metadata': metadata,
              'terminal_yield_pairs': terminal,
              'terminal_yield_metrics': suite.summarize(terminal, ['season_id', 'role', 'variable', 'unit']),
              'variable_metrics': suite.summarize(pairs, ['season_id', 'role', 'variable', 'unit']),
              'signed_water_nitrogen_response': suite.signed_response(terminal),
              'iteration_statistics': rounds, 'parameter_boundary_audit': bounds}
    for name, frame in tables.items():
        frame.to_csv(data / f'{name}.csv', index=False)
    suite.RUN, suite.OUT, suite.FIG, suite.NATIVE = work, data, output, {SEASON: work}
    suite.render_trial(pairs, metadata, terminal, rounds, bounds, status)
    harvest.FIG = output
    frames = {SEASON: {'FreshWt': read_native(work / 'FreshWt.OUT')}}
    for variable in ['CHFPW', 'CHPDT']:
        for smooth in [False, True]:
            harvest.plot_harvest_facets(pairs.rename(columns={'dataset_role': 'season_role'}).assign(dataset_role='diagnostic'),
                                        frames, SEASON, variable, smooth)
    return tables


def render(work, output):
    receipt_path = work / 'replay_receipt.json'
    receipt = read(receipt_path)
    bundle = Path(receipt['bundle'])
    assert receipt['success'] and receipt['physics']['passed']
    assert suite.sha(bundle / 'input_manifest.json') == receipt['bundle_manifest_sha256']
    assert all(suite.sha(bundle / row['name']) == row['sha256'] for row in read(bundle / 'input_manifest.json')['files'])
    assert all(suite.sha(work / name) == digest for name, digest in receipt['management_sha256'].items())
    assert suite.sha(work / 'parameters.csv') == receipt['parameter_sha256']
    pairs, metadata = read_pairs(work, bundle, 'fixed-parameter replay')
    assert set(pairs.trno) == set(receipt['treatments'])
    rounds, bounds, status, _ = historical_progress(read(REFERENCE))
    status.update(phi_label='Original two-spring calibration Phi', candidate_label=bundle.name,
                  diagnostic_footer=bundle.name, scientific_status='fixed_parameter_replay_diagnostic')
    tables = render_suite(work, output, pairs, metadata, rounds, bounds, status)
    manifest = read(output / 'diagnostic_manifest.json')
    manifest.pop('no_model_reruns', None)
    manifest.update(replay_receipt=str(receipt_path), replay_receipt_sha256=suite.sha(receipt_path),
                    original_calibration_history='100 members, 2 updates, historical objectives and physical bounds',
                    artifact_type='runtime_diagnostics',
                    artifacts=[dict(path=p.relative_to(output).as_posix(), sha256=suite.sha(p))
                               for p in sorted(output.rglob('*')) if p.is_file() and p.name != 'diagnostic_manifest.json'])
    suite.write(output / 'diagnostic_manifest.json', manifest)
    print(tables['terminal_yield_metrics'].to_string(index=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle_name')
    args = parser.parse_args()
    render(VERSION / 'evidence/management_bundle_replays' / args.bundle_name,
           ROOT / 'figture' / f'n_buffer_v16_{args.bundle_name}_diagnostics')
