"""Read-only audit and adapters for the existing candidate diagnostic plotters."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration import sa98_joint40 as model
from src.calibration import single_season_n as native
from tools.calibration import plot_dynamics as plots

ID='eggplant_26sp_cal25sp_val_sa98_joint40_100x5_20261031'
RUN=ROOT/'workspace/runs'/ID
OUT=RUN/'result_review_20261031'
FIG=ROOT/'figture/sa98_joint40_global00032_two_spring_suite_20261031'
CONFIG=RUN/'source_snapshot/configs/runs'/ID
UNITS={'LAID':'m2/m2','LWAD':'kg DM/ha','SWAD':'kg DM/ha','CHTD':'m','CHPDT':'kg DM/ha','HPODW':'kg DM/ha',
       'CHFPW':'kg fresh/ha','HFPOW':'kg fresh/ha','LEAF_N_PCT':'% DM','STEM_N_PCT':'% DM','FRUIT_N_PCT':'% DM','VWC':'cm3/cm3','ADAP':'d'}


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,j):Path(p).write_text(json.dumps(j,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def metrics(q):
    g=q[q.comparison_status.eq('matched') & q.simulated.notna()].copy()
    m=plots._metrics(g.observed,g.simulated)
    if len(g):
        error=g.simulated-g.observed;m['MBE']=float(error.mean());m['mean_observed']=float(g.observed.mean());m['mean_simulated']=float(g.simulated.mean())
        assert np.isclose(m['RMSE'],np.sqrt(np.mean(error**2)))
    return {'n_expected':len(q),'n_unmatched':len(q)-len(g),**m}


def data():
    OUT.mkdir(exist_ok=True);FIG.mkdir(exist_ok=True)
    d=json.loads((CONFIG/'design.json').read_text(encoding='utf-8'));selected=pd.read_csv(RUN/'best_calibration_parameters.csv').set_index('name').value
    bounds=pd.read_csv(RUN/'source_snapshot/data/parameter_registry/bounds_frozen/eggplant'/f'{ID}.csv').fillna('')
    model.validate(selected.to_dict(),bounds)
    # Frozen evidence table; its content is hash-bound by the reviewed receipt.
    review=ROOT/'configs/calibration_proposals/eggplant_26sp_cal25sp_val_sa98_review_20261031'
    receipt=json.loads((review/'review_receipt.json').read_text(encoding='utf-8'))
    catalog=review/'observation_evidence_catalog.csv'
    assert sha(catalog)==receipt['artifact_hashes'][catalog.name]
    evidence=pd.read_csv(catalog).fillna('');pairframes=[];mapping=[];sources={}
    for ds in d['datasets']:
        s=ds['season_id'];work=RUN/('selected_deterministic/_model' if s=='26SP' else 'validation/_model')
        obs=evidence[evidence.season_id.eq(s)].copy();obs['obsnme']=[f'review_{s}_{i:04d}' for i in range(len(obs))]
        pairs=model.extract(work,obs,strict=False)
        pg=native.read_native(work/'PlantGro.OUT').reset_index()
        dap=pg[['trno','date','DAP']];pairs=pairs.merge(dap,on=['trno','date'],how='left',validate='many_to_one').rename(columns={'DAP':'dap'})
        # ADAP is an event timing scalar; its time coordinate is its observed DAP.
        pairs.loc[pairs.variable.eq('ADAP'),'dap']=pairs.loc[pairs.variable.eq('ADAP'),'observed']
        pairs['unit']=pairs.variable.map(UNITS);pairframes.append(pairs)
        meta=pd.read_csv(RUN/'source_snapshot'/ds['bundle_path']/'treatment_metadata.csv');meta['season_id']=s;meta['dataset_role']='calibration' if s=='26SP' else 'validation';mapping.append(meta)
        sdir=OUT/'_seasons'/s;sdir.mkdir(parents=True,exist_ok=True)
        # Reuse native files by path in the plotting adapter; do not modify originals.
        srcpg=plots._read_plantgro(str(work));srcfw=plots._read_freshwt(str(work))
        q=pairs[pairs.variable.isin(['LAID','LWAD','SWAD','CHTD'])].copy()
        q['DATE']=pd.to_datetime(q.date).dt.strftime('%y%j').astype(int)
        op=q.pivot(index=['trno','DATE'],columns='variable',values='observed').add_prefix('OBS_')
        sp=q.pivot(index=['trno','DATE'],columns='variable',values='simulated').add_prefix('SIM_')
        proc=op.join(sp).reset_index().rename(columns={'trno':'TN'})
        h=pairs[pairs.variable.isin(['CHPDT','CHFPW','HPODW','HFPOW'])].copy();h['DATE']=pd.to_datetime(h.date).dt.strftime('%y%j').astype(int)
        names={'CHPDT':'DRY_CUM','CHFPW':'FRESH_CUM','HPODW':'DRY_INC','HFPOW':'FRESH_INC'};h['kind']=h.variable.map(names)
        ho=h.pivot(index=['trno','DATE'],columns='kind',values='observed').add_prefix('OBS_');hs=h.pivot(index=['trno','DATE'],columns='kind',values='simulated').add_prefix('SIM_')
        harv=ho.join(hs).reset_index().rename(columns={'trno':'TN'}).sort_values(['TN','DATE']);harv['HNO']=harv.groupby('TN').cumcount()+1
        proc.to_csv(sdir/f'{s}_deterministic_process_compare.csv',index=False);harv.to_csv(sdir/f'{s}_deterministic_harvest_compare.csv',index=False)
        for f in ['PlantGro.OUT','PlantN.OUT','FreshWt.OUT','Evaluate.OUT','SoilWat.OUT','SOIL.SOL','fixed_input_audit.json']:
            sources[str((work/f).relative_to(ROOT)).replace('\\','/')]=sha(work/f)
    pairs=pd.concat(pairframes,ignore_index=True);meta=pd.concat(mapping,ignore_index=True)
    pairs=pairs.merge(meta[['season_id','treatment','water_level','nitrogen_level']],left_on=['season_id','trno'],right_on=['season_id','treatment'],validate='many_to_one')
    pairs.to_csv(OUT/'all_observed_simulated_pairs.csv',index=False,encoding='utf-8-sig');meta.to_csv(OUT/'treatment_metadata.csv',index=False,encoding='utf-8-sig')
    rows=[]
    for (s,role,var),q in pairs.groupby(['season_id','role','variable']):rows.append(dict(season_id=s,role=role,variable=var,unit=UNITS[var],**metrics(q)))
    pd.DataFrame(rows).to_csv(OUT/'variable_metrics.csv',index=False,encoding='utf-8-sig')
    terminal=pairs[pairs.variable.isin(['CHPDT','CHFPW'])].sort_values('date').groupby(['season_id','trno','variable']).tail(1)
    terminal.to_csv(OUT/'terminal_yield_pairs.csv',index=False,encoding='utf-8-sig')
    tmetrics=pd.DataFrame([dict(season_id=s,role=role,variable=var,**metrics(q)) for (s,role,var),q in terminal.groupby(['season_id','role','variable'])]);tmetrics.to_csv(OUT/'terminal_yield_metrics.csv',index=False)
    raw=pd.read_csv(RUN/'selected_deterministic/last_comparison.csv').fillna('')
    independently=(raw.simulated-raw.observed)/raw.sigma_eff;z=independently.copy();ix=raw.loss.eq('pseudo_huber');delta=pd.to_numeric(raw.loc[ix,'huber_delta'])
    # Independent direct pseudo-Huber formula rather than the runtime's algebraic encoding.
    loss=independently**2;loss.loc[ix]=2*delta**2*(np.hypot(1,independently.loc[ix]/delta)-1)
    phi=float((loss*raw.budget_multiplier**2).sum())
    assert np.isclose(phi,raw.phi_contribution.sum(),rtol=1e-12)
    family=[]
    for fam,q in raw.groupby('family'):
        family.append(dict(family=fam,variable=q.variable.iloc[0],budget=q.family_budget.iloc[0],phi=float(q.phi_contribution.sum()),**plots._metrics(q.observed,q.simulated,value_kind='signed' if fam.endswith('CONTRAST') else 'raw')))
    fm=pd.DataFrame(family);fm['phi_share_pct']=fm.phi/phi*100;fm.to_csv(OUT/'calibration_family_metrics.csv',index=False)
    # Recompute objective for each saved realization, keeping membership changes explicit.
    obs=pd.read_csv(CONFIG/'calibration_observations.csv');iterations=[];member_rows=[]
    for i in range(6):
        o=pd.read_csv(RUN/f'joint/joint.{i}.obs.csv',index_col=0);pa=pd.read_csv(RUN/f'joint/joint.{i}.par.csv',index_col=0)
        ph=np.square(o.loc[:,obs.obsnme].to_numpy()*obs.final_weight.to_numpy()).sum(axis=1)
        assert np.isfinite(ph).all()
        iterations.append(dict(iteration=i,n_obs_members=len(o),n_par_members=len(pa),phi_min=float(ph.min()),phi_median=float(np.median(ph)),phi_mean=float(ph.mean())))
        member_rows.extend(dict(iteration=i,realization=str(n),phi=float(v)) for n,v in zip(o.index,ph))
    it=pd.DataFrame(iterations);members=pd.DataFrame(member_rows);it.to_csv(OUT/'iteration_statistics.csv',index=False);members.to_csv(OUT/'member_phi.csv',index=False)
    final_names=set(members[members.iteration.eq(5)].realization);same=members[members.realization.isin(final_names)].groupby('iteration').phi.agg(['count','mean','median','min']);same.to_csv(OUT/'same_final40_member_phi_statistics.csv')
    a=bounds[bounds.status.eq('active')].copy();a['selected']=a.name.map(selected);a['position']=(a.selected-a.lower)/(a.upper-a.lower)
    for i in [4,5]:
        pa=pd.read_csv(RUN/f'joint/joint.{i}.par.csv',index_col=0)
        for row in a.itertuples():
            p=(pa[row.name.lower()]-row.lower)/(row.upper-row.lower)
            for label,mask in [('near_lower',p.le(.02)),('near_upper',p.ge(.98)),('severe_lower',p.le(.005)),('severe_upper',p.ge(.995))]:a.loc[a.name.eq(row.name),f'round{i}_{label}']=float(mask.mean())
    a['persistent_severe_lower']=a.round4_severe_lower.ge(.2)&a.round5_severe_lower.ge(.2)
    a['persistent_severe_upper']=a.round4_severe_upper.ge(.2)&a.round5_severe_upper.ge(.2)
    a.to_csv(OUT/'parameter_boundary_audit.csv',index=False,encoding='utf-8-sig')
    status=json.loads((RUN/'pipeline_status.json').read_text(encoding='utf-8'));selection=json.loads((RUN/'selection.json').read_text(encoding='utf-8'))
    gate=json.loads((RUN/'joint/ies_quality/ies_run_quality.json').read_text(encoding='utf-8'))
    summary=dict(run_id=ID,status=status,selection=selection,independently_recomputed_phi=phi,
        phi_relative_reproduction_error=abs(phi-selection['phi'])/selection['phi'],
        best_phi_reduction_from_initial_min_pct=100*(1-phi/it.phi_min.iloc[0]),
        retained_members=40,validation_rows=len(pairs[pairs.role.eq('validation')]),validation_unmatched=int((pairs.role.eq('validation')&pairs.comparison_status.ne('matched')).sum()),
        persistent_severe_parameters=a[a.persistent_severe_lower|a.persistent_severe_upper].name.tolist(),
        selected_near_boundary=a[a.position.le(.02)|a.position.ge(.98)].name.tolist(),
        failed_engineering_checks=[x for x in gate['checks'] if x['status']=='fail'],sources_sha256=sources,
        no_DSSAT_reruns=True,figure_directory=str(FIG))
    write(OUT/'review_summary.json',summary)
    print('TERMINAL METRICS\n'+tmetrics.to_string(index=False),flush=True)
    print('ITERATIONS\n'+it.to_string(index=False),flush=True)
    print('PERSISTENT BOUNDS',summary['persistent_severe_parameters'],flush=True)
    return pairs,meta


def render(pairs,meta,*,out=OUT,fig_dir=FIG,native_dirs=None,label='Joint40 / iter5 global_00032',
           footer='engineering gate FAILED: retained 40/100',
           run_id=ID,scientific_status='science_not_passed_engineering_gate',
           engineering_status='engineering_failed'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.figure
    # Preserve existing diagnostic renderers, adding a run-status footer at export.
    save=matplotlib.figure.Figure.savefig
    roles = {"25SP": "validation", "26SP": "calibration"}
    if "dataset_role" in meta:
        for s, group in meta.groupby("season_id"):
            roles[s], = group.dataset_role.unique()
    role_caption = "; ".join(f"20{s[:2]} {roles[s]}" for s in ("26SP", "25SP"))
    def reviewed_save(fig,*args,**kwargs):
        top=max([1.0]+[t.get_position()[1] for t in fig.texts])
        fig.text(.5,top+.085,f'Run diagnostics | {footer} | {role_caption}',
                 ha='center',fontsize=8,color='#A93226' if engineering_status=='engineering_failed' else '#475569')
        kwargs['dpi']=200;return save(fig,*args,**kwargs)
    matplotlib.figure.Figure.savefig=reviewed_save
    OUT,FIG=out,fig_dir
    if native_dirs is None:
        native_dirs={'25SP':RUN/'validation/_model','26SP':RUN/'selected_deterministic/_model'}
    plots.MAPPING_CSV=str(OUT/'treatment_metadata.csv');plots._INCLUDE_ALL_TREATMENTS=True
    plots._ALL_TREATMENT_IDS={s:set(q.treatment.astype(int)) for s,q in meta.groupby('season_id')}
    plots.WATER_ORDER=[w for w in plots.WATER_ORDER if w in set(meta.water_level)]
    plots.SEASON_LABELS.update({s: f"20{s[:2]} Spring ({role})" for s, role in roles.items()})
    allproc={};allharv={}
    for s,sub in pairs.groupby('season_id'):
        work=native_dirs[s]
        pg=plots._read_plantgro(str(work));fw=plots._read_freshwt(str(work));folder=OUT/'_seasons'/s
        common=dict(plantgro=pg,freshwt=fw,ref_year=2025 if s=='25SP' else 2026)
        allproc[s]=common|dict(compare=pd.read_csv(folder/f'{s}_deterministic_process_compare.csv'))
        allharv[s]=common|dict(compare=pd.read_csv(folder/f'{s}_deterministic_harvest_compare.csv'))
    for var in ['LAID','LWAD','SWAD']:
        plots._scatter_cross_season(allproc,'OBS_'+var,'SIM_'+var,var,str(FIG/f'diagnostic_scatter_{var}.png'),str(FIG/f'diagnostic_mse_decomposition_{var}.csv'))
        plots._residual_cross_season(allproc,'OBS_'+var,'SIM_'+var,var,str(FIG/f'diagnostic_residual_{var}.png'))
    for key,label in [('DRY_CUM','dry_cum'),('FRESH_CUM','fresh_cum')]:
        plots._scatter_cross_season(allharv,'OBS_'+key,'SIM_'+key,key,str(FIG/f'diagnostic_scatter_{label}.png'),str(FIG/f'diagnostic_mse_decomposition_{label}.csv'))
        plots._residual_cross_season(allharv,'OBS_'+key,'SIM_'+key,key,str(FIG/f'diagnostic_residual_{label}.png'))
    plots._response_structure_audit(allproc,allharv,str(FIG/'diagnostic_response_structure_audit.png'),str(FIG/'diagnostic_response_structure_audit.csv'))
    audit=[]
    for s in allproc:
        for v in ['LAID','LWAD','SWAD']:
            plots._plot_dynamics_single_season(allproc[s],s,v,'process',str(FIG/s/f'diagnostic_timeseries_{v}_by_WxN.png'),None,v+' ('+UNITS[v]+')',v+': daily simulation and observations')
        for key,label in [('cum_dry','dry_cum'),('cum_fresh','fresh_cum')]:
            plots._plot_dynamics_single_season(allharv[s],s,'DRY_CUM' if key=='cum_dry' else 'FRESH_CUM',key,str(FIG/s/f'diagnostic_timeseries_{label}_by_WxN.png'),None,'Cumulative harvest (kg/ha)','Native cumulative harvest: event-step',curve_audit=audit,harvest_curve='native')
        plots._increment_plot({s:allharv[s]},str(FIG/s/'diagnostic_dry_yield_increment.png'))
    pd.DataFrame(audit).to_csv(FIG/'diagnostic_yield_curve_source_audit.csv',index=False)
    from tools.calibration import plot_diagnostic_custom as custom
    terminal=pd.read_csv(OUT/'terminal_yield_pairs.csv');fresh=terminal[terminal.variable.eq('CHFPW')].copy()
    fresh=fresh.rename(columns={'season_id':'season','trno':'tn'});fresh['obs_t_ha']=fresh.observed/1000.;fresh['sim_t_ha']=fresh.simulated/1000.
    fresh.to_csv(OUT/'terminal_fresh_yield_for_plot.csv',index=False)
    custom.plot_candidate_nitrogen_response(OUT,label,FIG/'diagnostic_nitrogen_yield_response.png',mapping_csv=OUT/'treatment_metadata.csv',seasons=['25SP','26SP'],yield_csv=OUT/'terminal_fresh_yield_for_plot.csv')
    custom.plot_candidate_low_n_canopy(OUT,label,FIG/'diagnostic_low_n_canopy.png',mapping_csv=OUT/'treatment_metadata.csv',native_dirs=native_dirs,comparison=pairs)
    matplotlib.figure.Figure.savefig=save
    files=[p for p in FIG.rglob('*') if p.is_file() and p.name!='diagnostic_manifest.json']
    write(FIG/'diagnostic_manifest.json',dict(run_id=run_id,scientific_status=scientific_status,engineering_status=engineering_status,
        no_model_reruns=True,code_reused=['tools/calibration/plot_dynamics.py','tools/calibration/plot_diagnostic_custom.py'],
        metadata_sha256=sha(OUT/'treatment_metadata.csv'),pairs_sha256=sha(OUT/'all_observed_simulated_pairs.csv'),
        renderer_code_sha256={p:sha(ROOT/p) for p in ['tools/calibration/plot_dynamics.py','tools/calibration/plot_diagnostic_custom.py','tools/reporting/report_sa98_joint40_20261031.py']},
        artifacts=[dict(path=str(p.relative_to(FIG)),sha256=sha(p)) for p in files]))
    print('DIAGNOSTIC FIGURES',len(list(FIG.rglob('*.png'))),str(FIG),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-only',action='store_true');args=p.parse_args()
    pairs,meta=data()
    if not args.data_only:render(pairs,meta)
