# 第四章：碳氮平衡与胁迫 (Carbon, Nitrogen & Stress)

如果说 `PlantGro.OUT` 告诉你"植物长成了什么样"，那么本章介绍的文件将告诉你"为什么长成这样"。深入理解碳氮平衡和胁迫因子，是诊断模型表现不佳（如产量低、早衰）的关键。

## 1. 光合作用与碳平衡 (`PlantC.OUT`)

该文件记录了碳的获取（光合）与消耗（呼吸）。

### 1.1 关键变量
*   **`PG` (Gross Photosynthesis)**: 日总光合量 (g[CH2O]/m²·d)。
    *   **诊断**: 如果 `PG` 突然下降，检查当天的太阳辐射 (`SRAD`) 或水分/氮素胁迫因子。
*   **`MAINR` (Maintenance Respiration)**: 维持呼吸消耗。
    *   **番茄/草莓**: 随着生物量 (`CWAD`) 的增加，`MAINR` 会显著上升。高温会加剧呼吸消耗，可能导致净光合 (`PG - MAINR`) 为负，即"入不敷出"。
*   **`GROWR` (Growth Respiration)**: 生长呼吸。
    *   与当天的生长速率成正比。
*   **`PGAVL` (Available Carbohydrate)**: 可用于生长的碳水化合物。
    *   `PGAVL = PG - MAINR - Cost_of_N_Fixation`。
    *   如果 `PGAVL` 长期偏低，果实会脱落 (`ABORT`) 或停止生长。

## 2. 氮素动态 (`PlantN.OUT`)

氮是限制番茄和草莓生长的最常见养分。

### 2.1 关键变量
*   **`CNAD` (Canopy N)**: 地上部总氮量 (kg[N]/ha)。
*   **`GNAD` (Grain N)**: 果实中的氮量。
*   **`LN%D` (Leaf N Percent)**: 叶片含氮率 (%)。
    *   **重要指标**: 每个作物都有临界氮浓度 (`Critical N`)。如果 `LN%D` 低于临界值，光合作用会受限。
    *   **早衰信号**: 在果实膨大期，如果根系吸氮不足，植物会从叶片中转运氮 (`Mobilization`) 到果实。如果 `LN%D` 下降过快，叶片会提前死亡。
*   **`NUPC` (N Uptake Cumulative)**: 累积根系吸氮量。

## 3. 胁迫因子 (Stress Factors)

DSSAT 使用 0.0 - 1.0 的因子来表示胁迫程度。
*   **1.0 = 无胁迫 (Optimal)**
*   **0.0 = 最大胁迫 (Dead/Stop)**
*   **注意**: 某些输出文件（如 `PlantGro.OUT` 的末尾列）可能记录的是 **1 - Stress** (即 0 代表无胁迫)，请务必查看表头说明或 `DATA.CDE`。**但在 `PlantN.OUT` 和 `PlantC.OUT` 以及内部变量中，通常遵循 0-1 (1为最佳) 的定义，或者是 Stress Factor (0-1, 1为最大胁迫)。**
    *   *修正*: 在 DSSAT 输出中，`WSGD`, `NSTD` 等通常代表 **Stress Level (0=No stress, 1=Max stress)**。而内部变量如 `SWFAC`, `TURFAC`, `NSTRES` 通常代表 **Reduction Factor (1=No stress, 0=Max stress)**。**阅读时务必小心区分！**

### 3.1 水分胁迫 (Water Stress) - `PlantGro.OUT` / `SoilWat.OUT`
*   **`WSGD` (Water Stress Growth)**: 影响细胞伸长（叶面积扩展）。
    *   轻微缺水首先抑制长叶 (`WSGD` > 0)，植物变矮小。
*   **`WSPD` (Water Stress Photo)**: 影响光合作用。
    *   严重缺水才会显著影响光合 (`WSPD` > 0)。气孔关闭。

### 3.2 氮胁迫 (Nitrogen Stress) - `PlantN.OUT`
*   **`NFAC` / `AGEFAC`**: 影响光合作用。缺氮导致叶绿素减少。
*   **`NSTRES`**: 影响细胞生长。

### 3.3 诊断案例
*   **案例**: 番茄果实很小，但叶子很绿。
    *   **检查**: `WSGD`。可能在坐果期遭遇了干旱，抑制了果实膨大，但没有严重到影响光合 (`WSPD` 低) 或引起叶片黄化 (`N` 充足)。
*   **案例**: 开花后叶片迅速变黄枯死。
    *   **检查**: `PlantN.OUT` 中的 `LN%D` 趋势。如果急剧下降，说明发生了严重的氮再移动 (N Remobilization)。这通常是库强过大（果实太多）或施肥不足导致的。

## 4. 小结

*   **碳 (`PlantC`)** 决定了"能长多少"。
*   **氮 (`PlantN`)** 决定了"能长多快"以及"叶片能活多久"。
*   **胁迫** 是限制上述过程的瓶颈。

在调试模型时，**不要只看产量**。如果产量不对，先看有没有水肥胁迫，再看光合和呼吸是否正常。
