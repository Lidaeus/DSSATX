"""Read-only C31 reconciliation and frozen inputs for paper reconstruction prototypes."""
from pathlib import Path
import hashlib
import json
import re
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.common.experiment_inputs import parse_filex

OUT=ROOT/'workspace/reviews/paper_stage01_20261031'
BUNDLE=OUT/'paper_data'
CASE='full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927'
RUN=ROOT/'workspace/runs'/CASE
OLD=ROOT/'workspace/reviews/paper_sections_audit_20261005'
PART=OLD/'xfint_xfpht_discussion'
SEASONS=['25SP','26SP']
SOURCES={}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def source(p):
    p=Path(p);SOURCES[p.relative_to(ROOT).as_posix()]=sha(p);return p
def read(p):return pd.read_csv(source(p))
def csv(df,name):
    df.to_csv(BUNDLE/name,index=False,encoding='utf-8-sig')
def parse_daily(path):
    source(path);rows=[];tn=None;header=None
    for line in path.read_text(encoding='utf-8-sig',errors='replace').splitlines():
        m=re.match(r'\s*TREATMENT\s+(\d+)\s*:',line)
        if m:tn=int(m[1]);header=None
        if line.startswith('@YEAR'):header=line[1:].split()
        elif header and re.match(r'\s*\d{4}\s+\d{3}\s',line):
            values=line.split();assert len(values)==len(header)
            row=dict(zip(header,map(float,values)));row['treatment']=tn
            row['date_full']=int(row['YEAR'])*1000+int(row['DOY']);rows.append(row)
    df=pd.DataFrame(rows);assert not df.duplicated(['treatment','date_full']).any()
    return df.set_index(['treatment','date_full']).sort_index()
def metrics(df):
    a=df.observed.to_numpy(float);b=df.simulated.to_numpy(float);err=b-a
    sst=np.sum((a-a.mean())**2);den=np.sum((np.abs(b-a.mean())+np.abs(a-a.mean()))**2)
    return dict(n=len(a),observed_mean=a.mean(),simulated_mean=b.mean(),rmse=np.sqrt(np.mean(err**2)),
        nrmse_pct=100*np.sqrt(np.mean(err**2))/a.mean() if a.mean() else np.nan,
        bias=err.mean(),mae=np.mean(abs(err)),r_squared=np.corrcoef(a,b)[0,1]**2 if len(a)>1 and np.std(a)>0 and np.std(b)>0 else np.nan,
        nse=1-np.sum(err**2)/sst if sst else np.nan,d_index=1-np.sum(err**2)/den if den else np.nan)
def full_date(date):return (2000+int(date)//1000)*1000+int(date)%1000
def shift(date,days):
    date=int(date);t=pd.Timestamp(year=date//1000,month=1,day=1)+pd.Timedelta(days=date%1000-1+days)
    return t.year*1000+t.dayofyear
def filex_rows(path,field):
    rows=[];header=[]
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if line.startswith('@'):header=line[1:].split()
        elif line.startswith('*'):header=[]
        elif field in header and line.strip() and not line.lstrip().startswith('!'):
            v=line.split()
            if len(v)>=len(header):rows.append(dict(zip(header,v)))
    return rows

def main():
    OUT.mkdir(parents=True,exist_ok=True);BUNDLE.mkdir(exist_ok=True)
    meta=read(ROOT/'paper/paper_data/conditional/treatment_metadata_two_season.csv')
    assert len(meta)==23 and not meta.duplicated(['season_id','treatment']).any()
    batch=source(RUN/'DSSBatch_calib_13trt.v48').read_text()
    mappings=[]
    for l in batch.splitlines():
        m=re.match(r'\s*(XXQL(2501|2601)\.TMX)\s+(\d+)',l)
        if m:mappings.append(dict(run_number=len(mappings)+1,season_id={'2501':'25SP','2601':'26SP'}[m[2]],treatment=int(m[3])))
    mapping=pd.DataFrame(mappings);assert len(mapping)==13
    pst_path=source(RUN/f'{CASE}.pst');pst=pst_path.read_text(encoding='utf-8-sig')
    obsblock=pst.split('* observation data')[1].split('*')[0]
    obs=pd.DataFrame([v for l in obsblock.splitlines() if len(v:=l.split())==4],columns=['name','observed','weight','group'])
    obs[['observed','weight']]=obs[['observed','weight']].astype(float)
    obs['run_number']=obs.name.str.extract(r'_r(\d+)').astype(int)
    obs=obs.merge(mapping,on='run_number',validate='many_to_one')
    assert len(obs)==455 and obs.weight.gt(0).all()
    obs['constraint_type']=np.where(obs.name.str.startswith('pen_'),'synthetic_constraint','measured_or_derived_target')
    csv(obs,'objective_observations.csv')
    counts=obs.groupby(['season_id','treatment']).agg(positive_objective_rows=('weight',lambda x:int(x.gt(0).sum()))).reset_index()
    roles=meta.merge(counts,on=['season_id','treatment'],how='left',validate='one_to_one').fillna({'positive_objective_rows':0})
    roles['positive_objective_rows']=roles.positive_objective_rows.astype(int)
    assert (roles.dataset_role.eq('calibration')==roles.positive_objective_rows.gt(0)).all()
    roles['evaluation_label_zh']=roles.dataset_role.map({'calibration':'率定处理','validation':'留出处理'})
    roles['independently_blind_verified']=False
    csv(roles,'treatment_role_audit.csv')
    group=obs.groupby(['constraint_type','group']).agg(n=('name','size'),weight_min=('weight','min'),weight_max=('weight','max')).reset_index()
    csv(group,'objective_group_audit.csv')

    parblock=pst.split('* parameter data')[1].split('*')[0]
    pars=pd.DataFrame([dict(parameter=v[0].upper(),transform=v[1],pst_initial=float(v[3]),working_lower=float(v[4]),working_upper=float(v[5]),parameter_group=v[6]) for l in parblock.splitlines() if len(v:=l.split())>=7])
    cand=read(ROOT/'workspace/candidates/candidate_c31_scheme1_dual_spring_precision/params.csv')
    cand['parameter']=cand.name.str.upper()
    frozen=read(ROOT/'data/parameter_registry/bounds_frozen/eggplant/eggplant_full_gen_final_calib_scheme1_tb1_200x6_20260927.csv')
    frozen['parameter']=frozen.name.str.upper()
    prior=read(RUN/f'{CASE}.0.par.csv');final=read(RUN/f'{CASE}.6.par.csv')
    nonbase=lambda d:d[~d.real_name.astype(str).str.lower().eq('base')]
    pr=nonbase(prior);po=nonbase(final)
    records=[]
    for row in pars.to_dict('records'):
        col=row['parameter'].lower();c=cand[cand.parameter.eq(row['parameter'])]
        row['c31_candidate_value']=c.value.iloc[0] if len(c)==1 else np.nan
        f=frozen[frozen.parameter.eq(row['parameter'])]
        for key in ['lower','upper','location','file']:
            row['frozen_'+key]=f[key].iloc[0] if len(f)==1 else None
        row['fixed_in_reference_ies']=row['transform']=='fixed'
        row['tomato_default_verified']=False
        if col in pr and col in po and row['transform']!='fixed':
            a=pr[col];b=po[col];tol=max(1e-10,1e-4*(row['working_upper']-row['working_lower']))
            row.update(ensemble_n=len(b),ensemble_nunique=b.nunique(),ensemble_q025=b.quantile(.025),ensemble_median=b.median(),ensemble_q975=b.quantile(.975),iqr_shrinkage=1-(b.quantile(.75)-b.quantile(.25))/(a.quantile(.75)-a.quantile(.25)),near_lower=float((abs(b-row['working_lower'])<=tol).mean()),near_upper=float((abs(b-row['working_upper'])<=tol).mean()))
        records.append(row)
    parameters=pd.DataFrame(records);csv(parameters,'parameter_reconciliation.csv')
    # Fixed-width model-readable ecotype values, separate from unrounded CSV values.
    eco=source(ROOT/'workspace/runs/c31_deterministic/_seasons/25SP/TMGRO048.ECO')
    line=next(l for l in eco.read_text().splitlines() if l.startswith('TM0001'))
    readable={k:float(line[a:b]) for k,a,b in [('XMAGE',126,132),('XFPHT',132,138),('XFINT',138,144)]}
    csv(pd.DataFrame([dict(parameter=k,c31_candidate_value=float(cand.set_index('parameter').loc[k,'value']),model_readable_value=v) for k,v in readable.items()]),'model_readable_key_parameters.csv')

    pairs=[];trajectory=[];management=[];weather=[];uncertainty=[];date_rows=[]
    for season in SEASONS:
        directory=ROOT/'workspace/runs/c31_deterministic/_seasons'/season
        ex={'25SP':'XXQL2501','26SP':'XXQL2601'}[season]
        filex=source(directory/f'{ex}.TMX');parsed=parse_filex(filex)
        irrigation=filex_rows(filex,'IDATE');fert=filex_rows(filex,'FDATE');planting=filex_rows(filex,'PDATE')
        plantdates={int(x['P']):int(x['PDATE']) for x in planting}
        for row in roles[roles.season_id.eq(season)].itertuples():
            factors=parsed['treatments'][row.treatment]
            irr=[x for x in irrigation if int(x['I'])==factors['MI']]
            fer=[x for x in fert if int(x['F'])==factors['MF']]
            management.append(dict(season_id=season,treatment=row.treatment,water_level=row.water_level,nitrogen_level=row.nitrogen_level,irrigation_mm=sum(float(x['IRVAL']) for x in irr),nitrogen_kg_ha=sum(float(x['FAMN']) for x in fer),irrigation_events=len(irr),nitrogen_positive_events=sum(float(x['FAMN'])>0 for x in fer),weather_station=parsed['weather_station'],planting_date=plantdates[factors['MP']],source_file=filex.relative_to(ROOT).as_posix()))
        station=parsed['weather_station'];wth=source(directory/f'{station}.WTH')
        head=[];wrows=[]
        for l in wth.read_text().splitlines():
            if l.startswith('@') and 'DATE' in l:head=l[1:].split()
            elif head and re.match(r'\s*\d{5,7}\s',l):
                v=l.split();wrows.append(dict(zip(head,v)))
        wf=pd.DataFrame(wrows);weather.append(dict(season_id=season,station=station,source_file=wth.relative_to(ROOT).as_posix(),n_days=len(wf),first_date=wf.DATE.iloc[0],last_date=wf.DATE.iloc[-1],columns=','.join(wf.columns),vpd_directly_available='VPD' in wf.columns))
        uncpath=directory/'observation_uncertainty.csv'
        if uncpath.exists():
            u=read(uncpath);u['audit_season']=season
            uncertainty.append(u)
        comparison=read(ROOT/'paper/paper_data'/season/'comparison.csv')
        for variant,subdir in [('baseline',directory),('disabled',ROOT/'workspace/runs/xf_partition_20261005'/f'constant_xfint1_{season}')]:
            plant=parse_daily(subdir/'PlantGro.OUT');fresh=parse_daily(subdir/'FreshWt.OUT')
            for variable in ['LAID','LWAD','SWAD','FRESH_CUM','FRESH_INC']:
                observations=comparison[comparison.variable.eq(variable)].copy()
                if not variable.startswith('FRESH'):observations=observations[observations.simulation_date_gap_days.eq(0)]
                for tn,g in observations.groupby('treatment'):
                    role=roles[(roles.season_id.eq(season)) & roles.treatment.eq(tn)].dataset_role.iloc[0]
                    for offset in ([0,1] if variable.startswith('FRESH') else [0]):
                        previous=0
                        for ob in g.sort_values('date_code').itertuples():
                            date=full_date(ob.date_code);wanted=shift(date,offset);used=wanted;gap=0
                            daily=fresh if variable.startswith('FRESH') else plant
                            if (int(tn),wanted) not in daily.index:
                                assert offset==1 and (int(tn),date) in daily.index
                                used=date;gap=-1
                            dr=daily.loc[(int(tn),used)]
                            if variable.startswith('FRESH'):
                                cumulative=dr.CHFPW/1000
                                simulated=cumulative-previous if variable=='FRESH_INC' else cumulative
                                previous=cumulative;observed=ob.observed/1000;unit='t ha-1'
                            else:simulated=dr[variable];observed=ob.observed;unit='m2 m-2' if variable=='LAID' else 'kg ha-1'
                            pairs.append(dict(season_id=season,treatment=int(tn),dataset_role=role,variant=variant,variable=variable,date_code=int(ob.date_code),dap=float(ob.dap),observed=observed,simulated=simulated,unit=unit,date_offset_days=offset,date_fallback_days=gap,source_file=(subdir/('FreshWt.OUT' if variable.startswith('FRESH') else 'PlantGro.OUT')).relative_to(ROOT).as_posix()))
                            if gap:date_rows.append(dict(season_id=season,treatment=int(tn),variant=variant,variable=variable,requested_date=wanted,used_date=used,gap_days=gap))
            # Daily continuous states for future full process plots; never sparse-data smoothing.
            selected=2 if season=='25SP' else 1
            d=plant.xs(selected,level='treatment')
            for date,row in d.iterrows():
                for v in ['LAID','LWAD','SWAD']:
                    trajectory.append(dict(season_id=season,treatment=selected,variant=variant,variable=v,dap=row.DAP,value=row[v],date_full=date))
    pairs=pd.DataFrame(pairs);csv(pairs,'evaluation_pairs.csv')
    csv(pd.DataFrame(trajectory),'daily_process_trajectories.csv')
    csv(pd.DataFrame(management),'management_audit.csv');csv(pd.DataFrame(weather),'weather_audit.csv')
    csv(pd.DataFrame(date_rows),'date_fallback_audit.csv')
    u=pd.concat(uncertainty,ignore_index=True)
    u['field_repeat_error_eligible']=u.sd_method.eq('replicate_sd') & u.n_rep.gt(1) & u.quality_flag.eq('ok')
    csv(u,'observation_uncertainty_audit.csv')
    summary=[]
    for (variant,season,offset,v),g in pairs.groupby(['variant','season_id','date_offset_days','variable']):
        for role,h in [('all',g),*list(g.groupby('dataset_role'))]:summary.append(dict(variant=variant,season_id=season,date_offset_days=offset,variable=v,dataset_role=role,**metrics(h)))
    term=pairs[pairs.variable.eq('FRESH_CUM')].sort_values('date_code').groupby(['variant','season_id','date_offset_days','treatment']).tail(1).copy()
    term['variable']='TERMINAL_FRESH'
    for (variant,offset),g0 in term.groupby(['variant','date_offset_days']):
        for season,g in [*list(g0.groupby('season_id')),('two_springs',g0)]:
            for role,h in [('all',g),*list(g.groupby('dataset_role'))]:summary.append(dict(variant=variant,season_id=season,date_offset_days=offset,variable='TERMINAL_FRESH',dataset_role=role,**metrics(h)))
    csv(term,'terminal_pairs.csv');summary=pd.DataFrame(summary);csv(summary,'performance_metrics.csv')
    main=pairs[pairs.variant.eq('baseline') & pairs.date_offset_days.eq(0)].copy()
    main=pd.concat([main,term[term.variant.eq('baseline') & term.date_offset_days.eq(0)]],ignore_index=True)
    assert not main.duplicated(['season_id','treatment','date_code','variable']).any()
    csv(main,'validation_sample_pairs.csv')
    # Reconcile same-day samples to prior audit independently reconstructed from PestHarvest.
    old=read(OLD/'revision_20261005/section_pairs_same_day.csv')
    checked=main[main.variable.ne('TERMINAL_FRESH')].merge(old,on=['treatment','date_code','variable'],suffixes=('','_previous'))
    checked=checked[checked.season_id.eq(checked.season)]
    assert len(checked)==len(main[main.variable.ne('TERMINAL_FRESH')])
    assert np.allclose(checked.simulated,checked.simulated_previous,atol=1e-9,rtol=0)
    archive=read(ROOT/'workspace/candidates/candidate_c31_scheme1_dual_spring_precision/all_35_treatments_final_yield.csv')
    check=term[(term.variant.eq('baseline')) & term.date_offset_days.eq(0)].merge(archive,left_on=['season_id','treatment'],right_on=['season','treatment'],validate='one_to_one')
    assert np.allclose(check.observed,check.obs_t_ha) and np.allclose(check.simulated,check.sim_t_ha)
    existing=read(PART/'comparison_pairs.csv')
    existing=existing[existing.season.isin(SEASONS) & existing.variant.isin(['baseline','constant_xfint1'])].copy()
    existing['variant']=existing.variant.replace({'constant_xfint1':'disabled'})
    checked=pairs.merge(existing,left_on=['season_id','treatment','date_code','variable','variant','date_offset_days'],right_on=['season','treatment','date_code','variable','variant','harvest_date_offset_days'],validate='one_to_one',suffixes=('','_previous'))
    assert len(checked)==len(pairs) and np.allclose(checked.simulated,checked.simulated_previous,atol=1e-9,rtol=0)
    # Frozen event trajectories, ordinary and monotone visual alternatives are rendered from these.
    events=pairs[pairs.variable.eq('FRESH_CUM') & pairs.date_offset_days.eq(0)].copy()
    events=events[((events.season_id.eq('25SP')) & events.treatment.eq(2)) | ((events.season_id.eq('26SP')) & events.treatment.eq(1))]
    csv(events,'ablation_events.csv')
    h=np.linspace(0,70,141)
    curve=pd.concat([pd.DataFrame(dict(photothermal_age=h,relative_potential_fraction=readable['XFINT']+(1-readable['XFINT'])*np.minimum(h/readable['XFPHT'],1),variant='baseline')),pd.DataFrame(dict(photothermal_age=h,relative_potential_fraction=np.ones(len(h)),variant='disabled'))])
    csv(curve,'partition_function.csv')
    # Deterministic representative and IES ensemble are intentionally distinct populations.
    membership=dict(initial_total=len(prior),initial_nonbase=len(pr),final_total=len(final),final_nonbase=len(po),member_policy='exclude base for revised ensemble statistics',deterministic_candidate='C31 / c28_scheme1_tb1_92',reference_ies=CASE,uncertainty_semantics='reference parameter-conditional ensemble; not a demonstrated full predictive distribution for C31')
    (OUT/'ensemble_membership.json').write_text(json.dumps(membership,ensure_ascii=False,indent=2),encoding='utf-8')
    # Explicit concept graph inputs, not inferred by R from raw files.
    nodes=[('source',.24,.86,'叶片光合\n可利用同化物','mechanism'),('vegetative',.12,.60,'叶、茎、根\n营养生长','mechanism'),('partition',.37,.60,'生殖分配潜在上限\nXFRT × 动态比例','mechanism'),('cohorts',.37,.34,'连续开花坐果\n多个果实队列','mechanism'),('harvest',.37,.10,'果龄条件 XMAGE\n＋输入采收安排','mechanism'),('env',.75,.88,'试验环境、管理与观测','workflow'),('sa',.75,.71,'Morris 全局敏感性筛选','workflow'),('pre',.75,.54,'物候→冠层→生物量→产量\n分过程预率定','workflow'),('ies',.75,.36,'PEST++ IES 联合更新\n参考批次：13 个率定处理','workflow'),('evaluate',.75,.16,'C31 确定性评价与前向对照\n留出评价＋条件集合诊断','workflow')]
    csv(pd.DataFrame(nodes,columns=['id','x','y','label','section']),'framework_nodes.csv')
    edges=[('source','vegetative'),('source','partition'),('partition','cohorts'),('cohorts','harvest'),('env','sa'),('sa','pre'),('pre','ies'),('ies','evaluate')]
    csv(pd.DataFrame(edges,columns=['from','to']),'framework_edges.csv')
    # Source provenance includes manuscript, actual run, candidates and reviewed mechanism implementation.
    for p in [ROOT/'paper/【排版】DSSAT茄子作物模型开发与验证-10.6.docx',RUN/'run_manifest.yaml',ROOT/f'configs/runs/{CASE}_design.json',PART/'comparison_verification.json',PART/'DEMAND_develop_snapshot.for',PART/'FreshWt_develop_snapshot.for',ROOT/'data/templates/genotype/TMGRO048.CUL.base',ROOT/'data/templates/genotype/TMGRO048.ECO.base']:
        source(p)
    source(OLD/'response_parameter_revision/kcan_verification.json')
    inventory_path=source(ROOT/'workspace/reviews/figure_system_plan_20261019/manuscript_inventory.json')
    inventory=json.loads(inventory_path.read_text(encoding='utf-8'))
    assert inventory['source_sha256']==sha(ROOT/'paper/【排版】DSSAT茄子作物模型开发与验证-10.6.docx')
    manifest=dict(schema_version=1,bundle_type='paper_reconstruction_prototypes',run_id='C31_reconciliation_stage01_20261031',data_status='audit_review_unvalidated',scenario_type='actual_trial_calibration',seasons=SEASONS,primary_date_policy='same observed day; DATE+1 sensitivity separately retained; scientific date reconciliation open',member_policy=membership,readable_parameters=readable,artifacts=[dict(path=p.name,sha256=sha(p)) for p in sorted(BUNDLE.glob('*.csv'))],sources=[dict(path=p,sha256=h) for p,h in SOURCES.items()],scientific_status_promoted=False)
    (BUNDLE/'paper_data_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    assert all(sha(ROOT/p)==h for p,h in SOURCES.items())
    (OUT/'source_hashes.json').write_text(json.dumps(SOURCES,indent=2),encoding='utf-8')
    receipt=dict(status='passed_with_documented_scientific_limits',source_files_unchanged=True,rate_treatments=13,held_out_treatments=10,positive_objective_rows=455,objective_rows_using_heldout_treatments=0,independently_blind_selection_proven=False,parameters=len(parameters),evaluation_pairs=len(pairs),independently_reproduced_previous_same_day_pairs=len(main[main.variable.ne('TERMINAL_FRESH')]),all_ablation_pairs_match_prior_audit=True,member_statistics=membership,model_readable=readable,scientific_status_promoted=False)
    (OUT/'stage0_verification.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
