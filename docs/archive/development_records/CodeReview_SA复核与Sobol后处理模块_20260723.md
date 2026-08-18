# Code Review：SA 复核 CSV 与 Sobol 后处理模块（第 3 轮）

> 日期：2026-07-23
>
> 范围：`src/sensitivity/sa_generate_param_review_csv.py`（640 行）、`src/sensitivity/sa_postprocess_sobol_interpret.py`（130 行）、`src/sensitivity/sa_postprocess_sobol.py`（528 行）
>
> 对照规范：《敏感性分析与率定用户指南》§4（2026-07-22）、《Morris v4 结果与 Sobol 参数选择》（2026-07-21）、《Sobol 敏感性分析设计方案》（2026-07-20）、`AGENTS.md` 论文图表双轨约定
>
> 关联前轮：第 1 轮（权重/观测策略）、第 2 轮（param_registry，其中 C3 DEFAULT_BOUNDS 漂移直接牵连本模块）
>
> 测试：`test_sa_supplement_tables.py` (1)、`test_sa_paper_figures.py` (6)、`test_constraint_review.py` (2)、`test_sobol_repair.py` (3)、`test_sobol_workflow.py` (8) — 24 passed

## 审查结论

本轮审查三个 SA 后处理工具，发现 **与前三轮同构的过度设计问题**：`sa_postprocess_sobol_interpret.py` 全文件为死代码（130 行，硬编码绝对路径，零生产调用方），`sa_generate_param_review_csv.py` 中存在第三方副本的参数分组逻辑、土壤 ID 推断、以及 DSSAT 文件解析，均与 `build_pest.py` / `run_dssat.py` / `param_registry.py` 的对应实现分立重复。此外 `sa_generate_param_review_csv.py` 通过 `compute_default_bounds` 消费第 2 轮的 C3 漂移，将陈旧的 DEFAULT_BOUNDS 值写入 SA 参数复核 CSV。

---

## 发现清单

### C1 [中·冲突] `sa_generate_param_review_csv.py` 通过 `compute_default_bounds` 传播第 2 轮 C3 漂移

**位置**：`sa_generate_param_review_csv.py:66-67,480,515,537,561,584`

**现象**：`_default_bounds` 是对 `compute_default_bounds` 的无附加逻辑包装器。第 2 轮 C3 确认 `DEFAULT_BOUNDS` 中 XFINT=(0.10, 0.35) 而非 T9/T10 权威冻结的 (0.08, 0.50)、XFPHT=(35, 70) 而非 T10 的 (31, 70)。当 CUL/ECO 的 `.base` 文件不包含 `999991`/`999992` 边界行时（第 474/514 行 fallback），以及 SPE/SOIL/IC 全部参数（第 537/561/584 行），该模块直接调用 `_default_bounds` → `compute_default_bounds` → 查 `DEFAULT_BOUNDS`，将陈旧范围写入 SA 参数复核 CSV。

**影响**：SA 参数复核 CSV 是人工审核参数范围的入口文档。若范围与 T9/T10 科学决策不一致，审核者可能误将陈旧范围作为讨论起点。当前 T9/T10 正式率定通过 `--bounds-id` 冻结 CSV 路径，故正式率定未受影响；但 SA 复核 CSV 的辅助决策价值被削弱。

**建议**：与第 2 轮 C3 同步解决——将 `DEFAULT_BOUNDS` 中 XFINT/XFPHT/SLAVR 同步到最新冻结值，或在本模块 `_default_bounds` 入口注释「范围仅为 SA 初始建议，正式率定一律以 frozen bounds 为准」。

---

### O1 [严重·过度设计] `sa_postprocess_sobol_interpret.py` 全文件为死代码

**位置**：`src/sensitivity/sa_postprocess_sobol_interpret.py`（130 行）

**现象**：
- **零生产调用方**：全仓 grep 无任何 Python 文件 `import` 或调用该模块。仅 `tools/migrate_phase2.py` 和 `tools/setup_workspace.py` 以文件名引用记录迁移历史。
- **零测试**：无任何 `test_*` 文件测试该模块。
- **硬编码绝对路径**（第 14–15 行）：
  ```python
  sti_csv_path = r"c:\DSSAT48\Tomato_Cal\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case\sa_sen_sobol.sobol.sti.csv"
  params_csv_path = r"c:\DSSAT48\Tomato_Cal\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case\sa_params.csv"
  ```
  这些路径在任何非原开发机器上均不可用。模块无 CLI、无 `argparse`，作为 `if __name__ == "__main__"` 脚本也无法被外部调用。
- **功能已被取代**：`sa_postprocess_sobol.py`（528 行）提供了完整的 CLI、质量门、诊断图生成和 CSV 导出，是当前生产级别的 Sobol 后处理工具。`sa_postprocess_sobol_interpret.py` 生成的 Markdown 表格（第 98–129 行）是 `sa_postprocess_sobol.py` 中 `_write_onepage_tables` 功能的子集。
- **自带参数映射字典**（第 70–82 行 `param_locs`）：是项目中参数→位置映射的**第四个独立副本**（详见 O2）。

**过度设计判断**：该文件是从 `Workspace/` 迁移而来的历史脚本，迁移时保留了原始形态但从未被集成到生产管道。其功能已被 `sa_postprocess_sobol.py` 完整覆盖，且硬编码路径使其不可移植。

**建议**：删除 `sa_postprocess_sobol_interpret.py`，同步清理 `tools/setup_workspace.py:143` 和 `tools/migrate_phase2.py:97-98` 中的引用。预计删 130 行。

---

### O2 [严重] `_infer_pargp` 是参数分组逻辑的第三个独立副本

**位置**：`sa_generate_param_review_csv.py:70-119`；对照 `param_registry.py:195-256`（已死，第 2 轮 O2）、`build_pest.py:2534-2605`（生产）

**现象**：项目中存在三个 `_infer_pargp` / `infer_parameter_group` 实现：

| 副本 | 位置 | 行数 | 状态 |
|---|---|---|---|
| `infer_parameter_group` | `param_registry.py:195-256` | 62 | 死代码（第 2 轮 O2） |
| `_infer_pargp_for_name` | `build_pest.py:2534-2605` | 72 | 生产（率定用） |
| `_infer_pargp` | `sa_generate_param_review_csv.py:70-119` | 50 | 生产（SA 复核用） |

三者逻辑不同但服务于同一目的。例如：
- `param_registry.infer_parameter_group` 使用 `startswith` 前缀匹配（`param_registry.py:218-232`）
- `sa_generate_param_review_csv._infer_pargp` 使用显式集合成员测试（`sa_generate_param_review_csv.py:91,104,111`）
- `build_pest._infer_pargp_for_name` 接受 `cul_params`/`eco_params` 参数集合并据此判断

三个副本的 `pargp` 分类结果未必完全一致（例如某个参数在 `build_pest` 中因上下文被判为 `ECO_Other`，而在 `sa_generate_param_review_csv` 中直接落入 `ECO_Other`）。

**判断**：`sa_generate_param_review_csv._infer_pargp` 虽然逻辑合理（显式集合比前缀匹配更精确），但它是第三份独立实现。如果参数分组规则需要调整，三个副本须同步修改，增加了维护风险。

**建议**：将 `sa_generate_param_review_csv._infer_pargp` 的显式集合逻辑提升为 `param_registry` 中的权威实现（替换已死的 `infer_parameter_group`），`build_pest._infer_pargp_for_name` 和 `sa_generate_param_review_csv._infer_pargp` 均改为调用该权威实现。这是低优先级重构，当前三副本均能正常工作，但应在下一轮清理中统一。

---

### O3 [中] `_infer_soil_id_from_filex` 是第三个独立副本

**位置**：`sa_generate_param_review_csv.py:173-210`；对照 `build_pest.py:1696-1730`、`run_dssat.py:1336-1368`

**现象**：三个模块各自实现了从 FILEX 的 `*FIELDS` 段解析 `ID_SOIL` 的逻辑：

| 副本 | 位置 | 行数 |
|---|---|---|
| `_infer_soil_id_from_filex` | `sa_generate_param_review_csv.py:173-210` | 38 |
| `_infer_soil_id_from_filex` | `build_pest.py:1696-1730` | 35 |
| `_infer_soil_id_from_filex` | `run_dssat.py:1336-1368` | 33 |

三个实现的核心逻辑完全相同（逐行扫描 `*FIELDS` 段 → 找 `@` 头部 → 定位 `ID_SOIL` 列 → 读取第一行数据），但细节上略有差异（如注释行处理、空行跳过方式）。累计约 106 行重复代码。

**建议**：提取为 `src/common/filex_utils.py` 或 `src/dssat/` 下的共享函数，三个模块统一调用。

---

### O4 [中] `_default_bounds` 是 pointless 一行包装器

**位置**：`sa_generate_param_review_csv.py:66-67`

```python
def _default_bounds(name, init, location):
    return compute_default_bounds(name, init, location)
```

该函数仅调用 `compute_default_bounds` 并原样返回三元组，零附加逻辑。存在的原因是历史迁移时保留了原始调用接口，但当前 `generate_review_csv` 中 6 处调用（第 480/515/537/561/584 行）均可直接替换为 `compute_default_bounds`。

**建议**：删除 `_default_bounds`，直接调用 `compute_default_bounds`。

---

### O5 [中] DSSAT 文件解析完全独立于 `build_pest.py` / `run_dssat.py`

**位置**：`sa_generate_param_review_csv.py:28-63,122-170,213-307,310-371`

**现象**：该模块包含 4 个独立的 DSSAT 文件解析函数，与 `build_pest.py` 和 `run_dssat.py` 中的对应解析无共享代码：

| 函数 | 行数 | 功能 | build_pest/run_dssat 中对应 |
|---|---|---|---|
| `_read_table_row_by_key` | 28-56 | 读取 CUL/ECO 表行 | `build_pest.py` 有独立解析逻辑 |
| `_read_spe_params` | 122-170 | 正则解析 SPE 参数 | `build_pest.py` 从 `.base` 模板解析 |
| `_read_soil_params` | 213-307 | 解析 SOIL.SOL 剖面 | `run_dssat.py` 有独立解析 |
| `_read_initial_conditions_sh2o` | 310-371 | 解析 FILEX IC 段 | `build_pest.py` 使用 PEST 模板注入 |

其中 `_read_spe_params`（第 122–170 行）尤其脆弱：它使用正则表达式在原始 SPE 文件的文本行中匹配浮点数，并依赖 `PARMAX,PHTMAX`、`WTFSD,PORPT`、`FINREF,SLAREF` 等硬编码的 needle 字符串定位。这与 `build_pest.py` 从 `.base` 模板文件的 `!Calibration` 标记行读取结构化参数的机制完全不同。如果 SPE 文件的格式或注释文本发生变化，`_read_spe_params` 可能静默返回不完整数据。

**判断**：该模块是一个独立工具，不依赖 `build_pest.py` 的庞大上下文是合理的设计选择。但 `_read_spe_params` 的脆弱性和 `_read_soil_params` 的复杂性（约 95 行）表明，如果未来需要维护这些解析器，独立实现会增加成本。

**建议**：低优先级。如果 DSSAT 文件解析在未来需要统一维护，优先将 `_read_spe_params` 替换为从 `.base` 模板文件读取（与 `build_pest.py` 同源），而非维护两套独立的 SPE 解析器。

---

### M1 [次要] `cul_keep`/`eco_keep`/`spe_keep` 硬编码白名单与 `!Calibration` 标记机制脱钩

**位置**：`sa_generate_param_review_csv.py:401-461`

**现象**：模块通过硬编码的 `cul_keep`（14 个参数）、`eco_keep`（14 个参数）、`spe_keep`（27 个参数）集合筛选参数。而 `build_pest.py` 通过 `.base` 模板文件中的 `!Calibration` 注释标记自动发现可率定参数。如果 `.base` 文件新增了 `!Calibration` 标记的参数（例如 T9 将 FL-VS 标记为活动参数），`sa_generate_param_review_csv.py` 不会自动包含，需手动同步白名单。

**判断**：目前白名单与 `.base` 文件一致（经核对 T9/T10 的 `!Calibration` 标记参数均在白名单中），但架构上存在脱钩风险。

**建议**：长期考虑将白名单替换为从 `.base` 文件读取 `!Calibration` 标记（与 `build_pest.py` 同源），或在模块注释中标注「白名单须与 `.base` 文件 `!Calibration` 标记保持同步」。

---

### M2 [次要] `sa_postprocess_sobol_interpret.py` 的 `param_locs` 字典缺少 TO21 和 TM1

**位置**：`sa_postprocess_sobol_interpret.py:70-82`

**现象**：`param_locs` 字典包含 TO11、TO12、TO13、TO22、TM2、TM3，但缺少 TO21 和 TM1。而 `sa_generate_param_review_csv._infer_pargp` 的 `spe_keep` 包含全部三组温度参数（TB1/2/3、TO11/12/13、TO21/22/23、TM1/2/3）。`sa_postprocess_sobol.py` 的 `_sobol_wide_to_long` 不依赖静态映射，而是从 CSV 列名动态提取。

**判断**：由于 `sa_postprocess_sobol_interpret.py` 本身已是死代码（O1），此问题属于死代码内的不一致，不影响生产。但若未来有人误以为该文件可用，TO21 和 TM1 的 Sobol 指数将显示为 `UNKNOWN` 位置。

**建议**：随 O1 一并删除。

---

### M3 [次要] `sa_postprocess_sobol.py` 导入 `matplotlib` 但归类为 run-diagnostic

**位置**：`sa_postprocess_sobol.py:10-13`

**现象**：`sa_postprocess_sobol.py` 导入 `matplotlib` 并生成 PNG/SVG 热力图和条形图。`AGENTS.md` 的论文图表双轨约定允许 Python 生成 `diagnostic_*` 输出，但禁止生成 `Fig`/`FigS`。该模块的输出文件名（如 `sobol_heatmap_*`、`sobol_top*`）未使用 `diagnostic_` 前缀，但属于 SA 运行诊断而非论文图。

**判断**：该模块的功能是生成 Sobol 后处理诊断（排名、热力图、一页式汇总），不涉及论文图的 Fig/FigS 编号。虽然文件名未遵循 `diagnostic_` 前缀约定，但语义上属于诊断范畴。`test_sa_paper_figures.py` 的 `test_sa_paper_figures_are_r_only_and_domain_separated` 已验证 R 端独立渲染 SA 论文图，Python 端无违规。

**建议**：低优先级。可考虑将输出文件名统一加 `diagnostic_` 前缀以更明确区分，或在模块 docstring 标注「仅限 SA 运行诊断，不生成论文图」。

---

## 已验证一致的关键点（无问题）

1. **`sa_postprocess_sobol.py` 质量门**：`postprocess_sobol` 调用 `assess_sobol` 并 `require_pass()`，失败时拒绝生成图表。✓（规范 §4「Sobol 应在获批 Top-K 上运行，并用至少两个通过质量门的正式尺度判断收敛」）
2. **`sa_postprocess_sobol.py` 排除 Phi 行**：第 310 行 `out = out[out["obs"].astype(str).str.strip().str.lower() != "phi"]`，避免将目标函数值误作响应变量。✓
3. **`sa_generate_param_review_csv.py` 的 CUL 边界回退逻辑**：优先读取 `.base` 文件中的 `999991`/`999992` 边界行；仅在不存在时回退到 `compute_default_bounds`（第 474-480 行）。该回退链符合「优先使用模板文件中的显式边界」原则。✓
4. **`sa_generate_param_review_csv.py` 的 `Paths` dataclass**：使用 `frozen=True`，防止路径被意外修改。✓
5. **`sa_postprocess_sobol.py` 的 `_find_sobol_si_csv`/`_find_sobol_sti_csv`**：支持多种文件名变体（`sa_sen_sobol.sobol.si.csv`、`sa_sen_sobol.sobol.sti.csv`），并回退到目录扫描。✓（容错设计）
6. **`sa_postprocess_sobol.py` 的 `_sobol_wide_to_long`**：自动识别 `output`/`obs`/`observation` 列名，参数名统一转大写。✓（列名容错）

---

## 建议的后续行动（按优先级）

1. **O1（删 130 行死代码）**：删除 `sa_postprocess_sobol_interpret.py`，同步清理 `tools/setup_workspace.py:143` 和 `tools/migrate_phase2.py:97-98`。
2. **O4（删 pointless 包装器）**：删除 `_default_bounds` 函数，6 处调用改为直接 `compute_default_bounds`。
3. **O2（统一参数分组）**：将 `sa_generate_param_review_csv._infer_pargp` 的显式集合逻辑提升为 `param_registry` 中的权威实现，`build_pest._infer_pargp_for_name` 改为调用同一实现。这是低优先级重构，当前三副本均能正常工作。
4. **O3（统一土壤 ID 推断）**：提取共享的 `_infer_soil_id_from_filex` 到 `src/dssat/` 或 `src/common/`。
5. **C1 + M1**：随第 2 轮 C3 解决——同步 `DEFAULT_BOUNDS` 或在本模块标注「范围仅为 SA 初始建议」。
6. **M3**：可考虑将 `sa_postprocess_sobol.py` 输出文件名加 `diagnostic_` 前缀。

---

## 附：本轮未覆盖（下一轮候选）

- `build_pest.py`（~103KB，最大模块，需 1–2 轮；本轮仅交叉核对了 `_infer_pargp_for_name` 和 `_infer_soil_id_from_filex` 的重复实现）
- `src/sensitivity/sobol_repair.py` + `sobol_audit.py` + `sobol_bootstrap.py` + `sobol_case.py`（Sobol 工具链核心，独立一轮）
- `tools/freeze_bounds.py` + `prepare_*_bounds.py`（6 个 preparer，均调 `assert_valid_frozen_bounds`，可合并一轮）
- `run_dssat.py`（~87KB，DSSAT 执行引擎，独立一轮）