"""Custom-engine69 successor: inherited all12 objective and dedicated pinned engine/template."""
from __future__ import annotations
import argparse
import json
import math
import os
import re
import shutil
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
from subprojects.critical_n.calibration.bounds_protocol import CNC_PHYSICAL_BOUNDS

ID="eggplant_26sp_all12_cnc_joint69_200x5_20261014"
CONFIG=ROOT/"configs/runs"/ID
ENGINE=CONFIG/"engine/dscsm048_cnc.exe"
SPE_BASE=CONFIG/"templates/TMGRO048.SPE.base"
CNC_NAMES=["CNC_A","CNC_B","CNC_W0","CNC_NC_INF"]
ENGINE_SHA="56c65127d0bba53ac4d1b5591d71fdb8f87525a44bf393c4e857acc0dfb2cc89"
os.environ["DSSAT_CUSTOM_EXE"]=str(ENGINE)
os.environ["DSSAT_SPE_BASE"]=str(SPE_BASE)

SIGNED=parent.SIGNED
extract_observations=parent.extract_observations


def check_relations(values):
    if not values['CNC_A']>values['CNC_NC_INF']>0 or values['CNC_B']<=0 or values['CNC_W0']<=0:raise ValueError('Invalid CNC curve ordering')
    if .16*(values['PROLFI']-values['PROLFG'])<.002-1e-10:raise ValueError('Custom-engine leaf demand cap cannot accommodate F1 safeguard')
    if .16*(values['PROSTI']-values['PROSTG'])<.001-1e-10:raise ValueError('Custom-engine stem demand cap cannot accommodate F1 safeguard')
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
        if name in (PHYSICAL_BOUNDS|CNC_PHYSICAL_BOUNDS) and not (PHYSICAL_BOUNDS|CNC_PHYSICAL_BOUNDS)[name][0]<=value<=(PHYSICAL_BOUNDS|CNC_PHYSICAL_BOUNDS)[name][1]:
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
    if len(obs)!=689 or obs.obsnme.duplicated().any() or not obs.final_weight.gt(0).all():raise ValueError('Expected689 unique targets')
    if not obs.dataset_role.eq('calibration').all() or set(obs.trno)!=set(range(1,13)):raise ValueError('Validation leaked into objective')
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
    if d.get('schema')!='formal_cnc_all12_joint_v1' or not d.get('approved'):raise ValueError('Approved robust joint design required')
    if require_preflight:
        receipt=json.loads((path.parent/'frozen_configuration_receipt.json').read_text(encoding='utf-8'))
        if not d.get('runtime_preflight_passed') or receipt['design_sha256']!=legacy.sha(path):raise ValueError('Missing or changed native preflight')
    for category in ['runtime_hashes','source_hashes']:
        for rel,digest in d[category].items():
            if legacy.sha(ROOT/rel)!=digest:raise ValueError('Frozen source changed: '+rel)
    if d['dssat_executable_sha256']!=ENGINE_SHA:raise ValueError('Custom engine identity differs from authorized binary')
    if legacy.sha(d['dssat_executable'])!=d['dssat_executable_sha256']:raise ValueError('DSSAT binary changed')
    for dataset in d['datasets']:
        actual=verify_manifest_integrity(ROOT/dataset['bundle_path'])
        if actual.manifest_sha256!=dataset['bundle_manifest_sha256']:raise ValueError('Input bundle changed')
    file=ROOT/'data/parameter_registry/bounds_frozen/eggplant'/(d['bounds_id']+'.csv')
    if legacy.sha(file)!=d['bounds_sha256']:raise ValueError('Frozen bounds changed')
    assert_valid_frozen_bounds(file);bounds=pd.read_csv(file).fillna('')
    if set(bounds[bounds.status=='active'].name)!=set(d['active_parameters']) or len(d['active_parameters'])!=69:raise ValueError('Active parameter identities changed')
    if d['noptmax']!=5 or d['ies_num_reals']!=200 or d.get('gradient_hard_gates'):raise ValueError('Execution differs from approval')
    season=next(x for x in d['datasets'] if x['season_id']=='26SP')
    if season['roles']!={'calibration':list(range(1,13))}:raise ValueError('All12 role contract changed')
    for dataset in d['datasets']:
        if dataset['season_id']!='26SP' and dataset['roles'].get('calibration'):raise ValueError('2025 validation leakage')
    fl=bounds.set_index('name').loc['FL-LF']
    if fl.lower!=45 or fl.upper!=220:raise ValueError('FL-LF must use user-approved45–220PTD')
    for filename,key in [('calibration_observations.csv','calibration_observations_sha256'),('approved_objective_policy.csv','policy_sha256')]:
        if legacy.sha(path.parent/filename)!=d[key]:raise ValueError('Objective catalog changed')
    obs=pd.read_csv(path.parent/'calibration_observations.csv').fillna('')
    policy=pd.read_csv(path.parent/'approved_objective_policy.csv')
    validate_catalog(obs,policy)
    return d,bounds,obs

def read_cnc_fields(work):
    lines=(Path(work)/'TMGRO048.SPE').read_text().splitlines()
    ids=[i for i,x in enumerate(lines) if x.startswith('!*CRITICAL NITROGEN DILUTION')]
    if len(ids)!=1:raise ValueError('Exactly one CNC species card required')
    line=next(x for x in lines[ids[0]+1:] if x.strip() and not x.startswith(('!','@')))
    values={}
    for j,name in enumerate(CNC_NAMES):
        token=line[j*6:(j+1)*6].strip()
        if not token:raise ValueError('Missing fixed-width CNC field: '+name)
        actual=float(token);digits=len(token.partition('.')[2]);values[name]=(actual,10.**(-digits))
    if len(line[:24])!=24:raise ValueError('CNC card must contain24fixed-width characters')
    return values


def inject_cnc_fields(work,values):
    file=Path(work)/'TMGRO048.SPE';lines=file.read_text().splitlines()
    i=next(i for i,x in enumerate(lines) if x.startswith('!*CRITICAL NITROGEN DILUTION'))
    j=next(j for j in range(i+1,len(lines)) if lines[j].strip() and not lines[j].startswith(('!','@')))
    fields=[runner._format_to_width(float(f'{values[k]:.12g}'),6) for k in CNC_NAMES]
    if any(len(x)!=6 for x in fields):raise ValueError('CNC field overflow')
    lines[j]=''.join(fields)+'               CNC_A,CNC_B,CNC_W0,CNC_NC_INF'
    file.write_text('\n'.join(lines)+'\n',encoding='ascii')
    return read_cnc_fields(work)


def audit_injection(work,values,active):
    rows=parent.audit_injection(work,values,[x for x in active if x not in CNC_NAMES])
    for name,(actual,resolution) in read_cnc_fields(work).items():
        if abs(actual-values[name])>resolution/2+1e-9:raise ValueError('CNC readback mismatch: '+name)
        rows.append(dict(name=name,requested=values[name],injected=actual,printed_resolution=resolution))
    pd.DataFrame(rows).to_csv(Path(work)/'joint_parameter_injection_audit.csv',index=False)
    return rows


def audit_mass_balance(work,treatments):
    file=Path(work)/'PlantNBal.OUT';totals={};trt=None
    for line in file.read_text().splitlines():
        match=re.match(r'\s*TREATMENT\s+(\d+)',line)
        if match:trt=int(match[1]);totals[trt]=[]
        elif re.match(r'\s+TOTAL N\s+',line) and trt is not None:totals[trt].append(float(line.split()[-1]))
    if set(totals)!=set(treatments) or any(len(x)!=2 for x in totals.values()):raise ValueError('Incomplete plant N balance coverage')
    soil=legacy.read_native(Path(work)/'SoilNiBal.OUT');rows=[]
    for t,values in totals.items():
        a,b=values;residual=abs(a-b)
        q=soil.loc[t];soil_max=float(np.abs(q[['DBAL','CBAL']].to_numpy()).max())
        if residual>.25+1e-9 or soil_max>.05+1e-9:raise ValueError(f'Native N mass balance failed: T{t}, plant={residual},soil={soil_max}')
        rows.append(dict(trno=t,plant_total_1=a,plant_total_2=b,plant_residual_kg_ha=residual,soil_daily_or_cumulative_max_kg_ha=soil_max))
    pd.DataFrame(rows).to_csv(Path(work)/'nitrogen_balance_audit.csv',index=False)
    return rows


def simulate(work,dataset,treatments,values,*,executable_sha256=None):
    if legacy.sha(ENGINE)!=ENGINE_SHA:raise ValueError('Pinned custom binary changed')
    work=legacy.prepare_inputs(work,dataset,treatments)
    if legacy.sha(work/'DSCSM048.EXE')!=ENGINE_SHA:raise ValueError('Prepared engine is not the custom engine; no official fallback')
    values={k:float(f'{v:.12g}') for k,v in values.items()}
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(work/'parameters.csv',index=False)
    before={f:legacy.sha(work/f) for f in [dataset['experiment_code']+'.TMX','XXTW2403.WTH']}
    soil_before=parent.soil_without_sldr((work/'SOIL.SOL').read_text())
    # A dedicated process contains writer globals; native execution never searches PATH.
    command=[sys.executable,'-X','utf8',str(ROOT/'src/dssat/forward_cnc_joint_20261014.py'),'--param-csv','parameters.csv','--batch','DSSBatch.v48']
    with (work/'model.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode:raise RuntimeError(f'Custom forward failed({result.returncode}): {work / "model.log"}')
    for f,h in before.items():
        if legacy.sha(work/f)!=h:raise ValueError('Measured input changed: '+f)
    if parent.soil_without_sldr((work/'SOIL.SOL').read_text())!=soil_before:raise ValueError('Soil modified beyond SLDR')
    audit_mass_balance(work,treatments)
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
