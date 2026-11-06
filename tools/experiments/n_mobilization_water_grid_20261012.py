"""Bounded tests of N remobilization and water-response priority, not calibration."""
from pathlib import Path
import argparse
import concurrent.futures
import itertools
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.experiments import et_environment_grid_20261012 as environment
from tools.experiments import water_n_response_grid_20261012 as base
from src.calibration import joint_n_objectives as joint

OUT=ROOT/'workspace/experiments/n_mobilization_water_grid_20261012'


def cases():
    reference=base.runner._read_param_dict(base.PARAMS)
    anchors={'original':{},'env':dict(RWUMX=.020,KEP=.90,SLDR=.80),'water':dict(RWUMX=.012,KEP=.90,SLDR=.90)}
    rows=[dict(case_id='baseline',family='original_reference',EVAPO='R',anchor='original'),
          dict(case_id='env_reference',family='environment_reference',EVAPO='R',anchor='env',**anchors['env']),
          dict(case_id='water_reference',family='water_reference',EVAPO='R',anchor='water',**anchors['water'])]
    for anchor in anchors:
        for nm,nv in itertools.product([.070,.085,.100],[.25,.35,.40]):
            rows.append(dict(case_id=f'{anchor}_nm{nm:.3f}_nv{nv:.2f}',family='NMOBMX_NVSMOB',EVAPO='R',anchor=anchor,
                **anchors[anchor],NMOBMX=nm,NVSMOB=nv,gene_overrides=dict(NMOBMX=nm,NVSMOB=nv)))
        for key,value in [('NMOBMX',.085),('NVSMOB',.35)]:
            overrides={key:value}
            rows.append(dict(case_id=f'{anchor}_only_{key}',family='single_mobilization_probe',EVAPO='R',anchor=anchor,
                **anchors[anchor],**overrides,gene_overrides=overrides))
    for refill in [.20,.35]:
        overrides=dict(NMOBMX=.100,NVSMOB=.35,NRCVR=refill)
        rows.append(dict(case_id=f'env_refill_{refill:.2f}',family='NRCVR_refill_probe',EVAPO='R',anchor='env',
            **anchors['env'],**overrides,gene_overrides=overrides))
    return rows


def worker(case,season):
    environment.OUT=OUT;base.OUT=OUT
    return environment.worker(case,season)


def execute(pair):
    case,season=pair;work=OUT/'cases'/case/season;work.mkdir(parents=True,exist_ok=True)
    with (work/'worker.log').open('w',encoding='utf-8') as log:
        result=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--worker',case,'--season',season],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    return dict(case_id=case,season_id=season,exit_code=result.returncode)


def initialize():
    if (OUT/'experiment_manifest.json').exists():return
    joint.load_design(base.CONFIG/'design.json')
    design=json.loads((base.CONFIG/'design.json').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True,exist_ok=True)
    sources=[base.PARAMS,base.CONFIG/'design.json',base.CONFIG/'calibration_observations.csv',Path(environment.__file__),Path(base.__file__),Path(__file__)]
    sources.extend(ROOT/d['bundle_path']/'input_manifest.json' for d in design['datasets'])
    sources.extend((ROOT/'workspace/audits/n_mobilization_revision_20261012/source').glob('*'))
    manifest=dict(status='authorized_bounded_proposal_support_not_formal_calibration',
        user_authorization='继续优化待审方案：保障水分响应正确，结合网格纳入环境参数；相关参数适度降低氮动员能力。',
        datasets=design['datasets'],cases=cases(),source_hashes={str(f.relative_to(ROOT)).replace('\\','/'):base.sha(f) for f in sources},
        nonwater_guard_policy='Same as ET trial: per-family max(2pp,10% baseline), nonwater/original Phi<=+10%, all exact targets required',
        ranking_policy='2026 only; 2025 retrospective external diagnostics do not select bounds',
        water_priority='Report all6 W2-W1/W3-W1 signs and amplitudes, not only4 N1/N2 contrasts; candidate with incorrect signs cannot be promoted',
        remobilization_policy='Only existing NMOBMX/NVSMOB lowered; NRCVR refill role separately probed; no soilN/organic matter/uptake scaling',
        flux_limit='Native tomato PlantN output does not expose NMINEA/WTNMOB directly; uptake/tissue pools are proxies, not direct mobilization flux',
        original_inputs_modified=False,formal_calibration_started=False)
    (OUT/'experiment_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker');parser.add_argument('--season');args=parser.parse_args()
    if args.worker:worker(args.worker,args.season);return
    initialize();m=json.loads((OUT/'experiment_manifest.json').read_text(encoding='utf-8'))
    tasks=[(case['case_id'],season) for case in m['cases'] for season in ['26SP','25SP','25FA']
        if not (OUT/'cases'/case['case_id']/season/'process_summary.csv').exists()]
    status=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for future in concurrent.futures.as_completed([pool.submit(execute,pair) for pair in tasks]):
            status.append(future.result());(OUT/'execution_status.json').write_text(json.dumps(dict(completed=len(status),expected=len(tasks),failed=sum(r['exit_code']!=0 for r in status))))
    pd=None
    import pandas as pd
    pd.DataFrame(status).to_csv(OUT/'execution_status.csv',index=False)
    for file,digest in m['source_hashes'].items():assert base.sha(ROOT/file)==digest,file
    print(json.dumps(dict(cases=len(m['cases']),season_runs=len(tasks),failed=sum(r['exit_code']!=0 for r in status),original_sources_unchanged=True)))


if __name__=='__main__':main()
