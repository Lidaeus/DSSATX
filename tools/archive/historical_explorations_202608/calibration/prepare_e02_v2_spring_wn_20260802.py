"""Prepare E02 V2 (25SP+26SP, canopy/yield/N-response, Sobol 150x4)."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
LAYER=ROOT/'data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_wnstress_fourcorner_layermeanic_v1_20260801.csv'
SOIL=ROOT/'data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_posterior_soil_wnresponse_v1_20260802.csv'
MORRIS=ROOT/'workspace/sa/supplement_tables/Table_S1_morris_sampling_space.csv'
PROPOSAL=ROOT/'data/parameter_registry/bounds_proposals/eggplant/eggplant_e02_v2_spring_wn_canopy_soil_20260802.csv'
BOUNDS_ID='eggplant_e02_v2_spring_wn_canopy_soil_20260802'
DESIGN=ROOT/'configs/runs/eggplant_e02_v2_spring_wn_canopy_soil_20260802.json'
MAPPING=ROOT/'configs/runs/e02_v2_spring_water_n_mapping_20260802.csv'
POLICY=ROOT/'configs/runs/e02_v2_canopy_yield_nresponse_policy_20260802.csv'

def make_bounds():
    d=pd.read_csv(LAYER); soil=pd.read_csv(SOIL); mor=pd.read_csv(MORRIS).set_index('parameter')
    # Preserve layermeanic active scope, but autumn offsets cannot be identified without 25FA.
    d.loc[d.name.astype(str).str.endswith('_AUT'), 'status']='fixed'
    for i in d.index[d.name.astype(str).str.endswith('_AUT')]:
        d.loc[i, 'lower'] = d.loc[i, 'init']
        d.loc[i, 'upper'] = d.loc[i, 'init']
    # Add the 32 layer soil hydraulic variables from the posterior-soil frozen proposal.
    extra=soil[soil.name.astype(str).str.startswith('SOIL_') & ~soil.name.eq('SOIL_SLPF')].copy()
    d=pd.concat([d,extra],ignore_index=True)
    # Morris ranges take precedence for all overlapping genetic parameters.
    for i,row in d.iterrows():
        name=str(row['name'])
        if name in mor.index and str(row['status']).lower() == 'active':
            lo=float(mor.loc[name,'lower_bound']); hi=float(mor.loc[name,'upper_bound'])
            d.loc[i,'lower']=lo; d.loc[i,'upper']=hi
            d.loc[i,'init']=min(max(float(row['init']),lo),hi)
            d.loc[i,'review_note']='Morris Table S1 candidate range; retained for V2 pre-calibration'
    # Release three previously fixed photoperiod/phenology safeguards locally.
    for name,lo,hi,note in [('CSDL',11.8,12.8,'Released around fixed value for V2 phenology sensitivity'),('PPSEN',0.0,0.20,'Released around fixed value for V2 phenology sensitivity'),('THRSH',7.5,9.5,'Released around fixed value for V2 phenology sensitivity')]:
        m=d.name.eq(name)
        d.loc[m,'status']='active'; d.loc[m,'lower']=lo; d.loc[m,'upper']=hi; d.loc[m,'review_note']=note
    # No autumn offsets in the active vector; they are fixed because 25FA is excluded.
    d=d.drop_duplicates('name',keep='first')
    d.to_csv(PROPOSAL,index=False)
    return int((d.status.astype(str).str.lower()=='active').sum()), d

def make_design():
    payload={
      'schema_version':1,'design_id':'eggplant_e02_v2_spring_wn_canopy_soil_20260802',
      'cultivar_identity':'TM0008','shared_parameter_scope':'V2 expanded canopy/yield/water-nitrogen plus soil hydraulic parameters',
      'observation_policy':'configs/runs/e02_v2_canopy_yield_nresponse_policy_20260802.csv',
      'group_policy':'configs/runs/t10_water_n_response_group_policy_harvestdry250_v1.csv',
      'initial_condition_policy':'layer-mean SH2O/SNH4/SNO3 FileX bundles; 25SP excludes TRNO9/TRNO14',
      'nitrogen_response_objective':{'enabled':True,'mapping_csv':'configs/runs/e02_v2_spring_water_n_mapping_20260802.csv','source_variable':'CHPDT','contrast':'ln1p_Nk_minus_ln1p_N0','response_target':'observed_shape','levels':['N1','N2','N3'],'sigma_floor':0.1,'budget_rule':'0.75 total per season; count-corrected across water levels, harvests and contrasts','response_scale':'ln1p CHPDT contrasts relative to N0','response_shape':'quadratic diagnostic; no monotonicity assumption'},
      'seasonal_parameterization':None,
      'seasons':[
       {'season_id':'25SP','experiment_code':'XXQL2501','bundle_path':'data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801','bundle_manifest_sha256':'','role':'calibration','treatments':[2,3,4,5,10,11,12,13]},
       {'season_id':'26SP','experiment_code':'XXQL2601','bundle_path':'data/user/experiments/xxql2601_layermean_ic_valid_n012_v1_20260801','bundle_manifest_sha256':'','role':'calibration','treatments':list(range(1,13))}
      ],
      'precalibration':{'purpose':'canopy + cumulative dry yield + plant nitrogen + explicit water-nitrogen response','scale':'empirical initialization/bounds proposal, not an independent prior','n_reals':150,'noptmax':4,'initial_ensemble_method':'sobol'}
    }
    for s in payload['seasons']:
        man=ROOT/s['bundle_path']/'input_manifest.json'
        if man.exists():
            import hashlib
            s['bundle_manifest_sha256']=hashlib.sha256(man.read_bytes()).hexdigest()
    DESIGN.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    base=pd.read_csv(ROOT/'configs/runs/e02_three_season_water_n_mapping_20260730.csv')
    base=base[(base.season_id.eq('25SP') & base.treatment.isin([2,3,4,5,10,11,12,13])) | (base.season_id.eq('26SP') & base.treatment.isin(range(1,13)))]
    base.to_csv(MAPPING,index=False)
    pol=pd.read_csv(ROOT/'configs/runs/e02_n_response_snam_lnam_chpdtlog_noadap_nochtd_v1.csv')
    pol.loc[pol.group.astype(str).str.upper().isin(['PDAPM','ADAPM','MDAPM','CHTDM']),'phi_role']='diagnostic_only'
    pol.to_csv(POLICY,index=False)

def main():
    n,d=make_bounds(); make_design()
    print(f'proposal={PROPOSAL} active={n} total={len(d)}')
    print(f'design={DESIGN}')
    if not (ROOT/'data/parameter_registry/bounds_frozen/eggplant'/f'{BOUNDS_ID}.csv').exists():
        subprocess.run([sys.executable,str(ROOT/'tools/freeze_bounds.py'),'--proposal',str(PROPOSAL),'--crop','eggplant','--bounds-id',BOUNDS_ID,'--notes','E02 V2 spring-only canopy/yield/N-response precalibration; Morris ranges plus layermeanic/soil hydraulic ranges; 25FA excluded','--operator','Codex'],cwd=ROOT,check=True)
if __name__=='__main__': main()
