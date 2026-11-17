"""Freeze explicit daily mechanism diagnostics. No plotting and no model mutation."""
from pathlib import Path
import hashlib,json,re
import numpy as np
import pandas as pd

KEY=['run','yrdoy']
NORDER=['N0','N1','N2','N3']
WORDER=['W1','W2','W3']

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def native_table(path):
    rows=[];run=None;trt=None;columns=None;label=None
    for line in Path(path).read_text(errors='replace').splitlines():
        if line.startswith('*RUN'):
            match=re.match(r'\*RUN\s+(\d+)\s*:\s*(.*?)\s+CRGRO',line)
            if not match:raise ValueError('Unsupported native run header: '+line)
            run=int(match[1]);label=match[2].strip();trt=None;columns=None
        elif re.match(r'^\s*TREATMENT\s+\d+',line):trt=int(re.search(r'TREATMENT\s+(\d+)',line)[1])
        elif line.startswith('@YEAR'):columns=line[1:].split()
        elif columns and re.match(r'^\s+20\d{2}\s',line):
            values=list(map(float,line.split()))
            if len(values)!=len(columns):raise ValueError(f'{path}: field count mismatch')
            if run is None or trt is None:raise ValueError('Daily rows without explicit run/treatment mapping')
            row=dict(zip(columns,values));row.update(run=run,treatment=trt,treatment_label_native=label)
            row['yrdoy']=int(row['YEAR'])*1000+int(row['DOY']);rows.append(row)
    frame=pd.DataFrame(rows)
    if frame.empty or frame.duplicated(KEY).any():raise ValueError(f'{path}: empty or duplicate daily records')
    return frame

def merge_daily(base,other,columns,source):
    if other.duplicated(KEY).any():raise ValueError(source+': duplicate run/day')
    if len(base.set_index(KEY).index.difference(other.set_index(KEY).index)):
        raise ValueError(source+': daily coverage differs; missing values must not be interpolated')
    # FreshWt can include pre-transplant days. The reviewed crop timeline is
    # explicit in PlantGro; extra non-crop days are outside this atlas scope.
    return base.merge(other[KEY+columns],on=KEY,how='left',validate='one_to_one')

def harvest_on_crop_grid(base,fresh):
    """Fill only provable pre-output zeros, never an unreported harvest history."""
    result=base.merge(fresh[KEY+['CHFPW','HFPOW','CHNUM']],on=KEY,how='left',validate='one_to_one')
    proven=0
    for run,g in fresh.groupby('run'):
        first=g.sort_values('yrdoy').iloc[0]
        before=result.run.eq(run)&result.yrdoy.lt(first.yrdoy)
        if first.CHFPW==0 and first.CHNUM==0:
            result.loc[before,['CHFPW','HFPOW','CHNUM']]=0.;proven+=int(before.sum())
        internal=result.run.eq(run)&result.yrdoy.ge(first.yrdoy)
        if result.loc[internal,['CHFPW','HFPOW','CHNUM']].isna().any().any():
            raise ValueError('FreshWt has missing days after reporting starts')
    return result,proven

def trace_tables(path):
    if not Path(path).exists():return {},None
    selected=[]
    for block in pd.read_csv(path,chunksize=200000,usecols=['seq','run','yrdoy','event','key','value']):
        selected.append(block[block.event.isin(['cg_end','cg_veg','leaf_capacity'])])
    records=pd.concat(selected,ignore_index=True)
    daily={}
    for event in ['cg_end','cg_veg']:
        q=records[records.event.eq(event)]
        if not q.empty:daily[event]=q.pivot(index=KEY,columns='key',values='value').reset_index()
    q=records[records.event.eq('leaf_capacity')].copy()
    if q.empty:return daily,None
    q['call']=q.key.eq('RNITP').cumsum()
    calls=q.pivot(index=['call',*KEY],columns='key',values='value').reset_index()
    if calls[['AGEMXL','AGEQE','RNITP','SLW']].isna().any().any():raise ValueError('Incomplete capacity calls')
    photo=calls.groupby(KEY).agg(photo_N_mean=('AGEMXL','mean'),photo_N_min=('AGEMXL','min'),
        photo_N_max=('AGEMXL','max'),photo_QE_mean=('AGEQE','mean'),photo_calls=('AGEMXL','size')).reset_index()
    return daily,photo

def freeze(case,metadata,out,label,profile,extra_n=None,extra_n_unit=None,comparison=None,simulation_only=False):
    case=Path(case).resolve();out=Path(out);out.mkdir(parents=True,exist_ok=False)
    sources={}
    def used(name):
        p=case/name
        if p.exists():sources[str(p)]=sha(p)
        return p
    def csv(name):
        p=used(name)
        return pd.read_csv(p,float_precision='round_trip').sort_values(KEY).reset_index(drop=True) if p.exists() else None
    meta=pd.read_csv(metadata)
    required={'treatment','treatment_label','water_level','nitrogen_level'}
    if not required.issubset(meta) or meta.treatment.duplicated().any():raise ValueError('Explicit unique treatment metadata required')
    if not set(meta.water_level)<=set(WORDER) or not set(meta.nitrogen_level)<=set(NORDER):
        raise ValueError('Declare supported water/nitrogen levels; do not infer from treatment IDs')
    if meta.duplicated(['water_level','nitrogen_level']).any():raise ValueError('Multiple treatments per water/N cell need an explicit replicate adapter')
    sources[str(Path(metadata).resolve())]=sha(metadata);sources[str(Path(profile).resolve())]=sha(profile)
    receipt_path=used('receipt.json')
    receipt=json.loads(receipt_path.read_text(encoding='utf-8-sig')) if receipt_path.exists() else {}
    if receipt.get('success') is False:raise ValueError('Do not plot a failed run as a valid simulation')
    config=receipt.get('config',{})
    p=used('NIntegration.nml')
    if p.exists():
        actual={k:float(v) for k,v in re.findall(r'(\w+)\s*=\s*([-+\d.eE]+)',p.read_text())}
        if any(k in actual and actual[k]!=v for k,v in config.items()):raise ValueError('Receipt/NML mismatch')
        config=actual|config
    gro=native_table(used('PlantGro.OUT')).sort_values(KEY).reset_index(drop=True)
    fresh=native_table(used('FreshWt.OUT')).sort_values(KEY).reset_index(drop=True)
    ni=csv('PlantNIntegration.csv');cash=csv('PlantCCash.csv')
    if ni is None or cash is None:raise ValueError('This adapter requires PlantNIntegration and actual PlantCCash outputs')
    d=gro[KEY+['treatment','treatment_label_native','DAP','LAID','LWAD','SWAD','NSTD']].copy()
    d=d.rename(columns={'DAP':'dap','LAID':'lai','LWAD':'leaf_DM','SWAD':'stem_DM'})
    d=d.merge(meta,on='treatment',validate='many_to_one',indicator=True)
    if not d['_merge'].eq('both').all() or not d.treatment_label_native.eq(d.treatment_label).all():
        raise ValueError('Native treatment labels differ from the explicitly supplied metadata')
    d=d.drop(columns='_merge')
    if set(d.treatment)!=set(meta.treatment):raise ValueError('Metadata/run treatment coverage mismatch')
    ni_columns=[c for c in ni if c not in KEY+['stage']]
    d=merge_daily(d,ni,ni_columns,'PlantNIntegration')
    d=merge_daily(d,cash,['PG','actual_C_mined','maintenance','N_assim','veg_growth','fruit_growth'],'PlantCCash')
    d,harvest_zero_days=harvest_on_crop_grid(d,fresh)
    p2=csv('PlantNP2.csv');lai=csv('PlantNLAI.csv');v3=csv('PlantNV3.csv');mob=csv('PlantNRemob.csv');lux=csv('PlantNLuxury.csv')
    optional=[]
    if harvest_zero_days:optional.append(f'FreshWt starts at flowering; {harvest_zero_days} pre-output run-days have zero harvest proven by first CHFPW=CHNUM=0, not interpolated')
    for frame,cols,name in [(p2,['R_end_leaf','R_end_stem','R_fill_leaf','R_fill_stem','R_fast_leaf','R_fast_stem',
            'R_sen_recovery_leaf','R_sen_recovery_stem','R_litter_leaf','R_litter_stem'],'PlantNP2'),
        (lai,['state_response','dm_leaf_actual','dm_leaf_request','new_leaf_area','old_leaf_area_lost','SLA_new',
            'C_available_veg','N_available_veg','C_leaf_actual','N_leaf_actual'],'PlantNLAI'),
        (v3,['growth_day','z_leaf_day','z_stem_day','pod_n_factor'],'PlantNV3'),
        (mob,['growth_severity_day','safe_leaf','safe_stem','function_leaf','function_stem','capR_leaf','capR_stem',
            'capF_leaf','capF_stem','rate_mode','rate_max','functional_rate_max'],'PlantNRemob'),
        (lux,['A_function_late','A_luxury'],'PlantNLuxury')]:
        if frame is None:
            optional.append(name+' unavailable')
            for col in cols:d[col]=np.nan
        else:
            missing=[col for col in cols if col not in frame]
            if missing:optional.append(name+' missing optional fields: '+', '.join(missing))
            d=merge_daily(d,frame.reindex(columns=KEY+cols),cols,name)
    reserve_status='enabled' if config.get('reserve_mode') in (1,2) else 'disabled' if config.get('reserve_mode',0)==0 else 'unknown'
    if reserve_status=='disabled':
        d['R_end_leaf']=0.;d['R_end_stem']=0.
        optional.append('R is disabled, not a measured zero reserve')
    homeo=csv('PlantNHomeostasis.csv')
    if homeo is not None:
        hcols=['Q3_reference','Q3_capacity_accept','Q3_capacity_target','root_unregulated','root_candidate',
            'root_accepted','root_feedback','substrate_factor_end','exposure_budget','exposure_spent']
        d=merge_daily(d,homeo,hcols,'PlantNHomeostasis')
        for dest,src in [('Q_reference','Q3_reference'),('Q_capacity','Q3_capacity_accept'),
                ('Q_capacity_target','Q3_capacity_target'),('U_unregulated_no3','root_unregulated'),
                ('U_candidate_no3','root_candidate'),('U_actual_no3','root_accepted')]:d[dest]=10*d[src]
        d['Q_relative']=d.QNO3/d.Q3_reference.where(d.Q3_reference>0)
        d['Q_root_feedback']=d.root_feedback;d['Q_assim_factor']=d.substrate_factor_end
    achain=csv('PlantNAssimChain.csv')
    if achain is not None:
        cols=['main_kinetic','main_after_receiver','main_after_C','returned_N','R_goal_gap','R_request',
            'R_actual','C_held','C_late_allowed','C_protein_paid']
        d=merge_daily(d,achain,cols,'PlantNAssimChain')
        for col in cols:d['chain_'+col]=10*d[col]
    trace,photo=trace_tables(used('P0Trace.csv'))
    if 'cg_end' in trace:
        keys=['WTNSH','WTNSD','WTNNOD','SDNPL','WTNLO','WTNSO','WTNRO','WTNSHO','WTNSDO','WTNNO']
        d=merge_daily(d,trace['cg_end'],keys,'cg_end trace')
        d['fruit_Norg']=10*(d.WTNSH+d.WTNSD)
    else:
        n=native_table(used('PlantN.OUT')).sort_values(KEY).reset_index(drop=True)
        if 'FRNAD' in n:
            d=merge_daily(d,n,['FRNAD'],'PlantN');d['fruit_Norg']=d.FRNAD
        else:d['fruit_Norg']=np.nan
        for key in ['WTNNOD','SDNPL']:d[key]=np.nan
        optional.append('Fruit N uses rounded native FRNAD; source-seed and nodule stocks unavailable')
    if 'cg_veg' in trace:
        d=merge_daily(d,trace['cg_veg'],['NSTRES'],'cg_veg trace')
    else:
        d['NSTRES']=1-d.NSTD
        optional.append('NSTRES reconstructed from daily 1-NSTD; native output precision applies')
    if photo is not None:
        # PGLFEQ can run before emergence. Keep only actual crop-day matches.
        photo=d[KEY].merge(photo,on=KEY,how='left',validate='one_to_one')
        d=d.merge(photo,on=KEY,validate='one_to_one')
    else:
        for col in ['photo_N_mean','photo_N_min','photo_N_max','photo_QE_mean','photo_calls']:d[col]=np.nan
        optional.append('Actual leaf-capacity calls unavailable; PG is still actual canopy C input')
    # Stocks, fluxes and concentrations have explicit, separate units.
    d['Q_total']=10*(d.QNO3+d.QNH4);d['Q_NO3']=10*d.QNO3;d['Q_NH4']=10*d.QNH4
    support = d[['carrier_leaf', 'carrier_stem', 'carrier_root']].sum(axis=1, min_count=3)
    support = support.where(support > 0)
    d['Q_NO3_concentration'] = 1000 * d.QNO3 / support
    d['Q_NH4_concentration'] = 1000 * d.QNH4 / support
    d['Q_total_concentration'] = d.Q_NO3_concentration + d.Q_NH4_concentration
    d['A_daily']=10*(d.A_NO3+d.A_NH4);d['A_nitrate']=10*d.A_NO3;d['A_ammonium']=10*d.A_NH4
    d['U_daily']=10*(d.U_NO3+d.U_NH4)
    d['A_cumulative']=d.groupby('run').A_daily.cumsum();d['U_cumulative']=d.groupby('run').U_daily.cumsum()
    d['R_total']=10*(d.R_end_leaf+d.R_end_stem)
    for organ in ['leaf','stem','root']:
        d[organ+'_Q']=10*(d['QNO3_'+organ]+d['QNH4_'+organ])
        d[organ+'_QNO3']=10*d['QNO3_'+organ];d[organ+'_QNH4']=10*d['QNH4_'+organ]
        d[organ+'_Norg']=10*d['Norg_'+organ]
        if organ!='root':
            d[organ+'_R']=10*d['R_end_'+organ]
            d[organ+'_Nnonreserve']=d[organ+'_Norg']-d[organ+'_R']
        d[organ+'_Corg_pct']=100*d['Corg_'+organ]
    w=d.W_leaf+d.W_stem
    d['canopy_Corg_pct']=100*(d.Norg_leaf+d.Norg_stem)/w
    d['canopy_Ctotal_pct']=100*(d.Norg_leaf+d.Norg_stem+(d.leaf_Q+d.stem_Q)/10)/w
    d['organ_Norg']=d.leaf_Norg+d.stem_Norg+d.root_Norg+d.fruit_Norg
    d['seed_remnant_N']=10*d.SDNPL;d['nodule_N']=10*d.WTNNOD
    d['plant_Norg_with_source']=d.organ_Norg+d.seed_remnant_N+d.nodule_N
    d['plant_N_total']=d.plant_Norg_with_source+d.Q_total
    d['leaf_N_functional_area']=d.functional_leaf_N_per_area
    d['leaf_Norg_area']=d.Norg_leaf/d.lai.where(d.lai>0)
    d['PG_daily']=10*d.PG;d['PG_cumulative']=d.groupby('run').PG.cumsum()/100
    d['PG_leaf_area']=d.PG/d.lai.where(d.lai>0)
    d['yield_cumulative']=d.CHFPW/1000;d['yield_event']=d.HFPOW/1000
    d['LAI_new']=d.new_leaf_area/10000;d['LAI_lost']=d.old_leaf_area_lost/10000
    d['leaf_DM_new']=10*d.dm_leaf_actual;d['leaf_SLA']=d.SLA_new/10
    d['leaf_acceptance']=d.dm_leaf_actual/d.dm_leaf_request.where(d.dm_leaf_request>1e-10)
    if config.get('lai_cn_mode',0)!=1:
        d['state_response']=np.nan
        optional.append('New h(G) is disabled in this branch; logger bypass value 1 is not plotted as an active response')
    d['functional_deficit_leaf']=np.maximum(0,10*d.leaf_crit*d.W_leaf-d.leaf_Nnonreserve)
    d['functional_surplus_leaf']=np.maximum(0,d.leaf_Nnonreserve-10*d.leaf_crit*d.W_leaf)
    d['mob_function_gate']=(1-np.clip(d.growth_severity_day,0,1))**2
    if config.get('remob_severity')==0:d['mob_function_gate']=1.
    # The root ledger reports potentials separately: never add MF to uptake.
    layer=csv('LayerNIntegration.csv')
    if layer is not None:
        if layer.duplicated(KEY+['layer']).any():raise ValueError('Duplicate root-layer records')
        root=layer.groupby(KEY).agg(MF=('MF_candidate_gN_m2','sum'),Diff=('Diff_potential_gN_m2','sum'),
            membrane=('membrane_potential_gN_m2','sum'),U_NO3_layers=('NO3_final_gN_m2','sum'),
            U_NH4_layers=('NH4_final_gN_m2','sum'))
        for k in ['MF','Diff','membrane']:root[k]=root[k]*10
        np.testing.assert_allclose(root.U_NO3_layers.to_numpy(),d.U_NO3.to_numpy(),atol=1e-12,rtol=0)
        np.testing.assert_allclose(root.U_NH4_layers.to_numpy(),d.U_NH4.to_numpy(),atol=1e-12,rtol=0)
        d=d.merge(root.reset_index()[KEY+['MF','Diff','membrane']],on=KEY,validate='one_to_one')
    else:
        for key in ['MF','Diff','membrane']:d[key]=np.nan
    # Independent checks against native units, not the renderer's own formulas.
    np.testing.assert_allclose(d.Q_total,d.leaf_Q+d.stem_Q+d.root_Q,atol=1e-12,rtol=0)
    np.testing.assert_allclose(d.leaf_Norg,100*d.W_leaf*d.leaf_Corg_pct/1000,atol=1e-10,rtol=0)
    if p2 is not None:
        np.testing.assert_allclose(d.leaf_Nnonreserve,10*p2.N_nonreserve_leaf,atol=1e-12,rtol=0)
    if 'cg_veg' in trace:
        np.testing.assert_allclose(d.NSTRES,1-d.NSTD,atol=.00051,rtol=0)
    if lai is not None:
        np.testing.assert_allclose(d.lai,lai.LAI_end,atol=.00051,rtol=0)
        # Use the precise area ledger for curves; native LAID is only 0.001.
        d['lai']=lai.LAI_end.to_numpy()
        d['leaf_Norg_area']=d.Norg_leaf/d.lai.where(d.lai>0)
        d['PG_leaf_area']=d.PG/d.lai.where(d.lai>0)
    a=csv('PlantABudget.csv')
    if a is not None and 'cg_end' in trace:
        np.testing.assert_allclose(d.plant_Norg_with_source,10*a.organic_end_including_seed,atol=1e-11,rtol=0)
    # Exact observation dates, no invented uncertainty or shifted fruit samples.
    if simulation_only:
        c=pd.DataFrame(columns=['trno','date','obsnme','family','observed','replicate_sd','simulated'])
    else:
        comparison=Path(comparison).resolve() if comparison is not None else used('comparison.csv')
        c=pd.read_csv(comparison,float_precision='round_trip')
        sources[str(comparison.resolve())]=sha(comparison)
    if c.duplicated('obsnme').any():raise ValueError('Duplicate observation IDs')
    d['date']=pd.to_datetime(d.yrdoy.astype(str),format='%Y%j').dt.strftime('%Y-%m-%d')
    lookup=d[['treatment','date','dap']]
    obs=c.rename(columns={'trno':'treatment'}).merge(lookup,on=['treatment','date'],how='left',validate='many_to_one')
    if obs.dap.isna().any():raise ValueError('Observation dates outside actual crop timeline')
    obs['observation_role']='objective';obs['observed_se']=np.nan
    obs['observed_sd']=obs.replicate_sd
    extra_added=0
    if extra_n is not None:
        if extra_n_unit not in ['g/kg','percent']:raise ValueError('Explicit extra-N unit required')
        raw=pd.read_csv(extra_n);sources[str(Path(extra_n).resolve())]=sha(extra_n)
        raw=raw[raw.organ.isin(['叶','茎'])].copy()
        raw['N_pct']=raw.N/(10 if extra_n_unit=='g/kg' else 1)
        q=raw.groupby(['trno','date','organ']).N_pct.agg(['mean','std','size']).reset_index()
        organ_family={'叶':'LEAF_N_CONCENTRATION','茎':'STEM_N_CONCENTRATION'}
        q['family']=q.organ.map(organ_family);q=q.rename(columns={'trno':'treatment'})
        q=q.merge(lookup,on=['treatment','date'],how='left',validate='many_to_one')
        if q.dap.isna().any():raise ValueError('Extra N observations outside crop dates; select an explicit season first')
        for _,r in q.iterrows():
            match=obs[(obs.treatment==r.treatment)&obs.date.eq(r.date)&obs.family.eq(r.family)]
            if len(match):
                if len(match)!=1 or abs(match.observed.iloc[0]-r['mean'])>1e-9:
                    raise ValueError('Extra source N means disagree with frozen objective observations')
                continue
            new={'treatment':r.treatment,'date':r.date,'dap':r.dap,'family':r.family,'observed':r['mean'],
                'observed_sd':r['std'],'observed_se':np.nan,'n_rep':r['size'],'observation_role':'diagnostic_only',
                'source_file':str(extra_n),'unit':'% dry mass','obsnme':'diagnostic_'+str(r.treatment)+'_'+r.date+'_'+r.organ}
            obs=pd.concat([obs,pd.DataFrame([new])],ignore_index=True);extra_added+=1
    obs=obs.merge(meta,on='treatment',validate='many_to_one')
    final=obs[obs.family.eq('FINAL_FRESH_YIELD')].copy()
    endpoint=d.sort_values('dap').groupby('run').tail(1)
    check=final.merge(endpoint[['treatment','CHFPW']],on='treatment',validate='one_to_one')
    if len(check):
        np.testing.assert_allclose(check.simulated,check.CHFPW,atol=.11,rtol=0)
    for run,g in d.groupby('run'):
        if (np.diff(g.CHFPW)<-.11).any():raise ValueError('Cumulative harvested fresh yield decreases')
        if abs(g.HFPOW.sum()-g.CHFPW.iloc[-1])>((g.HFPOW>0).sum()+1)*.051:
            raise ValueError('Event/cumulative harvest output mismatch')
    d.to_csv(out/'diagnostic_daily.csv',index=False);obs.to_csv(out/'diagnostic_observations.csv',index=False)
    final.to_csv(out/'diagnostic_final_yield.csv',index=False);meta.to_csv(out/'treatment_metadata.csv',index=False)
    state=dict(label=label,case_dir=str(case),source_hashes=sources,config=config,
        binary_sha256=receipt.get('binary_sha256'),reserve_status=reserve_status,notes=optional,
        days=int(d.dap.nunique()),treatments=int(d.treatment.nunique()),rows=len(d),objective_rows=len(c),
        additional_diagnostic_N_observations=extra_added,science_status='mechanism_debugging_not_publication_validated',
        photo_aggregation='unweighted arithmetic mean/min/max across actual PGLFEQ calls, not assimilation-weighted',
        canopy_definition='standing leaves and stems; root and fruit excluded',
        Q_definition='equivalent inorganic NO3/NH4 pool; not measured organ vacuoles',
        extra_N_unit=extra_n_unit,observed_error_bars='unavailable: no audited SE supplied')
    dump(out/'source_manifest.json',state)
    return d,obs,state
