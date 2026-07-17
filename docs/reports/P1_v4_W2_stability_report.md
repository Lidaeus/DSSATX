# P1 v4 — W2 正式多种子 Morris 与双域稳定性报告

> 任务ID：W2（正式多种子 Morris 与双域稳定性）
> 结论：**通过**。两个预声明 seed（20261007, 20261021）均 1740/1740 成功，双域 Spearman 0.997 / 0.997，Top-15 Jaccard 1.00 / 1.00，远超收敛阈值（0.90 / 0.80）。`science_validated=True`，`decision=stop_at_current_seed_count`。
> 标注：`science_validated`（排名可用于论文，但需 W3 Top-K 审批后确定最终参数集）。
> 运行日期：2026-07-17

## 1. 执行汇总

| 指标 | Seed 20261007 | Seed 20261021 |
|---|---|---|
| 设计点 | 1740/1740 | 1740/1740 |
| 模型失败 | 0 | 0 |
| 运行时失败 | 0 | 0 |
| 完整轨迹 | 30/30 | 30/30 |
| 每参数有效 elementary effects | 30 | 30 |
| 退化响应 | 0 | 0 |
| science_validated | ✅ | ✅ |

| 指标 | Seed 20260923（排除） |
|---|---|
| 设计点 | 1734/1740（6 次 DSSAT 失败） |
| 完整轨迹 | 29/30（轨迹 19 不稳定） |
| 排除原因 | formal_quality_gate_failed |
| 不稳定区域 | 低氮吸收组合（低 RTNO3/RTNH4/NMOBMX/NVSMOB + 高 LFMAX + 低 KCAN）；6 次连续失败分布在轨迹 19 的第 13–22 步，共享同一不稳定基底 |

## 2. 双域稳定性

| 排名域 | Spearman | Top-15 Jaccard | 稳定核心 | 边界并集 | 稳定 |
|---|---|---|---|---|---|
| general_genetic | **0.9973** | **1.00** | 15 | 15 | ✅ |
| water_nitrogen_response | **0.9966** | **1.00** | 15 | 15 | ✅ |

**两项排名域均远超 0.90 / 0.80 阈值，Top-15 在两个 seed 间完全一致。**

**决策：`stop_at_current_seed_count`** — 无需追加 seed 20261104 / 20261118。

## 3. 参数分类表（Top-15 每域，20 个独立参数）

### 两域共同重要（10 个）
`FRLFF` `LFMAX` `NMOBMX` `NVSMOB` `PM06` `RTNH4` `RTNO3` `TRIFL` `XFINT` `XFRT`

### 仅一般生长重要（5 个）
`EM-FL` `TB2` `TM2` `TO12` `TO22`

### 仅水氮响应重要（5 个）
`ATOP` `FRSTMF` `NSTFAC` `PORPT` `RWDTH`

### 低敏感/不稳定（37 个）
其余 37 个参数在两个域均未进入 Top-15。

## 4. 共识排名 Top-20（每域）

### general_genetic（按 mean_rank）

| rank | parameter | mean_score | 生物学含义 |
|---|---|---|---|
| 1 | RTNO3 | 0.233 | 根系氮吸收 |
| 2 | RTNH4 | 0.081 | 根系铵吸收 |
| 3 | TRIFL | 0.079 | 叶出现速率 |
| 4 | PM06 | 0.067 | 光合同化参数 |
| 5 | XFRT | 0.055 | 果实分配系数 |
| 6 | XFINT | 0.055 | 果实间隔 |
| 7 | LFMAX | 0.050 | 最大叶面积 |
| 8 | NMOBMX | 0.048 | 氮向果实迁移上限 |
| 9 | NVSMOB | 0.044 | 营养器官氮迁移 |
| 10 | TM2 | 0.035 | 温度响应 |
| 11 | TB2 | 0.034 | 基部温度 |
| 12 | TO12 | 0.034 | 最适温度 1 |
| 13 | TO22 | 0.034 | 最适温度 2 |
| 14 | FRLFF | 0.033 | 叶黄化 |
| 15 | EM-FL | 0.032 | 出苗到开花 |

### water_nitrogen_response（按 mean_rank）

| rank | parameter | mean_score | 生物学含义 |
|---|---|---|---|
| 1 | RTNO3 | 0.985 | 根系氮吸收 |
| 2 | RTNH4 | 0.228 | 根系铵吸收 |
| 3 | NSTFAC | 0.103 | 氮胁迫因子 |
| 4 | NMOBMX | 0.102 | 氮向果实迁移上限 |
| 5 | NVSMOB | 0.098 | 营养器官氮迁移 |
| 6 | ATOP | 0.086 | 顶端优势 |
| 7 | XFRT | 0.068 | 果实分配系数 |
| 8 | TRIFL | 0.061 | 叶出现速率 |
| 9 | PM06 | 0.056 | 光合同化参数 |
| 10 | FRLFF | 0.050 | 叶黄化 |
| 11 | PORPT | 0.049 | 孔隙度 |
| 12 | XFINT | 0.049 | 果实间隔 |
| 13 | FRSTMF | 0.048 | 茎衰老 |
| 14 | LFMAX | 0.048 | 最大叶面积 |
| 15 | RWDTH | 0.044 | 根宽 |

### 生物学一致性

- **RTNO3 在两个域均排第 1**，且在水氮响应域的效应量（0.985）远高于一般生长域（0.233）——符合氮吸收对水氮响应的支配性角色的生物学预期。
- 温度参数（TB2/TM2/TO12/TO22）仅在一半生长域高排，对水氮响应不敏感——逻辑正确。
- 水氮特有参数（NSTFAC、ATOP、PORPT、FRSTMF、RWDTH）均与胁迫响应或根系/冠层结构相关——生物学合理。

## 5. 排除的 Seed 20260923 不稳定区域诊断

轨迹 19 的 6 次 DSSAT 失败（第 13–22 步）共享同一参数基底：
- 极低氮吸收：`RTNO3=0.0164`，`RTNH4=0.05`（靠近 bounds 下限）
- 低氮迁移：`NMOBMX=0.336`，`NVSMOB=0.2`，`NSTFAC=0.52`
- 高 LFMAX=1.306，低 KCAN=0.462，`KC_SLOPE=0`

这个参数组合导致 DSSAT 在作物后期（高叶面积 × 低氮供应）数值发散。该不稳定区域落入 bounds 物理边界内但导致模型崩溃——**这不影响排名门禁，因为 formal 规则按计划不允许任何失败的 seed 进入排名**，但它是后续 bounds 细化的线索。

## 6. 产物

- `workspace/runs/p1_v4_formal_stability/morris_multiseed_stability.json`：完整稳定性结果
- `morris_seed_rankings.csv`：每 seed 每域排名
- `morris_seed_pairwise_stability.csv`：seed 间 Spearman/Jaccard
- `morris_consensus_ranking.csv`：双 seed 共识排名
- `morris_topk_proposal.csv`：Top-15 提案（每域 stable_core）
- 本报告：`docs/reports/P1_v4_W2_stability_report.md`

## 7. 下一步（W3 — 需用户审批）

W2 通过。按计划 §3 W3，下一步必须**暂停并提交用户审批**：

1. **Top-K 审批**：提交 20 个独立参数的分类表 + 每域共识排名证据。
2. **Sobol 决策点**：
   - Sobol 参数并集建议：20 个（两域共同 + 各域独有）
   - 失效风险：3 个 seed 中 1 个因 DSSAT 数值不稳定退出（6/1740 = 0.34% 失败率，局限于低氮极端区）
   - `N=4/8` 工程预检 → `N=64→128→必要时256` 正式预算
3. **审批后**：创建 v4 Sobol（与 v3 profile 哈希绑定分开），修复 `sobol_convergence` 已完成的按域排名分离。

## 8. 标注

`science_validated`。双域排名稳定、可复现，可用于 W3 审批材料。在用户审批 Top-K 参数集和 Sobol 预算前，不启动自动 Sobol 运行。
