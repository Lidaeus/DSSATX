# Code Review：报告管道模块（第 7 轮）

> 日期：2026-07-23
>
> 范围：`src/reporting/analyze_results.py`（1526 行）、`src/reporting/figure_data.py`（412 行）、`src/reporting/export_paper_data.py`（451 行）
>
> 对照规范：`AGENTS.md`（Paper Figure Pipeline 与 The frozen data contract 章节）、`docs/科研图表设计与开发计划.md`、`paper/README.md`
>
> 关联前轮：第 5 轮 M1（`_read_freshwt_var_by_run` 重复）
>
> 测试：`test_publication_figures.py`、`test_figure_data.py`、`test_export_paper_data.py`、`test_validation_metrics.py` — 全部通过

## 审查结论

三模块整体**与 AGENTS.md 硬规则无冲突**：matplotlib 禁令、R 唯一渲染器、frozen data contract、science_validated 多重门、realization 级 phi 等均一致。`figure_data.py` 作为 schema/VARIABLE_SPECS 单一来源的地位成立。`export_paper_data.py` 的上游验证链（run_manifest + quality_report + calibration_finalize 三重 run_id 一致 + finalize 显式授权）比"信任 CSV 字符串"显著更安全。主要改进空间集中在 `analyze_results.py` 的内部质量——与 `run_dssat.py` 的 6 函数重复及行为分叉是本轮最重要的发现。

---

## 已验证一致的关键点（15 项）

| # | 检查项 | 结论 |
|---|---|---|
| K1 | `export_paper_data.py` 不导入 matplotlib | ✓ grep 全文无 `matplotlib`；`test_r_is_the_only_paper_renderer` 强制断言 |
| K2 | R 是唯一论文图渲染器 | ✓ `paper_figures.py` / `figure_style.py` 不存在；`export_paper_data.py` 仅写 CSV + JSON manifest |
| K3 | comparison schema 列名与 AGENTS.md frozen data contract 完全一致 | ✓ `figure_data.py:13-37` 的 `REQUIRED_COMPARISON_COLUMNS` + `OPTIONAL_COMPARISON_COLUMNS` 逐字对应 |
| K4 | `dataset_role` 枚举 = {calibration, validation, diagnostic, legacy_unsplit} | ✓ `figure_data.py:104` `allowed_roles` 集合与 AGENTS.md 完全一致 |
| K5 | trajectory schema 列名与文档一致 | ✓ `figure_data.py:41-57` `TRAJECTORY_COLUMNS` 逐字对应；`statistic` 默认 `deterministic` |
| K6 | treatment_metadata 列 = treatment, treatment_label, water_level, nitrogen_level | ✓ `figure_data.py:59-64` 与 AGENTS.md 一致 |
| K7 | phi_ensemble 为 realization 级长表（非 mean 列） | ✓ `figure_data.py:361-383` 用 `melt` 展开为 iteration-realization-phi 长表 |
| K8 | `figure_data.py` 是 VARIABLE_SPECS / schema 单一来源 | ✓ `validation_metrics.py:42`、`export_paper_data.py:29` 均从 `figure_data` 导入 |
| K9 | science_validated 不信任 CSV 的 data_status 字符串 | ✓ `_resolve_upstream_validation` 要求三重 run_id 一致且 finalize 显式授权 |
| K10 | 混合 run_id 被拒（即使 DEMO 模式） | ✓ `export_paper_data.py:154-160` 在 DEMO 路径前即校验 |
| K11 | figure_data `performance_metrics` 残差 = simulated - observed | ✓ `figure_data.py:389` `residual = simulated - observed` |
| K12 | d-index（Willmott）公式正确 | ✓ `analyze_results.py:1068-1072` |
| K13 | RMSE 在 figure_data 与 analyze_results 中均用 sim-obs | ✓ |
| K14 | R 不读 DSSAT/PEST++ 临时文件 | ✓ `export_paper_data.py` 把 trajectory/treatment_metadata/phi 全部冻结为 CSV + SHA-256 manifest |
| K15 | DEMO 路径产出 `DEMO_` 前缀 + 水印，不可引用 | ✓ `export_paper_data.py:284-288, 336-344` |

---

## 发现清单

### O1 [严重·过度设计] 6 个 DSSAT 输出解析函数在 `analyze_results.py` 与 `run_dssat.py` 中重复定义（~160 行）

**位置**：`analyze_results.py:24,53,62,71,82,328` ↔ `run_dssat.py:174,203,438,491,553,564`

**现象**：`_parse_batch_entries`、`_infer_excode_from_filex`、`_yyddd_add_days`、`_nearest_on_or_before`、`_read_freshwt_var_by_run`、`_read_plantgro_vars_by_run` 在两个文件中各有一份副本。第 5 轮 M1 仅识别了 `_read_freshwt_var_by_run`，本次确认范围更广（6 个函数）。

两份副本还有**行为差异**：`_read_freshwt_var_by_run` 在 `analyze_results.py:116` 用 `s.lstrip().startswith("*")`，而 `run_dssat.py:472` 用 `s.startswith("*")`——对缩进行的处理不一致，是潜在维护陷阱。

---

### O2 [中·过度设计] `validation_metrics.py` 从 `analyze_results.py` 导入 9 个 `_` 前缀私有函数

**位置**：`validation_metrics.py:30-40`

**现象**：导入 `_infer_excode_from_filex`、`_nearest_on_or_before`、`_parse_batch_entries`、`_read_evaluate_out`、`_read_freshwt_var_by_run`、`_read_plantgro_vars_by_run`、`_read_tmt_harvest_obs`、`_read_tmt_process_obs`、`_yyddd_add_days`。私有前缀函数被跨模块导入，表明这些 DSSAT 解析器实为共享工具，应提取到独立模块（如 `src/dssat/output_readers.py`）。

---

### O3 [中·过度设计] `ensure_results_dir()` 是已废弃的 no-op，仍被调用 9 次

**位置**：`analyze_results.py:627-628` 定义；调用点 391,457,561,810,1115,1291,1325,1359

**现象**：函数体仅 `pass  # Deprecated, use run_dir directly`。9 个调用点全部是死调用。

---

### M1 [中·冲突] `analyze()` 残差符号与项目规范相反

**位置**：`analyze_results.py:861`

**现象**：`residual = measured - simulated`（obs - sim），而 AGENTS.md 规定"Residuals defined as simulated - observed (positive = overestimate)"。此处正残差 = 模拟低估，与规范相反。该残差写入 `{prefix}_error_diag.csv` 的 `Residual` 列并用于 `bias`（line 895）与 `Percent_Error`（line 864）。虽是运行诊断而非论文图输入，但符号约定不一致易混淆。同模块内 `_rmse_nrmse_d`、`_harvest_metrics_from_compare_df`、`_process_metrics_from_compare_df` 均用 sim-obs，唯独 `analyze()` 反向。

---

### O4 [低] `adapt_legacy_comparison_outputs` 未覆盖 joint-compare 变量

**位置**：`figure_data.py:190-209`

**现象**：仅适配 process（LAID/LWAD/SWAD）与 harvest（DRY/FRESH INC/CUM），不适配 joint（HWAM/LAIX/CNAM/CNAA）。legacy 历史数据若含 Evaluate.OUT 的 joint 变量无法进入 tidy 契约。可能是有意（joint 来源结构不同），但未在代码或注释中说明。

---

### O5 [低] `_make_standard_plots` 输出文件名不符合 `diagnostic_*` 约定

**位置**：`analyze_results.py:717-785`

**现象**：产出 `scatter_LAID.png`、`timeseries_LAID_by_TN.png` 等，既非 `diagnostic_*` 也非 `Fig`/`FigS`。AGENTS.md 要求 Python 诊断输出用 `diagnostic_*` 前缀。虽不违反"never Fig/FigS"，但命名约定漂移。

---

### M2 [次要] `cleanup_workspace` 日志输出错误变量

**位置**：`analyze_results.py:677`

**现象**：`print(f"Moved {count} files to {RESULTS_DIR}")` 实际移动目标是 `dst_dir`，当 `dst_dir != RESULTS_DIR` 时日志误导。

---

### M3 [次要] `analyze()` 忽略 `run_dir` 作为输出目录

**位置**：`analyze_results.py:884,923,956,961,1021`

**现象**：函数接受 `run_dir` 参数用于查找 `.pst`，但所有输出 CSV 硬编码写入 `RESULTS_DIR` 常量，与同模块其他函数（`deterministic_*_compare` 优先用 `run_dir`）的行为不一致。

---

### M4 [次要] CSV 编码不一致

**位置**：`analyze_results.py` 用 `utf-8-sig`；`export_paper_data.py` 与 `figure_data` 路径用 `utf-8`

**现象**：同一报告管道内输出编码不统一，可能导致下游 R/pandas 读取时 BOM 处理差异。

---

### M5 [次要] `get_ensemble_files` 硬编码废弃路径

**位置**：`analyze_results.py:638`

**现象**：硬编码 `os.path.join(WORKSPACE, "Calibration_Results", "_runs")`，而 AGENTS.md 数据流定义运行目录为 `workspace/runs/{run_id}/`。该路径对应旧目录结构，可能已失效。

---

### M6 [次要] `_resolve_upstream_validation` 的 `validated` 表达式未显式含 `report.science_validated`

**位置**：`export_paper_data.py:236-239`

**现象**：`validated = bool(report.process_completed and self_reported_validated)`，未直接检查 `report.science_validated`。当前安全（finalize artifact 是最终权威），但逻辑冗余。

---

### M7 [次要] `read_dssat_trajectories` 强依赖 DSSAT 输出含 `TREATMENT` 行

**位置**：`figure_data.py:250-253`

**现象**：用 `re.match(r"^TREATMENT\s+(\d+)\b", line)` 识别处理号；若 DSSAT 未输出该行，`current_treatment` 恒为 None，所有数据行被跳过，最终抛 "No readable trajectories"。

---

## 建议的后续行动（按优先级）

| 优先级 | 行动 | 对应问题 | 预期收益 |
|---|---|---|---|
| **P1** | 提取 6 个重复的 DSSAT 解析器到共享模块（如 `src/dssat/output_readers.py`），让 `analyze_results.py`、`run_dssat.py`、`validation_metrics.py` 统一导入；同步消除 `_read_freshwt_var_by_run` 的 `lstrip` 行为差异 | O1, O2 | 消除 ~160 行重复，消除行为分叉风险 |
| **P2** | 修正 `analyze()` 中 `residual = measured - simulated` 为 `simulated - measured`，使全模块残差约定统一为 sim-obs | M1 | 消除与 AGENTS.md 规范的符号冲突 |
| **P3** | 删除 `ensure_results_dir()` 函数及其 9 个调用点 | O3 | 移除死代码 ~12 行 |
| **P4** | 修正 `cleanup_workspace` 日志：`RESULTS_DIR` → `dst_dir` | M2 | 日志准确性 |
| **P5** | 统一报告管道 CSV 输出编码（建议统一 `utf-8`） | M4 | 下游一致性 |
| **P6** | 评估 `_make_standard_plots` 输出是否应改用 `diagnostic_*` 前缀 | O5 | 命名约定合规 |
| **P7** | 核实 `get_ensemble_files` 的 `Calibration_Results/_runs` 路径是否仍被使用 | M5 | 减少失效路径 |

**可删代码行数估计**：O1(~160 行重构为 import) + O3(~12 行纯删除) = **~170 行**。
