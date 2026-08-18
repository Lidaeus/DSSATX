# Code Review：试验矩阵与三季 FileA/FileT 适配

> 日期：2026-07-26  
> 审查范围：2026-07-24 后的 P0-A～P0-E、E00/E01 试验矩阵实现；`data/user/ref/DSSAT文件` 中重整后的 2025 春、2025 秋和 2026 春 FileA/FileT、标准差 CSV 与生成脚本。  
> 审查方式：代码静态审查、原始工作簿结构复核、临时 input bundle 兼容性审计及自动测试；不修改原始数据、现有正式 bundle 或历史运行。  
> 测试：`134 passed in 41.44s`（P0、E00、E01、指标/残差、观测策略和 legacy 退役相关测试）。

## 1. 结论

P0 试验架构已具备执行后续 E01--E07 的基础：参数/边界/观测策略均可由 `experiment_spec` 钉扎，多季节全局状态已清除，原尺度指标和残差诊断已就绪，工程质量门能区分模型失败与高 Phi 成员。代码层面没有发现阻止下一阶段开发的 P0 回归。

三季新整理数据的数值结构总体合理：三季均有唯一的 `(TRNO, DATE)` FileT 行，累计 `CHFPW/CHPDT` 单调；25 秋和 26 春的完整 FileA/FileT 可以被当前只读审计器解析。但是，**它们尚不可直接替换正式率定 bundle**。原因不在 DSSAT 固定宽度格式，而在处理映射、标准差接入和观测定义尚未形成项目契约。

当前建议是：先完成本文第 4 节的三个 P0 数据适配门；此后再建立新的、不可覆盖历史的版本化 bundle。不要用新的 ref 输出直接覆盖 `data/user/experiments/XXQL*` 或修改既有 experiment spec 的哈希。

## 2. 已通过的内容

### 2.1 试验矩阵代码

| 审查项 | 结果 | 说明 |
|---|---|---|
| P0-A 单一权重/变换入口 | 通过 | 正式构建器经 `observation_policy` 处理；退役的 `improved` 路径被拒绝。 |
| P0-B experiment spec 与 frozen bounds | 通过 | 参数集、边界、观察策略和输入 manifest 均有 SHA-256 钉扎。 |
| P0-C 多季节状态隔离 | 通过 | `SeasonContext` 取代跨季节全局输入目录；连续构建测试通过。 |
| P0-D 原尺度指标/残差 | 通过 | RMSE、MAE、MBE、RRMSE、NRMSE、NSE、R²、MSE_s/MSE_u 与处理级残差诊断可复用。 |
| P0-E 工程门 | 通过 | 高 Phi 只分类为 `phi_outlier`；明确运行失败才判定工程失败；legacy mode 已拒绝。 |

### 2.2 新观测文件的基本结构

| 季节 | 新 FileA TRNO | 新 FileT 行 | CHPDT 事件行 | 只读 bundle 审计 |
|---|---:|---:|---:|---|
| 25SP | 1--14（14 个） | 205 | 154 | 与现有 FileX 不可直接对应，见 C1 |
| 25FA | 1--12（12 个） | 84 | 36 | 可解析；仅有既有土壤输入警告 |
| 26SP | 1--12（12 个） | 84 | 48 | 可解析；旧 FileX 肥料行次序错误阻断正式使用 |

三季新文件使用标准的 6 字符固定宽度与 `-99` 缺失值，并含有 `LAID`、`LWAD`、`SWAD`、`CHFPW`、`CHPDT`。这些是本项目可直接对应 DSSAT 输出的主要作物状态变量。`CHPDT` 仍是唯一正式采收 Phi 目标。

## 3. 发现及处置

### C1 [阻断] 25SP 的 14 个原始小区与 FileX 的 10 个处理不一致

新 25SP FileA/FileT 包含 TRNO `1--14`；目前所有可用的 `XXQL2501.TMX` 仅定义 TN `2,3,4,5,9,10,11,12,13,14`。因此 TRNO 1、6、7、8 没有相应的实际管理、初始条件与土壤条件，且 FileX 的 10 个处理不应被替换为 14 个未经定义的 DSSAT treatment。

**影响：** 25SP 新输出不能直接导入正式率定；若静默使用，会造成 FileT--FileX 处理错配或为四个小区虚构管理信息。

**处置：** 在用户确认前，适配器只能生成 `25SP_candidate` 审计包。推荐以现有实际 FileX 的 TN 集合为准，保留 `2,3,4,5,9,10,11,12,13,14`，并把 1、6、7、8 写入排除审计；若研究需要全部 14 个小区，则必须提供/确认含 14 个处理的实际 FileX 及 batch，而不是由代码推断。

### C2 [阻断] `*_observations.csv` 不是项目可直接消费的 PEST++ 不确定性契约

新 CSV 确实保存了 `sd`、`n_rep`、`sd_source`，但同时直接写入 `weight=1/sd`，并为 HWAM、CHFPW、HFPOW、HPODW 等都生成了观测。项目正式路径不会读取该 CSV；它从 FileT 生成观测后，再由唯一的 `observation_policy` 处理变换、sigma 和组预算。

直接把该 CSV 的权重复制进 PST 会产生三个问题：

1. CHPDT 正式 Phi 使用 `ln(y+1)`，原尺度 `sd` 不能直接作为 log 尺度的 sigma；需在适配器中以审计过的一阶 delta 近似或明确的重复级变换计算 `sigma_log`。
2. 正式 Phi 只允许 CHPDT；HWAM、HFPOW、HPODW、CHFPW 均不能因 CSV 中存在而自动激活。
3. PEST 权重还需遵守已冻结的组权重/观测数校正，不能与 `1/sigma` 再叠加成第二条权重路径。

**处置：** 保存原始标准差，但新增 `observation_uncertainty.csv`（原尺度事实表）和由 spec 调用的 `uncertainty_adapter`。adapter 仅向当前活跃目标提供 `raw_sigma`/`sigma_log`，随后仍由 `observation_policy` 生成唯一 PST weight。未完成该接入前，标准差 CSV 只能作为数据审计，不得称为“PEST++ 已读取”。

### C3 [高] 两个生成器和 Excel 指南定义相互冲突

- `generate_dssat_all_seasons.py` 输出精简的 9 列 FileT，且不生成 `*_observations.csv`；
- 实际输出由 `generate_dssat_v2.py` 生成，为 20 列参考 FileT 和标准差 CSV；
- `DSSAT_FileA_FileT_Excel操作指南.md` 仍指向前者，且写明旧的 HWAH/HWAHF/SNAD/LNAD 结构。

这会使后续协作者即使重跑同一目录，也可能得到不同文件和不同标准差结果。

**处置：** 以新的单一脚本（建议命名 `generate_three_season_observations.py`）为唯一生成入口；旧两个脚本和 Excel 指南标为 `superseded`，保留但不得在正式输入中调用。新 README 必须记录输入工作簿 SHA、脚本 SHA、运行参数和每季输出 SHA。

### C4 [高] 当前输出仍含用户要求不计算的 CNAM，且 HWAM 容易被误用

用户已明确“不必计算 HIAM、CNAM”。但 v2 在 25SP/25FA 的 FileA/FileT 和标准差 CSV 中仍生成 CNAM；它由茎/叶氮浓度与最近生物量日拼接而来，不是本轮需率定的直接观测。FileA 的 HWAM 又被设置为最后一次 CHPDT，尽管当前连续采收合同明确禁止 HWAM 进入正式 Phi 或正式指标。

**处置：** 新正式 adapter 默认：

- FileA `HIAM`、`CNAM` 均写 `-99`，不生成其不确定性记录；
- `HWAM` 也写 `-99`，连续采收产量只保留 FileT 的 CHPDT；
- `SNAM/LNAM`、`SNAD/LNAD` 仅在用户另行决定做植株氮过程验证时才建立独立、定义匹配的观测合同；本轮不随意混入。

这不会丢失源数据：氮和 FileA 汇总值仍在原始工作簿/审计表保留，但不会误导正式率定。

### C5 [高] 半果含水率用于反推干产量，但尚无可审计的日期匹配阈值

三季皆将半果/果实含水率转为 `DMFR = 1 - moisture`，并按“同小区最近日期”匹配采收。该方法可生成 CHPDT，但当前脚本没有将 `source_quality_date`、`match_days`、质量测定重复数和匹配状态写进最终产物，也未设置最大允许间隔。尤其 25SP 的 11 个采收事件中，每个小区最终只使用一个不同的 DMFR 值；它不足以支持果实含水率的时间动态结论。

**处置：** 新 adapter 需生成 `fruit_quality_match_audit.csv`，逐行记录采收日、质量测定日、间隔、DMFR、DMFR SD、保留/拒绝原因。超过预先设定窗口的记录不得静默匹配；可保留鲜重诊断，但 CHPDT 必须标为不可用于正式率定或由用户批准替代规则。PDMCD 暂不作为 PEST++ 目标，因为当前项目没有经审计的同定义 DSSAT 输出读取器。

### C6 [中] 土壤体积含水率不能塞入 FileA/FileT，尚未纳入项目输出链

三季原始表都有可用于土壤水分验证的数据：25SP 为 3 个日期、5 个深度层、14 小区；25FA 为一次 12 小区土样；26SP 为 4 个日期、12 小区、多个深度和重复。DSSAT 的相应状态是 `SoilWat.OUT` 的层体积含水量 `SW(L)`，而不是当前 FileA/FileT 的作物变量。

**处置（项目负责人已决定）：** 建立独立 `soil_water_observations.csv` 与 `soil_water_match_audit.csv`，字段至少为 `season_id,trno,date,depth_top_cm,depth_bottom_cm,theta_v,n_rep,sd,source_file`。完成“实测层--DSSAT SOIL.SOL 层”重叠加权映射、`SoilWat.OUT` 读取器和零/缺失审计后，将其以独立 `SOIL_WATER` 过程组进入遗传参数率定 Phi；每季第一次测量标记为 `initial_condition_only`，不进入 Phi，因为它已被写入 FileX 初始条件。不得伪装成 FileT 或与作物变量共享未审计的观测定义。土壤参数是否参与率定必须先通过单独预筛，不能因为土壤水分进入 Phi 就自动放开全部土壤参数。

### C7 [中] 26SP 的实际 FileX 仍需先完成肥料行顺序修复

用新 26SP FileA/FileT 与现有 bundle 做临时审计时，观测解析通过，但旧 FileX 触发 `FILEX_FACTOR_ROWS_NONCONTIGUOUS` 和 `FILEX_FACTOR_DATES_UNSORTED`（无机肥 SM2）。这与新观测数据无关，但会阻断正式 bundle。

**处置：** 在派生的 26SP actual-trial bundle 中执行已存在的“同一肥料水平连续且按日期排序”修复，并对 FileX 管理段做字节/语义审计；不得修改原始 source bundle。

## 4. 下一步执行计划

| 顺序 | 工作 | 负责人交付 | 前置/验收 |
|---|---|---|---|
| A0 | 冻结 25SP 处理集合 | 保留 `2,3,4,5,9,10,11,12,13,14`；排除 `1,6,7,8` 的 audit | 不重编号；不虚构 FileX 管理/初始条件 |
| A1 | 统一生成器 | 单一脚本、输入/输出哈希、弃用注记 | 同一输入重复运行字节一致；旧脚本不再作为入口 |
| A2 | 不确定性事实表与 adapter | raw SD、log sigma、适用变量、来源审计 | 单元测试验证 CHPDT log sigma；PST 无双权重 |
| A3 | 连续采收/质量审计 | `fruit_quality_match_audit.csv` | 所有 CHPDT 行具质量来源与间隔；最近匹配不设最大间隔，完整报告间隔分布 |
| A4 | 土壤水分过程 registry 与输出链 | 三季 `soil_water_observations.csv`、层映射、`PestSoilWat.OUT` | 不写入 FileT；首测排除；确定性 SoilWat smoke 后以独立过程组进 Phi |
| A5 | 版本化 bundle 导入 | 25SP/25FA/26SP 新 bundle、manifest、E00 receipt | 原 FileX/实测 IC/SA 保留；25FA/26SP TN1--12 映射显式记录 |
| A6 | 端到端 smoke | 每季 build-only + 20×1 IES | 仅 CHPDT 活跃；HWAM/CNAM/PDMCD/soil water 均不误入 Phi |

## 5. 本轮判定

- **P0/E01 架构：通过，可继续。**
- **25FA 新作物观测：可进入 adapter 开发。**
- **26SP 新作物观测：可进入 adapter 开发，但正式 bundle 前先修 FileX 肥料行。**
- **25SP 新作物观测：可按已冻结的 10 个 FileX treatment 创建候选 bundle；`1,6,7,8` 排除并审计。**
- **DMC：最近日期匹配且不设最大间隔；保留完整 audit。土壤 VWC：走独立、可追溯的 SoilWat 输出链，首测排除后进入 `SOIL_WATER` Phi 组。**
