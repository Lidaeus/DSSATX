# Tomato_Cal 文档索引与知识导航

> **最后更新**：2026-09-20  
> **设计原则**：单一事实源（Single Source of Truth），现行规范与归档资产严格隔离；机理问题与率定经验按模块系统归口，历史文档全量消费并可溯源。

---

## 1. 核心阅读顺序与知识入口

1. **系统开发与架构规范**：
   - [AGENTS.md](../AGENTS.md)：Codex / AI Agent 交互指引、双轨制图表契约、参数边界层级规范。
   - [开发者指南](DEVELOPER_GUIDE.md)：代码结构、实现约束、测试体系与工程规范。
   - [项目重构规划](../项目重构规划.md)：项目整体架构设计、模块拆分与重构规划。

2. **核心机理与参数率定知识库（每日开发与同行交流必读）**：
   - **[模块化分册知识库 (docs/knowledge_base/)](knowledge_base/README.md)**  
     *按 DSSAT 模块与工程问题全面分类的 10 册专著体系*：涵盖 CENTURY 碳氮循环、SOILWAT 水分水力学、PHENOL/TRANS 物候苗龄、PHOTO/VEGGR 冠层源库、养分平衡、PEST++ 反演工程、数据治理管道、同效异构解及 8 大矛盾裁决与 83 篇全景溯源。
   - **[DSSAT_CROPGRO_参数率定与机理问题分类知识库 (单篇速查典)](DSSAT_CROPGRO_参数率定与机理问题分类知识库.md)**  
     一站式机理与工程排错总典，紧凑速查 8 大矛盾真相与历史文档对账。
   - **[CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结 (2026-09-20)](reports/CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md)**  
     *最新全景知识圣经（455行，约5.4万字）*：覆盖数据管道重构、CENTURY SASC 控矿化、100cm SRGF 根系筑坝、TB1 物候基温跨季泛化、13 处理扩容与四大科学门禁、十大黄金准则 Ten Golden Rules 及排查树。

3. **操作指南与科研规范**：
   - [敏感性分析与率定用户指南](敏感性分析与率定用户指南.md)：Morris/Sobol 敏感性分析、PEST++ IES 率定及验证工作流。
   - [科研图表设计与开发计划](科研图表设计与开发计划.md)：Python 计算导出/R 渲染发表级图表规范。
   - [观测误差与权重设计规范](权重设计方案改进提案.md)：观测分组、权重倍率与似然函数构建规范。
   - [DSSAT 并行隔离与输入路径规范](DSSAT并行隔离与输入路径规范.md)：多 Agent 沙箱运行隔离机制。

4. **数据资产与试验背景**：
   - [试验背景与数据说明：温室茄子水氮试验](试验背景与数据说明_温室茄子水氮试验.md)：试验基地条件、处理设计与高阶分析。
   - [数据来源与配置规范手册](数据来源与配置规范手册_v1_20260808.md)：只读数据资产与输入包配置规范。
   - [目录与输入资产规范](目录与输入资产规范.md)：项目目录布局与不可变输入契约。

---

## 2. 现行权威规范与技术专题

| 文档分类 | 权威文档 | 核心职责与知识范畴 |
|:---|:---|:---|
| **分册知识库** | [模块化分册知识库 (docs/knowledge_base/)](knowledge_base/README.md) | 按 DSSAT 生理/土壤模块与反演工程分册系统阐述（全 10 册，含 8 大矛盾裁决与 83 篇全景溯源） |
| **机理知识库** | [DSSAT_CROPGRO_参数率定与机理问题分类知识库](DSSAT_CROPGRO_参数率定与机理问题分类知识库.md) | 按 DSSAT 模块（CENTURY/SOILWAT/PHENOL/PHOTO/NUPTAK）归纳经验，消解历史假说矛盾 |
| **最新经验总结** | [CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结](reports/CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md) | C15/C16 冠军解参数、十大黄金准则、数据治理与排查树 |
| **论文写作框架** | [温室茄子水氮多目标优化论文框架 (打磨稿)](reports/温室茄子水氮多目标优化论文框架_打磨稿_20260918.md) | SCI 论文结构、研究假设、核心图表配置与讨论主线 |
| **系统架构** | [开发者指南](DEVELOPER_GUIDE.md) | 软件工程架构、CLI 设计、测试套件与代码规范 |
| **并行安全** | [DSSAT 并行隔离与输入路径规范](DSSAT并行隔离与输入路径规范.md) | Manager-Agent 分布式沙箱、端口分配与文件防撞机制 |
| **权重反演** | [观测误差与权重设计规范](权重设计方案改进提案.md) | 目标函数 Phi 构建、方差膨胀防范与水氮响应保真 |
| **科研图表** | [科研图表设计与开发计划](科研图表设计与开发计划.md) | 双轨制图表流水线、89mm/183mm 出版级样式与数据契约 |
| **代码演进** | [变更记录 (CHANGELOG)](CHANGELOG.md) | 系统版本演进与重大里程碑时间线 |

---

## 3. 作物模型生理生态机制底层资料库

- **[CROPGRO 氮素动力学机制专题 (`docs/CROPGRO_N_MECHANISM/`)](CROPGRO_N_MECHANISM/README.md)**：
  - 01 氮循环架构与日序驱动
  - 02 土壤有机质矿化与固定（CENTURY / CERES 模块）
  - 03 作物吸氮与根系阻力动力学（NUPTAK）
  - 04 临界氮浓度稀释与氮素动员（MOBIL）
  - 05 氮胁迫因子对光合与发育的影响
  - 06 氮素淋洗动力学
  - 07 数学模型总结与公式全编
- **[CROPGRO 水分动力学机制专题 (`docs/CROPGRO_WATER_MECHANISM/`)](CROPGRO_WATER_MECHANISM/README.md)**：
  - 01 体系架构与日序运行
  - 02 土壤水运动与分层蓄积（SOILWAT）
  - 03 蒸腾需求与根系吸水动力学
  - 04 水分胁迫因子计算
  - 05 水分对作物生理过程的影响
  - 06 数学公式汇编
- **[DSSAT 基础知识与参数输出解析 (`docs/reference/background_knowledge/`)](reference/background_knowledge/Summary.md)**：
  - 番茄/茄子 CUL、ECO、SPE 品种及物种参数全解析
  - DSSAT 核心输出文件（`PlantGro.OUT`, `SoilWat.OUT`, `SoilNi.OUT` 等）字段解读

---

## 4. 历史归档资产库 (`docs/archive/`)

在项目历史迭代中沉淀的 100+ 篇探索报告、阶段性多臂试验记录及旧设计方案，已被全部移入归档库，完整保留 Git 提交历史供回溯：

- **归档索引主入口**：[docs/archive/README.md](archive/README.md)
- **最新集中归档明细（2026-09-20，共83篇）**：[ARCHIVE_MANIFEST_20260920.md](archive/ARCHIVE_MANIFEST_20260920.md)
- **早期归档明细（2026-07-29）**：[ARCHIVE_MANIFEST_20260729.md](archive/ARCHIVE_MANIFEST_20260729.md)

### 归档子目录指引：
1. **[dssat_modules/](archive/dssat_modules/)**：按 DSSAT 生理土壤模块分类的历史探索
   - `soil_organic_matter/`（CENTURY、SASC、SLNF假说消解报告）
   - `soil_water_hydraulics/`（SOILWAT、100cm 根系筑坝、蒸发抑制报告）
   - `crop_phenology/`（PAGE 苗龄对账、TB1 基温泛化试验）
   - `crop_growth_source_sink/`（光合碳分配、多批次采收动态）
   - `nitrogen_phosphorus_dynamics/`（氮响应多臂、T0P0 磷素补全验收报告）
2. **[calibration_methodology/](archive/calibration_methodology/)**：历史率定方案、目标适用边界与范式融合设计
3. **[data_pipeline/](archive/data_pipeline/)**：数据清洗、双地块剖面重构、气象文件更新方案
4. **[historical_runs/](archive/historical_runs/)**：
   - `e02_series/`（E02 v37~v52 多臂探索与候选版本 C01~C04）
   - `full_genetic_v1_v8/`（全量遗传参数 V1~V8_ref 演变过程与 C05 候选集）
5. **[sensitivity_analysis_historical/](archive/sensitivity_analysis_historical/)**：早期 Morris/Sobol 敏感性分析记录
6. **[reviews_and_governance/](archive/reviews_and_governance/)**：代码审查、重复剔除与资产核对报告
