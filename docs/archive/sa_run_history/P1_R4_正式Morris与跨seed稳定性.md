# P1-R4 正式 Morris 与跨 seed 稳定性报告

> 状态：正式 Morris 已完成；跨 seed 稳定性通过；16参数 Top-K 已于后续轮次批准
> 日期：2026-07-16
> 正式运行根目录：`workspace/runs/p1_morris_formal_v3_20260716/`
> 运行源码提交：`b214e1c`

## 1. 结论

本轮完成了三个独立 `r=30, p=6` Morris 案例。seed `20260812` 和 `20260826` 全部通过进程、模型、轨迹、elementary effect 和逐响应非退化门禁；seed `20260729` 因 1740 个设计点中 1 个发生可重复的 DSSAT 模型失败而被整 seed 排除，不参与排名。

两个有效 seed 的总体排名 Spearman 为 `0.9962337662`，Top-15 Jaccard 为 `0.875`，分别高于预声明阈值 `0.90` 和 `0.80`。因此自适应 Morris 预算在当前 seed 数停止，不启动第4/5个 seed。

跨 seed Top-15 交集包含14个稳定核心参数；第15名边界在 `FL-SD` 与 `RTNH4` 之间变化。系统据此生成16参数的保守并集提案；该提案已在后续轮次批准并固化为 `eggplant_p1_sobol_top16_20260716`。本报告本身不改变冻结边界，后续工程验证见 [P1-R5 Sobol预检报告](P1_R5_Sobol工程预检与正式预算.md)。

## 2. 固定设计与可追溯性

三个案例均使用相同的正式契约：

- 冻结边界：`eggplant_p1_xxql2501_v3_20260716`，57个 active 参数；
- 输入包：`xxql2501_20260716`，10个处理；
- 输出 profile：`eggplant_p1_all_treatments_v3`，230项响应；
- Morris 规模：每个 seed 30条轨迹，理论设计点 `30 × (57 + 1) = 1740`；
- 源码：从干净提交 `b214e1c` 构建，三个案例不得混用后续工作区代码；
- frozen CSV SHA-256：`6b7e31248c7eb1aca173209bf9f8c5c2f86822be55ac4915e60803e58000674a`；
- output profile SHA-256：`46e8e539b3cfdf08dc2e747927b12adb9aab8e442b000a2e34d2798ee67e8ebd`；
- input manifest SHA-256：`5b7deac1502a5005cb46a1c2767a11d0567e13c094544f2faef3b9fdb950cb1b`。

## 3. 单 seed 质量门结果

| seed | 设计点成功 | 完整轨迹 | 有效 effects | 230项响应 | 科研状态 | 排名用途 |
|---:|---:|---:|---:|---|---|---|
| 20260729 | 1739/1740 | 29/30 | 1708/1710 | 有限且非退化 | failed | 整 seed 排除 |
| 20260812 | 1740/1740 | 30/30 | 1710/1710 | 全部通过 | validated | 纳入 |
| 20260826 | 1740/1740 | 30/30 | 1710/1710 | 全部通过 | validated | 纳入 |

少量失败不会让所有 Morris 结果失去价值，但会破坏该轨迹上后续 elementary effects 的可比性。因为正式门禁预先规定30条轨迹必须完整，不能在看到结果后放宽到29条，所以失败 seed 仅用于诊断，不能与完整 seed 混合排名。替换 seed `20260826` 独立生成并完整通过，避免了选择性删除失败点或用部分轨迹补齐结果。

两次首批运行在外层 controller 超时后，PEST++ manager 和 worker 继续正常完成；`.rns` 已在正常完成时被 PEST++ 清理，因此恢复命令被安全拒绝。新增的离线 finalize 只在 manager 已停止、全部设计点终态、`.mio` 存在、PEST++ 有完成标记且无 runtime/unknown failure 时重建父级状态，不重跑任何模型，并保留原 controller 错误用于审计。

## 4. seed 20260729 单点失败复盘

失败点是 run 38、trajectory 0、step 38，对应本步变化参数 `SLAVR`。相邻证据为：

- run 37：`SLAVR=270`，成功；
- run 38：`SLAVR=300, SLAREF=260, TB1=11.2, XMAGE=10, XFINT=0.12`，失败；
- run 39：保持 `SLAVR=300`，仅将 `TB1` 从11.2变为8.8，成功。

DSSAT 退出码为73，错误包含 floating divide by zero 与 `__libm_logf_e7`。按处理重放确认 TN2、TN3、TN14 失败，其余7个处理成功。因此这是特定处理状态与边界参数组合的交互失效，不支持把 `SLAVR=300` 单独判为非法，也不足以单方面收紧 v3 边界。

该证据说明 v3 域并非数学意义上的处处可行。后续 Sobol/IES 必须继续记录失败候选和参数关联；只有积累到跨 seed、跨方法的稳定失败区域后，才提出新的边界 proposal 并单独审批。

## 5. 跨 seed 排名方法与稳定性

排名遵循启动计划中的预声明方法：先在每个响应内把各参数 `mu*` 归一化为相对贡献，再对同一特征族的处理/DAP等权平均，随后在特征族内汇总，最后对物候、冠层、生物量、产量/采收四个过程组等权平均。该方法避免直接平均不同量纲响应的 `mu*`，也避免响应数量多的过程组自动获得更高权重。

有效 seed 的稳定性为：

| 指标 | 结果 | 阈值 | 判定 |
|---|---:|---:|---|
| 总体 Spearman | 0.9962337662 | ≥ 0.90 | 通过 |
| Top-15 Jaccard | 0.875 | ≥ 0.80 | 通过 |

共识排名前16位为：

| 共识名次 | 参数 | 选择类别 |
|---:|---|---|
| 1 | TRIFL | stable_core |
| 2 | XFRT | stable_core |
| 3 | TB2 | stable_core |
| 4 | RTNO3 | stable_core |
| 5 | FRLFF | stable_core |
| 6 | LFMAX | stable_core |
| 7 | EM-FL | stable_core |
| 8 | XFINT | stable_core |
| 9 | TO12 | stable_core |
| 10 | TO22 | stable_core |
| 11 | PM06 | stable_core |
| 12 | FRSTMF | stable_core |
| 13 | TM2 | stable_core |
| 14 | NMOBMX | stable_core |
| 15 | FL-SD | top_k_boundary_union |
| 16 | RTNH4 | top_k_boundary_union |

`FL-SD` 在 seed `20260812` 排第15、在 `20260826` 排第16；`RTNH4` 分别排第17和第15。因二者都位于人为设定的 Top-15 截断边界，本轮不依据一次名次差异武断淘汰其中一个。

## 6. 下一审批点

Sobol候选已按推荐采用16参数保守并集：14个稳定核心加 `FL-SD`、`RTNH4` 两个边界参数，避免Morris单名次截断造成假阴性。正式样本规模和收敛规则仍需在P1-R5审批后执行。

## 7. 关键产物与哈希

跨 seed 产物目录：`workspace/runs/p1_morris_formal_v3_20260716/stability_seed_20260812_20260826/`

| 产物 | SHA-256 |
|---|---|
| `morris_multiseed_stability.json` | `65e34ebedf28e4d4cd45435f72a5f0dd00084a21cc2a6c003c3525bed191e42c` |
| `morris_consensus_ranking.csv` | `fc2384c05952ef356f9d056c1ce66547a9c09102d7e096825da065750a56e9e3` |
| `morris_topk_proposal.csv` | `06034e916d42984ff7148a899606a3c88d61ee48da55d81bdf705504f9d3ec51` |
| `morris_topk_proposal.json` | `9b6bc96ee883a4b15d12dc3cef2c9610caae5a28da5b05371d4532918d138a7e` |
| seed 20260729 `.mio` | `d98ca7b248090f1db3a6c6e955366b52f4d12d8f93baecfd3f34c5632da82c08` |
| seed 20260812 `.mio` | `8812c6854701fbec7122532deb33c0868b41cf134187cc4603100d303324f4c5` |
| seed 20260826 `.mio` | `31443fef69f607dbe1e165f085c4d074ee394d1b137a9aa10d67f586034762d7` |
| run 38 处理重放报告 | `26974b327c7e42982b1de6168cd750a31b3b576fb3f89091f4fc6295cf740579` |

每个案例的 `run_manifest.yaml`、`run_status.json`、`morris_audit/` 和 `.mio` 共同组成证据链；仅凭汇总表不得重建或替代原始审计产物。
