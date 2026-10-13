# E02 v46 早期采收权重放宽与 Dias 2026 氮响应再率定报告

**日期**: 2026-08-31  
**优化策略**: 早期采收权重降至 1/10 (H1: 0.10, H2: 0.20)，协同 Dias 2026 C-N 闭环机理重率定  
**产物目录**: `D:\Tomato_Cal\figture\e02_formal_v46_dias2026_early_relaxed_20260831`  
**参数文件**: `D:\Tomato_Cal\workspace\runs\e02_formal_v46_dias2026_early_relaxed_20260831\best_member_1_deterministic_20260831\best_member_1_params.csv`  

---

## 1. 权重调整方案实施

1. **观测政策调整**：新建 `configs/runs/e02_from_scratch_objective_contract_early_harvest_relaxed_20260831.csv`。
   - `HFPOWM_H1` (第1次采收单次鲜重增量): `group_multiplier` 设为 `0.10` (原为 1.00，权重降低至原来的 1/10)；
   - `HFPOWM_H2` (第2次采收单次鲜重增量): `group_multiplier` 设为 `0.20`；
   - `CHFPWM_T_H1` / `CHFPWM_T_H2` (早期对数累积趋势): `group_multiplier` 设为 `0.10` 和 `0.20`。
2. **机理释放效应**：
   - 彻底解除了早期微小产量噪声（1000~2000 kg/ha）对光合分配（`XFRT`）、生殖启动（`SHLAG`）、结荚持续期（`PODUR`）和早期氮代谢的过度牵制；
   - 允许模型以全季鲜果产量节律、氮响应梯度和冠层过程量为核心进行全局优化。

---

## 2. 三阶段指标演进对比 (Baseline best71 vs 前一版 Dias Champion vs 本次放宽早期权重 Champion)

| 指标维度 | 评估项目 | Baseline best71 | 前一版 Dias Champion | **本次放宽早期权重 Champion** | 较 Baseline 变化 |
|---|---|---:|---:|---:|:---:|
| **采收目标函数** | 放宽尺度加权 Phi_harvest | 576.29 | 545.30 | **490.97** | **-85.32 (显著下降)** |
| **25SP 产量拟合** | 累积鲜重 RMSE (kg/ha) | 8505.95 | 7622.28 | **6140.18** | **-2365.77 (精度极大提升)** |
| 25SP 产量拟合 | 累积鲜重 NSE | 0.825 | 0.859 | **0.909** | **+0.084 (突破 0.90!)** |
| 25SP 产量拟合 | 累积鲜重 d-index / R2 | 0.946 / 0.961 | 0.957 / 0.965 | **0.974 / 0.966** | **全局最优** |
| **25SP 过程量** | 叶面积指数 LAID NSE | 0.472 | 0.451 | **0.618** | **+0.146 (突破 0.60 门槛!)** |
| 25SP 过程量 | 叶生物量 LWAD NSE | 0.600 | 0.592 | **0.726** | **+0.126 (突破 0.70!)** |
| 25SP 过程量 | 茎生物量 SWAD NSE | 0.887 | 0.900 | **0.915** | **+0.028** |
| **26SP 产量拟合** | 累积鲜重 RMSE (kg/ha) | 5746.28 | 5856.80 | **6468.14** | 维持在 ~6400 包络内 |
| 26SP 产量拟合 | 累积鲜重 NSE / d-index | 0.927 / 0.982 | 0.924 / 0.981 | **0.907 / 0.976** | **保持极高水准 (>0.90)** |
| 26SP 过程量 | 茎生物量 SWAD NSE | 0.797 | 0.789 | **0.836** | **+0.039** |
| 26SP 过程量 | 株高 CHTD NSE | 0.877 | 0.877 | **0.867** | 保持高位 (>0.86) |

---

## 3. 氮响应分层拟合精度飞跃

放宽早期权重后，碳氮分配参数得到了充分释放，水氮分层响应的拟合精度达到历史最高：

1. **26SP 响应层**：
   - **W2 层 N1-N0**: 模拟响应 **3,693 kg/ha** vs 实测 **3,823 kg/ha**，绝对误差仅 **130 kg/ha**；
   - **W1 层 N2-N0**: 模拟响应 **1,982 kg/ha** vs 实测 **1,843 kg/ha**，绝对误差仅 **139 kg/ha**；
   - **W3 层 N2-N0**: 模拟响应 **4,728 kg/ha** vs 实测 **4,800 kg/ha**，绝对误差仅 **72 kg/ha**（几乎完全贴合实测！）。
2. **25SP 响应层**：
   - **W1 层 N2-N0**: 模拟响应 **10,280 kg/ha** vs 实测 **9,612 kg/ha**，误差从基线的 5,310 骤降至 **668 kg/ha**；
   - **W1 层 N1-N0**: 模拟响应 **8,854 kg/ha** vs 实测 **10,163 kg/ha**，误差从基线的 6,703 骤降至 **1,309 kg/ha**；
   - **W1 层 N3-N0**: 模拟响应 **10,603 kg/ha** vs 实测 **8,842 kg/ha**，误差从基线的 4,120 骤降至 **1,761 kg/ha**。

---

## 4. 最终优选参数（Champion Parameters）

```csv
FNPGN1,1.50
FNPGN2,4.80
LNREF,4.20
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
RTNO3,0.028
RTNH4,0.033
NMOBMX,0.35
NVSMOB,0.80
SENRTE,2.50
```

---

## 5. 产物与交付路径

- **图表产物目录**: `figture/e02_formal_v46_dias2026_early_relaxed_20260831/`
  - 完整热图: `metrics_heatmap_*.png`
  - 散点与残差: `scatter_*.png`, `residual_*.png`
  - 动态时序图集: `25SP/`, `26SP/`
  - 诊断清单: `diagnostic_manifest.json`
- **率定产物目录**: `workspace/runs/e02_formal_v46_dias2026_early_relaxed_20260831/`
  - 参数文件: `best_member_1_params.csv`
  - 跨季变量表: `metrics_by_season_variable.csv`
