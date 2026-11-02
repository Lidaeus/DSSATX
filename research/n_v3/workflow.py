"""Isolated builds/replays of frozen native inputs; no calibration or imputation."""
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, subprocess, sys, time
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
CN = Path('D:/Tomato_Cal/subprojects/critical_n')
OUT = CN/'reports/n_v3_execution_20261103'
BASE = CN/'reports/A_budget_feedback_20261102/best_native_trace'
RUN = CN/'runs/n4864_A_joint80x4_20261102_r1'
OLD = CN/'runs/n4864_p5_r2_explicit_smoke14_24x2_20261102'
sys.path.insert(0, str(OLD/'runtime'))
from smoke_forward import redirect, extract
sys.path.insert(0, str(REPO/'research/a_budget_feedback'))
from forward_A import audit_A
sys.path.insert(0, str(REPO/'research/n_integration_v2'))
from prepare_readiness import numeric_records, COMPARE_FILES

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x): Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def env_build():
    cache=(REPO/'build/CMakeCache.txt').read_text()
    fc=re.search(r'^CMAKE_Fortran_COMPILER:[^=]+=(.*)$',cache,re.M)[1]
    env=os.environ.copy();env['PATH']=str(Path(fc).parent)+';'+env['PATH']
    return env
def build(label):
    target=OUT/'bin'/label
    target.mkdir(parents=True,exist_ok=False)
    with (target/'build.log').open('w') as f:
        p=subprocess.run(['cmake','--build',str(REPO/'build'),'--target','dscsm048','-j','6'],
                         env=env_build(),stdout=f,stderr=subprocess.STDOUT)
    if p.returncode: raise RuntimeError((target/'build.log').read_text()[-5000:])
    exe=target/('dscsm048_'+label+'.exe');shutil.copy2(REPO/'build/bin/dscsm048.exe',exe)
    sources={str(f.relative_to(REPO)):sha(f) for root in ['Plant/CROPGRO','SPAM']
             for f in (REPO/root).iterdir() if f.suffix.lower() in ['.for','.f90']}
    dump(target/'build_receipt.json',dict(exe=str(exe),sha256=sha(exe),sources=sources,
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        git_diff=subprocess.check_output(['git','diff','--stat'],cwd=REPO,text=True)))
    print('BUILT',label,sha(exe),flush=True)
    return exe

def case(name,exe,changes=None,trace=True,input_modifier=None):
    work=OUT/'cases'/name;work.mkdir(parents=True,exist_ok=False)
    design=json.loads((RUN/'design.json').read_text(encoding='utf8'))
    for p in Path(design['inputs']).iterdir():
        if p.is_file(): shutil.copy2(BASE/p.name,work/p.name)
    redirect(work/'DSSATPRO.v48',work)
    if input_modifier is not None: input_modifier(work)
    cfg=json.loads((RUN/'selected_deterministic/last_success.json').read_text(encoding='utf8'))['nitrogen_config']
    cfg.update(changes or {})
    (work/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v:.17g}\n'for k,v in cfg.items())+'/\n',encoding='ascii')
    env=os.environ.copy();env['DSSAT_N_CONFIG']=str(work/'NIntegration.nml');env['DSSAT_P0_TRACE']='1'if trace else'0'
    start=time.monotonic()
    with (work/'stdout.log').open('wb')as so,(work/'stderr.log').open('wb')as se:
        p=subprocess.run([str(exe),'B','DSSBatch.v48'],cwd=work,env=env,stdout=so,stderr=se,timeout=240)
    info=(work/'INFO.OUT').read_text(errors='replace')if(work/'INFO.OUT').exists()else''
    result=dict(name=name,success=p.returncode==0 and bool(re.search(r'Normal end of run\s+12\b',info)),
        returncode=p.returncode,config=cfg,binary=str(exe),binary_sha256=sha(exe),elapsed=time.monotonic()-start,
        input_hashes={f.name:sha(f)for f in work.iterdir()if f.is_file() and f.name in {p.name for p in Path(design['inputs']).iterdir()}})
    if not result['success']:
        dump(work/'receipt.json',result)
        raise RuntimeError(name+' '+(work/'stderr.log').read_text(errors='replace')[-2500:])
    if cfg['ni_stage']>=4 and cfg.get('budget_revision')==1:
        result['budget']=audit_A(work,cfg)
    try:
        comp=extract(work,pd.read_csv(design['observations']).fillna(''),Path(design['runtime']))
        comp.to_csv(work/'comparison.csv',index=False);result['phi']=float(comp.phi_contribution.sum())
    except ValueError as error: result['objective_error']=str(error)
    result['baseline_equal']={f:numeric_records(work/f)==numeric_records(BASE/f) for f in COMPARE_FILES}
    dump(work/'receipt.json',result)
    print('CASE',name,'Phi',result.get('phi'), 'budget',result.get('budget',{}).get('organic_independent_residual_max'),flush=True)
    return result

if __name__=='__main__':
    a=argparse.ArgumentParser();sub=a.add_subparsers(dest='cmd',required=True)
    b=sub.add_parser('build');b.add_argument('label')
    c=sub.add_parser('case');c.add_argument('name');c.add_argument('exe',type=Path);c.add_argument('--changes',default='{}')
    args=a.parse_args()
    if args.cmd=='build':build(args.label)
    else:case(args.name,args.exe,json.loads(args.changes))
