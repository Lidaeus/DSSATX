# CROPGRO 模板氮素机制静态代码分析（系列文档索引）

- **分析基准**：官方仓库 DSSAT/dssat-csm-os `develop` 分支 `d6556cca`（v4.8.6.0）
- **分析分支**：`analysis/mesol2-layering`（worktree `/Users/lidaeus/Documents/NewDssat-analysis`）
- **分析日期**：2026-08-27
- **方法**：纯静态代码阅读；全部结论均附 `文件:行号` 引用（相对 `Plant/CROPGRO/`，行号为 v4.8.6.0）
- **适用范围**：CROPGRO 模板全部作物（大豆、花生、番茄、棉花等）；文档中以番茄（CROPGRO-Tomato，非豆科）为主线时单独注明

## 核心结论（一分钟版）

1. **CROPGRO 的氮素模拟是"供需驱动"的平衡体系**：每日先计算碳（PGAVL）与氮（NAVL）的可用量，再依次满足籽粒/荚壳与茎叶根的生长需求，剩余量存入储备或"泄漏"。
2. **氮胁迫因子 NSTRES 是供需比型**（`SUPPN/(NSTFAC×NDMNEW)`，含 2 日滑动平均），**不是** CERES 那种氮浓度型（NFAC）——这是两套模板的本质区别。
3. **光合作用不直接乘 NSTRES**：氮通过两条间接路径影响光合——(a) 叶片氮浓度 RNITP 经物种文件曲线 AGEFAC→AGEFCC 削弱冠层光合；(b) 氮限制组织生长造成碳过剩 PGLEFT，经 EXCESS 因子下调次日 PG。
4. **氮的植物内分配按"三浓度体系"运作**：最大浓度（PROLFI 等奢侈蛋白）、正常浓度（PROLFG）、最低浓度（PROLFF 等下限）；供氮在最大与最低之间时新组织以中间浓度生长（氮稀释），低于最低浓度时整体生长速率按 NAVL/NGRVGG 比例压缩（NRATIO）。
5. **氮动员（再利用）是主动机制**：亏缺时按阶段依赖速率 NMINEP 从叶片/茎/根/荚壳的可动员氮库（WNRxx = 组织氮 − 最低蛋白×结构干重）抽取，动员直接引发叶片衰老（LFSEN = SENRTE×NRUSLF/0.16）。
6. **生殖库对氮极度敏感**：花添加量 ∝ CNSTRES^0.5；结荚量受叶片氮浓度 RNITPD 限制；籽粒灌浆受 min(碳比, 氮比) 双重限制，且籽粒蛋白质/油脂/碳水化合物成分随供需比可塑（PODCOMP）。

## 文档目录

| 编号 | 文件 | 内容 |
|---|---|---|
| 01 | [01_daily_sequence.zh-CN.md](01_daily_sequence.zh-CN.md) | 架构总览与每日氮流调用序列（CROPGRO.for 驱动逐段剖析） |
| 02 | [02_n_uptake_supply.zh-CN.md](02_n_uptake_supply.zh-CN.md) | 根系吸收：NUPTAK.for 逐层土壤供氮与需求约束的数学模型 |
| 03 | [03_n_demand_and_mobilization.zh-CN.md](03_n_demand_and_mobilization.zh-CN.md) | 需氮量体系：DEMAND.for（新组织/老组织/繁殖器官）与 MOBIL.for 氮动员 |
| 04 | [04_n_stress_factor.zh-CN.md](04_n_stress_factor.zh-CN.md) | 氮胁迫机制核心：NSTRES/CNSTRES 的定义、平滑、阈值与判读 |
| 05 | [05_n_partitioning_in_plant.zh-CN.md](05_n_partitioning_in_plant.zh-CN.md) | 植株内氮分配：NAVL 级联、三浓度体系、储备库与物质守恒 |
| 06 | [06_n_effects_on_physiology.zh-CN.md](06_n_effects_on_physiology.zh-CN.md) | 氮胁迫对生理活动的作用点全图：光合/SLA/根冠比/株高/花荚/籽粒成分/衰老 |
| 07 | [07_mathematical_model_summary.zh-CN.md](07_mathematical_model_summary.zh-CN.md) | 数学建模总结：全方程清单、单位约定、守恒恒等式与参数索引 |

## 关键源码文件一览（Plant/CROPGRO/）

| 文件 | 行数 | 在氮体系中的角色 |
|---|---|---|
| CROPGRO.for | 1866 | 模块驱动；NAVL/PGAVL 日内级联的宿主 |
| DEMAND.for | 1365 | C/N 需求（NDMNEW/NDMOLD/NDMTOT/NMINEP）；SLA 的氮效应 |
| NUPTAK.for | 253 | 土壤硝态/铵态氮吸收（TRNU） |
| MOBIL.for | 107 | 氮动员量 NMINEA 及各器官分配（NRUSxx） |
| VEGGR.for | 618 | 营养分配 FRLF/FRRT/FRSTM；**NSTRES 计算**；NRATIO 生长压缩 |
| PODS.for | 1485 | 籽粒/荚壳生长与花荚添加的氮限制；PODCOMP 成分可塑性 |
| GROW.for | 1836 | 状态积分：各器官氮含量、PCNL/RNITP、可动员氮库 WNRxx |
| PHOTO.for | 496 | 叶片氮 RNITP → AGEFAC/AGEFCC → PG；EXCESS 反馈 |
| SENES.for | 345 | 氮动员引发的叶衰老（SENRTE） |
| CANOPY.for | 321 | 株高/株宽的氮因子（NHGT） |
| NFIX.for | 470 | 豆科固氮（番茄等非豆科不激活） |
| INCOMP.for | 362 | 组织合成成本 AGRLF 等（组成×呼吸代价） |

## 与本仓库其它文档的关系

- 土壤侧分层与初始条件机制见 [../MESOL_SOIL_LAYERING_AND_IC_INITIALIZATION_20260827.zh-CN.md](../MESOL_SOIL_LAYERING_AND_IC_INITIALIZATION_20260827.zh-CN.md)。
- 本系列只描述**官方 v4.8.6.0** 行为；主工作区 `feat-cropgro-n-uptake-*` 分支上的修改不在此列。
