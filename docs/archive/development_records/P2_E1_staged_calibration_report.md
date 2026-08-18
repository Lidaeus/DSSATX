# P2 E1 分阶段率定结果报告

> 任务ID：P2-E1（分阶段率定 S1–S3）
> 结论：**S1、S2、S3 全部因边界堆积失败**。5/6 stage-active 参数撞到 bounds 边界，IES 集合坍缩到单点。R0.6 自动质量门正确拦截。根因是 v3 bounds（保留自 V14 设计）对当前观测/权重组合过紧。建议 widening bounds 后重试。
> 标注：`engineering_preflight`，全部 `failed_quality`。
> 更新日期：2026-07-17

## 1. S1 物候/冠层（EM-FL, TRIFL, 40 reals, 3 iter）

| 参数 | init | bounds | 最终值 | 边界 |
|---|---|---|---|---|
| EM-FL | 23.3 | [23.0, 31.0] | **23.0** | ❌ lower |
| TRIFL | 0.64 | [0.2, 0.85] | **0.85** | ❌ upper |

Phi: 74584 → 72148（第 1 轮后 std=0，集合坍缩）。质量门失败：`ies_simulation_variation=0`, `ies_phi_finite=156/160`。

## 2. S2 氮响应/营养生长（NSTFAC, RTNO3, NMOBMX, NVSMOB, 60 reals, 4 iter）

| 参数 | init | bounds | 最终值 | 边界 |
|---|---|---|---|---|
| NSTFAC | 0.51 | [0.3, 0.85] | **0.85** | ❌ upper |
| RTNO3 | 0.012 | [0.008, 0.05] | **0.050** | ❌ upper |
| NVSMOB | 0.38 | [0.2, 0.5] | **0.200** | ❌ lower |
| NMOBMX | 0.099 | [0.08, 0.40] | 0.113 | ✅ interior |

Phi: 75069 → 74059（std 收敛到 7.3）。质量门失败：`ies_phi_finite=279/453`（极端边界处 DSSAT 数值失败）。

## 3. S3 结实与采收（XFRT, XFINT, 60 reals, 4 iter）

| 参数 | init | bounds | 最终值 | 边界 |
|---|---|---|---|---|
| XFRT | 0.99 | [0.73, 0.99] | **0.990** | ❌ upper |
| XFINT | 0.348 | [0.12, 0.50] | **0.500** | ❌ upper |

Phi: 75160 → 72637（第 1 轮后 std=0）。质量门失败：`ies_simulation_variation=0`, `ies_phi_finite=285/300`。

## 4. 根因分析

**系统性边界堆积**：3 个阶段中 6 个参数有 5 个撞到边界。这不是随机噪声——IES 一致地将参数推向当前 bounds 之外。

可能原因：
1. **bounds 过紧**：v3 bounds 保留自 V14 设计的保守范围，数据要求更极端的值。
2. **sigma 过大**：`assumption_based_sigma_v1` 的假设型 sigma 可能降低了观测对参数的约束力，使 IES 过度自由。
3. **观测-参数耦合不足**：单参数阶段下，其他参数固定在 init，可能人为限制了 DSSAT 的响应空间。

## 5. 建议（需用户审批）

1. **Widen bounds**：为 5 个边界堆积参数放宽 bounds（特别是 RTNO3 上限、XFRT 上限、EM-FL 下限），但必须在 PHYSICAL_BOUNDS 内。
2. **或重新审视 sigma**：如果 sigma 过大是主因，收紧 sigma 可能在不改 bounds 的情况下解决。
3. **S4 取消**：由于 S1-S3 全部失败，S4 联合率定不具备前置条件。

## 6. 门禁验证

R0.6 自动质量门在所有 3 个阶段正确触发 `failed_quality`，阻止了后验与论文导出。这验证了门禁的有效性——边界堆积和集合坍缩不会被静默接受。
