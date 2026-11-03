"""Frozen-pair comparisons: no recalibration, new weights or inferred metadata."""
import json
import numpy as np
import pandas as pd
from workflow import OUT,CN,dump,numeric_records,COMPARE_FILES
from run_c4_delivery import specs,PREVIOUS

metrics=[];yields=[];phys=[]
meta=pd.read_csv(CN/'n_buffer_v14/inputs/26SP/treatment_metadata.csv').rename(columns={'treatment':'trno'})
reference=pd.read_csv(OUT/'cases/delivery_C3/comparison.csv').set_index('obsnme')
for name,_,factor in specs():
    work=OUT/'cases'/name
    d=pd.read_csv(work/'comparison.csv').set_index('obsnme')
    assert len(d)==612 and d.index.equals(reference.index)
    for col in ['observed','final_weight','pest_obsval','fit_scale','family','date','trno','sample_definition']:
        assert d[col].fillna('').equals(reference[col].fillna('')),(name,col)
    if factor is not None:
        cash=pd.read_csv(work/'PlantCCash.csv')
        phys.append(dict(case=name,role='modified_radiation_diagnostic',
            unpaid_maintenance_days=int(cash.maintenance_unpaid.gt(0).sum()),
            unpaid_maintenance_total_gCH2O_m2_across_12=float(cash.maintenance_unpaid.sum())))
        continue
    for family,g in d.groupby('family'):
        obs=g.observed.to_numpy();sim=g.simulated.to_numpy();res=sim-obs
        den=np.sum((np.abs(sim-obs.mean())+np.abs(obs-obs.mean()))**2)
        metrics.append(dict(case=name,family=family,n=len(g),unit=g.unit.iloc[0],
            RMSE=float(np.sqrt(np.mean(res**2))),bias=float(np.mean(res)),
            NRMSE_percent=float(100*np.sqrt(np.mean(res**2))/obs.mean()) if obs.mean()!=0 else None,
            d_index=float(1-np.sum(res**2)/den) if den>0 else None,phi=float(g.phi_contribution.sum())))
    f=d[d.family.eq('FINAL_FRESH_YIELD')][['trno','observed','simulated']].merge(meta,on='trno',validate='one_to_one')
    f['case']=name;f['observed_t_ha']=f.observed/1000;f['simulated_t_ha']=f.simulated/1000
    yields.append(f[['case','trno','treatment_label','water_level','nitrogen_level','observed_t_ha','simulated_t_ha']])

pd.DataFrame(metrics).to_csv(OUT/'C4_field_metrics_by_family.csv',index=False)
y=pd.concat(yields);y.to_csv(OUT/'C4_final_fresh_yield.csv',index=False)
differences=[]
for (name,water),g in y.groupby(['case','water_level']):
    t=g.set_index('nitrogen_level')
    differences.append(dict(case=name,water=water,
        observed_N3_minus_N0=float(t.loc['N3','observed_t_ha']-t.loc['N0','observed_t_ha']),
        simulated_N3_minus_N0=float(t.loc['N3','simulated_t_ha']-t.loc['N0','simulated_t_ha'])))
pd.DataFrame(differences).to_csv(OUT/'C4_yield_N3_minus_N0.csv',index=False)
checks={}
for suffix,old in [('mode0','delivery_mode0'),('A','delivery_A'),('C3','delivery_combined')]:
    checks[suffix]={f:numeric_records(OUT/f'cases/delivery_{suffix}'/f)==numeric_records(PREVIOUS/'cases'/old/f)for f in COMPARE_FILES}
    assert all(checks[suffix].values()),checks[suffix]
repeat_files=list(COMPARE_FILES)+['PlantNIntegration.csv','PlantNV3.csv','PlantNRemob.csv','PlantNLuxury.csv','PlantNLeaf.csv','PlantCCash.csv','LayerNIntegration.csv','PlantABudget.csv']
checks['repeat']={f:(numeric_records(OUT/'cases/delivery_full'/f)==numeric_records(OUT/'cases/delivery_repeat'/f)
    if f in COMPARE_FILES else (OUT/'cases/delivery_full'/f).read_bytes()==(OUT/'cases/delivery_repeat'/f).read_bytes())
    for f in repeat_files}  # Native headers contain wall-clock timestamps.
assert all(checks['repeat'].values())
dump(OUT/'C4_regression_checks.json',checks)
dump(OUT/'C4_lowcarbon_summary.json',phys)
physiology=[]
for name in ['delivery_C3','delivery_stock_photo','delivery_full','delivery_sen02','delivery_nogate']:
    work=OUT/'cases'/name
    selected=[]
    for chunk in pd.read_csv(work/'P0Trace.csv',chunksize=200000,usecols=['run','yrdoy','event','key','value']):
        selected.append(chunk[chunk.event.eq('c4_grow_end')])
    state=pd.concat(selected).pivot(index=['run','yrdoy'],columns='key',values='value')
    state['whole_SLA_cm2_g']=state.AREA/state.W_leaf.clip(1e-12)
    state['SLN_g_m2_leaf']=10000*state.N_leaf/state.AREA.clip(1e-12)
    state['LAI']=state.AREA/10000
    state['leaf_N_percent']=100*state.N_leaf/state.W_leaf.clip(1e-12)
    nv=pd.read_csv(work/'PlantNV3.csv').set_index(['run','yrdoy'])
    for run,g in state.groupby('run'):
        physiology.append(dict(case=name,trno=run,days=len(g),
            mean_LAI=float(g.LAI.mean()),final_LAI=float(g.LAI.iloc[-1]),
            mean_leaf_N_percent=float(g.leaf_N_percent.mean()),min_leaf_N_percent=float(g.leaf_N_percent.min()),
            mean_SLN_g_m2_leaf=float(g.SLN_g_m2_leaf.mean()),
            min_whole_SLA_cm2_g=float(g.whole_SLA_cm2_g.min()),max_whole_SLA_cm2_g=float(g.whole_SLA_cm2_g.max()),
            min_growth_day=float(nv.loc[run,'growth_day'].min())))
pd.DataFrame(physiology).merge(meta,on='trno',validate='many_to_one').to_csv(OUT/'C4_physiology_by_treatment.csv',index=False)
print(pd.DataFrame(differences).query("water=='W2'").to_string(index=False))
print(pd.DataFrame(metrics).query("case in ['delivery_C3','delivery_full']")[['case','family','RMSE','phi']].to_string(index=False))
print(phys)
