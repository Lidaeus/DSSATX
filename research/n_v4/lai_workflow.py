"""Isolated LAI-first builds, fixed-input experiments and independent budgets."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,json,os,runpy,shutil,subprocess,sys
import numpy as np
import pandas as pd
import p1_workflow as p1
import p2_workflow as p2

REPO=p1.REPO; CN=p1.CN; OUT=CN/'reports/n_v4_lai_20261103'
p1.OUT=OUT;p2.OUT=OUT
sha=p1.sha;dump=p1.dump

def variants():
    reserve=dict(reserve_mode=1,reserve_capacity=.004,reserve_fill_tau=3.,reserve_protect=.02)
    limits=dict(remob_rate_mode=1,remob_rate_max=.01,functional_rate_max=.001)
    return dict(compatibility={},baseline=dict(v4_diagnostics=1),
        reserve_control=dict(v4_diagnostics=1,**reserve),
        joint_control=dict(v4_diagnostics=1,common_acceptance=1,**reserve),
        slow_C4=dict(v4_diagnostics=1,**limits),
        slow_reserve=dict(v4_diagnostics=1,**reserve,**limits))

def prepare():
    p1.prepare()
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    previous=CN/'reports/n_v4_p2_20261103/bin/build_r5.json'
    old=json.loads(previous.read_text(encoding='utf8'))
    b['protected'][old['exe']]=old['sha256']
    b.update(baseline_commit='7c9818787aed4056b6abfde570b38f7b6cead39e',
        authorization='2026-11-03: implement LAI-first sequence and substantially lower daily N remobilization maximum',
        no_calibration=True,variants=variants())
    dump(OUT/'frozen_baseline.json',b)

def build(revision):
    target=OUT/'bin'/revision;target.mkdir(parents=True,exist_ok=False)
    env,_=p1.build_env()
    with (target/'build.log').open('w',encoding='utf8') as stream:
        r=subprocess.run(['cmake','--build',str(REPO/'build'),'--target','dscsm048','-j','6'],
            cwd=REPO,env=env,stdout=stream,stderr=subprocess.STDOUT)
    if r.returncode:raise RuntimeError((target/'build.log').read_text()[-5000:])
    exe=OUT/'bin'/f'dscsm048_v4_lai_{revision}.exe'
    assert not exe.exists()
    shutil.copy2(REPO/'build/bin/dscsm048.exe',exe)
    dump(target/'build_receipt.json',dict(exe=str(exe),sha256=sha(exe),
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        source_hashes={str(p.relative_to(REPO)):sha(p) for folder in ['Plant/CROPGRO','SPAM'] for p in (REPO/folder).iterdir() if p.suffix.lower() in ['.for','.f90']},
        source_diff=subprocess.check_output(['git','diff'],cwd=REPO,text=True,encoding='utf8')))
    print('BUILT',revision,sha(exe),flush=True)

def units(revision):
    p2.units(revision)
    w=OUT/'units'/revision;env,fc=p1.build_env()
    source=REPO/'research/n_v4/native_lai_tests.f90';exe=w/'native_lai_tests.exe'
    flags=['-ffree-line-length-none','-fcheck=all','-finit-real=snan','-ffpe-trap=invalid,zero,overflow']
    for cmd in [[fc,'-I',str(w/'mod'),'-I',str(REPO/'build/mod'),*flags,str(source),str(w/'core.obj'),'-o',str(exe),'-static','-static-libgcc','-static-libgfortran'],[str(exe)]]:
        r=subprocess.run(cmd,cwd=w,env=env,text=True,capture_output=True)
        if r.returncode:raise RuntimeError(r.stdout+r.stderr)
    dump(w/'LAI_receipt.json',dict(passed=True,source_sha256=sha(source),output=r.stdout))
    print(r.stdout.strip(),flush=True)

def audit_limits(work,cfg):
    m=pd.read_csv(work/'PlantNRemob.csv',float_precision='round_trip')
    assert len(m)==1512
    for organ in ['leaf','stem','root','shell']:
        assert (m['safe_'+organ]<=m['capR_'+organ]+1e-12).all()
        assert (m['function_'+organ]<=m['capF_'+organ]+1e-12).all()
    assert m.rate_mode.eq(cfg.get('remob_rate_mode',0)).all()
    if cfg.get('remob_rate_mode')==1:
        assert m.rate_max.eq(cfg['remob_rate_max']).all()
        assert m.functional_rate_max.eq(cfg['functional_rate_max']).all()
    return dict(passed=True,healthy_export=float(m.filter(regex='^(safe_|function_)').sum().sum()),
        functional_export=float(m.filter(regex='^function_').sum().sum()))

def execute(revision,variant,trace=False):
    p1.EXE_NAME=f'dscsm048_v4_lai_{revision}.exe'
    cfg=variants()[variant];name=revision+'_'+variant+('_trace' if trace else '')
    result=p1.case((name,cfg));work=OUT/'cases'/name
    try:
        if not result['success']:return result
        result['rate_budget']=audit_limits(work,result['config'])
        if max(cfg.get('common_acceptance',0),cfg.get('reserve_mode',0)):
            result['P2_budget']=p2.audit_p2(work,result['config'])
        if variant in ['baseline','compatibility']:
            assert all(result['numeric_baseline_equal'].values())
        dump(work/'receipt.json',result)
    except Exception as e:
        result.update(success=False,LAI_audit_error=str(e),LAI_audit_error_type=type(e).__name__)
        dump(work/'receipt.json',result)
    print('LAI',name,'PASS' if result['success'] else 'FAIL',result.get('LAI_audit_error',''),flush=True)
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('step',choices=['prepare','build','units','case','all','mode0'])
    ap.add_argument('--revision',default='r0');ap.add_argument('--variant',choices=list(variants()),default='slow_reserve');ap.add_argument('--trace',action='store_true');a=ap.parse_args()
    if a.step=='prepare':prepare()
    elif a.step=='build':build(a.revision)
    elif a.step=='units':units(a.revision)
    elif a.step=='mode0':
        p1.EXE_NAME=f'dscsm048_v4_lai_{a.revision}.exe';p1.mode0()
    elif a.step=='case':sys.exit(0 if execute(a.revision,a.variant,a.trace)['success'] else 1)
    else:
        with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(lambda k:execute(a.revision,k),variants()))
        dump(OUT/f'case_summary_{a.revision}.json',results)
        assert all(r['success'] for r in results),'Preserve failed receipts without excluding cases or relaxing budgets'
