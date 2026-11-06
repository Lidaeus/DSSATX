"""Write the complete numeric result report from audited raw-pair metric tables."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
RUN=ROOT/'workspace/runs/eggplant_26sp_n012_robust_joint65_200x5_20261012'
OUT=RUN/'result_review_20261012'
FIG=ROOT/'figture/robust_joint65_200x5_20261012_local00129_diagnostic_suite'
REPORT=ROOT/'docs/reports/稳健目标65参数联合率定_200x5结果报告_20261012.md'
FAMILIES={'STEM_DRY_MASS':'茎干重','LEAF_DRY_MASS':'叶干重','CANOPY_LAI':'LAI','HEIGHT':'株高',
 'HARVEST_DRY_EVENT':'分次干采收','HARVEST_DRY_CUMULATIVE_EARLY':'前四次累计干采收',
 'FINAL_DRY_YIELD':'终末累计干产','FINAL_FRESH_YIELD':'终末累计鲜产',
 'LEAF_N_CONCENTRATION':'叶氮浓度','STEM_N_CONCENTRATION':'茎氮浓度','FRUIT_N_CONCENTRATION':'成熟果氮浓度代理',
 'SOIL_WATER':'土壤含水量','ANTHESIS':'始花日','WATER_BALANCE_100CM':'1m区间表观耗水',
 'W_SIGNED_CONTRAST':'有符号水分产量差','N_ADJACENT_SIGNED_CONTRAST':'相邻氮水平产量差'}

def link(path,label):return f'[{label}]({Path(path).as_posix()})'
def fmt(value,digits=3):
    if isinstance(value,(float,np.floating)) and not np.isfinite(value):return '—'
    if pd.isna(value):return '—'
    return f'{value:.{digits}f}' if isinstance(value,(float,np.floating)) else str(value)
def table(frame,columns,labels=None,digits=3):
    labels=labels or columns
    lines=['|'+'|'.join(labels)+'|','|'+'|'.join(['---']*len(columns))+'|']
    for row in frame.to_dict('records'):lines.append('|'+'|'.join(fmt(row.get(c),digits).replace('|','/') for c in columns)+'|')
    return '\n'.join(lines)

def main():
    s=json.loads((OUT/'result_summary.json').read_text(encoding='utf-8'))
    family=pd.read_csv(OUT/'calibration_family_metrics_full.csv');family['label']=family.family.map(FAMILIES)
    metrics=pd.read_csv(OUT/'metrics_by_season_role_variable.csv')
    terminal=pd.read_csv(OUT/'terminal_yield_metrics.csv')
    progress=pd.read_csv(OUT/'iteration_progress.csv')
    params=pd.read_csv(OUT/'parameter_bounds_review.csv')
    responses=pd.read_csv(OUT/'signed_water_n_response.csv')
    before=pd.read_csv(OUT/'previous_vs_new_metrics_full.csv');before['label']=before.family.map(FAMILIES)
    primary=responses[responses.season_id.eq('26SP')&responses.dataset_role.eq('calibration')]
    water=primary[primary.contrast_type.eq('W')]
    adjacent=primary[primary.contrast_type.eq('N')&primary.contrast.eq('N2-N1')]
    init=s['initial_reference_phi'];best=s['best_initial_ensemble_phi'];phi=s['selected_phi']
    cols=['label','n','unit','RMSE','RRMSE','d','R2','NSE','MAE','MBE']
    heads=['目标族','n','单位','RMSE','NRMSE/%','d','R²','NSE','MAE','MBE']
    note=[
     '# 稳健目标65参数联合率定200×5结果报告\n',
     '日期：2026-10-12。批次：`eggplant_26sp_n012_robust_joint65_200x5_20261012`。代表解：**第5轮local_00129**。',
     '\n## 1. 执行与验收结论\n',
     '**计算完成，工程验收未通过。** 正式批次于上海时间20:39:33启动，结果/验证后处理于21:35:12结束。五次更新均执行，最终150/200成员，保留率75%，失去50个初始成员，低于98%要求。',
     '失败检查是`ies_realization_alignment`、`ies_phi_finite`、`ies_final_realization_alignment`。跨迭代缺失Phi槽位比例10.25%，高于2%容许值。源状态保持`science_not_passed_engineering_gate`，不将最小Phi候选提升为最终科学率定成功。',
     '工作进程日志统计到57个完整异常事件：末期负根分配余量30、叶蛋白顺序4、实际N取样日无成熟果池23。这包含试探调用/重试，**不能把57事件对应成57个丢失成员**。两次启动初始化失败已单独留档，未算入以上模型异常统计。',
     f'确定性复算Phi={phi:.12f}；PEST记录Phi={s["selection"]["phi"]:.12f}，差值{s["deterministic_vs_ensemble_phi_abs_difference"]:.9g}（约{100*s["deterministic_vs_ensemble_phi_abs_difference"]/phi:.6f}%）。最大编码残差差异{s["maximum_encoded_residual_difference"]:.9g}；在既定1e-6相对容差内。原生输出逐项重读与保存的确定性原始预测一致，不能表述为PEST编码逐位精确复现。',
     f'相对本轮基准seed_yield（Phi{init:.6f}）下降{100*(1-phi/init):.2f}%；但最佳初始成员已经是local_00129（Phi{best:.6f}），五次更新相对最佳初始仅下降**{100*(1-phi/best):.3f}%**。新目标与上一批目标不同，不把新旧总Phi直接比较成拟合提高。',
     table(progress,['iteration','n','min','median','mean'],['更新轮次（0为初始）','保留成员','最小Phi','中位Phi','平均Phi'],6),
     '中位数和平均数随成员变化，不将其下降全部解释为同一批成员的改善。',
     '\n## 2. 指标定义及数据范围\n',
     '所有拟合指标使用真实测定/采收日的原始观测与模拟配对，绝不使用图上的平滑值或稳健变换残差。NRMSE（表内亦称RRMSE）=100×RMSE/|观测均值|；R²为Pearson相关系数平方；NSE=1−SSE/SST；d为Willmott一致性指数；MAE为平均绝对误差；MBE=模拟−实测的平均值，正值代表高估。',
     '氮浓度RMSE/MAE/MBE单位为质量百分数的**百分点**，NRMSE为相对百分比。始花观测均为37天且全匹配，RMSE=0；d/R²/NSE因零方差未定义，用“—”表示。',
     '2026春W1/W2/W3下N0/N1/N2参与率定，共516项、16族、预算100。2026N3为留出，2025春/秋W1/W3为验证，秋W2为诊断。叶/茎N质量以及分次鲜重为补充诊断，不进入新目标。',
     '目标使用零观测＋带符号损失编码：终末产量、水分和软差值为二次损失，其余指定过程使用pseudo-Huber。下表两个响应差的NRMSE按各自实测差值均值报告；实际Phi仍按批准的**共同终末鲜产均值**归一，这两种尺度不混用。',
     'WB100是0–100cm的观测算子（灌水−储水增量等），与将深漏按0处理的实测表观耗水比较，不能解释为已经分离深漏的纯ET。2025秋干产量按已批准5%常量估算，与鲜产不是独立验证证据。',
     '\n## 3. 2026春率定集全部16族指标\n',
     table(family,cols,heads),
     '\n## 4. 终末产量：率定、验证和留出分开报告\n',
     table(terminal,['season_id','dataset_role','variable','n','unit','RMSE','RRMSE','d','R2','NSE','MAE','MBE'],
           ['季节','角色','变量','n','单位','RMSE','NRMSE/%','d','R²','NSE','MAE','MBE']),
     '2025春验证终末鲜产NRMSE11.20%，平均低估10.49%，NSE为−1.133；较上批9.01%的终末鲜产NRMSE变差。2025秋验证平均实测16.390t/ha、模拟45.117t/ha，鲜产NRMSE175.43%，约为实测均值的2.75倍，跨季适用性问题仍严重。2026N3留出鲜产NRMSE3.97%，但只有三个处理，不能据此确认水氮过程可靠。',
     '\n## 5. 独立验证集各变量指标\n',
    ]
    for season in ['25SP','25FA']:
        note += [f'### {season} W1/W3验证\n',table(metrics[metrics.season_id.eq(season)&metrics.dataset_role.eq('validation')],
            ['variable','n','n_total','n_unmatched','unit','RMSE','RRMSE','d','R2','NSE','MAE','MBE'],
            ['变量','匹配n','原始n','缺失n','单位','RMSE','NRMSE/%','d','R²','NSE','MAE','MBE'])]
    note += [
     '**缺失不被隐藏：** 锁定外部评价共1254项，1246项匹配、8项未匹配。缺失全部是2025春8处理在2025-07-04的成熟果N浓度，模型同日无成熟果池。因此本批不能计算25SP果氮验证指标；不填0、不改用邻近日。图册果氮散点仅有具备有效配对的25FA和26SP，并在索引页说明缺失。',
     '2026N3及2025秋W2诊断变量的完整指标另见CSV；没有将诊断/留出混进主要验证统计。',
     '\n## 6. 与上一批local_00086的同口径比较\n',
     table(before,['label','RRMSE_previous','RRMSE_new','NRMSE_change_pp'],['目标族','上一批NRMSE/%','本批NRMSE/%','变化/百分点']),
     '终末鲜产、叶/茎干重、LAI、株高、茎/果氮有所改善；终末干产、收获过程和叶氮变差；土壤水与区间耗水几乎未变。施氮处理叶N曲线仍高位轻微上升，N0仍缺少实测后期回升，叶氮稀释/动态问题未解决。果氮NRMSE下降，但其R²约0.001、NSE仍负，不能只按NRMSE判定动态机制改善。',
     '\n## 7. 水氮响应诊断\n',
     table(water,['stratum','contrast','observed','simulated','ratio','sign_agreement'],['氮层','水对比','实测差/kg鲜果·ha⁻¹','模拟差/kg鲜果·ha⁻¹','模拟/实测','方向一致']),
     table(adjacent,['stratum','contrast','observed','simulated','ratio','sign_agreement'],['水层','相邻氮对比','实测差/kg鲜果·ha⁻¹','模拟差/kg鲜果·ha⁻¹','模拟/实测','方向一致']),
     '六个率定水对比方向全部正确，但N2的W2−W1仅为实测幅度19.4%，W3−W1为31.3%；相邻N2−N1三个水层均为负，且W1/W2几乎为零。其核心是施氮后响应仍趋于平台，不能宣称水氮梯度修复。六个水差整体NRMSE61.32%；六个相邻氮目标（含N1−N0、N2−N1）NRMSE90.27%。两软目标实际Phi合计只约1.63%。',
     '\n## 8. 目标函数实际贡献及代表参数\n',
     table(family,['label','budget','phi','phi_pct','loss'],['目标族','预算','实际Phi','Phi占比/%','损失类型'],6),
     '终末鲜/干产预算合计70，实际Phi贡献合计37.72%；器官氮预算4，实际贡献约8.31%。预算不是实际误差占比，实际占比也不是参数雅可比贡献。',
     table(params[params.name.isin(['FL-LF','SENPOR_LATE','SLAVR','FRSTMF','FRLFF','RTNO3','RWUMX','NMOBMX','NVSMOB','PROLFF','PROSTF','KEP','SOIL_SLDR'])],
           ['name','selected','lower','upper'],['参数','代表解','下界','上界'],6),
     'FL-LF=206.247PTD，在批准45–220范围内。FRSTMF+FRLFF=0.978298，末期根余量非负。距边界2%内的活动参数共3个：FL-SD接近上界，PROSTI和PROSHI接近下界；不能仅凭边界靠近判定可辨识性。',
     '\n## 9. 诊断图与数据交付\n',
     '已复用现有plot_dynamics、原结果报告绘图函数及既有指标热图函数，生成**74张diagnostic_ PNG**。包含跨季散点、残差、季节水氮分面日轨迹、分次采收、累计采收事件折线与单调视觉平滑备选、指标热图、Phi/成员保留和响应结构审计。',
     '连续状态使用真实日尺度模型曲线；累计产量两种视觉版本均用相同原始收获节点，平滑不进入指标。没有将SD虚构为SE或绘制未经审核的不确定性区间。图件是运行诊断，未生成Fig/FigS论文图，也未将工程失败的数据标记为science_validated。',
     link(FIG/'diagnostic_index.html','诊断图册入口')+'；'+link(FIG/'diagnostic_manifest.json','图件来源及SHA-256清单'),
     link(OUT/'calibration_family_metrics_full.csv','16族完整指标')+'；'+link(OUT/'metrics_by_season_role_variable.csv','季节/角色完整指标')+'；'+link(OUT/'metrics_by_treatment_variable.csv','各处理完整指标'),
     link(OUT/'terminal_yield_metrics.csv','终末产量指标')+'；'+link(OUT/'comparison_all_roles.csv','所有原始观测模拟配对')+'；'+link(OUT/'signed_water_n_response.csv','有符号响应明细'),
     link(OUT/'unmatched_evaluation_observations.csv','8项果氮缺失明细')+'；'+link(OUT/'result_summary.json','审计摘要及来源哈希')+'；'+link(RUN/'best_calibration_parameters.csv','代表参数（工程未通过候选）'),
     '\n当前结果可用于拟合比较和问题诊断，尚不能作为通过工程验收、跨季验证及水氮响应检验的最终率定参数。',
    ]
    REPORT.write_text('\n\n'.join(note),encoding='utf-8')
    print(str(REPORT))

if __name__=='__main__':main()
