"""Freeze and replay the C4 accounting fix, preserving all previous binaries."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,os,shutil,subprocess,sys,runpy
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
CN=Path('D:/Tomato_Cal/subprojects/critical_n')
OUT=CN/'reports/C4_calibration_readiness_20261103_r2'
PREVIOUS=CN/'reports/n_v3_c4_execution_20261103'
FAILED=CN/'runs/n4864_C4_joint80x4_20261103_r1'
sys.path.insert(0,str(HERE));sys.path.insert(0,str(REPO/'research/n_integration_v2'))
from smoke_forward import sha,dump,redirect
from forward_c4 import audit_c4

def run(name,source,exe,inputs,design_path=None):
    work=OUT/'cases'/name;work.mkdir(parents=True,exist_ok=False)
    for item in list(inputs)+['NIntegration.nml']:shutil.copy2(source/item,work/item)
    redirect(work/'DSSATPRO.v48',work)
    env=os.environ.copy();env.update(DSSAT_N_CONFIG=str(work/'NIntegration.nml'),DSSAT_P0_TRACE='1')
    with (work/'stdout.log').open('wb')as so,(work/'stderr.log').open('wb')as se:
        r=subprocess.run([str(exe),'B','DSSBatch.v48'],cwd=work,env=env,stdout=so,stderr=se,timeout=240)
    assert r.returncode==0,(name,(work/'stderr.log').read_text()[-1200:])
    sys.path.insert(0,str(REPO/'research/n_v3'))
    from workflow import extract
    import pandas as pd,re
    cfg={k:float(v)for k,v in re.findall(r'(\w+)\s*=\s*([-+\d.eE]+)',(work/'NIntegration.nml').read_text())}
    design=json.loads((Path(design_path)if design_path else FAILED/'preparation_design.json').read_text(encoding='utf8'))
    comp=extract(work,pd.read_csv(design['observations']).fillna(''),Path(design['runtime']))
    comp.to_csv(work/'comparison.csv',index=False)
    receipt=dict(success=True,name=name,binary=str(exe),binary_sha256=sha(exe),config=cfg,
        phi=float(comp.phi_contribution.sum()),source=str(source),budget=audit_c4(work,cfg) if cfg.get('leaf_coupling')==1 else None)
    dump(work/'receipt.json',receipt);print(name,receipt['phi'],flush=True)
    return receipt

if __name__=='__main__':
    OUT.mkdir(exist_ok=False);(OUT/'bin').mkdir()
    exe=OUT/'bin/dscsm048_C4_r2.exe';shutil.copy2(REPO/'build/bin/dscsm048.exe',exe)
    d=json.loads((FAILED/'preparation_design.json').read_text(encoding='utf8'))
    inputs=[p.name for p in Path(d['inputs']).iterdir()if p.is_file()]
    jobs=[(f'delivery_{suffix}',PREVIOUS/f'cases/delivery_{suffix}')for suffix in ['mode0','A','C3','full']]
    import pandas as pd
    bounds=pd.read_csv(FAILED/'candidate_bounds.csv').set_index('name')
    for name in ['EM-FL','photo_slw_ref']:
        source=Path(json.loads((FAILED/'preflight'/bounds.loc[name,'pest_name']/'last_failure.json').read_text(encoding='utf8'))['trial'])
        jobs.append((name,source))
    with ThreadPoolExecutor(max_workers=3)as pool:
        results=list(pool.map(lambda item:run(*item,exe,inputs),jobs))
    protected=json.loads((PREVIOUS/'delivery_manifest.json').read_text(encoding='utf8'))['protected_executables_unchanged']
    previous=json.loads((PREVIOUS/'delivery_manifest.json').read_text(encoding='utf8'))
    protected[previous['binary']]=previous['binary_sha256']
    assert all(sha(p)==h for p,h in protected.items())
    sources={str(p.relative_to(REPO)):sha(p)for folder in ['Plant/CROPGRO','SPAM']for p in (REPO/folder).iterdir()if p.suffix.lower()in['.for','.f90']}
    dump(OUT/'delivery_manifest.json',dict(binary=str(exe),binary_sha256=sha(exe),mechanism_build_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        source_hashes=sources,protected_executables_unchanged=protected,cases=results,
        status='C4_accounting_fix_regression_for_requested_research_calibration_not_management_validation'))
    sys.path.insert(0,str(REPO/'research/n_v3'))
    import workflow
    workflow.OUT=OUT
    sys.argv=['run_units.py','C4_r1'];runpy.run_path(str(REPO/'research/n_v3/run_units.py'),run_name='__main__')
    for script,names in [('verify_c4.py',['delivery_full','EM-FL','photo_slw_ref']),('verify_c4_photo.py',['delivery_full','EM-FL','photo_slw_ref']),
                         ('verify_c1.py',['delivery_full']),('verify_c2.py',['delivery_full']),('verify_c3.py',['delivery_full'])]:
        sys.argv=[script]+names;runpy.run_path(str(REPO/'research/n_v3'/script),run_name='__main__')
