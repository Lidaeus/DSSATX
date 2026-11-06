"""Water-sign/amplitude and N donor-pool evidence; proposal, not optimization."""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration.single_season_n import read_native,sha

OUT=ROOT/'workspace/experiments/n_mobilization_water_grid_20261012'


def main():
    manifest=json.loads((OUT/'experiment_manifest.json').read_text(encoding='utf-8'))
    score=pd.read_csv(OUT/'candidate_review_2026_only.csv').set_index('case_id')
    budget=pd.read_csv(ROOT/'configs/calibration_proposals/joint65_et_environment_after_grid_20261012/objective_budget_review.csv').set_index('family')
    budget.loc['HARVEST_DRY_CUMULATIVE','phi_budget']=11
    budget.loc['HARVEST_DRY_EVENT','phi_budget']=11
    budget.loc['W_RESPONSE','phi_budget']=12
    rows=[];contrasts=[];organ_changes=[];family=[]
    references={anchor:pd.read_csv(OUT/'cases'/name/'26SP/calibration_diagnostic_comparison.csv').set_index('obsnme')
        for anchor,name in [('original','baseline'),('env','env_reference'),('water','water_reference')]}
    for case in manifest['cases']:
        name=case['case_id'];work=OUT/'cases'/name/'26SP';comp=pd.read_csv(work/'calibration_diagnostic_comparison.csv')
        w=comp[comp.family.eq('W_RESPONSE')].copy();ratios=w.simulated/w.observed
        for ob in w.itertuples():
            contrasts.append(dict(case_id=name,stratum=ob.stratum,trno=ob.trno,paired_trno=ob.paired_trno,
                observed=ob.observed,simulated=ob.simulated,ratio=ob.simulated/ob.observed,
                sigma_eff=ob.sigma_eff,positive=ob.simulated>0,minimum25pct=ob.simulated>=.25*ob.observed))
        phi=0.
        for fam,q in comp.groupby('family'):
            value=float(budget.loc[fam,'phi_budget']/len(q)*np.square((q.simulated-q.observed)/q.sigma_eff).sum()) if q.simulated.notna().all() else np.nan
            family.append(dict(case_id=name,family=fam,phi=value,n=len(q)));phi+=value
        extra=pd.read_csv(OUT/'family_phi_513_review.csv')
        for fam in ['N_DOSE_ADJACENT','WATER_BALANCE_100CM']:
            q=extra[(extra.case_id==name)&(extra.family==fam)].iloc[0]
            family.append(dict(case_id=name,family=fam,phi=q.phi,n=q.n));phi+=q.phi
        direction=float((3/6*np.square(np.maximum(0,-w.simulated)/1500)).sum())
        family.append(dict(case_id=name,family='W_RESPONSE_DIRECTION',phi=direction,n=6));phi+=direction
        values=dict(pd.read_csv(work/'parameters.csv').values)
        rate=values['NMOBMX']*values['NVSMOB']
        baseline_rate=.114772*.442344
        row=dict(case_id=name,anchor=case['anchor'],original_phi=score.loc[name,'original_phi'],
            water_first519_review_phi=phi,positive6_count=int(w.simulated.gt(0).sum()),min_response_ratio=float(ratios.min()),
            proposed_direction_gate=bool(w.simulated.gt(0).all()),proposed_amplitude25pct_gate=bool((ratios>=.25).all()),
            nonwater_guard_pass=bool(score.loc[name,'nonwater_guards_pass']),
            eligible_for_promotion=bool(w.simulated.gt(0).all() and (ratios>=.25).all() and score.loc[name,'nonwater_guards_pass']),
            NMOBMX=values['NMOBMX'],NVSMOB=values['NVSMOB'],PROLFF=values['PROLFF'],PROSTF=values['PROSTF'],
            PRORTF=values['PRORTF'],PROSHF=values['PROSHF'],nominal_veg_rate_at_unit_temperature=rate,
            nominal_veg_rate_reduction_pct=100*(1-rate/baseline_rate))
        rows.append(row)
        # Directly observed native endpoints; no claim to recover NMINEA flux.
        before=references[case['anchor']]
        q=comp.set_index('obsnme');n12=q[q.trno.isin([4,5,6,7,8,10]) & q.variable.eq('CHPDT')]
        delta=(n12.simulated-before.loc[n12.index,'simulated']).abs().max()
        organ_changes.append(dict(case_id=name,max_N1_N2_dry_harvest_delta_kg_ha=float(delta),
            max_N1_N2_Wcontrast_delta_kg_ha=float((w[w.stratum.isin(['N1','N2'])].set_index('obsnme').simulated-before[before.family.eq('W_RESPONSE')&before.stratum.isin(['N1','N2'])].simulated).abs().max())))
    result=pd.DataFrame(rows)
    result.to_csv(OUT/'water_priority_candidate_review.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(contrasts).to_csv(OUT/'all6_water_contrast_audit.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(organ_changes).to_csv(OUT/'N1_N2_parameter_effect_audit.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame(family).to_csv(OUT/'family_phi_water_first519_review.csv',index=False,encoding='utf-8-sig')
    proof=dict(status='completed_diagnostic_proposal_support',cases=len(result),successful_native_season_runs=len(result)*3,
        all_target_complete=True,positive6_cases=int(result.proposed_direction_gate.sum()),
        positive6_and_min25pct_cases=int((result.proposed_direction_gate&result.proposed_amplitude25pct_gate).sum()),
        all_gates_pass_cases=int(result.eligible_for_promotion.sum()),
        threshold_status='25% of observed paired gain is a proposed conservative effect-size gate, not a confidence bound or accepted final fitting precision',
        guard_stage='Scientific candidate-promotion gate only; wrong water response remains a valid forward output with residual, not a DSSAT execution failure',
        no_internal_mobilization_flux_observed=True,parameter_floors_indirectly_constrained_by_live_tissue_data=True,
        original_source_hashes_verified=True,formal_calibration_started=False,
        experiment_manifest_sha256=sha(OUT/'experiment_manifest.json'),script_sha256=sha(Path(__file__)))
    for file,digest in manifest['source_hashes'].items():assert sha(ROOT/file)==digest,file
    (OUT/'water_priority_receipt.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False,indent=2))
    names=['baseline','env_reference','env_nm0.100_nv0.35','env_pool_l0.230_s0.070','water_reference','water_pool_l0.230_s0.070']
    print(result[result.case_id.isin(names)][['case_id','positive6_count','min_response_ratio','original_phi','nonwater_guard_pass','water_first519_review_phi','nominal_veg_rate_reduction_pct']].to_string(index=False))


if __name__=='__main__':main()
