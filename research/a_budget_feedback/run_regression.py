from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import shutil
import subprocess
import sys
import time

import pandas as pd

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
CN=Path('D:/Tomato_Cal/subprojects/critical_n')
OLD=CN/'runs/n4864_p5_r2_explicit_smoke14_24x2_20261102'
OUT=CN/'reports/A_budget_feedback_20261102'
sys.path.insert(0,str(OLD/'runtime'))
from smoke_forward import sha,dump,redirect,extract,audit
sys.path.insert(0,str(REPO/'research/n_integration_v2'))
from prepare_readiness import numeric_records,COMPARE_FILES


def setup():
    OUT.mkdir(exist_ok=True,parents=True)
    (OUT/'bin').mkdir(exist_ok=True)
    shutil.copy2(REPO/'build/bin/dscsm048.exe',OUT/'bin/dscsm048_A_development.exe')


def case(name, changes=None, trace=False, binary=None):
    started=time.monotonic()
    changes=changes or {}
    d=json.loads((OLD/'design.json').read_text(encoding='utf8'))
    original=Path(json.loads((OLD/'diagnostics_r020_20261102/last_success.json').read_text(encoding='utf8'))['trial'])
    w=OUT/'regression'/name
    w.mkdir(parents=True,exist_ok=False)
    for p in Path(d['inputs']).iterdir():
        if p.is_file():shutil.copy2(original/p.name,w/p.name)
    redirect(w/'DSSATPRO.v48',w)
    values=pd.read_csv(OLD/'best_parameters.csv').set_index('name').value.to_dict()
    cfg=dict(ni_stage=5,root_mode=2,**{n:values[n] for n in d['nitrogen_names']})
    cfg.update(changes)
    (w/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v:.17g}\n'for k,v in cfg.items())+'/\n',encoding='ascii')
    env=os.environ.copy();env['DSSAT_N_CONFIG']=str(w/'NIntegration.nml');env['DSSAT_P0_TRACE']='1'if trace else'0'
    with(w/'stdout.log').open('wb')as so,(w/'stderr.log').open('wb')as se:
        p=subprocess.run([str(binary or OUT/'bin/dscsm048_A_development.exe'),'B','DSSBatch.v48'],cwd=w,env=env,stdout=so,stderr=se,timeout=240)
    info=(w/'INFO.OUT').read_text(encoding='utf8') if(w/'INFO.OUT').exists()else''
    r=dict(case=name,success=p.returncode==0 and bool(re.search(r'Normal end of run\s+12\b',info)),returncode=p.returncode,
           config=cfg,binary_sha256=sha(binary or OUT/'bin/dscsm048_A_development.exe'),elapsed_seconds=time.monotonic()-started)
    if r['success'] and cfg['ni_stage']==0:
        reference=CN/'reports/n_integration_v2_readiness_20261102/baseline_verified/reference_26SP'
        # These inputs are r020, not BASE; comparison belongs to a dedicated
        # same-input official call below, never the BASE regression output.
        legacy=OUT/'regression/official_original'
        if legacy.exists():r['same_input_numeric_equal']={f:numeric_records(w/f)==numeric_records(legacy/f)for f in COMPARE_FILES}
    if r['success'] and cfg['ni_stage']>0:
        a=dict(cfg)
        for organ in ['leaf','stem']:a[organ+'_a']=cfg[organ+'_a']*cfg.get('curve_w0',1.)**(-cfg[organ+'_b'])
        r['budget']=audit(w,a)
        r['budget']['legacy_bugs_deferred']=cfg.get('budget_revision',0)==0
        try:
            comp=extract(w,pd.read_csv(d['observations']).fillna(''),Path(d['runtime']))
            comp.to_csv(w/'comparison.csv',index=False)
            r['phi']=float(comp.phi_contribution.sum())
        except ValueError as error:
            if not name.startswith('diagnostic_'):raise
            r['objective_not_available']=str(error)
        if name=='revision_zero':r['numeric_equal']={f:numeric_records(w/f)==numeric_records(original/f)for f in COMPARE_FILES}
    dump(w/'receipt.json',r)
    print(name,r['success'],r.get('phi'),(w/'stderr.log').read_text(encoding='utf8')[-450:],flush=True)
    return r


if __name__=='__main__':
    setup()
    with ThreadPoolExecutor(max_workers=3)as pool:
        results=list(pool.map(lambda item:case(*item),[
            ('revision_zero',{},False),('A_base',{'budget_revision':1},True),('official_new',{'ni_stage':0,'root_mode':0},False)]))
    dump(OUT/'initial_regression_receipt.json',dict(cases=results))
