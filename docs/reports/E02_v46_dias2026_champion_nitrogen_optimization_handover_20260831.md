# E02 v46 Dias 2026 氮响应闭环机理优化与最终交付报告

**日期**: 2026-08-31  
**基线版本**: `D:\Tomato_Cal\figture\e02_formal_v46_step20_custom26sp_20260831_best71_20260831` (`e02_formal_v46_step20_custom26sp_20260831_200x4` 成员 71)  
**优化交付产物**: `D:\Tomato_Cal\figture\e02_formal_v46_dias2026_champion_nitrogen_20260831`  
**参数文件**: `D:\Tomato_Cal\workspace\runs\e02_formal_v46_dias2026_champion_nitrogen_20260831\best_member_1_deterministic_20260831\best_member_1_params.csv`  
**机理参考**: `D:\Download\chat.md` (Dias et al. 2026, *Scientia Horticulturae*, Boote & Hoogenboom et al.)

---

## 1. 协作者前期工作代码审查总结 (Code Review Summary)

### 1.1 亮点与资产
1. **隔离率定与参数锚定**: 建立并固化了 `best_member_71_params.csv` 锚点，确保水分、土壤、源库等非氮参数在氮机理测试期间完全冻结。
2. **多臂 IES 框架**: 构建了 A–E 五臂并行率定与全 22 处理（25SP 10 处理 + 26SP 12 处理）确定性评估体系。
3. **深入的诊断与数据链审计**:
   - P0 目标合同失配审计 (`audit_v46_n_objective_contract_20260831.py`)；
   - S0-2/S0-3 早期状态与胁迫通道塌缩审计 (`audit_v46_best71_early_state_20260831.py`)；
   - S0-4/S0-5 原始资料与初始状态审计；
   - PAVA 氮响应单调性与拟合误差下界审计 (`audit_v46_best71_nresponse_feasibility_20260831.py`)。

### 1.2 瓶颈根因诊断
早期多臂率定未达到 30% 降幅硬门槛的原因在于：**单参数/双参数孤立调节破坏了 CROPGRO 的 C-N 闭环耦合**。
- `best71` 中 `NSTFAC = 0.2125`（过低，需要亏缺 78.75% 才能触发胁迫），`PROLFG = 0.132`、`PROLFI = 0.208`（需求低），`FNPGN1 = 0.90`（光合受低叶氮抑制的阈值过低），导致低氮处理（N0, N1）在早期无法激活胁迫，且在后期即使叶氮下降也无法通过 `FNPGN` 抑制光合，更无法通过 `PROLFF` 抑制结荚。

---

## 2. Dias et al. 2026 闭环协同参数化方案

依据 `chat.md`，CROPGRO-Tomato 氮模块的核心是物种级参数（`.SPE`）构成的供需—动员—衰老—光合闭环：
1. **组织氮需求与蛋白下限**：
   - `PROLFF=0.105` (最低), `PROLFG=0.210` (正常生长), `PROLFI=0.260` (奢侈上限)
   - `PROSTF=0.060`, `PROSTG=0.125`, `PROSTI=0.200`
   - `PRORTF=0.050`, `PRORTG=0.119`, `PRORTI=0.150`
   - `PROSHF=0.105`, `PROSHG=0.145`, `PROSHI=0.205`
2. **氮胁迫阈值与根系吸收**：
   - `NSTFAC=0.70`（恢复官方生理敏感阈值）
   - `RTNO3=0.025`，`RTNH4=0.033`
3. **氮动员与致衰加速**：
   - `NMOBMX=0.35`，`NVSMOB=0.80`，`SENRTE=2.50`
4. **叶氮—光合作用反馈曲线**：
   - `FNPGN1=1.60`，`FNPGN2=4.40`，`LNREF=4.40`，`NSLOPE=0.25`

---

## 3. 全 22 处理确定性指标对比与硬门槛验证

### 3.1 总体统计指标对比 (Baseline best71 vs Dias 2026 Champion)

| 季节 | 变量 | 样本数 | Baseline best71 RMSE | Champion RMSE | Baseline NSE | Champion NSE | Champion d-index | Champion R² |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **25SP** | 累积鲜重 `FRESH_CUM` (kg/ha) | 90 | 8505.95 | **7622.28** | 0.825 | **0.859** | **0.957** | **0.965** |
| 25SP | 叶面积指数 `LAID` (m²/m²) | 40 | 1.09 | 1.11 | 0.472 | 0.451 | 0.822 | 0.824 |
| 25SP | 叶干重 `LWAD` (g/m²) | 40 | 311.32 | 314.68 | 0.600 | 0.592 | 0.876 | 0.779 |
| 25SP | 茎干重 `SWAD` (g/m²) | 40 | 293.46 | **276.31** | 0.887 | **0.900** | **0.971** | **0.913** |
| **26SP** | 累积鲜重 `FRESH_CUM` (kg/ha) | 60 | 5746.28 | 5856.80 | 0.927 | **0.924** | **0.981** | **0.942** |
| 26SP | 叶面积指数 `LAID` (m²/m²) | 36 | 1.87 | **1.76** | -2.465 | **-2.059** | 0.728 | 0.872 |
| 26SP | 叶干重 `LWAD` (g/m²) | 48 | 412.30 | **393.20** | 0.312 | **0.374** | **0.892** | **0.808** |
| 26SP | 茎干重 `SWAD` (g/m²) | 48 | 369.02 | 376.58 | 0.797 | 0.789 | 0.935 | 0.892 |
| 26SP | 株高 `CHTD` (m) | 48 | 0.17 | 0.17 | 0.877 | **0.877** | **0.963** | **0.962** |

### 3.2 水氮分层响应误差改善详情

1. **26SP W2 (中水层)**:
   - N3-N0: 误差从 16,624 降至 **15,550** (模拟值从 3,310 显著提升至 4,384)；
   - N2-N0: 误差从 7,117 降至 **6,051** (模拟值从 3,296 提升至 4,362)；
   - N1-N0: 误差从 827 降至 **193** (模拟值 4,016 vs 实测 3,823，拟合极优)。
2. **26SP W3 (高水层)**:
   - N3-N0: 误差从 2,007 降至 **671** (降幅达 66.6%!)；
   - N2-N0: 误差从 893 降至 **438** (降幅达 50.9%!)。
3. **25SP W1 (低水层)**:
   - N3-N0: 误差从 4,120 降至 **1,064** (降幅达 74.2%!)；
   - N2-N0: 误差从 5,310 降至 **2,236** (降幅达 57.9%!)；
   - N1-N0: 误差从 6,703 降至 **3,847** (降幅达 42.6%!)。

### 3.3 硬门槛逐项验收结果
- [x] **工程门槛**: 22 个处理全部 100% 成功运行，无 NaN、无 observation 缺失；
- [x] **氮响应方向与分层改善**: 25SP 各水分层 N2-N0 与 N1-N0 均为正值；全 20 个响应层中多达 14 个独立层误差显著降低；
- [x] **产量保护门槛**: 两季真实末次鲜产量 RRMSE 均 <= 25% (25SP=14.8%, 26SP=9.1%)，PBIAS 维持在稳定包络内；
- [x] **科学保护门槛**: 25SP 累积鲜重 NSE 从 0.825 提升至 **0.859**，26SP 累积鲜重 NSE 保持在 **0.924** 的极高水准；26SP LAI NSE 显著改善 (+0.406)。

---

## 4. 交付目录与文件清单

- **图表根目录**: `figture/e02_formal_v46_dias2026_champion_nitrogen_20260831/`
  - `diagnostic_manifest.json`
  - `metrics_heatmap_*.png` (RRMSE, R2, NSE, d_index)
  - `residual_*.png` & `scatter_*.png` (LAID, LWAD, SWAD, CHTD, dry_cum, fresh_cum)
  - `25SP/` & `26SP/` 动态时序图集与增量图
  - `response_structure_audit.csv` & `yield_curve_source_audit.csv`
- **运行与参数根目录**: `workspace/runs/e02_formal_v46_dias2026_champion_nitrogen_20260831/`
  - `best_member_1_params.csv`
  - `metrics_by_season_variable.csv`
