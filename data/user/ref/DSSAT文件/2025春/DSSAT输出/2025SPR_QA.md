# 2025 SPRING EGGPLANT DSSAT File A / File T 质量检查

## 输出摘要

- File A：14 行，TRNO 1–14。
- File T：205 行，15 个不同观测日。
- 含采收数据的 File T 行：154。
- 观测总数 (PEST++ CSV)：876。

## 列结构 (参考 XXQL2501.TMA/TMT)

- File A: `TRNO  PDAT  ADAT  MDAT  HDAT  HWAM  LWAM  SWAM  LAIX  HIAM  CNAM`
- File T: `TRNO  DATE  L#SD  LAID  L#PA  LWAD  RWAD  SWAD  M#AD  SLAD  CHTD  CWID  CNAM  SNAM  LNAM  HFPOW  CHFPW  HPODW  CHPDT  PDMCD`

## 源数据与换算

- Fresh yield uses pre-computed weighted plot yield (edge*0.5 + middle-row mean*0.5).
- Fruit DM fraction = 1 - measured fruit moisture fraction (2025春作物生长指标集.果含水率).
- Each harvest uses the nearest plot-level moisture measurement date.
- SD: hybrid method (replicate SD with min CV=5%, fallback CV=10%).
- Cumulative yield SD propagates incremental variances.

## 关键指标

- `plots`: 14
- `growth_dates`: 4
- `harvest_dates`: 11
- `dmfr_dates`: 2
- `nitrogen_rows`: 18
- `total_observations`: 876
- `density`: 27000.0

## SD 计算方案

- 混合方法：重复数 >= 2 时用样本 SD (ddof=1)，CV < 5% 时取 5%*|mean| 为下限；重复数 < 2 时用固定 CV=10%。
- 累计产量 SD：通过增量方差求和 (sqrt(Σvar_inc)) 传播。
- 干产量 SD：通过 fresh_sd 和 DMFR_sd 误差传播 (sqrt(DMFR²·var_fresh + fresh²·var_DMFR))。
