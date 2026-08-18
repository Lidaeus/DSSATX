# Code Review：近期新增代码与新增文档的一致性审查

> 日期：2026-07-27
>
> 审查范围：2026-07-24 至今提交（`bd1e43c`..`24ec71c`）涉及的新增代码与新增文档：
> - P0-B 试验规范框架（`experiment_spec.py`、`experiment_runner.py`、`run_calibration_experiment.py`）
> - P0-C 消除跨季节全局状态（`build_pest.py`、`build_pest_multiseason.py` 的 `SeasonContext` 重构）
> - P0-D 统一指标与残差诊断（`metrics.py`、`residual_diagnostics.py`、`experiment_evaluation.py`、`evaluate_calibration_experiment.py`）
> - O1/O2/O3 去重（`build_pest.py`）
> - E01→E02 边界提取桥（`extract_bounds_from_posterior.py`）
> - 配套实施记录文档（`P0-B/C/D`、`O1O2O3`、`E01_E02_边界提取桥` 共 5 份）
>
> 审查模式：只读审查，**未修改任何代码**（按用户要求，结果仅保存为本 markdown）。
>
> 审查方法：逐文件阅读新增源码 + 对照实施记录文档声称 + 实际运行测试套件验证。

---

## 0. 评审结论摘要

| 维度 | 评级 | 说明 |
|---|---|---|
| 架构设计 | **优** | SHA-256 钉扎契约、treatment-block bootstrap、数值闭合断言等设计扎实，科研可信度导向正确 |
| 代码质量 | **良** | P0-C 重构干净，O1/O2/O3 去重到位；存在一处真实逻辑 bug（C2） |
| 测试覆盖 | **中** | P0-D 核心路径覆盖好，但变量规范化边界未覆盖；spec 测试受工作树漂移影响全部失败 |
| **文档与实际一致性** | **差** | 多份实施记录声称"无回归、全部通过"，但实际测试 18 failed + 4 error；存在已落地 bug 未被测试捕获 |
| 工作树卫生 | **差** | spec 文件工作树改动（指向 v2_20260726 目录）未与实际工件 SHA 同步，破坏了 spec 框架本身要守护的可审计性 |

**最关键发现**：本次评审最重要的结论不是某个代码 bug，而是**"文档声称的测试基线与仓库实际可复现状态严重背离"**。spec 框架的全部价值在于 SHA-256 钉扎的可审计性，但当前工作树让这套守护机制自身处于失效状态（§C1）。这是一个需要在合并/正式运行前立即处理的阻塞项。

---

## 1. 严重发现（Critical / High）

### C1 [严重·阻塞] spec 工作树漂移：SHA 声明与实际工件不匹配，导致 spec 框架测试全面失败

**位置**：`configs/experiments/specs/E00_input_audit.json` 等 10 个 spec 文件（工作树未提交修改）+ `data/user/experiments/xxql*_v2_20260726/input_manifest.json`

**现象**：

实际运行 P0-B/P0-C 相关测试套件：

```
python -m pytest tests/test_experiment_spec.py tests/test_experiment_build.py -q
→ 18 failed, 55 passed, 4 errors
```

失败均源于同一根因——SHA-256 校验：

```
src.calibration.experiment_spec.ExperimentSpecError:
season_inputs[0] (25SP) input_manifest SHA-256 mismatch:
declared 5c44a3e75bd8ad4c04f58e558b714d7c7b5730f4bdb67ab8f635f85757a82641
   != actual c5dfcb7862e82a9c133736d9698fcc11921b50dabbda0fb5c532f7cdad53f2b7
```

实际工件 SHA（重新计算）：
| spec 声明路径 | 声明 SHA | 实际 SHA |
|---|---|---|
| `xxql2501_actual_trial_calibration_v2_20260726/input_manifest.json` | `5c44a3e7...` | `c5dfcb78...` |
| `xxql2502_actual_trial_calibration_v2_20260726/input_manifest.json` | `edaf9344...` | `44017c64...` |
| `xxql2601_actual_trial_calibration_v2_20260726/input_manifest.json` | `05611d3d...` | `58f7d687...` |

**根因**（`git diff configs/experiments/specs/E00_input_audit.json`）：

spec 文件在工作树中被改了 `input_manifest` 路径（`xxql2501_20260716` → `xxql2501_actual_trial_calibration_v2_20260726`）和对应 SHA，但**新声明的 SHA 与新指向目录下实际工件的 SHA 仍然不一致**。即：路径改了，SHA 没改对（或工件在路径修改后又被重新生成过）。

更糟的是，`git status` 显示 `data/user/experiments/XXQL2501/XXQL2501.TMA`、`XXQL2501.TMT` 等被删除（`D`），而 `XXQL2501.TMX` 被修改（`M`）——输入资产本身处于半迁移状态。

**影响**：

1. **spec 框架自身的守护机制失效**：`experiment_spec.py` 设计的全部价值就是"SHA 不匹配在 build 前失败"（P0-B 验收门第 1 条）。现在这套机制正确地**检测到了**漂移，但漂移本身没有被修复，导致 18 个测试（包括 `test_e00_input_audit_loads`、`test_e04_joint55_loads`、`test_e06_pool3season_loads` 等"happy path"测试）全部失败。

2. **实施记录的"无回归"声称无法复现**：
   - `P0-B_参数集与试验声明_实施记录` §4 称"37 passed"
   - `P0-C_消除跨季节全局状态_实施记录` §5 称"86 passed, 2 skipped"
   - `E01_E02_边界提取桥_实施记录` §5 称"50 passed，无回归"

   这些数字在 `bd1e43c` 提交时可能是真的，但当前工作树已无法复现。实施记录没有注明"测试基线对应 commit X"，也没有在文档中标记后续的输入资产迁移。

3. **阻塞 E01 正式运行**：`run_calibration_experiment.py` 调用 `ExperimentSpec.load()`，会立即因 SHA 不匹配而 `ExperimentSpecError` 退出。P0-B/C 实施记录声称"--execute 已解锁"，但用当前工作树根本无法启动。

**建议**（不在此 review 中执行）：

- 立即在 `docs/reports/` 新增一份"输入资产 v2 迁移记录"，说明 v2_20260726 目录的生成方式、各 manifest 的正确 SHA，并把 10 个 spec 文件的 SHA 重新冻结。
- 或：如果 v2 迁移尚未定稿，应 `git checkout configs/experiments/specs/` 回退到 `bd1e43c` 的状态，让 spec 与已删除的 `xxql2501_20260716` 等旧目录重新对齐（但旧目录已被 `git rm`，故此路径不可行——必须前进而非后退）。
- 在每份实施记录 §"测试结果"小节补注 commit hash 与测试运行日期，避免"通过"声明随工作树漂移而失效。
- 考虑增加一个 `tools/verify_spec_hashes.py`（或在 CI 里跑 `pytest tests/test_experiment_spec.py`），让 SHA 漂移在提交时就被拦截，而不是等到 review。

---

### C2 [高·真实逻辑 bug] `_normalise_variable` 把规范别名 `DRY_CUM` 错误规范化为 `DRY_CU`

**位置**：`src/reporting/experiment_evaluation.py:50-65`

**现象**：

```python
def _normalise_variable(name: Any) -> str:
    s = str(name).strip().upper()
    for suffix in ("M", "S"):
        if s.endswith(suffix) and len(s) > 4:
            s = s[:-1]
    aliases = {
        "DRY_CUM": "CHPDT",
        "DRY_CUMM": "CHPDT",
        "FRESH_CUM": "CHFPW",
        ...
    }
    return aliases.get(s, s)
```

实测（本次 review 运行）：

```
DRY_CUM   -> DRY_CU    (错误！AGENTS.md 规定 DRY_CUM 是 CHPDT 的规范别名)
DRY_CUMM  -> CHPDT     (正确，因为先剥离 M 得 DRY_CUM 再查别名)
FRESH_CUM -> FRESH_CU  (错误！应为 CHFPW)
CHPDT     -> CHPDT     (正确)
CHPDTM    -> CHPDT     (正确)
```

**根因**：

"剥离末尾 M/S"逻辑在**别名表查询之前**执行。其设计意图是去掉 PEST 的 measured/simulated 后缀（`PWADM`→`PWAD`），但当变量名本身就是裸名 `DRY_CUM`（无 M/S 后缀）时，`DRY_CUM` 以 `M` 结尾且 `len("DRY_CUM")=7 > 4`，于是末尾的 `M`（`CUM` 的 M）被错误剥离成 `DRY_CU`，随后别名表查不到 `DRY_CU`，返回 `DRY_CU`。

这与 AGENTS.md 的"comparison.csv variable 列允许 `DRY_CUM`/`FRESH_CUM` 作为 CHPDT/CHFPW 别名"契约直接冲突。

**影响**：

1. 若 comparison 表的 `variable` 列直接使用裸名 `DRY_CUM`/`FRESH_CUM`（AGENTS.md 明确允许的写法），这些行会被归到错误的 `_variable_root`（`DRY_CU`/`FRESH_CU`），导致：
   - 指标分组错乱（CHPDT 的观测被拆成两个 group）
   - 不会被 `ARTICLE_FORBIDDEN_VARIABLES` / `ARTICLE_DIAGNOSTIC_ONLY_VARIABLES` 正确识别
   - 残差诊断的 `season × treatment × variable_root` 分组失效

2. **测试盲区**：`tests/test_experiment_evaluation.py` 的 7 个测试全部使用 `CHPDT`/`CHFPW` 裸名或带 `M` 后缀的输入，**没有任何测试用 `DRY_CUM`/`FRESH_CUM` 裸名作为 variable**，故此 bug 未被捕获。P0-D 实施记录 §3 验收门称"article profile 拒绝 HWAM/PWAD/PWAI"，但未验证别名归一化的正确性。

**佐证**：`build_residual_trajectory`（`residual_diagnostics.py:166`）依赖 `variable_col` 内容匹配 `cumulative_variable_mark="cum"` 来判定累计非独立性。`DRY_CUM` 含 `cum` 仍能正确触发标记，但 `DRY_CU`（被错误规范化后的值）**不含** `cum`——不过 `build_residual_trajectory` 接收的是原始 df 而非规范化后的 df，所以这里侥幸不受影响。这进一步说明规范化逻辑的耦合很脆弱。

**建议**：

将"剥离 M/S 后缀"限制为 PEST 风格的 measured/simulated 后缀（即仅当剥离后仍能在已知变量集合中匹配时才剥离），或调整顺序：先查完整别名，未命中再尝试剥离后缀。例如：

```python
# 伪代码示意（不在本 review 中实施）
ALIASES = {"DRY_CUM": "CHPDT", "DRY_CUMM": "CHPDT", "FRESH_CUM": "CHFPW", ...}
def _normalise_variable(name):
    s = str(name).strip().upper()
    if s in ALIASES:
        return ALIASES[s]
    # 仅对未命中别名的名字尝试剥离 PEST M/S 后缀
    for suffix in ("M", "S"):
        if s.endswith(suffix) and len(s) > 4:
            stripped = s[:-1]
            if stripped in ALIASES or stripped in ARTICLE_ALLOWED_VARIABLES:
                return ALIASES.get(stripped, stripped)
    return s
```

并补一个测试：`_normalise_variable("DRY_CUM") == "CHPDT"`、`_normalise_variable("FRESH_CUM") == "CHFPW"`。

---

## 2. 中等发现（Medium）

### M1 [中·异常吞咽] `evaluate_experiment` 静默吞掉残差轨迹生成异常

**位置**：`src/reporting/experiment_evaluation.py:189-195`

**现象**：

```python
# residual trajectory (auxiliary)
if order_col:
    try:
        traj = build_residual_trajectory(df, runs_keys)
        traj.to_csv(out / "residual_trajectory.csv", index=False)
    except Exception:
        pass  # trajectory is auxiliary, not a hard gate
```

注释说"trajectory is auxiliary"，但裸 `except Exception: pass` 会吞掉所有异常，包括：
- `build_residual_trajectory` 的编程 bug（如 KeyError、列名假设错误）
- 磁盘写入失败
- pandas 序列化错误

**影响**：残差轨迹是 §4.2 证据链的一部分（标注累计非独立性）。如果它静默失败，下游分析会得到一份"看起来完整但缺少轨迹"的结果目录，且没有任何告警。对于一个以"科研可信度"为最高目标的项目，静默丢失证据是反模式。

**建议**：至少 `except Exception as exc: print(f"[warn] residual trajectory skipped: {exc}", file=sys.stderr)`，或写入一个 `residual_trajectory.SKIPPED` 标记文件说明跳过原因。若坚持"不硬失败"，也应记录原因而非静默。

---

### M2 [中·静默回退] `_enforce_temperature_ordering` 退化时回退到 base bounds 可能掩盖后验问题

**位置**：`src/calibration/extract_bounds_from_posterior.py:259-262, 281-284, 299-307`

**现象**：

温度组排序强制的三遍扫描中，当调整后产生退化区间（`lower >= upper`）时，调用 `_restore_from_base(row, base_by_name)` 把 active 成员的 init/lower/upper 整体回退到 base bounds 模板的值。init 反转时也直接回退。

**影响**：

1. **掩盖后验病理信号**：如果 IES 后验在某个温度参数上集中撞边界（这正是 `6c0e10e` 提交记录的"P2-E1 staged calibration S1-S3 all failed — systematic bound-hitting"现象），extract 工具会静默地把该参数的边界换回 base 值，proposal 仍然"通过" `assert_valid_frozen_bounds`，但实际的率定问题被藏起来了。

2. **回退后的 init 与后验脱节**：回退到 base init 意味着 E02 率定的起点不再是 E01 后验的中位数，丧失了"从 E01 后验热启动 E02"的统计意义。这对论文"E01→E02 边界提取桥"叙事是有损害的。

3. 实施记录（`E01_E02_边界提取桥_实施记录` §6）已承认"退化后验回退"为已知限制，但仅针对"零方差后验"，未覆盖"温度组排序冲突回退"这一更常见情形。

**建议**：

- 回退发生时，在 proposal CSV 旁输出一份 `temperature_overrides.csv`，列出每个被回退的参数、原后验分位数、回退原因，供人工 review。
- 或在 CLI `main()` 的 `Validation: PASS` 输出后追加一行 `Temperature overrides: N (see ...)` 计数。
- 现有的 `logger.warning` 只输出到日志，CLI 标准输出不体现，用户难以察觉。

---

### M3 [中·潜在 KeyError] `_season_for_obsnme` 对无法解析的观测名直接抛异常

**位置**：`src/calibration/build_pest_multiseason.py:418-429`

**现象**：

```python
def _season_for_obsnme(obsnme, run_seasons):
    match = re.search(r"_R(\d+)(?:_|$)", str(obsnme), flags=re.IGNORECASE)
    if match is None:
        raise ValueError(f"cannot assign observation to a season: {obsnme!r}")
    season = run_seasons.get(int(match.group(1)))
    if season is None:
        raise ValueError(f"observation run is absent from run mapping: {obsnme!r}")
    return season
```

该函数在 `_apply_t8_weights` 和 `_write_group_weight_audit` 的循环中被调用。如果 PST 里存在任何不符合 `*_R<digits>(_...|$)` 命名的非零权重观测（例如用户手动添加的诊断观测、或 `critical_obs` 中不带 `_R` 后缀的项），整个权重重写会因单个观测而失败。

**影响**：T8/T10 权重公式应用是 build 流程的最后一步，失败会导致 PST 权重处于半更新状态（`_build_ins_and_obs` 已写入，但 `_apply_t8_weights` 中途崩溃）。虽然 `pst.write` 在最后才落盘，但 `weights_path`（`*_observation_weights.csv`）的 audit 列可能在异常前已被读取。

**建议**：对无法解析的观测名，应记录警告并跳过（该观测保持 `create_ins_and_pst_multi` 给的原始权重），而非整体失败。或在文档中明确声明"所有进入 T8 权重的观测必须符合 `_R<global_run>` 命名契约"并加 build 时前置校验。

---

## 3. 次要发现与建议（Low / Nit）

### S1 [低·NaN 检查风格] `obs_abs == obs_abs` 老式 NaN 判断

**位置**：`src/reporting/residual_diagnostics.py:160`

```python
tail = float(np.mean(np.abs(dist) >= obs_abs)) if obs_abs == obs_abs else np.nan
```

`x == x` 是利用 `NaN != NaN` 的老式 NaN 判断。Python 3.13 + numpy 环境下建议 `np.isfinite(obs_abs)` 或 `math.isnan(obs_abs)`，更清晰且不被 linter 标红。此外该行优先级有歧义：`np.mean(np.abs(dist) >= obs_abs)` 中 `>=` 产生 bool 数组再 `np.mean`，逻辑正确但建议加括号 `np.mean(np.abs(dist) >= obs_abs)` → 实际无歧义，可保留。

### S2 [低·硬编码] `experiment_runner.py` 的 build 命令硬编码大量参数

**位置**：`src/calibration/experiment_runner.py:204-223`（`run_build` 的 `cmd` 列表）

命令里硬编码了 `--bad-phi-sigma 1e300`、`--include-n-uptake`、`--param-review-mode off` 等。这些值本应来自 spec 或一个命名的"profile"，而非散落在 adapter 里。注释说"mirrors the proven T10 dry-only runner contract"，但如果将来 E05（秋季偏移）需要不同的 `--include-n-uptake` 行为，这里会成为隐性耦合点。

**建议**：把这套硬编码提升为模块级常量（类似已有的 `IES_STABILITY_PROFILE`），命名为 `BUILD_CONTRACT_PROFILE`，并在 receipt 里记录其哈希/版本。

### S3 [Nit·文档措辞] P0-D 实施记录的"未解决风险"低估了 runs test 的统计限制

**位置**：`docs/reports/P0-D_统一指标与残差_实施记录_20260724.md` §5.2

文档称"n<8 已 `not_tested` 规避最危险区间；n≥8 的正态近似是 NIST e-Handbook 推荐做法"。实际上 Wald-Wolfowitz 游程检验在 n∈[8,15] 区间，正态近似的 II 类错误率仍然偏高，NIST 手册同时提供精确分布表。文档"可接受"的定性没问题，但建议补一句"若论文正式分析出现 n∈[8,15] 的关键结论，应补查精确分布表"，与项目"科研可信度优先"的基调一致。

---

## 4. 正向评价（值得保持的设计）

### P1 [优] P0-D 三模块的科研严谨性

`metrics.py` / `residual_diagnostics.py` / `experiment_evaluation.py` 在以下几个点体现了明显高于平均水平的工程-科研素养：

1. **OLS MSE 分解的数值闭合断言**（`metrics.py:177-182`）：用 `raise AssertionError`（而非会被 `-O` 优化的 `assert`）强制 `MSE = MSE_s + MSE_u` 在 1e-9 容差内成立。这是对"系统性误差占比"这一论文关键指标的数学正确性兜底。

2. **treatment-block bootstrap**（`residual_diagnostics.py:101-163`）：明确以"处理"为重抽样单位，禁止对累计采收的每个时间点做独立 t 检验——这正确处理了"同一处理的累计采收观测不独立"这一农业试验统计的经典陷阱。小样本（<8 处理）还额外给符号置换检验，体现了对样本量的敬畏。

3. **累计非独立性标签**（`residual_diagnostics.py:166-216`）：通过变量名含 `cum` 识别累计序列并打标，避免下游误用独立检验。虽然 C2 暴露了变量名归一化的脆弱性，但这个"标记"思路本身是对的。

4. **import 门测试**（`tests/test_metrics_import_gate.py`）：强制四个模块不导入 matplotlib/seaborn/pyplot，与 AGENTS.md"export_paper_data 不得导入绘图库"契约形成双重保险。

这些设计让 P0-D 模块在"为论文提供可审计、可复现的评价基础设施"这一目标上基本达标。

### P2 [优] P0-C 的 SeasonContext 重构彻底且向后兼容

`build_pest_multiseason.py` 从"13 符号 ctx 字典注入 + `USER_INPUT_DIR` 模块全局变异"重构为"直接 import + `SeasonContext` 数据类 + `input_dir` 显式传参"，几个细节做得好：

- **向后兼容**：`_resolve_filex_path(filex, input_dir=None)` 在 `input_dir=None` 时回退到全局 `USER_INPUT_DIR`，单季节 `__main__` 路径零改动（P0-C 实施记录 §6.1 明确记录此设计选择）。
- **循环导入处理**：`build_pest.py` 顶层移除 `from build_pest_multiseason import build_multiseason_stage2`，改为 multiseason 分支内 lazy import，避免了"`multiseason` 现在 import 自 `build_pest`"引入的循环。这是正确的解法。
- **可重入性**：消除全局变异后，`build_multiseason_stage2` 在原理上可被并发调用（虽然实际仍串行），为未来并行 build 留了空间。

### P3 [优] O1/O2/O3 去重数学等价性有验证

`O1O2O3_去重_实施记录` §5 明确论证了去重的数学等价性：

- O2：`(sigma0² + (cv·|med|)²)^0.5 · factor` 与原代码"先开方再乘 factor"由乘法交换律等价——论证正确。
- O3：`sigma_factors=None` 时因子为 1.0，行为不变——论证正确。
- 净减 126 行与预估一致，且 `create_ins_and_pst` 委托的 `_build_ins_and_obs` / `_populate_pst_from_par_obs` 此前已被 `create_ins_and_pst_multi` 使用并测试，去重后行为等价性有交叉验证。

这种"去重前预估行数、去重后核对、并论证数学等价"的纪律，比单纯追求行数减少更可信。

### P4 [优] extract_bounds_from_posterior 的"proposal 不写入 frozen"边界清晰

`extract_bounds_from_posterior.py` 严格遵守"proposal ≠ frozen"的审批桥契约：

- `extract_bounds_proposal()` 默认输出到 base 同级 `.proposal.csv`，从不写 `bounds_frozen/`。
- CLI `main()` 写入后立即调用 `assert_valid_frozen_bounds(out)` 做早期可冻结性反馈（`ad887b5` 提交修复），PASS/FAIL 退出码清晰。
- `_enforce_temperature_ordering` 虽有 M2 的回退问题，但其存在本身（在 extract 阶段就强制物理硬约束）是正确的——避免把不可冻结的 proposal 推到 `freeze_bounds.py` 才崩溃。

---

## 5. 测试基线复核：文档声称 vs 实际可复现

本次 review 实际运行的测试结果，与各实施记录文档声称的对比：

| 实施记录 | 文档声称 | 本次实际运行 | 差异原因 |
|---|---|---|---|
| P0-D `metrics/residual/experiment_evaluation/import_gate` | 69 passed（含 41 回归） | **28 passed**（仅 P0-D 四文件） | 28/28 全过，P0-D 核心无回归 ✅；差异是文档含相邻回归文件，本次未全跑 |
| P0-B `test_experiment_spec.py` | 33 passed | **18 failed, 12 passed** | C1 工作树 SHA 漂移 ❌ |
| P0-C `test_experiment_build.py` | 5 passed | **1 failed, 4 errors** | C1 同根因 ❌ |
| E01→E02 `test_extract_freeze_pipeline.py` | 11 passed | （未单独跑，依赖真实 sobol23/T9 工件） | 需 E01 真实后验才能完整验证 |

**关键结论**：

- **P0-D 的 28 个核心测试在隔离运行下全部通过**——C2 的变量规范化 bug 不在测试覆盖范围内，所以测试"全过"与 bug 存在不矛盾。这正说明测试覆盖有盲区（§C2 已建议补充）。
- **P0-B/P0-C 的测试失败全部源于 C1 的工作树漂移**，与代码逻辑无关。但这恰恰暴露了 spec 框架的脆弱性：它的正确性完全依赖工作树 SHA 与工件同步，而当前没有 CI 或提交前钩子来守护这一点。
- **各实施记录的"无回归"声明在撰写时（`bd1e43c` 提交，2026-07-24）很可能为真**，但由于未在文档中钉死测试基线的 commit hash，这些声明随工作树演进已不可复现。

---

## 6. 针对新增文档的具体评价

### 6.1 实施记录文档质量（总体良好）

5 份实施记录（P0-B/C/D、O1O2O3、E01_E02 桥）结构统一：问题 → 方案 → 交付清单 → 验收门核对表 → 测试结果 → 已知限制。这种"验收门核对表"写法值得保持——它强制每个工作包对照原始设计文档逐条勾选，降低验收遗漏。

### 6.2 文档需改进的点

| 文档 | 问题 | 建议 |
|---|---|---|
| 全部 5 份 | §测试结果小节未标注 commit hash 与运行日期 | 补注"基线对应 commit `bd1e43c`，2026-07-24 运行" |
| P0-B/C/D | §7 进度表反映各自完成时快照，互相不一致（P0-B 称 P0-A/C 待做，实际已完成） | 已有 `P0_总进度.md`（P0-C §6 提及）作为权威，但应在各包 §7 加"以 P0_总进度.md 为准"指引 |
| E01_E02 桥 §6 | "STAGE_INIT_ORDER 不在 extract 强制范围"措辞像设计缺陷的辩护 | 改为"温度组是物理硬约束（DSSAT 数值稳定性），阶段排序依赖栽培学判断故留给人工 review"，并指出 CLI 写入后验证会捕获 |
| P0-D §5.2 | runs test 正态近似的统计限制定调偏低 | 见 §S3 |

### 6.3 `CodeReview_P0二次审查_20260724.md` 已发现的 C1/C2 文档不一致

该文档（2026-07-24）已识别出"实施记录间进度表不一致""E01 实施记录 P0 状态声明错误"等问题。本次 review 确认这些问题中的一部分（进度表不一致）依然存在，且新增了更严重的 C1（工作树 SHA 漂移）。建议本次 review 与该二次审查合并视图阅读。

---

## 7. 优先级建议与下一步

按"阻塞正式运行 / 影响科研正确性 / 影响可维护性"排序：

| 优先级 | 项 | 行动 | 责任 |
|---|---|---|---|
| **P0（阻塞）** | C1 工作树 SHA 漂移 | 重新冻结 10 个 spec 的 SHA，或回退 spec 文件；补"v2 输入资产迁移记录" | 必须在 E01 正式运行前完成 |
| **P1（高）** | C2 `_normalise_variable` bug | 修复剥离 M/S 逻辑顺序，补 `DRY_CUM`/`FRESH_CUM` 裸名测试 | 影响论文指标分组正确性 |
| **P2（中）** | M2 温度组回退静默 | 输出 `temperature_overrides.csv` 供人工 review | 影响后验病理的可发现性 |
| **P2（中）** | M1 异常吞咽 | 残差轨迹失败时打 stderr 警告 | 影响证据链完整性 |
| **P3（低）** | M3/S1/S2/S3 | 按章节建议处理 | 可维护性改进 |
| **持续** | 测试基线钉死 | 每份实施记录补 commit hash；考虑加 spec SHA 守护 CI | 流程改进 |

---

## 8. 审查方法与局限

- **覆盖范围**：本次 review 聚焦 2026-07-24 起的 5 个工作包的新增/改动文件。未深入审查 `multiseason_design.py`、`seasonal_parameters.py`、`observation_policy.py` 的既有实现（仅审查其被 P0-C 调用的接口契约）。
- **未运行**：未实际执行 `run_build`/`run_execute` 的端到端 smoke（受 C1 阻塞，`ExperimentSpec.load` 会失败）；未跑 R 图表管道；未验证 PEST++ 实际执行。
- **DSSAT 领域正确性**：本 review 侧重代码与文档一致性、统计学正确性、工程模式；DSSAT 作物模型参数的农学合理性（如 `TB < TO1 < TO2 < TM` 的温度基数排序是否符合茄子生物学）不在审查范围。
- **代码未修改**：按用户要求，本 review 仅产出本 markdown，所有"建议"小节的代码片段为示意，未写入任何源文件。

---

> 本 review 由只读审查产生，所有结论可在仓库当前工作树状态下复现。核心数据（测试失败、SHA 不匹配、变量规范化输出）均附具体命令与文件:行号引用。

---

## 9. 复核与修正记录（2026-07-27）

本节覆盖本次复核后实际采取的修正，前文“未修改代码”的表述仅代表原始审查时点，不再代表当前工作树。

### 9.1 C1：真实有效，已修正

C1 的 SHA 漂移确实存在。已将 7 个受影响的输入 spec/设计中的 manifest SHA 更新为当前 v2 bundle 的实际 SHA，并同步测试夹具路径。`tests/test_experiment_spec.py` 现已 33/33 通过，`tests/test_experiment_build.py` 现已 5/5 通过。该问题属于“代码守护逻辑正确、文档/配置工件落后”，不是放宽 SHA 校验的理由。

### 9.2 C2：真实逻辑 bug，已修正

`DRY_CUM` 和 `FRESH_CUM` 现在先按完整别名匹配，再处理 PEST 的末尾 M/S；新增裸别名回归测试。`tests/test_experiment_evaluation.py` 与 `tests/test_run_multiseason.py` 合计 17 项通过。该问题属于代码落后于变量命名契约。

### 9.3 M1：真实问题，已修正

残差轨迹生成异常不再静默吞掉；现在会输出 warning，并写入 `residual_trajectory.SKIPPED`，同时保持该辅助产物不成为硬门禁。该问题属于代码落后于科研证据链文档要求。

### 9.4 M2：真实风险，暂不自动改变科学语义

温度排序冲突时回退到 base bounds 的行为确实存在，可能掩盖后验贴边。但它涉及 E01→E02 的边界升级语义，不应在没有项目负责人选择前擅自改为“强制使用后验”。当前仍要求人工审查日志后决定是否升级；正式 E02 前应增加 `temperature_overrides.csv` 审计产物。请项目负责人确认：温度组冲突时是否允许保留可行的后验收缩区间，还是继续采用 base 回退。

### 9.5 M3：设计约束而非当前 bug

`_season_for_obsnme` 对缺少 `_R<global_run>` 的观测名快速失败，符合当前多季节权重审计要求。跳过并保留原始权重会降低可审计性，因此不采纳原建议；应在设计文档中明确观测命名契约，并保留 fail-fast 行为。

### 9.6 S1/S2/S3：低优先级文档/风格问题

这些问题不影响当前 E01 运行正确性：S1 可在后续清理，S2 的 build 参数目前是有意固定的稳定性 profile，S3 应在论文统计方法中补充 n=8–15 的精确游程检验说明。它们不阻塞下一阶段。

### 9.7 后续多 agent 运行约定

重试机制已验证后，后续预率定和正式率定恢复多 agent 模式：默认 4 个 agent，资源稳定时可提升至 8 个；必须保留 `--dssat-max-retries 3`，并检查每个子试验的 retry policy、失败分类和工程门禁。单 agent 仅用于 DSSAT 原生崩溃的复现诊断，不再作为常规率定模式。
