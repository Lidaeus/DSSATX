# 二次 Code Review：P0 级别修复及其执行记录

> 日期：2026-07-24
>
> 审查范围：P0-A / P0-B / P0-C / P0-D 四个工作包的代码实现与实施记录，以及 E01 预率定执行准备、E01→E02 边界提取桥两个相邻包
>
> 审查模式：只读审查，不修改任何代码
>
> 测试基线：110 passed（11 个 P0 相关测试文件），无回归

## 1. 审查对象与实际完成状态

| 工作包 | 实施记录 | 代码实现 | 测试 | 实际状态 |
|---|---|---|---|---|
| P0-A 权重变换单一入口 | ✅ 20260724 | ✅ build_pest.py 3 处改动 | 6 新增 + 65 回归 | ✅ 完成 |
| P0-B 参数集与试验声明 | ✅ 20260724 | ✅ experiment_spec/runner + 9 spec | 37 passed | ✅ 完成 |
| P0-C 消除跨季节全局状态 | ✅ 20260724 | ✅ SeasonContext + lazy import + run_execute | 86 passed, 2 skipped | ✅ 完成 |
| P0-D 统一指标与残差 | ✅ 20260724 | ✅ metrics/residual_diagnostics/eval | 69 passed | ✅ 完成 |
| P0-E 工程质量门与旧路径退役 | ⬜ 无 | ⬜ 未实施 | — | ⬜ 待做 |
| E01 预率定执行准备 | ✅ 20260724 | ✅ 5 spec + 3 policy + 5 design + runner fix | 12 新增 | ✅ 完成 |
| E01→E02 边界提取桥 | ✅ 20260724 | ✅ extract_bounds_from_posterior | 11 passed | ✅ 完成 |

## 2. 核心发现

### C1 [严重·文档不一致] E01 实施记录中 P0 状态声明错误

**位置**：`docs/reports/E01_预率定执行准备_实施记录_20260724.md` §7

**现象**：
- §7 声称"正式运行需 P0-C（消除跨季节全局状态）完成后，由项目负责人用 `--execute` 启动"
- §7 声称"P0-A 未完成：observation profile JSON 与 policy CSV 的映射仍隐式"
- 实际：P0-A 和 P0-C 均已完成（有 2026-07-24 实施记录，代码已落地，测试已通过）

**根因**：E01 实施记录撰写时只检查了 P0-B 和 P0-D 的实施记录，未检查 P0-A 和 P0-C 是否已存在。这是一个审查遗漏——在撰写实施记录前未完整扫描 `docs/reports/` 目录。

**影响**：
- 误导后续工作决策：按 §7 建议，后续会等待"P0-C 完成"才启动 E01 正式运行，但 P0-C 实际已完成
- 低估了系统就绪度：E01 正式运行（`--execute`）实际已解锁（P0-C 的 `run_execute()` 已实现）

**建议**：更正 E01 实施记录 §7 的 P0 状态声明。实际阻塞 E01 正式运行的是 P0-E（legacy mode 退役），不是 P0-A 或 P0-C。

---

### C2 [中·文档过时] 跨包进度表不一致

**位置**：P0-A/B/D 实施记录各自的 §7 进度表

**现象**：各包的进度表反映的是各自完成时的快照，没有更新为最终状态：

| 实施记录 | 进度表声称 | 实际状态 |
|---|---|---|
| P0-A §7 | P0-C 待做、P0-E 待做 | P0-C 已完成 |
| P0-B §7 | P0-A/C/E 待做 | P0-A/C 已完成 |
| P0-D §7 | P0-B/A 待做 | P0-B/A 已完成 |

**根因**：各包按顺序实施，每包完成时更新自己的进度表，但不回溯更新先前包的进度表。这是顺序实施流程的固有问题，但会造成状态追踪混乱。

**影响**：新读者如果只看某一包的进度表，会得到错误的整体状态认知。

**建议**：在 `docs/reports/` 维护一个 `P0_总进度.md` 汇总文件，作为唯一权威进度来源；或在每包进度表注明"以最新包进度表为准"。

---

### C3 [中·文档未更新] P0-B 实施记录的 observation-policy 硬指向说明已过时

**位置**：`docs/reports/P0-B_参数集与试验声明_实施记录_20260724.md` §5.2

**现象**：
- P0-B §5.2 说"observation-policy 硬指向 — 当前可接受；direct_chpdt_log_v1 profile 与 v5_dryonly CSV 是唯一映射，待后续 profile 增多时再泛化"
- 实际：E01 预率定执行准备已将 `_resolve_observation_policy_csv()` 泛化为从 multiseason design JSON 的 `observation_policy` 字段读取
- P0-B 实施记录没有更新

**根因**：E01 修改了 P0-B 引入的函数，但未回溯更新 P0-B 实施记录的"未解决风险"部分。

**影响**：读者会以为 observation-policy 仍然硬指向，可能重复实施泛化。

**建议**：在 P0-B 实施记录 §5.2 添加更新注记："已在 E01 预率定执行准备中泛化，参见 E01 实施记录 §2.4"。

---

### C4 [低·已知风险] P0-A improved 拒绝不覆盖 legacy mode

**位置**：`src/calibration/build_pest.py` line 2972-2980

**现象**：`weight_scheme=improved` 拒绝逻辑仅覆盖 `eggplant_stage2` 和 `eggplant_joint` 两个正式模式。legacy mode（`eggplant_harvest`、`eggplant_process` 等）仍可使用 `weight_scheme=improved`，且这些 mode 有已知 bug（CodeReview_BuildPest构建模块 C1/C2 NameError）。

**根因**：P0-A 实施记录 §6.3 已明确说明这是 P0-E（legacy mode 退役）范围。这是刻意的范围划分，非缺陷。

**影响**：在 P0-E 完成前，legacy mode + improved 仍可运行，可能产生不可审计的权重。

**建议**：P0-E 实施时应优先拒绝 legacy mode 的 improved 路径，或直接退役 legacy mode。

---

### C5 [信息] P0-D 游程检验 n<8 阈值偏宽松

**位置**：`src/reporting/residual_diagnostics.py` line 43-44

**现象**：游程检验在 n<8 时返回 `not_tested`。NIST e-Handbook 建议 n<10 时使用精确分布表而非正态近似。

**根因**：P0-D 实施记录 §5.2 已说明"若后续 n∈[8,15] 需精确分布可补查表"。这是一个已知的精度取舍，非缺陷。

**影响**：n∈[8,9] 的游程检验使用正态近似，可能略有偏差。但农业试验数据通常 n≥8 时已有合理样本量。

**建议**：若后续试验中 n∈[8,9] 的游程检验结果进入论文，可补充精确分布表。当前不阻塞。

## 3. 代码实现审查（逐包）

### 3.1 P0-A 权重变换单一入口 — ✅ 通过

| 审查项 | 结果 | 证据 |
|---|---|---|
| improved 拒绝逻辑正确 | ✅ | [build_pest.py:2972-2980](file:///d:/Tomato_Cal/src/calibration/build_pest.py#L2972-L2980) — `SystemExit` with 清晰错误消息 |
| 5 死导入移除彻底 | ✅ | [build_pest.py:24-27](file:///d:/Tomato_Cal/src/calibration/build_pest.py#L24-L27) — 仅保留活导入 `WEIGHT_POLICY_ID`/`weight_from_sigma` |
| 双权重块删除 | ✅ | line 2195/2481 注释说明已删除；grep 无 `build_observation_weights(` 调用 |
| 测试覆盖充分 | ✅ | 6 测试：拒绝逻辑、源码检查、端到端权重来源审计 |
| 向后兼容 | ✅ | `weight_scheme` 参数保留在签名中；CLI choices 仍含 improved（避免破坏旧脚本 argparse） |

### 3.2 P0-B 参数集与试验声明 — ✅ 通过

| 审查项 | 结果 | 证据 |
|---|---|---|
| SHA-256 钉扎完整 | ✅ | experiment_spec.py line 236 |
| 参数计数匹配强制 | ✅ | experiment_spec.py line 182 |
| 禁用变量拒绝 | ✅ | experiment_spec.py line 202 |
| run_build() 实现正确 | ✅ | [experiment_runner.py](file:///d:/Tomato_Cal/src/calibration/experiment_runner.py) — subprocess 调用 build_pest.py |
| _resolve_observation_policy_csv() | ✅ | 已在 E01 中泛化为从 design JSON 读取（向后兼容回退） |

### 3.3 P0-C 消除跨季节全局状态 — ✅ 通过

| 审查项 | 结果 | 证据 |
|---|---|---|
| SeasonContext 数据类正确 | ✅ | [build_pest_multiseason.py:48-61](file:///d:/Tomato_Cal/src/calibration/build_pest_multiseason.py#L48-L61) — season_id/input_dir/experiment_code/treatments |
| USER_INPUT_DIR 全局变异已移除 | ✅ | grep 无 `main_mod.USER_INPUT_DIR=` 或 `bp_mod.USER_INPUT_DIR=`；单季节 __main__ 路径保留（刻意） |
| ctx 字典已移除 | ✅ | grep 无 `ctx[`/`ctx.get`/`ctx.pop`；直接导入替代 |
| lazy import 避免循环导入 | ✅ | [build_pest.py:34-35](file:///d:/Tomato_Cal/src/calibration/build_pest.py#L34-L35) — 注释说明 |
| run_execute() 解锁 --execute | ✅ | [experiment_runner.py:207](file:///d:/Tomato_Cal/src/calibration/experiment_runner.py#L207) — 调用 run_parallel.py |

### 3.4 P0-D 统一指标与残差 — ✅ 通过

| 审查项 | 结果 | 证据 |
|---|---|---|
| OLS MSE 分解数学正确 | ✅ | [metrics.py:61-81](file:///d:/Tomato_Cal/src/reporting/metrics.py#L61-L81) — 正规方程，零方差处理；与 Robeson & Willmott (2023) 一致 |
| 数值闭合断言 | ✅ | [metrics.py:176-180](file:///d:/Tomato_Cal/src/reporting/metrics.py#L176-L180) — `MSE = MSE_s + MSE_u` atol=1e-9 |
| 游程检验 Wald-Wolfowitz 精确公式 | ✅ | [residual_diagnostics.py:40-41](file:///d:/Tomato_Cal/src/reporting/residual_diagnostics.py#L40-L41) — E[R]/Var[R] 精确 |
| 处理级 bootstrap MBE | ✅ | 以处理为重抽样单位 |
| article profile 门 | ✅ | 拒绝 HWAM/PWAD/PWAI |
| 不导入绘图库 | ✅ | test_metrics_import_gate.py |

### 3.5 E01 预率定执行准备 — ✅ 通过（代码），⚠️ 实施记录需更正

| 审查项 | 结果 | 证据 |
|---|---|---|
| 域特定策略 CSV 正确 | ✅ | 3 个 CSV，phi_role 按域定义 |
| 7 smoke 全通过 | ✅ | 观测契约验证：每子试验仅激活目标域 |
| 观测契约验证 | ✅ | 12 测试（7 策略解析 + 5 端到端契约） |
| 实施记录 P0 状态声明 | ❌ | §7 错误声称 P0-A/C 未完成（见 C1） |

### 3.6 E01→E02 边界提取桥 — ✅ 通过

| 审查项 | 结果 | 证据 |
|---|---|---|
| 温度组排序强制 | ✅ | `_enforce_temperature_ordering()` 三遍扫描 |
| 混合 active/fixed 组处理 | ✅ | fixed 不被修改 |
| CLI 写入后验证 | ✅ | `assert_valid_frozen_bounds(out)` |
| 文件句柄修复 | ✅ | `with` 上下文管理器 |

## 4. 跨包一致性检查

### 4.1 权重单一路径（P0-A × P0-B × E01）

P0-A 删除了双权重路径，P0-B 的 `run_build()` 通过 `--observation-policy-csv` 传入策略，E01 的 `_resolve_observation_policy_csv()` 从 design JSON 解析策略路径。三者形成一致的单一路径链：

```
spec → multiseason design JSON → observation_policy 字段 → policy CSV → build_pest.py --observation-policy-csv → apply_observation_policy
```

**一致性**：✅ 无断点。P0-A 的 `test_observation_policy_is_single_weight_source` 端到端验证了活跃观测 `weight_policy_id=observation_policy_v2`。

### 4.2 全局状态清除（P0-C × E01）

P0-C 移除了 `USER_INPUT_DIR` 全局变异和 ctx 字典。E01 的 smoke 构建通过 `run_build()` 调用 multiseason 路径，验证了 SeasonContext 路径无回归。

**一致性**：✅ 无断点。E01 的 7 个 smoke 全通过，证明 P0-C 的 SeasonContext 改造不阻塞 E01。

### 4.3 边界生命周期（P0-B × E01 × E01→E02 桥）

P0-B 强制 frozen-only 边界消费。E01 使用 `eggplant_t9_highdim_v1_20260722` frozen 边界（55 active）。E01→E02 桥将 E01 后验投影到 `sobol23_dryonly_v1`（23 active）产生 proposal，经人工审批晋升为 frozen。

**一致性**：✅ 无断点。E01 的 spec 验证 frozen active=55=declared=55；E01→E02 桥的 `test_real_sobol23_t9_freeze_succeeds` 验证 23 active freeze 成功。

### 4.4 指标评价（P0-D × E01）

P0-D 的 `evaluate_experiment()` 已就绪。E01 的 spec 声明 `evaluation_profile: article_rawscale_v1`。E01 正式运行产出 comparison CSV 后，可直接用 `evaluate_calibration_experiment.py` CLI 评价。

**一致性**：✅ 无断点。P0-D 实施记录 §5.1 确认 API 就绪，等待下游接入。

## 5. 过度工程与死代码检查

| 检查项 | 结果 | 说明 |
|---|---|---|
| P0-A 死导入 | ✅ 已清除 | 5 个死导入已移除 |
| P0-C ctx 字典（13 符号注入） | ✅ 已清除 | 改为直接导入 |
| P0-C USER_INPUT_DIR 全局变异 | ✅ 已清除 | SeasonContext 替代 |
| P0-D 过度抽象 | ✅ 无 | 纯新增模块，职责单一 |
| E01 过度工程 | ✅ 无 | 仅新增配置文件 + 1 函数泛化，无多余抽象 |
| weight_scheme.py 退役函数 | ⚠️ 保留 | P0-A 刻意保留（手算 Phi 回归用途），非死代码 |

## 6. 测试验证

```
python -m pytest tests/test_p0a_single_weight_entry.py \
  tests/test_experiment_spec.py tests/test_experiment_build.py \
  tests/test_build_pest_multiseason.py tests/test_metrics.py \
  tests/test_residual_diagnostics.py tests/test_experiment_evaluation.py \
  tests/test_metrics_import_gate.py tests/test_e01_subtrial_policies.py \
  tests/test_observation_policy.py tests/test_weight_scheme.py -q
# 结果：110 passed in 52.17s
```

无回归，无跳过（P0-C 的 2 skipped 是 PEST++ 集成测试，非 P0 范围）。

## 7. 建议汇总

| 优先级 | 编号 | 建议 | 范围 |
|---|---|---|---|
| P0 | C1 | 更正 E01 实施记录 §7 的 P0 状态声明（P0-A/C 已完成） | 文档 |
| P1 | C2 | 维护 P0 总进度汇总文件，作为唯一权威进度来源 | 文档 |
| P1 | C3 | 在 P0-B 实施记录 §5.2 添加泛化注记 | 文档 |
| P2 | C4 | P0-E 优先拒绝 legacy mode 的 improved 路径 | P0-E 范围 |
| P3 | C5 | 若 n∈[8,9] 游程检验进入论文，补精确分布表 | 后续 |

## 8. 结论

P0-A/B/C/D 四个工作包的**代码实现**全部通过二次审查：数学语义正确、无过度工程、无死代码残留、测试覆盖充分、跨包一致性无断点。

主要问题集中在**实施记录的文档一致性**：E01 实施记录错误声明 P0-A/C 未完成（C1），各包进度表过时（C2），P0-B 的 observation-policy 说明未更新（C3）。这些是文档问题，不影响代码正确性，但会误导后续工作决策。

**代码层面无阻塞性问题**，E01 正式运行的唯一阻塞是 P0-E（legacy mode 退役），而非 P0-A 或 P0-C。
