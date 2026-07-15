# 04_敏感性分析结果解读_Morris

> **历史结果，禁止作为当前科研结论。** 对应运行存在敏感性全零退化；参数排名和解释需在 P0/P1 后重新生成。状态更新：2026-07-15。

## 1. 引言（Gap 发现）

茄子水氮优化试验已完成，但参数维度高、指标多时，直接进行全参数标定容易出现等效多解与计算成本过高的问题。当前急需通过 Screening 型 Sensitivity analysis 先建立“参数—指标”主控结构，为后续 PEST++ 率定制定合理的 Top-K 集合与分批策略，并明确哪些生理过程（如 Thermal time 与冠层形成）是限制拟合精度的关键。

## 2. 材料与方法（试验设计 + 模型描述）

- 模型与指标：基于 DSSAT 茄子模型，使用 LAI、果实干重曲线、产量（HWAMS）、干物质分配（CWAMS/AGB_END_CWAD）、HI 等指标，时间序列按 indicator group 聚合。
- 敏感性方法：采用 PEST++ Morris（全局一因子）筛选，敏感性口径使用 sen_mean_abs（等价于 * 的重要性排序）。
- 率定评价口径：后续批次标定评价采用 RMSE、NRMSE、d-index 指标作为一致的拟合准则。
- 机制约束：重点关注 Thermal time、光周期参数、冠层几何与同化分配参数，强调 Genotype-by-environment interaction 在不同处理与 TN 之间的影响结构差异。

## 3. 结果（标定验证 + 优化结果）

### 3.1 全局敏感性排序（Top 12）

| 排名 | 参数 | sen_mean_abs |
| --- | --- | --- |
| 1 | XFRT | 2466.36 |
| 2 | TRIFL | 1867.70 |
| 3 | PM06 | 1150.92 |
| 4 | LFMAX | 915.62 |
| 5 | FRLFF | 357.23 |
| 6 | FRSTMF | 264.95 |
| 7 | RWDTH | 225.12 |
| 8 | XFINT | 152.74 |
| 9 | TB2 | 134.18 |
| 10 | TO22 | 97.02 |
| 11 | TO12 | 95.86 |
| 12 | PORPT | 95.45 |

结论：果实分配（XFRT）与出叶速率（TRIFL）形成双核心，随后是光周期/发育（PM06）与冠层结构（LFMAX/RWDTH），并伴随 Thermal time 参数（TB2/TO22/TO12）形成显著贡献。

### 3.2 “参数 → 指标”主控结构

- 果实干重曲线：FRUITD_AUC 由 XFRT、TRIFL、PM06 主导；FRUITD_END 由 XFRT、TRIFL、PM06 共同控制。
- 冠层与生物量：LAI_AUC/LAI_PEAK 以 TRIFL、FRLFF、XFRT 为主，说明叶片形成速率与根系分配共同调控冠层扩张。
- 产量终值：YIELD_HWAMS 以 XFRT、TRIFL、LFMAX 为核心控制因子，表现出“分配 + 叶面积上限”的双重约束。

### 3.3 标定与优化建议（面向分批率定）

- 建议 Top-K 率定集合：XFRT、TRIFL、PM06、LFMAX、FRLFF、FRSTMF、RWDTH、XFINT、TB2、TO22、TO12、PORPT（必要时加入 TB1、TO11 作为 Thermal time 辅助调节）。
- 标定验证策略：对 LAI、FRUITD、YIELD、HI 指标分别计算 RMSE、NRMSE 与 d-index，优先保证时间结构拟合，再优化终值。

## 4. 讨论（生理机制阐述）

TRIFL 直接控制叶片出现速率与 Thermal time 的“叶片建成率”，是 LAI 动态与地上生物量形成的核心驱动；XFRT 作为同化物向果实分配的强度控制，决定了 FRUITD_AUC 与 YIELD_HWAMS 的上限。PM06 与 TB2/TO22/TO12 共同作用于物候推进与冠层扩张窗口，影响 LAI 与果实生长的时间对齐。FRLFF/FRSTMF 与 PORPT 的显著性提示水氮处理下根系吸水能力对冠层与果实形成存在间接约束，符合 Genotype-by-environment interaction 的敏感性差异结构。建议在后续率定中按“Thermal time → 冠层结构 → 果实分配”顺序推进，以降低参数共线与目标间冲突。
