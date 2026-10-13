# E02 v46 best71：S0-3 机制对照结果与后续执行单（2026-08-31）

## 1. 目的与不可变约束

本轮用于解释 26SP 首次采收前“模拟处理间状态完全塌缩、而观测存在明显梯度”的来源。所有试验均以

`workspace/runs/e02_formal_v46_step20_custom26sp_20260831_200x4/best_member_71_deterministic_20260831/best_member_71_params.csv`

为唯一参数锚点；正式 25SP/26SP bundle、TMT 观测、frozen bounds 均未改写。每个案例先复制 bundle 到独立 scratch 目录，再修改 TMX，故结果可删除、可重放。

执行脚本：

`tools/analysis/run_v46_s0_3_initial_state_mechanisms_20260831.py`

结果目录：

`workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_3_initial_state_mechanisms/`

核心汇总：`s0_3_scorecard.csv`。每个案例还保留两季 `PestTmtGrow.OUT`、`PestHarvest.OUT` 和确定性比较表。

## 2. S0-3A：事件定义复核

S0-2 已逐处理将 26SP HNO1 的 `.TMT` 观测日期与 `PestHarvest.OUT` 对齐：模拟和观测均为 **26146**，12/12 处理无日期错位。HNO1 不是被虚拟收获事件截断的结果，因此不应通过改变收获日期或成熟度解释首期处理差异。

## 3. S0-3B：统一初始植株状态对照

在两季 TMX 的共同种植行中，仅改变固定宽度字段 `PLWT` 或 `PAGE`；没有创建处理级初始状态，也没有将状态值写入遗传参数。

| 案例 | 改动 | 26SP 26122 模拟 LAI 范围 | 26SP HNO1 鲜重范围 | 25SP 终期鲜重 RRMSE | 26SP 终期鲜重 RRMSE | 26SP 累积鲜重 NSE | 26SP LAI NSE | 26SP N 响应 MAE |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| S0-3A | 基线 PLWT=9.4/PAGE=24 | 0.000 | 255.3 | 14.90% | 9.19% | 0.927 | -2.465 | 5714.1 |
| PLWT=5 | 共同 PLWT=5 | 0.000 | 221.8 | 39.67% | 13.26% | 0.842 | -1.343 | 7021.5 |
| PLWT=12 | 共同 PLWT=12 | 0.001 | 335.6 | 8.96% | 8.72% | 0.938 | -3.160 | 5165.8 |
| PAGE=12 | 共同 PAGE=12 | 0.000 | 36.9 | 67.26% | 67.26% | -1.240 | 0.336 | 7559.3 |
| PAGE=60 | 共同 PAGE=60 | 0.000 | 53.8 | 29.43% | 29.43% | 0.730 | 0.623 | 7844.8 |
| PLWT=12,PAGE=12 | 同时改变 | 0.000 | 47.4 | 61.76% | 61.76% | -0.952 | 0.476 | 7597.2 |

解释：共同 PLWT 只改变总体量级，不能制造处理间差异；26122 模拟 LAI 仍为 0（或仅 0.001 的数值舍入差），而观测 LAI 范围为 0.242。PLWT=12 对终期尺度和 N 响应 MAE 有小幅改善，但 LAI 变差且首期处理 spread 仍塌缩，不能晋级为正式输入。PAGE=12/60 造成明显尺度/产量退化，直接淘汰。

## 4. S0-3C：首期前施氮时序对照

保持每个处理的总施氮量不变，只将种植后、首期采收前的施肥日期整体平移 −3 或 +3 天；种植前施肥行不移动，以避免 DSSAT 的 “first fertilizer application prior to start” 输入错误。

| 案例 | 25SP 终期 RRMSE | 26SP 终期 RRMSE | 26SP N 响应 MAE | 26SP LAI NSE | 结论 |
|---|---:|---:|---:|---:|---|
| 基线 | 14.900% | 9.191% | 5714.1 | -2.465 | — |
| −3 d | 14.895% | 9.190% | 5713.6 | -2.465 | 数值噪声级变化 |
| +3 d | 14.906% | 9.193% | 5714.9 | -2.471 | 数值噪声级变化 |

因此，首期差异缺口不是由小范围施肥日期平移造成；不得据此放宽吸收/动员参数或提高 N_RESPONSE 权重。

## 5. S0-3 判定

1. S0-3A **通过**：事件日期与观测一致，排除日期配对错误。
2. S0-3B **不通过机制修复门槛**：共同 PLWT/PAGE 无法扩大首期处理 spread；极端 PAGE 明显破坏产量尺度。不得把共同值写入正式 bundle 或 frozen bounds。
3. S0-3C **不通过机制修复门槛**：±3 d 对 N 响应和尺度影响可忽略。
4. 未发现可在当前“共同种植行 + 官方 DSSAT”假设下恢复 26122 处理差异的单一机制；**不启动 G1/G2 局部 IES，不建立 F 臂，不扩展 N 参数边界**。

## 6. 交给协作者的下一步（按顺序）

### S0-4：只读原始证据核查（不得先改模型）

1. 核对 26SP 原始田间记录是否存在处理级移栽苗龄、移栽苗干重/叶面积、定植密度或缺株记录；若无原始证据，明确标记为不可识别，不得自行构造处理级 PLWT/PAGE。
2. 将 26075 种植日期、26122 状态观测、26146 HNO1 采收事件和首期前施肥—吸收记录做成逐处理溯源表；TMT 仍是产量/状态观测的唯一权威来源，禁止用 `FileT_values.csv` 替代。
3. 复核 `input_manifest.json` 与 bundle SHA-256，确认 S0-3 期间正式 bundle 未发生字节变化。

### S0-5：若且仅若有原始证据，做一个处理级初始状态反事实

在独立 scratch bundle 中，以原始记录支持的处理级初始状态为输入，固定 best71 其余参数，重跑完整 22 处理；必须同时报告 26122 状态范围、HNO1 鲜重范围、N3−N0/N2−N0/N1−N0、两季终期鲜重 RRMSE、累积鲜重 NSE、LAI NSE 和 W_RESPONSE。若没有原始证据，跳过 S0-5，不得用拟合值反推初始状态。

### 局部 IES 的准入（当前仍未满足）

只有某个 S0-5 反事实在不牺牲两季鲜重尺度、LAI 和 W_RESPONSE 的情况下显著扩大首期处理范围，才允许提交 G1/G2：60 realizations、`noptmax=3`、6 agents，固定 best71 的水分/土壤/源库/晚期参数，只激活 1–3 个经剖面证明可识别的 N 参数。G1/G2 仍须达到旧门槛：26SP N 平均绝对误差相对 A 臂下降 ≥30%、至少 3 个响应层改善、25SP 末次 N3−N0 为正、鲜重终期 RRMSE/LAI/W_RESPONSE 不明显退化。

若 S0-4 没有原始证据，或 S0-5 仍无法恢复 spread，应停止扩边和正式率定，把结论沉淀为“首期处理差异受输入/观测结构限制，在当前 DSSAT 场景下不可由后期 N 参数识别”，转入结果与论文方法章节。

## 7. S0-4 原始证据核查结果（2026-08-31）

只读审计脚本：`tools/analysis/audit_v46_s0_4_raw_initial_state_evidence_20260831.py`。

审计了 26SP 原始参考目录中的 4 个 Excel 工作簿（生长、产量、品质、土壤）及 `DSSAT输出`/`DSSAT输出_v2` 的 FileA/FileT/TMA/TMT。结果为：

- Excel 中只有处理/水氮处理/重复/日期和植株测定指标；没有处理级 `PLWT`、`PAGE`、苗龄、移栽苗重/叶面积、定植密度或缺株字段。
- 因此当前公开原始证据不能支持处理级初始植株状态反事实；不得按拟合优度反推处理级 PLWT/PAGE。
- 参考 TMT 与正式 TMT 均为 96 个 `(TRNO, DATE)` 键，但少数后期 LAI/LWAD/SWAD/CHTD 数值不同（正式 bundle 采用后续数据修订/含水率口径）。这属于版本溯源差异，不能用旧参考 TMT 覆盖正式 TMT；正式 bundle 的 TMT 仍为当前率定唯一权威观测源。
- 差异审计的具体计数为：LAID 2 行、LWAD 5 行、SWAD 3 行、CHTD 1 行（均在共同键上）；其中 TRNO=11、26122 的正式 LAI=0.311 是剔除异常重复后的均值，旧参考值 0.286 不是当前清洗口径。因此这些差异不构成“首期观测错配”证据，但必须在 manifest 中保留版本来源。
- 正式 bundle 的 `XXQL2601.TMX/TMA/TMT` SHA-256 已记录在 `workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_4_raw_initial_state_evidence/s0_4_raw_initial_state_audit.json`；审计过程未修改 bundle。

据此，S0-4 判定为“**无可授权的处理级初始状态证据**”。直接进入 S0-5 或把 PLWT/PAGE 写入正式输入均不允许；后续只能在获得新的原始田间记录后再申请处理级反事实。

## 8. 可复现命令与测试

```powershell
python -X utf8 tools/analysis/run_v46_s0_3_initial_state_mechanisms_20260831.py
python -m py_compile tools/analysis/run_v46_s0_3_initial_state_mechanisms_20260831.py tools/analysis/audit_v46_s0_4_raw_initial_state_evidence_20260831.py
python -m pytest -q tests/test_nitrogen_response_gate.py tests/test_soil_scalar_injection.py tests/test_t10_direct_harvest.py
```

本轮脚本使用固定宽度列切片写入 TMX（PLWT/PAGE 58:64、64:70；FDATE 3:8），避免再次破坏 DSSAT 定宽格式；任何后续脚本不得改用 `" ".join(fields)` 重写整行。
