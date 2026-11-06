"""Post-grid comparison, date-level LAI and objective trade-offs; no renderer."""
from pathlib import Path
import sys
import json
import pandas as pd
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.experiments.run_v52_photo_senescence_20260902 import OUT,plan,refine_plan,summarize,verify_seal
from tools.analysis.evaluate_v49_mechanism_20260902 import score
from tools.calibration.run_v49_mechanism_multiarm_20260902 import dump,sha


def main():
    tasks=plan()+refine_plan()
    for t in tasks:
        assert (OUT/t['label']/'completed.json').exists(), t['label']
    summarize(tasks)
    summary=pd.read_csv(OUT/'summary.csv')
    assert len(summary)==40 and not summary.label.duplicated().any()
    chosen=summary[summary.candidate_pass & summary.v48_scale_canopy_pass].copy()
    chosen['mean_yield_nse']=chosen[['25SP_FRESH_CUM_nse','26SP_FRESH_CUM_nse']].mean(axis=1)
    # Multiobjective shortlist: retain each qualified candidate; ranking is
    # descriptive, not automatic promotion or a replacement PEST objective.
    chosen=chosen.sort_values('mean_yield_nse',ascending=False)
    chosen.to_csv(OUT/'qualified_candidates.csv',index=False)
    dates,phis,contrasts,spreads=[],[],[],[]
    for t in tasks:
        label=t['label']
        folder=OUT/label
        phi=pd.read_csv(folder/'objective_residuals.csv')
        phi['family']=phi.sim_token.where(~phi.sim_token.str.match(r'^SW\d+S$'),'SOIL_WATER')
        phis.append(phi.groupby(['season_id','family'],as_index=False).actual_phi.sum().assign(label=label))
        for season in ['25SP','26SP']:
            p=pd.read_csv(folder/f'_seasons/{season}/{season}_deterministic_process_compare.csv')
            for variable in ['LAID','LWAD','SWAD']:
                for date,g in p.groupby('DATE'):
                    obs,sim=g['OBS_'+variable],g['SIM_'+variable]
                    valid=np.isfinite(obs)&np.isfinite(sim)&obs.ne(-99)&sim.ne(-99)
                    if valid.any():
                        dates.append(dict(label=label,season=season,variable=variable,date=int(date),
                              obs_mean=obs[valid].mean(),sim_mean=sim[valid].mean(),**score(obs[valid],sim[valid])))
        g=pd.read_csv(folder/'26SP_nonN0_gradients.csv')
        last=g[g.variable.eq('FRESH_CUM')].sort_values('date').groupby(['water','contrast']).tail(1)
        contrasts.append(last.assign(label=label))
        spread=pd.read_csv(folder/'26SP_nonN0_spread.csv')
        spreads.append(spread[spread.variable.eq('FRESH_CUM')].sort_values('date').groupby('water').tail(1).assign(label=label))
    daily=pd.DataFrame(dates)
    daily.to_csv(OUT/'date_metrics.csv',index=False)
    pd.concat(contrasts,ignore_index=True).to_csv(OUT/'terminal_nonN0_contrasts.csv',index=False)
    pd.concat(spreads,ignore_index=True).to_csv(OUT/'terminal_nonN0_spread.csv',index=False)
    phi=pd.concat(phis,ignore_index=True)
    reference=phi[phi.label.eq('p0_control')].drop(columns='label').rename(columns={'actual_phi':'reference_phi'})
    phi=phi.merge(reference,on=['season_id','family'],validate='many_to_one')
    phi['delta_phi']=phi.actual_phi-phi.reference_phi
    phi.to_csv(OUT/'phi_family_comparison.csv',index=False)
    fit=pd.read_csv(OUT/'all_fit_metrics.csv')
    response=fit[fit.variable.str.startswith(('NRESPS_','WRESPS_'))].copy()
    ref=response[response.label.eq('p0_control')][['season','variable','rmse']].rename(columns={'rmse':'reference_rmse'})
    response=response.merge(ref,on=['season','variable'],validate='many_to_one')
    response['rmse_change_pct']=100*(response.rmse/response.reference_rmse-1)
    response.to_csv(OUT/'response_comparison.csv',index=False)
    # Independent recomputation of every summary's cumulative NSE and terminal RRMSE.
    audit=[]
    for t in tasks:
        label=t['label']
        result=summary.set_index('label').loc[label]
        for season in ['25SP','26SP']:
            h=pd.read_csv(OUT/label/f'_seasons/{season}/{season}_deterministic_harvest_compare.csv')
            assert len(h)==(90 if season=='25SP' else 60)
            o,s=h.OBS_FRESH_CUM.to_numpy(),h.SIM_FRESH_CUM.to_numpy()
            nse=1-np.sum((s-o)**2)/np.sum((o-o.mean())**2)
            last=h.sort_values('DATE').groupby('TN').tail(1)
            rr=100*np.sqrt(np.mean((last.SIM_FRESH_CUM-last.OBS_FRESH_CUM)**2))/last.OBS_FRESH_CUM.mean()
            np.testing.assert_allclose(nse,result[season+'_FRESH_CUM_nse'],rtol=0,atol=1e-12)
            np.testing.assert_allclose(rr,result[season+'_FRESH_TERMINAL_rrmse_pct'],rtol=0,atol=1e-12)
            audit.append(dict(label=label,season=season,n_harvest_pairs=len(h),fresh_nse=nse,terminal_rrmse_pct=rr))
    pd.DataFrame(audit).to_csv(OUT/'independent_metric_audit.csv',index=False)
    verify_seal()
    dump(OUT/'analysis_manifest.json',dict(candidate_pairs=40,season_runs=80,treatment_runs=880,
         qualified=chosen.label.tolist(),no_automatic_promotion=True,
         source_seal_unchanged=True,analysis_script_sha256=sha(Path(__file__)),
         note='Conditional deterministic fit, not posterior inference or independent validation. All original objective weights unchanged.'))
    print(chosen[['label','phi','25SP_FRESH_CUM_nse','26SP_FRESH_CUM_nse','25SP_LAID_nse','26SP_LAID_nse']].to_string(index=False))


if __name__=='__main__':
    main()
