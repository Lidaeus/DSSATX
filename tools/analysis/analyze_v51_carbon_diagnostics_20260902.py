"""Official carbon output analysis; reconstructed states are not direct AGEFAC."""
from pathlib import Path
import json
import re
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.experiments.replay_v51_carbon_diagnostics_20260902 import OUT, SOURCE, CASES, verify_seal
from tools.analysis.audit_v46_best71_early_nstress_20260831 import parse_plantgro


def structural_leaf_n(pcnl, reserve_pct):
    pcnl, reserve_pct = np.asarray(pcnl, float), np.asarray(reserve_pct, float)
    if not np.isfinite(pcnl).all() or not np.isfinite(reserve_pct).all() or (pcnl < 0).any() or (reserve_pct < 0).any() or (reserve_pct >= 100).any():
        raise ValueError('Invalid leaf N or reserve denominator')
    return pcnl/(1-reserve_pct/100)


def parse_carbon(path):
    """Fixed-width native PlantC: retain rows with overflow in unrelated fields."""
    spans=[(1,5),(6,9),(10,15),(16,21),(22,28)]
    spans += [(28+8*i,36+8*i) for i in range(5)]
    spans += [(68,76),(76,83),(83,90),(91,97),(98,104),(105,112),(113,120),(121,128)]
    rows=[]
    run=None
    header=None
    for line in Path(path).read_text().splitlines():
        m=re.match(r'\*RUN\s+(\d+)',line)
        if m: run=int(m[1]); header=None
        if line.startswith('@YEAR'): header=line.replace('@YEAR','YEAR',1).split(); assert len(header)==18
        if run is None or header is None or not re.fullmatch(r'\d{4}',line[1:5]): continue
        row={'global_run':run}
        for col,(a,b) in zip(header,spans):
            value=line[a:b].strip()
            row[col]=np.nan if value and set(value)=={'*'} else float(value)
        rows.append(row)
    if not rows: raise ValueError('Empty carbon output')
    result=pd.DataFrame(rows)
    required=['YEAR','DOY','DAS','DAP','PHAD','CL%D','CHAD']
    assert np.isfinite(result[required]).all().all(), 'Missing required carbon field'
    return result


def main():
    verify_seal()
    meta = pd.read_csv(ROOT/'configs/runs/e02_mapping_26sp_w2_w1_20260830.csv')[['season_id','treatment','water_level','nitrogen_level']]
    summaries, contrasts, methods, noon = [], [], [], []
    for case in CASES:
        for season in ['25SP','26SP']:
            dest = OUT/case/season
            raw = SOURCE/case/'_seasons'/season
            key = ['global_run','YEAR','DOY','DAS','DAP']
            pg, pn = [parse_plantgro(dest/name) for name in ['PlantGro.OUT','PlantN.OUT']]
            pc = parse_carbon(dest/'PlantC.OUT')
            assert all(x[key].drop_duplicates().shape[0] == len(x) for x in [pg,pc,pn])
            daily = pg.merge(pc, on=key, validate='one_to_one')
            assert len(daily) == len(pg) == len(pc)
            daily = daily.merge(pn[[*key,'NUPC','CNAD','LNAD','SNAD','GNAD']], on=key,validate='one_to_one')
            mapping = pd.read_csv(raw/f'{season}_deterministic_process_compare.csv')[['RUN','TN']].drop_duplicates()
            daily = daily.merge(mapping,left_on='global_run',right_on='RUN',validate='many_to_one')
            daily = daily.merge(meta[meta.season_id.eq(season)],left_on='TN',right_on='treatment',validate='many_to_one')
            assert daily.water_level.notna().all()
            assert daily.groupby('TN').DAP.apply(lambda s: s.diff().dropna().eq(1).all()).all()
            lines = (dest/'TMGRO048.SPE').read_text().splitlines()
            curve = next(x for x in lines if 'FNPGN(4)' in x).split()
            nslope = float(next(x for x in lines if 'NSLOPE,LNREF' in x).split()[2])
            f2, f3 = float(curve[1]), float(curve[2])
            ep = parse_plantgro(dest/'ETPhot.OUT')
            ep = ep.merge(daily[['global_run','YEAR','DOY','DAP','TN','nitrogen_level','water_level']],on=['global_run','YEAR','DOY'],validate='one_to_one')
            assert len(ep)==len(daily)
            for tn,g in ep[ep.DAP>0].groupby('TN'):
                noon.append(dict(case=case,season=season,TN=tn,water=g.water_level.iloc[0],nitrogen=g.nitrogen_level.iloc[0],
                                 sun_noon_N_min=g['N%LN'].min(),sun_noon_N_max=g['N%LN'].max(),
                                 shade_noon_N_min=g['N%HN'].min(),shade_noon_N_max=g['N%HN'].max(),
                                 both_noon_N_on_plateau_fraction=((g['N%LN']-.005>=f2)&(g['N%HN']-.005>=f2)&(g['N%LN']+.005<=f3)&(g['N%HN']+.005<=f3)).mean()))
            # Output quantization interval, not biological confidence interval.
            daily['RNITP_reconstructed_endday'] = structural_leaf_n(daily['LN%D'],daily['CL%D'])
            low = structural_leaf_n(np.maximum(0,daily['LN%D']-.005), np.maximum(0,daily['CL%D']-.0005))
            high = structural_leaf_n(daily['LN%D']+.005,daily['CL%D']+.0005)
            daily['leafN_lower_with_rounding_and_partition'] = low-.5*abs(nslope)*(daily.LAID+.0005)
            daily['leafN_upper_with_rounding_and_partition'] = high+.5*abs(nslope)*(daily.LAID+.0005)
            daily['entire_leafN_envelope_on_plateau'] = (daily.leafN_lower_with_rounding_and_partition >= f2) & (daily.leafN_upper_with_rounding_and_partition <= f3)
            daily['date_code'] = daily.YEAR%100*1000+daily.DOY
            daily.to_csv(dest/'carbon_nitrogen_daily.csv',index=False)
            # Actual requested method, not assumed from file names.
            tmx = next(dest.glob('*.TMX')).read_text().splitlines()
            ix = next(i for i,x in enumerate(tmx) if x.startswith('@N METHODS'))
            fields, values = tmx[ix].split(),tmx[ix+1].split()
            method = values[fields.index('PHOTO')]
            assert method == 'L', (case,season,method)
            methods.append(dict(case=case,season=season,PHOTO=method,NSLOPE=nslope,FNPGN2=f2,FNPGN3=f3))
            harvest = pd.read_csv(raw/f'{season}_deterministic_harvest_compare.csv').sort_values('DATE').groupby('TN').tail(1).set_index('TN')
            for tn,g in daily.groupby('TN'):
                final=g.sort_values(['YEAR','DOY']).iloc[-1]
                active=g[g.DAP>0]
                summaries.append(dict(case=case,season=season,TN=tn,water=final.water_level,nitrogen=final.nitrogen_level,
                    days=len(active),RNITP_min=active.RNITP_reconstructed_endday.min(), RNITP_max=active.RNITP_reconstructed_endday.max(),
                    leafN_envelope_plateau_fraction=active.entire_leafN_envelope_on_plateau.mean(),
                    leaf_reserve_mean_pct=active['CL%D'].mean(), leaf_reserve_max_pct=active['CL%D'].max(),
                    PHAD_sum=active.PHAD.sum(), CHAD_sum=active.CHAD.sum(),
                    NUPC_final=final.NUPC, CNAD_final=final.CNAD,LNAD_final=final.LNAD,SNAD_final=final.SNAD,GNAD_final=final.GNAD,
                    LAI_final=final.LAID,LWAD_final=final.LWAD,SWAD_final=final.SWAD,PWAD_final=final.PWAD,
                    FRESH_CUM_final=harvest.loc[tn,'SIM_FRESH_CUM'], OBS_FRESH_CUM_final=harvest.loc[tn,'OBS_FRESH_CUM']))
            for (water,date),g in daily.groupby(['water_level','date_code']):
                gg=g.set_index('nitrogen_level')
                for high_n,low_n in [('N3','N1'),('N3','N2')]:
                    if high_n not in gg.index or low_n not in gg.index: continue
                    for var in ['PHAD','RNITP_reconstructed_endday','NUPC','LAID','LWAD','PWAD']:
                        a,b=float(gg.loc[high_n,var]),float(gg.loc[low_n,var])
                        contrasts.append(dict(case=case,season=season,water=water,date=date,contrast=high_n+'-'+low_n,
                                              variable=var,high=a,low=b,delta=a-b))
    s=pd.DataFrame(summaries)
    s.to_csv(OUT/'physiology_summary.csv',index=False)
    pd.DataFrame(contrasts).to_csv(OUT/'physiology_contrasts.csv',index=False)
    pd.DataFrame(methods).to_csv(OUT/'photosynthesis_methods.csv',index=False)
    pd.DataFrame(noon).to_csv(OUT/'direct_noon_leafN.csv',index=False)
    # Grain: same season, same water, different N; no averaging of treatment roles.
    rows=[]
    for (case,season,water),g in s.groupby(['case','season','water']):
        g=g.set_index('nitrogen')
        for h,l in [('N3','N1'),('N3','N2')]:
            if h not in g.index or l not in g.index:continue
            for var in ['PHAD_sum','NUPC_final','CNAD_final','LNAD_final','SNAD_final','GNAD_final','FRESH_CUM_final','OBS_FRESH_CUM_final']:
                a,b=g.loc[h,var],g.loc[l,var]
                rows.append(dict(case=case,season=season,water=water,contrast=h+'-'+l,variable=var,high=a,low=b,delta=a-b,
                                 relative_pct=100*(a-b)/b if b else np.nan))
    pd.DataFrame(rows).to_csv(OUT/'seasonal_N_contrasts.csv',index=False)
    # Recompute the positive-control fit with the existing event-date convention.
    sys.path.insert(0,str(ROOT/'tools/analysis'))
    from render_arm_d_best17_diagnostics_20260820 import build_season_harvest_compare, build_season_process_compare, compute_metrics
    metrics=[]
    for label in ['control_A47','probe_pgeff']:
        for season in ['25SP','26SP']:
            p=OUT/label/season
            h=build_season_harvest_compare(p,season)
            g=build_season_process_compare(p,season)
            g=g[(g.OBS_LAID!=-99)&(g.SIM_LAID!=-99)]
            end=h.sort_values('DATE').groupby('TN').tail(1)
            metrics.append(dict(case=label,season=season,
                                fresh_nse=compute_metrics(h.OBS_FRESH_CUM,h.SIM_FRESH_CUM)['nse'],
                                terminal_rrmse=compute_metrics(end.OBS_FRESH_CUM,end.SIM_FRESH_CUM)['rrmse_pct'],
                                lai_nse=compute_metrics(g.OBS_LAID,g.SIM_LAID)['nse']))
    pd.DataFrame(metrics).to_csv(OUT/'positive_control_fit_metrics.csv',index=False)
    # Recheck PlantC probe comparisons with overflow-preserving parsing.
    checks=[]
    for parameter in ['phtmax','parmax','pgeff']:
        for season in ['25SP','26SP']:
            a,b=[parse_carbon(OUT/label/season/'PlantC.OUT') for label in ['probe_'+parameter,'control_A47']]
            assert len(a)==len(b)
            if parameter!='pgeff':pd.testing.assert_frame_equal(a,b,check_exact=True)
            checks.append(dict(parameter=parameter,season=season,rows=len(a),
                               PHAD_max_change=float((a.PHAD-b.PHAD).abs().max()),
                               control_GC_pct_overflow_rows=int(b['GC%D'].isna().sum()),
                               probe_GC_pct_overflow_rows=int(a['GC%D'].isna().sum())))
    pd.DataFrame(checks).to_csv(OUT/'carbon_probe_full_row_audit.csv',index=False)
    print(s[s.season.eq('26SP')].groupby(['case','nitrogen']).agg(NUPC=('NUPC_final','mean'), PHAD=('PHAD_sum','mean'),fresh=('FRESH_CUM_final','mean'),plateau=('leafN_envelope_plateau_fraction','mean')).to_string())
    verify_seal()


if __name__ == '__main__':
    main()
