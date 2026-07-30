# R 论文图流水线

本目录是论文主图、补充图和投稿版源文件的唯一绘图实现。Python 只负责
SA/率定运行诊断以及将结果导出为冻结的 tidy 数据包；R 不读取 DSSAT 或
PEST++ 的临时文件，也不猜测处理映射、迭代号或数据用途。

## 目录职责

```text
paper/
  R/                 R 绘图入口、统一主题和各图实现
  README.md          依赖、数据契约与复现命令
configs/figures/     出版 profile 与 Fig/FigS 注册表
src/reporting/
  figure_data.py     Python 侧 tidy 数据契约和历史适配
  export_paper_data.py 只导出数据，不绘图
  plot_results.py    Python 运行诊断兼容入口，不生成论文图号
```

动态图相关模块按科学问题拆分：`fig_selected_dynamics.R` 负责主文代表处理，
`fig_residual_diagnostics.R` 负责 Fig. S3，`fig_all_treatment_dynamics.R`
负责 Fig. S4。`make_all.R` 只编排这些模块并登记产物，不重复实现统计或图层。

## R 依赖

要求 R 4.3 或更高版本，以及 `ggplot2`、`patchwork`、`jsonlite`、
`svglite`。Windows 使用系统 `certutil` 计算 SHA-256；非 Windows 需要
`sha256sum`。入口会在绘图前一次性检查依赖，不会在正式运行时
联网安装包。

`Rscript` 应加入 `PATH`；若机器并存多个 R 版本，可用选定版本的完整
`Rscript.exe` 路径执行。不要让新 R 版本加载旧版本编译的用户包库。

## 两阶段复现

先由 Python 冻结渲染器无关的数据包：

```powershell
python -m src.reporting.export_paper_data --run-id <run_id> `
  --comparison-csv <comparison.csv> --phi-csv <case.phi.actual.csv> `
  --trajectory-run-dir workspace/runs/<run_id> `
  --treatment-metadata-csv configs/figures/treatment_metadata_xxql2501.csv `
  --out-dir workspace/runs/<run_id>/paper_data
```

再由 R 生成论文图、每图 source CSV 和哈希清单：

```powershell
Rscript paper/R/make_all.R `
  --input-dir workspace/runs/<run_id>/paper_data `
  --out-dir workspace/runs/<run_id>/paper_figures
```

非 `science_validated` 数据默认被两端拒绝。仅版式开发可在两个命令中都
显式加入 `--allow-unvalidated-demo`；输出使用 `DEMO_` 前缀并带水印，不能
作为论文图引用。

## 动态图数据与视觉编码

`comparison.csv` 保存观测日期上的观测—模拟配对；`simulation_trajectory.csv`
保存从 `PlantGro.OUT` 和 `FreshWt.OUT` 提取的日尺度确定性模拟；
`treatment_metadata.csv` 显式保存处理标签、水水平和氮水平。三者不得在 R
端通过处理号或文件名猜测。

处理动态图使用氮水平颜色（N3 深红、N2 橙、N1 蓝、N0 灰）和水处理点形
（W3 圆、W2 方、W1 三角、CK 菱形）。连续生长过程用日模拟线叠加实测点；
增量采收使用事件图；累计采收同时输出普通事件折线和连续平滑备选图。平滑
备选图采用采收日期模拟累计值的单调三次 Hermite 插值，只用于视觉表达，指标始终
从未经插值的原始输出计算。

残差补充图按 `dataset_role` 分开输出，残差定义为模拟值减观测值；全处理补充图
按变量分页生成 5×2 小多图。历史布局数据只产生 `DEMO_` 文件，正式 Fig. S3/S4
必须由通过科研质量门的数据包生成。

## Morris 敏感性分析图

敏感性分析使用独立的冻结数据包，不与率定/验证图的数据包混用。Python 只校验并冻结每季的
`morris_consensus_ranking.csv`、`morris_seed_rankings.csv`、
`morris_seed_group_scores.csv`、`morris_seed_pairwise_stability.csv` 和稳定性 JSON；
R 只读取冻结后的 CSV 与哈希清单。

```powershell
python -m src.reporting.export_sa_paper_data `
  --run-id formal_morris_v4_20260721 `
  --results-root workspace/runs/morris_results_repro_v4 `
  --season XXQL2501=XXQL2501/r10 `
  --season XXQL2502=XXQL2502/r20 `
  --season XXQL2601=XXQL2601/r10 `
  --focus-config configs/figures/sa_focus_parameters.csv `
  --out-dir workspace/runs/morris_results_repro_v4/paper_data_v4 `
  --allow-unvalidated-demo

Rscript paper/R/make_all.R `
  --input-dir workspace/runs/morris_results_repro_v4/paper_data_v4 `
  --out-dir workspace/runs/morris_results_repro_v4/paper_figures_v4 `
  --figure-ids fig1_sa,figs1_sa_stability `
  --allow-unvalidated-demo
```

Fig. 1 分别展示一般遗传域和水氮响应域的跨季层级归一化 Morris 得分，并用过程组热图解释
参数主要影响物候、冠层、生物量、采收或水氮响应。Fig. S1 展示逐 seed 排名以及 Spearman
和 Top-15 Jaccard 门槛。两个域不得合并成一个无条件的总排名。当前任一季/域未通过门槛时，
导出器只允许显式生成带 `DEMO_` 前缀与水印的 `science_pending` 图。

## Sobol 效应分解与数值证据图

Sobol 使用独立于 Morris 和率定的冻结数据包。当前三季扩规模审查中，仅 XXQL2502 的 N=128→N=256 比较通过全部预设门；XXQL2601 未通过最大名次变化门，XXQL2501 未通过 bootstrap 有效重采样门。Fig. S2 因而只对 XXQL2502 展示固定标量响应的 S1、ST、paired-bootstrap 区间和 ST-S1 交互余量，同时保留三季证据状态与收敛指标。ST-S1 不是具体参数对的二阶交互，也不得在季节间直接合并。

```powershell
python -m src.reporting.export_sobol_stability_paper_data `
  --run-id sobol_multiseason_effects_v4_20260722 `
  --convergence-season XXQL2502=workspace/runs/sobol_stability_rerun_v1/XXQL2502/convergence_n0128_n0256_repaired_v2_20260722 `
  --convergence-season XXQL2601=workspace/runs/sobol_stability_rerun_v1/XXQL2601/convergence_n0128_n0256_repaired_v2_20260722 `
  --bootstrap-gate-season XXQL2501=workspace/runs/sobol_stability_rerun_v1/XXQL2501/n0256_seed_20260729/sobol_bootstrap/sobol_bootstrap_quality.json `
  --effect-season XXQL2502 `
  --effect-case workspace/runs/sobol_stability_rerun_v1/XXQL2502/n0256_seed_20260729_repaired_v2_20260722 `
  --out-dir workspace/runs/sobol_stability_rerun_v1/paper_data_multiseason_v4_20260722

Rscript paper/R/make_all.R `
  --input-dir workspace/runs/sobol_stability_rerun_v1/paper_data_multiseason_v4_20260722 `
  --out-dir workspace/runs/sobol_stability_rerun_v1/paper_figures_multiseason_v4_20260722 `
  --figure-ids figs2_sobol_convergence `
  --allow-unvalidated-demo
```

`fig1_sa`/`figs1_sa_stability` 与 `figs2_sobol_convergence` 必须分开渲染：它们消费不同的冻结证据包，避免 Sobol 的未收敛状态被 Morris 图隐式掩盖。
