# E02 v46 best71：逐步优化氮响应的剖面结果与协作者交接方案

日期：2026-08-31  
基线：`e02_formal_v46_step20_custom26sp_20260831_200x4` 的确定性成员 71  
范围：25SP 10 个处理、26SP 12 个处理；25FA 不参与本阶段调参

## 1. 本阶段已经完成的工作

已运行确定性单参数/窄网格剖面脚本：

`D:/Tomato_Cal/tools/calibration/profile_v46_best71_nitrogen_20260831.py`

输出目录：

`D:/Tomato_Cal/workspace/reports/e02_v46_stepwise_nitrogen_20260831/`

主要证据文件：

* `profile_results.csv`：36 个案例的原始结果；
* `profile_scorecard.csv`：按 25SP/26SP、N2−N0/N1−N0 汇总后的筛选结果；
* `design_all22.json`：本阶段确定性复跑所用处理清单。

覆盖的剖面为：

* `NSTFAC`：0.55、0.65、0.70、0.80、0.90；
* `RTNO3`：0.025、0.030、0.033、0.040、0.050；
* `NMOBMX`：0.20、0.30、0.40、0.50、0.60；
* `PROLFI`：0.16、0.20、0.21、0.24、0.28；
* `PROLFG/PROSTG/PRORTG` 联合缩放：0.80、1.00、1.15；
* `PROLFI/PROSTI/PRORTI` 联合缩放：0.90、1.00、1.10；
* `FNPGN1 × FNPGN2`：3×3 窄网格（FNPGN1=0.70/0.90/1.10，FNPGN2=3.80/4.15/4.50）。

每个案例实际写入了生成的 `TMGRO048.SPE`。例如 `NSTFAC=0.55`、`RTNO3=0.025`、`FNPGN1=1.10/FNPGN2=4.50` 均可在对应案例的 SPE 行中回读，故本阶段未发现参数注入失效。

## 2. 剖面结果与数据质量判断

### 2.1 总体结果

共 36 个案例、每个案例 20 个完整响应记录（25SP 4 个、26SP 6 个，分别计算 N2−N0 和 N1−N0），没有 DSSAT 运行失败或缺失记录。

以基线的 N2/N1 响应绝对误差均值 3523.59 为参照：

| 机制 | 最优剖面 | 响应绝对误差 | 相对基线 | 伴随现象 |
|---|---|---:|---:|---|
| `FNPGN1/FNPGN2` | 1.10 / 4.50 | 3082.14 | −12.53% | 26SP LAI NSE 仍约 −2.38，未解决跨处理冠层问题 |
| `RTNO3` | 0.025 | 3125.85 | −11.29% | 25SP/26SP 产量趋势基本保持，但 26SP N1-W3 的观测对照本身为负 |
| `PROLFI/PROSTI/PRORTI` | 0.90× | 3239.96 | −8.05% | 26SP LAI NSE 降至约 −2.92，不宜直接晋级 |
| `NMOBMX` | 0.20 | 3323.67 | −5.67% | 只产生中等改善 |
| `PROLFG/PROSTG/PRORTG` | 1.15× | 3495.39 | −0.80% | 影响很小 |
| `NSTFAC` | 0.55–0.80 | ≈3523.59 | 约 0% | 在当前基线和输出链下几乎没有可识别响应 |

当前基线的绝对指标为：25SP LAI NSE 0.472、26SP LAI NSE −2.465、25SP 累积鲜重 NSE 0.825、26SP 累积鲜重 NSE 0.927。这里的 26SP LAI NSE 很差，说明“相对基线不下降 0.05”只能作为保护性门槛，不能被误读为模型已通过绝对冠层质量验收。

### 2.2 关键数据条件

26SP 的 N1-W3 观测终端鲜重对照（TN7−TN9）为 −1006 g m⁻²。该值来自现有实测数据，不能在本阶段通过强制每个水分层方向为正来修正。后续必须：

1. 继续按季节、完整水分层分别计算 N2−N0 和 N1−N0；
2. 硬门槛使用每季两类差值的均值，而不是跨季节、跨变量合并 SST；
3. 单独报告 26SP N1-W3 这一负观测对照，避免把数据条件误判成参数注入错误。

### 2.3 当前筛选代码的限制

`profile_scorecard.csv` 中的 `protected_fit_pass` 是“相对本基线 NSE 不下降 0.05”的保护性判断。因此 FNPGN/RTNO3 案例会显示 `screen_pass=True`，但这不表示它们已经达到科学验收标准。下一阶段不得只依据 `screen_pass` 或旧版 N3 字段晋级，必须重新计算 N2/N0、N1/N0、末次鲜产量 RRMSE/PBIAS、LAI、W_RESPONSE 和边界压力。

## 3. S0：进入局部 IES 前必须修正的目标合同

当前 v46 配置仍引用：

* `configs/runs/e02_from_scratch_objective_contract_20260826.csv`；
* `configs/runs/e02_group_policy_v40_formal_fresh_3x_yield.csv`。

在生成下一轮控制文件前，协作者必须从这两份文件派生一份带新版本号的合同，并完成权重审计：

1. `CANOPY`、`CANOPY_INCREMENT` 的 Phi 权重设为 0；`LAIXM` 保持 `diagnostic_only`；仅保留按最后一次 LAI 观测日配对的 `CANOPY_TERMINAL`。
2. `N_RESPONSE` 不再只用 N3−N0。必须纳入 N2−N0 和 N1−N0，按“季节×水分层×氮对照”分组计算 SST，禁止跨变量或跨季节共用分母。
3. 保持鲜重目标与干重目标的口径一致：事件鲜重增量 + 季末真实观测日的累积鲜重，虚拟收获事件不得进入产量比较或 N 响应计算；末次产量验收使用 RRMSE 和 PBIAS，不用 NSE 代替。
4. 目标合同的 N 响应权重先使用 λ=1；只在 B 臂单独测试 λ=2。不要在所有臂同时提高 λ。
5. 合同、mapping、group-weight audit、run manifest 中的 active 参数数量必须由实际 frozen bounds 自动生成，不能沿用“122 active”之类的旧元数据。

建议新增文件名（由协作者实际生成并写入 manifest）：

`configs/runs/e02_v46_best71_n12_objective_contract_20260831.csv`  
`configs/runs/e02_v46_best71_n12_group_policy_20260831.csv`

## 4. 下一阶段局部多臂 IES 配置

只有完成 S0 合同审计后才运行以下 5 臂。每臂 60 realizations、`noptmax=3`、6 agents、官方 DSSAT v4.8。所有非本臂参数固定为 v46 best71；特别是水分、土壤、源库、PHTMAX、产量参数和冠层参数不得同时释放。

| 臂 | 目的 | 激活参数/设置 | 建议局部范围 |
|---|---|---|---|
| A | 局部氮基线 | 修正后的 N2/N1 响应合同，λ=1；保留最小可识别通道 | FNPGN1 0.88–0.92、FNPGN2 4.05–4.20、RTNO3 0.032–0.034 |
| B | 权重敏感性 | 与 A 相同，N_RESPONSE λ=2 | FNPGN1 0.88–0.92、FNPGN2 4.05–4.20、RTNO3 0.032–0.034 |
| C | 吸收—供需触发 | `RTNO3` | 0.025–0.040；`RTNH4` 固定 best71，先避免混淆硝态/铵态通道 |
| D | 蛋白需求—氮动员 | `PROLFI`、`PROSTI`、`PRORTI`、`NMOBMX`、`NVSMOB` | 三个 PRO*I 以 best71 的 0.90–1.05 倍；NMOBMX 0.20–0.45；NVSMOB 0.55–0.80 |
| E | 叶氮—光合响应 | `FNPGN1`、`FNPGN2`、`LNREF`、`NSLOPE` | FNPGN1 0.90–1.10；FNPGN2 4.15–4.50；LNREF 3.5–4.2；NSLOPE 0.08–0.14 |

说明：A/B 保留一个极窄但非零的本地参数通道，以便验证 IES 的参数—输出可识别性；它们不是“零活动参数”的空运行。C/E 的范围来自本次确定性剖面中最有响应的方向；D 只允许小范围释放，防止用蛋白需求参数替代真实吸收过程。不要恢复 v37/v40 的全部参数，也不要把 `NSTFAC` 作为无证据的主调参参数；本次剖面显示它在当前通道内几乎不可识别。

历史边界诊断中曾出现 `WTFSD`、`SFDUR`、`PARMAX`、`XFRMAX` 和 `PHTMAX` 的边界压力（包括成员 153 的边界附近聚集）。这些参数会显著影响产量尺度或源库分配，当前局部氮试验必须全部固定在 best71 值，不得与 C/D/E 同时释放；若氮臂通过而产量仍有系统偏差，再单独开展产量尺度参数的三点剖面。

## 5. 晋级规则（必须逐项满足）

### 5.1 工程门槛

* 所有 agent 和 manager 正常退出；无缺失 observation、NaN、重复 TN/HNO；
* 至少一个正 Phi 权重的模拟观测列在参数 lower/init/upper 三点测试中发生非零变化；`ies_simulation_variation < 1` 直接判工程失败；
* 生成的 CUL/ECO/SPE 固定宽度、soil bundle 哈希和输入 manifest 一致。

### 5.2 氮响应门槛

* 25SP 的 `(N2−N0)` 均值 > 0 且 `(N1−N0)` 均值 > 0；
* 26SP 的 N2/N1 响应绝对误差相对 A 臂至少降低 30%；
* 20 个 N2/N1 响应记录中至少 3 个水分层/氮对照的绝对误差改善；
* 对 26SP N1-W3 的负观测值只作诊断记录，不以单层方向替代季节均值门槛。

### 5.3 保护性科学门槛

* 两季真实末次鲜产量 RRMSE ≤25%，且 |PBIAS| 相比 A 臂不恶化超过 5 个百分点；
* 两季累积鲜重 NSE、LAI NSE 相比 A 臂下降均不得超过 0.05；
* W_RESPONSE（按季节×氮层单独 SST）不得明显退化；
* N 响应改善不能以牺牲总体鲜重尺度、末期叶/茎状态或水分响应为代价。

只有 C、D、E 中出现明确赢家，才允许组合 F；F 只组合已证明产生可识别输出变化的参数，仍固定所有其他参数。A/B 若继续出现零模拟变异，应保留为工程失败记录而不是增加 realizations 掩盖问题。

## 6. 结果文件与复现要求

协作者完成后必须在一个新的报告目录中保存：

* 每臂的配置、控制文件、`run_manifest.yaml`、IES quality 报告；
* 每臂最终 iteration 的 Phi、simulation variation、参数边界压力；
* 全 22 处理确定性复跑的 N2/N0、N1/N0 分层表；
* 末次鲜重 RRMSE/PBIAS、累积鲜重 NSE、LAI NSE、W_RESPONSE；
* 候选晋级表，明确 `engineering_pass`、`n_gate_pass`、`protected_fit_pass` 和最终 `promotion_pass`；
* 本文档所列的旧合同风险是否已修复的逐项审计结果。

推荐先运行确定性 A 的三点参数通道测试，再启动五臂并行率定。若没有任何臂同时通过氮响应和保护性门槛，应停止扩参，转而检查 26SP N 观测/土壤供氮输入与输出变量对应关系，而不是继续盲目扩大参数范围。

本轮已生成可执行脚本：

* 配置与 bounds 生成：`D:/Tomato_Cal/tools/calibration/setup_v46_best71_nitrogen_multiarm_20260831.py`；
* 构建、审计和启动：`D:/Tomato_Cal/tools/calibration/launch_v46_best71_nitrogen_multiarm_20260831.py`；
* 完成后的全 22 处理复跑与门槛：`D:/Tomato_Cal/tools/analysis/evaluate_v46_best71_nitrogen_multiarm_20260831.py`。

这些脚本已完成 build-only 审计；当前 A 臂正在运行，B–E 已完成构建审计并按顺序等待执行。运行目录为：

`D:/Tomato_Cal/workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831/`
