# 02 · 根系吸收：NUPTAK 的土壤供氮数学模型

系列：[README](README.md) · 上一篇：[01 日序列](01_daily_sequence.zh-CN.md) · 下一篇：[03 需求与动员](03_n_demand_and_mobilization.zh-CN.md)

**代码基准**：v4.8.6.0，`Plant/CROPGRO/NUPTAK.for`（253 行，全文精读）

---

## 1. 模型定位

NUPTAK 把"作物需氮量"翻译为"各土壤层的 NO₃⁻/NH₄⁺ 实际吸收量"，输出当日总吸收 TRNU（g[N]/m²/d）及分层 UNO3(L)/UNH4(L)（kg[N]/ha，供土壤模块记账）。它是 CERES 吸收模型在 CROPGRO 中的移植（文件头注明 "adapted from CERES"），其特点是：

- **需求上限**：总吸收 ≤ 作物需氮量；
- **供给能力**：单层供给 ∝ 根长密度 × 水分因子 × 浓度饱和曲线 × 物种参数；
- **残留下限**：每层吸收后保留不低于 0.25 ppm NO₃⁻ / 0.5 ppm NH₄⁺。

## 2. 需求侧：ANDEM（`NUPTAK.for:118`）

```fortran
ANDEM = (NDMTOT - NDMSDR) * 10.0        ! kg[N]/ha
```

- `NDMTOT`：作物总需氮（g/m²，DEMAND.for:660 = 新组织 NDMNEW + 老组织复充 NDMOLD，见 03 篇）；
- `NDMSDR`：可由**动员氮**满足的籽粒需氮部分（DEMAND.for:361-365），先扣除以避免重复需求；
- `×10`：g/m² → kg/ha 换算。
- 若 ANDEM ≤ 1e-9 则当日完全不吸收（`:119`）。

## 3. 供给侧：单层潜在吸收（`NUPTAK.for:123-156`）

对每个根长密度 RLV(L) > 1e-6 cm/cm³ 的层：

### 3.1 浓度饱和因子（Michaelis-Menten 型指数曲线）

```
FNO3 = 1 − exp(−0.08 × NO3(L))        ! NO3(L) 单位 µg N/g 土 (ppm)
FNH4 = 1 − exp(−0.08 × NH4(L))
边界：F < 0.04 → 0（低浓度截断）；F > 1 → 1
```
（`NUPTAK.for:125-130`）——供给能力随浓度饱和，半饱和点约 8.66 ppm。

### 3.2 土壤水分因子 SMDFR（`NUPTAK.for:132-141`）

```
SW ≤ DUL:  SMDFR = (SW − LL)/(DUL − LL)          ! 干旱抑制
SW > DUL:  SMDFR = 1 − (SW − DUL)/(SAT − DUL)    ! 过湿（缺氧）抑制
下限:      SMDFR ≥ 0.1
```

### 3.3 根系吸收能力因子 RFAC（`NUPTAK.for:144`）

```fortran
RFAC = RLV(L) * SQRT(SMDFR) * DLAYR(L) * 100.0
```

- RLV 为**昨日** ROOTS 计算的根长密度（cm 根/cm³ 土，`ROOTS.for` 输出）；
- `×100`：cm³→ha 尺度的量纲换算（1 ha·cm 土 = 10⁸ cm³；RFAC 单位 (kg N/ha)/(mg N/cm 根)）；
- 2023 年棉花改造（`:142-143` 注释）：由 `SMDFR²` 改为 `√SMDFR`，弱化了水分胁迫对吸收的抑制——这是官方在 v4.8.5+ 引入的变化，做氮响应分析时需注意。

### 3.4 单层潜在吸收（`NUPTAK.for:150-154`）

```
RNO3U(L) = RFAC × FNO3 × RTNO3        ! kg[N]/ha
RNH4U(L) = RFAC × FNH4 × RTNH4
TRNU     = Σ_L (RNO3U + RNH4U)        ! 潜在总供给
```

`RTNO3`、`RTNH4` 为物种文件 `!*ROOT` 段第 4 行参数（`NUPTAK.for:66-77`），物理意义"mg N / cm 根"，是**作物间吸收能力差异的主要载体**（NO₃ 与 NH₄ 各一条，故 NO₃/NH₄ 偏好由参数隐式给出）。

## 4. 需求约束与残留下限（`NUPTAK.for:160-189`）

```fortran
IF (ANDEM > TRNU) ANDEM = TRNU    ! 供给不足时按供给走
NUF = ANDEM / TRNU                ! 缩放系数 ≤ 1
DO L: UNO3(L) = RNO3U(L) × NUF    ! 均匀缩放各层
      XMIN = 0.25 / KG2PPM(L)     ! 残留下限: 0.25 ppm NO3
      UNO3(L) = MIN(UNO3(L), SNO3(L) − XMIN)
      XMIN = 0.5  / KG2PPM(L)     ! 残留下限: 0.5 ppm NH4
      UNH4(L) = MIN(UNH4(L), SNH4(L) − XMIN)
TRNO3U = Σ UNO3 / 10；TRNH4U = Σ UNH4 / 10；TRNU = TRNO3U + TRNH4U   ! kg/ha → g/m²
```

其中 `SNO3(L) = NO3(L)/KG2PPM(L)`（`:112`）把 ppm 转回 kg/ha；KG2PPM(L) = 1/(BD·0.1·DLAYR)（见土壤侧文档的量纲推导）。

## 5. 数学模型总结

当日吸收的完整表达式（分层）：

```
UNO3(L) = min{ NUF · [RLV·√SMDFR·Δz·100] · [1−e^(−0.08·NO3)] · RTNO3 ,  NO3_kg/ha(L) − 0.25/KG2PPM }
NUF     = min{1, ANDEM / Σ_L 潜在供给}
ANDEM   = (NDMTOT − NDMSDR) × 10
```

**结构性质**：

1. **线性于根长**（无根间竞争/耗竭梯度），**饱和于浓度**，**受水分双向抑制**；
2. 各层按同一 NUF 等比缩放——不模拟新根先锋层的优先吸收；
3. 吸收量与土壤溶液运移（质流/扩散）无关，是纯容量型（capacity-based）模型；
4. 模型不含"当日再吸收上限"或温度函数——温度仅通过需求侧（NDMTOT 中的生长速率）间接影响吸收。

## 6. 与土壤模块的接口

- 输入 `NO3/NH4`（ppm）、`SW/LL/DUL/SAT`、`RLV` 均为**内部土壤分层网格**上的数组（见 [../MESOL_SOIL_LAYERING_AND_IC_INITIALIZATION_20260827.zh-CN.md](../MESOL_SOIL_LAYERING_AND_IC_INITIALIZATION_20260827.zh-CN.md)——内部网格由 MESOL=2 的 LYRSET2 决定，因此**土壤文件分层方式会改变吸收的层分布与数量级**：层数越多、浅层越细，Σ RLV·Δz 的加权和及分层残留截断行为越不同）。
- 输出 UNO3/UNH4 回传土壤无机氮模块（SOILNI）做差分扣减；TRNU 进入植物 NAVL 级联，吸收的碳代价 RSPNO3/RSPNH4 在 `CROPGRO.for:983-989` 扣除。

## 7. 常见分析要点（做氮响应曲线时的检查清单）

| 现象 | 机制出处 |
|---|---|
| 低氮处理下吸收∝根长 | `:144` RFAC 线性项 |
| 高氮处理下吸收不随 NO₃ 线性增长 | `:125-126` 指数饱和 |
| 干旱显著抑氮、复水恢复 | `:133-141` SMDFR（注意 √ 抑制为 2023 改动） |
| 需氮为 0 的日子（如满载后）完全不吸收 | `:118-119` |
| 深层氮利用取决于根系下扎 | RLV 由 ROOTS.for 的 RTDEP 逐日推进 |
