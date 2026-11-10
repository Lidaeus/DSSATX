"""Freeze, preflight, screen and execute the user-approved 65-parameter joint IES."""
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
from src.calibration import water_n_joint as model
from src.calibration import single_season_n as legacy

ID='eggplant_26sp_n012_waterN_joint65_20261012'
CONFIG=ROOT/'configs/runs'/ID
RUN=ROOT/'workspace/runs'/ID
REVIEW=ROOT/'configs/calibration_proposals/joint65_water_first_N_pool_revision_20261012'
OLD=ROOT/'configs/runs/eggplant_26sp_n012_c31_joint67_20261011'
GRID=ROOT/'workspace/experiments/n_mobilization_water_grid_20261012'
AUTH='启动正式联合率定'


def stamp(): return dt.datetime.now(dt.timezone.utc).isoformat()


def logged(command,log,cwd=ROOT):
    with Path(log).open('w',encoding='utf-8') as f:
        result=subprocess.run(command,cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
    if result.returncode: raise RuntimeError(f'Process failed ({result.returncode}): {log}')


def make_targets():
    obs=pd.read_csv(OLD/'calibration_observations.csv').fillna('')
    obs['original_weight']=obs.final_weight
    adjacent=pd.read_csv(ROOT/'configs/calibration_proposals/joint67_response_revision_20261012/adjacent_N_targets_review.csv')
    extras=[]
    for r in adjacent.to_dict('records'):
        extras.append(dict(season_id='26SP',dataset_role='calibration',variable=r['variable'],family='N_DOSE_ADJACENT',
            trno=r['trno'],paired_trno=r['paired_trno'],date=r['date'],stratum=r['water_level'],
            observed=r['observed'],sigma_eff=r['sigma_eff'],unit=r['unit'],source_file=r['source'],original_weight=0.,n_eff=1))
    metadata=pd.read_csv(ROOT/'data/user/experiments/xxql2601_refreshed_20261010/treatment_metadata.csv')
    et=pd.read_csv(ROOT/'workspace/audits/observed_et_comparison_20261012/observed_ET_transcription.csv')
    et=et[et.season_id.eq('26SP') & et.nitrogen_level.isin(['N0','N1','N2']) & et.phase.isin(['early','late'])]
    for r in et.to_dict('records'):
        md=metadata[metadata.nitrogen_level.eq(r['nitrogen_level']) & metadata.water_level.eq(r['water_level'])]
        if len(md)!=1: raise ValueError('Ambiguous treatment metadata')
        extras.append(dict(season_id='26SP',dataset_role='calibration',variable='WB100_INTERVAL',family='WATER_BALANCE_100CM',
            trno=int(md.iloc[0].treatment),date=r['end'],interval_start=r['start'],interval_end=r['end'],
            observed=r['observed_ET'],replicate_sd=r['observed_sd'],n_rep=r['n_rep'],n_eff=1,
            sigma_eff=float(np.sqrt(r['observed_sd']**2+10**2+(.1*r['observed_ET'])**2)),unit='mm',
            source_file=r['source'],observation_operator='I+P-runoff-deltaS100, morning [start,end); drainage retained',original_weight=0.))
    for r in obs[obs.variable.eq('W_FRESH_CONTRAST')].to_dict('records'):
        extras.append(dict(season_id='26SP',dataset_role='calibration',variable='W_FRESH_SIGN_PENALTY',family='W_RESPONSE_DIRECTION',
            trno=r['trno'],paired_trno=r['paired_trno'],date=r['date'],stratum=r['stratum'],observed=0.,sigma_eff=1500.,
            unit='kg fresh/ha',source_file='derived from approved paired water-yield contrasts',original_weight=0.,n_eff=1))
    obs=pd.concat([obs,pd.DataFrame(extras)],ignore_index=True).fillna('')
    budget=pd.read_csv(REVIEW/'objective_budget_review.csv').set_index('family')
    for family,part in obs.groupby('family'):
        policy=budget.loc[family]
        if len(part)!=int(policy.n_targets): raise ValueError('Family size differs from approval: '+family)
        obs.loc[part.index,'phi_budget']=float(policy.phi_budget)
        obs.loc[part.index,'final_weight']=np.sqrt(float(policy.phi_budget)/len(part))/part.sigma_eff.astype(float)
    obs['approved']=True;obs['execution_enabled']=True
    obs['obsnme']=[f'wn26_{i:04d}' for i in range(len(obs))]
    if len(obs)!=519 or len(obs.family.unique())!=17 or budget.phi_budget.sum()!=100: raise ValueError('Objective contract differs')
    return obs


def prepare():
    if CONFIG.exists() or RUN.exists(): raise FileExistsError('Never overwrite a formal run')
    proposal=json.loads((REVIEW/'proposal.json').read_text(encoding='utf-8'))
    original=json.loads((OLD/'design.json').read_text(encoding='utf-8'))
    # Verify the historical sealed baseline before deriving any new runtime.
    from src.calibration import joint_n_objectives as oldmodel
    oldmodel.load_design(OLD/'design.json')
    bounds=pd.read_csv(REVIEW/'parameter_scope_review.csv').fillna('')
    bounds['approved']=True
    bounds.loc[bounds.name.eq('SOIL_SLDR'),'file']='SOIL.SOL'
    if len(bounds[bounds.status.eq('active')])!=65: raise ValueError('Incorrect active count')
    CONFIG.mkdir(parents=True);RUN.mkdir(parents=True)
    bounds.to_csv(CONFIG/'bounds_proposal.csv',index=False)
    model.assert_bounds(CONFIG/'bounds_proposal.csv')
    logged([sys.executable,str(ROOT/'tools/freeze_bounds.py'),'--proposal',str(CONFIG/'bounds_proposal.csv'),
        '--crop','eggplant','--bounds-id',ID,'--notes','User approved water-priority direct joint65: KEP and shared SLDR plus N rate and organ protein floors; no initial-condition changes'],RUN/'freeze_bounds.log')
    frozen=ROOT/'data/parameter_registry/bounds_frozen/eggplant'/(ID+'.csv')
    obs=make_targets();obs.to_csv(CONFIG/'calibration_observations.csv',index=False)
    shutil.copy2(OLD/'locked_evaluation_observations.csv',CONFIG/'locked_evaluation_observations.csv')
    shutil.copy2(REVIEW/'objective_budget_review.csv',CONFIG/'approved_objective_policy.csv')
    # Guard baseline is the original 67-parameter deterministic simulation,
    # not either new seed. No 2025 data participate in these limits.
    baseline=pd.read_csv(GRID/'cases/baseline/26SP/calibration_diagnostic_comparison.csv')
    if len(baseline)!=492 or not baseline.simulated.notna().all(): raise ValueError('Incomplete guard baseline')
    sq=np.square((baseline.simulated-baseline.observed)*baseline.final_weight)
    guard=dict(original_phi=float(sq.sum()),nonwater_phi=float(sq[~baseline.family.isin(['SOIL_WATER','W_RESPONSE'])].sum()),nrmse={})
    for variable in model.PROTECTED:
        q=baseline[baseline.variable.eq(variable)]
        guard['nrmse'][variable]=100*float(np.sqrt(np.mean(np.square(q.simulated-q.observed))))/float(q.observed.mean())
    legacy.write_json(CONFIG/'scientific_guard_baseline.json',guard)
    sources=[REVIEW/x for x in ['proposal.json','parameter_scope_review.csv','objective_budget_review.csv','water_priority_constraints_review.csv']]
    sources += [ROOT/'configs/calibration_proposals/joint67_response_revision_20261012/adjacent_N_targets_review.csv',
        ROOT/'workspace/audits/observed_et_comparison_20261012/observed_ET_transcription.csv',
        GRID/'cases/baseline/26SP/calibration_diagnostic_comparison.csv',OLD/'calibration_observations.csv',CONFIG/'scientific_guard_baseline.json']
    runtime=list(original['runtime_hashes'])+['src/calibration/water_n_joint.py','src/dssat/forward_water_n.py',str(Path(__file__).relative_to(ROOT)).replace('\\','/')]
    d=dict(schema='formal_water_n_joint_v1',design_id=ID,approved=True,executable=True,
        approval=dict(user_statement=AUTH,recorded_at=stamp(),review_sha256=legacy.sha(REVIEW/'proposal.json')),
        status='approved_preflight_pending',runtime_preflight_passed=False,datasets=proposal['datasets'],
        bounds_id=ID,bounds_sha256=legacy.sha(frozen),active_parameters=sorted(bounds[bounds.status.eq('active')].name),active_parameter_count=65,
        target_count=519,family_count=17,phi_budget_total=100,calibration_observations_sha256=legacy.sha(CONFIG/'calibration_observations.csv'),
        evaluation_catalog_sha256=legacy.sha(CONFIG/'locked_evaluation_observations.csv'),
        runtime_hashes={r:legacy.sha(ROOT/r) for r in runtime},source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):legacy.sha(p) for p in sources},
        dssat_executable=original['dssat_executable'],dssat_executable_sha256=original['dssat_executable_sha256'],
        noptmax=6,ies_num_reals=200,workers=6,seed=20261012,staged_calibration=False,
        fixed_environment=proposal['fixed_environment'],model_method='R',composition_constraints=proposal['composition_constraints'],
        scientific_candidate_promotion=proposal['scientific_candidate_promotion'],minimum_member_retention=.98,
        parameter_start='reviewed response seed and balanced seed; remainder feasible full-domain Sobol',
        selection_rule='minimum 519 calibration Phi among all exact-complete candidates passing all6 water sign/effect and nonwater guards; otherwise science_not_passed',
        uncertainty_interpretation='feasibility-conditioned optimization ensemble; WB100/VWC correlated; not Bayesian posterior',
        user_monitoring='startup confirmation only',kepsupport='versioned runtime validates approved [.70,.90]; shared historical registry unchanged')
    legacy.write_json(CONFIG/'design.json',d)
    initial=model.validate_parameters(dict(zip(bounds.name,bounds.init)),bounds)
    pd.DataFrame(initial.items(),columns=['name','value']).to_csv(RUN/'initial_parameters.csv',index=False)
    balanced=initial|{'RWUMX':.020,'SOIL_SLDR':.80}
    model.validate_parameters(balanced,bounds)
    pd.DataFrame(balanced.items(),columns=['name','value']).to_csv(RUN/'balanced_seed_parameters.csv',index=False)
    reports=[]
    for seed,param,case in [('response','initial_parameters.csv','water_pool_l0.230_s0.070'),('balanced','balanced_seed_parameters.csv','env_pool_l0.230_s0.070')]:
        comp=model.evaluate(CONFIG/'design.json',RUN/param,RUN/'preflight'/seed,preflight=True)
        # Exact original-date predictions must reproduce the reviewed native grid.
        expected=pd.read_csv(GRID/'cases'/case/'26SP/calibration_diagnostic_comparison.csv').simulated.to_numpy()
        if not np.allclose(comp.simulated.iloc[:492],expected,rtol=1e-10,atol=1e-8): raise ValueError('Seed does not reproduce reviewed grid: '+seed)
        gate=model.candidate_gates(comp,comp.simulated.to_numpy(),guard)
        reports.append(dict(seed=seed,target_count=len(comp),active_injection_count=65,phi=float(np.square((comp.simulated-comp.observed)*comp.final_weight).sum()),
            exact_reviewed_predictions_reproduced=True,scientific_gate=gate))
    legacy.write_json(RUN/'preflight/report.json',dict(status='passed',seeds=reports,targets=519,genotype_and_environment_readback=True,
        fixed_inputs_verified=True,original_runtime_unchanged=True,wrong_water_response_is_not_forward_failure=True))
    d.update(status='approved_ready',runtime_preflight_passed=True)
    legacy.write_json(CONFIG/'design.json',d)
    legacy.write_json(CONFIG/'frozen_configuration_receipt.json',dict(design_sha256=legacy.sha(CONFIG/'design.json'),recorded_at=stamp(),user_statement=AUTH))
    model.load_design(CONFIG/'design.json')
    legacy.write_json(RUN/'approval_receipt.json',dict(user_statement=AUTH,recorded_at=stamp(),design_sha256=legacy.sha(CONFIG/'design.json'),proposal_sha256=legacy.sha(REVIEW/'proposal.json')))
    legacy.write_json(RUN/'pipeline_status.json',dict(status='prepared',phase='preflight_passed',updated_at=stamp()))
    print('Both approved seeds reproduce reviewed predictions; 65/519 preflight passed',flush=True)


def screen_one(pair):
    ordinal,values=pair;folder=RUN/'initial_feasibility'/f'candidate_{ordinal:05d}'
    folder.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(folder/'parameters.csv',index=False)
    try:
        model.evaluate(CONFIG/'design.json',folder/'parameters.csv',folder)
        return dict(ordinal=ordinal,accepted=True,parameters=values,output_sha256=legacy.sha(folder/'FormalObjectives.OUT'))
    except Exception as error: return dict(ordinal=ordinal,accepted=False,error=str(error))


def initial_ensemble():
    d,bounds,obs=model.load_design(CONFIG/'design.json')
    points=qmc.Sobol(d=65,scramble=True,seed=d['seed']).random_base2(13)
    initial=dict(zip(bounds.name,bounds.init));byname=bounds.set_index('name')
    balanced=initial|{'RWUMX':.020,'SOIL_SLDR':.80}
    accepted=[dict(name='base',parameters=initial),dict(name='balanced_seed',parameters=balanced)]
    attempts=[];candidates=[]
    for ordinal,point in enumerate(points):
        values=initial.copy()
        for name,u in zip(d['active_parameters'],point):
            r=byname.loc[name];values[name]=float(r.lower+u*(r.upper-r.lower))
        try: values=model.validate_parameters(values,bounds)
        except ValueError as error:
            attempts.append(dict(ordinal=ordinal,accepted=False,phase='physical_order',error=str(error)));continue
        candidates.append((ordinal,values))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for offset in range(0,len(candidates),12):
            for result in pool.map(screen_one,candidates[offset:offset+12]):
                attempts.append({k:v for k,v in result.items() if k!='parameters'})
                if result['accepted'] and len(accepted)<200:
                    accepted.append(dict(name=f"sobol_{result['ordinal']:05d}",parameters=result['parameters']))
            legacy.write_json(RUN/'initial_feasibility_status.json',dict(status='screening',accepted=len(accepted),target=200,
                evaluated=len([x for x in attempts if x.get('phase')!='physical_order']),updated_at=stamp(),screening_used_observed_residuals=False))
            if len(accepted)==200: break
    pd.DataFrame(attempts).to_csv(RUN/'initial_feasibility_audit.csv',index=False)
    if len(accepted)!=200: raise RuntimeError('Unable to establish 200 feasible members; no automatic range/date/target changes')
    ensemble=pd.DataFrame([{k.lower():v for k,v in x['parameters'].items()} for x in accepted],index=[x['name'] for x in accepted])
    legacy.write_json(RUN/'initial_feasibility_status.json',dict(status='completed',accepted=200,screening_used_observed_residuals=False,seed=d['seed'],updated_at=stamp()))
    return ensemble


def build_case(ensemble):
    d,bounds,obs=model.load_design(CONFIG/'design.json');work=RUN/'joint';work.mkdir()
    (work/'parameters.tpl').write_text('ptf ~\nname,value\n'+''.join(f'{r.name},~ {r.name.lower():<20} ~\n' for r in bounds.itertuples()),encoding='ascii')
    shutil.copy2(RUN/'initial_parameters.csv',work/'parameters.csv')
    (work/'objectives.ins').write_text('pif ~\n'+''.join(f'l1 w !{r.obsnme}!\n' for r in obs.itertuples()),encoding='ascii')
    pst=pyemu.Pst.from_io_files([str(work/'parameters.tpl')],[str(work/'parameters.csv')],[str(work/'objectives.ins')],[str(work/'FormalObjectives.OUT')],pst_path='.')
    for r in bounds.itertuples():
        pst.parameter_data.loc[r.name.lower(),['partrans','parval1','parlbnd','parubnd','pargp']]=['none' if r.status=='active' else 'fixed',r.init,r.lower,r.upper,r.pargp.lower()]
    for r in obs.itertuples(): pst.observation_data.loc[r.obsnme,['obsval','weight','obgnme']]=[r.observed,r.final_weight,r.family.lower()]
    pst.model_command=[f'"{sys.executable}" -X utf8 "{ROOT / "src/calibration/water_n_joint.py"}" --design "{CONFIG / "design.json"}" --param-csv parameters.csv']
    pst.control_data.noptmax=6
    pst.pestpp_options=dict(ies_num_reals=200,ies_include_base=True,ies_no_noise=True,ies_save_binary=False,
        ies_bad_phi_sigma=1e300,ies_initial_lambda=100.,ies_lambda_mults=[.1,1.,10.],lambda_scale_fac=[.05,.1,.25],
        ies_par_en='initial_ensemble.csv',rand_seed=d['seed'],ies_drop_conflicts=False,ies_pdc_sigma_distance=0.,ies_subset_size=30,
        panther_agent_no_ping_timeout_secs=600)
    ensemble.to_csv(work/'initial_ensemble.csv');pst.write(str(work/'joint.pst'),version=1)
    check=pyemu.Pst(str(work/'joint.pst'))
    if check.npar_adj!=65 or check.nnz_obs!=519: raise ValueError('PST contract differs')
    manifest=dict(run_id=ID,mode='eggplant_stage2',design_schema=d['schema'],created_at=stamp(),bounds_id=ID,bounds_sha256=d['bounds_sha256'],
        design_sha256=legacy.sha(CONFIG/'design.json'),n_params=len(bounds),n_params_active=65,n_obs=519,n_obs_positive=519,noptmax=6,ies_num_reals=200,agents=6,
        batch_file='DSSBatch.v48',harvest_var='CHPDT',scientific_status='science_pending',scenario_type='actual_trial_calibration',minimum_member_retention=.98,
        initial_ensemble_sha256=legacy.sha(work/'initial_ensemble.csv'),input_manifest_sha256=next(x['bundle_manifest_sha256'] for x in d['datasets'] if x['season_id']=='26SP'))
    (work/'run_manifest.yaml').write_text(yaml.safe_dump(manifest,sort_keys=False),encoding='utf-8')
    return work


def finalize():
    d,bounds,obs=model.load_design(CONFIG/'design.json');work=RUN/'joint'
    guard=json.loads((CONFIG/'scientific_guard_baseline.json').read_text(encoding='utf-8'))
    candidates=[]
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
            gate=model.candidate_gates(obs,v,guard)
            phi=float(np.square((v-obs.observed.to_numpy())*obs.final_weight.to_numpy()).sum())
            candidates.append(dict(phi=phi,iteration=int(it),realization=real,parameter_file=str(par),
                eligible=gate['eligible'],failures=';'.join(gate['failures']),original_phi=gate['original_phi'],nonwater_phi=gate['nonwater_phi'],
                positive_water_contrasts=gate['positive_water_contrasts'],min_response_ratio=gate['min_response_ratio']))
    if not candidates: raise RuntimeError('No complete valid candidate')
    pd.DataFrame(candidates).to_csv(RUN/'selection_audit.csv',index=False)
    eligible=[x for x in candidates if x['eligible']]
    chosen=min(eligible or candidates,key=lambda x:(x['phi'],x['iteration'],x['realization']))
    table=pd.read_csv(chosen['parameter_file'],index_col=0);table.index=table.index.astype(str)
    values={r.name:float(table.loc[chosen['realization'],r.name.lower()]) for r in bounds.itertuples()}
    file=RUN/('final_parameters.csv' if eligible else 'engineering_candidate_parameters.csv')
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(file,index=False)
    comp=model.evaluate(CONFIG/'design.json',file,RUN/'selected_deterministic')
    checked=float(np.square((comp.simulated-comp.observed)*comp.final_weight).sum())
    if not np.isclose(checked,chosen['phi'],rtol=1e-6,atol=1e-7): raise ValueError('Deterministic Phi reproduction failed')
    gate=model.candidate_gates(comp,comp.simulated.to_numpy(),guard)
    if bool(eligible)!=gate['eligible']: raise ValueError('Deterministic scientific gate changed')
    selection=dict(**chosen,deterministic_phi=checked,scientific_status='science_validated' if eligible else 'science_not_passed',
        eligible_count=len(eligible),validation_used=False,gate=gate,candidate_only=not bool(eligible))
    legacy.write_json(RUN/'selection.json',selection)
    # Locked external checks follow selection, never feeding back into it.
    if legacy.sha(CONFIG/'locked_evaluation_observations.csv')!=d['evaluation_catalog_sha256']: raise ValueError('Locked catalog changed')
    evaluation=pd.read_csv(CONFIG/'locked_evaluation_observations.csv').fillna('');compared=[]
    for dataset in d['datasets']:
        treatments=[t for role,ts in dataset['roles'].items() if role!='calibration' for t in ts]
        if treatments:
            native=model.simulate(RUN/'evaluation'/dataset['season_id'],dataset,treatments,values,executable_sha256=d['dssat_executable_sha256'])
            model.audit_injection(native,values,d['active_parameters'])
            compared.append(legacy.extract_evaluation_observations(native,evaluation[evaluation.season_id.eq(dataset['season_id'])]))
    pd.concat(compared,ignore_index=True).to_csv(RUN/'evaluation_comparison.csv',index=False)
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
        final_files=sorted((f for f in work.glob('joint.*.obs.csv') if f.name.split('.')[1].isdigit()),key=lambda f:int(f.name.split('.')[1]))
        retention=len(pd.read_csv(final_files[-1],index_col=0))/200
        engineering=outcome.get('engineering_status')
        if retention<.98: engineering='engineering_failed'
        scientific=selection['scientific_status'] if engineering=='engineering_validated' else 'science_not_passed_engineering_gate'
        legacy.write_json(RUN/'pipeline_status.json',dict(status='completed',phase='finished',engineering_status=engineering,member_retention=retention,
            scientific_status=scientific,selection_scientific_status=selection['scientific_status'],phi=selection['deterministic_phi'],finished_at=stamp()))
    except Exception as error:
        legacy.write_json(RUN/'pipeline_status.json',dict(status='failed',error=str(error),failed_at=stamp()))
        raise


def launch():
    if (RUN/'launch_receipt.json').exists(): raise RuntimeError('Already launched')
    model.load_design(CONFIG/'design.json')
    state=json.loads((RUN/'pipeline_status.json').read_text(encoding='utf-8'))
    if state['status']!='prepared': raise RuntimeError('Not prepared')
    with (RUN/'controller.stdout.log').open('w',encoding='utf-8') as out,(RUN/'controller.stderr.log').open('w',encoding='utf-8') as err:
        p=subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--controller'],cwd=ROOT,stdout=out,stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    legacy.write_json(RUN/'launch_receipt.json',dict(pid=p.pid,launched_at=stamp(),user_statement=AUTH,monitoring_requested=False))
    print(f'Joint controller launched, PID={p.pid}',flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--launch',action='store_true');p.add_argument('--controller',action='store_true')
    a=p.parse_args()
    if a.prepare: prepare()
    elif a.launch: launch()
    elif a.controller: controller()
    else: p.error('Select action')


if __name__=='__main__': main()
