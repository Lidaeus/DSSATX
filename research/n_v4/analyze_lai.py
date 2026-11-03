"""Same-target metrics and daily leaf source/acceptance diagnostics; no fitting."""
import json,runpy,sys
import numpy as np
import pandas as pd
import lai_workflow as flow
from lai_workflow import OUT,CN,REPO,dump,sha

def main(revision):
    receipts=json.loads((OUT/f'case_summary_{revision}.json').read_text(encoding='utf8'))
    assert all(r['success'] for r in receipts)
    meta=pd.read_csv(CN/'n_buffer_v14/inputs/26SP/treatment_metadata.csv').rename(columns={'treatment':'run'})
    summaries=[];metrics=[];trajectories=[];constraints=[];stocks=[];reference=None
    for r in receipts:
        name=r['name'];w=OUT/'cases'/name
        c=pd.read_csv(w/'comparison.csv').set_index('obsnme').sort_index()
        assert len(c)==612
        if reference is None:reference=c
        assert c.index.equals(reference.index)
        for col in ['observed','final_weight','fit_scale','date','variable','family','trno','huber_delta']:
            assert c[col].fillna('').equals(reference[col].fillna('')),(name,col)
        row=dict(case=name,Phi=float(c.phi_contribution.sum()))
        for family,g in c.groupby('family'):
            rmse=float(np.sqrt(np.mean((g.simulated-g.observed)**2)))
            metrics.append(dict(case=name,family=family,n=len(g),unit=g.unit.iloc[0],RMSE=rmse,
                NRMSE_percent=100*rmse/g.observed.mean(),phi=float(g.phi_contribution.sum())))
            key={'CANOPY_LAI':'LAI_RMSE','LEAF_N_CONCENTRATION':'leaf_N_RMSE',
                 'STEM_N_CONCENTRATION':'stem_N_RMSE','LEAF_DRY_MASS':'leaf_DM_RMSE',
                 'FINAL_FRESH_YIELD':'yield_RMSE_t_ha'}.get(family)
            if key:row[key]=rmse/(1000 if family=='FINAL_FRESH_YIELD' else 1)
        yield_rows=c[c.family.eq('FINAL_FRESH_YIELD')].reset_index().rename(columns={'trno':'run'}).merge(meta,on='run',validate='one_to_one')
        for water,g in yield_rows.groupby('water_level'):
            y=g.set_index('nitrogen_level');row[water+'_N3_minus_N0_t_ha']=float((y.loc['N3','simulated']-y.loc['N0','simulated'])/1000)
        summaries.append(row)
        if (w/'PlantNLAI.csv').exists():
            d=pd.read_csv(w/'PlantNLAI.csv',float_precision='round_trip').merge(meta,on='run',validate='many_to_one')
            d['case']=name;d['leaf_acceptance_ratio']=d.dm_leaf_actual/np.maximum(d.dm_leaf_request,1e-12)
            # Raw ratios remain untruncated; a saturated process multiplier is
            # not proof that N1/N2/N3 have the same underlying concentration.
            d['raw_stock_z']=(d.N_nonreserve_begin/np.maximum(d.W_leaf_begin,1e-12)-d.N_min_begin)/(d.N_crit_begin-d.N_min_begin)
            trajectories.append(d)
            for run,g in d.groupby('run'):
                constraints.append(dict(case=name,run=run,response_active_days=int((g.state_response<.999).sum()),
                    minimum_response=float(g.state_response.min()),minimum_stock_state=float(g.raw_stock_z.min()),
                    stock_state_below_one_days=int((g.raw_stock_z<1).sum()),
                    actual_below_request_days=int((g.dm_leaf_actual<g.dm_leaf_request-1e-6).sum()),
                    leaf_DM_new_g_m2=float(g.dm_leaf_actual.sum()),leaf_N_new_g_m2=float(g.N_leaf_actual.sum()),
                    new_leaf_area_m2_m2=float(g.new_leaf_area.sum()/10000),lost_leaf_area_m2_m2=float(g.old_leaf_area_lost.sum()/10000)))
                stocks.append(dict(case=name,run=run,LAI_end=float(g.LAI_end.iloc[-1]),
                    mean_z=float(g.raw_stock_z.mean()),mean_state=float(g.state_smoothed.mean())))
    summary=pd.DataFrame(summaries);summary.to_csv(OUT/f'diagnostic_summary_{revision}.csv',index=False)
    pd.DataFrame(metrics).to_csv(OUT/f'diagnostic_all_metrics_{revision}.csv',index=False)
    daily=pd.concat(trajectories,ignore_index=True);daily.to_csv(OUT/f'diagnostic_leaf_daily_{revision}.csv',index=False)
    pd.DataFrame(constraints).merge(meta,on='run',validate='many_to_one').to_csv(OUT/f'diagnostic_leaf_constraints_{revision}.csv',index=False)
    pd.DataFrame(stocks).merge(meta,on='run',validate='many_to_one').to_csv(OUT/f'diagnostic_leaf_endpoints_{revision}.csv',index=False)
    spread=[]
    for (case,water),g in daily[daily.nitrogen_level.isin(['N1','N2','N3'])].groupby(['case','water_level']):
        for variable in ['LAI_end','raw_stock_z','state_response','dm_leaf_potential','dm_leaf_request','dm_leaf_actual']:
            t=g.groupby('yrdoy')[variable].agg(['min','max'])
            spread.append(dict(case=case,water_level=water,variable=variable,maximum_daily_range=float((t['max']-t['min']).max())))
    pd.DataFrame(spread).to_csv(OUT/f'diagnostic_N1_N3_spread_{revision}.csv',index=False)
    # Full original stock/CH2O/canopy checks on independent trace replays.
    names=[f'{revision}_{v}_trace' for v in ['baseline','slow_reserve','lai_slow','lai_build70']]
    sys.path.insert(0,str(REPO/'research/n_v3'));import workflow
    workflow.OUT=OUT
    for name in names:
        assert (OUT/'cases'/name/'receipt.json').exists(),name
        trace=json.loads((OUT/'cases'/name/'receipt.json').read_text());assert trace['success'],trace
        assert all(flow.p1.numeric_records(OUT/'cases'/name/f)==flow.p1.numeric_records(OUT/'cases'/name.removesuffix('_trace')/f) for f in flow.p1.COMPARE_FILES)
    for script in ['verify_c1.py','verify_c2.py','verify_c3.py','verify_c4.py','verify_c4_photo.py']:
        sys.argv=[script]+names;runpy.run_path(str(REPO/'research/n_v3'/script),run_name='__main__')
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    assert all(sha(p)==h for p,h in b['protected'].items())
    assert sha(b['observations'])==b['objective_sha256']
    dump(OUT/f'analysis_receipt_{revision}.json',dict(passed=True,observations=612,no_objective_edits=True,
        protected_executables_unchanged=True,trace_numeric_neutral=True,full_trace_cases=names,
        default_compatible=True,whole_elemental_C_closed=False,no_new_calibration=True,
        physiological_gradient_validated=False,formal_candidate_promoted=False,
        artifacts={p.name:sha(p) for p in OUT.glob(f'diagnostic_*{revision}.csv')}))
    print(summary.to_string(index=False))
    print(pd.DataFrame(spread).query('variable=="LAI_end"').to_string(index=False))

if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else 'r3')
