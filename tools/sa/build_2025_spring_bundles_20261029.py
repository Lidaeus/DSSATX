"""Freeze observed and controlled 2025 spring sensitivity inputs and preflight them."""
from pathlib import Path
import copy
import csv
import hashlib
import json
import os
import shutil
import sys
import subprocess

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.common.input_manifest import verify_manifest_integrity, verify_calibrated_input_bundle, InputUseProhibitedError
from src.common.experiment_inputs import parse_filex, filex_section_text, validate_input_bundle, findings_as_dicts
from src.sensitivity.counterfactual_inputs import pooled_median_initial_profile, replace_initial_profile
from src.sensitivity.treatment_factor_attribution import replace_treatment_factors
from src.sensitivity.output_contract import load_output_contract, observation_names
from src.sensitivity.sa_model import compute_indicators
from tools.experiments.rebuild_current_bundles import read_summary, read_daily_output, replace_section

DATE='2026-10-29'
SOURCE=ROOT/'data/user/experiments/xxql2501_refreshed_20261027'
DEST=ROOT/'data/user/sa_bundles'
AUDIT=ROOT/'workspace/audits/sa_bundles_20261029'
TRT=(2,3,4,5,10,11,12,13)


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def common_analysis(filex):
    rows=[]
    for line in filex_section_text(filex,'*SOIL ANALYSIS').splitlines():
        tokens=line.split()
        if len(tokens)==10 and tokens[0].isdigit():
            rows.append([float(v) for v in tokens])
    frame=pd.DataFrame(rows,columns=['factor','SABL','SADM','SAOC','SANI','SAPHW','SAPHB','SAPX','SAKE','SASC'])
    frame=frame[frame.factor.isin(TRT)]
    assert len(frame)==80
    pooled=frame.groupby('SABL').median(numeric_only=True).drop(columns='factor').reset_index()
    lines=['*SOIL ANALYSIS','@A SADAT  SMHB  SMPX  SMKE  SANAME',' 2 25071 SA012 SA001 SA001 pooled_median_background',
           '@A  SABL  SADM  SAOC  SANI SAPHW SAPHB  SAPX  SAKE  SASC']
    digits=[0,2,2,3,2,0,1,1,0]
    for r in pooled.itertuples(index=False,name=None):
        lines.append(' 2'+''.join(f'{value:6.{d}f}' for value,d in zip(r,digits)))
    return '\n'.join(lines),pooled


def profile_for(out,kind):
    profile=json.loads((ROOT/'configs/sa/eggplant_p1_outputs.json').read_text(encoding='utf-8'))
    # The current forward reader names this feature explicitly as cumulative harvest.
    profile=json.loads(json.dumps(profile).replace('FRUITD_DAP50','CUMHARVEST_DAP50'))
    profile['profile_id']=f'eggplant_25sp_{kind}_20261029'
    profile['experiment_bundle']=out.name
    fert=pd.read_csv(SOURCE/'fertilizer_event_audit.csv')
    doses=fert.groupby('施肥方案F')['N kg/ha'].sum().to_dict()
    parsed=parse_filex(out/'XXQL2501.TMX')
    for water,series in profile['water_nitrogen_design']['nitrogen_series'].items():
        for row in series:row['n_kg_ha']=float(doses[parsed['treatments'][row['treatment']]['MF']])
    profile['design_notes']=[
        '2025 spring only; W3/W1 by N0/N1/N2/N3; actual nitrogen totals 0/122/254/364 kg N ha-1.',
        'LAI measured sampling DAP 45/67/95/119; all SA responses are simulations, not observed targets.',
        'CUMHARVEST_DAP50 is simulated time to 50% cumulative harvested dry mass.',
        ('Treatment-specific initial conditions and soil analysis retained; contrasts remain conditional on those backgrounds.'
         if kind=='observed' else 'Common layerwise median IC and soil-analysis profile; only MI/MF differ between selected treatment factor vectors.'),
        'No parameter bounds are selected and no full Morris/Sobol experiment is launched by building these inputs.'
    ]
    write(out/'sa_outputs.json',profile)
    external=ROOT/'configs/sa'/f'eggplant_25sp_{kind}_20261029_outputs.json'
    write(external,profile)
    contract=load_output_contract(out/'sa_outputs.json',bundle_name=out.name)
    assert len(observation_names(contract))==profile['observation_count']==164
    return external


def main():
    parent=verify_manifest_integrity(SOURCE)
    source_hashes={p.name:sha(p) for p in SOURCE.iterdir() if p.is_file()}
    AUDIT.mkdir(parents=True,exist_ok=False)
    index={'date':DATE,'source_bundle':SOURCE.name,'source_manifest_sha256':parent.manifest_sha256,'bundles':{}}
    for kind in ['observed','controlled']:
        out=DEST/f'xxql2501_sa_{kind}_20261029'
        out.mkdir(parents=True,exist_ok=False)
        for p in SOURCE.iterdir():
            if p.is_file() and (p.suffix.upper() in ['.TMX','.TMA','.TMT','.SOL','.WTH','.CUL','.ECO','.SPE'] or p.name in
                ['DSSBatch.v48','treatment_metadata.csv','irrigation_event_audit.csv','fertilizer_event_audit.csv','harvest_schedule_audit.csv']):
                shutil.copy2(p,out/p.name)
        changes={}
        if kind=='controlled':
            text=(out/'XXQL2501.TMX').read_text(encoding='utf-8')
            profile=pooled_median_initial_profile(SOURCE/'XXQL2501.TMX',TRT)
            for level in sorted(parse_filex(SOURCE/'XXQL2501.TMX')['initial_conditions']):
                text=replace_initial_profile(text,level,profile)
            section,pooled=common_analysis(SOURCE/'XXQL2501.TMX')
            text=replace_section(text,'*SOIL ANALYSIS',section)
            for tn in TRT:text=replace_treatment_factors(text,tn,{'IC':2,'SA':2})
            (out/'XXQL2501.TMX').write_text(text,encoding='ascii')
            pooled.to_csv(out/'controlled_soil_analysis.csv',index=False)
            pd.DataFrame(profile).to_csv(out/'controlled_initial_profile.csv',index=False)
            changes={'IC':{'level':2,'aggregation':'median across 8 source treatment profiles at each layer','profile':profile},
                     'SA':{'level':2,'aggregation':'median across 8 source treatment soil-analysis values at each layer'},
                     'varying_factors':['MI','MF'],'unit_policy':'Pool existing declared units; no new unit or extraction-method conversion.'}
            factors=list(parse_filex(out/'XXQL2501.TMX')['treatments'].values())
            assert all({k:v for k,v in f.items() if k not in ['MI','MF']}=={k:v for k,v in factors[0].items() if k not in ['MI','MF']} for f in factors)
        external=profile_for(out,kind)
        summary,findings=validate_input_bundle(out,require_observations=False)
        assert not [f for f in findings if f.severity=='error'],findings
        assert set(summary['treatments'])==set(TRT)
        write(out/'source_provenance.json',{'source_bundle':str(SOURCE),'source_manifest_sha256':parent.manifest_sha256,
            'generator':str(Path(__file__).relative_to(ROOT)),'generator_sha256':sha(__file__),'transformations':changes,
            'unchanged_payloads':{name:source_hashes[name] for name in source_hashes if (out/name).is_file() and sha(out/name)==source_hashes[name]},
            'observations':'TMA/TMT copied as parent reference only; no observed-target fitting or counterfactual truth implied.'})
        (out/'README.md').write_text(f'# 2025春敏感性分析输入 {kind}\n\n源包：{SOURCE.name}。\n\n'+
            ('保留处理实测初始水分及土壤背景，作为条件情景。\n' if kind=='observed' else '8处理共用分层中位数初始水氮及土壤分析，作为受控反事实情景。\n')+
            '\n仅用于参数敏感性分析；禁止用于参数率定。TMA/TMT是源包参考观测，不作为本情景拟合目标。\n'+
            '\n沿用源包的实验室测定方法代码和深层先验，方法代码待核实的限制依旧。\n',encoding='utf-8')
        manifest={'bundle_id':out.name,'created':DATE,'scenario_type':f'2025_spring_{kind}_sensitivity_input',
            'intended_use':'genetic_parameter_sensitivity_analysis_only','prohibited_use':['parameter_calibration','validation_against_observed_treatment_initial_conditions'],
            'derived_from_bundle':SOURCE.name,'source_manifest_sha256':parent.manifest_sha256,
            'treatments':list(TRT),'controlled_factors':changes,'findings':findings_as_dicts(findings),
            'files':[{'name':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(out.iterdir()) if p.is_file()]}
        write(out/'input_manifest.json',manifest)
        verify_manifest_integrity(out)
        try:verify_calibrated_input_bundle(out)
        except InputUseProhibitedError:pass
        else:raise AssertionError('SA-only calibration prohibition was not enforced')
        # Real forward-model run and SA response extraction, preserving native evidence.
        qa=ROOT/'workspace/qa'/out.name;qa.mkdir(parents=True,exist_ok=False)
        for name in ['TMGRO048.CUL','TMGRO048.ECO','TMGRO048.SPE']:
            shutil.copy2(out/name,qa/name)
        (qa/'empty_params.csv').write_text('name,value\n',encoding='ascii')
        old_keep=os.environ.get('DSSAT_KEEP_RUNS');os.environ['DSSAT_KEEP_RUNS']='1'
        try:compute_indicators(str(qa),str(out/'DSSBatch.v48'),'TM0008',str(qa/'empty_params.csv'),
            str(qa/'sa_outputs.dat'),input_dir=str(out),output_profile=str(out/'sa_outputs.json'),failure_artifact_dir=str(qa/'failure'))
        finally:
            if old_keep is None:os.environ.pop('DSSAT_KEEP_RUNS',None)
            else:os.environ['DSSAT_KEEP_RUNS']=old_keep
        values=np.loadtxt(qa/'sa_outputs.dat',ndmin=1)
        contract=load_output_contract(out/'sa_outputs.json');names=observation_names(contract)
        pd.DataFrame({'name':names,'value':values}).to_csv(qa/'sa_response_check.csv',index=False)
        missing=[n for n,v in zip(names,values) if not np.isfinite(v) or v==-99]
        assert len(values)==164 and not missing,f'Unusable SA outputs: {missing}'
        runs=list((qa/'_sa_tmp_runs').iterdir());assert len(runs)==1
        # The SA runner copies back only response outputs. Run the exact frozen
        # payload directly as well to retain Summary/SoilNi native readback.
        native=qa/'native_readback';native.mkdir()
        for payload in out.iterdir():
            if payload.is_file():shutil.copy2(payload,native/payload.name)
        proc=subprocess.run(['C:/DSSAT48/DSCSM048.EXE','CRGRO048','B','DSSBatch.v48'],cwd=native,capture_output=True,text=True,timeout=180)
        (native/'console.txt').write_text(proc.stdout+'\n'+proc.stderr,encoding='utf-8')
        assert proc.returncode==0
        assert not (native/'ERROR.OUT').exists() or not (native/'ERROR.OUT').read_text(errors='replace').strip()
        summ=read_summary(native/'Summary.OUT')
        assert set(summ.TRNO.astype(int))==set(TRT) and (summ.HDAT>=2025194).all()
        nitrogen=read_daily_output(native/'SoilNi.OUT')
        parsed=parse_filex(out/'XXQL2501.TMX');soil=pd.read_csv(out/'controlled_initial_profile.csv') if kind=='controlled' else None
        from tools.soil.build_dual_plot_soil_profiles_20260917 import PHYSICAL_LAYERS
        inventory=[]
        for runno,tn in enumerate(TRT,1):
            previous=0;expected_nh4=expected_no3=0
            for row,physical in zip(parsed['initial_conditions'][parsed['treatments'][tn]['IC']],PHYSICAL_LAYERS):
                mass=(row['depth']-previous)*physical[6]*.1;previous=row['depth']
                expected_nh4+=mass*row['snh4'];expected_no3+=mass*row['sno3']
            native_n=nitrogen[runno][min(nitrogen[runno])]
            assert np.isclose(native_n['NITD'],expected_no3,atol=.1,rtol=.02)
            assert np.isclose(native_n['NHTD'],expected_nh4,atol=.1,rtol=.02)
            inventory.append({'trno':tn,'expected_no3':expected_no3,'read_no3':native_n['NITD'],'expected_nh4':expected_nh4,'read_nh4':native_n['NHTD']})
        proof={'bundle':out.name,'manifest_sha256':sha(out/'input_manifest.json'),'native_directory':str(native),
            'treatments_completed':8,'terminal_date':2025194,'SA_responses':164,'nonfinite_or_missing':missing,
            'calibration_use_prohibited':True,'initial_N_readback':inventory,'full_SA_launched':False}
        write(AUDIT/f'{kind}_preflight.json',proof)
        index['bundles'][kind]={'path':str(out),'manifest_sha256':sha(out/'input_manifest.json'),'output_profile':str(external),'preflight':str(AUDIT/f'{kind}_preflight.json')}
        print(json.dumps(proof,ensure_ascii=False),flush=True)
    assert source_hashes=={p.name:sha(p) for p in SOURCE.iterdir() if p.is_file()}
    write(ROOT/'configs/sa/current_2025_spring_bundles.json',index)
    write(AUDIT/'build_summary.json',index)


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
