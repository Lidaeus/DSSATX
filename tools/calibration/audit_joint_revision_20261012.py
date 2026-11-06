"""Isolated mechanism checks; never launches PEST or changes sealed inputs."""
from __future__ import annotations
import concurrent.futures as cf
import hashlib
import json
from pathlib import Path
import sys
import traceback
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration import water_n_joint as model
from src.calibration import single_season_n as native
from src.common.param_registry import PHYSICAL_BOUNDS

RUN = ROOT/'workspace/runs/eggplant_26sp_n012_rmse_joint65_200x5_20261012'
CONFIG = ROOT/'configs/runs'/RUN.name
OUT = ROOT/'workspace/audits/joint_revision_truth_20261012'

def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def cases():
    result = [('baseline', {})]
    for fl in [45,55,65,75,100,150,250,380]:
        for sen in [.188894,.28]:
            if fl==380 and sen==.188894: continue
            result.append((f'fl{fl}_sen{sen:.3f}', {'FL-LF':fl,'SENPOR_LATE':sen}))
    result += [('sen035',{'SENPOR_LATE':.35})]
    for name, value in [('PROLFG',.27),('PROSTG',.15),('PRORTG',.124),('PROSHI',.19),('PROSHG',.20),('RTNO3',.003),('RTNO3',.006),('RWUMX',.006),('RWUMX',.009),('SLAVR',135),('FRSTMF',.80),('FRSTMF',.85)]:
        result.append((f'{name.lower()}_{value:.4f}',{name:value}))
    # Mechanism combinations are diagnostics, not validation-season optimization.
    for rt in [.003,.006,.010329]:
        for rw in [.006,.009,.0120002]:
            result.append((f'combo_n{rt:.3f}_w{rw:.3f}', {'FL-LF':65,'SENPOR_LATE':.28,'RTNO3':rt,'RWUMX':rw}))
    for fl in [180,220,300]:
        for sen in [.15,.20,.25]:
            result.append((f'refine_fl{fl}_s{sen:.2f}',{'FL-LF':fl,'SENPOR_LATE':sen}))
    for fl in [220,300]:
        for rw in [.009,.0105,.0120002]:
            for rt in [.003,.006]:
                result.append((f'refine_fl{fl}_w{rw:.4f}_n{rt:.3f}',{'FL-LF':fl,'SENPOR_LATE':.20,'RWUMX':rw,'RTNO3':rt}))
    for name,value in [('NMOBMX',.08),('NVSMOB',.25),('PROLFF',.24),('PROSTF',.085)]:
        result.append((f'{name.lower()}_{value:.4f}',{name:value}))
    seed={'FL-LF':220,'SENPOR_LATE':.20,'RTNO3':.006,'RWUMX':.0120002,
          'FRSTMF':.85,'FRLFF':.14,'NMOBMX':.09,'NVSMOB':.30,'PROLFF':.235,'PROSTF':.08}
    result += [('seed_yield',seed),('seed_water',seed|{'RWUMX':.0105}),
               ('seed_broad',seed|{'FL-LF':300}),('slavr145',{'SLAVR':145}),
               ('slavr185',{'SLAVR':185}),('frstmf090_frlff008',{'FRSTMF':.90,'FRLFF':.08})]
    for fl in [55,75]:
        result.append((f'safe_fl{fl}',{'FL-LF':fl,'SENPOR_LATE':.28,'FRSTMF':.85,'FRLFF':.14}))
    return result

def one(case, design, obs, base):
    name, overrides=case
    folder=OUT/'cases'/name
    folder.mkdir(parents=True,exist_ok=True)
    values=base|overrides
    for par,v in values.items():
        if par in PHYSICAL_BOUNDS:
            lo,hi=PHYSICAL_BOUNDS[par]
            if not lo<=v<=hi: raise ValueError((par,v,lo,hi))
    status={'case':name,'overrides':overrides,'expected_targets':len(obs)}
    try:
        ds=next(x for x in design['datasets'] if x['roles'].get('calibration'))
        work=folder/'_model'
        if not (folder/'complete.json').exists():
            model.simulate(work,ds,ds['roles']['calibration'],values,executable_sha256=design['dssat_executable_sha256'])
            model.audit_injection(work,values,design['active_parameters'] + (["PROSHG"] if 'PROSHG' in overrides else []))
        try:
            comp=model.extract_observations(work,obs)
        except Exception as error:
            status['full_extract_error']=str(error)
            chunks=[]; errors={}
            for family,q in obs.groupby('family',sort=False):
                try: chunks.append(model.extract_observations(work,q))
                except Exception as e: errors[family]=str(e)
            comp=pd.concat(chunks,ignore_index=True) if chunks else pd.DataFrame()
            status['family_errors']=errors
        if len(comp):
            comp.to_csv(folder/'comparison.csv',index=False)
            metrics=[]
            for family,q in comp.groupby('family',sort=False):
                residual=q.simulated-q.observed; scale=float(q.fit_scale.iloc[0])
                metrics.append({'case':name,'family':family,'n':len(q),'rmse':float(np.sqrt(np.mean(residual**2))),
                    'nrmse_pct':100*float(np.sqrt(np.mean(residual**2)))/scale,'bias':float(residual.mean()),
                    'old_phi':float(np.sum((residual*q.final_weight)**2))})
            pd.DataFrame(metrics).to_csv(folder/'metrics.csv',index=False)
        status.update(matched_targets=len(comp),complete=len(comp)==len(obs),native_run=True)
        gro=native.read_native(work/'PlantGro.OUT').reset_index()
        fresh=native.read_native(work/'FreshWt.OUT').reset_index()
        diag=[]
        for tr,q in gro.groupby('trno'):
            end=q.iloc[-1]; before=q[q.date.eq('2026-06-29')]; after=q[q.date.eq('2026-07-17')]
            diag.append({'case':name,'trno':int(tr),'last_date':end.date,'last_dap':end.DAP,
                'lai_peak':float(q.LAID.max()),'lai_jun29':float(before.LAID.iloc[0]) if len(before) else None,
                'lai_jul17':float(after.LAID.iloc[0]) if len(after) else None,
                'leaf_jun29':float(before.LWAD.iloc[0]) if len(before) else None,'leaf_jul17':float(after.LWAD.iloc[0]) if len(after) else None,
                'mean_NSTD':float(q.NSTD.mean()) if 'NSTD' in q else None,
                'max_NSTD':float(q.NSTD.max()) if 'NSTD' in q else None})
        pd.DataFrame(diag).to_csv(folder/'daily_summary.csv',index=False)
        pairs=comp[(comp.variable=='CHFPW') & (comp.date=='2026-07-17')].set_index('trno') if len(comp) else pd.DataFrame()
        contrast=[]
        for label,high,low in [('W2_N0',11,12),('W3_N0',9,12),('W2_N1',8,10),('W3_N1',7,10),('W2_N2',5,6),('W3_N2',4,6),('N21_W1',6,10),('N21_W2',5,8),('N21_W3',4,7)]:
            if high in pairs.index and low in pairs.index:
                contrast.append({'case':name,'contrast':label,'observed':float(pairs.loc[high,'observed']-pairs.loc[low,'observed']),
                    'simulated':float(pairs.loc[high,'simulated']-pairs.loc[low,'simulated'])})
        pd.DataFrame(contrast).to_csv(folder/'contrasts.csv',index=False)
        # Numeric native comparisons, unaffected by timestamps or output banners.
        digests={}
        for file in ['PlantGro','PlantN','FreshWt','SoilWat']:
            frame=native.read_native(work/(file+'.OUT'))
            digests[file]=hashlib.sha256(frame.to_csv(float_format='%.12g').encode()).hexdigest()
        status['native_numeric_sha256']=digests
        dump(folder/'complete.json',status)
    except Exception as e:
        status.update(complete=False,native_run=False,error=str(e),traceback=traceback.format_exc())
        dump(folder/'failure.json',status)
    print(json.dumps({k:status.get(k) for k in ['case','complete','matched_targets','error']},ensure_ascii=False),flush=True)
    return status

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    design=json.loads((CONFIG/'design.json').read_text(encoding='utf-8'))
    obs=pd.read_csv(CONFIG/'calibration_observations.csv').fillna('')
    frame=pd.read_csv(RUN/'best_calibration_parameters.csv')
    base=dict(zip(frame.name,frame.value))
    protected={p: native.sha(ROOT/p) for p in design['runtime_hashes']}
    tasks=cases();dump(OUT/'case_design.json',dict(cases=[dict(case=n,overrides=v) for n,v in tasks],binary_sha256=design['dssat_executable_sha256'],calibration_only=True))
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda task:one(task,design,obs,base),tasks))
    for file,key in [('metrics.csv','grid_metrics.csv'),('daily_summary.csv','grid_daily_summary.csv'),('contrasts.csv','grid_contrasts.csv')]:
        frames=[pd.read_csv(OUT/'cases'/name/file) for name,_ in tasks if (OUT/'cases'/name/file).exists()]
        pd.concat(frames,ignore_index=True).to_csv(OUT/key,index=False)
    pd.DataFrame([{k:v for k,v in r.items() if k not in ['overrides','traceback','native_numeric_sha256']} for r in results]).to_csv(OUT/'grid_status.csv',index=False)
    changes=[p for p,digest in protected.items() if native.sha(ROOT/p)!=digest]
    dump(OUT/'audit_summary.json',dict(case_count=len(tasks),complete_cases=sum(x.get('complete',False) for x in results),sealed_runtime_changes=changes,results=results))
    if changes: raise RuntimeError('Sealed files changed')

if __name__=='__main__':main()
