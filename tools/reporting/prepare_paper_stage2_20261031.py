"""Freeze C31 stage-2 paper evidence. No rendering, forward model, or calibration."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.reporting.prepare_paper_stage01_20261031 import parse_daily, filex_rows, full_date, metrics
from src.common.experiment_inputs import parse_filex

OUT=ROOT/'workspace/reviews/paper_stage2_20261031'
B=OUT/'paper_data'
OLD=ROOT/'workspace/reviews/paper_stage01_20261031/paper_data'
CASE='full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927'
SOURCES={}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def source(p):
    p=Path(p);SOURCES[p.relative_to(ROOT).as_posix()]=sha(p);return p
def read(p):return pd.read_csv(source(p))
def write(df,name):df.to_csv(B/name,index=False,encoding='utf-8-sig')
def checked_manifest(directory):
    m=json.loads(source(directory/'paper_data_manifest.json').read_text(encoding='utf-8'))
    for a in m['artifacts']:
        assert Path(a['path']).name==a['path']
        assert sha(source(directory/a['path']))==a['sha256'],a['path']
    return m
def date_ts(code):
    code=int(code);code=full_date(code) if code<100000 else code
    return pd.Timestamp(year=code//1000,month=1,day=1)+pd.Timedelta(days=code%1000-1)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--allow-unvalidated-demo',action='store_true');args=ap.parse_args()
    if not args.allow_unvalidated_demo:ap.error('Stage 2 retains audit_review_unvalidated; explicit demo export required')
    B.mkdir(parents=True,exist_ok=True)
    previous=checked_manifest(OLD)
    roles=read(OLD/'treatment_role_audit.csv')
    pairs=read(OLD/'evaluation_pairs.csv')
    pairs=pairs[(pairs.variant=='baseline')&(pairs.date_offset_days==0)].copy()
    terminal=read(OLD/'terminal_pairs.csv');terminal=terminal[(terminal.variant=='baseline')&(terminal.date_offset_days==0)].copy()
    terminal['observation_origin']='observed_or_aggregated'
    performance=read(OLD/'performance_metrics.csv')
    performance=performance[(performance.variant=='baseline')&(performance.date_offset_days==0)].copy()
    parameters=read(OLD/'parameter_reconciliation.csv')
    management=read(OLD/'management_audit.csv')
    uncertainty=read(OLD/'observation_uncertainty_audit.csv')
    origin=uncertainty[uncertainty.variable.isin(['LAID','LWAD','SWAD'])][
      ['audit_season','trno','date','variable','sd_method']].rename(columns={
        'audit_season':'season_id','trno':'treatment','date':'date_code','sd_method':'observation_method'})
    assert not origin.duplicated(['season_id','treatment','date_code','variable']).any()
    pairs=pairs.merge(origin,on=['season_id','treatment','date_code','variable'],how='left',validate='one_to_one')
    pairs['observation_origin']=np.where(pairs.observation_method.str.startswith('imputed',na=False),'SLA_ratio_derived','observed_or_aggregated')
    selected=[]
    for season,tns in [('25SP',[2,13,12]),('26SP',[1,12,10])]:
        for rank,tn in enumerate(tns):
            r=roles[(roles.season_id==season)&(roles.treatment==tn)].iloc[0].to_dict()
            r.update(selection_order=rank+1,selection_basis=['高水高氮','低水零氮','同等级留出处理'][rank],
                     use_growth=True,use_harvest=rank!=1,design_label=r['water_level']+r['nitrogen_level'])
            selected.append(r)
    selected=pd.DataFrame(selected);write(selected,'representative_treatments.csv')
    # Reconstruct only eligible repeated-measurement SE; no minimum-CV or propagated errors.
    u=uncertainty[uncertainty.field_repeat_error_eligible & uncertainty.variable.isin(['LAID','LWAD','SWAD'])].copy()
    u=u.rename(columns={'audit_season':'join_season','trno':'treatment','date':'date_code','value':'error_source_mean'})
    keys=['treatment','date_code','variable']
    assert not u.duplicated(['join_season',*keys]).any()
    pairs=pairs.merge(u[['join_season',*keys,'error_source_mean','raw_sd','n_rep','sd_method']],
                      left_on=['season_id',*keys],right_on=['join_season',*keys],how='left',validate='one_to_one')
    eligible=pairs.raw_sd.notna()
    pairs['error_source_rounding_difference']=pairs.observed-pairs.error_source_mean
    # Archived FileA rounds LAI to 0.001 and organ mass to 1 kg/ha.
    tolerance=np.where(pairs.variable.eq('LAID'),.00050001,.50000001)
    assert (pairs.loc[eligible,'error_source_rounding_difference'].abs()<=tolerance[eligible]).all()
    pairs['observed_se']=pairs.raw_sd/np.sqrt(pairs.n_rep)
    pairs=pairs.drop(columns=['join_season'])
    write(pairs,'comparison.csv');write(terminal,'terminal_pairs.csv');write(performance,'performance_metrics.csv')
    direct=[]
    for season,g in pairs[(pairs.variable=='LAID') & (pairs.observation_origin!='SLA_ratio_derived')].groupby('season_id'):
        for role,h in [('all',g),*list(g.groupby('dataset_role'))]:
            direct.append(dict(season_id=season,variable='LAID',dataset_role=role,observation_scope='direct_measurements_only',**metrics(h)))
    write(pd.DataFrame(direct),'LAI_direct_measurement_metrics.csv')
    validation=pd.concat([pairs,terminal],ignore_index=True);assert len(validation)==617
    write(validation,'validation_sample_pairs.csv');write(roles,'treatment_metadata.csv')
    write(parameters,'parameter_reconciliation.csv');write(management,'management_totals.csv')
    ablation=read(OLD/'performance_metrics.csv')
    ablation=ablation[(ablation.date_offset_days==0)&(ablation.dataset_role=='all')]
    write(ablation,'ablation_metrics.csv');write(read(OLD/'partition_function.csv'),'partition_function.csv')
    daily=[];weather=[];events=[];seasons=[];source_comparison=[]
    for season in ['25SP','26SP']:
        run=ROOT/'workspace/runs/c31_deterministic/_seasons'/season
        ex={'25SP':'XXQL2501','26SP':'XXQL2601'}[season]
        plant=parse_daily(source(run/'PlantGro.OUT')).reset_index()
        harvest=terminal[terminal.season_id==season]
        start=date_ts(management[management.season_id==season].planting_date.iloc[0])
        end=date_ts(harvest.date_code.max())
        final_dap=(end-start).days
        for row in roles[roles.season_id==season].itertuples():
            part=plant[(plant.treatment==row.treatment)&plant.DAP.ge(0)&plant.DAP.le(final_dap)]
            for v in ['LAID','LWAD','SWAD']:
                d=part[['date_full','DAP',v]].rename(columns={'DAP':'dap',v:'simulated'})
                d=d.assign(season_id=season,treatment=row.treatment,variable=v,dataset_role=row.dataset_role,
                           water_level=row.water_level,nitrogen_level=row.nitrogen_level,
                           source_file=(run/'PlantGro.OUT').relative_to(ROOT).as_posix())
                daily.append(d)
        filex=source(run/f'{ex}.TMX');parsed=parse_filex(filex)
        irr=filex_rows(filex,'IDATE');fert=filex_rows(filex,'FDATE')
        for kind,rows,factor,level_col,value_col,date_col in [
            ('irrigation',irr,'MI','water_level','IRVAL','IDATE'),
            ('nitrogen',fert,'MF','nitrogen_level','FAMN','FDATE')]:
            factors={}
            for row in roles[roles.season_id==season].itertuples():
                key=parsed['treatments'][row.treatment][factor]
                level=getattr(row,level_col)
                assert level not in factors or factors[level]==key
                factors[level]=key
            for level,index in factors.items():
                group_key='I' if kind=='irrigation' else 'F'
                group=[r for r in rows if int(r[group_key])==index]
                for r in group:
                    dt=date_ts(r[date_col]);events.append(dict(season_id=season,kind=kind,level=level,
                      date=dt.date().isoformat(),dap=(dt-start).days,amount=float(r[value_col]),
                      factor=int(index),source_file=filex.relative_to(ROOT).as_posix()))
        wth=source(run/f"{parsed['weather_station']}.WTH")
        head=None;wrows=[]
        for line in wth.read_text().splitlines():
            if line.startswith('@') and 'DATE' in line:head=line[1:].split()
            elif head:
                values=line.split()
                if len(values)==len(head) and values[0].isdigit():wrows.append(dict(zip(head,values)))
        wf=pd.DataFrame(wrows);wf['date']=wf.DATE.map(date_ts);wf=wf[wf.date.dt.year.eq(start.year)&wf.date.dt.month.le(7)].copy()
        for col in ['TMAX','TMIN','SRAD','RAIN','RHUM']:wf[col]=pd.to_numeric(wf[col])
        wf['season_id']=season;wf['dap']=(wf.date-start).dt.days;wf['doy']=wf.date.dt.dayofyear
        wf['in_crop_period']=wf.date.between(start,end);wf['source_file']=wth.relative_to(ROOT).as_posix()
        wf['dekad']=(wf.date.dt.month-1)*3+np.minimum((wf.date.dt.day-1)//10+1,3)
        weather.append(wf)
        seasons.append(dict(season_id=season,planting_date=start.date().isoformat(),final_observed_harvest=end.date().isoformat(),
            final_dap=final_dap,weather_station=parsed['weather_station'],n_crop_days=final_dap+1))
    daily=pd.concat(daily,ignore_index=True);weather=pd.concat(weather,ignore_index=True);events=pd.DataFrame(events)
    write(daily,'simulation_trajectory.csv');write(weather,'weather_daily.csv');write(events,'management_events.csv')
    write(pd.DataFrame(seasons),'season_dates.csv')
    for kind,column in [('irrigation','water_level'),('nitrogen','nitrogen_level')]:
        sums=events[events.kind==kind].groupby(['season_id','level']).amount.sum()
        for row in management.itertuples():
            expected=row.irrigation_mm if kind=='irrigation' else row.nitrogen_kg_ha
            assert abs(sums.loc[(row.season_id,getattr(row,column))]-expected)<1e-7
    # Supplementary comparison reuses the reference's heat-stripe / daily-difference concept.
    # Values come from the actual station file for each C31 season, not a shared guessed source.
    wr=weather.melt(id_vars=['season_id','doy','date','dap','in_crop_period','dekad','source_file'],
                    value_vars=['TMAX','TMIN','SRAD'],var_name='variable',value_name='value')
    write(wr,'weather_stripes.csv')
    crop=weather[weather.in_crop_period]
    diff=crop[crop.season_id=='26SP'].merge(crop[crop.season_id=='25SP'],on='dap',suffixes=('_26','_25'))
    diffrows=[]
    for v in ['TMAX','TMIN','SRAD']:
        d=diff[['dap']].copy();d['variable']=v;d['difference']=diff[v+'_26']-diff[v+'_25']
        d['rolling7']=d.difference.rolling(7,center=True,min_periods=7).mean()
        d['mean_difference_common_dap']=d.difference.mean();diffrows.append(d)
    write(pd.concat(diffrows,ignore_index=True),'weather_daily_difference.csv')
    crop_summary=crop.groupby('season_id').agg(n_days=('dap','size'),tmax_mean=('TMAX','mean'),tmin_mean=('TMIN','mean'),
        srad_mean=('SRAD','mean'),srad_sum=('SRAD','sum'),rhum_mean=('RHUM','mean')).reset_index()
    write(crop_summary,'weather_crop_summary.csv')
    reference_wth=ROOT/'data/user/experiments/XXQL2501/XXLI2502.WTH'
    source(ROOT/'tools/reporting/plot_weather_comparison.py')
    source(ROOT/'workspace/weather_figures/agrometeorology_comprehensive_dashboard.png')
    if reference_wth.exists():source(reference_wth)
    # Historical multi-season sensitivity: preserve the run/domain and its pending status.
    sa_dir=ROOT/'workspace/_history/20260804/sensitivity/workspace_sa/w4_bundle'
    sa_manifest=checked_manifest(sa_dir)
    sa=read(sa_dir/'morris_group_scores.csv')
    sa=sa[sa.season.isin(['XXQL2501','XXQL2601'])].copy()
    sa['season_id']=sa.season.map({'XXQL2501':'25SP','XXQL2601':'26SP'})
    sa=sa.groupby(['run_id','data_status','season_id','ranking_domain','response_group','parameter'],as_index=False).agg(
        group_score=('group_score','mean'),n_seeds=('seed','nunique'))
    assert np.allclose(sa.groupby(['season_id','ranking_domain','response_group']).group_score.sum(),1)
    write(sa,'morris_process_scores.csv')
    sr=read(sa_dir/'morris_season_rankings.csv');sr=sr[sr.season.isin(['XXQL2501','XXQL2601'])].copy()
    sr['season_id']=sr.season.map({'XXQL2501':'25SP','XXQL2601':'26SP'})
    write(sr,'morris_season_rankings.csv')
    # Do not replace this historical C31-method context with a later single-season
    # observed-SA experiment that did not precede the C31 calibration.
    newer=ROOT/'workspace/runs/sa_25sp_observed_morris86_seed20261030_r30_refNguard_20261030/review_20261030/paper_data/paper_data_manifest.json'
    newer_manifest=json.loads(source(newer).read_text(encoding='utf-8'))
    run=ROOT/'workspace/runs'/CASE
    prior=read(run/f'{CASE}.0.par.csv');final=read(run/f'{CASE}.6.par.csv')
    prior=prior[prior.real_name.astype(str).str.lower().ne('base')];final=final[final.real_name.astype(str).str.lower().ne('base')]
    assert len(prior)==199 and len(final)==141
    selected_params=['TB1','EM-FL','FL-SH','FL-SD','LFMAX','KCAN','SLAVR','SIZLF','PODUR','SFDUR','XFRT','XMAGE','RWUMX','DSWBAR','RTNO3','NVSMOB']
    intervals=[];samples=[]
    for name in selected_params+['TRIFL']:
        row=parameters[parameters.parameter==name].iloc[0];assert not row.fixed_in_reference_ies
        for phase,df in [('initial',prior),('final',final)]:
            values=df[name.lower()].to_numpy(float)
            assert len(np.unique(values))>1
            for real,value in zip(df.real_name,values):samples.append(dict(parameter=name,phase=phase,realization=real,value=value))
            intervals.append(dict(parameter=name,phase=phase,n=len(values),q025=np.quantile(values,.025),q25=np.quantile(values,.25),median=np.median(values),q75=np.quantile(values,.75),q975=np.quantile(values,.975),working_lower=row.working_lower,working_upper=row.working_upper,iqr_shrinkage=row.iqr_shrinkage))
    write(pd.DataFrame(samples),'parameter_samples.csv');write(pd.DataFrame(intervals),'parameter_intervals.csv')
    c=final[[s.lower() for s in selected_params]].corr(method='spearman')
    correlations=[]
    for i,a in enumerate(selected_params):
        for j,b in enumerate(selected_params):correlations.append(dict(parameter_a=a,parameter_b=b,spearman=c.iloc[i,j],ensemble_n=141))
    write(pd.DataFrame(correlations),'spearman_correlation.csv')
    # Table 1: actual modeled inputs and actual available evaluation nodes.
    tab1=roles.merge(management[['season_id','treatment','irrigation_mm','nitrogen_kg_ha']],on=['season_id','treatment'],validate='one_to_one')
    counts=pairs.groupby(['season_id','treatment','variable']).size().unstack('variable',fill_value=0)
    for v in ['LAID','LWAD','SWAD','FRESH_CUM','FRESH_INC']:
        tab1[v+'_n']=[int(counts.loc[(r.season_id,r.treatment),v]) for r in tab1.itertuples()]
    tab1['terminal_n']=1;tab1['ep_ratio']=tab1.water_level.map({'W1':.4,'W2':.8,'W3':1.2})
    tab1['derived_LAI_n']=[int(((pairs.season_id==r.season_id)&(pairs.treatment==r.treatment)&
       (pairs.observation_origin=='SLA_ratio_derived')).sum()) for r in tab1.itertuples()]
    write(tab1,'Table1_trial_design.csv')
    # Table 2: verified input definitions; unknown pristine defaults remain blank.
    definitions=[
      ('TB1','物候','第一发育基温','°C'),('EM-FL','物候','出苗至初花的光温时间','光温日'),
      ('FL-VS','物候','初花至主茎末叶出现','光温日'),('FL-LF','冠层','初花至叶片扩展结束','光温日'),
      ('SD-PM','物候','始粒至生理成熟','光温日'),('TRIFL','冠层','主茎叶片出现速率','叶 热日⁻¹'),
      ('LFMAX','冠层','标准条件下最大叶片光合速率','mg CO₂ m⁻² s⁻¹'),('SLAVR','冠层','标准条件下比叶面积','cm² g⁻¹'),
      ('SIZLF','冠层','最大叶片面积','cm²'),('FRLFF','冠层','初花期向叶片分配的比例','g g⁻¹'),
      ('SENRTE','冠层','氮再动员伴随叶片衰老系数','g g⁻¹'),('SENDAY','冠层','水分胁迫导致的最大日衰老比例','d⁻¹'),
      ('FL-SH','生殖采收','初花至首荚形成','光温日'),('FL-SD','生殖采收','初花至始粒','光温日'),
      ('PODUR','生殖采收','形成最终果荚负载所需时间','光温日'),('SFDUR','生殖采收','单果队列种子充实持续期','光温日'),
      ('LNGSH','生殖采收','单果果壳结构生长持续期','光温日'),('XFRT','生殖采收','向种子和果壳分配的最大比例','g g⁻¹'),
      ('XMAGE','生殖采收','队列可采收光温年龄阈值','光温日'),('XFINT','生殖采收','初始生殖分配相对比例','无量纲'),
      ('XFPHT','生殖采收','动态分配达到最大基准所需时间','光温日'),('THRSH','生殖采收','种子占种子与果壳总干重的最大百分比','%'),
      ('RTNO3','水氮过程','单位根长最大硝态氮吸收系数','mg N cm⁻¹ d⁻¹'),('RWUMX','水氮过程','单位根长最大吸水系数','cm³ cm⁻¹ d⁻¹')]
    tab2=pd.DataFrame(definitions,columns=['parameter','process','definition_zh','unit']).merge(parameters,on='parameter',how='left',validate='one_to_one')
    assert len(tab2)==24 and tab2.c31_candidate_value.notna().all()
    tab2['original_tomato_default']=np.nan
    write(tab2,'Table2_key_parameters.csv')
    tab3=performance[((performance.season_id.isin(['25SP','26SP'])) & (performance.dataset_role.isin(['calibration','validation'])))|
       ((performance.season_id=='two_springs')&(performance.variable=='TERMINAL_FRESH'))].copy()
    assert len(tab3)==27
    write(tab3,'Table3_model_performance.csv')
    # Absolute response differences: endpoints N3-N0 and matched W2/3-W1;
    # missing treatment cells stay missing and CK never joins the water gradient.
    tr=terminal.merge(roles[['season_id','treatment','water_level','nitrogen_level']],on=['season_id','treatment'],validate='one_to_one')
    response=[]
    for season,d in tr[tr.water_level.ne('CK')].groupby('season_id'):
        for w,g in d.groupby('water_level'):
            low=g[g.nitrogen_level=='N0'];high=g[g.nitrogen_level=='N3']
            if len(low)==len(high)==1:
                response.append(dict(season_id=season,kind='nitrogen',level=w,contrast='N3−N0',
                  observed=float(high.observed.iloc[0]-low.observed.iloc[0]),simulated=float(high.simulated.iloc[0]-low.simulated.iloc[0])))
        for n,g in d.groupby('nitrogen_level'):
            ref=g[g.water_level=='W1']
            if len(ref)!=1:continue
            for w in ['W2','W3']:
                other=g[g.water_level==w]
                if len(other)==1:response.append(dict(season_id=season,kind='water',level=n,contrast=w+'−W1',
                  observed=float(other.observed.iloc[0]-ref.observed.iloc[0]),simulated=float(other.simulated.iloc[0]-ref.simulated.iloc[0])))
    response=pd.DataFrame(response);response['error']=response.simulated-response.observed
    response['direction_agrees']=np.sign(response.observed)==np.sign(response.simulated)
    write(response,'water_nitrogen_contrasts.csv')
    response_summary=[]
    for (season,kind),g in response.groupby(['season_id','kind']):
        response_summary.append(dict(season_id=season,kind=kind,n=len(g),rmse=float(np.sqrt(np.mean(g.error**2))),
          mae=float(g.error.abs().mean()),direction_agreement=float(g.direction_agrees.mean())))
    write(pd.DataFrame(response_summary),'water_nitrogen_contrast_summary.csv')
    source(ROOT/'data/templates/genotype/TMGRO048.ECO.base');source(ROOT/'data/templates/genotype/TMGRO048.SPE.base')
    source(ROOT/'data/templates/genotype/TMGRO048.CUL.base')
    source(ROOT/'subprojects/critical_n/parameter_n_mass_audit_20261018/sources/official_local/SENES.for')
    source(ROOT/'subprojects/critical_n/n_buffer_v1/vendor/Plant/CROPGRO/NUPTAK.for')
    source(ROOT/'subprojects/critical_n/n_buffer_v1/vendor/SPAM/ROOTWU.for')
    source(ROOT/'paper/【排版】DSSAT茄子作物模型开发与验证-10.6.docx')
    manifest=dict(schema_version=1,bundle_type='paper_reconstruction_stage2',run_id='C31_stage2_20261031',
        data_status='audit_review_unvalidated',scientific_status_promoted=False,
        scenario_type='actual_trial_calibration',seasons=['25SP','26SP'],date_policy='same_observed_day',
        parameter_ensemble=dict(reference_run=CASE,initial_nonbase=199,final_nonbase=141),
        sensitivity=dict(source_run=sa_manifest['run_id'],data_status=sa_manifest['data_status'],
          seasons=['XXQL2501','XXQL2601'],historical_screening_not_current_C31_local_sensitivity=True,
          later_single_season_run_not_used_in_C31_method_figure=newer_manifest['run_id']),
        ablation=dict(type='fixed_parameter_forward_comparison',refit_without_dynamic_partition=False,
          formal_refitted_ablation_pending=True),
        excluded_figure='Fig1_framework',retained_figure8_panels=['a','d'],
        weather_reference_default_path_exists=reference_wth.exists(),
        artifacts=[dict(path=f.name,sha256=sha(f)) for f in sorted(B.glob('*.csv'))],
        sources=[dict(path=p,sha256=h) for p,h in SOURCES.items()])
    (B/'paper_data_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    assert all(sha(ROOT/p)==h for p,h in SOURCES.items())
    (OUT/'source_hashes.json').write_text(json.dumps(SOURCES,ensure_ascii=False,indent=2),encoding='utf-8')
    verification=dict(status='passed_with_documented_scientific_limits',source_files_unchanged=True,
      roles=dict(calibration=13,held_out=10),pairs=len(pairs),terminal=len(terminal),
      true_replicate_se_pairs=int(pairs.observed_se.notna().sum()),daily_process_rows=len(daily),
      derived_LAI_pairs=int((pairs.observation_origin=='SLA_ratio_derived').sum()),
      management_event_totals_match=True,ensemble_final_nonbase=141,stage2_table_rows=[len(tab1),len(tab2),len(tab3)],
      no_DSSAT_or_PEST_run=True,scientific_status_promoted=False)
    (OUT/'data_verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(verification,ensure_ascii=True))

if __name__=='__main__':main()
