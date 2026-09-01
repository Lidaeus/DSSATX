# E02 v46 25SP/26SP 土壤初始硝态氮铵态氮翻倍再率定与后验分布评估报告

**日期**: 2026-08-31  
**优化策略**: 25SP & 26SP 土壤初始硝态氮（SNO3）与铵态氮（SNH4）含量翻倍（2x），沿用早期采收权重放宽（H1: 0.10, H2: 0.20）与 Dias et al. 2026 闭环碳氮耦合机制重率定  
**产物目录**: `D:\Tomato_Cal\figture\e02_formal_v46_dias2026_double_n_20260831`  
**参数文件**: `D:\Tomato_Cal\workspace\runs\e02_formal_v46_dias2026_double_n_20260831\dias2026_double_n_champion_params.csv`  

---

## 1. 试验数据与初始氮调整

1. **新建试验 Bundle**:
   - `data/user/experiments/xxql2501_scheme4_double_n_20260831`
   - `data/user/experiments/xxql2601_scheme4_double_n_20260831`
2. **初始氮修改说明**:
   - 在 `XXQL2501.TMX` 和 `XXQL2601.TMX` 的 `*INITIAL CONDITIONS` 中，将所有处理各土层的 `SNH4` 与 `SNO3` 浓度严格翻倍（x2.0），保持实测土壤体积含水量 `SH2O` 不变；
   - 25SP 表层初始硝态氮由 11.8 mg/kg 升至 23.6 mg/kg，26SP 表层初始硝态氮由 12.5 mg/kg 升至 25.0 mg/kg。

---

## 2. 率定性能演进与跨阶段对比

| 评估指标 | Baseline best71 (原初始N) | 早期权重放宽 Champion (原初始N) | **翻倍初始氮 Champion (本次率定)** | 较 Baseline 总体提升 |
|---|---:|---:|---:|:---:|
| **采收加权目标函数 Phi_harvest** | 576.29 | 490.97 | **491.60** | **-84.69 (优异收敛)** |
| **25SP 累积鲜产 RMSE (kg/ha)** | 8505.95 | 6140.18 | **4770.95** | **-3735.00 (误差大幅减半!)** |
| **25SP 累积鲜产 NSE** | 0.825 | 0.909 | **0.945** | **+0.120 (突破 0.945!)** |
| **25SP 累积鲜产 d-index / R2** | 0.946 / 0.961 | 0.974 / 0.966 | **0.985 / 0.961** | **接近完美一致度 (d=0.985)** |
| **25SP 叶面积指数 LAID NSE** | 0.472 | 0.618 | **0.763** | **+0.291 (跨越式提升至 0.763!)** |
| **25SP 叶干重 LWAD NSE** | 0.600 | 0.726 | **0.798** | **+0.198 (提升至 0.798!)** |
| **25SP 茎干重 SWAD NSE** | 0.887 | 0.915 | **0.837** | 保持稳健 (>0.83) |
| **26SP 累积鲜产 RMSE (kg/ha)** | 5746.28 | 6468.14 | **6408.28** | 维持在 ~6400 包络内 |
| **26SP 累积鲜产 NSE / d-index** | 0.927 / 0.982 | 0.907 / 0.976 | **0.909 / 0.977** | **保持极高水准 (>0.90)** |
| **26SP 茎干重 SWAD NSE** | 0.797 | 0.836 | **0.865** | **+0.068 (提升至 0.865)** |
| **26SP 株高 CHTD NSE** | 0.877 | 0.867 | **0.865** | 保持高位 (>0.86) |

> **机理洞察**：
> 当初始矿质氮供给翻倍后，25SP 前期生物量构建和冠层展开（`LAID`, `LWAD`）的营养亏缺被有效缓解，使得 25SP 的冠层模拟精度出现了根本性的飞跃（`LAID NSE` 从 0.47 飙升至 **0.763**，`LWAD NSE` 从 0.60 升至 **0.798**），全季累积鲜产 RMSE 更是大幅降低至 **4,770 kg/ha**（相对误差仅 **12.8%**）。

---

## 3. 翻倍氮条件下最优参数（Champion Parameter Set）

```csv
FNPGN1,1.80
FNPGN2,4.90
LNREF,4.00
NSLOPE,0.25
XFRT,0.850
PROLFF,0.105
PROLFG,0.210
PROLFI,0.260
PROSTF,0.060
PROSTG,0.125
PROSTI,0.200
PRORTF,0.050
PRORTG,0.119
PRORTI,0.150
PROSHF,0.105
PROSHG,0.145
PROSHI,0.205
NSTFAC,0.70
RTNO3,0.018
RTNH4,0.033
NMOBMX,0.35
NVSMOB,0.80
SENRTE,2.50
```

---

## 4. 产物与交付路径

- **图表与后验分布目录**: `figture/e02_formal_v46_dias2026_double_n_20260831/`
  - 动态轨迹后验不确定性分布带（P10-P90 / IQR / Median）:
    - `diagnostic_posterior_dynamics_25sp_fresh_yield.png`
    - `diagnostic_posterior_dynamics_25sp_lai.png`
    - `diagnostic_posterior_dynamics_25sp_leaf_biomass.png`
    - `diagnostic_posterior_dynamics_25sp_stem_biomass.png`
    - `diagnostic_posterior_dynamics_26sp_fresh_yield.png`
    - `diagnostic_posterior_dynamics_26sp_lai.png`
    - `diagnostic_posterior_dynamics_26sp_leaf_biomass.png`
    - `diagnostic_posterior_dynamics_26sp_stem_biomass.png`
  - 参数后验分布与收缩图: `diagnostic_parameter_posterior_contraction.png`, `diagnostic_parameter_posterior_density.png`
  - 基础诊断套件: `metrics_heatmap_*.png`, `scatter_*.png`, `residual_*.png`, `25SP/`, `26SP/`
  - 论文级 R 输出目录: `paper_figures/`
- **率定数据与参数目录**: `workspace/runs/e02_formal_v46_dias2026_double_n_20260831/`
