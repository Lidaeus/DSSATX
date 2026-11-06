"""Prespecified multi-objective review; calibration-only ranking, no optimizer."""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration.single_season_n import read_native,sha

OUT=ROOT/'workspace/experiments/et_environment_grid_20261012'
VARIABLES=['CHPDT','HPODW','LAID','LWAD','SWAD','CHTD','LEAF_N_PCT','STEM_N_PCT','FRUIT_N_PCT']


def main():
    manifest=json.loads((OUT/'experiment_manifest.json').read_text(encoding='utf-8'))
    metrics=pd.read_csv(OUT/'case_metrics.csv');cal=metrics[metrics.season_id.eq('26SP')].set_index('case_id')
    baseline=cal.loc['baseline'];et=pd.read_csv(OUT/'et_comparison/interval_ET_comparison_all_grid.csv')
    adj=pd.read_csv(ROOT/'configs/calibration_proposals/joint67_response_revision_20261012/adjacent_N_targets_review.csv')
    budgets=pd.read_csv(ROOT/'configs/calibration_proposals/joint67_et_environment_review_20261012/objective_budget_supplement_review.csv').set_index('family')
    family_rows=[];ranking=[];baseline_nonwater=None
    cases=sorted(manifest['cases'],key=lambda x: x['case_id']!='baseline')
    for case in cases:
        name=case['case_id'];work=OUT/'cases'/name/'26SP'
        comp=pd.read_csv(work/'calibration_diagnostic_comparison.csv')
        nonwater=comp[~comp.family.isin(['SOIL_WATER','W_RESPONSE'])]
        nonwater_phi=float(np.square((nonwater.simulated-nonwater.observed)*nonwater.final_weight).sum()) if nonwater.simulated.notna().all() else np.nan
        if name=='baseline':baseline_nonwater=nonwater_phi
        q=et[(et.case_id==name)&(et.season_id=='26SP')&(~et.phase.eq('total'))]
        wb_rmse=float(np.sqrt(np.mean(np.square(q.apparent100_residual))))
        wb_nrmse=100*wb_rmse/q.observed_ET.mean()
        q=q.copy();q['sigma_eff']=np.sqrt(q.observed_sd**2+10**2+(.1*q.observed_ET)**2)
        wb_phi=float((5/18*np.square(q.apparent100_residual/q.sigma_eff)).sum())
        proposed_phi=0.
        for family,part in comp.groupby('family'):
            phi=float((float(budgets.loc[family,'phi_budget'])/len(part)*np.square((part.simulated-part.observed)/part.sigma_eff)).sum()) if part.simulated.notna().all() else np.nan
            family_rows.append(dict(case_id=name,family=family,phi=phi,n=len(part)))
            proposed_phi+=phi
        fresh=read_native(work/'FreshWt.OUT');adj_phi=0.
        for row in adj.itertuples():
            sim=float(fresh.loc[(row.trno,row.date),'CHFPW']-fresh.loc[(row.paired_trno,row.date),'CHFPW'])
            adj_phi+=2/3*((sim-row.observed)/row.sigma_eff)**2
        family_rows.extend([dict(case_id=name,family='N_DOSE_ADJACENT',phi=adj_phi,n=3),dict(case_id=name,family='WATER_BALANCE_100CM',phi=wb_phi,n=18)])
        proposed_phi+=adj_phi+wb_phi
        m=cal.loc[name];failed=[]
        if m.missing_primary_targets:failed.append('missing_exact_date_targets')
        if pd.isna(nonwater_phi) or nonwater_phi>baseline_nonwater*1.10:failed.append('nonwater_phi_above_10pct')
        if pd.isna(m.full_phi) or m.full_phi>baseline.full_phi*1.10:failed.append('original_phi_above_10pct')
        for variable in VARIABLES:
            basevalue=baseline[variable+'_nrmse'];value=m[variable+'_nrmse']
            if pd.isna(value) or value>basevalue+max(2.,.1*basevalue):failed.append(variable+'_NRMSE_guard')
        b_wb=wb_nrmse if name=='baseline' else ranking[0]['WB100_interval_NRMSE']
        weak=wb_nrmse<b_wb and m.VWC_nrmse<baseline.VWC_nrmse
        strong=wb_nrmse<=b_wb*.90 and m.VWC_nrmse<=baseline.VWC_nrmse*.95
        row=dict(**case,original_phi=m.full_phi,proposed513_phi=proposed_phi,nonwater_phi=nonwater_phi,
            nonwater_phi_change_pct=100*(nonwater_phi/baseline_nonwater-1),WB100_interval_NRMSE=wb_nrmse,
            VWC_NRMSE=m.VWC_nrmse,CHPDT_NRMSE=m.CHPDT_nrmse,HPODW_NRMSE=m.HPODW_nrmse,
            LAI_NRMSE=m.LAID_nrmse,leaf_N_NRMSE=m.LEAF_N_PCT_nrmse,stem_N_NRMSE=m.STEM_N_PCT_nrmse,fruit_N_NRMSE=m.FRUIT_N_PCT_nrmse,
            W_response_NRMSE=m.W_nrmse,N_adjacent_NRMSE=m.N_adjacent_nrmse,
            missing_targets=int(m.missing_primary_targets),nonwater_guards_pass=not failed,guard_failures=';'.join(failed),
            weak_water_improvement=weak,strong_water_improvement=strong,
            admissible_weak=not failed and weak,admissible_strong=not failed and strong,
            weather_is_hypothetical=case['EVAPO'] in ['F','D','S','Z'])
        ranking.append(row)
    rank=pd.DataFrame(ranking)
    rank.to_csv(OUT/'candidate_review_2026_only.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(family_rows).to_csv(OUT/'family_phi_513_review.csv',index=False,encoding='utf-8-sig')
    # Independent native weather audit of ALL workers, not just requested WTH values.
    wind=[]
    for case in manifest['cases']:
        for season in ['26SP','25SP','25FA']:
            work=OUT/'cases'/case['case_id']/season;weather=read_native(work/'Weather.OUT')
            minwind,maxwind=float(weather.WDSD.min()),float(weather.WDSD.max())
            if 'WIND_m_s' in case:assert max(abs(x-case['WIND_m_s']*86.4) for x in [minwind,maxwind])<=.11
            wind.append(dict(case_id=case['case_id'],season_id=season,method=case['EVAPO'],requested_wind_m_s=case.get('WIND_m_s'),native_WDSD_min_km_day=minwind,native_WDSD_max_km_day=maxwind,
                caveat='ASCE missing-wind branch uses 2m/s in PETASCE, independent of Weather.OUT 1m/s fallback' if case['EVAPO']=='S' and 'WIND_m_s' not in case else 'assumed wind, not measured' if 'WIND_m_s' in case else 'model fallback, not measured'))
    pd.DataFrame(wind).to_csv(OUT/'native_weather_audit.csv',index=False,encoding='utf-8-sig')
    # Per-family guard limits are exported independently of candidate selection.
    pd.DataFrame([dict(variable=v,baseline_NRMSE=baseline[v+'_nrmse'],allowed_NRMSE=baseline[v+'_nrmse']+max(2.,.1*baseline[v+'_nrmse'])) for v in VARIABLES]).to_csv(OUT/'guard_limits.csv',index=False,encoding='utf-8-sig')
    success=0
    for case in manifest['cases']:
        for season in ['26SP','25SP','25FA']:
            work=OUT/'cases'/case['case_id']/season
            audit=json.loads((work/'environment_injection_audit.json').read_text())
            assert audit['native_EVAPO']==case['EVAPO'];assert (work/'process_summary.csv').exists();success+=1
    for file,digest in manifest['source_hashes'].items():assert sha(ROOT/file)==digest,file
    receipt=dict(status='completed_diagnostic_only',supported_cases=len(manifest['cases']),successful_native_season_runs=success,
        original492_target_missing_cases=int(rank.missing_targets.gt(0).sum()),
        guard_pass_cases=int(rank.nonwater_guards_pass.sum()),admissible_weak_cases=int(rank.admissible_weak.sum()),admissible_strong_cases=int(rank.admissible_strong.sum()),
        baseline_original_phi=float(baseline.full_phi),baseline_nonwater_phi=baseline_nonwater,
        baseline_WB100_interval_NRMSE=ranking[0]['WB100_interval_NRMSE'],baseline_VWC_NRMSE=float(baseline.VWC_nrmse),
        baseline_proposed513_phi=ranking[0]['proposed513_phi'],
        ranking_policy='Only 2026 calibration data. 2025 metrics excluded from ranking.',
        uncertainty='WB100 and VWC share soil samples; diagonal review weights are advisory, not covariance-correct likelihood',
        original_inputs_and_runs_unchanged=True,formal_calibration_started=False,
        manifest_sha256=sha(OUT/'experiment_manifest.json'),review_script_sha256=sha(Path(__file__)))
    (OUT/'review_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    cols=['case_id','original_phi','proposed513_phi','nonwater_phi_change_pct','WB100_interval_NRMSE','VWC_NRMSE','CHPDT_NRMSE','HPODW_NRMSE','W_response_NRMSE','nonwater_guards_pass','admissible_strong']
    print('ADMISSIBLE CANDIDATES');print(rank[rank.admissible_weak].sort_values('proposed513_phi')[cols].to_string(index=False))
    print('METHOD REVIEW');print(rank[rank.EVAPO.ne('R')][cols].to_string(index=False))


if __name__=='__main__':main()
