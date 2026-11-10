"""Reproduce C16 manuscript inputs from the archived iter6/real_90 forwards.

No calibration, raw-data edits, or scientific-status promotion. Publication
rendering remains in R; plot_dynamics.py is the diagnostic renderer.
"""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import datetime as dt

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.reporting.analyze_results import deterministic_harvest_compare, deterministic_process_compare, deterministic_joint_compare
from src.reporting.export_paper_data import export_bundle
from src.reporting.figure_data import VARIABLE_SPECS, read_dssat_trajectories

CASE = 'full_gen_13trt_tb1_80_95_150x6'
RUN = ROOT / 'workspace/runs' / (CASE + '_20260920')
CAND = ROOT / 'workspace/candidates/candidate_c16_real90_strong_nresp'
SRC = ROOT / 'scratch/eval_new_tb1_150x6/run_new_iter6_real90'
OUT = ROOT / 'paper/06_C16_Revision_20260920'
DET = RUN / 'c16_deterministic'
SEASONS = ['25SP', '26SP', '25FA']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metric(o, s):
    o, s = np.asarray(o, float), np.asarray(s, float)
    e = s-o
    rmse = np.sqrt(np.mean(e**2))
    sst = np.sum((o-o.mean())**2)
    den = np.sum((abs(s-o.mean())+abs(o-o.mean()))**2)
    return dict(n=len(o), observed_mean=o.mean(), simulated_mean=s.mean(),
                rmse=rmse, nrmse_pct=100*rmse/o.mean(), bias=e.mean(), mae=np.mean(abs(e)),
                r_squared=np.corrcoef(o,s)[0,1]**2 if len(o)>1 and np.std(s)>0 else np.nan,
                nse=1-np.sum(e**2)/sst if sst else np.nan,
                d_index=1-np.sum(e**2)/den if den else np.nan)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data = OUT/'data'; data.mkdir(exist_ok=True)
    params = pd.read_csv(CAND/'params.csv').assign(name=lambda d:d.name.str.lower()).set_index('name').value
    ensemble = pd.read_csv(RUN/(CASE+'.6.par.csv'), index_col=0)
    ensemble.columns = ensemble.columns.str.lower()
    member = ensemble.loc['90'] if '90' in ensemble.index else ensemble.loc[90]
    common = params.index.intersection(member.index)
    assert len(common) >= 50
    # params.csv is a rounded export, so compare at its six-significant-figure precision.
    assert np.allclose(params.loc[common], member.loc[common].astype(float), rtol=6e-6, atol=6e-7)
    labels = pd.read_csv(CAND/'metrics_three_seasons.csv')
    meta = labels[['season','tn','water','nitro']].rename(columns={
        'season':'season_id','tn':'treatment','water':'water_level','nitro':'nitrogen_level'})
    split = pd.read_csv(ROOT/'configs/figures/treatment_metadata_xxql2501_2601_joint.csv')
    meta = meta.merge(split[['season_id','treatment','dataset_role']], on=['season_id','treatment'], how='left', validate='one_to_one')
    meta.loc[meta.season_id=='25FA','dataset_role']='diagnostic'
    assert meta.dataset_role.notna().all() and len(meta)==35
    meta['treatment_label'] = meta.apply(lambda r:f'TN{r.treatment} ({r.water_level}-{r.nitrogen_level})',axis=1)
    mapping = pd.read_csv(ROOT/'configs/runs/e02_from_scratch_water_n_mapping_20260826.csv')
    check = meta.merge(mapping, on=['season_id','treatment'], suffixes=('','_map'), how='left')
    matched = check.water_level_map.notna()
    assert (check.loc[matched,'water_level']==check.loc[matched,'water_level_map']).all()
    assert (check.loc[matched,'nitrogen_level']==check.loc[matched,'nitrogen_level_map']).all()
    meta.to_csv(data/'treatment_metadata.csv', index=False)
    y = pd.read_csv(CAND/'all_35_treatments_final_yield.csv').merge(meta,left_on=['season','tn'],right_on=['season_id','treatment'],validate='one_to_one')
    y['observed_t_ha']=y.obs_cum_yield_kg_ha/1000
    y['simulated_t_ha']=y.sim_cum_yield_kg_ha/1000
    y.to_csv(data/'terminal_yield_with_roles.csv',index=False)
    groups=[('calibration',y[y.dataset_role=='calibration']),('held_out_treatments',y[y.dataset_role=='validation']),('two_springs',y[y.season!='25FA']),*[(s,y[y.season==s]) for s in SEASONS],('all_35',y)]
    pd.DataFrame([dict(group=g,**metric(d.observed_t_ha,d.simulated_t_ha)) for g,d in groups]).to_csv(data/'terminal_yield_metrics.csv',index=False)
    contrasts=[]
    for (season,water),d in y[y.water_level!='CK'].groupby(['season','water_level']):
        d=d.set_index('nitrogen_level')
        for lo,hi in [('N0','N3'),('N0','N1'),('N1','N2'),('N2','N3')]:
            if lo not in d.index or hi not in d.index: continue
            og=d.loc[hi,'observed_t_ha']-d.loc[lo,'observed_t_ha']
            sg=d.loc[hi,'simulated_t_ha']-d.loc[lo,'simulated_t_ha']
            contrasts.append(dict(season=season,water=water,contrast=f'{hi}-{lo}',observed_gap=og,simulated_gap=sg,gap_bias=sg-og))
    pd.DataFrame(contrasts).to_csv(data/'nitrogen_contrasts.csv',index=False)
    all_comp=[]; input_hashes=[]; date_audits=[]
    for season in SEASONS:
        target=DET/'_seasons'/season
        if not target.exists(): shutil.copytree(SRC/season,target)
        for path in sorted((SRC/season).iterdir()):
            if path.is_file():
                assert sha(path)==sha(target/path.name), f'Archived input changed: {path}'
                input_hashes.append(dict(season=season,path=str(path),sha256=sha(path)))
        batch=target/('DSSBatch.v48' if season=='25SP' else f'DSSBatch_{season}_all.v48')
        for fun in [deterministic_harvest_compare,deterministic_process_compare,deterministic_joint_compare]:
            fun(season,str(batch),run_dir=str(target))
        sm=meta[meta.season_id==season].copy()
        sm.to_csv(data/f'{season}_treatment_metadata.csv',index=False)
        roles=sm.set_index('treatment').dataset_role.to_dict()
        records=[]
        for kind,variables in [('process',['LAID','LWAD','SWAD']),('harvest',['DRY_INC','DRY_CUM','FRESH_INC','FRESH_CUM'])]:
            path=target/f'{season}_deterministic_{kind}_compare.csv'
            frame=pd.read_csv(path)
            assert not frame.duplicated(['TN','DATE']).any()
            for row in frame.to_dict('records'):
                tn=int(row['TN'])
                if tn not in roles: raise ValueError(f'Unmapped treatment {season}/{tn}')
                date=int(row['DATE']); year=2000+date//1000; doy=date%1000
                for var in variables:
                    o,s=row[f'OBS_{var}'],row[f'SIM_{var}']
                    if not np.isfinite(o) or not np.isfinite(s) or o<0 or s<0: continue
                    spec=VARIABLE_SPECS[var]
                    records.append(dict(run_id=CASE,data_status='legacy_unvalidated',dataset_role=roles[tn],
                        variable=var,variable_label=spec['label'],unit=spec['unit'],treatment=str(tn),
                        time=doy,time_label='Day of year',observed=o,simulated=s,source_file=str(path),
                        date_code=date,year=year,doy=doy,dap=np.nan,harvest_number=row.get('HNO',np.nan),
                        observed_sd=np.nan,observed_se=np.nan,n_rep=np.nan,season_id=season))
        comp=pd.DataFrame(records)
        # Calendar DAP remains defined after daily output ends. Do not leave
        # January DOY=10 on a DAP axis or extrapolate simulated process values.
        daily=read_dssat_trajectories(target,run_id=CASE,data_status='legacy_unvalidated')
        def calendar(code):
            code=int(code)
            return dt.date(2000+code//1000,1,1)+dt.timedelta(days=code%1000-1)
        origins={}
        for tn,d in daily.groupby('treatment'):
            starts={calendar(r.date_code)-dt.timedelta(days=float(r.time)) for r in d.itertuples()}
            assert len(starts)==1,(season,tn,starts)
            origins[str(tn)]=starts.pop()
        comp['dap']=[(calendar(r.date_code)-origins[str(r.treatment)]).days for r in comp.itertuples()]
        comp['time']=comp.dap
        comp['time_label']='Days after planting'
        dates=pd.read_csv(target/f'{season}_deterministic_process_compare.csv')[['TN','DATE','SIM_DATE','SIM_DATE_GAP_DAYS']]
        dates.insert(0,'season_id',season);date_audits.append(dates)
        date_source=data/f'{season}_process_date_matching.csv'
        dates.to_csv(date_source,index=False)
        terminal=comp[comp.variable=='FRESH_CUM'].sort_values('date_code').groupby('treatment').tail(1)
        audit=terminal.assign(tn=terminal.treatment.astype(int)).merge(y[y.season==season],on='tn',validate='one_to_one')
        assert len(audit)==len(sm)
        assert np.allclose(audit.observed,audit.obs_cum_yield_kg_ha,atol=.11)
        assert np.allclose(audit.simulated,audit.sim_cum_yield_kg_ha,atol=.11)
        comp.to_csv(data/f'{season}_comparison_input.csv',index=False)
        bundle=OUT/'paper_data'/season
        export_bundle(run_id=CASE,out_dir=bundle,comparison_csv=data/f'{season}_comparison_input.csv',
            trajectory_run_dir=target,treatment_metadata_csv=data/f'{season}_treatment_metadata.csv',
            phi_csv=RUN/(CASE+'.phi.actual.csv'),allow_unvalidated_demo=True)
        # Freeze the explicit date-matching evidence as an optional extension.
        # R uses exact-date process pairs for performance/residual metrics while
        # dynamic panels retain every observed point at its true calendar DAP.
        frozen_comp=pd.read_csv(bundle/'comparison.csv')
        frozen_comp=frozen_comp.merge(dates.rename(columns={'TN':'treatment','DATE':'date_code',
            'SIM_DATE':'simulation_date_code','SIM_DATE_GAP_DAYS':'simulation_date_gap_days'}),
            on=['season_id','treatment','date_code'],how='left',validate='many_to_one')
        nonprocess=~frozen_comp.variable.isin(['LAID','LWAD','SWAD'])
        frozen_comp.loc[nonprocess,['simulation_date_code','simulation_date_gap_days']]=np.nan
        frozen_comp.to_csv(bundle/'comparison.csv',index=False)
        manifest_path=bundle/'paper_data_manifest.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        for artifact in manifest['artifacts']:
            if artifact['path']=='comparison.csv': artifact['sha256']=sha(bundle/'comparison.csv')
        manifest['sources'].append(dict(path=str(date_source),sha256=sha(date_source)))
        manifest['process_date_matching']='Metrics exclude nonzero simulation_date_gap_days; dynamics retain all observations without extending simulation.'
        manifest_path.write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        all_comp.append(frozen_comp)
    comparison=pd.concat(all_comp,ignore_index=True)
    date_audit=pd.concat(date_audits,ignore_index=True)
    date_audit.to_csv(data/'process_date_matching_audit.csv',index=False)
    comparison.to_csv(data/'three_season_comparison.csv',index=False)
    # For the main accuracy chart and W x N contrasts, one terminal node per season/treatment.
    terminal=comparison[comparison.variable.isin(['FRESH_CUM','DRY_CUM'])].sort_values('date_code').groupby(['season_id','treatment','variable']).tail(1)
    terminal.to_csv(data/'terminal_comparison_input.csv',index=False)
    export_bundle(run_id=CASE,out_dir=OUT/'paper_data/terminal',comparison_csv=data/'terminal_comparison_input.csv',
        treatment_metadata_csv=data/'treatment_metadata.csv',phi_csv=RUN/(CASE+'.phi.actual.csv'),allow_unvalidated_demo=True)
    processes=[]
    for (season,role,var),d in comparison.groupby(['season_id','dataset_role','variable']):
        factor=1000 if var.startswith(('FRESH','DRY')) else 1
        processes.append(dict(season=season,dataset_role=role,variable=var,**metric(d.observed/factor,d.simulated/factor)))
    pd.DataFrame(processes).to_csv(data/'process_metrics.csv',index=False)
    by_season=[]
    for (season,var),d in comparison.groupby(['season_id','variable']):
        factor=1000 if var.startswith(('FRESH','DRY')) else 1
        by_season.append(dict(season=season,variable=var,**metric(d.observed/factor,d.simulated/factor)))
    pd.DataFrame(by_season).to_csv(data/'process_metrics_by_season.csv',index=False)
    strict=comparison[comparison.variable.isin(['LAID','LWAD','SWAD'])].merge(date_audit,
        left_on=['season_id','treatment','date_code'],right_on=['season_id','TN','DATE'],validate='many_to_one')
    exact=[]
    for (season,var),d in strict[strict.SIM_DATE_GAP_DAYS==0].groupby(['season_id','variable']):
        exact.append(dict(season=season,variable=var,**metric(d.observed,d.simulated)))
    pd.DataFrame(exact).to_csv(data/'process_metrics_exact_dates.csv',index=False)
    water_contrasts=[]
    for (season,nitrogen),d in y[y.water_level!='CK'].groupby(['season','nitrogen_level']):
        d=d.set_index('water_level')
        for water in ['W2','W3']:
            if water not in d.index or 'W1' not in d.index: continue
            o=d.loc[water,'observed_t_ha']-d.loc['W1','observed_t_ha']
            s=d.loc[water,'simulated_t_ha']-d.loc['W1','simulated_t_ha']
            water_contrasts.append(dict(season=season,nitrogen=nitrogen,contrast=water+'-W1',observed_gap=o,simulated_gap=s,gap_bias=s-o))
    pd.DataFrame(water_contrasts).to_csv(data/'water_contrasts.csv',index=False)
    old=pd.read_csv(ROOT/'paper/05_Revision_Audit_20260920/nitrogen_contrasts_recomputed.csv')
    old=old.rename(columns={'simulated_gap':'c15_simulated_gap','gap_bias':'c15_gap_bias'})
    paired=pd.DataFrame(contrasts).merge(old[['season','water','contrast','c15_simulated_gap','c15_gap_bias']],
        on=['season','water','contrast'],validate='one_to_one')
    paired.to_csv(data/'C15_C16_nitrogen_contrasts.csv',index=False)
    frozen=ROOT/'data/parameter_registry/bounds_frozen/eggplant/eggplant_full_gen_tb1_80_95_13trt_20260920.csv'
    bounds=pd.read_csv(frozen); bounds['name']=bounds.name.str.lower()
    bounds=bounds.merge(params.rename('c16_value'),left_on='name',right_index=True,validate='one_to_one')
    bounds['fraction_in_range']=(bounds.c16_value-bounds.lower)/(bounds.upper-bounds.lower)
    assert ((bounds.c16_value>=bounds.lower-1e-5)&(bounds.c16_value<=bounds.upper+1e-5)).all()
    bounds.to_csv(data/'C16_parameters_with_bounds.csv',index=False)
    shutil.copy2(CAND/'params.csv',data/'C16_params.csv')
    pd.DataFrame(input_hashes).to_csv(data/'archived_forward_hashes.csv',index=False)
    audit=dict(candidate='C16',realization='real_90',iteration=6,run_id=CASE,matched_parameters=len(common),
        parameter_match_tolerance='rtol=6e-6, atol=6e-7 (rounded candidate CSV)',
        source_params_sha256=sha(CAND/'params.csv'),ensemble_sha256=sha(RUN/(CASE+'.6.par.csv')),
        deterministic_source=str(SRC),deterministic_archive=str(DET),terminal_pairs=35,
        data_status='legacy_layout_demo',publication_label_suppression='Explicitly requested by user on 2026-09-20; scientific status unchanged',
        observed_between_season_SST_fraction=float(sum(len(d)*(d.observed_t_ha.mean()-y.observed_t_ha.mean())**2 for _,d in y.groupby('season'))/sum((y.observed_t_ha-y.observed_t_ha.mean())**2)))
    (OUT/'provenance.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=True))


if __name__=='__main__': main()
