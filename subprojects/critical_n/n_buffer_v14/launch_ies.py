"""True dual-spring PEST-IES with complete trial/failure provenance."""
from pathlib import Path
import argparse,concurrent.futures as cf,json,os,shutil,socket,subprocess,sys,time
import numpy as np
import pandas as pd
import pyemu
from scipy.stats import qmc
from protocol import ROOT,sha,write_json,validate
from coordinates import encode

def expected_infeasibility(result):
    error=result.get('error','')
    return result.get('error_type')=='ValueError' and error.startswith((
        'No mature fruit at the exact N sampling date;', 'Frozen bound ',
        'Physical bound ', 'Protein order ', 'Protein dilution margin ',
        'Encoded protein dilution margin ', 'Ordered response ',
        'Negative root partition', 'CNC monotonicity', 'Maturity after terminal harvest age',
        'Protein coordinate domain ', 'Partition coordinate domain', 'Native infeasible CH2O organ subset;'))

def screen(task):
    design,run,name,values=task;out=run/'preflight'/name;out.mkdir(parents=True)
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(out/'parameters.csv',index=False)
    cmd=[sys.executable,'-X','utf8',str(ROOT/'forward_search.py'),'--design',str(design),'--param-csv',str(out/'parameters.csv'),'--output-dir',str(out),'--no-diagnostics']
    cp=subprocess.run(cmd,capture_output=True,text=True,timeout=600);(out/'forward.log').write_text(cp.stdout+cp.stderr,encoding='utf8')
    rec=out/('last_success.json'if cp.returncode==0 else 'last_failure.json')
    result=json.loads(rec.read_text(encoding='utf8'))if rec.exists()else dict(success=False,error=(cp.stdout+cp.stderr)[-1500:])
    return dict(name=name,success=result['success'],trial=result.get('trial',''),error=result.get('error',''),error_type=result.get('error_type',''),values=values,phi=result.get('phi'))

def main():
    p=argparse.ArgumentParser();p.add_argument('--design',required=True);p.add_argument('--run-id',required=True);p.add_argument('--center',required=True)
    p.add_argument('--members',type=int,default=150);p.add_argument('--iterations',type=int,default=5);p.add_argument('--workers',type=int,default=6);p.add_argument('--seed',type=int,required=True);p.add_argument('--port',type=int,required=True);a=p.parse_args()
    design=Path(a.design).resolve();d=json.loads(design.read_text(encoding='utf8'))
    if not d['strict_capacity']:raise ValueError('Only strict capacity mechanism may enter new identification')
    for path,h in d['frozen_hashes'].items():
        if sha(path)!=h:raise ValueError('Changed dependency '+path)
    with socket.socket()as sock:sock.bind(('127.0.0.1',a.port))
    run=ROOT/'runs'/a.run_id;run.mkdir(parents=True,exist_ok=False)
    physical_bounds=pd.read_csv(d['bounds']);b=pd.read_csv(d['search_bounds']);active=b[b.status.eq('active')].name.tolist();center=pd.read_csv(Path(a.center).resolve());physical=dict(zip(center.name,center.value));validate(physical,physical_bounds);values=encode(physical,physical_bounds.set_index('name'))
    manifests=dict(design=str(design),design_sha256=sha(design),members=a.members,iterations=a.iterations,workers=a.workers,seed=a.seed,port=a.port,
        center=str(Path(a.center).resolve()),center_sha256=sha(a.center),active=active,targets=d['targets'],
        purpose='registered conditional dual-spring mechanism identification; not independent validation',
        sampling='conditional local refinement: +/-5% search-domain width around retained center; feasibility only; original physical hard bounds unchanged',
        physical_active=d['active'],search_coordinates=d['coordinate_mapping'],
        failure_policy='all unique attempts retained; no imputation; unexpected native/protocol/physical failure stops this run',
        executable='D:/Tomato_Cal/pestpp-5.2.16-win/bin/pestpp-ies.exe',launcher_sha256=sha(__file__))
    manifests['pestpp_sha256']=sha(manifests['executable']);write_json(run/'run_manifest.json',manifests)
    write_json(run/'status.json',dict(stage='preflight',accepted=0,attempts=0))
    accepted=[];audit=[]
    base=screen((design,run,'base',values));audit.append({k:v for k,v in base.items()if k!='values'})
    if not base['success']:raise RuntimeError('Base failed: '+base['error'])
    accepted.append(base);idx=b.set_index('name');lo=idx.loc[active,'lower'].to_numpy();hi=idx.loc[active,'upper'].to_numpy();mid=np.array([values[n]for n in active])
    local_lo=np.maximum(lo,mid-.05*(hi-lo));local_hi=np.minimum(hi,mid+.05*(hi-lo));samples=qmc.Sobol(len(active),scramble=True,seed=a.seed).random_base2(12);ordinal=0
    with cf.ThreadPoolExecutor(max_workers=a.workers)as pool:
        while len(accepted)<a.members:
            tasks=[]
            for _ in range(min(a.workers,a.members-len(accepted))):
                ordinal+=1;l,h=local_lo,local_hi
                tasks.append((design,run,f'p_{ordinal:05d}',values|dict(zip(active,l+samples[ordinal-1]*(h-l)))))
            for result in pool.map(screen,tasks):
                audit.append({k:v for k,v in result.items()if k!='values'})
                if result['success']:accepted.append(result)
                elif not expected_infeasibility(result):
                    write_json(run/'physical_stop.json',dict(reason=result['error'],trial=result['trial']));raise RuntimeError('Native physical failure')
            pd.DataFrame(audit).to_csv(run/'preflight_audit.csv',index=False)
            write_json(run/'status.json',dict(stage='preflight',accepted=len(accepted),attempts=len(audit)));print('preflight',len(accepted),'/',a.members,'attempts',len(audit),flush=True)
            if ordinal>10*a.members:raise RuntimeError('Too few complete vectors; no targets dropped')
    work=run/'case';work.mkdir();obs=pd.concat([pd.read_csv(ds['observations'])for ds in d['datasets']],ignore_index=True)
    (work/'parameters.tpl').write_text('ptf ~\nname,value\n'+'\n'.join(f'{n},~ {n.lower():<26} ~'for n in b.name)+'\n',encoding='ascii')
    (work/'objectives.ins').write_text('pif @\n'+'\n'.join(f'l1 w !{n}!'for n in obs.obsnme)+'\n',encoding='ascii')
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(work/'parameters.csv',index=False)
    (work/'FormalObjectives.OUT').write_text('\n'.join(f'{n} 0.0'for n in obs.obsnme)+'\n')
    pst=pyemu.Pst.from_io_files([str(work/'parameters.tpl')],[str(work/'parameters.csv')],[str(work/'objectives.ins')],[str(work/'FormalObjectives.OUT')],pst_path='.')
    for row in b.itertuples():pst.parameter_data.loc[row.name.lower(),['partrans','parval1','parlbnd','parubnd','pargp']]=['none'if row.status=='active'else'fixed',values[row.name],row.lower,row.upper,str(row.pargp).lower()]
    for row in obs.itertuples():pst.observation_data.loc[row.obsnme,['obsval','weight','obgnme']]=[0.,row.final_weight,(row.season_id+'_'+row.family).lower()]
    pst.model_command=[f'"{sys.executable}" -X utf8 "{ROOT/"forward_search.py"}" --design "{design}" --param-csv parameters.csv --output-dir . --no-diagnostics']
    pst.control_data.noptmax=a.iterations
    pd.DataFrame([{k.lower():v for k,v in r['values'].items()}for r in accepted],index=[r['name']for r in accepted]).to_csv(work/'initial.csv')
    pst.pestpp_options=dict(ies_num_reals=a.members,ies_include_base=True,ies_no_noise=True,ies_save_binary=False,ies_bad_phi_sigma=1e300,
        ies_initial_lambda=10.,ies_lambda_mults=[1.,5.],lambda_scale_fac=[.25,.5],ies_par_en='initial.csv',rand_seed=a.seed,
        ies_drop_conflicts=False,ies_subset_size=min(30,a.members),ies_enforce_bounds=True,ies_save_lambda_en=True,
        panther_agent_no_ping_timeout_secs=600)
    manifests['pestpp_options']=pst.pestpp_options.copy();write_json(run/'run_manifest.json',manifests)
    initial=pd.DataFrame([r['values']for r in accepted])[active].to_numpy()
    rank=int(np.linalg.matrix_rank((initial-initial.mean(axis=0))/(hi-lo)))
    write_json(run/'initial_ensemble_quality.json',dict(members=len(accepted),normalized_rank=rank,active_dimensions=len(active),physical_parameter_count=len(physical_bounds),interpretation='local feasible search ensemble, not posterior or unconditional prior'))
    pst.write(str(work/'case.pst'),version=1)
    master=run/'master';shutil.copytree(work,master);entries=[];handles=[]
    def start(cwd,args):
        handle=(cwd/'process.log').open('x',encoding='utf8');handles.append(handle)
        proc=subprocess.Popen([manifests['executable'],'case.pst',*args],cwd=cwd,stdout=handle,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt'else 0);entries.append((proc,cwd));return proc
    def stop(proc):
        if proc.poll()is None:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True)if os.name=='nt'else proc.terminate()
    try:
        controller=start(master,['/h',':'+str(a.port)])
        time.sleep(2)
        for i in range(a.workers):
            w=run/f'worker_{i:02d}';shutil.copytree(work,w);start(w,['/h','127.0.0.1:'+str(a.port)])
        write_json(run/'owned_processes.json',[dict(pid=p.pid,cwd=str(w))for p,w in entries]);write_json(run/'status.json',dict(stage='ies_running',preflight_attempts=len(audit),preflight_accepted=len(accepted)))
        last_check=0;seen=set()
        while controller.poll()is None:
            if time.time()-last_check>15:
                failures=[str(p)for _,w in entries for p in w.glob('native_trials/*/*/NBufferFailure.txt')]
                for _,w in entries:
                    for path in w.glob('native_trials/*/receipt.json'):
                        if str(path)in seen:continue
                        q=json.loads(path.read_text(encoding='utf8'));seen.add(str(path))
                        if not q['success']and not expected_infeasibility(q):failures.append(str(path))
                if failures:write_json(run/'physical_stop.json',dict(failures=failures));raise RuntimeError('Native physical failure: revision stopped')
                last_check=time.time()
            time.sleep(1)
        if controller.returncode:raise RuntimeError('PEST++ failed; see master/process.log')
        for proc,_ in entries[1:]:
            try:proc.wait(timeout=15)
            except subprocess.TimeoutExpired:stop(proc)
        terminal=pd.read_csv(master/f'case.{a.iterations}.obs.csv',index_col=0)
        write_json(run/'status.json',dict(stage='ies_completed',preflight_attempts=len(audit),preflight_accepted=len(accepted),retained_members=len(terminal),audit_required=True));print('IES completed',run,flush=True)
    except Exception as exc:
        write_json(run/'status.json',dict(stage='ies_failed',error=str(exc),audit_required=True));raise
    finally:
        for proc,_ in entries:stop(proc)
        for handle in handles:handle.close()

if __name__=='__main__':main()
