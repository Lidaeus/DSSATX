"""Approved signed, selectively robust joint objective (separate from sealed runs)."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration import single_season_n as legacy
from src.calibration import water_n_joint as parent
from src.common.param_registry import PHYSICAL_BOUNDS, assert_valid_frozen_bounds
from src.common.input_manifest import verify_manifest_integrity
from src.dssat import run_dssat as runner

SIGNED=parent.SIGNED
extract_observations=parent.extract_observations
audit_injection=parent.audit_injection

def check_relations(values):
    if values['FRSTMF']+values['FRLFF']>1+1.e-12:
        raise ValueError('FRSTMF+FRLFF>1 gives a negative endpoint root fraction')
    for organ in ['LF','ST','RT']:
        names=['PRO'+organ+x for x in ['F','G','I']]
        if not all(values[a]<=values[b] for a,b in zip(names,names[1:])):
            raise ValueError('Invalid protein order: '+str(names))
    if values['PROSHF']>values['PROSHI']:
        raise ValueError('Shell donor floor exceeds initial protein')
    for names in [('TB1','TO11','TO21','TM1'),('TB2','TO12','TO22','TM2'),('FNPGN1','FNPGN2','FNPGN3')]:
        if not all(values[a]<values[b] for a,b in zip(names,names[1:])):
            raise ValueError('Invalid ordered fields: '+str(names))
    if values['XMAGE']>=values['XFPHT']:
        raise ValueError('Mature fruit age must precede complete harvest age')

def validate_parameters(values,bounds):
    values=legacy.validate_parameters(values,bounds)
    for name,value in values.items():
        if name in PHYSICAL_BOUNDS and not PHYSICAL_BOUNDS[name][0]<=value<=PHYSICAL_BOUNDS[name][1]:
            raise ValueError('Physical hard bound violation: '+name)
    check_relations(values)
    return values

def loss_residual(r,kind,delta=.15):
    r=np.asarray(r,dtype=float)
    if kind=='quadratic':return r
    if kind!='pseudo_huber' or delta<=0:raise ValueError('Unsupported robust loss')
    return r*np.sqrt(2/(np.hypot(1,r/delta)+1))

def encode(comparison):
    comparison=comparison.copy()
    comparison['normalized_raw_residual']=(comparison.simulated-comparison.observed)/pd.to_numeric(comparison.fit_scale)
    comparison['pest_output']=np.nan
    for family,q in comparison.groupby('family',sort=False):
        kind=q.loss.iloc[0]
        comparison.loc[q.index,'pest_output']=loss_residual(q.normalized_raw_residual,kind)
    if not np.isfinite(comparison.pest_output).all():raise ValueError('Nonfinite objective encoding')
    comparison['phi_contribution']=np.square(comparison.pest_output*comparison.final_weight)
    return comparison

def validate_catalog(obs,policy):
    if len(obs)!=516 or obs.obsnme.duplicated().any() or not obs.final_weight.gt(0).all():raise ValueError('Expected516 unique targets')
    if not obs.dataset_role.eq('calibration').all() or set(obs.trno)!=set(range(4,13)):raise ValueError('Validation leaked into objective')
    if len(policy)!=16 or policy.phi_budget.sum()!=100 or set(obs.family)!=set(policy.family):raise ValueError('Budget contract changed')
    if not obs.approved.eq(True).all() or not policy.approved.eq(True).all():raise ValueError('Unapproved objective row')
    if not obs.pest_obsval.eq(0).all():raise ValueError('PEST observations must be zero transformed residual targets')
    fresh=obs[obs.family=='FINAL_FRESH_YIELD'].set_index('trno')
    for row in policy.itertuples():
        q=obs[obs.family==row.family]
        if len(q)!=row.n_targets or set(q.variable)!={row.variable} or set(q.loss)!={row.loss}:raise ValueError('Family contract changed')
        scale=2. if row.scale_policy=='fixed_2_days' else float(fresh.observed.mean()) if row.scale_policy=='frozen_terminal_fresh_yield_mean' else float(q.observed.mean())
        if not math.isfinite(scale) or scale<=0 or not np.allclose(q.fit_scale,scale,rtol=1e-12):raise ValueError('Frozen scale changed')
        if not np.allclose(q.final_weight,np.sqrt(row.phi_budget/len(q)),rtol=1e-12):raise ValueError('Transformed objective weight mismatch')
        if row.loss=='pseudo_huber' and not np.allclose(pd.to_numeric(q.huber_delta),.15):raise ValueError('Robust threshold changed')
        if row.family in ['W_SIGNED_CONTRAST','N_ADJACENT_SIGNED_CONTRAST']:
            for item in q.itertuples():
                expected=float(fresh.loc[item.trno,'observed']-fresh.loc[int(item.paired_trno),'observed'])
                if not np.isclose(expected,item.observed,rtol=1e-12):raise ValueError('Contrast primitive source mismatch')

def load_design(path,*,require_preflight=True):
    path=Path(path).resolve();d=json.loads(path.read_text(encoding='utf-8'))
    if d.get('schema')!='formal_robust_joint_v1' or not d.get('approved'):raise ValueError('Approved robust joint design required')
    if require_preflight:
        receipt=json.loads((path.parent/'frozen_configuration_receipt.json').read_text(encoding='utf-8'))
        if not d.get('runtime_preflight_passed') or receipt['design_sha256']!=legacy.sha(path):raise ValueError('Missing or changed native preflight')
    for category in ['runtime_hashes','source_hashes']:
        for rel,digest in d[category].items():
            if legacy.sha(ROOT/rel)!=digest:raise ValueError('Frozen source changed: '+rel)
    if legacy.sha(d['dssat_executable'])!=d['dssat_executable_sha256']:raise ValueError('DSSAT binary changed')
    for dataset in d['datasets']:
        actual=verify_manifest_integrity(ROOT/dataset['bundle_path'])
        if actual.manifest_sha256!=dataset['bundle_manifest_sha256']:raise ValueError('Input bundle changed')
    file=ROOT/'data/parameter_registry/bounds_frozen/eggplant'/(d['bounds_id']+'.csv')
    if legacy.sha(file)!=d['bounds_sha256']:raise ValueError('Frozen bounds changed')
    assert_valid_frozen_bounds(file);bounds=pd.read_csv(file).fillna('')
    if set(bounds[bounds.status=='active'].name)!=set(d['active_parameters']) or len(d['active_parameters'])!=65:raise ValueError('Active parameter identities changed')
    if d['noptmax']!=5 or d['ies_num_reals']!=200 or d.get('gradient_hard_gates'):raise ValueError('Execution differs from approval')
    fl=bounds.set_index('name').loc['FL-LF']
    if fl.lower!=45 or fl.upper!=220:raise ValueError('FL-LF must use user-approved45–220PTD')
    for filename,key in [('calibration_observations.csv','calibration_observations_sha256'),('approved_objective_policy.csv','policy_sha256')]:
        if legacy.sha(path.parent/filename)!=d[key]:raise ValueError('Objective catalog changed')
    obs=pd.read_csv(path.parent/'calibration_observations.csv').fillna('')
    policy=pd.read_csv(path.parent/'approved_objective_policy.csv')
    validate_catalog(obs,policy)
    return d,bounds,obs

def simulate(work,dataset,treatments,values,*,executable_sha256=None):
    work=legacy.prepare_inputs(work,dataset,treatments)
    if executable_sha256 and legacy.sha(work/'DSCSM048.EXE')!=executable_sha256:raise ValueError('Prepared binary changed')
    values={k:float(f'{v:.12g}') for k,v in values.items()}
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(work/'parameters.csv',index=False)
    before={f:legacy.sha(work/f) for f in [dataset['experiment_code']+'.TMX','XXTW2403.WTH']}
    soil_before=parent.soil_without_sldr((work/'SOIL.SOL').read_text())
    command=[sys.executable,'-X','utf8',str(ROOT/'src/dssat/forward_robust_joint.py'),'--param-csv','parameters.csv','--batch','DSSBatch.v48']
    with (work/'model.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=120)
    if result.returncode:raise RuntimeError(f'Native forward failed({result.returncode}): {work / "model.log"}')
    for f,h in before.items():
        if legacy.sha(work/f)!=h:raise ValueError('Measured input changed: '+f)
    if parent.soil_without_sldr((work/'SOIL.SOL').read_text())!=soil_before:raise ValueError('Soil modified beyond SLDR')
    return work

def evaluate(design_path,param_csv,output_dir,*,preflight=False):
    out=Path(output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    output=out/'FormalObjectives.OUT';output.unlink(missing_ok=True)
    (out/'model_failure.json').unlink(missing_ok=True)
    d,bounds,obs=load_design(design_path,require_preflight=not preflight)
    values=validate_parameters(runner._read_param_dict(param_csv),bounds)
    dataset=next(x for x in d['datasets'] if x['roles'].get('calibration'))
    work=simulate(out/'_model',dataset,dataset['roles']['calibration'],values,executable_sha256=d['dssat_executable_sha256'])
    audit_injection(work,values,d['active_parameters'])
    compared=encode(extract_observations(work,obs))
    compared.to_csv(out/'last_comparison.csv',index=False)
    temporary=output.with_suffix('.tmp')
    temporary.write_text('\n'.join(f'{r.obsnme} {r.pest_output:.12g}' for r in compared.itertuples())+'\n',encoding='ascii')
    temporary.replace(output)
    return compared

def metrics(compared):
    rows=[]
    for family,q in compared.groupby('family',sort=False):
        error=q.simulated-q.observed;rmse=float(np.sqrt(np.mean(error**2)));mean=float(q.observed.mean())
        rows.append(dict(family=family,variable=q.variable.iloc[0],n=len(q),unit=q.unit.iloc[0],loss=q.loss.iloc[0],
            observed_mean=mean,fit_scale=float(q.fit_scale.iloc[0]),rmse=rmse,nrmse_pct=100*rmse/mean if mean>0 else None,
            bias=float(error.mean()),phi_budget=float(q.phi_budget.iloc[0]),phi=float(q.phi_contribution.sum())))
    return pd.DataFrame(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--design',required=True);p.add_argument('--param-csv',default='parameters.csv');p.add_argument('--output-dir',default='.')
    a=p.parse_args()
    try:evaluate(a.design,a.param_csv,a.output_dir)
    except Exception as e:
        legacy.write_json(Path(a.output_dir)/'model_failure.json',dict(error=str(e),missing_values_imputed=False))
        raise

if __name__=='__main__':main()
