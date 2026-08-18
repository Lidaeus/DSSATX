# Code Review：build_pest 构建模块（第 6 轮）

> 日期：2026-07-23
>
> 范围：`src/calibration/build_pest.py`（3988 行）— PEST 控制文件（.pst/.tpl/.ins）构建、模式分发、参数解析、staged 设计契约、run_manifest 生成
>
> 对照规范：`AGENTS.md`、`docs/敏感性分析与率定用户指南.md`、`docs/项目状态与科研启动清单.md`、`docs/论文讨论写作参考_率定范式季节适应性与异参同效.md`
>
> 关联前轮：第 1 轮 C1/O1（weight_scheme 死导入与双权重路径）、第 2 轮 C3（DEFAULT_BOUNDS 漂移）、第 3 轮 O3（`_infer_soil_id_from_filex` 三副本）、第 5 轮 O1/O3（`_read_evaluate_out` 与 TMT 解析重复）
>
> 测试：`test_build_pest_multiseason.py`、`test_build_bounds_application.py`、`test_staged_inheritance_smoke.py`、`test_p2_n1_n3.py`、`test_pestpp_resume_integration.py` — 48 passed, 2 skipped

## 审查结论

`build_pest.py` 是项目最大（3988 行）、最核心的构建模块，承担模式分发（9 种模式）、参数解析、PST 生成、staged 设计契约验证、run_manifest 全链路溯源。其**staged 设计契约验证（`_fixed_from_provenance` 三方哈希校验、design_config 交叉校验）和 run_manifest 溯源质量是全项目最高水平**。但该文件也是**代码重复和遗留代码积累最严重的模块**——包含 2 个未测试的遗留模式中的 `NameError` 级 bug、1 个 232 行的遗留 PST 构建器与其提取后的版本并存、3 处收获/过程 sigma 计算几乎逐字重复、4 个第 1 轮已确认的死导入在此再次出现。此外，multiseason 路径的「上下文字典注入」模式和 `USER_INPUT_DIR` 全局变异是脆弱的工程模式。

---

## 发现清单

### C1 [严重·bug] `eggplant_harvest` 模式引用未定义的 `events_by_run`

**位置**：`build_pest.py:3325`（定义 `events_by_tn`）、`build_pest.py:3331`（使用 `events_by_run`）

**现象**：

```python
# 第 3325 行：定义的是 events_by_tn（按 treatment number 索引）
events_by_tn = _read_tmt_harvest_events(tmt_path)

# 第 3331 行：使用的是 events_by_run（按 run number 索引）——从未定义
for ev in events_by_run.get(run_no, []):
```

`eggplant_harvest` 模式分支（第 3307–3373 行）从未调用 `_collect_tmt_events_per_run(entries)`（该函数返回 `events_by_run`），仅调用了 `_read_tmt_harvest_events(tmt_path)` 返回 `events_by_tn`。因此 `events_by_run` 在此作用域中不存在，执行该路径将抛 `NameError`。

**根因**：从 `eggplant_stage2` 模式（第 3171 行 `events_by_run, points_by_run = _collect_tmt_events_per_run(entries)`）复制代码时，变量名未同步修改。

**影响**：`eggplant_harvest` 模式完全不可用。该模式无任何测试覆盖（`tests/` 中 grep `eggplant_harvest` 零命中），因此 bug 未被发现。生产模式 `eggplant_stage2` 不受影响。

**修复方向**：将 `events_by_run.get(run_no, [])` 改为 `events_by_tn.get(tn, [])`（使用 entry 的 `tn`），或改用 `_collect_tmt_events_per_run(entries)` 获取 `events_by_run`。

---

### C2 [严重·bug] `eggplant_process` 模式引用未定义的 `points_by_run`

**位置**：`build_pest.py:3568`（定义 `points_by_tn`）、`build_pest.py:3573`（使用 `points_by_run`）

**现象**：与 C1 完全相同的 bug 模式：

```python
# 第 3568 行
points_by_tn = _read_tmt_process_points(tmt_path)

# 第 3573 行——从未定义
for p in points_by_run.get(run_no, []):
```

**影响**：`eggplant_process` 模式完全不可用。同样无测试覆盖。

**修复方向**：同 C1，改为 `points_by_tn.get(tn, [])` 或使用 `_collect_tmt_events_per_run`。

---

### C3 [中·冲突] weight_scheme "improved" 路径是僵尸代码（第 1 轮 C1 在此的体现）

**位置**：`build_pest.py:2186-2203`（`create_ins_and_pst` 内）、`build_pest.py:2484-2501`（`create_ins_and_pst_multi` 内）

**现象**：两个 PST 构建器都包含 `if weight_scheme == "improved"` 分支，调用 `build_observation_weights(...)`（来自 `weight_scheme.py`）。但随后立即调用 `_apply_policy_and_prepare_runner`（第 2205/2503 行），用 `observation_policy.apply_observation_policy` 覆盖重算权重——这正是第 1 轮 C1 发现的「双权重计算路径」。

此外，`build_observation_weights` 的三个关键控制参数 `apply_normalization`、`apply_log_transform`、`apply_pwtadj1` 对应的 CLI 选项已全部退役：

```python
# 第 2934-2945 行
if args.apply_normalization:
    parser.error("--apply-normalization is retired ...")
if args.apply_log_transform:
    parser.error("--apply-log-transform is retired ...")
if args.apply_pwtadj1:
    parser.error("--apply-pwtadj1 is deferred ...")
```

因此 "improved" 路径即使被触发，所有退役标志均为 `False`，`build_observation_weights` 以退化模式运行后立即被 `observation_policy` 覆盖。整个分支是**功能上无效但语法上可达的僵尸代码**。

**建议**：移除 `weight_scheme == "improved"` 分支和 `--weight-scheme` 选项中的 `"improved"` 选择项，统一为 `observation_policy` 单一权重入口（与第 1 轮建议一致）。

---

### O1 [严重·过度设计] 遗留 `create_ins_and_pst`（232 行）与提取后的 `_build_ins_and_obs` + `_populate_pst_from_par_obs` 并存

**位置**：
- `create_ins_and_pst`：第 2015–2247 行（遗留单输出构建器，内联 INS/obs 循环 + 内联 PST 填充）
- `_build_ins_and_obs`：第 2276–2383 行（提取后的 INS/obs 构建，被 `create_ins_and_pst_multi` 调用）
- `_populate_pst_from_par_obs`：第 2386–2402 行（提取后的 PST 填充，被 `create_ins_and_pst_multi` 调用）
- `_is_tagged_output`：第 2250–2258 行（提取后的辅助函数，仅被 `_build_ins_and_obs` 调用）

**现象**：`create_ins_and_pst` 内部第 2054–2166 行的 INS/obs 构建循环与 `_build_ins_and_obs` 几乎逐字相同（~110 行重复），第 2213–2228 行的 PST 填充与 `_populate_pst_from_par_obs` 完全相同（~16 行重复）。`create_ins_and_pst` 内部还内联了 `_is_tagged_output` 的逻辑（第 2074–2081 行）。

**当前使用者**：`create_ins_and_pst` 仍被 7 个遗留模式调用（`tomato_full`、`eggplant_pheno`、`eggplant_growth`、`eggplant_joint`、`eggplant_harvest`、`eggplant_process`、`eggplant_spe_temp`），通过第 3859 行的非 `stage2_outputs` 分支进入。生产模式 `eggplant_stage2` 和 `eggplant_v13` 使用 `create_ins_and_pst_multi`。

**建议**：将 `create_ins_and_pst` 改为调用 `_build_ins_and_obs` 和 `_populate_pst_from_par_obs`（单输出包装器），消除 ~126 行重复。低优先级：遗留模式无生产调用，但保留它们会增加维护负担。

---

### O2 [中·过度设计] 收获 sigma 计算重复 3 次（~72 行）

**位置**：
- `eggplant_stage2` 模式：第 3216–3239 行
- `eggplant_harvest` 模式：第 3350–3372 行
- `eggplant_v13` 模式：第 3464–3488 行

**现象**：三处几乎逐字相同的代码块，均实现 `sigma = (sigma0² + (cv * |median|)²)^0.5 * sigma_factor * early_scale` 的收获事件 sigma 计算，包括 `PWADM`（累积）和 `PWAIM`（增量）两个变量、`harvest_early_hno_max` / `harvest_early_weight_factor` / `harvest_early_apply_to` 的早期收获加权逻辑。

**建议**：提取为 `_compute_harvest_sigmas(df_harvest, args) -> dict` 共享函数。三处调用统一。

---

### O3 [中·过度设计] 过程 sigma 计算重复 3 次（~45 行）

**位置**：
- `eggplant_stage2` 模式：第 3249–3267 行（LAIDM/LWADM/SWAD 三变量）
- `eggplant_v13` 模式：第 3493–3505 行（L#SDM/LAIDM/LWADM/SWAD 四变量）
- `eggplant_process` 模式：第 3591–3602 行（LAIDM/LWADM/SWAD 三变量）

**现象**：三处实现相同的 `sigma = (sigma0² + (cv * |median|)²)^0.5` 过程点 sigma 计算，仅变量列表不同。

**建议**：提取为 `_compute_process_sigmas(df_process, var_specs, sigma_factors) -> dict` 共享函数，`var_specs` 为 `(var_name, sigma0, cv)` 元组列表。

---

### O4 [中] 4 个第 1 轮已确认的死导入在此再次出现

**位置**：`build_pest.py:26-31`

```python
from src.calibration.weight_scheme import (
    WEIGHT_POLICY_ID,
    normalize_and_weight,       # 死导入——全文件零调用
    compute_cv_based_sigma,     # 死导入——全文件零调用
    compute_balanced_weights,   # 死导入——全文件零调用
    build_observation_weights,  # 仅在 C3 的僵尸路径中调用
    weight_from_sigma,          # 活跃：_resolve_sigma 中调用
    VARIABLE_TREATMENT,         # 死导入——全文件零调用
)
```

**现象**：`normalize_and_weight`、`compute_cv_based_sigma`、`compute_balanced_weights`、`VARIABLE_TREATMENT` 四个符号在 `build_pest.py` 中仅出现在 import 语句，全文件无任何调用。`build_observation_weights` 仅在 C3 的僵尸路径中被调用。这是第 1 轮 O1（`weight_scheme.py` 中 ~120 行死代码）在消费侧的体现。

**建议**：与 C3 一并清理——移除 "improved" 路径后，仅保留 `WEIGHT_POLICY_ID` 和 `weight_from_sigma` 两个活跃导入。

---

### O5 [中·过度设计] multiseason 上下文字典注入模式

**位置**：`build_pest.py:3815-3837`

**现象**：

```python
ctx = {
    "_parse_batch_entries": _parse_batch_entries,
    "_build_evaluate_observations_from_filea": _build_evaluate_observations_from_filea,
    "_read_tmt_harvest_events": _read_tmt_harvest_events,
    "_read_tmt_process_points": _read_tmt_process_points,
    "_resolve_filex_path": _resolve_filex_path,
    "_infer_excode_from_filex": _infer_excode_from_filex,
    "PEST_EVAL_FILE": PEST_EVAL_FILE,
    "PEST_JOINT_FILE": PEST_JOINT_FILE,
    "PEST_HARVEST_FILE": PEST_HARVEST_FILE,
    "PEST_TMTGROW_FILE": PEST_TMTGROW_FILE,
    "create_ins_and_pst_multi": create_ins_and_pst_multi,
    "_write_run_manifest": _write_run_manifest,
    "_finalize_ies_contract": _finalize_ies_contract,
    "bad_phi_sigma": bad_phi_sigma,
    "observation_policies": observation_policies,
}
import src.calibration.build_pest as _bp
ctx["_bp_module"] = _bp
_bp.USER_INPUT_DIR = str(Path(args.multiseason_design).parent)  # fallback
build_multiseason_stage2(args, prefix, allowed, extra_allowed, params, model_cmd_extra, ctx)
```

13 个函数/常量通过字典传递给 `build_multiseason_stage2`。这是一种非标准的依赖注入模式——可能是为了测试可替换性或避免循环导入，但 `build_pest_multiseason.py` 可以直接 `from src.calibration.build_pest import ...` 获取这些符号（它已经 `import src.calibration.build_pest as _bp` 通过 ctx 获取了模块引用）。

更严重的是第 3836 行 `_bp.USER_INPUT_DIR = str(Path(args.multiseason_design).parent)` —— 在 multiseason 路径中将模块级全局 `USER_INPUT_DIR` 设置为 multiseason design JSON 的**父目录**作为 "fallback"。如果同一进程内后续有任何代码依赖 `USER_INPUT_DIR` 进行 FileX 解析，将使用错误的目录。

**建议**：`build_pest_multiseason.py` 直接从 `build_pest` 导入所需函数，移除 ctx 字典。`USER_INPUT_DIR` 应作为参数显式传递，而非变异模块全局。

---

### O6 [中] `_read_tmt_harvest_events` / `_read_tmt_process_points` 与 `run_dssat.py` 重复

**位置**：`build_pest.py:1188-1313` / `build_pest.py:1316-1382`；对照 `run_dssat.py:212-287` / `run_dssat.py:310-376`（第 5 轮 O3 已记录）

**现象**：两个模块各自实现了 TMT 文件解析。`build_pest.py` 版本额外计算 `dry_cum`/`dry_inc`/`fresh_cum`/`fresh_inc`（T10 直接累积逻辑），`run_dssat.py` 版本仅返回原始事件。但文件读取和 header 解析框架完全相同。

**建议**：与第 5 轮 O3 同步解决——提取通用 TMT 解析框架到共享模块。

---

### O7 [中] `_infer_soil_id_from_filex` 第三个副本（第 3 轮 O3 / 第 5 轮 O6）

**位置**：`build_pest.py:1696-1733`；对照 `run_dssat.py:1336-1373`、`sa_generate_param_review_csv.py:173-210`

详见第 3 轮 O3，累计 ~106 行重复。

---

### M1 [次要] `USER_INPUT_DIR` 模块全局变异

**位置**：`build_pest.py:62`（定义 `USER_INPUT_DIR = None`）、`build_pest.py:2906`（`USER_INPUT_DIR = str(Path(args.input_dir)...)`）、`build_pest.py:3836`（`_bp.USER_INPUT_DIR = ...`）

**现象**：`USER_INPUT_DIR` 是模块级全局变量，在 `__main__` 块中被设置（第 2906 行），在 multiseason 路径中被再次设置（第 3836 行）。`_resolve_filex_path`（第 1675 行）直接读取该全局变量。这与第 5 轮 C2（`run_dssat.py` 的 `global BATCH_FILE`）是相同的反模式——模块不可重入，且 multiseason 路径的变异可能影响后续 FileX 解析。

**建议**：将 `USER_INPUT_DIR` 作为参数显式传递给 `_resolve_filex_path` 和 `_collect_tmt_events_per_run` 等函数。

---

### M2 [次要] `SPE_DIRECT_BOUNDS_EGGPLANT` 传播 DEFAULT_BOUNDS 漂移（第 2 轮 C3）

**位置**：`build_pest.py:483-509`

**现象**：`SPE_DIRECT_BOUNDS_EGGPLANT` 中的 `KC_SLOPE: (0.0, 0.40)` 和 `VSSINK: (2.05, 8.20)` 来自 `param_registry.py` 的 `DEFAULT_BOUNDS`（第 2 轮 C3 已记录其与 T9/T10 冻结值的漂移）。注释（第 493–495 行）明确说明这些是发现用默认范围，会被 frozen bounds-id 覆盖，因此不影响生产率定。但若 `--bounds-id` 未指定，这些漂移值将进入 PST。

**建议**：与第 2 轮 C3 一并解决——对齐 `DEFAULT_BOUNDS` 与冻结值，或在 `SPE_DIRECT_BOUNDS_EGGPLANT` 中直接使用冻结值。

---

### M3 [次要] 7 个遗留模式无测试覆盖

**位置**：`tomato_full`、`eggplant_pheno`、`eggplant_growth`、`eggplant_joint`、`eggplant_harvest`、`eggplant_process`、`eggplant_spe_temp`

**现象**：7 个遗留模式中，`eggplant_harvest` 和 `eggplant_process` 有 C1/C2 的 `NameError` 级 bug 但无测试发现；其余 5 个模式也无直接模式测试（`test_build_bounds_application.py` 使用 `eggplant_pheno` 字符串作为 mode 标签，但不触发 `build_pest.py` 的模式分发逻辑）。生产模式 `eggplant_stage2` 和 `eggplant_v13` 有 `test_build_pest_multiseason.py` 和 `test_staged_inheritance_smoke.py` 覆盖。

**建议**：为仍需保留的遗留模式补充冒烟测试，或评估是否可退役不再需要的模式。

---

## 已验证一致的关键点（设计值得肯定）

1. **`_fixed_from_provenance` 的三方哈希契约**：`--fixed-from` 代表性参数 CSV 的文件哈希必须与 finalize JSON 的 `stage_representative.sha256` 和 representative metadata JSON 的 `output_sha256` 三方一致（第 217–241 行）。任何独立编辑 finalize 工件都会被检测到。✓（全项目最严格的上游溯源契约）

2. **staged 设计的 CLI 交叉校验**：`--design-config` + `--stage` 必须同时提供；`--bounds-id` 必须与 design_spec 的 `bounds_id` 一致；`--input-dir` 的 bundle_id 必须与 design 的 `input_bundle` 一致；`--observation-policy-csv` 的文件名 stem 必须与 design 的 `observation_policy_id` 一致（第 2850–2932 行）。✓

3. **`_assert_no_hwam_calibration_target` 拒绝 HWAM 作为率定观测**：正确实现规范「HWAM 是 indeterminate crop 的诊断专用变量，不可用于率定目标」（第 2261–2273 行）。✓

4. **IES 契约的 `ies_bad_phi_sigma` 区分 staged vs legacy**：staged 模式默认 `1e300`（禁用相对 Phi 筛选，保留所有有限成功实现），legacy 模式默认 `2.0`（第 2897–2901 行）。✓

5. **`_finalize_ies_contract` 的观测噪声集成**：从 `weights.audit.csv` 的 `raw_sigma` 生成独立正态噪声集成（`observed + N(0, sigma)`），与 PEST++ 的 `ies_observation_ensemble` 对接，同时保持目标函数权重不变（第 351–461 行）。✓

6. **`_write_weight_audit` 的审计独立性**：权重审计 CSV 写为 `{prefix}.weights.audit.csv`，与 PEST++ 运行时生成的 `case.weights.csv` 区分，防止覆盖（第 328–330 行注释明确说明）。✓

7. **`_resolve_sigma` 的无静默回退**：sigma 缺失时抛 `KeyError` 而非使用默认值（第 290–302 行），与规范「禁止隐式 sigma 回退」一致。✓

8. **run_manifest 的全链路溯源**：manifest 记录 `bounds_sha256`、`input_manifest_sha256`、`observation_policy_sha256`、`design_config_sha256`、`validation_split_sha256`、`fixed_from_sha256`（列表）、`fixed_from_upstream_manifest_sha256`、`fixed_from_upstream_finalize_sha256` 等完整哈希链（第 3906–3987 行）。✓（全项目最完整的运行溯源）

9. **`apply_bounds_review_csv` 的 `lower <= init <= upper` 校验**：对每个参数强制检查初始值在边界内，fixed 行要求 `lower == init == upper`，active 行要求 `lower != upper`（第 760–780 行）。✓

10. **`validate_sensitivity_param_review_csv` 的土壤层物理一致性检查**：逐层校验 `SLLL < SDUL < SSAT` 和 `SLLL <= SH2O <= SSAT`（第 889–909 行）。✓

---

## 建议的后续行动（按优先级）

1. **C1 + C2（修复 NameError bug）**：`eggplant_harvest` 和 `eggplant_process` 模式的 `events_by_run` / `points_by_run` 改为 `events_by_tn.get(tn, [])` / `points_by_tn.get(tn, [])`。**立即行动**——虽为遗留模式，但 bug 级别严重。

2. **C3 + O4（清理 weight_scheme 僵尸路径）**：移除 `weight_scheme == "improved"` 分支和 4 个死导入，统一为 `observation_policy` 单一入口。与第 1 轮建议一致。

3. **O2 + O3（提取 sigma 计算共享函数）**：提取 `_compute_harvest_sigmas` 和 `_compute_process_sigmas`，消除 ~117 行重复。中优先级。

4. **O1（统一遗留 PST 构建器）**：`create_ins_and_pst` 改为调用 `_build_ins_and_obs` + `_populate_pst_from_par_obs`，消除 ~126 行重复。中优先级。

5. **O5 + M1（消除 `USER_INPUT_DIR` 全局变异和 ctx 字典注入）**：`build_pest_multiseason.py` 直接导入所需函数，`USER_INPUT_DIR` 作为参数传递。中优先级。

6. **O6 + O7（跨模块去重）**：与第 3 轮 O3、第 5 轮 O3/O6 同步解决 `_infer_soil_id_from_filex` 和 TMT 解析的三模块去重。低优先级。

7. **M3（遗留模式测试或退役）**：评估 7 个遗留模式是否仍需保留；保留的补充冒烟测试。低优先级。

**合计可删代码**：O1(126) + O2(48) + O3(30) + O4(4) + C3(36) = **~244 行**（不含跨模块去重）。

---

## 附：六轮 code review 汇总

| 轮次 | 模块 | 行数 | 严重冲突 | 过度设计 | 可删行数 |
|---|---|---|---|---|---|
| 1 | weight_scheme + observation_policy | 647 | 1（C1 双权重） | 2（O1 死代码 ~120 行） | ~120 |
| 2 | param_registry | 696 | 2（C1 FL-VS、C2 XFINT） | 2（O1 注册表 I/O ~115 行） | ~115 |
| 3 | SA 复核 + Sobol 后处理 | 1298 | 1（C1 DEFAULT_BOUNDS 传播） | 5（O1 死文件 130 行、O2/O3 三副本） | ~135 |
| 4 | Sobol 工具链 | 1380 | 0 | 2（O1/O2 公式重复） | ~16 |
| 5 | run_dssat | 2839 | 2（C1 HARVEST_VAR、C2 BATCH_FILE） | 6（O1/O2 重复 80 行、O4/O5 死函数 55 行） | ~135 |
| 6 | build_pest | 3988 | 3（C1/C2 NameError、C3 僵尸路径） | 7（O1 遗留构建器 126 行、O2/O3 sigma 重复 117 行） | ~244 |
| **合计** | | **10848** | **9** | **24** | **~765** |
