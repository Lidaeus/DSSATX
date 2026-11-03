"""Read-only current-best physiology audit; never changes model/configuration."""
from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from diagnostics import CN,COLORS,SHAPES,save

SOURCE=CN/'reports/C3_C4_diagnostics_and_calibration_20261103'
WORK=SOURCE/'final_verification/cases/best_trace'
OUT=CN/'reports/C4_functional_N_LAI_audit_20261103'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

if __name__=='__main__':
    if (OUT/'diagnostic_audit_manifest.json').exists():raise ValueError('Preserve completed audit')
    OUT.mkdir(exist_ok=True)
    manifest=json.loads((SOURCE/'C4_calibrated/diagnostic_manifest.json').read_text(encoding='utf8'))
    cfg=manifest['config']
    assert cfg['c4_photo']==cfg['leaf_coupling']==1 and cfg['n_sen_rate']==0
    assert sha(manifest['binary'])==manifest['binary_sha256']
    daily=pd.read_csv(SOURCE/'C4_calibrated/diagnostic_daily_source.csv',float_precision='round_trip')
    trace=[]
    for c in pd.read_csv(WORK/'P0Trace.csv',chunksize=200000,usecols=['run','yrdoy','event','key','value']):
        trace.append(c[c.event.eq('leaf_capacity')|
            (c.event.eq('c4_grow_end')&c.key.isin(['W_leaf','Q_leaf']))|
            (c.event.eq('cg_begin')&c.key.eq('PG'))])
    trace=pd.concat(trace)
    stocks=trace[trace.event.eq('c4_grow_end')].pivot(index=['run','yrdoy'],columns='key',values='value').reset_index()
    stocks=stocks.merge(daily[['run','yrdoy','leaf_min','leaf_crit']],on=['run','yrdoy'],validate='one_to_one').sort_values(['run','yrdoy'])
    stocks['sf']=(stocks.W_leaf-stocks.Q_leaf)/stocks.W_leaf
    for col in ['sf','leaf_min','leaf_crit']:stocks['prev_'+col]=stocks.groupby('run')[col].shift()
    p=trace[trace.event.eq('leaf_capacity')].copy();p['call']=p.key.eq('RNITP').cumsum()
    p=p.pivot(index=['call','run','yrdoy'],columns='key',values='value').reset_index()
    p=p.merge(stocks[['run','yrdoy','prev_sf','prev_leaf_min','prev_leaf_crit']],on=['run','yrdoy'],validate='many_to_one')
    assert p.prev_sf.notna().all()  # Leaf calculations start after first end-state.
    whole_slw=p.SLW/p.prev_sf
    functional=np.minimum(np.maximum(0,(p.RNITP/100*p.prev_sf-p.prev_leaf_min)*whole_slw),
        (p.prev_leaf_crit-p.prev_leaf_min)*whole_slw)
    p['uncapped_capacity_ratio']=functional/((p.prev_leaf_crit-p.prev_leaf_min)*cfg['photo_slw_ref'])
    reconstructed=cfg['photo_floor']+(1-cfg['photo_floor'])*p.uncapped_capacity_ratio.clip(0,1)**cfg['photo_gamma']
    err=float(abs(reconstructed-p.AGEMXL).max());assert err<2*np.finfo(np.float32).eps
    photo=p.groupby(['run','yrdoy']).agg(photo_factor_mean=('AGEMXL','mean'),photo_factor_min=('AGEMXL','min'),
        uncapped_ratio_min=('uncapped_capacity_ratio','min'),uncapped_ratio_mean=('uncapped_capacity_ratio','mean'),leaf_calls=('AGEMXL','size')).reset_index()
    p.to_csv(OUT/'diagnostic_actual_leaf_capacity_calls.csv',index=False)
    daily=daily.merge(photo,on=['run','yrdoy'],how='left',validate='one_to_one')
    assert len(daily[daily.photo_factor_min.isna()])==12
    assert daily.loc[daily.photo_factor_min.isna(),'DAP'].eq(0).all() # No leaf capacity call on transplant day.
    pg=trace[trace.event.eq('cg_begin')].rename(columns={'value':'PG'})[['run','yrdoy','PG']]
    daily=daily.merge(pg,on=['run','yrdoy'],validate='one_to_one')
    nv=pd.read_csv(WORK/'PlantNV3.csv',float_precision='round_trip')
    mob=pd.read_csv(WORK/'PlantNRemob.csv',float_precision='round_trip')
    sen=pd.read_csv(WORK/'PlantNLeaf.csv',float_precision='round_trip')
    daily=daily.merge(nv[['run','yrdoy','growth_day','z_leaf_day']],on=['run','yrdoy'],validate='one_to_one')
    daily=daily.merge(mob[['run','yrdoy','function_leaf','function_stem','safe_leaf','safe_stem']],on=['run','yrdoy'],validate='one_to_one')
    daily=daily.merge(sen[['run','yrdoy','sen_N_leaf','sen_N_stem','cell_loss_leaf','n_sen_rate','old_area_lost']],on=['run','yrdoy'],validate='one_to_one')
    assert len(daily)==1512 and daily.n_sen_rate.eq(0).all()
    daily.to_csv(OUT/'diagnostic_daily_LAI_N_photo_senescence.csv',index=False)
    late=daily[daily.DAP>=35]
    assert late.photo_factor_min.eq(1).all()
    summaries=[]
    for (water,n),g in daily.groupby(['water_level','nitrogen_level']):
        g=g.sort_values('DAP');f=g[g.function_leaf>1e-12];s=g[g.DAP>=35]
        summaries.append(dict(water=water,nitrogen=n,trno=int(g.trno.iloc[0]),peak_LAI=float(g.LAID.max()),
            final_LAI=float(g.LAID.iloc[-1]),LAI_integral_day=float(np.trapezoid(g.LAID,g.DAP)),
            min_growth_factor=float(g.growth_day.min()),late_photo_factor_min=float(s.photo_factor_min.min()),
            late_uncapped_ratio_min=float(s.uncapped_ratio_min.min()),
            late_uncapped_ratio_mean=float(p[p.run.eq(g.run.iloc[0])&p.yrdoy.isin(s.yrdoy)].uncapped_capacity_ratio.mean()),
            functional_leaf_N_export_g_m2=float(g.function_leaf.sum()),functional_export_days=len(f),
            min_photo_on_functional_export_days=float(f.photo_factor_min.min())if len(f)else None,
            normal_leaf_N_recovery_g_m2=float(g.sen_N_leaf.sum()),total_PG_gCH2O_m2=float(g.PG.sum())))
    summary=pd.DataFrame(summaries);summary.to_csv(OUT/'diagnostic_treatment_summary.csv',index=False)
    comp=pd.read_csv(WORK/'comparison.csv');obs=comp[comp.variable.eq('LAID')].copy()
    meta=daily[['trno','water_level','nitrogen_level']].drop_duplicates()
    obs=obs.merge(meta,on='trno',validate='many_to_one').merge(daily[['trno','date','DAP']],on=['trno','date'],validate='one_to_one')
    obs.to_csv(OUT/'diagnostic_LAI_observed_simulated.csv',index=False)
    contrasts=[]
    for (water,date),g in obs.groupby(['water_level','date']):
        q=g.set_index('nitrogen_level')
        for lo,hi in [('N0','N1'),('N1','N2'),('N2','N3'),('N0','N3')]:
            contrasts.append(dict(water=water,date=date,contrast=hi+'-'+lo,
                observed=float(q.loc[hi,'observed']-q.loc[lo,'observed']),
                simulated=float(q.loc[hi,'simulated']-q.loc[lo,'simulated'])))
    contrasts=pd.DataFrame(contrasts);contrasts.to_csv(OUT/'diagnostic_LAI_signed_contrasts.csv',index=False)
    fig,axes=plt.subplots(2,3,figsize=(15,8),sharex=True,sharey='row')
    for col,water in enumerate(['W1','W2','W3']):
        for n in ['N3','N2','N1','N0']:
            g=daily[daily.water_level.eq(water)&daily.nitrogen_level.eq(n)]
            o=obs[obs.water_level.eq(water)&obs.nitrogen_level.eq(n)]
            axes[0,col].plot(g.DAP,g.LAID,c=COLORS[n],lw=1.8,label=n)
            axes[0,col].scatter(o.DAP,o.observed,c=COLORS[n],marker=SHAPES[water],s=30,edgecolors='white',lw=.4,zorder=3)
            axes[1,col].plot(g.DAP,g.photo_factor_mean,c=COLORS[n],lw=1.5)
        axes[0,col].set(title=water,ylim=(0,4.5));axes[1,col].set(xlabel='移栽后天数（DAP）',xlim=(0,128),ylim=(.84,1.025))
        axes[1,col].text(.98,.1,'35 DAP后各处理因子均为1',ha='right',transform=axes[1,col].transAxes,fontsize=9)
        for row in range(2):axes[row,col].grid(alpha=.15)
    axes[0,0].set_ylabel('LAI（m²/m²）');axes[1,0].set_ylabel('叶级光合氮能力因子（AGEMXL）')
    axes[0,2].legend(frameon=False,ncol=2,loc='upper left')
    fig.suptitle('最新C4最佳组：LAI已分离N0，叶级光合氮反馈仍饱和',fontsize=14)
    fig.text(.5,.015,'运行诊断：上图线=真实逐日模拟、点=实测；下图为调用记录平均能力乘子，不是日净光合或实测光合率',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.05,1,.95));save(fig,OUT/'diagnostic_LAI_and_photo_N_feedback.png')
    text='''# 当前C4功能氮、光合—衰老与LAI梯度核查

对象：2026-11-03新率定最佳组，执行体SHA-256 `b61c5d0e6489404fb67f1052d959855bcb7783ede8133a849d9a5049868c63bb`，Phi=54.56142049525302。本次只读核查，没有修改模型、配置、观测或参数。

## 结论

**没有形成当前配置下有效的“功能氮损失—光合减弱—额外缺氮衰老”闭环。** 功能氮到光合的源码路径存在，但最佳参数下后期能力因子一直饱和；额外缺氮衰老的代码存在，但配置`n_sen_rate=0`将其关闭。LAI能区分N0与施氮处理，N1/N2/N3几乎重合，尚未复现实测处理差异的幅度和时序。

## 代码路径与实际开关

- `CG_Nitrogen.f90:1099`：NI_LEAF_FACTOR使用实际有机N减去Nmin部分，结合单位叶面积干重计算功能N/面积；超过Ncrit部分不自动同比增加光合。C4同步换算RNITP和SLW的非碳水/全干重基准。
- `SPAM/ETPHR.for:548`：新因子替换原AGEMXL；随后进入LFMAX和AGEQE/QEFF，再进入叶级实际光合方程。新路径没有再乘一次原生SLWMAX，也没有新增AGEFAC×NNI重复惩罚。
- GROW实际扣除提交的NRUS，因此功能输出可通过日末有机N和叶面积状态影响下一天光合；不是将候选转运量直接再乘一个光合惩罚。
- `CG_Nitrogen.f90:161`与`SENES.for:256`：可选额外N衰老比例为`1-exp[-n_sen_rate*(1-G_day)^2]`。它读取平滑后的共享叶氮生长状态G_day，并非AGEMXL或单独累计的功能蛋白损伤；只在原生NR7前的相应衰老分支接入。
- 真实最佳NML为`leaf_coupling=1,c4_photo=1,n_sen_rate=0`。旧的`SENRTE*NRUSLF/0.16`路径在新叶耦合下明确置零，GROW也不再因总NRUS直接扣面积。蛋白回补不会直接制造面积。
- 叶龄/遮阴/水分/物候等原生衰老仍保留，N状态改变生长也可能间接改变这些过程；不能将这些现象解释成额外缺氮衰老已经启用。

## 光合反馈的实际强度

完整追踪中有41352次叶级容量调用。每个处理的光合氮能力因子都只在DAP 1—34低于0.99，其后35—125 DAP全部为1；早期各处理差异也极小。这些早期共同下降不能归因于N0处理特有的功能N损失。

实际叶片功能N输出仅在N0出现：W1/W2/W3分别为0.004125/0.000439/0.003614 g N/m²，分别发生于26/7/21个处理日。这些输出日的实际光合氮因子仍全部为1。因此，本批模拟中没有观察到功能输出时该能力乘子下降；这不代表源码对足够严重的N损失没有响应。

按每次真实PGLFEQ输入、上一日真实状态和实际最佳参数重建函数，最大误差小于一个单精度量级。35 DAP后，截断前容量比`功能N/面积 ÷ 参考功能N/面积`在所有调用中都大于1（全局最小约1.0069）。W2N0平均约1.4457、W2N3约1.3750，最后均被`min(1,ratio)`截为1。单位面积干重/叶N补偿以及当前参考阈值共同造成饱和；不能仅因器官N浓度下降就认定光合已受抑制。详细重建值在调用级CSV中保留。

表中的调用均值不是辐射或同化量加权的日光合损失；AGEMXL=1只表示没有额外的N能力惩罚，温度、水分、CO₂和冠层截光仍影响整株光合。

## LAI梯度

下表为同一季末（7月17日）的模拟值；LAI单位m²/m²。

| 水分 | 模拟N0 | 模拟N1 | 模拟N2 | 模拟N3 | 模拟N3−N0 | 实测N3−N0 |
|---|---:|---:|---:|---:|---:|---:|
'''
    for water in ['W1','W2','W3']:
        q=obs[obs.water_level.eq(water)&obs.date.eq('2026-07-17')].set_index('nitrogen_level')
        text+=f'| {water} | {q.loc["N0","simulated"]:.3f} | {q.loc["N1","simulated"]:.3f} | {q.loc["N2","simulated"]:.3f} | {q.loc["N3","simulated"]:.3f} | {q.loc["N3","simulated"]-q.loc["N0","simulated"]:.3f} | {q.loc["N3","observed"]-q.loc["N0","observed"]:.3f} |\n'
    text+='''
N1/N2/N3的全季逐日最大LAI离散范围仅W1=0.009、W2=0.003、W3=0.004，接近原生输出分辨率。N0确实分离，但晚期差值普遍偏大，且对比实测并不能要求每一天都严格按N0<N1<N2<N3排序。例如W1在6月29日实测N3−N0约−0.037，模拟却约+1.327；这应作为幅度和时序偏差，而不是新增强制排序规则。

LAI分离也不等于产量差值相同：W2N0全季LAI积分约124.45，N3约153.51（N0/N3≈81.1%）；对应真实日总光合CH2O积分比约92.0%。叶级N能力没有额外惩罚、冠层截光非线性以及其他源库过程使二者不能等同。这里没有用单项积分证明全部产量因果关系。

## 后续应处理的缺口

先在预算不变的基础上做固定参数消融，区分“功能N/面积保持”与“参考容量过易饱和”，再调整反馈尺度；不要通过额外重复乘N胁迫因子制造差异。若启用额外N衰老，须单独验证持续缺N、恢复、死叶不可无代价恢复及落叶N/DM预算，不能仅把n_sen_rate改为正值就宣布生理闭环成立。N1/N2/N3是否应当继续分离，需要与对应实测差值核对，不能预设强制单调。

![LAI与实际光合氮能力](FIGURE)
'''
    text=text.replace('FIGURE',(OUT/'diagnostic_LAI_and_photo_N_feedback.png').as_posix())
    (OUT/'功能氮反馈与LAI梯度核查_20261103.md').write_text(text,encoding='utf8')
    sources=[WORK/f for f in ['P0Trace.csv','PlantNRemob.csv','PlantNLeaf.csv','PlantNV3.csv','comparison.csv','NIntegration.nml']]
    evidence=dict(binary_sha256=manifest['binary_sha256'],configuration_sha256=sha(WORK/'NIntegration.nml'),
        source_files={str(p):sha(p)for p in sources},script_sha256=sha(__file__),source_read_only=True,
        leaf_capacity_calls=len(p),reconstruction_max_error=err,late_calls_all_factor_one=True,
        extra_N_senescence_enabled=False,artifacts={p.name:sha(p)for p in OUT.iterdir()if p.is_file()})
    (OUT/'diagnostic_audit_manifest.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    print(summary.to_string(index=False));print('capacity calls',len(p),'reconstruction error',err,'report',OUT)
