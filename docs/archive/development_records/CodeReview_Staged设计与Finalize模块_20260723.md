# Code Review：Staged 设计与 Finalize 模块（第 9 轮）

> 日期：2026-07-23
>
> 范围：`src/calibration/build_pest_multiseason.py`（589 行）、`design_config.py`（392 行）、`finalize_calibration.py`（332 行）、`stage_representative.py`（67 行）、`multiseason_design.py`（252 行）
>
> 对照规范：`AGENTS.md`、`docs/项目状态与科研启动清单.md`、`docs/论文讨论写作参考_率定范式季节适应性与异参同效.md`
>
> 关联前轮：第 6 轮 O5（ctx 字典注入）、C1/C2（NameError bug）
>
> 测试：`test_p2_n1_n3.py`（30+ 测试）、`test_staged_inheritance_smoke.py`、`test_stage_representative*.py`、`test_finalize_*.py` — 全部通过

## 审查结论

五个模块整体设计严谨，**staged 设计的参数释放/观测管理、`--fixed-from` 三方哈希溯源、stage representative 中位数规则、artifact manifest SHA-256 验证**均与规范一致。最严重的问题是前轮已发现的 C1/C2 NameError（确认在 build_pest.py 中）和**新发现的 M1 科学期接线断裂**——`_science_ok` 被计算后从未用于设置 `science_status`，未来翻转 `SCIENCE_PROMOTION_ENABLED` 时门控不会生效。

---

## 发现清单

### C1/C2 [严重·bug] `eggplant_harvest`/`eggplant_process` 模式 NameError

**位置**：`build_pest.py:3325/3331`、`build_pest.py:3568/3573`

详见第 6 轮 C1/C2。本轮交叉核对确认：这两个模式完全不可用，且无任何测试覆盖。staged 设计路径（`eggplant_stage2`）不受影响。

---

### C3 [低·冲突] `design_config.py` 硬编码 S3 观测集包含 `PWAI`，与讨论文档冲突

**位置**：`design_config.py:139-140`

**现象**：硬编码回退映射中 `"S3": {"PestHarvest.OUT": ["PWAI"]}`。讨论文档第 5.1 节明确："HWAM、PWAD、PWAI 不进入正式 Phi"，T10 改用 `CHFPW/CHPDT`。

**缓解**：当前所有 design JSON 均显式声明 `observation_outputs`，覆盖此回退。但若未来某个 design JSON 删除了 `observation_outputs`，会静默引入文档禁止的 PWAI。

**建议**：将回退默认改为抛 `ValueError`，强制显式声明。

---

### M1 [中·潜在 bug] `finalize_calibration.py` 科学期门控接线断裂

**位置**：`finalize_calibration.py:256-260, 268`

**现象**：

```python
_science_ok, science_failures = _science_evidence(run_dir)   # line 256
science_status = "science_pending"                            # line 260 ← 硬编码
...
"scientific_status": "validated" if science_status == "science_validated" else "not_assessed",  # line 268
```

`_science_ok` 被计算但**从未用于设置 `science_status`**。即使 `SCIENCE_PROMOTION_ENABLED=True`、`approval_scope=science_use`、四个证据布尔全为 True，`science_status` 仍为 `"science_pending"`，`scientific_status` 仍为 `"not_assessed"`。

**当前安全**：`SCIENCE_PROMOTION_ENABLED = False`（硬关），不可触发。但未来翻转开关时，门控不会实际生效——这是给未来维护者的陷阱。

**测试缺口**：`test_tooling_development_finalize_can_never_promote` 和 `test_science_evidence_booleans_cannot_promote_automatically` 均在 `SCIENCE_PROMOTION_ENABLED=False` 下断言 `science_pending`，**没有**测试覆盖"开关打开 + 四证据全 True → 应晋升"的路径。

**建议**：补全接线 `science_status = "science_validated" if _science_ok else "science_pending"`，并增加 monkeypatch 测试。

---

### O1 [低] `_PARENT_NAMESPACE` 死代码

**位置**：`build_pest_multiseason.py:32`

`_PARENT_NAMESPACE: dict = {}` 定义后全项目无任何引用。可删 ~3 行。

---

### O2 [中] `build_multiseason_stage2` 三个死参数

**位置**：`build_pest_multiseason.py:73`（签名）、`build_pest.py:3837`（调用点）

签名 `(args, prefix, allowed, extra_allowed, params, model_cmd_extra, ctx)` 中：
- `allowed` —— 函数体内零引用
- `extra_allowed` —— 函数体内零引用
- `model_cmd_extra` —— 第 303 行被直接覆盖，传入值被丢弃

调用方为保持与单季路径的签名兼容而传入，但多季路径完全忽略它们。可删 ~6 行。

---

### O3 [低] `multiseason_design.py` 多个声明性字段从未被 src/ 逻辑读取

**位置**：`multiseason_design.py:60-61, 89-96`

`cultivar_identity`、`shared_parameter_scope`、`season_by_code()`、`validation_seasons` 属性在 src/ 中零调用（仅测试用）。保留无害但属过度设计。

---

### O4 [低] `_sha256` 函数重复定义

**位置**：`finalize_calibration.py:29-38` 与 `stage_representative.py:13-18`

两处几乎相同的 SHA-256 实现。可合并到 `src/common/`，删 ~6 行。

---

### O5 [低] 函数内晚期 import

**位置**：`build_pest_multiseason.py:145, 411, 424, 488, 515, 537`

模块顶部已 `import csv, os`，但 `re`、`math`、`sys` 在函数内反复 import。

---

### O6 [低] `design_config.py` 硬编码观测映射是死代码

**位置**：`design_config.py:131-147`

在所有现有 design JSON（均提供 `observation_outputs`）中被完全覆盖。与 C3 合并处理，可删 ~17 行。

---

### O7 [低] `_family_for_group` 含未使用条目

**位置**：`build_pest_multiseason.py:384-388`

`"CWAMS"`、`"LAIXS"`、`"PWADM"/"PWAIM"` 在 T10 多季路径中不会出现。`HIAMM` 映射到 `BIOMASS` 在科学上存疑（HIAM 是无量纲收获指数）。

---

### M2 [低] `_write_obs_registry` 正则与 `_season_for_obsnme` 不一致

**位置**：`build_pest_multiseason.py:516` vs `413`

- `_season_for_obsnme`：`r"_R(\d+)(?:_|$)"` + `re.IGNORECASE` —— 正确匹配字面量 `_R`
- `_write_obs_registry`：`r"[_Rr](\d+)(?:_|$)"` —— `[_Rr]` 是字符类，匹配 `_`/`R`/`r` 中任意单个字符

当前观测名都遵循 `_R<n>` 约定故不触发，但正则不一致是维护陷阱。

---

### M3 [低] 多季路径静默忽略多个 CLI 权重标志

**位置**：`build_pest_multiseason.py:304-312`

单季路径传递 `apply_normalization`/`apply_log_transform`/`apply_pwtadj1`/`cv_based_sigma`/`noptmax0_sims`，多季路径完全不传。用户若在多季模式加这些标志会被静默忽略。设计上是有意省略（T10 不用 pwtadj1/log_transform），但应校验并拒绝。

---

### M4 [中] 全局变异 `__main__.USER_INPUT_DIR` 脆弱（前轮 O5 确认）

**位置**：`build_pest_multiseason.py:145-151`

每季循环中变异 `__main__` 和 `src.calibration.build_pest` 两个命名空间的全局变量。循环结束后两者指向**最后一季的 bundle**。当前靠 `SystemExit(0)` 兜底，库式调用会泄漏。

---

## 已验证一致的关键点

| 检查项 | 结论 |
|---|---|
| S1→S2→S3→S4 参数释放/固定与 design JSON 一致 | ✓ `apply_parameter_stage` 严格按 `active_params`/`fixed_params` 过滤；30+ 测试覆盖 |
| `--fixed-from` 上游溯源与三方哈希契约 | ✓ manifest run_id ↔ finalize case、相邻阶段、approval_scope、三方哈希一致 |
| `stage_representative` 选择规则 = 末轮集合中位数 | ✓ `values.median()`，`rule="median_of_final_parameter_ensemble"` |
| engineering → science 门控严格不可绕过 | ✓ 当前 `SCIENCE_PROMOTION_ENABLED=False` 硬关（但 M1 接线断裂） |
| artifact manifest SHA-256 验证 | ✓ `verify_calibration_artifact_manifest` 重新解析路径、重算 SHA-256、检查 required_roles |
| 多季季节隔离 | ✓ 每季独立 bundle、`local_to_global` 重映射 RUN、观测带 `season` 标签 |
| T10 直接采收契约 CHFPW/CHPDT | ✓ 读取 `chfpw`/`chpdt`，不差分 |
| `diagnostic_single_season` 诊断单季 opt-in | ✓ 强制要求恰好 1 个 calibration 季节 |
| 观测角色互斥（cal/validation/diagnostic） | ✓ 拒绝重复 treatment ID |
| S4 拒绝"按 validation 选参" | ✓ `_reject_validation_selection` 扫描禁用短语 |
| prior_only profile 放宽更新检查但不放宽变异检查 | ✓ `PRIOR_ONLY_IES_CHECKS = FORMAL_IES_CHECKS - {ies_parameter_update, ies_iteration_progress}` |

---

## 建议的后续行动（按优先级）

| 优先级 | 行动 | 对应问题 |
|---|---|---|
| **P0** | 修复 C1/C2 NameError（`events_by_tn.get(tn, [])` / `points_by_tn.get(tn, [])`） | C1, C2 |
| **P0** | 修复 M1 科学期接线：`science_status = "science_validated" if _science_ok else "science_pending"`，补测试 | M1 |
| **P1** | `USER_INPUT_DIR` 改为参数传入或上下文管理器 | M4 |
| **P1** | C3/O6：硬编码 PWAI 回退改为抛 `ValueError`，强制显式声明 | C3, O6 |
| **P1** | M3：多季入口校验 CLI 权重标志为关闭 | M3 |
| **P2** | O1/O2/O4 删除死代码（~15 行） | O1, O2, O4 |
| **P2** | M2：统一 `_write_obs_registry` 正则 | M2 |

**可删代码行数估计**：~40 行（O1 3 + O2 6 + O4 6 + O6 17 + O3 8）。
