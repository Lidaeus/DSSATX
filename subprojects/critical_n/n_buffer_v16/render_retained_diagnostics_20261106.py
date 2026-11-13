"""Adapt the V16 retained-reference replay to the November 6 diagnostic suite."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import json

import numpy as np
import pandas as pd

VERSION = Path(__file__).resolve().parent
ROOT = VERSION.parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration.single_season_n import read_native
from tools.reporting import report_dual_morris98_trial_20261105 as suite
from tools.reporting import report_rmse_joint65_20261012 as harvest

REPLAY = VERSION / 'evidence/diagnostic_replay_20261106'
REFERENCE = VERSION / 'evidence/unified_final_20261029/reference_selection.json'
FIGURES = ROOT / 'figture/n_buffer_v16_retained_interface_diagnostic_suite_20261106'
DATA = FIGURES / 'data'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def historical_progress(reference):
    history = Path(reference['original_parameter_source']).parent
    audit = read(history / 'final_audit.json')
    assert audit['success'] and audit['parameter_sha256'] == reference['parameter_sha256']
    run = read(history / 'run_manifest.json')
    design_path = Path(run['design'])
    assert suite.sha(design_path) == run['design_sha256']
    bounds = pd.read_csv(read(design_path)['bounds']).query('status == "active"').copy()
    bounds['native_name'] = bounds.name
    chosen = pd.read_csv(reference['original_parameter_source']).set_index('name').value
    bounds['selected'] = bounds.name.map(chosen)
    width = bounds.upper - bounds.lower
    bounds['position'] = (bounds.selected - bounds.lower) / width
    bounds['selected_near'] = bounds.position.le(.02) | bounds.position.ge(.98)
    rows, selected = [], []
    for i in range(run['iterations'] + 1):
        checkpoint = history / f'checkpoints/iteration_{i}.lineage.csv'
        lineage = pd.read_csv(checkpoint, float_precision='round_trip')
        phi = lineage.phi
        selected.extend((i, r.member) for r in lineage.itertuples() if r.trial == audit['best_source_trial'])
        rows.append(dict(iteration=i, retained=len(phi), passed=True, phi_min=phi.min(),
                         phi_median=phi.median(), phi_q25=phi.quantile(.25), phi_q75=phi.quantile(.75)))
        if i >= run['iterations'] - 1:
            vectors = []
            for row in lineage.itertuples():
                receipt = Path(row.trial) / 'receipt.json'
                assert suite.sha(receipt) == row.receipt_sha256
                vectors.append(read(receipt)['parameters'])
            positions = (pd.DataFrame(vectors)[bounds.name].to_numpy() - bounds.lower.to_numpy()) / width.to_numpy()
            for suffix, mask in [('near_lower', positions <= .02), ('near_upper', positions >= .98),
                                 ('severe_lower', positions <= .005), ('severe_upper', positions >= .995)]:
                bounds[f'r{i}_{suffix}'] = mask.mean(axis=0)
    (best_round, best_member), = selected
    status = dict(selected_iteration=best_round, selected_member=best_member,
                  selected_phi=audit['selected_replay_phi'], members=run['members'], retained=rows[-1]['retained'],
                  all_rounds_passed=True, scientific_status='calibration_fit', engineering_status='replay_verified',
                  phi_label='Original 100-member joint calibration Phi',
                  candidate_label='V16 retained interface',
                  diagnostic_footer=f"V16 retained interface | refreshed data replay Phi {reference['phi']:.6f}")
    return pd.DataFrame(rows), bounds, status, history


def replay_pairs(trial):
    target = pd.read_csv(trial / 'comparison.csv', float_precision='round_trip')
    diagnostic = pd.read_csv(trial / 'diagnostic_comparison.csv', float_precision='round_trip')
    variables = list(suite.UNITS)
    target = target[target.variable.isin(variables)].copy()
    diagnostic = diagnostic[diagnostic.variable.isin(variables)].copy()
    key = ['season_id', 'trno', 'date', 'variable']
    # VWC exists only among target rows, so retain all five depth-weighted pairs.
    target_keys = pd.MultiIndex.from_frame(target[key])
    extra = diagnostic[~pd.MultiIndex.from_frame(diagnostic[key]).isin(target_keys)]
    pairs = pd.concat([target, extra], ignore_index=True)
    pairs['unit'] = pairs.variable.map(suite.UNITS)
    pairs['role'] = pairs.dataset_role
    pairs['diagnostic_visit'] = (pairs.season_id.eq('26SP') & pairs.date.eq('2026-07-17') &
                                 pairs.variable.isin(['LEAF_N_PCT', 'STEM_N_PCT']))
    assert pairs.loc[pairs.diagnostic_visit, 'dataset_role'].eq('diagnostic').all()
    assert pairs.diagnostic_visit.sum() == 24
    metadata, pieces, frames = [], [], {}
    for season in ('25SP', '26SP'):
        work = trial / season
        meta = pd.read_csv(work / 'treatment_metadata.csv').assign(season_id=season, dataset_role='calibration')
        metadata.append(meta)
        frames[season] = {'FreshWt': read_native(work / 'FreshWt.OUT')}
        pg = read_native(work / 'PlantGro.OUT').reset_index()
        season_pairs = pairs[pairs.season_id.eq(season)].merge(pg[['trno', 'date', 'DAP']],
            on=['trno', 'date'], how='left', validate='many_to_one').rename(columns={'DAP': 'dap'})
        assert set(season_pairs.trno) == set(meta.treatment)
        season_pairs.loc[season_pairs.variable.eq('ADAP'), 'dap'] = season_pairs.loc[season_pairs.variable.eq('ADAP'), 'observed']
        pieces.append(season_pairs)
        folder = DATA / '_seasons' / season
        folder.mkdir(parents=True, exist_ok=True)
        for kind, names in [('process', dict(LAID='LAID', LWAD='LWAD', SWAD='SWAD', CHTD='CHTD')),
                            ('harvest', dict(CHPDT='DRY_CUM', CHFPW='FRESH_CUM', HPODW='DRY_INC', HFPOW='FRESH_INC'))]:
            q = season_pairs[season_pairs.variable.isin(names)].copy()
            assert q.comparison_status.eq('matched').all() and q.dap.notna().all()
            q['DATE'] = pd.to_datetime(q.date).dt.strftime('%y%j').astype(int)
            q['variable'] = q.variable.map(names)
            observed = q.pivot(index=['trno', 'DATE'], columns='variable', values='observed').add_prefix('OBS_')
            simulated = q.pivot(index=['trno', 'DATE'], columns='variable', values='simulated').add_prefix('SIM_')
            wide = observed.join(simulated).reset_index().rename(columns={'trno': 'TN'}).sort_values(['TN', 'DATE'])
            if kind == 'harvest':
                wide['HNO'] = wide.groupby('TN').cumcount() + 1
            wide.to_csv(folder / f'{season}_deterministic_{kind}_compare.csv', index=False)
    metadata = pd.concat(metadata, ignore_index=True)
    pairs = pd.concat(pieces, ignore_index=True).merge(
        metadata.drop(columns='dataset_role'), left_on=['season_id', 'trno'], right_on=['season_id', 'treatment'],
        validate='many_to_one')
    return pairs, metadata, frames


def main():
    reference = read(REFERENCE)
    receipt = read(REPLAY / 'last_success.json')
    trial = Path(receipt['trial'])
    assert receipt['success'] and receipt['phi'] == reference['phi']
    assert receipt['binary_sha256'] == reference['binary_sha256']
    assert suite.sha(reference['latest_design']) == receipt['design_sha256']
    assert suite.sha(REFERENCE.parent / 'retained_reference/best_parameters.csv') == reference['parameter_sha256']
    assert all(q['passed'] and q['over_capacity_records'] == 0 for q in receipt['physics'].values())
    previous = Path(reference['source_trial'])
    pd.testing.assert_frame_equal(pd.read_csv(previous / 'comparison.csv'), pd.read_csv(trial / 'comparison.csv'), check_exact=True)
    rounds, bounds, status, history = historical_progress(reference)
    pairs, metadata, frames = replay_pairs(trial)
    terminal = pairs[pairs.variable.isin(['CHFPW', 'CHPDT'])].sort_values('date').groupby(['season_id', 'trno', 'variable']).tail(1)
    assert terminal.groupby(['season_id', 'variable']).date.nunique().eq(1).all()
    tables = {'all_observed_simulated_pairs': pairs, 'treatment_metadata': metadata,
              'terminal_yield_pairs': terminal, 'terminal_yield_metrics': suite.summarize(terminal, ['season_id', 'role', 'variable', 'unit']),
              'variable_metrics': suite.summarize(pairs, ['season_id', 'role', 'variable', 'unit']),
              'signed_water_nitrogen_response': suite.signed_response(terminal),
              'iteration_statistics': rounds, 'parameter_boundary_audit': bounds}
    for name, frame in tables.items():
        frame.to_csv(DATA / f'{name}.csv', index=False)
    suite.RUN, suite.OUT, suite.FIG = REPLAY, DATA, FIGURES
    suite.NATIVE = {season: trial / season for season in frames}
    suite.render_trial(pairs, metadata, terminal, rounds, bounds, status)
    harvest.FIG = FIGURES
    for season in frames:
        for variable in ['CHFPW', 'CHPDT']:
            for smooth in [False, True]:
                harvest.plot_harvest_facets(pairs, frames, season, variable, smooth)
    manifest_path = FIGURES / 'diagnostic_manifest.json'
    manifest = read(manifest_path)
    manifest.update(model_rerun=True, replay_receipt=str(REPLAY / 'last_success.json'),
                    reference_selection=str(REFERENCE), selected_phi=receipt['phi'],
                    original_calibration_run=str(history), historical_phi=status['selected_phi'],
                    artifact_type='runtime_diagnostics',
                    cumulative_harvest='native steps, observed-date node lines and visual-only monotone PCHIP',
                    artifacts=[dict(path=p.relative_to(FIGURES).as_posix(), sha256=suite.sha(p))
                               for p in sorted(FIGURES.rglob('*')) if p.is_file() and p != manifest_path])
    manifest.pop('no_model_reruns', None)
    suite.write(manifest_path, manifest)
    print(tables['terminal_yield_metrics'].to_string(index=False), flush=True)


if __name__ == '__main__':
    main()
