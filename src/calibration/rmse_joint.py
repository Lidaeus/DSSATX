"""Versioned direct RMSE/NRMSE objective; gradient behavior is diagnostic only."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration import water_n_joint as parent
from src.calibration import single_season_n as legacy
from src.dssat import run_dssat as runner

SIGNED = {'WB100_INTERVAL'}
GRADIENT_VARIABLES = {'N_FRESH_CONTRAST','W_FRESH_CONTRAST','N2_SIGN_PENALTY',
                      'N_ADJACENT_FRESH_CONTRAST','W_FRESH_SIGN_PENALTY'}
validate_parameters = parent.validate_parameters
simulate = parent.simulate
audit_injection = parent.audit_injection
extract_observations = parent.extract_observations


def validate_catalog(obs, policy):
    if len(obs)!=504 or obs.obsnme.duplicated().any() or not obs.final_weight.gt(0).all():
        raise ValueError('Expected 504 unique direct-fit targets')
    if obs.variable.isin(GRADIENT_VARIABLES).any():
        raise ValueError('Gradient objectives were explicitly canceled')
    if not obs.dataset_role.eq('calibration').all() or set(obs.trno)!=set(range(4,13)):
        raise ValueError('Incorrect calibration split')
    if len(policy)!=14 or policy.phi_budget.sum()!=100:
        raise ValueError('Expected 14 families, total budget 100')
    if set(obs.family)!=set(policy.family):
        raise ValueError('Family identities differ')
    for row in policy.itertuples():
        q=obs[obs.family.eq(row.family)]
        if len(q)!=row.n_targets or set(q.variable)!={row.variable}:
            raise ValueError('Incorrect objective count or variable')
        scale=float(q.observed.mean()) if row.metric=='NRMSE' else float(row.fixed_scale)
        if not math.isfinite(scale) or scale<=0:
            raise ValueError('Nonpositive frozen normalization scale')
        expected=np.sqrt(row.phi_budget/len(q))/scale
        if not np.allclose(q.fit_scale,scale,rtol=1e-12) or not np.allclose(q.final_weight,expected,rtol=1e-12):
            raise ValueError('Weights do not implement declared RMSE/NRMSE')
        if row.family in {'FINAL_DRY_YIELD','FINAL_FRESH_YIELD'}:
            if not q.date.eq('2026-07-17').all() or q.trno.duplicated().any():
                raise ValueError('Final yield must be one exact terminal value per treatment')


def load_design(path, *, require_preflight=True):
    path=Path(path).resolve();d=json.loads(path.read_text(encoding='utf-8'))
    if d.get('schema')!='formal_rmse_joint_v1' or not d.get('approved'):
        raise ValueError('Approved direct-fit joint design required')
    if require_preflight:
        receipt=json.loads((path.parent/'frozen_configuration_receipt.json').read_text(encoding='utf-8'))
        if not d.get('runtime_preflight_passed') or legacy.sha(path)!=receipt['design_sha256']:
            raise ValueError('Missing/changed preflight')
    # The inherited bounds, input bundles, writer and original registry remain
    # hash sealed. The new design owns only the new objective and initialization.
    old,bounds,_=parent.load_design(ROOT/d['parent_design'])
    if d['bounds_id']!=old['bounds_id'] or d['bounds_sha256']!=old['bounds_sha256'] or d['datasets']!=old['datasets']:
        raise ValueError('Physical domain or input split changed')
    for category in ['runtime_hashes','source_hashes']:
        for rel,digest in d[category].items():
            if legacy.sha(ROOT/rel)!=digest: raise ValueError('Frozen source changed: '+rel)
    if set(d['active_parameters'])!=set(old['active_parameters']) or d['noptmax']!=5 or d['ies_num_reals']!=200:
        raise ValueError('Execution differs from authorized 65/200x5 scope')
    if d.get('gradient_hard_gates') or d.get('gradient_penalties'):
        raise ValueError('Unexpected gradient gate')
    file=path.parent/'calibration_observations.csv'
    if legacy.sha(file)!=d['calibration_observations_sha256']:
        raise ValueError('New objective catalog changed')
    obs=pd.read_csv(file).fillna('')
    policy=pd.read_csv(path.parent/'approved_objective_policy.csv')
    validate_catalog(obs,policy)
    return d,bounds,obs


def evaluate(design_path,param_csv,output_dir,*,preflight=False):
    out=Path(output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    output=out/'FormalObjectives.OUT';output.unlink(missing_ok=True)
    (out/'model_failure.json').unlink(missing_ok=True)
    d,bounds,obs=load_design(design_path,require_preflight=not preflight)
    values=validate_parameters(runner._read_param_dict(param_csv),bounds)
    dataset=next(x for x in d['datasets'] if x['roles'].get('calibration'))
    work=simulate(out/'_model',dataset,dataset['roles']['calibration'],values,executable_sha256=d['dssat_executable_sha256'])
    audit_injection(work,values,d['active_parameters'])
    comparison=extract_observations(work,obs)
    comparison.to_csv(out/'last_comparison.csv',index=False)
    temporary=output.with_suffix('.tmp')
    temporary.write_text('\n'.join(f'{r.obsnme} {r.simulated:.12g}' for r in comparison.itertuples())+'\n',encoding='ascii')
    temporary.replace(output)
    return comparison


def metrics(comparison):
    rows=[]
    for family,q in comparison.groupby('family',sort=False):
        residual=q.simulated-q.observed
        rmse=float(np.sqrt(np.mean(np.square(residual))))
        mean=float(q.observed.mean());scale=float(q.fit_scale.iloc[0])
        rows.append(dict(family=family,variable=q.variable.iloc[0],n=len(q),unit=q.unit.iloc[0],metric=q.fit_metric.iloc[0],
            observed_mean=mean,fit_scale=scale,phi_budget=float(q.phi_budget.iloc[0]),rmse=rmse,
            nrmse_pct=100*rmse/mean if mean>0 else None,bias=float(residual.mean()),
            phi=float(np.square(residual*q.final_weight).sum())))
    return pd.DataFrame(rows)


def main():
    p=argparse.ArgumentParser();p.add_argument('--design',required=True);p.add_argument('--param-csv',default='parameters.csv');p.add_argument('--output-dir',default='.')
    a=p.parse_args()
    try: evaluate(a.design,a.param_csv,a.output_dir)
    except Exception as error:
        legacy.write_json(Path(a.output_dir)/'model_failure.json',dict(error=str(error)))
        raise


if __name__=='__main__': main()
