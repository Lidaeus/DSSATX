# E02 v46 best71：A–E 多臂试验复核与下一阶段交接（2026-08-31）

## 1. 目的与范围

本文件用于把 `e02_v46_best71_nitrogen_multiarm_20260831` 的多臂试验结果、可归因结论和下一阶段执行顺序交给协作者。所有结果均基于：

- 锚点参数：`workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/best_member_71_deterministic_20260831/best_member_71_params.csv`；
- 25SP/26SP 正式 bundle：`data/user/experiments/xxql2501_formal_scheme4_soil_20260830`、`data/user/experiments/xxql2601_formal_scheme4_soil_20260830`；
- 处理映射：`configs/runs/e02_mapping_25sp_w3w1_26sp_w2w1_n2n0_20260830.csv`；
- 25FA 不参与调参；本轮没有写回正式 bundle、观测表或 frozen bounds。

本文件是执行交接，不是新的正式率定批准。除非完成第 4 节的契约审计并得到明确批准，不得启动新的 200-realization 正式 IES。

## 2. 多臂试验已完成性与工程状态

运行状态文件：
`workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/orchestrator_status.json`

状态为 `calibration_completed_pending_all22_gate`，A–E 五个臂均完成，均为工程成功。所有本轮回归测试通过：

```text
python -m pytest tests/test_nitrogen_response_gate.py tests/test_soil_scalar_injection.py tests/test_t10_direct_harvest.py -q
11 passed
```

输入 bundle 的 soil 哈希在各臂一致，A–E 的设计均固定非本臂参数；因此臂间差异可以归因于本臂激活参数/权重，而不是水分、土壤或源库参数漂移。

## 3. A–E 结果与科学判定

权威汇总：
`workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/deterministic_candidate_metrics.csv`

| 臂 | 激活参数 | 25SP N MAE | 26SP N MAE | 26SP 相对 A 降幅 | 改善层数 | 26SP 末期鲜重 RRMSE | 25SP/26SP LAI NSE | 判定 |
|---|---|---:|---:|---:|---:|---:|---|---|
| A | FNPGN1、FNPGN2、RTNO3，λ=1 | 3673.7 | 3518.3 | 0% | 0 | 9.17% | -2.494/-2.516 | 基线 |
| B | A，λ=2 | 3673.7 | 3518.3 | 0% | 0 | 9.17% | -2.494/-2.516 | λ 加倍没有改变确定性结果 |
| C | RTNO3 | 3142.5 | 3277.2 | 6.85% | 6 | 9.21% | -2.469/-2.759 | 有方向但不足 |
| D | NMOBMX、NVSMOB、PROLFI、PRORTI、PROSTI | 3064.8 | 3387.1 | 3.73% | 6 | 8.89% | -2.778/-2.686 | 25SP 较好，26SP 不足 |
| E | FNPGN1、FNPGN2、LNREF、NSLOPE | 3291.8 | 3228.3 | 8.24% | 8 | 8.91% | -2.686/-2.687 | 相对最好但未达门槛 |

硬门槛结论：A–E 均不满足 `26SP N MAE 至少下降 30%`、`至少 3 个响应层改善`、且同时保持鲜重/LAI/W_RESPONSE 不退化的联合要求；因此不得构建 F 臂，不得据此扩大 N 参数边界或晋级 frozen bounds。

### 3.1 为什么提高 N_RESPONSE λ 没有作用

A/B 的确定性结果完全相同，说明 λ 只改变 PEST++ 残差惩罚，不改变固定锚点的 DSSAT 状态；它不能创造模型中不存在的 N 梯度。A 臂目标函数审计显示每个 realization 有 66 行 N_RESPONSE（25SP 36、26SP 30），来源为 `CHFPW`，按季节×水分层分别计算 SST，未发现误用干重或跨季节分母。

审计目录：
`workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/n_response_objective_audit_arm_a/`

### 3.2 关键机制证据

- 26SP 早期（DOY 075–146，扩展检查至 DOY 198）`PlantGro.OUT` 中 `NSTD`、`PST1A`、`PST2A` 全部为 0；氮胁迫通道在首期采收前没有被激活。
- 26SP 首期模拟鲜重范围仅约 255.3，而观测范围约 9963；26122 模拟 LAI 在 12 个处理间几乎恒定（约 0.330），观测 LAI 有明显处理差异。
- 26SP TMX 的水分、施氮总量及 mapping 已逐处理核对通过（12/12）；因此当前证据不支持把首期梯度缺失归因于处理映射或施肥记录缺失。
- PAVA 可行性审计显示，33 个季节×采收期×水分层中，25SP 有 13/18、26SP 有 6/15 个观测层违反 N1≤N2≤N3。单调拟合误差下界远小于当前模型 MAE（25SP 515.5 vs 5734.3；26SP 357.9 vs 5688.2），说明主要问题是模型没有生成足够 N 梯度，而非少数观测非单调噪声。

对应产物：

- `.../s0_6_early_nstress_audit/early_nstress_audit.json`
- `.../s0_6_early_nstress_audit_to198/early_nstress_audit.json`
- `.../s0_7_nresponse_feasibility/nresponse_feasibility_audit.json`
- `.../26sp_tmx_schedule_audit.csv`

## 4. 必须先解决的目标函数契约问题

发现正式 v46 配置与硬门槛定义不一致：

- `configs/runs/e02_formal_v46_step20_custom26sp_20260831_200x4.json` 的 N_RESPONSE 为 `N3_minus_N0_within_same_water`，`levels=["N3"]`；
- `src/reporting/nitrogen_response_gate.py` 的硬门槛函数 `mean_n2_n1_minus_n0_gate()` 明确计算并平均 `N2−N0` 与 `N1−N0`，有意排除 N3；
- `configs/runs/e02_from_scratch_objective_contract_20260826.csv` 的 NRESPM 备注仍写成 N3−N0；WRESPM 备注也仍是旧的“25SP/26SP W3−W1”文字，需与实际 design JSON 核对后再更新说明。

这不是 A–E 工程失败，但会造成“率定优化的目标”和“晋级验收的目标”不完全同一。协作者下一步必须先做只读契约审计，给出：

1. 每个正式/局部 design JSON 的 N_RESPONSE levels、contrast、source_variable、SST scope、λ；
2. gate 实际使用的 N1/N2 对比、季节/水分分层和鲜重来源；
3. contract CSV 备注与实现的差异；
4. 一个明确的候选方案：建议正式 N_RESPONSE 至少包含 N1、N2（如保留 N3，须说明它是附加诊断还是优化目标），并使 gate 与 objective 使用同一组响应定义；
5. 修改前后的 diff、测试和 deterministic 对照。未经审核不得直接覆盖现有正式 JSON。

## 5. 下一阶段执行顺序（交给协作者）

### P0：目标函数契约审计（只读）

建议新增脚本：
`tools/analysis/audit_v46_n_objective_contract_20260831.py`

输入为正式 v46 JSON、A–E 五个 design JSON、目标合同 CSV、`nitrogen_response_gate.py`。输出到：
`workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_9_objective_contract_audit/`

必须输出 `audit.json`、`objective_rows.csv`、`gate_definition.csv`，并标记 `contract_consistent`。不得改动正式 bundle 或观测。

### P1：首期状态/事件溯源（优先于任何参数扩界）

按以下顺序核对 26SP 每个处理：

1. 播种/移栽日期、首期采收日期、MI/MF、首期观测日期；
2. HNO1 的 `CHFPW` 是否是实际首期采收，是否被虚拟收获事件或日期截断；
3. 首期前 `PlantGro.OUT` 的 LAI/LWAD/SWAD/果数/果重/成熟度；
4. 逐日施肥—吸收—土壤无机氮—`NSTD/PST1A/PST2A`；
5. 初始植株状态与原始记录的对应关系。

当前 S0-4 原始 Excel 审计没有发现可授权的处理级 PLWT、PAGE、移栽苗面积/密度或缺株记录，不能自行构造 treatment-specific 初始状态。如果获得新原始证据，必须另建 scratch 对照并保存来源、哈希和授权说明。

### P2：只做一个机制假设的确定性对照

在 P0/P1 有证据后，只允许一次改一个假设，建议候选为：

- D0：best71 当前输入基线；
- D1：首期事件解释（实际采收 vs 虚拟采收），只改事件语义；
- D2：有原始证据时的处理级初始植株状态；
- D3：有逐日证据时的施肥—吸收时序；
- D4：若 P0 确认目标定义调整，只改 N_RESPONSE levels/contrast，不同时放开参数。

每个对照必须保留 22 个春季处理，并报告首期模拟/观测范围、N3−N0、N2−N0、N1−N0、26SP N MAE、鲜重末期 RRMSE、LAI、W_RESPONSE。不得用低 FAMN、虚拟观测或人为填补缺测来制造赢家。

### P3：局部 IES 的准入条件

只有某个单一机制对照同时扩大首期处理 spread、激活可观测 N 通道，并且不破坏鲜重尺度/LAI/W_RESPONSE，才允许设计局部 IES。局部 IES 仍应：

- 固定 best71 水分、土壤、源库和晚期参数；
- 只激活经剖面证明可识别的 1–5 个 N 参数；
- 60 realizations、`noptmax=3`、6 agents；
- 不重新开放 v37/v46 全体参数，不直接扩展 frozen bounds。

晋级仍使用硬门槛：25SP 末次 N3−N0 为正；26SP N1/N2 响应平均绝对误差相对基线下降至少 30%；至少 3 个独立响应层改善；鲜重尺度、LAI、W_RESPONSE 不明显退化。

### P4：停止规则

若 P1 无法找到可授权的首期状态/事件证据，或 D1–D4 在不改变权威输入的条件下仍不能恢复首期 N 梯度，则停止继续扩展 N 参数和提高 N_RESPONSE 权重，转入论文中的“早期状态/观测事件结构限制了 N 响应可识别性”限制讨论。此时可以做敏感性/不确定性展示，但不能把未通过 gate 的成员称为科学赢家。

## 6. 当前不得执行的事项

1. 不得构建 F 臂或新的正式 200-realization IES；
2. 不得把 `FAMN=0.1` 阶梯结果写回 26SP 正式 TMX；
3. 不得把 `PLWT=7` 或任何 PAGE/PLWT 反事实值写入正式 bundle；
4. 不得把 `NSTFAC` 扩至 1.0 的无效剖面当作参数边界依据；
5. 不得把 26180 缺失 LAI 填成有效观测；
6. 不得仅凭总 Phi 或 λ 加倍结果晋级。

## 7. 交接交付清单

协作者完成下一阶段后，须将以下文件放入本报告目录或其子目录：

- P0 `s0_9_objective_contract_audit/audit.json`、diff 与测试日志；
- P1 首期事件/状态/施肥逐处理溯源表；
- P2 每个确定性对照的 manifest、输入哈希、22 处理指标和失败原因；
- 若获准做 P3：run manifest、IES quality、三类确定性候选、逐条 gate 结果；
- 更新本文件第 8 节执行记录，写明命令、时间、输入 bundle SHA-256、是否改写任何正式文件。

## 8. 执行记录

- 2026-08-31：A–E 五臂完成，工程成功；无臂同时满足科学晋级门槛。
- 2026-08-31：完成 N_RESPONSE 行数/鲜重来源/SST 分层审计；未发现干重误配或跨季节分母。
- 2026-08-31：完成首期早期氮胁迫、N 供应阶梯、NSTFAC 上限、PLWT=7 反事实和 PAVA 可行性诊断；均未形成可写回正式输入的证据。
- 2026-08-31：正式下一步冻结为 P0 目标函数契约审计 → P1 首期事件/状态溯源 → P2 单假设确定性对照；在此之前不启动新的正式率定。

### 8.1 P0 契约审计已执行

已新增并运行只读脚本：

`D:/Tomato_Cal/tools/analysis/audit_v46_n_objective_contract_20260831.py`

命令：

```text
python tools/analysis/audit_v46_n_objective_contract_20260831.py --out-dir workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_9_objective_contract_audit
```

输出：

- `s0_9_objective_contract_audit/audit.json`
- `s0_9_objective_contract_audit/objective_contract_rows.csv`

审计结果为 `contract_consistent=false`，具体原因已被机器复核：正式 v46 的 N_RESPONSE 仍为 `levels=["N3"]`，而硬门槛使用 `N1/N2`；同时合同 CSV 的 WRESPM 备注仍写“26SP W3 minus W1”，正式设计实际为 26SP W2−W1。脚本确认正式 N 来源为 `CHFPW`、SST 为 `season_x_response_stratum`，因此问题是契约不一致，不是鲜重来源或 SST 实现错误。正式 JSON 尚未修改。

### 8.2 FileA/FileT 只读审计补充

对 25SP、26SP 正式 bundle 运行了现有观测审计：

```text
python -m src.calibration.audit_observations --input-dir data/user/experiments/xxql2601_formal_scheme4_soil_20260830 --out-dir workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_10_26sp_observation_audit
python -m src.calibration.audit_observations --input-dir data/user/experiments/xxql2501_formal_scheme4_soil_20260830 --out-dir workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_10_25sp_observation_audit
```

报告显示 26SP 有 60 个 `CHFPW`、60 个 `CHPDT` 收获事件，FileT 的固定宽度字段按正确六字符列读取；首期收获行的 `CHFPW` 是累计鲜重，`HFPOW` 缺测，不存在“把 10720 读成 HFPOW、把 592 读成 CHFPW”的列错位。审计返回非零主要来自已知的 MESOL=2 IC 测量深度与 7 层 SOIL 层底不重合，以及少数深层 SH2O 越界；这些必须按 `mesol2_ic_mapping_audit.json` 的规则继续溯源，不能把它们误判为 N_RESPONSE 代码错误，也不能静默重写 TMX。

### 8.3 P1 原始证据审计已执行

已完成 26SP 原始生长/产量/质量工作簿、正式 TMT/TMA/TMX 的只读核对，输出目录为：

`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_4_raw_initial_state_evidence`

结论：原始资料中没有可授权写入正式 bundle 的处理级 `PLWT`、`PAGE`、移栽植株质量/面积/密度或缺株字段；正式 TMT 的首期采收日期与观测日期一致，`CHFPW` 为累计鲜重，未发现事件日期偏移或字段错位。当前模型首期 26SP 的 LAI/LWAD/SWAD/CHTD 几乎为零，而首期观测鲜重已经达到处理间明显不同的水平，因此首要矛盾仍是首期状态/事件信息缺失与模型初始化可识别性不足，而不是继续放宽 N 参数即可解决。

协作者下一步必须先提交逐处理 P1 溯源表（字段、来源文件、原始单元、哈希、是否可写回），再决定是否运行 D1–D4。没有新原始证据时，只允许运行 D0 基线和不改权威输入的诊断性对照；不得将反事实 `FAMN`、`PLWT`、`PAGE` 或虚拟观测写入正式 TMX/TMT/TMA。

### 8.4 目标函数对齐草案（仅供审核）

P0 审计发现正式 v46 的 N_RESPONSE 只约束 `N3−N0`，而科学 gate 使用 `N1−N0` 与 `N2−N0` 均值；两者在新一轮正式率定前必须由项目负责人明确统一。建议若批准一次局部验证，统一采用同水分、同季节的 `CHFPW` 响应，分别计算 N1/N2（必要时再报告 N3）并按“季节×水分层”单独计算 SST，λ 暂保持 1，避免用提高权重掩盖首期状态缺陷。该建议不改变当前正式 JSON，需在 P1/P2 证据后单独形成版本化配置与审计记录。
