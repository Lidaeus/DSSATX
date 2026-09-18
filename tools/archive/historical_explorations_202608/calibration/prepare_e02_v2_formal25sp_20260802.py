"""Prepare 25SP-only formal E02 V2 bounds/design after posterior audit."""
from __future__ import annotations
import json, hashlib, subprocess, sys
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]
BASE_B=ROOT/'data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v2_spring_wn_canopy_soil_20260802.csv'
POST=ROOT/'workspace/runs/e02_v2_spring_wn_canopy_soil_150x4_20260802/e02_v2_spring_wn_canopy_soil_150x4_20260802.4.par.csv'
PROPOSAL=ROOT/'data/parameter_registry/bounds_proposals/eggplant/eggplant_e02_v2_formal25sp_nreleased_20260802.csv'
BOUND_ID='eggplant_e02_v2_formal25sp_nreleased_20260802'
DESIGN=ROOT/'configs/runs/eggplant_e02_v2_formal25sp_nreleased_20260802.json'
MAP=ROOT/'configs/runs/e02_v2_25sp_water_n_mapping_20260802.csv'
POLICY='configs/runs/e02_v2_canopy_yield_nresponse_policy_20260802.csv'
SRC_MAP=ROOT/'configs/runs/e02_v2_spring_water_n_mapping_20260802.csv'
def main():
 d=pd.read_csv(BASE_B); p=pd.read_csv(POST); cols={str(c).lower():c for c in p.columns}
 # Posterior-guided widening at strong boundary accumulation; preserve physical/model safeguards.
 actions={
  'NSTFAC':(0.50,1.00,'Organ-N/stress factor: 78% upper-edge; release upper bound to process-safe 1.0 and avoid weak-response lower region'),
  'NMOBMX':(0.02,0.40,'Organ-N remobilisation: 99% lower-edge; release lower bound to historical process-safe floor'),
  'LNREF':(3.0,7.0,'Leaf-N reference concentration control: allow higher N concentration response'),
  'RTNH4':(0.005,0.05,'Root ammonium uptake rate: release lower bound for N concentration identifiability'),
  'RTNO3':(0.008,0.05,'Root nitrate uptake rate: retain physical lower bound and active status'),
  'NVSMOB':(0.15,0.60,'Vegetative N mobilisation: release historical process-safe envelope'),
  'NRCVR':(0.03,0.35,'N recovery after stress: release historical process-safe envelope'),
  'CMOBMX':(0.005,0.05,'Carbon mobilisation coupled to organ-N remobilisation'),
  'SENRTE':(0.30,3.0,'Senescence rate affecting leaf-N dilution/remobilisation'),
  'SENDAY':(0.001,0.08,'Senescence daily fraction affecting organ-N retention'),
  'TO13':(20.0,27.9,'Posterior upper-edge phenology safeguard; modest release while preserving TO13<TO23'),
  'RWDTH':(0.70,1.80,'Posterior upper-edge canopy width; modest release'),
  'XFINT':(0.12,0.40,'Posterior upper-edge harvest interval; retain IPDMND safeguard'),
 }
 for i,row in d.iterrows():
  n=str(row['name'])
  if n in actions:
   lo,hi,note=actions[n]; d.loc[i,'lower']=lo; d.loc[i,'upper']=hi; d.loc[i,'init']=min(max(float(row['init']),lo),hi); d.loc[i,'review_note']=note
  elif str(row['status']).lower()=='active' and n.lower() in cols:
   x=pd.to_numeric(p[cols[n.lower()]],errors='coerce').dropna(); q05=float(x.quantile(.05)); q95=float(x.quantile(.95)); span=q95-q05
   # Narrow only clearly uninformative tails; never shrink a boundary-touching parameter here.
   if span>0 and ((x<=float(row['lower'])+0.02*(float(row['upper'])-float(row['lower']))).mean()<.05) and ((x>=float(row['upper'])-0.02*(float(row['upper'])-float(row['lower']))).mean()<.05):
    lo=max(float(row['lower']),q05-.15*span); hi=min(float(row['upper']),q95+.15*span)
    if lo<hi: d.loc[i,'lower']=lo; d.loc[i,'upper']=hi; d.loc[i,'init']=min(max(float(row['init']),lo),hi); d.loc[i,'review_note']='Posterior Q05-Q95 with 15% padding; no strong boundary accumulation'
 d.to_csv(PROPOSAL,index=False)
 m=pd.read_csv(SRC_MAP); m=m[m.season_id.eq('25SP')]; m.to_csv(MAP,index=False)
 payload={'schema_version':1,'design_id':'eggplant_e02_v2_formal25sp_nreleased_20260802','cultivar_identity':'TM0008','shared_parameter_scope':'V2 posterior-adjusted canopy/yield/N-response plus organ-N and soil parameters','observation_policy':POLICY,'group_policy':'configs/runs/t10_water_n_response_group_policy_harvestdry250_v1.csv','initial_condition_policy':'25SP layer-mean IC valid bundle; TRNO9/TRNO14 excluded','nitrogen_response_objective':{'enabled':True,'mapping_csv':'configs/runs/e02_v2_25sp_water_n_mapping_20260802.csv','source_variable':'CHPDT','contrast':'ln1p_Nk_minus_ln1p_N0','response_target':'observed_shape','levels':['N1','N2','N3'],'sigma_floor':0.1,'budget_rule':'0.75 static N_RESPONSE budget within 25SP'},'seasonal_parameterization':None,'seasons':[{'season_id':'25SP','experiment_code':'XXQL2501','bundle_path':'data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801','bundle_manifest_sha256':hashlib.sha256((ROOT/'data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801/input_manifest.json').read_bytes()).hexdigest(),'role':'calibration','treatments':[2,3,4,5,10,11,12,13]}],'formal':{'n_reals':200,'noptmax':5,'initial_ensemble_method':'sobol'}}
 payload['diagnostic_single_season']=True
 DESIGN.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 if not (ROOT/'data/parameter_registry/bounds_frozen/eggplant'/f'{BOUND_ID}.csv').exists(): subprocess.run([sys.executable,str(ROOT/'tools/freeze_bounds.py'),'--proposal',str(PROPOSAL),'--crop','eggplant','--bounds-id',BOUND_ID,'--notes','25SP-only formal bounds from V2 posterior; explicit organ-N parameter release','--operator','Codex'],cwd=ROOT,check=True)
 print('active',int(d.status.eq('active').sum()),'proposal',PROPOSAL,'design',DESIGN)
if __name__=='__main__': main()
