"""Verify raw-pair scores and write the custom/official all12 comparison."""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys
import numpy as np
import pandas as pd
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.reporting import report_cnc_joint69_20261015 as review
from tools.reporting.write_robust_joint65_results_20261012 import table,link,FAMILIES
from src.calibration import single_season_n as legacy

RUN,OUT,FIG,PRIOR=review.RUN,review.OUT,review.FIG,review.PRIOR


def independent_scores(frame):
    x=frame.observed.to_numpy(float);y=frame.simulated.to_numpy(float)
    mask=np.isfinite(x)&np.isfinite(y)
    if frame.variable.iloc[0] not in review.model.SIGNED:mask&=(x>=0)&(y>=0)
    x,y=x[mask],y[mask];e=y-x
    sse=float(np.sum(e*e));sst=float(np.sum((x-x.mean())**2))
    denominator=float(np.sum((abs(y-x.mean())+abs(x-x.mean()))**2))
    rmse=float(np.sqrt(np.mean(e*e)))
    return dict(RMSE=rmse,RRMSE=100*rmse/abs(x.mean()) if x.mean() else np.nan,
        MAE=float(abs(e).mean()),MBE=float(e.mean()),
        NSE=1-sse/sst if sst>1e-12 else np.nan,
        R2=float(np.corrcoef(x,y)[0,1]**2) if np.std(x)>1e-12 and np.std(y)>1e-12 else np.nan,
        d=1-sse/denominator if denominator>1e-12 else np.nan)


def verify():
    summary=json.loads((OUT/'result_summary.json').read_text(encoding='utf-8'))
    pairs=pd.read_csv(OUT/'comparison_all_roles.csv')
    targets=pd.read_csv(RUN/'selected_deterministic/last_comparison.csv')
    families=pd.read_csv(OUT/'calibration_family_metrics_full.csv')
    roles=pd.read_csv(OUT/'metrics_by_season_role_variable.csv')
    terminal=pd.read_csv(OUT/'terminal_yield_pairs.csv')
    terminal_metrics=pd.read_csv(OUT/'terminal_yield_metrics.csv')
    official_pairs=pd.read_csv(PRIOR/'comparison_all_roles.csv')
    official_targets=pd.read_csv(PRIOR.parent/'selected_deterministic/last_comparison.csv')
    official_endpoints=pd.read_csv(PRIOR/'terminal_yield_pairs.csv')
    checked=0
    for frame,metrics,keys in [(targets,families,['family','variable']),
            (pairs,roles,['season_id','dataset_role','variable']),
            (terminal,terminal_metrics,['season_id','dataset_role','variable']),
            (official_targets,pd.read_csv(PRIOR/'calibration_family_metrics_full.csv'),['family','variable']),
            (official_pairs,pd.read_csv(PRIOR/'metrics_by_season_role_variable.csv'),['season_id','dataset_role','variable']),
            (official_endpoints,pd.read_csv(PRIOR/'terminal_yield_metrics.csv'),['season_id','dataset_role','variable'])]:
        for key,q in frame.groupby(keys,sort=False):
            key=key if isinstance(key,tuple) else (key,)
            row=metrics
            for name,value in zip(keys,key):row=row[row[name].eq(value)]
            if len(row)!=1:raise ValueError('Metric group not unique')
            expected=independent_scores(q)
            for name,value in expected.items():
                if not np.isclose(value,row.iloc[0][name],rtol=1e-10,atol=1e-10,equal_nan=True):
                    raise ValueError(f'Independent metric mismatch: {key} {name}')
            checked+=1
    # Recompute saved balances from native outputs, without writing to model folders.
    balances=[]
    for season,folder in [('26SP',RUN/'selected_deterministic/_model'),('25SP',RUN/'evaluation/25SP'),('25FA',RUN/'evaluation/25FA')]:
        totals={};trt=None
        for line in (folder/'PlantNBal.OUT').read_text().splitlines():
            match=re.match(r'\s*TREATMENT\s+(\d+)',line)
            if match:trt=int(match[1]);totals[trt]=[]
            elif re.match(r'\s+TOTAL N\s+',line) and trt is not None:totals[trt].append(float(line.split()[-1]))
        soil=legacy.read_native(folder/'SoilNiBal.OUT')
        saved=pd.read_csv(folder/'nitrogen_balance_audit.csv').set_index('trno')
        if set(totals)!=set(saved.index):raise ValueError('N balance treatment mismatch')
        for t,v in totals.items():
            if len(v)!=2:raise ValueError('N total count mismatch')
            a=abs(v[0]-v[1]);b=float(abs(soil.loc[t][['DBAL','CBAL']]).to_numpy().max())
            if not np.allclose([a,b],saved.loc[t,['plant_residual_kg_ha','soil_daily_or_cumulative_max_kg_ha']],atol=1e-10):raise ValueError('N balance audit does not reproduce')
            if a>.25+1e-9 or b>.05+1e-9:raise ValueError('Selected native N balance fails')
            balances.append(dict(season_id=season,trno=t,plant=a,soil=b))
    # Verify the fixed crop-parameter comparison really preserves all old parameters.
    original=legacy.runner._read_param_dict(PRIOR.parent/'best_calibration_parameters.csv')
    baseline=legacy.runner._read_param_dict(RUN/'seed_yield_parameters.csv')
    if not all(np.isclose(v,baseline[k],rtol=1e-12,atol=1e-12) for k,v in original.items()):raise ValueError('Fixed-parameter engine baseline changed crop parameters')
    obs=pd.read_csv(review.CONFIG/'calibration_observations.csv');weights=obs.set_index('obsnme').final_weight
    reread_official=review.model.encode(review.model.extract_observations(PRIOR.parent/'selected_deterministic/_model',obs))
    if not np.allclose(reread_official.simulated,official_targets.simulated,rtol=1e-12,atol=1e-10):raise ValueError('Official native target reproduction failed')
    if not np.isclose(reread_official.phi_contribution.sum(),pd.read_csv(PRIOR/'calibration_family_metrics_full.csv').phi.sum(),rtol=1e-12):raise ValueError('Official Phi closure fails')
    a=pd.read_csv(RUN/'joint/joint.0.obs.csv',index_col=0);b=pd.read_csv(RUN/'joint/joint.5.obs.csv',index_col=0)
    members=a.index.intersection(b.index)
    cohort=[float(((q.loc[members,weights.index]*weights)**2).sum(axis=1).mean()) for q in [a,b]]
    distribution=[]
    params=pd.read_csv(OUT/'parameter_bounds_review.csv').set_index('name')
    posterior=pd.read_csv(RUN/'joint/joint.5.par.csv',index_col=0)
    for name in params[params.status=='active'].index:
        q=posterior[name.lower() if name.lower() in posterior else name]
        distribution.append(dict(name=name,selected=params.loc[name,'selected'],lower=params.loc[name,'lower'],upper=params.loc[name,'upper'],
            q05=q.quantile(.05),q50=q.median(),q95=q.quantile(.95),sd=q.std(),n=len(q)))
    pd.DataFrame(distribution).to_csv(OUT/'final_ensemble_parameter_distribution.csv',index=False)
    images=list(FIG.rglob('diagnostic_*.png'))
    for file in images:
        with Image.open(file) as im:
            im.load()
            if im.width<500 or im.height<300:raise ValueError('Invalid image geometry')
    if len(images)!=74:raise ValueError('Diagnostic figure count changed')
    for rel,h in summary['source_hashes'].items():
        if legacy.sha(ROOT/rel)!=h:raise ValueError('Source changed: '+rel)
    evidence=[Path(__file__),review.CONFIG/'engine/dscsm048_cnc.exe',PRIOR.parent/'selected_deterministic/last_comparison.csv',
        PRIOR/'comparison_all_roles.csv',PRIOR/'terminal_yield_metrics.csv',PRIOR/'metrics_by_season_role_variable.csv',
        RUN/'seed_yield_parameters.csv',RUN/'preflight/seed_yield/last_comparison.csv']
    for folder in [RUN/'selected_deterministic/_model',RUN/'evaluation/25SP',RUN/'evaluation/25FA']:
        evidence += [folder/name for name in ['PlantNBal.OUT','SoilNiBal.OUT','nitrogen_balance_audit.csv']]
    record=dict(status='verified',independent_metric_groups=checked,metric_formulas='RMSE/NRMSE/MAE/MBE/NSE/PearsonR2/Willmott d independently recomputed',
        identical_observation_scope_rows=len(pairs),target_count=len(targets),target_policy_byte_identical=True,
        baseline_existing_parameter_values_identical=True,official_689_targets_reproduced_from_native=True,png_decoded_count=len(images),selected_native_n_balance_treatments=len(balances),
        max_selected_plant_n_residual=max(r['plant'] for r in balances),max_selected_soil_n_residual=max(r['soil'] for r in balances),
        retained_cohort_n=len(members),retained_cohort_initial_mean_phi=cohort[0],retained_cohort_final_mean_phi=cohort[1],
        source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):legacy.sha(p) for p in evidence})
    legacy.write_json(OUT/'report_verification.json',record)
    return summary,record


def main():
    s,v=verify()
    family=pd.read_csv(OUT/'calibration_family_metrics_full.csv');family['label']=family.family.map(FAMILIES)
    comparison=pd.read_csv(OUT/'official_vs_custom_calibration_metrics.csv');comparison['label']=comparison.family.map(FAMILIES)
    roles=pd.read_csv(OUT/'metrics_by_season_role_variable.csv')
    terminal=pd.read_csv(OUT/'official_vs_custom_terminal_yield_metrics.csv')
    role_comparison=pd.read_csv(OUT/'official_vs_custom_metrics_by_season_role_variable.csv')
    progress=pd.read_csv(OUT/'iteration_progress.csv')
    responses=pd.read_csv(OUT/'signed_water_n_response.csv')
    old_responses=pd.read_csv(PRIOR/'signed_water_n_response.csv')
    response_compare=old_responses.merge(responses,on=['season_id','contrast_type','stratum','contrast','dataset_role'],suffixes=('_official','_custom'),validate='one_to_one')
    response_compare.to_csv(OUT/'official_vs_custom_signed_water_n_response.csv',index=False)
    selected=pd.read_csv(OUT/'parameter_bounds_review.csv')
    posterior=pd.read_csv(OUT/'final_ensemble_parameter_distribution.csv')
    old_phi=float(comparison.phi_official.sum());phi=s['selected_phi'];base=s['initial_reference_phi'];initial=s['best_initial_ensemble_phi']
    stages=pd.DataFrame([dict(stage='官方引擎/官方最优local_00023',phi=old_phi),dict(stage='自定义引擎/保留官方参数+CNC默认',phi=base),
        dict(stage='自定义引擎/最佳初始集合成员',phi=initial),dict(stage='自定义引擎/第1轮seed_canopy',phi=phi)])
    stages.to_csv(OUT/'objective_stage_comparison.csv',index=False)
    cols=['label','n','unit','RMSE','RRMSE','d','R2','NSE','MAE','MBE']
    headings=['变量/目标族','n','单位','RMSE','NRMSE/%','d','R²','NSE','MAE','MBE']
    note=[
        '# 自定义DSSAT 69参数联合率定结果及与官方版本对比\n',
        '复核日期：2026-10-15。自定义批次`eggplant_26sp_all12_cnc_joint69_200x5_20261014`，对照为官方批次`eggplant_26sp_all12_robust_joint65_200x5_20261012`。',
        '**结论：自定义版本主要改善了2026春叶氮浓度及部分生长指标，季末鲜产略改善；水分拟合基本不变，施氮处理产量饱和和跨季验证问题仍在。正式200×5计算已经完成，但工程验收未通过，不能认定为已验收的最终率定解。**',
        '\n## 1. 执行情况与可复现性\n',
        '上海时间2026-10-14 23:07:21启动，2026-10-15 00:16:21完成全流程。五次更新均已落盘；代表解为**第1轮seed_canopy**，不是第5轮最小成员。最优参数由率定集Phi选取，没有用2025验证集挑选。',
        f'保留184/200成员（92%），官方对照186/200（93%），均低于98%工程门槛。自定义批次工程失败项为成员对应率、最终成员对应率及非有限Phi槽位占比（4.1667%，门槛2%）。当前状态仍为`science_not_passed_engineering_gate`。',
        '工作进程日志有17次实测采样日无成熟果池及6次植株N收支残差超限异常，合计23次异常事件，包含试算/重试，不能对应成23个丢失成员。6次收支异常约0.26–0.29 kg N/ha，超过本适配器0.25门槛。初始200成员通过预检不保证所有后续更新向量均可行。',
        f'确定性复算Phi={phi:.12f}；PEST记录{s["selection"]["phi"]:.12f}，绝对差{s["deterministic_vs_ensemble_phi_abs_difference"]:.9g}，在1e-6相对容差内。689个率定目标均从原生输出同日重读，2025外部评价1044项全部同日匹配。',
        f'代表参数三季32处理的原生N收支重新解析通过：植株最大残差{v["max_selected_plant_n_residual"]:.2f} kg N/ha，土壤逐日/累计最大绝对残差{v["max_selected_soil_n_residual"]:.4f} kg N/ha。这仅验证代表参数，不代表整个参数空间已经消除收支风险。',
        table(progress,['iteration','n','min','median','mean'],['更新轮次（0初始）','成员数','最小Phi','中位Phi','平均Phi'],6),
        f'对最终保留的同一184成员，初始平均Phi={v["retained_cohort_initial_mean_phi"]:.6f}，最终={v["retained_cohort_final_mean_phi"]:.6f}，下降{100*(1-v["retained_cohort_final_mean_phi"]/v["retained_cohort_initial_mean_phi"]):.2f}%。集合确有更新，但第2–5轮未超过第1轮最优解。',
        '\n## 2. 比较范围与指标口径\n',
        '**同一2026春12处理、同一689项目标、同一16族预算/损失/归一尺度**；两批目标目录与政策文件SHA-256完全相同。其他评价将1944行原始观测按季节、角色、处理、变量、日期及土层一一对应，观测值、单位、水氮映射逐项一致。2025春8处理为验证，2025秋W1/W3共8处理为验证，W2共4处理仅诊断，分别报告。',
        'RMSE、NRMSE、MAE、MBE均来自原始观测模拟值；NRMSE=100×RMSE/|实测均值|；R²是Pearson相关系数平方，不能替代一致性；NSE=1−SSE/SST；d为Willmott一致性指数。残差=模拟−观测。氮浓度RMSE单位为质量百分数的百分点。始花观测恒为37天且模拟全匹配，RMSE为0，R²/d/NSE因零方差未定义。',
        'Phi使用批准的二次/pseudo-Huber目标，不能将总Phi下降百分比等同为整体NRMSE下降百分比。两个响应目标的表内NRMSE按各自差值观测均值计算，Phi却统一按终末鲜产均值归一；氮相邻差有正负抵消，NRMSE可能很大，应同时看原始kg/ha差值与实际Phi。',
        'WB100是灌水及0–100cm储水变动定义的表观耗水算子；实测把深漏/径流按0，不能将该指标称作已分离深漏的纯ET。秋季实测干产来自鲜产×5%，两项不构成独立证据。2025评价未参与本次参数更新，但沿用历史土壤设定，部分土壤肥力系数曾受历史拟合调整，因此不能宣称完全未经历史信息调整的外部场景。',
        '\n## 3. 总Phi变化及改善来源\n',
        table(stages,['stage','phi'],['计算阶段','同一689项目标Phi'],9),
        f'相对官方最优总Phi下降**{100*(1-phi/old_phi):.3f}%**。保持官方现有参数、只换自定义引擎并给CNC默认值，Phi已下降{100*(1-base/old_phi):.3f}%；再到本轮代表解下降{100*(1-phi/base):.3f}%。相对本轮最佳初始成员，IES最佳值仅再下降**{100*(1-phi/initial):.4f}%**。因此主要收益出现在引擎切换及初始冠层参考方案阶段，不能把全部改善归因于69参数IES优化。',
        '固定参数的引擎对照保持全部既有参数一致，新加CNC默认值为4.85/0.38/1.0/1.7；最佳初始seed_canopy再将FL-LF设180、SENPOR_LATE设0.19。自定义引擎还包含其他源码修改及不同引擎构建版本，以上是整套引擎方案的对照，不能单独归因于临界氮稀释机制。',
        '\n## 4. 2026春率定集：16目标族完整指标\n',
        table(family,cols,headings),
        '\n### 与官方版本逐目标比较\n',
        table(comparison,['label','RRMSE_official','RRMSE_custom','NRMSE_change_pp','d_official','d_custom','R2_official','R2_custom'],
            ['目标族','官方NRMSE/%','自定义NRMSE/%','变化/百分点','官方d','自定义d','官方R²','自定义R²']),
        '叶氮浓度NRMSE由12.678%降至9.183%，相对降低27.57%；d由0.617升至0.738，但NSE仍为−0.407，尚未达到可靠复现处理差异/时序动态的水平。日轨迹显示施氮处理已有中后期下降，但N1后期的实测低值及N0末期实测回升仍未充分复现。茎干重与LAI改善，叶干重、分次干采收、果氮略变差。叶N质量LNAM为补充诊断，NRMSE由26.481%降至22.892%；茎N质量SNAM由37.088%升至40.484%，浓度改善不代表各器官N质量全面改善。',
        '\n## 5. 季末干鲜产量：率定与验证分别比较\n',
        table(terminal,['season_id','dataset_role','variable','n_custom','RMSE_official','RMSE_custom','RRMSE_official','RRMSE_custom','R2_official','R2_custom','d_official','d_custom','NSE_custom'],
            ['季节','角色','变量','n','官方RMSE','自定义RMSE','官方NRMSE/%','自定义NRMSE/%','官方R²','自定义R²','官方d','自定义d','自定义NSE']),
        '2026终末鲜产RMSE由4972.9降至4747.1 kg/ha，NRMSE由7.656%降至7.308%；终末干产RMSE由279.0增至281.1 kg/ha，NRMSE由7.265%微升至7.321%。',
        '2025春终末鲜产NRMSE由11.084%微升至11.148%，干产由9.448%升至9.544%。自定义版鲜产均值56.580 t/ha，实测63.132 t/ha，平均低估10.38%；鲜/干产NSE均小于−1，高R²仍掩盖系统低估。',
        '2025秋W1/W3验证鲜产实测均值16.390 t/ha，官方47.614、自定义48.263 t/ha；自定义约实测2.94倍。鲜产NRMSE由190.615%升至194.580%，干产由207.204%升至211.425%。W2四处理的R²虽显著升高，鲜产d仍仅0.089且NRMSE184.409%，不能解读为秋季拟合成功。',
        '\n## 6. 各季验证/诊断变量完整指标\n',
    ]
    for season,role in [('25SP','validation'),('25FA','validation'),('25FA','diagnostic')]:
        q=roles[roles.season_id.eq(season)&roles.dataset_role.eq(role)]
        c=role_comparison[role_comparison.season_id.eq(season)&role_comparison.dataset_role.eq(role)]
        note += [f'### {season} / {role}\n',table(q,['variable','n','unit','RMSE','RRMSE','d','R2','NSE','MAE','MBE'],
            ['变量','n','单位','RMSE','NRMSE/%','d','R²','NSE','MAE','MBE']),
            table(c,['variable','RRMSE_official','RRMSE_custom','NRMSE_change_pp'],['变量','官方NRMSE/%','自定义NRMSE/%','变化/百分点'])]
    note += [
        '\n## 7. 水氮响应是否改善\n',
        table(response_compare[response_compare.season_id.eq('26SP')&((response_compare.contrast_type.eq('W'))|response_compare.contrast.isin(['N1-N0','N2-N1','N3-N2']))],
            ['contrast_type','stratum','contrast','observed_custom','simulated_official','simulated_custom','ratio_custom'],
            ['响应','层次','对比','实测差/kg鲜果·ha⁻¹','官方模拟差','自定义模拟差','自定义/实测']),
        '水响应方向仍为7/8一致，N3的W3−W1实测只有−232.2 kg/ha，接近零，不能据其符号单独判断失真。关键N2的W2−W1由官方1580.8变为1489.5 kg/ha，实测10801.8；恢复幅度由14.63%降至13.79%。N2的W3−W1恢复幅度由22.72%降至21.32%。高氮条件水响应仍弱。',
        'N2−N1三水层实测2912.85/7239.60/6561.00，自定义−9.3/72.9/−81.9 kg/ha。虽然相邻氮差总体Phi下降，N1至N2的响应仍接近零，两个水层方向错误，不能认为产量平台已经打破。全部9项相邻氮差方向仍仅4/9一致。',
        '\n## 8. 新增CNC参数及集合分布\n',
        table(posterior[posterior.name.str.startswith('CNC')],['name','selected','lower','upper','q05','q50','q95','sd','n'],
            ['参数','代表解','下界','上界','第5轮5%分位','第5轮中位','第5轮95%分位','第5轮标准差','成员数'],6),
        '代表解CNC_A=4.84990、CNC_B=0.379996、CNC_W0=1.00009、CNC_NC_INF=1.69998，几乎保持初始参考值。上表分布来自最终184成员，第1轮代表解与第5轮分布并非同一迭代；分位数仅作IES集合诊断，不能当作独立辨识证明或正式置信区间。',
        table(selected[selected.name.isin(['FL-LF','SENPOR_LATE','SLAVR','FRSTMF','RWUMX','RTNO3','NMOBMX','NVSMOB','PROLFF','PROSTF'])],
            ['name','selected','lower','upper'],['参数','代表解','下界','上界'],6),
        '代表解距边界2%以内的活动参数为CMOBMX、EM-V1、FRSTMF。整体集合改善与最佳成员改善有限同时存在；当前证据支持继续诊断结构/输入和参数可辨识性，不支持仅凭Phi改善把自定义版认定为全面优于官方版。',
        '\n## 9. 目标实际贡献与交付\n',
        table(family,['label','budget','phi','phi_pct','loss'],['目标族','名义预算','实际Phi','实际Phi占比/%','损失类型'],6),
        '已复用现有代码生成74张运行诊断PNG，含散点、残差、日轨迹、水氮分面、分次采收、累计采收两种视觉版本、热图和Phi进程。所有图均为diagnostic，不标记science_validated，也未制作论文Fig/FigS。统计不使用视觉平滑点，未把SD当作SE。74张均完成文件解码检查，并抽查叶氮日轨迹及季末产量散点。',
        link(FIG/'diagnostic_index.html','诊断图册')+'；'+link(FIG/'diagnostic_manifest.json','图件清单'),
        link(OUT/'official_vs_custom_calibration_metrics.csv','官方与自定义：16族逐项对比')+'；'+link(OUT/'official_vs_custom_terminal_yield_metrics.csv','各季终末产量对比'),
        link(OUT/'official_vs_custom_metrics_by_season_role_variable.csv','全季全角色拟合对比')+'；'+link(OUT/'official_vs_custom_raw_pairs.csv','1944行同口径配对'),
        link(OUT/'report_verification.json','独立公式/收支/来源验证')+'；'+link(OUT/'result_summary.json','批次审计摘要')+'；'+link(RUN/'best_calibration_parameters.csv','代表参数候选'),
    ]
    review.REPORT.write_text('\n\n'.join(note),encoding='utf-8')
    artifacts=[p for p in OUT.glob('*') if p.is_file() and p.name!='delivery_manifest.json']+[review.REPORT]
    legacy.write_json(OUT/'delivery_manifest.json',dict(run_id=review.ID,scientific_status=s['scientific_status'],
        artifacts={str(p.relative_to(ROOT)).replace('\\','/'):legacy.sha(p) for p in artifacts}))
    print(json.dumps(dict(report=str(review.REPORT),verification=v),ensure_ascii=True))


if __name__=='__main__':main()
