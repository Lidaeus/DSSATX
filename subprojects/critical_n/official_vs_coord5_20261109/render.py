import sys
from replay import ROOT, OUT, BUNDLES
sys.path.insert(0,str(ROOT))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd
from src.calibration.single_season_n import read_native
from src.calibration.sa98_joint40 import extract
from tools.calibration import run_dual_morris98_trial_20261105 as trial

COLORS={'N0':'#707070','N1':'#2980B9','N2':'#E67E22','N3':'#C0392B'}
MODELS={'official':'Official','coord5':'V15 coordination + 5 days'}
GROUPS=[
 ('canopy',[('LAID','LAI'),('CHTD','Height (m)'),('LWAD','Leaf DM (kg/ha)'),('SWAD','Stem DM (kg/ha)')]),
 ('organ_n',[('LEAF_N_PCT','Leaf N (%)'),('STEM_N_PCT','Stem N (%)'),('LNAD','Leaf N (kg/ha)'),('SNAD','Stem N (kg/ha)')]),
 ('uptake',[('NUPC','Cumulative plant N uptake (kg/ha)'),('N_DAILY','Daily N uptake (kg/ha/d)'),('TRL','Total root length (m/m2)'),('RWAD','Root DM (kg/ha)'),('RDPD','Root depth (cm)')]),
 ('water_soil',[('SWTD','Profile water storage (mm)'),('EPAA','Transpiration (mm/d)'),('NITD','Profile nitrate N (kg/ha)'),('NHTD','Profile ammonium N (kg/ha)')]),
 ('stress',[('WSPD','Photosynthesis water stress'),('WSGD','Growth water stress'),('NSTD','Growth N stress')]),
 ('yield',[('CHFPW','Cumulative fresh yield (kg/ha)'),('HFPOW','Fresh harvest (kg/ha)'),('CHPDT','Cumulative dry yield (kg/ha)')]),
 ('coordination',[('uptake_psi','Uptake psi'),('total_psi','Total psi'),('vegetative_nni','Vegetative NNI'),('leaf_reserve','Leaf reserve (g N/m²)'),('stem_reserve','Stem reserve (g N/m²)'),('growth_request','Growth N request'),('repair_request','Repair N request'),('dmax_kgN_ha','Acceptance limit (kg N/ha)')])
]

def metrics(g):
    o,s=g.observed,g.simulated
    e=s-o
    rmse=np.sqrt((e**2).mean())
    div=((o-o.mean())**2).sum()
    will=((s-o.mean()).abs()+(o-o.mean()).abs()).pow(2).sum()
    return pd.Series(dict(n=len(g),bias=e.mean(),rmse=rmse,nrmse_pct=100*rmse/abs(o.mean()) if o.mean() else np.nan,
                          r2=o.corr(s)**2 if len(g)>1 and o.std()>0 and s.std()>0 else np.nan,
                          nse=1-(e**2).sum()/div if div else np.nan,d=1-(e**2).sum()/will if will else np.nan))

def save(fig,pdf,dest,name):
    fig.savefig(dest/f'diagnostic_{name}.png',dpi=155)
    pdf.savefig(fig)
    plt.close(fig)

def main():
    dest=OUT/'atlas'
    dest.mkdir(exist_ok=True)
    allpairs=[]; allmetrics=[]; allresponses=[]
    with PdfPages(dest/'diagnostic_atlas.pdf') as pdf:
        for season,name in BUNDLES.items():
            bundle=ROOT/'data/user/experiments'/name
            meta=pd.read_csv(bundle/'treatment_metadata.csv').set_index('treatment')
            trial.DATES={**trial.DATES,season:pd.to_datetime(pd.read_csv(bundle/'FileA_values.csv').ADAT.astype(int).astype(str),format='%y%j').dt.strftime('%Y-%m-%d').iloc[0]}
            obs=trial.observation_catalog(bundle,season)
            obs=obs.loc[obs.variable.ne('FRUIT_N_PCT')].reset_index(drop=True).assign(role='diagnostic')
            obs['point_id']=obs.index
            obs['fourth_n_visit']=obs.date.eq('2026-07-17') & obs.variable.isin(['LEAF_N_PCT','STEM_N_PCT'])
            daily={}; pairs={}
            for model in MODELS:
                work=OUT/'replay'/model/season
                p=extract(work,obs,strict=False)
                p['model']=model
                pairs[model]=p
                pg=read_native(work/'PlantGro.OUT')
                assert set(pg.index.get_level_values('trno'))==set(meta.index)
                frames=[pg]
                for file,fields in [('PlantN',['LN%D','SN%D','LNAD','SNAD','NUPC']),('FreshWt',['CHFPW','HFPOW','CHPDT']),('SoilWat',['SWTD','IRRC','PREC']),('SoilNi',['NIAD','NITD','NHTD']),('ET',['EPAA'])]:
                    frames.append(read_native(work/f'{file}.OUT')[fields].rename(columns={'LN%D':'LEAF_N_PCT','SN%D':'STEM_N_PCT'}))
                d=frames[0].join(frames[1:],how='left').reset_index()
                d['N_DAILY']=d.groupby('trno').NUPC.diff()
                depths=np.array([5,10,15,10,10,10,10,10,20,80])
                d['TRL']=d[[f'RL{i}D' for i in range(1,11)]].where(lambda x:x>=0).mul(depths*100,axis=1).sum(axis=1,min_count=10)
                if model=='coord5':
                    for file,fields in [('NDecision',['uptake_psi','total_psi','growth_request','repair_request','dmax_kgN_ha']),('OrganNState',['vegetative_nni','leaf_reserve','stem_reserve'])]:
                        x=pd.read_csv(work/f'{file}.csv').rename(columns={'trt':'trno'})
                        x['date']=pd.to_datetime(x.yrdoy.astype(str),format='%Y%j').dt.strftime('%Y-%m-%d')
                        d=d.merge(x[['trno','date',*fields]],on=['trno','date'],how='left',validate='one_to_one')
                daily[model]=d
                d.to_csv(dest/f'{season}_{model}_daily.csv',index=False)
            common=set.intersection(*(set(p.loc[p.comparison_status.eq('matched'),'point_id']) for p in pairs.values()))
            both=pd.concat(pairs.values(),ignore_index=True)
            both['common_pair']=both.point_id.isin(common)
            allpairs.append(both)
            scored=both[both.common_pair & ~both.fourth_n_visit].copy()
            terminal=scored[scored.variable.isin(['CHFPW','CHPDT'])].sort_values('date').groupby(['model','trno','variable']).tail(1)
            scored=pd.concat([scored,terminal.assign(variable='FINAL_'+terminal.variable)])
            allmetrics.append(scored.groupby(['season_id','model','variable'],dropna=False).apply(metrics,include_groups=False).reset_index())
            water=sorted(meta.water_level.unique())
            for topic,fields in GROUPS:
                fig,axes=plt.subplots(len(fields),len(water),squeeze=False,sharex='col',sharey='row',figsize=(4.5*len(water),2.05*len(fields)+1),layout='constrained')
                fig.suptitle(f'{season} | {topic} | official solid, V15 dashed; points observed')
                for row,(field,label) in enumerate(fields):
                    for col,w in enumerate(water):
                        ax=axes[row,col]
                        if row==0: ax.set_title(w)
                        if col==0: ax.set_ylabel(label)
                        for t,m in meta[meta.water_level.eq(w)].iterrows():
                            color=COLORS[m.nitrogen_level]
                            for model,d in daily.items():
                                if field not in d: continue
                                f=d[d.trno.eq(t)].dropna(subset=[field])
                                y=f[field].where(f[field]>-90)
                                if field=='HFPOW':
                                    ax.scatter(f.loc[y.gt(0),'DAP'],y[y.gt(0)],c=color,s=10,marker='.' if model=='official' else '+')
                                elif field in ['CHFPW','CHPDT']:
                                    ax.step(f.DAP,y,where='post',color=color,ls='-' if model=='official' else '--',lw=1)
                                else: ax.plot(f.DAP,y,color=color,ls='-' if model=='official' else '--',lw=1)
                            q=obs[obs.trno.eq(t)&obs.variable.eq(field)].merge(daily['official'][['trno','date','DAP']],on=['trno','date'])
                            for fourth,g in q.groupby('fourth_n_visit'):
                                ax.scatter(g.DAP,g.observed,edgecolor=color,facecolor='none' if fourth else color,s=18,zorder=5)
                        if row==len(fields)-1: ax.set_xlabel('Days after planting')
                fig.legend([plt.Line2D([],[],color=c) for c in COLORS.values()],list(COLORS),loc='outside lower center',ncol=4)
                save(fig,pdf,dest,f'{season}_{topic}')
            term=terminal[terminal.variable.eq('CHFPW')].pivot(index='trno',columns='model',values='simulated')
            term['observed']=terminal[terminal.variable.eq('CHFPW')].drop_duplicates('trno').set_index('trno').observed
            term=term.join(meta)
            fig,axes=plt.subplots(1,3,sharey=True,figsize=(12,4),layout='constrained')
            for ax,key in zip(axes,['observed',*MODELS]):
                for w,g in term.groupby('water_level'):
                    g=g.sort_values('nitrogen_level')
                    ax.plot(g.nitrogen_level,g[key]/1000,'o-',label=w)
                ax.set_title(MODELS.get(key,'Observed'))
                ax.set_xlabel('N treatment')
            axes[0].set_ylabel('Final fresh yield (t/ha)')
            axes[-1].legend()
            save(fig,pdf,dest,f'{season}_yield_response')
            for key in ['observed',*MODELS]:
                mat=term.pivot(index='water_level',columns='nitrogen_level',values=key)
                for w in mat.index:
                    for l,h in zip(mat.columns[:-1],mat.columns[1:]):
                        if pd.notna(mat.loc[w,[l,h]]).all():
                            allresponses.append((season,key,w,f'{h}-{l}',mat.loc[w,h]-mat.loc[w,l]))
                if {'W1','W3'}<=set(mat.index) and {'N0','N3'}<=set(mat.columns):
                    for n in mat.columns:
                        allresponses.append((season,key,n,'W3-W1',mat.loc['W3',n]-mat.loc['W1',n]))
                    allresponses.append((season,key,'W3-W1','N3-N0',(mat.loc['W3','N3']-mat.loc['W3','N0'])-(mat.loc['W1','N3']-mat.loc['W1','N0'])))
    pd.concat(allpairs).to_csv(dest/'pairs.csv',index=False)
    pd.concat(allmetrics).to_csv(dest/'metrics.csv',index=False)
    pd.DataFrame(allresponses,columns=['season','model','stratum','contrast','delta_kg_ha']).to_csv(dest/'yield_contrasts.csv',index=False)

if __name__=='__main__':
    main()


