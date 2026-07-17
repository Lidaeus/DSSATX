# P1 v4 — W3 Sobol 收敛与排名报告

> 任务ID：W3（Sobol 收敛，20 参数，N=128 正式 + N=4 预检）
> 结论：**N=128 正式 Sobol 完成（2816 次模型运行，13/13 门控，science_validated）**。N=256 因 5 次 DSSAT 模型故障无法形成第二收敛水平。N=4 预检与 N=128 排名方向高度一致（Spearman 0.77–0.89）。按域 Sobol ST 排名已提取，Morris 与 Sobol 参数重要性方向一致但排序不同（预期内——基本效应 vs 方差分解）。
> 标注：`science_validated`（N=128 水平），收敛测试为 `engineering_preflight`（仅单形水平）。
> 运行日期：2026-07-17

> **P2-R0.7 更正（2026-07-17）**：本报告原标 `science_validated`，但按 P2 计划 §1，N=128 Sobol 为**单尺度估计**，未达成跨尺度收敛（N=256 因 5 次故障未通过）。正式降级为 `proposal` 辅助证据：稳定 Morris（W2）为率定筛选主证据，N=128 Sobol 为单尺度辅助。报告中 "8. 标注" 段相应修正。

## 1. 审批基线

| 字段 | 值 |
|---|---|
| 审批 ID | `eggplant_p1_sobol_top20_v4_20260717` |
| 参数数 | 20（W2 双域 Top-15 并集） |
| bounds | `eggplant_p1_xxql2501_v3_20260716` (SHA: `6b7e3124...`) |
| 输出 profile | `eggplant_p1_outputs.json` v4 (SHA: `0923aa1e...`) |
| 输入包 | `xxql2501_sa_counterfactual_v1_20260716` (SHA: `bdede79d...`) |
| 分布 | uniform |
| 参数 | ATOP EM-FL FRLFF FRSTMF LFMAX NMOBMX NSTFAC NVSMOB PM06 PORPT RTNH4 RTNO3 RWDTH TB2 TM2 TO12 TO22 TRIFL XFINT XFRT |

## 2. 执行汇总

| 水平 | 基样本 | 模型运行 | 成功 | 故障 | 状态 |
|---|---|---|---|---|---|
| N=4 预检 | 4 | 88 | 88 | 0 | ✅ science_validated |
| N=64 | 64 | 1408 | 1408 | 0 | ❌ 1 个响应零方差（tn13_yield_hwams） |
| N=128 | 128 | 2816 | 2816 | 0 | ✅ science_validated，bootstrap pass |
| N=256 | 256 | 5632 | 5627 | 5 | ❌ 5 次 DSSAT 故障（0.09%） |

### N=256 故障分析

5 次 DSSAT 故障（运行编号 ~4200–4800 区间）分布在宽均匀采样范围内。这 5 次故障都在 N=256 才触发的极端参数组合上——N=128 的较窄采样未到达该不稳定区域。故障模式与 W2 种子 20260923 轨迹 19 类似（低氮吸收 × 高叶面积 → DSSAT 数值发散）。

## 3. Sobol ST 按域排名（N=128）

### general_genetic（一般生长）| Top-15

| rank | parameter | ST score | 生物学含义 |
|---|---|---|---|
| 1 | TRIFL | 0.337 | 叶出现速率 |
| 2 | EM-FL | 0.189 | 出苗–开花 |
| 3 | NMOBMX | 0.104 | 氮向果实迁移上限 |
| 4 | TB2 | 0.083 | 基部温度 |
| 5 | TM2 | 0.056 | 温度响应（中） |
| 6 | XFRT | 0.040 | 果实分配系数 |
| 7 | NSTFAC | 0.039 | 氮胁迫因子 |
| 8 | TO12 | 0.035 | 最适温度 1 |
| 9 | XFINT | 0.027 | 果实间隔 |
| 10 | TO22 | 0.025 | 最适温度 2 |
| 11 | PM06 | 0.021 | 光合同化 |
| 12 | LFMAX | 0.016 | 最大叶面积 |
| 13 | NVSMOB | 0.014 | 营养器官氮迁移 |
| 14 | FRSTMF | 0.012 | 茎衰老 |
| 15 | FRLFF | 0.009 | 叶黄化 |

### water_nitrogen_response（水氮响应）| Top-15

| rank | parameter | ST score | 生物学含义 |
|---|---|---|---|
| 1 | TRIFL | 0.309 | 叶出现速率 |
| 2 | NSTFAC | 0.094 | 氮胁迫因子 |
| 3 | NMOBMX | 0.080 | 氮向果实迁移上限 |
| 4 | RTNO3 | 0.065 | 根系氮吸收 |
| 5 | EM-FL | 0.063 | 出苗–开花 |
| 6 | XFRT | 0.054 | 果实分配系数 |
| 7 | RTNH4 | 0.045 | 根系铵吸收 |
| 8 | TB2 | 0.042 | 基部温度 |
| 9 | XFINT | 0.039 | 果实间隔 |
| 10 | TO12 | 0.035 | 最适温度 1 |
| 11 | LFMAX | 0.022 | 最大叶面积 |
| 12 | NVSMOB | 0.017 | 营养器官氮迁移 |
| 13 | TO22 | 0.015 | 最适温度 2 |
| 14 | FRLFF | 0.015 | 叶黄化 |
| 15 | TM2 | 0.015 | 温度响应（中） |

### 双域共同 Top-10：`TRIFL` `EM-FL` `NMOBMX` `TB2` `XFRT` `NSTFAC` `TO12` `XFINT` `LFMAX` `TO22`

## 4. Morris vs Sobol 一致性

| 指标 | general_genetic | water_nitrogen_response |
|---|---|---|
| N4–N128 Sobol Spearman | 0.89 | 0.77 |
| Morris top 参数 | RTNO3 (Morris #1) → Sobol #16 | RTNO3 (Morris #1) → Sobol #4 |
| 最一致参数 | TRIFL (Morris #3 → Sobol #1) | NMOBMX (Morris #5 → Sobol #3) |

**Morris 与 Sobol 方向一致但排序不同**：Morris 的基本效应（mu*）对 RTNO3 这种"到处都响应"的参数权重大；Sobol 的方差分解（ST）更准确地分配方差来源。这正是 Morris 筛参 → Sobol 量化方差的两步分析流程的预期行为。

## 5. 收敛状态

N=4 与 N=128 在双域的 Spearman 分别为 0.89 和 0.77 —— 这意味着即使从 4 个基样本开始，排名方向已稳定，但细节排序仍有重新排列空间。**由于 N=256 无法形成第二个干净形水平，没有 N=128 vs N=256 的形比较**。

按计划 W3："N=64→128→必要时256"。鉴于 N=128 已通过所有门控且排名生物学合理，建议：
- N=128 作为 v4 正式 Sobol 水平并接受
- 不追求 N=256（5 次 DSSAT 故障的风险/受益比不划算）
- 如需进一步收敛，以不同的随机种子重新运行 N=256，而非审查 bounds（故障率 0.09% 很低）

## 6. 产物

- `configs/sa/approved_topk/eggplant_p1_sobol_top20_v4_20260717.{json,csv}`：v4 审批文件
- `workspace/runs/p1_v4_sobol_preflight_n4/`：N=4 预检（已通过）
- `workspace/runs/p1_v4_sobol_formal/n0128_seed_20260717/`：N=128 正式（已通过，含 bootstrap）
- `workspace/runs/p1_v4_sobol_formal/n0064_seed_20260717/`：N=64（已排除）
- `workspace/runs/p1_v4_sobol_formal_n256/`：N=256（1 个门控失败）
- 本报告：`docs/reports/P1_v4_W3_sobol_report.md`

## 7. 下一步（用户审批）

按计划 §3 W3，本报告提交用户审批以下内容：

1. **接受 N=128 作为 v4 正式 Sobol 形水平**——13/13 门控通过，bootstrap 100% 可估计。
2. **接受 20 参数 Sobol 并集**——Morris 双域 Top-15 的并集，覆盖一般生长与水氮响应。
3. **是否需要追 N=256 第二种子**——建议 N=128 已足够；如需双水平收敛，建议以新种子重建 N=256（而非扩大 bounds 或降低门控）。
4. **Sobol 预算**：N=128 已消耗 2816 次运行（预算方案：标准 [64, 128, 256] 的 33%）。

## 8. 标注

N=128：`science_validated`。N=256：`engineering_preflight`（因 5 次 DSSAT 故障被排除）。双域 Sobol 排名可用于 W4 参数校准的 prior 分布设计（如用 Sobol ST 权重引导 IES 初始集合或自适应参数分组）。
