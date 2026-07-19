# DSSAT 输出文件解读手册大纲 (番茄与草莓)

本手册旨在帮助 DSSAT 初学者深入理解模型输出文件的结构、含义及应用，特别针对番茄 (Tomato) 和草莓 (Strawberry) 这类园艺作物。

## 1. 入门指南 (Getting Started)
*   DSSAT 输出文件命名规则与格式 (.OUT)
*   如何启用/禁用特定的输出文件 (Control File)
*   常用的查看工具 (Text editors, Excel, GBuild)

## 2. 核心概览与总结文件 (Overview & Summary)
*   **Overview.OUT**: 模拟运行的"体检报告"。包含输入回显、关键事件日期、最终产量及胁迫摘要。
*   **Summary.OUT**: 批量运行时的汇总表。一行代表一次模拟，适合多处理比较。
*   **Evaluate.OUT**: 模拟值与实测值的对比分析（如果提供了 FileA/FileT）。

## 3. 生长发育指标 (Plant Growth)
*   **PlantGro.OUT**: 每日生长动态的核心文件。
    *   关键变量：`LAID` (叶面积指数), `CWAD` (地上部生物量), `GWAD`/`PODWT` (果实干重), `VSTAGE` (叶龄), `RSTAGE` (发育阶段)。
    *   **番茄/草莓特有**: 重点关注果实发育 (`PODNO`, `SEEDNO`) 和生物量分配。
*   **FreshWt.OUT** (针对番茄/草莓): 鲜重输出，包含多次收获记录。
    *   关键变量：`FWAD` (鲜果重), `CHNUM` (累积收获次数)。

## 4. 碳氮平衡与胁迫 (Carbon, Nitrogen & Stress)
*   **PlantN.OUT**: 植株氮素动态。
    *   关键变量：`CNAD` (冠层氮), `GNAD` (果实氮), `NFAC` (氮亏缺因子)。
*   **PlantC.OUT**: 光合作用与呼吸消耗。
    *   关键变量：`PG` (总光合), `MAINR` (维持呼吸), `GROWR` (生长呼吸)。
*   **胁迫因子解读**:
    *   水分胁迫 (`TURFAC`, `SWFAC`)
    *   氮胁迫 (`NSTRES`, `AGEFAC`)
    *   温度胁迫 (影响光合与物候)

## 5. 土壤环境与水肥管理 (Soil & Management)
*   **SoilWat.OUT**: 土壤水分动态。
    *   关键变量：`SW(L)` (各层含水量), `ES` (土面蒸发), `EP` (植物蒸腾)。
*   **SoilNi.OUT**: 土壤无机氮动态。
    *   关键变量：`NI(L)` (硝态氮), `NH(L)` (铵态氮), `NUPC` (累积吸氮)。
*   **MgmtOps.OUT** / **MgmtEvent.OUT**: 管理操作记录（灌溉、施肥、收获）。

## 6. 进阶应用：如何利用输出进行模型校准
*   基于 `PlantGro.OUT` 调整光合参数 (`LFMAX`)。
*   基于 `Evaluate.OUT` 评估模拟精度 (RMSE, d-stat)。
*   针对多次收获作物的特殊检查点 (番茄/草莓)。

---

**执行计划**:
我们将从 **章节 3: 生长发育指标** 开始详细编写，因为这是理解作物模型最直观、最重要的部分，特别是对于关注产量的用户。
