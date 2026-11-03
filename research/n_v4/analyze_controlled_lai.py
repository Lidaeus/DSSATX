"""Independent native-input read-back and descriptive controlled-crop responses."""
import json,re,sys
import numpy as np
import pandas as pd
from lai_workflow import OUT,dump,sha

def native_table(path):
    records=[];run=None;columns=None
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith('*RUN'):run=int(re.match(r'\*RUN\s+(\d+)',line)[1])
        elif line.startswith('@YEAR'):columns=line[1:].split()
        elif columns and re.match(r'^\s+20\d{2}\s',line):
            values=list(map(float,line.split()))
            assert len(values)==len(columns),(path,len(values),len(columns))
            records.append(dict(run=run,**dict(zip(columns,values))))
    return pd.DataFrame(records)

def main(revision='r2'):
    rows=[];daily=[];receipts=[]
    for kind in ['gradient','recovery','pulse','low_light','initial_N']:
        for variant in ['slow_reserve','lai_slow']:
            attempt='a4' if kind in ['recovery','initial_N'] else 'a3'
            w=OUT/'controlled'/f'{revision}_{kind}_{variant}_{attempt}'
            receipt=json.loads((w/'receipt.json').read_text(encoding='utf8'));assert receipt['success']
            d=pd.read_csv(w/'PlantNLAI.csv',float_precision='round_trip')
            d['dap']=d.yrdoy-2026073;d['scenario']=kind;d['variant']=variant
            schedule=pd.read_csv(w/'controlled_N_schedule.csv')
            soil=native_table(w/'SoilNi.OUT');weather=native_table(w/'Weather.OUT')
            # Native applied-N cumulative is independent of our generated CSV.
            applied=soil.sort_values('DOY').groupby('run').NAPC.last()
            expected=schedule.groupby('run').nitrate_fertilizer_kgN_ha.sum()
            assert (abs(applied-expected)<=.51).all(),(kind,applied,expected)
            # Native initialization through the actual FileX fixed-field reader.
            init=soil.sort_values('DOY').groupby('run').first()
            np.testing.assert_allclose(init.NI1D,receipt['provenance'].get('initial_NO3_ppm',[.25]*12),atol=.000001,rtol=0)
            np.testing.assert_allclose(init.NH1D,.5,atol=.000001,rtol=0)
            cash=pd.read_csv(w/'PlantCCash.csv',float_precision='round_trip')
            d=d.merge(cash[['run','yrdoy','PG','N_assim','veg_growth','fruit_growth','actual_C_mined']],on=['run','yrdoy'],validate='one_to_one')
            if kind=='recovery':
                cols=[c for c in d.columns if c not in ['run','scenario','variant']]
                for run in range(1,7):
                    left=d[(d.run==run)&(d.dap<35)][cols].reset_index(drop=True)
                    right=d[(d.run==run+6)&(d.dap<35)][cols].reset_index(drop=True)
                    pd.testing.assert_frame_equal(left,right,check_exact=True)
            if kind=='pulse':
                cols=[c for c in d.columns if c not in ['run','scenario','variant']]
                for run in range(1,7):
                    pd.testing.assert_frame_equal(d[d.run==run][cols].reset_index(drop=True),d[d.run==run+6][cols].reset_index(drop=True),check_exact=True)
                for run in range(1,4):assert expected[run]==expected[run+3]
            if kind=='low_light':
                ref=OUT/'controlled'/f'{revision}_gradient_{variant}_a3'
                previous=pd.read_csv(ref/'PlantNLAI.csv',float_precision='round_trip')
                pd.testing.assert_frame_equal(d[d.dap<35][previous.columns].reset_index(drop=True),previous[previous.yrdoy<2026108].reset_index(drop=True),check_exact=True)
                original=native_table(ref/'Weather.OUT')
                ww=weather.merge(original,on=['run','YEAR','DOY'],suffixes=('_low','_control'),validate='one_to_one')
                altered=ww.DOY.between(108,137)
                assert (ww.loc[altered,'SRAD_low']<=ww.loc[altered,'SRAD_control']*.25+.051).all()
                np.testing.assert_allclose(ww.loc[~altered,'SRAD_low'],ww.loc[~altered,'SRAD_control'],atol=0,rtol=0)
            for run,g in d.groupby('run'):
                reserve=pd.read_csv(w/'PlantNP2.csv',float_precision='round_trip');rr=reserve[reserve.run.eq(run)]
                rows.append(dict(scenario=kind,variant=variant,run=run,total_N_kg_ha=float(expected[run]),
                    initial_NO3_ppm=float(init.loc[run,'NI1D']),
                    LAI_max=float(g.LAI_end.max()),LAI_end=float(g.LAI_end.iloc[-1]),
                    gross_new_area=float(g.new_leaf_area.sum()/10000),lost_area=float(g.old_leaf_area_lost.sum()/10000),
                    N_uptake_kg_ha=float(g.N_uptake_day.sum()*10),N_assim_kg_ha=float(g.N_assim_day.sum()*10),
                    response_min=float(g.state_response.min()),response_mean=float(g.state_response.mean()),
                    response_during_withdrawal=float(g[g.dap.between(35,84 if kind=='recovery' else 64)].state_response.mean()),
                    response_after_resumption=float(g[g.dap.between(85 if kind=='recovery' else 65,114 if kind=='recovery' else 94)].state_response.mean()),
                    R_fast_gN_m2=float((rr.R_fast_leaf+rr.R_fast_stem).sum()),
                    R_sen_recovery_gN_m2=float((rr.R_sen_recovery_leaf+rr.R_sen_recovery_stem).sum()),
                    PG_35_64=float(g[g.dap.between(35,64)].PG.sum()),
                    leaf_new_DM_35_64=float(g[g.dap.between(35,64)].dm_leaf_actual.sum())))
            receipts.append(dict(case=w.name,passed=True,native_N_input_readback=True,
                soil_initial_fixed_field_readback=True,pre_event_state_identical=True if kind in ['recovery','low_light'] else None,
                repeated_treatment_reset_verified=kind=='pulse',synthetic_not_observed=True))
            daily.append(d)
    summary=pd.DataFrame(rows);summary.to_csv(OUT/f'diagnostic_controlled_summary_{revision}.csv',index=False)
    pd.concat(daily,ignore_index=True).to_csv(OUT/f'diagnostic_controlled_daily_{revision}.csv',index=False)
    dump(OUT/f'controlled_validation_{revision}.json',dict(passed=True,scenarios=5,batches=len(receipts),treatments=120,
        actual_native_inputs_verified=True,synthetic_not_empirical_validation=True,cases=receipts,
        whole_elemental_C_closed=False,not_a_parameter_calibration=True,
        artifact_sha256=sha(OUT/f'diagnostic_controlled_summary_{revision}.csv')))
    print(summary[summary.scenario.eq('gradient')&summary.variant.eq('lai_slow')].to_string(index=False))
    print(summary[summary.scenario.eq('recovery')&summary.variant.eq('lai_slow')&summary.run.isin([6,12])].to_string(index=False))

if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else 'r3')
