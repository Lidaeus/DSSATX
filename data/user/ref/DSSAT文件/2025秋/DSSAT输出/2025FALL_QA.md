# 2025 FALL EGGPLANT DSSAT File A / File T 质量检查

## 输出摘要

- File A：12 行，TRNO 1–12。
- File T：72 行，6 个不同观测日。
- 含采收数据的 File T 行：36。
- 观测总数 (PEST++ CSV)：312。

## 列结构 (参考 XXQL2501.TMA/TMT)

- File A: `TRNO  PDAT  ADAT  MDAT  HDAT  HWAM  LWAM  SWAM  LAIX  HIAM  CNAM`
- File T: `TRNO  DATE  L#SD  LAID  L#PA  LWAD  RWAD  SWAD  M#AD  SLAD  CHTD  CWID  CNAM  SNAM  LNAM  HFPOW  CHFPW  HPODW  CHPDT  PDMCD`

## 源数据与换算

- Fresh yield is a per-harvest measurement (mean across replicates), cumulatively summed by plot.
- Dry harvested yield uses the nearest measured plot fruit DM fraction (mean).
- Fruit DM samples below the dry-weight threshold (10.0g) are excluded.
- Remaining DM fractions are screened within measurement date using Tukey 1.5*IQR fences.
- Two user-identified fruit DM outliers are always excluded.
- SD: hybrid method (replicate SD with min CV=5%, fallback CV=10%).

## 关键指标

- `plots`: 12
- `growth_dates`: 1
- `harvest_dates`: 3
- `dmfr_samples_kept`: 66
- `dmfr_samples_excluded_user`: 0
- `dmfr_samples_excluded_low_weight`: 50
- `dmfr_samples_excluded_iqr`: 1
- `nitrogen_rows`: 24
- `total_observations`: 312
- `density`: 27000.0

## SD 计算方案

- 混合方法：重复数 >= 2 时用样本 SD (ddof=1)，CV < 5% 时取 5%*|mean| 为下限；重复数 < 2 时用固定 CV=10%。
- 累计产量 SD：通过增量方差求和 (sqrt(Σvar_inc)) 传播。
- 干产量 SD：通过 fresh_sd 和 DMFR_sd 误差传播 (sqrt(DMFR²·var_fresh + fresh²·var_DMFR))。
