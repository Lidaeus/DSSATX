# 2026 SPRING EGGPLANT DSSAT File A / File T 质量检查

## 输出摘要

- File A：12 行，TRNO 1–12。
- File T：96 行，8 个不同观测日。
- 含采收数据的 File T 行：60。
- 观测总数 (PEST++ CSV)：420。

## 列结构 (参考 XXQL2501.TMA/TMT)

- File A: `TRNO  PDAT  ADAT  MDAT  HDAT  HWAM  LWAM  SWAM  LAIX  HIAM  CNAM`
- File T: `TRNO  DATE  L#SD  LAID  L#PA  LWAD  RWAD  SWAD  M#AD  SLAD  CHTD  CWID  CNAM  SNAM  LNAM  HFPOW  CHFPW  HPODW  CHPDT  PDMCD`

## 源数据与换算

- Fresh yield is a per-harvest measurement (mean across replicates), cumulatively summed by plot.
- Fruit DM fraction = 1 - measured half-fruit moisture fraction (2026春品质指标集.半果含水率).
- Each harvest uses the nearest plot-level quality measurement date.
- 2026春 has no nitrogen data; SNAM/LNAM/CNAM are -99.
- SD: hybrid method (replicate SD with min CV=5%, fallback CV=10%).

## 关键指标

- `plots`: 12
- `growth_dates`: 4
- `harvest_dates`: 5
- `quality_dates`: 3
- `total_observations`: 420
- `density`: 27000.0

## SD 计算方案

- 混合方法：重复数 >= 2 时用样本 SD (ddof=1)，CV < 5% 时取 5%*|mean| 为下限；重复数 < 2 时用固定 CV=10%。
- 累计产量 SD：通过增量方差求和 (sqrt(Σvar_inc)) 传播。
- 干产量 SD：通过 fresh_sd 和 DMFR_sd 误差传播 (sqrt(DMFR²·var_fresh + fresh²·var_DMFR))。
