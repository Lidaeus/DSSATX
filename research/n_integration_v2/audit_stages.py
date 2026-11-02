"""Independent checks of exported stage ledgers; preserves native residuals."""
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd
from prepare_readiness import numeric_records,digest

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
 p.add_argument('--prefix',default='verified');p.add_argument('--out-name',default='integration_audit');a=p.parse_args()
 root=a.root.resolve();out=root/a.out_name;out.mkdir(exist_ok=False)
 reference=Path(r'D:/Tomato_Cal/subprojects/critical_n/reports/p0b_trace_4864_20261102/final_run/trace_off')
 mode0=root/f'{a.prefix}_all/stage0'
 comparison={}
 for file in sorted(reference.glob('*.OUT')):
  try:expected=numeric_records(file);actual=numeric_records(mode0/file.name)
  except ValueError as e:
   if str(e).startswith('No comparable native data rows:'):continue
   raise
  comparison[file.name]={'rows':len(expected),'exact':expected==actual}
 assert all(v['exact'] for v in comparison.values())
 rows=[];detail=[]
 cases=[(f'stage{i}',root/f'{a.prefix}_all/stage{i}') for i in range(1,6)]
 cases += [('R1',root/f'{a.prefix}_r1/stage3'),('feedback_R0',root/f'{a.prefix}_feedback_r0/stage5')]
 for label,folder in cases:
  d=pd.read_csv(folder/'PlantNIntegration.csv',float_precision='round_trip')
  assert len(d)==1512 and len(d.columns)==55 and np.isfinite(d.to_numpy()).all()
  assert d.Q_residual.abs().max()<1e-9
  for species,capacity in [('QNO3',.003),('QNH4',.0001)]:
   for organ in ['leaf','stem','root']:
    assert (d[f'{species}_{organ}']>=0).all()
    assert (d[f'{species}_{organ}']<=capacity*d[f'carrier_{organ}']+1e-9).all()
  assert np.allclose(d.QNO3,d[['QNO3_leaf','QNO3_stem','QNO3_root']].sum(axis=1),atol=1e-12,rtol=0)
  assert np.allclose(d.QNH4,d[['QNH4_leaf','QNH4_stem','QNH4_root']].sum(axis=1),atol=1e-12,rtol=0)
  per=[]
  for run,g in d.groupby('run'):
   last=g.iloc[-1]
   q=last.QNO3+last.QNH4
   balance=q+g.inorg_litter.sum()-(g.U_NO3+g.U_NH4).sum()+(g.A_NO3+g.A_NH4).sum()
   assert abs(balance)<1e-9
   assert abs(last.soil_litter_returned_kg_ha/10+last.pending_litter-g.inorg_litter.sum())<1e-9
   per.append({'case':label,'run':run,'Q_end_gN_m2':q,'Q_season_residual_gN_m2':balance,
    'uptake_kgN_ha':float((g.U_NO3+g.U_NH4).sum()*10),
    'assimilation_kgN_ha':float((g.A_NO3+g.A_NH4).sum()*10),
    'organic_N_residual_kgN_ha':float(g.legacy_organic_N_residual.sum()*10),
    'growth_C_overrun_gCH2O_m2':float(g.legacy_growth_C_overrun.sum())})
  detail+=per
  if int(d.stage.iloc[0])>=4:
   for organ in ['leaf','stem']:
    w=np.maximum(1,(d.W_leaf+d.W_stem)/100)
    A,B=(.042,.30) if organ=='leaf' else (.025,.35)
    assert np.allclose(d[f'{organ}_crit'],A*w**(-B),rtol=1e-12,atol=1e-14)
    assert np.allclose(d[f'{organ}_min'],.4*d[f'{organ}_crit'],rtol=1e-12,atol=1e-14)
    assert np.allclose(d[f'{organ}_max'],1.25*d[f'{organ}_crit'],rtol=1e-12,atol=1e-14)
  layer=folder/'LayerNIntegration.csv'
  if layer.exists():
   l=pd.read_csv(layer,float_precision='round_trip')
   assert np.isfinite(l.to_numpy()).all()
   assert (l.NO3_final_gN_m2>=0).all() and (l.NH4_final_gN_m2>=0).all()
   assert (l.NO3_final_gN_m2<=l.NO3_candidate_gN_m2+1e-12).all()
   assert (l.NO3_final_gN_m2<=l.membrane_potential_gN_m2+1e-12).all()
   if label=='R1':assert (l.NO3_final_gN_m2<=l.MF_candidate_gN_m2+1e-12).all()
   aggregates=l.groupby(['run','yrdoy'])[['NO3_final_gN_m2','NH4_final_gN_m2']].sum()
   assert np.allclose(aggregates.NO3_final_gN_m2,d.set_index(['run','yrdoy']).U_NO3,atol=1e-12,rtol=0)
   assert np.allclose(aggregates.NH4_final_gN_m2,d.set_index(['run','yrdoy']).U_NH4,atol=1e-12,rtol=0)
  rows.append({'case':label,'days':len(d),'Q_residual_max_gN_m2':float(d.Q_residual.abs().max()),
   'QNO3_max_gN_m2':float(d.QNO3.max()),'QNH4_max_gN_m2':float(d.QNH4.max()),
   'raw_organic_N_residual_max_abs_gN_m2':float(d.legacy_organic_N_residual.abs().max()),
   'raw_growth_C_overrun_max_gCH2O_m2':float(d.legacy_growth_C_overrun.max()),
   'leaf_actual_above_max_days':int((d.Corg_leaf>d.leaf_max).sum()) if int(d.stage.iloc[0])>=4 else None,
   'leaf_actual_below_min_days':int((d.Corg_leaf<d.leaf_min).sum()) if int(d.stage.iloc[0])>=4 else None,
   'ledger_sha256':digest(folder/'PlantNIntegration.csv')})
 pd.DataFrame(rows).to_csv(out/'stage_checks.csv',index=False)
 pd.DataFrame(detail).to_csv(out/'per_treatment_ledgers.csv',index=False)
 report={'passed':True,'official_mode_numeric_comparisons':comparison,
   'new_incremental_N_ledgers_passed':True,'native_organic_and_C_residuals_not_cancelled':True,
   'cases':rows,'status':'engineering_integration_only_not_calibrated','v15_adopted':False}
 (out/'audit_receipt.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'passed':True,'official_numeric_files':len(comparison),'new_cases':len(cases),'growth_days':len(cases)*1512},ensure_ascii=False))
if __name__=='__main__':main()
