"""Independent checks on exported data, exact replay, and unchanged reference."""
from pathlib import Path
import hashlib,json,math,csv,datetime,re
import numpy as np
import pandas as pd
R=Path(__file__).resolve().parent;O=R/'已填数据_stable79_20261019'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
load=lambda p:json.loads(Path(p).read_text(encoding='utf8'))
raw=R/'原始模型输出/stable79_checkpointed150x5_20261019';rec=load(raw/'last_success.json');trial=Path(rec['trial'])
project=R.parent/'critical_n/n_buffer_v13';baseline=project/'runs/stable79_checkpointed150x5_20261018'
oldtrial=Path(load(baseline/'champion_audit.json')['replay_trial'])
design=load(project/'configs/capacity_a_stable79_checkpointed_r4.json')
assert all(sha(p)==h for p,h in design['frozen_hashes'].items())
assert sha(O/'最佳参数_120项.csv')==sha(baseline/'best_parameters.csv')
assert rec['complete_targets']==1123 and abs(rec['phi']-127.19135195285774)<1e-10
a=pd.read_csv(trial/'comparison.csv',float_precision='round_trip');b=pd.read_csv(oldtrial/'comparison.csv',float_precision='round_trip')
assert np.array_equal(a.simulated.to_numpy(),b.simulated.to_numpy())
ledgers=['NCBalance','DMState','OrganNState','RootNSupply','CAllocation','PhotoN','CH2OPools','CohortSync','NFlux','NAcceptance']
exact={s:{n:sha(trial/s/(n+'.csv'))==sha(oldtrial/s/(n+'.csv'))for n in ledgers}for s in ['26SP','25SP']}
assert all(all(v.values())for v in exact.values())
def read(n):return pd.read_csv(next(O.glob(n+'_*.csv')))
runs=read('01');water=read('02');soil=read('03');org=read('04');events=read('05');mapping=read('06');cal=read('07');periods=read('08');daily=read('10');nitrogen=read('11')
assert len(runs)==20 and runs.run_id.nunique()==20 and runs.block_id.isna().all()
assert len(water)==2504 and not water.duplicated(['season','run_id','date']).any()
assert len(events)==132 and not events.duplicated(['season','run_id','date','event_type']).any()
assert not soil.duplicated(['season','run_id','date','state_timing','layer_top_cm','layer_bottom_cm']).any()
assert not org.duplicated(['season','run_id','date','state_timing','organ']).any()
assert not daily.duplicated(['season','run_id','date','state_timing','organ']).any()
assert len(cal[cal.data_use.eq('CALIBRATION')])==1123 and not cal.data_use.eq('VALIDATION').any()
assert (water.ET_actual_mm-water.transp_actual_mm-water.evap_soil_actual_mm).abs().max()<=.001001
assert water.drainage_below100_mm.isna().all() and water.capillary_into100_mm.isna().all()
assert water.balance_depth_cm.eq(180).all()
for q in [org,daily,events]:
    assert q.P_kg_ha.isna().all()and q.K_kg_ha.isna().all()
    assert q[['drymatter_kg_ha','N_kg_ha']].notna().all().all()
    assert (q[['drymatter_kg_ha','N_kg_ha']]>=-1e-9).all().all()
for q in [org,daily]:
    mask=q.drymatter_kg_ha.gt(0)
    assert np.allclose(q.loc[mask,'N_g_kg_DM'],1000*q.loc[mask,'N_kg_ha']/q.loc[mask,'drymatter_kg_ha'],rtol=1e-10,atol=1e-9)
    assert q.loc[~mask,'N_g_kg_DM'].isna().all()
assert soil.theta_v_m3_m3.between(0,1).all()
assert np.allclose(soil.layer_storage_mm,soil.theta_v_m3_m3*(soil.layer_bottom_cm-soil.layer_top_cm)*10,atol=1e-9)
plant=runs.set_index('run_id').transplant_date.to_dict()
for rid,g in water.groupby('run_id'):
    expected=(pd.to_datetime(g.date)-pd.Timestamp(plant[rid])).dt.days
    assert np.array_equal(g.DAT.to_numpy(),expected.to_numpy())
for p in periods.to_dict('records'):
    dates=pd.date_range(p['start_date'],pd.Timestamp(p['end_date_exclusive'])-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    g=water[water.run_id.eq(p['run_id'])&water.date.isin(dates)]
    assert len(g)==p['days']==p['n_daily_rows']
    assert math.isclose(math.fsum(g.ET_actual_mm),p['ET_actual_mm'],rel_tol=1e-10,abs_tol=1e-8)
    assert math.isclose(p['ET_intensity_mm_d']*p['days'],p['ET_actual_mm'],rel_tol=1e-10,abs_tol=1e-8)
for rid,g in periods.groupby('run_id'):
    year=int(g.season.iloc[0][:4]);get=lambda tag:float(g[g.interval_id.eq(f'{year}_{tag}')].ET_actual_mm.iloc[0])
    assert math.isclose(get('SEEDLING')+get('FLOWER_FRUIT')+get('MATURITY_POINT'),get('SEASON_POINT'),abs_tol=1e-8)
    assert math.isclose(get('SEASON_POINT')+get('LAST_DAY'),get('SEASON_CALENDAR'),abs_tol=1e-8)
targets=pd.read_csv(R/'填报模板/04_器官状态.csv')
post=org[~org.state_timing.eq('PRE_HARVEST_RECONSTRUCTED')]
assert len(targets.merge(post,on=['season','run_id','date','organ'],validate='one_to_one'))==360
harvest_check=read('13');assert harvest_check.pre_post_harvest_residual_kg_ha.abs().max()<=.10001
# Independent ledger unit, harvest and cumulative uptake checks.
max_n=0.;unit_pairs=0
for s in ['26SP','25SP']:
    work=trial/s;d=pd.read_csv(work/'DMState.csv');n=pd.read_csv(work/'OrganNState.csv');nb=pd.read_csv(work/'NCBalance.csv')
    date=lambda v:(pd.Timestamp(int(v)//1000,1,1)+pd.Timedelta(days=int(v)%1000-1)).strftime('%Y-%m-%d')
    for q in [d,n,nb]:q['date']=q.yrdoy.map(date)
    for run in runs[runs.season.eq('2026春'if s=='26SP'else'2025春')].to_dict('records'):
        trt=int(run['source_plot_code']);rid=run['run_id'];dd=d[d.trt.eq(trt)].set_index('date');nn=n[n.trt.eq(trt)].set_index('date');bb=nb[nb.trt.eq(trt)].set_index('date')
        for row in daily[daily.run_id.eq(rid)].to_dict('records'):
            o=row['organ'];date=row['date'];mass=(dd.loc[date,'shell_dm']+dd.loc[date,'seed_dm'])if o=='fruit_onplant'else dd.loc[date,o+'_dm'];value=nn.loc[date,'fruit_n']if o=='fruit_onplant'else nn.loc[date,o+'_n']
            assert math.isclose(row['drymatter_kg_ha'],mass*10,rel_tol=1e-10,abs_tol=1e-8)
            assert math.isclose(row['N_kg_ha'],value*10,rel_tol=1e-10,abs_tol=1e-9);unit_pairs+=1
        e=events[events.run_id.eq(rid)].set_index('date')
        assert np.allclose(e.N_kg_ha,bb.loc[e.index,'harvest_n']*10,rtol=1e-10,atol=1e-9)
        uq=nitrogen[nitrogen.run_id.eq(rid)].set_index('date')
        assert np.allclose(uq.root_uptake_cumulative_N_kg_ha,bb.root_input.cumsum()*10,rtol=1e-10,atol=1e-9)
        assert np.allclose(uq.harvest_cumulative_N_kg_ha,bb.harvest_n.cumsum()*10,rtol=1e-10,atol=1e-9)
    max_n=max(max_n,float(nb.filter(regex='residual').abs().to_numpy().max()*10))
missing=set(pd.read_csv(R/'填报模板/06_变量映射与支持情况.csv').target_field)-set(mapping.target_field)
assert not missing,missing
P=read('12');p_bad=int(P.native_missing_fields.notna().sum());p_mismatch=len(read('14'))
# Input templates and measurements are preserved, not filled in place.
for num,cols in [('02',['ET_actual_mm']),('03',['theta_v_m3_m3']),('04',['drymatter_kg_ha','N_kg_ha','P_kg_ha','K_kg_ha']),('05',['drymatter_kg_ha','N_kg_ha'])]:
    q=pd.read_csv(next((R/'填报模板').glob(num+'_*.csv')));assert q[cols].isna().all().all()
result=dict(checked_on='2026-10-19',passed=True,selected_run=baseline.name,parameters_sha256=sha(baseline/'best_parameters.csv'),binary_sha256=design['binary_sha256'],
    original_frozen_dependencies_verified=len(design['frozen_hashes']),targets_exact=1123,phi=rec['phi'],exact_replay_ledgers=exact,
    full_parameter_readback=load(trial/'full_parameter_readback_audit.json'),runs=20,daily_water_rows=len(water),soil_boundary_rows=len(soil),key_organ_rows=len(org),
    daily_organ_rows=len(daily),daily_organ_unit_pairs_verified=unit_pairs,harvest_rows=len(events),interval_rows=len(periods),
    no_false_block_replicates=True,no_false_independent_validation=True,P_K_core_values_blank=True,P_native_overflow_rows=p_bad,P_state_timing_mismatch_rows=p_mismatch,
    max_native_N_residual_kg_ha=max_n,max_ET_T_E_rounding_residual_mm=float((water.ET_actual_mm-water.transp_actual_mm-water.evap_soil_actual_mm).abs().max()),
    max_harvest_DM_rounding_residual_kg_ha=float(harvest_check.pre_post_harvest_residual_kg_ha.abs().max()),
    templates_unchanged_empty=True,scientific_use_limits=['ET is simulated, not independently validated','100cm interface flux not exported','P organ timing/harvest not validated; K disabled','BOD is previous EOD approximation','initial transplant stock is modeled, not observed'])
(O/'交付核验.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
inventory=[dict(file=p.relative_to(R).as_posix(),bytes=p.stat().st_size,sha256=sha(p))for folder in [O,raw]for p in sorted(folder.rglob('*'))if p.is_file()and p.name!='文件校验SHA256.json']
(O/'文件校验SHA256.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items()if k not in ['exact_replay_ledgers','full_parameter_readback']},ensure_ascii=False,indent=2))
