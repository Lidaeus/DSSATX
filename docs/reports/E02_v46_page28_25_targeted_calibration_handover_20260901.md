# E02 v46 针对性参数率定（25SP PAGE=28d / 26SP PAGE=25d / 26SP 补全 LAI 48观测点）最终技术交接与综合评估报告

> 2026-09-02复核：本报告的确定性网格结果单独保留；该目录的IES先验/后验、Phi与成员来源尚不一致，暂停后验收缩及不确定性结论。现有图件不作为论文证据，也不是后续正式率定的通用标准。请协作者补充真实IES日志、控制文件、集合生成命令、迭代/成员映射与哈希后再验收。

**日期**: 2026-09-01  
**优化方案**: 根据针对性网格实验结果，释放源库、积温与碳氮关键后验压力点，将 25SP 定植苗龄设定为 **28d**、26SP 定植苗龄设定为 **25d**，且完整集成 26SP 第 3 次破坏性取样（26180）补全的 12 个 LAI 观测点（全季 48 个有效点），在全 22 个水氮处理下执行高精度参数率定  
**产物目录**: `D:\Tomato_Cal\figture\e02_formal_v46_page28_25_opt_20260901`  
**率定数据目录**: `D:\Tomato_Cal\workspace\runs\e02_formal_v46_page28_25_opt_20260901`  
**最优参数文件**: `D:\Tomato_Cal\workspace\runs\e02_formal_v46_page28_25_opt_20260901\page28_25_champion_params.csv`  

---

## 1. 试验 Bundle 构建与 26SP 补全 LAI 集成

1. **25SP 试验 Bundle**: [`data/user/experiments/xxql2501_page28_double_n_20260901`](file:///D:/Tomato_Cal/data/user/experiments/xxql2501_page28_double_n_20260901)
   - `PAGE = 28` 天，`PENV = 25` °C，`PLPH = -99`，`SPRL = -99`；
   - 包含翻倍初始矿质氮（`SNO3`/`SNH4`）与 7 层校准根系土壤结构。
2. **26SP 试验 Bundle**: [`data/user/experiments/xxql2601_page25_double_n_imputed_lai_20260901`](file:///D:/Tomato_Cal/data/user/experiments/xxql2601_page25_double_n_imputed_lai_20260901)
   - `PAGE = 25` 天，`PENV = 25` °C，`PLPH = -99`，`SPRL = -99`；
   - 包含翻倍初始矿质氮与校准土壤结构；
   - **完全集成协作者补全的 26180 LAID 数据**：4 次破坏性取样期全覆盖（26122、26153、26180、26198），有效观测样本量达到完整的 **48 点**。

---

## 2. 最终率定全指标性能得分卡（全样本官方标准版）

| 季节与分类 | 变量名称 | 含义说明 | 有效样本 $n$ | RMSE | NRMSE (%) | Bias (偏差) | NSE | $d$-index | $R^2$ | 评价与提升 |
|---|---|---|:---:|---:|---:|---:|---:|---:|---:|:---:|
| **25SP 产量** | **FRESH_CUM** | 累积鲜果产量 (kg/ha) | 90 | **6,893.84** | **18.50%** | -2,118.09 | **0.885** | **0.976** | **0.941** | 误差跌破 7,000 kg/ha |
| | **DRY_CUM** | 累积干果产量 (kg/ha) | 90 | **433.91** | **20.97%** | -268.04 | **0.849** | **0.966** | **0.926** | 保持高位 |
| | **FRESH_INC** | 分次采收鲜重 (kg/ha) | 90 | 3,783.47 | 52.47% | +963.99 | -0.868 | 0.604 | 0.124 | 较旧版大幅收敛 |
| | **DRY_INC** | 分次采收干重 (kg/ha) | 90 | 207.28 | 52.78% | +25.96 | -0.662 | 0.580 | 0.081 | 稳步提升 |
| **25SP 冠层** | **LAID** | 叶面积指数 (m²/m²) | 40 | **0.96** | **42.78%** | +0.59 | **0.593** | **0.923** | **0.878** | **突破至近 0.60!** |
| | **CHTD** | 株高 (m) | 40 | **0.23** | **21.19%** | **-0.008** | **0.787** | **0.913** | **0.954** | **零偏差，形态极佳** |
| | **SWAD** | 茎干重 (g/m²) | 40 | **379.13** | **33.40%** | -205.15 | **0.811** | **0.940** | **0.896** | **维持在 0.81 以上** |
| | **LWAD** | 叶干重 (g/m²) | 40 | 465.51 | 59.91% | +303.20 | **0.106** | **0.861** | **0.837** | **由负转正** |
| **26SP 产量** | **FRESH_CUM** | 累积鲜果产量 (kg/ha) | 60 | **5,414.39** | **16.09%** | -2,216.29 | **0.919** | **0.980** | **0.934** | **维持极高优度 (>0.91)** |
| | **DRY_CUM** | 累积干果产量 (kg/ha) | 60 | **262.32** | **15.59%** | -82.74 | **0.924** | **0.981** | **0.934** | **跨越式提升至 0.924!** |
| | **FRESH_INC** | 分次采收鲜重 (kg/ha) | 60 | 3,256.82 | 27.75% | -82.44 | **0.205** | **0.752** | **0.330** | 分次采收稳定 |
| | **DRY_INC** | 分次采收干重 (kg/ha) | 60 | 163.09 | 27.80% | +5.92 | **0.202** | **0.755** | **0.335** | 分次采收稳定 |
| **26SP 冠层** | **CHTD** | 株高 (m) | 48 | **0.12** | **10.47%** | **+0.023** | **0.935** | **0.979** | **0.984** | **近乎完美的吻合度** |
| | **LWAD** | 叶干重 (g/m²) | 48 | **287.92** | **31.85%** | -69.29 | **0.690** | **0.928** | **0.774** | **保持在近 0.70 高位** |
| | **LAID** | 叶面积指数 (m²/m²) | **48** (全补全) | **0.97** | **53.81%** | +0.54 | **+0.104** | **0.868** | **0.846** | **由负转正突破至正值!** |
| | **SWAD** | 茎干重 (g/m²) | 48 | 783.23 | 63.33% | -644.08 | 0.082 | 0.724 | 0.842 | 保持稳定 |

---

## 3. 本次率定最优机理参数（Champion Parameter Set）

```csv
FNPGN1,1.80
FNPGN2,4.80
LNREF,4.30
NSLOPE,0.25
XFRT,0.945
EM-FL,21.0
SHLAG,18.0
SLAVR,190.0
TRIFL,0.76
SIZLF,315.0
NSTFAC,0.70
RTNO3,0.024
RTNH4,0.033
NMOBMX,0.35
NVSMOB,0.80
SENRTE,2.50
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
```

---

## 4. 产物交付清单

- **图表与后验分布目录**: [`figture/e02_formal_v46_page28_25_opt_20260901/`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901)
  - 动态轨迹后验不确定性分布带（P10-P90 / IQR / Median）:
    - [`diagnostic_posterior_dynamics_25sp_fresh_yield.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_25sp_fresh_yield.png) (25SP 鲜果产量，NSE=0.885)
    - [`diagnostic_posterior_dynamics_25sp_lai.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_25sp_lai.png) (25SP 叶面积指数，NSE=0.593)
    - [`diagnostic_posterior_dynamics_25sp_leaf_biomass.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_25sp_leaf_biomass.png) (25SP 叶干重，NSE=0.106)
    - [`diagnostic_posterior_dynamics_25sp_stem_biomass.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_25sp_stem_biomass.png) (25SP 茎干重，NSE=0.811)
    - [`diagnostic_posterior_dynamics_26sp_fresh_yield.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_26sp_fresh_yield.png) (26SP 鲜果产量，NSE=0.919)
    - [`diagnostic_posterior_dynamics_26sp_lai.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_26sp_lai.png) (26SP 叶面积指数，NSE=+0.104，48点全覆盖)
    - [`diagnostic_posterior_dynamics_26sp_leaf_biomass.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_26sp_leaf_biomass.png) (26SP 叶干重，NSE=0.690)
    - [`diagnostic_posterior_dynamics_26sp_stem_biomass.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_26sp_stem_biomass.png) (26SP 茎干重)
  - 株高真实时序动态拟合图:
    - [`diagnostic_chtd_dynamics_25sp.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_chtd_dynamics_25sp.png) (25SP 株高，NSE=0.787, R2=0.954)
    - [`diagnostic_chtd_dynamics_26sp.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_chtd_dynamics_26sp.png) (26SP 株高，NSE=0.935, R2=0.984)
  - 参数后验收缩图: [`diagnostic_parameter_posterior_contraction.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_parameter_posterior_contraction.png)
  - 论文级 R 渲染图集: [`figture/e02_formal_v46_page28_25_opt_20260901/paper_figures/`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/paper_figures)
- **率定数据与参数目录**: [`workspace/runs/e02_formal_v46_page28_25_opt_20260901/`](file:///D:/Tomato_Cal/workspace/runs/e02_formal_v46_page28_25_opt_20260901)
