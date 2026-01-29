# Sobol 敏感性结果解读（Top-K, N=200）

本解读基于 Sobol（Saltelli）阶段结果，强调参数的“总效应 STi”，用于确认关键参数并细化分批率定顺序。

## 数据来源

- 总体 STi 排名：sobol_overall_parameter_ranking_STi.csv
- 指标-参数 Top20（STi）：sobol_top20_all_indicators_STi.csv
- 质量报告：sobol_quality_report.csv

对应文件路径：

- [sobol_overall_parameter_ranking_STi.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/sobol_results_compact/sobol_overall_parameter_ranking_STi.csv)
- [sobol_top20_all_indicators_STi.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/sobol_results_compact/sobol_top20_all_indicators_STi.csv)
- [sobol_quality_report.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/sobol_results_compact/sobol_quality_report.csv)

## 质量检查

Sobol 结果无 NaN，说明本次采样与前向模型响应稳定：

- Si/STi 均 0% NaN

见 [sobol_quality_report.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/sobol_results_compact/sobol_quality_report.csv)。

## 总体结论（STi 排名）

Top-K 中最核心的参数如下（按 STi 由高到低）：

1. EM-V1
2. TRIFL
3. XMAGE
4. FL-LF
5. TB2
6. TO12
7. FL-SD
8. TO11
9. TB1
10. EM-FL

完整排序见 [sobol_overall_parameter_ranking_STi.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/sobol_results_compact/sobol_overall_parameter_ranking_STi.csv)。

## 指标主导参数（Sobol 视角）

从指标层面看，Sobol 强调“时间与分配”的结构性影响：

- ADAPS：EM-V1、TB2、EM-FL、TO12
- LAI_AUC / LAI_DAP：EM-V1、TRIFL、FL-LF、TB1/TO11
- FRUITD_AUC / FRUITD_END：EM-V1、XMAGE、TB2、XFRT、TRIFL
- HIAMS / HI_END_HIAD：XMAGE、FL-SD、XFRT、TM2

见 [sobol_top20_all_indicators_STi.csv](file:///C:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Output/sobol_results_compact/sobol_top20_all_indicators_STi.csv)。

## 分批率定建议（Sobol 视角）

Sobol 结果把“时间尺度参数”推到更高优先级，建议如下分批：

### 第 1 批：物候核心时间尺度

目标指标：ADAPS、LAI 时间结构、FRUITD 时间结构。

- EM-V1
- EM-FL
- TB1、TB2、TO11、TO12、TO22、TM2

### 第 2 批：冠层结构与叶面积形成

目标指标：LAI_AUC、LAI_DAP、LAI_PEAK、LAI_END。

- TRIFL
- FL-LF
- RWDTH、RHGHT
- KCAN

### 第 3 批：果实与收获过程

目标指标：FRUITD_AUC、FRUITD_END、YIELD_HWAMS、HIAMS。

- XMAGE
- FL-SD
- XFRT
- XFINT

### 第 4 批：根系与水分相关参数

Sobol 中 FRLFF、FRSTMF、PORPT 仍有贡献，但相对靠后。建议作为水分情景或后续微调批次：

- FRLFF
- FRSTMF
- PORPT

## 与 Morris 的对比要点

- Morris 强调“筛选”：XFRT、TRIFL、PM06、LFMAX 等呈现高敏感。
- Sobol 强调“主导机制”：EM-V1、TRIFL、XMAGE、FL-LF、TB/TO/TM 系列成为主导。
- 结论指向一致的“首批校准核心”：物候时间参数 + 冠层结构参数。

## 直接可执行的率定顺序

建议的优先级可合并为三步：

1. 物候时间（EM-V1、EM-FL、TB/TO/TM）
2. 冠层结构（TRIFL、FL-LF、RWDTH、RHGHT、KCAN）
3. 果实分配与收获（XMAGE、FL-SD、XFRT、XFINT）

该顺序覆盖 Sobol 与 Morris 的共同高敏感区，并且与指标层面的权重一致。
