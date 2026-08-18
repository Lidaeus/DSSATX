# Code Review：DSSAT 执行引擎（第 5 轮）

> 日期：2026-07-23
>
> 范围：`src/dssat/run_dssat.py`（2839 行）— 参数注入、DSSAT 执行、PEST 输出文件生成
>
> 对照规范：`AGENTS.md`、`docs/DSSAT并行隔离与输入路径规范.md`、`docs/敏感性分析与率定用户指南.md`、`docs/论文讨论写作参考_率定范式季节适应性与异参同效.md`
>
> 关联前轮：第 3 轮 O3（`_infer_soil_id_from_filex` 三个副本）、第 2 轮 C3（XFINT 安全约束）
>
> 测试：`test_dssat_safety.py` (10)、`test_dssat_failure_artifacts.py` (1)、`test_bounds_injection_preflight.py` (2)、`test_t10_direct_harvest.py` (6)、`test_management_dap_policy.py` (12) — 31 passed

## 审查结论

`run_dssat.py` 是项目中最核心的运行时模块，承担参数注入、DSSAT 执行、PEST 输出文件生成三大职责。其**关键算法正确性经测试验证**（`_format_to_width` 的 DSSAT 固定宽度格式、`_bounded_nearest_within_window` 的 T10 d±1 窗口、`_atomic_write_lines` 的原子写入、`validate_candidate_parameters` 的 advisory-only 语义均正确）。但该文件是**代码重复最严重的模块**——内部 `_read_evaluate_out` 重复 3 次（90 行）、`_as_int` 重复 5 次（25 行）、`_read_tmt_*` 函数结构几乎完全相同（170 行）——且包含 2 个死函数。此外，`_infer_soil_id_from_filex` 是项目中第三个副本（第 3 轮 O3 已记录），`_read_freshwt_var_by_run` 在 `analyze_results.py` 中有独立副本。

---

## 发现清单

### O1 [严重] `_read_evaluate_out` 在三个函数中重复定义（3 × 30 行 = 90 行）

**位置**：`_write_pest_eval_from_evaluate`（第 1022–1048 行）、`_write_pest_grow_from_evaluate`（第 1096–1122 行）、`_write_pest_joint_from_evaluate`（第 1167–1193 行）

**现象**：三个函数各自定义了一个完全相同的局部 `_read_evaluate_out` 函数：

```python
def _read_evaluate_out(path):
    rows = []
    header = None
    with open(path, "r") as f:
        for line in f:
            s = line.rstrip("\n")
            if not s.strip():
                continue
            stripped = s.lstrip()
            if stripped.startswith("@RUN"):
                header = stripped.split()
                continue
            if header is None:
                continue
            if stripped.startswith("*") or stripped.startswith("@"):
                continue
            if not re.match(r"^\s*\d+\s+", s):
                continue
            parts = stripped.split()
            if len(parts) < len(header):
                parts += ["-99"] * (len(header) - len(parts))
            rows.append(dict(zip(header, parts[: len(header)])))
    return pd.DataFrame(rows)
```

三个副本逐字相同，仅因 Python 作用域被定义为局部函数，无法跨函数共享。

**建议**：提取为模块级函数 `_read_evaluate_out(path) -> pd.DataFrame`，三个 `_write_pest_*` 函数统一调用。预计删 60 行。

---

### O2 [严重] `_as_int` 在五个函数中重复定义（5 × 5 行）

**位置**：
- `_read_tmt_harvest_events` 第 238–242 行
- `_read_tmt_process_points` 第 336–340 行
- `_write_pest_eval_from_evaluate` 第 1050–1056 行
- `_write_pest_grow_from_evaluate` 第 1124–1130 行
- `_write_pest_joint_from_evaluate` 第 1195–1201 行

**现象**：五个函数各自定义了完全相同的 `_as_int` 辅助函数：

```python
def _as_int(v, default=-99):
    try:
        if pd.isna(v):
            return default
        return int(float(v))
    except Exception:
        return default
```

其中 `_read_tmt_*` 版本不含 `pd.isna` 检查（因为解析的是 dict 而非 pandas），其余三个版本完全一致。

**建议**：提取为模块级函数 `_as_int(v, default=-99)`，统一处理 `pd.isna` 检查（对 dict 无害）。预计删 20 行。

---

### O3 [中] `_read_tmt_harvest_events` 和 `_read_tmt_process_points` 结构几乎完全相同（~170 行）

**位置**：`_read_tmt_harvest_events`（第 212–287 行）、`_read_tmt_process_points`（第 310–376 行）

**现象**：两个函数共享相同的 TMT 文件解析框架：
1. 找 `@TRNO` header → 按 header 解析行 → 补 `-99` 到 header 长度 → 构建 `dict(zip(header, parts))`
2. 定义完全相同的 `_as_int` 和 `_as_float` 局部函数
3. 按 `tn`（treatment number）分组，按 `date` 排序

唯一区别是提取的列：
- `_read_tmt_harvest_events`：`CHPDT`、`HPODW`、`PWAD`（收获事件）
- `_read_tmt_process_points`：`L#SD`、`LAID`、`LWAD`、`SWAD`（生长过程点）

两个函数合计约 170 行，其中约 120 行为相同框架代码。

**建议**：提取通用 TMT 解析器 `_read_tmt_file(path, columns) -> dict[int, list[dict]]`，两个函数调用通用解析器后仅处理各自特有的列逻辑。这是低优先级重构，但会显著减少代码量。

---

### O4 [中] `_read_plantgro_pwad_by_run` 是死函数（53 行，零调用者）

**位置**：`run_dssat.py:379-431`

**现象**：全仓 grep 确认 `_read_plantgro_pwad_by_run` 仅在自身定义处出现，无任何外部调用者。该函数从 `PlantGro.OUT` 按 `*RUN` 段读取 `PWAD` 列并累积，但其功能已被 `_read_plantgro_vars_by_run`（第 491 行，支持多变量）和 `_read_freshwt_var_by_run`（第 438 行，从 FreshWt.OUT 读取收获变量）覆盖。

**建议**：删除。预计删 53 行。

---

### O5 [中] `_read_freshwt_chpdt_by_run` 是死包装器（2 行，零调用者）

**位置**：`run_dssat.py:434-435`

```python
def _read_freshwt_chpdt_by_run(freshwt_path):
    return _read_freshwt_var_by_run(freshwt_path, "CHPDT")
```

全仓 grep 确认无外部调用者。`_read_freshwt_var_by_run(freshwt_path, "CHPDT")` 在其唯一的生产消费者（`_write_pest_harvest_from_tmt_and_freshwt` 第 639 行）中已直接调用。

**建议**：删除。预计删 2 行。

---

### O6 [中] `_infer_soil_id_from_filex` 是项目中第三个副本（第 3 轮 O3 已记录）

**位置**：`run_dssat.py:1336-1373`；对照 `build_pest.py:1696-1730`、`sa_generate_param_review_csv.py:173-210`

**现象**：三个模块各自实现了从 FILEX 的 `*FIELDS` 段解析 `ID_SOIL` 的逻辑（累计约 106 行），详见第 3 轮 O3。

**建议**：与第 3 轮 O3 同步解决——提取到 `src/dssat/` 或 `src/common/` 共享函数。

---

### C1 [中] `run_model()` 引用未在模块级定义的 `HARVEST_VAR`

**位置**：第 2771 行（`run_model()` 内）vs 第 2812 行（`__main__` 块）

**现象**：

```python
# 第 2771 行（run_model 内）
_write_pest_harvest_from_tmt_and_freshwt(
    BATCH_FILE, "FreshWt.OUT", _harvest_pest_file(),
    harvest_var=HARVEST_VAR,  # <-- 未在模块级定义
)

# 第 2812 行（__main__ 块）
HARVEST_VAR = (args.harvest_var or "CHPDT").strip().upper()
```

`HARVEST_VAR` 仅在 `__main__` 块中定义，而 `run_model()` 在第 2839 行从 `__main__` 调用，因此实际运行时不会触发 `NameError`。但 `run_model()` 是一个可被外部导入的公开函数（无下划线前缀），如果任何代码在 `__main__` 块之外调用 `run_model()`，将因 `HARVEST_VAR` 未定义而崩溃。

**当前保护**：`src/calibration/run_dssat.py` 有自己的 `run_model()` 实现，不导入 `run_dssat.run_model`。`run_dssat.py` 的 `run_model()` 仅从 `__main__` 调用。

**建议**：将 `HARVEST_VAR` 改为 `run_model()` 的参数（默认 `"CHPDT"`），消除对 `__main__` 块全局变量的隐式依赖。

---

### C2 [中] `run_model()` 使用 `global BATCH_FILE` 修改模块级状态

**位置**：第 2647 行 `global BATCH_FILE`，第 2713 行 `BATCH_FILE = batch_dst`

**现象**：`run_model()` 在运行时将模块级 `BATCH_FILE` 从原始值（如 `"DSSBatch.v48"`）修改为本地化后的路径（如 `"/path/to/run_dir/DSSBatch.v48"`）。如果同一进程内多次调用 `run_model()`，第二次调用将使用上一次的本地化路径，可能导致路径解析错误。

**当前保护**：`run_model()` 在 `__main__` 中仅调用一次，且 `src/calibration/run_dssat.py` 有独立实现。但该全局状态修改使模块不可重入。

**建议**：将 `BATCH_FILE` 的本地化路径作为局部变量传递，避免修改模块级全局状态。

---

### M1 [次要] `_read_freshwt_var_by_run` 在 `analyze_results.py` 中有独立副本

**位置**：`run_dssat.py:438-488` vs `analyze_results.py:82-132`

**现象**：`analyze_results.py` 中定义了自己的 `_read_freshwt_var_by_run`（约 50 行），逻辑与 `run_dssat.py` 的版本几乎相同（逐行解析 FreshWt.OUT、找 `*RUN` 段、找 `@YEAR` header、提取变量值）。两个副本已独立演化，未来可能不一致。

**建议**：`analyze_results.py` 改为从 `run_dssat.py` 导入（与 `validation_metrics.py:35` 和 `dap_policy.py:23` 一致）。三个消费者统一为一个来源。

---

### M2 [次要] `_read_tmt_harvest_events` 和 `_read_tmt_process_points` 被 workspace 脚本作为私有 API 导入

**位置**：`workspace/generate_pst.py:99`、`workspace/generate_pst_improved.py:115`、`workspace/generate_pest_outputs.py:11` 等

**现象**：workspace 下的遗留脚本直接导入 `run_dssat` 的私有函数（下划线前缀）。这些是历史迁移产物，`workspace/` 下的脚本是 `src/` 的 stub。

**建议**：workspace 脚本的清理独立于本次代码审查。这是已知的技术债务。

---

### M3 [次要] 混合 `os.path` 和 `pathlib.Path`

**位置**：多处

**现象**：`_resolve_batch_path`（第 121–137 行）使用 `os.path.exists`、`os.path.join`、`os.path.normpath`；`_is_same_path`（第 791–799 行）混合 `os.path.samefile` 和 `os.path.normcase`；而 `_read_param_dict`（第 1719 行）使用 `os.path.exists`。模块顶部导入 `from pathlib import Path`（第 12 行），但在 I/O 密集型函数中仍使用 `os.path`。

**建议**：低优先级。将 `_resolve_batch_path`、`_is_same_path`、`_read_param_dict` 等函数统一为 `pathlib.Path`。这是逐步重构，不影响功能。

---

## 已验证一致的关键点（设计值得肯定）

1. **`validate_candidate_parameters` 的 advisory-only 语义**：物理边界越界、温度顺序违反、SLLL<SDUL<SSAT 违反均仅输出 `RUNNER_ADVISORY` 警告而**不拒绝**候选参数。NaN/Inf 仍然拒绝（因为无法写入 DSSAT 输入文件）。✓（与 `AGENTS.md`「runner 不得冻结 PEST++ 实现」一致）

2. **`_format_to_width` 的 DSSAT 固定宽度格式**：~90 行的复杂函数，正确处理缩略小数点格式（`.1234`）、trailing dot（`123.`）、科学计数法回退等 DSSAT 特有的格式约定。✓（测试覆盖：`test_cultivar_injection_changes_only_requested_parameter` 验证 `LFMAX=1.50` 正确写入 6 字符字段）

3. **`_bounded_nearest_within_window` 的 T10 d±1 窗口**：正确实现 `d±1` 窗口搜索、ties 解析到 later date、跳过 -99 sentinel 和 NaN。`_yyddd_add_days` 正确处理 YYDDD 跨年边界。✓（规范 §8 T10 方案「T10 bounded-nearest read」）

4. **`_atomic_write_lines` 的原子写入**：使用 `tempfile.mkstemp` + `os.fsync` + `os.replace`，失败时重试 8 次。✓（并行执行场景下的文件安全）

5. **`_acquire_file_lock` / `_release_file_lock` 的锁机制**：使用 `os.O_CREAT | os.O_EXCL` 原子创建锁文件，支持 stale lock 检测（900s 超时），写入 PID 和时间戳。✓（并行 agent 隔离）

6. **`_write_pest_harvest_from_tmt_and_freshwt` 的 T10 直接累积逻辑**：CHFPW/CHPDT 以**直接累积序列**从 FreshWt.OUT 读取（非差分），同时保留 legacy `@PWADS@`/`@PWAIS@` 差分路径用于向后兼容诊断。✓（T10 规范 §8）

7. **`_assert_fresh_nonempty` 的陈旧文件检测**：检查 `mtime` 是否在运行开始时间之后，容忍 2s 时钟偏差。✓（防止读取前一次运行的残留输出）

8. **XFINT 的 advisory 而非拒绝**：`update_eco_file` 第 1976–1983 行对 XFINT < 0.12 或 > 0.50 仅输出 `RUNNER_ADVISORY`，不拒绝实现。✓（与第 2 轮 C2 的「runner 不拦截」决策一致）

9. **`_write_dssatpro_with_crd` 的 CRD 路径重写**：正确将 DSSATPRO 的 `CRD` 行指向 run_dir，使 DSSAT 从 run_dir 解析 FileX/genotype/SOIL。✓（DSSAT 并行隔离规范 §2.2）

10. **`_localize_experiment_files` 的 TMX/TMA/TMT 三件套**：正确复制实验文件的 TMX（FileX）、TMA（time series）、TMT（treatment）到 run_dir。✓（并行隔离规范）

---

## 建议的后续行动（按优先级）

1. **O1（删除 `_read_evaluate_out` 重复）**：提取为模块级函数，删 60 行。立即行动。
2. **O2（删除 `_as_int` 重复）**：提取为模块级函数，删 20 行。立即行动。
3. **O4 + O5（删除死函数）**：删除 `_read_plantgro_pwad_by_run`（53 行）和 `_read_freshwt_chpdt_by_run`（2 行）。立即行动。
4. **C1 + C2（消除全局状态）**：`HARVEST_VAR` 改为 `run_model()` 参数；`BATCH_FILE` 局部化。中优先级。
5. **O3（统一 TMT 解析）**：提取通用 `_read_tmt_file` 框架。低优先级。
6. **O6（统一 `_infer_soil_id_from_filex`）**：与第 3 轮 O3 同步解决。低优先级。
7. **M1（统一 `_read_freshwt_var_by_run`）**：`analyze_results.py` 改为导入。低优先级。

**合计可删代码**：O1(60) + O2(20) + O4(53) + O5(2) = **135 行**。

---

## 附：本轮未覆盖（下一轮候选）

- `build_pest.py`（~103KB，最大模块，前 5 轮已多次交叉核对，完整审查需 1–2 轮）
- `src/calibration/run_dssat.py`（PEST++ 入口，三层隔离实现，与 `run_dssat.py` 的关系值得专审）
- `src/reporting/analyze_results.py` + `validation_metrics.py`（后处理 + 指标，其中有 `_read_freshwt_var_by_run` 副本）
- `tools/freeze_bounds.py` + `prepare_*_bounds.py`（6 个 preparer + 边界冻结，可合并一轮）