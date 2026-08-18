# Code Review：边界生命周期与质量基础设施模块（第 10 轮）

> 日期：2026-07-23
>
> 范围：`tools/freeze_bounds.py`（90 行）、`src/common/input_manifest.py`（295 行）、`src/common/quality.py`（604 行）、`src/common/project.py`（78 行）、`src/common/run_state.py`（63 行）
>
> 对照规范：`AGENTS.md`（Parameter Bound Layers / Data Flow）、`docs/敏感性分析与率定用户指南.md`
>
> 关联前轮：第 2 轮 C1/C2（FL-VS/XFINT 文档与代码不符）、第 6 轮（`_resolve_bounds_id` 消费侧）
>
> 测试：`test_freeze_bounds_*.py`、`test_input_manifest_*.py`、`test_quality_*.py`、`test_run_state_*.py` — 全部通过

## 审查结论

5 个审查模块整体质量**良好**：边界冻结的不可变性、input bundle 的完整性门禁、科研/工程状态分离、YAML scalar 转义对 Windows 路径的处理均设计到位且有测试覆盖。主要风险集中在**下游消费者（`build_pest.py`）对冻结契约的强制范围不足**（X1、X2），使得 `freeze_bounds.py` 建立的审批 provenance 可被路径直传绕过。模块内部无重大过度设计，死代码量约 17 行。

---

## 发现清单

### X1 [中·冲突] `--bounds-id` 强制范围与文档不符

**位置**：`build_pest.py` 消费侧（非本审查模块，但直接关系边界生命周期强制）

**现象**：AGENTS.md 称"Calibration 必须指定 `--bounds-id`，无自动回退到最新 SA 结果"。但 `build_pest.py` 仅在 `--design-config` 分支（第 2854-2873 行）强制 `--bounds-id`；无 `--design-config` 时回落到 `--bounds-review-csv` 的 "auto" 模式，非 staged（legacy）率定可在无 `--bounds-id` 下运行。

**建议**：将 `--bounds-id` 强制提升为所有率定 mode 的硬性契约，或修订 AGENTS.md 明确"仅 staged 率定强制"。

---

### X2 [中·冲突] 冻结步骤可被路径绕过

**位置**：`build_pest.py:_resolve_bounds_id`（第 94-95 行）

**现象**：`_resolve_bounds_id` 接受任意 `os.path.exists(bounds_id)` 的文件路径作为"frozen bounds"。`--bounds-id path/to/bounds_proposals/xxx.csv` 会通过 `assert_valid_frozen_bounds`（仅校验 CSV 内容）而被采纳，绕过 `freeze_bounds.py` 的审批/元数据步骤，丢失 `approved_by`/`derived_from`/`automatic_repairs` 等溯源。内容安全保留，但审批 provenance 丢失。

**建议**：`_resolve_bounds_id` 应校验解析出的路径位于 `bounds_frozen/` 下，拒绝 `bounds_proposals/` 路径直传；或要求 frozen CSV 同目录存在同名 `.yaml` 元数据作为准入凭证。

---

### X3/X4 [低·冲突] XFINT/FL-VS 文档与代码不符（第 2 轮 C1/C2 确认）

**位置**：`param_registry.py` vs `AGENTS.md`

详见第 2 轮 C1/C2。AGENTS.md 中"XFINT constrained to 0.12–0.50"和"FL-VS is always fixed at 100.0"两条均与代码和 SA 指南不符，需同步文档。

---

### Q1 [中] `read_flat_run_manifest_field` 用 `errors="ignore"` 静默丢弃非 UTF-8 字节

**位置**：`quality.py:214`

**现象**：作为科研完整性链路的一环，`errors="ignore"` 会掩盖损坏/篡改。推测为兼容历史编码而设，但削弱了完整性保证。

**建议**：改 `errors="strict"`，或加显式编码回退。

---

### F1 [低] `freeze_bounds.py` 的 `notes` 字段 YAML 转义不健壮

**位置**：`freeze_bounds.py:78`

**现象**：`f'notes: "{args.notes}"'` 直接以双引号包裹写入 YAML。若 notes 含 `"` 或换行会破坏 YAML 解析。`quality.py` 已有 `serialize_manifest_scalar` 专门处理此问题，但本模块未复用。

---

### F2 [低] 冻结元数据 YAML 自身无 hash 保护

**位置**：`freeze_bounds.py`

**现象**：`derived_from_sha256` 覆盖 proposal、`bounds_sha256` 覆盖 frozen CSV，但 metadata YAML 本身被篡改（如改 `approved_by`/`automatic_repairs`）无法检测。provenance 链有缺口。

---

### I1 [低·死代码] `manifest_summary` 和 `issues_as_dicts` 零调用

**位置**：`input_manifest.py:263-276`

全代码库（含测试）零调用方。约 15 行死代码。

---

### I2 [低·死代码] `USE_GENETIC_SENSITIVITY` 常量零外部调用

**位置**：`input_manifest.py:31`

定义并导出但无任何外部调用方；测试与 SA 构建均用字符串字面量。

---

### P1 [低] `git_metadata()` docstring 与行为不符

**位置**：`project.py:62, 72`

**现象**：docstring 称 "never hide command failure"，但实现中 git 命令非零退出时返回 `""`，调用方无法区分"git 未安装"与"干净工作树/无提交"。

---

### 其他次要问题

| 编号 | 位置 | 问题 |
|---|---|---|
| F3 | `freeze_bounds.py:63,69-70` | `created_at` 与 `approved_at` 使用同一时间戳，语义重叠 |
| F4 | `freeze_bounds.py:28` | `os.environ.get("USERNAME","unknown")` 为 Windows 专属变量 |
| F5 | `freeze_bounds.py:73` | `derived_from` 仅记录 basename，不含目录路径 |
| I3 | `input_manifest.py:200` | `verify_manifest_files` 仅扫描顶层文件，静默跳过子目录 |
| I4 | `input_manifest.py` docstring | `intended_use` 描述为门禁但实际仅校验 `prohibited_use` |
| I5 | `input_manifest.py:191` | SHA-256 比较用大小写不敏感 |
| Q2 | `quality.py:128` | `load_quality_report` 不校验 `schema_version` |
| Q3 | `quality.py:198-199` | `_strip_manifest_scalar` 对双引号遗留 scalar round-trip 非无损 |
| Q4 | `quality.py:216-222` | 重复 key 时返回首个匹配，行为未定义 |
| P2 | `project.py:46` | `resolve_path(must_exist=False)` 不验证存在性 |
| R1 | `run_state.py:62` | `canonical_status` 对未识别值原样返回 |
| R2 | `run_state.py:60-61` | `text.startswith("stop")` → `"stopping"` 可能误映射 `"stopped"` |

---

## 已验证一致的关键点

| 检查项 | 结论 |
|---|---|
| freeze_bounds 晋升语义正确 | ✓ 调用 `assert_valid_frozen_bounds` 在写入前校验，校验失败抛 `ValueError` 终止，绝不 mutate/clamp/repair |
| 冻结 ID 不可覆盖 | ✓ 已存在时 `parser.error` |
| 元数据完整性 | ✓ 包含 `bounds_id`/`crop`/`created_at`/`approved_at`/`approved_by`/`review_status:"approved"`/`derived_from`/`derived_from_sha256`/`bounds_sha256`/`parameter_count`/`automatic_repairs:0`/`notes` |
| input_manifest 校验严格 | ✓ bundle_id==目录名、逐文件 SHA-256、`UNTRACKED_FILE` 检测、`FILE_MISSING`/`HASH_MISMATCH` 分类、malformed JSON 拒绝 |
| 无自动回退到"最新 SA" | ✓ `_resolve_bounds_id` 在 frozen 目录找不到时返回 `None`（仅在路径直传场景有 X2 软绕过） |
| 科研/工程状态分离 | ✓ `science_validation_mode="engineering_only"` 阻止 IES 报告自授科研有效性 |
| `serialize_manifest_scalar` 设计正确 | ✓ YAML 单引号 scalar 保留 Windows 反斜杠字面值 |
| `sha256_file` 流式读取 | ✓ 1MB chunk，内存安全，跨平台 |
| `run_state` Windows 退出码处理 | ✓ `WINDOWS_CONTROL_C_EXIT=0xC000013A` 正确，区分 abort 与 runtime_failed |
| Frozen CSV 列与文档一致 | ✓ `name,init,lower,upper,status,pargp,location,file,cultivar,ecotype,mode` 与 AGENTS.md 完全一致 |

---

## 建议的后续行动（按优先级）

| 优先级 | 行动 | 对应问题 |
|---|---|---|
| **P1** | `_resolve_bounds_id` 校验路径位于 `bounds_frozen/` 下，拒绝 `bounds_proposals/` 路径直传 | X2 |
| **P1** | 将 `--bounds-id` 强制提升为所有率定 mode 的硬性契约，或修订 AGENTS.md | X1 |
| **P2** | `read_flat_run_manifest_field` 改 `errors="strict"` | Q1 |
| **P2** | `freeze_bounds.py` 复用 `quality.serialize_manifest_scalar` 写 notes | F1 |
| **P2** | 同步 AGENTS.md 中 XFINT/FL-VS 表述 | X3, X4 |
| **P3** | 删除 `manifest_summary`/`issues_as_dicts`/`USE_GENETIC_SENSITIVITY` 死代码 | I1, I2 |
| **P3** | `git_metadata` 区分"命令失败"与"空输出" | P1 |

**可删代码行数估计**：~17 行（I1 15 + I2 2）。
