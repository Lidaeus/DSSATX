"""Custom engine69 contract: provenance, fixed-width values, F1 safety, no fallback."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest
from src.calibration import cnc_joint_20261014 as model

def params():
    d,b,o=model.load_design(model.CONFIG/'design.json')
    return dict(zip(b.name,b.init)),b

def test_parent_objective_and_original65_ranges_unchanged():
    d,b,o=model.load_design(model.CONFIG/'design.json')
    parent=model.ROOT/'configs/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012'
    pd.testing.assert_frame_equal(pd.read_csv(parent/'calibration_observations.csv'),o.replace('',np.nan),check_dtype=False)
    pd.testing.assert_frame_equal(pd.read_csv(parent/'approved_objective_policy.csv'),pd.read_csv(model.CONFIG/'approved_objective_policy.csv'))
    old=json.loads((parent/'design.json').read_text())
    prior=pd.read_csv(model.ROOT/'data/parameter_registry/bounds_frozen/eggplant'/(old['bounds_id']+'.csv')).set_index('name')
    pd.testing.assert_frame_equal(prior[['lower','upper','status']],b.set_index('name').loc[prior.index,['lower','upper','status']])
    assert len(b[b.status=='active'])==69 and len(o)==689

def test_four_CNC_fields_written_and_read_independently(tmp_path):
    (tmp_path/'TMGRO048.SPE').write_text('!*CRITICAL NITROGEN DILUTION PARAMETERS\n@ CNC_A CNC_B CNC_W0 CNC_NC_INF\n  4.85  0.38  1.00  1.70\n\n!*NEXT\n')
    values=dict(CNC_A=4.23741,CNC_B=.32681,CNC_W0=1.37891,CNC_NC_INF=1.95678)
    actual=model.inject_cnc_fields(tmp_path,values)
    for key,(val,resolution) in actual.items():assert abs(val-values[key])<=resolution/2+1e-9
    assert len((tmp_path/'TMGRO048.SPE').read_text().splitlines()[2][:24])==24
    assert len(actual)==4

def test_F1_guards_respect_custom_caps():
    v,b=params();model.validate_parameters(v,b)
    with pytest.raises(ValueError,match='leaf demand cap'):model.validate_parameters(v|{'PROLFG':.270,'PROLFI':.275},b)
    with pytest.raises(ValueError,match='stem demand cap'):model.validate_parameters(v|{'PROSTG':.143,'PROSTI':.145},b)
    with pytest.raises(ValueError,match='curve ordering'):model.check_relations(v|{'CNC_A':1.5,'CNC_NC_INF':1.7})

def test_engine_mismatch_fails_without_native_fallback(tmp_path,monkeypatch):
    fake=tmp_path/'fake.exe';fake.write_bytes(b'not the authorized custom DSSAT')
    monkeypatch.setattr(model,'ENGINE',fake)
    with pytest.raises(ValueError,match='Pinned custom binary changed'):model.simulate(tmp_path/'work',{},[],{})
    assert not (tmp_path/'work').exists()

def test_balance_audit_uses_actual_treatment_ID_and_both_daily_cumulative(tmp_path):
    (tmp_path/'PlantNBal.OUT').write_text(' TREATMENT 5 : sample\n   TOTAL N 100.00\n   TOTAL N 100.04\n')
    soil='*RUN 1\n TREATMENT 5 : sample\n@YEAR DOY DAS DBAL CBAL\n 2026 198 1 0.0001 0.0002\n'
    (tmp_path/'SoilNiBal.OUT').write_text(soil)
    records=model.audit_mass_balance(tmp_path,[5]);assert records[0]['trno']==5
    (tmp_path/'SoilNiBal.OUT').write_text(soil.replace('0.0001','0.0600'))
    with pytest.raises(ValueError,match='mass balance failed'):model.audit_mass_balance(tmp_path,[5])
