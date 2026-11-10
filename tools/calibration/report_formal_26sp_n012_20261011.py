"""Recompute the completed r3 result without changing sealed calibration evidence."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = 'eggplant_26sp_n012_formal_20261011_r3'
RUN = ROOT / 'workspace/runs' / RUN_ID
CONFIG = ROOT / 'configs/runs' / RUN_ID
OUT = RUN / 'result_review'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metrics(frame, label):
    rows = []
    for (season, role, variable), group in frame.groupby(['season_id', 'dataset_role', 'variable']):
        y, p = group.observed.to_numpy(float), group.simulated.to_numpy(float)
        assert np.isfinite(y).all() and np.isfinite(p).all()
        errors = p-y
        ss = float(np.dot(errors, errors))
        mean_y = float(y.mean())
        denominator = float(np.sum((np.abs(p-mean_y)+np.abs(y-mean_y))**2))
        variation = float(np.sum((y-mean_y)**2))
        rows.append(dict(comparison=label, season_id=season, dataset_role=role, variable=variable,
            unit=str(group.unit.iloc[0]), n=len(group), observed_mean=mean_y, simulated_mean=float(p.mean()),
            rmse=float(np.sqrt(ss/len(y))), nrmse_pct=100*float(np.sqrt(ss/len(y)))/mean_y if mean_y else None,
            d_index=1-ss/denominator if denominator else None, nse=1-ss/variation if variation else None,
            mean_bias=float(errors.mean()), relative_mean_bias_pct=100*float(errors.mean())/mean_y if mean_y else None,
            weighted_phi=float(np.sum((errors*group.final_weight.to_numpy(float))**2)) if label != 'evaluation' else np.nan))
    return pd.DataFrame(rows)


def local_time(text):
    return dt.datetime.fromisoformat(text.replace('Z', '+00:00')).astimezone(dt.timezone(dt.timedelta(hours=8)))


def main():
    OUT.mkdir(exist_ok=True)
    state, design = read_json(RUN/'pipeline_status.json'), read_json(CONFIG/'design.json')
    assert state['status'] == 'completed_pending_scientific_review'
    assert sha(RUN/'final_parameters.csv') == state['final_parameters_sha256']
    base = pd.read_csv(RUN/'preflight/baseline_comparison.csv')
    final_stage = state['completed_stages'][-1]['stage']
    final = pd.read_csv(RUN/final_stage/'selected_deterministic/last_comparison.csv')
    evaluation = pd.read_csv(RUN/'evaluation_comparison.csv')
    obs = pd.read_csv(CONFIG/'calibration_observations.csv')
    assert len(final) == 423 and np.isfinite(final.simulated).all()
    assert final.obsnme.tolist() == obs.obsnme.tolist()
    assert np.array_equal(final.observed.to_numpy(), obs.observed.to_numpy())
    assert np.array_equal(final.final_weight.to_numpy(), obs.final_weight.to_numpy())
    assert len(evaluation) == 1254 and evaluation.comparison_status.eq('matched').all()
    tables = pd.concat([metrics(base,'baseline'),metrics(final,'final_calibration'),metrics(evaluation,'evaluation')],ignore_index=True)
    tables.to_csv(OUT/'recomputed_metrics.csv',index=False)
    previous = pd.read_csv(RUN/'evaluation_metrics.csv')
    check = tables[tables.comparison.eq('evaluation')].merge(previous,on=['season_id','dataset_role','variable'],suffixes=('_recomputed','_original'),validate='one_to_one')
    assert np.allclose(check.rmse_recomputed,check.rmse_original)
    assert np.allclose(check.nrmse_pct/100,check.nrmse)
    assert np.allclose(check.d_index_recomputed,check.d_index_original)

    stages=[]
    for folder in sorted(RUN.glob('S*')):
        if not folder.is_dir(): continue
        status=read_json(folder/'run_status.json')
        quality=read_json(folder/'ies_quality/ies_run_quality.json')
        member=pd.read_csv(folder/'ies_quality'/f'{folder.name}.member_status.csv')
        initial=read_json(folder/'initial_feasibility/report.json')
        phi=pd.read_csv(folder/f'{folder.name}.phi.actual.csv')
        checks={c['check_id']:c for c in quality['checks']}
        selection=read_json(folder/'selection.json') if (folder/'selection.json').exists() else {}
        rec=(folder/f'{folder.name}.rec').read_text(encoding='utf-8',errors='replace')
        missing=set(member.loc[~member.state.eq('retained'),'real_name'].str.lower())
        # Manager REC also proves failed evaluations when a worker REC was replaced.
        manager_failures=set()
        for line in rec.splitlines():
            if 'failed during evaluation of the remaining ensemble:' in line or 'runs failed for lambda,scale' in line:
                manager_failures.update(m.group(1).lower() for m in re.finditer(r'([^\s,:>]+)\s*:\s*([^\s,]+)',line))
        record=dict(stage=folder.name,started_local=local_time(status['started_at']).isoformat(),
            finished_local=local_time(status['finished_at']).isoformat(),engineering_status=status['engineering_status'],
            retained=int(member.state.eq('retained').sum()),requested=200,
            retained_pct=100*float(member.state.eq('retained').mean()),
            final_iteration=int(phi.iteration.iloc[-1]),manager_total_runs=int(phi.total_runs.iloc[-1]),
            initial_infeasible_candidates=initial['rejected_candidates'],
            phi_invalid_fraction=checks['ies_phi_finite']['actual'],
            full_selected_phi=selection.get('selected_phi'),selected_realization=selection.get('realization'),
            unclassified_member_table=int(member.state.eq('other_dropped').sum()),
            unclassified_with_manager_failure_evidence=len(set(member.loc[member.state.eq('other_dropped'),'real_name'].str.lower()) & manager_failures))
        stages.append(record)
    stage_table=pd.DataFrame(stages)
    stage_table.to_csv(OUT/'stage_events.csv',index=False)

    # Read the frozen explicit treatment map, never infer from number order.
    cal_dataset=next(d for d in design['datasets'] if d['roles'].get('calibration'))
    metadata=pd.read_csv(ROOT/cal_dataset['bundle_path']/'treatment_metadata.csv').rename(columns={'treatment':'trno'})
    treatments=metadata[metadata.trno.isin(final.trno.unique())][['trno','water_level','nitrogen_level']].rename(columns={'water_level':'water','nitrogen_level':'nitrogen'})
    assert set(treatments.trno)==set(final.trno)
    harvest=final[final.variable.eq('HPODW')].groupby('trno')[['observed','simulated']].sum().reset_index().merge(treatments,on='trno',validate='one_to_one')
    harvest['relative_bias_pct']=100*(harvest.simulated/harvest.observed-1)
    harvest.to_csv(OUT/'calibration_harvest_totals.csv',index=False)
    cumulative=evaluation[evaluation.variable.eq('CHPDT')].sort_values('date').groupby(['season_id','dataset_role','trno']).tail(1)
    cumulative[['season_id','dataset_role','trno','date','observed','simulated']].to_csv(OUT/'evaluation_last_cumulative_dry.csv',index=False)
    nitrogen=final[final.variable.isin(['LEAF_N_PCT','STEM_N_PCT','FRUIT_N_PCT'])].merge(treatments,on='trno',validate='many_to_one').groupby(['variable','nitrogen'])[['observed','simulated']].mean().reset_index()
    nitrogen.to_csv(OUT/'calibration_nitrogen_response.csv',index=False)

    bounds=pd.read_csv(ROOT/f"data/parameter_registry/bounds_frozen/eggplant/{design['bounds_id']}.csv")
    params=pd.read_csv(RUN/'final_parameters.csv').merge(bounds[['name','init','lower','upper','status']],on='name',validate='one_to_one')
    assert len(params)==len(bounds) and params.value.between(params.lower-1e-9,params.upper+1e-9).all()
    params['eligible_active']=params.name.isin(design['eligible_active_parameters'])
    params['range_position']=(params.value-params.lower)/(params.upper-params.lower).replace(0,np.nan)
    params['near_bound_5pct']=params.eligible_active & ((params.range_position<=.05)|(params.range_position>=.95))
    params.to_csv(OUT/'final_parameter_review.csv',index=False)
    phi0=float(tables.loc[tables.comparison.eq('baseline'),'weighted_phi'].sum())
    phif=float(tables.loc[tables.comparison.eq('final_calibration'),'weighted_phi'].sum())
    assert np.isclose(phif,state['final_calibration_phi'])
    selection=read_json(RUN/final_stage/'selection.json')
    review=dict(run_id=RUN_ID,data_status='science_pending',execution_completed=True,
        scientific_fit_assessment='needs_revision',baseline_phi=phi0,final_phi=phif,
        reduction_pct=100*(1-phif/phi0),calibration_rows=len(final),evaluation_rows=len(evaluation),
        validation_rows=int(evaluation.dataset_role.eq('validation').sum()),evaluation_unmatched=0,
        duration_hours=(local_time(state['finished_at'])-local_time(state['started_at'])).total_seconds()/3600,
        final_realization=selection['realization'],final_iteration=selection['iteration'],
        deterministic_phi_absolute_difference=abs(phif-selection['selected_phi']),
        validation_used_for_selection=state['validation_used_for_selection'],
        near_bound_parameters=params.loc[params.near_bound_5pct,'name'].tolist(),
        final_fruit_pool_rows=int(final.variable.eq('FRUIT_N_PCT').sum()),
        inputs={str(p.relative_to(ROOT)):sha(p) for p in [CONFIG/'design.json',CONFIG/'calibration_observations.csv',CONFIG/'locked_evaluation_observations.csv',
            ROOT/cal_dataset['bundle_path']/'treatment_metadata.csv',
            ROOT/f"data/parameter_registry/bounds_frozen/eggplant/{design['bounds_id']}.csv",
            RUN/'pipeline_status.json',RUN/'final_parameters.csv',RUN/'evaluation_comparison.csv',RUN/final_stage/'selected_deterministic/last_comparison.csv',Path(__file__).resolve()]})
    (OUT/'review_summary.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in review.items() if k!='inputs'},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
