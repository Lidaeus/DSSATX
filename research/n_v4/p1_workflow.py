"""Frozen C4-best P0/P1 mechanism comparisons, without calibration or imputation."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse,hashlib,json,os,re,runpy,shutil,subprocess,sys,time

import numpy as np
import pandas as pd

REPO=Path(__file__).resolve().parents[2]
CN=Path('D:/Tomato_Cal/subprojects/critical_n')
OUT=CN/'reports/n_v4_p0_p1_20261103'
OLD=CN/'runs/n4864_C4_joint80x4_20261103_r2'
sys.path.insert(0,str(REPO/'research/n_integration_v2'))
sys.path.insert(0,str(REPO/'research/n_v3_calibration'))
from smoke_forward import redirect,extract
from forward_c4 import audit_c4
from prepare_readiness import numeric_records,COMPARE_FILES

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def config(p):return {k:float(v) for k,v in re.findall(r'(\w+)\s*=\s*([-+\d.eE]+)',Path(p).read_text())}
def build_env():
    cache=(REPO/'build/CMakeCache.txt').read_text()
    fc=re.search(r'^CMAKE_Fortran_COMPILER:[^=]+=(.*)$',cache,re.M)[1]
    env=os.environ.copy();env['PATH']=str(Path(fc).parent)+';'+env['PATH']
    return env,fc

def prepare():
    OUT.mkdir(parents=True,exist_ok=False)
    d=json.loads((OLD/'design.json').read_text(encoding='utf8'))
    done=json.loads((OLD/'completion_receipt.json').read_text(encoding='utf8'))
    source=Path(done['best_trial'])
    protected=json.loads((CN/'reports/C4_calibration_readiness_20261103_r2/delivery_manifest.json').read_text(encoding='utf8'))['protected_executables_unchanged']
    protected[d['binary']]=d['binary_sha256']
    protected[str(CN/'n_buffer_v15/bin/v15_s1_interface.exe')]='107ec95f443af66eb30d53769496836414131d6befd6ab2f34cd00ef98b137fc'
    assert all(sha(p)==h for p,h in protected.items())
    inputs=[p.name for p in Path(d['inputs']).iterdir() if p.is_file()]
    cfg=config(source/'NIntegration.nml')
    assert cfg['c4_photo']==cfg['leaf_coupling']==cfg['c4_budget']==1
    assert done['completed'] and done['updates']==4
    dump(OUT/'frozen_baseline.json',dict(source=str(source),design=str(OLD/'design.json'),
        runtime=d['runtime'],observations=d['observations'],phi=done['best_actual_phi'],config=cfg,
        inputs=inputs,input_hashes={n:sha(source/n) for n in inputs},
        baseline_commit='6762098293fdaae9ede83911664ce25133d969ab',
        protected=protected,baseline_binary=d['binary'],baseline_binary_sha256=d['binary_sha256'],
        objective_sha256=sha(d['observations']),user_authorization='2026-11-03: start staged improvements and critically evaluate four-zone proposal',
        parameter_role='frozen C4 best; experimental mechanism variants, not calibrated or approved management model'))

def deliver():
    target=OUT/'bin';target.mkdir(exist_ok=True)
    assert not (target/'build_receipt.json').exists(),'Preserve completed delivery'
    exe=target/'dscsm048_v4_p1_research.exe'
    if exe.exists():assert sha(exe)==sha(REPO/'build/bin/dscsm048.exe'),'Unexpected partial delivery'
    else:shutil.copy2(REPO/'build/bin/dscsm048.exe',exe)
    dump(target/'build_receipt.json',dict(exe=str(exe),sha256=sha(exe),
        git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        source_hashes={str(p.relative_to(REPO)):sha(p) for folder in ['Plant/CROPGRO','SPAM'] for p in (REPO/folder).iterdir() if p.suffix.lower() in ['.for','.f90']},
        git_diff=subprocess.check_output(['git','diff'],cwd=REPO,text=True,encoding='utf8'),build_log_sha256=sha(REPO/'build/build_v4.log')))

def units():
    sys.path.insert(0,str(REPO/'research/n_v3'))
    import workflow
    workflow.OUT=OUT
    sys.argv=['run_units.py','p1']
    runpy.run_path(str(REPO/'research/n_v3/run_units.py'),run_name='__main__')
    work=OUT/'units/p1';env,fc=build_env()
    exe=work/'native_p1_tests.exe'
    flags=['-ffree-line-length-none','-fcheck=all','-finit-real=snan','-ffpe-trap=invalid,zero,overflow']
    commands=[[fc,'-I',str(work/'mod'),'-I',str(REPO/'build/mod'),*flags,
        str(REPO/'research/n_v4/native_p1_tests.f90'),str(work/'core.obj'),'-o',str(exe),'-static','-static-libgcc','-static-libgfortran'],[str(exe)]]
    output=[]
    for cmd in commands:
        r=subprocess.run(cmd,cwd=work,env=env,text=True,capture_output=True)
        if r.returncode:raise RuntimeError(r.stdout+r.stderr)
        output.append(r.stdout+r.stderr)
    dump(work/'p1_receipt.json',dict(passed=True,output=output,source_sha256=sha(REPO/'research/n_v4/native_p1_tests.f90')))
    print(output[-1].strip(),flush=True)

def experiments():
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))['config']
    plateau={o:b[o+'_a']*b['curve_w0']**(-b[o+'_b']) for o in ['leaf','stem']}
    area_ref=(1-b['min_ratio'])*plateau['leaf']*b['photo_slw_ref']*10000
    shape={}
    for o,inf,exponent in [('leaf',.021782,.2012),('stem',.021782*.159/.261,.2012*.548)]:
        shape.update({o+'_inf':inf,o+'_b':exponent,
            o+'_a':inf+(plateau[o]-inf)*b['curve_w0']**exponent})
    # Shape changes preserve the original establishment plateau and breakpoint.
    # They are not a transplant of the complete V15 optimum.
    photo=dict(photo_reference_mode=1,photo_sln_ref=area_ref)
    return dict(compatibility={},baseline=dict(v4_diagnostics=1),
        leaf_band=dict(v4_diagnostics=1,leaf_min_ratio=.59),
        stem_band=dict(v4_diagnostics=1,stem_min_ratio=.4025),
        curve_shape=dict(v4_diagnostics=1,**shape),
        fixed_photo=dict(v4_diagnostics=1,**photo),
        native_growth_budget=dict(v4_diagnostics=1,leaf_expansion_mode=1),
        leaf_band_fixed_photo=dict(v4_diagnostics=1,leaf_min_ratio=.59,**photo),
        native_growth_fixed_photo=dict(v4_diagnostics=1,leaf_expansion_mode=1,**photo),
        curve_shape_fixed_photo=dict(v4_diagnostics=1,**shape,**photo),
        curve_shape_leaf_band=dict(v4_diagnostics=1,leaf_min_ratio=.59,**shape))

def case(item):
    name,changes=item
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    work=OUT/'cases'/name;work.mkdir(parents=True,exist_ok=False)
    source=Path(b['source']);cfg=dict(b['config']);cfg.update(changes)
    for n in b['inputs']:shutil.copy2(source/n,work/n)
    redirect(work/'DSSATPRO.v48',work)
    (work/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v:.17g}\n' for k,v in cfg.items())+'/\n',encoding='ascii')
    env=os.environ.copy();env.update(DSSAT_N_CONFIG=str(work/'NIntegration.nml'),DSSAT_P0_TRACE='1' if name=='baseline' or name.endswith('_trace') else '0')
    exe=OUT/'bin/dscsm048_v4_p1_research.exe';start=time.monotonic()
    result=dict(name=name,changes=changes,config=cfg,binary_sha256=sha(exe),success=False)
    try:
        with (work/'stdout.log').open('wb') as so,(work/'stderr.log').open('wb') as se:
            r=subprocess.run([str(exe),'B','DSSBatch.v48'],cwd=work,env=env,stdout=so,stderr=se,timeout=240)
        assert r.returncode==0,(work/'stderr.log').read_text(errors='replace')[-2200:]
        assert re.search(r'Normal end of run\s+12\b',(work/'INFO.OUT').read_text())
        result['budget']=audit_c4(work,cfg)
        n=pd.read_csv(work/'PlantNIntegration.csv',float_precision='round_trip')
        w=(n.W_leaf+n.W_stem)/100
        for organ in ['leaf','stem']:
            inf=cfg.get(organ+'_inf',0)
            critical=inf+(cfg[organ+'_a']-inf)*np.maximum(cfg['curve_w0'],w)**(-cfg[organ+'_b'])
            np.testing.assert_allclose(n[organ+'_crit'],critical,rtol=2e-14,atol=1e-14)
            np.testing.assert_allclose(n[organ+'_min'],critical*cfg.get(organ+'_min_ratio',cfg['min_ratio']),rtol=2e-14,atol=1e-14)
        if cfg.get('v4_diagnostics')==1:
            v=pd.read_csv(work/'PlantNV4.csv',float_precision='round_trip')
            assert len(v)==1512 and not v.duplicated(['run','yrdoy']).any()
            for key in ['photo_reference_mode','leaf_expansion_mode']:
                assert v[key].eq(cfg.get(key,0)).all()
            if cfg.get('leaf_expansion_mode')==1:
                assert v.leaf_gate.eq(1).all() and v.storage_shift_leaf_to_stem.eq(0).all()
        try:
            c=extract(work,pd.read_csv(b['observations']).fillna(''),Path(b['runtime']))
            c.to_csv(work/'comparison.csv',index=False);result['phi']=float(c.phi_contribution.sum())
        except ValueError as error:result['objective_error']=str(error)
        result['numeric_baseline_equal']={f:numeric_records(work/f)==numeric_records(source/f) for f in COMPARE_FILES}
        if name in ['compatibility','baseline']:
            assert all(result['numeric_baseline_equal'].values())
            assert abs(result['phi']-b['phi'])<1.e-12
        assert all(sha(work/n)==h for n,h in b['input_hashes'].items() if n!='DSSATPRO.v48')
        result['success']=True
    except Exception as e:
        result['error']=str(e);result['error_type']=type(e).__name__
    result['elapsed_seconds']=time.monotonic()-start;dump(work/'receipt.json',result)
    print(name,'OK' if result['success'] else 'FAILED',result.get('phi',result.get('error')),flush=True)
    return result

def mode0():
    source=CN/'reports/C4_calibration_readiness_20261103_r2/cases/delivery_mode0'
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    work=OUT/'cases/official_mode0';work.mkdir(parents=True,exist_ok=False)
    for name in b['inputs']+['NIntegration.nml']:shutil.copy2(source/name,work/name)
    redirect(work/'DSSATPRO.v48',work)
    env=os.environ.copy();env.update(DSSAT_N_CONFIG=str(work/'NIntegration.nml'),DSSAT_P0_TRACE='0')
    with (work/'stdout.log').open('wb') as so,(work/'stderr.log').open('wb') as se:
        r=subprocess.run([str(OUT/'bin/dscsm048_v4_p1_research.exe'),'B','DSSBatch.v48'],cwd=work,env=env,stdout=so,stderr=se,timeout=240)
    assert r.returncode==0,(work/'stderr.log').read_text(errors='replace')
    checks={f:numeric_records(work/f)==numeric_records(source/f) for f in COMPARE_FILES}
    assert all(checks.values())
    dump(work/'receipt.json',dict(passed=True,official_mode0_numeric_equal=checks))

def run_cases():
    dump(OUT/'experimental_design.json',experiments())
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(case,experiments().items()))
    dump(OUT/'case_summary.json',results)
    mode0()
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    assert all(sha(p)==h for p,h in b['protected'].items())
    assert sha(b['observations'])==b['objective_sha256']
    dump(OUT/'protection_check.json',dict(passed=True,protected=b['protected'],objectives_unchanged=True))
    assert all(x['success'] for x in results),'Inspect individual failure receipts without excluding cases or relaxing budgets'

def trace_checks():
    names=['curve_shape_leaf_band','native_growth_budget','fixed_photo']
    for name in names:
        result=case((name+'_trace',experiments()[name]))
        assert result['success'],result
        left=OUT/'cases'/name;right=OUT/'cases'/(name+'_trace')
        assert all(numeric_records(left/f)==numeric_records(right/f) for f in COMPARE_FILES)
    sys.path.insert(0,str(REPO/'research/n_v3'))
    import workflow
    workflow.OUT=OUT
    for script in ['verify_c1.py','verify_c2.py','verify_c3.py','verify_c4.py','verify_c4_photo.py']:
        sys.argv=[script,'baseline']+[name+'_trace' for name in names]
        runpy.run_path(str(REPO/'research/n_v3'/script),run_name='__main__')
    dump(OUT/'independent_trace_checks.json',dict(passed=True,cases=['baseline']+names,
        trace_numeric_neutral=True,whole_elemental_C_closed=False))

def guards():
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    tests=[('leaf_ratio',dict(leaf_min_ratio=1),'invalid minimum ratio'),
        ('stem_ratio',dict(stem_min_ratio=0),'invalid minimum ratio'),
        ('photo_reference',dict(photo_reference_mode=1,photo_sln_ref=0),'explicit area-N reference'),
        ('mode',dict(leaf_expansion_mode=2),'invalid mode'),
        ('asymptote',dict(leaf_inf=b['config']['leaf_a']),'asymptote must be below'),
        ('inactive_stage',dict(ni_stage=0,v4_diagnostics=1),'experiments require complete C4')]
    results=[]
    for name,changes,expected in tests:
        w=OUT/'invalid_config'/name;w.mkdir(parents=True,exist_ok=False)
        for n in b['inputs']:shutil.copy2(Path(b['source'])/n,w/n)
        redirect(w/'DSSATPRO.v48',w)
        cfg=dict(b['config']);cfg.update(changes)
        (w/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v:.17g}\n' for k,v in cfg.items())+'/\n')
        env=os.environ.copy();env.update(DSSAT_N_CONFIG=str(w/'NIntegration.nml'),DSSAT_P0_TRACE='0')
        r=subprocess.run([str(OUT/'bin/dscsm048_v4_p1_research.exe'),'B','DSSBatch.v48'],cwd=w,env=env,capture_output=True,text=True,timeout=60)
        (w/'output.log').write_text(r.stdout+r.stderr,encoding='utf8')
        assert r.returncode!=0 and expected in r.stdout+r.stderr,(name,r.returncode,r.stdout+r.stderr)
        results.append(dict(name=name,passed=True,expected=expected,returncode=r.returncode))
    dump(OUT/'invalid_configuration_checks.json',results)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('step',choices=['prepare','deliver','units','cases','trace-checks','guards']);args=a.parse_args()
    {'prepare':prepare,'deliver':deliver,'units':units,'cases':run_cases,'trace-checks':trace_checks,'guards':guards}[args.step]()
