# P2-MVP T4.2.1-A/C code review 与 T4.2.1-B 交接（2026-07-19）

> 实施状态：**T4.2.1-B 已完成**。代码提交 `10d3498`；候选模块 `26 passed`，全套 `225 passed, 2 skipped`，compileall 通过。本轮未运行 DSSAT，`_v2` 继续作为已复核的 `tooling_demo` 数据。实施记录见 [T4.2.1-B 实施记录](P2_MVP_T4_2_1_B_实施记录_20260719.md)。
>
> 审查对象：`3433c29`（T4.2.1-A）、`01585d5`（T4.2.1-C 审计）与 `t4_candidate_predictions_v2/`
> 历史结论：`_v2` demo 运行证据有效，但代码尚有 1 项 P1 冻结链缺口；先做 T4.2.1-B 最小补丁，不重复运行 DSSAT，暂不进入 T4.3。（现已解决）

## 1. 审查通过项

- S4-frozen observation policy 和 `harvest_var` 默认被正确使用，CLI 不一致覆盖会失败。
- 非空目录防复用和 `returncode == 0 AND 无 missing` 门禁已实现。
- candidate-pair 门禁能拒绝超过 3 对、小数 realization、自配对和重复 pair id。
- `candidate_comparison.csv` 已包含 A/B 两侧、全部 6 个 realization 和 `candidate_side`。
- runner 已去除 `TM0008` 硬编码；sigma 基础/附加分量语义与 observation policy 一致。
- 候选模块测试 `20 passed`；全套测试 `219 passed, 2 skipped`；compileall 通过。

## 2. `_v2` 运行证据独立复核

审查期间协作者已在新目录完成 6 次确定性复跑。本次 code review 将其纳入核对，未再启动 DSSAT。

- 17 个顶层 artifacts、6 个 candidate run manifest 及其 48 个 OUT 哈希全部匹配。
- 9 个上游哈希均与当前 S4/posterior/input/batch/policy/split 匹配。
- posterior manifest 实际包含 finalize/artifact-manifest 两个必需哈希，且值正确。
- 6 份参数 CSV 与 final ensemble 对应行逐值一致。
- 6/6 `returncode=0`，无 missing outputs；manifest 记录 `git_commit=3433c29`、`git_dirty=false`。
- comparison 共 2400 行，`sides={A,B}`，realization 为 `2/4/9/16/20/32`。
- 独立重新解析 OUT 与计算距离后，三对结果为 `0.1345080716 / 0.0155688279 / 0.0225499894`，与冻结 CSV 一致。

因此，下述代码缺口不会推翻 `_v2` 当前数值；它影响的是将来对缺失字段的恶化/损坏 manifest 是否能 fail closed。

## 3. code review 发现

### [P1] posterior 上游哈希字段缺失时被放行

当前条件为 `if expected and expected != actual`，只会拒绝“存在但不一致”的哈希，不会拒绝缺失或空值。

审查负向复现：删除 posterior manifest 的 `calibration_finalize_sha256` 和 `calibration_artifacts_manifest_sha256` 后，入口仍成功写出 bundle，并调用了 2 次注入 runner。这与“posterior 必须强制绑定当前 S4”相冲突，是 T4.3 前的阻塞项。

### [P2] 命令与失败诊断的审计表达尚不完整

- run manifest 的 `argv` 只记录模型参数，不包含实际 subprocess 使用的 Python 可执行文件和 runner 脚本路径；记录值与实际 command 由两段代码分别构建。
- 默认 runner 失败时写 `_runner_stderr.txt`，但 candidate run manifest 中的 `diagnostics` 仍为空，stderr 文件也未记录哈希。
- 全部候选失败时，header-only `candidate_comparison.csv` 仍使用旧列集，缺少 `candidate_side`。

这三项不影响已全部成功的 `_v2`，但适合与 P1 一起用小补丁收口，不应扩展为新框架。

## 4. 下一阶段：T4.2.1-B 最小补丁

本阶段只修改候选预测入口及对应测试，**不运行 DSSAT，不生成 `_v3`，不覆盖 `_v2`**。

1. 要求 posterior 两个上游哈希必须存在、为 64 位十六进制字符串且与当前 S4 相等；缺失、空值、格式错误或值不一致均必须在零 runner 调用时失败。
2. 校验 posterior `candidate_pair_count` 与 candidate-pair CSV 行数一致。
3. 将实际 command 集中为单一构建函数，供执行和 manifest 共用；或将现有 `argv` 准确改名为 `model_args`。
4. 非零返码至少记录非空的返回码诊断；如保留 stderr 文件，在 manifest 中记录其相对路径和 SHA-256。
5. 空 comparison 使用与正常输出一致的最小 schema，包含 `candidate_side`。

必须新增对应负向测试，并运行：

```powershell
python -m pytest tests/test_candidate_predictions.py
python -m pytest tests
python -m compileall -q src tests
```

完成标准：全套不低于 `219 passed, 2 skipped`，工作树干净，单独提交后暂停 code review。

## 5. T4.2.1-B 之后

若 B 的修改不改变 comparison 或 prediction-distance 定义，则无需再跑 6 次 DSSAT：保留已通过独立复核的 `_v2` 作为 `tooling_demo` 数据，下一轮再批准 T4.3 的 R `DEMO_` 图表数据接入。

如 B 意外改变距离公式、comparison 行对齐或候选参数来源，则停止并重新评审，不自动开启新的真实复跑。
