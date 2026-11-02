"""Exercise real-engine default-off behavior and fail-fast configuration guards."""
from pathlib import Path
import argparse,os,subprocess,json,shutil
from run_stages import ENGINEERING
from prepare_readiness import redirect_profile,numeric_records,COMPARE_FILES,digest
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--exe',type=Path,required=True);a=p.parse_args()
 out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);exe=a.exe.resolve()
 frozen=Path(r'D:/Tomato_Cal/subprojects/critical_n/reports/n_integration_v2_readiness_20261102/baseline_verified')
 cases={'default_off':None,'missing_parameters':{'ni_stage':5,'root_mode':2},
  'invalid_band':{'ni_stage':5,'root_mode':2,**ENGINEERING,'min_ratio':1.1},'unknown_field':{'ni_stage':1,'unknown_parameter':5},
  'missing_explicit_file':'missing'}
 receipt={'binary_sha256':digest(exe),'cases':{}}
 for name,cfg in cases.items():
  run=out/name;shutil.copytree(frozen/'inputs_26SP',run);redirect_profile(run/'DSSATPRO.v48',run)
  env=os.environ.copy();env.pop('DSSAT_N_CONFIG',None);env['DSSAT_P0_TRACE']='0'
  if isinstance(cfg,dict):(run/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v}\n' for k,v in cfg.items())+'/\n',encoding='ascii')
  if cfg=='missing':env['DSSAT_N_CONFIG']=str(run/'does_not_exist.nml')
  r=subprocess.run([str(exe),'B','DSSBatch.v48'],cwd=run,env=env,capture_output=True,timeout=300)
  (run/'stdout.txt').write_bytes(r.stdout);(run/'stderr.txt').write_bytes(r.stderr)
  if name=='default_off':
   assert r.returncode==0 and not (run/'PlantNIntegration.csv').exists()
   checks={n:numeric_records(run/n)==numeric_records(frozen/'reference_26SP'/n) for n in COMPARE_FILES}
   assert all(checks.values());receipt['cases'][name]={'passed':True,'official_outputs_exact':checks}
  else:
   assert r.returncode!=0 and b'NI:' in r.stderr,(name,r.returncode,r.stderr[-600:])
   receipt['cases'][name]={'passed':True,'rejected':True,'returncode':r.returncode,'reason':r.stderr.decode(errors='replace')[:400]}
 receipt['passed']=True
 (out/'configuration_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('CONFIGURATION_CHECKS_PASSED=5')
if __name__=='__main__':main()
