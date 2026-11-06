"""Prepare a review-only calibration proposal; never launch DSSAT or PEST++."""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.input_manifest import verify_manifest_integrity
from src.common.param_registry import PHYSICAL_BOUNDS
from src.calibration import build_pest as bp

ID = 'eggplant_26sp_n012_review_20261011'
OUT = ROOT / 'configs/calibration_proposals' / ID
C31 = 'full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927'
BOUND = 'eggplant_full_gen_final_calib_scheme1_tb1_200x6_20260927'
CAL = [4, 5, 6, 7, 8, 9, 10, 11, 12]
FAMILY = {
    'LAID': ('CANOPY_LAI', 1., .05, .10),
    'LWAD': ('LEAF_DRY_MASS', .75, 20., .15),
    'SWAD': ('STEM_DRY_MASS', .75, 25., .15),
    'CHTD': ('HEIGHT', .25, .03, .10),
    'HPODW': ('HARVEST_DRY_EVENT', 2., 25., .20),
    'VWC': ('SOIL_WATER', .5, .01, .08),
    'LEAF_N_PCT': ('LEAF_N_CONCENTRATION', 1., .15, .10),
    'STEM_N_PCT': ('STEM_N_CONCENTRATION', 1., .15, .10),
    'FRUIT_N_PCT': ('FRUIT_N_CONCENTRATION', .75, .15, .20),
}
STAGES = {
    'S1_canopy': 'EM-FL FL-SH FL-SD LFMAX SLAVR SIZLF KCAN TB1 TB2 TO11 TO12 TM1 TM2 LNGSH RHGHT FRLFF FRSTMF VSSINK PGEFF CMOBMX SENRTE SENDAY SENRT2 SENPOR_LATE SENMAX_LATE'.split(),
    'S2_nitrogen': 'LNREF NSLOPE NSTFAC RTNO3 RTNH4 NMOBMX NVSMOB NRCVR PROLFF PROLFG PROLFI PROSTF PROSTG PROSTI FNPGN1 FNPGN2'.split(),
    'S3_water_fruit': 'ATOP DSWBAR RWDTH RWUMX SWBAR_REC YSWBAR_MID XFRT XMAGE SFDUR PODUR PROSHI PROSHF'.split(),
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_json(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def read_native(p):
    """Read printed daily outputs with run and treatment identity."""
    run = tn = None
    header = None
    rows = []
    for line in Path(p).read_text(errors='replace').splitlines():
        m = re.match(r'\*RUN\s+(\d+)', line)
        if m:
            run = int(m.group(1)); header = None
        m = re.match(r'\s*TREATMENT\s+(\d+)', line)
        if m:
            tn = int(m.group(1))
        if line.startswith('@YEAR'):
            header = line.lstrip('@').split()
        elif header and re.match(r'\s*20\d{2}\s+\d+', line):
            values = line.split()
            if len(values) != len(header):
                raise ValueError(f'Native width/column mismatch: {p}')
            r = dict(zip(header, map(float, values)))
            r.update(run=run, trno=tn)
            r['date'] = (pd.Timestamp(int(r['YEAR']), 1, 1)+pd.Timedelta(days=int(r['DOY'])-1)).strftime('%Y-%m-%d')
            rows.append(r)
    frame = pd.DataFrame(rows)
    if frame.duplicated(['trno', 'date']).any():
        raise ValueError('Duplicate native treatment/date')
    return frame


def parse_pst(p):
    block=p.read_text(encoding='utf-8-sig').split('* parameter data')[1].split('*')[0]
    return pd.DataFrame([dict(key=f[0].upper(), transform=f[1], pst_init=float(f[3]), pst_lower=float(f[4]), pst_upper=float(f[5]))
        for line in block.splitlines() if len(f:=line.split())>=7])


def canonical_values():
    vals = {r['name'].upper(): r['init'] for r in bp.parse_cul_params('TM0008', allow_all_flagged=True)}
    vals.update(bp._read_eco_init_values('TM0001'))
    vals.update(bp._read_spe_temp_init_values())
    vals.update(bp._read_spe_direct_init_values())
    lines=(ROOT/'data/templates/genotype/TMGRO048.SPE.base').read_text().splitlines()
    rules = {
        'SENRTE,SENRT2': ['SENRTE','SENRT2','SENDAY'],
        'ICMP,TCMP':['ICMP','TCMP'],
        'XSWBAR(1-5)':['ignore','ignore','SWBAR_REC'],
        'YSWBAR(1-5)':['ignore','ignore','YSWBAR_MID'],
    }
    for marker, names in rules.items():
        line = next(l for l in lines if marker in l)
        fields=line.split()
        for i,name in enumerate(names):
            if name!='ignore': vals[name]=float(fields[i])
    i=next(i for i,l in enumerate(lines) if 'SENPOR.........' in l)
    fields=lines[i+1].split()
    vals.update(SENPOR_LATE=float(fields[3]), SENMAX_LATE=float(fields[7]))
    return {k.upper():float(v) for k,v in vals.items()}


def parameters():
    original=ROOT/f'data/parameter_registry/bounds_frozen/eggplant/{BOUND}.csv'
    b=pd.read_csv(original).fillna('')
    b['key']=b.name.str.upper()
    effective=parse_pst(ROOT/f'workspace/runs/{C31}/{C31}.pst')
    comparison=b.merge(effective,on='key',how='left')
    for bid in ['eggplant_full_gen_final_uncertainty_13trt_20260924','eggplant_full_gen_final_calib_200x6_20260926']:
        prior=pd.read_csv(ROOT/f'data/parameter_registry/bounds_frozen/eggplant/{bid}.csv')
        prior['key']=prior.name.str.upper()
        comparison=comparison.merge(prior[['key','lower','upper','status']].rename(columns={k:f'{bid}_{k}' for k in ['lower','upper','status']}),on='key',how='left')
    values=canonical_values()
    active={name:stage for stage,names in STAGES.items() for name in names}
    records=[]
    for r in b.to_dict('records'):
        name=r['key']
        if r['location'] not in ['CUL','ECO','SPE']:
            continue
        # Fixed values come from the current baseline, never old fitted IC/soil.
        if name not in values:
            if name in active: raise ValueError(f'No baseline parser for active {name}')
            continue  # The unmodified bundle template supplies this fixed value.
        value=values[name]
        new=dict(r);new.pop('key')
        new['name']=name; new['file']=f'TMGRO048.{r["location"]}.base'
        new['cultivar']='TM0008';new['ecotype']='TM0001';new['mode']='eggplant_stage2'
        if name in active:
            new.update(status='active',init=(float(r['lower'])+float(r['upper']))/2)
            rationale='C31 frozen scientific domain; no posterior +/-15% tightening'
        else:
            new.update(status='fixed',init=value,lower=value,upper=value)
            rationale='Current canonical template; no root/P or weak-structure joint release'
        new.update(proposed_stage=active.get(name,'fixed'),rationale=rationale,baseline_value=value,
            init_source='domain_midpoint' if name in active else 'current_canonical_template')
        records.append(new)
    # PROSHG is absent from the official PODS nitrogen calculation. PROSHF,
    # present in PODS/GROW, controls mobilizable fruit N and is added explicitly.
    records.append(dict(name='PROSHF',init=.11,lower=.099,upper=.121,status='active',pargp='SPE_Compo',location='SPE',file='TMGRO048.SPE.base',cultivar='TM0008',ecotype='TM0001',mode='eggplant_stage2',proposed_stage='S3_water_fruit',rationale='Registry DEFAULT_BOUNDS; fruit N minimum/mobilization; new proposal',baseline_value=values['PROSHF'],init_source='registry_default'))
    # Keep every independent draw ordered, without silently clipping draws.
    for r in records:
        if r['name']=='PROSTG': r['upper']=.16;r['init']=.13;r['rationale']='C31 .10-.20 narrowed to .10-.16 to enforce PROSTG <= PROSTI'
        if r['name']=='PROSHI': r['lower']=.121;r['init']=(.121+.22)/2;r['rationale']='C31 .08-.22 narrowed to .121-.22 to enforce PROSHF <= PROSHI'
        if r['status']=='active':
            lo,hi=PHYSICAL_BOUNDS[r['name']]
            assert lo<=r['lower']<r['upper']<=hi
            assert r['lower']<=r['init']<=r['upper']
    proposal=pd.DataFrame(records)
    assert set(proposal.loc[proposal.status.eq('active'),'name'])==set(active)
    proposal.to_csv(OUT/'parameter_review.csv',index=False,encoding='utf-8-sig')
    columns=['name','init','lower','upper','status','pargp','location','file','cultivar','ecotype','mode']
    proposal[columns].to_csv(ROOT/f'data/parameter_registry/bounds_proposals/{ID}.csv',index=False,encoding='utf-8-sig')
    comparison.to_csv(OUT/'recent_parameter_comparison.csv',index=False,encoding='utf-8-sig')
    return proposal


def append_observation(rows, sid, tn, date, var, mean, sd, nrep, nsamples, source, unit, status='calibration_candidate'):
    family,budget,floor,cv = FAMILY.get(var,('DIAGNOSTIC',0.,0.,0.))
    dataset_role='calibration' if sid=='26SP' and tn in CAL else ('holdout' if sid=='26SP' else 'validation')
    if dataset_role!='calibration': status=dataset_role
    if family=='DIAGNOSTIC': status='diagnostic'
    n_eff=1.  # Conservative until independent plot sampling is approved.
    safe_sd=float(sd) if pd.notna(sd) and float(sd)>=0 else 0.
    sigma=math.sqrt(safe_sd**2/n_eff+floor**2+(cv*abs(float(mean)))**2) if budget else None
    rows.append(dict(season_id=sid,trno=int(tn),date=str(date),variable=var,unit=unit,
        observed=float(mean),replicate_sd=float(sd) if pd.notna(sd) else None,n_rep=int(nrep),n_samples=int(nsamples) if pd.notna(nsamples) else int(nrep),
        n_eff=n_eff,family=family,phi_budget=budget,sigma_floor=floor,cv_model=cv,sigma_eff=sigma,
        sigma_source='measured_dispersion_plus_assumed_model_cv_and_floor',dataset_role=dataset_role,
        status=status,source_file=source,final_weight=0.))


def observations(bundles):
    rows=[];metadata=[]
    for sid,bundle in bundles.items():
        g=pd.read_csv(bundle/'growth_replicates.csv')
        mapping=g[['trno','水处理','氮处理']].drop_duplicates().sort_values('trno')
        for r in mapping.to_dict('records'):
            tn=int(r['trno']);role='calibration' if sid=='26SP' and tn in CAL else ('holdout' if sid=='26SP' else ('validation' if r['水处理'] in ['W1','W3'] else 'diagnostic'))
            metadata.append(dict(season_id=sid,trno=tn,water_level=r['水处理'],nitrogen_level=r['氮处理'],dataset_role=role))
        u=pd.read_csv(bundle/'observation_uncertainty.csv')
        for r in u.to_dict('records'):
            if r['variable'] not in ['LAID','LWAD','SWAD','CHTD','HPODW','HFPOW','CHPDT','CHFPW','SNAM','LNAM']:continue
            unit={'LAID':'m2/m2','CHTD':'m','SNAM':'kg N/ha','LNAM':'kg N/ha'}.get(r['variable'],'kg DM/ha' if r['variable'] in ['LWAD','SWAD','HPODW','CHPDT'] else 'kg fresh/ha')
            mean=r.get('unrounded_source_mean',r['value'])
            append_observation(rows,sid,int(r['trno']),r['date'],r['variable'],mean if pd.notna(mean) else r['value'],r['raw_sd'],r['n_rep'],r.get('n_samples',r['n_rep']),r['source_workbook'],unit)
            rows[-1]['quality_flag']=r['quality_flag']
        n=pd.read_csv(bundle/'plant_npk_source_values.csv')
        for (tn,date,organ),part in n.groupby(['trno','date','organ']):
            x=part.N.dropna()/10.  # mg N/g dry mass -> percent of dry mass.
            var={'叶':'LEAF_N_PCT','茎':'STEM_N_PCT','果':'FRUIT_N_PCT'}[organ]
            append_observation(rows,sid,int(tn),date,var,x.mean(),x.std(ddof=1),0 if sid=='25FA' else len(x),len(x),'plant_npk_source_values.csv','% dry mass')
            if var=='FRUIT_N_PCT':
                rows[-1].update(sample_definition='picked_mature_fruit_remaining_dried_half',
                    observation_operator='mature_seed_shell_weighted_model_average_N_proxy',
                    representation_assumption='remaining_half_represents_mature_fruit;no_skin_or_seed_removal_reported',
                    runtime_operator_preflight_passed=False)
        s=pd.read_csv(bundle/'soil_water_observations.csv')
        for r in s[s.phi_role.eq('soil_water_phi')].to_dict('records'):
            append_observation(rows,sid,int(r['trno']),r['date'],'VWC',r['vwc_mean'],r['vwc_sd'],r['n_rep'],r['n_samples'],'soil_water_observations.csv','cm3/cm3')
            rows[-1].update(depth_label=r['depth_label'],dssat_layer_weights=r['dssat_layer_weights'])
    obs=pd.DataFrame(rows);meta=pd.DataFrame(metadata)
    roles={(r.season_id,r.trno):r.dataset_role for r in meta.itertuples()}
    for i,r in obs.iterrows():
        role=roles[(r.season_id,r.trno)]
        obs.at[i,'dataset_role']=role
        if role!='calibration':obs.at[i,'status']=role if r.family!='DIAGNOSTIC' else 'diagnostic'
    eligible=obs.status.eq('calibration_candidate')
    for family,group in obs[eligible].groupby('family'):
        nt=group.trno.nunique()
        for tn,part in group.groupby('trno'):
            obs.loc[part.index,'final_weight']=(part.phi_budget/(nt*len(part))).pow(.5)/part.sigma_eff
    if obs.duplicated(['season_id','trno','date','variable','depth_label']).any():raise ValueError('Duplicate observations')
    obs.to_csv(OUT/'observation_catalog.csv',index=False,encoding='utf-8-sig')
    meta.to_csv(OUT/'treatment_roles.csv',index=False,encoding='utf-8-sig')
    summary=obs.groupby(['dataset_role','variable','status']).size().rename('n').reset_index()
    summary.to_csv(OUT/'observation_counts.csv',index=False,encoding='utf-8-sig')
    pd.DataFrame([dict(variable=k,family=v[0],phi_budget=v[1],sigma_floor=v[2],cv_model=v[3],transform='raw',n_eff=1,approved=False) for k,v in FAMILY.items()]).to_csv(OUT/'objective_policy.csv',index=False,encoding='utf-8-sig')
    return obs,meta


def mature_fruit_n_percent(seed_pct, shell_pct, seed_dm, shell_dm):
    """Dry-mass-weighted mature-fruit proxy, not a cohort-specific N state."""
    values=[float(v) for v in (seed_pct,shell_pct,seed_dm,shell_dm)]
    if any(not math.isfinite(v) or v<0 for v in values):
        raise ValueError('Missing, non-finite or negative mature-fruit component')
    seed_pct,shell_pct,seed_dm,shell_dm=values
    if seed_dm+shell_dm<=0:
        raise ValueError('No modeled mature fruit; never substitute all-age fruit')
    return (seed_pct*seed_dm+shell_pct*shell_dm)/(seed_dm+shell_dm)


def readback(obs):
    qa=ROOT/'workspace/qa/input_smoke_xxql2601_refreshed_20261010'
    n=read_native(qa/'PlantN.OUT');g=read_native(qa/'PlantGro.OUT');f=read_native(qa/'FreshWt.OUT')
    # This installed executable lacks FRN%D/FRNAD. CNAD-VNAD is live fruit
    # N (not harvested cumulative N); dividing by PWAD gives all-age fruit N%.
    joined=n.merge(g[['trno','date','PWAD']],on=['trno','date'],validate='one_to_one')
    joined['fruit_n_kg_ha']=joined.CNAD-joined.VNAD
    joined['fruit_all_age_n_pct']=100*joined.fruit_n_kg_ha/joined.PWAD.where(joined.PWAD>1.)
    joined=joined.merge(f[['trno','date','MTDSD','MTDSH','MTDPW','CHNUM']],on=['trno','date'],how='left',validate='one_to_one')
    matches=[]
    for r in obs[obs.dataset_role.eq('calibration')&obs.variable.isin(['LEAF_N_PCT','STEM_N_PCT','FRUIT_N_PCT'])].itertuples():
        part=joined[joined.trno.eq(r.trno)&joined.date.eq(r.date)]
        assert len(part)==1
        s=part.iloc[0]
        value=(mature_fruit_n_percent(s['GN%D'],s['SHND'],s.MTDSD,s.MTDSH) if r.variable=='FRUIT_N_PCT'
            else s['LN%D'] if r.variable=='LEAF_N_PCT' else s['SN%D'])
        matches.append(dict(trno=r.trno,date=r.date,variable=r.variable,observed=r.observed,baseline_simulated=value,
            valid_native_date=True,target_semantics='mature_fruit_organ_average_N_proxy' if r.variable=='FRUIT_N_PCT' else 'native_organ_n_percent',
            native_column={'LEAF_N_PCT':'LN%D','STEM_N_PCT':'SN%D','FRUIT_N_PCT':'(GN%D*MTDSD+SHND*MTDSH)/(MTDSD+MTDSH)'}[r.variable]))
    pd.DataFrame(matches).to_csv(OUT/'nitrogen_output_readback.csv',index=False,encoding='utf-8-sig')
    fruit=[]
    for r in obs[obs.dataset_role.eq('calibration')&obs.variable.eq('FRUIT_N_PCT')].itertuples():
        for shift in [0,-1]:
            date=(pd.Timestamp(r.date)+pd.Timedelta(days=shift)).strftime('%Y-%m-%d')
            nf=n[n.trno.eq(r.trno)&n.date.eq(date)];ff=f[f.trno.eq(r.trno)&f.date.eq(date)]
            if len(nf)==1 and len(ff)==1:
                a=nf.iloc[0];b=ff.iloc[0]
                dry=b.MTDSH+b.MTDSD
                mature=(a.SHND*b.MTDSH+a['GN%D']*b.MTDSD)/dry if dry>1 else None
                fruit.append(dict(trno=r.trno,sample_date=r.date,model_date=date,date_shift=shift,mature_fruit_dry_kg_ha=dry,mature_n_pct_proxy=mature,
                    method='mature seed/shell masses weighted by model organ-average N%; phase preflight still required',
                    selected_for_review_proxy=shift==0,actual_simulated_harvest_number=b.CHNUM))
    pd.DataFrame(fruit).to_csv(OUT/'fruit_semantics_candidates.csv',index=False,encoding='utf-8-sig')
    return {'native_n_rows_matched':len(matches),'native_plantn_columns':list(n.columns),'fruit_FRN_percent_native_available':'FRN%D' in n.columns,
        'fruit_semantic_confirmation_required':False,'fruit_sampling_definition':'picked_mature_fruit_remaining_dried_half',
        'fruit_proxy_native_dates_available':sum(r['variable']=='FRUIT_N_PCT' for r in matches),
        'fruit_proxy_is_cohort_specific_N':False,'fruit_operator_runtime_phase_preflight_passed':False,
        'new_native_reader_is_not_integrated_into_pest':True}


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    idx=json.loads((ROOT/'configs/experiments/current_bundles.json').read_text())
    bundles={}
    for sid,r in idx['bundles'].items():
        b=ROOT/'data/user/experiments'/r['bundle_id'];m=verify_manifest_integrity(b)
        assert m.manifest_sha256==r['manifest_sha256']
        assert 'refreshed_20261010' in r['bundle_id']
        bundles[sid]=b
    param=parameters();obs,meta=observations(bundles);evidence=readback(obs)
    proposal=dict(schema='calibration_review_proposal_v1',design_id=ID,status='awaiting_user_review',executable=False,
        formal_calibration_started=False,weather_boundary={'TAV':20.,'AMP':6.},
        fruit_sampling_definition=json.loads((OUT/'fruit_sampling_definition.json').read_text(encoding='utf-8')),
        datasets=[dict(season_id=sid,experiment_code=b.name.split('_')[0].upper(),bundle_path=str(b.relative_to(ROOT)).replace('\\','/'),bundle_manifest_sha256=idx['bundles'][sid]['manifest_sha256'],
            roles={role:part.trno.astype(int).tolist() for role,part in meta[meta.season_id.eq(sid)].groupby('dataset_role')}) for sid,b in bundles.items()],
        parameter_proposal=f'data/parameter_registry/bounds_proposals/{ID}.csv',bounds_id=None,
        bounds_reference=BOUND,active_parameter_count=int(param.status.eq('active').sum()),
        activation_rule='Only reviewed parameters passing calibration-only injection and perturbation checks; validation outcomes may never activate parameters or alter bounds.',
        stages=[dict(stage_id=stage,active_parameters=names,freeze_other_stages=True,noptmax=3,ies_num_reals=200,seed=20261011+i) for i,(stage,names) in enumerate(STAGES.items())],
        final_joint=dict(noptmax=6,ies_num_reals=200,seed=20261014,active_scope='Only stage parameters with non-degenerate effects; approval required for changes',agents=6),
        uncertainty_model=dict(n_eff=1,formula='sqrt(SD^2/n_eff + floor^2 + (cv*abs(observed))^2)',floor_and_cv_status='assumed_pending_review',
            weight_formula='sqrt(family_budget / (number_treatments * number_observations_in_treatment_family)) / sigma_eff',
            interpreted_as='balanced composite objective; not independent chi-square likelihood',validation_weight=0),
        objectives=dict(catalog='observation_catalog.csv',policy='objective_policy.csv',primary='Raw date-specific stem/leaf dry mass, LAI, height, soil water, dry event harvest, leaf/stem N%, and mature-fruit dry-basis N% via the proposed organ-average proxy; all await design review and runtime preflight',
            diagnostic_only=['SNAM','LNAM','CNAM','cumulative_harvest_N','CHPDT','CHFPW','HFPOW','N_RESPONSE','W_RESPONSE','PDMCD'],
            no_duplicate_primary_states_increments_or_products=True),
        constraints=['TBj < TO1j < TO2j < TMj','XMAGE < fixed XFPHT','PROLFF <= PROLFG <= PROLFI','PROSTF <= PROSTG <= PROSTI','PROSHF <= PROSHI','FNPGN1 < FNPGN2 < FNPGN3 = FNPGN4','FRLFF + FRSTMF may need mechanism-specific partition constraints at injection'],
        fixed_inputs='Immutable per-season TMX/SOL/weather: N, water, fertilizer, PAGE/PENV/PLWT, density, soil chemistry/physical layers/SASC/SLPF; do not import old fixed IC/soil values',
        historical_validation_caveat='C31 and prior batches have already used 2025 treatments; current split is locked out of this run but is retrospective external validation, not historically blind validation.',
        pending=['User review of objectives/bounds/weights/stages including mature-fruit proxy','Validate mature-fruit proxy output phase and finite mature mass on exact sample dates; no substitution or added bulk harvest','Implement and test concentration objectives in builder/runtime','Support one formal calibration season without diagnostic_single_season workaround','Verify all proposal parameter injection and perturbation effects against current 26SP only','Freeze a new approved bounds ID before building PST'],
        output_evidence=evidence)
    write_json(OUT/'proposal.json',proposal)
    files=[p for p in OUT.iterdir() if p.is_file() and p.name!='proposal_receipt.json']
    sources=[ROOT/'configs/experiments/current_bundles.json',ROOT/f'data/parameter_registry/bounds_frozen/eggplant/{BOUND}.csv',ROOT/f'workspace/runs/{C31}/{C31}.pst',ROOT/f'configs/runs/{C31}_design.json',Path(__file__)]
    sources.extend(ROOT/f'data/parameter_registry/bounds_frozen/eggplant/{bid}.csv' for bid in ['eggplant_full_gen_final_uncertainty_13trt_20260924','eggplant_full_gen_final_calib_200x6_20260926'])
    sources.extend(ROOT/f'data/templates/genotype/TMGRO048.{kind}.base' for kind in ['CUL','ECO','SPE'])
    sources.append(ROOT/'src/common/param_registry.py')
    sources.extend(ROOT/f'workspace/audits/input_refresh_20261010/{name}.json' for name in ['fruit_sampling_metadata'])
    sources.append(ROOT/'workspace/audits/input_refresh_20261010/dssat_n_source/source_manifest.json')
    sources.extend(bundles['26SP']/name for name in ['input_manifest.json','plant_npk_source_values.csv','growth_replicates.csv','observation_uncertainty.csv','soil_water_observations.csv'])
    sources.extend(ROOT/f'workspace/qa/input_smoke_xxql2601_refreshed_20261010/{name}.OUT' for name in ['PlantN','PlantGro','FreshWt'])
    sources.append(ROOT/'docs/reports/正式率定方案_2026N012_20261011.md')
    sources.append(ROOT/f'data/parameter_registry/bounds_proposals/{ID}.csv')
    write_json(OUT/'proposal_receipt.json',{'formal_calibration_started':False,'files':[{'name':p.name,'sha256':sha(p)} for p in files],
        'source_files':[{'path':str(p.relative_to(ROOT)).replace('\\','/'),'sha256':sha(p)} for p in sources],
        'approved_bounds_created':False,'positive_weight_observations':int(obs.final_weight.gt(0).sum()),
        'fruit_sampling_definition_confirmed':True,'fruit_operator_runtime_preflight_passed':False,
        'proposed_fruit_concentrations':int((obs.variable.eq('FRUIT_N_PCT')&obs.dataset_role.eq('calibration')).sum()),
        'pending_fruit_concentrations':0})
    print(json.dumps({'out':str(OUT),'active_parameters':proposal['active_parameter_count'],'positive_weight_observations':int(obs.final_weight.gt(0).sum()),'counts':obs[obs.dataset_role.eq('calibration')].groupby(['variable','status']).size().rename('n').reset_index().to_dict('records')},default=str))


if __name__=='__main__':main()
