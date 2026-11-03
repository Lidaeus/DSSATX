"""Compare frozen versions with a real, deterministically replayed C4 fit."""
from pathlib import Path
import json,sys,hashlib,shutil,re
import numpy as np
import pandas as pd
from diagnostics import CN,OUT,render,save as save_figure
import matplotlib.pyplot as plt

ROOT=CN/'runs/n4864_C4_joint80x4_20261103_r2'
REPO=Path(__file__).resolve().parents[2]

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

if __name__=='__main__':
    done=json.loads((ROOT/'completion_receipt.json').read_text(encoding='utf8'))
    assert done['completed'] and done['updates']==4
    d=json.loads((ROOT/'design.json').read_text(encoding='utf8'))
    for p,h in d['frozen_hashes'].items():assert sha(p)==h,p
    assert all(sha(p)==h for p,h in d['protected'].items())
    selected=Path(done['best_trial'])
    shutil.copy2(selected/'NIntegration.nml',ROOT/'best_NIntegration.nml')
    work=OUT/'C4_calibrated'
    render('C4率定后',selected,work)
    cases=dict(C3=CN/'reports/n_v3_execution_20261103/cases/delivery_combined',
        C4=CN/'reports/n_v3_c4_execution_20261103/cases/delivery_full',C4_calibrated=selected)
    metrics=[];ys=[];reference=None
    meta=pd.read_csv(CN/'n_buffer_v14/inputs/26SP/treatment_metadata.csv').rename(columns={'treatment':'trno'})
    for label,path in cases.items():
        c=pd.read_csv(path/'comparison.csv').set_index('obsnme')
        if reference is None:reference=c
        else:
            assert c.index.equals(reference.index)
            for col in ['observed','final_weight','date','trno','variable','family','fit_scale','pest_obsval']:
                assert c[col].fillna('').equals(reference[col].fillna('')),(label,col)
        for family,g in c.groupby('family'):
            error=g.simulated-g.observed;rmse=float(np.sqrt(np.mean(error**2)))
            den=float(np.square(np.abs(g.simulated-g.observed.mean())+np.abs(g.observed-g.observed.mean())).sum())
            metrics.append(dict(version=label,family=family,n=len(g),unit=g.unit.iloc[0],RMSE=rmse,
                NRMSE_percent=100*rmse/g.observed.mean(),bias=float(error.mean()),
                d_index=1-float(np.square(error).sum())/den if den else None,phi=float(g.phi_contribution.sum())))
        y=c[c.family.eq('FINAL_FRESH_YIELD')][['trno','observed','simulated']].merge(meta,on='trno',validate='one_to_one')
        y['version']=label;y['observed_t_ha']=y.observed/1000;y['simulated_t_ha']=y.simulated/1000;ys.append(y)
    metrics=pd.DataFrame(metrics);metrics.to_csv(OUT/'diagnostic_three_version_metrics.csv',index=False)
    y=pd.concat(ys);y.to_csv(OUT/'diagnostic_three_version_yields.csv',index=False)
    diffs=[]
    for (version,water),g in y.groupby(['version','water_level']):
        q=g.set_index('nitrogen_level')
        for lo,hi in [('N0','N1'),('N1','N2'),('N2','N3'),('N0','N3')]:
            obs=float(q.loc[hi,'observed_t_ha']-q.loc[lo,'observed_t_ha']);sim=float(q.loc[hi,'simulated_t_ha']-q.loc[lo,'simulated_t_ha'])
            diffs.append(dict(version=version,water=water,contrast=hi+'-'+lo,observed=obs,simulated=sim,error=sim-obs))
    pd.DataFrame(diffs).to_csv(OUT/'diagnostic_signed_yield_responses.csv',index=False)
    water=[]
    for (version,nitrogen),g in y.groupby(['version','nitrogen_level']):
        q=g.set_index('water_level')
        for lo,hi in [('W1','W2'),('W2','W3'),('W1','W3')]:
            obs=float(q.loc[hi,'observed_t_ha']-q.loc[lo,'observed_t_ha']);sim=float(q.loc[hi,'simulated_t_ha']-q.loc[lo,'simulated_t_ha'])
            water.append(dict(version=version,nitrogen=nitrogen,contrast=hi+'-'+lo,observed=obs,simulated=sim,error=sim-obs))
    pd.DataFrame(water).to_csv(OUT/'diagnostic_signed_water_responses.csv',index=False)
    history=pd.read_csv(ROOT/'manager/smoke.phi.actual.csv')
    columns=[c for c in history if re.fullmatch(r'base|r\d+',c,re.I)]
    summaries=[]
    for row in history.itertuples(index=False):
        values=pd.to_numeric(history.loc[history.iteration.eq(row.iteration),columns].iloc[0],errors='coerce').dropna().to_numpy()
        assert len(values)>0
        summaries.append(dict(iteration=int(row.iteration),members=len(values),median=float(np.median(values)),
            q05=float(np.quantile(values,.05)),q95=float(np.quantile(values,.95)),minimum=float(values.min())))
    progress=pd.DataFrame(summaries);progress.to_csv(OUT/'diagnostic_phi_ensemble_summary.csv',index=False)
    fig,ax=plt.subplots(1,2,figsize=(11,4.6))
    ax[0].fill_between(progress.iteration,progress.q05,progress.q95,color='#4477AA',alpha=.18,label='成员5–95%范围')
    ax[0].plot(progress.iteration,progress['median'],c='#4477AA',marker='o',label='成员中位数')
    ax[0].plot(progress.iteration,progress.minimum,c='#BB7744',marker='s',label='该轮成员最低Phi')
    ax[0].set(xlabel='IES更新次数（0=初始集合）',ylabel='实际Phi',xticks=range(5));ax[0].legend(frameon=False,fontsize=9)
    ax[1].bar(progress.iteration,progress.members,color='#4477AA',width=.6)
    ax[1].axhline(80,c='#777777',ls=':',label='请求初始80成员')
    ax[1].set(xlabel='IES更新次数',ylabel='实际有效成员数',xticks=range(5),ylim=(0,88));ax[1].legend(frameon=False,fontsize=9)
    for a in ax:a.grid(axis='y',alpha=.15);a.set_axisbelow(True)
    fig.suptitle('最新C4：真实PEST-IES更新诊断',fontsize=13)
    fig.text(.5,.015,'工程率定，不是独立验证；成员范围不是预测置信区间；失败成员没有填补',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,.065,1,.94));save_figure(fig,OUT/'diagnostic_C4_IES_progress.png')
    bounds=pd.read_csv(d['bounds'],float_precision='round_trip')
    best=json.loads((ROOT/'best_parameters.exact.json').read_text(encoding='utf8'))
    bounds['best_value']=bounds.name.map(best)
    bounds['boundary_position']=(bounds.best_value-bounds.lower)/(bounds.upper-bounds.lower).replace(0,np.nan)
    bounds.to_csv(OUT/'diagnostic_calibrated_parameters.csv',index=False)
    mapping=pd.read_csv(ROOT/'reference_active_76.csv').rename(columns={'status':'reference_status'})
    mapping=mapping.merge(bounds[['name','status','lower','upper','init','best_value']],on='name',how='left',suffixes=('_reference','_C4'),validate='one_to_one')
    mapping.to_csv(OUT/'diagnostic_reference76_mapping.csv',index=False)
    errors=pd.read_csv(ROOT/'evaluation_audit.csv').loc[lambda x:~x.success]
    errors.groupby('error',dropna=False).size().rename('count').to_csv(OUT/'diagnostic_failure_reasons.csv')
    save(OUT/'diagnostic_post_calibration_receipt.json',dict(completed=True,updates=4,
        requested_members=80,final_members=done['final_members'],active=d['active'],workers=6,
        binary=d['binary'],binary_sha256=d['binary_sha256'],best_trial=str(selected),
        configuration=str(ROOT/'best_NIntegration.nml'),configuration_sha256=sha(ROOT/'best_NIntegration.nml'),
        best_phi=done['best_actual_phi'],observations_and_weights_unchanged=True,protected_unchanged=True,
        journal_budget=done['budget'],scientific_validation=False,whole_elemental_C_closed=False,
        frozen_design_sha256=sha(ROOT/'design.json'),completion_receipt_sha256=sha(ROOT/'completion_receipt.json'),
        artifacts={p.name:sha(p)for p in OUT.glob('diagnostic_*.csv')}))
    gallery=OUT/'诊断图册与新率定执行记录_20261103.md'
    text=gallery.read_text(encoding='utf8')
    marker='## 最新C4率定最终结果'
    if marker in text:raise ValueError('Preserve existing final report')
    text=text.replace('率定正在实际运行。','率定已完成4次更新。')
    final_n=done['final_members'];initial_n=done['initial_successful_members']
    total=metrics.groupby('version').phi.sum()
    text+='\n\n'+marker+'\n\n'
    text+=f'已真实完成80初始成员×4次更新、6并行。初始有效{initial_n}组，最终保留{final_n}组；请求规模不能当成最终后验样本数。74活动参数为55原生项＋19个NI项。\n\n'
    text+=f'新模型旧参数起点Phi=87.3203501；最佳实际候选Phi={done["best_actual_phi"]:.8f}，独立确定性重放Phi={done["independent_replay_phi"]:.8f}，实际参数与注入文件精确核对通过。'
    text+=f' 相对起点下降{100*(1-done["best_actual_phi"]/87.3203500866426):.2f}%。这是同一26SP数据的拟合，不是独立验证。\n\n'
    text+='| 版本 | 总Phi |\n|---|---:|\n'
    for version in ['C3','C4','C4_calibrated']:text+=f'| {version} | {total[version]:.5f} |\n'
    text+='\n逐指标RMSE（同一612目标口径；百分点与百分数相同量纲）如下。\n\n'
    text+='| 指标（RMSE单位） | C3旧参数 | C4旧参数 | 最新C4率定后 |\n|---|---:|---:|---:|\n'
    labels={'ANTHESIS':('花期（d）',1),'CANOPY_LAI':('LAI（m²/m²）',1),'FINAL_FRESH_YIELD':('最终鲜产（t/ha）',1000),
        'FRUIT_N_CONCENTRATION':('成熟果N浓度（百分点）',1),'HARVEST_FRESH_CUMULATIVE_EARLY':('早期累计鲜产（t/ha）',1000),
        'HARVEST_FRESH_EVENT':('分次鲜产（t/ha）',1000),'HEIGHT':('株高（m）',1),'LEAF_DRY_MASS':('叶干重（kg DM/ha）',1),
        'LEAF_N_CONCENTRATION':('叶N浓度（百分点）',1),'SOIL_WATER':('土壤体积含水量（cm³/cm³）',1),
        'STEM_DRY_MASS':('茎干重（kg DM/ha）',1),'STEM_N_CONCENTRATION':('茎N浓度（百分点）',1)}
    pivot=metrics.pivot(index='family',columns='version',values='RMSE')
    for family,(label,scale) in labels.items():
        v=pivot.loc[family]/scale
        text+=f'| {label} | {v.C3:.4f} | {v.C4:.4f} | {v.C4_calibrated:.4f} |\n'
    text+='\n| 水分水平 | 实测N3−N0（t/ha） | C3 | C4旧参数 | 最新C4率定后 |\n|---|---:|---:|---:|---:|\n'
    diff=pd.DataFrame(diffs).query("contrast=='N3-N0'")
    for level in ['W1','W2','W3']:
        q=diff[diff.water.eq(level)].set_index('version')
        text+=f'| {level} | {q.observed.iloc[0]:.4f} | {q.loc["C3","simulated"]:.4f} | {q.loc["C4","simulated"]:.4f} | {q.loc["C4_calibrated","simulated"]:.4f} |\n'
    text+='\n最新参数、各指标NRMSE/d-index/Phi、相邻施N及水分差值、失败原因已分别保存为`diagnostic_calibrated_parameters.csv`、`diagnostic_three_version_metrics.csv`、`diagnostic_signed_yield_responses.csv`、`diagnostic_signed_water_responses.csv`、`diagnostic_failure_reasons.csv`。处理差值用于诊断，未写入模型或设为强制排序约束。\n\n'
    for f,label in [('diagnostic_leaf_N_dynamics.png','最新C4率定后叶氮'),('diagnostic_stem_N_dynamics.png','最新C4率定后茎氮'),
                    ('diagnostic_yield_observed_simulated.png','最新C4率定后鲜产'),('diagnostic_N_reference_curves.png','最新C4率定后三曲线'),
                    ('diagnostic_N_state_vs_biomass.png','最新C4率定后实际N状态')]:text+=f'![{label}]({(work/f).as_posix()})\n\n'
    text+=f'![IES真实进度]({(OUT/"diagnostic_C4_IES_progress.png").as_posix()})\n\n'
    text+='## 使用与证据边界\n\n'
    text+=f'本次执行体完整SHA-256：`{d["binary_sha256"]}`。最佳真实原生工作目录为`{selected}`，最佳启用配置为`{ROOT/"best_NIntegration.nml"}`。执行体默认仍可回退原版模式，重用时须同时明确配置和最佳参数输入；仅切换exe不足以复现。\n\n'
    text+='所有冻结运行依赖、既有受保护执行体哈希复核通过；没有修改官方或既有自定义执行体。全程未用挪日、填值、删成熟果目标来保住成员。缺少当天成熟果、完整元素C组成账和独立水氮管理验证等局限仍需单独解决；较低Phi不等于这些问题已解决。\n'
    gallery.write_text(text,encoding='utf8')
    print(metrics[['version','family','RMSE','phi']].to_string(index=False))
    print(pd.DataFrame(diffs).query("water=='W2' and contrast=='N3-N0'").to_string(index=False))
