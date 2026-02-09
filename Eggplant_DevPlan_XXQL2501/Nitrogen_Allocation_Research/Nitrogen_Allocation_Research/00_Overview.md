# DSSAT 氮分配与果实优先机制研究报告

## 摘要
本报告针对 DSSAT CROPGRO 模块在氮胁迫下的氮分配逻辑进行系统梳理，重点聚焦果实/籽粒（seed/pod）氮分配与胁迫耦合机制。通过代码级分析，明确了氮供需链路、动员上限、胁迫因子与果实分配的关键交互点，并提出在不破坏非胁迫行为的前提下，提升低氮条件果实氮供给的可调节点与约束条件。

## 研究范围
- 作物对象：番茄（Tomato）
- 模型对象：DSSAT-CROPGRO
- 核心主题：氮胁迫因子、动员上限、果实生长与氮分配
- 关键子程序：DEMAND、NUPTAK、MOBIL、VEGGR、PODS、CROPGRO

## 实验文件
- /Users/lidaeus/Downloads/DSSAT_CSM_OS_REPORT/XXQL2501.TMA
- /Users/lidaeus/Downloads/DSSAT_CSM_OS_REPORT/XXQL2501.TMT
- /Users/lidaeus/Downloads/DSSAT_CSM_OS_REPORT/XXQL2501.TMX

## 研究问题
1. 番茄果实生长中，氮胁迫如何被量化并作用于分配与生长
2. 果实氮需求的计算如何与动员/吸收耦合
3. 低氮条件下提高果实氮分配的合理调节点与风险

## 研究结论概览
- NSTRES 与 CNSTRES 构成氮胁迫的主驱动，对生殖生长与壳体/种子氮消耗形成双层约束
- NDMSDR 决定动员 N 对种子需求的覆盖上限，并通过 NUPTAK 反馈影响土壤吸收强度
- 果实氮分配优化应限定于生殖期与低 NSTRES 区间，避免扰动非胁迫情景的基线行为

## 文档结构
- 01_Methods.md：方法与技术路线
- 02_Results.md：结果与机制分析
- 03_Diagrams.md：流程图与变量依赖图
- 04_Recommendations.md：建议表与实施约束
