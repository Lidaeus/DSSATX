# PEST-GLM 接续 PEST-IES 率定开发方案（2026-08-18）

## 1. 目的与执行边界

本方案用于在两季正式 PEST-IES 率定结果基础上，开发一套可审计、可并行、可恢复的 PEST-GLM 局部优化流程。目标是在保留成员 126 总体产量尺度优势的前提下，探索 GLM 是否能够进一步降低目标函数、改善两季拟合，并尽可能修复氮素响应和水分响应。

本方案是开发规范，不授权立即启动正式率定。开发完成后必须先通过构建审计、确定性基线复跑和 `noptmax=1` 烟雾试验，再由用户决定是否启动正式 GLM。

必须保持以下科学口径不变：

- 使用官方 DSSAT v4.8：`D:\Tomato_Cal\DSCSM048.EXE`。
- 两季联合运行：25SP 10 个处理，26SP 12 个处理。
- 使用修复后的 25SP/26SP TMX；26SP 12 号处理采用 2026-08-18 用户指定的 INITIAL CONDITIONS。
- 土壤物理参数、土壤初始水分和初始氮素固定，不参与 GLM。
- 删除 CANOPY 目标族，不使用 LAIX。
- CANOPY_TERMINAL 使用每个处理最后一次 LAI 观测值和同日模拟值。
- W_RESPONSE 定义为同氮水平下 `W2-W1`。
- N_RESPONSE 定义为同水分水平下 `N1/N2-N0`。
- 所有 NSE 权重按“季节 × 目标族”分别计算 SST，禁止跨季节或跨变量合并分母。
- Python 图仅作为运行诊断，不生成 `Fig`/`FigS` 论文图编号。

## 2. 基线与数据来源

### 2.1 IES 基线

- 正式运行目录：
  `workspace/runs/e02_fixedsoil_nse_official_25sp26sp_200x6_20260817`
- IES 最终迭代：6。
- GLM 首选初值：成员 126（`phi_q10_highest_nse`）。
- 成员 126 当前两季累积干重 NSE：
  - 25SP：0.905360
  - 26SP：0.877187
- 当前 N/W 响应 NSE：
  - N_RESPONSE 25SP：-0.926381
  - N_RESPONSE 26SP：-3.518331
  - W_RESPONSE 25SP：-1.660082
  - W_RESPONSE 26SP：-1.461583

成员 126 优先于最低 Phi 和集合中位参数，因为其两季累积干重 NSE 均更高。最低 Phi、集合中位参数仅作为备选多起点，不作为第一轮默认起点。

### 2.2 敏感性证据

参数池以项目已批准的 Sobol top-23 为主要先验：

- `configs/sa/approved_topk/eggplant_formal_sobol_top23_v1_20260721.csv`

同时参考 Morris 跨季和分响应结果：

- `workspace/_history/20260804/sensitivity/workspace_sa/w4_bundle/morris_cross_season_summary.csv`
- `workspace/_history/20260804/sensitivity/workspace_sa/w4_bundle/morris_response_effects.csv`

上述 Morris 数据状态为 `science_pending`，只能作为参数筛选先验，不能替代本批次 GLM 局部 Jacobian。最终活动参数必须同时通过局部导数检查。

## 3. 参数池

### 3.1 Top-15 参数池

按已批准 Sobol 选择顺序定义：

1. RTNO3
2. TRIFL
3. XFRT
4. LFMAX
5. XFINT
6. FRLFF
7. PM06
8. RTNH4
9. NMOBMX
10. EM-V1
11. EM-FL
12. TB2
13. TO11
14. FRSTMF
15. NVSMOB

### 3.2 Top-23 参数池

Top-15 加入：

16. FL-SD
17. PORPT
18. TO12
19. ATOP
20. NSTFAC
21. TB1
22. TO22
23. TM2

代码必须从批准 CSV 读取参数顺序，不得在多个脚本中复制硬编码列表。构建时需要验证这些参数存在于正式 PST、当前冻结边界和成员 126 参数表中。

### 3.3 边界压力替换白名单

PHTMAX 和 PODUR 不自动加入 top-15/top-23，但允许在局部 Jacobian 证明其敏感时进入“边界压力替换”分支：

- PHTMAX 保持批准边界 45–75。
- PODUR 保持批准边界 12–58。
- 活动参数总数仍不得超过所选池规模；若加入 PHTMAX/PODUR，应替换局部复合敏感度最低的参数，而不是追加为第 24/25 个参数。
- 不允许因本轮 GLM 自动扩大 PHTMAX、PODUR、RTNO3 或其他物理边界。

## 4. 初值和 GLM 边界生成规则

### 4.1 初值

默认初值为成员 126 的最终 IES 参数向量。所有未进入 GLM 参数池的遗传参数固定为成员 126 值。

如果参数正好位于边界：

- 保留成员 126 原值，不擅自“内移”初值。
- 差分方向必须改为边界内的单侧差分。
- 记录参数、边界、差分方向和实际差分步长。
- 如果单侧导数在两种步长下不稳定，该参数不得进入正式 GLM，除非用户单独批准。

### 4.2 后验边界

默认使用 IES 最终参数集合的 2.5%–97.5% 分位数，较原建议的 5%–95% 更宽。算法如下：

```text
posterior_lo = q02.5
posterior_hi = q97.5
padding      = 0.10 × (posterior_hi - posterior_lo)
glm_lo       = max(frozen_lo, posterior_lo - padding)
glm_hi       = min(frozen_hi, posterior_hi + padding)
```

随后强制：

- 范围必须包含成员 126。
- 范围不得超出冻结边界和 `PHYSICAL_BOUNDS`。
- 若后验宽度小于冻结宽度的 5%，将范围扩展到以成员 126 为中心的冻结宽度 10%，再裁剪到冻结边界。
- 若成员 126 距冻结边界不足冻结宽度的 1%，允许直接使用该方向的完整冻结边界。
- 所有最终边界、分位数、扩展原因和裁剪原因写入 `glm_parameter_bounds_audit.csv`。

不得直接改写既有 frozen bounds。GLM 应生成新的、带来源元数据的 frozen bounds ID。

## 5. 目标函数试验臂

### 5.1 GLM-A：IES 目标函数复现臂

完整继承正式 IES 的观测、变换、权重和分季累积干重 NSE λ=75/季。该臂用于识别“算法由 IES 换成 GLM”本身能否带来局部改善。

### 5.2 GLM-B：响应增强臂

在 GLM-A 基础上：

- N_RESPONSE：分季 NSE，λ=1.0/季。
- W_RESPONSE：分季 NSE，λ=0.5/季。
- 其他目标族不变。
- 第一轮不加入叶/茎变化量 NSE，避免同时改变过多目标定义。

### 5.3 可选 GLM-C：温和响应增强臂

若 GLM-B 一步试验明显牺牲总体尺度，可构建：

- N_RESPONSE：λ=0.5/季。
- W_RESPONSE：λ=0.25/季。

GLM-C 不是默认必跑项，仅在 A/B 均不能进入正式阶段时启用。

## 6. 放宽后的晋级和评价规则

采用“工程可行”“科学优选”两层标准，不再用单一严格门槛淘汰所有探索性结果。

### 6.1 工程可行门槛

满足以下条件即可进入候选集：

- 运行正常结束，无非有限模拟值，无 DSSAT 重试耗尽。
- 两季累积干重 NSE 相对成员 126 的下降均不超过 0.05。
- 25SP 累积干重 `|PBIAS| ≤ 10%`。
- 26SP 累积干重 `|PBIAS| ≤ 18%`。
- LAID、LWAD、SWAD 的分季 NSE 单项下降不超过 0.10。
- 四个 N/W 响应 NSE 的平均值相对基线下降不超过 0.15。
- 同一响应族不得在两季同时下降超过 0.10。
- 参数不突破冻结/物理边界。

### 6.2 科学优选标准

工程可行候选按 Pareto/分层排序，不要求每项均优于成员 126：

1. 两季累积干重平均 NSE。
2. 两季累积干重绝对 PBIAS。
3. 四个 N/W 响应 NSE 的平均改善。
4. 26SP 水分响应平均模拟值是否由负值向实测正值方向移动。
5. 两季 LAID/LWAD/SWAD 的平均 NSE。
6. 总 Phi 和参数边界压力。

以下任一条件可标记为“建议晋级”：

- 两季累积干重 NSE 均不低于基线 0.02，且至少一个响应族的两季平均 NSE 改善 ≥0.10；或
- 两季累积干重平均 NSE 提高 ≥0.01，四个响应 NSE 平均不恶化超过 0.05；或
- 四个响应 NSE 平均改善 ≥0.25，同时两季累积干重 NSE 下降均不超过 0.03。

不得仅按最低 Phi 自动晋级。每个试验臂必须用自身未改变的权重计算相对 Phi；不同目标函数试验臂之间不得直接比较绝对 Phi。

## 7. 运行阶段

### 阶段 0：基线冻结与一致性检查

1. 验证正式 IES 状态和成员 126 来源。
2. 使用当前 TMX 对成员 126确定性复跑。
3. 验证 25SP=10、26SP=12 个处理。
4. 导出基线总体、器官、N_RESPONSE、W_RESPONSE 指标。
5. 保存全部输入哈希和 DSSAT/PEST++ 可执行文件哈希。

若基线与当前已确认指标不一致，停止构建。

### 阶段 1：Top-15 一步 GLM

- 试验臂：GLM-A、GLM-B。
- 参数池：top-15。
- `noptmax=1`。
- 官方 DSSAT，6 agents。
- 使用前向/边界内单侧差分。
- 输出局部 Jacobian、复合敏感度、奇异值、列相关性和一步候选。

### 阶段 2：Top-23 扩展判断

满足任一条件时运行 top-23 一步试验：

- top-15 有效 Jacobian 秩低于 8；
- top-15 中少于 8 个参数具有稳定局部导数；
- top-15 一步试验总体和响应指标均无实质改善；
- top-15 更新集中撞击同一组边界；
- 用户明确要求比较 top-15 与 top-23。

Top-23 不默认同时跑 A/B 两臂。优先使用阶段 1 中表现更好的目标函数臂，以控制计算量。

### 阶段 3：正式 GLM

- 从一步试验中选择 10–15 个局部有效参数；若 top-23 的有效秩充分，可最多保留 18 个，但不得无筛选地把 23 个全部送入正式优化。
- 默认 `noptmax=5`，最大允许 7；超过 5 需要在运行清单记录原因。
- 使用截断 SVD；`maxsing` 不得高于有效参数数目。
- 连续两次迭代总 Phi 改善不足 0.5%时停止。
- 若任一季累积干重 NSE 比基线下降超过 0.08，提前停止并保留诊断结果。
- 正式阶段使用 6 agents。

### 阶段 4：确定性候选复跑

至少复跑以下候选：

- GLM 最低 Phi。
- 满足工程门槛后两季累积干重平均 NSE 最高。
- 满足工程门槛后四个 N/W 响应 NSE 平均最高。
- GLM 最终参数。
- 成员 126 基线。

## 8. PEST-GLM 数值设置

- 复用正式多季 PST 的模板、指令文件和 model command。
- PST 模式设为 estimation。
- 删除或隔离 IES 专用选项，防止 GLM 读取无关 ensemble 配置。
- 参数差分步长默认是 GLM 范围的 1%；对核心参数抽查 0.5%和2%。
- 差分必须尊重边界，禁止生成越界模板值。
- 初始阶段不使用超参数自动扩边。
- 使用 SVD 处理局部不可辨识方向。
- 若 Jacobian 条件数过高或有效秩低于参数数目的 60%，优先删减参数；不要先用强正则化掩盖问题。
- 如删减后仍秩亏，可增加以成员 126 和 IES 后验标准差为尺度的弱 preferred-value regularization，并将测量 Phi 与正则 Phi 分开报告。
- GLM 的 lambda、SVD、差分和停止设置必须写入机器可读运行清单，不得只存在于控制台命令。

## 9. 代码开发工作包

### WP1：GLM 构建器

新增建议：

- `tools/calibration/prepare_ies_to_glm_20260818.py`

职责：

- 读取正式 IES PST、最终参数集合、成员 126 和批准 SA top-k。
- 支持 `--pool top15|top23`。
- 支持 `--objective-arm A|B|C`。
- 生成 GLM 专用 PST、bounds、初值、参数池审计和目标函数审计。
- 固定未选遗传参数和全部土壤/IC参数。
- 移除 IES 专用选项。
- 不覆盖正式 IES 目录。

### WP2：并行执行器 GLM 支持

修改：

- `tools/parallel/run_parallel.py`

要求：

- `--mode` 增加 `glm`。
- 路由到 `pestpp-glm.exe`。
- 沿用 manager/agent 沙箱隔离、端口选择和 agent guard。
- 增加 GLM 完成标志、失败标志和返回码解析。
- `--resume` 是否支持必须经过实际验证；未验证前明确拒绝，不得假装恢复。
- 现有 IES/SEN 行为不得改变。

### WP3：局部 Jacobian 审计器

新增建议：

- `tools/calibration/analyze_glm_jacobian_20260818.py`

输出：

- `jacobian_parameter_sensitivity.csv`
- `jacobian_column_correlation.csv`
- `jacobian_singular_values.csv`
- `derivative_step_stability.csv`
- `recommended_formal_parameter_set.csv`
- `jacobian_audit.json`

局部复合敏感度必须同时报告原始量纲和缩放后结果，并按全部目标、DRY_CUM、N_RESPONSE、W_RESPONSE、器官目标分别汇总。

### WP4：正式启动器

新增建议：

- `tools/calibration/launch_glm_followup_20260818.py`

CLI 至少支持：

```text
--stage pilot|formal
--pool top15|top23|selected
--objective-arm A|B|C
--noptmax N
--agents N
--variant official
--port PORT
--wait / --background
```

启动器必须先完成 preflight，失败时恢复 DSSAT 默认 EXE/SPE。

### WP5：结果评价器

新增建议：

- `tools/calibration/evaluate_glm_followup_20260818.py`

要求：

- 计算总体拟合、器官 NSE、累积干重 NSE/PBIAS、N_RESPONSE、W_RESPONSE 和边界压力。
- 使用本方案的工程门槛和科学优选规则。
- 输出每次迭代和每个候选的确定性结果。
- 不跨目标函数臂直接比较绝对 Phi。
- 生成机器可读晋级结论和人工审核表。

## 10. 目录和产物契约

建议 case 命名：

```text
e02_glm_A_top15_pilot_official_20260818
e02_glm_B_top15_pilot_official_20260818
e02_glm_<arm>_top23_pilot_official_20260818
e02_glm_<arm>_<npar>p_formal_official_20260818
```

每个运行目录必须包含：

- `run_manifest.yaml`
- `glm_design.json`
- `source_ies_manifest.json`
- `selected_parameters.csv`
- `glm_parameter_bounds_audit.csv`
- `objective_weight_audit.csv`
- `run_status.json`
- GLM PST/Jacobian/record/parameter files
- `glm_quality/engineering_quality.json`
- `glm_evaluation/candidate_metrics.csv`
- `glm_evaluation/promotion_decision.json`

不得写入或修改正式 IES 原目录中的 PST、ensemble 或 finalize 文件。

## 11. 测试要求

### 单元测试

- top-15/top-23 顺序与批准 CSV 完全一致。
- 参数名大小写规范化正确。
- 后验边界计算、padding、冻结边界裁剪正确。
- 成员 126 必须位于全部 GLM 边界内。
- soil/IC 参数全部固定。
- A/B/C 目标函数权重与设计一致。
- NSE 权重满足 `phi = lambda × (1-NSE)` 数值恒等式。
- W_RESPONSE 严格为 W2-W1。
- 25SP/26SP 处理数严格为10/12。

### 回归测试

- `python -m pytest tests/test_migration.py`
- `python -m pytest tests/test_publication_figures.py`
- 现有 IES/SEN 并行模式行为保持不变。

### 集成测试

1. GLM `noptmax=0` 或等价构建检查。
2. 2 agents、top-15、A臂、`noptmax=1` 烟雾试验。
3. 6 agents、top-15、A/B一步正式试验。
4. 验证 manager 正常退出、agent 无残留、默认 EXE/SPE 已恢复。

## 12. 开发完成判定

只有同时满足以下条件，才能向用户申请启动正式 GLM：

- GLM 构建器、并行模式、Jacobian审计器、评价器均已实现。
- 单元、迁移和相关回归测试全部通过。
- top-15 A/B 一步试验均有完整工程质量报告。
- 参数池、初值、边界、目标函数和响应定义均可从机器可读文件复核。
- 没有修改正式 IES 结果和原始/用户输入数据。
- 已确定推荐的正式目标函数臂和正式参数集合。
- 用户明确批准正式运行。

## 13. 推荐默认执行路线

开发代理应按以下顺序工作：

1. 实现 WP1/WP2 和单元测试。
2. 完成 top-15 A臂 `noptmax=1` 烟雾试验。
3. 实现 WP3/WP5 并审计该试验。
4. 运行 top-15 A/B 一步对照。
5. 判断是否需要 top-23。
6. 提交正式参数集合、边界和目标函数臂供用户审核。
7. 获得用户批准后，才运行正式 GLM。

