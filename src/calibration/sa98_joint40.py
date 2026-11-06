"""Sealed 40-parameter, 26SP-only uncertainty-weighted joint calibration."""
from pathlib import Path
import argparse
import json
import math
import re
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration import single_season_n as legacy
from src.calibration.all12_joint import check_relations
from src.common.input_manifest import verify_manifest_integrity
from src.common.param_registry import assert_valid_frozen_bounds
from src.dssat import run_dssat as runner

SIGNED = {'W_FRESH_CONTRAST', 'N_ADJACENT_FRESH_CONTRAST'}


def load_design(path, preflight=False):
    path=Path(path);d=json.loads(path.read_text(encoding='utf-8'))
    if d.get('schema')!='approved_sa98_joint40_v1' or not d.get('approved'):
        raise ValueError('Explicit approved40 design required')
    if not preflight and not d.get('ensemble_preflight_passed'):
        raise ValueError('Complete100-member preflight required')
    receipt=json.loads((path.parent/'frozen_configuration_receipt.json').read_text(encoding='utf-8'))
    if receipt['design_sha256']!=legacy.sha(path):raise ValueError('Design changed after sealing')
    for p,h in d['runtime_hashes'].items():
        if legacy.sha(ROOT/p)!=h:raise ValueError('Frozen runtime changed: '+p)
    if legacy.sha(d['dssat_executable'])!=d['dssat_executable_sha256']:raise ValueError('Binary changed')
    for ds in d['datasets']:
        if verify_manifest_integrity(ROOT/ds['bundle_path']).manifest_sha256!=ds['bundle_manifest_sha256']:
            raise ValueError('Input bundle changed')
        expected=list(range(1,13)) if ds['season_id']=='26SP' else [2,3,4,5,10,11,12,13]
        role='calibration' if ds['season_id']=='26SP' else 'validation'
        if ds['roles']!={role:expected}:raise ValueError('Frozen season split changed')
    if (d['ies_num_reals'],d['noptmax'],len(d['active_parameters']))!=(100,5,40):raise ValueError('Wrong approved size')
    bp=ROOT/'data/parameter_registry/bounds_frozen/eggplant'/(d['bounds_id']+'.csv')
    if legacy.sha(bp)!=d['bounds_sha256']:raise ValueError('Frozen bounds changed')
    assert_valid_frozen_bounds(bp);bounds=pd.read_csv(bp).fillna('')
    if set(bounds[bounds.status.eq('active')].name)!=set(d['active_parameters']):raise ValueError('Parameter identities changed')
    if legacy.sha(path.parent/'calibration_observations.csv')!=d['calibration_observations_sha256']:raise ValueError('Targets changed')
    obs=pd.read_csv(path.parent/'calibration_observations.csv').fillna('')
    if len(obs)!=665 or not obs.season_id.eq('26SP').all() or not obs.role.eq('calibration').all():raise ValueError('Validation leaked into objective')
    if obs.obsnme.duplicated().any() or not obs.final_weight.gt(0).all():raise ValueError('Invalid target weights/IDs')
    required={'FL-LF':400.,'SLPF_25SP':.93,'SLPF_26SP':.89,'SASC_RATIO':.9,'ICNS_25SP':1.,'ICNS_26SP':1.}
    indexed=bounds.set_index('name')
    for n,v in required.items():
        x=indexed.loc[n]
        if x.status!='fixed' or x.init!=v or x.lower!=v or x.upper!=v:raise ValueError('Fixed contract changed: '+n)
    return d,bounds,obs


def validate(values,bounds):
    values=legacy.validate_parameters(values,bounds);check_relations(values)
    if values['LNREF']<=values['FNPGN1']:raise ValueError('Reference N curve order')
    return values


def expected_filex(text,ratio):
    """Only SASC may change, rounded to the existing injector's .01 percent."""
    lines=text.splitlines(keepends=True);in_section=False;in_layers=False
    for i,line in enumerate(lines):
        if line.startswith('*'):in_section=line.upper().startswith('*SOIL ANALYSIS');in_layers=False
        if line.lstrip().startswith('@'):
            in_layers=in_section and 'SABL' in line and 'SAOC' in line;continue
        if in_layers and line.strip() and not line.lstrip().startswith('!'):
            parts=line.split();saoc=float(parts[3])
            if saoc<=0:raise ValueError('No measured SAOC; no hidden fallback')
            lines[i]=line.rstrip('\r\n')[:51].ljust(51)+f'{saoc*ratio:5.2f}\n'
    return ''.join(lines)


def simulate(work,dataset,values,d):
    work=legacy.prepare_inputs(work,dataset,next(iter(dataset['roles'].values())))
    # Always overwrite any machine-selected executable with the sealed binary.
    import shutil
    shutil.copy2(d['dssat_executable'],work/'DSCSM048.EXE')
    if legacy.sha(work/'DSCSM048.EXE')!=d['dssat_executable_sha256']:raise ValueError('Prepared binary mismatch')
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(work/'parameters.csv',index=False)
    fx=work/(dataset['experiment_code']+'.TMX');before=fx.read_text()
    soil=(work/'SOIL.SOL').read_text();weather=legacy.sha(work/'XXTW2403.WTH')
    command=[sys.executable,'-X','utf8',str(ROOT/'src/dssat/forward_sa98_joint40.py'),'--param-csv','parameters.csv','--batch','DSSBatch.v48']
    with (work/'model.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=180)
    if result.returncode:raise RuntimeError(f'Native forward failed({result.returncode}): {work / "model.log"}')
    if fx.read_text()!=expected_filex(before,.9):raise ValueError('FileX modified beyond approved SASC')
    target=values['SLPF_'+dataset['season_id']]
    def mask_slpf(text):
        lines=text.splitlines(keepends=True);i=next(i for i,l in enumerate(lines) if l.startswith('@ SCOM'))+1
        matches=list(re.finditer(r'[-+]?(?:\d*\.\d+|\d+)',lines[i]));m=matches[6]
        value=float(m.group());lines[i]=lines[i][:m.start()]+'<SLPF>'+lines[i][m.end():]
        return ''.join(lines),value
    masked_before,_=mask_slpf(soil);masked_after,actual_slpf=mask_slpf((work/'SOIL.SOL').read_text())
    if masked_before!=masked_after or abs(actual_slpf-target)>1e-9:raise ValueError('Soil changed beyond season-specific SLPF')
    if legacy.sha(work/'XXTW2403.WTH')!=weather:raise ValueError('Weather changed')
    audited=sorted(set(values).intersection(legacy.read_injected_parameters(work)))
    legacy.audit_injection(work,values,audited)
    native=legacy.read_injected_parameters(work)
    for n in d['active_parameters']:
        if n not in native:raise ValueError('Active parameter has no injection readback: '+n)
    if native['FL-LF'][0]!=400.:raise ValueError('FL-LF not400')
    check_relations({k:v[0] for k,v in native.items()})
    legacy.write_json(work/'fixed_input_audit.json',dict(season=dataset['season_id'],SASC_RATIO=.9,SLPF=target,
        ICNS=1.,FL_LF=400.,weather_unchanged=True,other_soil_and_filex_fields_unchanged=True))
    return work


def read_anthesis(path):
    result={};header=None
    for line in Path(path).read_text().splitlines():
        if line.startswith('@RUN'):header=line.lstrip('@').split()
        elif header and line.split() and line.split()[0].isdigit():
            row=dict(zip(header,line.split()));tn=int(row['TN']);v=float(row['ADAPS'])
            if tn in result or not math.isfinite(v) or v<0:raise ValueError('Invalid/duplicate anthesis')
            result[tn]=v
    return result


def check_water_geometry(work,obs):
    lines=(Path(work)/'SoilWat.OUT').read_text().splitlines()
    geometry=[]
    for line in lines:
        if line.startswith('!') and re.search(r'\b0-5\b',line):
            geometry.append([(int(a),int(b)) for a,b in re.findall(r'(\d+)\s*-\s*(\d+)',line)])
    if not geometry or any(x!=geometry[0] for x in geometry):raise ValueError('Ambiguous native output soil geometry')
    for row in obs[obs.variable.eq('VWC')].itertuples():
        top,bottom=float(row.depth_top_cm),float(row.depth_bottom_cm)
        expected={i:max(0.,min(bottom,b)-max(top,a))/(bottom-top) for i,(a,b) in enumerate(geometry[0])}
        expected={i:w for i,w in expected.items() if w>0}
        actual={int(a):float(b) for a,b in (x.split(':') for x in row.dssat_layer_weights.split(';'))}
        if set(actual)!=set(expected) or any(abs(actual[i]-expected[i])>1e-6 for i in actual):raise ValueError('Measured/native depth mapping mismatch')


def extract(work,obs,strict=True):
    work=Path(work);frames={n:legacy.read_native(work/(n+'.OUT')) for n in ['PlantGro','PlantN','FreshWt','SoilWat']}
    check_water_geometry(work,obs);anthesis=read_anthesis(work/'Evaluate.OUT');rows=[]
    for item in obs.to_dict('records'):
        try:
            var=item['variable'];key=(int(item['trno']),item['date'])
            if var=='ADAP':value=anthesis[key[0]]
            elif var in SIGNED:
                hi=float(frames['FreshWt'].loc[key,'CHFPW']);lo=float(frames['FreshWt'].loc[(int(item['paired_trno']),key[1]),'CHFPW'])
                if min(hi,lo)<0 or not np.isfinite([hi,lo]).all():raise ValueError('Missing contrast parent')
                value=hi-lo
            else:
                row=legacy.extract_observations(work,pd.DataFrame([item]),native_frames=frames).iloc[0]
                value=float(row.simulated)
            if not math.isfinite(value):raise ValueError('Nonfinite response')
            rows.append(item|dict(simulated=value,comparison_status='matched',model_error=''))
        except (KeyError,ValueError) as e:
            if strict:raise
            rows.append(item|dict(simulated=np.nan,comparison_status='model_unmatched',model_error=str(e)))
    return pd.DataFrame(rows)


def encode(frame):
    frame=frame.copy();r=(frame.simulated-frame.observed)/frame.sigma_eff
    e=r.copy();idx=frame.loss.eq('pseudo_huber');delta=pd.to_numeric(frame.loc[idx,'huber_delta'])
    e.loc[idx]=r.loc[idx]*np.sqrt(2/(np.hypot(1,r.loc[idx]/delta)+1))
    frame['standardized_raw_residual']=r;frame['pest_output']=e
    frame['phi_contribution']=np.square(e*frame.budget_multiplier)
    if not np.isfinite(frame.pest_output).all():raise ValueError('Nonfinite encoded response')
    return frame


def evaluate(design,param_csv,out,preflight=False):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True);output=out/'FormalObjectives.OUT';output.unlink(missing_ok=True)
    (out/'model_failure.json').unlink(missing_ok=True)
    d,bounds,obs=load_design(design,preflight);values=validate(runner._read_param_dict(param_csv),bounds)
    ds=next(x for x in d['datasets'] if x['season_id']=='26SP')
    work=simulate(out/'_model',ds,values,d);comparison=encode(extract(work,obs))
    comparison.to_csv(out/'last_comparison.csv',index=False)
    tmp=output.with_suffix('.tmp');tmp.write_text(''.join(f'{r.obsnme} {r.pest_output:.12g}\n' for r in comparison.itertuples()),encoding='ascii');tmp.replace(output)
    return comparison


def main():
    p=argparse.ArgumentParser();p.add_argument('--design',required=True);p.add_argument('--param-csv',default='parameters.csv');p.add_argument('--output-dir',default='.')
    a=p.parse_args()
    try:evaluate(a.design,a.param_csv,a.output_dir)
    except Exception as e:
        legacy.write_json(Path(a.output_dir)/'model_failure.json',dict(error=str(e),missing_values_imputed=False));raise


if __name__=='__main__':main()
