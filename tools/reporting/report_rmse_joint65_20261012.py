"""Audit the completed run and reuse figture diagnostic renderers, without rerunning calibration."""
from __future__ import annotations
from collections import Counter
import json
from pathlib import Path
import re
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration import rmse_joint as model
from src.calibration import water_n_joint as parent
from src.calibration import single_season_n as legacy
from tools.calibration import plot_dynamics as plot
from tools.calibration import evaluate_fixedsoil_official_best189_20260813 as heatmaps

ID='eggplant_26sp_n012_rmse_joint65_200x5_20261012'
RUN=ROOT/'workspace/runs'/ID
CONFIG=ROOT/'configs/runs'/ID
OUT=RUN/'result_review_20261012'
FIG=ROOT/'figture/rmse_joint65_200x5_20261012_local00086_diagnostic_suite'
CATALOG=ROOT/'configs/calibration_proposals/eggplant_26sp_n012_review_20261011/observation_catalog.csv'
LABELS={'CHPDT':'累计干采收','CHFPW':'累计鲜采收','HPODW':'分次干采收','HFPOW':'分次鲜采收','LAID':'LAI','LWAD':'叶干重','SWAD':'茎干重','CHTD':'株高','LEAF_N_PCT':'叶氮浓度','STEM_N_PCT':'茎氮浓度','FRUIT_N_PCT':'成熟果氮浓度代理','VWC':'土壤含水量','WB100_INTERVAL':'1m区间表观耗水','ADAP':'始花日','LNAM':'叶N质量（诊断）','SNAM':'茎N质量（诊断）'}
NATIVE_NAMES=['PlantGro','PlantN','FreshWt','SoilWat']
MAIN_ROLES={'26SP':'calibration','25SP':'validation','25FA':'validation'}


def save(frame,name):
    frame.to_csv(OUT/name,index=False,encoding='utf-8-sig')


def fit_metrics(q):
    kind='signed' if q.variable.iloc[0]=='WB100_INTERVAL' else 'state'
    m=plot._metrics(q.observed,q.simulated,value_kind=kind)
    good=np.isfinite(q.observed)&np.isfinite(q.simulated)
    if kind=='state':good&=q.observed.ge(0)&q.simulated.ge(0)
    g=q[good]
    mean=float(g.observed.mean()) if len(g) else np.nan
    m.update(n_total=len(q),n_unmatched=len(q)-len(g),unit=q.unit.iloc[0],observed_mean=mean,
        simulated_mean=float(g.simulated.mean()) if len(g) else np.nan,
        MBE=float((g.simulated-g.observed).mean()) if len(g) else np.nan,
        bias_pct=100*float((g.simulated-g.observed).mean())/abs(mean) if mean else np.nan)
    return m


def grouped_metrics(frame,keys):
    return pd.DataFrame([{**dict(zip(keys,k if isinstance(k,tuple) else (k,))),**fit_metrics(q)}
                         for k,q in frame.groupby(keys,sort=False,dropna=False)])


def prepare_data():
    OUT.mkdir(parents=True,exist_ok=True);FIG.mkdir(parents=True,exist_ok=True)
    design,bounds,obs=model.load_design(CONFIG/'design.json')
    status=json.loads((RUN/'pipeline_status.json').read_text(encoding='utf-8'))
    selection=json.loads((RUN/'selection.json').read_text(encoding='utf-8'))
    if status['status']!='completed' or 'analysis complete' not in (RUN/'joint/joint.rec').read_text(errors='replace').lower():
        raise ValueError('Completed PEST execution required')
    values=model.validate_parameters(legacy.runner._read_param_dict(RUN/'best_calibration_parameters.csv'),bounds)
    comparison=pd.read_csv(RUN/'selected_deterministic/last_comparison.csv').fillna('')
    independent=model.extract_observations(RUN/'selected_deterministic/_model',obs)
    if not np.allclose(comparison.simulated,independent.simulated,rtol=1e-12,atol=1e-10):raise ValueError('Native target reproduction failed')
    phi=float(np.square((comparison.simulated-comparison.observed)*comparison.final_weight).sum())
    if not np.isclose(phi,selection['deterministic_phi'],rtol=1e-12):raise ValueError('Selected Phi mismatch')
    candidates=pd.read_csv(RUN/'selection_audit.csv')
    if not np.isclose(phi,candidates.phi.min(),rtol=1e-12):raise ValueError('Representative is not fixed calibration minimum')
    metadata=[];frames={};native_paths=[]
    for dataset in design['datasets']:
        season=dataset['season_id']
        md=pd.read_csv(ROOT/dataset['bundle_path']/'treatment_metadata.csv').rename(columns={'treatment':'trno'})
        roles={tn:role for role,tns in dataset['roles'].items() for tn in tns}
        md=md[md.trno.isin(roles)].copy();md['dataset_role']=md.trno.map(roles);md['season_id']=season
        metadata.append(md)
        folders=[RUN/'evaluation'/season]
        if season=='26SP':folders.insert(0,RUN/'selected_deterministic/_model')
        frames[season]={}
        for name in NATIVE_NAMES:
            files=[folder/(name+'.OUT') for folder in folders];native_paths.extend(files)
            f=pd.concat([legacy.read_native(path) for path in files]).sort_index()
            if f.index.duplicated().any():raise ValueError('Duplicate treatment/date native trajectories')
            frames[season][name]=f
    meta=pd.concat(metadata,ignore_index=True)
    meta.to_csv(OUT/'treatment_metadata.csv',index=False)
    catalog=pd.read_csv(CATALOG).fillna('')
    raw=catalog[(catalog.season_id=='26SP') & catalog.dataset_role.eq('calibration')]
    raw=legacy.extract_observations(RUN/'selected_deterministic/_model',raw)
    specials=comparison[comparison.variable.isin(['ADAP','WB100_INTERVAL'])]
    evaluation=pd.read_csv(RUN/'evaluation_comparison.csv')
    # Independently reread every locked evaluation row on its actual date.
    checks=[]
    for season,q in evaluation.groupby('season_id'):
        native=RUN/'evaluation'/season
        reread=legacy.extract_evaluation_observations(native,q.drop(columns=['simulated']))
        if not np.allclose(q.simulated,reread.simulated,rtol=1e-12,atol=1e-10,equal_nan=True):raise ValueError('Evaluation native mismatch')
        checks.append(dict(season_id=season,total=len(q),matched=int(q.simulated.notna().sum())))
    pairs=pd.concat([raw,specials,evaluation],ignore_index=True).merge(meta[['season_id','trno','water_level','nitrogen_level']],on=['season_id','trno'],validate='many_to_one')
    # Retrospective 2025 ET is an external diagnostic, never in the fitted Phi.
    et_path=ROOT/'workspace/audits/observed_et_comparison_20261012/observed_ET_transcription.csv'
    et=pd.read_csv(et_path);extra=[]
    season='25SP';soil=frames[season]['SoilWat']
    text=(RUN/'evaluation'/season/'SoilWat.OUT').read_text()
    layerline=next(x for x in text.splitlines() if '0-5' in x)
    layers=[tuple(map(int,x)) for x in re.findall(r'(\d+)-(\d+)',layerline)]
    for md in meta[meta.season_id.eq(season)].itertuples():
        q=et[et.season_id.eq(season)&et.water_level.eq(md.water_level)&et.nitrogen_level.eq(md.nitrogen_level)&~et.phase.eq('total')]
        for r in q.itertuples():
            extra.append(dict(season_id=season,trno=md.trno,dataset_role=md.dataset_role,water_level=md.water_level,nitrogen_level=md.nitrogen_level,
                date=r.end,variable='WB100_INTERVAL',observed=r.observed_ET,simulated=parent.water_balance100(soil,md.trno,r.start,r.end,layers),unit='mm',
                interval_start=r.start,interval_end=r.end,source_file=str(et_path.relative_to(ROOT)),comparison_status='matched',evaluation_scope='retrospective_ET_diagnostic'))
    pairs=pd.concat([pairs,pd.DataFrame(extra)],ignore_index=True)
    # Reporting pairs are unweighted. Phi is independently recomputed from the
    # frozen 504-target catalog, never from diagnostic or validation weights.
    pairs['final_weight']=0.
    pairs['residual']=pairs.simulated-pairs.observed
    save(pairs,'comparison_all_roles.csv')
    family=grouped_metrics(comparison,['family','variable'])
    budgets=comparison.groupby('family',sort=False).phi_budget.first()
    family['budget']=family.family.map(budgets)
    fp=comparison.assign(phi_row=np.square((comparison.simulated-comparison.observed)*comparison.final_weight)).groupby('family').phi_row.sum()
    family['phi']=family.family.map(fp);family['phi_pct']=100*family.phi/phi
    save(family,'calibration_family_metrics_full.csv')
    metrics=grouped_metrics(pairs,['season_id','dataset_role','variable']);save(metrics,'metrics_by_season_role_variable.csv')
    treatment=grouped_metrics(pairs,['season_id','dataset_role','trno','water_level','nitrogen_level','variable'])
    save(treatment,'metrics_by_treatment_variable.csv')
    endpoints=pairs[pairs.variable.isin(['CHPDT','CHFPW'])].sort_values('date').groupby(['season_id','dataset_role','trno','variable']).tail(1).copy()
    save(endpoints,'terminal_yield_pairs.csv');save(grouped_metrics(endpoints,['season_id','dataset_role','variable']),'terminal_yield_metrics.csv')
    # Old starting point and selected candidate compared using the SAME new
    # raw metric definitions, not incomparable old Phi values.
    initial=pd.read_csv(RUN/'preflight/iter6_base/last_comparison.csv')
    im=grouped_metrics(initial,['family','variable'])
    delta=im.merge(family,on=['family','variable'],suffixes=('_initial','_selected'))
    delta['NRMSE_change_pp']=delta.RRMSE_selected-delta.RRMSE_initial
    save(delta,'initial_vs_selected_metrics_full.csv')
    param=bounds.copy();param['selected']=param.name.map(values)
    param['fraction_in_range']=(param.selected-param.lower)/(param.upper-param.lower).replace(0,np.nan)
    param['near_bound_2pct']=param.status.eq('active') & ((param.fraction_in_range<=.02)|(param.fraction_in_range>=.98))
    save(param,'parameter_bounds_review.csv')
    progress=[]
    for it in range(6):
        f=RUN/f'joint/joint.{it}.obs.csv';data=pd.read_csv(f,index_col=0)[obs.obsnme]
        v=np.square((data.to_numpy()-obs.observed.to_numpy())*obs.final_weight.to_numpy()).sum(axis=1)
        progress.append(dict(iteration=it,n=len(v),mean=float(np.mean(v)),min=float(np.min(v)),median=float(np.median(v)),
            q05=float(np.quantile(v,.05)),q25=float(np.quantile(v,.25)),q75=float(np.quantile(v,.75)),q95=float(np.quantile(v,.95))))
    save(pd.DataFrame(progress),'iteration_progress.csv')
    quality=json.loads((RUN/'joint/ies_quality/ies_run_quality.json').read_text(encoding='utf-8'))
    failures=Counter()
    for file in (RUN/'joint/_agents').glob('agent_*/panther_agent.stderr.log'):
        for line in file.read_text(errors='replace').splitlines():
            if re.match(r'^(ValueError|RuntimeError|KeyError|OSError):',line):
                if 'No mature fruit' in line and 'treatment=' not in line:continue
                kind='NoMatureFruit' if 'No mature fruit' in line else line.split(';')[0]
                failures[kind]+=1
    save(pd.DataFrame([dict(reason=k,exception_event_count=v) for k,v in failures.items()]),'forward_failure_events.csv')
    sources=[CONFIG/'design.json',CONFIG/'calibration_observations.csv',RUN/'best_calibration_parameters.csv',RUN/'selection.json',RUN/'selection_audit.csv',
        RUN/'selected_deterministic/last_comparison.csv',RUN/'evaluation_comparison.csv',RUN/'pipeline_status.json',
        RUN/'joint/ies_quality/ies_run_quality.json',RUN/'joint/ies_quality/joint.member_status.csv',CATALOG,et_path]+native_paths
    hashes={str(p.relative_to(ROOT)).replace('\\','/'):legacy.sha(p) for p in sources}
    summary=dict(run_id=ID,selection=selection,pipeline=status,selected_phi=phi,initial_reference_phi=float(np.square((initial.simulated-initial.observed)*initial.final_weight).sum()),
        iteration_progress=progress,quality_failures=[x for x in quality['checks'] if x['status']=='fail'],failure_exception_events=dict(failures),
        exception_count_note='includes rejected trial calls and retries; not unique lost members',evaluation_coverage=checks,
        near_bound_active_parameters=int(param.near_bound_2pct.sum()),source_hashes=hashes,fit_definition='NRMSE/RRMSE=100*RMSE/abs(mean observed); R2=squared Pearson correlation; residual=simulated-observed',
        rendering='Python runtime diagnostics only; no publication Fig/FigS',scientific_status='science_not_passed_engineering_gate')
    legacy.write_json(OUT/'result_summary.json',summary)
    return design,pairs,frames,meta,family,metrics,endpoints,summary


def wide(q):
    q=q.copy();q['TN']=q.trno.astype(int)
    q['DATE']=[int(pd.Timestamp(x).strftime('%y%j')) for x in q.date]
    basecols=['TN','DATE']
    if q.variable.eq('VWC').any():basecols+=['depth_label']
    if q.duplicated(basecols+['variable']).any():raise ValueError('Ambiguous wide comparison')
    o=q.pivot(index=basecols,columns='variable',values='observed').add_prefix('OBS_')
    s=q.pivot(index=basecols,columns='variable',values='simulated').add_prefix('SIM_')
    return o.join(s).reset_index()


def plot_harvest_facets(pairs,frames,season,var,smooth):
    """Reuse legacy W/N layout, but show harvested cumulative nodes faithfully."""
    q=pairs[pairs.season_id.eq(season)&pairs.variable.eq(var)]
    cells=[x for x in plot._wn_grid(season) if x[2][0] in set(q.trno)]
    ncols=min(4,len(cells));nrows=int(np.ceil(len(cells)/ncols))
    fig,axs=plt.subplots(nrows,ncols,figsize=(3.4*ncols,2.8*nrows),sharex=True,sharey=True)
    axs=np.asarray(axs).reshape(-1)
    source=[]
    for ax,(w,n,tns) in zip(axs,cells):
        tn=tns[0];g=q[q.trno.eq(tn)].sort_values('date');mk,col=plot._style_for((w,n))
        daily=frames[season]['FreshWt'].loc[tn]
        x=np.array([float(daily.loc[d,'DAP']) for d in g.date]);y=g.simulated.to_numpy(float)
        if (np.diff(x)<=0).any() or (np.diff(y)<-1e-8).any():raise ValueError('Invalid cumulative interpolation nodes')
        if smooth and len(x)>=2:
            xx=np.linspace(x.min(),x.max(),300);yy=PchipInterpolator(x,y,extrapolate=False)(xx)
            if (np.diff(yy)<-1e-6).any():raise ValueError('Nonmonotone visual interpolation')
            ax.plot(xx,yy,color='#1f3a93',lw=1.3)
        else:ax.plot(x,y,color='#1f3a93',lw=1.3)
        ax.scatter(x,g.observed,marker=mk,c=col,edgecolors='k',s=24,zorder=5)
        ax.set_title(f'{w} × {n} ({g.dataset_role.iloc[0]})',fontsize=8.5);ax.grid(alpha=.22)
        ax.tick_params(labelsize=8);ax.spines[['top','right']].set_visible(False)
        for r,xx in zip(g.itertuples(),x):source.append(dict(season_id=season,trno=tn,dataset_role=r.dataset_role,date=r.date,DAP=xx,variable=var,observed=r.observed,simulated=r.simulated))
    for ax in axs[len(cells):]:ax.axis('off')
    for ax in axs[-ncols:]:ax.set_xlabel('Days after planting',fontsize=9)
    for ax in axs[::ncols]:ax.set_ylabel('Cumulative harvest (kg/ha)',fontsize=9)
    title='Monotone PCHIP of harvest nodes (visual only)' if smooth else 'Line connecting raw simulated harvest nodes'
    fig.suptitle(f'Diagnostic {season}: {var} — {title}',fontsize=11)
    from matplotlib.lines import Line2D
    h=[Line2D([0],[0],color='#1f3a93',label='Simulated'),Line2D([0],[0],marker='o',color='k',ls='',label='Observed means (no uncertainty bars)')]
    fig.legend(handles=h,loc='lower center',ncol=2,fontsize=8)
    fig.tight_layout(rect=[0,.05,1,.95])
    folder=FIG/season;folder.mkdir(exist_ok=True)
    file=folder/f'diagnostic_timeseries_{var}_{"monotone_visual" if smooth else "event_line"}.png'
    fig.savefig(file,dpi=150,bbox_inches='tight');plt.close(fig)
    pd.DataFrame(source).to_csv(file.with_suffix('.source.csv'),index=False)
    return file


def render(design,pairs,frames,meta,metrics,endpoints):
    plot.MAPPING_CSV=str(OUT/'treatment_metadata.csv')
    md=meta.rename(columns={'trno':'treatment'})
    md.to_csv(OUT/'treatment_metadata.csv',index=False)
    plot._ALL_TREATMENT_IDS={s:set(g.treatment) for s,g in md.groupby('season_id')}
    plot._INCLUDE_ALL_TREATMENTS=True
    plot.SEASON_LABELS={'26SP':'2026 Spring | calibration N0–N2', '25SP':'2025 Spring | validation', '25FA':'2025 Autumn | validation'}
    old_unit=plot._var_unit
    units={'CHPDT':'kg DM/ha','CHFPW':'kg fresh/ha','HPODW':'kg DM/ha','HFPOW':'kg fresh/ha','CHTD':'m',
        'LEAF_N_PCT':'% dry mass','STEM_N_PCT':'% dry mass','FRUIT_N_PCT':'% dry mass','LNAM':'kg N/ha','SNAM':'kg N/ha','VWC':'cm³/cm³','WB100_INTERVAL':'mm'}
    plot._var_unit=lambda v:units.get(str(v).replace('OBS_','').replace('SIM_',''),old_unit(v))
    primary=pairs[pairs.dataset_role.eq(pairs.season_id.map(MAIN_ROLES))]
    chartvars=list(LABELS.keys())
    for var in chartvars:
        if var=='ADAP':continue
        data={}
        for season,q in primary[primary.variable.eq(var)].groupby('season_id'):
            if q.simulated.notna().any():data[season]={'compare':wide(q)}
        if not data:continue
        plot._scatter_cross_season(data,'OBS_'+var,'SIM_'+var,var,str(FIG/f'diagnostic_scatter_{var}.png'),str(FIG/f'diagnostic_mse_decomposition_{var}.csv'))
        plot._residual_cross_season(data,'OBS_'+var,'SIM_'+var,var,str(FIG/f'diagnostic_residual_{var}.png'))
        print('Rendered paired diagnostics:',var,flush=True)
    for var in ['CHPDT','CHFPW']:
        data={s:{'compare':wide(q)} for s,q in endpoints[endpoints.variable.eq(var)&endpoints.dataset_role.eq(endpoints.season_id.map(MAIN_ROLES))].groupby('season_id')}
        plot._scatter_cross_season(data,'OBS_'+var,'SIM_'+var,'FINAL_'+var,str(FIG/f'diagnostic_scatter_FINAL_{var}.png'),str(FIG/f'diagnostic_mse_FINAL_{var}.csv'))
        secondary={s:{'compare':wide(q)} for s,q in endpoints[endpoints.variable.eq(var)&~endpoints.dataset_role.eq(endpoints.season_id.map(MAIN_ROLES))].groupby('season_id')}
        plot.SEASON_LABELS.update({'26SP':'2026 Spring | N3 holdout','25FA':'2025 Autumn | W2 diagnostic'})
        plot._scatter_cross_season(secondary,'OBS_'+var,'SIM_'+var,'FINAL_'+var,str(FIG/f'diagnostic_scatter_SECONDARY_FINAL_{var}.png'),str(FIG/f'diagnostic_mse_SECONDARY_FINAL_{var}.csv'))
        plot.SEASON_LABELS.update({'26SP':'2026 Spring | calibration N0–N2','25FA':'2025 Autumn | validation'})
    for season in frames:
        folder=FIG/season;folder.mkdir(exist_ok=True)
        pg=frames[season]['PlantGro'].copy()
        pn=frames[season]['PlantN']
        pg['LEAF_N_PCT']=pn['LN%D'];pg['STEM_N_PCT']=pn['SN%D']
        pg=pg.reset_index().rename(columns={'trno':'TN'})
        q=pairs[pairs.season_id.eq(season)&pairs.variable.isin(['LAID','LWAD','SWAD','CHTD','LEAF_N_PCT','STEM_N_PCT'])]
        sd={'plantgro':pg,'compare':wide(q)}
        plot.SEASON_LABELS[season]={'26SP':'2026 Spring: N0–N2 calibration; N3 holdout','25FA':'2025 Autumn: W1/W3 validation; W2 diagnostic','25SP':'2025 Spring: validation W1/W3'}[season]
        for var in ['LAID','LWAD','SWAD','CHTD','LEAF_N_PCT','STEM_N_PCT']:
            plot._plot_dynamics_single_season(sd,season,var,'process',str(folder/f'diagnostic_timeseries_{var}_by_WxN.png'),None,units.get(var,old_unit(var)),f'{var}: daily model line and observed mean points')
        for var in ['CHPDT','CHFPW']:
            for smooth in [False,True]:plot_harvest_facets(pairs,frames,season,var,smooth)
        inc=pairs[pairs.season_id.eq(season)&pairs.variable.eq('HPODW')].copy()
        inc['HNO']=inc.groupby('trno').date.rank(method='dense').astype(int)
        x=wide(inc);x=x.merge(inc.assign(TN=inc.trno.astype(int),DATE=[int(pd.Timestamp(d).strftime('%y%j')) for d in inc.date])[['TN','DATE','HNO']],on=['TN','DATE'],validate='one_to_one')
        x=x.rename(columns={'OBS_HPODW':'OBS_DRY_INC','SIM_HPODW':'SIM_DRY_INC'})
        plot._increment_plot({season:{'compare':x}},str(folder/'diagnostic_bar_dry_yield_increment.png'))
        print('Rendered daily/harvest diagnostics:',season,flush=True)
    hm=metrics[metrics.dataset_role.eq(metrics.season_id.map(MAIN_ROLES)) & ~metrics.variable.isin(['ADAP'])].copy()
    hm=hm.rename(columns={'season_id':'season','RRMSE':'rrmse_pct','R2':'r2','NSE':'nse','d':'d_index'})
    heatmaps.SEASON_IDS=['25SP','26SP','25FA'];heatmaps.COLORS={'25SP':'#2878B5','26SP':'#c0392b','25FA':'#2A9D55'}
    for file in heatmaps._plot_metrics(hm,FIG):file.rename(file.with_name('diagnostic_'+file.name))
    progress=pd.read_csv(OUT/'iteration_progress.csv')
    fig,axs=plt.subplots(1,2,figsize=(10.5,4))
    x=progress.iteration.to_numpy()
    axs[0].fill_between(x,progress.q05,progress.q95,color='#2980b9',alpha=.12,label='5–95%')
    axs[0].fill_between(x,progress.q25,progress.q75,color='#2980b9',alpha=.25,label='IQR')
    axs[0].plot(x,progress['median'],color='#2980b9',label='Median')
    axs[0].plot(x,progress['min'],color='#e67e22',marker='o',label='Minimum')
    axs[0].set_yscale('log');axs[0].set_ylabel(f"Fixed {design['target_count']}-target Phi");axs[0].legend(fontsize=8)
    axs[1].plot(x,progress.n,marker='o',color='#2980b9');axs[1].axhline(196,color='gray',ls='--',label='98% gate (196/200)')
    axs[1].set_ylim(0,210);axs[1].set_ylabel('Retained members');axs[1].legend(fontsize=8)
    for ax in axs:ax.set_xlabel('Iteration (0 = initial)');ax.grid(alpha=.2)
    fig.suptitle('Diagnostic optimization and member retention');fig.tight_layout();fig.savefig(FIG/'diagnostic_phi_progress.png',dpi=150);plt.close(fig)
    plot.SEASON_LABELS={'25SP':'2025 Spring | validation','26SP':'2026 Spring | calibration N0–N2','25FA':'2025 Autumn | validation'}
    proc={s:{'compare':wide(g)} for s,g in primary[primary.variable.eq('LAID')].groupby('season_id')}
    harv={s:{'compare':wide(g).rename(columns={'OBS_CHPDT':'OBS_DRY_CUM','SIM_CHPDT':'SIM_DRY_CUM'})}
          for s,g in primary[primary.variable.eq('CHPDT')].groupby('season_id')}
    plot._response_structure_audit(proc,harv,str(FIG/'diagnostic_response_structure_audit.png'),str(FIG/'diagnostic_response_structure_audit.csv'))


def response_tables(endpoints):
    terminal=endpoints[endpoints.variable.eq('CHFPW')]
    rows=[]
    for season,g in terminal.groupby('season_id'):
        for nitrogen,q in g.groupby('nitrogen_level'):
            levels=q.set_index('water_level')
            for high in ['W2','W3']:
                if high not in levels.index or 'W1' not in levels.index:continue
                a,b=levels.loc[high],levels.loc['W1']
                if a.date!=b.date:raise ValueError('Water contrast date mismatch')
                rows.append(dict(season_id=season,contrast_type='W',stratum=nitrogen,contrast=high+'-W1',dataset_role=a.dataset_role if a.dataset_role==b.dataset_role else 'mixed_diagnostic',
                    observed=a.observed-b.observed,simulated=a.simulated-b.simulated))
        for water,q in g.groupby('water_level'):
            levels=q.set_index('nitrogen_level')
            for low,high in [('N0','N1'),('N0','N2'),('N1','N2'),('N2','N3')]:
                if high not in levels.index or low not in levels.index:continue
                a,b=levels.loc[high],levels.loc[low]
                if a.date!=b.date:raise ValueError('N contrast date mismatch')
                rows.append(dict(season_id=season,contrast_type='N',stratum=water,contrast=high+'-'+low,dataset_role=a.dataset_role if a.dataset_role==b.dataset_role else 'mixed_diagnostic',
                    observed=a.observed-b.observed,simulated=a.simulated-b.simulated))
    out=pd.DataFrame(rows)
    out['residual']=out.simulated-out.observed;out['ratio']=out.simulated/out.observed.replace(0,np.nan)
    out['sign_agreement']=(np.sign(out.observed)==np.sign(out.simulated)).where(out.observed.abs()>1e-8)
    save(out,'signed_water_n_response.csv')
    return out


def main():
    design,pairs,frames,meta,family,metrics,endpoints,summary=prepare_data()
    responses=response_tables(endpoints)
    render(design,pairs,frames,meta,metrics,endpoints)
    for rel,digest in summary['source_hashes'].items():
        if legacy.sha(ROOT/rel)!=digest:raise ValueError('Read-only source changed: '+rel)
    manifest=dict(run_id=ID,selected_iteration=summary['selection']['iteration'],selected_realization=summary['selection']['realization'],
        artifact_type='runtime_diagnostics',engineering_status='engineering_failed',scientific_status='science_not_passed_engineering_gate',
        mapping_source=str((OUT/'treatment_metadata.csv').relative_to(ROOT)),uncertainty_bars='none; no audited SE fabricated from SD',
        cumulative_curves='event-node ordinary line and monotone PCHIP visual-only alternative; statistics use raw pairs',
        code_reuse=['tools/calibration/plot_dynamics.py','tools/calibration/evaluate_fixedsoil_official_best189_20260813.py:_plot_metrics'],
        artifacts={str(p.relative_to(FIG)).replace('\\','/'):legacy.sha(p) for p in FIG.rglob('*') if p.is_file()})
    legacy.write_json(FIG/'diagnostic_manifest.json',manifest)
    print(json.dumps(dict(status='diagnostics_rendered',png_count=len(list(FIG.rglob('*.png'))),selected_phi=summary['selected_phi'],figure_root=str(FIG)),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
