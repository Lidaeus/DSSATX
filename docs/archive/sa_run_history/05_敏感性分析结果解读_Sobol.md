# 05_敏感性分析结果解读_Sobol

> **历史结果，禁止作为当前科研结论。** 其上游 SA 未通过现行质量门；指数、排名和交互解释需重新验证。状态更新：2026-07-15。

## 1. 引言（Gap 发现）

Morris 已完成全参数 Screening，但其结果无法充分揭示参数交互与总效应贡献。为避免在 PEST++ 标定中出现“强交互参数被低估”的风险，需要使用 Sobol（STi）对 Top-K 参数进行二次定权，从而形成更稳健的分批率定顺序与论文中的机制解释框架。

## 2. 材料与方法（试验设计 + 模型描述）

- 方法与数据：采用 PEST++ Sobol（Saltelli）方案，使用 STi 作为总效应指标；质量报告显示 Si/STi 无 NaN，结果可用于解释。
- 指标体系：与 Morris 保持一致，包含 LAI、FRUITD、YIELD、HI 与生物量相关指标，时间序列按 indicator group 聚合。
- 率定评价口径：后续批次标定继续采用 RMSE、NRMSE、d-index 作为拟合评价标准。
- 机制重点：强调 Thermal time 与冠层几何对物候与同化的共同驱动，并识别 Genotype-by-environment interaction 对不同处理间敏感性差异的影响。

## 3. 结果（标定验证 + 优化结果）

### 3.1 Sobol 总效应排序（STi）

| 排名 | 参数 | STi |
| --- | --- | --- |
| 1 | TRIFL | 0.512 |
| 2 | XFRT | 0.157 |
| 3 | TB2 | 0.130 |
| 4 | TO22 | 0.110 |
| 5 | TO11 | 0.077 |
| 6 | RWDTH | 0.039 |
| 7 | KCAN | 0.035 |
| 8 | PM06 | 0.035 |
| 9 | TB1 | 0.034 |
| 10 | ATOP | 0.031 |
| 11 | FRLFF | 0.028 |
| 12 | FRSTMF | 0.025 |
| 13 | LFMAX | 0.025 |
| 14 | RHGHT | 0.019 |
| 15 | PORPT | 0.004 |

结论：TRIFL 在总效应上占据绝对主导，XFRT 与 Thermal time（TB2/TO22/TO11/TB1）构成产量与物候的核心约束，冠层几何（RWDTH、KCAN、LFMAX）与根系分配（FRLFF/FRSTMF）对 LAI 与生物量具有稳定但次级的总效应。

### 3.2 指标层面的关键响应

- LAI 与生物量：TRIFL 对 LAI_AUC/LAI_END 具有极高 STi（>0.80），是冠层时序拟合的首要参数；RWDTH 与 KCAN 对 LAI 形态提供结构性约束。
- 果实与产量：XFRT 对 FRUITD_END 与 HI 的 STi 显著，同时 TO22 对 YIELD_HWAMS 的 STi 达到 0.70 级别，提示 Thermal time 对收获窗口与累积产量具有决定性影响。
- 物候尺度：TB2 与 TO11 在 ADAPS 与 HI 上具有明显贡献，适合作为优先校准参数，以稳定物候—冠层—产量的时序联动。

### 3.3 标定与优化建议

- 分批率定顺序建议：Thermal time（TB1/TB2/TO11/TO22）→ 冠层结构（TRIFL、RWDTH、KCAN、LFMAX）→ 果实分配（XFRT、PM06、ATOP）→ 根系水分（FRLFF、FRSTMF、PORPT）。
- 标定验证重点：对 LAI、FRUITD、YIELD、HI 分别计算 RMSE、NRMSE、d-index，优先锁定时间结构与关键 DAP 的形态一致性，再优化终值。

## 4. 讨论（生理机制阐述）

Sobol 结果显示 TRIFL 与 Thermal time 参数共同塑造冠层扩张与物候推进的主导框架，属于典型“源—时序耦合控制”。XFRT 的高总效应反映果实库强度对累积产量的限制性作用，而 TO22 对产量的高 STi 表明“有效积温窗口”是茄子模型中产量形成的关键生态尺度。RWDTH、KCAN、LFMAX 等冠层几何参数通过光截获与同化效率影响 LAI 形态，根系参数（FRLFF/FRSTMF/PORPT）在水氮情景下放大 G×E 交互效应。该结果支持采用分批率定与多指标协同评价，避免在单一产量指标上过度拟合而破坏过程一致性。
