"""Authorized finite ET/environment experiments; isolated native DSSAT runs."""
from __future__ import annotations

import argparse
import concurrent.futures
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.experiments import water_n_response_grid_20261012 as base
from src.calibration import joint_n_objectives as joint
from src.common.param_registry import PHYSICAL_BOUNDS

OUT = ROOT/'workspace/experiments/et_environment_grid_20261012'
SOURCE = ROOT/'workspace/audits/et_method_grid_20261012/source'


def cases():
    rows=[dict(case_id='baseline',family='baseline',EVAPO='R')]
    for rw,k,dr in itertools.product([.008,.012,.020],[.70,.85,.90],[.25,.65,.90]):
        rows.append(dict(case_id=f'R_r{rw:.3f}_k{k:.2f}_d{dr:.2f}',family='RWUMX_KEP_SLDR',EVAPO='R',RWUMX=rw,KEP=k,SLDR=dr))
    for dr in [.10,.25,.40,.90]:
        rows.append(dict(case_id=f'R_SLDR_{dr:.2f}',family='SLDR_single',EVAPO='R',SLDR=dr))
    for scale,dr in itertools.product([.5,2.],[.25,.65,.90]):
        rows.append(dict(case_id=f'R_ks{scale:.1f}_d{dr:.2f}',family='SSKS_SLDR',EVAPO='R',RWUMX=.012,KEP=.85,SLDR=dr,SSKS_scale=scale))
    for key,levels in [('SALB',[.08,.20]),('SLU1',[2.,8.])]:
        for value in levels:rows.append(dict(case_id=f'R_{key}_{value}',family='evaporation_single',EVAPO='R',**{key:value}))
    rows.append(dict(case_id='H_default',family='ET_method',EVAPO='H'))
    for rw,k in itertools.product([.008,.012,.020],[.70,.85]):
        rows.append(dict(case_id=f'H_r{rw:.3f}_k{k:.2f}',family='H_water',EVAPO='H',RWUMX=rw,KEP=k))
    for method in ['F','D','S','Z']:
        rows.append(dict(case_id=f'{method}_default',family='ET_method_default_wind',EVAPO=method))
        for wind in [.2,.5,1.,2.]:
            rows.append(dict(case_id=f'{method}_wind_{wind:.1f}',family='ET_method_wind',EVAPO=method,WIND_m_s=wind))
        rows.append(dict(case_id=f'{method}_water_wind_0.5',family='ET_method_water',EVAPO=method,WIND_m_s=.5,RWUMX=.012,KEP=.85))
    for ratio in [.8,1.2,1.4]:
        rows.append(dict(case_id=f'F_water_ratio_{ratio:.1f}',family='F_EORATIO',EVAPO='F',WIND_m_s=.5,RWUMX=.012,KEP=.85,EORATIO=ratio))
    assert len({x['case_id'] for x in rows})==len(rows)
    return rows


ORIGINAL_PATCH=base.patch_inputs


def patch_inputs(work,dataset,case):
    audit=ORIGINAL_PATCH(work,dataset,case)
    filex=work/(dataset['experiment_code']+'.TMX')
    lines=filex.read_text().splitlines(keepends=True);methods=[]
    for i,line in enumerate(lines):
        tokens=list(re.finditer(r'\S+',line))
        if len(tokens)>=13 and tokens[0].group().isdigit() and tokens[1].group()=='ME':
            span=tokens[5].span();lines[i]=line[:span[0]]+case['EVAPO']+line[span[1]:];methods.append(case['EVAPO'])
    if not methods:raise ValueError('No FileX method rows patched')
    filex.write_text(''.join(lines))
    soil=work/'SOIL.SOL';lines=soil.read_text().splitlines(keepends=True);actual={};ks=[];in_layers=False
    for i,line in enumerate(lines):
        if line.startswith('@ SCOM'):
            vals=lines[i+1].split()
            for key,idx in [('SALB',1),('SLDR',3)]:
                if key in case:
                    lo,hi=PHYSICAL_BOUNDS['SOIL_'+key]
                    if not lo<=case[key]<=hi:raise ValueError('Outside hard soil bounds '+key)
                    vals[idx]=f"{case[key]:.2f}"
                actual[key]=float(vals[idx])
            actual['SLU1']=float(vals[2])
            lines[i+1]=''.join(f'{x:>6}' for x in vals)+'\n'
        if line.startswith('@  SLB'):in_layers=True;continue
        if line.startswith('*') or line.startswith('@'):in_layers=False
        if in_layers and line.split() and line.split()[0].isdigit():
            value=float(line.split()[6])*case.get('SSKS_scale',1.)
            if value<=0:raise ValueError('Invalid saturated conductivity')
            if 'SSKS_scale' in case:lines[i]=line[:36]+f'{value:6.2f}'+line[42:]
            ks.append(float(lines[i].split()[6]))
    soil.write_text(''.join(lines))
    if not ks:raise ValueError('No conductivity profile read')
    wth=work/'XXTW2403.WTH'
    if 'WIND_m_s' in case:
        # DSSAT WIND = daily run km/d, not m/s. Height explicitly 2 m.
        lines=wth.read_text().splitlines(keepends=True);count=0
        for i,line in enumerate(lines):
            if line.startswith('@ INSI'):
                lines[i]=line.rstrip()+' WINDHT\n';lines[i+1]=lines[i+1].rstrip()+f'{2.0:6.1f}'+'\n'
            if line.lstrip().startswith('@') and 'DATE' in line:
                if 'WIND' in line.split():raise ValueError('Unexpected existing wind column')
                lines[i]=line.rstrip()+'  WIND\n'
            if re.match(r'^\s*20\d{5}\s',line):
                lines[i]=line.rstrip()+f"{case['WIND_m_s']*86.4:6.1f}"+'\n';count+=1
        if not count:raise ValueError('No daily wind values patched')
        wth.write_text(''.join(lines))
        # Independently check header/row width and supplied wind in km/day.
        for line in wth.read_text().splitlines():
            if re.match(r'^\s*20\d{5}\s',line):
                if len(line.split())!=7 or abs(float(line.split()[-1])-case['WIND_m_s']*86.4)>.051:
                    raise ValueError('Wind injection readback mismatch')
    dew_count=0
    if case.get('derived_DEWP'):
        coverage=pd.read_csv(ROOT/'workspace/audits/et_method_grid_20261012/humidity/dewpoint_coverage_and_weather_match.csv')
        coverage=coverage[coverage.season_id.eq(dataset['season_id'])].set_index('date')
        lines=wth.read_text().splitlines(keepends=True)
        for i,line in enumerate(lines):
            if line.lstrip().startswith('@') and 'DATE' in line:lines[i]=line.rstrip()+'  DEWP\n'
            if re.match(r'^\s*20\d{5}\s',line):
                code=line.split()[0];date=(pd.Timestamp(int(code[:4]),1,1)+pd.Timedelta(days=int(code[4:])-1)).strftime('%Y-%m-%d')
                value=-99.
                if date in coverage.index and bool(coverage.loc[date,'same_source_weather_match']):
                    value=float(coverage.loc[date,'DEWP']);dew_count+=1
                lines[i]=line.rstrip()+f'{value:6.1f}'+'\n'
        wth.write_text(''.join(lines))
    # Independent soil readback after all patches.
    reread=soil.read_text().splitlines();header=next(i for i,s in enumerate(reread) if s.startswith('@ SCOM'))
    vals=reread[header+1].split()
    for key,idx in [('SALB',1),('SLU1',2),('SLDR',3)]:
        if key in case and abs(float(vals[idx])-case[key])>.006:raise ValueError('Soil readback mismatch '+key)
    payload=dict(methods_written=methods,soil=actual,SSKS_written=ks,
        wind_source='explicit_assumed_constant_2m' if 'WIND_m_s' in case else 'missing_WIND_model_defaults',
        WIND_m_s=case.get('WIND_m_s'),WIND_km_day=case.get('WIND_m_s',0)*86.4 if 'WIND_m_s' in case else None,
        WIND_written_km_day=round(case['WIND_m_s']*86.4,1) if 'WIND_m_s' in case else None,
        derived_DEWP_days=dew_count,derived_DEWP=bool(case.get('derived_DEWP')),
        weather_sha256=base.sha(wth),filex_sha256=base.sha(filex),soil_sha256=base.sha(soil))
    (work/'environment_injection_audit.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
    return audit


def worker(case_id,season):
    base.OUT=OUT;base.patch_inputs=patch_inputs
    rows=base.worker(case_id,season)
    # DSSAT-generated final input independently confirms the actual method.
    inp=(OUT/'cases'/case_id/season/'DSSAT48.INP').read_text().splitlines()
    index=inp.index('*SIMULATION CONTROL ')
    effective=inp[index+3].split()[3]
    case=next(x for x in json.loads((OUT/'experiment_manifest.json').read_text())['cases'] if x['case_id']==case_id)
    if effective!=case['EVAPO']:raise ValueError('Native input method mismatch '+effective)
    p=OUT/'cases'/case_id/season/'environment_injection_audit.json';audit=json.loads(p.read_text());audit['native_EVAPO']=effective
    weather=base.legacy.read_native(OUT/'cases'/case_id/season/'Weather.OUT')
    audit['native_WDSD_range_km_day']=[float(weather.WDSD.min()),float(weather.WDSD.max())]
    if 'WIND_m_s' in case and max(abs(x-case['WIND_m_s']*86.4) for x in audit['native_WDSD_range_km_day'])>.11:
        raise ValueError('Native weather wind mismatch')
    if case.get('derived_DEWP'):
        coverage=pd.read_csv(ROOT/'workspace/audits/et_method_grid_20261012/humidity/dewpoint_coverage_and_weather_match.csv')
        coverage=coverage[(coverage.season_id==season)&coverage.same_source_weather_match].set_index('date')
        native=weather.reset_index().groupby('date').TDWD.first()
        difference=(native.loc[native.index.intersection(coverage.index)]-coverage.DEWP).dropna()
        if difference.abs().max()>.11:raise ValueError('Native dewpoint readback mismatch')
        audit['native_DEWP_max_error_C']=float(difference.abs().max())
    p.write_text(json.dumps(audit,indent=2)+'\n')
    return rows


def execute(pair):
    case,season=pair;work=OUT/'cases'/case/season;work.mkdir(parents=True,exist_ok=True)
    with (work/'worker.log').open('w',encoding='utf-8') as handle:
        result=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--worker',case,'--season',season],cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT)
    return dict(case_id=case,season_id=season,exit_code=result.returncode)


def initialize():
    if (OUT/'experiment_manifest.json').exists():return
    joint.load_design(base.CONFIG/'design.json')
    design=json.loads((base.CONFIG/'design.json').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True,exist_ok=True)
    sources=[base.PARAMS,base.CONFIG/'design.json',base.CONFIG/'calibration_observations.csv',Path(base.__file__),
        ROOT/'tools/experiments/compare_observed_et_20261012.py',ROOT/'workspace/audits/observed_et_comparison_20261012/observed_ET_transcription.csv']
    sources.extend(ROOT/x['bundle_path']/'input_manifest.json' for x in design['datasets'])
    sources.extend(SOURCE.glob('*'))
    manifest=dict(status='authorized_small_diagnostic_grid_not_formal_calibration',
        user_authorization='先按上述策略做小规模试验或者网格试验，找出有效范围，尝试更换蒸散方法，根据试验制定下次正式率定方案。',
        datasets=design['datasets'],cases=cases(),parameter_reference=str(base.PARAMS),
        selection_policy='2026 only; 2025 spring/autumn external retrospective checks, never used in candidate ranking',
        wind_policy='F/D/S/Z with missing wind or explicit assumed 0.2/0.5/1/2 m/s at 2m; all are diagnostic, not real weather observations',
        baseline_reproduction='all 492 exact-date predictions and original Phi required',
        prespecified_acceptance=dict(no_missing_targets=True,nonwater_phi_max_increase_fraction=.10,
          per_target_family_NRMSE_max_increase='max(2 percentage points, 10% baseline NRMSE)',
          full_original_phi_max_increase_fraction=.10,
          strong_water_improvement='WB100 two-interval NRMSE at least 10% lower AND VWC NRMSE at least 5% lower',
          weak_water_improvement='WB100 and VWC both improve without required percentage cutoff',
          scope='advisory diagnostic guardrails, not experimental measurement accuracy'),
        unsupported_method_policy='If H baseline fails for missing crop PHSV/PHTV, omit further H grid; do not invent coefficients',
        source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):base.sha(p) for p in sources},
        source_code_sha256=base.sha(Path(__file__)),frozen_inputs_modified=False)
    (OUT/'experiment_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker');parser.add_argument('--season');parser.add_argument('--probe',action='store_true')
    args=parser.parse_args()
    if args.worker:worker(args.worker,args.season);return
    initialize();manifest=json.loads((OUT/'experiment_manifest.json').read_text(encoding='utf-8'))
    skipped=[]
    hlog=OUT/'cases/H_default/26SP/WARNING.OUT'
    h_bad=hlog.exists() and ('PHSV' in hlog.read_text(errors='replace') or 'PHTV' in hlog.read_text(errors='replace'))
    selected=[x for x in manifest['cases'] if not args.probe or x['case_id'] in ['baseline','H_default','F_default','D_default','S_default','Z_default']]
    tasks=[]
    for case in selected:
        if h_bad and case['EVAPO']=='H':
            skipped.append(dict(case_id=case['case_id'],reason='Crop has no defined PHSV/PHTV for H; no fabricated coefficients'));continue
        for season in (['26SP'] if args.probe else ['26SP','25SP','25FA']):
            work=OUT/'cases'/case['case_id']/season
            if (work/'process_summary.csv').exists() and (work/'environment_injection_audit.json').exists():
                audit=json.loads((work/'environment_injection_audit.json').read_text())
                if audit.get('native_EVAPO')==case['EVAPO']:continue
            tasks.append((case['case_id'],season))
    status=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for future in concurrent.futures.as_completed([pool.submit(execute,pair) for pair in tasks]):
            status.append(future.result())
            (OUT/'execution_status.json').write_text(json.dumps(dict(completed=len(status),expected=len(tasks),failed=sum(x['exit_code']!=0 for x in status))))
    pd.DataFrame(status).to_csv(OUT/('probe_status.csv' if args.probe else 'execution_status.csv'),index=False)
    (OUT/'skipped_cases.json').write_text(json.dumps(skipped,ensure_ascii=False,indent=2)+'\n')
    for name,digest in manifest['source_hashes'].items():assert base.sha(ROOT/name)==digest,name
    print(json.dumps(dict(phase='probe' if args.probe else 'full',cases=len(selected),tasks=len(tasks),failed=sum(x['exit_code']!=0 for x in status),skipped=len(skipped),sources_unchanged=True)))


if __name__=='__main__':main()
