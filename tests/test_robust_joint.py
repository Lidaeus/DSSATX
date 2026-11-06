"""Scientific contract tests for the approved transformed joint objective."""
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import pytest
from src.calibration import robust_joint as model

ROOT=Path(__file__).resolve().parents[1]
REVIEW=ROOT/'configs/calibration_proposals/joint65_yield_robust_revision_20261012'

def catalogs():
    obs=pd.read_csv(REVIEW/'observation_catalog.csv').fillna('');obs['approved']=True
    policy=pd.read_csv(REVIEW/'objective_policy.csv');policy['approved']=True
    return obs,policy

def values():
    b=pd.read_csv(REVIEW/'bounds_proposal.csv').fillna('')
    b.loc[b.name=='FL-LF',['lower','upper']]=[45.,220.]
    return dict(zip(b.name,b.init)),b

def test_stable_pseudohuber_and_quadratic():
    r=np.array([-3.,-.15,-1.e-12,0.,1.e-12,.15,3.])
    z=model.loss_residual(r,'pseudo_huber')
    assert np.allclose(z,-model.loss_residual(-r,'pseudo_huber'))
    assert np.allclose(z*z,2*.15**2*(np.hypot(1,r/.15)-1),rtol=1e-12,atol=1e-15)
    assert np.isclose(z[4]/r[4],1.)
    assert np.array_equal(model.loss_residual(r,'quadratic'),r)
    assert abs(z[-1])<abs(r[-1])

def test_516_family_budget_and_contrast_primitive_identity():
    obs,policy=catalogs();model.validate_catalog(obs,policy)
    broken=obs.copy();i=broken.index[broken.family=='N_ADJACENT_SIGNED_CONTRAST'][0]
    broken.loc[i,'observed']+=100
    with pytest.raises(ValueError,match='primitive'):model.validate_catalog(broken,policy)

def test_encoding_closes_phi_without_changing_raw_measurements():
    comp=pd.read_csv(REVIEW/'seed_yield_objective_preflight.csv')
    original=comp[['observed','simulated']].copy();encoded=model.encode(comp)
    pd.testing.assert_frame_equal(original,encoded[['observed','simulated']])
    assert np.allclose(comp.pest_output,encoded.pest_output,rtol=1e-12,atol=1e-12)
    phi=float(encoded.phi_contribution.sum())
    assert np.isclose(phi,model.metrics(encoded).phi.sum(),rtol=1e-12)
    assert (encoded.pest_output<0).any()  # Signed outputs must not be rejected as nonphysical states.

def test_approved_FL_LF_endpoints_and_invalid_root_allocation():
    v,b=values()
    for fl in [45.,220.]:model.validate_parameters(v|{'FL-LF':fl},b)
    with pytest.raises(ValueError,match='outside'):model.validate_parameters(v|{'FL-LF':221.},b)
    with pytest.raises(ValueError,match='negative endpoint'):model.validate_parameters(v|{'FRSTMF':.9,'FRLFF':.2},b)

def test_unused_shell_placeholder_does_not_limit_actual_donor_floor():
    v,b=values();v['PROSHG']=.05
    model.check_relations(v)
    with pytest.raises(ValueError,match='Shell donor'):model.check_relations(v|{'PROSHF':v['PROSHI']+.01})

def test_failed_evaluation_removes_stale_objective(tmp_path):
    stale=tmp_path/'FormalObjectives.OUT';stale.write_text('old valid output')
    with patch.object(model,'load_design',side_effect=ValueError('bad frozen design')):
        with pytest.raises(ValueError):model.evaluate('invalid','invalid',tmp_path)
    assert not stale.exists()
