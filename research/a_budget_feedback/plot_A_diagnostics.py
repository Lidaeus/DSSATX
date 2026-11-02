"""Run diagnostics only. Never export or label a paper figure."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT=Path('D:/Tomato_Cal/subprojects/critical_n/reports/A_budget_feedback_20261102')
RUN=OUT.parents[1]/'runs/n4864_A_joint80x4_20261102_r1'
plt.rcParams.update({'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],'axes.unicode_minus':False,'font.size':10})
data=OUT/'analysis';dest=OUT/'figures';dest.mkdir(exist_ok=True)
d=pd.read_csv(data/'mechanism_daily.csv');ab=pd.read_csv(data/'leaf_mobilization_ablation.csv')
fig,ax=plt.subplots(1,3,figsize=(15,4.6))
for run,color in [(2,'#C0392B'),(11,'#707070')]:
 q=d[(d['case']=='old_r020')&(d.run==run)]
 ax[0].plot(q.DAP,100*q.Corg_leaf,color=color,label=q.label.iloc[0])
q=d[(d['case']=='old_r020')&(d.run==11)]
ax[0].fill_between(q.DAP,100*q.leaf_min,100*q.leaf_max,color='#2980B9',alpha=.12,label='软参考带')
ax[0].plot(q.DAP,100*q.leaf_crit,color='#2980B9',lw=1.2,label='Ncrit')
obs=pd.read_csv(data/'observed_leaf_and_reference_bands.csv')
z=obs[(obs['case']=='old_r020')&(obs.label=='W2_N0')]
lookup=q.set_index('date').DAP
ax[0].scatter([lookup.loc[s]for s in z.date],z.observed,color='#333333',marker='s',zorder=5,label='N0实测')
ax[0].set(xlabel='移栽后天数',ylabel='叶片氮浓度（% DM）',title='旧模型：参考带整体偏低')
ax[0].legend(fontsize=8,frameon=False,ncol=2)
for case,label,style in [('old_r020','旧模型','-'),('A_fixed','A修复后','--')]:
 t=pd.read_csv(data/f'{case}_trace_daily.csv')
 for run,color in [(2,'#C0392B'),(11,'#707070')]:
  q=t[t.run==run];ax[1].plot(np.arange(len(q)),q.cg_mobil__NRUSLF.cumsum(),color=color,ls=style,label=f'{label} '+('N3'if run==2 else'N0'))
ax[1].set(xlabel='模型日序',ylabel='累计叶片氮动员（g N/m²）',title='低氮更依赖内部动员')
ax[1].legend(fontsize=8,frameon=False)
for i,(prefix,title)in enumerate([('old_','旧模型'),('','A修复后')]):
 rows=[ab[ab['case']==('old_r020'if prefix else'A_fixed')].iloc[0],ab[ab['case']==prefix+'leaf_mobil_half'].iloc[0],ab[ab['case']==prefix+'leaf_mobil_off'].iloc[0]]
 ax[2].plot([1,.5,0],[r.W2_N3_minus_N0_t_ha for r in rows],marker='o',label=title)
ax[2].axhline(0,c='#777777',lw=.8)
ax[2].set(xlabel='叶片动员比例（其他机制保持）',ylabel='W2：N3−N0 鲜产（t/ha）',title='叶片供氮有因果作用，响应非单调')
ax[2].legend(fontsize=8,frameon=False)
for a in ax:a.spines[['top','right']].set_visible(False);a.grid(alpha=.15)
fig.suptitle('工程运行诊断：未经独立科学验证，不作为论文图',fontsize=10,color='#666666')
fig.tight_layout(rect=[0,0,1,.94]);fig.savefig(dest/'diagnostic_leaf_N_cause_and_ablation.png',dpi=160);plt.close(fig)

grid=pd.read_csv(data/'controlled_curve_grid.csv')
fig,axs=plt.subplots(1,2,figsize=(11,4.8))
for a,var,title in zip(axs,['phi','W2_N3_minus_N0_t_ha'],['相同参数下的总Phi','W2：N3−N0 鲜产（t/ha）']):
 g=grid.copy();g['band']=g.min_ratio.map(lambda x:f'{x:g}')+' / '+g.max_ratio.map(lambda x:f'{x:g}')
 p=g.pivot(index='band',columns='w0',values=var).sort_index()
 im=a.imshow(p.to_numpy(),aspect='auto',cmap='viridis')
 a.set_xticks(range(len(p.columns)),[f'{x:g}'for x in p.columns]);a.set_yticks(range(len(p.index)),p.index)
 a.set(xlabel='W0（t DM/ha）',ylabel='Nmin/Ncrit / Nmax/Ncrit',title=title)
 for i in range(len(p.index)):
  for j in range(len(p.columns)):a.text(j,i,f'{p.iloc[i,j]:.2f}',ha='center',va='center',color='black'if im.norm(p.iloc[i,j])>.65 else'white',fontsize=9)
 fig.colorbar(im,ax=a,shrink=.8)
fig.suptitle('固定参数的受控对照；不是各结构分别率定后的优劣比较',fontsize=10)
fig.tight_layout(rect=[0,0,1,.93]);fig.savefig(dest/'diagnostic_curve_grid.png',dpi=160);plt.close(fig)

if (RUN/'best_comparison.csv').exists():
 comp=pd.read_csv(RUN/'best_comparison.csv');bounds=pd.read_csv(json.loads((RUN/'design.json').read_text(encoding='utf8'))['bounds'])
 best=pd.read_csv(RUN/'best_parameters.csv').set_index('name').value
 fig,axs=plt.subplots(1,3,figsize=(14,4.5))
 families=['FINAL_FRESH_YIELD','LEAF_N_CONC','STEM_N_CONC']
 # Select concentration families by their direct variable definitions.
 selected=[comp[comp.family.eq('FINAL_FRESH_YIELD')],comp[comp.variable.eq('LEAF_N_PCT')],comp[comp.variable.eq('STEM_N_PCT')]]
 for a,q,title in zip(axs,selected,['最终鲜产','叶片氮浓度','茎氮浓度']):
  scale=1000 if title=='最终鲜产'else 1
  for tr,q2 in q.groupby('trno'):
   label=d[d.run==tr].label.iloc[0];n=label.split('_')[1]
   color={'N3':'#C0392B','N2':'#E67E22','N1':'#2980B9','N0':'#707070'}[n]
   marker={'W3':'o','W2':'s','W1':'^'}[label.split('_')[0]]
   a.scatter(q2.observed/scale,q2.simulated/scale,c=color,s=20,marker=marker)
  lo=min(q.observed.min(),q.simulated.min())/scale;hi=max(q.observed.max(),q.simulated.max())/scale
  unit='t/ha'if title=='最终鲜产'else'% DM'
  a.plot([lo,hi],[lo,hi],color='#777777',lw=1);a.set(xlabel=f'实测（{unit}）',ylabel=f'模拟（{unit}）',title=title);a.grid(alpha=.15)
 fig.suptitle('最佳实际候选的确定性重跑诊断；率定拟合不等同独立验证',fontsize=10)
 fig.tight_layout(rect=[0,0,1,.93]);fig.savefig(dest/'diagnostic_best_fit.png',dpi=160);plt.close(fig)
print('diagnostic PNGs saved:',dest)
