# Code Review：权重与观测策略模块（第 1 轮）

> 日期：2026-07-23
>
> 范围：`src/calibration/weight_scheme.py`（302 行）、`src/calibration/observation_policy.py`（345 行）
>
> 对照规范：`docs/权重设计方案改进提案.md`（实际标题《观测误差与权重设计规范》，2026-07-22，当前权威专题规范）
>
> 关联代码：`src/calibration/build_pest.py`（调用方）、`src/calibration/build_pest_multiseason.py`（T10 权重重写）
>
> 测试：`tests/test_weight_scheme.py`（13）、`tests/test_observation_policy.py`（10），本轮 23 passed

## 审查结论

两个模块的**数学语义与规范完全一致**（`w=1/sigma`、log 传播、均值 sigma、`1/sigma²` 禁止、Min–Max 禁止、pwtadj1 停用均已正确实现并有测试覆盖）。主要问题是**过度设计与职责重叠**：`weight_scheme.py` 与 `observation_policy.py` 在 P0 之后演化为两套并行的权重/变换计算路径，其中 `weight_scheme.py` 的大部分公共 API 已被 `observation_policy.py` 取代但未被清理，形成死代码和"双计算"风险。这是本轮发现的最严重问题。

发现按严重程度分级：**冲突/不一致（C）**、**过度设计（O）**、**次要/建议（M）**。

---

## C1 [严重] 双权重计算路径：`weight_scheme` 与 `observation_policy` 职责重叠且可相互覆盖

**位置**：`build_pest.py:2186-2207`（`create_ins_and_pst`）、`build_pest.py:2484`（`create_ins_and_pst_multi`）

**现象**：
```python
# 第 2195 行：先用 weight_scheme.build_observation_weights 计算一次权重
obs_df = pd.DataFrame(build_observation_weights(obs_data, ...))
# 第 2205 行：再用 observation_policy.apply_observation_policy 覆盖重算
obs_df, model_cmd_extra = _apply_policy_and_prepare_runner(obs_df, ...)
_write_weight_audit(obs_df, out_dir, prefix)
```
`build_observation_weights`（weight_scheme）写入 `weight/sigma/base_weight/group_multiplier`，随后 `apply_observation_policy`（observation_policy）用相同字段名**全部覆盖**。只有 `weight_scheme == "improved"` 分支才会调用前者；默认 `weight_scheme="legacy"`（`build_pest.py:2029,2415`）跳过，直接由 observation_policy 计算。

**冲突点**：
- 规范 §2 明确要求"四者（sigma/base_weight/group_multiplier/final_weight）都应出现在审计表中，不能只保留最终数字"，但当 `weight_scheme="improved"` 时，weight_scheme 写入的审计字段在 12 行后即被 observation_policy 覆盖，审计表最终只反映 observation_policy 的结果，weight_scheme 的中间计算不可追溯。
- 两个模块对"raw sigma + 1/sigma 权重"的实现不同（见 O1、O2），若两路径对同一观测给出不同 sigma，覆盖行为会掩盖差异。

**建议**：统一为单一权重计算入口。`observation_policy.apply_observation_policy` 已是更完整、更符合规范的实现（支持 log/mean-sigma/phi_role/sigma_source 全链路）。应移除 `build_pest.py` 中对 `build_observation_weights` 的调用，将 `weight_scheme="improved"` 标记为废弃或在 builder 内直接拒绝，避免维护两套逻辑。

---

## C2 [中] `weight_scheme.py` 的 `VARIABLE_TREATMENT` 缺失 T10 核心变量 CHFPW/CHPDT

**位置**：`weight_scheme.py:28-41`

**现象**：`VARIABLE_TREATMENT` 字典包含 12 个变量（ADAPM/CNAMM/HIAMM/LAIXM/LAIDM/LWADM/SWADM/CHTAM/CNAAM/H#AMM/PWADM/PWAIM），但**不包含 T10 正式率定的核心采收变量 CHFPW、CHPDT**。

**对照规范**：
- T10 方法文档（`论文材料与方法_DSSAT_PEST多季节参数率定框架.md` §4.1）与权重规范 §4.2.1 明确：CHFPW/CHPDT 的 `sigma_raw = 250 kg ha⁻¹`，且使用 log 残差。
- `build_pest_multiseason.py:385-387` 的 `_family_for_group` 已正确将 CHFPWM/CHPDTM 映射到 HARVEST_FRESH/HARVEST_DRY 家庭。
- 但 `weight_scheme.VARIABLE_TREATMENT` 仍停留在 T8 时代的 PWADM/PWAIM（增量/累计采收旧命名），未跟进 T10 的直接累计采收变量。

**影响**：若 `build_observation_weights` 被调用且某 CHFPW 观测缺少显式 `sigma` 字段，会回退到默认 `sigma_base=1.0`（`weight_scheme.py:264`），导致权重严重失真。当前因 C1 的双路径覆盖，实际生产中 observation_policy 先于此回退生效，未触发；但这是潜伏的隐患。

**建议**：既然 C1 建议废弃 `build_observation_weights`，此问题随之消解。若保留，必须补齐 CHFPW/CHPDT 条目。注意 `VARIABLE_TREATMENT` 在 `build_pest.py:31` 被 import 但**实际未使用**（见 O3），本身已是死代码。

---

## O1 [严重·过度设计] `weight_scheme.py` 存在大量已被取代的公共 API（死代码）

**位置**：`weight_scheme.py` 整体

**现象**：`build_pest.py` 从 `weight_scheme` 导入 6 个符号（`build_pest.py:24-32`），但实际使用情况：

| 导入符号 | build_pest.py 中使用次数（非 import 行） | 状态 |
|---|---|---|
| `weight_from_sigma` | 2 次（仅用于校验 sigma 有限性，`build_pest.py:297,2146`） | 误用为校验函数 |
| `build_observation_weights` | 2 次（`build_pest.py:2195,2493`，仅 `weight_scheme="improved"` 分支） | 半活跃 |
| `normalize_and_weight` | 0 次 | **死导入** |
| `compute_cv_based_sigma` | 0 次 | **死导入** |
| `compute_balanced_weights` | 0 次（仅被 build_observation_weights 内部 pwtadj1 调用） | **死导入** |
| `VARIABLE_TREATMENT` | 0 次 | **死导入** |

即 6 个导入中有 4 个完全未使用。`weight_scheme.py` 内部 `minmax_normalize`（`weight_scheme.py:75`）、`normalize_and_weight`（`weight_scheme.py:85`）是"故意抛错"的退役守卫函数——功能已迁至 observation_policy，但函数体保留为 `raise ValueError` 占位。

**过度设计判断**：这些函数在 P0 阶段被设计为"预留接口"，但规范 §8 已明确"相关误差模式...该能力不属于 P0 的必要范围，避免过度设计"。`compute_balanced_weights`（实验性组 Phi 平衡，`weight_scheme.py:151-191`）+ `compute_cv_based_sigma`（CV 异方差，`weight_scheme.py:110-132`）+ `apply_weight_scheme_to_obs_df`（`weight_scheme.py:194-224`）构成一套完整的"备选权重方案框架"，而规范明确说 pwtadj1 本轮停用、异方差需用户审批后才能启用。这套框架至今无生产调用，属于预留过度。

**建议**：删除 `minmax_normalize`、`normalize_and_weight`、`compute_cv_based_sigma`、`compute_balanced_weights`、`apply_weight_scheme_to_obs_df` 及对应死导入；保留 `weight_from_sigma`、`compute_phi`（手算校验工具，规范 §9.8 要求）、`build_observation_weights`（若 C1 不立即废弃则保留）。

---

## O2 [中·过度设计] `weight_scheme.py` 保留退役特性的"抛错占位"增加认知负担

**位置**：`weight_scheme.py:23-24, 75-82`

**现象**：
```python
# 第 23-24 行
LOG_TRANSFORM_VARS: set[str] = set()  # 空集合，注释"P0 does not activate"
# 第 75-82 行
def minmax_normalize(...):
    raise ValueError("Dynamic Min-Max normalization is disabled...")
```
`LOG_TRANSFORM_VARS` 永远是空集合；`minmax_normalize`/`normalize_and_weight` 永远抛错。这些是为"防止旧调用点误用"而保留的反向兼容桩。但规范已明确这些设计"不再采用"（规范第 7 行），且 `observation_policy.py` 已完整接管 log 变换。

**判断**：在 `build_pest.py` 已不再调用 `normalize_and_weight`/`minmax_normalize` 的情况下（见 O1），这些占位函数的唯一价值是"若有人误调则报错"——但没有任何调用点会误调。这是防御已不存在的风险的过度设计。

**建议**：随 O1 一并删除。若担心外部脚本误用，改为在模块 `__all__` 中移除并在文档注明即可，无需保留可调用但必抛错的函数体。

---

## O3 [次要] `weight_scheme.py` 与 `observation_policy.py` 重复定义 `MISSING_VALUE` 和 sigma 常量

**位置**：`weight_scheme.py:21`（`MISSING_VALUE = -99.0`）、`observation_policy.py:22`（`MISSING_VALUE = -99.0`）

**现象**：两个模块各自定义 `MISSING_VALUE = -99.0`。规范无强制要求单一来源，但这是 DSSAT 缺失值约定，应集中到 `src/common/` 统一定义，避免两处修改不同步。

**建议**：次要，可在后续重构时将 DSSAT 约定常量（`MISSING_VALUE`、`-99` 等）集中到 `src/common/` 或 `param_registry.py`。

---

## M1 [建议] `observation_policy.py` 对"weight==0 即缺失"的推断可能过宽

**位置**：`observation_policy.py:187`

**现象**：
```python
is_missing = raw_obs == MISSING_VALUE or float(record.get("weight", 0.0)) == 0.0
```
将 `weight == 0` 等同于缺失观测。这在设计阶段（diagnostic_only 观测主动置零权重）是合理的，但规范 §3 区分了"缺失值（-99）"和"诊断用途（weight=0）"两种语义。当前合并为单一 `is_missing`，导致诊断观测的 `obsval` 被强制设为 0.0（`observation_policy.py:247`），可能丢失其原始物理值用于诊断报告。

**判断**：非冲突，但语义合并可能在未来"诊断观测需保留原值用于报告"时产生问题。建议分离 `is_missing`（仅 `== MISSING_VALUE`）与 `is_zero_weight`（`weight==0`），分别处理 `obsval` 清零与否。

**建议**：低优先级，待诊断报告需求明确后再改。

---

## 已验证一致的关键点（无问题）

为避免只报问题，下列规范要求经代码与数值核对**确认实现正确**：

1. **`w = 1/sigma`（非 `1/sigma²`）**：`weight_scheme.py:54` `return group_multiplier / sigma`；`observation_policy.py:253` `base_weight = 1.0 / effective_sigma`。✓
2. **log 变换公式**：`observation_policy.py:92` `math.log(shifted / reference)` 与规范 §4.2 `z = ln((y+offset)/reference)` 一致；数值验证 y=1000,offset=1 → z=6.908755 精确匹配。✓
3. **log sigma 传播**：`observation_policy.py:117` `math.sqrt(math.log1p((raw_sigma/shifted)**2))` 与规范 `sigma_log = sqrt(ln(1+(sigma_raw/(y+offset))²))` 一致；数值验证 0.245982 精确匹配。✓
4. **均值 sigma**：`observation_policy.py:57-59` `sqrt(replicate_sd²/n_eff + model_sigma² + sigma_floor²)` 与规范 §3.4 一致；`n_eff > n_replicates` 正确拒绝（`observation_policy.py:53`）。✓
5. **`y+offset <= 0` 直接失败**：`observation_policy.py:88-91` 抛 ValueError，不静默截断。✓（规范 §4.2）
6. **Min-Max 禁止**：`weight_scheme.py:79` 抛错；`observation_policy` 无 Min-Max 路径。✓（规范 §4.3）
7. **pwtadj1 停用**：`weight_scheme.py` 中 pwtadj1 路径仅在显式 `apply_pwtadj1=True` 时触发，默认 False；`build_pest.py` 默认不传。✓（规范 §5.2）
8. **增量与累计不重复计权**：`observation_policy.py` 无自动累计逻辑；T10 路径 `build_pest_multiseason.py` 明确只对 CHFPW/CHPDT（累计）计权，不同时计 PWAD/PWAI。✓（规范 §6）
9. **审计字段齐全**：`observation_policy.py:260-276` 写入 raw_obsval/raw_sigma/sigma/sigma_source/base_weight/group_multiplier/weight/transform 全链路。✓（规范 §2、§7）

---

## T10 权重公式交叉核对（`build_pest_multiseason.py`）

规范 §4.2.1 的 T10 公式：
```
final_weight_i = (1 / sigma_log_i) × sqrt(budget_family × season_share × variable_share / n_cell)
```

代码实现（`build_pest_multiseason.py:447-471`）：
```python
bucket_mult[bucket] = math.sqrt(budget / max(n, 1))  # n = 该 family-season 内观测数
new_weights.append(mult / sigma if active ... else 0.0)  # (1/sigma) × sqrt(budget/n)
```

**结论**：与规范一致——`bucket = (season, family)`，`n_cell` 即该 season-family 桶内观测数 `n`，`budget` 来自 family 预算表（PLANT_N=1.00/HARVEST_FRESH=1.25/HARVEST_DRY=1.25）。代码注释 `# One budget applies to a scientific family within a season. Harvest HNO and process DATE groups must not each receive the full family budget.` 正确防止了预算重复分配。**但**代码只实现了 `season_share=1`、`variable_share=1` 的扁平情况（单季单变量内分摊），规范公式中的 `season_share`/`variable_share` 分层系数当前未显式参数化——在当前 T10 双季配置下因每季独立计 bucket 而隐式等价，但若未来扩展到多变量共享家庭预算需补齐。**记为 M2，非当前阻塞项。**

---

## 建议的后续行动（按优先级）

1. **C1 + O1 + O2（合并处理）**：移除 `build_pest.py` 中 `build_observation_weights` 调用与 4 个死导入；废弃或删除 `weight_scheme.py` 中 `minmax_normalize`/`normalize_and_weight`/`compute_cv_based_sigma`/`compute_balanced_weights`/`apply_weight_scheme_to_obs_df`；统一为 `observation_policy` 单一权重入口。预计删除 ~120 行死代码。
2. **C2**：随 C1 消解；若保留 `VARIABLE_TREATMENT` 则补 CHFPW/CHPDT。
3. **M1/M2/O3**：低优先级，记录待后续重构。

## 附：本轮未覆盖（下一轮候选）

- `build_pest.py`（155KB，单季 PST 构建主逻辑）——需独立 1–2 轮。
- `build_pest_multiseason.py`（T8/T10 多季构建）——本轮仅交叉核对了权重公式，完整审查待后续。
- `param_registry.py`（PHYSICAL_BOUNDS、边界校验）——独立一轮。
- `run_dssat.py` + `run_multiseason.py`（隔离与执行）——对照 `DSSAT并行隔离规范.md` 独立一轮。
