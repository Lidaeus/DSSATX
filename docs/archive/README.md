# 已淘汰与历史归档文档库

本目录集中保存已完成、被替代或仅作为迁移输入的历史技术文档。所有文件均保留原始文件名与完整 Git 历史，供后续开发与同行交流追溯设计演变。

## 核心使用限制与警示

- **严禁直接复用**：不得直接复制归档文档中的参数取值范围、Top-K 列表、目标函数权重、运行规模或中间状态到新试验；
- **严禁作为入口**：不得把归档脚本或命令视为当前有效运行入口；
- **严禁作为科学结论**：不得引用已淘汰的阶段性假说（如 `SLNF` 调控矿化、W1 缺氮倒挂、`TB1` 低温拟合等）作为学术结论；
- **权威真理查阅**：所有关于机理机制、参数率定与工程准则的最新定论，必须直接查阅：
  - [DSSAT_CROPGRO_参数率定与机理问题分类知识库.md](../DSSAT_CROPGRO_参数率定与机理问题分类知识库.md)
  - [CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md](../reports/CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md)

## 归档目录结构分类

### 1. DSSAT 生理与土壤模块机理归档 (`dssat_modules/`)
- [dssat_modules/soil_organic_matter/](dssat_modules/soil_organic_matter/)：CENTURY SOM、SASC 惰性碳、SLNF 矿化调控假说与历史 N0 倒挂报告；
- [dssat_modules/soil_water_hydraulics/](dssat_modules/soil_water_hydraulics/)：SOILWAT 水分动力学、10L-B 微网格、100cm SRGF 根系筑坝、滴灌蒸发抑制 (Run 14)；
- [dssat_modules/crop_phenology/](dssat_modules/crop_phenology/)：TRANS 移栽、PAGE 苗龄 (22d) 对账、TB1 基温跨季泛化；
- [dssat_modules/crop_growth_source_sink/](dssat_modules/crop_growth_source_sink/)：PHOTO 光合、VEGGR 营养器官生长、单果灌浆与采收分配；
- [dssat_modules/nitrogen_phosphorus_dynamics/](dssat_modules/nitrogen_phosphorus_dynamics/)：NUPTAK 吸氮、MOBIL 动员、SENES 衰老脱落与 T0P0 磷素施肥补全。

### 2. 率定方法学与数据管道 (`calibration_methodology/`, `data_pipeline/`)
- [calibration_methodology/](calibration_methodology/)：PEST++ IES 反演算法配置、Sobol 初始集合、13 处理扩容与四大科学门禁；
- [data_pipeline/](data_pipeline/)：XXSL2501 与 XXSL2601 双地块独立剖面重构、26122 LAID 笔误纠偏、无机氮纯氮折算、TMT/TMA 数据链对账。

### 3. 历史运行与阶段性交接 (`historical_runs/`)
- [historical_runs/e02_series/](historical_runs/e02_series/)：E02 从头率定系列、v37~v52 多臂探索与阶段性候选集 C01~C04；
- [historical_runs/full_genetic_v1_v8/](historical_runs/full_genetic_v1_v8/)：全量主效遗传参数协同率定 V1~V8_ref 演变过程与验收报告。

### 4. 敏感性分析与质量审查 (`sensitivity_analysis_historical/`, `reviews_and_governance/`)
- [sensitivity_analysis_historical/](sensitivity_analysis_historical/)：2026年7-8月 Morris 与 Sobol 全局敏感性分析历史报告；
- [reviews_and_governance/](reviews_and_governance/)：代码静态审查、异常重复剔除与不可变资产审查备忘录。

### 5. 早期归档资产 (2026-07-29 以前)
- [completed_plans/](completed_plans/) / [designs/](designs/) / [handoffs/](handoffs/) / [paper_drafts/](paper_drafts/)：更早期的构想与草稿。

## 批次归档清单索引
- **2026-09-23 旧 bundle 合约归档**：[legacy_bundle_contracts_20260923/](data_pipeline/legacy_bundle_contracts_20260923/)；旧规格、设计、入口和测试仅供溯源。
- **2026-09-20 集中大归档（83 篇）**：[ARCHIVE_MANIFEST_20260920.md](ARCHIVE_MANIFEST_20260920.md)
- **2026-07-29 早期归档清单**：[ARCHIVE_MANIFEST_20260729.md](ARCHIVE_MANIFEST_20260729.md)

当前系统入口请返回 [主文档索引](../README.md)。
