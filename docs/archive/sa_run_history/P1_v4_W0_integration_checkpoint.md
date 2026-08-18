# P1 v4 — W0 集成检查点与环境冻结报告

> 任务ID：W0（集成检查点与环境冻结）
> 结论：**通过**。工作树已建立可追溯提交，跨线用途门禁落地，统一输入清单完整性检查已接入 SA/率定入口，论文导出不再仅凭 CSV 自报状态，全部阻塞性回归测试已落地。结果标注为 `engineering_preflight`（门禁实现），尚未触发任何正式科研运行。
> 更新日期：2026-07-16

## 1. 环境与版本基线

| 组件 | 版本 |
|---|---|
| Python | 3.13.12 |
| R | 未在 PATH（与 AGENTS.md 一致；正式渲染需在 PATH 固定 R 4.5.2） |
| DSSAT | v4.8（`C:\DSSAT48\DSCSM048.EXE` 存在） |
| PEST++ | 5.2.16-win（已打包） |
| Git 分支 | `codex/p0-research-credibility` |
| Git commit | 提交后由本报告所在 commit 给出 |

## 2. 三个核心 SHA-256（W0.4）

| 产物 | SHA-256 |
|---|---|
| v4 输出 profile (`configs/sa/eggplant_p1_outputs.json`) | `0923aa1ed16627243da8a2d50a63209bc9ba3fcb19f9e42d7e38b71ced9e27dc` |
| SA 反事实输入清单 (`data/user/experiments/xxql2501_sa_counterfactual_v1_20260716/input_manifest.json`) | `bdede79d723cfbf02e8517a86c56d6c6c1693c26a950fff83e7f104133ef7d77` |
| 冻结率定 bounds (`data/parameter_registry/bounds_frozen/eggplant/eggplant_p1_xxql2501_v3_20260716.csv`) | `6b7e31248c7eb1aca173209bf9f8c5c2f86822be55ac4915e60803e58000674a` |

`run_manifest.yaml` 中的 `bounds_sha256` / `input_manifest_sha256` / `output_profile_sha256` 现在会被多种子分析器（`analyze_multiseed`）跨 seed 比对，任何一个 seed 偏离即硬失败。

## 3. 已完成的门禁（W0.5 / W0.6）

### W0.6 — 统一输入清单完整性检查

新增 `src/common/input_manifest.py`，作为 SA、率定、确定性复跑入口共用的单一事实来源。检查内容：

1. 目录名与清单 `bundle_id` 一致（重命名/部分拷贝会被发现）；
2. 清单中每个文件存在且 SHA-256 匹配（不是只哈希清单文件本身）；
3. 目录中不得出现清单未记录的额外文件（防止注入未跟踪输入）；
4. 结构校验：`bundle_id` 必须为字符串，`files` 必须为非空对象数组，`prohibited_use` 必须为字符串数组。

辅助函数：`load_input_manifest`、`verify_manifest_integrity`、`verify_manifest_files`、`assert_use_allowed`、`verify_calibrated_input_bundle`。

### W0.5a — 率定用途门禁

- `src/calibration/build_pest.py`：在 `--input-dir` 解析后立即调用 `verify_calibrated_input_bundle`，对 `prohibited_use` 含 `parameter_calibration` 的 SA 反事实包硬失败（`parser.error`）。已用真实 SA 包 CLI 验证拒绝信息明确。
- `src/sensitivity/sa_build_sen_case.py`：在 `validate_input_bundle`（FileX/土壤一致性）之前调用 `verify_manifest_integrity`，先验证字节级完整性再验证语义一致性。
- "实际包可率定、SA 包不可率定"：`test_input_manifest.py::test_calibration_rejects_counterfactual_bundle` 与 `test_real_sa_counterfactual_bundle_rejected_for_calibration` 覆盖；真实率定包 `test_real_calibration_bundle_passes_integrity` 通过。

### W0.5b — 论文导出科研验证门禁

`src/reporting/export_paper_data.py` 的 `science_validated` 不再仅相信 comparison CSV 自报状态：

- 新增 `--run-manifest` 与 `--quality-report` 参数；非 DEMO 导出必须同时提供，且 `run_id` 与 comparison 表、run manifest、quality report 三方一致；
- 拒绝 comparison/phi 携带与 `--run-id` 不同的 run_id（混合 run_id 即拒绝，即便 DEMO 也不允许）；
- quality report 必须通过（`report.require_pass()`），否则按 `ScientificQualityError` 失败；
- DEMO 路径（`--allow-unvalidated-demo`）仍显式放行，输出 `DEMO_` 前缀与水印，不可作为论文证据；
- `paper_data_manifest.json` 新增 `upstream_validation` 字段，记录 run manifest 与 quality report 的路径、SHA-256 与状态。

为支持该门禁，`src/common/quality.py` 新增 `load_quality_report`（`QualityReport.write` 的逆运算）与 `read_flat_run_manifest_field`（读取扁平 `run_manifest.yaml` 标量）。

### W0.7 — R 侧 `--figure-ids` 模块选择

`paper/R/make_all.R` 增加 `--figure-ids`，将每个科学问题封装为可选模块（`fig2_phi`、`fig3_performance`、`fig4_dynamics`、`figs3_residuals`、`figs4_all_treatments`）。默认 `all` 保留全量渲染；选择 SA 图时不再被强制提供率定轨迹，反之亦然。轨迹/处理元数据需求变为条件触发（仅当选中需要它的模块时报错）。

## 4. 阻塞性回归测试（计划 §7）落地情况

| 测试 | 状态 | 文件 |
|---|---|---|
| `test_calibration_rejects_counterfactual_bundle` | ✅ | `tests/test_input_manifest.py` |
| `test_sa_rejects_wrong_bundle_id_or_treatment_set` | ✅ | `tests/test_sensitivity_water_nitrogen.py` |
| `test_input_manifest_file_hash_mismatch_is_rejected` | ✅ | `tests/test_input_manifest.py` |
| `test_morris_rejects_mixed_profile_input_or_bounds_hashes` | ✅ | `tests/test_morris_multiseed.py` |
| `test_morris_requires_exact_164_outputs_and_both_domains` | ✅ | `tests/test_morris_multiseed.py` |
| `test_unstable_morris_domain_is_not_science_validated` | ✅ | `tests/test_morris_multiseed.py` |
| `test_sobol_convergence_preserves_two_ranking_domains` | ✅ | `tests/test_sobol_budget_and_convergence.py` |
| `test_paper_export_requires_upstream_quality_report` | ✅（名 `test_validated_bundle_requires_upstream_manifest_and_quality_report`） | `tests/test_publication_figures.py` |
| `test_paper_export_rejects_mixed_run_ids_and_counterfactual_calibration_data` | ✅（名 `test_paper_export_rejects_mixed_run_ids_and_failing_quality_report` + `test_paper_export_rejects_mixed_run_id_in_comparison_table`） | `tests/test_publication_figures.py` |
| `test_make_all_selected_sa_figures_need_no_calibration_trajectory` | ✅ | `tests/test_publication_figures.py` |
| `test_dap50_rejects_nonmonotone_cumulative_series` | ✅ | `tests/test_sensitivity_water_nitrogen.py` |

附带修复：
- `morris_multiseed.analyze_multiseed` 的 `science_validated` 原无条件为 `True`，现已改为 `bool(stable)`，并新增显式 `case_quality_validated` 与 `ranking_stable` 字段（计划 W2 要求分开记录）。
- `sobol_convergence._rank_case` 原跨全部 response_group 求一个总分，现已按 `ranking_domain` 分别排名；收敛判定为两域 AND（任一域不收敛即整体不通过）。
- `sa_model._cumulative_dap_fraction` 原对下降累计节点静默返回当前 DAP，现已对任何非单调累计序列返回 `None`（→ `-99` 缺失哨兵），触发响应审计；单调性在插值前对全序列校验。

## 5. 测试结果

```
145 passed, 2 skipped in ~6.3s
```

（基线 124 passed + 21 个新增/改写测试；2 skipped 为既有。）

## 6. 生成/修改文件清单

新增：
- `src/common/input_manifest.py`
- `tests/test_input_manifest.py`
- `docs/reports/P1_v4_W0_integration_checkpoint.md`（本文件）

修改：
- `src/calibration/build_pest.py`（导入 + 用途门禁）
- `src/sensitivity/sa_build_sen_case.py`（导入 + 完整性检查）
- `src/sensitivity/morris_multiseed.py`（跨 seed 哈希一致性、164/双域校验、`science_validated` 条件化）
- `src/sensitivity/sobol_convergence.py`（按 ranking_domain 分别排名与收敛判定）
- `src/sensitivity/sa_model.py`（DAP50 非单调拒绝）
- `src/common/quality.py`（`load_quality_report`、`read_flat_run_manifest_field`）
- `src/reporting/export_paper_data.py`（上游质量门禁、混合 run_id 拒绝）
- `paper/R/make_all.R`（`--figure-ids` 模块选择）
- `tests/test_publication_figures.py`、`tests/test_morris_multiseed.py`、`tests/test_sensitivity_water_nitrogen.py`、`tests/test_sobol_budget_and_convergence.py`

## 7. 未解决风险与审批边界

- 无触发用户审批的变更：未改变公共 IC 生成方法/数值/SA bundle ID，未增删 164 项响应或双域定义，未启用 pwtadj1 或新误差模型，未将任何 DEMO/未过门结果升级为论文证据。
- R 未在 PATH：`--figure-ids` 已通过 Python 侧契约测试（字符串/守卫存在性），但未做端到端 R 渲染验证；正式渲染前需将选定 R 固定到 PATH（AGENTS.md 已记录 4.5.2/4.6 不兼容警告）。
- `morris_multiseed` 的双域强制仅在 contract 声明 `observation_count` 时触发（正式 P1 profile 命中）；合成单域单元测试 profile 不受影响。

## 8. 标注

本交付结果标注为 **`engineering_preflight`**（门禁与测试实现）。尚未启动任何正式科研运行；W1 `r=8` 预检可从本检查点冻结的工作树执行。
