# E02 joint62 + PlantN + SLPF 150×5 结果分析

## 技术摘要

运行目录：`workspace/runs/e02_joint62_m1_offsets_plantn_slpf_150x5_20260729_v6`。

- 工程门：通过；PEST++ 管理器退出码 0，150 个先验成员、5 次 IES 更新，最终 150 个成员全部保留，非有限模拟观测比例为 0。
- 末轮最小 `actual Phi`：**190.926**，成员 **82**；末轮均值 209.169，较初始均值 3036.380 明显下降。
- 拟合不是均匀改善：25FA 的累积干重拟合较好，但叶/茎干重和 SNAM/LNAM 仍明显偏低；25SP 的器官生物量尚可，收获过程 HPODW 和 LAIX 仍较差。
- `SOIL_SLPF` 后验集中在高值区（q05=0.941、median=0.981、q95=0.991），没有触及下界 0.65；当前证据不支持继续降低综合肥力指数来改善拟合。

## 最优成员的原尺度拟合能力

指标由末轮最小 Phi 成员 82 计算；对 `log(y+1)` 目标先反变换。RRMSE = RMSE / 实测绝对均值，NSE 为 Nash–Sutcliffe efficiency，R² 为相关系数平方。

| 季节 | 目标 | n | RRMSE | NSE | R² | 偏差（模拟−实测） |
|---|---:|---:|---:|---:|---:|---:|
| 25SP | CHPDT | 110 | 32.79% | 0.699 | 0.758 | −289.6 |
| 25SP | HPODW | 110 | 62.47% | −0.827 | 0.140 | −57.8 |
| 25SP | LAID | 40 | 61.45% | 0.161 | 0.816 | +0.76 |
| 25SP | LWAD | 40 | 32.82% | 0.732 | 0.801 | −11.9 |
| 25SP | SWAD | 40 | 50.40% | 0.570 | 0.832 | +304.5 |
| 25SP | CHTD | 40 | 46.34% | −0.017 | 0.949 | −0.23 m |
| 25SP | SNAM | 9 | 24.92% | −0.308 | 0.546 | +8.0 |
| 25SP | LNAM | 9 | 27.71% | −1.330 | 0.509 | +8.8 |
| 25SP | ADAP | 10 | 61.76% | — | — | −21 d |
| 25FA | CHPDT | 36 | 15.11% | 0.857 | 0.903 | +81.6 |
| 25FA | HPODW | 36 | 18.77% | 0.060 | 0.187 | +23.9 |
| 25FA | LAID | 36 | 29.71% | 0.559 | 0.886 | −0.42 |
| 25FA | LWAD | 36 | 87.24% | −0.921 | 0.882 | −669.9 |
| 25FA | SWAD | 36 | 59.48% | −0.014 | 0.936 | −436.4 |
| 25FA | CHTD | 36 | 34.96% | −0.229 | 0.919 | +0.25 m |
| 25FA | SNAM | 12 | 42.79% | −7.328 | 0.002 | −9.6 |
| 25FA | LNAM | 12 | 72.33% | −16.553 | 0.025 | −31.8 |
| 25FA | ADAP | 12 | 39.29% | — | — | −11 d |

PDAP is exact by construction. Soil-water observations are retained in Phi but are not included in the table above because they are pointwise states rather than crop-response indicators.

## 主要误差来源

按最优成员的加权 Phi 贡献，25FA 的最大误差来自 LWAD、SWAD、LNAM 和 CHTD；25SP 的最大误差来自 CHTD、SWAD、HPODW 和 ADAP。也就是说，当前总 Phi 已下降，但剩余误差主要是器官生物量/氮质量和物候—冠层结构的系统偏差，而不是收获干重序列本身。

## 末轮参数后验与触边

触边比例按距离边界 1% 范围计算。高触边参数如下：

| 参数 | 边界 | 后验中位数 | 触边比例 | 方向 |
|---|---:|---:|---:|---|
| RHGHT | 0.50–2.20 | 0.501 | 97.3% | 下界 |
| PODUR | 18–60 | 18.000 | 92.0% | 下界 |
| DXFRT_AUT | −0.35–0.35 | −0.350 | 88.0% | 下界 |
| RTNH4 | 0.005–0.05 | 0.005 | 80.7% | 下界 |
| TB3 | 6–13 | 13.000 | 78.0% | 上界 |
| VSSINK | 1.5–8.0 | 1.528 | 72.7% | 下界 |
| SLAVR | 240–310 | 310.000 | 71.3% | 上界 |
| NSTFAC | 0.20–1.00 | 0.407 | 66.7% | 靠近下界 |
| PHTMAX | 40–80 | 78.734 | 45.3% | 上界 |
| SIZLF | 250–350 | 253.459 | 41.3% | 下界 |

根系参数中，RTNO3、RTEXF、NVSMOB 和 NRCVR 没有明显触边；只有 RTNH4 强烈触及下界。`SOIL_SLPF` 后验均值 0.976、中位数 0.981，触边比例为 0%，说明把综合肥力倍率纳入率定是有效的诊断约束，但当前数据更支持接近 1 的土壤综合肥力，而不是更低肥力。

## 下一步建议

1. **先处理结构性偏差，不立即扩大所有边界。** 25FA LWAD/LNAM 的同步低估，以及 25SP/25FA ADAP 的负偏差，说明需要先检查秋季 FileX 终止/采收规则、器官干物质读入和氮质量单位，再决定参数边界。
2. **对 RTNH4 做定向小试验。** 虽然它在 80.7% 成员触及下界，但当前 25FA SNAM/LNAM 已低估；单纯降低 RTNH4 可能进一步降低吸氮，不应直接作为正式边界扩展结论。建议用 3 个固定下界（0.001、0.003、0.005）的小规模对照，同时保留 SNAM/LNAM 和 NSTD/PlantN 工程门。
3. **优先拆分秋季偏移与遗传参数代偿。** DXFRT_AUT、DSLAVR_AUT、DSFDUR_AUT 和 DTB1_AUT 明显触边，建议下一轮固定或收窄未触边偏移，仅对 DXFRT_AUT/DSLAVR_AUT 做受控二因素试验，避免其代偿 XFRT、SLAVR、SFDUR。
4. **收窄已明确方向的结构参数。** RHGHT、PODUR、VSSINK、SIZLF、TB3、SLAVR 已出现强触边，可将其边界沿后验方向收窄；但 RHGHT 下界和 TB3 上界应先核对 DSSAT 输出单位与温度响应定义，再冻结。
5. **保留 SLPF，但暂不向低值放宽。** 建议下一轮使用 0.90–1.00 或固定 0.98 的敏感性对照，检验其是否只是吸收季节土壤差异；不要把 SLPF 当作降低 25FA 器官氮/干重偏差的直接修复参数。
6. **建立季节分层验收门。** 总 Phi 已通过工程门，但正式科研验收应增加：25FA LWAD/SNAM/LNAM 的 NSE、ADAP 偏差、同水分 N0–N3 产量排序及二次曲率检查，防止总目标函数掩盖秋季结构性失配。

分析产物：

- [best_member_metrics_rawscale.csv](D:/Tomato_Cal/workspace/runs/e02_joint62_m1_offsets_plantn_slpf_150x5_20260729_v6/best_member_metrics_rawscale.csv)
- [posterior_bounds_touch_summary.csv](D:/Tomato_Cal/workspace/runs/e02_joint62_m1_offsets_plantn_slpf_150x5_20260729_v6/posterior_bounds_touch_summary.csv)
- [quality_report.md](D:/Tomato_Cal/workspace/runs/e02_joint62_m1_offsets_plantn_slpf_150x5_20260729_v6/quality_report.md)
