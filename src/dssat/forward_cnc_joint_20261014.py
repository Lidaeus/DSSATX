"""Isolated writer and explicit custom DSSAT execution; no executable fallback."""
from pathlib import Path
import argparse
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.dssat import run_dssat as runner
from src.dssat.forward_joint import inject_phosphorus
from src.dssat.forward_water_n import inject_environment
from src.calibration import cnc_joint_20261014 as model

def main():
    p=argparse.ArgumentParser();p.add_argument('--param-csv',required=True);p.add_argument('--batch',default='DSSBatch.v48');a=p.parse_args()
    work=Path.cwd();engine=work/'DSCSM048.EXE'
    if model.legacy.sha(engine)!=model.ENGINE_SHA:raise ValueError('Custom engine hash mismatch before native execution')
    runner.PARAM_CSV=a.param_csv;runner.BATCH_FILE=a.batch
    values=runner._read_param_dict(a.param_csv);model.check_relations(values)
    runner.update_cul_file(param_csv_path=a.param_csv,target_cultivar='TM0008')
    ecotype=runner._infer_ecotype_from_cul(runner.CUL_FILE,'TM0008') or 'TM0001'
    runner.update_eco_file(param_csv_path=a.param_csv,target_ecotype=ecotype)
    runner.update_spe_file(param_csv_path=a.param_csv)
    inject_phosphorus(runner.SPE_FILE,values);inject_environment(work,values)
    actual={k:v[0] for k,v in model.legacy.read_injected_parameters(work).items()}
    actual.update({k:v[0] for k,v in model.inject_cnc_fields(work,values).items()})
    model.check_relations(actual)
    # Remove all prior outputs before calling the executable. Keep every new native balance output.
    for file in work.glob('*.OUT'):file.unlink()
    command=[str(engine),'CRGRO048','B',a.batch];started=time.time()
    cp=subprocess.run(command,cwd=work,input='\n'*8,capture_output=True,text=True,errors='replace',timeout=160)
    (work/'native_stdout.log').write_text(cp.stdout+'\n'+cp.stderr,encoding='utf-8')
    if cp.returncode:raise RuntimeError(f'Custom DSSAT exit={cp.returncode}')
    error=work/'ERROR.OUT'
    if error.exists() and error.read_text(errors='replace').strip():raise RuntimeError('Native ERROR.OUT produced')
    warnings=(work/'Warning.OUT').read_text(errors='replace') if (work/'Warning.OUT').exists() else ''
    if 'Invalid CNC_' in warnings or 'CNC_A <= CNC_NC_INF' in warnings:raise RuntimeError('Native CNC default fallback detected')
    for name in ['Evaluate.OUT','FreshWt.OUT','PlantGro.OUT','PlantN.OUT','SoilWat.OUT','SoilNi.OUT','PlantNBal.OUT','SoilNiBal.OUT']:
        file=work/name
        if not file.exists() or not file.stat().st_size or file.stat().st_mtime<started-2:raise RuntimeError('Missing or stale native output: '+name)
    model.legacy.write_json(work/'custom_engine_execution.json',dict(engine_path=str(engine),engine_sha256=model.legacy.sha(engine),
       command=command,elapsed_seconds=time.time()-started,cnc_readback={k:v[0] for k,v in model.read_cnc_fields(work).items()},
       source_template_sha256=model.legacy.sha(work/'TMGRO048.SPE.base'),official_fallback_allowed=False))
    print('Custom DSSAT native run complete; explicit hash-pinned engine; balances retained',flush=True)

if __name__=='__main__':main()
