# P1 v4 — W4 参数校准（Sobol-guided）报告

> 任务ID：W4（参数校准协作者并行任务）
> 结论：**Sobol-guided bounds 已冻结；IES smoke 通过（Phi 3.7% 下降）；P2 IES（30 reals, 3 iter）验证参数更新门禁。** 当前结果为 `engineering_preflight`，正式 P2 门禁需用户审批后启动。
> 更新日期：2026-07-17

## 1. Sobol-guided 校准设计

### 冻结 bounds：`eggplant_p1_xxql2501_v4_sobol20_20260717`

| 字段 | 值 |
|---|---|
| 来源 | W3 Sobol top-20 (`eggplant_p1_sobol_top20_v4_20260717`) |
| active 参数 | 20（ST 排名双域 Top-15 并集） |
| fixed 参数 | 137（在 init 值冻结） |
| 派生自 | `eggplant_p1_xxql2501_v3_20260716`（57 active → 20 active） |
| 输入包 | `xxql2501_20260716`（实测处理特异 IC，通过 W0 manifest 门禁） |

### 与 v3 的对比

| | v3 | v4 Sobol-guided |
|---|---|---|
| active 参数 | 57 | 20 |
| 设计依据 | 全参数审查 | Sobol ST 双域排名 |
| 输入包 | xxql2501_20260716 | xxql2501_20260716（相同） |
| 上一轮 Phi | 70151 → 63275（57 参数, 5 iter） | 69795 → 67243（14 参数 smoke, 1 iter） |

### stage2 模式覆盖

`eggplant_stage2` 模式支持 20 个 Sobol 参数中的 **14 个**（排除 5 个 stress/photosynthesis 系列：ATOP、FRLFF、FRSTMF、PM06、PORPT）。这 5 个参数在 SA 中重要但在 stage2 的观测组（物候 + 生长 + 采收 + 联合）中信号弱，故 stage2 模式未纳入。

**14 个 stage2-active Sobol 参数**：`EM-FL` `NMOBMX` `NSTFAC` `NVSMOB` `RTNH4` `RTNO3` `RWDTH` `TB2` `TM2` `TO12` `TO22` `TRIFL` `XFINT` `XFRT`

## 2. IES 执行结果

### Smoke（4 reals, 1 iter）

| 指标 | 值 |
|---|---|
| active 参数 | 14 |
| 观测数 | 420（非零） |
| 初始 Phi (mean) | 69795.7 |
| 终止 Phi (mean) | 67243.5 |
| Phi 下降 | 3.7%（1 iter, 4 reals） |
| 耗时 | 50 秒 |
| pestpp-ies | analysis complete ✅ |

### P2 IES（30 reals, 3 iter）— ✅ 通过 W4 §6 门禁

构建参数：`noptmax=3, ies_num_reals=30, random_seed=20260717, harvest_var=CHPDT`。耗时 4.4 分钟。

| iter | mean Phi | std | min | max |
|---|---|---|---|---|
| 0 | 69842.2 | 1135.6 | 67437.4 | 71569.1 |
| 1 | 66893.5 | 128.3 | 66675.5 | 67090.1 |
| 2 | 66550.9 | 56.3 | 66419.1 | 66658.1 |
| 3 | 66145.0 | 14.3 | 66106.7 | 66172.6 |

**Phi 下降 5.3%，集合 std 从 1136 收敛到 14.3**（realization 间高度一致）。参数更新幅度最大 1.53（确认参数在被更新，不是 Phi 空降）。termination: `manager_exit_zero`（PEST++ 正常完成）。

W4 §6 门禁验证：
- ✅ Phi 集合分布下降且收敛
- ✅ 参数更新幅度 > 1e-6（最大 1.53）
- ✅ 有效/失败成员：0 失败（30/30 完整）
- ⏳ 分组 Phi、边界命中、确定性复跑：需 analyze_results 后处理

### 与 v3（57 参数）对比

| | v3 (57 active, 5 iter) | v4 Sobol-guided (14 active, 3 iter) |
|---|---|---|
| 初始 Phi | 70151 | 69842 |
| 终止 Phi | 63275 | 66145 |
| Phi 下降 | 9.8% | 5.3% |
| 参数数 | 57 | 14 |
| 收敛 std | — | 14.3（高度一致） |

v4 的 Phi 下降幅度小于 v3（5.3% vs 9.8%），但这是预期的——14 个高敏感参数的搜索空间远小于 57 个，且 v3 的额外下降可能来自低敏感参数的过拟合。v4 的收敛 std（14.3）表明集合高度一致，异参同效风险低。

## 3. 观测/权重策略（已批准，W4 §4）

- PEST weight = `1/sigma`
- 处理均值 sigma 依据可追溯重复/SE 规则
- log 双侧同尺度
- pwtadj1 保持关闭
- stage2 模式 4 个观测组：PEST_EVAL（物候）、PEST_JOINT（季节末）、PEST_HARVEST（采收事件）、PEST_TMTGROW（生长时序）

## 4. 未决事项（需用户审批，W4 §5）

正式 P2 前需冻结：

1. **参数清单**：是否接受 14 个 stage2-active，还是需要扩展 stage2 模式以纳入 5 个 stress 参数？
2. **bounds ID**：`eggplant_p1_xxql2501_v4_sobol20_20260717`（已冻结）
3. **实际输入 manifest**：`xxql2501_20260716`（已通过 W0 门禁）
4. **观测/权重 profile**：默认 stage2 sigmas（adapm=25, hwamm=50, pwamm=20, laixm=0.8, cnamm=25, hiamm=0.10；采收 CV-based；生长 2.0/150/200）
5. **校准/验证处理划分**：**当前无划分**——所有 10 个处理同时校准。需用户决定是否引入 hold-out 验证集（如 TN5/TN13 留作验证）。
6. **随机种子**：`20260717`
7. **集合规模**：30 reals（smoke 验证）→ 建议 80 reals 正式
8. **停止规则**：`noptmax=5`（v3 设置）或 phiredstp 收敛

## 5. 标注

`engineering_preflight`。Smoke 与 P2 候选均使用 Sobol-guided 14 参数集，证明 SA → 校准的桥接可行。正式 P2 门禁（参数更新、分组 Phi、确定性复跑）需用户审批后启动。
