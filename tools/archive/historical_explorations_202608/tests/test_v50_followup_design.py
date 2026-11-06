import numpy as np
import pandas as pd
from tools.experiments import run_v50_mechanism_followup_20260902 as m


def test_plan_is_paired_and_bounded(monkeypatch):
    base = dict(icns_25sp=.53, icns_26sp=.72, fnpgn1=1.39, fnpgn2=2.79,
                nstfac=.157, rtno3=.017, xfrt=.85, slavr=200.)
    monkeypatch.setattr(m, "member", lambda *args: base.copy())
    monkeypatch.setattr(m, "anchor_values", lambda: base.copy())
    tasks = m.plan()
    assert len(tasks) == 20
    assert len({t['label'] for t in tasks}) == 20
    assert sum(t['kind'] == 'replay' for t in tasks) == 3
    for t in tasks:
        if t['kind'] == 'probe':
            assert set(t['changes']) <= {'nstfac', 'fnpgn1', 'fnpgn2', 'rtno3'}
            assert all(t['values'][k] == v for k, v in base.items() if k not in t['changes'])


def test_missing_lai_never_becomes_zero_or_imputed(tmp_path, monkeypatch):
    metadata = pd.DataFrame([
        dict(season_id='26SP', treatment=3*w+n, water_level=f'W{w+1}', nitrogen_level=f'N{n}')
        for w in range(3) for n in (1, 2, 3)
    ])
    meta_path = tmp_path / 'configs/runs/e02_mapping_26sp_w2_w1_20260830.csv'
    meta_path.parent.mkdir(parents=True)
    metadata.to_csv(meta_path, index=False)
    monkeypatch.setattr(m, 'ROOT', tmp_path)
    dest = tmp_path / 'result'
    season = dest / '_seasons/26SP'
    season.mkdir(parents=True)
    harvest, process = [], []
    for trno in metadata.treatment:
        harvest.append(dict(TN=trno, DATE=26198, OBS_FRESH_CUM=100+trno, SIM_FRESH_CUM=101+trno))
        process.extend([dict(TN=trno, DATE=26180, OBS_LAID=-99, SIM_LAID=3.),
                        dict(TN=trno, DATE=26198, OBS_LAID=trno/10, SIM_LAID=trno/9)])
    pd.DataFrame(harvest).to_csv(season / '26SP_deterministic_harvest_compare.csv', index=False)
    pd.DataFrame(process).to_csv(season / '26SP_deterministic_process_compare.csv', index=False)
    m.gradients(dest)
    excluded = pd.read_csv(dest / '26SP_gradient_exclusions.csv')
    gradients = pd.read_csv(dest / '26SP_nonN0_gradients.csv')
    assert len(excluded) == 3 and excluded.date.eq(26180).all()
    assert len(gradients) == 18
    assert gradients.date.eq(26198).all()
    assert np.isfinite(gradients[['observed', 'simulated', 'residual']]).all().all()
