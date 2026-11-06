# R 论文图流水线

## 2026-09-27 Champion C31 全局双春高精度代表解与交付

当前最终全局 Champion 确立为 **C31**（`c28_scheme1_tb1_92`，基于 Scheme 1 物理土壤校正体系与发育基温 `TB1 = 9.20 °C`），产物入口见 [README_PAPER_WORKSPACE.md](README_PAPER_WORKSPACE.md)。
本轮引入方案 1 实测物理土壤参数（`SLPF_25SP = 0.88`, `SLPF_26SP = 0.89`, `SASC_RATIO = 0.92`, `SOIL_SLDR = 0.40`, `SOIL_SLU1 = 2.50 mm d⁻¹`），实现双春季精度的历史性跨越：
- **2026春 (26SP, 12处理)**：$R^2 = 0.7016$，$\text{NRMSE} = 4.89\%$，$\text{NSE} = +0.7011$，$d = 0.9022$（$0.9072$），同时攻破两项 0.70 门槛；
- **2025春 (25SP, 11处理)**：$R^2 = 0.8802$，$\text{NRMSE} = 6.24\%$，$\text{NSE} = +0.3726$；
- **双春合并 (23处理)**：$R^2 = 0.7246$，$\text{NRMSE} = 5.57\%$，$\text{NSE} = +0.5721$；
- **三季全样本 (35处理)**：$R^2 = 0.9846$（$0.9840$），$\text{NRMSE} = 7.67\%$，$\text{NSE} = +0.9757$（$+0.9745$），Willmott $d = 0.9940$；
- **2025秋盲验 (25FA, 12处理)**：均产 $13.41\text{ t/ha}$，$\text{NRMSE} = 23.07\%$；
- **水氮农艺阶梯**：Table 4 中春茬所有处理的水分边际缓解（W2−W1）与充分灌溉恢复（W3−W1）阶梯 100% 严格为正，彻底消解零氮负灌溉非物理陷阱。

全套图版位于 `03_Figures/Main_Figures` 与 `Supplementary_Figures`，数据包位于 `paper_data/`，所有图版 SHA-256 校验记录于 `03_Figures/figure_manifest.json`。

## 2026-09-22 Champion C23 历史阶段回顾（已由 C31 继承与超越）

历史代表解 C23（iter8_real194）查明并修复 25SP W2N0/W2N3 底土 20–60 cm 初始无机氮与有机质反向错位问题，实现 25SP 鲜果产量 NRMSE 6.00%。其历史产物已被 Champion C31 全面升级与覆盖。

## 2026-09-20 C16 重绘与显式标签控制

当前论文代表解及产物入口见 [README_PAPER_WORKSPACE.md](README_PAPER_WORKSPACE.md)。R 入口支持 `--publication-label-note "作者明确要求及日期"`：在原数据哈希及未验证数据许可门禁之后，仅控制 DEMO 水印和文件名前缀。使用这一选项不会将数据改为 `science_validated`；输出 manifest 保存实际 `data_status`、`science_validated`、`demo_label_visible`、`publication_label_note` 和 `scientific_status_promoted=false`。未传此选项时保留原有 DEMO 展示行为。

C16 的季节数据包显式冻结过程配对的 `simulation_date_code` 与 `simulation_date_gap_days`。R 性能/残差图排除已知非同日过程配对；动态点仍保留在真实观测 DAP，模型线不外推。三季轨迹不得用年份推断春/秋归属。累计采收的单调插值允许至少两个真实节点，验证节点与插值结果均不下降。线宽点值转换为 ggplot 毫米单位；各季全处理同变量使用统一纵轴。

回归检查：`python -m pytest tests/test_publication_figures.py -q`；使用固定 R 4.5.2 运行 `tests/test_c16_plot_contracts.R`。

## 2026-09-02 迁移与证据修订

旧Python入口 `tools/reporting/generate_v46_page25_publication_suite.py` 已降为诊断，只接受显式确定性目录、处理映射与空输出目录；不再自动挑选champion或后验，也不再输出Fig/FigS。其历史产物保留但不得当作论文证据。
后验诊断必须显式指定IES运行目录、case和迭代，核对同批次先验/PST/实际Phi/成员/边界。缺先验直接告知并拒绝先后验比较；不能用后验或均匀边界分布替代。默认不画模拟不确定性区间。

`fig_model_performance.R` 现支持comparison显式携带season_id时按季分行、每行最多4变量，并分别计算指标；没有季节字段则保持原接口，不猜测季节。坐标覆盖观测SE端点且保持1:1等轴。`fig_all_treatment_dynamics.R` 的增量采收不连接成连续线，轴范围包含观测误差棒。
本次是分阶段迁移的首个切片，不代表所有Python历史布局已迁完。R仍只消费冻结数据，科学状态/哈希门禁不变；合成QA图一律DEMO，不是正式结果。

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
