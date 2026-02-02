# Morris Top-K 选择标准化说明

## 引言（Gap发现）
针对茄子 DSSAT 模型高维参数空间，直接在 Sobol 阶段开展全参数 Sensitivity analysis 计算成本高且不易解释。为解决筛选阶段难以同时捕捉直接效应与非线性交互的问题，本研究采用 Morris 进行初筛，并在 Top-K 规则中显式引入交互补偿。

## 材料方法（试验设计 + 模型描述）
试验设计基于既有水氮优化试验与多指标观测体系，指标组包括：YIELD_HWAMS, LAI_AUC, LAI_PEAK, FRUITD_END, STEM_END_SWAD, LEAF_END_LWAD, CWAMS, HIAMS, ADAPS, PDFPS, MDAPS。模型关键过程涵盖 Thermal time 驱动物候、冠层结构与干物质分配等模块，并考虑 Genotype-by-environment interaction 的非线性响应。Morris 输出的敏感性度量采用 "{score_kind}"（μ* 等价指标），交互强度采用 σ。

Top-K 选择采用三层漏斗：
1) 指标内累计贡献阈值：按 sen_mean_abs 排序，累计贡献达到 0.88 截止；每个指标组最多保留 12 个参数。
2) 交互补偿：对 σ/μ* ≥ 1.00 的参数进行捞回，确保非线性与交互项进入 Sobol。
3) 全局约束：在覆盖各指标核心参数的前提下，并将全局保留数量限制为 15。

## 结果（标定验证 + 优化结果）
Morris 结果输出包含肘部图与累计贡献曲线，用于证明 Top-K 的边界选择具有可解释的拐点特征。交互捞回清单用于报告非线性驱动参数进入 Sobol 的依据。后续标定评价采用 RMSE、NRMSE 与 d-index，优先比较不同 Top-K 规则在目标指标上的拟合稳定性与跨环境一致性。

## 讨论（生理机制阐述）
高 σ/μ* 参数通常对应强交互或阶段性响应，如 Thermal time 与冠层结构参数对 LAI 峰值与物候期的耦合。通过交互补偿避免遗漏关键机制参数，有助于解释水氮情景下的非线性响应与 Genotype-by-environment interaction。
