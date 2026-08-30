# W0 工作区基线状态记录（敏感性分析方案 20260729）

> 生成日期：2026-07-29
> 生成方式：只读 `git` 命令，未做任何 `reset/checkout/clean`
> 目的：满足《敏感性分析方案与图表优化_协作实施计划_20260729》§10 W0 的交付要求，并在进入 W1 前固定工作区事实。

## 1. 仓库指针

| 项 | 值 |
|---|---|
| HEAD | `24ec71c1cb41a7b9c4cc24bfe6853f499842ac26` |
| 分支 | `codex/p0-research-credibility` |
| upstream | **未配置**（`fatal: no upstream configured`） |
| 主分支 | `master` |

## 2. 工作树脏度总览

`git status --short` 共 **467** 项变更：

| 状态 | 数量 |
|---|---|
| 已修改 `M` | 82 |
| 已删除 `D` | 174 |
| 未跟踪 `??` | 211 |

按主题分类（粗判，详见 §3）：

- **率定 / 试验框架**：`configs/experiments/`（13 改）、`configs/runs/`（4 改 + 43 新）、`src/calibration/`（8 改）、`tools/calibration/`（27 新）、`configs/experiments/specs/` 多个 spec 改动（即上一轮 review 的 C1 SHA 漂移源）
- **输入资产迁移**：`data/user/`（105 删 + 13 新 + 4 改），含 XXQL2501/2502/2601 的 TMA/TMT/TMX 删除与重生成
- **管理优化**：`src/management/`（2 改 + 5 新）、`configs/management/`（2 新）
- **SA 相关**：`src/sensitivity/`（4 改）、`tools/sa/`（1 改 + 2 新）、`configs/sa/`（2 新）、`paper/R/fig_sa_sobol.R`（1 改）、SA 相关测试（2 改）
- **边界注册表（率定+SA 混合）**：`data/parameter_registry/`（37 新），含大量 `e02_*`、`e01_*`、`fwc_*`、`t9_*`、`t10_*` 边界文件
- **文档**：`docs/reports/`（50 删 + 19 删中文 + 多新）、`docs/archive/`（9 改 + 7 新）
- **工程生成物泄露**：`workspace/tmp_moisture_inspect/`、`workspace/tmp_moisture_corrected/`、`workspace/t10_sobol23_proposal_from_posterior.csv`、`workspace/t10_bounds_freeze_ready.csv`、`workspace/validation/`

## 3. SA 相关变更清单（W0 要求的"SA 变更文件清单"）

### 3.1 已修改

```
M  paper/R/fig_sa_sobol.R
M  src/sensitivity/morris_audit.py
M  src/sensitivity/morris_multiseed.py
M  src/sensitivity/sa_model.py            (+21/-1)
M  src/sensitivity/sa_postprocess_morris.py
M  src/sensitivity/sobol_repair.py
M  tests/test_morris_run_audit.py
M  tests/test_sobol_repair.py
M  tools/sa/rerun_unstable_sa.py
```

### 3.2 新增（未跟踪）

```
?? configs/sa/eggplant_fwc_v1_outputs.json
?? configs/sa/eggplant_fwc_v2_outputs.json
?? src/reporting/export_sobol_stability_paper_data.py
?? tools/sa/extract_fwc_output_ranges.py
?? tools/sa/summarize_fwc_morris.py
?? workspace/t10_sobol23_proposal_from_posterior.csv   (工程生成物，疑似误入仓库根)
```

### 3.3 删除

```
D  docs/reports/P1_v4_W3_sobol_report.md   (已移至 docs/archive/sa_run_history/)
```

## 4. 上游证据路径核查（W0 要求的 SHA-256 清单前置）

### 4.1 §3.1 引用的冻结参数文件

`eggplant_formal_multiseason_candidate_v4_20260721.csv`：

```
（待补：文件实际路径与 SHA-256，需用户确认 v4 frozen bounds 的权威位置）
```

### 4.2 §6.1 引用的 Sobol repaired 证据 —— **缺失（阻塞）**

文档 §6.1 指定本轮 Sobol 只消费：

- XXQL2502：`n0256_seed_20260729_repaired_v2_20260722`
- XXQL2601：`n0256_seed_20260729_repaired_v2_20260722`

实测：

```bash
find workspace -maxdepth 3 -type d -iname '*n0256*'        # 无结果
find workspace -maxdepth 3 -type d -iname '*repaired*'     # 无结果
```

磁盘上仅存在 `n0128_seed_*` 目录（如 `workspace/runs/p1_v4_sobol_formal/n0128_seed_20260717`），**无任何 `n0256` 或 `repaired` 证据**。

**结论：W3（Sobol 证据包收口）的上游输入目前不可得，无法按 §6.1 实施。**

### 4.3 现有 Morris/Sobol 证据目录（散落，未跟踪）

`workspace/runs/` 下存在大量 SA 产物目录（节选）：

```
formal_morris, formal_morris_repro_v1..v4, formal_morris_stability_rerun_v1
morris_results, morris_results_repro_v4, morris_results_stability_rerun_v1
p1_morris_formal_20260715, p1_morris_formal_v2_20260715, p1_morris_formal_v3_20260716
p1_v4_sobol_formal/n0128_seed_20260717
fwc_v2_formal_seed_20260729/morris_audit, fwc_v2_formal_seed_20260812/morris_audit  (注：20260812 晚于今日 20260729)
eggplant_stage2_v4_sobol20_p2, eggplant_stage2_v4_sobol20_smoke
```

**这些目录未被 git 跟踪**（`.gitignore` 排除 `workspace/runs/`），其内容归属、是否为 W2/W3 应消费的"v4 证据"需要用户确认。

## 5. 归属冲突判定（§13 第 9 条）

工作树同时包含以下**不同主题**的未提交改动，无法区分哪些属于"本轮 SA"、哪些属于"率定/管理优化"：

1. **SA 代码改动**（§3.1）：与 W1–W4 直接相关；
2. **率定试验框架改动**（`configs/experiments/`、`src/calibration/`、`tools/calibration/`）：与 SA 本轮无关，且包含上一轮 review 发现的 spec SHA 漂移（C1）；
3. **边界注册表**（`data/parameter_registry/` 37 新文件）：`e01_*`/`e02_*` 属率定，`fwc_*`/`t9_*` 可能属 SA 历史证据，混合存放；
4. **管理优化**（`src/management/`、`configs/management/`）：与 SA 无关；
5. **输入资产迁移**（`data/user/` 大规模删改）：影响 spec SHA，属率定侧；
6. **工程生成物**（`workspace/tmp_moisture_*`、根目录 CSV）：疑似误提交。

**按 §10 W0 第 4 条"新 SA 工作不得夹带率定/管理优化改动"与 §13 第 9 条，本轮 SA 实施无法在当前工作树干净启动，必须先由用户协调隔离方式。**

## 6. 待用户决策的阻塞项

1. **隔离方式**：当前 467 项脏变更无法用简单分支隔离。可选方案见 AskUserQuestion。
2. **Sobol v2 repaired 证据位置**：§6.1 引用的 `n0256_*_repaired_v2_20260722` 在磁盘上不存在，需用户提供真实路径或确认是否降级为 N=128。
3. **v4 frozen bounds 权威路径**：§3.1 的 `eggplant_formal_multiseason_candidate_v4_20260721.csv` 需定位并计算 SHA-256 入清单。
4. **`fwc_v2_formal_seed_20260812` 目录**：日期晚于今日，需确认是否命名错误。

## 7. 关键发现：工作树"SA 改动"实为 FWC（果实含水量）独立研究线

逐文件核查 SA 代码改动后，发现工作树中标记为"SA"的改动**主体不属于本轮 SA 实施计划**，而是一条独立的 **FWC（Fruit Water Content，果实含水量）研究线**：

| 工作树改动 | 实质内容 | 是否属本轮 SA（文档 §1–§9） |
|---|---|---|
| `src/sensitivity/sa_model.py` (+21/-1) | 新增 `PDMCD` 解析与 `FWC_END/FWC_PEAK/FWC_FROM_RATIO_END` 响应 | **否**——文档 §4 响应分层无 FWC |
| `configs/sa/eggplant_fwc_v1_outputs.json` (新) | FWC 输出配置 | **否** |
| `configs/sa/eggplant_fwc_v2_outputs.json` (新) | FWC 输出配置 v2 | **否** |
| `tools/sa/extract_fwc_output_ranges.py` (新) | FWC 输出范围提取 | **否** |
| `tools/sa/summarize_fwc_morris.py` (新) | FWC Morris 汇总 | **否** |
| `workspace/runs/fwc_v2_formal_seed_20260729/` (新) | FWC 正式运行 | **否** |
| `workspace/runs/fwc_v2_formal_seed_20260812/` (新) | FWC 运行（日期异常） | **否** |
| `src/sensitivity/morris_audit.py` (+63/-16) | 待核查（可能混合 FWC 与通用改动） | **待定** |
| `src/sensitivity/sobol_repair.py` (+37/-1) | 待核查 | **待定** |
| `paper/R/fig_sa_sobol.R` | 待核查 | **待定** |

**判定**：

1. 工作树的"SA 改动"主要是 FWC 研究，**不是**文档定义的"参数敏感性论文优化"。
2. FWC 属于果实品质/含水量分析，已偏离文档 §1 的中心问题（参数敏感性与率定设计）。
3. 按文档 §13 第 10 条（"论文中心问题扩展到品种或管理优化 → 必须暂停"）与 §13 第 9 条（归属冲突），**本轮 SA 实施不能直接消费这些工作树改动**。
4. 若新建分支把这些 FWC 改动作为"SA 工作"提交，将违反 §11 的 Commit 主题纯净要求，并可能破坏正在进行的 FWC 工作。

**因此本轮 SA 实施的真正起点，应是基于干净 HEAD 的全新代码，而非工作树中已存在的 FWC 改动。** 这需要用户明确授权隔离方式（见 §6 决策项）。

## 8. 已完成的只读动作

- `git rev-parse HEAD` / branch / upstream
- `git status --short` 分类统计
- `git status --short -- <pathspec>` 按 SA/率定/管理路径过滤
- `find` 定位 SA 证据目录
- `git diff src/sensitivity/sa_model.py` 等逐文件核查 SA 改动实质
- 未执行任何写操作（本文件除外）、未执行任何 `reset/checkout/clean/stash`。
