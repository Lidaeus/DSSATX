"""Regression checks for the current source/observation contracts."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tools.experiments import rebuild_current_bundles as refresh
from src.calibration.audit_observations import read_dssat_observation_table, audit_observation_bundle
from src.common.experiment_inputs import parse_filex, filex_section_text
from src.calibration.build_pest import _read_tmt_process_points, _read_tmt_harvest_events


def test_interpolation_is_linear_and_holds_endpoints():
    frame=pd.DataFrame({'date':pd.to_datetime(['2026-06-01','2026-06-11']),'dmfr':[.04,.08]})
    value,method,*_=refresh.interpolate_at(frame,'2026-06-06','dmfr')
    assert value==pytest.approx(.06)
    assert method=='linear'
    assert refresh.interpolate_at(frame,'2026-05-01','dmfr')[:2]==(.04,'endpoint_hold')
    assert refresh.interpolate_at(frame,'2026-07-01','dmfr')[:2]==(.08,'endpoint_hold')


def test_unpaired_mean_product_does_not_invent_covariance():
    concentration=np.array([10.,30.]);mass=np.array([100.,300.])
    assert np.mean(refresh.paired_nutrient(concentration,mass))==5.
    assert refresh.mean_product(concentration,mass)==4.


@pytest.mark.parametrize('raw,expected',[('2025/0813','2025-08-13'),(45932,'2025-10-02'),(20261002,'2026-10-02')])
def test_dates_preserve_year(raw,expected):
    assert str(refresh.date_of(raw).date())==expected


@pytest.fixture(scope='module')
def rebuilt(tmp_path_factory):
    root=tmp_path_factory.mktemp('current_sources')
    refresh.build(root)
    return root


@pytest.mark.parametrize('season',list(refresh.SPECS))
def test_current_sources_and_runtime_readers(rebuilt,season):
    spec=refresh.SPECS[season];out=rebuilt/f'{spec["excode"].lower()}_refreshed_20261010'
    t=read_dssat_observation_table(out/f'{spec["excode"]}.TMT')
    a=read_dssat_observation_table(out/f'{spec["excode"]}.TMA')
    assert set(t.TRNO)==set(spec['treatments'])
    assert set(a.TRNO)==set(spec['treatments'])
    assert not t.duplicated(['TRNO','DATE']).any()
    assert set(a.PDAT)=={refresh.code(spec['planting'])}
    assert set(a.MDAT)=={-99}
    if season!='25FA':assert a.ADAT.ne(-99).all()
    assert set(_read_tmt_process_points(str(out/f'{spec["excode"]}.TMT')))==set(spec['treatments'])
    assert set(_read_tmt_harvest_events(str(out/f'{spec["excode"]}.TMT')))==set(spec['treatments'])
    source=pd.read_csv(out/'harvest_replicates.csv')
    for (tn,date),g in source.groupby(['trno','date']):
        row=t[(t.TRNO==tn)&(t.DATE==refresh.code(date))].iloc[0]
        assert row.CHPDT==pytest.approx(round(g.CHPDT.mean()))
        assert row.CHFPW==pytest.approx(round(g.CHFPW.mean()))
    # Exact cumulative plot covariance is retained in the source SD table.
    u=pd.read_csv(out/'observation_uncertainty.csv')
    last=source.sort_values('date').groupby(['trno','rep']).tail(1)
    for tn,g in last.groupby('trno'):
        row=u[(u.trno==tn)&(u.variable=='CHPDT')].sort_values('date').iloc[-1]
        assert row.raw_sd==pytest.approx(g.CHPDT.std(ddof=1))
    parsed=parse_filex(out/f'{spec["excode"]}.TMX')
    assert parsed['weather_station']=='XXTW2403'
    n_profiles={tuple((r['snh4'],r['sno3']) for r in v) for v in parsed['initial_conditions'].values()}
    assert len(n_profiles)==1
    assert next(iter(n_profiles))[0]==pytest.approx((2.01,8.41))
    fert=pd.read_csv(out/'fertilizer_event_audit.csv')
    ic=filex_section_text(out/f'{spec["excode"]}.TMX','*INITIAL CONDITIONS')
    icdates=[int(l.split()[2]) for l in ic.splitlines() if ' TN' in l and '_prebasal' in l]
    assert max(icdates)<int(fert['TMX日期码'].min())
    audit,_=audit_observation_bundle(out)
    assert all(f['code']=='WEATHER_MISSING' for f in audit['findings'] if f['severity']=='error')
    assert 'PLANT_N_OBSERVATIONS_UNAVAILABLE' not in {f['code'] for f in audit['findings']}
    assert audit['available_counts']['SNAM']>0


def test_autumn_out_of_season_soil_is_preserved_and_excluded(rebuilt):
    p=rebuilt/'xxql2502_refreshed_20261010'
    water=pd.read_csv(p/'soil_water_observations.csv')
    future=water[water.date=='2026-10-02']
    assert len(future)==48
    assert set(future.phi_role)=={'out_of_season'}
    final=water[water.date=='2026-01-06']
    assert len(final)==60 and set(final.n_rep)=={0} and set(final.n_samples)=={4}
    u=pd.read_csv(p/'observation_uncertainty.csv')
    n=u[u.variable.isin(['SNAM','LNAM'])]
    assert n.raw_sd.isna().all() and n.n_rep.eq(0).all()


def test_spring_growth_gaps_not_imputed_and_initial_water_not_scaled(rebuilt):
    t=pd.read_csv(rebuilt/'xxql2501_refreshed_20261010'/'FileT_values.csv')
    assert not t.DATE.isin([refresh.code('2025-06-09'),refresh.code('2025-06-21')]).any()
    out=rebuilt/'xxql2601_refreshed_20261010'
    water=pd.read_csv(out/'soil_water_observations.csv')
    parsed=parse_filex(out/'XXQL2601.TMX')
    for tn in [10,12]:
        v=water[(water.trno==tn)&(water.date=='2026-03-14')&(water.depth_top_cm==0)].vwc_mean.iloc[0]
        assert parsed['initial_conditions'][tn][0]['sh2o']==pytest.approx(round(v,3))
    audit=pd.read_csv(out/'standing_npk_calculation_audit.csv')
    june=audit[audit.concentration_date=='2026-06-03']
    assert set(june.growth_date)=={'2026-06-02'}


def test_manual_moisture_provenance_and_weather_format(rebuilt):
    out=rebuilt/'xxql2501_refreshed_20261010'
    matches=pd.read_csv(out/'fruit_quality_match_audit.csv')
    assert matches.approved_manual_moisture_influence.any()
    u=pd.read_csv(out/'observation_uncertainty.csv')
    assert (u.quality_flag=='includes_approved_manual_moisture').any()
    refresh.weather_output('25SP',out,'existing')
    weather=(out/'XXTW2403.WTH').read_text().splitlines()
    assert weather[0].startswith('$WEATHER')
    assert weather[5].startswith('2025068')
    header=next(l for l in weather if l.strip().startswith('XXTW'))
    assert float(header[29:35])==20.
    assert float(header[35:41])==6.
    t_header=(out/'XXQL2501.TMT').read_text().splitlines()[3]
    assert t_header[:6]=='@TRNO '
    x_header=filex_section_text(out/'XXQL2501.TMX','*INITIAL CONDITIONS')
    layer=next(l for l in x_header.splitlines() if len(l.split())==5 and l.split()[0].isdigit())
    assert len(layer)==26


def test_rebuilding_generated_filex_preserves_harvest_options(rebuilt, tmp_path):
    season = '26SP'
    old = rebuilt / 'xxql2601_refreshed_20261010'
    growth = pd.read_csv(old / 'growth_replicates.csv', parse_dates=['date'])
    harvest = pd.read_csv(old / 'harvest_replicates.csv', parse_dates=['date'])
    water = pd.read_csv(old / 'soil_water_observations.csv')
    refresh.filex_outputs(season, tmp_path, old, refresh.soil_chemistry(season), water, harvest, growth)
    before = filex_section_text(old / 'XXQL2601.TMX', '*HARVEST DETAILS')
    after = filex_section_text(tmp_path / 'XXQL2601.TMX', '*HARVEST DETAILS')
    assert before == after
    rows = [line.split() for line in after.splitlines() if line.strip() and line.strip()[0].isdigit()]
    assert all(len(row) == 9 for row in rows)
