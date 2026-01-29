# Morris 敏感性结果解读（r=100）

本解读基于最新的 Morris 后处理结果，主要用于为“参数分批率定”提供优先级排序与指标对应关系。

## 数据来源

- 总体排序：morris_overall_parameter_ranking.csv
- 指标-参数 Top20：morris_top20_all_indicators.csv
- 参数到指标汇总：morris_param_to_indicator_scores.csv
- Top-K 参数清单：topk_params.csv

对应文件路径：

- [morris_overall_parameter_ranking.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/morris_results_compact/morris_overall_parameter_ranking.csv)
- [morris_top20_all_indicators.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/morris_results_compact/morris_top20_all_indicators.csv)
- [morris_param_to_indicator_scores.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/morris_results_compact/morris_param_to_indicator_scores.csv)
- [topk_params.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/morris_results_compact/topk_params.csv)

## 总体结论（全局排序）

综合敏感度排名显示，影响最强的参数集中在“冠层扩展与物候/分配”模块：

- 超高敏感：XFRT、TRIFL、PM06、LFMAX
- 高敏感：FRLFF、FRSTMF、RWDTH、XFINT、TB2
- 中高敏感：TO12、TO22、TO11、TB1、PORPT、PM09、FL-SH

见 [morris_overall_parameter_ranking.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/morris_results_compact/morris_overall_parameter_ranking.csv)。

## 指标主导参数（从指标看）

基于指标 Top20 汇总，主要结论如下：

- LAI（AUC / DAP / END）：TRIFL 主导，其次 XFRT、FRLFF、LFMAX、PM06、RWDTH
- 果实干重曲线（FRUITD AUC / DAP / END）：XFRT、TRIFL、PM06、LFMAX、XFINT、TB2/TO12/TO22
- 生物量/冠层干重（AGB_END_CWAD / CWAMS）：TRIFL、XFRT、FRLFF、FRSTMF、LFMAX、PM06
- 物候时间（ADAPS）：TB2、EM-FL、TO12、TO22、EM-V1、TM2

见 [morris_top20_all_indicators.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/morris_results_compact/morris_top20_all_indicators.csv)。

## 分批率定建议（Morris 视角）

以下分批顺序用于“先稳结构，再调产量，再调细节”的策略，且与敏感度排序一致：

### 第 1 批：冠层扩展与形态结构

目标指标：LAI_AUC、LAI_DAP、LAI_END、RHGHT/RWDTH 对应的结构性表现。

- TRIFL
- LFMAX
- RWDTH
- RHGHT
- FRLFF
- FRSTMF

### 第 2 批：物候时间与温度阈值

目标指标：ADAPS、LAI_TPEAK、果实形成关键时间点。

- EM-V1
- EM-FL
- TB1、TB2、TO11、TO12、TO22、TM2
- PM06、PM09

### 第 3 批：分配与果实形成

目标指标：FRUITD_AUC、FRUITD_END、YIELD_HWAMS、HIAMS。

- XFRT
- XFINT
- FL-LF、FL-SH、FL-SD
- XMAGE
- SFDUR

### 第 4 批：水分与土壤约束（当前试验情景）

土壤参数在当前情景中总体敏感性较弱，但在水分胁迫或不同土层设置下可能上升。建议作为后置批次：

- PORPT
- SOIL_SLLL_06、SOIL_SLLL_07
- SOIL_SSAT_02
- SOIL_SBDM_05、SOIL_SBDM_06

## 核心提醒

- Morris 反映的是“筛选”级别，重点用于判断“值得继续深入”的参数集合。
- 当前 Top-K（25 个）参数为 Sobol 进一步精细分析的输入，见 [topk_params.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/morris_results_compact/topk_params.csv)。
- 若后续校准侧重产量与成熟期分布，建议优先在第 1～3 批内做迭代，而将土壤参数作为情景扩展验证环节。
