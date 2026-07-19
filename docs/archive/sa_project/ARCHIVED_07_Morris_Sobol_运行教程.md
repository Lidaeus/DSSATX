# Morris/Sobol 运行与指标排名/热力图教程（DSSAT 茄子模型）

本教程面向 DSSAT 茄子模型的敏感性分析流程，覆盖从参数准备到 Morris/Sobol 运行与可视化产物生成的全链路步骤。强调“可复现、可扩展、可解释”，并给出参数含义、设置建议、背景知识与常见坑的解决办法。

## 1. 背景知识速览（用于结果解释，不做基础科普）

- **Morris（全局一因子筛选）**：适合高维参数的快速筛选，用于识别高敏参数与潜在非线性/交互（通过敏感性均值与波动幅度）。
- **Sobol（Saltelli）**：提供一阶指数 Si 与总效应指数 STi，适合对 Top-K 参数的精细解释与交互识别。
- **Thermal time** 与物候控制：温度阈值类参数（TB/TO/TM）往往在物候、LAI 与产量指标上表现敏感。
- **Genotype-by-environment interaction**：同一参数在不同处理/环境下的敏感性结构可能显著变化，需结合 TN/处理维度或 MEAN_ 指标综合判断。
- **Sensitivity analysis 与标定衔接**：敏感性排序用于参数标定优先级，不直接替代标定；标定评价标准以 RMSE、NRMSE、d-index 为主。

## 2. 全流程步骤（从零到出图）

### 2.1 生成参数清单（参数范围与状态）

```powershell
python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_generate_param_review_csv.py --cultivar TM0008 --ecotype TM0001
```

可选参数：

- `--cultivar`：目标品种编号（CUL）。
- `--ecotype`：目标生态型编号（ECO）。
- `--filex`：指定试验 FileX（TMX/TMA/TMT），用于解析处理结构。
- `--soil`：指定土壤文件（SOL），用于土壤参数与 IC 范围解析。

产物：

- `Workspace\Sensitivity_Analyze\SA_Project_Output\sensitivity_param_review.csv`

你可以手工编辑 `lower/upper/status`：

- `status=active`：进入敏感性分析
- `status=fixed`：固定参数（不参与）

### 2.2 构建敏感性 Case（生成 .pst/.tpl/.ins）

```powershell
python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_build_sen_case.py --param-review .\Workspace\Sensitivity_Analyze\SA_Project_Output\sensitivity_param_review.csv --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --cultivar TM0008 --morris-r 100
```

参数说明：

- `--param-review`：参数范围 CSV 的路径（唯一真源）。
- `--case-dir`：case 输出目录。建议每次大规模运行新建独立目录便于追踪。
- `--cultivar`：目标品种编号。
- `--morris-r`：Morris 轨迹数（推荐 100 作为大规模筛选起点）。
- `--morris-p`：Morris 轨迹划分水平数（整数，通常用默认）。
- `--morris-delta`：步长（可选，默认由 PEST++ 处理）。

主要产物：

- `sa_sen_morris.pst`：Morris 配置
- `sa_sen_sobol.pst`：Sobol 配置（默认全参数）
- `sa_params.csv` / `sa_params.csv.tpl`
- `SA_Indicators.OUT.ins`

### 2.3 运行 Morris（PESTPP-SEN）

```powershell
python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_run_sen.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --mode morris
```

参数说明：

- `--case-dir`：Morris case 目录
- `--mode`：`morris` 或 `sobol`

关键输出：

- `sa_sen_morris.mio`
- `sa_sen_morris.rec`

### 2.4 Morris 后处理与热力图

```powershell
python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_postprocess_morris.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --out-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\morris_results_compact --top-n 20 --formats png,svg --dpi 600 --base-font-size 10 --heatmap-percentile 99 --onepage-indicator-top 3 --plot-mode compact
```

参数说明：

- `--out-dir`：输出目录（推荐 `morris_results_compact`）
- `--top-n`：排名与热力图使用的参数数量
- `--formats`：图像格式（建议 `png,svg`）
- `--dpi`：分辨率（建议 600）
- `--base-font-size`：基础字号
- `--heatmap-percentile`：热力图截断上限百分位，用于抑制极值
- `--onepage-indicator-top`：一页式汇总中每个指标组列出参数数
- `--plot-mode`：`compact` 或 `full`

核心产物：

- `morris_overall_parameter_ranking.csv`
- `morris_heatmap_param_x_indicator.png/.svg`
- `morris_heatmap_<metric>.png/.svg`
- `morris_scatter_score_vs_sigma.png/.svg`

### 2.5 选取 Top-K 参数（用于 Sobol）

```powershell
python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_select_topk_from_morris.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --k 12 --max-total 15 --cum-threshold 0.88 --interaction-ratio 1.0 --out .\Workspace\Sensitivity_Analyze\SA_Project_Output\morris_results_compact\topk_params.csv --out-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\morris_results_compact --formats png,svg --dpi 600 --base-font-size 10
```

参数说明：

- `--k`：每个指标组最多保留的参数数
- `--max-total`：全局最多保留的参数数（建议 10–15）
- `--cum-threshold`：指标内累计贡献阈值（建议 0.85–0.90）
- `--interaction-ratio`：交互补偿阈值（σ/μ*），建议 1.0
- `--out`：输出 Top-K CSV
- `--out-dir`：图表与说明输出目录
- `--formats`：图像格式
- `--dpi`：分辨率
- `--base-font-size`：基础字号

新增产物：

- `morris_topk_elbow.png/.svg`：肘部图
- `morris_topk_cum_contribution.png/.svg`：累计贡献曲线
- `morris_topk_interaction_reclaimed.csv`：交互捞回清单（σ/μ* 高但被指标内阈值剔除者）
- `morris_topk_method_summary.md`：论文方法学与审稿答复标准化说明

### 2.6 生成 Sobol Top-K Case（大规模样本）

```powershell
python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_prepare_sobol_topk_case.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --topk .\Workspace\Sensitivity_Analyze\SA_Project_Output\morris_results_compact\topk_params.csv --samples 1000
```

参数说明：

- `--samples`：Sobol 样本数 N（推荐大规模从 1000 起）

Sobol 运行次数近似为 `N(2k+2)`，k 为可变参数数。

### 2.7 运行 Sobol（PESTPP-SEN）

```powershell
python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_run_sen.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --mode sobol
```

### 2.8 Sobol 后处理与热力图

```powershell
python .\Workspace\Sensitivity_Analyze\SA_Project_Code\sa_postprocess_sobol.py --case-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sen_case --out-dir .\Workspace\Sensitivity_Analyze\SA_Project_Output\sobol_results_compact --top-n 20 --formats png,svg --dpi 600 --base-font-size 10 --heatmap-percentile 99 --plot-mode compact
```

核心产物：

- `sobol_overall_parameter_ranking.csv`
- `sobol_heatmap_param_x_indicator_STi.png/.svg`
- `sobol_heatmap_<metric>_STi.png/.svg`
- `sobol_quality_report.csv`

## 3. 参数如何设置（策略建议）

### 3.1 Morris 轨迹数与 Sobol 样本数

- Morris：`r=100` 适合“高维参数筛选 + 高稳定性排序”
- Sobol：`N=1000` 适合 Top-K 精细分解（计算量大，需算力保障）

### 3.2 Top-K 策略

- 采用“指标内累计贡献阈值 + 交互补偿 + 全局上限”的三层漏斗
- 累计贡献建议 0.85–0.90，可配合肘部图与累计贡献曲线确认拐点
- 交互补偿建议 σ/μ* ≥ 1.0，避免遗漏强非线性参数
- 当指标组数量多时优先限制 `max-total`，避免 Sobol 计算爆炸

### 3.3 指标时间序列设置

- DAP 序列过密会放大计算成本并稀释主信号
- 推荐以关键生育期节点（如 LAI_peak、FRUITD_end）为主

## 4. 可能会用到的背景知识补充

- **Parameter identifiability**：敏感性高不等于可辨识，仍需结合观测信息量与相关性结构。
- **Nonlinearity & interaction**：Morris 的 `sigma` 高通常提示非线性/交互强；Sobol 的 STi-Si 差异可量化交互贡献。
- **Physiology linkage**：Thermal time 控制物候与器官分配窗口；光合与冠层扩展参数影响干物质积累与 LAI 曲线形态。

## 5. 常见坑与处理方案

1. **DSSBatch.v48 为空或格式错误**
   - 现象：DSSAT 报 “Error in the format of the batch file”
   - 处理：确保 `Workspace\DSSBatch.v48` 非空且指向有效 FileX

2. **输出出现 -99 或 NaN**
   - 现象：`SA_Indicators.OUT` 中大量 `-99`，Sobol 质量报告 NaN 比例高
   - 处理：确认 `Evaluate.OUT` 被同步，且 `run_dssat.py` 已纳入同步策略

3. **pestpp-sen.exe 路径问题**
   - 处理：保证 `C:\DSSAT48\Tomato_Cal\pestpp-5.2.16-win\bin\pestpp-sen.exe` 存在

4. **Sobol 计算量过大**
   - 处理：降低 Top-K 或 N；优先保持关键指标组

5. **日志文件占用提示**
   - 现象：`Log file is already in use`
   - 处理：不影响产物生成，确认 `*.rec` finished 时间戳即可

## 6. 推荐阅读与结果解读入口

- Morris 解读：[04_Morris_结果解读.md](file:///c:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Docs/04_Morris_结果解读.md)
- Sobol 解读：[05_Sobol_结果解读.md](file:///c:/DSSAT48/Tomato_Cal/Workspace/Sensitivity_Analyze/SA_Project_Docs/05_Sobol_结果解读.md)
