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
    controls=dict(compatibility={},baseline=dict(v4_diagnostics=1),
        reserve_control=dict(v4_diagnostics=1,**reserve),
        joint_control=dict(v4_diagnostics=1,common_acceptance=1,**reserve),
        slow_C4=dict(v4_diagnostics=1,**limits),
        slow_reserve=dict(v4_diagnostics=1,**reserve,**limits))
    leaf=dict(v4_diagnostics=1,**reserve,**limits,lai_cn_mode=1,lai_cn_shape=2.)
    return controls|dict(lai_only=dict(v4_diagnostics=1,**reserve,lai_cn_mode=1,lai_cn_shape=2.),
        lai_slow=leaf,lai_linear=dict(leaf,lai_cn_shape=1.),
        lai_build85=dict(leaf,build_min_leaf=.85),lai_build70=dict(leaf,build_min_leaf=.70),
        lai_joint=dict(leaf,common_acceptance=1))

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

def audit_lai(work,cfg):
    d=pd.read_csv(work/'PlantNLAI.csv',float_precision='round_trip')
    assert len(d)==1512 and not d.duplicated(['run','yrdoy']).any()
    assert d.accept_calls.eq(1).all() and d.area_calls.eq(1).all()
    assert d.lai_cn_mode.eq(cfg.get('lai_cn_mode',0)).all()
    assert (d.C_used_veg<=d.C_available_veg+2e-5).all()
    assert (d.N_used_veg<=d.N_available_veg+1e-6).all()
    np.testing.assert_allclose(d.new_leaf_area,d.dm_leaf_actual*d.SLA_new,atol=.0002,rtol=2e-7)
    if cfg.get('lai_cn_mode')==1:
        state=np.clip(d.state_smoothed,0,1)
        factor=1-(1-state)**cfg['lai_cn_shape']
        np.testing.assert_allclose(d.state_response,factor,rtol=1e-13,atol=1e-14)
        assert (d.dm_leaf_request<=d.dm_leaf_potential*factor+1e-12).all()
        assert (d.dm_leaf_actual<=d.dm_leaf_request+2e-6).all()
        assert (d.N_leaf_actual>=d.dm_leaf_actual*d.build_N_leaf-1e-7).all()
    # Temporal area budget; establishment is audited by the full C4 trace.
    previous=d.groupby('run').LAI_end.shift()
    err=(d.LAI_end-previous)*10000-d.new_leaf_area+d.old_leaf_area_lost
    assert abs(err.dropna()).max()<.01
    return dict(passed=True,rows=len(d),maximum_area_budget_error_cm2=float(abs(err.dropna()).max()),
        signal_active_days=int(d.state_response.lt(.999).sum()),minimum_signal=float(d.state_response.min()))

def execute(revision,variant,trace=False):
    p1.EXE_NAME=f'dscsm048_v4_lai_{revision}.exe'
    cfg=variants()[variant];name=revision+'_'+variant+('_trace' if trace else '')
    result=p1.case((name,cfg));work=OUT/'cases'/name
    try:
        if not result['success']:return result
        result['rate_budget']=audit_limits(work,result['config'])
        if (work/'PlantNLAI.csv').exists():result['LAI_budget']=audit_lai(work,result['config'])
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

def guards(revision):
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    tests=[('rate_mode',dict(remob_rate_mode=2),'invalid remobilization rate mode'),
        ('missing_rate',dict(remob_rate_mode=1),'ordered daily rate limits'),
        ('rate_order',dict(remob_rate_mode=1,remob_rate_max=.001,functional_rate_max=.01),'ordered daily rate limits'),
        ('rate_without_mode',dict(remob_rate_max=.01),'unused rate limits'),
        ('leaf_mode',dict(lai_cn_mode=2),'invalid leaf C/N mode'),
        ('missing_shape',dict(lai_cn_mode=1),'explicit response shape'),
        ('shape_without_mode',dict(lai_cn_shape=2),'unused leaf response'),
        ('shape_high',dict(lai_cn_mode=1,lai_cn_shape=4.01),'explicit response shape'),
        ('duplicate_gate',dict(lai_cn_mode=1,lai_cn_shape=2,leaf_expansion_mode=1),'duplicate expansion policy'),
        ('inactive_stage',dict(lai_cn_mode=1,lai_cn_shape=2,ni_stage=0),'complete revised C4 routes'),
        ('build_without_route',dict(build_min_leaf=.7),'requires common acceptance'),
        ('build_invalid',dict(lai_cn_mode=1,lai_cn_shape=2,build_min_leaf=0),'new-tissue fraction')]
    results=[]
    for name,changes,expected in tests:
        w=OUT/'invalid_lai'/revision/name;w.mkdir(parents=True,exist_ok=False)
        for filename in b['inputs']:shutil.copy2(Path(b['source'])/filename,w/filename)
        p1.redirect(w/'DSSATPRO.v48',w);cfg=dict(b['config']);cfg.update(changes)
        (w/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v:.17g}\n' for k,v in cfg.items())+'/\n')
        env=os.environ.copy();env.update(DSSAT_N_CONFIG=str(w/'NIntegration.nml'),DSSAT_P0_TRACE='0')
        r=subprocess.run([str(OUT/'bin'/f'dscsm048_v4_lai_{revision}.exe'),'B','DSSBatch.v48'],cwd=w,env=env,text=True,capture_output=True,timeout=60)
        (w/'output.log').write_text(r.stdout+r.stderr,encoding='utf8')
        assert r.returncode!=0 and expected in r.stdout+r.stderr,(name,r.returncode,r.stdout+r.stderr)
        results.append(dict(name=name,passed=True,expected_message=expected))
    dump(OUT/f'invalid_configuration_checks_{revision}.json',results)

def mode0(revision):
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    source=CN/'reports/C4_calibration_readiness_20261103_r2/cases/delivery_mode0'
    w=OUT/'cases'/f'{revision}_official_mode0';w.mkdir(parents=True,exist_ok=False)
    for filename in b['inputs']+['NIntegration.nml']:shutil.copy2(source/filename,w/filename)
    p1.redirect(w/'DSSATPRO.v48',w)
    env=os.environ.copy();env.update(DSSAT_N_CONFIG=str(w/'NIntegration.nml'),DSSAT_P0_TRACE='0')
    with (w/'stdout.log').open('wb') as so,(w/'stderr.log').open('wb') as se:
        r=subprocess.run([str(OUT/'bin'/f'dscsm048_v4_lai_{revision}.exe'),'B','DSSBatch.v48'],cwd=w,env=env,stdout=so,stderr=se,timeout=240)
    assert r.returncode==0
    checks={f:p1.numeric_records(source/f)==p1.numeric_records(w/f) for f in p1.COMPARE_FILES}
    assert all(checks.values());dump(w/'receipt.json',dict(passed=True,official_mode0_numeric_equal=checks))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('step',choices=['prepare','build','units','case','all','mode0','guards'])
    ap.add_argument('--revision',default='r3');ap.add_argument('--variant',choices=list(variants()),default='lai_slow');ap.add_argument('--trace',action='store_true');a=ap.parse_args()
    if a.step=='prepare':prepare()
    elif a.step=='build':build(a.revision)
    elif a.step=='units':units(a.revision)
    elif a.step=='mode0':mode0(a.revision)
    elif a.step=='guards':guards(a.revision)
    elif a.step=='case':sys.exit(0 if execute(a.revision,a.variant,a.trace)['success'] else 1)
    else:
        dump(OUT/f'experimental_design_{a.revision}.json',variants())
        with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(lambda k:execute(a.revision,k),variants()))
        dump(OUT/f'case_summary_{a.revision}.json',results)
        assert all(r['success'] for r in results),'Preserve failed receipts without excluding cases or relaxing budgets'
