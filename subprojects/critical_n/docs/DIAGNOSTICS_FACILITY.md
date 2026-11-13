# 配套诊断设施索引（Diagnostic Facility）

本仓库的诊断图集/图表渲染代码设施总索引。**代码入 git、产物不入 git**
（`figture/`、各实验 `atlas/`、`replay/` 数据目录均被 .gitignore 排除或按
数据目录对待，仅渲染代码与说明进入版本库）。所有渲染器一律遵循
"先确定性重放、后渲染"：图集只消费带 receipt/audit 哈希链的冻结运行产物，
不直接触碰率定过程文件。

## 1. 单季率定试验评审套件（根基，已在库）

`tools/reporting/report_dual_morris98_trial_20261105.py`
（内嵌 `render_trial`：φ 轨迹、终产 1:1、物候-水氮、参数边界、残差/散点/
MSE 分解、水氮梯度等）→ `report_sa98_joint40_20261031.py` 的 `render`
（深层逐日诊断）、`report_rmse_joint65_20261012.py` 的收获分面。
入口约定：`suite.RUN/OUT/FIG/NATIVE` 四路径注入。产出形如
`figture/<run>_diagnostics/`（png + data/ CSV + 26SP/ 子套件 +
diagnostic_manifest.json 哈希清单）。

## 2. 管理束重放渲染对（n_buffer_v16）

| 文件 | 作用 |
|---|---|
| `n_buffer_v16/replay_26sp_management_bundles.py` | 按管理束（如 `xxql2601_final_20261105`）确定性复跑，写 replay receipt（物理门 + 哈希链） |
| `n_buffer_v16/render_26sp_management_bundles.py` | 以 §1 套件渲染每个束重放；`read_pairs`/`write_wide`/`render_suite` 为后续渲染器的公共入口 |
| `n_buffer_v16/render_retained_diagnostics_20261106.py` | 保留参考（retained reference）界面对照渲染 |

产出：`figture/n_buffer_v16_<bundle>_diagnostics/`（如
`figture/n_buffer_v16_xxql2601_final_20261105_diagnostics/`）。

## 3. v15_s4_nstate 开关矩阵渲染器

| 文件 | 作用 |
|---|---|
| `v15_s4_nstate/render_50x3.py` | 50×3 试点（(2,2) 主推组合）最优成员审计重放渲染（含 ψ* 状态面板） |
| `v15_s4_nstate/render_60x3.py` | 60×3 三组合（k11/k21/k12）渲染；mode-1 无 NStatePsi 时按设计跳过状态面板并双向核验账本存在性；kernel-2 导出 RootKernelLedger 日值 |
| `v15_s4_nstate/plot_s4_diagnostics.py` | 2×2 因子 ψ/ψ* 对照诊断（macOS 诊断线，依赖 v15_s3_v4root 谱系） |
| `v15_s4_nstate/replay_s4.py` | S4 2×2 因子重放驱动 |

产出：`figture/v15_s4_nstate_26sp_{50x3,60x3_*}_20261109_diagnostics/`。

## 4. 官方 vs 协调对照图集（official_vs_coord5_*）

| 目录/文件 | 作用 |
|---|---|
| `official_vs_coord5_20261109/`（README.md、replay.py、render.py、summarize.py） | 双春官方 DSSAT 与 V15 协调+5 日窗口主对照：确定性复跑 → 水分分面/氮梯度颜色图集（PDF）、日值、配对指标、产量差分、V15 氮平衡残差 |
| `official_vs_coord5_refreshed_20261110/`（replay.py、render.py、summarize.py、render_fertilizer_editions.py、render_s4_beta200.py） | 刷新束版（25SP `xxql2501_refreshed_lwad_20261108`、26SP `xxql2601_final_20261105`）；`render_fertilizer_editions.py` 产出含施肥事件平滑产量版的官方图集（`diagnostic_official_atlas_with_fertilizer_smooth_yield.pdf`）；`render_s4_beta200.py` 叠加 S4 β200 变体对照 |

产出：各自目录 `atlas/*.pdf` 与 png（数据目录不入库）。

## 5. R 侧渲染器

`n_buffer_v15/render_final.R`：只消费哈希冻结表格证据
（data_manifest.json 逐件 sha256 校验）的科学诊断渲染（依赖
`paper/R/common.R`）。

## 约定

- 渲染代码**原地入库**，不搬迁：率定 design.json 的 frozen_hashes 链按
  绝对路径冻结这些文件，移动即断链。
- 渲染前置断言：replay receipt φ = audit best φ、管理文件哈希 = 设计
  冻结值、目标帧逐字节一致、最优成员可溯源至 checkpoint lineage。
- 环境约定：Windows，仓库根 `D:/Tomato_Cal`；matplotlib Agg；
  观测目录由 `tools/calibration/run_dual_morris98_trial_20261105.py`
  提供、原生输出由 `src/calibration/single_season_n.read_native` 解析。
