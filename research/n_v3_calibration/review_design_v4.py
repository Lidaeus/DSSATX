"""Read-only, same-observation comparison for the proposed next nitrogen design.

Does not run DSSAT, edit its inputs, or change calibration objectives.
"""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
import pandas as pd

CN = Path('D:/Tomato_Cal/subprojects/critical_n')
OUT = CN / 'reports/N_design_v4_review_20261103'
CURRENT = CN / 'runs/n4864_C4_joint80x4_20261103_r2'
OLD = CN / 'reports/v15_s1_vs_current_20261101'
V15 = CN / 'n_buffer_v15/runs/v15_s1_interface_100x2_20261028'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    done = json.loads((CURRENT / 'completion_receipt.json').read_text(encoding='utf8'))
    design = json.loads((CURRENT / 'design.json').read_text(encoding='utf8'))
    old_receipt = json.loads((V15 / 'selected_deterministic/last_success.json').read_text(encoding='utf8'))
    old_native = Path(old_receipt['trial']) / '26SP'
    current_native = Path(done['best_trial'])
    paths = {
        'V15_S1': OLD / 'comparison_V15_s1.csv',
        'C3': CN / 'reports/n_v3_execution_20261103/cases/delivery_combined/comparison.csv',
        'C4_before_calibration': CN / 'reports/n_v3_c4_execution_20261103/cases/delivery_full/comparison.csv',
        'C4_r2_best': current_native / 'comparison.csv',
    }
    reference = pd.read_csv(paths['C4_r2_best']).set_index('obsnme').sort_index()
    assert len(reference) == 612 and reference.index.is_unique
    metadata = pd.read_csv(CN / 'n_buffer_v14/inputs/26SP/treatment_metadata.csv').rename(columns={'treatment': 'trno'})
    metrics, yields, identity = [], [], []
    for version, path in paths.items():
        c = pd.read_csv(path).set_index('obsnme').sort_index()
        assert c.index.equals(reference.index), version
        for col in ['observed', 'final_weight', 'date', 'trno', 'variable', 'family', 'fit_scale', 'pest_obsval', 'huber_delta']:
            assert c[col].fillna('').equals(reference[col].fillna('')), (version, col)
        error = c.simulated - c.observed
        z = error / c.fit_scale
        loss = 2 * c.huber_delta**2 * (np.sqrt(1 + (z / c.huber_delta)**2) - 1)
        phi = loss * c.final_weight**2
        np.testing.assert_allclose(phi, c.phi_contribution, rtol=1e-8, atol=1e-12)
        identity.append(dict(version=version, observations=len(c), phi=float(phi.sum()), observation_contract_identical=True))
        for family, g in c.groupby('family'):
            e = g.simulated - g.observed
            rmse = float(np.sqrt(np.mean(e**2)))
            denominator = float(((abs(g.simulated-g.observed.mean()) + abs(g.observed-g.observed.mean()))**2).sum())
            metrics.append(dict(version=version, family=family, n=len(g), unit=g.unit.iloc[0], RMSE=rmse,
                                NRMSE_percent=100*rmse/g.observed.mean(), bias=float(e.mean()),
                                d_index=1-float((e**2).sum())/denominator if denominator else None,
                                phi=float(phi.loc[g.index].sum())))
        y = c[c.family.eq('FINAL_FRESH_YIELD')][['trno', 'observed', 'simulated']].merge(metadata, on='trno', validate='one_to_one')
        y['version'] = version
        yields.append(y)
    m = pd.DataFrame(metrics)
    m.to_csv(OUT / 'diagnostic_same612_metrics.csv', index=False)
    pd.DataFrame(identity).to_csv(OUT / 'diagnostic_same612_identity.csv', index=False)
    y = pd.concat(yields, ignore_index=True)
    y.to_csv(OUT / 'diagnostic_final_yields.csv', index=False)
    contrast = []
    for version, q in y.groupby('version'):
        for water, group in q.groupby('water_level'):
            g = group.set_index('nitrogen_level')
            for n in ['N0', 'N1', 'N2']:
                contrast.append(dict(version=version, kind='N3-minus-lower-N', context=water, contrast='N3-'+n,
                                     observed=g.loc['N3','observed']-g.loc[n,'observed'],
                                     simulated=g.loc['N3','simulated']-g.loc[n,'simulated']))
        for nitrogen, group in q.groupby('nitrogen_level'):
            g = group.set_index('water_level')
            for w in ['W1', 'W2']:
                contrast.append(dict(version=version, kind='W3-minus-lower-W', context=nitrogen, contrast='W3-'+w,
                                     observed=g.loc['W3','observed']-g.loc[w,'observed'],
                                     simulated=g.loc['W3','simulated']-g.loc[w,'simulated']))
    contrasts = pd.DataFrame(contrast)
    contrasts['error'] = contrasts.simulated - contrasts.observed
    contrasts['same_sign'] = np.sign(contrasts.simulated).eq(np.sign(contrasts.observed))
    contrasts.to_csv(OUT / 'diagnostic_signed_contrasts.csv', index=False)
    summaries = []
    for (version, kind), g in contrasts.groupby(['version', 'kind']):
        summaries.append(dict(version=version, kind=kind, n=len(g), RMSE_kg_ha=float(np.sqrt(np.mean(g.error**2))), same_sign=int(g.same_sign.sum())))
    pd.DataFrame(summaries).to_csv(OUT / 'diagnostic_contrast_summary.csv', index=False)

    # Read actual six-column DSSAT inputs, rather than comparing optimizer precision.
    sys.path.insert(0, design['runtime'])
    from src.calibration.single_season_n import read_injected_parameters
    parsed = {label: read_injected_parameters(path) for label, path in [('V15_S1', old_native), ('C4_r2_best', current_native)]}
    names = sorted(set.intersection(*(set(v) for v in parsed.values())))
    pars = []
    for name in names:
        old = parsed['V15_S1'][name][0]
        new = parsed['C4_r2_best'][name][0]
        pars.append(dict(name=name, V15_S1=old, C4_r2_best=new, change=new-old,
                         change_percent=100*(new-old)/old if old else None,
                         warning='Same file parameter does not imply same active pathway or physiological meaning'))
    pd.DataFrame(pars).to_csv(OUT / 'diagnostic_native_parameter_readback.csv', index=False)
    pd.DataFrame([dict(name=k, requested_value=v) for k,v in old_receipt['parameters'].items() if k.startswith(('NB_', 'CNC_'))]).to_csv(OUT / 'diagnostic_V15_special_parameters_requested.csv', index=False)
    special={}
    for filename in ['CNCParam.OUT','NBufferParam.OUT']:
        lines=(old_native/filename).read_text(encoding='ascii').splitlines()
        keys=lines[0].lstrip('@').split()
        values=[float(x) for x in lines[1].split()]
        assert len(keys)==len(values)
        special.update(zip(keys,values))
    pd.DataFrame([dict(name=k,actual_value=v) for k,v in special.items()]).to_csv(OUT/'diagnostic_V15_special_parameters_actual.csv',index=False)
    newpars=json.loads((CURRENT/'best_parameters.exact.json').read_text(encoding='utf8'))
    curve=[]
    for w in [.7,.9,1.,2.,4.,8.]:
        oldleaf=(special['CNC_NC_INF']+(special['CNC_A']-special['CNC_NC_INF'])*max(1,w/special['CNC_W0'])**(-special['CNC_B']))/100
        oldstem=(special['CNC_NC_INF']+(special['CNC_A']-special['CNC_NC_INF'])*max(1,w/special['CNC_W0'])**(-special['CNC_B']*special['STEM_BMULT']))/100*parsed['V15_S1']['PROSTI'][0]/parsed['V15_S1']['PROLFI'][0]
        for organ,crit,ratio in [('leaf',oldleaf,parsed['V15_S1']['PROLFF'][0]/parsed['V15_S1']['PROLFI'][0]),('stem',oldstem,parsed['V15_S1']['PROSTF'][0]/parsed['V15_S1']['PROSTI'][0])]:
            cap=special['CAPACITY']*special['CNC_A']/100*(1 if organ=='leaf' else parsed['V15_S1']['PROSTI'][0]/parsed['V15_S1']['PROLFI'][0])
            curve.append(dict(version='V15_S1',organ=organ,W_t_ha=w,Nmin_percent=100*ratio*crit,Ncrit_percent=100*crit,Nmax_percent=100*(crit+cap)))
            newcrit=newpars[organ+'_a']*max(newpars['curve_w0'],w)**(-newpars[organ+'_b'])
            curve.append(dict(version='C4_r2_best',organ=organ,W_t_ha=w,Nmin_percent=100*newpars['min_ratio']*newcrit,Ncrit_percent=100*newcrit,Nmax_percent=100*newpars['max_ratio']*newcrit))
    pd.DataFrame(curve).to_csv(OUT/'diagnostic_reference_curve_values.csv',index=False)

    # Archived daily native mechanisms were already joined to explicit treatment metadata.
    daily = pd.read_csv(OLD / 'daily_native_mechanisms.csv').loc[lambda x: x.model.eq('V15_s1')].copy()
    assert len(daily)==1512 and not daily.duplicated(['trt','yrdoy']).any()
    old_lai_path=CN/'reports/V15_S1_LAI_gradient_audit_20261103/diagnostic_V15_S1_daily_LAI.csv'
    old_lai=pd.read_csv(old_lai_path)
    old_lai['yrdoy']=old_lai.YEAR.astype(int)*1000+old_lai.DOY.astype(int)
    daily=daily.merge(old_lai[['trno','yrdoy','DAP']].rename(columns={'trno':'trt'}),on=['trt','yrdoy'],validate='one_to_one')
    # DAS is three days larger than transplant-based DAP in these native files.
    assert daily.das.sub(daily.DAP).eq(3).all()
    summaries=[]
    for (water,nitrogen,trt),g in daily.groupby(['water_level','nitrogen_level','trt']):
        valid=g[g.kernel_calls.gt(0)]
        late=valid[valid.DAP.ge(35)]
        summaries.append(dict(water=water,nitrogen=nitrogen,trno=trt,
            total_root_N_kg_ha=10*g.root_actual.sum(),total_PG_gCH2O_m2=g.PHAD.sum(),
            fast_mobilized_gN_m2=g.fast_mob.sum(),bound_mobilized_gN_m2=g.bound_mob.sum(),
            maximum_reserve_gN_m2=g.reserve_total.max(),
            capacity_calls=int(valid.kernel_calls.sum()),
            late_mean_factor_call_weighted=float(np.average(late.unweighted_mean_n_factor,weights=late.kernel_calls)),
            late_days_factor_below_099=int(late.unweighted_mean_n_factor.lt(.99).sum())))
    pd.DataFrame(summaries).to_csv(OUT / 'diagnostic_V15_native_mechanisms.csv',index=False)
    integration=CN/'reports/C3_C4_diagnostics_and_calibration_20261103/final_verification/cases/best_trace/PlantNIntegration.csv'
    ni=pd.read_csv(integration)
    root=ni.groupby('run')[['U_NO3','U_NH4']].sum().sum(axis=1).mul(10).rename('total_root_N_kg_ha').rename_axis('trno').reset_index()
    root=root.merge(metadata,on='trno',validate='one_to_one')
    root.to_csv(OUT/'diagnostic_C4_root_N_total.csv',index=False)
    c4_audit=CN/'reports/C4_functional_N_LAI_audit_20261103/diagnostic_treatment_summary.csv'
    newdaily=pd.read_csv(c4_audit).merge(root[['trno','total_root_N_kg_ha']],on='trno',validate='one_to_one')
    ratio=[]
    for version,frame in [('V15_S1',pd.DataFrame(summaries)),('C4_r2_best',newdaily)]:
        for water,g in frame.groupby('water'):
            q=g.set_index('nitrogen')
            yy=y[y.version.eq(version)&y.water_level.eq(water)].set_index('nitrogen_level')
            ratio.append(dict(version=version,water=water,
                root_N_N0_over_N3=q.loc['N0','total_root_N_kg_ha']/q.loc['N3','total_root_N_kg_ha'],
                gross_PG_N0_over_N3=q.loc['N0','total_PG_gCH2O_m2']/q.loc['N3','total_PG_gCH2O_m2'],
                fresh_yield_N0_over_N3=yy.loc['N0','simulated']/yy.loc['N3','simulated'],
                observed_fresh_yield_N0_over_N3=yy.loc['N0','observed']/yy.loc['N3','observed']))
    pd.DataFrame(ratio).to_csv(OUT/'diagnostic_N0_N3_process_ratios.csv',index=False)
    old_c_path=old_native/'CAllocation.csv'
    new_c_path=integration.parent/'PlantCCash.csv'
    cc=[]
    for version,path,key,mapping in [
        ('V15_S1',old_c_path,'trt',{'fruit_ch2o':'fruit_growth','vegetative_ch2o':'veg_growth','assimilation_ch2o':'N_assim','resynthesis_ch2o':'N_resynthesis','carbohydrate_storage_ch2o':'storage_cost'}),
        ('C4_r2_best',new_c_path,'run',{k:k for k in ['fruit_growth','veg_growth','N_assim','N_resynthesis','storage_cost']})]:
        q=pd.read_csv(path).groupby(key)[list(mapping)].sum().rename(columns=mapping).rename_axis('trno').reset_index()
        q=q.merge(metadata,on='trno',validate='one_to_one');q['version']=version
        cc.append(q)
    pd.concat(cc,ignore_index=True).to_csv(OUT/'diagnostic_CH2O_allocations.csv',index=False)

    sources=list(paths.values())+[CURRENT/'design.json',CURRENT/'completion_receipt.json',
        V15/'selected_deterministic/last_success.json',OLD/'daily_native_mechanisms.csv',
        old_native/'DSCSM048.EXE',Path(design['binary']),
        old_native/'TMGRO048.SPE',old_native/'TMGRO048.CUL',old_native/'TMGRO048.ECO',
        current_native/'TMGRO048.SPE',current_native/'TMGRO048.CUL',current_native/'TMGRO048.ECO',
        old_native/'CNCParam.OUT',old_native/'NBufferParam.OUT',integration,CURRENT/'best_parameters.exact.json',old_lai_path,c4_audit,old_c_path,new_c_path,
        Path(__file__)]
    assert sha(old_native/'DSCSM048.EXE')==old_receipt['binary_sha256']
    assert sha(design['binary'])==design['binary_sha256']
    receipt=dict(scope='2026 spring only; archived deterministic outputs; no new runs; no objective edits',
                 observation_count=612,observation_and_loss_identity_verified=True,
                 comparison_is_causal=False,source_hashes={str(p):sha(p) for p in sources},
                 artifacts={p.name:sha(p) for p in OUT.glob('diagnostic_*.csv')})
    (OUT/'diagnostic_review_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(pd.DataFrame(identity).to_string(index=False))
    print(m.pivot(index='family',columns='version',values='RMSE').to_string())
    print(pd.DataFrame(summaries).to_string(index=False))


if __name__ == '__main__':
    main()
