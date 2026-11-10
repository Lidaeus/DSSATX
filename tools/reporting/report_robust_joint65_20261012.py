"""Read-only robust-run review, reusing the existing figture diagnostic renderer."""
from __future__ import annotations
from collections import Counter
import html
import json
from pathlib import Path
import re
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration import robust_joint as model
from src.calibration import single_season_n as legacy
from src.calibration import water_n_joint as parent
from tools.reporting import report_rmse_joint65_20261012 as renderer

ID='eggplant_26sp_n012_robust_joint65_200x5_20261012'
RUN=ROOT/'workspace/runs'/ID
CONFIG=ROOT/'configs/runs'/ID
OUT=RUN/'result_review_20261012'
FIG=ROOT/'figture/robust_joint65_200x5_20261012_local00129_diagnostic_suite'
REPORT=ROOT/'docs/reports/稳健目标65参数联合率定_200x5结果报告_20261012.md'
PRIOR=ROOT/'workspace/runs/eggplant_26sp_n012_rmse_joint65_200x5_20261012/result_review_20261012'
CATALOG=renderer.CATALOG
renderer.ID=ID;renderer.RUN=RUN;renderer.CONFIG=CONFIG;renderer.OUT=OUT;renderer.FIG=FIG

def fit_metrics(q):
    kind='signed' if q.variable.iloc[0] in model.SIGNED else 'state'
    m=renderer.plot._metrics(q.observed,q.simulated,value_kind=kind)
    valid=np.isfinite(q.observed)&np.isfinite(q.simulated)
    if kind=='state':valid&=q.observed.ge(0)&q.simulated.ge(0)
    g=q[valid];mean=float(g.observed.mean()) if len(g) else np.nan
    m.update(n_total=len(q),n_unmatched=len(q)-len(g),unit=q.unit.iloc[0],observed_mean=mean,
        simulated_mean=float(g.simulated.mean()) if len(g) else np.nan,
        MBE=float((g.simulated-g.observed).mean()) if len(g) else np.nan,
        bias_pct=100*float((g.simulated-g.observed).mean())/abs(mean) if mean else np.nan)
    return m

renderer.fit_metrics=fit_metrics
grouped=renderer.grouped_metrics
save=renderer.save

def prepare_data():
    OUT.mkdir(parents=True,exist_ok=True);FIG.mkdir(parents=True,exist_ok=True)
    d,bounds,obs=model.load_design(CONFIG/'design.json')
    status=json.loads((RUN/'pipeline_status.json').read_text(encoding='utf-8'))
    selection=json.loads((RUN/'selection.json').read_text(encoding='utf-8'))
    if status['status']!='completed' or 'analysis complete' not in (RUN/'joint/joint.rec').read_text(errors='replace').lower():raise ValueError('Completed IES required')
    values=model.validate_parameters(legacy.runner._read_param_dict(RUN/'best_calibration_parameters.csv'),bounds)
    compared=pd.read_csv(RUN/'selected_deterministic/last_comparison.csv').fillna('')
    independent=model.encode(model.extract_observations(RUN/'selected_deterministic/_model',obs))
    if not np.allclose(compared.simulated,independent.simulated,rtol=1e-12,atol=1e-10):raise ValueError('Native raw target reproduction failed')
    if not np.allclose(compared.pest_output,independent.pest_output,rtol=1e-12,atol=1e-12):raise ValueError('Robust encoding mismatch')
    phi=float(independent.phi_contribution.sum())
    assert np.isclose(phi,selection['deterministic_phi'],rtol=1e-12)
    candidates=pd.read_csv(RUN/'selection_audit.csv')
    if not np.isclose(selection['phi'],candidates.phi.min(),rtol=1e-12):raise ValueError('Selected ensemble member is not minimum fixed Phi')
    member=pd.read_csv(RUN/f"joint/joint.{selection['iteration']}.obs.csv",index_col=0).loc[selection['realization'],obs.obsnme].to_numpy(float)
    encoded_difference=independent.pest_output.to_numpy()-member
    if not np.isclose(phi,selection['phi'],rtol=1e-6,atol=1e-8):raise ValueError('Deterministic Phi outside declared reproduction tolerance')
    metadata=[];frames={};native_paths=[]
    for dataset in d['datasets']:
        season=dataset['season_id'];md=pd.read_csv(ROOT/dataset['bundle_path']/'treatment_metadata.csv').rename(columns={'treatment':'trno'})
        roles={t:role for role,ts in dataset['roles'].items() for t in ts}
        md=md[md.trno.isin(roles)].copy();md['dataset_role']=md.trno.map(roles);md['season_id']=season;metadata.append(md)
        folders=[RUN/'evaluation'/season]
        if season=='26SP':folders.insert(0,RUN/'selected_deterministic/_model')
        frames[season]={}
        for name in renderer.NATIVE_NAMES:
            files=[folder/(name+'.OUT') for folder in folders];native_paths+=files
            frame=pd.concat([legacy.read_native(f) for f in files]).sort_index()
            if frame.index.duplicated().any():raise ValueError('Duplicate native treatment/date')
            frames[season][name]=frame
    meta=pd.concat(metadata,ignore_index=True)
    catalog=pd.read_csv(CATALOG).fillna('')
    raw=catalog[catalog.season_id.eq('26SP')&catalog.dataset_role.eq('calibration')]
    raw=legacy.extract_observations(RUN/'selected_deterministic/_model',raw)
    specials=compared[compared.variable.isin(['ADAP','WB100_INTERVAL'])]
    evaluation=pd.read_csv(RUN/'evaluation_comparison.csv');checks=[]
    for season,q in evaluation.groupby('season_id',sort=False):
        reread=legacy.extract_evaluation_observations(RUN/'evaluation'/season,q.drop(columns=['simulated']))
        if not np.allclose(q.simulated,reread.simulated,rtol=1e-12,atol=1e-10,equal_nan=True):raise ValueError('Locked evaluation differs from native actual-date output')
        checks.append(dict(season_id=season,total=len(q),matched=int(q.simulated.notna().sum()),unmatched=int(q.simulated.isna().sum())))
    pairs=pd.concat([raw,specials,evaluation],ignore_index=True).merge(meta[['season_id','trno','water_level','nitrogen_level']],on=['season_id','trno'],validate='many_to_one')
    et_path=ROOT/'workspace/audits/observed_et_comparison_20261012/observed_ET_transcription.csv'
    et=pd.read_csv(et_path);extra=[];soil=frames['25SP']['SoilWat']
    layerline=next(x for x in (RUN/'evaluation/25SP/SoilWat.OUT').read_text().splitlines() if '0-5' in x)
    layers=[tuple(map(int,x)) for x in re.findall(r'(\d+)-(\d+)',layerline)]
    for md in meta[meta.season_id=='25SP'].itertuples():
        q=et[et.season_id.eq('25SP')&et.water_level.eq(md.water_level)&et.nitrogen_level.eq(md.nitrogen_level)&~et.phase.eq('total')]
        for r in q.itertuples():
            extra.append(dict(season_id='25SP',trno=md.trno,dataset_role=md.dataset_role,water_level=md.water_level,nitrogen_level=md.nitrogen_level,
                date=r.end,variable='WB100_INTERVAL',observed=r.observed_ET,simulated=parent.water_balance100(soil,md.trno,r.start,r.end,layers),unit='mm',
                interval_start=r.start,interval_end=r.end,source_file=str(et_path.relative_to(ROOT)),comparison_status='matched',evaluation_scope='retrospective_ET_diagnostic'))
    pairs=pd.concat([pairs,pd.DataFrame(extra)],ignore_index=True)
    pairs['final_weight']=0.;pairs['residual']=pairs.simulated-pairs.observed
    save(pairs,'comparison_all_roles.csv')
    save(evaluation[evaluation.simulated.isna()],'unmatched_evaluation_observations.csv')
    family=grouped(compared,['family','variable'])
    detail=model.metrics(compared).set_index('family')
    family['budget']=family.family.map(detail.phi_budget);family['phi']=family.family.map(detail.phi)
    family['phi_pct']=100*family.phi/phi;family['loss']=family.family.map(detail.loss)
    save(family,'calibration_family_metrics_full.csv')
    metrics=grouped(pairs,['season_id','dataset_role','variable']);save(metrics,'metrics_by_season_role_variable.csv')
    save(grouped(pairs,['season_id','dataset_role','trno','water_level','nitrogen_level','variable']),'metrics_by_treatment_variable.csv')
    endpoints=pairs[pairs.variable.isin(['CHPDT','CHFPW'])].sort_values('date').groupby(['season_id','dataset_role','trno','variable']).tail(1).copy()
    save(endpoints,'terminal_yield_pairs.csv');save(grouped(endpoints,['season_id','dataset_role','variable']),'terminal_yield_metrics.csv')
    initial=pd.read_csv(RUN/'preflight/seed_yield/last_comparison.csv')
    delta=grouped(initial,['family','variable']).merge(family,on=['family','variable'],suffixes=('_initial','_selected'))
    delta['NRMSE_change_pp']=delta.RRMSE_selected-delta.RRMSE_initial;save(delta,'initial_vs_selected_metrics_full.csv')
    prior=pd.read_csv(PRIOR/'calibration_family_metrics_full.csv')
    comparison=prior.merge(family,on=['family','variable'],suffixes=('_previous','_new'))
    comparison['NRMSE_change_pp']=comparison.RRMSE_new-comparison.RRMSE_previous;save(comparison,'previous_vs_new_metrics_full.csv')
    param=bounds.copy();param['selected']=param.name.map(values)
    param['fraction_in_range']=(param.selected-param.lower)/(param.upper-param.lower).replace(0,np.nan)
    param['near_bound_2pct']=param.status.eq('active')&((param.fraction_in_range<=.02)|(param.fraction_in_range>=.98))
    save(param,'parameter_bounds_review.csv')
    progress=[]
    for it in range(6):
        out=pd.read_csv(RUN/f'joint/joint.{it}.obs.csv',index_col=0)[obs.obsnme]
        v=np.square(out.to_numpy()*obs.final_weight.to_numpy()).sum(axis=1)
        progress.append(dict(iteration=it,n=len(v),mean=float(np.mean(v)),min=float(np.min(v)),median=float(np.median(v)),
            q05=float(np.quantile(v,.05)),q25=float(np.quantile(v,.25)),q75=float(np.quantile(v,.75)),q95=float(np.quantile(v,.95))))
    save(pd.DataFrame(progress),'iteration_progress.csv')
    quality=json.loads((RUN/'joint/ies_quality/ies_run_quality.json').read_text(encoding='utf-8'));failures=Counter()
    for file in (RUN/'joint/_agents').glob('agent_*/panther_agent.stderr.log'):
        for line in file.read_text(errors='replace').splitlines():
            if re.match(r'^(ValueError|RuntimeError|KeyError|OSError):',line):
                if 'No mature fruit' in line and 'treatment=' not in line:continue
                reason='NoMatureFruit' if 'No mature fruit' in line else line.split(';')[0]
                failures[reason]+=1
    save(pd.DataFrame([dict(reason=k,exception_event_count=v) for k,v in failures.items()]),'forward_failure_events.csv')
    sources=[CONFIG/'design.json',CONFIG/'calibration_observations.csv',CONFIG/'approved_objective_policy.csv',RUN/'best_calibration_parameters.csv',
        RUN/'selection.json',RUN/'selection_audit.csv',RUN/'selected_deterministic/last_comparison.csv',RUN/'evaluation_comparison.csv',RUN/'pipeline_status.json',
        RUN/'joint/ies_quality/ies_run_quality.json',RUN/'joint/ies_quality/joint.member_status.csv',CATALOG,et_path,
        Path(__file__),ROOT/'tools/reporting/report_rmse_joint65_20261012.py']+native_paths
    summary=dict(run_id=ID,selection=selection,pipeline=status,selected_phi=phi,initial_reference_phi=float(model.encode(initial).phi_contribution.sum()),
        best_initial_ensemble_phi=progress[0]['min'],iteration_progress=progress,evaluation_coverage=checks,
        deterministic_vs_ensemble_phi_abs_difference=float(abs(phi-selection['phi'])),maximum_encoded_residual_difference=float(np.max(np.abs(encoded_difference))),
        deterministic_reproduction_relative_tolerance=1e-6,
        quality_failures=[x for x in quality['checks'] if x['status']=='fail'],failure_exception_events=dict(failures),
        exception_count_note='includes trials/retries, not unique lost members',near_bound_active_parameters=int(param.near_bound_2pct.sum()),
        source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):legacy.sha(p) for p in sources},
        fit_definition='NRMSE=100*RMSE/abs(mean observed), R2=squaredPearson, residual=simulated-observed; raw pairs only',
        objective_definition=d['objective_equation'],scientific_status=status['scientific_status'],rendering='Pythonruntime diagnostics, noFig/FigS')
    legacy.write_json(OUT/'result_summary.json',summary)
    return d,pairs,frames,meta,family,metrics,endpoints,summary

def gallery(summary):
    pictures=sorted(FIG.rglob('diagnostic_*.png'))
    sections=['<!doctype html><meta charset="utf-8"><title>Joint65 diagnostics</title>',
        '<style>body{font:15px sans-serif;margin:25px;background:#f6f7f9}h1{font-size:23px}article{background:white;padding:16px;margin:18px 0}img{width:100%;height:auto}a{color:#205b91}</style>',
        '<h1>稳健目标联合65参数：local_00129运行诊断</h1>',
        '<p>第5轮；150/200成员保留（75%），工程验收未通过。图件为运行诊断，非论文图。统计使用原始配对；单调平滑仅作视觉展示。</p>',
        '<p>2025春果氮：2025-07-04八项无成熟果池，保持缺失，不填0或移日。</p>']
    for p in pictures:
        rel=p.relative_to(FIG).as_posix();sections.append(f'<article><h2>{html.escape(rel)}</h2><a href="{rel}"><img loading="lazy" src="{rel}" alt="{html.escape(rel)}"></a></article>')
    (FIG/'diagnostic_index.html').write_text('\n'.join(sections),encoding='utf-8')
    return len(pictures)

def main():
    d,pairs,frames,meta,family,metrics,endpoints,summary=prepare_data()
    responses=renderer.response_tables(endpoints)
    renderer.render(d,pairs,frames,meta,metrics,endpoints)
    count=gallery(summary)
    manifest=dict(run_id=ID,selected_iteration=5,selected_realization='local_00129',artifact_type='runtime_diagnostics',
        engineering_status=summary['pipeline']['engineering_status'],scientific_status=summary['scientific_status'],
        uncertainty_bars='none; no audited SE invented',cumulative_curves='event line + monotone PCHIP visual-only; scores from rawpairs',
        code_reuse=['tools/reporting/report_rmse_joint65_20261012.py:render','tools/calibration/plot_dynamics.py','tools/calibration/evaluate_fixedsoil_official_best189_20260813.py:_plot_metrics'],
        artifacts={str(p.relative_to(FIG)).replace('\\','/'):legacy.sha(p) for p in FIG.rglob('*') if p.is_file()})
    legacy.write_json(FIG/'diagnostic_manifest.json',manifest)
    for rel,h in summary['source_hashes'].items():
        if legacy.sha(ROOT/rel)!=h:raise ValueError('Read-only source changed: '+rel)
    print(json.dumps(dict(status='rendered',png_count=count,selected_phi=summary['selected_phi'],figure_root=str(FIG)),ensure_ascii=False),flush=True)

if __name__=='__main__':main()
