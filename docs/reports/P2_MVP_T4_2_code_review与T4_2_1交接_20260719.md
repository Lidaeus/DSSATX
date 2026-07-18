# P2-MVP T4.2 code review 与 T4.2.1 交接（2026-07-19）

> 审查对象：`bf4d551`、`b263159`、`7f8dbc7` 及 `workspace/runs/t3_1_s4_20260718/t4_candidate_predictions/`
> 审查结论：**现有 T4.2-B demo 运行证据可复核，但工具复用契约存在 3 项 P1 和 2 项 P2 缺口；暂不批准接入 R 图表。**
> 下一阶段：只实施 T4.2.1 最小契约收口，不启动新的 IES、Morris 或 Sobol。

## 1. 已通过的证据

- 工作树在审查开始时干净；三个提交范围与 T4.2-A/B/C 记录一致。
- 6 份候选参数 CSV 与 S4 末轮 parameter ensemble 对应行逐值一致，包含 `XFINT/XFRT`，无中位数替代。
- 6 个候选运行的 8 类 OUT 均存在；逐项重算 SHA-256 与各自 `candidate_run_manifest.json` 一致，返回码均为 0。
- posterior manifest 记录的 finalize/artifact-manifest 哈希与当前 S4 文件一致；当前实际使用的 observation policy 也恰为 S4 冻结版。
- 重新从候选 OUT 解析 comparison，并按冻结 split 和 raw-scale `sigma_eff` 重算后，3 对距离与记录值一致：`0.134508`、`0.015569`、`0.022550`。
- 全套测试：`211 passed, 2 skipped`。

因此，现有结果可作为 `tooling_demo` 接口打通证据；下述问题不表示这 6 次 demo 的距离数值已经算错，而是说当前入口无法保证下一次运行仍遵守同一冻结契约。

## 2. code review 发现

### [P1] 冻结证据链没有真正闭合

`candidate_predictions` 验证了 posterior 内各 artifact 的哈希，但没有将 posterior manifest 内的 `calibration_finalize_sha256` 和 `calibration_artifacts_manifest_sha256` 与当前 S4 重新对比。同时，距离计算直接使用 CLI 传入的 `observation_policy_csv`，只把它的哈希写入新 manifest，却没有要求该哈希等于 S4 `run_manifest.yaml` 中冻结的 policy 哈希。

这意味着，同一个 case 下可以混入旧 posterior candidate pairs，或使用另一套 sigma 重算 prediction distance，但仍生成形式完整的新 manifest。这会直接改变距离和分类，必须在 R 接口之前修复。

### [P1] 候选运行可误用旧 OUT，且非零返回码未参与完整性判定

入口在已存在的 `runs/real_N/` 中直接运行，既不拒绝非空目录，也不清除或隔离历史 OUT。运行后只依据文件“是否存在”决定是否构建 comparison，没有同时要求 `returncode == 0`。

审查时已用最小例子复现：目录中预先放入 8 个旧 OUT，runner 返回 1 且不写新文件，当前 `_run_candidate_dssat()` 仍返回 `missing_outputs=[]`。若继续构建，会把旧输出当成本次候选预测。

### [P1] `candidate_comparison.csv` 只写入每对的 A 解

当前代码在每个 pair 中只将 `comp_a` 追加到 `candidate_comparison.csv`。现有文件因此只包含 realization `4/9/2`，而候选集实际为 `4/16/9/20/2/32`。

距离内部计算使用了 A/B 两侧，所以现有距离值未受影响；但冻结输出无法支持后续重画两个候选解的预测对比，也不符合“候选解 canonical comparison 合并表”的契约。

### [P2] 没有在消费端限制最多 3 对/6 个唯一 realization

posterior 生成器默认最多 3 对，但 candidate 入口对 manifest 中的候选数没有二次门禁，可被一份哈希自洽但规模更大的 CSV 触发任意多次 DSSAT 运行，超出 T4.2 的批准范围。

另外，`int(value)` / `int(float(value))` 会将 `4.5` 静默变成 `4`。审查复现中，`4.5/9.9` 被解析为 realization `4/9`，应改为严格的非负整数校验。

### [P2] 执行元数据尚未完全冻结

- runner 硬编码 `TM0008`，而底层已支持从 frozen FileX 推断 cultivar；
- `harvest_var` 可由 CLI 任意改变，未与 S4 manifest 中的 `CHPDT` 比对；
- sigma 校验要求 `model_sigma` 和 `sigma_floor` 各自严格大于 0，而项目共享 observation-policy 语义允许它们为 0；应要求基础 `sigma > 0`、附加分量 `>= 0`，且最终 `sigma_eff` 有限且为正；
- candidate run manifest 的 `command` 只记录抽象文字，没有保存实际 argv；其 `parameter_csv` 在 Windows 下仍为反斜杠路径，与顶层 manifest 的 POSIX 路径规则不一致。

这些不影响当前 xxql2501/TM0008 demo，但会降低下一数据包的可迁移性与审计可读性。

## 3. 下一阶段：T4.2.1 最小契约收口

### A. 纯代码和负向测试（不运行 DSSAT）

1. 从 S4 `run_manifest.yaml` 解析 observation policy 和 `harvest_var`；如保留 CLI 参数，则必须验证路径内容哈希与 S4 冻结哈希相等。sigma 分量校验与共享 observation-policy 语义保持一致。
2. 将 posterior manifest 记录的 finalize/artifact-manifest 哈希与当前 S4 强制比对；不一致时在任何模型调用前失败。
3. 严格验证 candidate-pair schema：`1–3` 对、`1–6` 个唯一 realization、严格非负整数、A/B 不自配对、pair id 唯一。
4. 对非空 `out_dir` 直接拒绝，不引入 `--force`。每个候选目录必须是本次新建，不复用历史 OUT。
5. 候选只有在 `returncode == 0` 且所有必需 OUT 都由本次生成时才能构建 comparison；异常/非零返回码需保留简明诊断并将相关 pair 标记为 `prediction_incomplete`。
6. `candidate_comparison.csv` 同时写入 A/B 两侧，增加 `candidate_side` 字段，并保留 `pair_id` 和 `realization`。
7. 去掉 `TM0008` 硬编码，让现有 runner 从 frozen FileX 推断；在 run manifest 中记录可复现的实际 argv，所有相对路径统一为 POSIX 格式。

必须新增与上述 7 项一一对应的负向/回归测试，特别要覆盖“非零返回码 + 预存旧 OUT”、“改变 policy 但哈希自洽”、“posterior 上游哈希过期”和“comparison 包含 A/B 两侧”。

### B. 静态验收与提交

- 运行 `python -m pytest tests` 和 `python -m compileall src tests`；
- 不降低当前 `211 passed, 2 skipped` 基线；
- 先单独提交代码和测试，工作树干净后提交 code review；
- 本阶段不运行 DSSAT，不改文章图表，不修改历史 T4.2-B 目录。

### C. 通过 code review 后的受控重放

只有 A/B 通过审查后，才允许在新目录 `t4_candidate_predictions_v2/` 完成最多 6 次确定性 DSSAT 重放。不得覆盖当前 `t4_candidate_predictions/`。重放验收需再次核对：

- 6 份参数与 final ensemble 对应行一致；
- 6/6 返回码为 0 且 OUT 时间/哈希属于本次运行；
- A/B comparison 共覆盖 6 个 realization；
- 距离分量可独立复算，标签仍只能为 `tooling_demo`；
- 全部输入、运行和输出 manifest 哈希逐项通过。

## 4. T4.2.1 后的候选阶段

T4.2.1 通过后再安排 T4.3：让 R 只消费冻结、哈希校验的 posterior/candidate bundle，为 Fig. 5 和 Fig. S5–S7 建立 `DEMO_` 图表核心与版式 QA。届时仍不改变 registry 的 `pending_P4` 科学状态，不使用“已证明功能异参同效”的表述，也不引入 PCA/VIF/聚类/t-SNE 平台。

## 5. 停止条件

任一上游哈希不一致、非空目录被尝试复用、候选超出 6 个、任一候选返回码非零、A/B 行不能一对一对齐，或全套测试退化时，停止在 T4.2.1，不进入 R 图表开发。
