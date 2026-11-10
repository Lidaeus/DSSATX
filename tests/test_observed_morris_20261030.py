import json
from pathlib import Path

import pandas as pd
import pytest

from src.sensitivity.sa_build_sen_case import _write_params_csv_and_tpl
from src.sensitivity.strict_forward import validate_responses, read_genotype_parameters
from src.sensitivity.sa_model import derive_water_nitrogen_responses
from src.sensitivity.output_contract import load_output_contract, observation_names

ROOT = Path(__file__).resolve().parents[1]


def test_fixed_literal_is_written_but_not_templated(tmp_path):
    frame = pd.DataFrame([dict(name='LFMAX',init=1.8,status='active'),
                          dict(name='SASC_RATIO',init=.9,status='fixed'),
                          dict(name='UNUSED',init=123,status='disabled')])
    _write_params_csv_and_tpl(frame,tmp_path/'p.csv',tmp_path/'p.tpl')
    rows = pd.read_csv(tmp_path/'p.csv').set_index('name')
    assert rows.loc['SASC_RATIO','value'] == .9 and 'UNUSED' not in rows.index
    text = (tmp_path/'p.tpl').read_text()
    assert '~ LFMAX ~' in text and '~ SASC_RATIO ~' not in text


def test_strict_responses_reject_missing_but_allow_diagnostic_missing():
    contract = {'ranking_observations':['Y']}
    validate_responses({'Y':0.,'diagnostic':-99},contract)
    for values in ({},{'Y':-99},{'Y':float('nan')}):
        with pytest.raises(ValueError,match='Required sensitivity responses'):
            validate_responses(values,contract)


def test_signed_contrast_minus99_is_a_valid_difference():
    # Two valid native biomasses 5308 and 5407 produce exactly -99 kg/ha.
    contract={'ranking_observations':['WN_WATER_N2_AGB_END_CWAD']}
    validate_responses({'WN_WATER_N2_AGB_END_CWAD':5308.-5407.},contract)
    with pytest.raises(ValueError):validate_responses({},contract)


def test_nitrogen_slope_requires_every_approved_dose():
    profile = load_output_contract(ROOT/'configs/sa/eggplant_25sp_observed_expanded_morris_20261030_outputs.json')
    values = {f'TN{t}_{f}':1. for t in profile['treatments'] for f in profile['water_nitrogen_design']['contrast_features']}
    values.pop('TN4_LEAF_N_END')
    with pytest.raises(ValueError,match='Incomplete nitrogen dose series'):
        derive_water_nitrogen_responses(values,profile)


def test_expanded_profile_has_exact_partition_and_one_seed():
    p = ROOT/'configs/sa/eggplant_25sp_observed_expanded_morris_20261030_outputs.json'
    c = load_output_contract(p)
    assert len(observation_names(c))==226 and len(c['ranking_observations'])==170
    assert len(c['diagnostic_observations'])==56 and not c['cross_seed_analysis']
    assert c['random_seed']==20261030
    bad = json.loads(p.read_text(encoding='utf-8'))
    bad['diagnostic_observations'].append(bad['ranking_observations'][0])
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as d:
        dst = Path(d)/'bad.json';dst.write_text(json.dumps(bad),encoding='utf-8')
        with pytest.raises(ValueError,match='partition'):
            load_output_contract(dst)


def test_genotype_readback_covers_every_approved_parameter():
    actual = read_genotype_parameters(ROOT/'data/user/sa_bundles/xxql2501_sa_observed_final_20261105')
    bounds = pd.read_csv(ROOT/'data/parameter_registry/bounds_frozen/eggplant/eggplant_25sp_observed_morris_expanded86_20261030.csv')
    active = set(bounds.loc[bounds.status.eq('active'),'name'])
    assert len(active)==86 and active <= actual.keys()
    assert actual['SWBAR_REC']==.25 and actual['YSWBAR_MID']==1.
    assert actual['OPTLFP_FS']==.0022 and actual['PROLFI']==.270


def test_phosphorus_full_seed_injection_preserves_other_stages(tmp_path, monkeypatch):
    import shutil
    from src.dssat import run_dssat as runner
    source = ROOT/'data/user/sa_bundles/xxql2501_sa_observed_final_20261105/TMGRO048.SPE'
    shutil.copy2(source,tmp_path/'TMGRO048.SPE.base')
    shutil.copy2(source,tmp_path/'TMGRO048.SPE')
    pd.DataFrame([{'name':'OPTLFP_FS','value':.0034},
                  {'name':'OPTSTP_FS','value':.0031},
                  {'name':'OPTSDP_FS','value':.0056}]).to_csv(tmp_path/'params.csv',index=False)
    monkeypatch.chdir(tmp_path)
    runner.update_spe_file('params.csv')
    lines=(tmp_path/'TMGRO048.SPE').read_text().splitlines()
    values={prefix:next(line.split()[:3] for line in lines if prefix+'-EM' in line and not line.startswith('!'))
            for prefix in ['OPTLFP','OPTSTP','OPTSDP']}
    assert list(map(float,values['OPTLFP']))==[.0038,.0033,.0034]
    assert list(map(float,values['OPTSTP']))==[.0028,.0025,.0031]
    assert list(map(float,values['OPTSDP']))==[-99.,.0040,.0056]


def test_reference_photosynthesis_guard_covers_all_independent_samples():
    from src.sensitivity.strict_forward import validate_parameter_domain
    b=pd.DataFrame([dict(name='LNREF',lower=3.,upper=6.,status='active'),
                    dict(name='FNPGN1',lower=1.5,upper=3.5,status='active')])
    with pytest.raises(ValueError,match='lower\\(LNREF\\) > upper\\(FNPGN1\\)'):
        validate_parameter_domain(b)
    b.loc[b.name.eq('LNREF'),'lower']=3.6
    validate_parameter_domain(b)
