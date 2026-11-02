"""Replay the exact selected native inputs, with read-only trace and ablations."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,os,shutil,subprocess,sys,re
import pandas as pd
from run_regression import OUT,OLD,sha,dump,redirect,extract,numeric_records,COMPARE_FILES
from forward_A import audit_A

ROOT=OUT.parents[1]/'runs/n4864_A_joint80x4_20261102_r1'
d=json.loads((ROOT/'design.json').read_text(encoding='utf8'))
selected=json.loads((ROOT/'completion_receipt.json').read_text(encoding='utf8'))
original=Path(selected['best_trial'])
cfg=json.loads((ROOT/'selected_deterministic/last_success.json').read_text(encoding='utf8'))['nitrogen_config']


def one(name,binary,trace):
    w=OUT/name;w.mkdir(exist_ok=False)
    for p in Path(d['inputs']).iterdir():
        if p.is_file():shutil.copy2(original/p.name,w/p.name)
    shutil.copy2(original/'NIntegration.nml',w/'NIntegration.nml');redirect(w/'DSSATPRO.v48',w)
    env=os.environ.copy();env['DSSAT_N_CONFIG']=str(w/'NIntegration.nml');env['DSSAT_P0_TRACE']='1'if trace else'0'
    with(w/'stdout.log').open('wb')as so,(w/'stderr.log').open('wb')as se:
        p=subprocess.run([str(binary),'B','DSSBatch.v48'],cwd=w,env=env,stdout=so,stderr=se,timeout=180)
    if p.returncode or not re.search(r'Normal end of run\s+12\b',(w/'INFO.OUT').read_text(encoding='utf8')):raise RuntimeError(name)
    r=dict(passed=True,binary_sha256=sha(binary),config=cfg,budget=audit_A(w,cfg),source_trial=str(original),parameters_changed=False)
    if trace:
        r['numeric_regression']={f:numeric_records(w/f)==numeric_records(original/f)for f in COMPARE_FILES}
        assert all(r['numeric_regression'].values())
    try:
        comp=extract(w,pd.read_csv(d['observations']).fillna(''),Path(d['runtime']))
        comp.to_csv(w/'comparison.csv',index=False);r['phi']=float(comp.phi_contribution.sum())
    except ValueError as e:r['objective_error']=str(e)
    dump(w/'receipt.json',r);print(name,r.get('phi'),flush=True)
    return r


with ThreadPoolExecutor(max_workers=3)as pool:
    args=[('best_native_trace',Path(d['binary']),True),
          ('best_leaf_mobil_off',OUT/'leaf_mobil_ablation/leaf_0.0/dscsm048_leaf_ablation.exe',False),
          ('best_leaf_mobil_half',OUT/'leaf_mobil_ablation/leaf_0.5/dscsm048_leaf_ablation.exe',False)]
    results=list(pool.map(lambda v:one(*v),args))
dump(OUT/'best_trace_ablation_receipt.json',dict(cases=results,calibrated_model_unchanged=True))
