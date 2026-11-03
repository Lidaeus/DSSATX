"""P2: bounded stateful consumers of a single C/N plan and an organic-R substock."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,json,os,runpy,shutil,subprocess,sys
import numpy as np
import pandas as pd
import p1_workflow as p1

REPO=p1.REPO;CN=p1.CN;OUT=CN/'reports/n_v4_p2_20261103'
p1.OUT=OUT
sha=p1.sha;dump=p1.dump

def variants():
    r=dict(reserve_mode=1,reserve_capacity=.004,reserve_fill_tau=3.,reserve_protect=.02)
    return dict(compatibility={},baseline=dict(v4_diagnostics=1),reserve_only=dict(v4_diagnostics=1,**r),
        joint_only=dict(v4_diagnostics=1,common_acceptance=1),
        joint_reserve=dict(v4_diagnostics=1,common_acceptance=1,**r),
        reserve_small=dict(v4_diagnostics=1,common_acceptance=1,**dict(r,reserve_capacity=.001)),
        reserve_slow_fill=dict(v4_diagnostics=1,common_acceptance=1,**dict(r,reserve_fill_tau=8.)))

def build_variants():
    base=variants()['joint_reserve']
    return dict(build_leaf85=dict(base,build_min_leaf=.85),build_leaf70=dict(base,build_min_leaf=.70),
                build_both70=dict(base,build_min_leaf=.70,build_min_stem=.70))

def prepare():
    p1.prepare()
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    previous=CN/'reports/n_v4_p0_p1_20261103/delivery_manifest.json'
    d=json.loads(previous.read_text(encoding='utf8'));b['protected'][d['binary']]=d['binary_sha256']
    b.update(baseline_commit='3cfd205303cd03e6f6f846c50e83941624d68a41',
        user_authorization='2026-11-03 explicit request: implement one C/N acceptance plus leaf/stem organic reserve substocks',
        P2_parameters_role='explicit engineering values, not calibrated physiological estimates',
        variants=variants())
    dump(OUT/'frozen_baseline.json',b)

def deliver(revision):
    (OUT/'bin').mkdir(exist_ok=True)
    p1.EXE_NAME=f'dscsm048_v4_p2_{revision}.exe'
    exe=OUT/'bin'/p1.EXE_NAME
    assert not exe.exists(),'Preserve earlier builds and their failed cases'
    shutil.copy2(REPO/'build/bin/dscsm048.exe',exe)
    dump(OUT/'bin'/f'build_{revision}.json',dict(exe=str(exe),sha256=sha(exe),
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        source_hashes={str(p.relative_to(REPO)):sha(p) for folder in ['Plant/CROPGRO','SPAM'] for p in (REPO/folder).iterdir() if p.suffix.lower() in ['.for','.f90']},
        source_diff=subprocess.check_output(['git','diff'],cwd=REPO,text=True,encoding='utf8'),build_log_sha256=sha(REPO/'build/build_p2.log')))

def units(revision):
    sys.path.insert(0,str(REPO/'research/n_v3'))
    import workflow
    workflow.OUT=OUT
    sys.argv=['run_units.py',revision]
    runpy.run_path(str(REPO/'research/n_v3/run_units.py'),run_name='__main__')
    w=OUT/'units'/revision;env,fc=p1.build_env();flags=['-ffree-line-length-none','-fcheck=all','-finit-real=snan','-ffpe-trap=invalid,zero,overflow']
    results=[]
    for driver in ['native_p1_tests','native_p2_tests']:
        source=REPO/'research/n_v4'/f'{driver}.f90';exe=w/f'{driver}.exe'
        commands=[[fc,'-I',str(w/'mod'),'-I',str(REPO/'build/mod'),*flags,str(source),str(w/'core.obj'),'-o',str(exe),'-static','-static-libgcc','-static-libgfortran'],[str(exe)]]
        for cmd in commands:
            r=subprocess.run(cmd,cwd=w,env=env,text=True,capture_output=True)
            if r.returncode:raise RuntimeError(r.stdout+r.stderr)
        results.append(dict(driver=driver,passed=True,output=r.stdout,source_sha256=sha(source)))
        print(r.stdout.strip(),flush=True)
    dump(w/'P2_receipt.json',results)
    lifecycle(revision)

def lifecycle(revision,label='verified',changes=None):
    w=OUT/'units'/revision;env,fc=p1.build_env();flags=['-ffree-line-length-none','-fcheck=all','-finit-real=snan','-ffpe-trap=invalid,zero,overflow']
    life=w/('reserve_lifecycle_'+label);life.mkdir(exist_ok=False)
    cfg=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))['config'];cfg.update(variants()['reserve_only'])
    cfg.update(changes or {})
    (life/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v:.17g}\n' for k,v in cfg.items())+'/\n')
    env['DSSAT_N_CONFIG']=str(life/'NIntegration.nml')
    source=REPO/'research/n_v4/native_reserve_lifecycle.f90';exe=life/'lifecycle.exe'
    for cmd in [[fc,'-I',str(w/'mod'),'-I',str(REPO/'build/mod'),*flags,str(source),str(w/'core.obj'),'-o',str(exe),'-static','-static-libgcc','-static-libgfortran'],[str(exe)]]:
        r=subprocess.run(cmd,cwd=life,env=env,text=True,capture_output=True)
        (life/'output.log').write_text(r.stdout+r.stderr,encoding='utf8')
        if r.returncode:raise RuntimeError(r.stdout+r.stderr)
    p=pd.read_csv(life/'PlantNP2.csv')
    assert len(p)==11 and (p.R_fast_leaf+p.R_fast_stem).sum()>0
    assert (p.R_litter_leaf+p.R_litter_stem).sum()>0
    assert p.iloc[-1][['R_fast_leaf','R_fast_stem']].sum()==0
    dump(life/'receipt.json',dict(passed=True,driver_scope='controlled module lifecycle, not whole-crop validation',
        output=r.stdout,maximum_R=float((p.R_end_leaf+p.R_end_stem).max()),
        fast_release=float((p.R_fast_leaf+p.R_fast_stem).sum()),litter=float((p.R_litter_leaf+p.R_litter_stem).sum())))
    print(r.stdout.strip(),flush=True)

def lifecycle_sensitivity(revision):
    settings=dict(slow_fill=dict(reserve_fill_tau=8.),small_capacity=dict(reserve_capacity=.002),unprotected=dict(reserve_protect=0.))
    w=OUT/'units'/revision
    for label,changes in settings.items():lifecycle(revision,label,changes)
    values={label:json.loads((w/('reserve_lifecycle_'+label)/'receipt.json').read_text()) for label in ['verified',*settings]}
    assert values['slow_fill']['maximum_R']<values['verified']['maximum_R']
    assert values['small_capacity']['maximum_R']<values['verified']['maximum_R']
    assert values['unprotected']['fast_release']>values['verified']['fast_release']
    dump(w/'reserve_parameter_sensitivity.json',dict(passed=True,scope='controlled module only; field identifiability is not claimed',cases=values))

def audit_p2(work,cfg):
    p=pd.read_csv(work/'PlantNP2.csv',float_precision='round_trip')
    n=pd.read_csv(work/'PlantNIntegration.csv',float_precision='round_trip')
    a=pd.read_csv(work/'PlantABudget.csv',float_precision='round_trip')
    leaf=pd.read_csv(work/'PlantNLeaf.csv',float_precision='round_trip')
    mob=pd.read_csv(work/'PlantNRemob.csv',float_precision='round_trip')
    lux=pd.read_csv(work/'PlantNLuxury.csv',float_precision='round_trip')
    assert len(p)==1512 and not p.duplicated(['run','yrdoy']).any()
    assert all(list(zip(p.run,p.yrdoy))==list(zip(t.run,t.yrdoy)) for t in [n,a,leaf,mob,lux])
    assert p.common_acceptance.eq(cfg.get('common_acceptance',0)).all()
    assert p.reserve_mode.eq(cfg.get('reserve_mode',0)).all()
    if cfg.get('common_acceptance')==1:
        assert p.plan_calls.eq(1).all() and p.veg_calls.eq(1).all()
        assert p.common_scale.between(0,1).all()
        dc=np.zeros(len(p));dn=np.zeros(len(p))
        for o in ['leaf','stem','root']:
            dc+=p['dm_accept_'+o]*p['unit_C_'+o]
            dn+=p['N_accept_'+o]+p['repair_accept_'+o]
            assert (p['dm_accept_'+o]<=p['dm_request_'+o]+1e-12).all()
            assert (p['repair_used_'+o]<=p['repair_accept_'+o]+1e-7).all()
            if 'build_N_'+o in p:
                assert (p['N_accept_'+o]>=p['dm_accept_'+o]*p['build_N_'+o]-1e-7).all()
                assert (p['N_accept_'+o]<=p['dm_accept_'+o]*p['target_N_'+o]+1e-7).all()
                if cfg.get('build_min_'+o,-1)>0:
                    np.testing.assert_allclose(p['build_N_'+o],cfg['build_min_'+o]*p['target_N_'+o],rtol=0,atol=1e-14)
        assert (dc+p.fruit_C_cap+p.C_assim_accepted<=p.C_available+2e-5).all()
        assert (dn+p.fruit_N_cap<=p.N_available+1e-6).all()
        assert (p.fruit_C_used<=p.fruit_C_cap+2e-5).all()
        assert (p.fruit_N_used<=p.fruit_N_cap+1e-6).all()
        assert lux.A_function_late.eq(0).all(),'No second functional-repair acceptance'
    if cfg.get('reserve_mode')==1:
        for o in ['leaf','stem']:
            old=p.groupby('run')['R_end_'+o].shift().fillna(0)
            np.testing.assert_allclose(old,p['R_begin_'+o],rtol=0,atol=1e-14)
            res=p['R_begin_'+o]+p['R_fill_'+o]-p['R_fast_'+o]-p['R_sen_recovery_'+o]-p['R_litter_'+o]-p['R_end_'+o]
            assert abs(res).max()<1e-12
            assert (p['R_end_'+o]>=0).all() and (p['R_end_'+o]<=n['Norg_'+o]+1e-7).all()
            assert (p['R_end_'+o]<=p['R_capacity_'+o]+1e-9).all()
            np.testing.assert_allclose(p['N_nonreserve_'+o]+p['R_end_'+o],n['Norg_'+o],atol=1e-14,rtol=0)
            np.testing.assert_allclose(p['R_fast_'+o],mob['safe_'+o],atol=1e-14,rtol=0)
            assert (p['R_sen_recovery_'+o]<=leaf['sen_N_'+o]+1e-14).all()
            assert (p['R_litter_'+o]<=leaf['litter_N_'+o]+1e-12).all()
            assert not ((p['R_fast_'+o]>1e-12)&(p['R_fill_'+o]>1e-12)).any()
        np.testing.assert_allclose(p.R_fill_leaf+p.R_fill_stem,lux.A_luxury,rtol=0,atol=1e-12)
        for o in ['leaf','stem']:
            z=(p['N_nonreserve_'+o]/n['W_'+o]-n[o+'_min'])/(n[o+'_crit']-n[o+'_min'])
            np.testing.assert_allclose(z,n['NNI_functional_'+o],rtol=0,atol=1e-12)
    return dict(passed=True,rows=len(p),single_common_plan=cfg.get('common_acceptance')==1,
        reserve_stock_flow=cfg.get('reserve_mode')==1,
        maximum_reserve_N=float((p.R_end_leaf+p.R_end_stem).max()),reserve_fill_N=float((p.R_fill_leaf+p.R_fill_stem).sum()),
        reserve_fast_export_N=float((p.R_fast_leaf+p.R_fast_stem).sum()),
        reserve_sen_recovery_N=float((p.R_sen_recovery_leaf+p.R_sen_recovery_stem).sum()),
        reserve_litter_N=float((p.R_litter_leaf+p.R_litter_stem).sum()),whole_elemental_C_closed=False)

def execute(revision,variant,trace=False):
    p1.EXE_NAME=f'dscsm048_v4_p2_{revision}.exe'
    name=revision+'_'+variant+('_trace' if trace else '')
    cfg=(variants()|build_variants())[variant];result=p1.case((name,cfg))
    work=OUT/'cases'/name
    try:
        if result['success'] and max(cfg.get('common_acceptance',0),cfg.get('reserve_mode',0)):
            result['P2_budget']=audit_p2(work,result['config'])
        if variant in ['compatibility','baseline']:
            assert all(result['numeric_baseline_equal'].values())
            assert result['phi']==json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))['phi']
    except Exception as e:
        result.update(success=False,P2_audit_error=str(e),P2_audit_error_type=type(e).__name__)
    dump(work/'receipt.json',result)
    print('P2',name,'PASS' if result['success'] else 'FAIL',result.get('P2_budget',result.get('P2_audit_error','')),flush=True)
    return result

def guards(revision):
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    tests=[('mode',dict(common_acceptance=2),'NI P2: invalid mode'),
        ('missing_capacity',dict(reserve_mode=1),'explicit reserve capacity'),
        ('zero_fill_tau',dict(reserve_mode=1,reserve_capacity=.004,reserve_fill_tau=0,reserve_protect=.02),'explicit reserve capacity'),
        ('stage0',dict(common_acceptance=1,ni_stage=0),'complete C4/C1-C3 routes'),
        ('duplicate_leaf_gate',dict(common_acceptance=1,leaf_expansion_mode=1),'replaces the P1 expansion ablation'),
        ('build_outside',dict(common_acceptance=1,build_min_leaf=1.01),'new-tissue fraction must be'),
        ('build_without_common',dict(build_min_leaf=.7),'requires common acceptance')]
    results=[]
    for name,changes,message in tests:
        w=OUT/'invalid_p2'/revision/name;w.mkdir(parents=True,exist_ok=False)
        for filename in b['inputs']:shutil.copy2(Path(b['source'])/filename,w/filename)
        p1.redirect(w/'DSSATPRO.v48',w)
        cfg=dict(b['config']);cfg.update(changes)
        (w/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v:.17g}\n' for k,v in cfg.items())+'/\n')
        env=os.environ.copy();env.update(DSSAT_N_CONFIG=str(w/'NIntegration.nml'),DSSAT_P0_TRACE='0')
        r=subprocess.run([str(OUT/'bin'/p1.EXE_NAME),'B','DSSBatch.v48'],cwd=w,env=env,text=True,capture_output=True,timeout=60)
        (w/'output.log').write_text(r.stdout+r.stderr,encoding='utf8')
        assert r.returncode!=0 and message in r.stdout+r.stderr,(name,r.returncode,r.stdout+r.stderr)
        results.append(dict(name=name,passed=True,expected_message=message))
    dump(OUT/f'invalid_configuration_checks_{revision}.json',results)

def mode0(revision):
    source=CN/'reports/C4_calibration_readiness_20261103_r2/cases/delivery_mode0'
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    w=OUT/'cases'/f'{revision}_official_mode0';w.mkdir(parents=True,exist_ok=False)
    for name in b['inputs']+['NIntegration.nml']:shutil.copy2(source/name,w/name)
    p1.redirect(w/'DSSATPRO.v48',w)
    env=os.environ.copy();env.update(DSSAT_N_CONFIG=str(w/'NIntegration.nml'),DSSAT_P0_TRACE='0')
    with (w/'stdout.log').open('wb') as so,(w/'stderr.log').open('wb') as se:
        r=subprocess.run([str(OUT/'bin'/p1.EXE_NAME),'B','DSSBatch.v48'],cwd=w,env=env,stdout=so,stderr=se,timeout=240)
    assert r.returncode==0
    checks={f:p1.numeric_records(source/f)==p1.numeric_records(w/f) for f in p1.COMPARE_FILES}
    assert all(checks.values())
    dump(w/'receipt.json',dict(passed=True,official_mode0_numeric_equal=checks))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('step',choices=['prepare','deliver','units','lifecycle','lifecycle-sensitivity','case','all','mode0','guards','build-cases']);ap.add_argument('--revision',default='r5');ap.add_argument('--variant',choices=list(variants()|build_variants()),default='joint_reserve');ap.add_argument('--trace',action='store_true');a=ap.parse_args()
    p1.EXE_NAME=f'dscsm048_v4_p2_{a.revision}.exe'
    if a.step=='prepare':prepare()
    elif a.step=='deliver':deliver(a.revision)
    elif a.step=='units':units(a.revision)
    elif a.step=='lifecycle':lifecycle(a.revision)
    elif a.step=='lifecycle-sensitivity':lifecycle_sensitivity(a.revision)
    elif a.step=='case':
        r=execute(a.revision,a.variant,a.trace);sys.exit(0 if r['success'] else 1)
    elif a.step=='mode0':mode0(a.revision)
    elif a.step=='guards':guards(a.revision)
    elif a.step=='build-cases':
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda variant:execute(a.revision,variant),build_variants()))
        dump(OUT/f'build_cases_{a.revision}.json',results)
        assert all(x['success'] for x in results)
    else:
        with ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda variant:execute(a.revision,variant),variants()))
        dump(OUT/f'case_summary_{a.revision}.json',results)
        assert all(x['success'] for x in results),'Preserve failure receipts; do not exclude failed members or relax budgets'
