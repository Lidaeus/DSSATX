# CROPGRO 模板水分机制静态代码分析（系列文档索引）

- **分析基准**：官方仓库 DSSAT/dssat-csm-os `develop` 分支 `d6556cca`（v4.8.6.0）
- **分析分支**：`analysis/mesol2-layering`（worktree `/Users/lidaeus/Documents/NewDssat-analysis`）
- **分析日期**：2026-08-27
- **方法**：纯静态代码阅读；全部结论附 `文件:行号` 引用（v4.8.6.0 行号）
- **姊妹篇**：氮系列见 [../CROPGRO_N_MECHANISM/README.md](../CROPGRO_N_MECHANISM/README.md)；土壤分层与初始条件见 [../MESOL_SOIL_LAYERING_AND_IC_INITIALIZATION_20260827.zh-CN.md](../MESOL_SOIL_LAYERING_AND_IC_INITIALIZATION_20260827.zh-CN.md)

## 核心结论（一分钟版）

1. **水分模拟横跨三个模块**：土壤水（`Soil/SoilWater/WATBAL.for`，tipping-bucket）→ 土壤-植物-大气（`SPAM/`：PET 需求、逐层潜在根系吸水、实际吸水与蒸散）→ 植物侧（`Plant/CROPGRO/`：胁迫因子与生理响应）。
2. **水胁迫因子 SWFAC/TURFAC 在植物模块内计算**（`CROPGRO.for:684-702`），不是土壤或 SPAM 模块——源码注释明确 "These calcs replace the old SWFACS subroutine, stress factors now calculated as needed in PLANT routines"（`SPAM.for:392-394`）。二者都是**供需比型**：供给=潜在根系吸水 TRWUP（土壤侧算出），需求=潜在蒸腾 EOP。
3. **双阈值语义**：TURFAC（扩张胁迫）当 TRWUP/EOP < 物种参数 RWUEP1（典型 1.5）即触发——**扩张胁迫先于光合胁迫**；SWFAC（光合胁迫）只在 TRWUP < EOP 时才降。二者**当日计算、当日生效、无平滑**（与氮 NSTRES 的 2 日平均、CNSTRES 的 8 日平均形成鲜明对照）。
4. **SWFAC 直接乘进光合**（`PHOTO.for:195`，PG 的最后一个乘子）——这与氮形成根本对比（氮不直接乘 PG）。
5. **水分对生理的作用是双向的**：既有抑制（光合、扩张、花荚添加），也有**促进**（干旱促繁殖分配 TURXFR、轻度胁迫促单粒灌浆速率 TURADD、干旱加速根系深扎、旱后复水叶分配补偿 CUMTUR）。
6. **渍涝是独立通道**：SWEXF/SATFAC（根系氧亏）限制吸水、抑制并杀死根系、经 WSENP 影响物候；SATFAC 本身在 CROPGRO 中仅作诊断输出，生理效应全部通过根系与吸水间接实现。
7. **物候受水胁迫调制**：FSW(J)=1+(1−SWFAC)·WSENP(J)（生态型逐期参数，±1），发芽期另用苗床水分 SWFEM；叶龄推进直接乘 TURFAC（`PHENOL.for:469`）。

## 文档目录

| 编号 | 文件 | 内容 |
|---|---|---|
| 01 | [01_architecture_and_daily_sequence.zh-CN.md](01_architecture_and_daily_sequence.zh-CN.md) | 三模块架构、每日水分调用序列与状态-速率闭环 |
| 02 | [02_soil_water_movement.zh-CN.md](02_soil_water_movement.zh-CN.md) | 土壤水运移：雪、径流(SCS-CN)、入渗/饱和流(tipping-bucket)、毛管上升、水田与暗管 |
| 03 | [03_et_demand_and_root_uptake.zh-CN.md](03_et_demand_and_root_uptake.zh-CN.md) | 蒸散需求（PET 方法族/EOP/EOS/两阶段土壤蒸发）与根系吸水（ROOTWU/XTRACT） |
| 04 | [04_water_stress_factors.zh-CN.md](04_water_stress_factors.zh-CN.md) | **水胁迫机制核心**：SWFAC/TURFAC/SATFAC/FSW 的定义、阈值、平滑与判读 |
| 05 | [05_water_effects_on_physiology.zh-CN.md](05_water_effects_on_physiology.zh-CN.md) | 水胁迫对生理活动的作用点全图：光合/扩张/分配/生殖/衰老/根系/物候 |
| 06 | [06_mathematical_summary.zh-CN.md](06_mathematical_summary.zh-CN.md) | 数学建模总结：全方程清单、水平衡守恒、参数索引、水-氮机制对照 |

## 关键源码文件一览

| 文件 | 行数 | 在水分体系中的角色 |
|---|---|---|
| Soil/SoilWater/WATBAL.for | 691 | 土壤水模块驱动：日序列与积分 |
| Soil/SoilWater/WBSUBS.for | 620 | SNOWFALL、UP_FLOW（毛管上升）等子程序 |
| Soil/SoilWater/RNOFF.for | 155 | SCS-CN 型径流（含覆盖修正） |
| Soil/SoilWater/INFIL.for | 182 | 降雨/灌溉日入渗与排水（tipping-bucket） |
| Soil/SoilWater/SATFLO.for | 153 | 无雨日饱和再分配排水 |
| SPAM/SPAM.for | 680 | SPAM 驱动：PET→SOILEV→TRANS→XTRACT 序列 |
| SPAM/PET.for | 1544 | 7 种 EO 方法（PT 默认/FAO56/ASCE/动态 PM 等） |
| SPAM/ROOTWU.for | 166 | 逐层潜在根系吸水（Ritchie 指数模型）+ 渍涝 SWEXF |
| SPAM/TRANS.for | 386 | 潜在蒸腾 EOP（含 CO₂ 修正 TRATIO） |
| SPAM/SOILEV.for | 266 | Ritchie 两阶段土壤蒸发 |
| SPAM/SPSUBS.for (XTRACT) | — | 实际吸水分配：TRWU 与逐层 SWDELTX |
| Plant/CROPGRO/CROPGRO.for | 1866 | **SWFAC/TURFAC 计算（:684-702）** |
| Plant/CROPGRO/PHENOL.for | 648 | FSW 物候耦合、TURFAC 叶龄、SWFEM 发芽 |
| Plant/CROPGRO/ROOTS.for | 621 | SWDF/SWEXF/SATFAC、根系深扎与死亡 |
| Plant/CROPGRO/PHOTO.for | 496 | PG×SWFAC、R5 后 CUMSTR 累积胁迫 |
