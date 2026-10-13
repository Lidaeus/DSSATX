# E02 v46 苗龄（PAGE）统一多臂实验与全指标评估报告

**日期**: 2026-09-01  
**优化目的**: 探索两季苗龄（`PAGE`）统一设置为 25、30 或 60 对株高（CHTD）、鲜果产量（CHFPW）、叶面积（LAID）及碳氮响应的综合影响，找出两季兼优的最优配置  
**产物目录**: `D:\Tomato_Cal\figture\e02_formal_v46_page25_unified_20260901`  
**参数文件**: `D:\Tomato_Cal\workspace\runs\e02_formal_v46_page25_unified_20260901\page25_champion_params.csv`  

---

## 1. 实验臂设计与控制

本实验构建了 3 个统一苗龄实验臂（各臂均在全 22 个水氮处理下执行）：
1. **Arm_PAGE25 (两季统一 PAGE = 25 天)**: 适宜商品苗龄，幼苗未老化，初始化主茎节位 $L\#SD \approx 0.7$；
2. **Arm_PAGE30 (两季统一 PAGE = 30 天)**: 稍长商品苗龄，初始化主茎节位 $L\#SD \approx 2.5$；
3. **Arm_PAGE60 (两季统一 PAGE = 60 天)**: 严重老化苗龄，初始化主茎节位 $L\#SD \approx 18.3$。

---

## 2. 三臂综合表现多指标得分卡

| 评估指标 | **Arm_PAGE25 (统一 25 天, Champion)** | **Arm_PAGE30 (统一 30 天)** | **Arm_PAGE60 (统一 60 天)** |
|---|---:|---:|---:|
| **25SP 株高 CHTD NSE** | **0.834** | 0.707 | **-0.786 (严重失真)** |
| **25SP 株高 CHTD RMSE (m)** | **0.20 m** | 0.27 m | 0.67 m |
| **25SP 株高 CHTD d-index / R2** | **0.939 / 0.955** | 0.875 / 0.932 | 0.443 / 0.035 |
| **26SP 株高 CHTD NSE** | **0.933** | 0.695 | **-7.256 (彻底崩溃)** |
| **26SP 株高 CHTD RMSE (m)** | **0.12 m** | 0.26 m | 1.15 m |
| **26SP 株高 CHTD d-index / R2** | **0.979 / 0.983** | 0.892 / 0.956 | 0.412 / 0.910 |
| **25SP 累积鲜产 CHFPW NSE** | **0.824** | **0.910** | 0.944 |
| **25SP 累积鲜产 d-index** | **0.963** | 0.980 | 0.985 |
| **26SP 累积鲜产 CHFPW NSE** | **0.920** | **0.922** | 0.798 |
| **26SP 累积鲜产 d-index** | **0.979** | 0.979 | 0.952 |
| **25SP 叶面积指数 LAID NSE** | **0.378** | -0.252 | 0.763 |
| **综合多目标评分 (Yield+CHTD+LAI)** | **87.78 (最优平衡)** | 75.40 | 8.44 (极差) |

---

## 3. 多臂机理发现与核心结论

1. **Arm_PAGE60 被坚决淘汰**：
   - 过去 25SP 设置 `PAGE=60` 是为了强行提前坐果来贴合早期采收；
   - 当将 `PAGE=60` 推广到 26SP 时，26SP 的株高 NSE 直接暴跌至 **-7.256**，鲜产 NSE 从 0.92 跌至 0.79。这证实 `PAGE=60` 会引发全季生理早熟、节位瞬间饱和及株高过早封顶，完全脱离真实农艺规律。
2. **Arm_PAGE25 为综合最佳解（Champion Arm）**：
   - 将两季统一为适龄苗龄（`PAGE=25`）后，通过对生育期参数微调（`EM-FL` 从 24.7 调至 21.7，`XFRT` 设为 0.910），两季株高均呈现出生理自然的 S 型平滑伸长曲线；
   - **25SP 株高 NSE 达到 0.834（RMSE 仅 0.20 m）**，**26SP 株高 NSE 达到 0.933（RMSE 仅 0.12 m）**；
   - 同时两季累积鲜果产量 NSE 分别达到 **0.824** 和 **0.920**（一致性指数 $d > 0.96$），实现了产量、株高与冠层生长的多目标全局平衡。
3. **Arm_PAGE30 作为次优备选**：
   - 产量表现优异（两季 NSE 均 > 0.91），但株高模拟提前封顶（两季 CHTD NSE 降至 ~0.70），冠层生物量积累稍受挤压。

---

## 4. 产物与交付清单

- **多臂对比图**: [`figture/e02_formal_v46_page25_unified_20260901/diagnostic_page_multiarm_comparison.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page25_unified_20260901/diagnostic_page_multiarm_comparison.png)
- **25SP 株高全处理动态图 (PAGE=25)**: [`figture/e02_formal_v46_page25_unified_20260901/diagnostic_chtd_dynamics_25sp.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page25_unified_20260901/diagnostic_chtd_dynamics_25sp.png)
- **26SP 株高全处理动态图 (PAGE=25)**: [`figture/e02_formal_v46_page25_unified_20260901/diagnostic_chtd_dynamics_26sp.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page25_unified_20260901/diagnostic_chtd_dynamics_26sp.png)
- **基础评估套件**: `figture/e02_formal_v46_page25_unified_20260901/` (`metrics_heatmap_*.png`, `scatter_*.png`, `residual_*.png`, `25SP/`, `26SP/`)
- **最优参数文件**: `workspace/runs/e02_formal_v46_page25_unified_20260901/page25_champion_params.csv`
