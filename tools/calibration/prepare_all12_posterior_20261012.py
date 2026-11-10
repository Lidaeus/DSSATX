"""Evidence-based, user-authorized all-treatment successor of the sealed robust run."""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration import single_season_n as legacy

PARENT='eggplant_26sp_n012_robust_joint65_200x5_20261012'
ID='eggplant_26sp_all12_robust_joint65_200x5_20261012'
BOUND_ID='eggplant_26sp_all12_posterior_joint65_20261012'
AUTH='根据刚才的率定结果以及参数后验分布，微调相关参数取值范围，然后将2026年的12个处理均纳入率定集，重新运行正式联合率定。'
REVISED={
 'FRLFF':(.09,.14,'与FRSTMF联合设界，端点分配之和不超过1'),
 'FRSTMF':(.72,.86,'与FRLFF联合设界，保留代表解及主要后验区间，避免负根分配'),
 'PROLFF':(.220,.240,'收紧残留叶蛋白，矩形范围保证F<=G<=I'),
 'PROLFG':(.242,.270,'保留主要后验区间并与F/I范围分离'),
 'PROLFI':(.275,.310,'保留代表解及主要后验区间'),
 'PROSTF':(.072,.088,'矩形范围保证茎蛋白F<=G<=I'),
 'PROSTG':(.105,.143,'保留主要后验区间并与F/I范围分离'),
 'PROSTI':(.145,.225,'下界堆积，适当向低蛋白侧探索；上界保留后验95%附近'),
 'PROSHI':(.115,.180,'原下界堆积，轻微降低但仍高于固定PROSHF=.11'),
 'RTNO3':(.003,.015,'保留下界，削减高吸氮率尾部'),
 'RTNH4':(.006,.028,'下界堆积，小幅向低吸氮率侧扩展'),
 'RWUMX':(.009,.018,'保留水响应敏感下界及主要后验上尾'),
 'NMOBMX':(.080,.097,'限制过强再动员上尾，保留代表解'),
 'NVSMOB':(.26,.33,'围绕主要后验轻微收紧'),
 'SENPOR_LATE':(.17,.26,'保留代表解及主要后验，削减低/高衰老率尾部'),
 'SLAVR':(140.,225.,'保留代表解及后验95%附近，不强制压到125–145'),
 'FL-SD':(16.,27.,'原上界堆积，微扩上界；删除远离主要后验的低尾'),
 'SFDUR':(18.,52.,'原下界堆积，小幅探索较早成熟并缩减高尾'),
 'PODUR':(7.,19.,'保留主要后验和成熟库探索空间'),
 'XMAGE':(8.,15.,'保留代表解与主要后验，准确日期果氮仍做完整性检查'),
 'KEP':(.76,.90,'削减低尾，保留物理上限及贴边后验'),
 'SOIL_SLDR':(.75,.93,'原上界堆积，小幅上探；不改变实测水/N初值'),
}

def stamp():return dt.datetime.now(dt.timezone.utc).isoformat()

def prepare(model):
    config=ROOT/'configs/runs'/ID;run=ROOT/'workspace/runs'/ID
    if config.exists() or run.exists():raise FileExistsError('Never overwrite a formal run')
    parent_config=ROOT/'configs/runs'/PARENT;parent_run=ROOT/'workspace/runs'/PARENT
    from src.calibration import robust_joint
    old,bounds,_=robust_joint.load_design(parent_config/'design.json')
    assert json.loads((parent_run/'pipeline_status.json').read_text())['status']=='completed'
    config.mkdir(parents=True);run.mkdir(parents=True)
    selected=legacy.runner._read_param_dict(parent_run/'best_calibration_parameters.csv')
    p0=pd.read_csv(parent_run/'joint/joint.0.par.csv',index_col=0)
    p5=pd.read_csv(parent_run/'joint/joint.5.par.csv',index_col=0)
    p0.index=p0.index.astype(str);p5.index=p5.index.astype(str)
    paired=p0.loc[p5.index];stats=[]
    for row in bounds[bounds.status=='active'].itertuples():
        q=p5[row.name.lower()];prior=paired[row.name.lower()];width=row.upper-row.lower
        stats.append(dict(name=row.name,old_lower=row.lower,old_upper=row.upper,best=selected[row.name],
          final_n=len(q),prior_all_n=len(p0),post_q05=q.quantile(.05),post_q50=q.median(),post_q95=q.quantile(.95),
          post_sd=q.std(),matched_prior_sd=prior.std(),matched_sd_ratio=q.std()/prior.std(),
          lower_1pct_count=int((q<=row.lower+.01*width).sum()),upper_1pct_count=int((q>=row.upper-.01*width).sum())))
    posterior=pd.DataFrame(stats);posterior.to_csv(config/'conditional_posterior_statistics.csv',index=False)
    bounds['init']=bounds.name.map(selected)
    bounds['reason']='保留原范围，代表解作为新中心；未据条件后验盲目收紧'
    for name,(lo,hi,reason) in REVISED.items():
        bounds.loc[bounds.name==name,['lower','upper','reason']]=[lo,hi,reason]
    bounds['approved']=True;bounds['execution_enabled']=True
    bounds.to_csv(config/'approved_bounds_proposal.csv',index=False)
    changes=posterior.merge(bounds[['name','lower','upper','reason']],on='name')
    changes['changed']=(changes.lower!=changes.old_lower)|(changes.upper!=changes.old_upper)
    changes.to_csv(config/'posterior_bounds_changes.csv',index=False)
    model.validate_parameters(selected,bounds)
    result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools/freeze_bounds.py'),'--proposal',str(config/'approved_bounds_proposal.csv'),
      '--crop','eggplant','--bounds-id',BOUND_ID,'--notes','User-authorized all12 successor; conditional posterior guided, root/protein rectangular safety; FL-LF45–220 retained'],
      cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    (run/'bounds_freeze.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    frozen=ROOT/'data/parameter_registry/bounds_frozen/eggplant'/(BOUND_ID+'.csv')
    obs=pd.read_csv(parent_config/'calibration_observations.csv').fillna('')
    rows=obs[~obs.family.isin(['W_SIGNED_CONTRAST','N_ADJACENT_SIGNED_CONTRAST'])].to_dict('records')
    canonical_path=ROOT/'configs/calibration_proposals/eggplant_26sp_n012_review_20261011/observation_catalog.csv'
    canonical=pd.read_csv(canonical_path).fillna('')
    n3=canonical[(canonical.season_id=='26SP')&canonical.trno.isin([1,2,3])]
    families={'SWAD':'STEM_DRY_MASS','LWAD':'LEAF_DRY_MASS','LAID':'CANOPY_LAI','CHTD':'HEIGHT',
        'LEAF_N_PCT':'LEAF_N_CONCENTRATION','STEM_N_PCT':'STEM_N_CONCENTRATION','FRUIT_N_PCT':'FRUIT_N_CONCENTRATION',
        'HPODW':'HARVEST_DRY_EVENT','VWC':'SOIL_WATER'}
    for row in n3.to_dict('records'):
        if row['variable'] in families:row['family']=families[row['variable']]
        elif row['variable']=='CHPDT':row['family']='FINAL_DRY_YIELD' if row['date']=='2026-07-17' else 'HARVEST_DRY_CUMULATIVE_EARLY'
        elif row['variable']=='CHFPW' and row['date']=='2026-07-17':row['family']='FINAL_FRESH_YIELD'
        else:continue
        rows.append(row)
    file_a_path=ROOT/'data/user/experiments/xxql2601_refreshed_20261010/FileA_values.csv'
    file_a=pd.read_csv(file_a_path).set_index('TRNO')
    for t in [1,2,3]:
        a=file_a.loc[t];pd0=dt.datetime.strptime(str(int(a.PDAT)),'%y%j');ad0=dt.datetime.strptime(str(int(a.ADAT)),'%y%j')
        template=obs[obs.variable=='ADAP'].iloc[0].to_dict()
        rows.append(template|dict(trno=t,date=ad0.date().isoformat(),observed=float((ad0-pd0).days),source_file=str(file_a_path.relative_to(ROOT))))
    et_path=ROOT/'workspace/audits/observed_et_comparison_20261012/observed_ET_transcription.csv'
    et=pd.read_csv(et_path);meta_path=file_a_path.parent/'treatment_metadata.csv';meta=pd.read_csv(meta_path)
    lookup={(r.water_level,r.nitrogen_level):int(r.treatment) for r in meta.itertuples()}
    for e in et[(et.season_id=='26SP')&(et.nitrogen_level=='N3')&et.phase.isin(['early','late'])].itertuples():
        template=obs[obs.variable=='WB100_INTERVAL'].iloc[0].to_dict()
        rows.append(template|dict(trno=lookup[(e.water_level,e.nitrogen_level)],date=e.end,observed=e.observed_ET,
          replicate_sd=e.observed_sd,n_rep=e.n_rep,interval_start=e.start,interval_end=e.end,source_file=str(et_path.relative_to(ROOT)),
          representation_assumption=e.measurement_method))
    preliminary=pd.DataFrame(rows);fresh=preliminary[preliminary.family=='FINAL_FRESH_YIELD'].set_index('trno')
    template_w=obs[obs.family=='W_SIGNED_CONTRAST'].iloc[0].to_dict()
    template_n=obs[obs.family=='N_ADJACENT_SIGNED_CONTRAST'].iloc[0].to_dict()
    for ni in range(4):
        for wi in [2,3]:
            high=lookup[(f'W{wi}',f'N{ni}')];low=lookup[('W1',f'N{ni}')]
            rows.append(template_w|dict(trno=high,paired_trno=low,observed=float(fresh.loc[high,'observed']-fresh.loc[low,'observed']),
              stratum=f'W{wi}-W1_N{ni}',parent_observations=f'CHFPW:T{high}-T{low}'))
    for wi in [1,2,3]:
        for ni in [1,2,3]:
            high=lookup[(f'W{wi}',f'N{ni}')];low=lookup[(f'W{wi}',f'N{ni-1}')]
            rows.append(template_n|dict(trno=high,paired_trno=low,observed=float(fresh.loc[high,'observed']-fresh.loc[low,'observed']),
              stratum=f'N{ni}-N{ni-1}_W{wi}',parent_observations=f'CHFPW:T{high}-T{low}'))
    obs=pd.DataFrame(rows).fillna('');policy=pd.read_csv(parent_config/'approved_objective_policy.csv')
    obs['dataset_role']='calibration';obs['status']='approved_all12_direct_target';obs['source_catalog_status']='calibration';obs['approved']=True;obs['execution_enabled']=True
    obs['parent_obsnme']=obs.get('obsnme','');obs['obsnme']=[f'all26_{i:04d}' for i in range(len(obs))];obs['pest_obsval']=0.
    for r in policy.itertuples():
        mask=obs.family==r.family;n=int(mask.sum());policy.loc[policy.family==r.family,'n_targets']=n
        scale=2. if r.scale_policy=='fixed_2_days' else float(fresh.observed.mean()) if r.scale_policy=='frozen_terminal_fresh_yield_mean' else float(pd.to_numeric(obs.loc[mask,'observed']).mean())
        for col,value in dict(phi_budget=r.phi_budget,fit_scale=scale,final_weight=np.sqrt(r.phi_budget/n),loss=r.loss,
            huber_delta=.15 if r.loss=='pseudo_huber' else '',scale_policy=r.scale_policy,
            fit_metric='RMSE' if r.scale_policy=='fixed_2_days' else 'NRMSE',fit_scale_source='frozen_all12_observed_family_mean').items():obs.loc[mask,col]=value
    model.validate_catalog(obs,policy)
    assert not obs[~obs.variable.isin(model.SIGNED)].observed.lt(0).any()
    obs.to_csv(config/'calibration_observations.csv',index=False);policy.to_csv(config/'approved_objective_policy.csv',index=False)
    external=pd.read_csv(parent_config/'locked_evaluation_observations.csv')
    external=external[external.season_id!='26SP'];assert len(external)==1044
    external.to_csv(config/'locked_evaluation_observations.csv',index=False)
    references={'seed_yield':selected,'seed_water':selected|{'RWUMX':.0105},'seed_canopy':selected|{'FL-LF':180.,'SENPOR_LATE':.19}}
    for name,values in references.items():
        model.validate_parameters(values,bounds)
        pd.DataFrame(values.items(),columns=['name','value']).to_csv(run/(name+'_parameters.csv'),index=False)
    shutil.copy2(run/'seed_yield_parameters.csv',run/'initial_parameters.csv')
    d=dict(old)
    for stale in ['proposal_file_sha256','inherited_runtime_hashes','startup_repair_history','initial_ensemble_sha256','initial_observation_ensemble_sha256','reference_change']:d.pop(stale,None)
    for dataset in d['datasets']:
        if dataset['season_id']=='26SP':dataset['roles']={'calibration':list(range(1,13))}
    runtime=dict(old['runtime_hashes'])
    for f in ['src/calibration/all12_joint.py','tools/calibration/prepare_all12_posterior_20261012.py','tools/calibration/launch_all12_joint_200x5_20261012.py']:runtime[f]=legacy.sha(ROOT/f)
    sources=[parent_config/'design.json',parent_run/'best_calibration_parameters.csv',parent_run/'joint/joint.0.par.csv',parent_run/'joint/joint.5.par.csv',
        canonical_path,file_a_path,meta_path,et_path,config/'conditional_posterior_statistics.csv',config/'posterior_bounds_changes.csv',
        config/'approved_bounds_proposal.csv',config/'locked_evaluation_observations.csv',run/'initial_parameters.csv']
    d.update(schema='formal_all12_robust_joint_v1',design_id=ID,parent_design=str((parent_config/'design.json').relative_to(ROOT)),
      parent_design_sha256=legacy.sha(parent_config/'design.json'),proposed_bounds_id=BOUND_ID,bounds_id=BOUND_ID,bounds_sha256=legacy.sha(frozen),
      target_count=689,status='native_preflight_pending',runtime_preflight_passed=False,ensemble_preflight_passed=False,
      approval=dict(user_statement=AUTH,recorded_at=stamp(),change='22 posterior-informed ranges; all12 calibration; budget/loss/200x5 unchanged'),
      calibration_observations_sha256=legacy.sha(config/'calibration_observations.csv'),policy_sha256=legacy.sha(config/'approved_objective_policy.csv'),
      evaluation_catalog_sha256=legacy.sha(config/'locked_evaluation_observations.csv'),runtime_hashes=runtime,
      source_hashes={str(f.relative_to(ROOT)).replace('\\','/'):legacy.sha(f) for f in sources},
      signed_contrasts='8 W contrasts and9 adjacent N contrasts; observed signed differences, including N3 negative effects; no minimum-effect gate',
      selection_rule='minimum complete fixed689-row calibration objective among physically valid candidates; independent2025 evaluation only after selection',
      native_preflight_cases=4,native_complete_cases=0,preflight_scope='4 references followed by200native members at689exact-date targets each',
      seed=20261013,posterior_interpretation='Conditional optimization ensemble:150/200survivors, mixed local/global initialization; not unbiased Bayesian credible intervals',
      initialization=old['initialization']|dict(base='parent_selected_local00129',reference_seeds=['seed_waterRWUMX.0105','seed_canopyFL180_SENPOR.19']),
      initial_predictions_reused_by_IES=False)
    d['engineering_plan']=[s.replace('516','689').replace('held-out seasons','independent2025seasons') for s in d['engineering_plan']]
    legacy.write_json(config/'design.json',d)
    reports=[]
    for name in references:
        compared=model.evaluate(config/'design.json',run/(name+'_parameters.csv'),run/'preflight'/name,preflight=True)
        model.metrics(compared).to_csv(run/'preflight'/name/'family_metrics.csv',index=False)
        reports.append(dict(seed=name,targets=len(compared),phi=float(compared.phi_contribution.sum()),complete=True))
    endpoint=selected|{'FL-LF':45.}
    pd.DataFrame(endpoint.items(),columns=['name','value']).to_csv(run/'preflight/fl45_parameters.csv',index=False)
    compared=model.evaluate(config/'design.json',run/'preflight/fl45_parameters.csv',run/'preflight/fl45',preflight=True)
    reports.append(dict(seed='fl45_endpoint',targets=len(compared),phi=float(compared.phi_contribution.sum()),complete=True))
    legacy.write_json(run/'preflight/report.json',dict(status='passed',seeds=reports,missing_fruit_imputed=False))
    d.update(runtime_preflight_passed=True,native_complete_cases=4,status='ensemble_preflight_pending')
    legacy.write_json(config/'design.json',d)
    legacy.write_json(config/'frozen_configuration_receipt.json',dict(design_sha256=legacy.sha(config/'design.json'),recorded_at=stamp()))
    legacy.write_json(run/'approval_receipt.json',dict(user_statement=AUTH,recorded_at=stamp(),design_sha256=legacy.sha(config/'design.json')))
    legacy.write_json(run/'pipeline_status.json',dict(status='prepared',phase='ensemble_preflight_pending',updated_at=stamp()))
    model.load_design(config/'design.json')
    print('All12 runtime preflight passed:65parameters,689targets,22revised ranges',flush=True)
