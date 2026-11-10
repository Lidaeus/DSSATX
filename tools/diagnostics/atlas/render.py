"""Diagnostic-only static atlas. Reads hash-frozen CSV, never model temp outputs."""
from pathlib import Path
import json,os,textwrap
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import LinearSegmentedColormap
from scipy.interpolate import PchipInterpolator
from data import sha,dump,NORDER,WORDER
from catalogue import V,PLATES,CHAIN

class Atlas:
    def __init__(self,bundle,out,profile):
        self.bundle=Path(bundle);self.out=Path(out);self.out.mkdir(parents=True,exist_ok=False)
        self.state=json.loads((self.bundle/'source_manifest.json').read_text(encoding='utf8'))
        for name,digest in self.state['bundle_artifacts'].items():
            if sha(self.bundle/name)!=digest:raise ValueError('Frozen data hash mismatch: '+name)
        self.d=pd.read_csv(self.bundle/'diagnostic_daily.csv',float_precision='round_trip')
        self.obs=pd.read_csv(self.bundle/'diagnostic_observations.csv',float_precision='round_trip')
        self.summary=pd.read_csv(self.bundle/'diagnostic_separation_summary.csv',float_precision='round_trip')
        self.delta=pd.read_csv(self.bundle/'diagnostic_contrasts.csv',float_precision='round_trip')
        self.profile=json.loads(Path(profile).read_text(encoding='utf8'));self.colors=self.profile['nitrogen_colors']
        font_override = os.environ.get('DSSAT_DIAGNOSTIC_FONT')
        candidates = [font_override] if font_override else [
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/Supplemental/Songti.ttc',
            '/System/Library/Fonts/STHeiti Medium.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf',
        ]
        for f in candidates:
            if Path(f).expanduser().is_file():
                f = str(Path(f).expanduser())
                font_manager.fontManager.addfont(f);self.font=font_manager.FontProperties(fname=f).get_name();break
        else:raise RuntimeError('Set DSSAT_DIAGNOSTIC_FONT to an installed CJK font file')
        plt.rcParams.update({'font.family':self.font,'font.size':10,'axes.unicode_minus':False,
            'pdf.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,'axes.spines.right':False,
            'axes.linewidth':.65,'axes.labelsize':10,'xtick.labelsize':9,'ytick.labelsize':9,
            'legend.fontsize':10,'savefig.facecolor':'white'})
        self.pdf=PdfPages(self.out/'diagnostic_atlas.pdf');self.inventory=[]
        self.shapes={'W1':'^','W2':'s','W3':'o'}

    def legend(self,fig,observed=False,pools=False,yield_obs=False):
        if pools:return
        handles=[Line2D([0],[0],color=self.colors[n],lw=2,label=n) for n in NORDER]
        if yield_obs:
            handles+=[Line2D([0],[0],color='#333333',marker='o',mfc='white',ls='',markersize=5,label='实测（空心点）')]
        elif observed:
            handles+=[Line2D([0],[0],color='#333333',marker='o',ls='',markersize=5,label='目标观测'),
                Line2D([0],[0],color='#333333',marker='o',mfc='white',ls='',markersize=5,label='诊断观测')]
        fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.5,.99-50/(fig.get_figheight()*72)),ncol=len(handles),frameon=False)

    def save(self,fig,name,title,fields,obs=None,note='',source=None):
        fig.suptitle(title,x=.055,y=.99,ha='left',va='top',fontsize=17,fontweight='bold',color='#213444')
        fig.text(.055,.99-28/(fig.get_figheight()*72),self.state['label']+' ｜ 26SP机制运行诊断 ｜ 非论文验证图',
            fontsize=10,color='#566570',va='top')
        fig.text(.055,.014,textwrap.fill(note,width=103),fontsize=8.5,color='#566570',va='bottom')
        fig.canvas.draw()
        # Export keeps the reviewed chart; formats share the same Figure object.
        for ext in ['png','pdf','svg']:
            fig.savefig(self.out/f'diagnostic_{name}.{ext}',dpi=220,bbox_inches='tight')
        self.pdf.savefig(fig,bbox_inches='tight')
        if source is None:
            keys=['run','treatment','treatment_label','water_level','nitrogen_level','date','dap']
            source=self.d[keys+[c for c in fields if c in self.d]].copy()
        source.to_csv(self.out/f'diagnostic_{name}.source.csv',index=False)
        files=[self.out/f'diagnostic_{name}.{ext}' for ext in ['png','pdf','svg','source.csv']]
        if obs is not None and len(obs):
            op=self.out/f'diagnostic_{name}.observations.csv';obs.to_csv(op,index=False);files.append(op)
        receipt=dict(name='diagnostic_'+name,title=title,fields=fields,diagnostic_only=True,note=note,
            source_manifest_sha256=sha(self.bundle/'source_manifest.json'),
            artifacts={p.name:sha(p) for p in files},renderer='matplotlib',version=matplotlib.__version__,font=self.font)
        dump(self.out/f'diagnostic_{name}.manifest.json',receipt);self.inventory.append(receipt)
        plt.close(fig)

    def axis(self,ax,water,row,field):
        ax.grid(axis='y',color='#E5E9ED',lw=.6);ax.set_axisbelow(True)
        if row==0:ax.set_title(water,fontsize=12,fontweight='bold',pad=10)
        lo,hi=float(self.d.dap.min()),float(self.d.dap.max())
        ax.set_xlim(lo,hi+19)
        ticks=sorted(set([lo,hi]+[v for v in np.arange(np.ceil(lo/30)*30,hi,30) if hi-v>=15]))
        ax.set_xticks(ticks)
        if field in V:
            label,unit,kind,_=V[field];ax.set_ylabel(label+'\n('+unit+')',labelpad=8)
            if kind=='factor':
                ax.set_ylim(0,1.07);ax.axhline(1,color='#929BA2',lw=.7,ls=':')
            elif kind=='index':
                ax.axhline(0,color='#929BA2',lw=.7,ls=':');ax.axhline(1,color='#929BA2',lw=.7,ls=':')
            else:ax.set_ylim(bottom=0)

    def end_labels(self,ax,groups):
        values=[]
        for n,g,field in groups:
            q=g[['dap',field]].dropna()
            if len(q):values.append((float(q[field].iloc[-1]),n,float(q.dap.iloc[-1])))
        if not values:return
        lower,upper=ax.get_ylim();step=(upper-lower)*.065
        targets=[]
        for i,(value,n,x) in enumerate(sorted(values)):
            y=max(value,lower+.035*(upper-lower))
            if targets:y=max(y,targets[-1][0]+step)
            targets.append((y,value,n,x))
        overflow=max(0,targets[-1][0]-(upper-.04*(upper-lower)))
        for y,value,n,x in targets:
            ax.annotate(n,xy=(x,value),xytext=(x+5,y-overflow),color=self.colors[n],fontsize=8,
                va='center',annotation_clip=False,arrowprops=dict(arrowstyle='-',color=self.colors[n],lw=.55))

    def timeseries(self,name,title,fields,note):
        fig,axes=plt.subplots(len(fields),3,figsize=(14,2.15*len(fields)+1.7),sharex=True,sharey='row',squeeze=False)
        fig.subplots_adjust(left=.095,right=.97,top=.99-105/(fig.get_figheight()*72),
            bottom=max(.075,1/fig.get_figheight()),hspace=.28,wspace=.18)
        allobs=[]
        for row,field in enumerate(fields):
            family=V[field][3];collected=[]
            for col,water in enumerate(WORDER):
                ax=axes[row,col];groups=[];available=False
                for idx,n in enumerate(NORDER):
                    g=self.d[self.d.water_level.eq(water)&self.d.nitrogen_level.eq(n)].sort_values('dap')
                    if g.empty or field not in g or not g[field].notna().any():continue
                    available=True;groups.append((n,g,field))
                    ax.plot(g.dap,g[field],color=self.colors[n],lw=1.35,marker=self.shapes[water],
                        ms=2.4,markevery=(idx*4,25),mew=.5)
                    if field=='photo_N_mean':
                        ax.fill_between(g.dap,g.photo_N_min,g.photo_N_max,color=self.colors[n],alpha=.06,lw=0)
                    if family:
                        o=self.obs[self.obs.water_level.eq(water)&self.obs.nitrogen_level.eq(n)&self.obs.family.eq(family)]
                        for role,points in o.groupby('observation_role'):
                            val=points.observed/(1000 if field=='yield_event' else 1)
                            ax.scatter(points.dap,val,color=self.colors[n] if role=='objective' else 'white',
                                edgecolors=self.colors[n],s=29,marker=self.shapes[water],lw=.9,zorder=5)
                        if len(o):allobs.append(o)
                self.axis(ax,water,row,field)
                if not available:ax.text(.5,.5,'本运行未提供此变量',transform=ax.transAxes,ha='center',color='#7B858D')
                elif field in ['leaf_R','stem_R'] and self.state['reserve_status']=='disabled':
                    ax.text(.5,.45,'该分支未启用有机储备R',transform=ax.transAxes,ha='center',color='#7B858D')
                if col>0:ax.set_ylabel('')
                if row==len(fields)-1:ax.set_xlabel('移栽后天数 DAP')
                collected.append((ax,groups))
            # Establish row limits AFTER all water panels. Setting a lower bound
            # early disables autoscaling on shared axes and clips later panels.
            values=self.d[field].to_numpy(dtype=float)
            if field=='photo_N_mean':values=np.r_[values,self.d.photo_N_min,self.d.photo_N_max]
            if family:
                measured=self.obs.loc[self.obs.family.eq(family),'observed'].to_numpy(dtype=float)
                values=np.r_[values,measured]
            finite=values[np.isfinite(values)]
            if len(finite):
                low=min(0,float(finite.min()));high=max(float(finite.max()),1. if V[field][2] in ['factor','index'] else 0.)
                if high<=low:high=low+1
                axes[row,0].set_ylim(low-.03*(high-low) if low<0 else 0,high+.10*(high-low))
            for ax,groups in collected:self.end_labels(ax,groups)
        self.legend(fig,bool(allobs))
        self.save(fig,name,title,fields,pd.concat(allobs).drop_duplicates('obsnme') if allobs else None,note)

    def overview(self,name='00_overview',title='施氮梯度在哪一环节形成差异',reference=None):
        if reference is None:
            summaries=[self.summary,self.summary]
            columns=['high_N_max_range_pct_peak','N3_minus_N0_signed_peak_pct']
            subtitles=['N1—N3：最大同日离散范围','N3−N0：最大绝对差的符号值']
        else:
            summaries=[reference,self.summary];columns=['high_N_max_range_pct_peak']*2
            subtitles=['冻结参考：N1—N3差异','当前配置：N1—N3差异']
        fig,axes=plt.subplots(1,2,figsize=(14,10));fig.subplots_adjust(left=.21,right=.95,bottom=.09,top=.99-130/720,wspace=.65)
        cmap=LinearSegmentedColormap.from_list('blue_scale',['#F3F6F8','#A7C5DA','#244E6A'])
        source=[]
        for i,(s,col,subtitle) in enumerate(zip(summaries,columns,subtitles)):
            q=s[s.variable.isin(CHAIN)].pivot(index='variable',columns='water_level',values=col).reindex(index=CHAIN,columns=WORDER)
            arr=q.to_numpy();diverging=col=='N3_minus_N0_signed_peak_pct';ax=axes[i]
            image=ax.imshow(np.ma.masked_invalid(arr),aspect='auto',cmap='BrBG' if diverging else cmap,
                vmin=-100 if diverging else 0,vmax=100)
            ax.set_xticks(range(3),WORDER);ax.xaxis.tick_top();ax.set_yticks(range(len(CHAIN)),[V[k][0] for k in CHAIN],fontsize=9)
            ax.set_title(subtitle,pad=35,fontsize=12,fontweight='bold')
            for r in range(len(CHAIN)):
                for c in range(3):
                    value=arr[r,c]
                    text='NA' if not np.isfinite(value) else '0' if value==0 else f'{value:.2g}' if abs(value)<.01 else f'{value:.2f}' if abs(value)<1 else f'{value:.1f}'
                    ax.text(c,r,text,ha='center',va='center',fontsize=9,color='white' if np.isfinite(value) and abs(value)>65 else '#23323D')
            fig.colorbar(image,ax=ax,fraction=.035,pad=.03,label='%（相对同水水平该变量全季绝对峰值）')
            copy=q.reset_index();copy['panel']=subtitle;source.append(copy)
        note='这里是描述性差异幅度，不是统计显著性或通过门槛。NA表示全零分母、缺变量或缺处理；绝对差及单位见源CSV。'
        self.save(fig,name,title,CHAIN,note=note,source=pd.concat(source,ignore_index=True))

    def high_n_differences(self):
        fields=['Q_total','A_daily','canopy_Corg_pct','lai','PG_daily','yield_cumulative']
        fig,axes=plt.subplots(len(fields),3,figsize=(14,14.7),sharex=True,sharey='row')
        fig.subplots_adjust(left=.1,right=.97,top=.99-105/(fig.get_figheight()*72),bottom=.065,hspace=.28,wspace=.16)
        for r,key in enumerate(fields):
            for c,water in enumerate(WORDER):
                q=self.delta[self.delta.variable.eq(key)&self.delta.water_level.eq(water)].sort_values('dap')
                ax=axes[r,c]
                ax.plot(q.dap,q.N2_minus_N1,color=self.colors['N2'],lw=1.3,label='N2−N1')
                ax.plot(q.dap,q.N3_minus_N1,color=self.colors['N3'],lw=1.3,label='N3−N1')
                ax.axhline(0,color='#6F7980',lw=.8);ax.grid(axis='y',color='#E5E9ED',lw=.6)
                ax.ticklabel_format(axis='y',style='sci',scilimits=(-3,4),useOffset=False)
                if r==0:ax.set_title(water,fontweight='bold')
                if c==0:ax.set_ylabel(V[key][0]+'差值\n('+V[key][1]+')')
                if r==len(fields)-1:ax.set_xlabel('移栽后天数 DAP')
                hi=float(self.d.dap.max());lo=float(self.d.dap.min())
                ax.set_xticks(sorted(set([lo,hi]+[v for v in np.arange(lo,hi,30) if hi-v>=15])))
                peak=q[['N2_minus_N1','N3_minus_N1']].abs().max().max()
                ax.text(.02,.92,f'最大绝对差 {peak:.3g}',transform=ax.transAxes,va='top',fontsize=8.5)
        fig.legend(handles=[Line2D([0],[0],color=self.colors['N2'],label='N2−N1'),Line2D([0],[0],color=self.colors['N3'],label='N3−N1')],
            loc='upper center',bbox_to_anchor=(.5,.99-50/(fig.get_figheight()*72)),ncol=2,frameon=False)
        self.save(fig,'09_high_N_differences','N1、N2、N3重合时：直接看差值',fields,
            note='差值坐标采用独立量纲，可能显示很小数值；每行三水水平共用纵轴。零线不代表显著性检验。',
            source=self.delta[self.delta.variable.isin(fields)].copy())

    def yield_plate(self,smooth=False):
        fig,axes=plt.subplots(3,3,figsize=(14,9.5),sharey='row')
        fig.subplots_adjust(left=.09,right=.97,top=.99-105/(fig.get_figheight()*72),bottom=.09,hspace=.32,wspace=.18)
        included=[]
        for c,water in enumerate(WORDER):
            final=self.obs[self.obs.water_level.eq(water)&self.obs.family.eq('FINAL_FRESH_YIELD')]
            for idx,n in enumerate(NORDER):
                g=self.d[self.d.water_level.eq(water)&self.d.nitrogen_level.eq(n)].sort_values('dap')
                if g.empty:continue
                colour=self.colors[n];events=g[g.HFPOW>0]
                if smooth:
                    nodes=g.loc[g.CHFPW.diff().fillna(g.CHFPW)>0,['dap','yield_cumulative']]
                    nodes=pd.concat([g[['dap','yield_cumulative']].iloc[[0]],nodes]).drop_duplicates('dap')
                    if len(nodes)>1:
                        x=np.linspace(nodes.dap.iloc[0],nodes.dap.iloc[-1],400);y=PchipInterpolator(nodes.dap,nodes.yield_cumulative)(x)
                        if (np.diff(y)<-1e-10).any():raise ValueError('Nonmonotone visual cumulative curve')
                        axes[0,c].plot(x,y,color=colour,lw=1.4)
                else:axes[0,c].step(g.dap,g.yield_cumulative,where='post',color=colour,lw=1.4)
                axes[1,c].vlines(events.dap,0,events.yield_event,color=colour,lw=1,alpha=.7)
                axes[1,c].scatter(events.dap,events.yield_event,s=19,color=colour,marker=self.shapes[water],zorder=3)
                o=self.obs[self.obs.water_level.eq(water)&self.obs.nitrogen_level.eq(n)]
                cumulative=o[o.family.isin(['HARVEST_FRESH_CUMULATIVE_EARLY','FINAL_FRESH_YIELD'])]
                actual=o[o.family.eq('HARVEST_FRESH_EVENT')]
                axes[0,c].scatter(cumulative.dap,cumulative.observed/1000,s=28,facecolors='white',edgecolors=colour,marker=self.shapes[water],lw=1,zorder=4)
                axes[1,c].scatter(actual.dap,actual.observed/1000,s=28,facecolors='white',edgecolors=colour,marker=self.shapes[water],lw=1,zorder=4)
                endpoint=final[final.nitrogen_level.eq(n)]
                axes[2,c].bar(idx,g.yield_cumulative.iloc[-1],color=colour,alpha=.7,width=.58)
                if len(endpoint):axes[2,c].scatter([idx],endpoint.observed/1000,facecolors='white',edgecolors='#222222',marker=self.shapes[water],s=42,zorder=5)
                included.append(o[o.family.isin(['HARVEST_FRESH_CUMULATIVE_EARLY','FINAL_FRESH_YIELD','HARVEST_FRESH_EVENT'])])
            for r in range(3):
                axes[r,c].grid(axis='y',color='#E5E9ED',lw=.6);axes[r,c].set_axisbelow(True);axes[r,c].set_ylim(bottom=0)
                if c==0:axes[r,c].set_ylabel(['累计采收鲜果量\n(t/ha)','单次采收鲜果量\n(t/ha/event)','最终累计鲜产量\n(t/ha)'][r])
                if r<2:axes[r,c].set_xlabel('移栽后天数 DAP')
                else:axes[r,c].set_xticks(range(4),NORDER)
                if r==0:axes[r,c].set_xticks([0,30,60,90,float(self.d.dap.max())])
                if r==1:
                    event_days=sorted(self.d.loc[self.d.HFPOW>0,'dap'].unique())
                    axes[r,c].set_xticks(event_days)
            axes[0,c].set_title(water,fontweight='bold')
        cumulative_obs=self.obs[self.obs.family.isin(['HARVEST_FRESH_CUMULATIVE_EARLY','FINAL_FRESH_YIELD'])].observed/1000
        event_obs=self.obs[self.obs.family.eq('HARVEST_FRESH_EVENT')].observed/1000
        max_cumulative=max(float(self.d.yield_cumulative.max()),float(cumulative_obs.max()))
        max_event=max(float(self.d.yield_event.max()),float(event_obs.max()))
        for row,upper in enumerate([max_cumulative,max_event,max_cumulative]):axes[row,0].set_ylim(0,upper*1.12)
        self.legend(fig,yield_obs=not self.obs.empty)
        name='06b_yield_visual_smooth' if smooth else '06_yield_actual_events'
        note='线／棒为模拟。采收按实际事件日期绘制。'
        if not self.obs.empty:note='空心点为实测，线／棒为模拟。保留采样和采收日期。'
        if smooth:note+=' 本页累计曲线为单调Hermite视觉备选，不参与任何指标；实际事件阶梯见06。'
        title='产量：累计、单次及最终鲜产量' if self.obs.empty else '产量：累计、单次与最终实测对照'
        self.save(fig,name,title+('｜视觉平滑备选' if smooth else ''),
            ['yield_cumulative','yield_event'],pd.concat(included).drop_duplicates('obsnme'),note)

    def pool_composition(self):
        d=self.d.copy();d['veg_nonreserve']=d.leaf_Nnonreserve+d.stem_Nnonreserve
        d['source_other']=d.seed_remnant_N+d.nodule_N
        parts=['veg_nonreserve','R_total','root_Norg','fruit_Norg','source_other','Q_total']
        labels=['茎叶非储备有机N','茎叶储备R','根有机N','果实有机N','苗源剩余／根瘤N','无机Q']
        colors=['#355F73','#B3A466','#5F8B63','#B2727D','#929AA3','#E6C56D']
        fig,axes=plt.subplots(4,3,figsize=(14,11.7),sharex=True,sharey=True)
        fig.subplots_adjust(left=.08,right=.97,top=.99-105/(fig.get_figheight()*72),bottom=.075,hspace=.25,wspace=.15)
        for r,n in enumerate(NORDER):
            for c,water in enumerate(WORDER):
                ax=axes[r,c];g=d[d.water_level.eq(water)&d.nitrogen_level.eq(n)].sort_values('dap')
                if g.empty or g[parts].isna().any().any():ax.text(.5,.5,'缺少完整分库，未作堆叠',transform=ax.transAxes,ha='center')
                else:
                    np.testing.assert_allclose(g[parts].sum(axis=1),g.plant_N_total,atol=1e-10,rtol=0)
                    ax.stackplot(g.dap,*[g[k].to_numpy() for k in parts],colors=colors,linewidth=0)
                ax.set_title(water+' / '+n,fontsize=10);ax.set_ylim(bottom=0);ax.grid(axis='y',color='#E5E9ED',lw=.5)
                if c==0:ax.set_ylabel('库存 (kg N/ha)')
                if r==3:ax.set_xlabel('移栽后天数 DAP')
                ax.set_xticks([0,30,60,90,float(self.d.dap.max())])
        axes[0,0].set_ylim(0,max(1,float(d.plant_N_total.max()))*1.08)
        fig.legend(handles=[Line2D([0],[0],color=c,lw=6,label=l) for c,l in zip(colors,labels)],
            loc='upper center',bbox_to_anchor=(.5,.99-50/(fig.get_figheight()*72)),ncol=3,frameon=False,fontsize=9)
        self.save(fig,'07d_disjoint_pool_composition','各处理的完整氮库存组成（不重复计数）',parts,
            note='此页颜色表示氮库类型，氮处理写在分面标题中。大库会遮住Q和R的细节，分别见01和07a／07b。',source=d[['run','treatment','water_level','nitrogen_level','dap',*parts,'plant_N_total']])

    def dilution_curves(self):
        cfg=self.state['config'];fig,axes=plt.subplots(1,2,figsize=(14,5.5));fig.subplots_adjust(left=.08,right=.97,top=.99-105/(fig.get_figheight()*72),bottom=.18,wspace=.18)
        weight=(self.d.W_leaf+self.d.W_stem)/100
        x=np.geomspace(max(.001,float(weight.min())*.8),float(weight.max())*1.2,300)
        source=[]
        for ax,organ,cn in zip(axes,['leaf','stem'],['叶片','茎']):
            inf=cfg.get(organ+'_inf',0)
            critical=100*(inf+(cfg[organ+'_a']-inf)*np.maximum(cfg['curve_w0'],x)**(-cfg[organ+'_b']))
            ratio=cfg.get(organ+'_min_ratio',-1)
            if ratio<=0:ratio=cfg['min_ratio']
            minimum=critical*ratio;maximum=critical*cfg['max_ratio']
            ax.fill_between(x,minimum,maximum,color='#DBE3DD',alpha=.8)
            ax.plot(x,critical,color='#304D3B',lw=1.7,label='Ncrit')
            ax.plot(x,minimum,color='#7E8B82',lw=.8,ls=':');ax.plot(x,maximum,color='#7E8B82',lw=.8,ls=':')
            for n in NORDER:
                for water in WORDER:
                    g=self.d[self.d.water_level.eq(water)&self.d.nitrogen_level.eq(n)]
                    ax.scatter((g.W_leaf+g.W_stem)/100,g[organ+'_Corg_pct'],c=self.colors[n],marker=self.shapes[water],s=6,alpha=.3,lw=0)
            ax.set_xscale('log');ax.set_ylim(bottom=0);ax.set_title(cn,fontweight='bold');ax.set_ylabel('有机N浓度 (% DM)')
            ax.set_xlabel('站存茎叶干重 (t DM/ha)');ax.axvline(cfg['curve_w0'],color='#8D969B',lw=.7,ls='--');ax.grid(axis='y',color='#E5E9ED',lw=.6)
            source.append(pd.DataFrame(dict(row_type='soft_reference',organ=organ,W_t_ha=x,Nmin_pct=minimum,Ncrit_pct=critical,Nmax_pct=maximum)))
            points=self.d[['treatment','water_level','nitrogen_level','date','dap']].copy()
            points['row_type']='daily_simulation';points['organ']=organ
            points['W_t_ha']=(self.d.W_leaf+self.d.W_stem)/100
            points['actual_organic_N_pct']=self.d[organ+'_Corg_pct']
            source.append(points)
        self.legend(fig)
        self.save(fig,'03b_soft_reference_curves','当前Nmin、Ncrit、Nmax形状与实际轨迹',[],
            note='点为逐日模拟有机N；深线为Nc，灰带为软参考区间（不是置信区间）。虚线为W0；实际浓度不被硬投影。',source=pd.concat(source))

    def close(self):
        self.pdf.close();dump(self.out/'figure_manifest.json',dict(figures=self.inventory,
            atlas_sha256=sha(self.out/'diagnostic_atlas.pdf'),diagnostic_only=True))
