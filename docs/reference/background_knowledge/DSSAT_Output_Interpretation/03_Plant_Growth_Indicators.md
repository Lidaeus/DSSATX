# 第三章：生长发育指标 (Plant Growth Indicators)

`PlantGro.OUT` 是 DSSAT 中最重要、信息量最大的输出文件之一。它记录了作物每天的生长状态、形态发育和生物量积累情况。对于番茄和草莓这种无限生长、连续结果的作物，深入理解这个文件是掌握模型行为的关键。

## 1. 文件结构概览

`PlantGro.OUT` 是一个文本文件，通常以头部信息开始，随后是按天记录的数据列。

*   **@YEAR DOY DAS DAP**: 时间索引。
    *   `DOY`: Day of Year (1-365/366)。
    *   `DAS`: Days After Start of simulation (模拟开始后的天数)。
    *   `DAP`: Days After Planting (播种/定植后的天数)。**这是农学分析最常用的时间轴**。

## 2. 关键变量详解 (番茄/草莓重点)

以下变量是分析番茄和草莓生长动态的核心指标：

### 2.1 发育阶段 (Phenology)
*   **`GSTD` (Growth Stage)**: 当前的生长阶段代码。
    *   虽然是数字，但在 `Overview.OUT` 中有对应的文本描述（如 Emergence, Flowering, First Fruit 等）。
    *   **监控点**: 检查开花 (`NR1`) 和果实成熟 (`NR7`) 的时间是否符合预期。
*   **`VSTAGE` (Vegetative Stage)**: 主茎节点数（叶龄）。
    *   **番茄**: 决定了株高和叶片的增加。如果模拟无限生长型番茄，该值应持续增加。
    *   **草莓**: 反映了冠层的发育程度。
*   **`RSTAGE` (Reproductive Stage)**: 生殖发育阶段。
    *   这通常是一个连续的数值，反映了从开花到成熟的进程。

### 2.2 叶面积与光合潜力 (Canopy Structure)
*   **`LAID` (Leaf Area Index)**: 叶面积指数 (m² leaf / m² ground)。
    *   **含义**: 决定了光拦截能力。
    *   **番茄**: 正常的温室番茄 LAI 可能达到 3.0-5.0。如果过低，产量受限；如果过高，可能徒长。
    *   **草莓**: LAI 相对较低。
*   **`CHTD` (Canopy Height)**: 冠层高度 (m)。
*   **`CWID` (Canopy Width)**: 冠层宽度 (m)。

### 2.3 生物量积累 (Biomass Accumulation)
这些变量单位通常是 **kg [dm]/ha** (干重，千克/公顷)。注：1000 kg/ha = 100 g/m²。

*   **`CWAD` (Tops Dry Weight)**: 地上部总生物量（不含根）。
    *   `CWAD = LWAD + SWAD + PWAD` (大致等于叶+茎+果)。
*   **`LWAD` (Leaf Weight)**: 叶片干重。
*   **`SWAD` (Stem Weight)**: 茎干重。
    *   对于番茄，这包括主茎和侧枝。
*   **`PWAD` (Pod Weight)**: **核心产量指标**。
    *   在 CROPGRO 中，"Pod" 泛指果实。对于番茄和草莓，这就是**果实干重**。
    *   **注意**: 对于多次收获的作物，这个值可能代表"当前挂果量"或"累积产量"，具体取决于模型配置（参见 `FreshWt.OUT` 章节）。

### 2.4 果实数量与大小 (Yield Components)
*   **`HIPD` (Pod Harvest Index)**: 果实指数 (`PWAD / CWAD`)。反映了光合产物向果实分配的效率。
*   **`P#AD` (Pod Number)**: 果实数量 (No./m²)。
    *   对于草莓，这对应果实个数。
*   **`GWAD` (Grain Weight)**: 种子重量。
    *   番茄/草莓主要关注果肉，种子重量占比很小 (`THRESH` 参数控制)，但在模型内部计算中很重要。

## 3. 如何利用 PlantGro.OUT 诊断模型

### 3.1 诊断：光合受阻？
*   观察 `LAID` 曲线。如果生长初期 `LAID` 增长极慢，可能是温度太低 (`TB` 设置不当) 或初始叶重 (`WTNEW`) 太小。
*   观察 `CWAD` 的斜率。斜率代表作物生长率 (CGR)。如果斜率突然变平，检查是否有水分胁迫 (`WSGD` 在 `PlantGro` 后面几列) 或氮胁迫。

### 3.2 诊断：源库不平衡？
*   **"疯长" (Vegetative growth only)**: `SWAD` (茎) 和 `LWAD` (叶) 持续飙升，但 `PWAD` (果) 始终为 0 或极低。
    *   原因：未达到开花积温，或分配系数 (`XFRUIT`) 设置错误，或夜温过高导致落花。
*   **"早衰" (Premature Senescence)**: 开花后 `LWAD` 迅速下降，`LAID` 崩溃。
    *   原因：果实负载过重 (`XFRUIT` 太高)，抽空了叶片的氮素 (`MOBIL` 过程)。

### 3.3 诊断：多次收获是否生效？
*   如果模拟的是连续采收番茄，观察 `PWAD`。
    *   **预期**: 呈锯齿状（生长-采摘-生长）。
    *   **异常**: 如果 `PWAD` 一直累积不减少，说明"自动收获"逻辑未触发。

## 4. 小结

`PlantGro.OUT` 是理解作物"每天在做什么"的窗口。对于番茄和草莓，重点关注 `LAID` (工厂大小)、`CWAD` (总产出) 和 `PWAD` (产品) 三者的动态关系。下一章我们将结合 `FreshWt.OUT` 专门讲解鲜重与收获数据。
