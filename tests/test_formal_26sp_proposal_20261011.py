"""Scientific contract checks for the review-only refreshed-data proposal."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.common.param_registry import PHYSICAL_BOUNDS
from tools.calibration.prepare_formal_26sp_n012_20261011 import mature_fruit_n_percent
from tools.experiments.rebuild_current_bundles import historical_bundle_directory

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'configs/calibration_proposals/eggplant_26sp_n012_review_20261011'


def test_roles_exclude_all_validation_and_n3_from_fit():
    p=json.loads((OUT/'proposal.json').read_text(encoding='utf-8'))
    assert p['executable'] is False and p['formal_calibration_started'] is False
    assert p['bounds_id'] is None
    roles={r['season_id']:r['roles'] for r in p['datasets']}
    assert roles['26SP']['calibration']==list(range(4,13))
    assert roles['26SP']['holdout']==[1,2,3]
    assert roles['25SP']['validation']==[2,3,4,5,10,11,12,13]
    assert roles['25FA']['validation']==[1,3,4,6,7,9,10,12]
    obs=pd.read_csv(OUT/'observation_catalog.csv')
    positive=obs[obs.final_weight>0]
    assert positive.season_id.eq('26SP').all()
    assert set(positive.trno)==set(range(4,13))
    assert len(positive)==423
    assert not positive.variable.isin(['SNAM','LNAM','CHPDT','CHFPW','HFPOW']).any()
    assert p['fruit_sampling_definition']['calibration_design_approved'] is False


def test_family_normalization_and_fruit_gate():
    obs=pd.read_csv(OUT/'observation_catalog.csv')
    positive=obs[obs.final_weight>0]
    for family,part in positive.groupby('family'):
        assert ((part.final_weight*part.sigma_eff)**2).sum()==pytest.approx(part.phi_budget.iloc[0])
        totals=part.assign(total=(part.final_weight*part.sigma_eff)**2).groupby('trno').total.sum()
        assert np.allclose(totals,totals.iloc[0])
    fruit=positive[positive.variable.eq('FRUIT_N_PCT')]
    assert len(fruit)==27 and fruit.final_weight.gt(0).all()
    assert fruit.observation_operator.eq('mature_seed_shell_weighted_model_average_N_proxy').all()
    assert fruit.runtime_operator_preflight_passed.eq(False).all()


def test_domains_respect_hard_bounds_and_composition_order():
    p=pd.read_csv(OUT/'parameter_review.csv').set_index('name')
    active=p[p.status.eq('active')]
    assert len(active)==53
    for name,r in active.iterrows():
        lo,hi=PHYSICAL_BOUNDS[name]
        assert lo<=r.lower<r.upper<=hi
        assert r.lower<=r.init<=r.upper
    assert p.loc['PROLFF','upper']<=p.loc['PROLFG','lower']
    assert p.loc['PROLFG','upper']<=p.loc['PROLFI','lower']
    assert p.loc['PROSTF','upper']<=p.loc['PROSTG','lower']
    assert p.loc['PROSTG','upper']<=p.loc['PROSTI','lower']
    assert p.loc['PROSHF','upper']<=p.loc['PROSHI','lower']
    assert p.loc['PROSHG','status']=='fixed'
    assert p.loc['XMAGE','upper']<p.loc['XFPHT','init']
    assert p.loc['FL-VS','init']==100.
    assert not any(name.startswith(('SOIL_','ICNS','SASC','SLPF_','PAGE_','PENV_')) for name in p.index)


def test_direct_n_values_use_dry_percent_and_exact_dates():
    obs=pd.read_csv(OUT/'observation_catalog.csv')
    b=historical_bundle_directory('xxql2601_refreshed_20261010')
    raw=pd.read_csv(b/'plant_npk_source_values.csv')
    for r in obs[(obs.season_id=='26SP')&obs.variable.isin(['LEAF_N_PCT','STEM_N_PCT','FRUIT_N_PCT'])].itertuples():
        organ={'LEAF_N_PCT':'叶','STEM_N_PCT':'茎','FRUIT_N_PCT':'果'}[r.variable]
        part=raw[(raw.trno==r.trno)&(raw.date==r.date)&(raw.organ==organ)]
        assert r.observed==pytest.approx(part.N.mean()/10.)
    reads=pd.read_csv(OUT/'nitrogen_output_readback.csv')
    assert len(reads)==99
    assert reads.valid_native_date.all()
    assert reads.baseline_simulated.notna().all()
    fruit=reads[reads.variable.eq('FRUIT_N_PCT')]
    assert fruit.target_semantics.eq('mature_fruit_organ_average_N_proxy').all()
    leaf=reads[reads.variable.eq('LEAF_N_PCT')]
    assert set(leaf.date)=={'2026-05-02','2026-06-03','2026-06-29','2026-07-17'}


def test_mature_fruit_concentration_uses_component_dry_mass():
    assert mature_fruit_n_percent(4.,2.,10.,30.)==pytest.approx(2.5)
    # Halving the representative sample mass does not double concentration.
    assert mature_fruit_n_percent(4.,2.,5.,15.)==pytest.approx(2.5)


@pytest.mark.parametrize('components',[(4.,2.,0.,0.),(-99.,2.,10.,30.),(4.,2.,float('nan'),30.)])
def test_invalid_mature_pool_cannot_fall_back_to_live_fruit(components):
    with pytest.raises(ValueError):
        mature_fruit_n_percent(*components)
