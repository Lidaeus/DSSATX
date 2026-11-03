"""Read-only archived V15 S1 LAI contrast; do not transplant mechanisms."""
from pathlib import Path
import hashlib,json,re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from diagnostics import CN,COLORS,SHAPES,save,read_native

OUT=CN/'reports/V15_S1_LAI_gradient_audit_20261103'
RUN=CN/'n_buffer_v15/runs/v15_s1_interface_100x2_20261028'
C4=CN/'reports/C3_C4_diagnostics_and_calibration_20261103/C4_calibrated'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

if __name__=='__main__':
    OUT.mkdir(exist_ok=False)
    receipt=json.loads((RUN/'selected_deterministic/last_success.json').read_text(encoding='utf8'))
    archive=Path(receipt['trial'])/'26SP'
    expected='107ec95f443af66eb30d53769496836414131d6befd6ab2f34cd00ef98b137fc'
    assert receipt['success'] and receipt['binary_sha256']==sha(archive/'DSCSM048.EXE')==sha(CN/'n_buffer_v15/bin/v15_s1_interface.exe')==expected
    meta_file=CN/'n_buffer_v14/inputs/26SP/treatment_metadata.csv'
    meta=pd.read_csv(meta_file).rename(columns={'treatment':'trno'})
    tmx=(archive/'XXQL2601.TMX').read_text(encoding='ascii')
    labels={int(n):label for n,label in re.findall(r'^\s*(\d+)\s+1\s+0\s+0\s+(W\d_N\d)\s',tmx,re.M)}
    assert all(labels[r.trno]==r.treatment_label for r in meta.itertuples())
    d=read_native(archive/'PlantGro.OUT').reset_index().merge(meta,on='trno',validate='many_to_one')
    assert len(d)==1512 and d.groupby('trno').size().eq(126).all()
    c4=pd.read_csv(C4/'diagnostic_daily_source.csv',float_precision='round_trip')
    assert set(zip(d.trno,d.date))==set(zip(c4.trno,c4.date))
    d.to_csv(OUT/'diagnostic_V15_S1_daily_LAI.csv',index=False)
    obs_path=Path(json.loads((CN/'runs/n4864_C4_joint80x4_20261103_r2/completion_receipt.json').read_text())['best_trial'])/'comparison.csv'
    obs=pd.read_csv(obs_path).loc[lambda x:x.variable.eq('LAID'),['trno','date','observed']]
    obs=obs.merge(meta,on='trno',validate='many_to_one').merge(d[['trno','date','DAP','LAID']],on=['trno','date'],validate='one_to_one')
    assert len(obs)==48
    obs.to_csv(OUT/'diagnostic_LAI_common_observation_dates.csv',index=False)
    summaries=[];spreads=[];rows=[]
    for label,frame in [('V15_S1',d),('C4_best',c4)]:
        for (water,n),g in frame.groupby(['water_level','nitrogen_level']):
            g=g.sort_values('DAP')
            summaries.append(dict(version=label,water=water,nitrogen=n,peak_LAI=float(g.LAID.max()),
                final_LAI=float(g[g.date.eq('2026-07-17')].LAID.iloc[0]),LAI_integral=float(np.trapezoid(g.LAID,g.DAP))))
        for water,g in frame.groupby('water_level'):
            p=g.pivot(index='DAP',columns='nitrogen_level',values='LAID')
            span=p[['N1','N2','N3']].max(axis=1)-p[['N1','N2','N3']].min(axis=1)
            for dap,v in span.items():spreads.append(dict(version=label,water=water,DAP=dap,N123_range=v))
            rows.append(dict(version=label,water=water,N123_max_daily_range=float(span.max()),
                N1_N3_max_abs_difference=float(abs(p.N1-p.N3).max()),N2_N3_max_abs_difference=float(abs(p.N2-p.N3).max()),
                days_range_exceeds_0_01=int((span>.01000001).sum()),days_range_exceeds_0_1=int((span>.1).sum())))
    summaries=pd.DataFrame(summaries);rows=pd.DataFrame(rows);spreads=pd.DataFrame(spreads)
    summaries.to_csv(OUT/'diagnostic_LAI_treatment_summary.csv',index=False)
    rows.to_csv(OUT/'diagnostic_high_N_overlap_summary.csv',index=False)
    spreads.to_csv(OUT/'diagnostic_high_N_daily_range.csv',index=False)
    fig,ax=plt.subplots(2,3,figsize=(15,8),sharex=True,sharey='row')
    for j,water in enumerate(['W1','W2','W3']):
        for n in ['N3','N2','N1','N0']:
            g=d[d.water_level.eq(water)&d.nitrogen_level.eq(n)]
            o=obs[obs.water_level.eq(water)&obs.nitrogen_level.eq(n)]
            ax[0,j].plot(g.DAP,g.LAID,c=COLORS[n],lw=1.7,label=n)
            ax[0,j].scatter(o.DAP,o.observed,c=COLORS[n],marker=SHAPES[water],s=29,edgecolors='white',lw=.4,zorder=4)
        for version,color,name in [('V15_S1','#4477AA','V15 S1'),('C4_best','#AA7733','当前C4最佳组')]:
            g=spreads[spreads.version.eq(version)&spreads.water.eq(water)]
            ax[1,j].plot(g.DAP,g.N123_range,c=color,lw=1.7,label=name)
        ax[0,j].set(title=water,ylim=(0,4.5));ax[1,j].set(xlabel='移栽后天数（DAP）',ylim=(0,.33),xlim=(0,128))
        for i in [0,1]:ax[i,j].grid(alpha=.15)
    ax[0,0].set_ylabel('V15 S1：LAI（m²/m²）')
    ax[1,0].set_ylabel('N1/N2/N3逐日LAI最大值−最小值')
    ax[0,2].legend(frameon=False,ncol=2,loc='upper left');ax[1,2].legend(frameon=False,loc='upper left',fontsize=9)
    fig.suptitle('V15 S1冻结最佳组：N1部分分离，N2/N3仍接近',fontsize=14)
    fig.text(.5,.015,'运行诊断，仅26SP；上图线=V15原生日轨迹、点=同口径实测；下图为离散幅度，不判断排序或机制因果',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.05,1,.95));save(fig,OUT/'diagnostic_V15_S1_LAI_gradient.png')
    text='''# V15 S1氮处理间LAI梯度核查

核查对象为冻结`v15_s1_interface_100x2_20261028`最佳组独立重放的26SP原生输出，执行体SHA-256为`107ec95f443af66eb30d53769496836414131d6befd6ab2f34cd00ef98b137fc`。这是旧DSSAT 4.8.2.0底座，不是S2、低CNC或后续根系分支。本次仅读取归档，不修改或借鉴模型机制，不重新率定。

## 结论

**V15 S1的N1/N2/N3不是完全重合，但也没有充分形成三个清晰分离的梯度。** W1中N1与N2/N3分离较明显；W3有一定分离；W2三者仍非常接近。N2与N3在三种水分下均高度接近。相比当前C4最佳组，V15对施氮组三者的区分更明显，不能据此认定其全部水氮机制更正确。

## 季末LAI（2026-07-17，m²/m²）

| 水分 | N0 | N1 | N2 | N3 | N3−N1 | N3−N2 |
|---|---:|---:|---:|---:|---:|---:|
'''
    for water in ['W1','W2','W3']:
        q=summaries[summaries.version.eq('V15_S1')&summaries.water.eq(water)].set_index('nitrogen')
        text+=f'| {water} | {q.loc["N0","final_LAI"]:.3f} | {q.loc["N1","final_LAI"]:.3f} | {q.loc["N2","final_LAI"]:.3f} | {q.loc["N3","final_LAI"]:.3f} | {q.loc["N3","final_LAI"]-q.loc["N1","final_LAI"]:.3f} | {q.loc["N3","final_LAI"]-q.loc["N2","final_LAI"]:.3f} |\n'
    text+='''
W2下N2略高于N3，差0.027；这不是“零氮超过高氮”，也不能为了构造梯度强制将N3设为最大。季末N0与施氮组已有分离，但“拉开差异”不等于已经复现实测差值。共同观测日期上的逐处理对照已另存CSV。

## 全季逐日重合程度

以下范围为同一天N1/N2/N3三者的最大LAI减最小LAI，再取全季最大值；不是将不同日期的峰值相减，也不是Spread Ratio。

| 水分 | V15 S1最大离散范围 | 当前C4最佳组 | V15 N2−N3最大绝对差 |
|---|---:|---:|---:|
'''
    for water in ['W1','W2','W3']:
        q=rows[rows.water.eq(water)].set_index('version')
        text+=f'| {water} | {q.loc["V15_S1","N123_max_daily_range"]:.3f} | {q.loc["C4_best","N123_max_daily_range"]:.3f} | {q.loc["V15_S1","N2_N3_max_abs_difference"]:.3f} |\n'
    text+='''
V15中三种水分下的N1/N2/N3范围超过0.01的日数分别为84/78/78天；超过0.1的日数为53/0/50天。W2确实只有很弱的施氮组区分，不能简单回答为“V15已经把所有N梯度拉开”。

## 证据和解释边界

从真实`PlantGro.OUT`的LAID逐日读取，处理号与原TMX标签逐项核对；126天×12处理共1512条，日期范围与当前C4一致。点所用的48条26SP实测LAI来自当前冻结观测，只作同口径诊断，不重写历史V15目标。

本次比较的是两个版本各自的最佳参数组。两者底座、参数向量和历史率定目标不同；这些结果是行为对照，不能把LAI差别归因于某一个氮函数，更不能据此直接移植旧代码。

![V15 S1氮处理LAI梯度](FIGURE)
'''
    text=text.replace('FIGURE',(OUT/'diagnostic_V15_S1_LAI_gradient.png').as_posix())
    (OUT/'V15_S1_LAI梯度与重合核查_20261103.md').write_text(text,encoding='utf8')
    sources=[archive/'DSCSM048.EXE',archive/'PlantGro.OUT',archive/'XXQL2601.TMX',RUN/'selected_deterministic/last_success.json',C4/'diagnostic_daily_source.csv',obs_path,meta_file]
    evidence=dict(read_only=True,season='26SP',version='frozen_V15_S1_best',binary_sha256=expected,rows=len(d),
        source_files={str(p):sha(p)for p in sources},script_sha256=sha(__file__),
        artifacts={p.name:sha(p)for p in OUT.iterdir()if p.is_file()})
    (OUT/'diagnostic_audit_manifest.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    print(summaries[summaries.version.eq('V15_S1')].to_string(index=False));print(rows.to_string(index=False));print(OUT)
