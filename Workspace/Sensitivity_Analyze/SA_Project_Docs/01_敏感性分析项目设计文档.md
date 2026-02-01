# DSSAT 遗传参数敏感性分析项目（设计文档）

## 0. 背景与目标

本项目针对番茄（Tomato，TMGRO048）遗传参数开展敏感性分析，参数来源与变更依据见：

- `Workspace\Sensitivity_Analyze\需要进行敏感性分析的遗传参数.txt`
- `Workspace\Sensitivity_Analyze\CUL_Comparison.md`
- `Workspace\Sensitivity_Analyze\ECO_Comparison.md`
- `Workspace\Sensitivity_Analyze\SPE_Comparison.md`
- `Workspace\Sensitivity_Analyze\Summary.md`

敏感性分析的核心目标：

1. 在给定参数变化范围内，定量识别不同输出指标对哪些遗传参数最敏感。
2. 面向用户提供直观可视化（“指标 → 参数” 与 “参数 → 指标” 两种视角）。
3. 采用“先参数范围 CSV 审核 → 再批量运行 → 再统计与可视化”的可重复流程。

## 1. 范围与约束

### 1.1 分析对象（遗传参数）

本项目参数来源于三类遗传文件：

- `TMGRO048.CUL.base`（Cultivar，品种参数）
- `TMGRO048.ECO`（Ecotype，生态型参数）
- `TMGRO048.SPE`（Species，物种参数）

本轮在遗传参数之外，额外将“关键土壤水文/物理参数”纳入敏感性分析范围（来源：`Workspace\SOIL.SOL`，按 `Workspace\XXQL2501.TMX` 中的 `ID_SOIL` 自动定位土壤剖面）。

`需要进行敏感性分析的遗传参数.txt` 中列出的“候选参数集合”作为默认纳入范围；当某些条目在文件中实际是同一行的多列参数时，以文件头部的真实参数名为准（例如 `PARMAX,PHTMAX,KCAN,KC_SLOPE` 行中第 4 列对应 `KC_SLOPE`）。

### 1.2 重点输出指标（用户关注）

本项目以以下指标为“必做输出”：

- LAI 曲线（`PlantGro.OUT` 通常为 `LAID`）
- 果实干重积累曲线（优先使用 `FreshWt.OUT` 的 `CHPDT` 或 `PlantGro.OUT` 的果实/器官相关变量，具体以可解析字段为准）
- 果实总产量（最终收获汇总，优先从 `Summary.OUT` 提取，如 `HWAM`/`HWAH` 类字段；或以 `CHPDT`/`CHFPW` 终值代表）
- 茎干重（`PlantGro.OUT` 通常为 `SWAD`）
- 叶干重（`PlantGro.OUT` 通常为 `LWAD`）

指标解析与含义参考：

- `Workspace\Sensitivity_Analyze\DSSAT_Output_Interpretation\*`

### 1.3 运行约束

- 必须保持 DSSAT 固定宽度文件格式正确（避免破坏列对齐）。
- 必须显式设置 DSSAT 运行 `cwd`（避免相对路径导致的文件找不到）。
- 参数范围需可由用户通过 CSV 直接修改并作为唯一真源（single source of truth）。

### 1.4 本次敏感性分析固定输入

- 实验文件（FileX）：`Workspace\XXQL2501.TMX`
- 遗传参数文件：
  - `Workspace\TMGRO048.CUL`
  - `Workspace\TMGRO048.CUL.base`
  - `Workspace\TMGRO048.ECO`
  - `Workspace\TMGRO048.SPE`
- 土壤文件：`Workspace\SOIL.SOL`
- 品种（Cultivar）：`TM0008 Brilliance`

### 1.5 本次新增：纳入敏感性分析的土壤参数（为何选这些）

本项目不做“大而全”的土壤全剖面参数敏感性分析，而是优先纳入对作物水分可利用度与蒸散过程影响最直接、且与观测指标（LAI/产量/干物质）联动最强的一小组参数：

- `SOIL_SLLL_01`：表层下限含水量（LL，萎蔫点附近），直接控制可提取水下界，影响早期生长胁迫窗口。
- `SOIL_SDUL_01`：表层田间持水量（DUL），控制雨后/灌溉后可利用水储量上界，影响冠层扩张与果实膨大。
- `SOIL_SSAT_01`：表层饱和含水量（SAT），影响入渗/积水与土壤空气限制的可能性。
- `SOIL_SBDM_01`：表层容重（BD），影响孔隙度与根系扩展阻力，从而影响水分获取能力。
- `SOIL_SLOC_01`：表层有机碳（OC），影响土壤结构与保水性，并间接影响氮矿化供给。
- `SOIL_SALB`：土壤反照率，影响土壤能量平衡与蒸发分配，进而影响土壤温度与早期生长。
- `SOIL_SLDR`：排水系数（drainage rate），影响过湿消退速度与有效水分动态。
- `SOIL_SLRO`：径流潜势参数（runoff），影响降雨入渗与表面径流分配，进而影响土壤贮水与胁迫频率。

说明：当前仅纳入第 1 层（`_01`）参数以控制维度与运行规模；若后续需要做“根区分层敏感性”，可按 `_02/_03...` 扩展。

## 10. 实际开发进度与实现细节同步（与原设计文档差异）

### 10.1 已实现的可复现流水线（当前状态：可跑通）

已完成并验证可运行的流水线为：

1. 参数范围与初值：`Workspace\Sensitivity_Analyze\SA_Project_Output\sensitivity_param_review.csv`
2. Case 构建：`Workspace\Sensitivity_Analyze\SA_Project_Code\sa_build_sen_case.py`
3. 前向模型：PEST++ 调用 `Workspace\Sensitivity_Analyze\SA_Project_Code\sa_model.py`
4. DSSAT 执行：`Workspace\run_dssat.py` 负责更新遗传文件并运行 `DSCSM048.EXE`
5. 指标输出：`SA_Indicators.OUT`（由 `sa_model.py` 生成，供 PEST++ 读取）
6. Morris 运行：`pestpp-sen.exe`（路径见 10.3）
7. 后处理与图表：`Workspace\Sensitivity_Analyze\SA_Project_Code\sa_postprocess_morris.py`

当前已成功完成的大规模 Morris Case：

- Case 目录：`Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case_r10_big_fix2`
- 运行规模：`gsa_morris_r=10`，总运行数 510（见 `sa_sen_morris.rec` 的 finished 时间戳）
- 核心结果：`sa_sen_morris.mio`、`sa_sen_morris.msn`、`sa_sen_morris.raw.csv`、`sa_sen_morris.sen.par.csv`

### 10.2 与原设计的主要差异点（已发生/已修复）

1. `DSSBatch.v48` 作为“固定输入”在实际运行中必须有效。
   - 实际问题：`Workspace\DSSBatch.v48` 曾为空，导致 DSSAT 报错 “Error in the format of the batch file”，进而触发失败惩罚输出。
   - 现状：已补齐 `Workspace\DSSBatch.v48`，并用 `XXQL2501.TMX` 的 TRT 2/3 作为批处理条目。

2. 输出同步策略需要包含 `Evaluate.OUT`。
   - 实际问题：DSSAT 输出文件生成目录与运行目录不一致时，`Evaluate.OUT` 未被同步会导致后续指标解析失败并输出 `-99`。
   - 现状：`Workspace\run_dssat.py` 已将 `Evaluate.OUT` 纳入同步（见 `run_dssat.py:1852`）。

3. PEST++ 输出列名与“传统 mu* 口径”存在差异。
   - 设计预期：从 Morris 输出读取 `mu*`（mu_star）与 `sigma`。
   - 实际输出：当前 `sa_sen_morris.mio` 为 `observation_name,parameter_name,n_samples,sen_mean,sen_mean_abs,sen_std_dev`。
   - 现状：后处理脚本已兼容此结构，并以 `sen_mean_abs` 作为默认重要性评分口径。

4. `SA_Indicators.OUT` 原子写入与行序控制（稳健性增强）。
   - 原因：在大量并行调用前向模型时，非原子写入可能导致 `SA_Indicators.OUT` 被 PEST++ 读取到“部分写入”的无效内容。
   - 现状：`Workspace\Sensitivity_Analyze\SA_Project_Code\sa_model.py` 采用临时文件 + `os.replace` 的原子写入方式，并在写前按 `sa_obs_order.txt` 或 `_default_observation_names()` 固定输出行序；对输入模板 `sa_params.csv` 还增加了短暂等待机制以缓解 I/O 抖动；所有临时运行目录均在 `finally` 中清理。
   - 影响：Sobol/Morris 在高样本数下更稳定，不再出现“输出缺失导致的全 `-99`/`NaN`”情况；若确有异常，后处理会在 `sobol_quality_report.csv` 中给出 NaN 比例并停止出图以便排查。

### 10.3 工具与路径约定（Windows 实际）

- DSSAT 可执行：`C:\DSSAT48\DSCSM048.EXE`
- PEST++（本项目实测版本）：`C:\DSSAT48\Tomato_Cal\pestpp-5.2.16-win\bin\pestpp-sen.exe`
  - 说明：当前环境未将 `pestpp-sen` 加入 PATH，需使用绝对路径或显式调用。

## 11. 当前已落地的可视化产物（科研出版级目标）

### 11.1 当前产物目录

- Morris 默认输出目录（可自定义 `--out-dir`）：`Workspace\Sensitivity_Analyze\SA_Project_Output\morris_results`
- 推荐用于日常审阅的“紧凑型 Dashboard”目录（建议命名）：`Workspace\Sensitivity_Analyze\SA_Project_Output\morris_results_compact`
- 推荐用于深挖诊断的“全量图”目录（建议命名）：`Workspace\Sensitivity_Analyze\SA_Project_Output\morris_results_full`

### 11.2 已实现图表类型（已生成）

为避免“输出图太多”，当前默认采用两档输出：`compact`（默认/推荐）与 `full`（全量）。

1. 紧凑型 Dashboard（`--plot-mode compact`，默认）
   - 总体参数敏感性 Top-N：`morris_overall_top<top_n>.png` 与 `morris_overall_parameter_ranking.csv`
   - 参数 × 指标组（indicator group）热力图（信息密度高，用于回答“参数影响哪些指标”）：`morris_heatmap_param_x_indicator.png/.csv`
   - 时间序列类指标的“参数 × DAP”热力图：仅对最重要的少量 metric 出图（最多 8 个），例如 `morris_heatmap_lai.png/.csv`、`morris_heatmap_fruitd.png/.csv`
   - Morris 非线性/交互迹象（聚合版敏感性 vs 波动）：`morris_scatter_score_vs_sigma.png`
   - 一页式汇总表：`morris_onepage_summary.md`、`morris_onepage_summary.tsv`
   - 追溯用明细：各指标组 Top-N 的表格（不出图，只出 CSV），如 `morris_top20_<indicator_group>.csv`。

2. 全量出图（`--plot-mode full`）
   - 指标组 → 参数 Top-N 条形图：`morris_top<top_n>_<indicator_group>.png/.svg`（同时保留同名 `.csv`）
   - 参数 → 指标组 Top-N 条形图：`morris_param_top<top_n>_indicators_<par>.png/.svg`
   - 其余与紧凑型相同。

关于“指标组（indicator group）”的定义：
- 同一条时间序列不同时间点（例如 `LAI_DAP028/LAI_DAP042/...`）自动合并为一个 `LAI_DAP` 指标组，用于压缩展示维度，避免每个时间点一张 Top-N 图。

## 12. 后续可视化设计（将继续在现有实现上迭代）

出版级标准的关键约束（本项目默认遵循）：

- 提供矢量格式（`svg`）以满足论文排版，且保持一致的字体、字号与线宽。
- 提供统一主题（颜色、网格、坐标刻度、科学计数法显示）。
- 支持“指标→参数”和“参数→指标”两种视角。
- 对时序热力图支持可选缩放（例如 `log1p`、按列标准化），避免少数极端值掩盖结构。

## 13. 使用手册（从零到出图）

本节给出从“生成参数范围 CSV → 构建 Case → 运行 Morris → 后处理出图 → 选 Top-K → 运行 Sobol → 后处理”的可复现操作步骤。

### 13.1 运行前检查（必做）

1. 确认工作根目录：`C:\DSSAT48\Tomato_Cal`。
2. 确认固定输入存在：
   - `Workspace\XXQL2501.TMX`
   - `Workspace\TMGRO048.CUL.base`、`Workspace\TMGRO048.ECO`、`Workspace\TMGRO048.SPE`
   - `Workspace\SOIL.SOL`
   - `Workspace\DSSBatch.v48`（必须为有效内容；至少包含 `XXQL2501.TMX` 的 TRT 条目）
3. 确认可执行文件：
   - DSSAT：`C:\DSSAT48\DSCSM048.EXE`
   - PEST++：`C:\DSSAT48\Tomato_Cal\pestpp-5.2.16-win\bin\pestpp-sen.exe`

### 13.2 第一步：生成参数范围 CSV（审核入口）

在 `C:\DSSAT48\Tomato_Cal` 下执行：

`python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_generate_param_review_csv.py --cultivar TM0008 --ecotype TM0001`

如需指定不同的试验文件或土壤文件：

`python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_generate_param_review_csv.py --cultivar TM0008 --ecotype TM0001 --filex .\Workspace\XXQL2501.TMX --soil .\Workspace\SOIL.SOL`

输出：`Workspace\Sensitivity_Analyze\SA_Project_Output\sensitivity_param_review.csv`

你可以直接编辑该 CSV 的 `lower/upper/status` 来控制参与敏感性分析的参数与范围（后续以该 CSV 为唯一真源）。

### 13.3 第二步：构建敏感性 Case（生成 .pst/.tpl/.ins）

`python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_build_sen_case.py --param-review .\Workspace\Sensitivity_Analyze\SA_Project_Output\sensitivity_param_review.csv --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --cultivar TM0008 --morris-r 10`

主要产物（在 `case-dir` 内）：

- `sa_sen_morris.pst`：Morris 配置
- `sa_sen_sobol.pst`：Sobol 配置（默认全参数；后续可按 Top-K 固定非关键参数）
- `sa_params.csv` / `sa_params.csv.tpl`：参数输入与模板
- `SA_Indicators.OUT.ins`：指标输出解析规则

### 13.4 第三步：运行 Morris（PESTPP-SEN）

推荐用封装脚本运行（会把 stdout/stderr 落盘到 log 文件）：

`python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_run_sen.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --mode morris`

关键输出（在 `case-dir` 内，文件名以实际为准）：

- `sa_sen_morris.mio`：按观测量（指标）×参数的敏感性表
- `sa_sen_morris.rec`：运行记录（可用 finished 时间戳确认完成）

### 13.5 第四步：Morris 后处理与科研出版级图表

推荐优先使用紧凑型 Dashboard（默认 `compact`，只出少量信息密度更高的图，便于快速审阅）：

`python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_postprocess_morris.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --out-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\morris_results_compact --top-n 20 --formats png,svg --dpi 600 --base-font-size 10 --heatmap-percentile 99 --onepage-indicator-top 3 --plot-mode compact`

如需“全量出图”（会产生较多图片，适合深挖诊断）：

`python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_postprocess_morris.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --out-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\morris_results_full --top-n 20 --formats png,svg --dpi 600 --base-font-size 10 --heatmap-percentile 99 --onepage-indicator-top 3 --plot-mode full`

核心产物（在 `out-dir` 内）：

- 总体排序表：`morris_overall_parameter_ranking.csv`
- 总体 Top-N 图：`morris_overall_top<top_n>.png/.svg`
- 参数 × 指标组热力图：`morris_heatmap_param_x_indicator.png/.svg` 与同名 `.csv`
- 时间序列类指标热力图：`morris_heatmap_<metric>.png/.svg` 与同名 `.csv`
- 非线性/交互迹象散点图：`morris_scatter_score_vs_sigma.png/.svg`
- 一页式汇总：`morris_onepage_summary.md`、`morris_onepage_summary.tsv`

推荐审阅顺序（紧凑型 `compact`）：

1. 看 `morris_overall_top<top_n>.png`，锁定关键参数集合。
2. 看 `morris_heatmap_param_x_indicator.png`，理解每个关键参数主要影响哪些指标组。
3. 看 `morris_heatmap_lai.png`、`morris_heatmap_fruitd.png` 等时序热力图，确认敏感性随生育期的变化窗口。
4. 看 `morris_scatter_score_vs_sigma.png`，筛出“高敏感且波动大”的参数，作为后续 Sobol/交互验证重点。

### 13.6 第五步：从 Morris 结果自动选 Top-K 参数（用于 Sobol）

`python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_select_topk_from_morris.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --k 12 --max-total 25 --out .\Workspace\Sensitivity_Analyze\SA_Project_Output\morris_results_compact\topk_params.csv`

输出：`topk_params.csv`（包含参数名与平均重要性得分列，如 `sen_mean_abs_mean`）。

### 13.7 第六步：生成 Sobol Top-K Case（固定非关键参数）

`python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_prepare_sobol_topk_case.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --topk .\Workspace\Sensitivity_Analyze\SA_Project_Output\morris_results_compact\topk_params.csv --samples 200`

输出：覆盖/生成 `case-dir\sa_sen_sobol.pst`（仅 Top-K 参数保持可变，其余参数被固定为初值）。

### 13.8 第七步：运行 Sobol（PESTPP-SEN）

`python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_run_sen.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --mode sobol`

Sobol 的运行次数近似为 `N(2k+2)`，其中 `N` 为 `gsa_sobol_samples`，`k` 为可变参数个数；建议先从较小样本数试跑。

### 13.9 第八步：Sobol 后处理与图表

推荐优先使用紧凑型 Dashboard（默认 `compact`）：

`python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_postprocess_sobol.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --out-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sobol_results_compact --top-n 20 --formats png,svg --dpi 600 --base-font-size 10 --heatmap-percentile 99 --plot-mode compact`

如需全量出图：

`python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_postprocess_sobol.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --out-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sobol_results_full --top-n 20 --formats png,svg --dpi 600 --base-font-size 10 --heatmap-percentile 99 --plot-mode full`

核心产物（在 `out-dir` 内，依据输出中是否包含 `Si/STi` 自动选择列）：

- 原始表：`sobol_raw.csv`
- 质量报告：`sobol_quality_report.csv`（用于快速判断 `Si/STi` 是否存在大量 NaN/无效值）
- 总体排序：`sobol_overall_parameter_ranking_<Si或STi>.csv`
- 指标→参数：`sobol_top20_<indicator>.png/.svg`（以及同名 `.csv`）
- 参数→指标：`sobol_param_top20_indicators_<par>.png/.svg`
- 时序热力图：`sobol_heatmap_<metric>_<Si或STi>.png/.svg` 与同名 `.csv`

如果 `sobol_quality_report.csv` 显示 `Si/STi` 全部为 NaN（例如 `*_sobol.si.csv` 中出现 `-nan(ind)`），后处理会仅输出 `sobol_raw.csv` 与 `sobol_quality_report.csv` 并停止出图，此时需优先排查 Sobol 运行是否有效。

### 13.10 常见问题与排障

1. DSSAT 报 “Error in the format of the batch file”
   - 检查 `Workspace\DSSBatch.v48` 非空且格式正确；条目需指向存在的 FileX（如 `XXQL2501.TMX`）。

2. 指标文件出现 `-99`
   - 通常表示输出缺失或解析失败；确认 `Workspace` 下生成了 `Evaluate.OUT`、`PlantGro.OUT`、`FreshWt.OUT` 等。
   - 若 `Evaluate.OUT` 缺失，确认 `run_dssat.py:1852` 已纳入同步策略。

3. `pyemu` 警告缺少 `flopy`
   - 该警告不影响本项目当前用到的 `pyemu.Pst` 与写入 `.pst` 的功能；可以忽略。

4. `pestpp-sen.exe` 找不到或路径不一致
   - 修改 `Workspace\Sensitivity_Analyze\SA_Project_Code\sa_run_sen.py:41-46` 内的 `exe_path`，或直接在 `case-dir` 用绝对路径调用：
     - `C:\DSSAT48\Tomato_Cal\pestpp-5.2.16-win\bin\pestpp-sen.exe sa_sen_morris.pst`

5. 想增删指标/时间点
   - 修改 `Workspace\Sensitivity_Analyze\SA_Project_Code\sa_build_sen_case.py:_default_observation_names()` 里定义的指标名与 DAP 列表。

## 2. 参数多、如何组织分析（回答问题 1）

本项目采用“两阶段 + 分组”的策略：

### 2.1 第一阶段：全参数筛选（Screening）

目的：在“参数很多”的情况下，用计算量相对可控的方法识别“可能重要”的参数，避免直接对全部参数做高成本方法（如 Sobol）。

建议方法：

- 全参数采用 **Morris（全局一因子法）** 或 **LHS+相关/回归** 的筛选。
- 该阶段默认纳入：SPE/ECO/CUL 所有被标记为“参与校准/需分析”的参数。

输出：对每个指标（以及必要时每个时间点）生成“参数重要性排名”，并标注非线性/交互迹象（如 Morris 的 \(\sigma\) 较大）。

### 2.2 第二阶段：针对关键指标的精细分析（Focused GSA）

目的：对第一阶段筛选出的 Top-K 参数（例如每个指标 Top 8~12）进行更深入的全局敏感性分析。

建议方法：

- 对“关键指标”使用 **Sobol（Saltelli）** 的一阶指数 \(S_i\) 与总效应指数 \(S_{Ti}\)。
- 只对 Top-K 参数做 Sobol，避免计算量爆炸。

### 2.3 为什么不建议“一次把所有参数全部 Sobol”

- Sobol 需要的模型运行次数约为 \(N(2k+2)\)，k 越大成本越高。
- Morris 更适合“参数很多”的先验筛选；Sobol 更适合“少量关键参数”的解释与交互分解。

### 2.4 参数分组（便于管理与汇报）

以文件来源与机理模块分组（用于报表与可视化筛选，不代表必须拆开运行）：

- `SPE_Photosynthesis`：如 `PARMAX`,`PHTMAX`,`KCAN`,`KC_SLOPE` 等
- `SPE_RootWater`：如 `WTFSD`,`PORPT` 等与根系吸水相关参数
- `SPE_SourceSink`：如 `VSSINK` 等
- `SPE_TempStages`：三个时期 `TB/TO1/TO2/TM`
- `ECO_Phenology`：`PL-EM`,`EM-V1`,`V1-JU`,`JU-R0` 等
- `ECO_Architecture`：如 `TRIFL`,`RWDTH`,`RHGHT` 等
- `CUL_PhenologyHarvest`：`EM-FL`,`FL-SH`,`FL-SD`,`SD-PM`,…等

## 3. 指标很多，如何设计让用户快速知道“哪个指标对哪个参数敏感”（回答问题 2）

核心思想：把“输出指标”拆成两类对象，并对每一类都提供统一的敏感性结果视图。

### 3.1 标量指标（Scalar metrics）

适用：果实总产量、最终叶/茎干重等。

设计：

- 每个标量指标作为一个“观测量/预测量”。
- 为每个指标计算：Morris \(\mu^*\)、\(\sigma\)（筛选），以及 Sobol \(S_i\)、\(S_{Ti}\)（精细）。

### 3.2 时序曲线指标（Time-series metrics）

适用：LAI 曲线、果实干重积累曲线。

为兼顾“信息完整”与“结果可读”，提供两种并行表达：

1. **逐时间点敏感性**：把曲线在若干关键时间点（或所有观测日期）拆成多个观测量，输出“参数×时间”的敏感性热力图。
2. **曲线特征敏感性**：把曲线压缩为少量特征（便于跨试验比较与汇报），例如：
   - `peak`：峰值（如最大 LAI）
   - `t_peak`：达到峰值时间（DAP 或 YYDDD）
   - `auc`：曲线面积（生长季累积量）
   - `end`：末期值（成熟/终止时的值）
   - `slope_early`：早期增长斜率（可选）

最终用户视角输出：

- “某指标（例如 LAI）最敏感的参数 Top-N”
- “某参数（例如 VSSINK）对哪些指标最敏感（跨指标排行）”

## 4. 可视化设计（回答问题 3）

### 4.1 面向用户的必做图表

1. **指标→参数条形图（Top-N）**
   - X：参数名；Y：重要性（Morris \(\mu^*\) 或 Sobol \(S_{Ti}\)）
   - 适用：每个标量指标、每个曲线特征

2. **参数→指标雷达/条形图**
   - X：指标；Y：重要性（标准化后）
   - 适用：回答“VSSINK 对哪些指标影响最大”

3. **时间-参数敏感性热力图**
   - 行：参数；列：时间点；色阶：重要性
   - 适用：LAI/果实干重等曲线

4. **散点/回归诊断图（可选）**
   - 参数取值 vs 指标（带 LOESS 或分位数带）
   - 适用：解释非线性与阈值效应

5. **交互迹象图（第二阶段可选）**
   - Sobol \(S_i\) 与 \(S_{Ti}\) 同图；若 \(S_{Ti}-S_i\) 大，提示交互/非线性强。

### 4.2 输出格式

- 静态图片：`png`（快速浏览）
- 矢量图：`svg`（用于报告排版）
- 汇总表：`csv`（可被二次分析）

## 5. 参数范围设定（回答问题 4）

### 5.1 范围设定原则

参数范围采用“默认规则 + 用户可覆盖”的方式：

1. **默认规则**：从当前遗传文件读取 `init`，再按参数类型生成 `lower/upper`。
2. **用户覆盖**：用户在 CSV 中修改 `lower/upper/init/status` 后，后续所有采样与敏感性分析严格以 CSV 为准。

### 5.2 默认范围规则（建议）

按参数类别给出默认区间（最终以 CSV 为准）：

- **比例/系数（0~1）**：默认 \(\pm 30\%\) 相对变化，并裁剪到 [0.0, 1.0]
- **正值率/尺度参数（>0）**：默认 \(\pm 25\%\) 相对变化，且 `lower>0`
- **发育历期（天）**：默认 \(\pm 20\%\) 相对变化，且 `lower>=0`
- **温度阈值（TB/TO1/TO2/TM）**：采用固定合理边界，并加入顺序约束：
  - 约束：`TB < TO1 < TO2 < TM`
  - 推荐默认区间（与现有茄子配置一致）：
    - `TB`：8~12
    - `TO1`：22~28
    - `TO2`：27~32
    - `TM`：33~40

### 5.3 基于现有项目经验的初始边界来源

工作区已有边界字典示例（后续开发可复用并扩展）：

- `Workspace\build_pest.py:18` 的 `ECO_BOUNDS_EGGPLANT`
- `Workspace\build_pest.py:34` 的 `SPE_TEMP_BOUNDS_EGGPLANT`

## 6. 参数范围 CSV（审核入口）（回答问题 5）

在正式敏感性分析前，必须生成一个供用户审核/编辑的 CSV 文件：

### 6.1 CSV 文件位置

- 生成到：`Workspace\Sensitivity_Analyze\SA_Project_Output\sensitivity_param_review.csv`
- 该文件被视为后续所有分析的唯一参数范围来源。

### 6.2 CSV 字段（建议最小集）

| 字段 | 含义 |
| --- | --- |
| `name` | 参数名（与 PEST/采样一致） |
| `init` | 当前值（从遗传文件读取） |
| `lower` | 下界 |
| `upper` | 上界 |
| `status` | `active`/`fixed`（固定参数不参与采样） |
| `pargp` | 参数组（用于汇总与图表筛选） |
| `location` | `SPE`/`ECO`/`CUL` |
| `file` | 对应遗传文件名 |
| `cultivar` | 目标品种编号（如 `TM0007`/`TM0008`，按实际选择） |
| `ecotype` | 目标生态型编号（如 `TM0001`，按实际选择） |
| `mode` | `morris`/`sobol`/`both`（可选，用于控制阶段） |

说明：该字段结构与 `Workspace\build_pest.py:76` 的 `write_param_review_csv()` 兼容，便于复用。

## 7. 方法与工具选型（PESTPP-SEN 优先）（参考 pestpp 手册）

### 7.1 优先方案：PESTPP-SEN

理由：

- PESTPP-SEN 原生支持 Morris 与 Sobol（见 `pestpp_users_manual.md` 第 7 章，含输出文件定义）。
- 可以对 PEST 控制文件中的每个“观测量”（即我们定义的指标/时间点/曲线特征）直接输出敏感性。

关键设计点：

1. 构建一个专用的 `case_sensitivity.pst`：
   - 参数为待分析遗传参数（来自 CSV，带上下界）
   - 观测为各指标（标量/时间点/曲线特征）
2. 使用现有 DSSAT 运行脚本将输出整理成 PEST 可读取的输出文件（如 `PestEval.OUT`/`PestGrow.OUT`/自定义汇总 OUT）。
3. 运行 PESTPP-SEN：
   - 阶段 1：默认 Morris（全参数筛选）
   - 阶段 2：Sobol（Top-K 精细分析）

### 7.2 备选方案：纯 Python 敏感性

当 PESTPP-SEN 不可用或需要更灵活的曲线分析时，使用 Python：

- 采样：LHS 或 Sobol（依赖库可选，若无则实现 LHS+PRCC 作为替代）
- 模型运行：调用 `Workspace\run_dssat.py` 并写入遗传文件
- 指标提取：解析 `PlantGro.OUT`/`FreshWt.OUT`/`Summary.OUT`
- 敏感性：Spearman/PRCC、线性回归 SRC、随机森林重要性（可选）

## 8. 文件夹与交付物（回答问题 7/8/9）

### 8.1 本项目目录（均在 `Workspace\Sensitivity_Analyze` 下）

- 开发文档：`Workspace\Sensitivity_Analyze\SA_Project_Docs\`
- 输出内容：`Workspace\Sensitivity_Analyze\SA_Project_Output\`

### 8.2 本阶段（文档评审阶段）的交付物

1. 本设计文档（当前文件）
2. 审核清单（在本文“9. 审核要点”中）

说明：原计划为“文档评审后再开发”，但当前项目已进入可运行与可视化迭代阶段；本节内容保留作为项目设计依据。

## 9. 审核要点（请您重点确认）

1. **参数范围策略**：是否接受“全参数 Morris 筛选 + Top-K Sobol 精细”的两阶段方案。（接受）
2. **指标集合**：除 LAI、果实干重曲线、总产量、茎干重、叶干重外，是否还需要纳入：开花期/成熟期（发育指标）、地上总生物量、收获指数等。（纳入）
3. **曲线表达**：LAI/果实干重是否需要“逐时间点热力图 + 曲线特征”两套并行输出。（并行输出）
4. **目标品种/生态型**：敏感性分析默认锁定哪条记录（品种为TM0008 Brilliance）。
5. **输出组织**：图表与汇总 CSV 的命名与目录结构是否满足您的归档习惯。（满足）
