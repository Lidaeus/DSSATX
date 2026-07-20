# Morris v4 结果审查与 Sobol 参数选择

> 日期：2026-07-21  
> 状态：Morris 工程证据通过；Sobol 参数集已按用户本轮指令批准；结果仍为 `science_pending`。

## 1. 输入与运行边界

- 三季：XXQL2501、XXQL2502、XXQL2601。
- XXQL2601 的 TN12 已修正为 W1（`MI=1`），TN9 保持 W3。
- 参数边界：`eggplant_formal_multiseason_candidate_v4_20260721`。
- `EM-V1` 使用经确定性前向检查确认的有效域：初值 39.3，范围 38–40。
- 每季均使用两个预注册排名域：`general_genetic` 与 `water_nitrogen_response`。

## 2. Morris 完整性与稳定性

三季 r=10、3 seeds 的 9 个案例均完成，正式完整性审计未发现模型失败、运行时失败、缺失设计点或无效 elementary effect。

| 季次 | r | 最小 Spearman | Top-15 最小 Jaccard | 结论 |
|---|---:|---:|---:|---|
| XXQL2501 | 10 | 0.977 | 0.875 | 通过 |
| XXQL2502 | 10 | 0.895 | 0.667 | 扩展 |
| XXQL2601 | 10 | 0.957 | 0.875 | 通过 |
| XXQL2502 | 20 | 0.931 | 0.579 | 全局排序通过；水氮域 Top-15 边界互换 |

XXQL2502 r=20 的一般遗传域通过（Spearman 0.990，Jaccard 0.875）。水氮响应域的前 11 个参数形成稳定核心，但第 12–20 名分数较低且相近，导致硬 Top-15 集合随 seed 互换。继续增加单个 seed 无法改变已有最小两两 Jaccard；盲目提升到 r=30 也不保证消除由近似并列造成的集合跳变。因此本轮不把 Top-15 Jaccard 失败误写成全局排序失败，而对该域使用各 seed Top-15 的保守并集，降低错误排除潜在交互参数的风险。

## 3. Sobol 选择规则

在三季 × 两排名域共 6 个列表中：

1. 参数进入 Top-15（XXQL2502 不稳定水氮域使用各 seed Top-15 并集）至少 2 次时入选；
2. 仅出现 1 次、但任一域标准化 Morris 平均分不低于 0.02 时，作为季节特异保护项入选；
3. 其他参数固定在 v4 初值，不进入本轮 Sobol 维度；
4. 该规则用于筛选覆盖，不代表未入选参数的生物学效应严格为零。

最终选择 23 个参数：

`RTNO3, TRIFL, XFRT, LFMAX, XFINT, FRLFF, PM06, RTNH4, NMOBMX, EM-V1, EM-FL, TB2, TO11, FRSTMF, NVSMOB, FL-SD, PORPT, TO12, ATOP, NSTFAC, TB1, TO22, TM2`

其中 `TO22` 和 `TM2` 为季节特异保护项；其余 21 个为跨域重复出现项。基数/最适/上限温度参数中 `TB1, TB2, TO11, TO12, TO22, TM2` 得以保留，支持后续跨春秋季温度响应分解。

机器可读文件：

- `configs/sa/approved_topk/eggplant_formal_sobol_top23_v1_20260721.csv`
- 同目录下分别绑定 XXQL2501、XXQL2502、XXQL2601 输入哈希和输出契约的三个 JSON 审批文件。

## 4. Sobol 执行顺序

1. 三季分别运行 N=16 preflight，要求设计点齐全、失败为 0、响应有限且不含 DSSAT `-99`；
2. preflight 通过后构建正式 N=64；
3. 按 N=64 → 128 → 256 检查 S1/ST 排名、Top-8 集合和置信区间收敛；
4. 仅在上一层未收敛时执行下一层，避免预先运行无必要的大样本。

Sobol 参数服从冻结范围内均匀分布。Morris 与 Sobol 均属于敏感性分析证据，不能单独授权率定结果或 `science_validated`。
