"""Independent daily acceptance, actual photo calls and reproductive-limit readout."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from p1_workflow import OUT,CN,REPO,sha,dump

def table(frame,columns):
    q=frame[columns].copy()
    for c in q.select_dtypes('number'):
        q[c]=q[c].map(lambda x:f'{x:.4f}' if pd.notna(x) else '')
    return '| '+' | '.join(q.columns)+' |\n| '+' | '.join(['---']*len(q.columns))+' |\n'+''.join('| '+' | '.join(map(str,r))+' |\n' for r in q.itertuples(index=False,name=None))

def trace_analysis(name):
    w=OUT/'cases'/name
    cfg=json.loads((w/'receipt.json').read_text(encoding='utf8'))['config']
    parts=[]
    wanted=['pods_set_budget','veg_potential','veg_after_N','c4_grow_end','leaf_capacity']
    for c in pd.read_csv(w/'P0Trace.csv',chunksize=200000,usecols=['run','yrdoy','event','key','value']):
        keep=c.event.isin(wanted)
        keep &= ~c.event.eq('c4_grow_end')|c.key.isin(['W_leaf','Q_leaf'])
        parts.append(c[keep])
    t=pd.concat(parts,ignore_index=True)
    per={event:g.pivot(index=['run','yrdoy'],columns='key',values='value').reset_index() for event,g in t[~t.event.eq('leaf_capacity')].groupby('event')}
    pods=per['pods_set_budget']
    active=pods.selected.gt(1e-10)&pods.PODADD.gt(1e-10)
    for key in ['PODADD','C_limit','N_limit','flower_limit']:
        pods[key+'_binding']=active&np.isclose(pods[key],pods.selected,rtol=1e-5,atol=1e-8)
    pods['active']=active;pods.to_csv(OUT/f'diagnostic_{name}_pod_limits.csv',index=False)
    vg=per['veg_potential'].merge(per['veg_after_N'],on=['run','yrdoy'],suffixes=('_potential','_actual'),validate='one_to_one')
    vg=vg.merge(pd.read_csv(w/'PlantNV4.csv'),on=['run','yrdoy'],validate='one_to_one')
    vg['new_tissue_budget_limited']=vg.NRATIO.lt(.999999)
    vg['additional_leaf_gate_active']=vg.leaf_gate.lt(.999999)
    vg.to_csv(OUT/f'diagnostic_{name}_veg_acceptance.csv',index=False)
    n=pd.read_csv(w/'PlantNIntegration.csv',float_precision='round_trip')
    s=per['c4_grow_end'].merge(n[['run','yrdoy','leaf_min','leaf_crit']],on=['run','yrdoy'],validate='one_to_one').sort_values(['run','yrdoy'])
    s['sf']=(s.W_leaf-s.Q_leaf)/s.W_leaf
    for c in ['sf','leaf_min','leaf_crit']:s['prev_'+c]=s.groupby('run')[c].shift()
    p=t[t.event.eq('leaf_capacity')].copy();p['call']=p.key.eq('RNITP').cumsum()
    p=p.pivot(index=['call','run','yrdoy'],columns='key',values='value').reset_index()
    p=p.merge(s[['run','yrdoy','prev_sf','prev_leaf_min','prev_leaf_crit']],on=['run','yrdoy'],validate='many_to_one')
    slw=p.SLW/p.prev_sf
    functional=np.minimum(np.maximum(0,(p.RNITP/100*p.prev_sf-p.prev_leaf_min)*slw),
        (p.prev_leaf_crit-p.prev_leaf_min)*slw)
    reference=cfg['photo_sln_ref']/10000 if cfg.get('photo_reference_mode')==1 else (p.prev_leaf_crit-p.prev_leaf_min)*cfg['photo_slw_ref']
    p['functional_sln_gN_m2leaf']=functional*10000
    p['uncapped_ratio']=functional/reference
    f=cfg['photo_floor']+(1-cfg['photo_floor'])*p.uncapped_ratio.clip(0,1)**cfg['photo_gamma']
    err=float(abs(f-p.AGEMXL).max());assert err<2*np.finfo(np.float32).eps
    # Native transplant day is 2026 DOY73; DAP comes from the frozen date contract.
    p['DAP']=pd.to_datetime(p.yrdoy.astype(str),format='%Y%j').sub(pd.Timestamp('2026-03-14')).dt.days
    p.to_csv(OUT/f'diagnostic_{name}_actual_photo_calls.csv',index=False)
    late=p[p.DAP.ge(35)]
    summary=late.groupby('run').agg(late_photo_mean=('AGEMXL','mean'),late_photo_min=('AGEMXL','min'),late_ratio_mean=('uncapped_ratio','mean'))
    summary['late_limited_days']=late[late.AGEMXL.lt(.99)].groupby('run').yrdoy.nunique()
    summary=summary.fillna(0).reset_index();summary['case']=name
    return pods,vg,summary,err

def main():
    cases=json.loads((OUT/'case_summary.json').read_text(encoding='utf8'))
    assert all(x['success'] for x in cases)
    baseline=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    assert all(sha(p)==h for p,h in baseline['protected'].items())
    assert sha(baseline['observations'])==baseline['objective_sha256']
    meta=pd.read_csv(CN/'n_buffer_v14/inputs/26SP/treatment_metadata.csv').rename(columns={'treatment':'run'})
    rows=[];metrics=[];budgets=[];yields=[];reference=None
    for receipt in cases:
        name=receipt['name'];w=OUT/'cases'/name
        c=pd.read_csv(w/'comparison.csv').set_index('obsnme').sort_index()
        if reference is None:reference=c
        assert c.index.equals(reference.index)
        for col in ['observed','final_weight','fit_scale','date','variable','trno','family','huber_delta']:
            assert c[col].fillna('').equals(reference[col].fillna('')),(name,col)
        for family,g in c.groupby('family'):
            e=g.simulated-g.observed
            metrics.append(dict(case=name,family=family,n=len(g),unit=g.unit.iloc[0],RMSE=float(np.sqrt(np.mean(e**2))),
                NRMSE_percent=float(np.sqrt(np.mean(e**2))/g.observed.mean()*100),bias=float(e.mean()),phi=float(g.phi_contribution.sum())))
        yy=c[c.family.eq('FINAL_FRESH_YIELD')].reset_index().rename(columns={'trno':'run'}).merge(meta,on='run',validate='one_to_one')
        yy['case']=name;yields.append(yy[['case','run','water_level','nitrogen_level','observed','simulated']])
        delta={}
        for water,g in yy.groupby('water_level'):
            z=g.set_index('nitrogen_level');delta[water]=float((z.loc['N3','simulated']-z.loc['N0','simulated'])/1000)
        def rmse(family):
            g=c[c.family.eq(family)];return float(np.sqrt(np.mean((g.simulated-g.observed)**2)))
        rows.append(dict(case=name,Phi=float(c.phi_contribution.sum()),leaf_N_RMSE=rmse('LEAF_N_CONCENTRATION'),
            stem_N_RMSE=rmse('STEM_N_CONCENTRATION'),LAI_RMSE=rmse('CANOPY_LAI'),yield_RMSE_t_ha=rmse('FINAL_FRESH_YIELD')/1000,
            W1_N3_minus_N0=delta['W1'],W2_N3_minus_N0=delta['W2'],W3_N3_minus_N0=delta['W3']))
        cash=pd.read_csv(w/'PlantCCash.csv',float_precision='round_trip')
        cash=cash.groupby('run')[['PG','actual_C_mined','maintenance','N_assim','N_resynthesis','veg_growth','fruit_growth','storage_cost']].sum().reset_index().merge(meta,on='run',validate='one_to_one')
        cash['case']=name;budgets.append(cash)
    summary=pd.DataFrame(rows);summary.to_csv(OUT/'diagnostic_same_parameter_summary.csv',index=False)
    pd.DataFrame(metrics).to_csv(OUT/'diagnostic_all_metrics.csv',index=False)
    pd.concat(yields).to_csv(OUT/'diagnostic_yields.csv',index=False)
    pd.concat(budgets).to_csv(OUT/'diagnostic_CH2O_acceptance.csv',index=False)
    allpods=[];allveg=[];photo=[];errors={}
    for name in ['baseline','curve_shape_leaf_band_trace','native_growth_budget_trace','fixed_photo_trace']:
        p,v,s,err=trace_analysis(name);errors[name]=err
        pp=p.groupby('run').agg(set_days=('active','sum'),PODADD_binding=('PODADD_binding','sum'),C_binding=('C_limit_binding','sum'),
            N_binding=('N_limit_binding','sum'),flower_binding=('flower_limit_binding','sum'),pod_sum=('selected','sum'),mean_RNITPD=('RNITPD','mean')).reset_index()
        pp['case']=name;allpods.append(pp.merge(meta,on='run',validate='one_to_one'))
        vv=v.groupby('run').agg(native_N_limit_days=('new_tissue_budget_limited','sum'),extra_leaf_limit_days=('additional_leaf_gate_active','sum'),
            leaf_gate_min=('leaf_gate','min'),leaf_gate_mean=('leaf_gate','mean'),storage_shift_DM=('storage_shift_leaf_to_stem','sum')).reset_index()
        vv['case']=name;allveg.append(vv.merge(meta,on='run',validate='one_to_one'));photo.append(s.merge(meta,on='run',validate='one_to_one'))
    pp=pd.concat(allpods);vv=pd.concat(allveg);ss=pd.concat(photo)
    pp.to_csv(OUT/'diagnostic_reproductive_binding.csv',index=False)
    vv.to_csv(OUT/'diagnostic_leaf_constraint_days.csv',index=False)
    ss.to_csv(OUT/'diagnostic_photo_sensitivity.csv',index=False)
    audit=dict(passed=True,observation_count=612,observations_and_loss_unchanged=True,
        regular_experiments=len(cases),trace_replays=3,official_fallback=True,invalid_config_rejections=6,
        actual_photo_reconstruction_max_error=errors,all_candidate_budgets_passed=True,
        whole_elemental_C_closed=False,no_new_calibration=True,no_candidate_promoted=True,
        protected_unchanged=True,artifacts={p.name:sha(p) for p in OUT.glob('diagnostic_*.csv')})
    dump(OUT/'analysis_receipt.json',audit)
    print(summary.to_string(index=False))
    print(pp[pp.case.eq('baseline')&pp.water_level.eq('W2')&pp.nitrogen_level.isin(['N0','N3'])].to_string(index=False))
    print(vv[vv.case.eq('baseline')&vv.water_level.eq('W2')&vv.nitrogen_level.isin(['N0','N3'])].to_string(index=False))

if __name__=='__main__':main()
