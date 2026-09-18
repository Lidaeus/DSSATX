import copy
import numpy as np
import pandas as pd
import pytest
from tools.experiments.run_v52_photo_senescence_20260902 import (
    plan, validate_task, member, acceptance, CONTROL,
    refine_plan, last_node_template, ROOT,
)
from src.dssat.array_expander import expand_senpor


def test_paired_grid_keeps_common_n_soil_and_source_sink():
    tasks = plan()
    assert len(tasks) == 25 and len({t['label'] for t in tasks}) == 25
    base = member('A_ic_control', 3, 47)
    for task in tasks:
        validate_task(task, base)
        for key in ['icns_25sp','icns_26sp','xfpht','xfrt','rtno3','phtmax','parmax']:
            assert task['values'][key] == base[key]


def test_canopy_reference_does_not_import_its_initial_n():
    task = next(t for t in plan() if t['label']=='p0_canopyE')
    source = member('E_canopy', 2, 3)
    assert task['values']['icns_26sp'] != source['icns_26sp']
    assert task['values']['senrte'] == source['senrte']


def test_senpor_expansion_is_not_false_default_control():
    assert expand_senpor(1/3).y_values == pytest.approx([0,0,.12,1/3])
    assert expand_senpor(.16).y_values[2] != pytest.approx(.12)
    assert 'senpor_late' not in next(t for t in plan() if t['label']=='p0_control')['values']


def test_non_arm_change_rejected():
    task = copy.deepcopy(plan()[0])
    task['values']['rtno3'] = .01
    with pytest.raises(AssertionError):
        validate_task(task, member('A_ic_control',3,47))


def good_candidate():
    reference = pd.read_csv(CONTROL/'fit_metrics.csv')
    candidate = reference.copy()
    candidate.loc[candidate.variable.eq('FRESH_CUM'),'nse'] += .02
    candidate.loc[candidate.variable.eq('FRESH_TERMINAL'),'rrmse_pct'] -= .5
    return candidate,reference


def test_yield_gain_cannot_compensate_for_bad_lai():
    candidate,reference = good_candidate()
    assert acceptance(candidate,reference)['passed']
    candidate.loc[(candidate.season=='26SP') & (candidate.variable=='LAID'),'nse'] -= .031
    assert not acceptance(candidate,reference)['passed']


@pytest.mark.parametrize('variable',['LAID_early','LAID_late','WRESPS_N0','NRESPS_W1'])
def test_stage_and_response_guard(variable):
    candidate,reference = good_candidate()
    mask = candidate.variable.eq(variable)
    assert mask.any()
    candidate.loc[mask,'rmse'] *= 1.11
    assert not acceptance(candidate,reference)['passed']


def test_missing_metric_cannot_pass():
    candidate,reference = good_candidate()
    candidate.loc[candidate.variable.eq('LAID'),'nse'] = np.nan
    assert not acceptance(candidate,reference)['passed']


def test_last_node_probe_preserves_earlier_nodes_and_all_other_characters():
    original = (ROOT/'data/templates/genotype/TMGRO048.SPE.base').read_text()
    output = last_node_template(original,.18)
    a,b=original.splitlines(),output.splitlines()
    i=next(i for i,s in enumerate(a) if 'SENPOR.........' in s)+1
    assert all(x==y for j,(x,y) in enumerate(zip(a,b)) if j!=i)
    assert a[i][:18]==b[i][:18] and a[i][24:]==b[i][24:]
    assert float(b[i][18:24])==.18
    assert len(refine_plan())==15


def test_last_node_probe_rejects_large_or_combined_expansion():
    with pytest.raises(AssertionError):
        last_node_template('',.3)
    task=copy.deepcopy(refine_plan()[0])
    task['values']['senpor_late']=.5
    task['changes']['senpor_late']=.5
    with pytest.raises(AssertionError):
        validate_task(task,member('A_ic_control',3,47))
