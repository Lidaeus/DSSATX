"""Prepare, native-screen200, then launch approved robust joint65 in isolation."""
from __future__ import annotations
import argparse
import concurrent.futures as cf
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
from src.calibration import robust_joint as model
from src.calibration import single_season_n as legacy

ID='eggplant_26sp_n012_robust_joint65_200x5_20261012'
CONFIG=ROOT/'configs/runs'/ID
RUN=ROOT/'workspace/runs'/ID
REVIEW=ROOT/'configs/calibration_proposals/joint65_yield_robust_revision_20261012'
AUTH='FL-LF的取值范围设置为 [45.0, 220] 光温日 (PTD)，批准方案，完成新运行适配器及200成员集合预检，启动正式参数联合率定。'

def stamp():return dt.datetime.now(dt.timezone.utc).isoformat()
def write(path,data):legacy.write_json(path,data)
def receipt(d):
    write(CONFIG/'design.json',d)
    write(CONFIG/'frozen_configuration_receipt.json',dict(design_sha256=legacy.sha(CONFIG/'design.json'),recorded_at=stamp()))

def prepare():
    if CONFIG.exists() or RUN.exists():raise FileExistsError('Never overwrite a formal run')
    draft=json.loads((REVIEW/'design.json').read_text(encoding='utf-8'))
    for rel,h in draft['proposal_file_sha256'].items():
        if legacy.sha(ROOT/rel)!=h:raise ValueError('Reviewed artifact changed: '+rel)
    for rel,h in draft['inherited_runtime_hashes'].items():
        if legacy.sha(ROOT/rel)!=h:raise ValueError('Sealed runtime changed: '+rel)
    CONFIG.mkdir(parents=True);RUN.mkdir(parents=True)
    bounds=pd.read_csv(REVIEW/'bounds_proposal.csv').fillna('')
    bounds.loc[bounds.name=='FL-LF',['lower','upper']]=[45.,220.]
    bounds.loc[bounds.name=='FL-LF','reason']='Explicit user approval overrides earlier150–400proposal; units PTD'
    bounds['approved']=True;bounds['execution_enabled']=True
    bounds.to_csv(CONFIG/'approved_bounds_proposal.csv',index=False)
    bound_id=draft['proposed_bounds_id']
    command=[sys.executable,'-X','utf8',str(ROOT/'tools/freeze_bounds.py'),'--proposal',str(CONFIG/'approved_bounds_proposal.csv'),
             '--crop','eggplant','--bounds-id',bound_id,'--notes','Explicitly approved robust joint65; FL-LF45–220PTD; no automatic repairs']
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    (RUN/'bounds_freeze.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError('Bounds freeze failed: '+result.stdout+result.stderr)
    frozen=ROOT/'data/parameter_registry/bounds_frozen/eggplant'/(bound_id+'.csv')
    policy=pd.read_csv(REVIEW/'objective_policy.csv');policy['approved']=True
    obs=pd.read_csv(REVIEW/'observation_catalog.csv').fillna('');obs['approved']=True;obs['execution_enabled']=True
    policy.to_csv(CONFIG/'approved_objective_policy.csv',index=False)
    obs.to_csv(CONFIG/'calibration_observations.csv',index=False)
    old=ROOT/draft['parent_design']
    shutil.copy2(old.parent/'locked_evaluation_observations.csv',CONFIG/'locked_evaluation_observations.csv')
    base=dict(zip(bounds.name,bounds.init))
    references={'seed_yield':base,'seed_water':base|{'RWUMX':.0105},'seed_canopy':base|{'FL-LF':180.,'SENPOR_LATE':.15}}
    for name,values in references.items():
        model.validate_parameters(values,bounds)
        pd.DataFrame(values.items(),columns=['name','value']).to_csv(RUN/(name+'_parameters.csv'),index=False)
    shutil.copy2(RUN/'seed_yield_parameters.csv',RUN/'initial_parameters.csv')
    runtime=dict(draft['inherited_runtime_hashes'])
    for f in ['src/calibration/robust_joint.py','src/dssat/forward_robust_joint.py','tools/calibration/launch_robust_joint_200x5_20261012.py']:
        runtime[f]=legacy.sha(ROOT/f)
    sources=[REVIEW/'design.json',REVIEW/'bounds_proposal.csv',REVIEW/'objective_policy.csv',REVIEW/'observation_catalog.csv',old,
             CONFIG/'approved_bounds_proposal.csv',CONFIG/'approved_objective_policy.csv',RUN/'initial_parameters.csv']
    d=dict(draft)
    d.update(schema='formal_robust_joint_v1',design_id=ID,approved=True,executable=True,status='native_preflight_pending',
        approval=dict(user_statement=AUTH,recorded_at=stamp(),change='FL-LF45–220PTD; rest of approved proposal retained'),
        runtime_preflight_passed=False,ensemble_preflight_passed=False,bounds_id=bound_id,bounds_sha256=legacy.sha(frozen),
        bounds_state='approved_frozen',runtime_implementation_pending=False,
        calibration_observations_sha256=legacy.sha(CONFIG/'calibration_observations.csv'),
        policy_sha256=legacy.sha(CONFIG/'approved_objective_policy.csv'),evaluation_catalog_sha256=legacy.sha(CONFIG/'locked_evaluation_observations.csv'),
        runtime_hashes=runtime,source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):legacy.sha(p) for p in sources},
        gradient_hard_gates=False,seed=20261012,scientific_status='science_pending',
        reference_change='seed_broadFL300 is outside new approved bound; replaced withFL180/SENPOR.15 feasible canopy reference',
        initialization=dict(base='seed_yieldFL220',reference_seeds=['seed_water','seed_canopy'],base_members=1,reference_members=2,local_members=147,global_members=50,
            local_sampling='Sobol ordinal rejection sampling, center ±10% full revised range intersect bounds; no clipping',
            global_sampling='fixed Sobol ordinal order; physical/readback/exact-date completeness only; no residual ranking'),
        parameter_step_handling='infeasible requested or printed candidates fail explicitly; PEST lambda trials use step factors.05/.1/.25; no parameter projection or missing-fruit imputation')
    write(CONFIG/'design.json',d)
    reports=[]
    for name,values in references.items():
        compared=model.evaluate(CONFIG/'design.json',RUN/(name+'_parameters.csv'),RUN/'preflight'/name,preflight=True)
        scores=model.metrics(compared);scores.to_csv(RUN/'preflight'/name/'family_metrics.csv',index=False)
        phi=float(compared.phi_contribution.sum())
        assert np.isclose(phi,scores.phi.sum(),rtol=1e-12)
        if name in ['seed_yield','seed_water']:
            prior=pd.read_csv(REVIEW/(name+'_objective_preflight.csv'))
            assert compared.obsnme.tolist()==prior.obsnme.tolist()
            assert np.allclose(compared.simulated,prior.simulated,rtol=1e-10,atol=1e-8)
            assert np.allclose(compared.pest_output,prior.pest_output,rtol=1e-10,atol=1e-10)
        reports.append(dict(seed=name,targets=len(compared),active_readback=65,phi=phi,complete=True))
    # Direct native test of the user's new lower endpoint, without residual filtering.
    lower=base|{'FL-LF':45.}
    pd.DataFrame(lower.items(),columns=['name','value']).to_csv(RUN/'preflight/fl45_parameters.csv',index=False)
    compared=model.evaluate(CONFIG/'design.json',RUN/'preflight/fl45_parameters.csv',RUN/'preflight/fl45',preflight=True)
    reports.append(dict(seed='fl45_endpoint',targets=len(compared),phi=float(compared.phi_contribution.sum()),complete=True))
    write(RUN/'preflight/report.json',dict(status='passed',seeds=reports,raw_and_transformed_deterministic_reproduction=True,
          lower_FL_LF_endpoint_native_checked=True,missing_fruit_imputed=False,approval_reference_adjustment=d['reference_change']))
    d.update(runtime_preflight_passed=True,status='ensemble_preflight_pending');receipt(d)
    write(RUN/'approval_receipt.json',dict(user_statement=AUTH,recorded_at=stamp(),design_sha256=legacy.sha(CONFIG/'design.json')))
    write(RUN/'pipeline_status.json',dict(status='prepared',phase='ensemble_preflight_pending',updated_at=stamp()))
    model.load_design(CONFIG/'design.json')
    print('Runtime/native seed preflight passed:65parameters,516targets,FL-LF45–220PTD',flush=True)

def screen_one(task):
    group,ordinal,values=task;name=f'{group}_{ordinal:05d}';folder=RUN/'initial_feasibility'/name
    folder.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(folder/'parameters.csv',index=False)
    try:
        comp=model.evaluate(CONFIG/'design.json',folder/'parameters.csv',folder)
        printed=pd.read_csv(folder/'_model/joint_parameter_injection_audit.csv')
        if len(comp)!=516 or len(printed)!=65:raise ValueError('Incomplete native preflight')
        return dict(name=name,group=group,ordinal=ordinal,accepted=True,parameters=values,
                    output=comp.set_index('obsnme').pest_output.to_dict(),phi=float(comp.phi_contribution.sum()),
                    targets=516,output_sha256=legacy.sha(folder/'FormalObjectives.OUT'),parameter_sha256=legacy.sha(folder/'parameters.csv'))
    except Exception as e:
        write(folder/'feasibility_failure.json',dict(error=str(e),residual_based_rejection=False))
        return dict(name=name,group=group,ordinal=ordinal,accepted=False,error=str(e))

def ensemble_preflight():
    d,bounds,obs=model.load_design(CONFIG/'design.json')
    if d.get('ensemble_preflight_passed'):raise RuntimeError('200-member preflight already complete')
    indexed=bounds.set_index('name');active=d['active_parameters'];center=dict(zip(bounds.name,bounds.init))
    lo=indexed.loc[active,'lower'].to_numpy();hi=indexed.loc[active,'upper'].to_numpy();mid=np.array([center[k] for k in active])
    a=np.maximum(lo,mid-.1*(hi-lo));b=np.minimum(hi,mid+.1*(hi-lo))
    pd.DataFrame(dict(name=active,center=mid,frozen_lower=lo,frozen_upper=hi,local_lower=a,local_upper=b)).to_csv(RUN/'local_initial_support.csv',index=False)
    accepted=[];audit=[]
    for name,real in [('seed_yield','base'),('seed_water','seed_water'),('seed_canopy','seed_canopy')]:
        v=model.validate_parameters(legacy.runner._read_param_dict(RUN/(name+'_parameters.csv')),bounds)
        comp=pd.read_csv(RUN/'preflight'/name/'last_comparison.csv')
        accepted.append(dict(name=real,group='reference',parameters=v,output=comp.set_index('obsnme').pest_output.to_dict()))
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        for group,target,left,right,seed in [('local',147,a,b,d['seed']),('global',50,lo,hi,d['seed']+1)]:
            points=qmc.Sobol(d=65,scramble=True,seed=seed).random_base2(14)
            count=0;index=0
            while count<target and index<len(points):
                batch=[]
                while len(batch)<min(12,target-count) and index<len(points):
                    ordinal=index;point=points[index];index+=1
                    values=center|dict(zip(active,left+point*(right-left)))
                    try:values=model.validate_parameters(values,bounds)
                    except ValueError as e:
                        audit.append(dict(group=group,ordinal=ordinal,accepted=False,phase='physical_order',error=str(e)));continue
                    batch.append((group,ordinal,values))
                for r in pool.map(screen_one,batch):
                    audit.append({k:v for k,v in r.items() if k not in ['parameters','output']})
                    if r['accepted']:
                        accepted.append(r);count+=1
                state=dict(status='screening',group=group,group_accepted=count,group_target=target,accepted=len(accepted),target=200,updated_at=stamp(),screening_used_observed_residuals=False)
                write(RUN/'initial_feasibility_status.json',state)
                pd.DataFrame(audit).to_csv(RUN/'initial_feasibility_audit.csv',index=False)
                print(f'Native preflight {group}:{count}/{target};total:{len(accepted)}/200',flush=True)
            if count!=target:raise RuntimeError('Insufficient feasible members; no bounds or target auto-repair')
    ensemble=pd.DataFrame([{k.lower():v for k,v in x['parameters'].items()} for x in accepted],index=[x['name'] for x in accepted])
    predictions=pd.DataFrame([x['output'] for x in accepted],index=ensemble.index)[obs.obsnme]
    assert len(ensemble)==200 and ensemble.index.is_unique and np.isfinite(predictions.to_numpy()).all()
    assert (ensemble.loc[:,'fl-lf'].between(45,220)).all()
    ensemble.to_csv(RUN/'initial_ensemble.csv');predictions.to_csv(RUN/'initial_observation_ensemble.csv')
    phi=np.square(predictions.to_numpy()*obs.final_weight.to_numpy()).sum(axis=1)
    pd.DataFrame(dict(realization=ensemble.index,complete_targets=516,phi=phi)).to_csv(RUN/'initial_member_phi.csv',index=False)
    write(RUN/'initial_feasibility_status.json',dict(status='completed',accepted=200,local_accepted=147,global_accepted=50,references=3,targets_per_member=516,
        member_target_pairs=103200,screening_used_observed_residuals=False,missing_values_imputed=False,updated_at=stamp()))
    d.update(ensemble_preflight_passed=True,status='approved_ready',initial_ensemble_sha256=legacy.sha(RUN/'initial_ensemble.csv'),
             initial_observation_ensemble_sha256=legacy.sha(RUN/'initial_observation_ensemble.csv'))
    receipt(d);build_case(ensemble,predictions)
    write(RUN/'pipeline_status.json',dict(status='prepared',phase='ies_ready',members=200,updated_at=stamp()))
    print('200/200 native members passed;103200 complete exact-date target pairs;formal case ready',flush=True)

def build_case(ensemble,predictions):
    d,bounds,obs=model.load_design(CONFIG/'design.json');work=RUN/'joint';work.mkdir()
    (work/'parameters.tpl').write_text('ptf ~\nname,value\n'+''.join(f'{r.name},~ {r.name.lower():<20} ~\n' for r in bounds.itertuples()),encoding='ascii')
    shutil.copy2(RUN/'initial_parameters.csv',work/'parameters.csv')
    shutil.copy2(RUN/'preflight/seed_yield/FormalObjectives.OUT',work/'FormalObjectives.OUT')
    (work/'objectives.ins').write_text('pif ~\n'+''.join(f'l1 w !{r.obsnme}!\n' for r in obs.itertuples()),encoding='ascii')
    pst=pyemu.Pst.from_io_files([str(work/'parameters.tpl')],[str(work/'parameters.csv')],[str(work/'objectives.ins')],[str(work/'FormalObjectives.OUT')],pst_path='.')
    for r in bounds.itertuples():
        pst.parameter_data.loc[r.name.lower(),['partrans','parval1','parlbnd','parubnd','pargp']]=['none' if r.status=='active' else 'fixed',ensemble.loc['base',r.name.lower()],r.lower,r.upper,r.pargp.lower()]
    for r in obs.itertuples():pst.observation_data.loc[r.obsnme,['obsval','weight','obgnme']]=[0.,r.final_weight,r.family.lower()]
    pst.model_command=[f'"{sys.executable}" -X utf8 "{ROOT / "src/calibration/robust_joint.py"}" --design "{CONFIG / "design.json"}" --param-csv parameters.csv']
    pst.control_data.noptmax=5
    pst.pestpp_options=dict(ies_num_reals=200,ies_include_base=True,ies_no_noise=True,ies_save_binary=False,
        ies_bad_phi_sigma=1e300,ies_initial_lambda=100.,ies_lambda_mults=[.1,1.,10.],lambda_scale_fac=[.05,.1,.25],
        ies_par_en='initial_ensemble.csv',rand_seed=d['seed'],
        ies_drop_conflicts=False,ies_pdc_sigma_distance=0.,ies_subset_size=30,panther_agent_no_ping_timeout_secs=600)
    ensemble.to_csv(work/'initial_ensemble.csv');predictions.to_csv(work/'initial_observation_ensemble.csv')
    pst.write(str(work/'joint.pst'),version=1);check=pyemu.Pst(str(work/'joint.pst'))
    assert check.npar_adj==65 and check.nnz_obs==516 and check.control_data.noptmax==5
    commit=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
    manifest=dict(run_id=ID,git_commit=commit,mode='eggplant_stage2',design_schema=d['schema'],created_at=stamp(),
        bounds_id=d['bounds_id'],bounds_sha256=d['bounds_sha256'],design_sha256=legacy.sha(CONFIG/'design.json'),
        n_params=len(bounds),n_params_active=65,n_obs=516,n_obs_positive=516,noptmax=5,ies_num_reals=200,agents=6,
        batch_file='DSSBatch.v48',harvest_var='CHPDT',scientific_status='science_pending',scenario_type='actual_trial_calibration',minimum_member_retention=.98,
        initial_ensemble_sha256=legacy.sha(work/'initial_ensemble.csv'),initial_observation_ensemble_sha256=legacy.sha(work/'initial_observation_ensemble.csv'),
        input_manifest_sha256=next(x['bundle_manifest_sha256'] for x in d['datasets'] if x['season_id']=='26SP'),
        objective_output='signed_sqrt_loss; zero PEST observations; raw observed/simulated separately retained')
    (work/'run_manifest.yaml').write_text(yaml.safe_dump(manifest,sort_keys=False),encoding='utf-8')
    write(RUN/'formal_case_receipt.json',dict(pst_sha256=legacy.sha(work/'joint.pst'),adjustable_parameters=65,targets=516,initial_members=200,
        native_preflight_passed=True,initial_predictions_reused=False,final_yield_budget=70,organ_N_budget=4,soft_contrast_budget=3,hard_gradient_gates=False))

def finalize():
    d,bounds,obs=model.load_design(CONFIG/'design.json');work=RUN/'joint';candidates=[]
    for file in work.glob('joint.*.obs.csv'):
        it=file.name.removeprefix('joint.').removesuffix('.obs.csv');par=work/f'joint.{it}.par.csv'
        if not it.isdigit() or not par.exists():continue
        out=pd.read_csv(file,index_col=0);pars=pd.read_csv(par,index_col=0)
        out.index=out.index.astype(str);pars.index=pars.index.astype(str)
        for real in out.index.intersection(pars.index):
            encoded=out.loc[real,obs.obsnme].to_numpy(dtype=float)
            if not np.isfinite(encoded).all():continue
            values={r.name:float(pars.loc[real,r.name.lower()]) for r in bounds.itertuples()}
            try:model.validate_parameters(values,bounds)
            except ValueError:continue
            candidates.append(dict(phi=float(np.square(encoded*obs.final_weight.to_numpy()).sum()),iteration=int(it),realization=real,parameter_file=str(par),complete_targets=516))
    if not candidates:raise RuntimeError('No complete physically valid candidate')
    pd.DataFrame(candidates).to_csv(RUN/'selection_audit.csv',index=False)
    chosen=min(candidates,key=lambda x:(x['phi'],x['iteration'],x['realization']))
    table=pd.read_csv(chosen['parameter_file'],index_col=0);table.index=table.index.astype(str)
    values={r.name:float(table.loc[chosen['realization'],r.name.lower()]) for r in bounds.itertuples()}
    file=RUN/'best_calibration_parameters.csv';pd.DataFrame(values.items(),columns=['name','value']).to_csv(file,index=False)
    compared=model.evaluate(CONFIG/'design.json',file,RUN/'selected_deterministic')
    metrics=model.metrics(compared);metrics.to_csv(RUN/'calibration_family_metrics.csv',index=False)
    checked=float(metrics.phi.sum())
    if not np.isclose(checked,chosen['phi'],rtol=1e-6,atol=1e-8):raise ValueError('Deterministic objective reproduction failed')
    pd.read_csv(RUN/'preflight/seed_yield/family_metrics.csv').merge(metrics,on='family',suffixes=('_initial','_selected')).to_csv(RUN/'initial_vs_selected_metrics.csv',index=False)
    compared[compared.family.isin(['W_SIGNED_CONTRAST','N_ADJACENT_SIGNED_CONTRAST'])].to_csv(RUN/'water_n_gradient_diagnostics.csv',index=False)
    selection=chosen|dict(deterministic_phi=checked,validation_used=False,gradient_gates_used=False,scientific_status='science_pending_review')
    write(RUN/'selection.json',selection)
    if legacy.sha(CONFIG/'locked_evaluation_observations.csv')!=d['evaluation_catalog_sha256']:raise ValueError('Validation catalog changed')
    evaluation=pd.read_csv(CONFIG/'locked_evaluation_observations.csv').fillna('');checks=[]
    for dataset in d['datasets']:
        treatments=[t for role,ts in dataset['roles'].items() if role!='calibration' for t in ts]
        if treatments:
            native=model.simulate(RUN/'evaluation'/dataset['season_id'],dataset,treatments,values,executable_sha256=d['dssat_executable_sha256'])
            model.audit_injection(native,values,d['active_parameters'])
            checks.append(legacy.extract_evaluation_observations(native,evaluation[evaluation.season_id==dataset['season_id']]))
    pd.concat(checks,ignore_index=True).to_csv(RUN/'evaluation_comparison.csv',index=False)
    return selection

def controller():
    try:
        d,_,_=model.load_design(CONFIG/'design.json')
        if not d.get('ensemble_preflight_passed'):raise RuntimeError('Cannot start without200native members')
        write(RUN/'pipeline_status.json',dict(status='running',phase='ies',controller_pid=os.getpid(),members=200,updated_at=stamp()))
        command=[sys.executable,'-X','utf8',str(ROOT/'tools/parallel/run_parallel.py'),'--run-dir',str(RUN/'joint'),'--case','joint','--mode','ies','--n-agents','6','--wait']
        with (RUN/'parallel_controller.log').open('w',encoding='utf-8') as log:r=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if r.returncode:raise RuntimeError('PEST parallel process failed; inspect parallel_controller.log')
        outcome=json.loads((RUN/'joint/run_status.json').read_text(encoding='utf-8'))
        if outcome.get('status')!='completed' or 'analysis complete' not in (RUN/'joint/joint.rec').read_text(errors='replace').lower():raise RuntimeError('PEST completion not confirmed')
        write(RUN/'pipeline_status.json',dict(status='running',phase='postselection',updated_at=stamp()))
        selection=finalize()
        files=sorted((p for p in (RUN/'joint').glob('joint.*.obs.csv') if p.name.split('.')[1].isdigit()),key=lambda p:int(p.name.split('.')[1]))
        retention=len(pd.read_csv(files[-1],index_col=0))/200
        engineering=outcome.get('engineering_status') if retention>=.98 else 'engineering_failed'
        write(RUN/'pipeline_status.json',dict(status='completed',phase='finished',engineering_status=engineering,member_retention=retention,
            scientific_status='science_pending_review' if engineering=='engineering_validated' else 'science_not_passed_engineering_gate',phi=selection['deterministic_phi'],finished_at=stamp()))
    except Exception as e:
        write(RUN/'pipeline_status.json',dict(status='failed',error=str(e),failed_at=stamp()));raise

def launch():
    if (RUN/'launch_receipt.json').exists():raise RuntimeError('Already launched')
    d,_,_=model.load_design(CONFIG/'design.json')
    if not d.get('ensemble_preflight_passed') or json.loads((RUN/'pipeline_status.json').read_text(encoding='utf-8')).get('phase')!='ies_ready':raise RuntimeError('200-member preflight/PST not ready')
    for f,key in [('initial_ensemble.csv','initial_ensemble_sha256'),('initial_observation_ensemble.csv','initial_observation_ensemble_sha256')]:
        if legacy.sha(RUN/f)!=d[key] or legacy.sha(RUN/'joint'/f)!=d[key]:raise ValueError('Initial ensemble changed')
    with (RUN/'controller.stdout.log').open('w',encoding='utf-8') as out,(RUN/'controller.stderr.log').open('w',encoding='utf-8') as err:
        process=subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--controller'],cwd=ROOT,stdout=out,stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    write(RUN/'launch_receipt.json',dict(pid=process.pid,launched_at=stamp(),user_statement=AUTH,monitoring_requested=False,native_preflight_members=200))
    print(f'Formal robust joint65 controller launched,PID={process.pid}',flush=True)

def main():
    p=argparse.ArgumentParser();group=p.add_mutually_exclusive_group(required=True)
    for name in ['prepare','preflight','launch','controller']:group.add_argument('--'+name,action='store_true')
    a=p.parse_args()
    if a.prepare:prepare()
    elif a.preflight:ensemble_preflight()
    elif a.launch:launch()
    else:controller()

if __name__=='__main__':main()
