"""Contracts for the 2025-only sensitivity input deliverables."""
import json
from pathlib import Path

import pytest

from src.common.experiment_inputs import parse_filex, filex_section_text
from src.common.input_manifest import verify_manifest_integrity, verify_calibrated_input_bundle, InputUseProhibitedError
from src.sensitivity.counterfactual_inputs import replace_initial_profile
from src.sensitivity.output_contract import load_output_contract, observation_names

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('kind',['observed','controlled'])
def test_sa_payload_and_use_contract(kind):
    p=ROOT/'data/user/sa_bundles'/f'xxql2501_sa_{kind}_final_20261105'
    verify_manifest_integrity(p)
    with pytest.raises(InputUseProhibitedError):verify_calibrated_input_bundle(p)
    contract=load_output_contract(p/'sa_outputs.json')
    assert len(observation_names(contract))==164
    for rows in contract['water_nitrogen_design']['nitrogen_series'].values():
        assert [r['n_kg_ha'] for r in rows]==[0,122,254,364]
    assert 'CUMHARVEST_DAP50' in contract['features']


def test_controlled_treatments_differ_only_in_management():
    p=ROOT/'data/user/sa_bundles/xxql2501_sa_controlled_final_20261105/XXQL2501.TMX'
    parsed=parse_filex(p)
    backgrounds=[{k:v for k,v in row.items() if k not in ['MI','MF']} for row in parsed['treatments'].values()]
    assert all(row==backgrounds[0] for row in backgrounds)
    assert backgrounds[0]['SA']==backgrounds[0]['IC']==2
    rows=filex_section_text(p,'*INITIAL CONDITIONS').splitlines()
    layers=[row for row in rows if len(row.split())==5 and row.split()[0].isdigit()]
    assert all(len(row)==26 for row in layers)


def test_initial_rewriter_retains_two_character_factor_field():
    text='*INITIAL CONDITIONS\n@C ICBL SH2O SNH4 SNO3\n10     2 0.200  0.50  1.00\n'
    result=replace_initial_profile(text,10,[{'depth':2.,'sh2o':.225,'snh4':2.01,'sno3':8.41}])
    row=result.splitlines()[-1]
    assert len(row)==26 and row[:2]=='10'
    assert float(row[2:8])==2 and float(row[14:20])==2.01 and float(row[20:26])==8.41
