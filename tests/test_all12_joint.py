"""All12 successor: target provenance, signed responses, and safe bounds."""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from src.calibration import all12_joint as model

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'configs/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012'
PARENT=ROOT/'configs/runs/eggplant_26sp_n012_robust_joint65_200x5_20261012'

def catalogs():
    return pd.read_csv(CONFIG/'calibration_observations.csv').fillna(''),pd.read_csv(CONFIG/'approved_objective_policy.csv')

def test_all12_budget_and_negative_response_preserved():
    obs,policy=catalogs();model.validate_catalog(obs,policy)
    old=pd.read_csv(PARENT/'approved_objective_policy.csv').set_index('family')
    new=policy.set_index('family')
    pd.testing.assert_series_equal(old.phi_budget,new.phi_budget)
    pd.testing.assert_series_equal(old.loss,new.loss)
    assert len(obs)==689 and set(obs.trno)==set(range(1,13))
    negative=obs[obs.variable.str.contains('CONTRAST')&obs.observed.lt(0)]
    assert len(negative)==3
    assert set(zip(negative.trno,negative.paired_trno))=={(1,3),(2,5),(1,4)}
    broken=obs.copy();broken.loc[negative.index[0],'observed']=abs(negative.iloc[0].observed)
    with pytest.raises(ValueError,match='primitive'):model.validate_catalog(broken,policy)

def test_existing_primitive_measurements_and_operators_unchanged():
    obs,_=catalogs();old=pd.read_csv(PARENT/'calibration_observations.csv').fillna('')
    columns=['trno','date','variable','depth_label','interval_start','interval_end']
    left=old[~old.variable.str.contains('CONTRAST')].set_index(columns).sort_index()
    right=obs[obs.trno.ge(4)&~obs.variable.str.contains('CONTRAST')].set_index(columns).sort_index()
    for col in ['observed','unit','observation_operator','dssat_layer_weights']:
        pd.testing.assert_series_equal(left[col],right[col],check_names=False)
    assert len(pd.read_csv(CONFIG/'locked_evaluation_observations.csv'))==1044
    assert '26SP' not in set(pd.read_csv(CONFIG/'locked_evaluation_observations.csv').season_id)

def test_rectangular_root_and_protein_bounds_and_original_FL_domain():
    d,b,obs=model.load_design(CONFIG/'design.json')
    b=b.set_index('name')
    assert b.loc['FRSTMF','upper']+b.loc['FRLFF','upper']<=1+1e-12
    for organ in ['LF','ST']:
        names=['PRO'+organ+x for x in ['F','G','I']]
        for a,c in zip(names,names[1:]):assert b.loc[a,'upper']<b.loc[c,'lower']
    assert tuple(b.loc['FL-LF',['lower','upper']])==(45,220)
    assert d['datasets'][2]['roles']=={'calibration':list(range(1,13))}
    encoded=pd.read_csv(ROOT/'workspace/runs'/d['design_id']/'preflight/seed_yield/last_comparison.csv')
    assert np.isclose(encoded.phi_contribution.sum(),model.metrics(model.encode(encoded)).phi.sum(),rtol=1e-12)
