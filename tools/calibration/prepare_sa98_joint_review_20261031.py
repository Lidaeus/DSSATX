"""Build an unapproved review package only; never calls DSSAT, PEST or freeze_bounds."""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.param_registry import PHYSICAL_BOUNDS
from src.sensitivity.strict_forward import read_genotype_parameters

OUT = ROOT / 'configs/calibration_proposals/eggplant_26sp_cal25sp_val_sa98_review_20261031'
SA = ROOT / 'workspace/runs/sa_25sp_observed_morris86_seed20261030_r30_refNguard_20261030/review_20261030/paper_data'
BOUNDS = ROOT / 'data/parameter_registry/bounds_frozen/eggplant'
SA_ID = 'eggplant_25sp_observed_morris_expanded86_refNguard_20261030'
REFS = {
    'C31': 'eggplant_full_gen_final_calib_scheme1_tb1_200x6_20260927',
    'joint67': 'eggplant_26sp_n012_c31_joint67_20261011',
    'all12_65': 'eggplant_26sp_all12_posterior_joint65_20261012',
}


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p, x): p.write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def main():
    if (OUT/'review_receipt.json').exists():
        raise FileExistsError('Never overwrite a completed review package')
    OUT.mkdir(parents=True, exist_ok=True)
    sources = {}; datasets = []; evidence = []
    def bind(p):
        p = Path(p); sources[str(p.relative_to(ROOT)).replace('\\', '/')] = sha(p)
    sm = json.loads((SA/'paper_data_manifest.json').read_text(encoding='utf-8'))
    for a in sm['artifacts']: assert sha(SA/a['path']) == a['sha256']
    bind(SA/'paper_data_manifest.json'); bind(SA/'balanced_rankings.csv')
    ranking = pd.read_csv(SA/'balanced_rankings.csv')
    original = pd.read_csv(BOUNDS/(SA_ID+'.csv')).fillna(''); bind(BOUNDS/(SA_ID+'.csv'))
    genetic = original[original.location.isin(['CUL', 'ECO', 'SPE'])].copy()
    assert len(genetic) == 86 and set(ranking.parameter) == set(genetic.name)
    n98 = int(np.flatnonzero(ranking.cumulative.ge(.98))[0]+1)
    selected = ranking.head(n98).parameter.tolist(); assert n98 == 40
    params = genetic.copy(); params['sa_init'] = params.init
    params['status'] = np.where(params.name.isin(selected), 'active', 'fixed')
    params.loc[params.status.eq('fixed'), ['lower', 'upper']] = params.loc[params.status.eq('fixed'), 'init'].to_numpy()[:, None].repeat(2, axis=1)
    params['proposal_reason'] = 'SA98 membership; retain audited screening range'
    params.loc[params.status.eq('fixed'), 'proposal_reason'] = 'Outside SA98; fixed at declared screening center'
    # No observation of terminal leaf formation: retain the repository running contract.
    params.loc[params.name.eq('FL-VS'), ['init', 'lower', 'upper']] = 100.0
    params.loc[params.name.eq('FL-VS'), 'proposal_reason'] = 'Fixed structural timing; no terminal-leaf observation; AGENTS contract=100'
    # The unselected stem endpoint is fixed at .645. Keep a positive root fraction.
    params.loc[params.name.eq('FRLFF'), 'upper'] = .35
    params.loc[params.name.eq('FRLFF'), 'init'] = (.08+.35)/2
    params.loc[params.name.eq('FRLFF'), 'proposal_reason'] = 'FRSTMF fixed .645; upper .35 leaves endpoint root fraction >=.005'
    params['mode'] = 'draft_genotype_joint_cal26_val25'; params['approved'] = False
    params['executable'] = False
    refs = {}
    for key, name in REFS.items():
        p = BOUNDS/(name+'.csv'); bind(p)
        table = pd.read_csv(p).fillna(''); table.name = table.name.str.upper(); refs[key] = table.set_index('name')
    extra = refs['all12_65'].loc['FL-LF'].to_dict()
    extra.update(name='FL-LF', init=132.5, lower=45., upper=220., status='active', sa_init=np.nan,
                 proposal_reason='Outside Morris86; leaf-lifespan supplementary parameter from all12_65, explicitly subject to approval',
                 mode='draft_genotype_joint_cal26_val25', approved=False, executable=False)
    strict_extra = extra.copy()
    strict_extra.update(init=400., lower=400., upper=400., status='fixed',
                        proposal_reason='Strict40 alternative: FL-LF not screened; retain current bundle400')
    strict40 = pd.concat([params, pd.DataFrame([strict_extra])], ignore_index=True)
    params = pd.concat([params, pd.DataFrame([extra])], ignore_index=True)
    strict40.to_csv(OUT/'bounds_proposal_strict40.csv', index=False, encoding='utf-8-sig')
    params.to_csv(OUT/'bounds_proposal_recommended41.csv', index=False, encoding='utf-8-sig')
    assert params.status.eq('active').sum() == 41
    for row in params.itertuples():
        assert row.lower <= row.init <= row.upper
        if row.name in PHYSICAL_BOUNDS:
            a, b = PHYSICAL_BOUNDS[row.name]; assert a <= row.lower <= row.upper <= b, row.name
    active = params[params.status.eq('active')].copy()
    comparison = active[['name', 'location', 'init', 'lower', 'upper', 'proposal_reason']].merge(
        ranking[['parameter', 'rank', 'score', 'cumulative']], left_on='name', right_on='parameter', how='left')
    comparison = comparison.merge(genetic[['name', 'lower', 'upper']], on='name', how='left', suffixes=('', '_sa'))
    for key, table in refs.items():
        comparison = comparison.merge(table.reset_index()[['name', 'init', 'lower', 'upper', 'status']].rename(
            columns={x:f'{key}_{x}' for x in ['init', 'lower', 'upper', 'status']}), on='name', how='left')
    comparison.sort_values(['rank', 'name'], na_position='last').to_csv(OUT/'parameter_range_comparison.csv', index=False, encoding='utf-8-sig')
    for season, role in [('25SP', 'validation'), ('26SP', 'calibration')]:
        code = 'XXQL2501' if season == '25SP' else 'XXQL2601'
        p = ROOT/f'data/user/experiments/{code.lower()}_refreshed_20261027'
        m = json.loads((p/'input_manifest.json').read_text(encoding='utf-8'))
        for f in m['files']: assert sha(p/f['name']) == f['sha256'], p/f['name']
        bind(p/'input_manifest.json')
        meta = pd.read_csv(p/'treatment_metadata.csv'); trts = sorted(meta.treatment.astype(int))
        assert len(trts) == (8 if season=='25SP' else 12)
        datasets.append(dict(season_id=season, experiment_code=code, bundle_path=str(p.relative_to(ROOT)).replace('\\','/'),
                             bundle_manifest_sha256=sha(p/'input_manifest.json'), role=role, treatments=trts,
                             verified_bundle_files=len(m['files'])))
        for f in ['observation_uncertainty.csv', 'plant_npk_source_values.csv', 'soil_water_observations.csv', 'treatment_metadata.csv', 'SOIL.SOL', code+'.TMX']:
            bind(p/f)
        u = pd.read_csv(p/'observation_uncertainty.csv')
        for row in u.itertuples():
            if row.variable not in ['LAID','LWAD','SWAD','CHTD','HFPOW','CHFPW','HPODW','CHPDT']: continue
            evidence.append(dict(season_id=season, role=role, trno=int(row.trno), date=row.date, variable=row.variable,
                observed=float(row.unrounded_source_mean), raw_sd=float(row.raw_sd), n_rep=int(row.n_rep),
                source_file=str((p/'observation_uncertainty.csv').relative_to(ROOT)).replace('\\','/'), source_rule='unrounded_source_mean'))
        n = pd.read_csv(p/'plant_npk_source_values.csv')
        for (tn, date, organ), g in n.groupby(['trno','date','organ']):
            vals=pd.to_numeric(g.N, errors='raise')/10.
            evidence.append(dict(season_id=season, role=role, trno=int(tn), date=date,
                variable={'叶':'LEAF_N_PCT','茎':'STEM_N_PCT','果':'FRUIT_N_PCT'}[organ],
                observed=float(vals.mean()), raw_sd=float(vals.std(ddof=1)), n_rep=int(vals.count()),
                source_file=str((p/'plant_npk_source_values.csv').relative_to(ROOT)).replace('\\','/'), source_rule='N mg/g dry mass /10 = dry mass percent; mean over replicates'))
        water = pd.read_csv(p/'soil_water_observations.csv')
        water = water[water.phi_role.eq('soil_water_phi')]
        for row in water.itertuples():
            evidence.append(dict(season_id=season, role=role, trno=int(row.trno), date=row.date, variable='VWC',
                observed=row.vwc_mean, raw_sd=row.vwc_sd, n_rep=int(row.n_rep), depth_label=row.depth_label,
                depth_top_cm=row.depth_top_cm, depth_bottom_cm=row.depth_bottom_cm,
                dssat_layer_weights=row.dssat_layer_weights,
                source_file=str((p/'soil_water_observations.csv').relative_to(ROOT)).replace('\\','/'), source_rule='post-planting measured layer; native output depth weights'))
        a=pd.read_csv(p/'FileA_values.csv')
        for row in a.itertuples():
            pdte=pd.to_datetime(str(int(row.PDAT)), format='%y%j'); adte=pd.to_datetime(str(int(row.ADAT)), format='%y%j')
            evidence.append(dict(season_id=season, role=role, trno=int(row.TRNO), date=str(adte.date()), variable='ADAP',
                observed=float((adte-pdte).days), raw_sd=0., n_rep=1,
                source_file=str((p/'FileA_values.csv').relative_to(ROOT)).replace('\\','/'), source_rule='ADAT-PDAT; shared phenology record, no independent replication claimed'))
    cat=pd.DataFrame(evidence); assert np.isfinite(cat.observed).all()
    cat.to_csv(OUT/'observation_evidence_catalog.csv', index=False, encoding='utf-8-sig')
    rows=[]
    policy={
        'FINAL_FRESH_YIELD':(25.,'CHFPW',500.,.15,'quadratic'),
        'FINAL_DRY_YIELD':(20.,'CHPDT',25.,.20,'quadratic'),
        'HARVEST_DRY_CUMULATIVE_EARLY':(5.,'CHPDT',25.,.20,'pseudo_huber'),
        'HARVEST_DRY_EVENT':(10.,'HPODW',25.,.20,'pseudo_huber'),
        'CANOPY_LAI':(10.,'LAID',.05,.10,'pseudo_huber'),
        'LEAF_DRY_MASS':(6.,'LWAD',20.,.15,'pseudo_huber'),
        'STEM_DRY_MASS':(6.,'SWAD',25.,.15,'pseudo_huber'),
        'HEIGHT':(3.,'CHTD',.03,.10,'pseudo_huber'),
        'LEAF_N_CONCENTRATION':(3.,'LEAF_N_PCT',.15,.10,'pseudo_huber'),
        'STEM_N_CONCENTRATION':(3.,'STEM_N_PCT',.15,.10,'pseudo_huber'),
        'FRUIT_N_CONCENTRATION':(2.,'FRUIT_N_PCT',.15,.20,'pseudo_huber'),
        'ANTHESIS':(3.,'ADAP',2.,0.,'quadratic'),
        'SOIL_WATER':(2.,'VWC',.01,.08,'quadratic'),
        'W_SIGNED_CONTRAST':(1.,'W_FRESH_CONTRAST',1500.,.20,'quadratic'),
        'N_ADJACENT_SIGNED_CONTRAST':(1.,'N_ADJACENT_FRESH_CONTRAST',1500.,.20,'quadratic'),
    }
    q=cat[cat.role.eq('calibration')].copy()
    for fam,(budget,var,floor,cv,loss) in policy.items():
        if fam.endswith('CONTRAST'):continue
        g=q[q.variable.eq(var)].copy()
        if fam in ['FINAL_FRESH_YIELD','FINAL_DRY_YIELD']:
            g=g[g.date.eq(g.groupby('trno').date.transform('max'))]
        elif fam=='HARVEST_DRY_CUMULATIVE_EARLY':
            g=g[~g.date.eq(g.groupby('trno').date.transform('max'))]
        g['family']=fam;rows.extend(g.to_dict('records'))
    targets=pd.DataFrame(rows)
    fresh=targets[targets.family.eq('FINAL_FRESH_YIELD')].set_index('trno')
    meta=pd.read_csv(ROOT/datasets[1]['bundle_path']/'treatment_metadata.csv').set_index('treatment')
    by={(r.water_level,r.nitrogen_level):int(i) for i,r in meta.iterrows()}
    for fam,pairs in [
        ('W_SIGNED_CONTRAST',[(by[w,n],by['W1',n]) for n in ['N0','N1','N2','N3'] for w in ['W2','W3']]),
        ('N_ADJACENT_SIGNED_CONTRAST',[(by[w,f'N{i+1}'],by[w,f'N{i}']) for w in ['W1','W2','W3'] for i in range(3)])]:
        for hi,lo in pairs:
            h,l=fresh.loc[hi],fresh.loc[lo]
            rows.append(dict(season_id='26SP',role='calibration',trno=hi,paired_trno=lo,date=h.date,
                variable=policy[fam][1],observed=float(h.observed-l.observed),raw_sd=float(np.hypot(h.raw_sd,l.raw_sd)),n_rep=1,
                source_file=h.source_file,source_rule=f'signed final fresh yield difference TN{hi}-TN{lo}; zero inter-treatment covariance assumed',family=fam))
    targets=pd.DataFrame(rows)
    for fam,(budget,var,floor,cv,loss) in policy.items():
        ix=targets.family.eq(fam); g=targets[ix]
        targets.loc[ix,'sigma_eff']=np.sqrt(g.raw_sd**2+floor**2+(cv*g.observed.abs())**2)
        # Equal strata: treatment; contrast family pairs; VWC treatment x depth.
        keys=['trno','depth_label'] if fam=='SOIL_WATER' else ['trno','paired_trno'] if fam.endswith('CONTRAST') else ['trno']
        group=g.groupby(keys,dropna=False)
        m=group.ngroups; nc=group['observed'].transform('size')
        targets.loc[ix,'family_budget']=budget
        targets.loc[ix,'base_weight']=1/targets.loc[ix,'sigma_eff']
        targets.loc[ix,'budget_multiplier']=np.sqrt(budget/(m*nc))
        targets.loc[ix,'proposed_weight']=targets.loc[ix,'base_weight']*targets.loc[ix,'budget_multiplier']
        targets.loc[ix,'loss']=loss;targets.loc[ix,'huber_delta']=1.5 if loss=='pseudo_huber' else np.nan
        assert np.isclose(np.square(targets.loc[ix,'proposed_weight']*targets.loc[ix,'sigma_eff']).sum(),budget)
    targets['approved']=False;targets['execution_enabled']=False
    targets.to_csv(OUT/'proposed_calibration_targets.csv', index=False, encoding='utf-8-sig')
    assert len(targets)==665 and set(targets.season_id)=={'26SP'}
    assert targets.proposed_weight.gt(0).all() and np.isfinite(targets.proposed_weight).all()
    policy_rows=[dict(family=fam,budget=b,variable=v,floor=fl,cv=cv,loss=loss,huber_delta=1.5 if loss=='pseudo_huber' else None,
        n_targets=int(targets.family.eq(fam).sum()),n_eff=1,approved=False) for fam,(b,v,fl,cv,loss) in policy.items()]
    pd.DataFrame(policy_rows).to_csv(OUT/'proposed_objective_policy.csv',index=False,encoding='utf-8-sig')
    fixed=[('SASC_RATIO',.90,'SAOC times .90 at each layer; runtime only; user prior decision'),
           ('ICNS_25SP',1.,'No extra scaling of current measured initial mineral N'),('ICNS_26SP',1.,'No extra scaling of current measured initial mineral N'),
           ('PAGE_25SP',25.,'Current bundle planting field'),('PAGE_26SP',24.,'Current bundle planting field'),
           ('PENV_25SP',20.,'Current bundle planting field'),('PENV_26SP',20.,'Current bundle planting field'),
           ('SOIL_SLDR',.65,'Current SOIL.SOL; do not use historical fitted .873538'),('SOIL_SLU1',5.5,'Current SOIL.SOL'),
           ('SLPF_25SP',.933,'Current bundle; inherited empirical setting, not a field measurement'),('SLPF_26SP',.933,'Current bundle; inherited empirical setting, not a field measurement'),
           ('SOIL_SALB',.13,'Current SOIL.SOL'),('SOIL_SLRO',75.,'Current SOIL.SOL'),('SOIL_SLNF',1.,'Current SOIL.SOL'),
           ('KEP',.70,'Current SPE canopy/soil evaporation coefficient; keep empirical process setting fixed'),
           ('TAV',20.,'Current WTH header'),('AMP',6.,'Current WTH header'),('PPOP',2.7,'Current TMX, plants/m2'),('PPOE',2.7,'Current TMX, plants/m2')]
    pd.DataFrame(fixed,columns=['name','proposed_value','basis']).to_csv(OUT/'proposed_fixed_non_genetic.csv',index=False,encoding='utf-8-sig')
    # Freeze all readable untouched genotype fields as well, including those not in Morris86.
    genotype=read_genotype_parameters(ROOT/datasets[1]['bundle_path'])
    assert genotype==read_genotype_parameters(ROOT/datasets[0]['bundle_path'])
    fixed_rows=[];index=params.set_index('name');active_set=set(active.name)
    for name,value in genotype.items():
        if name in active_set:continue
        fixed_rows.append(dict(name=name,value=float(index.loc[name,'init']) if name in index.index else value,
            source='declared_SA_center_or_FLVS_contract' if name in index.index else 'unchanged_current_bundle_genotype'))
    pd.DataFrame(fixed_rows).to_csv(OUT/'proposed_fixed_genotype.csv',index=False,encoding='utf-8-sig')
    assert len(fixed_rows)==78
    pd.DataFrame(fixed_rows+[dict(name='FL-LF',value=400.,source='strict40_current_bundle')]).to_csv(
        OUT/'proposed_fixed_genotype_strict40.csv',index=False,encoding='utf-8-sig')
    binary=Path('C:/DSSAT48/DSCSM048.EXE'); binary_hash=sha(binary)
    assert binary_hash=='92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a'
    for ref in ['eggplant_26sp_all12_robust_joint65_200x5_20261012','eggplant_26sp_all12_cnc_joint69_200x5_20261014']:
        bind(ROOT/'configs/runs'/ref/'design.json');bind(ROOT/'workspace/runs'/ref/'pipeline_status.json')
    bind(ROOT/'workspace/runs/coord5_joint76_formal200x5_20261030_direct1043/run_manifest.json')
    bind(ROOT/'workspace/runs/coord5_joint76_formal200x5_20261030_direct1043/status.json')
    bind(Path(__file__))
    proposal=dict(schema='unapproved_calibration_review_v1',date='2026-10-31',approved=False,executable=False,
        science_status='science_pending',runtime_preflight_passed=False,model_runs_executed_by_preparation=0,
        datasets=datasets,sa98_parameter_count=40,sa98_cumulative_share=float(ranking.iloc[39].cumulative),
        recommended_active_count=41,strict_alternative_count=40,supplementary_parameter='FL-LF',
        active_parameters=active.name.tolist(),non_genetic_active_parameters=[],calibration_targets=665,
        validation_evidence_rows=int(cat.role.eq('validation').sum()),bounds_frozen=False,
        dssat_executable=str(binary),dssat_executable_sha256=binary_hash,
        execution=dict(ies_num_reals=200,noptmax=6,workers=6,seed=20261031,staged=False,no_noise=True,
          initial_distribution='199 global scrambled Sobol feasible points + declared center; no historical posterior import',
          maximum_native_initial_screen_candidates=2000,minimum_final_member_retention=.98),
        scientific_caveats=['SA was on 2025 validation environment, not calibration2026; no strict untouched blind validation claim',
          '98% covers three equally weighted treatment-mean responses only; does not certify organ-N sensitivity or all genetic parameters',
          'FRLFF constrained .08-.35 and FL-VS fixed100; SA original domain differs from proposed conditional domain',
          'FL-LF was not screened by Morris86; 41st parameter requires explicit user approval',
          'Current bundle SLPF .933 and hydraulic profile are inherited assumptions, not newly measured physiological constants'],
        observation_policy='uncertainty-normalized raw-scale composite objective; delta1.5 standard-residual pseudo-Huber on state/event targets; no residual-driven weights',
        parent_runtime_reusable_without_edits=False,source_hashes=sources)
    write(OUT/'proposal.json',proposal)
    # A review receipt asserts static checks, never native preflight or approval.
    artifacts={p.name:sha(p) for p in OUT.iterdir() if p.is_file()}
    write(OUT/'review_receipt.json',dict(approved=False,executable=False,static_checks_passed=True,
        native_forward_executed=False,input_files_checked=66,genetic_parameters_in_sa=86,active_recommended=41,
        active_strict=40,objective_budget_sum=sum(x[0] for x in policy.values()),calibration_targets=len(targets),
        validation_in_objective=False,artifact_hashes=artifacts))
    print(json.dumps(dict(output=str(OUT),active=41,strict=40,targets=len(targets),validation_rows=int(cat.role.eq('validation').sum()),
        objective_budget=sum(x[0] for x in policy.values()),native_runs=0),ensure_ascii=False))


if __name__=='__main__': main()
