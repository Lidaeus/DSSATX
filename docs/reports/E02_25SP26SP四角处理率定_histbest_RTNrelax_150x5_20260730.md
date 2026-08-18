# E02 25SP+26SP 四角水氮处理率定结果

日期：2026-07-30

## 运行结论

正式版本为 `e02_spring_pair_histbest_4corner_150x5_20260730_v4`。运行规模为150×5，最终150个成员全部保留，管理器退出码为0，工程状态为 `engineering_validated`。

本版本只使用25SP和26SP，每季只使用四个水氮角点处理：W3N3、W1N0、W3N0、W1N3。25FA完全排除。活动参数55个，有效观测408个，氮响应观测32个，ADAP保持diagnostic-only。

> **2026-07-30 追补审计：本批次的 N-response 科学结论已退役。**
> 当时把 `PestHarvest.OUT` 的 CHPDT token 误认为原尺度并再次执行 `log1p`；
> 实际上该 token 已由观测策略转换为 `ln(y+1)`，因此 v4 使用了双重变换。
> v3 和 v4 均只能作为工程与绝对拟合历史，不能用于解释氮响应目标的效果。
> 当前正确实现是对两个已变换 token 直接相减。

## 收敛和最优成员

末轮最优成员为 **74**，actual Phi = **185.162**。末轮平均 Phi = **208.923**，末轮最小 Phi = **185.162**（报告指标由成员74确定性复跑得到）。

## 最优成员原尺度拟合

| 指标 | 25SP | 26SP | 两季合并 |
|---|---:|---:|---:|
| 累积干重 RRMSE | 32.34% | 18.66% | 27.88% |
| 累积干重 NSE | 0.701 | 0.900 | 0.783 |
| 单次干重 RRMSE | 58.47% | 40.06% | 50.58% |
| 单次干重 NSE | -0.776 | -0.166 | 0.429 |
| LAID RRMSE | 31.04% | 62.59% | 42.56% |
| LAID NSE | 0.774 | 0.124 | 0.616 |
| LWAD RRMSE | 28.72% | 36.57% | 33.64% |
| LWAD NSE | 0.785 | 0.571 | 0.678 |
| SWAD RRMSE | 27.14% | 24.52% | 25.76% |
| SWAD NSE | 0.866 | 0.858 | 0.863 |
| CHTD RRMSE | 52.66% | 39.03% | 46.00% |
| CHTD NSE | -0.291 | 0.117 | -0.094 |

本次只保留四个角点后，26SP累积干重拟合较好；25SP累积干重和单次采收仍偏弱。LAID、CHTD及单次采收时序仍是主要过程误差来源。

## 氮响应能力

32个 `N3−N0` log-ratio 响应的原尺度比较为：

| 指标 | 结果 |
|---|---:|
| RMSE | 0.4685 |
| MAE | 0.4072 |
| Bias（模拟−实测） | -0.4070 |
| NSE | -2.986 |
| R² | 0.025 |

最优成员的模拟响应均值约0.006，而实测均值约0.413，说明将 `RTNH4` 和 `RTNO3` 下界降低并不能自动恢复氮响应幅度；当前模型仍主要把角点处理拟合为接近无氮响应的平台。

## 后验边界诊断

| 参数 | 本轮范围 | 后验中位数 | 触边比例 |
|---|---:|---:|---:|
| RHGHT | 0.50–2.20 | 0.537 | 下界85.3% |
| RTNH4 | 0.001–0.05 | 0.0158 | 0% |
| RTNO3 | 0.003–0.05 | 0.0113 | 0% |
| NSTFAC | 0.20–1.00 | 0.434 | 下界5.3% |
| SOIL_SLPF | 0.65–1.00 | 0.981 | 上界46.7% |

`RTNH4/RTNO3` 放宽后均脱离边界，说明此前的下界确实限制了后验；但氮响应仍弱，问题已经从“边界截断”转向“模型响应结构或目标约束不足”。`RHGHT` 仍强烈贴近历史下界，需单独处理，不能让其继续代偿氮响应。

## 文件

- 率定运行：[e02_spring_pair_histbest_4corner_150x5_20260730_v4](</D:/Tomato_Cal/workspace/runs/e02_spring_pair_histbest_4corner_150x5_20260730_v4>)
- 最优成员诊断：[e02_spring_pair_histbest_4corner_150x5_20260730_v4_best](</D:/Tomato_Cal/workspace/diagnostics/e02_spring_pair_histbest_4corner_150x5_20260730_v4_best>)
- 冻结边界：[eggplant_e02_spring_pair_histbest_rtn_relax_20260730.csv](</D:/Tomato_Cal/data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_spring_pair_histbest_rtn_relax_20260730.csv>)
