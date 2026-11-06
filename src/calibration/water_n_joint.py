"""Approved 519-target, water-priority joint runtime, separate from sealed runs."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration import joint_n_objectives as joint
from src.calibration import single_season_n as legacy
from src.common.input_manifest import verify_manifest_integrity
from src.common.param_registry import assert_valid_frozen_bounds
from src.dssat import run_dssat as runner

SIGNED = joint.SIGNED | {'N_ADJACENT_FRESH_CONTRAST', 'WB100_INTERVAL'}
EXTRA = {'N_ADJACENT_FRESH_CONTRAST', 'WB100_INTERVAL', 'W_FRESH_SIGN_PENALTY'}
PROTECTED = ['CHPDT','HPODW','LAID','LWAD','SWAD','CHTD','LEAF_N_PCT','STEM_N_PCT','FRUIT_N_PCT']


def assert_bounds(path):
    assert_valid_frozen_bounds(path)
    bounds = pd.read_csv(path).fillna('')
    # Versioned support for the previously unregistered field. This strict
    # reviewed working domain supplements, rather than changes, the old registry.
    k = bounds.set_index('name').loc['KEP']
    if not .7 <= k.lower <= k.init <= k.upper <= .9:
        raise ValueError('KEP exceeds explicitly approved positive extinction domain')
    if len(bounds[bounds.status.eq('active')]) != 65:
        raise ValueError('Exactly 65 active parameters required')
    return bounds


def load_design(path, *, require_preflight=True):
    path = Path(path).resolve()
    d = json.loads(path.read_text(encoding='utf-8'))
    if d.get('schema') != 'formal_water_n_joint_v1' or not d.get('approved'):
        raise ValueError('Explicit approved water/N joint design required')
    if require_preflight:
        receipt = json.loads((path.parent/'frozen_configuration_receipt.json').read_text(encoding='utf-8'))
        if not d.get('runtime_preflight_passed') or legacy.sha(path) != receipt['design_sha256']:
            raise ValueError('Missing or changed preflight design')
    for rel, digest in d['runtime_hashes'].items():
        if legacy.sha(ROOT/rel) != digest:
            raise ValueError(f'Frozen runtime changed: {rel}')
    for rel, digest in d['source_hashes'].items():
        if legacy.sha(ROOT/rel) != digest:
            raise ValueError(f'Approved source changed: {rel}')
    if legacy.sha(d['dssat_executable']) != d['dssat_executable_sha256']:
        raise ValueError('DSSAT executable changed')
    frozen = ROOT/'data/parameter_registry/bounds_frozen/eggplant'/(d['bounds_id']+'.csv')
    if legacy.sha(frozen) != d['bounds_sha256']:
        raise ValueError('Frozen bounds changed')
    bounds = assert_bounds(frozen)
    if set(bounds[bounds.status.eq('active')].name) != set(d['active_parameters']):
        raise ValueError('Active identities changed')
    for dataset in d['datasets']:
        if verify_manifest_integrity(ROOT/dataset['bundle_path']).manifest_sha256 != dataset['bundle_manifest_sha256']:
            raise ValueError('Input bundle changed')
        ids = [t for v in dataset['roles'].values() for t in v]
        if len(ids) != len(set(ids)):
            raise ValueError('Data roles overlap')
    cal = [x for x in d['datasets'] if x['roles'].get('calibration')]
    if len(cal) != 1 or cal[0]['season_id'] != '26SP' or sorted(cal[0]['roles']['calibration']) != list(range(4,13)):
        raise ValueError('Incorrect calibration split')
    file = path.parent/'calibration_observations.csv'
    if legacy.sha(file) != d['calibration_observations_sha256']:
        raise ValueError('Observation catalog changed')
    obs = pd.read_csv(file).fillna('')
    if len(obs) != 519 or obs.obsnme.duplicated().any() or not obs.final_weight.gt(0).all():
        raise ValueError('519 unique positive weighted targets required')
    if not obs.dataset_role.eq('calibration').all() or set(obs.trno) != set(range(4,13)):
        raise ValueError('Validation leaked into calibration')
    return d, bounds, obs


def validate_parameters(values, bounds):
    values = joint.validate_parameters(values, bounds)
    for organ in ['LF','ST','RT','SH']:
        if values['PRO'+organ+'F'] > min(values['PRO'+organ+'I'], values['PRO'+organ+'G']):
            raise ValueError(f'Invalid donor pool protein floor: {organ}')
    return values


def soil_without_sldr(text):
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith('@ SCOM'):
            lines[i+1] = lines[i+1][:18]+'<SLDR>'+lines[i+1][24:]
    return ''.join(lines)


def simulate(work, dataset, treatments, values, *, executable_sha256=None):
    work = legacy.prepare_inputs(work, dataset, treatments)
    if executable_sha256 and legacy.sha(work/'DSCSM048.EXE') != executable_sha256:
        raise ValueError('Prepared DSSAT executable changed')
    values = {str(k).upper():float(f'{float(v):.12g}') for k,v in values.items()}
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(work/'parameters.csv', index=False)
    before = {f:legacy.sha(work/f) for f in [dataset['experiment_code']+'.TMX','XXTW2403.WTH']}
    soil_before = soil_without_sldr((work/'SOIL.SOL').read_text())
    command = [sys.executable,'-X','utf8',str(ROOT/'src/dssat/forward_water_n.py'),'--param-csv','parameters.csv','--batch','DSSBatch.v48']
    with (work/'model.log').open('w',encoding='utf-8') as log:
        result = subprocess.run(command,cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=120)
    if result.returncode:
        raise RuntimeError(f'Native forward failed ({result.returncode}): {work / "model.log"}')
    for f,digest in before.items():
        if legacy.sha(work/f) != digest:
            raise ValueError('Measured input changed: '+f)
    if soil_without_sldr((work/'SOIL.SOL').read_text()) != soil_before:
        raise ValueError('Soil changed outside the single approved SLDR field')
    return work


def audit_injection(work, values, active):
    extra = {'KEP','SOIL_SLDR'}
    rows = joint.audit_extended_injection(work,values,[x for x in active if x not in extra])
    lines = (Path(work)/'TMGRO048.SPE').read_text().splitlines()
    kep = next(x for x in lines if 'KEP, EORATIO' in x)
    lines = (Path(work)/'SOIL.SOL').read_text().splitlines()
    soil = lines[next(i for i,x in enumerate(lines) if x.startswith('@ SCOM'))+1]
    for name,printed in [('KEP',kep[:6]),('SOIL_SLDR',soil[18:24])]:
        actual = float(printed)
        resolution = 10.**(-len(printed.strip().partition('.')[2]))
        if abs(actual-values[name]) > resolution/2+1e-9:
            raise ValueError(f'Injection mismatch: {name}')
        rows.append(dict(name=name,requested=values[name],injected=actual,printed_resolution=resolution))
    pd.DataFrame(rows).to_csv(Path(work)/'joint_parameter_injection_audit.csv',index=False)
    return rows


def water_balance100(soil, trno, start, end, layers):
    a = (pd.Timestamp(start)-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    b = (pd.Timestamp(end)-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    sa,sb = soil.loc[(int(trno),a)],soil.loc[(int(trno),b)]
    if layers[0][0] != 0 or not any(bottom == 100 for top,bottom in layers):
        raise ValueError('Cannot represent measured 0-100 cm depth')
    if any(layers[i][1] != layers[i+1][0] for i in range(len(layers)-1)):
        raise ValueError('Noncontiguous native soil water layers')
    def stock(row):
        total = 0.
        for j,(top,bottom) in enumerate(layers,1):
            if top >= 100:
                break
            theta = float(row[f'SW{j}D'])
            if not math.isfinite(theta) or theta < 0:
                raise ValueError('Missing/invalid volumetric soil water')
            total += theta*(min(bottom,100)-top)*10.
        return total
    value = sum(float(sb[x]-sa[x])*factor for x,factor in [('IRRC',1),('PREC',1),('ROFC',-1)])-(stock(sb)-stock(sa))
    if not math.isfinite(value):
        raise ValueError('Invalid WB100 interval')
    return value


def extract_observations(work, obs):
    frames = {name:legacy.read_native(Path(work)/(name+'.OUT')) for name in ['PlantGro','PlantN','FreshWt','SoilWat']}
    ordinary = obs[~obs.variable.isin(EXTRA)]
    normal = joint.extract_observations(work,ordinary,native_frames=frames).set_index('obsnme')
    header = next(x for x in (Path(work)/'SoilWat.OUT').read_text().splitlines() if '0-5' in x)
    layers = [tuple(map(int,x)) for x in re.findall(r'(\d+)-(\d+)',header)]
    result = []
    for item in obs.to_dict('records'):
        var = item['variable']
        if var not in EXTRA:
            result.append(normal.loc[item['obsnme']].to_dict() | {'obsnme':item['obsnme']})
            continue
        if var == 'WB100_INTERVAL':
            value = water_balance100(frames['SoilWat'],item['trno'],item['interval_start'],item['interval_end'],layers)
        else:
            high = float(frames['FreshWt'].loc[(int(item['trno']),item['date']),'CHFPW'])
            low = float(frames['FreshWt'].loc[(int(item['paired_trno']),item['date']),'CHFPW'])
            if not all(math.isfinite(x) and x >= 0 for x in [high,low]):
                raise ValueError('Missing contrast parent')
            value = high-low
            if var == 'W_FRESH_SIGN_PENALTY':
                value = max(0.,-value)
        result.append({**item,'simulated':value})
    compared = pd.DataFrame(result)
    if not np.isfinite(compared.simulated).all() or (compared.loc[~compared.variable.isin(SIGNED),'simulated'] < 0).any():
        raise ValueError('Missing/nonphysical target')
    return compared


def evaluate(design_path,param_csv,output_dir,*,preflight=False):
    out = Path(output_dir).resolve()
    out.mkdir(parents=True,exist_ok=True)
    output = out/'FormalObjectives.OUT'
    output.unlink(missing_ok=True)
    (out/'model_failure.json').unlink(missing_ok=True)
    d,bounds,obs = load_design(design_path,require_preflight=not preflight)
    values = validate_parameters(runner._read_param_dict(param_csv),bounds)
    dataset = next(x for x in d['datasets'] if x['roles'].get('calibration'))
    work = simulate(out/'_model',dataset,dataset['roles']['calibration'],values,executable_sha256=d['dssat_executable_sha256'])
    audit_injection(work,values,d['active_parameters'])
    compared = extract_observations(work,obs)
    compared.to_csv(out/'last_comparison.csv',index=False)
    temp = output.with_suffix('.tmp')
    temp.write_text('\n'.join(f'{r.obsnme} {r.simulated:.12g}' for r in compared.itertuples())+'\n',encoding='ascii')
    temp.replace(output)
    return compared


def candidate_gates(obs, simulated, baseline):
    """Selection only; failing water response is never a forward failure."""
    v = np.asarray(simulated,dtype=float)
    original = ~obs.variable.isin(EXTRA).to_numpy()
    old_weights = pd.to_numeric(obs.original_weight,errors='coerce').fillna(0).to_numpy()
    sq = np.square((v-obs.observed.to_numpy())*old_weights)
    nonwater = original & ~obs.family.isin(['SOIL_WATER','W_RESPONSE']).to_numpy()
    phi, nonphi = float(sq[original].sum()),float(sq[nonwater].sum())
    w = obs.variable.eq('W_FRESH_CONTRAST').to_numpy()
    ratios = v[w]/obs.loc[w,'observed'].to_numpy()
    failures = []
    if not np.isfinite(v).all(): failures.append('incomplete_exact_targets')
    if not (v[w]>0).all(): failures.append('water_direction')
    if not (ratios>=.25).all(): failures.append('water_minimum_effect')
    if phi>baseline['original_phi']*1.10: failures.append('original_phi_guard')
    if nonphi>baseline['nonwater_phi']*1.10: failures.append('nonwater_phi_guard')
    metrics = {}
    for variable in PROTECTED:
        mask = obs.variable.eq(variable).to_numpy()
        nrmse = 100*float(np.sqrt(np.mean(np.square(v[mask]-obs.loc[mask,'observed'].to_numpy()))))/float(obs.loc[mask,'observed'].mean())
        metrics[variable] = nrmse
        base = baseline['nrmse'][variable]
        if not math.isfinite(nrmse) or nrmse>base+max(2.,.1*base): failures.append(variable+'_NRMSE_guard')
    return dict(eligible=not failures,failures=failures,original_phi=phi,nonwater_phi=nonphi,
                positive_water_contrasts=int((v[w]>0).sum()),min_response_ratio=float(ratios.min()),nrmse=metrics)


def main():
    p=argparse.ArgumentParser();p.add_argument('--design',required=True);p.add_argument('--param-csv',default='parameters.csv');p.add_argument('--output-dir',default='.')
    a=p.parse_args()
    try: evaluate(a.design,a.param_csv,a.output_dir)
    except Exception as error:
        legacy.write_json(Path(a.output_dir)/'model_failure.json',{'error':str(error)})
        raise


if __name__ == '__main__': main()
