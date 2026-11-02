"""Native wiring probes, frozen bounds, then real 80 x 4 IES with six workers."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse,json,shutil,subprocess,sys
import numpy as np
import pandas as pd
import pyemu

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
MAIN=Path('D:/Tomato_Cal');CN=MAIN/'subprojects/critical_n'
OLD=CN/'runs/n4864_p5_r2_explicit_smoke14_24x2_20261102'
REFERENCE=CN/'reports/A_budget_feedback_20261102/parameter_reference'
sys.path.insert(0,str(REPO/'research/n_integration_v2'))
from smoke_forward import sha,dump
from calibration_smoke import launch
from forward_A import evaluate

NI_DOMAINS={
 'q_no3_max':(.0015,.012), 'assim_no3_v':(.0015,.012),
 'assim_no3_k':(.00025,.004), 'root_v':(.00005,.001),
 'root_k':(2.,40.), 'diffusion_k':(.001,.02), 'pool_beta':(.25,4.),
 'leaf_a':(.030,.050), 'stem_a':(.014,.035),
 'leaf_b':(.20,.45), 'stem_b':(.20,.45),
 'min_ratio':(.40,.75), 'max_ratio':(1.10,1.25),
 'photo_gamma':(.7,2.), 'growth_tau':(.5,4.),
 'photo_slw_ref':(.0028,.0056), 'curve_w0':(.7,1.5),
}


def prepare(root):
    root.mkdir(parents=True,exist_ok=False);(root/'bin').mkdir()
    shutil.copy2(REPO/'build/bin/dscsm048.exe',root/'bin/dscsm048_A.exe')
    shutil.copy2(MAIN/'pestpp-5.2.16-win/bin/pestpp-ies.exe',root/'bin/pestpp-ies.exe')
    old=json.loads((OLD/'design.json').read_text(encoding='utf8'))
    original=Path(json.loads((OLD/'diagnostics_r020_20261102/last_success.json').read_text(encoding='utf8'))['trial'])
    (root/'inputs').mkdir()
    for p in Path(old['inputs']).iterdir():
        if p.is_file():shutil.copy2(original/p.name,root/'inputs'/p.name)
    shutil.copy2(OLD/'observations.csv',root/'observations.csv')
    shutil.copy2(REFERENCE/'active_parameters_76.source.csv',root/'reference_active_76.csv')
    shutil.copytree(MAIN/'src',root/'runtime/src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for p in [HERE/'forward_A.py',REPO/'research/n_integration_v2/smoke_forward.py']:
        shutil.copy2(p,root/'runtime'/p.name)
    sys.path.insert(0,str(root/'runtime'))
    from src.calibration.single_season_n import read_injected_parameters
    from src.common.param_registry import PHYSICAL_BOUNDS
    parsed=read_injected_parameters(root/'inputs')
    slines=(root/'inputs/TMGRO048.SPE').read_text(encoding='ascii').splitlines()
    for n,mark,start in [('ICMP','ICMP,TCMP',0),('TCMP','ICMP,TCMP',6),('KEP','KEP, EORATIO',0)]:
        parsed[n]=(float(next(l for l in slines if mark in l)[start:start+6]),0.)
    lines=(root/'inputs/SOIL.SOL').read_text(encoding='ascii').splitlines()
    parsed['SOIL_SLDR']=(float(lines[next(i for i,l in enumerate(lines)if l.startswith('@ SCOM'))+1][18:24]),0.)
    candidates=pd.read_csv(REFERENCE/'native_bound_candidates.csv')
    rows=[]
    for r in candidates.itertuples():
        # KEP is an existing frozen working parameter, absent from the main
        # registry. Retain its user range inside an explicit local [0,1]
        # engineering domain; do not silently add a global physical rule.
        lo,hi=PHYSICAL_BOUNDS[r.name] if r.name!='KEP' else (0.,1.)
        if not lo<=r.lower<r.upper<=hi:raise ValueError('Native physical domain '+r.name)
        baseline=parsed[r.name][0]
        initial=float(np.clip(baseline,r.lower,r.upper))
        rows.append(dict(name=r.name,init=initial,lower=r.lower,upper=r.upper,status='active',pargp='native',
                         location=r.location,baseline_value=baseline,reference_init=r.init,
                         domain_source='user_reference_76_exact_native_range',unit_role='official native parameter'))
    oldvals=pd.read_csv(OLD/'best_parameters.csv').set_index('name').value.to_dict()
    nitrogen_names=old['nitrogen_names']+['curve_w0','photo_slw_ref']
    for name in nitrogen_names:
        initial=oldvals.get(name,{'curve_w0':1.,'photo_slw_ref':.0028}.get(name))
        if name=='max_ratio':initial=1.1
        lo,hi=NI_DOMAINS.get(name,(initial,initial))
        rows.append(dict(name=name,init=float(np.clip(initial,lo,hi)),lower=lo,upper=hi,
                         status='active'if name in NI_DOMAINS else'fixed',pargp='new_n',location='NIntegration.nml',
                         baseline_value=oldvals.get(name,initial),reference_init=None,
                         domain_source='explicit_engineering_domain_after_controlled_A_tests; not biological confidence interval',
                         unit_role='NI specification; N fractions g/g; root_v gN/m root/d; photo_slw_ref gDM/cm2 leaf; curve_w0 tDM/ha'))
    bounds=pd.DataFrame(rows);bounds['pest_name']=[f'p{i:03}'for i in range(len(bounds))]
    bounds.to_csv(root/'candidate_bounds.csv',index=False)
    base=pd.DataFrame(dict(name=bounds.pest_name,value=bounds.init));base.to_csv(root/'base_parameters.csv',index=False)
    d=dict(schema='A_joint_native_IES_v1',binary=str(root/'bin/dscsm048_A.exe'),binary_sha256=sha(root/'bin/dscsm048_A.exe'),
           bounds=str(root/'candidate_bounds.csv'),observations=str(root/'observations.csv'),inputs=str(root/'inputs'),runtime=str(root/'runtime'),
           nitrogen_names=nitrogen_names,members=80,updates=4,workers=6,targets=612,season='26SP',required_mode={'ni_stage':5,'root_mode':2,'budget_revision':1},
           protected=old['protected'],frozen_hashes={},ready_for_IES=False,
           reference=str(root/'reference_active_76.csv'),reference_sha256=sha(root/'reference_active_76.csv'),
           source_head=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip(),
           source_dirty=subprocess.check_output(['git','-C',str(REPO),'status','--porcelain'],text=True).strip(),
           objective_limitation='Existing 612 targets and reduced-organic-N operators unchanged; nitrate assay recovery unconfirmed',
           V15_physiology_adopted=False)
    dump(root/'preparation_design.json',d)
    return d


def preflight(root,d):
    first=evaluate(root/'preparation_design.json',root/'base_parameters.csv',root/'preflight/base')
    again=evaluate(root/'preparation_design.json',root/'base_parameters.csv',root/'preflight/repeat')
    if first['phi']!=again['phi']:raise ValueError('Deterministic repeat failed')
    bound=pd.read_csv(d['bounds']);base=pd.read_csv(root/'base_parameters.csv')
    baseline=pd.read_csv(Path(first['trial'])/'PlantNIntegration.csv')
    basecomp=pd.read_csv(Path(first['trial'])/'comparison.csv')
    results=[]
    def one(row):
        w=root/'preflight'/row.pest_name;w.mkdir(exist_ok=True)
        frame=base.copy();value=row.lower if abs(row.init-row.lower)>abs(row.upper-row.init)else row.upper
        frame.loc[frame.name==row.pest_name,'value']=value;frame.to_csv(w/'parameters.csv',index=False)
        first_endpoint_error=None
        try:result=evaluate(root/'preparation_design.json',w/'parameters.csv',w)
        except ValueError as e:
            # A physically empty commercial-fruit inventory has no N
            # concentration. Preserve the failed endpoint; never invent an
            # objective or change its date to make the probe pass.
            if 'No mature fruit at the exact N sampling date'not in str(e):raise
            first_endpoint_error=str(e)
            value=row.upper if value==row.lower else row.lower
            frame.loc[frame.name==row.pest_name,'value']=value
            frame.to_csv(w/'parameters_other_endpoint.csv',index=False)
            result=evaluate(root/'preparation_design.json',w/'parameters_other_endpoint.csv',w/'other_endpoint')
        native=pd.read_csv(Path(result['trial'])/'PlantNIntegration.csv')
        comp=pd.read_csv(Path(result['trial'])/'comparison.csv')
        change=float(np.max(np.abs(native.iloc[:,3:].to_numpy()-baseline.iloc[:,3:].to_numpy())))
        effect=float(np.max(np.abs(comp.simulated-basecomp.simulated)))
        context=None
        if row.name=='TCMP'and change<=1.e-10 and effect<=1.e-8:
            # TCMP governs the time course after the ICMP light threshold
            # is crossed. A single unshaded baseline cannot test its wiring.
            icmp=bound[bound.name=='ICMP'].iloc[0]
            f0=base.copy();f0.loc[f0.name==icmp.pest_name,'value']=icmp.upper
            f0.to_csv(w/'context_base.csv',index=False)
            rb=evaluate(root/'preparation_design.json',w/'context_base.csv',w/'context_base')
            f0.loc[f0.name==row.pest_name,'value']=value;f0.to_csv(w/'context_changed.csv',index=False)
            rc=evaluate(root/'preparation_design.json',w/'context_changed.csv',w/'context_changed')
            nb=pd.read_csv(Path(rb['trial'])/'PlantNIntegration.csv');nc=pd.read_csv(Path(rc['trial'])/'PlantNIntegration.csv')
            change=float(np.max(np.abs(nb.iloc[:,3:].to_numpy()-nc.iloc[:,3:].to_numpy())))
            cb=pd.read_csv(Path(rb['trial'])/'comparison.csv');cc=pd.read_csv(Path(rc['trial'])/'comparison.csv')
            effect=float(np.max(np.abs(cb.simulated-cc.simulated)))
            context=f'ICMP={icmp.upper}; TCMP contrast only, both native runs retained'
        return dict(name=row.name,pest_name=row.pest_name,requested=value,native_change=change,objective_change=effect,
                    effective=change>1.e-10 or effect>1.e-8,success=True,phi=result['phi'],trial=result['trial'],
                    first_endpoint_error=first_endpoint_error,interaction_context=context)
    with ThreadPoolExecutor(max_workers=6)as pool:
        jobs={pool.submit(one,r):r.name for r in bound[bound.status=='active'].itertuples()}
        for job in as_completed(jobs):
            name=jobs[job]
            try:results.append(job.result())
            except Exception as e:results.append(dict(name=name,success=False,effective=False,error=str(e)))
            print('wiring',name,results[-1].get('effective'),results[-1].get('error',''),flush=True)
    wiring=pd.DataFrame(results);wiring.to_csv(root/'parameter_wiring_preflight.csv',index=False)
    if not wiring.success.all():raise RuntimeError('Native wiring probes failed; repair before IES')
    # Truly inactive fields are excluded; retain their original requested
    # ranges in the audit, rather than claiming a 76-parameter active model.
    inactive=set(wiring.loc[~wiring.effective,'name'])
    bound.loc[bound.name.isin(inactive),'status']='fixed'
    # Physical ranges remain recorded. PEST fixed fields receive a constant
    # in the forward contract, while their unused domains are not sampled.
    fixed=bound.status=='fixed'
    bound.loc[fixed,'lower']=bound.loc[fixed,'init'];bound.loc[fixed,'upper']=bound.loc[fixed,'init']
    dest=root/'data/parameter_registry/bounds_frozen/eggplant/A_joint_20261102.csv';dest.parent.mkdir(parents=True)
    bound.to_csv(dest,index=False)
    dump(dest.with_suffix('.meta.json'),dict(status='frozen',reference_sha256=d['reference_sha256'],
          native_ranges_preserved=True,excluded_after_probe=sorted(inactive),V15_physiology_adopted=False,
          new_N_domain_status='engineering working domains, not established biological hard bounds',
          initial_policy='r020 native input bounded into user ranges; no adoption of V15 best parameter vector',
          breakpoint_policy='0.7/1.0 controlled; working domain 0.7-1.5 combines explicit 0.7 comparison with reference upper 1.5'))
    d.update(bounds=str(dest),ready_for_IES=True,active=int((bound.status=='active').sum()),excluded_after_probe=sorted(inactive))
    immutable=[p for p in (root/'runtime').rglob('*')if p.is_file()and '__pycache__'not in p.parts]
    immutable+=list((root/'inputs').glob('*'))+[dest,dest.with_suffix('.meta.json'),root/'observations.csv',root/'reference_active_76.csv',root/'bin/dscsm048_A.exe',root/'bin/pestpp-ies.exe']
    d['frozen_hashes']={str(p):sha(p)for p in immutable}
    dump(root/'design.json',d)
    dump(root/'preflight_receipt.json',dict(passed=True,deterministic_phi=first['phi'],active=d['active'],
         excluded_after_probe=sorted(inactive),native_probes=len(results),new_budget=first['budget']))
    return bound


def control(root,d,bounds):
    template=root/'template';template.mkdir()
    (template/'parameters.tpl').write_text('ptf ~\nname,value\n'+''.join(f'{r.pest_name},~ {r.pest_name:18} ~\n'for r in bounds.itertuples()),encoding='ascii')
    pd.DataFrame(dict(name=bounds.pest_name,value=bounds.init)).to_csv(template/'parameters.csv',index=False)
    obs=pd.read_csv(d['observations'])
    (template/'objectives.ins').write_text('pif ~\n'+''.join(f'l1 w !{n}!\n'for n in obs.obsnme),encoding='ascii')
    pst=pyemu.Pst.from_io_files([str(template/'parameters.tpl')],[str(template/'parameters.csv')],[str(template/'objectives.ins')],[str(template/'FormalObjectives.OUT')])
    pst.model_input_data.loc[:,'pest_file']='parameters.tpl';pst.model_input_data.loc[:,'model_file']='parameters.csv'
    pst.model_output_data.loc[:,'pest_file']='objectives.ins';pst.model_output_data.loc[:,'model_file']='FormalObjectives.OUT'
    for r in bounds.itertuples():pst.parameter_data.loc[r.pest_name,['parval1','parlbnd','parubnd','pargp','partrans']]=[r.init,r.lower,r.upper,r.pargp,'log'if r.status=='active'else'fixed']
    for r in obs.itertuples():pst.observation_data.loc[r.obsnme,['obsval','weight','obgnme']]=[0.,r.final_weight,r.family.lower()]
    pst.model_command=[f'"{sys.executable}" -X utf8 "{root/"runtime/forward_A.py"}" --design "{root/"design.json"}"']
    pst.control_data.noptmax=4;pst.control_data.phiredstp=0.;pst.control_data.nphinored=10;pst.control_data.nphistp=10;pst.control_data.relparstp=0.;pst.control_data.nrelpar=10
    pst.pestpp_options=dict(ies_num_reals=80,ies_par_en='initial.par.csv',ies_no_noise=True,ies_include_base=True,ies_save_binary=False,
                           ies_reg_factor=0.,ies_initial_lambda=10.,ies_lambda_mults=[1.],ies_subset_size=80,
                           ies_bad_phi=1.e10,overdue_giveup_minutes=5.,overdue_giveup_fac=20.)
    pst.write(str(template/'smoke.pst'),version=2)
    rng=np.random.default_rng(20261102)
    ensemble=pd.DataFrame(np.tile(bounds.init.to_numpy(),(80,1)),columns=bounds.pest_name,index=['base']+[f'r{i:03}'for i in range(1,80)])
    for r in bounds[bounds.status=='active'].itertuples():
        # Broad user working bounds remain intact. Start the finite 80x4
        # experiment near its verified center rather than assuming the
        # whole high-dimensional rectangle is an observable crop state.
        halfwidth=.12*(r.upper-r.lower)
        lo=max(r.lower,r.init-halfwidth);hi=min(r.upper,r.init+halfwidth)
        ensemble.loc[ensemble.index!='base',r.pest_name]=rng.uniform(lo,hi,79)
    ensemble.to_csv(template/'initial.par.csv',index_label='real_name')
    dump(root/'control_receipt.json',dict(members=80,updates=4,workers=6,active=d['active'],seed=20261102,
          source='explicit local uniform ensemble, center +/-12% full domain width intersect frozen bounds; no candidate growth/date screening',
          pst_sha256=sha(template/'smoke.pst'),ensemble_sha256=sha(template/'initial.par.csv')))


def finalize(root,d):
    phi=pd.read_csv(root/'manager/smoke.phi.actual.csv')
    if int(phi.iteration.max())!=4:raise ValueError('Requested four updates not completed')
    obs=pd.read_csv(root/'manager/smoke.4.obs.csv',index_col=0)
    if len(obs)!=80 or not np.isfinite(obs.to_numpy()).all():raise ValueError('Incomplete final 80 members')
    receipts=[json.loads(p.read_text(encoding='utf8'))for p in (root/'_agents').glob('*/native_trials/*/receipt.json')]
    successful=[r for r in receipts if r['success']]
    best=min(successful,key=lambda r:r['phi']);bound=pd.read_csv(d['bounds'])
    out=root/'selected_deterministic';out.mkdir()
    pd.DataFrame([(r.pest_name,best['parameters'][r.name])for r in bound.itertuples()],columns=['name','value']).to_csv(out/'parameters.csv',index=False)
    pd.DataFrame(best['parameters'].items(),columns=['name','value']).to_csv(root/'best_parameters.csv',index=False)
    replay=evaluate(root/'design.json',out/'parameters.csv',out)
    if not np.isclose(replay['phi'],best['phi'],atol=1e-10,rtol=1e-12):raise ValueError('Replay differs')
    comp=pd.read_csv(Path(replay['trial'])/'comparison.csv');comp.to_csv(root/'best_comparison.csv',index=False)
    metrics=[]
    for family,q in comp.groupby('family'):
        error=q.simulated-q.observed;rmse=float(np.sqrt(np.mean(error**2)));den=float(np.square(q.observed-q.observed.mean()).sum())
        metrics.append(dict(family=family,n=len(q),rmse=rmse,nrmse_pct=100*rmse/q.observed.mean(),bias=float(error.mean()),nse=1-float(np.square(error).sum())/den if den else None,phi=float(q.phi_contribution.sum())))
    pd.DataFrame(metrics).to_csv(root/'best_metrics.csv',index=False)
    pd.DataFrame([dict(trial=r['trial'],success=r['success'],phi=r.get('phi'),error=r.get('error'))for r in receipts]).to_csv(root/'evaluation_audit.csv',index=False)
    if not all(sha(p)==h for p,h in d['protected'].items()):raise ValueError('Protected executable changed')
    dump(root/'completion_receipt.json',dict(completed=True,updates=4,final_members=80,workers=6,active=d['active'],
          native_IES_evaluations=len(receipts),failures=sum(not r['success']for r in receipts),best_actual_phi=best['phi'],
          independent_replay_phi=replay['phi'],best_trial=replay['trial'],budget=replay['budget'],protected_unchanged=True,
          scientific_validation=False,limitations=[d['objective_limitation'],'engineering-domain joint calibration; controlled events and independent observations still needed']))
    dump(root/'execution_status.json',dict(stage='completed',completed=True,updates=4,members=80))
    print('COMPLETED',replay['phi'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--prepare-only',action='store_true');p.add_argument('--launch-prepared',action='store_true');p.add_argument('--finalize-only',action='store_true');p.add_argument('--resume-preflight',action='store_true')
    a=p.parse_args();root=a.out.resolve()
    if a.launch_prepared or a.finalize_only:d=json.loads((root/'design.json').read_text(encoding='utf8'))
    elif a.resume_preflight:
        if (root/'design.json').exists():raise ValueError('Already frozen; do not mutate a launched design')
        d=json.loads((root/'preparation_design.json').read_text(encoding='utf8'))
        shutil.copy2(HERE/'forward_A.py',root/'runtime/forward_A.py')
        bounds=preflight(root,d);control(root,d,bounds)
    else:
        d=prepare(root);bounds=preflight(root,d);control(root,d,bounds)
    if not a.prepare_only:
        if not a.finalize_only:launch(root,d)
        finalize(root,d)
