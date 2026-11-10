"""Critical scientific contracts for the approved40 runtime."""
import numpy as np
import pandas as pd
import pytest

from src.calibration.sa98_joint40 import encode, expected_filex, read_anthesis, check_water_geometry


def test_objective_encodes_sigma_once_and_keeps_signed_residual():
    d=pd.DataFrame(dict(observed=[10.,10.,10.],simulated=[14.,6.,14.],sigma_eff=[2.,2.,2.],
                        loss=['quadratic','pseudo_huber','pseudo_huber'],huber_delta=['',1.5,1.5],budget_multiplier=[.5,.5,.5]))
    out=encode(d)
    assert out.phi_contribution.iloc[0]==pytest.approx(1.)
    expected=.25*2*1.5**2*(np.sqrt(1+(2/1.5)**2)-1)
    assert out.phi_contribution.iloc[1]==pytest.approx(expected)
    assert out.pest_output.iloc[1]==pytest.approx(-out.pest_output.iloc[2])


def test_sasc_changes_only_declared_layer_field():
    raw='*SOIL ANALYSIS\n@A SABL SADM SAOC SANI SAPHW SAPHB SAPX SAKE SASC\n'
    layer=' 1     2  1.36  1.05 0.132  7.78   -99 103.0   1.4   -99\n'
    after=expected_filex(raw+layer+'*OTHER\n',.9)
    assert after.splitlines()[2][:51]==layer[:51]
    assert float(after.splitlines()[2][51:])==pytest.approx(.95)
    assert after.endswith('*OTHER\n')


def test_anthesis_supports_locked2025_validation_without_hardcoded2026(tmp_path):
    p=tmp_path/'Evaluate.OUT';p.write_text('@RUN EXCODE TN ADAPS\n1 XXQL2501 2 37\n')
    assert read_anthesis(p)=={2:37.}


def test_water_mapping_uses_native_regridded_layers(tmp_path):
    (tmp_path/'SoilWat.OUT').write_text('! 0-5 5-15 15-30 30-40\n')
    q=pd.DataFrame(dict(variable=['VWC'],depth_top_cm=[0],depth_bottom_cm=[20],dssat_layer_weights=['0:0.25;1:0.50;2:0.25']))
    check_water_geometry(tmp_path,q)
    q.loc[0,'dssat_layer_weights']='0:0.1;1:0.1;2:0.55;3:0.25'
    with pytest.raises(ValueError,match='mapping'):check_water_geometry(tmp_path,q)
