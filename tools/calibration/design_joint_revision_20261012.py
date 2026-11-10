"""Build a review-only, fully specified objective and bounds proposal."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.common.param_registry import PHYSICAL_BOUNDS
from src.calibration import single_season_n as native

ID='joint65_yield_robust_revision_20261012'
OUT=ROOT/'configs/calibration_proposals'/ID
AUDIT=ROOT/'workspace/audits/joint_revision_truth_20261012'
OLD=ROOT/'configs/runs/eggplant_26sp_n012_rmse_joint65_200x5_20261012'
RUN=ROOT/'workspace/runs'/OLD.name

def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def loss_residual(r,kind,delta=.15):
    r=np.asarray(r,dtype=float)
    if kind=='quadratic':return r
    if kind!='pseudo_huber':raise ValueError(kind)
    # Stable signed sqrt[2 delta² (sqrt(1+(r/delta)²)-1)].
    return r*np.sqrt(2/(np.hypot(1,r/delta)+1))

def make_policy():
    rows=[
        ('CHPDT','FINAL_DRY_YIELD',35,9,'quadratic'),
        ('CHFPW','FINAL_FRESH_YIELD',35,9,'quadratic'),
        ('CHPDT','HARVEST_DRY_CUMULATIVE_EARLY',2,36,'pseudo_huber'),
        ('HPODW','HARVEST_DRY_EVENT',5,45,'pseudo_huber'),
        ('LAID','CANOPY_LAI',3,36,'pseudo_huber'),
        ('LWAD','LEAF_DRY_MASS',2,36,'pseudo_huber'),
        ('SWAD','STEM_DRY_MASS',3,36,'pseudo_huber'),
        ('CHTD','HEIGHT',1,36,'pseudo_huber'),
        ('LEAF_N_PCT','LEAF_N_CONCENTRATION',1.5,36,'pseudo_huber'),
        ('STEM_N_PCT','STEM_N_CONCENTRATION',1.5,36,'pseudo_huber'),
        ('FRUIT_N_PCT','FRUIT_N_CONCENTRATION',1,27,'pseudo_huber'),
        ('ADAP','ANTHESIS',1,9,'quadratic'),
        ('VWC','SOIL_WATER',4,135,'quadratic'),
        ('WB100_INTERVAL','WATER_BALANCE_100CM',2,18,'quadratic'),
        ('W_FRESH_CONTRAST','W_SIGNED_CONTRAST',1.5,6,'quadratic'),
        ('N_ADJACENT_FRESH_CONTRAST','N_ADJACENT_SIGNED_CONTRAST',1.5,6,'quadratic'),
    ]
    p=pd.DataFrame(rows,columns=['variable','family','phi_budget','n_targets','loss'])
    p['delta']=np.where(p.loss=='pseudo_huber',.15,np.nan)
    p['scale_policy']='frozen_calibration_family_mean'
    p.loc[p.family=='ANTHESIS','scale_policy']='fixed_2_days'
    p.loc[p.family.isin(['W_SIGNED_CONTRAST','N_ADJACENT_SIGNED_CONTRAST']),'scale_policy']='frozen_terminal_fresh_yield_mean'
    p['approved']=False
    assert p.phi_budget.sum()==100 and p.n_targets.sum()==516
    return p

def make_targets(policy):
    obs=pd.read_csv(OLD/'calibration_observations.csv').fillna('')
    final=obs[obs.family=='FINAL_FRESH_YIELD'].set_index('trno')
    rows=[]
    pairs=[('W_SIGNED_CONTRAST','W_FRESH_CONTRAST',h,l) for h,l in [(11,12),(9,12),(8,10),(7,10),(5,6),(4,6)]]
    pairs += [('N_ADJACENT_SIGNED_CONTRAST','N_ADJACENT_FRESH_CONTRAST',h,l) for h,l in [(10,12),(6,10),(8,11),(5,8),(7,9),(4,7)]]
    for family,var,h,l in pairs:
        a,b=final.loc[h],final.loc[l]
        sd=np.hypot(float(a.replicate_sd),float(b.replicate_sd))
        rows.append(dict(season_id='26SP',dataset_role='calibration',trno=h,paired_trno=l,date='2026-07-17',
            variable=var,family=family,observed=float(a.observed-b.observed),unit='kg fresh/ha',
            replicate_sd=sd,measurement_sigma_eff=sd,sigma_source='quadrature of measured SD; covariance unknown; diagnostic only',
            n_eff=1,source_file=str(a.source_file)+' | '+str(b.source_file),
            parent_observations=str(a.obsnme)+' | '+str(b.obsnme),observation_operator='actual-date cumulative mature fresh harvest difference',
            obsnme=f'draft_{var.lower()}_{h:02d}_{l:02d}'))
    with pd.option_context('future.no_silent_downcasting',True):
        obs=pd.concat([obs,pd.DataFrame(rows)],ignore_index=True).fillna('').infer_objects(copy=False)
    for row in policy.itertuples():
        mask=obs.family==row.family
        scale=2. if row.scale_policy=='fixed_2_days' else float(final.observed.mean()) if row.scale_policy=='frozen_terminal_fresh_yield_mean' else float(obs.loc[mask,'observed'].mean())
        obs.loc[mask,'fit_scale']=scale
        obs.loc[mask,'scale_policy']=row.scale_policy
        obs.loc[mask,'phi_budget']=row.phi_budget
        obs.loc[mask,'loss']=row.loss
        obs.loc[mask,'huber_delta']=row.delta
        # PEST consumes transformed residuals and zero observations.
        obs.loc[mask,'pest_obsval']=0.
        obs.loc[mask,'final_weight']=np.sqrt(row.phi_budget/row.n_targets)
    obs['approved']=False;obs['execution_enabled']=False
    assert len(obs)==516 and not obs.obsnme.duplicated().any()
    assert obs.dataset_role.eq('calibration').all() and set(obs.trno)==set(range(4,13))
    return obs

def score_case(case,targets,policy):
    comp=pd.read_csv(AUDIT/'cases'/case/'comparison.csv')
    v=comp.set_index('obsnme').simulated.to_dict()
    fresh=comp[comp.family=='FINAL_FRESH_YIELD'].set_index('trno').simulated
    output=targets.copy();sim=[]
    for row in output.itertuples():
        if row.family in ['W_SIGNED_CONTRAST','N_ADJACENT_SIGNED_CONTRAST']:
            sim.append(float(fresh.loc[row.trno]-fresh.loc[int(row.paired_trno)]))
        else:sim.append(float(v[row.obsnme]))
    output['simulated']=sim
    output['normalized_raw_residual']=(output.simulated-output.observed)/pd.to_numeric(output.fit_scale)
    output['pest_output']=0.
    for row in policy.itertuples():
        mask=output.family==row.family
        output.loc[mask,'pest_output']=loss_residual(output.loc[mask,'normalized_raw_residual'],row.loss)
    output['phi_contribution']=(output.pest_output*output.final_weight)**2
    scores=output.groupby('family').phi_contribution.sum().rename('new_phi').reset_index()
    scores['case']=case;scores['phi_share_pct']=100*scores.new_phi/scores.new_phi.sum()
    return output,scores

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    old=json.loads((OLD/'design.json').read_text(encoding='utf-8'))
    policy=make_policy();targets=make_targets(policy)
    policy.to_csv(OUT/'objective_policy.csv',index=False)
    targets.to_csv(OUT/'observation_catalog.csv',index=False)
    oldb=ROOT/'data/parameter_registry/bounds_frozen/eggplant'/(old['bounds_id']+'.csv')
    bounds=pd.read_csv(oldb).fillna('')
    base=pd.read_csv(AUDIT/'cases/seed_yield/_model/parameters.csv').set_index('name').value
    bounds['init']=bounds.name.map(base)
    changes={
        'FL-LF':(150.,400.,'150–380 grid: shorter progression improves allocation; 45–75 collapses canopy/yield with this seed'),
        'SENPOR_LATE':(.15,.28,'natural cumulative senescence anchor; .15–.25 grid favorable; .35 worsens canopy'),
        'RTNO3':(.003,.020,'allow supply limitation; .003 is executable but not independently beneficial for all targets'),
        'RWUMX':(.009,.020,'exclude .006 severe production collapse; .009–.012 tested and prior .020 reference retained'),
        'FRLFF':(.08,.30,'paired with FRSTMF under endpoint sum<=1; avoid negative root allocation'),
        'PROLFI':(.27,.32,'protein fraction, not nitrogen percent; measured leaf N supports a modest narrower prior'),
        'NMOBMX':(.08,.10,'retain tested restrained domain; start .09 rather than .0984'),
        'NVSMOB':(.25,.35,'trim high remobilization corner; start .30'),
        'PROLFF':(.215,.25,'allow smaller donor N pool; coupled PROLFF<=PROLFG<=PROLFI'),
        'PROSTF':(.07,.09,'raising donor floor is supported by .085 forward probe; coupled protein order'),
    }
    bounds['old_lower']=bounds.lower;bounds['old_upper']=bounds.upper
    bounds['reason']='Retain prior frozen working domain; initialize from physically feasible tested seed'
    for name,(lo,hi,reason) in changes.items():
        mask=bounds.name==name;assert mask.sum()==1
        bounds.loc[mask,['lower','upper']]=[lo,hi];bounds.loc[mask,'reason']=reason
    bounds['approved']=False;bounds['execution_enabled']=False
    for row in bounds.itertuples():
        assert np.isfinite(row.init) and row.lower<=row.init<=row.upper,(row.name,row.init,row.lower,row.upper)
        if row.name in PHYSICAL_BOUNDS:
            lo,hi=PHYSICAL_BOUNDS[row.name];assert lo<=row.lower<=row.upper<=hi
    assert len(bounds[bounds.status=='active'])==65
    assert base['FRSTMF']+base['FRLFF']<=1
    for organ in ['LF','ST','RT']:
        assert base['PRO'+organ+'F']<=base['PRO'+organ+'G']<=base['PRO'+organ+'I']
    bounds.to_csv(OUT/'bounds_proposal.csv',index=False)
    # No proposal bounds are promoted to bounds_frozen in this script.
    score_frames=[];rank=[]
    summary=json.loads((AUDIT/'audit_summary.json').read_text(encoding='utf-8'))
    for item in summary['results']:
        if not item.get('complete'):continue
        case=item['case'];output,scores=score_case(case,targets,policy)
        score_frames.append(scores)
        rank.append(dict(case=case,phi=float(scores.new_phi.sum()),n=len(output),
            final_yield_phi=float(scores.loc[scores.family.isin(['FINAL_DRY_YIELD','FINAL_FRESH_YIELD']),'new_phi'].sum())))
        if case in ['baseline','seed_yield','seed_water','seed_broad','fl55_sen0.280']:
            output.to_csv(OUT/(case+'_objective_preflight.csv'),index=False)
    scores=pd.concat(score_frames,ignore_index=True)
    scores.to_csv(OUT/'grid_new_objective_contributions.csv',index=False)
    pd.DataFrame(rank).sort_values('phi').to_csv(OUT/'grid_new_objective_ranking.csv',index=False)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    files={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in OUT.glob('*.csv')}
    design=dict(schema='review_joint65_signed_pseudohuber_v1',design_id=ID,status='review_pending',approved=False,executable=False,
        parent_design=str((OLD/'design.json').relative_to(ROOT)),parent_design_sha256=sha(OLD/'design.json'),
        proposed_bounds_id='eggplant_26sp_n012_yield_robust_joint65_20261012',bounds_state='proposal_only_not_frozen',
        active_parameters=old['active_parameters'],active_parameter_count=65,target_count=516,family_count=16,phi_budget_total=100,
        datasets=old['datasets'],dssat_executable=old['dssat_executable'],dssat_executable_sha256=old['dssat_executable_sha256'],
        fixed_environment=old['fixed_environment'],model_method='R',noptmax=5,ies_num_reals=200,workers=6,staged_calibration=False,
        objective_equation='sum_k B_k/n_k * sum_i L_k((simulated_i-observed_i)/frozen_scale_k)',
        robust_loss='L=2*delta^2*(sqrt(1+(r/delta)^2)-1), delta=0.15; final yields/soil/WB/anthesis/signed contrasts remain quadratic',
        pest_encoding='obsval=0; model output signed_sqrt(L); PEST weight=sqrt(B_k/n_k); raw predictions separately retained',
        signed_contrasts='6 W contrasts and 6 adjacent N contrasts; measured difference, common terminal fresh mean scale; no minimum-effect inequality',
        selection_rule='minimum complete fixed 516-row objective among physical-valid candidates; no water/N direction/magnitude gate',
        correlations='fresh/dry yield, cumulative/event harvest, organ mass/concentration, VWC/WB and signed contrasts are composite priorities, not independent evidence',
        native_preflight_cases=summary['case_count'],native_complete_cases=summary['complete_cases'],
        preflight_scope='calibration-only finite forward grid and exact 516-row objective encoding; NOT a 200-member ensemble or IES startup preflight',
        joint_constraints=['FRSTMF+FRLFF<=1 after fixed-width injection','PROLFF<=PROLFG<=PROLFI','PROSTF<=PROSTG<=PROSTI','PRORTF<=PRORTG<=PRORTI','PROSHF<=PROSHI; PROSHG fixed placeholder is not a donor-pool constraint','ordered temperature and stress arrays; inherited physical limits'],
        initialization=dict(base='tested seed_yield (no validation ranking)',reference_seeds=['seed_water','seed_broad'],
            members=200,base_members=1,reference_members=2,local_members=147,global_members=50,
            local_sampling='rejection sampling around tested feasible seed; support ±10% revised full domain, intersect bounds; no clipping',
            global_sampling='fixed Sobol ordinal order; screen only constraints and complete same-date operators; do not rank by residuals',
            out_of_bounds_old_candidate='local_00086 kept only as diagnostic reference; endpoint FRSTMF+FRLFF=1.018214 so not inserted unchanged'),
        ies_settings=dict(initial_lambda=100,lambda_multipliers=[.1,1.,10.],step_multipliers=[.05,.1,.25],no_noise=True,minimum_member_retention=.98),
        engineering_plan=['freeze approved bounds under NEW id only','implement NEW versioned objective adapter; sealed rmse_joint.py stays unchanged',
            'validate 200 native initial members: all 516 actual-date targets finite, fruit pool exists, input readback passes',
            'during IES reject/shorten infeasible candidate steps; never fill a missing fruit concentration with zero or shift its date',
            'record member retention/failure provenance; engineering failure remains explicit, not called scientific success',
            'after deterministic ranking assess all held-out seasons once; report raw RMSE/NRMSE/d/R2/NSE/MAE/MBE alongside new Phi'],
        monitoring='confirm startup only; no continuous progress monitoring',runtime_implementation_pending=True,proposal_file_sha256=files,
        inherited_runtime_hashes=old['runtime_hashes'])
    dump(OUT/'design.json',design)
    # Verify exact objective encoding and dimensional closure without PEST.
    r=np.array([-1.,-.15,-1.e-8,0.,1.e-8,.15,1.]);z=loss_residual(r,'pseudo_huber')
    expected=2*.15**2*(np.hypot(1,r/.15)-1)
    assert np.allclose(z*z,expected,rtol=1e-10,atol=1e-15)
    assert np.allclose(z,-loss_residual(-r,'pseudo_huber'))
    assert np.allclose(loss_residual(r,'quadratic'),r)
    checks=dict(status='passed_review_only',targets=516,budget_sum=100,active_parameters=65,
        exact_objective_encoding=True,robust_sign_and_near_zero_checks=True,physical_bounds_and_seed_joint_checks=True,
        original_phi_reproduced=float(pd.read_csv(AUDIT/'cases/baseline/metrics.csv').old_phi.sum()),
        source_runtime_changes=summary['sealed_runtime_changes'],ensemble_preflight=False,formal_run_started=False)
    dump(OUT/'proposal_validation.json',checks)
    dump(AUDIT/'source_provenance.json',dict(official_source_commit='25c93b9a2f73f8ec45bf441b198dac5fb7b22849',
        note='Official source snapshot is not asserted to be the exact executable build commit; actual binary perturbations complement reader inspection',
        binary_sha256=old['dssat_executable_sha256'],sources=[dict(file=p.name,url='https://github.com/DSSAT/dssat-csm-os/blob/25c93b9a2f73f8ec45bf441b198dac5fb7b22849/'+('SPAM/' if p.name in ['ETPHOT.for','ETPHR.for'] else 'Plant/FORAGE/' if p.name=='for_rstages.for' else 'Plant/CROPGRO/')+p.name,sha256=sha(p)) for p in (AUDIT/'source').glob('*.for')]))
    print(json.dumps(checks,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
