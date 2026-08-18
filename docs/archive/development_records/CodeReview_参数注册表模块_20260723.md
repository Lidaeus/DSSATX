# Code Review：参数注册表模块（第 2 轮）

> 日期：2026-07-23
>
> 范围：`src/common/param_registry.py`（696 行）
>
> 对照规范：《敏感性分析与率定用户指南》§3/§3.1/§5（2026-07-22 当前权威指南）、《T9 高维参数率定边界调整方案》（2026-07-22）、《项目状态与科研启动清单》（2026-07-22）、`AGENTS.md` 参数约定
>
> 关联代码：`src/calibration/build_pest.py`（DEFAULT_BOUNDS 消费方）、`src/sensitivity/sa_generate_param_review_csv.py` + `sa_postprocess_sobol_interpret.py`（compute_default_bounds 消费方）、`tools/freeze_bounds.py` 等 6 个工具（assert_valid_frozen_bounds 消费方）
>
> 测试：`tests/test_param_validation.py`（9）、`tests/test_migration.py`（含 param_registry 部分）、`tests/test_p1_readiness.py`，本轮 `test_param_validation.py + test_migration.py` 通过（exit 0）

## 审查结论

`param_registry.py` 的**核心校验语义与规范完全一致**：物理硬边界覆盖全部 shipped baseline、`validate_frozen_bounds` 拒绝（而非裁剪/重排）非法范围、温度四组顺序与 XMAGE<XFPHT、SLLL<SDUL<SSAT 顺序约束、FIXED/ACTIVE 语义、SOIL/IC nuisance 警告均正确实现并有测试覆盖。`AGENTS.md` 自己标记待核对的 FL-VS / XFINT 两个潜在冲突经核对**确实存在**——但冲突方向是 `AGENTS.md` 约定陈旧，`param_registry` 代码与 T9/T10 权威冻结边界/专题规范反而一致。

主要问题与第 1 轮同构：**过度设计与死代码**。模块中存在一整套未被生产消费的"注册表 CSV I/O"子系统（`RegistryEntry`/`load_registry_csv`/`save_registry_csv`/`REGISTRY_COLUMNS`，约 115 行），以及两个无生产调用且其中一个与"拒绝而非裁剪"策略相悖的工具函数（`infer_parameter_group`、`clamp_to_physical`）。此外 `DEFAULT_BOUNDS` 相对 T9/T10 权威冻结边界已发生漂移，且漂移通过 `build_pest.py` 的 extra-params fallback 与 SA review CSV 两条路径渗入生产。

发现按严重程度分级：**冲突/不一致（C）**、**过度设计（O）**、**次要/建议（M）**。

---

## C1 [中·冲突] `AGENTS.md`「FL-VS 恒为 100.0 且非率定参数」与代码 / 冻结边界 / 专题规范三方冲突

**位置**：`AGENTS.md`（Important Conventions）；`param_registry.py:80,153`；`data/parameter_registry/bounds_frozen/eggplant/eggplant_t9_highdim_v1_20260722.csv:22`、`eggplant_t10_m0_v1_20260722.csv:22`

**现象**：
- `AGENTS.md` 明文："`FL-VS` is always fixed at 100.0 (not a calibration parameter)"。
- `param_registry.py:80` `PHYSICAL_BOUNDS["FL-VS"] = (0.0, 300.0)`，注释「Indeterminate crops may legitimately use values above 100」。
- `param_registry.py:153` `DEFAULT_BOUNDS["FL-VS"] = (100.0, 140.0)`（`lb != ub` → 状态 active）。
- T9 冻结：`FL-VS,120.0,100.0,140.0,active`。
- T10 M0 冻结：`FL-VS,120,120,120,fixed`（固定，但固定值是 **120**，不是 100）。
- 《敏感性分析与率定用户指南》§3.1 与《项目状态与科研启动清单》均明确：FL-VS 以 100–140 作为结构敏感性探针，T9 接受用户决定将其设为活动参数。

**冲突点**：`AGENTS.md` 的约定在 T9 之后已被显式推翻（先 active 100–140，T10 再 fixed 120）。`param_registry` 代码与权威专题规范一致、是正确的一方；`AGENTS.md` 是陈旧的一方。但 `param_registry` 内部对此无任何提示或守卫，新读者若以 `AGENTS.md` 为准会误判代码违规。

**建议**：更新 `AGENTS.md` 该条约定（FL-VS 不再恒为 100；T9 active 100–140、T10 fixed 120），并在 `param_registry.py:153` 的 DEFAULT_BOUNDS 注释里补一句「T9 起作为结构敏感性探针活动」。代码无需改动。

---

## C2 [中·冲突] XFINT「0.12–0.50 防 IPDMND」约束既不在代码也不在冻结边界中

**位置**：`AGENTS.md`；`param_registry.py:92,164`；T9/T10 冻结边界

**现象**：
- `AGENTS.md` 明文："`XFINT` constrained to 0.12–0.50 to avoid IPDMND risk"。
- `param_registry.py:92` `PHYSICAL_BOUNDS["XFINT"] = (0.0, 1.0)`（纯数值包络，未提 IPDMND）。
- `param_registry.py:164` `DEFAULT_BOUNDS["XFINT"] = (0.10, 0.35)`。
- T9 冻结：`XFINT,0.3,0.08,0.5,active`（下界 **0.08**，低于 AGENTS.md 所称 0.12 安全下限）。
- T10 M0 冻结：`XFINT,0.3,0.08,0.5,active`（同上）。
- 《T9 方案》§4/§5.1 明确将 XFINT 由 T8 的 0.12–0.35 扩为 0.08–0.50。

**冲突点**：AGENTS.md 声称的「IPDMND 安全下限 0.12」在 `param_registry` 中没有任何编码（物理下界是 0.0），而 T9/T10 的权威冻结边界已将下界下探到 0.08 并通过 `assert_valid_frozen_bounds` 校验（因 0.08 ≥ 物理下界 0.0）。即：**要么 IPDMND 风险已被重新评估、AGENTS.md 陈旧，要么冻结边界在未更新守卫的情况下接受了该风险**。两种情形都属于文档/实践/代码三者不一致。

**建议**：需用户/领域决策定调。若 0.08 确实安全，应在 `param_registry.py:92` 注释说明 IPDMND 风险为何不构成物理下限，并同步修订 AGENTS.md；若 0.12 才是真实安全地板，则 T9/T10 冻结边界的 XFINT 下界需复审。**不应让 `AGENTS.md` 的安全声称与代码/冻结层长期矛盾。**

---

## C3 [中] `DEFAULT_BOUNDS` 与权威冻结边界漂移，且经两条生产路径渗入

**位置**：`param_registry.py:145-190`；`build_pest.py:463-477`（`ECO_BOUNDS_EGGPLANT`/`SPE_TEMP_BOUNDS_EGGPLANT`）；`sa_generate_param_review_csv.py:67`、`sa_postprocess_sobol_interpret.py:94`

**现象**：

| 参数 | `DEFAULT_BOUNDS`（param_registry） | T9 冻结 | T10 M0 冻结 |
|---|---|---|---|
| XFINT | (0.10, 0.35) | (0.08, 0.50) | (0.08, 0.50) |
| XFPHT | (35.0, 70.0) | (35.0, 70.0) | **(31.0, 70.0)** |
| SLAVR | (—, 不在表) | (220, 340) | (240, 330) |

`DEFAULT_BOUNDS` 被两条生产路径消费：
1. `build_pest.py:463-477` 用 `DEFAULT_BOUNDS` 构造 `ECO_BOUNDS_EGGPLANT` / `SPE_TEMP_BOUNDS_EGGPLANT`，作为 `parse_extra_params(bounds_map=...)` 的 fallback 边界（`build_pest.py:3645,3653`）。
2. `sa_generate_param_review_csv.py:67` 与 `sa_postprocess_sobol_interpret.py:94` 调用 `compute_default_bounds`，而 `compute_default_bounds` 优先查 `DEFAULT_BOUNDS`（`param_registry.py:280`），用于生成 SA 参数复核 CSV。

**影响**：当前 T9/T10 正式率定的可率定参数走 `--bounds-id` 冻结 CSV 路径（`build_pest.py:2976,3712`），故 `DEFAULT_BOUNDS` 漂移暂未污染正式率定；但 SA 参数复核 CSV 对 XFINT 会输出 (0.10, 0.35)、对 XFPHT 输出 (35, 70)，与 T9/T10 科学决策不一致。若后续有人用 extra-params 路径注入 XFINT/XFPHT，会落到陈旧的窄范围上。

**判断**：`DEFAULT_BOUNDS` 在模块内被注释明确定义为「比物理硬边界更窄的工作范围，来源是文献 + 历史率定经验」，并非权威层；但它并非纯死代码——它是 SA 与 extra-params 的实际 fallback。漂移属于「陈旧默认值」类不一致，非硬性 bug。

**建议**：将 `DEFAULT_BOUNDS` 的 XFINT 同步到 (0.08, 0.50)、XFPHT 同步到 (31.0, 70.0)（或明确标注 DEFAULT_BOUNDS 只反映 T8 前基线、T9/T10 须读冻结层），并在 `compute_default_bounds` 入口注释强调「SA 复核 CSV 的范围仅为建议，正式率定一律以 frozen bounds 为准」。

---

## O1 [严重·过度设计] `RegistryEntry` / `load_registry_csv` / `save_registry_csv` / `REGISTRY_COLUMNS` 整套注册表 I/O 子系统为死代码

**位置**：`param_registry.py:23-41`（`REGISTRY_COLUMNS`）、`605-696`（`RegistryEntry`、`load_registry_csv`、`save_registry_csv`、`_safe_float`、`_fmt_float`）

**现象**：全仓 grep 该 4 个符号，生产侧零调用，唯一消费者是 `tests/test_migration.py:22-28` 的迁移存活性测试。模块自身职责声明第 4 条「加载/保存参数注册表 CSV」实际并不在生产执行。

权威参数工件的真正 schema 是冻结边界 CSV（`name,init,lower,upper,status,pargp,location,file,cultivar,ecotype,mode[,review_note,decision_role]`），与本子系统提供的 `REGISTRY_COLUMNS`（`parameter_name,crop,parameter_family,target_file,section,dtype,format_width,format_precision,base_value,physical_lower,physical_upper,default_step,calibration_stage,enabled_by_default,description`）**完全不同**：

- `data/parameter_registry/baseline/baseline_params.csv` 实际 schema 是 `name,value`（两列），并非 `REGISTRY_COLUMNS`。
- `data/parameter_registry/baseline/parameter_registry_skeleton.csv` 虽采用 `REGISTRY_COLUMNS`，但文件名即「skeleton」——是一份未填充的模板，无代码读取。

即：`load_registry_csv` 能读 skeleton，但没有任何生产路径调用它；`save_registry_csv` 也无任何生产写入方。整套 I/O 子系统（约 115 行）是 P0 期设计的「注册表」概念遗留，后被「冻结边界 CSV + 物理边界字典」双轨取代但未清理。

**过度设计判断**：`AGENTS.md` 称 `param_registry.py` 为「Single source of truth for all parameter constraints」——对 `PHYSICAL_BOUNDS` / `DEFAULT_BOUNDS` / `validate_frozen_bounds` 成立，但对 registry-CSV I/O 层不成立。保留这套未被消费的 I/O 反而让读者误以为存在第三套参数来源。

**建议**：删除 `REGISTRY_COLUMNS`、`RegistryEntry`、`load_registry_csv`、`save_registry_csv`、`_safe_float`、`_fmt_float`（`_fmt_float` 仅被 `save_registry_csv` 调用，一并删）。同步精简模块 docstring 第 4 条职责。预计删 ~115 行。若担心外部脚本依赖，先在 `__all__` 移除并标注废弃一轮再删。

---

## O2 [中·过度设计] `infer_parameter_group` 与 `clamp_to_physical` 生产无调用，且后者与「拒绝而非裁剪」策略相悖

**位置**：`param_registry.py:195-256`（`infer_parameter_group`）、`359-373`（`clamp_to_physical`）

**现象**：
- `infer_parameter_group`：全仓生产侧零调用，唯一消费者 `tests/test_migration.py:38-43`。冻结边界 CSV 已自带 `pargp` 列（见 T9/T10 文件），无需推断。
- `clamp_to_physical`：全仓生产侧零调用，唯一消费者 `tests/test_migration.py:48-49`。

**策略冲突**：`validate_frozen_bounds` 的 docstring（`param_registry.py:393-396`）明确「Invalid ranges are **rejected rather than reordered, clipped, or expanded automatically**」，《T9 方案》§5.1 也要求「范围均位于当前物理硬边界内」（即由人保证，不是程序裁剪）。而 `clamp_to_physical` 的语义正是「clip 到物理边界内」——保留它等于在模块内暗示「越界可被静默裁剪」，与权威策略直接相悖。

**判断**：`infer_parameter_group` 是纯死代码；`clamp_to_physical` 是「死代码 + 策略误导」双重问题。两者均由 `test_migration.py` 以「迁移存活性」名义保留，但迁移早已完成（项目处于 phases 0–4 完成后），该测试本身值得复审。

**建议**：删除 `infer_parameter_group`、`clamp_to_physical` 及 `test_migration.py` 中对应断言；若 `test_migration.py` 整体已无迁移对象，考虑将其改造为对仍在用的 `compute_default_bounds` / `validate_frozen_bounds` 的常规测试或直接移除。

---

## O3 [次要] `_soil_bounds` 中 SALB/SLDR/SLRO 分支不可达；VSSINK/KC_SLOPE 特例与冻结值漂移

**位置**：`param_registry.py:280-283`（DEFAULT_BOUNDS 优先查找）、`322-354`（`_soil_bounds`）、`296-304`（VSSINK/KC_SLOPE 特例）

**现象 1（不可达分支）**：`compute_default_bounds` 第 280 行先查 `DEFAULT_BOUNDS`，命中即返回。`SOIL_SALB`/`SOIL_SLDR`/`SOIL_SLRO` 已在 `DEFAULT_BOUNDS`（`param_registry.py:187-189`），因此 `_soil_bounds` 第 325-330 行的这三个分支永远不会被执行——它们与 `DEFAULT_BOUNDS` 重复定义同一组数值（(0.05,0.35)/(0.10,2.00)/(40,95)），属于被遮蔽的死分支。

**现象 2（特例漂移）**：VSSINK、KC_SLOPE 不在 `DEFAULT_BOUNDS`，走 `compute_default_bounds` 的特殊分支：
- VSSINK（init=4.1）：`lb=max(0.2, 0.5*4.1)=2.05`、`ub=max(2.05+0.2, 2*4.1)=8.2` → (2.05, 8.2)。T9/T10 冻结为 (1.5, 8.0)。
- KC_SLOPE（init=0.1）：`lb=max(0, 0.1-0.10)=0.0`、`ub=0.1+0.10=0.2` → (0.0, 0.2)。T9/T10 冻结为 (0.04, 0.2)。

SA 参数复核 CSV 经 `compute_default_bounds` 对这两个参数会输出特例范围，与科学冻结值不一致（VSSINK 下界差 0.55、KC_SLOPE 下界差 0.04）。

**判断**：现象 1 是纯重复死分支；现象 2 与 C3 同源（DEFAULT_BOUNDS 体系未跟进 T9/T10），但因其走特殊分支而非查表，故单列。

**建议**：删除 `_soil_bounds` 中 SALB/SLDR/SLRO 三分支（保留 SLLL/SDUL/SSAT/SBDM/SLOC/通用分支）；将 VSSINK、KC_SLOPE 的期望范围写入 `DEFAULT_BOUNDS`（(1.5, 8.0)/(0.04, 0.2)）并删除特殊分支，统一走查表路径。

---

## M1 [建议] `compute_default_bounds` 通用 ±25%/±30% 回退与规范「不自动扩边界」精神略有张力

**位置**：`param_registry.py:307-319`

**现象**：对未命中 `DEFAULT_BOUNDS`、非 SOIL/IC/VSSINK/KC_SLOPE 的参数，回退到 `lb=init*0.75, ub=init*1.25`（init∈(0,1] 时为 0.7/1.3）。这是对任意未识别参数的 blanket 百分比启发式。

**对照规范**：《敏感性分析与率定用户指南》§5 与《T9 方案》§11 强调「不自动扩边界」「范围调整规则应预注册」。`compute_default_bounds` 用于 SA 复核 CSV，并非率定自动扩边界器，故不构成违规；但 blanket ±25% 可为本应固定的参数 fabricate 出一个活动范围，SA 读者可能误以为该范围有依据。

**建议**：低优先级。可考虑对未命中 `DEFAULT_BOUNDS` 的参数返回 `(init, init, "fixed")` 而非 ±25%，强制人工显式声明活动范围；或在该回退路径打 warning。

---

## 已验证一致的关键点（无问题）

为避免只报问题，下列规范要求经代码与数值核对**确认实现正确**：

1. **物理硬边界覆盖 shipped baselines**：`test_physical_safety_envelopes_include_shipped_dssat_baselines` 校验 WTPSD=0.004、SD-PM=400、FL-LF=400、SDPDV=111.4、PARMAX=41、PHTMAX=61、FINREF=220、EVMODC=0、FL-VS=120、XFPHT=60、XFINT=0.10 全部落入 `PHYSICAL_BOUNDS`。✓
2. **拒绝而非裁剪**：`validate_frozen_bounds` 对 REVERSED_BOUNDS / INIT_OUTSIDE_BOUNDS / OUTSIDE_PHYSICAL_BOUNDS 一律报 error，不重排不截断（`param_registry.py:473-502`）。✓（规范：immutable scientific decisions）
3. **温度四组顺序全校验**：`_validate_temperature_relationships` 对 (TB,TO1,TO2,TM) 及 TB1/2/3 三套均校验 init 顺序与 range 顺序（`param_registry.py:539-564`）。✓（T9 §5.1）
4. **XMAGE < XFPHT 顺序**：`_validate_stage_relationships` 同时校验 init 与 range（`param_registry.py:521-536`）。✓（T9/T10）
5. **土壤水 SLLL < SDUL < SSAT 顺序**：`_validate_soil_water_relationships` 按后缀分组校验（`param_registry.py:567-592`）。✓
6. **FIXED/ACTIVE 语义**：`fixed` 要求 `lower==init==upper`；`active` 要求 `lower<upper`（`param_registry.py:477-486`）。✓
7. **SOIL/IC/INIT nuisance 警告**：`NUISANCE_PARAMETER_ACTIVE` 对 active 的 SOIL/IC/INIT 发 warning（`param_registry.py:505-513`）。✓（SA 指南 §5「土壤和初始条件默认固定」）
8. **FRCNOD 排除约定**：物理边界存在并标注「fixed/excluded for eggplant」；T9/T10 冻结文件均 `FRCNOD,0.05,0.05,0.05,fixed`。约定由冻结层落实、代码不强制，可接受。✓
9. **v14 作为已知失败 fixture 保留并回归**：`test_current_v14_is_a_preserved_failure_fixture` 固化其 21 个 error + 44 个 warning，防止回归误判。✓（良好的防腐设计）
10. **DERIVED / seasonal_offsets.json 前向校验**：`validate_frozen_bounds` 接受 `location=DERIVED` 且限定 `target_file=seasonal_offsets.json`（`param_registry.py:449-456`），与 T10 秋季偏移 `eggplant_t10_m1_autumn_offsets_v1_20260723.csv` 对应。✓

---

## 建议的后续行动（按优先级）

1. **C2（需用户决策）**：XFINT 的 IPDMND 安全下限到底是 0.12 还是 0.08？定调后同步 `AGENTS.md` 与 `param_registry.py:92` 注释，或复审 T9/T10 冻结下界。这是本轮唯一需要领域判断的项。
2. **C1 + C3（文档/默认值同步）**：更新 `AGENTS.md` 的 FL-VS 条目；将 `DEFAULT_BOUNDS` 的 XFINT/XFPHT/SLAVR 同步到 T9/T10 冻结值或显式标注其仅反映 T8 前基线。
3. **O1（删 ~115 行死代码）**：移除 `REGISTRY_COLUMNS`/`RegistryEntry`/`load_registry_csv`/`save_registry_csv`/`_safe_float`/`_fmt_float` 及模块 docstring 第 4 条职责。
4. **O2（删 2 个死函数）**：移除 `infer_parameter_group`/`clamp_to_physical`，并复审 `test_migration.py` 是否仍有存在必要。
5. **O3 + M1（清理）**：删 `_soil_bounds` 不可达三分支；将 VSSINK/KC_SLOPE 移入 `DEFAULT_BOUNDS` 并删特殊分支；考虑 M1 的 fixed 回退。

---

## 附：本轮未覆盖（下一轮候选）

- `build_pest.py`（最大、最值得审，~103KB；本轮仅交叉核对了 DEFAULT_BOUNDS 消费点，完整审查需 1–2 轮）。
- `src/sensitivity/sa_generate_param_review_csv.py` + `sa_postprocess_sobol_interpret.py`（`compute_default_bounds` 的真正消费者，决定 SA 复核 CSV 范围语义，独立一轮）。
- `tools/freeze_bounds.py` + `prepare_*_bounds.py`（6 个冻结前 preparer，均调 `assert_valid_frozen_bounds`，可合并一轮审查 preparer 一致性）。
- `run_dssat.py` + 并行隔离（对照《DSSAT 并行隔离与输入路径规范》）——独立一轮。
