# TN5/9/13 遗传参数率定对比报告：CENTURY（v16）vs Godwin→CENTURY 前参数集（v15）

日期：2026-02-03

## 1. 背景与变更

你已在试验文件的 Simulation Controls 中，将 Soil Organic Matter 方法从 Godwin 切换为 CENTURY（`*SIMULATION CONTROLS` → `@N METHODS`）。

- 文件：`Workspace/XXQL2501.TMX`
- 位置：`*SIMULATION CONTROLS` 段（示例行见 `@N METHODS ... MESOM ...`）

本报告对比：

- v15：`eggplant_stage2_v15_onlyTN5_TN9_TN13`（切换前完成的 TN5/9/13 率定参数集）
- v16：`eggplant_stage2_v16_onlyTN5_TN9_TN13_century`（在 CENTURY 方法下重新率定得到的参数集）

## 2. 率定设置（两轮一致）

- 处理：仅 TN5、TN9、TN13（TRTNO=5/9/13）
- Batch：`Workspace/DSSBatch_only_TN5_TN9_TN13.v48`
- 算法：PEST++ IES
- `noptmax=6`，`ies_num_reals=80`
- 遗传参数边界：`Workspace/Sensitivity_Analyze/SA_Project_Output/sensitivity_param_review.csv`

运行目录：

- v15 run_dir：`Workspace/Calibration_Results/_runs/20260203_eggplant_stage2_v15_onlyTN5_TN9_TN13`
- v16 run_dir：`Workspace/Calibration_Results/_runs/20260203_eggplant_stage2_v16_onlyTN5_TN9_TN13_century`

## 3. 率定汇总（IES 最优解）

|项目|v15|v16（CENTURY）|
|---|---:|---:|
|Best realization (phi)|27 (1.3388)|68 (0.1217)|
|RMSE（weighted obs）|1652.2001|1407.4886|
|Mean Bias（weighted obs）|940.6825|531.6198|
|Best-fit bound hits|8|9|

关键文件：

- v15 best params（fixed）：`Workspace/Calibration_Results/eggplant_stage2_v15_onlyTN5_TN9_TN13_best_parameters_fixed.csv`
- v16 best params（fixed）：`Workspace/Calibration_Results/eggplant_stage2_v16_onlyTN5_TN9_TN13_century_best_parameters_fixed.csv`
- v15 bound hits：`Workspace/Calibration_Results/eggplant_stage2_v15_onlyTN5_TN9_TN13_bound_hits.csv`
- v16 bound hits：`Workspace/Calibration_Results/eggplant_stage2_v16_onlyTN5_TN9_TN13_century_bound_hits.csv`

## 4. 参数差异（v16 − v15）

|参数|v15(原)|v16(CENTURY)|Δ|Δ%|
|-:|--:|--:|--:|--:|
|pl-em|11.453|11.2879|-0.1651|-1.4%|
|em-v1|17.4557|15.0482|-2.4075|-13.8%|
|em-fl|23|24.4287|1.4287|6.2%|
|ju-r0|7.81347|2.01821|-5.79526|-74.2%|
|fl-lf|400|400|0|0.0%|
|fl-sd|7.12387|8.95211|1.82824|25.7%|
|sd-pm|400|360.658|-39.342|-9.8%|
|sfdur|10.1881|10|-0.1881|-1.8%|
|trifl|0.525749|0.798893|0.273144|52.0%|
|rhght|1.86272|1.66568|-0.19704|-10.6%|
|rwdth|1.56999|1.6|0.03001|1.9%|
|xmage|20.6345|12.7011|-7.9334|-38.4%|
|xfint|0.239601|0.336329|0.096728|40.4%|
|xfpht|40|29.6688|-10.3312|-25.8%|
|xfrt|0.987425|0.932624|-0.054801|-5.5%|
|rtno3|0.0190943|0.01|-0.0090943|-47.6%|
|rtnh4|0.011786|0.0100088|-0.0017772|-15.1%|
|rtexf|0.0679485|0.0783337|0.0103852|15.3%|
|kc_slope|0.0796379|0.118584|0.0389461|48.9%|
|vssink|5.19006|4.52702|-0.66304|-12.8%|
|tb1|9.34026|10.98|1.63974|17.6%|
|tb2|9.83135|9.28133|-0.55002|-5.6%|
|tm2|34.7304|34.1301|-0.6003|-1.7%|
|to11|24.9962|25.1314|0.1352|0.5%|
|to12|26.6721|26.4836|-0.1885|-0.7%|
|to22|29.3999|28.9998|-0.4001|-1.4%|

## 5. 同一 CENTURY 环境下的确定性评估（仅 TN5/9/13）

为保证“方法切换”后的公平对比，使用当前 `XXQL2501.TMX`（CENTURY）分别对两套参数在同一 batch（TN5/9/13）下进行确定性运行并计算 metrics-grid：

- v15 参数在 CENTURY 环境下：`v15_params_on_century_only`
- v16 参数在 CENTURY 环境下：`v16_century_on_only`

|指标|v15(NRMSE%)|v15(d)|v16(NRMSE%)|v16(d)|ΔNRMSE%|Δd|
|-:|--:|--:|--:|--:|--:|--:|
|harvest_curve/dry_cum|95.65|0.522|103.83|0.483|+8.19|-0.039|
|harvest_curve/dry_inc|93.90|0.414|100.07|0.403|+6.17|-0.011|
|process/LAID|65.28|0.869|26.06|0.975|-39.21|+0.106|
|process/LWAD|125.20|0.726|25.31|0.977|-99.90|+0.251|
|process/SWAD|181.50|0.652|175.49|0.711|-6.01|+0.059|

metrics-grid 文件：

- `Workspace/Calibration_Results/v15_params_on_century_only_metrics_grid.csv`
- `Workspace/Calibration_Results/v16_century_on_only_metrics_grid.csv`

## 6. 图表输出（已补齐）

本轮已为两个率定版本生成标准图表（散点 1:1 + 分 TN 时序），输出目录：

- v15：`Workspace/Calibration_Results/plots/eggplant_stage2_v15_onlyTN5_TN9_TN13/`
- v16（CENTURY）：`Workspace/Calibration_Results/plots/eggplant_stage2_v16_onlyTN5_TN9_TN13_century/`

图表文件（两版本同名，便于直接对照）：

- `scatter_dry_cum.png`, `scatter_fresh_cum.png`
- `scatter_LAID.png`, `scatter_LWAD.png`, `scatter_SWAD.png`
- `scatter_HWAM.png`, `scatter_LAIX.png`, `scatter_CNAM.png`
- `timeseries_LAID_by_TN.png`, `timeseries_fresh_cum_by_TN.png`

## 7. 结果解读（针对“Godwin→CENTURY”切换的影响）

1) **率定目标函数（weighted obs）显著改善**：v16 的 best phi 远低于 v15（0.1217 vs 1.3388），RMSE 与 bias 同时下降，说明在当前权重与观测集合下，CENTURY 环境更容易被某组遗传参数解释。

2) **过程变量拟合显著改善，但采收曲线仍极差**：在同一 CENTURY 环境下，v16 的 `LAID/LWAD` NRMSE 大幅下降且 d-index 接近 1，但 `dry_cum/dry_inc` 仍处于 NRMSE≈100% 的不可接受区间。这类“过程拟合好、采收拟合差”的模式，通常意味着：

- 采收相关过程（sink strength / multi-harvest rhythm）与当前观测口径或管理输入仍存在结构性不一致；或
- 权重体系使优化优先满足 LAI/生物量过程，而牺牲采收曲线（参数补偿效应）。

3) **参数层面的方向性变化**（最值得关注）：

- v16 相比 v15：`TRIFL` 上升、`KC_SLOPE` 上升，解释了 LAI/叶生物量显著改善；
- v16 将 `XMAGE` 下调、`XFINT` 上调、`XFPHT` 下调，说明优化倾向于改变繁殖分配动态，但这些变化并未带来采收曲线改善；
- `RTNO3/RTNH4` 靠近下界（v16 的 `RTNO3` 直接到下界），提示在 CENTURY 环境下，氮供应/矿化过程可能更容易满足植株氮需求，导致模型不再需要更高的根系吸收能力来拟合现有加权观测。

## 8. 结论与下一步建议

- 结论：切换到 CENTURY 后，**率定目标函数与冠层过程拟合显著改善**，但 **TN5/9/13 的采收曲线（dry_cum/dry_inc）仍然处于不可接受误差水平**，说明主要瓶颈仍然不在 SOM 方法本身，而在 TN5/9/13 的采收/管理/观测口径一致性或繁殖—采收过程结构。
- 建议（优先级从高到低）：
  1. 先核对 TN5/9/13 的采收观测口径与单位（dry/fresh、累积方式、缺失采收点处理），确保与其他 TN 一致。
  2. 检查 TN5/9/13 的施肥/初始 N/水分管理是否存在与其他处理不同的关键输入（尤其与 CENTURY 相关的初始有机质/残茬设置）。
  3. 若继续纳入 TN5/9/13 做遗传参数率定，建议对 multi-harvest 接口参数（`XMAGE/XFINT/XFPHT`）进行更严格的先验边界与分阶段率定，避免其与 `TRIFL/KCAN/SLAVR` 等冠层参数发生强补偿。
