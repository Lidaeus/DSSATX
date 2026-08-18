# 当前开发与科研报告入口

> 重整日期：2026-07-29

`docs/reports/` 只作为后续新报告的暂存入口。已经完成、被替代或仅用于经验追溯的报告已分批移入 `docs/archive/`，避免历史命令、旧边界和旧评价口径继续与当前研究混用。

## 当前先读

1. [近期遗传参数率定关键科研决策](../archive/decision_records/DR-20260729_近期遗传参数率定关键科研决策.md)
2. [项目状态与科研启动清单](../项目状态与科研启动清单.md)
3. [参数率定试验矩阵与论文逻辑](../参数率定试验矩阵与论文逻辑_v1_20260723.md)
4. [论文材料与方法：多季节参数率定框架](../论文材料与方法_DSSAT_PEST多季节参数率定框架.md)

## 历史报告分类

| 类别 | 位置 | 内容 |
|---|---|---|
| 工程开发与代码审查 | [development_records](../archive/development_records/) | Code Review、P0/P2、质量门和工程实施记录 |
| SA 与早期率定历史 | [sa_run_history](../archive/sa_run_history/) | P1、Morris、Sobol、T6–T10 和失败复盘 |
| E00–E02 率定迭代 | [calibration_run_history](../archive/calibration_run_history/) | 预率定、正式率定、边界、权重和结果诊断 |
| 管理优化探索 | [management_optimization](../archive/management_optimization/) | 水氮 PSO、管理优化和 DEMO |
| 科研决策快照 | [decision_records](../archive/decision_records/) | 经整理的关键口径、降级决定和下一轮硬门 |

完整批次说明见 [2026-07-29 文档归档清单](../archive/ARCHIVE_MANIFEST_20260729.md)。

## 新报告规则

- 新运行报告可先写入本目录，但阶段结束后必须归档。
- 文件名中的“正式”不等于 `science_validated`；科研状态以 manifest、质量门和决策记录为准。
- 报告记录当时发生了什么，不自动成为当前配置、参数范围或运行命令的权威入口。
- 对论文有长期价值的方法定义应合并到根目录的材料与方法、讨论或图表规范，不能长期散落在运行报告中。
