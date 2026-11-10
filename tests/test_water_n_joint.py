"""Scientific operator and promotion contracts for the authorized joint run."""
import numpy as np
import pandas as pd
import pytest

from src.calibration import water_n_joint as model
from tools.calibration.launch_water_n_joint_20261012 import make_targets, REVIEW


def test_water_balance_morning_boundary_retains_sample_day_irrigation():
    soil=pd.DataFrame([
        dict(trno=4,date='2026-03-13',IRRC=0.,PREC=0.,ROFC=0.,DRNC=0.,SW1D=.20,SW2D=.30),
        dict(trno=4,date='2026-05-01',IRRC=118.,PREC=0.,ROFC=0.,DRNC=24.,SW1D=.22,SW2D=.28),
        dict(trno=4,date='2026-05-02',IRRC=145.,PREC=0.,ROFC=0.,DRNC=25.,SW1D=.25,SW2D=.31),
    ]).set_index(['trno','date'])
    value=model.water_balance100(soil,4,'2026-03-14','2026-05-02',[(0,40),(40,100)])
    # 118 - (8-12) = 122; neither endpoint-day extra irrigation nor 24 mm
    # unmeasured drainage is subtracted from the observational operator.
    assert value == pytest.approx(122.)


def test_catalog_exact_counts_budgets_and_original_sigmas():
    obs=make_targets()
    budgets=pd.read_csv(REVIEW/'objective_budget_review.csv').set_index('family')
    assert len(obs)==519 and obs.obsnme.is_unique
    assert budgets.phi_budget.sum()==100
    for family,q in obs.groupby('family'):
        assert len(q)==budgets.loc[family,'n_targets']
        assert np.square(q.final_weight*q.sigma_eff).sum()==pytest.approx(budgets.loc[family,'phi_budget'])
    assert obs.iloc[:492].original_weight.gt(0).all()
    assert obs.iloc[492:].original_weight.eq(0).all()
    wb=obs[obs.variable.eq('WB100_INTERVAL')]
    assert len(wb)==18 and set(wb.interval_start)=={'2026-03-14','2026-05-02'}
    assert set(obs.trno)==set(range(4,13))


def test_scientific_gate_rejects_wrong_or_weak_water_without_forward_failure():
    obs=make_targets()
    baseline=dict(original_phi=1e9,nonwater_phi=1e9,nrmse={v:1000. for v in model.PROTECTED})
    values=obs.observed.to_numpy().copy()
    assert model.candidate_gates(obs,values,baseline)['eligible']
    mask=obs.variable.eq('W_FRESH_CONTRAST').to_numpy()
    index=np.flatnonzero(mask)[0]
    values[index]=.24*obs.observed.iloc[index]
    gate=model.candidate_gates(obs,values,baseline)
    assert not gate['eligible'] and 'water_minimum_effect' in gate['failures']
    values[index]=-1.
    gate=model.candidate_gates(obs,values,baseline)
    assert 'water_direction' in gate['failures']
    assert 'W_FRESH_CONTRAST' in model.SIGNED


def test_donor_floor_validation_does_not_clip_values():
    bounds=pd.read_csv(REVIEW/'parameter_scope_review.csv').fillna('')
    values=dict(zip(bounds.name,bounds.init))
    model.validate_parameters(values,bounds)
    values['PROLFF']=.24
    values['PROLFG']=.23
    with pytest.raises(ValueError): model.validate_parameters(values,bounds)
    assert values['PROLFF']==.24
