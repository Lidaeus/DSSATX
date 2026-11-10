"""Numeric review of the completed all12 run, using audited existing metric tables."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from tools.reporting.write_robust_joint65_results_20261012 import table,link,FAMILIES

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'workspace/runs/eggplant_26sp_all12_robust_joint65_200x5_20261012'
OUT=RUN/'result_review_20261013'
FIG=ROOT/'figture/all12_robust_joint65_200x5_20261013_local00023_diagnostic_suite'
REPORT=ROOT/'docs/reports/全12处理稳健目标65参数联合率定_200x5结果报告_20261013.md'

def main():
    s=json.loads((OUT/'result_summary.json').read_text(encoding='utf-8'))
    family=pd.read_csv(OUT/'calibration_family_metrics_full.csv');family['label']=family.family.map(FAMILIES)
    metrics=pd.read_csv(OUT/'metrics_by_season_role_variable.csv')
    terminal=pd.read_csv(OUT/'terminal_yield_metrics.csv')
    progress=pd.read_csv(OUT/'iteration_progress.csv')
    params=pd.read_csv(OUT/'parameter_bounds_review.csv')
    responses=pd.read_csv(OUT/'signed_water_n_response.csv')
    before=pd.read_csv(OUT/'previous_vs_new_common9_metrics_full.csv');before['label']=before.family.map(FAMILIES)
    primary=responses[responses.season_id.eq('26SP')&responses.dataset_role.eq('calibration')]
    water=primary[primary.contrast_type.eq('W')]
    adjacent=primary[primary.contrast_type.eq('N')&primary.contrast.isin(['N1-N0','N2-N1','N3-N2'])]
    phi=s['selected_phi'];initial=s['initial_reference_phi'];best=s['best_initial_ensemble_phi']
    eval_total=sum(x['total'] for x in s['evaluation_coverage']);eval_missing=sum(x['unmatched'] for x in s['evaluation_coverage'])
    columns=['label','n','unit','RMSE','RRMSE','d','R2','NSE','MAE','MBE']
    headings=['目标族','n','单位','RMSE','NRMSE/%','d','R²','NSE','MAE','MBE']
    yield_cols=['season_id','dataset_role','variable','n','RMSE','RRMSE','d','R2','NSE','MAE','MBE']
    yield_heads=['季节','角色','变量','n','RMSE','NRMSE/%','d','R²','NSE','MAE','MBE']
    notes=[
      '# 全12处理稳健目标65参数联合率定200×5结果报告',
      '日期：2026-10-13（北京时间）。批次：`eggplant_26sp_all12_robust_joint65_200x5_20261012`。代表解：**第3轮local_00023**，五轮IES更新均已执行。',
      '## 1. 完成状态与复算核验',
      '**计算完成，工程验收未通过。** 本批于10月13日00:03:59启动，01:04:31完成率定、最优候选复算及2025验证后处理，约61分钟。最终186/200成员，保留率93%，比上一批75%提高18个百分点，但仍低于98%要求。',
      '成员状态表确认186个保留、14个模型失败，无高Phi筛除。工作进程日志记录16个“准确果氮采样日无成熟果池”的异常事件；包括试探/重试，不能当作16个丢失成员。上批出现的负根分配及叶蛋白顺序异常未在本批日志中复现，但这不能替代完整科研验收。',
      '失败检查为`ies_realization_alignment`、`ies_phi_finite`、`ies_final_realization_alignment`。跨迭代非有限/缺失Phi槽位占4%，超过2%容许值；存活成员自身的参数与输出有限值检查通过。项目状态保留`science_not_passed_engineering_gate`，最优参数是待科学评估的候选。',
      f'确定性复算Phi={phi:.12f}；PEST成员Phi={s["selection"]["phi"]:.12f}，差值{s["deterministic_vs_ensemble_phi_abs_difference"]:.9g}，最大编码残差差异{s["maximum_encoded_residual_difference"]:.9g}，满足既定1e-6相对复算容差。原生模型输出重新提取的689项与保存的确定性原始配对逐项一致。',
      f'相对本批起点（上一批代表解在新689目标上的Phi={initial:.6f}）下降{100*(1-phi/initial):.2f}%；相对最佳初始成员Phi={best:.6f}仅下降{100*(1-phi/best):.3f}%。第4、5轮最优值没有超过第3轮，按批准的全迭代最小完整目标规则选出local_00023。',
      table(progress,['iteration','n','min','median','mean'],['轮次（0为初始）','成员数','最小Phi','中位Phi','平均Phi'],6),
      '集合成员身份在更新中变化，平均/中位Phi下降不能全部解释为同一组成员的拟合改善。',
      '## 2. 数据范围与指标定义',
      '2026春W1/W2/W3×N0/N1/N2/N3全部12处理参加率定，689项、16目标族，预算100。2025春W1/W3为独立验证；2025秋原W1/W3验证和W2诊断划分不变。2026 N3已不再是留出集，禁止将其拟合指标报告为独立验证。2025数据未用于拟合或选择候选。',
      'NRMSE（CSV中RRMSE）=100×RMSE/|实测均值|；R²为Pearson相关系数平方；NSE=1−SSE/SST；d为Willmott一致性指数；MAE为平均绝对误差；MBE=模拟−实测的均值，正号表示高估。所有指标只使用同日的原始观测/模拟配对，不使用稳健变换残差或图上的平滑曲线。',
      '氮浓度RMSE/MAE/MBE单位为质量百分数的百分点；NRMSE是相对百分比。始花观测及模拟均为37天，RMSE=0；d、R²、NSE因零方差未定义，显示“—”。模拟值不变的秋季果氮R²也显示“—”，不当作0。',
      '有符号响应差的NRMSE按其自身实测差值均值报告；其实际Phi使用共同终末鲜产均值64956.8625 kg/ha归一化。新增N3负差值使相邻氮差的均值减小，响应差NRMSE受分母影响较大，须同时看RMSE/MAE和各有符号差，不能只拿百分数与上批比较。',
      'WB100是0–100cm区间表观水量消耗算子，与将深漏按0处理的实测表观耗水比较，并非已经分离深漏的纯ET。2025春WB100为追加的回顾性诊断，未参与率定；其第一窗含定植前4日，不等同于严格定植后生育期ET。2025秋干产仍按获准5%鲜重常量估算，不是独立于鲜产的新证据。',
      '## 3. 2026春全部16目标族拟合指标',
      table(family,columns,headings),
      '生长量时序相关性较好，但误差仍有量级差别：茎干重平均低估14.01%，叶干重均值几乎无偏（+0.07%）；叶/茎/果氮NSE均为负，尤其果氮R²=0.0135，浓度均值拟合并不证明正确复现氮动态。土壤水平均高估0.02038 cm³/cm³；区间表观耗水平均低估14.52 mm。',
      '## 4. 终末产量：率定、验证、诊断分开',
      'CHPDT的RMSE/MAE/MBE单位kg DM/ha；CHFPW对应kg fresh/ha。此表只取各处理最后真实采收日期；不与全采收过程的累计产量指标混淆。',
      table(terminal,yield_cols,yield_heads),
      '2026春鲜产实测均值64.957 t/ha，模拟68.498 t/ha，平均高估5.45%；干产平均低估5.41%。2025春鲜产NRMSE=11.08%，平均低估10.33%，NSE仍为−1.090。2025秋W1/W3验证实测均产16.390 t/ha、模拟47.614 t/ha，模拟为实测的2.905倍，NRMSE=190.61%，跨季适用性明显不通过；R²=0.624不能掩盖系统性高估。',
      '## 5. 独立验证的全部变量指标',
    ]
    for season in ['25SP','25FA']:
        notes.extend([f'### {season} W1/W3验证',table(metrics[metrics.season_id.eq(season)&metrics.dataset_role.eq('validation')],
          ['variable','n','n_total','n_unmatched','unit','RMSE','RRMSE','d','R2','NSE','MAE','MBE'],
          ['变量','有效n','原始n','缺失n','单位','RMSE','NRMSE/%','d','R²','NSE','MAE','MBE'])])
    notes.extend([
      f'本候选外部锁定评价共{eval_total}项，未匹配{eval_missing}项。2025春2025-07-04的8项成熟果N在本代表解中均有同日成熟果池，NRMSE=10.63%；这与上批候选8项缺失不同，缺失不能沿用上批结论。该指标仅8项、NSE=−5.950，不能据NRMSE确认动态机制。未补0、未移观测日期。',
      'LNAM/SNAM、分次鲜重和早期累计鲜重为补充诊断，未新增为率定证据。2025秋W2各变量以及2026全部处理明细均见季节/角色及处理级CSV。',
      '## 6. 与上批比较：只用共同9处理',
      '本批加入N3后全12处理的统计总体及归一化均值改变。下表将本代表解限制在上批共同的N0/N1/N2×W1/W2/W3（处理4–12），同样516项、同样日期；两批总Phi不直接比较。',
      table(before,['label','n_previous','n_new','RRMSE_previous','RRMSE_new','NRMSE_change_pp'],
        ['目标族','上批n','本批共同n','上批NRMSE/%','本批NRMSE/%','变化/百分点']),
      '共同9处理下，茎干重NRMSE由30.47%降至21.69%，果氮由18.95%降至14.71%；终末鲜产仅由8.58%降至8.53%。叶干重和水分近乎不变；分次干采收、茎氮及水氮差拟合变差。全12鲜产7.66%不能全部解释为参数改进，因为新加入的N3总体改变了样本。',
      '2025春终末鲜产NRMSE较上批11.20%略降到11.08%；2025秋由175.43%恶化到190.61%。因此本次主要改善工程稳定性和部分率定集生长/果氮指标，未改善跨季泛化。',
      '## 7. 水氮响应与叶氮动态',
      table(water,['stratum','contrast','observed','simulated','residual','ratio','sign_agreement'],
        ['氮层','水差','实测/kg鲜果·ha⁻¹','模拟/kg鲜果·ha⁻¹','误差','模拟/实测','符号一致']),
      table(adjacent,['stratum','contrast','observed','simulated','residual','ratio','sign_agreement'],
        ['水层','相邻氮差','实测/kg鲜果·ha⁻¹','模拟/kg鲜果·ha⁻¹','误差','模拟/实测','符号一致']),
      '水差7/8符号一致；唯一不符是N3 W3−W1（实测−232.2，模拟+1627.4），该实测差很小，−7.01比值不宜当作强反向效应。N2的W2−W1/W3−W1仅为实测幅度14.6%/22.7%，低于上批19.4%/31.3%，主要水响应幅度并未修复。',
      '相邻氮差4/9符号一致。N2−N1在W1/W2/W3分别模拟−19.6/+16.0/−1055.6 kg/ha，实测+2912.85/+7239.60/+6561.00；W2虽符号为正，幅度只有0.22%，不能叫作正确的氮响应。N3−N2三个水层符号全部错误。',
      '叶氮诊断图中，施氮处理多数仍从约4.56%升至4.9%，没有重现实测的中后期下降；N0后期模拟降至约2.7–3.5%，实测末期反弹也未复现。果氮指标改善属于残差降低，不能据此宣称吸氮/再动员结构已经正确。',
      '## 8. 实际目标贡献及参数边界',
      table(family,['label','budget','phi','phi_pct','loss'],['目标族','预算','实际Phi','Phi占比/%','损失'],6),
      f'终末干/鲜产合计实际Phi占{family[family.family.isin(["FINAL_DRY_YIELD","FINAL_FRESH_YIELD"])].phi_pct.sum():.2f}%；器官氮占{family[family.family.str.contains("N_CONCENTRATION")].phi_pct.sum():.2f}%；两个有符号响应目标占{family[family.family.str.contains("SIGNED_CONTRAST")].phi_pct.sum():.2f}%。预算不是实际误差占比，实际误差贡献也不是雅可比敏感度。',
      table(params[params.name.isin(['FL-LF','SENPOR_LATE','SLAVR','FRSTMF','FRLFF','RTNO3','RWUMX','NMOBMX','NVSMOB','PROLFF','PROSTF','KEP','SOIL_SLDR'])],
        ['name','selected','lower','upper'],['参数','代表解','下界','上界'],6),
      'FL-LF=192.323 PTD，位于获准45–220范围。FRSTMF+FRLFF=0.975864，端点根分配余量0.024136。距范围边界2%以内的活动参数3个：CMOBMX接近下界、EM-V1接近下界、FRSTMF接近上界；贴边本身不证明不可辨识。',
      '## 9. 图件与可复核数据',
      '已使用现有report_rmse_joint65渲染函数、plot_dynamics和既有指标热图代码生成74张diagnostic_ PNG。仅适配本批路径、全12处理角色和代表解标注，没有另建论文绘图体系。图件包含跨季散点/残差、日轨迹水氮分面、分次采收、累计采收事件折线及单调视觉平滑备选、指标热图、Phi与成员保留、响应结构审计。',
      '散点终末产量与全采收过程分开；累计采收平滑仅用于展示，不进入任何拟合指标。日轨迹使用实际每日模型输出。未把SD假装为SE、未虚构误差棒或后验预测区间。图册是运行诊断，不是通过科研门槛的Fig/FigS论文图。',
      link(FIG/'diagnostic_index.html','诊断图册')+'；'+link(FIG/'diagnostic_manifest.json','图件与来源哈希'),
      link(OUT/'calibration_family_metrics_full.csv','率定16族完整指标')+'；'+link(OUT/'metrics_by_season_role_variable.csv','三季各变量完整指标')+'；'+link(OUT/'metrics_by_treatment_variable.csv','各处理完整指标'),
      link(OUT/'terminal_yield_metrics.csv','终末产量指标')+'；'+link(OUT/'comparison_all_roles.csv','全部原始配对')+'；'+link(OUT/'signed_water_n_response.csv','有符号响应明细'),
      link(OUT/'previous_vs_new_common9_metrics_full.csv','上批与本批共同9处理比较')+'；'+link(OUT/'result_summary.json','核验摘要')+'；'+link(RUN/'best_calibration_parameters.csv','最优候选参数'),
      '本批可用于拟合诊断及后续方案判断；工程保留率、水氮响应和秋季验证仍不满足最终科学率定解的要求。',
    ])
    REPORT.write_text('\n\n'.join(notes)+'\n',encoding='utf-8')
    print(str(REPORT))

if __name__=='__main__':main()
