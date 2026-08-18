# Code Review：试验规范框架模块

> 日期：2026-07-24
>
> 审查对象：`src/calibration/experiment_spec.py`（689 行）
>
> 审查模式：只读审查，不修改任何代码
>
> 依据文档：`docs/参数率定试验架构与协作交接_v1_20260723.md` §3，`docs/参数率定试验矩阵与论文逻辑_v1_20260723.md` §2-§3

## 1. 模块概述

`experiment_spec.py` 是 P0-B 工作包的核心交付——试验规范框架的解析、哈希钉扎和契约强制模块。它绑定参数集、冻结边界、观测策略、多季节设计和执行配置，在 build 前完整验证所有输入的一致性。

**架构定位**：所有率定试验（E00-E07）的唯一可审计入口。`ExperimentSpec.load()` 是 build 前的强制门控。

## 2. 审查对象

| 文件 | 行数 | 职责 |
|---|---|---|
| `src/calibration/experiment_spec.py` | 689 | spec 解析、SHA-256 钉扎、契约强制、receipt 生成、矩阵一致性校验 |
| `tests/test_experiment_spec.py` | ~400 | 30 项测试覆盖合法 spec、模板 spec 拒绝、禁止 Phi、26SP 角色、E05 偏移、矩阵一致性 |
| `configs/experiments/specs/E00-E06*.json` | 9 个 | 实际 spec 文件 |
| `configs/experiments/observation_profiles/direct_chpdt_log_v1.json` | 1 个 | 观测策略 profile |

## 3. 核心发现

### S1 [中·死代码+bug] `_load_parameter_set` inline dict 支持无效且存在逻辑 bug

**位置**：`experiment_spec.py:360-408`

**现象**：`_load_parameter_set` 支持两种输入：路径字符串和内联字典。当 `ref` 是字典时：

```python
elif isinstance(ref, dict):
    _require_keys(ref, "parameter_set (inline)", ...)  # 验证内联字段
    path = _resolve_path(ref["path"])
    raw = ref                                                # ← 赋值
else:
    ...
with path.open("r", encoding="utf-8") as fh:
    raw = json.load(fh)                                      # ← 覆盖！内联数据被丢弃
```

`raw = ref` 在第 369 行赋值后，被第 374 行的 `raw = json.load(fh)` 覆盖。内联字典的 `set_id`、`parameters`、`source_file` 等字段**永远不会被使用**——只有 `ref["path"]` 被用来加载文件。

**影响**：
- 内联字典路径的 `_require_keys` 验证（第 365-367 行）是无效操作
- 如果内联字典的 `path` 指向的文件内容与内联字段不一致，代码会静默使用文件内容而非内联声明
- 无 spec 使用内联字典，无测试覆盖此路径

**根因**：内联字典支持是为"未来灵活性"添加的，但实现不完整——应该在 `ref` 是字典时直接使用 `ref` 作为 `raw`，不重新加载文件（或至少用文件内容覆盖前先校验一致性）。

**建议**：移除内联字典支持（所有 spec 都使用路径字符串），或修复为真正使用内联数据。

### S2 [低·死代码] `SCHEMA_VERSION` 常量未使用

**位置**：`experiment_spec.py:59`

**现象**：`SCHEMA_VERSION: int = 1` 定义后从未被引用、检查或写入 receipt。

**影响**：无实际影响，但暗示了一个未实现的设计意图（版本化 schema 迁移）。

**建议**：移除，或在 spec JSON 中要求 `"schema_version": 1` 字段并在 `load()` 中校验。

### D1 [低·文档不一致] `bounds_sha256` 字段在文档中声明但代码不读取

**位置**：架构交接文档 §3 的 spec 示例包含 `"bounds_sha256": "..."`，但代码不从 spec JSON 读取此字段。

**现象**：
- 架构文档 §3 的 spec 示例包含 `"bounds_sha256": "..."`
- 9 个实际 spec 文件均**不包含** `bounds_sha256` 字段
- 代码在 `load()` 中从文件**计算** `bounds_sha256 = sha256_file(bounds_path)`（第 179 行），不读取 spec 中的声明值

**评估**：代码的做法**优于**文档设计——从文件计算哈希可防止声明值过期。但文档应更新以反映实际实现。

**建议**：更新架构文档 §3，移除 `bounds_sha256` 字段或标注"由代码计算，不需在 spec 中声明"。

### D2 [低·设计限制] 26SP `frozen_validation` 角色强制不完整

**位置**：`experiment_spec.py:552-574`，`_enforce_26sp_role`

**现象**：文档规定"`frozen_validation` 仅在 E02 前有效"，但代码只拒绝 `validation` 角色，不拒绝 E02+ 实验中的 `frozen_validation`。

**影响**：一个 E06 spec 如果将 26SP 标为 `frozen_validation`，代码会接受。当前所有实际 spec 都正确标记了 26SP 角色（E00=`frozen_validation`，E06=`development_calibration`），所以没有实际触发。

**根因**：代码无法知道当前实验是 E00 还是 E02+，除非解析 `experiment_id` 中的编号（脆弱）。

**建议**：可接受的 pragmatic 限制。如需更强强制，可在 spec JSON 中增加 `"experiment_phase": "pre_e02" | "e02_plus"` 字段。

### O1 [低·过度设计] `validate_matrix_consistency` 未集成到工作流

**位置**：`experiment_spec.py:600-689`

**现象**：`validate_matrix_consistency()` 是一个有用的矩阵级一致性校验函数（检查对比组的 seed/reals/noptmax/observation_profile/season_inputs 一致性），但：
- 仅被 3 个测试调用
- 不被 CLI `run_calibration_experiment.py` 调用
- 不被 `experiment_runner.py` 调用
- 不在 `prepare_experiment_run` 或 `run_build` 中执行

**影响**：函数功能正确且有测试覆盖，但未集成到生产流程中。对比组一致性违规只会在手动调用时被发现。

**建议**：在 CLI 的 `--build-only` 路径中增加可选的 `--validate-matrix` 标志，调用此函数。或在 `prepare_experiment_run` 中自动调用（当 spec 属于某个对比组时）。

### P1 [低·验证缺口] `ObservationProfile` 的 offset/reference 未与 transform 一致性校验

**位置**：`experiment_spec.py:411-439`

**现象**：`ObservationProfile` 加载 `transform`（如 `"ln(y+1)"`）、`offset`（如 `1.0`）和 `reference`（如 `1.0`），但不校验三者的一致性。如果 `transform="ln(y+1)"` 但 `offset=0.0`，代码不会报错。

**影响**：当前 profile `direct_chpdt_log_v1.json` 的值是正确的（`offset=1.0` 与 `ln(y+1)` 一致）。但如果未来新增 profile 时手误设错 offset，不会被 spec 校验捕获。

**建议**：可选改进——在 `_load_observation_profile` 中增加 `transform` 与 `offset` 的交叉校验（如 `ln(y+1)` 要求 `offset=1.0`）。

### P2 [低·硬编码] `_resolve_frozen_bounds_path` 硬编码 "eggplant"

**位置**：`experiment_spec.py:508`

**现象**：`frozen_dir = PROJECT_ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant"` 硬编码了作物名。

**影响**：当前项目仅率定 eggplant，无实际影响。但如果未来扩展到番茄原生率定，需要修改此函数。

**建议**：可接受的项目范围限制。如需泛化，可从 spec JSON 的 `"crop"` 字段读取（当前 spec 无此字段）。

## 4. 正面发现

| 验收点 | 状态 | 证据 |
|---|---|---|
| SHA-256 钉扎所有工件 | ✅ | spec/parameter_set/bounds/observation_profile/season_inputs 全部计算并存储哈希 |
| 禁止 Phi 目标强制 | ✅ | `FORBIDDEN_PHI_TARGETS = {PWAD, PWAI, HWAM}`，load() 第 202-208 行拒绝 |
| CHPDT 必须为活跃 Phi 目标 | ✅ | 第 211-215 行强制 |
| 参数计数匹配 | ✅ | `bounds_active_count != pset.declared_count` 时拒绝（第 182-187 行） |
| 26SP 角色强制（部分） | ✅ | 拒绝 `validation` 角色（D2 指出 `frozen_validation` 未完全强制） |
| E05 秋季偏移验证 | ✅ | 1-3 个偏移、非空、DMC 禁止、target_season 在 season_inputs 中 |
| 无绘图库导入 | ✅ | 仅导入 csv/json/dataclasses/pathlib/typing |
| 无 DSSAT/PEST++ runner 导入 | ✅ | 仅导入 `src.common.project` |
| `bounds_proposals/` 路径拒绝 | ✅ | 第 517-522 行防止跳过 freeze 审批 |
| 矩阵级一致性校验 | ✅ | seed/reals/noptmax/observation_profile/season_inputs 全部对比 |
| frozen dataclass 设计 | ✅ | 所有值对象 `@dataclass(frozen=True)` |
| 测试覆盖 | ✅ | 30 项测试，覆盖合法/非法/边界情况 |
| receipt 完整性 | ✅ | 所有钉扎字段进入 `experiment_receipt.json` |

## 5. 问题列表

| 编号 | 严重度 | 类型 | 位置 | 描述 |
|---|---|---|---|---|
| S1 | 中 | 死代码+bug | 360-408 | `_load_parameter_set` inline dict 支持无效——`raw=ref` 被 `json.load` 覆盖 |
| S2 | 低 | 死代码 | 59 | `SCHEMA_VERSION` 常量从未使用 |
| D1 | 低 | 文档不一致 | 文档 §3 | `bounds_sha256` 在文档中声明但代码不读取（代码做法更好） |
| D2 | 低 | 设计限制 | 552-574 | 26SP `frozen_validation` 在 E02+ 中未被拒绝 |
| O1 | 低 | 过度设计 | 600-689 | `validate_matrix_consistency` 未集成到 CLI 或 runner |
| P1 | 低 | 验证缺口 | 411-439 | `ObservationProfile` offset/reference 未与 transform 交叉校验 |
| P2 | 低 | 硬编码 | 508 | `_resolve_frozen_bounds_path` 硬编码 "eggplant" |

## 6. 根因分析

1. **S1 根因**：内联字典支持是为"未来灵活性"预设的接口，但实现时直接复用了路径字符串的加载逻辑，导致内联数据被覆盖。这是典型的"预设接口但未完成实现"模式。

2. **O1 根因**：`validate_matrix_consistency` 是在 E01→E02 边界提取桥轮次中添加的，当时作为"确保对比组一致性"的防御性功能。但添加时未同步集成到 CLI，因为 CLI 的 `--build-only` 路径只处理单个 spec，不处理整个矩阵。集成需要 CLI 增加矩阵级入口。

3. **D1 根因**：文档先于代码撰写，设计时计划在 spec 中声明 `bounds_sha256`，但实现时改为从文件计算（更安全）。文档未同步更新。

## 7. 建议

### 7.1 立即可做（低风险）

- **S1**：移除 `_load_parameter_set` 的内联字典分支（`isinstance(ref, dict)` 分支），简化为仅支持路径字符串。可删除第 364-370 行。
- **S2**：移除 `SCHEMA_VERSION` 常量（第 59 行），或在 spec JSON 中要求 `schema_version` 字段并校验。
- **D1**：更新架构文档 §3，移除 `bounds_sha256` 或标注"由代码计算"。

### 7.2 后续迭代（需评估）

- **O1**：在 CLI 增加矩阵级校验入口（如 `--validate-matrix configs/experiments/eggplant_article_calibration_matrix_v1.json`）。
- **D2**：如需更强 26SP 强制，在 spec JSON 增加 `experiment_phase` 字段。
- **P1**：在 `_load_observation_profile` 增加 transform-offset 交叉校验。

## 8. 与已审查模块的对比

| 维度 | experiment_spec.py | Sobol 工具链（基准） | build_pest.py |
|---|---|---|---|
| 模块大小 | 689 行 | ~2000 行（5 文件） | ~3900 行 |
| 死代码 | ~15 行（S1+S2） | 极少 | ~126 行（已清理 O1/O2/O3） |
| 过度设计 | 1 处（O1） | 极少 | 多处（已清理） |
| 测试覆盖 | 30 项（充分） | 充分 | 9 项端到端 |
| 文档一致性 | 1 处不一致（D1） | 一致 | 一致 |

**总体评价**：模块质量良好，设计清晰，测试充分。7 个发现中无严重（P0）级别问题，2 个中低级别（S1/S2）可立即修复。与 Sobol 工具链同为项目中的高质量模块。
