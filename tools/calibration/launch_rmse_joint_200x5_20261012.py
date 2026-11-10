"""Execute authorized yield-priority direct joint65, 200 members and five updates."""
from __future__ import annotations
import argparse
import concurrent.futures
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pyemu
from scipy.stats import qmc
import yaml

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration import rmse_joint as model
from src.calibration import water_n_joint as parent
from src.calibration import single_season_n as legacy
from tools.calibration.launch_water_n_joint_20261012 import logged, stamp

ID='eggplant_26sp_n012_rmse_joint65_200x5_20261012'
CONFIG=ROOT/'configs/runs'/ID
RUN=ROOT/'workspace/runs'/ID
OLD=ROOT/'workspace/runs/eggplant_26sp_n012_waterN_joint65_20261012'
PARENT=ROOT/'configs/runs'/OLD.name/'design.json'
CATALOG=ROOT/'configs/calibration_proposals/eggplant_26sp_n012_review_20261011/observation_catalog.csv'
AUTH='调整目标函数：减弱或者取消硬性水氮梯度约束，增强RMSE/NRMSE与最终产量权重，重新正式联合率定200*5；参考第6轮base及鲜产量诊断。'


def policy():
    rows=[
        ('CHPDT','FINAL_DRY_YIELD',20,9,'NRMSE'),
        ('CHFPW','FINAL_FRESH_YIELD',20,9,'NRMSE'),
        ('CHPDT','HARVEST_DRY_CUMULATIVE_EARLY',5,36,'NRMSE'),
        ('HPODW','HARVEST_DRY_EVENT',15,45,'NRMSE'),
        ('LAID','CANOPY_LAI',5,36,'NRMSE'),
        ('LWAD','LEAF_DRY_MASS',4,36,'NRMSE'),
        ('SWAD','STEM_DRY_MASS',8,36,'NRMSE'),
        ('CHTD','HEIGHT',2,36,'NRMSE'),
        ('LEAF_N_PCT','LEAF_N_CONCENTRATION',5,36,'NRMSE'),
        ('STEM_N_PCT','STEM_N_CONCENTRATION',5,36,'NRMSE'),
        ('FRUIT_N_PCT','FRUIT_N_CONCENTRATION',4,27,'NRMSE'),
        ('ADAP','ANTHESIS',2,9,'RMSE'),
        ('VWC','SOIL_WATER',3,135,'NRMSE'),
        ('WB100_INTERVAL','WATER_BALANCE_100CM',2,18,'NRMSE'),
    ]
    frame=pd.DataFrame(rows,columns=['variable','family','phi_budget','n_targets','metric'])
    frame['fixed_scale']=np.where(frame.metric.eq('RMSE'),2.,np.nan)
    frame['approved']=True
    return frame


def make_targets():
    old=pd.read_csv(PARENT.parent/'calibration_observations.csv').fillna('')
    obs=old[~old.variable.isin(model.GRADIENT_VARIABLES)].copy()
    obs['parent_obsnme']=obs.obsnme
    obs['prior_family']=obs.family
    obs['prior_final_weight']=obs.final_weight
    final=obs.variable.eq('CHPDT') & obs.date.eq('2026-07-17')
    obs.loc[final,'family']='FINAL_DRY_YIELD'
    obs.loc[obs.variable.eq('CHPDT') & ~final,'family']='HARVEST_DRY_CUMULATIVE_EARLY'
    catalog=pd.read_csv(CATALOG).fillna('')
    fresh=catalog[catalog.variable.eq('CHFPW') & catalog.date.eq('2026-07-17') & catalog.trno.isin(range(4,13))].copy()
    if len(fresh)!=9 or fresh.trno.duplicated().any(): raise ValueError('Missing/duplicate measured terminal fresh yield')
    # Independent primitive-data check, not a reconstruction from contrasts.
    repeats=pd.read_csv(ROOT/'data/user/experiments/xxql2601_refreshed_20261010/harvest_replicates.csv')
    repeats=repeats[repeats.date.eq('2026-07-17') & repeats.trno.isin(range(4,13))]
    grouped=repeats.groupby('trno').CHFPW.agg(['mean','std','count'])
    for r in fresh.itertuples():
        a=grouped.loc[r.trno]
        if a['count']!=3 or not np.isclose(a['mean'],r.observed,rtol=1e-12) or not np.isclose(a['std'],float(r.replicate_sd),rtol=1e-12):
            raise ValueError('Fresh catalog differs from frozen harvest replicates')
    fresh['family']='FINAL_FRESH_YIELD';fresh['parent_obsnme']=''
    fresh['prior_family']='diagnostic_absolute_fresh_yield';fresh['prior_final_weight']=0.
    fresh['sigma_eff']=pd.to_numeric(fresh.replicate_sd)
    fresh['sigma_source']='measured_SD_n_eff_1; audit only, not fitting normalization'
    with pd.option_context('future.no_silent_downcasting', True):
        obs=pd.concat([obs,fresh],ignore_index=True).fillna('').infer_objects(copy=False)
    obs['measurement_sigma_eff']=obs.sigma_eff
    obs['observed']=pd.to_numeric(obs.observed)
    for p in policy().itertuples():
        mask=obs.family.eq(p.family);q=obs[mask]
        scale=float(q.observed.mean()) if p.metric=='NRMSE' else float(p.fixed_scale)
        obs.loc[mask,'fit_scale']=scale
        obs.loc[mask,'fit_metric']=p.metric
        obs.loc[mask,'fit_scale_source']='frozen_2026_calibration_family_observed_mean' if p.metric=='NRMSE' else 'fixed_2_day_RMSE_scale'
        obs.loc[mask,'phi_budget']=p.phi_budget
        obs.loc[mask,'base_weight']=1/scale
        obs.loc[mask,'group_multiplier']=np.sqrt(p.phi_budget/len(q))
        obs.loc[mask,'final_weight']=np.sqrt(p.phi_budget/len(q))/scale
    obs['obsnme']=[f'rm26_{i:04d}' for i in range(len(obs))]
    obs['approved']=True;obs['execution_enabled']=True;obs['status']='approved_direct_RMSE_NRMSE_target'
    model.validate_catalog(obs,policy())
    return obs


def cached_comparison(folder,obs):
    folder=Path(folder)
    native=folder/'_model'
    old=pd.read_csv(folder/'last_comparison.csv').fillna('').set_index('obsnme')
    fresh=legacy.read_native(native/'FreshWt.OUT')
    result=[]
    for item in obs.to_dict('records'):
        if item['parent_obsnme']:
            r=old.loc[item['parent_obsnme']]
            if r.variable!=item['variable'] or int(r.trno)!=int(item['trno']) or r.date!=item['date']:
                raise ValueError('Cached target identity changed')
            value=float(r.simulated)
            if item['variable']=='FRUIT_N_PCT':
                if float(r.mature_seed_dm)+float(r.mature_shell_dm)<=0 or r.model_date!=item['date'] or r.date_shift!=0:
                    raise ValueError('Cached fruit N was not exact-date mature-pool output')
        else:
            value=float(fresh.loc[(int(item['trno']),item['date']),'CHFPW'])
        if not np.isfinite(value) or (item['variable'] not in model.SIGNED and value<0):
            raise ValueError('Missing/invalid cached output')
        result.append({**item,'simulated':value})
    return pd.DataFrame(result)


def prepare():
    if CONFIG.exists() or RUN.exists(): raise FileExistsError('Never overwrite a formal run')
    d,bounds,oldobs=parent.load_design(PARENT)
    table=pd.read_csv(OLD/'joint/joint.6.par.csv',index_col=0)
    values=model.validate_parameters({r.name:float(table.loc['base',r.name.lower()]) for r in bounds.itertuples()},bounds)
    predictions=pd.read_csv(OLD/'joint/joint.6.obs.csv',index_col=0)
    oldphi=float(np.square((predictions.loc['base',oldobs.obsnme].to_numpy()-oldobs.observed)*oldobs.final_weight).sum())
    if not np.isclose(oldphi,137.8178211884225,atol=1e-8): raise ValueError('Referenced iteration6 base identity differs')
    CONFIG.mkdir(parents=True);RUN.mkdir(parents=True)
    obs=make_targets();obs.to_csv(CONFIG/'calibration_observations.csv',index=False)
    policy().to_csv(CONFIG/'approved_objective_policy.csv',index=False)
    shutil.copy2(PARENT.parent/'locked_evaluation_observations.csv',CONFIG/'locked_evaluation_observations.csv')
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(RUN/'initial_parameters.csv',index=False)
    shutil.copy2(OLD/'balanced_seed_parameters.csv',RUN/'balanced_seed_parameters.csv')
    sources=[PARENT,OLD/'joint/joint.6.par.csv',OLD/'joint/joint.6.obs.csv',OLD/'joint/initial_ensemble.csv',
        CATALOG,ROOT/'data/user/experiments/xxql2601_refreshed_20261010/harvest_replicates.csv',
        CONFIG/'approved_objective_policy.csv',RUN/'initial_parameters.csv',RUN/'balanced_seed_parameters.csv']
    runtime=dict(d['runtime_hashes'])
    runtime.update({f:legacy.sha(ROOT/f) for f in ['src/calibration/rmse_joint.py','tools/calibration/launch_rmse_joint_200x5_20261012.py']})
    design=dict(schema='formal_rmse_joint_v1',design_id=ID,approved=True,executable=True,
        approval=dict(user_statement=AUTH,recorded_at=stamp(),reference='verified iteration6 base 137.8178211884 plus frozen primitive terminal fresh harvest'),
        status='preflight_pending',runtime_preflight_passed=False,parent_design=str(PARENT.relative_to(ROOT)).replace('\\','/'),
        datasets=d['datasets'],bounds_id=d['bounds_id'],bounds_sha256=d['bounds_sha256'],active_parameters=d['active_parameters'],active_parameter_count=65,
        target_count=504,family_count=14,phi_budget_total=100,gradient_hard_gates=False,gradient_penalties=False,
        legacy_nonwater_promotion_thresholds=False,selection_rule='minimum complete 504-row fixed calibration Phi among physical valid candidates, no gradient or legacy +10%/2pp selection gates',
        calibration_observations_sha256=legacy.sha(CONFIG/'calibration_observations.csv'),
        evaluation_catalog_sha256=legacy.sha(CONFIG/'locked_evaluation_observations.csv'),runtime_hashes=runtime,
        source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):legacy.sha(p) for p in sources},
        dssat_executable=d['dssat_executable'],dssat_executable_sha256=d['dssat_executable_sha256'],
        noptmax=5,ies_num_reals=200,workers=6,seed=20261012,staged_calibration=False,model_method='R',fixed_environment=d['fixed_environment'],
        objective_equation='sum family B*(RMSE/frozen_calibration_family_mean)^2; anthesis B*(RMSE/2 days)^2',
        observation_uncertainty='measured SD and prior sigma retained for reporting, not interpreted as NRMSE normalization or independent likelihood',
        correlated_targets='terminal fresh/dry, earlier cumulative/event and WB100/VWC share samples; budgets express composite fitting priorities, not independent evidence',
        initialization=dict(base='iteration6 base, verified identity and 519 predictions',local_members=140,
            local_support='each frozen interval intersect center +/-10% of full frozen width; no drawn-value clipping',
            global_members=58,global_source='first58 original feasible Sobol members in ordinal order; no residual ranking',balanced_reference_members=1),
        minimum_member_retention=.98,scientific_status='science_pending',user_monitoring='startup confirmation only')
    legacy.write_json(CONFIG/'design.json',design)
    reports=[]
    for seed,param,cached in [('iter6_base','initial_parameters.csv',OLD/'iter6_base_deterministic'),
                              ('balanced','balanced_seed_parameters.csv',OLD/'preflight/balanced')]:
        compared=model.evaluate(CONFIG/'design.json',RUN/param,RUN/'preflight'/seed,preflight=True)
        expected=cached_comparison(cached,obs)
        if not np.allclose(compared.simulated,expected.simulated,rtol=1e-10,atol=1e-8):
            raise ValueError('New direct observations failed deterministic reproduction: '+seed)
        metrics=model.metrics(compared);metrics.to_csv(RUN/'preflight'/seed/'family_metrics.csv',index=False)
        phi=float(np.square((compared.simulated-compared.observed)*compared.final_weight).sum())
        if not np.isclose(phi,metrics.phi.sum(),rtol=1e-12): raise ValueError('Metric decomposition differs')
        reports.append(dict(seed=seed,targets=len(compared),active_readback=65,phi=phi,deterministic_reproduction_passed=True))
    legacy.write_json(RUN/'preflight/report.json',dict(status='passed',seeds=reports,referenced_iter6_base_old_phi=oldphi,
        nrmse_equation_verified=True,terminal_fresh_means_and_SD_verified_against_three_replicates=True,
        gradient_terms_and_promotion_gates_removed=True,original_frozen_parameter_ranges_unchanged=True))
    design.update(status='approved_ready',runtime_preflight_passed=True)
    legacy.write_json(CONFIG/'design.json',design)
    legacy.write_json(CONFIG/'frozen_configuration_receipt.json',dict(design_sha256=legacy.sha(CONFIG/'design.json'),recorded_at=stamp()))
    legacy.write_json(RUN/'approval_receipt.json',dict(user_statement=AUTH,recorded_at=stamp(),design_sha256=legacy.sha(CONFIG/'design.json')))
    model.load_design(CONFIG/'design.json')
    legacy.write_json(RUN/'pipeline_status.json',dict(status='prepared',phase='preflight_passed',updated_at=stamp()))
    print('Verified iteration6 base; direct-fit 65/504 preflight passed',flush=True)


def screen_one(pair):
    ordinal,values=pair;folder=RUN/'initial_feasibility'/f'local_{ordinal:05d}';folder.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(folder/'parameters.csv',index=False)
    try:
        model.evaluate(CONFIG/'design.json',folder/'parameters.csv',folder)
        return dict(ordinal=ordinal,accepted=True,parameters=values,output_sha256=legacy.sha(folder/'FormalObjectives.OUT'))
    except Exception as error:
        legacy.write_json(folder/'feasibility_failure.json',dict(error=str(error)))
        return dict(ordinal=ordinal,accepted=False,error=str(error))


def initial_ensemble():
    d,bounds,obs=model.load_design(CONFIG/'design.json')
    center=model.validate_parameters(legacy.runner._read_param_dict(RUN/'initial_parameters.csv'),bounds)
    balanced=model.validate_parameters(legacy.runner._read_param_dict(RUN/'balanced_seed_parameters.csv'),bounds)
    accepted=[dict(name='base',parameters=center),dict(name='balanced_seed',parameters=balanced)]
    old=pd.read_csv(OLD/'joint/initial_ensemble.csv',index_col=0)
    (RUN/'initial_feasibility_global').mkdir(exist_ok=True)
    global_audit=[]
    for name in [x for x in old.index if x.startswith('sobol_')][:58]:
        values=model.validate_parameters({r.name:float(old.loc[name,r.name.lower()]) for r in bounds.itertuples()},bounds)
        ordinal=int(name.split('_')[1]);folder=OLD/'initial_feasibility'/f'candidate_{ordinal:05d}'
        stored=legacy.runner._read_param_dict(folder/'parameters.csv')
        if any(not np.isclose(stored[k],v,rtol=1e-12,atol=1e-10) for k,v in values.items()): raise ValueError('Global cached parameters differ')
        comp=cached_comparison(folder,obs)
        comp.to_csv(RUN/'initial_feasibility_global'/f'{name}.csv',index=False)
        accepted.append(dict(name='global_'+name,parameters=values))
        global_audit.append(dict(name=name,complete_targets=len(comp),native_fresh_sha256=legacy.sha(folder/'_model/FreshWt.OUT'),
            original_comparison_sha256=legacy.sha(folder/'last_comparison.csv'),parameter_sha256=legacy.sha(folder/'parameters.csv')))
    if len(global_audit)!=58: raise ValueError('Expected58 global feasible members')
    pd.DataFrame(global_audit).to_csv(RUN/'global_initial_revalidation.csv',index=False)
    active=d['active_parameters'];indexed=bounds.set_index('name');pointcenter=np.array([center[k] for k in active])
    lo=indexed.loc[active,'lower'].to_numpy();hi=indexed.loc[active,'upper'].to_numpy()
    a=np.maximum(lo,pointcenter-.1*(hi-lo));b=np.minimum(hi,pointcenter+.1*(hi-lo))
    pd.DataFrame(dict(name=active,center=pointcenter,frozen_lower=lo,frozen_upper=hi,local_lower=a,local_upper=b)).to_csv(RUN/'local_initial_support.csv',index=False)
    points=qmc.Sobol(d=65,scramble=True,seed=d['seed']).random_base2(12)
    attempts=[];index=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        while len(accepted)<200 and index<len(points):
            batch=[]
            while len(batch)<12 and index<len(points):
                ordinal=index;point=points[index];index+=1
                values=center.copy();values.update(dict(zip(active,a+point*(b-a))))
                try: values=model.validate_parameters(values,bounds)
                except ValueError as error:
                    attempts.append(dict(ordinal=ordinal,accepted=False,phase='physical_order',error=str(error)));continue
                batch.append((ordinal,values))
            for result in pool.map(screen_one,batch):
                attempts.append({k:v for k,v in result.items() if k!='parameters'})
                if result['accepted'] and len(accepted)<200:
                    accepted.append(dict(name=f"local_{result['ordinal']:05d}",parameters=result['parameters']))
            legacy.write_json(RUN/'initial_feasibility_status.json',dict(status='screening',accepted=len(accepted),local_accepted=len(accepted)-60,
                global_accepted=58,references=2,target=200,updated_at=stamp(),screening_used_observed_residuals=False))
    pd.DataFrame(attempts).to_csv(RUN/'initial_feasibility_audit.csv',index=False)
    if len(accepted)!=200: raise RuntimeError('200 feasible members unavailable; no automatic parameter/observation changes')
    legacy.write_json(RUN/'initial_feasibility_status.json',dict(status='completed',accepted=200,local_accepted=140,global_accepted=58,references=2,
        screening_used_observed_residuals=False,updated_at=stamp()))
    return pd.DataFrame([{k.lower():v for k,v in x['parameters'].items()} for x in accepted],index=[x['name'] for x in accepted])


def build_case(ensemble):
    d,bounds,obs=model.load_design(CONFIG/'design.json');work=RUN/'joint';work.mkdir()
    (work/'parameters.tpl').write_text('ptf ~\nname,value\n'+''.join(f'{r.name},~ {r.name.lower():<20} ~\n' for r in bounds.itertuples()),encoding='ascii')
    shutil.copy2(RUN/'initial_parameters.csv',work/'parameters.csv')
    shutil.copy2(RUN/'preflight/iter6_base/FormalObjectives.OUT',work/'FormalObjectives.OUT')
    (work/'objectives.ins').write_text('pif ~\n'+''.join(f'l1 w !{r.obsnme}!\n' for r in obs.itertuples()),encoding='ascii')
    pst=pyemu.Pst.from_io_files([str(work/'parameters.tpl')],[str(work/'parameters.csv')],[str(work/'objectives.ins')],[str(work/'FormalObjectives.OUT')],pst_path='.')
    for r in bounds.itertuples():
        pst.parameter_data.loc[r.name.lower(),['partrans','parval1','parlbnd','parubnd','pargp']]=['none' if r.status=='active' else 'fixed',float(ensemble.loc['base',r.name.lower()]),r.lower,r.upper,r.pargp.lower()]
    for r in obs.itertuples(): pst.observation_data.loc[r.obsnme,['obsval','weight','obgnme']]=[r.observed,r.final_weight,r.family.lower()]
    pst.model_command=[f'"{sys.executable}" -X utf8 "{ROOT / "src/calibration/rmse_joint.py"}" --design "{CONFIG / "design.json"}" --param-csv parameters.csv']
    pst.control_data.noptmax=5
    pst.pestpp_options=dict(ies_num_reals=200,ies_include_base=True,ies_no_noise=True,ies_save_binary=False,
        ies_bad_phi_sigma=1e300,ies_initial_lambda=100.,ies_lambda_mults=[.1,1.,10.],lambda_scale_fac=[.05,.1,.25],
        ies_par_en='initial_ensemble.csv',rand_seed=d['seed'],ies_drop_conflicts=False,ies_pdc_sigma_distance=0.,ies_subset_size=30,
        panther_agent_no_ping_timeout_secs=600)
    ensemble.to_csv(work/'initial_ensemble.csv');pst.write(str(work/'joint.pst'),version=1)
    check=pyemu.Pst(str(work/'joint.pst'))
    if check.npar_adj!=65 or check.nnz_obs!=504 or check.control_data.noptmax!=5: raise ValueError('PST contract differs')
    commit=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    manifest=dict(run_id=ID,git_commit=commit,mode='eggplant_stage2',design_schema=d['schema'],created_at=stamp(),bounds_id=d['bounds_id'],bounds_sha256=d['bounds_sha256'],
        design_sha256=legacy.sha(CONFIG/'design.json'),n_params=len(bounds),n_params_active=65,n_obs=504,n_obs_positive=504,noptmax=5,ies_num_reals=200,agents=6,
        batch_file='DSSBatch.v48',harvest_var='CHPDT',scientific_status='science_pending',scenario_type='actual_trial_calibration',minimum_member_retention=.98,
        initial_ensemble_sha256=legacy.sha(work/'initial_ensemble.csv'),input_manifest_sha256=next(x['bundle_manifest_sha256'] for x in d['datasets'] if x['season_id']=='26SP'))
    (work/'run_manifest.yaml').write_text(yaml.safe_dump(manifest,sort_keys=False),encoding='utf-8')
    return work


def finalize():
    d,bounds,obs=model.load_design(CONFIG/'design.json');work=RUN/'joint';candidates=[]
    for file in work.glob('joint.*.obs.csv'):
        it=file.name.removeprefix('joint.').removesuffix('.obs.csv');par=work/f'joint.{it}.par.csv'
        if not it.isdigit() or not par.exists(): continue
        out=pd.read_csv(file,index_col=0);pars=pd.read_csv(par,index_col=0);out.index=out.index.astype(str);pars.index=pars.index.astype(str)
        for real in out.index.intersection(pars.index):
            v=out.loc[real,obs.obsnme].to_numpy(dtype=float)
            if not np.isfinite(v).all() or np.any(v[~obs.variable.isin(model.SIGNED).to_numpy()]<0): continue
            values={r.name:float(pars.loc[real,r.name.lower()]) for r in bounds.itertuples()}
            try: model.validate_parameters(values,bounds)
            except ValueError: continue
            phi=float(np.square((v-obs.observed.to_numpy())*obs.final_weight.to_numpy()).sum())
            candidates.append(dict(phi=phi,iteration=int(it),realization=real,parameter_file=str(par),complete_targets=504))
    if not candidates: raise RuntimeError('No complete physically valid candidate')
    pd.DataFrame(candidates).to_csv(RUN/'selection_audit.csv',index=False)
    chosen=min(candidates,key=lambda x:(x['phi'],x['iteration'],x['realization']))
    table=pd.read_csv(chosen['parameter_file'],index_col=0);table.index=table.index.astype(str)
    values={r.name:float(table.loc[chosen['realization'],r.name.lower()]) for r in bounds.itertuples()}
    file=RUN/'best_calibration_parameters.csv'
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(file,index=False)
    compared=model.evaluate(CONFIG/'design.json',file,RUN/'selected_deterministic')
    metrics=model.metrics(compared);metrics.to_csv(RUN/'calibration_family_metrics.csv',index=False)
    checked=float(metrics.phi.sum())
    if not np.isclose(checked,chosen['phi'],rtol=1e-6,atol=1e-8): raise ValueError('Deterministic Phi reproduction failed')
    pd.read_csv(RUN/'preflight/iter6_base/family_metrics.csv').merge(metrics,on='family',suffixes=('_initial','_selected')).to_csv(RUN/'initial_vs_selected_metrics.csv',index=False)
    # Full old gradient and guard information is descriptive, never a selector.
    _,_,oldobs=parent.load_design(PARENT)
    diagnostic=parent.extract_observations(RUN/'selected_deterministic/_model',oldobs)
    diagnostic[diagnostic.variable.isin(model.GRADIENT_VARIABLES)].to_csv(RUN/'water_n_gradient_diagnostics.csv',index=False)
    selection=dict(**chosen,deterministic_phi=checked,validation_used=False,gradient_gates_used=False,legacy_nonwater_gates_used=False,
        scientific_status='science_pending_review',note='Minimum fixed calibration objective is an optimization result; no automatic scientific promotion')
    legacy.write_json(RUN/'selection.json',selection)
    if legacy.sha(CONFIG/'locked_evaluation_observations.csv')!=d['evaluation_catalog_sha256']: raise ValueError('Locked catalog changed')
    evaluation=pd.read_csv(CONFIG/'locked_evaluation_observations.csv').fillna('');checks=[]
    for dataset in d['datasets']:
        treatments=[t for role,ts in dataset['roles'].items() if role!='calibration' for t in ts]
        if treatments:
            native=model.simulate(RUN/'evaluation'/dataset['season_id'],dataset,treatments,values,executable_sha256=d['dssat_executable_sha256'])
            model.audit_injection(native,values,d['active_parameters'])
            checks.append(legacy.extract_evaluation_observations(native,evaluation[evaluation.season_id.eq(dataset['season_id'])]))
    pd.concat(checks,ignore_index=True).to_csv(RUN/'evaluation_comparison.csv',index=False)
    return selection


def controller():
    def status(phase,**kwargs): legacy.write_json(RUN/'pipeline_status.json',dict(status='running',phase=phase,controller_pid=os.getpid(),updated_at=stamp(),**kwargs))
    try:
        status('initial_feasibility_screen');ensemble=initial_ensemble();work=build_case(ensemble)
        status('ies',members=200)
        logged([sys.executable,'-X','utf8',str(ROOT/'tools/parallel/run_parallel.py'),'--run-dir',str(work),'--case','joint','--mode','ies','--n-agents','6','--wait'],RUN/'parallel_controller.log')
        outcome=json.loads((work/'run_status.json').read_text(encoding='utf-8'))
        if outcome.get('status')!='completed' or 'analysis complete' not in (work/'joint.rec').read_text(errors='replace').lower(): raise RuntimeError('PEST did not complete')
        status('postselection');selection=finalize()
        files=sorted((p for p in work.glob('joint.*.obs.csv') if p.name.split('.')[1].isdigit()),key=lambda p:int(p.name.split('.')[1]))
        retention=len(pd.read_csv(files[-1],index_col=0))/200
        engineering=outcome.get('engineering_status') if retention>=.98 else 'engineering_failed'
        legacy.write_json(RUN/'pipeline_status.json',dict(status='completed',phase='finished',engineering_status=engineering,member_retention=retention,
            scientific_status='science_pending_review' if engineering=='engineering_validated' else 'science_not_passed_engineering_gate',
            phi=selection['deterministic_phi'],finished_at=stamp(),gradient_gates_used=False))
    except Exception as error:
        legacy.write_json(RUN/'pipeline_status.json',dict(status='failed',error=str(error),failed_at=stamp()))
        raise


def launch():
    if (RUN/'launch_receipt.json').exists(): raise RuntimeError('Already launched')
    model.load_design(CONFIG/'design.json')
    if json.loads((RUN/'pipeline_status.json').read_text(encoding='utf-8'))['status']!='prepared': raise RuntimeError('Not prepared')
    with (RUN/'controller.stdout.log').open('w',encoding='utf-8') as out,(RUN/'controller.stderr.log').open('w',encoding='utf-8') as err:
        p=subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--controller'],cwd=ROOT,stdout=out,stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    legacy.write_json(RUN/'launch_receipt.json',dict(pid=p.pid,launched_at=stamp(),user_statement=AUTH,monitoring_requested=False))
    print(f'Direct-fit joint controller launched, PID={p.pid}',flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--launch',action='store_true');p.add_argument('--controller',action='store_true')
    a=p.parse_args()
    if a.prepare: prepare()
    elif a.launch: launch()
    elif a.controller: controller()
    else: p.error('Select action')


if __name__=='__main__': main()
