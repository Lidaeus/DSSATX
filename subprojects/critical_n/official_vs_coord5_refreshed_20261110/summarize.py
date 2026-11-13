from pathlib import Path
from replay import BUNDLES, OUT, ROOT
import pandas as pd

def main():
    atlas=OUT/'atlas'
    c=pd.read_csv(atlas/'yield_contrasts.csv')
    c['delta_n_kg_ha']=float('nan')
    records=[]
    for season,bundle in BUNDLES.items():
        rates=pd.read_csv(Path('D:/Tomato_Cal_Cold_Storage/bundle_retirement_20261105/calibration')/bundle/'fertilizer_event_audit.csv')
        rates=rates.groupby(['氮水平','施肥方案F'])['N kg/ha'].sum()
        assert rates.groupby(level=0).size().eq(1).all()
        rates=rates.droplevel(1)
        for i,r in c[c.season.eq(season)].iterrows():
            hi,lo=r.contrast.split('-')
            if r.stratum in ('W1','W2','W3') and hi in rates and lo in rates:
                c.loc[i,'delta_n_kg_ha']=rates[hi]-rates[lo]
        w=OUT/'replay/coord5'/season
        b=pd.read_csv(w/'NCBalance.csv')
        for field in [x for x in b if x.endswith('_residual')]:
            records.append(dict(season=season,field=field,rows=len(b),max_abs_native=b[field].abs().max()))
    c['marginal_yield_kg_per_kg_n']=c.delta_kg_ha/c.delta_n_kg_ha
    keys=['season','stratum','contrast']
    reference=c[c.model.eq('observed')].set_index(keys).delta_kg_ha
    c=c.join(reference.rename('observed_delta_kg_ha'),on=keys)
    c['abs_contrast_error_kg_ha']=(c.delta_kg_ha-c.observed_delta_kg_ha).abs()
    c.to_csv(atlas/'yield_contrasts_with_rates.csv',index=False)
    pd.DataFrame(records).to_csv(atlas/'coord5_native_balance_residuals.csv',index=False)

if __name__=='__main__':
    main()


