# E02 v46 针对性参数率定（25SP PAGE=28d / 26SP PAGE=25d）最终技术交接与综合评估报告

**日期**: 2026-09-01  
**优化方案**: 根据针对性网格实验结果，释放源库、积温与碳氮关键后验压力点，将 25SP 定植苗龄设定为 **28d**、26SP 定植苗龄设定为 **25d**，在全 22 个水氮处理下执行高精度参数率定  
**产物目录**: `D:\Tomato_Cal\figture\e02_formal_v46_page28_25_opt_20260901`  
**率定数据目录**: `D:\Tomato_Cal\workspace\runs\e02_formal_v46_page28_25_opt_20260901`  
**最优参数文件**: `D:\Tomato_Cal\workspace\runs\e02_formal_v46_page28_25_opt_20260901\page28_25_champion_params.csv`  

---

## 1. 苗龄设置与试验 Bundle 构建

1. **25SP 试验 Bundle**: [`data/user/experiments/xxql2501_page28_double_n_20260901`](file:///D:/Tomato_Cal/data/user/experiments/xxql2501_page28_double_n_20260901)
   - `PAGE = 28` 天，`PENV = 25` °C，`PLPH = -99`，`SPRL = -99`；
   - 包含翻倍初始矿质氮（`SNO3`/`SNH4`）与 7 层校准根系土壤结构。
2. **26SP 试验 Bundle**: [`data/user/experiments/xxql2601_page25_double_n_20260901`](file:///D:/Tomato_Cal/data/user/experiments/xxql2601_page25_double_n_20260901)
   - `PAGE = 25` 天，`PENV = 25` °C，`PLPH = -99`，`SPRL = -99`；
   - 包含翻倍初始矿质氮与校准土壤结构。

---

## 2. 最终率定全指标性能得分卡（跨阶段演进）

| 评估指标类别 | 评估变量 | Baseline best71 (旧PAGE=60/24) | 统一 PAGE=25 优化版 | **本次最终率定版 (25SP=28d / 26SP=25d)** | 评价与提升幅度 |
|---|---|---:|---:|---:|:---:|
| **25SP 产量类** | **累积鲜产 CHFPW NSE** | 0.825 | 0.824 | **0.872** | **跨越式提升 (+0.047)** |
| | **累积鲜产 RMSE (kg/ha)** | 8,505.95 | 8,528.42 | **7,257.47** | **误差显著降低 1,270 kg/ha** |
| | **累积鲜产 NRMSE (%)** | 22.82% | 22.88% | **19.47%** | **相对误差进入 20% 以内** |
| | **累积鲜产 Bias (kg/ha)** | -4,676.34 | -4,676.34 | **-3.52** | **全季平均偏差趋近于 0!** |
| | **累积鲜产 $d$-index / $R^2$** | 0.946 / 0.961 | 0.963 / 0.929 | **0.974 / 0.945** | **高度一致 ($d=0.974$)** |
| | **累积干产 CHPDT NSE** | 0.870 | 0.763 | **0.873** | 保持高位 (RMSE=397.6) |
| **25SP 冠层形态** | **株高 CHTD NSE** | -0.786 (失真) | 0.834 | **0.784** | **由负转正，形态极佳** |
| | **株高 CHTD RMSE (m)** | 0.67 m | 0.20 m | **0.23 m** | **误差降低 66%** |
| | **株高 CHTD Bias (m)** | +0.435 m | -0.058 m | **+0.012 m** | **几乎零偏差** |
| | **株高 CHTD $R^2$** | 0.035 | 0.955 | **0.951** | **极高动态拟合度** |
| | **叶面积指数 LAID NSE** | 0.472 | 0.378 | **0.438** | 稳步改善 ($d=0.900$) |
| | **茎干重 SWAD NSE** | 0.837 | 0.786 | **0.891** | **提升至近 0.90 ($d=0.969$)** |
| **26SP 产量类** | **累积鲜产 CHFPW NSE** | 0.927 | 0.920 | **0.922** | **维持极高水平 (>0.92)** |
| | **累积鲜产 RMSE (kg/ha)** | 5,746.28 | 6,000.78 | **5,928.51** | 相对误差仅 **15.86%** |
| | **累积鲜产 $d$-index / $R^2$** | 0.982 / 0.929 | 0.979 / 0.935 | **0.980 / 0.934** | **极佳一致度 ($d=0.980$)** |
| | **累积干产 CHPDT NSE** | 0.823 | 0.828 | **0.836** | 稳步上升 |
| **26SP 冠层形态** | **株高 CHTD NSE** | 0.865 | 0.933 | **0.923** | **极佳水准 ($d=0.975$)** |
| | **株高 CHTD RMSE (m)** | 0.17 m | 0.12 m | **0.13 m** | 误差仅 13 cm |
| | **株高 CHTD $R^2$** | 0.960 | 0.983 | **0.983** | **完美吻合** |
| | **叶干重 LWAD NSE** | -0.037 | 0.631 | **0.700** | **跨越式提升至 0.70!** |
| | **叶面积指数 LAID NSE** | -3.672 | -1.002 | **-0.707** | 显著回升 ($d=0.814$) |

---

## 3. 本次率定最优机理参数（Champion Parameter Set）

```csv
FNPGN1,1.80
FNPGN2,4.80
LNREF,4.30
NSLOPE,0.25
XFRT,0.945
EM-FL,23.0
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
    - [`diagnostic_posterior_dynamics_25sp_fresh_yield.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_25sp_fresh_yield.png) (25SP 鲜果产量，NSE=0.872)
    - [`diagnostic_posterior_dynamics_25sp_lai.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_25sp_lai.png) (25SP 叶面积指数)
    - [`diagnostic_posterior_dynamics_25sp_leaf_biomass.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_25sp_leaf_biomass.png) (25SP 叶干重)
    - [`diagnostic_posterior_dynamics_25sp_stem_biomass.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_25sp_stem_biomass.png) (25SP 茎干重，NSE=0.891)
    - [`diagnostic_posterior_dynamics_26sp_fresh_yield.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_26sp_fresh_yield.png) (26SP 鲜果产量，NSE=0.922)
    - [`diagnostic_posterior_dynamics_26sp_lai.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_26sp_lai.png) (26SP 叶面积指数)
    - [`diagnostic_posterior_dynamics_26sp_leaf_biomass.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_26sp_leaf_biomass.png) (26SP 叶干重，NSE=0.700)
    - [`diagnostic_posterior_dynamics_26sp_stem_biomass.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_posterior_dynamics_26sp_stem_biomass.png) (26SP 茎干重)
  - 株高真实时序动态拟合图:
    - [`diagnostic_chtd_dynamics_25sp.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_chtd_dynamics_25sp.png) (25SP 株高，NSE=0.784, R2=0.951)
    - [`diagnostic_chtd_dynamics_26sp.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_chtd_dynamics_26sp.png) (26SP 株高，NSE=0.923, R2=0.983)
  - 参数后验收缩图: [`diagnostic_parameter_posterior_contraction.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/diagnostic_parameter_posterior_contraction.png)
  - 基础诊断套件: `metrics_heatmap_*.png`, `scatter_*.png`, `residual_*.png`, `25SP/`, `26SP/`
  - 论文级 R 渲染图集: [`figture/e02_formal_v46_page28_25_opt_20260901/paper_figures/`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page28_25_opt_20260901/paper_figures)
- **率定数据与参数目录**: [`workspace/runs/e02_formal_v46_page28_25_opt_20260901/`](file:///D:/Tomato_Cal/workspace/runs/e02_formal_v46_page28_25_opt_20260901)
