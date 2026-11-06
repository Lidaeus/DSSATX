"""Five genuine PEST-IES updates with explicit feasible-state rejection.

Each failed upgrade keeps that member's previous verified parameter/output PAIR
at the next documented restart. No output is ever attached to a failed vector.
The fixed original prior ensemble is supplied on every restart. This is local
constrained optimization, not an unmodified IES posterior sampler.
"""
from pathlib import Path
import argparse,concurrent.futures as cf,json,os,re,shutil,socket,subprocess,sys,time
import numpy as np
import pandas as pd
import pyemu
from scipy.stats import qmc
from protocol import ROOT,sha,write_json,validate
from coordinates import encode
from launch_ies import screen,expected_infeasibility

def checkpoint(run,number,states,names,obsnames,bounds):
    """Only receipt-backed pairs enter a checkpoint, including held members."""
    folder=run/'checkpoints';folder.mkdir(exist_ok=True);pars=[];outputs=[];lineage=[]
    for name in names:
        state=states[name];trial=Path(state['trial']);q=json.loads((trial/'receipt.json').read_text(encoding='utf8'))
        if not q['success']:raise ValueError('Checkpoint contains failed trial')
        values=q['search_parameters'];physical=q['parameters'];validate(physical,bounds)
        comp=pd.read_csv(trial/'comparison.csv',float_precision='round_trip').set_index('obsnme').loc[obsnames]
        if len(comp)!=len(obsnames) or not np.isfinite(comp.pest_output).all():raise ValueError('Checkpoint target completeness')
        pars.append({k.lower():v for k,v in values.items()});outputs.append(comp.pest_output.to_dict())
        lineage.append(dict(member=name,trial=str(trial),receipt_sha256=sha(trial/'receipt.json'),held=state.get('held',False),reason=state.get('reason',''),phi=q['phi']))
    pd.DataFrame(pars,index=names).to_csv(folder/f'iteration_{number}.par.csv')
    pd.DataFrame(outputs,index=names)[obsnames].to_csv(folder/f'iteration_{number}.obs.csv')
    pd.DataFrame(lineage).to_csv(folder/f'iteration_{number}.lineage.csv',index=False)
    write_json(folder/f'iteration_{number}.json',dict(iteration=number,members=len(names),held=sum(x['held']for x in lineage),
        mean_phi=float(np.mean([x['phi']for x in lineage])),minimum_phi=float(min(x['phi']for x in lineage)),
        par_sha256=sha(folder/f'iteration_{number}.par.csv'),obs_sha256=sha(folder/f'iteration_{number}.obs.csv')))

def recover_survivors(stage,previous,bounds):
    """Recover full precision actual inputs, never restart from rounded PEST CSV."""
    par_files=[p for p in (stage/'master').glob('case.*.par.csv')if re.fullmatch(r'case\.\d+\.par\.csv',p.name)]
    final=max(par_files,key=lambda p:int(p.name.split('.')[1]))
    pe=pd.read_csv(final,index_col=0);pe.index=pe.index.str.lower();oe=pd.read_csv(final.with_name(final.name.replace('.par.csv','.obs.csv')),index_col=0);oe.index=oe.index.str.lower()
    active=bounds[bounds.status.eq('active')];cols=active.name.str.lower().tolist();width=(active.upper-active.lower).to_numpy()
    candidates=[]
    for path in stage.glob('worker_*/native_trials/*/receipt.json'):
        q=json.loads(path.read_text(encoding='utf8'))
        if q['success']:
            values={k.lower():v for k,v in q['search_parameters'].items()}
            candidates.append((q, np.array([values[k]for k in cols])))
    # PEST may retain an unchanged current member; include its original receipt.
    for state in previous.values():
        q=json.loads((Path(state['trial'])/'receipt.json').read_text(encoding='utf8'));v={k.lower():x for k,x in q['search_parameters'].items()}
        candidates.append((q,np.array([v[k]for k in cols])))
    matrix=np.array([v for _,v in candidates]);result={}
    for name,row in pe.iterrows():
        distances=np.max(np.abs(matrix-row[cols].to_numpy(float))/width,axis=1)
        # PEST exports six significant figures: for narrow physical domains
        # (e.g. PRORTI) this can exceed 2e-5 of the interval width. Matching also
        # requires the complete 1123-vector of actual model outputs below.
        matches=np.flatnonzero(distances<1e-4)
        matches=sorted(matches,key=lambda i:distances[i])
        for idx in matches:
            q=candidates[idx][0];comp=pd.read_csv(Path(q['trial'])/'comparison.csv').set_index('obsnme')
            if np.allclose(comp.loc[oe.columns,'pest_output'],oe.loc[name],rtol=2e-5,atol=2e-6):
                result[name]=dict(trial=q['trial'],held=False);break
        else:raise ValueError('Cannot recover exact evaluated survivor '+name)
    if not set(result)<=set(previous):raise ValueError('Unexpected realization identity')
    for name,state in previous.items():
        if name not in result:result[name]=dict(trial=state['trial'],held=True,reason='failed proposed upgrade rejected; previous exact parameter/output pair retained')
    return result,len(pe),int(final.name.split('.')[1])

def run_stage(stage,exe,pst,port,workers):
    entries=[];handles=[];seen=set()
    def start(folder,args):
        log=(folder/'process.log').open('x',encoding='utf8');handles.append(log)
        p=subprocess.Popen([exe,pst,*args],cwd=folder,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt'else 0)
        entries.append((p,folder));return p
    try:
        controller=start(stage/'master',['/h',':'+str(port)])
        for i in range(workers):
            work=stage/f'worker_{i:02d}';shutil.copytree(stage/'case',work)
            start(work,['/h','127.0.0.1:'+str(port)])
        write_json(stage/'owned_processes.json',[dict(pid=p.pid,cwd=str(w))for p,w in entries])
        while True:
            for _,work in entries:
                for path in work.glob('native_trials/*/receipt.json'):
                    if str(path)in seen:continue
                    q=json.loads(path.read_text(encoding='utf8'));seen.add(str(path))
                    if not q['success']and not expected_infeasibility(q):
                        write_json(stage/'unexpected_failure.json',dict(receipt=str(path),error=q.get('error')))
                        raise RuntimeError('Unexpected native/protocol failure '+str(path))
            if controller.poll()is not None:break
            time.sleep(5)
        if controller.returncode:raise RuntimeError('PEST stage failed: '+str(stage))
        for p,_ in entries[1:]:
            try:p.wait(timeout=15)
            except subprocess.TimeoutExpired:pass
    finally:
        for p,_ in entries:
            if p.poll()is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True)
        for h in handles:h.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--design',required=True);p.add_argument('--run-id',required=True);p.add_argument('--center',required=True)
    p.add_argument('--members',type=int,default=150);p.add_argument('--iterations',type=int,default=5);p.add_argument('--workers',type=int,default=6)
    p.add_argument('--seed',type=int,required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--reuse-preflight')
    p.add_argument('--max-preflight-attempts',type=int,default=300)
    p.add_argument('--local-fraction',type=float,default=.15);p.add_argument('--broad-fraction',type=float,default=.20);a=p.parse_args()
    design=Path(a.design).resolve();d=json.loads(design.read_text(encoding='utf8'))
    for file,h in d['frozen_hashes'].items():
        if sha(file)!=h:raise ValueError('Frozen dependency changed '+file)
    with socket.socket()as sock:sock.bind(('127.0.0.1',a.port))
    run=ROOT/'runs'/a.run_id;run.mkdir(exist_ok=False)
    physical_bounds=pd.read_csv(d['bounds']);b=pd.read_csv(d['search_bounds']);active=b[b.status.eq('active')].name.tolist()
    physical=pd.read_csv(a.center).set_index('name').value.to_dict();validate(physical,physical_bounds);center=encode(physical,physical_bounds.set_index('name'))
    obs=pd.concat([pd.read_csv(ds['observations'])for ds in d['datasets']],ignore_index=True);obsnames=obs.obsnme.tolist()
    exe='D:/Tomato_Cal/pestpp-5.2.16-win/bin/pestpp-ies.exe'
    manifest=dict(design=str(design),design_sha256=sha(design),center=str(Path(a.center).resolve()),center_sha256=sha(a.center),members=a.members,iterations=a.iterations,
        workers=a.workers,seed=a.seed,port=a.port,physical_active=d['active'],active=active,targets=d['targets'],executable=exe,pestpp_sha256=sha(exe),launcher_sha256=sha(__file__),
        method=f'checkpointed constrained PEST-IES; {a.iterations} separate one-update stages; failed upgrade retains prior verified member pair; original ensemble remains prior',
        sampling=dict(local_fraction=a.local_fraction,broad_fraction=a.broad_fraction,feasible_coordinates=True),max_preflight_attempts=a.max_preflight_attempts,no_imputation=True,independent_validation_claim=False)
    write_json(run/'run_manifest.json',manifest);write_json(run/'status.json',dict(stage='preflight',accepted=0,attempts=0))
    accepted=[];audit=[]
    if a.reuse_preflight:
        source=Path(a.reuse_preflight).resolve();source_manifest=json.loads((source/'run_manifest.json').read_text())
        source_design=json.loads(Path(source_manifest['design']).read_text())
        if source_design['binary_sha256']!=d['binary_sha256']or source_design['datasets']!=d['datasets']or source_design['bounds']!=d['bounds']:raise ValueError('Preflight source uses different forward model/data')
        for file in [ROOT/'protocol.py',ROOT/'forward_search.py',ROOT/'coordinates.py']:
            if source_design['frozen_hashes'][str(file)]!=d['frozen_hashes'][str(file)]:raise ValueError('Preflight forward implementation changed')
        for row in pd.read_csv(source/'preflight_audit.csv').itertuples():
            if row.success and len(accepted)<a.members:
                q=json.loads((Path(row.trial)/'receipt.json').read_text());accepted.append(dict(name=row.name,trial=q['trial'],values=q['search_parameters'],success=True,phi=q['phi']))
        manifest['reused_preflight_source']=str(source);write_json(run/'run_manifest.json',manifest)
    if not accepted:
        result=screen((design,run,'base',center));audit.append({k:v for k,v in result.items()if k!='values'})
        if not result['success']:raise RuntimeError('Retained center failed')
        accepted.append(result)
    idx=b.set_index('name');lo=idx.loc[active,'lower'].to_numpy();hi=idx.loc[active,'upper'].to_numpy();mid=np.array([center[n]for n in active])
    left=np.maximum(lo,mid-a.local_fraction*(hi-lo));right=np.minimum(hi,mid+a.local_fraction*(hi-lo));draw=qmc.Sobol(len(active)+1,scramble=True,seed=a.seed).random_base2(12);ordinal=0
    if not 0<a.local_fraction<=1 or not 0<=a.broad_fraction<=1: raise ValueError('Sampling fractions')
    with cf.ThreadPoolExecutor(max_workers=a.workers)as pool:
        while len(accepted)<a.members:
            tasks=[]
            remaining=a.max_preflight_attempts-len(audit)
            if remaining<=0:
                write_json(run/'status.json',dict(stage='preflight_budget_exhausted',accepted=len(accepted),attempts=len(audit)))
                raise RuntimeError('Authorized preflight attempt budget exhausted')
            for _ in range(min(a.workers,a.members-len(accepted),remaining)):
                ordinal+=1;name=f'new_{ordinal:05d}';point=draw[ordinal-1];broad=point[-1]<a.broad_fraction
                low,high=(lo,hi) if broad else (left,right)
                values=center|dict(zip(active,low+point[:-1]*(high-low)));tasks.append((design,run,name,values))
            for result in pool.map(screen,tasks):
                audit.append({k:v for k,v in result.items()if k!='values'})
                if result['success']:accepted.append(result)
                elif not expected_infeasibility(result):raise RuntimeError('Unexpected preflight failure '+result['error'])
            pd.DataFrame(audit).to_csv(run/'preflight_audit.csv',index=False);write_json(run/'status.json',dict(stage='preflight',accepted=len(accepted),attempts=len(audit)))
            print('preflight',len(accepted),'/',a.members,'attempts',len(audit),flush=True)
            if len(audit)>a.max_preflight_attempts:raise RuntimeError('Preflight budget accounting')
    names=[x['name'].lower()for x in accepted]
    if len(set(names))!=a.members:raise ValueError('Duplicate initial identities')
    states={x['name'].lower():dict(trial=x['trial'])for x in accepted}
    checkpoint(run,0,states,names,obsnames,physical_bounds)
    if not (run/'preflight_audit.csv').exists():pd.DataFrame(audit,columns=['name','trial','success','error','error_type','phi']).to_csv(run/'preflight_audit.csv',index=False)
    template=run/'template';template.mkdir()
    (template/'parameters.tpl').write_text('ptf ~\nname,value\n'+'\n'.join(f'{n},~ {n.lower():<26} ~'for n in b.name)+'\n',encoding='ascii')
    (template/'objectives.ins').write_text('pif @\n'+'\n'.join(f'l1 w !{n}!'for n in obsnames)+'\n',encoding='ascii')
    pd.DataFrame(center.items(),columns=['name','value']).to_csv(template/'parameters.csv',index=False)
    (template/'FormalObjectives.OUT').write_text('\n'.join(f'{n} 0.0'for n in obsnames)+'\n')
    pst=pyemu.Pst.from_io_files([str(template/'parameters.tpl')],[str(template/'parameters.csv')],[str(template/'objectives.ins')],[str(template/'FormalObjectives.OUT')],pst_path='.')
    for row in b.itertuples():pst.parameter_data.loc[row.name.lower(),['partrans','parval1','parlbnd','parubnd','pargp']]=['none'if row.status=='active'else'fixed',center[row.name],row.lower,row.upper,str(row.pargp).lower()]
    for row in obs.itertuples():pst.observation_data.loc[row.obsnme,['obsval','weight','obgnme']]=[0.,row.final_weight,(row.season_id+'_'+row.family).lower()]
    pst.model_command=[f'"{sys.executable}" -X utf8 "{ROOT/"forward_search.py"}" --design "{design}" --param-csv parameters.csv --output-dir . --no-diagnostics']
    pst.control_data.noptmax=1;lam=10.
    try:
        for number in range(1,a.iterations+1):
            stage=run/'stages'/f'step_{number:02d}';case=stage/'case';shutil.copytree(template,case)
            shutil.copy2(run/'checkpoints/iteration_0.par.csv',case/'prior.csv')
            shutil.copy2(run/'checkpoints'/f'iteration_{number-1}.par.csv',case/'restart.par.csv')
            shutil.copy2(run/'checkpoints'/f'iteration_{number-1}.obs.csv',case/'restart.obs.csv')
            # With explicit restart realization names, the target ensemble must
            # carry the same names; an auto-generated no-noise ensemble uses
            # numeric IDs and PEST cannot align it with named restart pairs.
            pd.DataFrame(0.,index=names,columns=obsnames).to_csv(case/'obs.noise.csv')
            # In 5.2.16, ies_no_noise conflicts with an explicitly supplied
            # target ensemble. obs.noise.csv is exactly zero, so there is still
            # no observation perturbation; False selects the file-reading path.
            pst.pestpp_options=dict(ies_num_reals=a.members,ies_include_base=True,ies_no_noise=False,ies_save_binary=False,ies_bad_phi_sigma=1e300,
                ies_par_en='prior.csv',ies_obs_en='obs.noise.csv',ies_restart_par_en='restart.par.csv',ies_restart_obs_en='restart.obs.csv',
                ies_initial_lambda=lam,ies_lambda_mults=[1.,5.],lambda_scale_fac=[.25,.5],ies_subset_size=min(30,a.members),
                ies_drop_conflicts=False,ies_enforce_bounds=True,ies_save_lambda_en=True,rand_seed=a.seed+number,panther_agent_no_ping_timeout_secs=600)
            pst.write(str(case/'case.pst'),version=1);shutil.copytree(case,stage/'master')
            write_json(run/'status.json',dict(stage='ies_running',iteration=number,members=a.members,marquardt_lambda=lam))
            run_stage(stage,exe,'case.pst',a.port,a.workers)
            states,raw_survivors,actual_updates=recover_survivors(stage,states,b)
            checkpoint(run,number,states,names,obsnames,physical_bounds)
            logfile=(stage/'master/process.log').read_text(errors='replace');matches=re.findall(r'updating lambda to\s+([\deE.+-]+)',logfile)
            if matches:lam=float(matches[-1])
            write_json(stage/'stage_receipt.json',dict(step=number,raw_pest_survivors=raw_survivors,checkpoint_members=len(states),held=a.members-raw_survivors,actual_pest_updates=actual_updates,next_lambda=lam))
            print('checkpoint',number,'members',len(states),'PEST survivors',raw_survivors,'held',a.members-raw_survivors,flush=True)
        write_json(run/'status.json',dict(stage='ies_completed',iterations=a.iterations,retained_members=len(states),audit_required=True))
        print('all checkpointed updates completed',run,flush=True)
    except Exception as exc:
        write_json(run/'status.json',dict(stage='ies_failed',error=str(exc),audit_required=True));raise

if __name__=='__main__':main()
