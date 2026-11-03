"""Actual daily C3/C4 run diagnostics, not a publication renderer."""
from pathlib import Path
import argparse,hashlib,json,re,sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

CN=Path('D:/Tomato_Cal/subprojects/critical_n')
OUT=CN/'reports/C3_C4_diagnostics_and_calibration_20261103'
RUNTIME=CN/'runs/n4864_A_joint80x4_20261102_r1/runtime'
sys.path.insert(0,str(RUNTIME))
from src.calibration.single_season_n import read_native
COLORS={'N3':'#C0392B','N2':'#E67E22','N1':'#2980B9','N0':'#707070'}
SHAPES={'W3':'o','W2':'s','W1':'^'}
META=CN/'n_buffer_v14/inputs/26SP/treatment_metadata.csv'
RAW=Path('D:/Tomato_Cal/data/user/experiments/xxql2601_refreshed_20261027/plant_npk_source_values.csv')
plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
    'axes.unicode_minus':False,'font.size':10,'axes.spines.top':False,'axes.spines.right':False})

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(fig,path):
    fig.savefig(path,dpi=190,facecolor='white');plt.close(fig)
def config(path):
    return {k:float(v)for k,v in re.findall(r'(\w+)\s*=\s*([-+\d.eE]+)',path.read_text())}
def title(fig,label,extra=''):
    caption='｜26SP最佳组确定性诊断' if '率定后' in label else '｜26SP固定参数运行诊断'
    fig.suptitle(label+caption,fontsize=14,y=.99)
    fig.text(.5,.015,'工程诊断，未经独立验证；'+extra,ha='center',fontsize=9,color='#555555')

def curve_plot(dest,cfg,curves,label):
    fig,axes=plt.subplots(1,2,figsize=(12,5),sharex=True)
    for ax,organ,cn in zip(axes,['leaf','stem'],['叶片','茎']):
        c=curves[curves.organ.eq(organ)]
        ax.fill_between(c.W_t_ha,c.Nmin,c.Nmax,color='#DDE7DD',alpha=.75)
        for key,color,ls in [('Nmax','#4477AA','--'),('Ncrit','#17692C','-'),('Nmin','#AA7733','--')]:
            ax.plot(c.W_t_ha,c[key],c=color,ls=ls,lw=2 if key=='Ncrit'else 1.5,label=key)
        ax.axvline(cfg['curve_w0'],c='#777777',lw=.9,ls=':')
        ymax=max(4.5 if organ=='leaf'else 2.8,float(np.ceil(c.Nmax.max()*1.1*2)/2))
        ax.set(title=f'{cn}：a={100*cfg[organ+"_a"]:.4f}%，b={cfg[organ+"_b"]:.4f}',xlabel='茎叶站存干物质量 W（t DM/ha）',ylabel='氮浓度（% DM）',xlim=(0,12),ylim=(0,ymax))
        ax.text(.98,.97,f'W0={cfg["curve_w0"]:.4f} t/ha\nNmin/Ncrit={cfg["min_ratio"]:.4f}\nNmax/Ncrit={cfg["max_ratio"]:.4f}',transform=ax.transAxes,ha='right',va='top',fontsize=9)
        ax.grid(alpha=.15);ax.legend(frameon=False,loc='upper center')
    title(fig,label+'：三条软参考曲线','Ncrit(%)=100a·max(W0,W)^(−b)；阴影为软参考带，不是置信区间或实际浓度硬边界')
    fig.tight_layout(rect=(0,.065,1,.925));save(fig,dest/'diagnostic_N_reference_curves.png')

def render(label,work,dest):
    if dest.exists():assert not list(dest.iterdir()),'Preserve existing diagnostic artifacts'
    dest.mkdir(parents=True,exist_ok=True)
    receipt=json.loads((work/'receipt.json').read_text(encoding='utf8'))
    assert receipt['success'] and sha(receipt['binary'])==receipt['binary_sha256']
    cfg=config(work/'NIntegration.nml')
    meta=pd.read_csv(META).rename(columns={'treatment':'trno'})
    pg=read_native(work/'PlantGro.OUT').reset_index()
    assert pg.groupby('run').trno.nunique().eq(1).all()
    daily=pd.read_csv(work/'PlantNIntegration.csv',float_precision='round_trip')
    daily['date']=pd.to_datetime(daily.yrdoy.astype(str),format='%Y%j').dt.strftime('%Y-%m-%d')
    daily=daily.merge(pg[['run','trno','date','DAP','LAID']],on=['run','date'],validate='one_to_one').merge(meta,on='trno',validate='many_to_one')
    daily['W_standing_t_ha']=(daily.W_leaf+daily.W_stem)/100
    assert len(daily)==1512
    comp=pd.read_csv(work/'comparison.csv')
    raw=pd.read_csv(RAW)
    late=raw[raw.organ.isin(['叶','茎'])&raw.date.eq('2026-07-17')].groupby(['trno','date','organ'],as_index=False).N.mean()
    late['observed']=late.N/10  # raw g N/kg DM -> % DM
    late['variable']=late.organ.map({'叶':'LEAF_N_PCT','茎':'STEM_N_PCT'})
    paired=comp[comp.variable.isin(['LEAF_N_PCT','STEM_N_PCT'])][['trno','date','variable','observed']].copy()
    assert len(paired)==72
    paired['organ']=paired.variable.map({'LEAF_N_PCT':'叶','STEM_N_PCT':'茎'})
    observations=pd.concat([paired,late[paired.columns]],ignore_index=True)
    observations['diagnostic_only']=observations.date.eq('2026-07-17')
    assert observations.diagnostic_only.sum()==24
    observations=observations.merge(pg[['trno','date','DAP']],on=['trno','date'],validate='many_to_one').merge(meta,on='trno',validate='many_to_one')
    daily.to_csv(dest/'diagnostic_daily_source.csv',index=False)
    observations.to_csv(dest/'diagnostic_N_observations.csv',index=False)
    # The current engine uses standing leaf+stem mass, not harvested/fruit mass.
    w=np.unique(np.r_[np.linspace(0,12,601),cfg['curve_w0'],.7,1.,2.,5.,10.])
    curves=[]
    for organ in ['leaf','stem']:
        critical=100*cfg[organ+'_a']*np.maximum(cfg['curve_w0'],w)**(-cfg[organ+'_b'])
        curves.append(pd.DataFrame(dict(organ=organ,W_t_ha=w,Nmin=cfg['min_ratio']*critical,Ncrit=critical,Nmax=cfg['max_ratio']*critical)))
        actual=100*cfg[organ+'_a']*daily.W_standing_t_ha.clip(lower=cfg['curve_w0'])**(-cfg[organ+'_b'])
        assert np.max(abs(actual-100*daily[organ+'_crit']))<1e-10
    curves=pd.concat(curves);curves.to_csv(dest/'diagnostic_curve_source.csv',index=False)
    for organ,cn in [('leaf','叶片'),('stem','茎')]:
        fig,axes=plt.subplots(1,3,figsize=(15,5),sharex=True,sharey=True)
        ymax=max(6 if organ=='leaf'else 3.8,float(np.ceil(100*daily['Ctotal_'+organ].max()*1.08*2)/2))
        for ax,water in zip(axes,['W1','W2','W3']):
            for n in ['N3','N2','N1','N0']:
                d=daily[daily.water_level.eq(water)&daily.nitrogen_level.eq(n)]
                assert len(d)==126
                ax.plot(d.DAP,100*d['Corg_'+organ],c=COLORS[n],lw=1.8,label=n)
                ax.plot(d.DAP,100*d['Ctotal_'+organ],c=COLORS[n],lw=1,ls=':',alpha=.85)
                o=observations[observations.water_level.eq(water)&observations.nitrogen_level.eq(n)&observations.organ.eq('叶'if organ=='leaf'else'茎')]
                q=o[~o.diagnostic_only];late=o[o.diagnostic_only]
                ax.scatter(q.DAP,q.observed,c=COLORS[n],marker=SHAPES[water],s=33,edgecolors='white',linewidths=.5,zorder=4)
                ax.scatter(late.DAP,late.observed,c=COLORS[n],marker='x',s=43,lw=1.4,zorder=4)
            ax.set(title=water,xlabel='移栽后天数（DAP）',xlim=(0,128),ylim=(0,ymax))
            ax.grid(alpha=.15)
        axes[0].set_ylabel(cn+'氮浓度（% DM）')
        axes[-1].legend(frameon=False,ncol=2,loc='upper right')
        title(fig,label+'：'+cn+'氮浓度','实线=有机N（率定口径）；点线=含无机库的总N；点=实测；×=7月17日仅诊断')
        fig.tight_layout(rect=(0,.065,1,.925));save(fig,dest/f'diagnostic_{organ}_N_dynamics.png')
    # Yield categories are explicit treatment metadata; no inferred mapping.
    final=comp[comp.family.eq('FINAL_FRESH_YIELD')].merge(meta,on='trno',validate='one_to_one')
    final['observed_t_ha']=final.observed/1000;final['simulated_t_ha']=final.simulated/1000
    final.to_csv(dest/'diagnostic_yield_source.csv',index=False)
    fig,axes=plt.subplots(1,3,figsize=(15,5),sharey=True)
    for ax,water in zip(axes,['W1','W2','W3']):
        q=final[final.water_level.eq(water)].set_index('nitrogen_level').loc[['N0','N1','N2','N3']]
        x=np.arange(4);colors=[COLORS[n]for n in q.index]
        a=ax.bar(x-.19,q.observed_t_ha,.36,facecolor='white',edgecolor=colors,lw=1.5)
        b=ax.bar(x+.19,q.simulated_t_ha,.36,color=colors,alpha=.9)
        ax.bar_label(a,fmt='%.1f',fontsize=9,padding=3);ax.bar_label(b,fmt='%.1f',fontsize=9,padding=3)
        delta=q.loc['N3','simulated_t_ha']-q.loc['N0','simulated_t_ha']
        ymax=max(90,float(np.ceil(final[['observed_t_ha','simulated_t_ha']].to_numpy().max()*1.2/10)*10))
        ax.set(title=f'{water}  模拟N3−N0={delta:+.2f} t/ha',xticks=x,xticklabels=q.index,ylim=(0,ymax),xlabel='施氮处理')
        ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
    axes[0].set_ylabel('季末累计采收鲜产（t/ha）')
    note='本轮PEST最佳参数的独立重放' if '率定后' in label else '同一组A最佳参数，没有为各版本分别率定'
    title(fig,label+'：实测与模拟鲜产','空心柱=实测；实心柱=模拟；'+note)
    fig.tight_layout(rect=(0,.065,1,.925));save(fig,dest/'diagnostic_yield_observed_simulated.png')
    curve_plot(dest,cfg,curves,label)
    fig,axes=plt.subplots(1,2,figsize=(12,5))
    for ax,organ,cn in zip(axes,['leaf','stem'],['叶片','茎']):
        c=curves[curves.organ.eq(organ)];ax.fill_between(c.W_t_ha,c.Nmin,c.Nmax,color='#DDE7DD',alpha=.7)
        ax.plot(c.W_t_ha,c.Ncrit,c='#17692C',lw=1.4,label='Ncrit')
        for n in ['N3','N0']:
            q=daily[daily.water_level.eq('W2')&daily.nitrogen_level.eq(n)]
            ax.plot(q.W_standing_t_ha,100*q['Corg_'+organ],c=COLORS[n],lw=1.8,label='W2 '+n)
            ax.scatter(q.W_standing_t_ha.iloc[-1],100*q['Corg_'+organ].iloc[-1],c=COLORS[n],s=30)
        ax.set(title=cn,xlabel='茎叶站存干物质量（t DM/ha）',ylabel='有机N浓度（% DM）',xlim=(0,12),ylim=(0,6 if organ=='leaf'else 3.8))
        ax.legend(frameon=False);ax.grid(alpha=.15)
    title(fig,label+'：W2实际状态与软参考带','线按生长日顺序连接真实状态；末点为季末；实际浓度允许高于或低于参考带')
    fig.tight_layout(rect=(0,.065,1,.925));save(fig,dest/'diagnostic_N_state_vs_biomass.png')
    sources={str(work/p):sha(work/p)for p in ['receipt.json','NIntegration.nml','PlantNIntegration.csv','PlantGro.OUT','comparison.csv']}
    sources.update({str(META):sha(META),str(RAW):sha(RAW)})
    manifest=dict(label=label,binary=receipt['binary'],binary_sha256=receipt['binary_sha256'],phi=receipt['phi'],config=cfg,
        renderer_file=str(Path(__file__).resolve()),renderer_sha256=sha(__file__),
        source_hashes=sources,curve_definition='Ncrit=a*max(W0,W)^(-b), Nmin=min_ratio*Ncrit, Nmax=max_ratio*Ncrit; W=(Wleaf+Wstem)/100',
        observations='72 fitting N means/dates from frozen comparison; 24 July17 diagnostic means from raw g/kg converted to percent; no calibration-date remapping',
        scientific_status='engineering_diagnostic_not_independent_validation',
        artifacts={p.name:sha(p)for p in dest.iterdir()if p.is_file()})
    (dest/'diagnostic_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print('PLOTTED',label,dest,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repair-curves-font',action='store_true');parser.add_argument('--label');parser.add_argument('--work',type=Path);parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    if args.repair_curves_font:
        for label in ['C3','C4']:
            dest=OUT/label;m=json.loads((dest/'diagnostic_manifest.json').read_text(encoding='utf8'))
            curve_plot(dest,m['config'],pd.read_csv(dest/'diagnostic_curve_source.csv'),label)
            m['artifacts']['diagnostic_N_reference_curves.png']=sha(dest/'diagnostic_N_reference_curves.png')
            (dest/'diagnostic_manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf8')
    elif args.work:render(args.label,args.work,args.out)
    else:
        render('C3',CN/'reports/n_v3_execution_20261103/cases/delivery_combined',OUT/'C3')
        render('C4',CN/'reports/n_v3_c4_execution_20261103/cases/delivery_full',OUT/'C4')
