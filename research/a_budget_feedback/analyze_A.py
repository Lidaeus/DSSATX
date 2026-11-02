"""Engineering diagnostics and inspectable tables, never publication figures."""
from pathlib import Path
import json,re,sys
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
CN=Path('D:/Tomato_Cal/subprojects/critical_n');OUT=CN/'reports/A_budget_feedback_20261102'
OLD=CN/'runs/n4864_p5_r2_explicit_smoke14_24x2_20261102'
sys.path.insert(0,str(OLD/'runtime'))
from smoke_forward import dump,sha
from src.calibration.single_season_n import read_native


def trace(path,prefix):
    cache=OUT/'analysis'/f'{prefix}_trace_daily.csv'
    if cache.exists():return pd.read_csv(cache)
    scalar=[];photo=[];residue=[]
    events={'cg_begin','cg_seed','cg_mobil','cg_repro','cg_before_veg','cg_veg','cg_end','cg_ledger_end','etphot_rate','grow_losses'}
    for q in pd.read_csv(path,chunksize=150000,usecols=['run','yrdoy','event','layer','key','value']):
        scalar.append(q[q.event.isin(events)&q.layer.eq(0)])
        photo.append(q[q.event.eq('leaf_capacity')&q.key.eq('AGEMXL')])
        residue.append(q[q.event.eq('grow_residue')])
    x=pd.concat(scalar);assert not x.duplicated(['run','yrdoy','event','key']).any()
    t=x.pivot(index=['run','yrdoy'],columns=['event','key'],values='value');t.columns=['__'.join(c)for c in t.columns];t=t.reset_index()
    z=pd.concat(photo).groupby(['run','yrdoy']).value.agg(['mean','min','max']).add_prefix('photo_AGEMXL_').reset_index()
    t=t.merge(z,on=['run','yrdoy'],how='left',validate='one_to_one')
    z=pd.concat(residue).groupby(['run','yrdoy','key']).value.sum().unstack('key').add_prefix('residue__').reset_index()
    t=t.merge(z,on=['run','yrdoy'],how='left',validate='one_to_one')
    t.to_csv(cache,index=False)
    return t


def main():
    data=OUT/'analysis';data.mkdir(exist_ok=True)
    base=CN/'runs/early_n_r020_diag_20261102/cases/baseline'
    names={int(m[1]):m[2]for m in re.finditer(r'^\s*(\d+)\s+1\s+0\s+0\s+(W[123]_N[0123])\b',(base/'XXQL2601.TMX').read_text(),re.M)}
    assert set(names)==set(range(1,13))
    meta=pd.DataFrame([dict(run=k,label=v,water=v.split('_')[0],nitrogen=v.split('_')[1])for k,v in names.items()])
    meta.to_csv(data/'treatment_metadata.csv',index=False)
    cases={'old_r020':base,'A_fixed':OUT/'regression/A_verified',
           'leaf_mobil_half':OUT/'regression/diagnostic_leaf_mobil_0.5',
           'leaf_mobil_off':OUT/'regression/diagnostic_leaf_mobil_0.0',
           'old_leaf_mobil_half':OUT/'regression/diagnostic_old_leaf_mobil_0.5',
           'old_leaf_mobil_off':OUT/'regression/diagnostic_old_leaf_mobil_0.0'}
    if (OUT/'best_native_trace/receipt.json').exists():
        cases.update(best_fit=OUT/'best_native_trace',best_leaf_mobil_half=OUT/'best_leaf_mobil_half',best_leaf_mobil_off=OUT/'best_leaf_mobil_off')
    treatment=[];ablation=[];budgets=[];flow=[];pair=[];daily=[]
    observation=pd.read_csv(OLD/'observations.csv')
    yobs=observation[observation.family.eq('FINAL_FRESH_YIELD')].set_index('trno').observed
    traces={}
    for name,w in cases.items():
        n=pd.read_csv(w/'PlantNIntegration.csv');n['date']=pd.to_datetime(n.yrdoy.astype(str),format='%Y%j').dt.strftime('%Y-%m-%d')
        n=n.merge(meta,on='run',validate='many_to_one');n['case']=name
        g=read_native(w/'PlantGro.OUT').reset_index();f=read_native(w/'FreshWt.OUT').reset_index()
        n=n.merge(g[['run','date','DAP','LAID']],on=['run','date'],validate='one_to_one');daily.append(n)
        y=f.groupby('trno').CHFPW.max()
        for trno,value in y.items():pair.append(dict(case=name,run=trno,label=names[trno],observed_t_ha=yobs.loc[trno]/1000,simulated_t_ha=value/1000))
        ablation.append(dict(case=name,W2_N3_yield_t_ha=y.loc[2]/1000,W2_N0_yield_t_ha=y.loc[11]/1000,W2_N3_minus_N0_t_ha=(y.loc[2]-y.loc[11])/1000,
                             mean_yield_t_ha=y.mean()/1000,yield_nrmse_pct=100*np.sqrt(np.mean((y-yobs)**2))/yobs.mean(),
                             W2_N0_final_leaf_N_pct=100*n[n.run.eq(11)].Corg_leaf.iloc[-1]))
        if name in {'old_r020','A_fixed','best_fit'}:
            t=trace(w/'P0Trace.csv',name);traces[name]=t
            t=t.merge(n[['run','yrdoy','date','DAP','label','Corg_leaf','leaf_min','leaf_crit','leaf_max']],on=['run','yrdoy'],validate='one_to_one')
            for run,q in t.groupby('run'):
                fn=q.cg_repro__NGRSH+q.cg_repro__NGRSD
                nav=q.cg_mobil__NAVL;nl=q.cg_mobil__NRUSLF
                others=np.maximum(0,nav-nl)
                lower=np.maximum(0,fn-others);upper=np.minimum(fn,nl)
                mixed=fn*nl/nav.replace(0,np.nan)
                flow.append(dict(case=name,run=run,label=names[run],leaf_mobil_gN_m2=nl.sum(),stem_mobil_gN_m2=q.cg_mobil__NRUSST.sum(),
                   total_mobil_gN_m2=q.cg_mobil__NMINEA.sum(),fruit_new_N_gN_m2=fn.sum(),
                   leaf_to_fruit_direct_lower_gN_m2=lower.sum(),leaf_to_fruit_direct_upper_gN_m2=upper.sum(),
                   leaf_to_fruit_well_mixed_bookkeeping_gN_m2=mixed.sum(),
                   gross_PG_gCH2O_m2=q.etphot_rate__PG.sum(),fruit_C_gCH2O_m2=(q.cg_repro__CGRSH+q.cg_repro__CGRSD).sum(),
                   photo_factor_ge_0p99_days=int(q.photo_AGEMXL_mean.ge(.99).sum()),photo_days=int(q.photo_AGEMXL_mean.notna().sum())))
            # Independently reconcile actual organ loss and soil residue.
            previous=t.groupby('run').grow_losses__NHSHWT.shift().fillna(0)
            harvest=t.grow_losses__NHSHWT-previous
            surface=t.residue__surface_N/10
            expected=t.grow_losses__NLOFF+t.grow_losses__NSOFF+t.grow_losses__NSHOFF-t.grow_losses__NLPEST-harvest
            root=t.residue__root_N/10
            budgets.append(dict(case=name,surface_return_residual_max_gN_m2=float((surface-expected).abs().max()),
                   root_return_residual_max_gN_m2=float((root-t.grow_losses__NROFF).abs().max()),
                   surface_harvest_N_duplicate_sum_gN_m2=float((surface-expected).sum()),
                   growth_C_overrun_max=float(n.legacy_growth_C_overrun.max()),organic_N_residual_max=float(n.legacy_organic_N_residual.abs().max())))
        for run,q in n.groupby('run'):
            treatment.append(dict(case=name,run=run,label=names[run],A_N_gN_m2=float((q.A_NO3+q.A_NH4).sum()),
                 uptake_gN_m2=float((q.U_NO3+q.U_NH4).sum()),C_assim_gCH2O_m2=q.C_assim.sum(),C_refund_gCH2O_m2=q.C_refund.sum(),
                 leaf_N_mean_pct=100*q.Corg_leaf.mean(),leaf_N_min_pct=100*q.Corg_leaf.min(),
                 mean_growth_factor=q.growth_factor.mean(),min_leaf_to_lower=(q.Corg_leaf/q.leaf_min).min()))
    pd.concat(daily).to_csv(data/'mechanism_daily.csv',index=False)
    pd.DataFrame(flow).to_csv(data/'N_source_and_C_paths.csv',index=False)
    pd.DataFrame(budgets).to_csv(data/'independent_residue_budget.csv',index=False)
    pd.DataFrame(treatment).to_csv(data/'treatment_budgets.csv',index=False)
    pd.DataFrame(ablation).to_csv(data/'leaf_mobilization_ablation.csv',index=False)
    pd.DataFrame(pair).to_csv(data/'mechanism_yield_pairs.csv',index=False)
    # Compare exact-date observations to soft references, not to a guessed
    # lower physiological threshold inferred from the N0 treatment label.
    obs=observation[observation.variable.eq('LEAF_N_PCT')].copy();obs=obs.rename(columns={'trno':'run'})
    bands=[]
    for name,n in pd.concat(daily).groupby('case'):
        q=obs.merge(n[['run','date','label','Corg_leaf','Ctotal_leaf','leaf_min','leaf_crit','leaf_max']],on=['run','date'],validate='many_to_one')
        q['case']=name
        for col in ['Corg_leaf','Ctotal_leaf','leaf_min','leaf_crit','leaf_max']:q[col+'_pct']=q[col]*100
        q['observed_to_min']=q.observed/q.leaf_min_pct;bands.append(q)
    pd.concat(bands).to_csv(data/'observed_leaf_and_reference_bands.csv',index=False)
    grid=[]
    for w in sorted((OUT/'regression').glob('finalcurve_*')):
        r=json.loads((w/'receipt.json').read_text(encoding='utf8'));c=pd.read_csv(w/'comparison.csv')
        y=c[c.family.eq('FINAL_FRESH_YIELD')].set_index('trno');n=pd.read_csv(w/'PlantNIntegration.csv')
        early=n[n.yrdoy.between(2026103,2026128)] # DAP30-55 diagnostic window only
        grid.append(dict(case=w.name,w0=r['config']['curve_w0'],min_ratio=r['config']['min_ratio'],max_ratio=r['config']['max_ratio'],
             phi=r['phi'],mean_yield_t_ha=y.simulated.mean()/1000,
             yield_nrmse_pct=100*np.sqrt(np.mean((y.simulated-y.observed)**2))/y.observed.mean(),
             W2_N3_minus_N0_t_ha=(y.loc[2,'simulated']-y.loc[11,'simulated'])/1000,
             early_leaf_N_mean_pct=100*early.Corg_leaf.mean(),actual_leaf_to_min_min=(n.Corg_leaf/n.leaf_min).min()))
    pd.DataFrame(grid).to_csv(data/'controlled_curve_grid.csv',index=False)
    dump(data/'analysis_receipt.json',dict(sources={str(p):sha(p)for p in [base/'P0Trace.csv',OUT/'regression/A_verified/P0Trace.csv',OLD/'observations.csv']},
         mapping_source=str(base/'XXQL2601.TMX'),V15_physiology=False,
         source_attribution='direct daily flow bounds plus explicitly labelled well-mixed accounting; no measured leaf-to-fruit tracer claim',
         ablation='leaf donor 0.5/0 only in private diagnostic executables; actual total NMINEA recomputed; calibrated executable unchanged',
         curves='Nc=a max(W0,W)^(-b), a fixed across paired breakpoints; standing vegetative shoot',
         scientific_status='engineering diagnostics only, not publication-validated'))
    print(pd.DataFrame(ablation).to_string(index=False))
    print(pd.DataFrame(flow).query('run in [2,11]').to_string(index=False))
    print(pd.DataFrame(budgets).to_string(index=False))


if __name__=='__main__':main()
