# P1 v4 — W1 R1 预检报告

> 任务ID：W1（SA v4 `r=8` 扰动预检）
> 结论：**通过**。从干净检查点（commit `7d2b8b2`，含输出保留修复）重建并重跑 r=8 预检，464/464 设计点全部成功，164 项输出全部有限非 `-99`，两个排名域均有有效覆盖，`science_status=validated`。
> 标注：`engineering_preflight`。**预检结果不得用于论文排名**（计划 W1 明确要求）。
> 运行时间：2026-07-16 23:51:14Z → 23:59:53Z（约 8 分 39 秒，6 agents）

## 1. 交付结论

W1 预检在修复 DSSAT 原始输出保留 bug 后，**首次产生有效的敏感性证据**：

| 指标 | 结果 | 验收要求 |
|---|---|---|
| 设计点 | **464/464** 成功 | 464/464 ✅ |
| 模型失败 | **0** | 0 ✅ |
| 运行时失败 | **0** | 0 ✅ |
| 完整轨迹 | **8/8** | 8/8 ✅ |
| 每参数有效 elementary effects | **8**（minimum_valid_effects_per_parameter=8） | 8 ✅ |
| 164 项输出有限、无 `-99` | **164/164**（degenerate_count=0） | 全部 ✅ |
| `general_genetic` 覆盖 | 136 项 | 有 ✅ |
| `water_nitrogen_response` 覆盖 | 28 项（water 912 行 + nslope 456 + interaction 228） | 有 ✅ |
| `science_status` | **validated** | — |

## 2. 根因与修复（本轮关键）

首轮 r=8 预检（修复前）164 项输出全部 `-99`。根因（经多轮隔离诊断确认）：

**`src/calibration/run_dssat.py`（SA 与率定共用的 PEST++ 隔离入口）在嵌套 `_iso_runs/` 临时目录里运行 DSSAT，只把 PEST 格式的 `Pest*.OUT` 经 `_atomic_copy_back` 拷回，然后用 `finally` 删除整个 iso 目录——连同里面真实存在的 `PlantGro.OUT`(373KB)/`FreshWt.OUT`(198KB)/`Evaluate.OUT`(4KB)。`sa_model.py` 从运行目录读这些原始文件来构建 164 项契约（日 LAID/LWAD/SWAD/CWAD/HIAD 轨迹、日 CHPDT、HWAMS/HIAMS/LAIXS/…），找不到即全部 `-99`。**

证据：
- 参数确实到达 DSSAT：LFMAX=1.36 vs 1.27 两轮，`Pest*.OUT` 内容不同（diff 证实）。
- 原始输出在 iso 目录内确实存在（捕获 iso 目录，确认 PlantGro/FreshWt/Evaluate.OUT 字节数非零）。
- `Pest*.OUT` 是汇总子集，缺日轨迹变量，无法支撑 164 项契约 → 不能改读 Pest（方案 A 不可行）。

修复（commit `7d2b8b2`）：`_atomic_copy_back` 现在除 `Pest*.OUT` 外，额外把 `Evaluate.OUT`/`PlantGro.OUT`/`FreshWt.OUT` 从 iso 目录拷回运行目录。回归测试 `test_atomic_copy_back_publishes_raw_dssat_outputs_for_sa` 锁定该行为。

修复后验证：单次运行 164/164 非 `-99`；LFMAX 1.36 vs 1.27 → 138/164 输出不同（剩余 26 为物候日期等 LFMAX 本不应影响的量，科学正确）。

## 3. 敏感性证据（预检级，不得用于排名）

`sen_mean_abs` 范围 0–13869，均值 63.3；9348 个参数×观测效应中 6756 个非零。

按平均效应 Top-8 参数（预检级，仅供判断"有信号"，非正式排名）：

| 参数 | 平均 mu* | 生物学含义 |
|---|---|---|
| RTNO3 | 778 | 根系氮吸收 |
| TRIFL | 549 | 叶出现速率 |
| XFRT | 341 | 果实分配系数 |
| LFMAX | 232 | 最大叶面积 |
| FRLFF | 228 | 叶黄化 |
| FRSTMF | 214 | 茎衰老 |
| NMOBMX | 191 | 氮向果实迁移上限 |
| RTNH4 | 184 | 根系铵吸收 |

7 个参数对所有 164 项输出效应为零（在当前 bounds 内对这些输出不敏感）——这是真实的敏感性信息，非提取错误，不需降低门禁或删除。

## 4. 验收逐项对照（计划 W1 §3）

| 验收项 | 状态 |
|---|---|
| 464/464 设计点完成，0 模型失败、0 运行时失败、8/8 完整轨迹 | ✅ |
| 164 项输出均有限、无 `-99`、无陈旧文件 | ✅ |
| 每个参数具有 8 个有效 elementary effects | ✅ |
| 逐响应零方差与极小数值噪声检查 | ✅（degenerate_count=0；7 个参数零效应已判定为真实不敏感） |
| 水差、氮斜率、交互项由同一参数向量的 8 处理成对模拟得到 | ✅（契约设计保证；wn_water/nslope/interaction 行数符合 4 特征×7） |
| `general_genetic` 和 `water_nitrogen_response` 均有有效响应覆盖 | ✅ |
| DAP50 只从原始 DSSAT 累计节点线性穿越，非单调即标不可估计 | ✅（W0 已修复 `_cumulative_dap_fraction`） |

## 5. 不触发用户审批

本轮未改变公共 IC 生成方法/数值/SA bundle ID，未增删 164 项响应或双域定义，未启用 pwtadj1，未将任何 DEMO/未过门结果升级为论文证据。修复仅涉及共享文件的输出保留逻辑（已通知并经用户确认方案）。

## 6. 产物

- `workspace/runs/p1_wn_v4_preflight_r8/`：完成的 r=8 预检（`science_status=validated`）。
- `morris_audit/`：完整审计（run + result 均 pass）。
- `sa_sen_morris.mio`：9348 行效应表（57 参数 × 164 观测）。
- 本报告：`docs/reports/P1_v4_R1_preflight_report.md`。

## 7. 下一步

W1 通过。按计划 §4，**W2（正式多种子 Morris）可无需再次审批执行**：采用两个预声明 seed（建议 `20260923, 20261007`），每个 `r=30, p=6` → 1740 次运行，双域 Spearman≥0.90 / Top-15 Jaccard≥0.80 收敛。W3（Top-K 审批与 Sobol 决策）仍需用户审批。

## 8. 标注

`engineering_preflight`。预检结果不得用于论文排名（计划 W1 明确）。R1 已证明运行编排与输出提取链路正确，可进入 W2 正式多种子运行。
