"""Render the audited S4 optimum using the project's single-season suite."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'n_buffer_v16'))
from render_26sp_management_bundles import ROOT, read, read_pairs, render_suite, suite

RUN = ROOT / 'workspace/runs/v15_s4_nstate_26sp_50x3_20261109'
FIG = ROOT / 'figture/v15_s4_nstate_26sp_50x3_20261109_diagnostics'


def history(design, audit):
    bounds = pd.read_csv(design['bounds']).query('status == "active"').copy()
    bounds['native_name'] = bounds.name
    chosen = pd.read_csv(RUN / 'final/best_parameters.csv').set_index('name').value
    center = pd.read_csv(RUN / 'preflight/base/physical_parameters.csv').set_index('name').value
    bounds['selected'] = bounds.name.map(chosen)
    bounds['starting'] = bounds.name.map(center)
    width = bounds.upper - bounds.lower
    bounds['position'] = (bounds.selected - bounds.lower) / width
    bounds['selected_near'] = bounds.position.le(.02) | bounds.position.ge(.98)
    rows, selection = [], []
    for i in range(audit['actual_pest_updates'] + 1):
        lineage = pd.read_csv(RUN / f'checkpoints/iteration_{i}.lineage.csv')
        selection.extend((i, row.member) for row in lineage.itertuples() if row.trial == audit['best_source_trial'])
        phi = lineage.phi
        rows.append(dict(iteration=i, retained=len(phi), held=int(lineage.held.sum()), passed=True,
                         phi_min=phi.min(), phi_median=phi.median(), phi_q25=phi.quantile(.25), phi_q75=phi.quantile(.75)))
        if i < audit['actual_pest_updates'] - 1:
            continue
        columns = bounds.name.str.lower().tolist()
        ensemble = pd.read_csv(RUN / f'checkpoints/iteration_{i}.par.csv')[columns].to_numpy()
        position = (ensemble - bounds.lower.to_numpy()) / width.to_numpy()
        for suffix, mask in [('near_lower', position <= .02), ('near_upper', position >= .98),
                             ('severe_lower', position <= .005), ('severe_upper', position >= .995)]:
            bounds[f'r{i}_{suffix}'] = mask.mean(axis=0)
    assert selection, 'Selected evaluation must appear in the audited checkpoint lineage'
    iteration, member = selection[0]
    status = dict(selected_iteration=iteration, selected_member=member, selected_phi=audit['best_phi'],
                  members=50, retained=50, all_rounds_passed=True,
                  scientific_status='single_season_calibration_fit', engineering_status='replay_verified',
                  phi_label='26SP calibration Phi (593 targets)', candidate_label=f'S4 / update {iteration} {member}',
                  diagnostic_footer=f'S4 | 50 × 3 | best Phi {audit["best_phi"]:.4f} | verified replay')
    return pd.DataFrame(rows), bounds, status


def fit_metrics(frame):
    rows = []
    for family, group in frame.groupby('family'):
        kind = 'signed' if family.endswith('CONTRAST') else 'state'
        fit = suite.plots._metrics(group.observed, group.simulated, value_kind=kind)
        rows.append(dict(family=family, phi=group.phi_contribution.sum(),
                         bias=(group.simulated - group.observed).mean(), **fit))
    return pd.DataFrame(rows)


def plot_state(work, metadata, bundle):
    import matplotlib.pyplot as plt

    raw = pd.read_csv(work / 'NStatePsi.csv')
    assert set(raw.nstate_mode) == {2} and set(raw.trt) == set(metadata.treatment)
    np.testing.assert_array_equal(raw.psi_star, raw.psi_pub)
    np.testing.assert_array_equal(raw.psi_star, raw.uptake_psi)
    raw['date'] = pd.to_datetime(raw.yrdoy.astype(str), format='%Y%j')
    planting = pd.to_datetime(pd.read_csv(bundle / 'FileA_values.csv').PDAT.astype(int).astype(str), format='%y%j')
    assert planting.nunique() == 1
    raw['dap'] = (raw.date - planting.iloc[0]).dt.days
    raw = raw.merge(metadata, left_on='trt', right_on='treatment', validate='many_to_one')
    labels = ['W3_N3', 'W2_N2', 'W1_N0']
    fig, axes = plt.subplots(2, 3, figsize=(12, 6), sharex=True, sharey='row', layout='constrained')
    for j, label in enumerate(labels):
        q = raw[raw.treatment_label.eq(label)].sort_values('dap')
        assert len(q) > 100 and q.dap.max() == 125
        # The mode-2 ledger writes the fused state into both legacy psi fields.
        axes[0, j].plot(q.dap, q.psi_star, color='#176B87', lw=1.5)
        axes[1, j].plot(q.dap, q.nni_func, color='#176B87', lw=1.5)
        axes[0, j].axhline(0, color='.7', lw=.8, ls='--')
        axes[1, j].axhline(1, color='.7', lw=.8, ls='--')
        axes[0, j].set_title(label.replace('_', ' × '))
        axes[1, j].set(xlabel='Days after transplanting', xlim=(-1, 127))
        for ax in axes[:, j]:
            ax.grid(alpha=.2)
    axes[0, 0].set_ylabel('Fused plant N state (ψ*)')
    axes[1, 0].set_ylabel('Functional N nutrition index')
    fig.suptitle('S4 best-parameter replay | Root kernel 2, fused state, τ = 0')
    fig.savefig(FIG / 'diagnostic_s4_nitrogen_state.png', dpi=200, facecolor='white')
    plt.close(fig)
    raw.to_csv(FIG / 'data/nitrogen_state_daily.csv', index=False)


def main():
    audit_path = RUN / 'final/audit.json'
    audit = read(audit_path)
    run_manifest = read(RUN / 'run_manifest.json')
    design_path = Path(run_manifest['design'])
    assert suite.sha(design_path) == run_manifest['design_sha256']
    design = read(design_path)
    bundle = Path(design['management_bundle'])
    assert audit['completed'] and audit['exact_replay'] and audit['actual_pest_updates'] == 3
    replay = Path(audit['full_replay_trial'])
    work = replay / '26SP'
    assert read(replay / 'receipt.json')['phi'] == audit['best_phi']
    for name, digest in design['datasets'][0]['native_hashes'].items():
        if name in ('DSSBatch.v48', 'XXQL2601.TMX', 'XXQL2601.TMA', 'XXQL2601.TMT', 'XXTW2403.WTH', 'SOIL.SOL'):
            assert suite.sha(work / name) == digest
    assert suite.sha(bundle / 'input_manifest.json') == design['management_manifest_sha256']
    assert all(suite.sha(bundle / r['name']) == r['sha256'] for r in read(bundle / 'input_manifest.json')['files'])
    best = pd.read_csv(replay / 'comparison.csv', float_precision='round_trip')
    base_trial = Path(read(RUN / 'preflight/base/last_success.json')['trial'])
    base = pd.read_csv(base_trial / 'comparison.csv', float_precision='round_trip')
    pd.testing.assert_frame_equal(best[['obsnme', 'observed', 'final_weight', 'fit_scale']],
                                  base[['obsnme', 'observed', 'final_weight', 'fit_scale']], check_exact=True)
    pairs, metadata = read_pairs(work, bundle, 'calibration replay')
    rounds, bounds, status = history(design, audit)
    tables = render_suite(work, FIG, pairs, metadata, rounds, bounds, status)
    metrics = fit_metrics(base).merge(fit_metrics(best), on='family', suffixes=('_center', '_best'), validate='one_to_one')
    metrics.to_csv(FIG / 'data/objective_metrics_center_vs_best.csv', index=False)
    plot_state(work, metadata, bundle)
    manifest_path = FIG / 'diagnostic_manifest.json'
    manifest = read(manifest_path)
    manifest.update(artifact_type='runtime_diagnostics', best_phi=audit['best_phi'], actual_pest_updates=3,
                    calibration_audit=str(audit_path), calibration_audit_sha256=suite.sha(audit_path),
                    replay_trial=str(replay), bundle_manifest_sha256=design['management_manifest_sha256'],
                    state_ledger_note='Mode 2 writes identical values to psi_total and psi_star. The state plot uses psi_star.',
                    artifacts=[dict(path=p.relative_to(FIG).as_posix(), sha256=suite.sha(p))
                               for p in sorted(FIG.rglob('*')) if p.is_file() and p != manifest_path])
    suite.write(manifest_path, manifest)
    print(metrics[['family', 'n_best', 'RRMSE_center', 'RRMSE_best', 'R2_best', 'NSE_best', 'd_best']].to_string(index=False))
    print(tables['terminal_yield_metrics'].to_string(index=False))


if __name__ == '__main__':
    main()
