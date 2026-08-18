# Code Review：Sobol 工具链模块（第 4 轮）

> 日期：2026-07-23
>
> 范围：`src/sensitivity/sobol_case.py`（193 行）、`src/sensitivity/sobol_audit.py`（307 行）、`src/sensitivity/sobol_bootstrap.py`（243 行）、`src/sensitivity/sobol_repair.py`（318 行）、`src/sensitivity/sobol_convergence.py`（319 行）
>
> 对照规范：《敏感性分析与率定用户指南》§4（2026-07-22）、《Morris v4 结果与 Sobol 参数选择》（2026-07-21）、《Sobol 敏感性分析设计方案》（2026-07-20）、`AGENTS.md`
>
> 关联前轮：第 3 轮（SA 复核与 Sobol 后处理）
>
> 测试：`test_sobol_workflow.py` (8)、`test_sobol_repair.py` (3)、`test_sobol_budget_and_convergence.py` (8)、`test_select_sobol_from_morris.py` (4)、`test_run_sobol_n128.py` (2) — 23 passed

## 审查结论

Sobol 工具链是项目中**设计质量最高的模块组**。与前三轮发现大量死代码和过度设计不同，本轮五个模块的**数学语义、科学严谨性和工程纪律均与规范完全一致**，且几乎无死代码。主要发现集中在**可提取的共享工具函数**（`read_flat_manifest` 和 Saltelli 公式在两处重复），以及一处**部署假设**（`sobol_repair` 的 runtime 路径）。**本轮无严重冲突或过度设计**。

---

## 发现清单

### O1 [中] `read_flat_manifest` 在两个模块中重复定义

**位置**：`sobol_audit.py:22-29`、`replay_morris_failure.py:21-28`

**现象**：两个模块各定义了一个完全相同的 `read_flat_manifest` 函数（~8 行），逻辑均为逐行读取 `key: value` 格式的 YAML 子集。该函数在 `sobol_audit.py` 中被 4 个下游模块导入（`sobol_repair.py`、`sobol_bootstrap.py`、`sobol_convergence.py`、`export_sobol_stability_paper_data.py`），是事实上的共享实现；`replay_morris_failure.py` 中的副本仅自身使用。

此外，`quality.py:203-223` 存在功能相似的 `read_flat_run_manifest_field`（读取单个字段，带 YAML 引号处理），与 `read_flat_manifest`（读取全部字段，不含引号处理）形成互补但不一致的接口。

**建议**：将 `read_flat_manifest` 提取到 `src/common/project.py`（与 `sha256_file`、`git_metadata` 同级），两个副本统一调用。同时统一 `read_flat_run_manifest_field` 与 `read_flat_manifest` 的引号处理行为（见 M1）。

---

### O2 [中] Saltelli 公式在 `sobol_repair` 和 `sobol_bootstrap` 中重复实现

**位置**：`sobol_repair.py:127-153`（`recompute_indices`）、`sobol_bootstrap.py:84-154`（`bootstrap_sobol` 内联）

**现象**：两个模块各自实现了 Saltelli 单参数 Sobol 指数估计器：

```python
# 核心公式（两处一致）
s1 = mean(b * (hybrid - a)) / variance
st = 0.5 * mean((a - hybrid)²) / variance
```

**差异**：
- `sobol_repair.recompute_indices`：独立函数，接受 `(parameters, outputs, samples)`，返回 `(si_df, st_df)`，用于修复后重算全部指数。
- `sobol_bootstrap.bootstrap_sobol`：内联在 bootstrap 循环中，额外计算 bootstrap 百分位置信区间和 SE，且与 PEST++ 原始指数做点估计复现校验。

**判断**：`sobol_bootstrap` 无法直接调用 `recompute_indices`，因为它需要逐参数逐观测的 bootstrap CI 计算（`recompute_indices` 按观测批量处理）。但核心点估计公式（第 103–104 行与第 147–148 行）的数学表达完全一致，可提取为 `_saltelli_estimator(a, b, hybrid, variance)` 共享函数，减少公式漂移风险。

**建议**：提取 `_saltelli_estimator` 到 `sobol_repair.py` 或新建 `sobol_estimators.py`，`sobol_bootstrap` 和 `sobol_repair` 共同调用。低优先级：当前两处公式一致且均有测试覆盖。

---

### M1 [次要] `read_flat_manifest` 不处理 YAML 引号，与 `read_flat_run_manifest_field` 不一致

**位置**：`sobol_audit.py:22-29` vs `quality.py:203-223`

**现象**：
- `read_flat_manifest` 使用 `split(":", 1)` + `.strip()`，不处理 YAML 单引号/双引号。
- `read_flat_run_manifest_field` 使用 `_strip_manifest_scalar` 处理 `'...'` 和 `"..."` 引号，并正确处理单引号内的双写转义 `''` → `'`。
- `build_pest._write_run_manifest` 使用 `serialize_manifest_scalar` 写入带单引号的值（如 `run_id: 'my_run_id'`）。
- `sobol_case._append_manifest` 写入不带引号的原始值（如 `sobol_samples: 64`）。

**影响**：当前 `read_flat_manifest` 主要读取 `sobol_case._append_manifest` 追加的字段（`sobol_samples`、`sobol_parameter_count`、`run_type` 等），这些字段均为无引号简单值，故未触发 bug。但若未来有人用 `read_flat_manifest` 读取 `build_pest` 写入的带引号字段（如 `run_id`），将返回带引号的字符串。

**建议**：在 O1 统一 `read_flat_manifest` 时，同步引入 `_strip_manifest_scalar` 的引号处理逻辑，使两个 manifest 读取器行为一致。

---

### M2 [次要] `sobol_repair._execute_replay` 硬编码 `runtime` 子目录路径

**位置**：`sobol_repair.py:89-108`

**现象**：

```python
runtime = source / "runtime"
script = runtime / "src/sensitivity/sa_model.py"
...
"--batch", str(runtime / "input/DSSBatch.v48"),
...
"--input-dir", str(runtime / "input"),
"--output-profile", str(runtime / "config/output_profile.json"),
```

`_execute_replay` 假设 source case 目录下存在 `runtime/` 子目录，且该目录内包含完整的项目结构（`src/`、`input/`、`config/`）。这是 `run_parallel.py` 的 agent sandbox 部署约定，在 `AGENTS.md` 的"Parallel Execution Model"中有描述。但该约定未在 `sobol_repair.py` 的 docstring 或 `repair_case` 的文档中显式声明。

**判断**：这是部署契约而非代码缺陷。`sobol_repair` 的 CLI 通过 `--source-case` 接收已部署的 case 目录，该目录由 `run_parallel.py` 准备，`runtime/` 子目录是 agent sandbox 的标准布局。但若有人直接对非 agent 部署的 case 目录运行 repair，会因 `runtime/` 不存在而失败。

**建议**：在 `repair_case` 的 docstring 中补充 `runtime/` 目录的部署契约说明，或在校验阶段检查 `(source / "runtime" / "src/sensitivity/sa_model.py").is_file()` 并给出明确错误信息。

---

### M3 [次要] `sobol_case.build_sobol_case` 的 PST 写回校验依赖 `pyemu` 重新解析

**位置**：`sobol_case.py:160-169`

**现象**：

```python
output_pst = destination / f"{case_name}.pst"
pst.write(str(output_pst))
verification = pyemu.Pst(str(output_pst))
adjustable = {
    str(name).strip().upper()
    for name, row in verification.parameter_data.iterrows()
    if str(row["partrans"]).lower() != "fixed"
}
if adjustable != selected:
    raise RuntimeError(...)
```

该段代码将 PST 写入磁盘后立即用 `pyemu` 重新解析，校验 adjustable 参数集合是否与 approved 集合一致。这是正确的防御性设计，但 `pyemu.Pst` 的解析是重量级操作（会解析整个 PST 文件），且 `pst.write` 后立即 `pyemu.Pst` 重读的逻辑在 `build_pest.py` 中也有类似模式（build → write → re-read → verify）。未来可考虑将 PyEMU 的写回校验抽取为共享工具。

**判断**：这是正确的防御性设计，不构成问题。仅作为后续重构的候选点。

**建议**：无立即行动。若未来 `build_pest.py` 和 `sobol_case.py` 均需 PST 写回校验，可提取为 `src/common/pest_utils.py::write_and_verify_pst`。

---

## 已验证一致的关键点（设计值得肯定）

本轮模块的科学严谨性显著高于前三轮。以下实现经核对确认正确，且部分设计值得作为项目最佳实践：

1. **`sobol_repair` 的不可变源 + 双重重放策略**：源 case 目录只读，失败成员重放两次，要求 `response_sha256` 和 `np.array_equal` 双重一致（第 224 行）。派生 case 的 manifest 记录完整的源哈希链（`derived_from_obs_sha256`、`derived_from_si_sha256`、`derived_from_sti_sha256`）。✓

2. **`sobol_repair._align_replay_vector` 的按名称对齐**：PEST++ 的响应 CSV 列顺序可能与 `sa_obs_order.txt` 不同，`_align_replay_vector` 按 observation name（case-insensitive）对齐，而非按位置。同时校验名称集合完全一致（第 78-84 行）。✓

3. **`sobol_audit._missing_sentinel_counts` 的 wn_ 豁免**：derived `wn_*` 响应（treatment contrast）可能合法等于 -99.0，仅对 source `tn*` 列检查 DSSAT sentinel。✓（规范 §4「Sobol 应在获批 Top-K 上运行」的工程基础）

4. **`sobol_audit` 的 preflight vs formal 区别处理**：`sobol_base_response_variance` 检查在 preflight 模式下仅记录零方差响应、不拒绝 case（第 182-201 行）。✓（规范 §4「preflight 通过后构建正式 N=64」）

5. **`sobol_bootstrap._load_design` 的 hybrid block 结构校验**：逐参数验证 hybrid block 中非当前参数的列与矩阵 A 一致、当前参数列与矩阵 B 一致（第 39-51 行）。✓（Saltelli 设计的正确性前提）

6. **`sobol_bootstrap` 的点估计复现校验**：`sobol_point_reproduction` 检查重算的 S1/ST 与 PEST++ 原始指数一致，使用宽松容差（`rtol=1e-3, atol=5e-4`）并注释原因（PEST++ 的响应和指数 CSV 是六位小数舍入文本）。✓（工程诚实）

7. **`sobol_case.load_approved_topk` 的完整审批链校验**：要求 `review_status=approved`、CSV 哈希匹配、`approval_status=approved` 全覆盖、参数数量匹配、且输入 bundle 和 output profile 的 SHA-256 与审批时一致（第 99-102 行）。✓（规范 §4「只有稳定 Morris 结果可以进入 Top-K 人工审核」）

8. **`sobol_convergence` 的 ranking_domain 独立比较**：收敛检查按 ranking_domain 分别计算 Spearman/Jaccard/rank_shift，最终 verdict 是所有 domain 的 AND（第 178-224 行）。✓（与 Morris 的多域排名契约一致）

9. **`sobol_case` 的 PST 写回校验**：写入磁盘后立即用 `pyemu.Pst` 重新解析，验证 adjustable 参数集合与 approved 集合一致（第 163-170 行）。✓

10. **`sobol_repair` 的修复后审计**：`repair_case` 第 295-297 行在派生 case 上运行 `write_sobol_audit`，拒绝未通过质量门的修复结果。✓

---

## 建议的后续行动（按优先级）

1. **O1（提取共享 `read_flat_manifest`）**：提取到 `src/common/project.py`，`sobol_audit` 和 `replay_morris_failure` 统一调用，同步引入引号处理（M1）。
2. **O2（提取共享 Saltelli 估计器）**：提取 `_saltelli_estimator(a, b, hybrid, variance)` 到 `sobol_repair.py`，`sobol_bootstrap` 的点估计部分调用共享实现。低优先级。
3. **M2**：在 `repair_case` docstring 中补充 `runtime/` 部署契约说明。

---

## 附：本轮未覆盖（下一轮候选）

- `build_pest.py`（~103KB，最大模块，需 1–2 轮；本轮仅交叉核对了 `_write_run_manifest` 的 manifest 写入格式）
- `run_dssat.py`（~87KB，DSSAT 执行引擎，独立一轮）
- `tools/freeze_bounds.py` + `prepare_*_bounds.py`（6 个 preparer，均调 `assert_valid_frozen_bounds`，可合并一轮）
- `src/sensitivity/sa_build_sen_case.py`（`build_case` 函数，被 `sobol_case` 和 Morris 工具共用）