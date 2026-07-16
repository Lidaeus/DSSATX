# P1-R3：Morris 可行性预检与响应契约修复

> 状态：预检通过；v3 边界可提交冻结审批；不得使用本报告生成正式参数排名
> 日期：2026-07-16

## 结论

`eggplant_p1_xxql2501_v3_candidate_20260716` 在新输入包、57 个活跃参数和独立 `r=8` Morris 设计下完成 464/464 个设计点，零模型失败、零运行时失败、8/8 条轨迹完整。响应契约修复后，230/230 项均具有至少一个非零 Morris 效应，最终 `scientific_status=validated`。

该证据支持把 v3 proposal 提交用户审批并冻结。它不提供正式参数排序，也不自动批准两个 `r=30` 正式 seed、Top-K、Sobol 或率定。

## 两轮预检及门禁发现

### 第一轮：参数域通过，响应契约失败

- `run_id`：`p1_morris_preflight_v3_20260716_seed_20261017`
- 来源提交：`cb6b6391f389330ab58d5749371a3bcda26ca825`
- 设计：57 参数、240 响应、`r=8`、`p=6`、seed `20261017`
- 运行：464/464 成功，8/8 完整轨迹，456/456 有效 elementary effects
- 响应审计：13,680 个 `.mio` 汇总值有限，但20项响应全域退化

退化项为全部10个处理的 `LAIXM` 和 `FRUITD_DAP045`。检查 DSSAT `Evaluate.OUT` 后确认：

- `LAIXM` 中 `M` 表示 measured，旧代码错误地把 FileA 观测值当成模型响应；模拟字段应为 `LAIXS`；
- `FRUITD_DAP045` 在本候选域和全部处理下结构性为0，不含参数筛选信息；
- LAI 的 DAP45 仍有变化且与 FileT 早期观测对齐，应保留。

因此第一轮只能证明 v3 参数域未触发运行失败，不能证明旧240项响应契约可用于正式分析。新增逐响应非退化门禁后，该轮的 `morris_result_quality.json` 正确返回 `fail`。

## 修复内容

1. SA 最大 LAI 响应由实测 `LAIXM` 修正为模拟 `LAIXS`；
2. 输出契约允许 LAI 和果实使用不同过程时间点；
3. 保留 LAI DAP45/67/95/119，果实改为 DAP67/95/119；
4. profile 升级为 `eggplant_p1_all_treatments_v3`，响应数由240收敛为230；
5. 并行运行完成后同时生成轨迹质量和结果质量报告；任何声明响应全零都会使科研状态失败。

## 第二轮：修复后通过

- `run_id`：`p1_morris_preflight_v3_outputs_v3_20260716_seed_20261031`
- 来源提交：`1cc4199bfbf9ab91c5ef98b1a72f9dafca1aacd9`
- `run_type`：`sensitivity_preflight_case`
- 输入包：`xxql2501_20260716`
- 边界 SHA-256：`6b7e31248c7eb1aca173209bf9f8c5c2f86822be55ac4915e60803e58000674a`
- 输出 profile SHA-256：`afbed5794c037578c72811b71dc911cc34c9c9dac0a699d940446e4db26be5a5`
- 输入 manifest SHA-256：`5b7deac1502a5005cb46a1c2767a11d0567e13c094544f2faef3b9fdb950cb1b`

| 门禁 | 结果 |
|---|---:|
| 设计点成功 | 464/464 |
| 模型/运行时/未知失败 | 0/0/0 |
| 完整且有效轨迹 | 8/8 |
| 有效/无效 elementary effects | 456/0 |
| 每参数最少有效 effects | 8 |
| `.mio` 汇总值有限 | 13,110/13,110 |
| 非零汇总值 | 8,401 |
| 退化响应 | 0/230 |
| 科研状态 | `validated` |

关键证据 SHA-256：

- `run_manifest.yaml`：`f75522a94b5e5de9522bbcc646dd2d3871a32ccca3d3da59b5c4efda4fd84155`
- `morris_run_audit.json`：`c231a1194951f61292fbdc845a301836002954a5e67736484214b5b51f9d77c7`
- `morris_run_quality.json`：`1ebc65b23ddb90735ce79058c6a02fdb8af5430e73be49cbbcf09f026dd7cac0`
- `morris_result_quality.json`：`14851172590393ca8d70d5fe9c0906ef072b07d51fabbe4df847a138ae305760`
- `sa_sen_morris.mio`：`d7afc1193812c8145140fe9f4a0297b1edc48b6b335d94bb14baed434fcc671d`

## 下一审批点

请用户审核并批准：

1. 将 v3 candidate 冻结为正式 bounds ID；
2. 将10 TN/230响应的 `eggplant_p1_all_treatments_v3` 作为 P1 正式契约；
3. 批准从新 seed 开始执行两个独立 `r=30` 正式 Morris 案例。

正式运行必须在批准后的 frozen CSV 上重新构建；不得直接把 proposal 或本次预检 `.mio` 用于参数排名。

## 证据位置

- 第一轮：`workspace/runs/p1_morris_preflight_v3_20260716_seed_20261017/`
- 第二轮：`workspace/runs/p1_morris_preflight_v3_outputs_v3_20260716_seed_20261031/`
- 失败历史复盘：[P1 运行失败原因排查复盘](P1_运行失败原因排查复盘.md)
- TN/MF 归因：[P1-R2 TN2 失效归因](P1_R2_TN2_factor_attribution.md)
