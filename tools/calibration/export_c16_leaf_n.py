"""Read-only extraction of the dated leaf-N workbook for C16 diagnostics."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pandas as pd
import openpyxl

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.reporting.export_paper_data import export_bundle
from src.reporting.figure_data import VARIABLE_SPECS

OUT=ROOT/'paper/06_C16_Revision_20260920'
CASE='full_gen_13trt_tb1_80_95_150x6'
source=next((ROOT/'data/user/ref').rglob('2025年春季茄子植株样氮磷钾测定.xlsx'))
wb=openpyxl.load_workbook(source,read_only=True,data_only=True)
rows=list(wb['Sheet1'].values)
raw=pd.DataFrame([r[:9] for r in rows[1:] if r[1]=='叶'],columns=['date','organ','plot','rep','n_mg_g','p_mg_g','k_mg_g','water','nitrogen'])
raw['n_pct']=pd.to_numeric(raw.n_mg_g)/10
assert not raw.duplicated(['date','plot','rep']).any()
agg=raw.groupby(['date','plot','water','nitrogen']).n_pct.agg(['mean','std','count']).reset_index()
assert len(agg)==9 and len(raw)==27
raw.to_csv(OUT/'data/leaf_n_raw_readonly_extract.csv',index=False)
agg.to_csv(OUT/'data/leaf_n_repeat_summary.csv',index=False)
trajectory=pd.read_csv(OUT/'paper_data/25SP/simulation_trajectory.csv')
metadata=pd.read_csv(OUT/'data/25SP_treatment_metadata.csv').set_index('treatment')
# The workbook calls the control CK/CK; retain that designation instead of
# translating its nitrogen category to the N2 label used in the yield metadata.
metadata.loc[14,'nitrogen_level']='CK'
metadata.loc[14,'treatment_label']='TN14 (CK)'
metadata.reset_index().to_csv(OUT/'data/leaf_n_treatment_metadata.csv',index=False)
records=[]
for r in agg.to_dict('records'):
    day=pd.Timestamp(r['date']); doy=day.dayofyear; code=(day.year%100)*1000+doy
    tn=int(r['plot'])
    assert metadata.loc[tn,'water_level']==r['water'] and metadata.loc[tn,'nitrogen_level']==r['nitrogen']
    sim=trajectory[(trajectory.variable=='LN%D')&(trajectory.treatment==tn)&(trajectory.date_code==code)]
    assert len(sim)==1
    spec=VARIABLE_SPECS['LN%D']; node=sim.iloc[0]
    records.append(dict(run_id=CASE,data_status='legacy_unvalidated',dataset_role='diagnostic',variable='LN%D',
        variable_label=spec['label'],unit=spec['unit'],treatment=str(tn),time=node.time,time_label='Days after planting',
        observed=r['mean'],simulated=node.simulated,source_file=str(source),date_code=code,year=day.year,doy=doy,
        dap=node.time,harvest_number=np.nan,observed_sd=r['std'],observed_se=np.nan,n_rep=r['count'],season_id='25SP'))
comp=pd.DataFrame(records)
comp.to_csv(OUT/'data/leaf_n_comparison_input.csv',index=False)
manifest=export_bundle(run_id=CASE,out_dir=OUT/'paper_data/leaf_n',comparison_csv=OUT/'data/leaf_n_comparison_input.csv',
    trajectory_run_dir=ROOT/'workspace/runs'/f'{CASE}_20260920/c16_deterministic/_seasons/25SP',
    treatment_metadata_csv=OUT/'data/leaf_n_treatment_metadata.csv',allow_unvalidated_demo=True)
m=json.loads(manifest.read_text(encoding='utf-8'))
m['sources'].append(dict(path=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
m['replicate_interpretation']='Three records labelled repeat per plot, independence not established; SD retained; no inferential SE/error bars.'
m['control_label']='Raw workbook TN14 is CK/CK; the leaf figure retains CK rather than assigning N2.'
manifest.write_text(json.dumps(m,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(f'Leaf N: {len(comp)} plot means from {len(raw)} records; sample date {day.date()}; exact simulated dates matched.')
