"""Verify exact direct-fit metrics, raw harvest mapping and frozen normalization."""
import numpy as np
import pandas as pd
import pytest
from src.calibration import rmse_joint as model
from tools.calibration.launch_rmse_joint_200x5_20261012 import make_targets, policy


def test_direct_catalog_excludes_gradient_and_double_terminal_dry_count():
    obs=make_targets()
    assert len(obs)==504 and not obs.variable.isin(model.GRADIENT_VARIABLES).any()
    dry=obs[obs.variable.eq('CHPDT')]
    assert len(dry)==45 and not dry.duplicated(['trno','date']).any()
    assert dry.family.eq('FINAL_DRY_YIELD').sum()==9
    fresh=obs[obs.variable.eq('CHFPW')]
    assert len(fresh)==9 and fresh.family.eq('FINAL_FRESH_YIELD').all()
    assert fresh.observed.min()==pytest.approx(51579.)
    assert fresh.observed.max()==pytest.approx(74314.8)


def test_pest_phi_is_exact_sum_of_declared_nrmse_squared_metrics():
    obs=make_targets()
    obs['simulated']=obs.observed+obs.fit_scale*.2
    groups=model.metrics(obs)
    # Every family has dimensionless RMSE .20, including anthesis RMSE/2d.
    assert groups.phi.sum()==pytest.approx(100*.2**2)
    for row in groups.itertuples():
        assert row.phi==pytest.approx(row.phi_budget*(row.rmse/row.fit_scale)**2)
    for _,q in obs.groupby('family'):
        assert q.final_weight.nunique()==1


def test_normalization_is_not_point_relative_or_candidate_dependent():
    obs=make_targets()
    q=obs[obs.family.eq('FINAL_FRESH_YIELD')]
    assert q.fit_scale.nunique()==1
    assert q.fit_scale.iloc[0]==pytest.approx(q.observed.mean())
    assert q.measurement_sigma_eff.nunique()>1
    changed=obs.copy()
    changed.loc[changed.family.eq('FINAL_FRESH_YIELD'),'final_weight']*=1.01
    with pytest.raises(ValueError,match='Weights do not implement'):
        model.validate_catalog(changed,policy())


def test_terminal_yield_budget_and_exact_sampling_scope():
    p=policy()
    assert p.phi_budget.sum()==100 and len(p)==14
    assert p[p.family.isin(['FINAL_DRY_YIELD','FINAL_FRESH_YIELD'])].phi_budget.sum()==40
    obs=make_targets()
    assert set(obs.dataset_role)=={'calibration'} and set(obs.trno)==set(range(4,13))
    n=obs[obs.variable.eq('FRUIT_N_PCT')]
    assert len(n)==27 and set(n.date)=={'2026-06-03','2026-06-24','2026-07-02'}
    assert obs[obs.variable.eq('WB100_INTERVAL')].shape[0]==18
