"""Latest frozen C4, reference native ranges, real 80x4 IES / six workers."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse,json,shutil,subprocess,sys
import numpy as np
import pandas as pd
import pyemu
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
MAIN=Path('D:/Tomato_Cal');CN=MAIN/'subprojects/critical_n'
OLD=CN/'runs/n4864_A_joint80x4_20261102_r1'
DELIVERY=CN/'reports/C4_calibration_readiness_20261103_r2'
sys.path.insert(0,str(REPO/'research/n_integration_v2'))
sys.path.insert(0,str(REPO/'research/a_budget_feedback'))
from smoke_forward import sha,dump
from calibration_smoke import launch
import joint_A as previous
from forward_c4 import evaluate

def prepare(root):
    root.mkdir(parents=True,exist_ok=False);(root/'bin').mkdir()
    delivery=json.loads((DELIVERY/'delivery_manifest.json').read_text(encoding='utf8'))
    assert sha(delivery['binary'])==delivery['binary_sha256']
    shutil.copy2(delivery['binary'],root/'bin/dscsm048_C4.exe')
    shutil.copy2(MAIN/'pestpp-5.2.16-win/bin/pestpp-ies.exe',root/'bin/pestpp-ies.exe')
    old=json.loads((OLD/'design.json').read_text(encoding='utf8'))
    original=DELIVERY/'cases/delivery_full'
    (root/'inputs').mkdir()
    for p in Path(old['inputs']).iterdir():
        if p.is_file():shutil.copy2(original/p.name,root/'inputs'/p.name)
    shutil.copy2(OLD/'observations.csv',root/'observations.csv')
    shutil.copy2(OLD/'reference_active_76.csv',root/'reference_active_76.csv')
    shutil.copytree(OLD/'runtime/src',root/'runtime/src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for p in [HERE/'forward_c4.py',REPO/'research/n_integration_v2/smoke_forward.py']:
        shutil.copy2(p,root/'runtime'/p.name)
    bound=pd.read_csv(old['bounds'],float_precision='round_trip')
    best=json.loads((OLD/'best_parameters.exact.json').read_text(encoding='utf8'))
    for i,row in bound.iterrows():bound.loc[i,'init']=best[row['name']]
    # Deliberately retain the requested native ranges. SENRTE's old pathway
    # is disabled by C4; the actual native perturbation probe must confirm it.
    rows=[]
    for name,initial,lower,upper in [('remob_tau',10.,5.,20.),('protect_beta',.7,.5,.9)]:
        rows.append(dict(name=name,init=initial,lower=lower,upper=upper,status='active',pargp='new_n',
            location='NIntegration.nml',baseline_value=initial,reference_init=initial,
            domain_source='C4 report finite sensitivity domain; engineering not biological CI',
            unit_role='day' if name=='remob_tau' else 'dimensionless',pest_name=f'p{len(bound)+len(rows):03}'))
    bound=pd.concat([bound,pd.DataFrame(rows)],ignore_index=True)
    bound.to_csv(root/'candidate_bounds.csv',index=False)
    pd.DataFrame(dict(name=bound.pest_name,value=bound.init)).to_csv(root/'base_parameters.csv',index=False)
    settings=dict(state_timing=1,pods_n_state=1,remob_mode=1,luxury_priority=1,remob_severity=1,
        slow_ratio=3,c4_budget=1,leaf_coupling=1,c4_photo=1,n_sen_rate=0)
    required=dict(ni_stage=5,root_mode=2,budget_revision=1,**{k:v for k,v in settings.items() if k!='slow_ratio'})
    settings.update(ni_stage=5,root_mode=2,budget_revision=1)
    dump(root/'fixed_nitrogen_config.json',settings)
    protected=dict(delivery['protected_executables_unchanged']);protected[delivery['binary']]=delivery['binary_sha256']
    d=dict(schema='C4_joint_native_IES_v1',binary=str(root/'bin/dscsm048_C4.exe'),binary_sha256=sha(root/'bin/dscsm048_C4.exe'),
        bounds=str(root/'candidate_bounds.csv'),observations=str(root/'observations.csv'),inputs=str(root/'inputs'),runtime=str(root/'runtime'),
        nitrogen_names=old['nitrogen_names']+['remob_tau','protect_beta'],fixed_nitrogen_config=settings,
        members=80,updates=4,workers=6,targets=612,season='26SP',required_mode=required,
        protected=protected,frozen_hashes={},ready_for_IES=False,
        reference=str(root/'reference_active_76.csv'),reference_sha256=sha(root/'reference_active_76.csv'),
        source_head=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip(),
        mechanism_source_head=delivery['mechanism_build_commit'],source_dirty=subprocess.check_output(['git','-C',str(REPO),'status','--porcelain'],text=True).strip(),
        objective_limitation='612 direct targets unchanged; July17 leaf/stem N diagnostic only; same-day mature fruit without shifts/imputation',
        scientific_validation=False,whole_elemental_C_closed=False,
        user_authorization='2026-11-03 explicitly requests latest C4 new calibration; research fit is not management validation')
    dump(root/'preparation_design.json',d)
    return d

def preflight(root,d):
    first=evaluate(root/'preparation_design.json',root/'base_parameters.csv',root/'preflight/base')
    again=evaluate(root/'preparation_design.json',root/'base_parameters.csv',root/'preflight/repeat')
    if first['phi']!=again['phi']:raise ValueError('Deterministic repeat failed')
    bound=pd.read_csv(d['bounds'],float_precision='round_trip');base=pd.read_csv(root/'base_parameters.csv',float_precision='round_trip')
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
    dest=root/'data/parameter_registry/bounds_frozen/eggplant/C4_joint_20261103.csv';dest.parent.mkdir(parents=True)
    bound.to_csv(dest,index=False)
    dump(dest.with_suffix('.meta.json'),dict(status='frozen',reference_sha256=d['reference_sha256'],
          native_ranges_preserved=True,excluded_after_probe=sorted(inactive),V15_principles='approved independently adapted V1-V4; not whole-file transplant',
          new_N_domain_status='engineering working domains, not established biological hard bounds',
          initial_policy='exact A best plus C1-C4 fixed switches; no V15 best vector',
          breakpoint_policy='0.7/1.0 controlled; working domain 0.7-1.5 combines explicit 0.7 comparison with reference upper 1.5'))
    d.update(bounds=str(dest),ready_for_IES=True,active=int((bound.status=='active').sum()),excluded_after_probe=sorted(inactive))
    immutable=[p for p in (root/'runtime').rglob('*')if p.is_file()and '__pycache__'not in p.parts]
    immutable+=list((root/'inputs').glob('*'))+[root/'fixed_nitrogen_config.json',dest,dest.with_suffix('.meta.json'),root/'observations.csv',root/'reference_active_76.csv',root/'bin/dscsm048_C4.exe',root/'bin/pestpp-ies.exe']
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
    pst.model_command=[f'"{sys.executable}" -X utf8 "{root/"runtime/forward_c4.py"}" --design "{root/"design.json"}"']
    pst.control_data.noptmax=4;pst.control_data.phiredstp=0.;pst.control_data.nphinored=10;pst.control_data.nphistp=10;pst.control_data.relparstp=0.;pst.control_data.nrelpar=10
    pst.pestpp_options=dict(ies_num_reals=80,ies_par_en='initial.par.csv',ies_no_noise=True,ies_include_base=True,ies_save_binary=False,
                           ies_reg_factor=0.,ies_initial_lambda=10.,ies_lambda_mults=[1.],ies_subset_size=80,
                           ies_bad_phi=1.e10,overdue_giveup_minutes=5.,overdue_giveup_fac=20.)
    pst.write(str(template/'smoke.pst'),version=2)
    rng=np.random.default_rng(20261103)
    ensemble=pd.DataFrame(np.tile(bounds.init.to_numpy(),(80,1)),columns=bounds.pest_name,index=['base']+[f'r{i:03}'for i in range(1,80)])
    for r in bounds[bounds.status=='active'].itertuples():
        # Broad user working bounds remain intact. Start the finite 80x4
        # experiment near its verified center rather than assuming the
        # whole high-dimensional rectangle is an observable crop state.
        halfwidth=.12*(r.upper-r.lower)
        lo=max(r.lower,r.init-halfwidth);hi=min(r.upper,r.init+halfwidth)
        ensemble.loc[ensemble.index!='base',r.pest_name]=rng.uniform(lo,hi,79)
    ensemble.to_csv(template/'initial.par.csv',index_label='real_name')
    dump(root/'control_receipt.json',dict(members=80,updates=4,workers=6,active=d['active'],seed=20261103,
          source='explicit local uniform ensemble, center +/-12% full domain width intersect frozen bounds; no candidate growth/date screening',
          pst_sha256=sha(template/'smoke.pst'),ensemble_sha256=sha(template/'initial.par.csv')))



def finalize(root,d):
    previous.evaluate=evaluate
    previous.finalize(root,d)
    path=root/'exact_replay_receipt.json'
    r=json.loads(path.read_text(encoding='utf8'))
    r['replay_adapter_sha256']=sha(HERE/'forward_c4.py')
    r['adapter_precision_fix']='round-trip CSV parsing used by both actual IES operator and deterministic replay'
    dump(path,r)
    path=root/'completion_receipt.json';r=json.loads(path.read_text(encoding='utf8'))
    r.update(binary_sha256=d['binary_sha256'],required_mode=d['required_mode'],whole_elemental_C_closed=False)
    dump(path,r)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--prepare-only',action='store_true');p.add_argument('--launch-prepared',action='store_true');p.add_argument('--finalize-only',action='store_true');p.add_argument('--resume-preflight',action='store_true')
    a=p.parse_args();root=a.out.resolve()
    if a.launch_prepared or a.finalize_only:d=json.loads((root/'design.json').read_text(encoding='utf8'))
    elif a.resume_preflight:
        if (root/'design.json').exists():raise ValueError('Frozen design cannot be mutated')
        d=json.loads((root/'preparation_design.json').read_text(encoding='utf8'))
        shutil.copy2(HERE/'forward_c4.py',root/'runtime/forward_c4.py')
        bound=preflight(root,d);control(root,d,bound)
    else:
        d=prepare(root);bound=preflight(root,d);control(root,d,bound)
    if not a.prepare_only:
        if not a.finalize_only:launch(root,d)
        finalize(root,d)
