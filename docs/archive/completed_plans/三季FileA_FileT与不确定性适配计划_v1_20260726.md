# 三季 FileA/FileT 与不确定性适配计划（v1）

> 归档状态：三季观测包已按后续修复版本重建；当前口径以版本化输入 manifest、观测注册表和 2026-07-29 决策记录为准。

**目的：** 将 `data/user/ref/DSSAT文件` 中重新整理的三季实测数据变成可追溯、可被本项目读取的版本化观测 bundle；同时保留果实含水率和土壤体积含水率的科学价值，但不把尚未定义同一模拟量的指标强行写入 FileA/FileT 或正式遗传参数 Phi。

> **2026-07-28 项目负责人纠正（优先于本文后续旧表述）**
>
> “采收部分只有 CHPDT 进入 Phi”是指鲜重不进入率定，而不是指其他作物观测全部退出率定。正式 E02 中，FileT 的累计干重 `CHPDT` 与单次干重 `HPODW` 均进入 Phi，二者使用一致的干重采收变换；累计鲜重 `CHFPW` 仅作诊断。可用的物候、冠层、生物量、株高和植株氮等观测正常进入率定。土壤水分继续进入 Phi，并按季节内观测数使用 `sqrt(phi_budget/n_obs)` 校正。

本文后续“仅 CHPDT”“LAID/LWAD/SWAD 仅诊断”等表述保留为 2026-07-26 版本的历史设计记录，但不再定义 E02_55 的当前执行合同。

## 1. 目标数据产品

每个季节在新目录 `data/user/experiments/<bundle_id>/` 中建立不可覆盖的正式候选 bundle，并在同一来源目录产生下列事实表：

| 产品 | 作用 | 是否可进入当前 Phi |
|---|---|---|
| `<EXCODE>.TMA` | 兼容 DSSAT 的 season-end 作物观测；HIAM/CNAM/HWAM 为 -99 | 否 |
| `<EXCODE>.TMT` | LAID、LWAD、SWAD、CHFPW、CHPDT 时间序列 | 仅 CHPDT |
| `observation_uncertainty.csv` | FileT 数值的原尺度 SD、重复数、来源、变换后 sigma | 仅经 adapter 的 CHPDT |
| `fruit_quality_match_audit.csv` | 每次采收与半果含水率/DMFR 的对应和间隔 | 否；支持 CHPDT 来源审计 |
| `soil_water_observations.csv` | 深度分层体积含水率及 SD | 是；仅排除每季首次测量，作为独立 `SOIL_WATER` 过程组进入 Phi |
| `input_manifest.json` | 文件 SHA、来源工作簿 SHA、生成器 SHA、处理映射、实际 FileX 保留证明 | 是（spec 钉扎） |

`FileA_values.csv`、`FileT_values.csv` 可作为人工核对副本，但不是权威不确定性来源；权威是文本 FileA/FileT 与对应 audit/uncertainty 表。

## 2. FileA/FileT 的固定字段

为兼容标准 TMGRO FileA/FileT 外形，同时避免连续采收模型的误用，使用完整参考列，但只填下列变量：

```text
FileA: TRNO PDAT ADAT MDAT HDAT HWAM LWAM SWAM LAIX HIAM CNAM
       填值: TRNO, HDAT, LWAM, SWAM, LAIX
       固定 -99: PDAT, ADAT, MDAT, HWAM, HIAM, CNAM

FileT: TRNO DATE L#SD LAID L#PA LWAD RWAD SWAD M#AD SLAD CHTD CWID
       CNAM SNAM LNAM HFPOW CHFPW HPODW CHPDT PDMCD
       填值: TRNO, DATE, LAID, LWAD, SWAD, CHFPW, CHPDT
       固定 -99: 其余列（含 CNAM/SNAM/LNAM、HFPOW/HPODW、PDMCD）
```

理由：CHPDT 和 CHFPW 是已定义、已被当前 `FreshWt.OUT` 直接读取的累计采收量；LAID/LWAD/SWAD 有 `PlantGro.OUT` 对应量。半果含水率仍用于构造 CHPDT，但 PDMCD 本身当前没有经审计的同定义读取器；增量采收变量、HWAM 和总植株氮也不满足本项目正式目标定义。

## 3. 不确定性适配

### 3.1 事实表 schema

每个可记录的实测值一行：

```text
season_id,excode,trno,date,variable,value,raw_sd,n_rep,sd_method,
source_workbook,source_sheet,source_row_rule,quality_flag
```

- `raw_sd` 是同小区重复的样本 SD；若重复不足，保留已有最小 CV/回退 CV 的 `sd_method`，绝不把其伪称为直接重复 SD。
- CHPDT 的 raw SD 采用增量鲜重与 DMFR 方差传播后再累积；同时保留 `incremental_raw_sd` 及其质量匹配来源，防止把累计事件误当独立重复。
- 该表不存 PEST weight。

### 3.2 PEST adapter

adapter 的输入是事实表和 experiment spec，输出为 builder 可审计的 observation sigma override：

1. 从 spec 筛选活跃变量（当前仅 CHPDT）。
2. 保留原尺度 `raw_sigma`；对 `ln(y+1)` 生成 `sigma_log = raw_sigma/(y+1)`，并记录 `sigma_transform=delta_ln1p`。若未来有重复级原始产量，优先在重复级先变换再计算 SD。
3. `observation_policy` 是唯一计算 PST `weight` 的地方；adapter 绝不自行写 `weight=1/sigma` 到 PST。
4. 仅在用户另行批准的诊断导出中输出 CHFPW、LAID、LWAD、SWAD 的不确定性；它们不因有 SD 而自动进入 Phi。

需加入单元测试：原尺度 CHPDT 的已知值/SD 变换、零值、缺失值、非活跃变量过滤、一次且仅一次的权重处理。

## 4. 半果含水率与干产量

半果含水率按 `DMFR = 1 - moisture_fraction` 使用，单位必须确认是 0--1 而非 0--100。每次采收需有：

```text
trno,harvest_date,quality_date,match_days,fresh_yield,fresh_sd,
dmfr,dmfr_sd,dry_increment,dry_increment_sd,chpdt,chpdt_sd,match_status
```

按项目负责人 2026-07-26 决定，半果含水率与采收事件一律采用**同小区最近日期**匹配，**不设最大间隔**。这不是对果实含水率稳定性的假设：每一行必须记录 `match_days`、`quality_date` 和 `match_status=nearest_unbounded`，并在质量审计和论文方法中报告间隔分布。若某小区没有任何可用质量记录，才拒绝构造该行 CHPDT。

特别说明：25SP 的质量观测频率明显低于采收频率。即使所有数据通过时间窗口，也只能支撑“以最近实测 DMFR 构建 CHPDT”，不能支撑果实含水率时序被模型准确模拟的结论。

## 5. 土壤体积含水率

土壤数据进入独立 registry，不进入 FileT。实施步骤：

1. 将 25SP 的 0--20、20--40、40--60、60--80、80--100 cm；25FA 的深度；26SP 的深度，统一为 `depth_top_cm/depth_bottom_cm`。
2. 对 `season × trno × date × depth` 计算均值、样本 SD、重复数，保留异常/缺失标记。
3. 读取 `SOIL.SOL` 的层边界，与实测层求厚度重叠权重；不能一对一匹配时输出 mapping audit，不进行静默最近层匹配。
4. 在确定性 DSSAT smoke 中读取 `SoilWat.OUT` 的 `SW(L)`，验证单位为体积含水率并按上述权重聚合。
5. 每个季节按日期排序后，首个可用的 `season × trno × depth` 土壤水分观测只作为 FileX 初始条件核验，标记 `initial_condition_only`，**不生成 PEST 观测**；其余日期的观测进入独立 `SOIL_WATER` 过程组。
6. 在确定性 smoke 中读取 `SoilWat.OUT` 的 `SW1D...SWnD`，以第 3 步的层重叠权重聚合成观测深度层；输出 `PestSoilWat.OUT` 和逐行 match audit。不得把体积含水率伪装为 FileT 作物变量。
7. `SOIL_WATER` 必须按组预算做观测数校正，不能因时间点和土层更多而压倒 CHPDT 或植株生长组；首版只允许一个清晰、可复算的组预算和一条由 `observation_policy` 生成的权重路径。

25FA 土壤表的日期需要从元数据/文件名 `20251002` 写为明确的 `2025-10-02`，并在 audit 标识为“单次土样日期推断”，而非无日期记录。

## 6. bundle 适配顺序

1. **冻结处理映射。** 25FA、26SP 采用已确认 TN1--TN12 ↔ plot1--12；25SP 只保留已有 FileX 可定义的 TN `2,3,4,5,9,10,11,12,13,14`，明确排除 `1,6,7,8`，并在 `treatment_exclusion_audit.csv` 记录“缺少实际 FileX 管理/初始条件定义”的原因。不得重编号，也不得虚构四个处理。
2. **修正 26SP 派生 FileX。** 只调整无机肥管理行次序，保留实测初始条件、土壤分析、水氮管理内容；输入审计必须通过。
3. **由唯一生成器生成作物观测与事实表。** 旧生成器不再写正式输出。
4. **运行 adapter 和 bundle importer。** 新 bundle 名含日期和 `actual_trial_calibration`，不覆盖现有 XXQL 输入目录。
5. **E00。** 对每个候选 bundle 运行 input/harvest/manifest audit，生成 SHA receipt。
6. **20×1 smoke。** 验证 FileT 日期、真实采收日--前移事件--虚拟末次事件链，且 PST 只有 CHPDT 活跃。
7. **土壤水分过程链 smoke。** 每季至少一次确定性运行；验证输出日期、处理、深度映射、首测排除、单位和缺失值处理。25FA 若唯一土样即为 FileX 初始条件，则该季没有可进入 Phi 的后续土壤水分观测，必须如实记录。
8. **用户批准。** 仅批准的 bundle 更新 E01/E02 以后 spec 的 manifest SHA。

## 7. 唯一需要项目负责人决定的事项

以下三项已由项目负责人于 2026-07-26 决定，无需重复确认：

1. 25SP 只使用现有 FileX 可定义的 10 个处理 `2,3,4,5,9,10,11,12,13,14`；排除 `1,6,7,8` 并审计。
2. 半果含水率按最近采收日匹配，不设最大间隔；必须审计日期间隔。
3. 土壤体积含水率进入遗传参数率定的 Phi；每个季节的第一次测量只核验 FileX 初始条件，不进入 Phi。

仍需在土壤参数预筛完成后，由项目负责人决定是否将任何土壤环境参数纳入正式参数集；具体候选、边界和反混淆规则见 `docs/土壤水分进入Phi与土壤参数预筛方案_v1_20260726.md`。
