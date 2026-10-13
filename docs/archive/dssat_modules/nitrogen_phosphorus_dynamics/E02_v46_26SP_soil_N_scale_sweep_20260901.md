# E02 v46 26SP 初始矿质氮缩放剖面（2026-09-01）

## 目的与固定条件

以 `e02_formal_v46_dias2026_double_n_20260831` 确定性最佳成员 #1 的遗传/土壤参数为固定锚点，仅改变26SP `XXQL2601.TMX` 中0–60 cm的初始 `SNH4`、`SNO3`。Excel文件“三重复与判定”按处理×土层取三重复均值：0–20 cm映射到DSSAT 2/4/15 cm，20–40 cm映射到30/40 cm，40–60 cm映射到60 cm；80 cm以下保持双氮bundle原值。

缩放倍率为0.10、0.14、…、0.90（步长0.04）。25SP使用不变的双氮bundle作为运行控制季，实际比较只使用26SP。

## 运行审计

- 21/21倍率、每倍率22个处理（25SP 10 + 26SP 12）均成功完成；无失败倍率。
- 初始N行采用TMX原始固定列宽，避免跨位后触发DSSAT `IPSLIN`误报。
- 遗传参数来源：`best_member_1_params.csv`；未重新率定参数。

## 26SP最佳倍率

| 指标 | 最佳倍率 | 指标值 |
|---|---:|---:|
| LAI NSE（绝对值最佳） | 0.10 | -1.944 |
| LAI RRMSE（最低） | 0.10 | 113.88% |
| LWAD NSE | 0.10 | 0.406 |
| SWAD NSE | 0.90 | 0.818 |
| CHTD NSE | 0.30 | 0.871 |
| 累积鲜重 NSE | 0.34 | 0.871 |
| 累积鲜重 RRMSE | 0.34 | 20.36% |
| 累积干重 NSE | 0.54 | 0.742 |
| 累积干重 RRMSE | 0.54 | 29.42% |

按过程状态与产量误差的综合秩，最佳点为0.34，随后为0.38、0.42；0.30–0.54构成较稳定的产量折中区间。

## 响应结构

基于最终累积鲜重事件计算：

- `N_RESPONSE = N3 − N0`（W1/W2/W3、5个收获期，共15点）：倍率0.10的RMSE最低（7894 kg/ha，NSE=-1.804），但仍明显低估氮响应；倍率升高到0.34时NSE降至-5.167。
- `W_RESPONSE = W2 − W1`：N3响应对倍率几乎不敏感，所有倍率NSE约-6.82；N0响应在0.82–0.90较好，但NSE仍为-1.40至-1.61。
- LAI处理间扩散比 `SD(sim)/SD(obs)` 从0.10的3.82降至0.90的1.12，说明高倍率改善了处理间LAI spread，但没有改善总体LAI尺度。

## 结论

初始矿质氮缩放可以调节产量偏差和处理间响应形状，但不能单独修复26SP后期LAI过高：

1. 低倍率（0.10–0.18）略有利于LAI/LWAD误差，但牺牲产量尺度；
2. 中倍率（0.30–0.54）给出最佳累积鲜重拟合，推荐作为后续机制试验的输入范围；
3. 高倍率（0.82–0.90）改善LAI处理间spread和SWAD，但总体LAI仍偏高，且N响应没有改善；
4. 因此不应把某一倍率直接写入正式bundle。下一步应在0.34附近固定初始N，单独剖面物候/叶面积形成—衰老参数（`TB1`、`XFINT`、`PM06`、`JU-R0`、`FNPGN2`、`SENRTE`），并继续以26SP LAI与两季鲜重RRMSE为联合门槛。

## 产物

- [完整倍率指标](D:/Tomato_Cal/workspace/reports/e02_v46_26sp_soil_n_scale_sweep_20260901/scale_metrics_ranked.csv)
- [N/W响应指标](D:/Tomato_Cal/workspace/reports/e02_v46_26sp_soil_n_scale_sweep_20260901/scale_response_metrics.csv)
- [倍率曲线图](D:/Tomato_Cal/workspace/reports/e02_v46_26sp_soil_n_scale_sweep_20260901/scale_metric_profiles.png)
- [可复现脚本](D:/Tomato_Cal/tools/experiments/run_26sp_soil_n_scale_sweep_20260901.py)
