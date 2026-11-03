"""Same-target P2 readout and independent trace/stock verification; no plotting or calibration."""
from pathlib import Path
import json,runpy,sys
import numpy as np
import pandas as pd
import p2_workflow as p2
from p2_workflow import OUT,CN,REPO,sha,dump

def main(revision):
    receipts=json.loads((OUT/f'case_summary_{revision}.json').read_text(encoding='utf8'))
    if (OUT/f'build_cases_{revision}.json').exists():receipts+=json.loads((OUT/f'build_cases_{revision}.json').read_text(encoding='utf8'))
    assert all(r['success'] for r in receipts)
    metrics=[];summary=[];carbon=[];ys=[];stocks=[];ref=None
    meta=pd.read_csv(CN/'n_buffer_v14/inputs/26SP/treatment_metadata.csv').rename(columns={'treatment':'run'})
    for r in receipts:
        name=r['name'];w=OUT/'cases'/name
        c=pd.read_csv(w/'comparison.csv').set_index('obsnme').sort_index()
        if ref is None:ref=c
        assert c.index.equals(ref.index) and len(c)==612
        for col in ['observed','final_weight','fit_scale','date','variable','family','trno','huber_delta']:
            assert c[col].fillna('').equals(ref[col].fillna('')),(name,col)
        for family,g in c.groupby('family'):
            e=g.simulated-g.observed;rmse=float(np.sqrt(np.mean(e**2)))
            den=float(((abs(g.simulated-g.observed.mean())+abs(g.observed-g.observed.mean()))**2).sum())
            metrics.append(dict(case=name,family=family,n=len(g),unit=g.unit.iloc[0],RMSE=rmse,
                NRMSE_percent=100*rmse/g.observed.mean(),bias=float(e.mean()),d_index=1-float((e**2).sum())/den if den else None,phi=float(g.phi_contribution.sum())))
        y=c[c.family.eq('FINAL_FRESH_YIELD')].reset_index().rename(columns={'trno':'run'}).merge(meta,on='run',validate='one_to_one')
        y['case']=name;ys.append(y[['case','run','water_level','nitrogen_level','observed','simulated']])
        row=dict(case=name,Phi=float(c.phi_contribution.sum()))
        for f,k in [('FINAL_FRESH_YIELD','yield_RMSE_t_ha'),('LEAF_N_CONCENTRATION','leaf_N_RMSE'),('STEM_N_CONCENTRATION','stem_N_RMSE'),('CANOPY_LAI','LAI_RMSE')]:
            g=c[c.family.eq(f)];row[k]=float(np.sqrt(np.mean((g.simulated-g.observed)**2)))/(1000 if f=='FINAL_FRESH_YIELD' else 1)
        for water,g in y.groupby('water_level'):
            q=g.set_index('nitrogen_level');row[water+'_N3_minus_N0_t_ha']=float((q.loc['N3','simulated']-q.loc['N0','simulated'])/1000)
        summary.append(row)
        cash=pd.read_csv(w/'PlantCCash.csv');cash=cash.groupby('run')[['PG','actual_C_mined','maintenance','N_assim','N_resynthesis','veg_growth','fruit_growth','storage_cost']].sum().reset_index().merge(meta,on='run',validate='one_to_one')
        cash['case']=name;carbon.append(cash)
        if (w/'PlantNP2.csv').exists():
            p=pd.read_csv(w/'PlantNP2.csv');p['case']=name
            for run,g in p.groupby('run'):
                stocks.append(dict(case=name,run=run,maximum_R_gN_m2=float((g.R_end_leaf+g.R_end_stem).max()),
                    R_fill_gN_m2=float((g.R_fill_leaf+g.R_fill_stem).sum()),
                    R_fast_gN_m2=float((g.R_fast_leaf+g.R_fast_stem).sum()),R_litter_gN_m2=float((g.R_litter_leaf+g.R_litter_stem).sum()),
                    R_sen_recovery_gN_m2=float((g.R_sen_recovery_leaf+g.R_sen_recovery_stem).sum())))
    pd.DataFrame(metrics).to_csv(OUT/f'diagnostic_all_metrics_{revision}.csv',index=False)
    pd.DataFrame(summary).to_csv(OUT/f'diagnostic_summary_{revision}.csv',index=False)
    pd.concat(ys).to_csv(OUT/f'diagnostic_yields_{revision}.csv',index=False)
    pd.concat(carbon).to_csv(OUT/f'diagnostic_CH2O_{revision}.csv',index=False)
    pd.DataFrame(stocks).merge(meta,on='run',validate='many_to_one').to_csv(OUT/f'diagnostic_reserves_{revision}.csv',index=False)
    names=[revision+'_'+v+'_trace' for v in ['baseline','reserve_only','joint_reserve']]
    if (OUT/'cases'/f'{revision}_build_leaf70_trace').exists():names.append(f'{revision}_build_leaf70_trace')
    # Reuse independent stock/area and canopy integration checks, with the
    # explicitly added functional-repair recipient in the C2 verifier.
    sys.path.insert(0,str(REPO/'research/n_v3'))
    import workflow
    workflow.OUT=OUT
    for script in ['verify_c1.py','verify_c2.py','verify_c3.py','verify_c4.py','verify_c4_photo.py']:
        sys.argv=[script]+names;runpy.run_path(str(REPO/'research/n_v3'/script),run_name='__main__')
    import analyze_p1 as photo_audit
    photo_audit.OUT=OUT
    photo_errors={};exclusion_errors={}
    for name in names:
        w=OUT/'cases'/name;plain=OUT/'cases'/name.removesuffix('_trace')
        assert all(p2.p1.numeric_records(w/f)==p2.p1.numeric_records(plain/f) for f in p2.p1.COMPARE_FILES)
        _,_,_,error=photo_audit.trace_analysis(name);photo_errors[name]=error
        if (w/'PlantNP2.csv').exists():
            parts=[]
            for t in pd.read_csv(w/'P0Trace.csv',chunksize=200000,usecols=['run','yrdoy','event','key','value']):
                parts.append(t[t.event.eq('cg_end')&t.key.isin(['WTNLF','WTLF','WCRLF','RNITP'])])
            t=pd.concat(parts).pivot(index=['run','yrdoy'],columns='key',values='value').reset_index()
            p=pd.read_csv(w/'PlantNP2.csv',float_precision='round_trip')
            t=t.merge(p[['run','yrdoy','R_end_leaf']],on=['run','yrdoy'],validate='one_to_one')
            expected=100*(t.WTNLF-t.R_end_leaf)/(t.WTLF-t.WCRLF)
            e=float(abs(expected-t.RNITP).max());assert e<2e-6
            exclusion_errors[name]=e
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    assert all(sha(p)==h for p,h in b['protected'].items())
    assert sha(b['observations'])==b['objective_sha256']
    dump(OUT/f'analysis_receipt_{revision}.json',dict(passed=True,observations=612,no_objective_edits=True,
        protected_executables_unchanged=True,trace_numeric_neutral=True,
        actual_photo_reconstruction_errors=photo_errors,reserve_excluded_from_RNITP_errors=exclusion_errors,
        no_new_calibration=True,whole_elemental_C_closed=False,formal_candidate_promoted=False,
        artifacts={p.name:sha(p) for p in OUT.glob(f'diagnostic_*{revision}*.csv')}))
    print(pd.DataFrame(summary).to_string(index=False))

if __name__=='__main__':
    main(sys.argv[1] if len(sys.argv)>1 else 'r5')
