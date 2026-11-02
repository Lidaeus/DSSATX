"""Isolated engineering integration smoke runs. No calibration or approved biological defaults."""
from pathlib import Path
import argparse, json, os, shutil, subprocess, re
from prepare_readiness import digest,manifest,redirect_profile,numeric_records,COMPARE_FILES
import pandas as pd

ENGINEERING={
 'q_no3_max':.003,'q_nh4_max':.0001,
 'assim_no3_v':.003,'assim_nh4_v':.006,'assim_no3_k':.001,'assim_nh4_k':.00005,
 'root_v':.0002,'root_k':10.,'diffusion_k':.005,'pool_beta':1.,
 'leaf_a':.042,'leaf_b':.30,'stem_a':.025,'stem_b':.35,
 'min_ratio':.40,'max_ratio':1.25,'photo_floor':.05,'photo_gamma':1.,'growth_tau':2.,
}
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--out',type=Path,required=True);p.add_argument('--exe',type=Path,required=True)
 p.add_argument('--stages',type=int,nargs='+',default=[0,1,2,3,4,5]);p.add_argument('--root-mode',type=int,default=2)
 a=p.parse_args();root=a.out.resolve();root.mkdir(parents=True,exist_ok=False)
 frozen=Path(r'D:/Tomato_Cal/subprojects/critical_n/reports/n_integration_v2_readiness_20261102/baseline_verified')
 protection=json.loads((frozen/'readiness_receipt.json').read_text(encoding='utf-8'))['protected_executables_before']
 assert all(digest(Path(n))==h for n,h in protection.items())
 (root/'bin').mkdir();exe=root/'bin/dscsm048_nintegration.exe';shutil.copy2(a.exe,exe)
 receipt={'parameter_role':'ENGINEERING_DIAGNOSTIC_ONLY_NOT_CALIBRATED_NOT_RECOMMENDED_FOR_PREDICTION',
  'engineering_values':ENGINEERING,'v15_borrowing':False,'fruit_N_design':'official unchanged, no dilution curve',
  'legacy_bugs':'recorded and deferred by user; do not suppress their residuals',
  'binary':{'path':str(exe),'sha256':digest(exe)},'runs':{},'protected_before':protection}
 try:
  for stage in a.stages:
   run=root/f'stage{stage}';shutil.copytree(frozen/'inputs_26SP',run);redirect_profile(run/'DSSATPRO.v48',run)
   cfg={'ni_stage':stage,'root_mode':a.root_mode if stage>=3 else 0,**ENGINEERING}
   (run/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v}\n' for k,v in cfg.items())+'/\n',encoding='ascii')
   before=manifest(run);env=os.environ.copy();env['DSSAT_P0_TRACE']='0';env.pop('DSSAT_N_CONFIG',None)
   r=subprocess.run([str(exe),'B','DSSBatch.v48'],cwd=run,env=env,capture_output=True,timeout=600)
   (run/'stdout.txt').write_bytes(r.stdout);(run/'stderr.txt').write_bytes(r.stderr)
   info=(run/'INFO.OUT').read_text(errors='replace') if (run/'INFO.OUT').exists() else ''
   result={'returncode':r.returncode,'normal_end_12':bool(re.search(r'Normal end of run\s+12\b',info)),
     'input_hashes':before,'configuration':cfg}
   receipt['runs'][str(stage)]=result
   if r.returncode or not result['normal_end_12']:raise RuntimeError(f'stage {stage} failed: {r.stderr[-1000:]!r}')
   assert all(digest(run/n)==h for n,h in before.items())
   if stage==0:
    result['official_numeric_comparisons']={name:numeric_records(frozen/'reference_26SP'/name)==numeric_records(run/name) for name in COMPARE_FILES}
    assert all(result['official_numeric_comparisons'].values())
    assert not (run/'PlantNIntegration.csv').exists()
   else:
    d=pd.read_csv(run/'PlantNIntegration.csv',float_precision='round_trip')
    assert len(d)==1512 and len(d.columns)==26,(len(d),list(d.columns))
    assert d.Q_residual.abs().max()<1e-9 and d[['QNO3','QNH4','A_NO3','A_NH4']].min().min()>=0
    result['new_module']={'days':len(d),'Q_residual_max':float(d.Q_residual.abs().max()),
       'Q_NO3_max':float(d.QNO3.max()),'Q_NH4_max':float(d.QNH4.max()),
       'assimilation_total_across_treatments':float((d.A_NO3+d.A_NH4).sum()),
       'soil_return_total_kg_ha_by_run':d.groupby('run').soil_litter_returned_kg_ha.last().to_dict()}
    d.groupby('run')[['QNO3','QNH4','U_NO3','U_NH4','A_NO3','A_NH4','C_assim','inorg_litter']].agg(['sum','max','last']).to_csv(run/'engineering_summary.csv')
   print('stage',stage,'OK',flush=True)
  receipt['protected_after']={n:digest(Path(n)) for n in protection}
  assert receipt['protected_after']==protection
  receipt['passed']=True
 except Exception as e:
  receipt['passed']=False;receipt['error']=repr(e);raise
 finally:(root/'stage_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
