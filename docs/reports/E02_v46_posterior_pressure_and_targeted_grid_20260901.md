# E02 v46 参数后验分布压力诊断与针对性网格实验报告

**日期**: 2026-09-01  
**优化对象**: `e02_formal_v46_page25_unified_20260901`（两季统一 PAGE=25）参数后验分布边界压迫、敏感性收缩与机理冲突诊断  
**产物目录**: `D:\Tomato_Cal\figture\e02_formal_v46_page25_unified_20260901`  
**实验结果数据**: `D:\Tomato_Cal\workspace\reports\e02_targeted_pressure_relief_grid_20260901/targeted_grid_scorecard.csv`  

---

## 1. 后验分布压力的 4 大核心聚集点

通过对 126 个遗传与环境参数的后验区间、收缩率及边界距离（Boundary Proximity Ratio）进行系统审计，后验分布压力主要集中在以下 4 个关键机理模块：

### 压力点 1：碳分配上界拉力与源库平衡 (`XFRT`, `SHLAG`, `SFDUR`)
- **受压参数**: `XFRT`（每日光合产物分配给果实的最大比例）被推挤至 0.910 上界附近（$p \ge 90\%$ 区间）；
- **机理矛盾**: 在多批次采收模式下，高产处理（W3N3/W2N3）需要极高的碳分配向果实流动，导致 `XFRT` 受到持续向上的拉力；但过高的 `XFRT` 会挤压茎干重（`SWAD`）与叶干重（`LWAD`）的积累。

### 压力点 2：适龄苗龄下的生育期热时间压缩 (`EM-FL`, `FL-SH`, `FL-SD`)
- **受压参数**: `EM-FL`（出苗至初花有效积温）从历史的 24.7 °C·d 下移至 21.7 °C·d 甚至更低；
- **机理矛盾**: 苗龄从 60 天缩短为 25 天后，模型在苗床中积累的预设热时间减少了 35 天，必须在定植后更快启动花芽分化与坐果以贴合田间第 1 次采收；若 `EM-FL` 过大，坐果推迟导致早期产量断档；若过小，株高营养生长期不足。

### 压力点 3：比叶面积（SLAVR）与冠层展开（LAID）的结构性挤压
- **受压参数**: `SLAVR = 189.15 cm²/g` 处于偏低水平（通常茄果类为 220–280 cm²/g）；
- **机理矛盾**: 模型中叶面积展开（`LAID`）相较于叶生物量（`LWAD`）偏小（叶片偏厚）。若单纯放大 `SLAVR`，在固定光合速率下会导致叶肉单位厚度光合稀释，反而压低整株干物质积累。

### 压力点 4：光合临界叶氮与根系吸氮通量 (`FNPGN2`, `LNREF`, `RTNO3`)
- **受压参数**: `FNPGN2`（最大光合所需临界叶氮，4.90%~5.20%）与 `LNREF`（参考叶氮，4.20%）处于上限附近；
- **机理矛盾**: 高氮处理对光合能力的拉动依赖高 `FNPGN2`，但若 `FNPGN2` 过高，低氮处理（N0/N1）的光合抑制会过于剧烈，破坏氮响应阶梯对比度。

---

## 2. 针对性网格实验设计与结果

针对上述 4 大压力点，构建了 113 个针对性组合网格实验：

### 网格关键发现与性能突破：
1. **源库与热时间解耦最优解（`EM-FL = 22.0`, `XFRT = 0.93`, `SHLAG = 18.0`）**：
   - **25SP 累积鲜产 NSE = 0.828**（$d = 0.965$）
   - **26SP 累积鲜产 NSE = 0.924**（$d = 0.980$）
   - **25SP 株高 CHTD NSE = 0.828**（RMSE 仅 0.20 m）
   - **26SP 株高 CHTD NSE = 0.933**（RMSE 仅 0.12 m）
   - **25SP 叶面积 LAID NSE = 0.457**（较基线显著改善）
   - **26SP 叶面积 LAID NSE = -0.391**（较原先的 -1.002 产生跨越式回升！）
2. **冠层与叶面积最优折中解（`EM-FL = 20.0`, `XFRT = 0.93`, `SHLAG = 18.0`）**：
   - **25SP 叶面积 LAID NSE 飙升至 0.596**，株高 NSE 保持在 0.818（25SP）和 0.944（26SP），全季叶面积展开极其饱满。

---

## 3. 释放压力后的最优参数组合推荐

```csv
FNPGN1,1.80
FNPGN2,4.90
LNREF,4.20
NSLOPE,0.25
XFRT,0.930
EM-FL,22.0
SHLAG,18.0
SLAVR,195.0
TRIFL,0.750
SIZLF,315.0
NSTFAC,0.70
RTNO3,0.024
RTNH4,0.033
NMOBMX,0.35
NVSMOB,0.80
SENRTE,2.50
```

---

## 4. 产物交付

- **后验压力诊断与网格响应综合图**: [`figture/e02_formal_v46_page25_unified_20260901/diagnostic_posterior_pressure_and_grid.png`](file:///D:/Tomato_Cal/figture/e02_formal_v46_page25_unified_20260901/diagnostic_posterior_pressure_and_grid.png)
- **网格实验完整评估表**: `workspace/reports/e02_targeted_pressure_relief_grid_20260901/targeted_grid_scorecard.csv`
