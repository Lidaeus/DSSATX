# E02 v46 best71 局部氮响应多臂试验：结果与后续交接

日期：2026-08-31  
基线：`e02_formal_v46_step20_custom26sp_20260831_200x4` 确定性成员 71  
试验范围：25SP 10 个处理、26SP 12 个处理；25FA 不参与本阶段调参

## 1. 已完成工作

本阶段按冻结的 best71 参数锚点运行了 5 个局部 PEST-IES 臂：

| 臂 | 释放的局部机制 | N_RESPONSE λ | realizations / noptmax / agents |
|---|---|---:|---|
| A | FNPGN1、FNPGN2、RTNO3 窄基线通道 | 1 | 60 / 3 / 6 |
| B | 与 A 相同，仅提高 N_RESPONSE 权重 | 2 | 60 / 3 / 6 |
| C | RTNO3（吸收—供氮通道） | 1 | 60 / 3 / 6 |
| D | PROLFI、PROSTI、PRORTI、NMOBMX、NVSMOB（需求—动员） | 1 | 60 / 3 / 6 |
| E | FNPGN1、FNPGN2、LNREF、NSLOPE（叶氮—光合） | 1 | 60 / 3 / 6 |

所有臂均使用同一 25SP/26SP soil bundle（SHA-256：`d84f5695f0cd8d6977c32a5ff7a037857288c9e9814fdf5d5b9cada1ab6e161d`），所有非本臂参数固定为 best71。A–E 的 IES 工程质量报告均为 `status=pass`，没有 agent 失败、NaN 或 observation 缺失。

## 2. 确定性复跑结果

每臂从最终 iteration 选择最低 Phi 成员，再对完整 22 处理进行 deterministic replay。A/B 的最低 Phi 成员均为 26，C 为 31，D 为 13，E 为 20。完整结果见：

`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/deterministic_candidate_metrics.csv`

| 臂 | 成员 | 25SP 末次鲜产量 RRMSE % | 26SP 末次鲜产量 RRMSE % | 25SP 累积鲜重 NSE | 26SP 累积鲜重 NSE | 25SP LAI NSE | 26SP LAI NSE | 25SP W NSE | 26SP W NSE | 26SP N 误差降幅 vs A | 改善层数 | 晋级 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| A | 26 | 14.84 | 9.17 | 0.825 | 0.927 | 0.473 | -2.494 | -1.705 | -5.198 | 0.0% | 0 | 否 |
| B | 26 | 14.84 | 9.17 | 0.825 | 0.927 | 0.473 | -2.494 | -1.705 | -5.198 | 0.0% | 0 | 否 |
| C | 31 | 15.14 | 9.21 | 0.821 | 0.927 | 0.471 | -2.469 | -1.259 | -5.694 | 6.9% | 6 | 否 |
| D | 13 | 10.55 | 8.89 | 0.889 | 0.932 | 0.530 | -2.778 | -0.918 | -5.709 | 3.7% | 6 | 否 |
| E | 20 | 12.49 | 8.91 | 0.863 | 0.931 | 0.510 | -2.686 | -1.382 | -5.817 | 8.2% | 8 | 否 |

说明：末次产量验收使用 RRMSE，响应差值允许为负；W/N 响应的 NSE 不再使用 `> -90` 的过滤，以免把合法的负响应差值误判为缺失。

## 3. 门槛判定与科学结论

没有任何一个臂满足全部晋级条件：

1. A/B 没有降低 N 响应误差，且仅提高 λ 没有产生可识别改善。
2. C/D/E 虽分别改善了 6、6、8 个响应层，但 26SP N 响应绝对误差相对 A 仅下降 6.9%、3.7%、8.2%，远低于 30% 门槛。
3. A–E 两季末次鲜产量 RRMSE 均低于 25%，说明产量尺度没有工程性崩溃；因此“不晋级”主要由 N 响应不足和保护指标失败造成，而不是产量门槛失败。
4. C 的 26SP LAI 略高于 A，但仍为 -2.469，且 26SP W_RESPONSE NSE 降至 -1.075；D/E 的 26SP LAI 和 W_RESPONSE 进一步恶化。N 响应改善不能以牺牲晚期冠层或水分响应为代价。
5. 当前 26SP 的水分响应结构本身仍很弱（A 为 -0.958），应避免将 C/D/E 的小幅 N 改善解释为机制已被识别。

因此：**C、D、E 没有形成可组合的 F 臂赢家；不得据此放开 v37/v40 的全部参数，也不得直接更新正式率定边界。**

## 4. 本阶段代码修正

评估脚本已更新为：

`D:/Tomato_Cal/tools/analysis/evaluate_v46_best71_nitrogen_multiarm_20260831.py`

修正内容：

- 增加有符号响应差值的 NSE 计算，负响应不再被当作缺失值；
- 计算 26SP N 响应相对 A 的误差降幅；
- 统计 20 个 N2/N1 响应层中实际改善层数；
- 将两季鲜产量 NSE、LAI NSE、W_RESPONSE NSE 和末次产量 PBIAS 纳入保护性门槛；
- `promotion_pass` 只有在工程、N 响应、产量和保护门槛全部通过时才为真。

本轮回归测试：`11 passed`（N 响应门槛、土壤标量注入、直接收获事件）。

## 5. 交给协作者的下一阶段任务

### 5.1 先做输入/输出溯源审计，不扩大全参数

1. 核对 26SP `PestNResponse.OUT`、`PestHarvest.OUT` 与 `XXQL2601` 的 TN/HNO/日期对应关系，确认 N0 参考处理、N1/N2 对照和末次真实收获事件均一致。
2. 单独导出每个季节、每个水分层的 N2−N0 和 N1−N0 观测/模拟差值，检查异常的 26SP N1-W3 负观测是否只是数据特征，而非输入或映射错误。
3. 对 `PestWResponse.OUT` 做同样审计；按修正后的 N0/N3 口径，当前 A 的 26SP W_RESPONSE NSE=-5.198，不能把它当作稳定保护基线而跳过检查。
4. 保持当前目标口径：末次鲜产量用 RRMSE/PBIAS，N/W 响应按“季节×响应层”单独 SST；虚拟收获事件不得进入产量或响应比较。

### 5.2 若审计通过，运行受控 deterministic 网格，而不是立即组合 F

建议建立一个新的 27–36 点小网格，仍固定 best71 的水分、土壤、源库和其他遗传参数：

- `RTNO3`：0.025、0.032、0.040；
- `FNPGN1`：0.90、1.00、1.10；
- `FNPGN2`：4.15、4.35、4.50；
- 可选 `LNREF`：3.5、3.85、4.2（若计算量允许）。

每个网格点都要输出 25SP/26SP 的 N2−N0、N1−N0、W_RESPONSE、LAI、累积鲜重 NSE、末次鲜产量 RRMSE/PBIAS 和边界距离。只接受同时满足：

- 25SP 的 N2−N0 与 N1−N0 均值为正；
- 26SP N 响应绝对误差相对 A 至少下降 30%；
- 至少 3 个响应层改善；
- 两季末次鲜产量 RRMSE≤25%，LAI/W_RESPONSE/累积鲜重相对 A 不下降超过 0.05。

### 5.3 只有网格出现明确可重复赢家时才开局部 F

F 只能组合网格中已经证明有效的参数方向，且仍限制在该局部参数族内；不重新激活 v37 的 114 个参数。若网格也无法达到 30% 的 26SP 误差降幅，应停止扩边，转向检查 26SP 实测氮输入、土壤供氮和观测—模拟变量对应关系。

## 6. 复现入口

- A–E 配置清单：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/arm_configuration_manifest.csv`
- A–E IES 运行目录：`D:/Tomato_Cal/workspace/runs/e02_v46_best71_n_*_60x3_20260831/`
- 确定性指标：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/deterministic_candidate_metrics.csv`
- 运行与构建脚本：
  - `D:/Tomato_Cal/tools/calibration/setup_v46_best71_nitrogen_multiarm_20260831.py`
  - `D:/Tomato_Cal/tools/calibration/launch_v46_best71_nitrogen_multiarm_20260831.py`
- `D:/Tomato_Cal/tools/analysis/evaluate_v46_best71_nitrogen_multiarm_20260831.py`

## 7. 多臂结束后的复核结果（2026-08-31）

### 7.1 输入 bundle 完整性

已对当前 25SP/26SP formal bundle 重新计算并修复 `input_manifest.json`。修复只涉及 manifest 元数据，不改动 bundle 载荷；当前逐文件 SHA-256/文件大小校验通过。

- 25SP manifest：`ecff23482cd4b4f71fe2c657d7c086952b0742efcce06eff7eee8f79a6ae58d5`，23 个 payload 文件。
- 26SP manifest：`29deeb4d878ed6a423f004eaed1d887d02f121804faa05f5982256b35615e637`，22 个 payload 文件。
- 修复脚本：`D:/Tomato_Cal/tools/analysis/repair_formal_bundle_manifests_20260831.py`。

输入审计报告位于：

- `D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/input_audit_25sp/observation_audit.json`
- `D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/input_audit_26sp/observation_audit.json`

审计当前仍报告 `safe_for_direct_formal_use=false`：25SP 有 73 个 error（主要为 IC 深度未落在层边界，另有 `IC_WATER_OUTSIDE_SOIL`），26SP 有 84 个 error（均以 `IC_LAYER_UNMATCHED` 为主）。这些深度不重合项来自观测 IC 深度与 DSSAT 土层边界的不同采样网格，属于必须明确插值/归属规则的审计项，不能直接删除或把 TMX 深度强行改成土层边界。25SP 另有少量深层 SH2O 高于当前 SSAT 的记录，协作者须单独核实其测量单位和土壤层对应关系，不能静默截断。正式率定前应把“已知且有规则的深度映射”与“真正越界/单位错误”分开报告，并让审计脚本显式记录处理规则。

### 7.2 局部确定性网格结果

在 best71 锚点上，仅改变 `RTNO3 × FNPGN1 × FNPGN2`，共完成 27 个确定性点（另含 baseline），所有 DSSAT 运行成功，但没有点通过完整晋级门槛。

结果文件：

`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_grid_20260831/grid_results.csv`

网格最优点的 26SP 氮响应绝对误差降幅约 10%，仍远低于 30%；按修正后的 N0/N3 W_RESPONSE 保护口径，该点的保护门槛也不再通过。多数点只能改善少量响应层，不能证明单一吸收/光合响应通道足以解释当前偏差。因此不得据此放宽边界、组合成 F 臂或重新激活 v37/v40 的全参数集合。

### 7.3 N_RESPONSE 源与配对复核

已抽查 `PestNResponse.OUT` 与同一运行的 `PestHarvest.OUT`：例如 TN12 在 25140 的 `NRESPS=43.2`，等于映射的 TN12 鲜重 6814.5 减 TN13（N0 参考）鲜重 6771.3。该输出是同一收获事件的成对差值，没有发现鲜重/干重源混用或跨收获日期错配。

已进一步对 baseline 的全部 61 行（33 行 N_RESPONSE、28 行 W_RESPONSE）进行逐行重建，最大浮点差为 `5.9e-12`，61/61 行通过。审计产物：

- `D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_grid_20260831/pairing_audit/nw_pairing_audit.csv`
- `D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_grid_20260831/pairing_audit/nw_pairing_audit_summary.csv`
- 审计脚本：`D:/Tomato_Cal/tools/analysis/audit_v46_best71_nw_pairing_20260831.py`

后续审计必须按映射表逐行核对：`season × water × HNO × DATE × nitrogen_level`，并同时保存观测值、模拟值、N0 参考处理和 source variable。任何只按 TN 编号或只比较末次累计值的复核都不具备足够溯源性。

### 7.4 W_RESPONSE 保护门槛修正

复核发现旧版 A–E/网格评估器的 `W_PAIRS` 遗漏了 N3 水分层，实际使用了 N0/N1/N2；这与 formal all22 合同（N0、N3；25SP 为 W3−W1，26SP 为 W2−W1）不一致。已修正 `evaluate_v46_best71_nitrogen_multiarm_20260831.py` 和 `grid_v46_best71_nitrogen_20260831.py`，并从已有 deterministic 输出重算：

- A/B：25SP W NSE = -1.705，26SP = -5.198；
- C：-1.259 / -5.694；D：-0.918 / -5.709；E：-1.382 / -5.817；
- 网格 baseline：-1.588 / -5.242，所有网格点 `grid_gate_pass=false`。

重算脚本：`D:/Tomato_Cal/tools/analysis/recompute_v46_best71_grid_gates_20260831.py`。今后所有保护门槛必须从目标合同读取 N 层和季节水分方向，禁止在脚本中另行硬编码不一致的 W 配对。

## 8. 交给协作者的下一步执行顺序

1. 先完成 25SP/26SP 的 N_RESPONSE、W_RESPONSE 配对审计，输出逐行审计 CSV；确认 IC 深度归属、TN 映射、收获日期和 `source_variable=CHFPW` 均一致。
2. 在不改变 best71 其余参数的前提下，对已完成网格的最优 2–3 点做独立 deterministic replay，并复核 22 个处理的鲜产量 RRMSE、LAI NSE、W_RESPONSE NSE、N2−N0/N1−N0 方向及边界压力。
3. 只有当同一参数方向在两季、多个水分层和至少 3 个 N_RESPONSE 层重复改善，且 26SP 氮响应降幅达到 30% 时，才允许建立局部 F 臂；F 臂仍只能包含已验证的局部氮参数，不得放开全部遗传参数。
4. 若审计通过而网格/F 臂仍不能达到门槛，应停止继续率定扩边，转向检查 26SP 的实测氮输入、土壤供氮和观测—模拟变量定义；不得用提高 N_RESPONSE 权重或牺牲 LAI/水分/产量尺度来制造“改善”。

复现入口：

- manifest 修复：`D:/Tomato_Cal/tools/analysis/repair_formal_bundle_manifests_20260831.py`
- 网格脚本：`D:/Tomato_Cal/tools/calibration/grid_v46_best71_nitrogen_20260831.py`
- 网格 manifest：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_grid_20260831/grid_manifest.json`
- N/W 逐行配对审计：`D:/Tomato_Cal/tools/analysis/audit_v46_best71_nw_pairing_20260831.py`

## 9. IC 深度与 MESOL=2 的专门复核（2026-08-31）

本轮新增了只读审计脚本：

`D:/Tomato_Cal/tools/analysis/audit_v46_best71_mesol2_ic_mapping_20260831.py`

审计结果：

- 25SP、26SP 的 TMX 均声明 `MESOL=2`，使用同一 `IBTM910017` 土壤剖面；原始 `SOIL.SOL` 层底为 10、30、60、90、120、150、180 cm。
- 两季 IC 观测深度为 2、4、15、30、40、60、80、100、140、180 cm，其中 2、4、15、40、80、100、140 cm 不是原始层底；这反映测量采样网格与 DSSAT 原始层网格不同，不能把这些值静默改写到最近的层底。
- 25SP、26SP 的 `soil_water_layer_mapping.csv` 均通过重叠权重审计（每个观测区间权重和为 1.0）。该映射解释了水分观测如何聚合到 10 个内部水分列，但还不能替代 IC 初始氮/水分值的逐层分配证明。

因此，`IC_LAYER_UNMATCHED` 当前应标记为“需要 MESOL=2 分配溯源”，而不是直接认定 TMX 数值错误。正式扩大率定前，协作者必须补交以下二选一证据：

1. 由实际运行生成的“观测深度→DSSAT 内部层/权重→初始 SH2O、SNH4、SNO3”逐行表；或
2. 一个最小确定性对照，证明当前测量深度写法与显式层底写法在 DSSAT 输出中的分配差异，并说明采用哪一种作为正式输入。

在证据补齐前，不得因审计脚本的 `safe_for_direct_formal_use=false` 而改写 IC 深度，也不得把 25SP/26SP 的水分映射表合并成一个跨季节表。复核产物：

`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/mesol2_ic_mapping_audit.json`

## 10. 当前阶段结论

A–E 局部率定和 RTNO3×FNPGN1×FNPGN2 网格均未达到晋级门槛；修正后的 N/W 配对审计为 61/61 行通过，但 26SP 氮响应误差最大降幅约 10%，且 W_RESPONSE 保护门槛全部未通过。故当前不建立 F 臂、不放宽边界、不重新激活 v37 全部参数。下一轮应先完成第 9 节的输入溯源，再决定是否开展新的局部氮试验；若仍不能达到 26SP 误差下降 30% 且不牺牲鲜产量、LAI 和水分响应，应停止继续扩展率定，转向检查 26SP 实测氮输入、土壤供氮与观测—模拟变量定义。

## 11. 后续新增的氮响应剖面结果（2026-08-31）

为填补旧剖面的两个缺口，新增并完成两轮确定性试验。所有案例均以 best71 为锚点，使用 25SP 10 个、26SP 12 个处理，未改变正式 bundle 或 frozen bounds。

### 11.1 NSTFAC/NREXP/NRMIN 曲率剖面

脚本：`D:/Tomato_Cal/tools/calibration/profile_v46_best71_nitrogen_shape_20260831.py`。共 36 个案例，覆盖 `NSTFAC` 锚点附近 0.15–0.60、`NREXP` 0.20–0.90、`NRMIN` 0.30–0.85 以及两组小交互网格。所有案例的 `PestHarvest.OUT` SHA-256 与 baseline 完全一致，`N2/N1` 响应误差均为 3523.59；生成的 SPE 行已确认数值写入成功。因此在当前官方 DSSAT 可执行文件和当前处理/初始条件下，这三个字段对本批次可观测产量响应没有可识别影响，不应据此放宽边界或加入 IES。

结果：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_shape_profile_20260831/shape_profile_scorecard.csv`

### 11.2 吸收通道剖面

脚本：`D:/Tomato_Cal/tools/calibration/profile_v46_best71_nitrogen_uptake_20260831.py`。共 22 个案例，测试 `RTNH4`、`RTEXF`、`PORMIN` 以及 `RTNO3×RTNH4`。最佳点为 `RTNO3=0.025, RTNH4=0.033734`，N2/N1 平均绝对误差由 3523.59 降至 3125.85（约 11.3%）；仍低于 30% 晋级门槛。`RTEXF` 在本试验中无可识别变化，`PORMIN=0.10` 会使 LAI/鲜重保护门槛失败。该结果只支持将低 RTNO3 作为后续候选方向，不支持建立正式 F 臂。

结果：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_uptake_profile_20260831/uptake_profile_scorecard.csv`

### 11.3 26SP 时间结构诊断

脚本：`D:/Tomato_Cal/tools/analysis/summarize_v46_n_response_structure_20260831.py`；结果：`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_grid_20260831/n_response_structure_baseline.csv`。该脚本已修正为读取正式 bundle 的 `.TMT`（不再读取可能含预调整值的 `FileT_values.csv`）。基线模型的主要问题不是单纯终端幅度，而是早期响应形状：例如 26SP W2/N3 的末次观测响应为 19,934，而模拟为 3,310；26SP W3/N1 的末次观测响应为 −1,006，模拟为 3,541。后者应作为诊断异常保留，不能强制改成正值。该证据说明继续只调静态胁迫曲率参数很可能无效，下一步必须优先核查早期氮供给/吸收时序及观测映射。

### 11.4 协作者下一步执行顺序

1. 对 26SP 的逐次 SNH4/SNO3、施肥日期、土壤供氮扣减和 `PestNResponse.OUT` 做同一 `season × water × nitrogen × HNO × DATE` 逐行溯源；保留 N1-W3 的负观测，不做方向性修正。
2. 只有在溯源通过后，才以 `RTNO3=0.025`（可选 `RTNH4=0.020–0.050`）开展不超过 3 个局部确定性复跑，并同时验收 W_RESPONSE、LAI、鲜重 RRMSE/PBIAS。
3. 若仍不能达到 26SP 氮误差下降 30%，停止继续增加氮参数和 Phi 权重，转入输入/观测定义审查。
