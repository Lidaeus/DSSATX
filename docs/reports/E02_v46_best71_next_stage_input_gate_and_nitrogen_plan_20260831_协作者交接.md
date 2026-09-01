# E02 v46 best71：多臂试验后的下一阶段交接方案（2026-08-31）

## 1. 交接目的

本文件用于协作者继续执行，不代表已经批准新的正式率定。当前所有结论均以 `best71` 确定性重放为锚点，25SP 使用 10 个处理、26SP 使用 12 个处理；非本阶段试验参数保持 best71，不得复用“最佳成员”标签替代参数文件。

## 2. 已完成证据与当前判断

### 2.1 多臂 IES 未产生可晋级赢家

A–E 五个局部臂（60 realizations、`noptmax=3`、6 agents、官方 DSSAT）均完成工程验收，但没有同时达到 26SP 氮响应绝对误差下降 30%、至少 3 个响应层改善以及鲜重/LAI/W_RESPONSE 保护门槛。因此不建立 F 臂，不重新放开 v37 全参数集，也不据此扩展 frozen bounds。

### 2.2 曲率参数在当前场景不可识别

`NSTFAC/NREXP/NRMIN` 的 36 个确定性剖面均产生相同的 `PestHarvest.OUT` SHA-256 和相同氮响应误差（3523.59）。SPE 行已确认实际写入，因此不是注入失败；在当前官方可执行文件、处理和初始条件下，这组字段对可观测收获量没有可识别影响。不得直接把它们加入 IES。

### 2.3 吸收通道仅有弱改善

`RTNO3×RTNH4` 剖面最佳点为 `RTNO3=0.025`、`RTNH4=0.033734`，N2/N1 平均绝对误差由 3523.59 降至 3125.85（约 11.3%），仍未达到 30% 门槛。`RTEXF` 无可识别变化；`PORMIN=0.10` 破坏 LAI/鲜重保护门槛。可保留低 RTNO3 作为候选起点，但不能宣称已经解决氮响应。

### 2.4 关键结构性问题是早期处理间差异塌缩

权威来源必须是正式 bundle 的 `.TMT`；`FileT_values.csv` 可能含预调整中间值，禁止作为最终观测源。基线早期/末期结构审计位于：

`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_grid_20260831/early_structure_audit/`

其中 `early_structure_flags.csv` 显示：

- 25SP HNO1：观测处理范围 3563，模拟范围 365，范围比 0.103，标记为 spread collapse；
- 26SP HNO1：观测范围 9963，模拟范围 255，范围比 0.026，标记为 spread collapse；
- 26SP HNO2–HNO5 仍分别只有约 0.03–0.16 的模拟/观测范围比。

26SP HNO1 的同水分 N3−N0 观测响应为 W1 7310、W2 7496、W3 5576，而模拟仅约 0.5、1.7、7.0。与此同时，首期模拟值几乎按水分处理固定（W1 约 5544、W2 5291、W3 5408），而观测在 W1/W2/W3 间差异很大。这不是单一末期尺度问题，优先级高于继续盲目增加 N_RESPONSE 权重。

`first_harvest_fruit_state.csv` 进一步记录了首期的 `CHNUM/CMFNM/AFPWD/CHFPW`。26SP 首期 `CHNUM` 全部为 1、`CMFNM` 为 21–22，且鲜果输出主要按水分变化而非按氮水平变化；这为后续检查果实成熟/初始植株状态提供了机制层证据。

## 3. 协作者必须先完成的 S0 输入/溯源闸门

### 3.1 重放并核对完整配对

使用下列脚本和输入重新生成审计，不得手工改 CSV：

```powershell
python -X utf8 tools/analysis/audit_v46_best71_early_structure_20260831.py `
  --det-dir workspace/reports/e02_v46_best71_nitrogen_grid_20260831/scratch_runs/baseline_best71 `
  --mapping-csv configs/runs/e02_mapping_25sp_w3w1_26sp_w2w1_n2n0_20260830.csv `
  --bundle-25sp data/user/experiments/xxql2501_formal_scheme4_soil_20260830 `
  --bundle-26sp data/user/experiments/xxql2601_formal_scheme4_soil_20260830 `
  --out-dir workspace/reports/e02_v46_best71_nitrogen_grid_20260831/early_structure_audit
```

必须逐行核对 `season × treatment × HNO × DATE × source=CHFPW`。输出中的 N0 行由正式 TMT 重新读取，不能从只含 N1–N3 的响应摘要推断。

### 3.2 26SP 供氮和处理映射核查

逐处理读取 `XXQL2601.TMX`：确认 MI/MF、灌溉日期/数量、施肥日期/数量、IC 的 SNH4/SNO3 和 SH2O 均与 mapping CSV 一致；确认 26SP 的 W1/W2/W3 与 N0–N3 组合没有错位。保存一张逐处理溯源表，至少包含 `treatment, MI, MF, water_level, nitrogen_level, fertilizer_date, fertilizer_N, IC_source`。

### 3.3 IC/MESOL=2 证据

继续使用 `tools/analysis/audit_v46_best71_mesol2_ic_mapping_20260831.py`。`IC_LAYER_UNMATCHED` 只能在提供“观测深度→DSSAT 层/重叠权重→写入 SH2O/SNH4/SNO3”的证据后关闭；不得因审计不通过而直接删除或强行改写观测深度。

S0 只有在以下条件全部满足后才算通过：

1. 22 个处理的 TN/水分映射无一对多或错位；
2. 观测日期与模拟收获事件逐行一致；
3. 施肥和逐次初始氮输入可追溯到 TMX；
4. `PestNResponse.OUT` 与同一事件的 `PestHarvest.OUT` 差值重建通过；
5. 所有异常（包括负的观测响应）被保留并解释，不做方向性修正。

## 4. S0 通过后的最小试验设计

### 4.1 先做确定性回归，不立即正式率定

以 best71 和下列已观测有效点各做一次全 22 处理 deterministic replay：

- D0：best71 基线；
- D1：`RTNO3=0.025`，其余保持 best71；
- D2：`RTNO3=0.025, RTNH4=0.033734`，其余保持 best71。

比较 HNO1/HNO2/HNO末次的处理范围、N3−N0、W 响应以及鲜重尺度。若 D1/D2 仍在 HNO1 出现 spread collapse，停止释放更多氮参数，转入输入/模型事件诊断。

### 4.2 仅在 D1/D2 证实可重复改善后做局部 IES

不得重开 v37 的 114 参数。建议最多两个可归因臂：

| 臂 | 激活参数 | 初值/范围 | N_RESPONSE λ | 规模 |
|---|---|---|---:|---:|
| F1 | RTNO3、RTNH4 | RTNO3 0.020–0.040；RTNH4 0.020–0.050 | 1 | 60 realizations，noptmax=3，6 agents |
| F2 | RTNO3、RTNH4、PROLFI、NMOBMX | 前两者同上；后两者仅在已冻结物理范围内小幅浮动 | 1 | 60 realizations，noptmax=3，6 agents |

所有非本臂参数（尤其水分、土壤、源库、PHTMAX、WTFSD、SFDUR）固定为 best71。不要同时释放 `NSTFAC/NREXP/NRMIN/RTEXF/PORMIN`，因为剖面没有显示可识别改善或会破坏保护指标。

## 5. 晋级与停止规则

### 5.1 晋级必须同时满足

- 26SP N2−N0 与 N1−N0 的均值绝对误差相对 D0 至少下降 30%；
- 25SP 两个末次 N3−N0 恢复为正；
- 至少 3 个独立 N_RESPONSE 层改善；
- 22 处理鲜重尺度 RRMSE 不恶化超过 2 个百分点，LAI NSE 和 W_RESPONSE NSE 不下降超过 0.05；
- 早期处理范围比有实质改善，且不能通过牺牲末期尺度换取响应分数。

NSE 必须按“季节×目标族”独立计算；末期处理间产量优先用 RRMSE/PBIAS，不得用跨处理 NSE 代替。

### 5.2 停止条件

若 S0 通过后 F1/F2 仍不能达到 30% 误差下降，或首期 spread collapse 未改善，则停止继续扩展氮参数和提高 Phi 权重，转入论文中的“输入/观测结构限制”说明。只有出现可重复、跨季节且不牺牲鲜重/LAI/W 响应的赢家，才允许构建新的正式率定配置。

## 6. 交付清单

协作者完成后应提交：

1. `early_structure_pairs.csv`、`harvest_spread_summary.csv`、`n3_minus_n0_by_harvest.csv`、`water_response_by_harvest.csv`、`early_structure_flags.csv`；
2. 26SP 逐处理 TMX 供氮/灌溉/IC 溯源表；
3. D0–D2 的 deterministic 指标表和 22 处理逐事件对照；
4. 若运行 F1/F2，提交 run manifest、IES quality、确定性三类候选（最低 Phi、前 10% Phi 内最高 NSE、集合中位参数）及门槛判定；
5. 更新本文件末尾的“执行记录”，注明命令、时间、输入 bundle SHA-256 和是否通过每一条门槛。

## 7. 当前执行记录

- 2026-08-31：A–E 多臂 IES 完成，全部工程通过，无科学晋级赢家。
- 2026-08-31：曲率剖面 36 点完成，输出不变；吸收剖面 22 点完成，最佳约 11.3% 改善。
- 2026-08-31：完成全 22 处理早期结构审计；当前建议停在 S0 溯源闸门，不启动新的正式率定。

## 8. 新增确定性需求/动员触发剖面（2026-08-31）

脚本：`D:/Tomato_Cal/tools/calibration/profile_v46_best71_nitrogen_demand_20260831.py`  
结果：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_demand_profile_20260831/demand_profile_scorecard.csv`

该剖面共 20 个全 22 处理案例，测试 `PROLFI`、`NMOBMX` 及其小交互。结果显示：

- `PROLFI=0.30` 仅使 N2/N1 误差增加 196.02；`PROLFI=0.12/0.60` 明显破坏 LAI 与鲜重；
- `NMOBMX=0.25` 仅改善 138.76，`NMOBMX=0.60/0.85` 几乎不再变化；
- 所有案例在 26SP HNO1 的 `NSTD/PST1A/PST2A` 仍为零，说明这些试验没有在首期前打开可观测的氮胁迫通道；不能用其结果证明应继续放宽需求/动员边界。

同时输出的 `first_harvest_fruit_state.csv` 显示 26SP 首期 `CHNUM=1`，`CMFNM` 仅 21–22，且 `AFPWD/CHFPW` 主要随 W 变化、几乎不随 N 变化。这与首期观测的强 N 梯度不一致，提示当前差异缺口更可能位于早期果实成熟/初始植株状态或观测事件定义，而不是简单的 N_RESPONSE 权重不足。

在 S0 溯源证据完成前，协作者不得把 `PROLFI/NMOBMX` 剖面中的数值直接写入 frozen bounds；若要继续，必须先提交首期事件前的果实数、成熟度、初始植株状态及施肥—吸收逐日对照。

## 9. 26SP TMX 供给与处理映射复核（2026-08-31）

新增只读审计脚本：`D:/Tomato_Cal/tools/analysis/audit_v46_best71_26sp_tmx_schedule_20260831.py`。结果：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/26sp_tmx_schedule_audit.csv`。

12 个处理的水分名称、总灌溉量和总施氮量均与 mapping CSV 逐项一致（12/12）。首期收获前累计灌溉量为 W1=165.9、W2=211.1、W3=256.4 mm；首期前施氮量为 N0=0、N1=64、N2=128、N3=192 kg ha⁻¹，说明处理梯度确实写入 TMX，当前首期模拟范围塌缩不能归因于 MI/MF 映射或施肥/灌溉记录缺失。

因此，下一步应把重点放在“首期前模型状态为何未响应处理梯度”：包括初始植株/果实状态、成熟度与收获事件定义、以及 DSSAT 在当前作物模型下的早期氮需求计算；不得再用单纯提高 N_RESPONSE 权重掩盖该差异。

补充证据：26SP 观测的 26122 LAI 与 26146 首期鲜重的处理间 Pearson 相关为约 0.688，而基线模型 26122 LAI 对 12 个处理均约为 0.330。首期产量差异很可能已在首个观测冠层状态之前形成；这也是为什么仅调整后期 N 吸收/动员参数无法恢复首期 N 梯度的关键理由。该相关仅作诊断证据，不应被当作额外拟合目标直接重复计权。
## 10. A–E 多臂最终结果与目标函数审计（2026-08-31）

最终确定性候选表：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/deterministic_candidate_metrics.csv`。

| 臂 | 激活参数 | 25SP N 平均绝对误差 | 26SP N 平均绝对误差 | 26SP 误差下降 | 改善层数 | 结论 |
|---|---|---:|---:|---:|---:|---|
| A | FNPGN1、FNPGN2、RTNO3，λ=1 | 3673.68 | 3518.30 | 0% | 0 | 基线 |
| B | 同 A，λ=2 | 3673.68 | 3518.30 | 0% | 0 | 提高 λ 未改变确定性结果 |
| C | RTNO3 | 3142.48 | 3277.20 | 6.85% | 6 | 有方向性但不足 |
| D | NMOBMX、NVSMOB、PROLFI、PRORTI、PROSTI | 3064.80 | 3387.05 | 3.73% | 6 | 25SP 较好，26SP 不足 |
| E | FNPGN1、FNPGN2、LNREF、NSLOPE | 3291.78 | 3228.33 | 8.24% | 8 | 相对最好但远低于 30% |

A–E 全部工程成功，但没有任何一个臂同时满足 26SP 误差下降 ≥30%、至少 3 个响应层改善、鲜重/LAI/W_RESPONSE 保护门槛。因此不建立 F 臂、不扩展 frozen bounds，也不启动新的正式 IES。

### 10.1 N_RESPONSE 目标函数实现核对

新增只读审计脚本：`D:/Tomato_Cal/tools/analysis/audit_v46_best71_nresponse_objective_contract_20260831.py`。A 臂审计输出位于：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/nresponse_objective_audit_arm_a/`。

审计确认：每个 realization 有 66 个 N_RESPONSE 行，25SP=36（4 个水分层对比 × 9 次收获），26SP=30（6 个水分层对比 × 5 次收获）；设计明确 `source_variable=CHFPW`、`contrast_scale=raw_difference`，按季节×水分层分别计算 SST，没有发现误用干重或跨季节合并分母。有效 sigma 约 86.60，是 sigma_floor=50 与 T8 season×stratum 权重重标定的结果。A 臂 N_RESPONSE 平均 Phi 约 20.99（25SP 15.90、26SP 5.10）。因此当前问题不是 N_RESPONSE 代码错配；提高 λ 只会惩罚同一结构性残差，不能恢复首期处理差异。

C、D、E 的对应审计目录分别为 `nresponse_objective_audit_arm_c_local_n_supply_rtno3`、`nresponse_objective_audit_arm_d_local_n_demand_mobilization` 和 `nresponse_objective_audit_arm_e_local_n_leaf_photosynthesis`，三者均通过相同的行数/来源/分层结构检查。

补充核对发现：当前 A 臂 observation registry 中 26SP 的 `LAIDM` 和 `LAIDDM` 权重全部为 0（`phi_role=diagnostic_only`），只有叶/茎增量和终端状态进入 Phi。这是当前合同的明确选择，并非权重计算丢失；但它意味着 26122 首期绝对 LAI 不会反向约束 IES。若后续采用 G1/G2，必须把该改变作为单独的目标合同敏感性试验记录，不能与氮参数效果混为一谈。

## 11. 下一阶段执行顺序（交给协作者）

在任何新 IES 之前，必须按顺序提交以下 S0 证据：

1. **首期事件溯源**：对 26SP 每个处理核对播种/移栽日期、首期采收日期、MI/MF、施肥日期与剂量、IC、首期观测日；将 `CHFPW` 与 `.TMT` 逐行对齐，特别检查 HNO1 是否被虚拟收获事件或日期截断。
2. **首期前状态输出**：提取首期采收前 26122–26146 的 LAI、叶/茎质量、果数、果重、成熟度和光合/氮胁迫变量；确认 NSTD/PST1A/PST2A 是否在首期前为零，以及是否存在所有处理相同的状态。
3. **机制定位确定性对照**：只改变一个假设，至少包含“首期采收事件/成熟度”“首期前初始植株状态”“首期前施肥—吸收时序”三类对照；每类保留完整 22 处理的首期及末期指标。
4. 仅当对照能在不破坏鲜重尺度、LAI 和 W_RESPONSE 的前提下扩大首期模拟处理范围，才允许局部 IES。建议固定 best71 的水分、土壤、源库和晚期参数，仅释放经剖面证明可识别的 1–3 个氮参数；60 realizations、`noptmax=3`、6 agents，N_RESPONSE λ=1。
5. 晋级必须同时满足：25SP 末次 N3−N0 为正；26SP N 响应平均绝对误差相对 A 下降 ≥30%；至少 3 个独立响应层改善；鲜重终期 RRMSE、LAI 和 W_RESPONSE 不明显退化。失败则停止扩边并转入论文“早期状态/观测结构限制”说明。

### 协作者交付物

- `n_response_objective_audit.json`、`n_response_objective_rows.csv`、`n_response_objective_summary.csv`；
- 首期事件/状态逐处理溯源表及确定性重放日志；
- 三类 S0 对照试验的配置、输入哈希、22 处理指标和失败原因；
- 若获准运行局部 IES：manifest、engineering/science gate、三类确定性候选及本文件执行记录。

## 12. 执行记录（续）

- 2026-08-31：完成 A–E 多臂确定性候选汇总；无科学晋级赢家。
- 2026-08-31：对 A、C、D、E 最终迭代完成 N_RESPONSE 目标函数审计；66 行/realization、季节分层和鲜重来源均通过。
- 2026-08-31：下一阶段冻结为 S0-1→S0-2→S0-3；在首期结构问题未解释前不启动 F 臂或正式率定。

## 13. S0-2 首期前状态审计结果（2026-08-31）

新增只读脚本：`D:/Tomato_Cal/tools/analysis/audit_v46_best71_early_state_20260831.py`。

运行结果目录：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/early_state_audit_26sp/`。

关键机器证据（26SP、12 个处理、best71 确定性重放）：

- 26122 的模拟 LAI、LWAD、SWAD、CHTD 处理间范围均为 0；实测 LAI 范围 0.242、LWAD 范围 100、SWAD 范围 68、CHTD 范围 0.065，四类状态均触发 spread-collapse 标志。
- 26153 的 LAI 模拟/实测范围比为 0.509，但 SWAD 为 0.158、CHTD 为 0.065；处理差异仍明显不足。
- 首期采收日期模拟与 TMT 均为 26146，12/12 无日期错位；因此首期差异塌缩不是收获日期配对错误。
- 首期鲜重模拟范围为 255.3，而实测范围为 9963，范围比约 0.0256，与早期结构审计一致。
- 26180 实测 LAI 没有有效范围（观测均缺失/无效），该日期不得被当作 LAI 验收目标；其他变量仍保留作为诊断。

审计 JSON：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/early_state_audit_26sp/early_state_audit.json`；逐处理配对表为 `early_state_pairs.csv`，范围与标志表为 `early_state_flags.csv`。

该结果把下一阶段优先级进一步收敛为：先解释 26122 首期前统一状态的来源（初始植株状态、初始化日期/成熟度或模型启动逻辑），再考虑任何氮参数释放；不能用后期 N_RESPONSE 权重或后期吸收参数替代这一缺口。

## 14. S0-3 机制定位对照方案（交给协作者执行）

S0-2 已经证明：26122 首期模型状态在 12 个处理间完全相同，而实测 LAI/LWAD/SWAD/CHTD 均有处理差异；首期模拟和 TMT 的收获日期均为 26146。因此 S0-3 必须优先检验“状态生成机制”，而不是继续放大 N_RESPONSE 权重。

### 14.1 三个确定性对照

| 对照 | 只改变的内容 | 建议实现 | 通过标准 |
|---|---|---|---|
| S0-3A 事件定义 | 首期采收事件/成熟度解释 | 保持输入数值不变，分别测试首期观测是否为真实采收、虚拟采收或成熟度触发；记录 26122–26146 状态及首期 CHFPW | 日期配对仍正确，且至少一种解释能产生可重复的首期处理差异 |
| S0-3B 初始植株状态 | 首期前植株状态 | 仅对照性地把 26122 TMT 的 LAI、LWAD、SWAD 映射为处理级初始状态（或在 26075 种植时对 PLWT/PAGE 做受控映射）；不得写入遗传 frozen bounds | 首期范围明显扩大，同时末期鲜重 RRMSE、LAI、W_RESPONSE 不劣化 |
| S0-3C 施肥—吸收时序 | 首期前供氮进入模型的时间 | 保持总施氮量不变，只平移/拆分首期前施肥日期；输出逐日吸收、土壤无机氮、NSTD/PST1A/PST2A | 只有在时序改变确实激活首期前氮胁迫且不改变水分输入时才保留 |

三类对照均须使用完整 22 个春季处理、best71 其余参数固定；25FA 不参与。每个案例必须保存输入 bundle/模板哈希、命令、PestTmtGrow.OUT、PestHarvest.OUT、早期状态表和 22 处理终期指标。

### 14.2 目标函数敏感性对照（不等同于机制修复）

若 S0-3B 证明首期状态可由处理级初始状态解释，可额外构建一个**仅用于归因的局部 IES**：

- G0：当前 A 臂合同（LAIDM/LAIDDM 为 diagnostic_only）；
- G1：只将 26122 的 `LAIDM` 设为 calibration，保留 `LAIDDM`、LAIX 和其他 CANOPY 目标关闭；
- G2：G1 + `RTNO3`（范围 0.025–0.040），其余参数固定 best71。

G1/G2 的目的只是检验“首期绝对 LAI 约束是否能把处理差异传递到氮响应”，不是借权重制造赢家。若 G1/G2 不能扩大首期模拟范围，立即停止；不得把 LAIDM 权重、处理级初始状态或施肥平移写入正式 frozen bounds。

只有 G1/G2 同时满足 26SP N 平均绝对误差下降 ≥30%、25SP 末次 N3−N0 为正、至少 3 个响应层改善且鲜重/LAI/W_RESPONSE 不退化时，才可考虑局部正式率定。否则将“首期状态缺失导致 N 响应不可识别”作为论文限制结论。

### 14.3 协作者执行约束

1. 先交 S0-3A/B/C 的确定性结果，再申请 G1/G2；不得跳过 S0-3 直接运行 200 realizations 正式率定。
2. 不得修改正式 bundle、TMT 观测值或现有 best71 参数文件；所有试验输入放在独立 scratch 目录并写入 manifest。
3. 不得用 `FileT_values.csv` 替代 TMT；不得将 26180 缺失 LAI 填补为有效观测。
4. 报告必须同时给出首期模拟/观测范围、N3−N0、N2−N0、N1−N0、鲜重终期 RRMSE、LAI 指标和 W_RESPONSE 指标；不得只报告总 Phi。

## 15. S0-5 历史共同 PLWT=7 g 证据对照（2026-08-31）

为核对早期项目记录中“壮苗 `PLWT=7 g`”的可迁移性，新增只读确定性脚本：

`D:/Tomato_Cal/tools/analysis/run_v46_s0_5_evidence_plwt7_20260831.py`

仅将独立 scratch bundle 的 26SP 种植行 `PLWT` 改为 7.0 g，25SP、正式 bundle、TMT 和 best71 参数均未修改。结果：

| 季节 | 首期鲜重模拟/观测范围 | 终期鲜重 RRMSE | 累积鲜重 NSE | LAI NSE | N 响应 MAE |
|---|---:|---:|---:|---:|---:|
| 25SP（未改） | 414.9 / 3563.0 | 14.90% | 0.825 | 0.472 | 3073.1 |
| 26SP PLWT=7 | 283.2 / 9963.0 | 10.44% | 0.901 | -1.964 | 6500.0 |

相对于 best71 26SP 基线（首期范围 255.3、终期 RRMSE 9.19%、累积鲜重 NSE 0.927、LAI NSE -2.465、N 响应 MAE 5714.1），`PLWT=7` 虽使 LAI NSE 略升，但终期鲜重、累积鲜重和 N 响应均退化，且首期处理 spread 仍接近塌缩。因此该历史共同值不能晋级为正式输入，也不能作为 G1/G2 的参数释放依据。

交付物：

`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_5_evidence_plwt7/s0_5_scorecard.csv`

当前决策保持不变：没有处理级原始初始状态证据时，不再继续 PLWT/PAGE 反事实或扩展 N 参数边界；若获得新证据，必须先重新申请 S0-5，并用本文件的全部保护门槛验收。

## 16. 首期氮胁迫通道审计（2026-08-31）

新增只读脚本：

`D:/Tomato_Cal/tools/analysis/audit_v46_best71_early_nstress_20260831.py`

对 S0-3A 基线的 26SP `PlantGro.OUT` 逐日解析（DOY 075–146、12 个处理）显示：`NSTD`、`PST1A`、`PST2A` 在首期采收日前全部为 0，三列最大值均为 0。该结果与 HNO1–HNO2 模拟 N 响应几乎不随 N 水平变化相一致，说明首期前氮胁迫通道尚未被模型激活；继续提高 N_RESPONSE 权重或释放后期动员参数不能解决这一结构缺口。

审计产物：

`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_6_early_nstress_audit/early_nstress_audit.json`

协作者下一步只能在获得可授权的首期前叶氮/植株状态或施肥—吸收逐日证据后，设计针对“首期前氮供需状态”的单一机制对照；在此之前不得启动新的 IES 正式率定。

## 17. N_RESPONSE 可行性审计（2026-08-31）

新增只读脚本：

`D:/Tomato_Cal/tools/analysis/audit_v46_best71_nresponse_feasibility_20260831.py`

该脚本对 S0-3A 基线的全部 33 个“季节×采收期×水分层”N1/N2/N3−N0 对比，计算观测单调性和单调模型的 PAVA 误差下界。结果：

- 25SP：18 个层中 13 个观测层违反 N1≤N2≤N3，模拟平均 MAE 5734.3，而单调拟合误差下界仅 515.5；
- 26SP：15 个层中 6 个观测层违反单调性，模拟平均 MAE 5688.2，而单调拟合误差下界仅 357.9。

因此当前 N_RESPONSE 误差的主要部分不是由少量观测非单调噪声造成，而是模型在多个层中没有产生足够的 N 梯度；仅改用单调目标或提高权重不能替代机制修复。该审计只用于可行性诊断，未修改 Phi、观测或晋级门槛。

产物：

`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_7_nresponse_feasibility/nresponse_feasibility_audit.json`

在获得新的首期状态证据前，后续工作应优先定位供氮状态为何未进入胁迫区间，而不是继续增加 N_RESPONSE 权重或把非单调观测强行改为单调。

## 18. 26SP 施氮量阶梯（S0-8，2026-08-31）

为判断“施氮供给过量掩盖了模型氮响应”这一假设，执行了 26SP `FAMN` 乘数的隔离确定性阶梯；25SP 保持不变，所有正式 bundle 和观测均未改写。脚本：

`D:/Tomato_Cal/tools/analysis/run_v46_s0_8_26sp_n_supply_ladder_20260831.py`

| 26SP FAMN 乘数 | 终期鲜重 RRMSE | 累积鲜重 NSE | LAI NSE | N 响应 MAE | NSTD 最大值 |
|---:|---:|---:|---:|---:|---:|
| 1.00（基线） | 9.19% | 0.927 | -2.465 | 5714.1 | 0 |
| 0.50 | 9.55% | 0.921 | -1.988 | 6111.7 | 0 |
| 0.25 | 9.70% | 0.921 | -1.330 | 6064.0 | 0 |
| 0.10 | 8.06% | 0.930 | -0.619 | 5229.5 | 0 |

低至 0.10 倍才出现方向性改善，但仍未激活 `NSTD`，且该改动与权威施肥记录不一致，不能写回正式 TMX 或作为率定候选。该结果只能说明供氮量级会影响结果，但当前模型的氮胁迫通道仍未在可接受输入范围内工作；下一步仍需原始首期状态/供需证据或模型机制层证据，不能通过任意缩减施氮量制造拟合改善。

结果表：

`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/s0_8_26sp_n_supply_ladder/s0_8_scorecard.csv`

## 19. NSTFAC 上限补充剖面（2026-08-31）

根据 `docs/CROPGRO_N_MECHANISM/04_n_stress_factor.zh-CN.md` 中的源码约束，将 `NSTFAC` 的未覆盖区间补齐至 0.70、0.85 和 1.00。结果仍基本不变：`NSTFAC=1.00` 的 N 响应 MAE 仅比基线降低约 0.45，LAI、鲜重和处理 spread 没有实质变化；所有此前剖面均未产生可晋级候选。

该结果排除了“NSTFAC 仅因剖面上限过低而未识别”的解释。后续不应再扩大 NSTFAC/NREXP/NRMIN 的剖面范围，除非出现新的源码、初始状态或叶氮观测证据。
