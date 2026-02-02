# DSSAT × PEST++ 自动化率定系统（茄子为主）

本项目将 DSSAT v4.8 的作物模型（当前以茄子试验为主，作物文件基于 TMGRO048）与 PEST++（IES）连接，实现遗传参数与关键环境/初始条件的自动化率定，并提供确定性模拟、论文级评价表与图表输出。

本 README 以“用户可以照着一步步做”为目标，给出两条路径：

1) 完整率定：build → pestpp-ies → analyze → 确定性模拟 → 指标表/出图
2) 手动微调：在最优参数基础上人工修改 → 直接跑确定性模拟并出图（不跑 PEST）

## 环境要求

- Windows 10/11
- DSSAT v4.8（默认安装路径 `C:\DSSAT48`）
- Python 3.8+（本项目脚本依赖：`pandas`, `numpy`, `pyemu`, `matplotlib`）
- PEST++ 已打包在 `pestpp-5.2.16-win` 目录

建议在工作目录安装依赖：

```powershell
cd C:\DSSAT48\Tomato_Cal\Workspace
pip install pandas numpy pyemu matplotlib
```

## 目录

- [核心约定](#核心约定)
- [你在“率定”什么（3 分钟理解版）](#你在率定什么3-分钟理解版)
- [0 基线检查](#0-基线检查)
- [1 构建率定任务](#1-构建率定任务)
- [2 运行 PEST++ IES](#2-运行-pest-ies)
- [3 后处理与最优参数导出](#3-后处理与最优参数导出)
- [4 确定性模拟与论文级指标表](#4-确定性模拟与论文级指标表)
- [5 一键出图](#5-一键出图)
- [6 手动微调最优参数并出图](#6-手动微调最优参数并出图)
- [7 权重策略 方案A 早期采收增量加权](#7-权重策略-方案a-早期采收增量加权)
- [8 SPE 中与低氮耐受相关的参数](#8-spe-中与低氮耐受相关的参数)
- [9 关键生理参数速查](#9-关键生理参数速查)
- [并行运行（方案A：PEST++ manager/agent）](#并行运行方案apest-manageragent)
- [常见问题与定位](#常见问题与定位)

## 核心约定

- `prefix`：一次任务的唯一名称，建议包含阶段/日期/策略，例如 `eggplant_stage2_v12_yieldfocus`
- `run_dir`：构建输出目录（包含 `.pst/.tpl/.ins` 与参数模板），建议：`Workspace\Calibration_Results\_runs\<timestamp>_<prefix>`
- `det_dir`：确定性模拟目录（用某一套参数跑 DSSAT，用于出图/指标表），建议：`Workspace\Calibration_Results\_det\<prefix>_best`

## 你在“率定”什么（3 分钟理解版）

本项目以 DSSAT 的 Tomato 作物文件（`TMGRO048.*`）承载“茄子化”的参数体系。PEST++（IES）做的事情本质是：

1) 生成一批候选参数集合（ensemble）
2) 对每个集合跑一次 DSSAT（前向模型）
3) 用观测-模拟残差计算目标函数（phi）并更新下一轮 ensemble

在 `eggplant_stage2` 里，目标函数同时包含 4 类观测：

- 物候（来自 `Evaluate.OUT → PestEval.OUT`，例如 `ADAPM`）
- 季末生长/产量综合指标（来自 `Evaluate.OUT/PlantGro.OUT → PestJoint.OUT`）
- 多次采收曲线（来自 `FreshWt.OUT → PestHarvest.OUT`，按采收事件对齐）
- 过程点（来自 `PlantGro.OUT → PestTmtGrow.OUT`，按采样日期对齐）

评价表默认输出 `RMSE / NRMSE / d-index`（总体与分 TN/TRNO），用于识别 Genotype-by-environment interaction 的残差结构。

## 0 基线检查

目的：确认 DSSAT IO、批处理、观测文件路径都通。

```powershell
cd C:\DSSAT48\Tomato_Cal\Workspace
python run_dssat.py --param-csv baseline_params.csv --batch DSSBatch.v48 --harvest-var CHPDT
```

看到 `Evaluate.OUT generated successfully.` 即通过。

## 1 构建率定任务

以 `eggplant_stage2` 为主（包含物候、植株生长、采收曲线、关键综合指标）。

```powershell
cd C:\DSSAT48\Tomato_Cal\Workspace

$prefix = "eggplant_stage2_v12_yieldfocus"
$runDir = "C:\DSSAT48\Tomato_Cal\Workspace\Calibration_Results\_runs\20260201_$prefix"

python build_pest.py `
  --mode eggplant_stage2 `
  --prefix $prefix `
  --noptmax 6 `
  --ies-num-reals 80 `
  --batch DSSBatch.v48 `
  --harvest-var CHPDT `
  --param-review-mode off `
  --bounds-review-mode require `
  --bounds-review-csv "Sensitivity_Analyze\SA_Project_Output\sensitivity_param_review.csv" `
  --tighten-from "C:\DSSAT48\Tomato_Cal\Workspace\Calibration_Results\eggplant_stage2_v11_tight5_best_parameters_fixed.csv" `
  --tighten-frac 0.10 `
  --pwadm-sigma0 120 `
  --pwadm-cv 0.05 `
  --pwadm-sigma-factor 0.25 `
  --hiamm-sigma 0.25 `
  --hwamm-sigma 250 `
  --pwamm-sigma 150 `
  --out-dir $runDir
```

成功标志：输出 `PST file written to ...\{prefix}.pst`。

提示：`eggplant_stage2` 默认将 `KC_SLOPE`、`VSSINK`、以及根系供氮参数（`RTNO3/RTNH4/RTEXF`）纳入率定参数集。

### build_pest.py 关键参数含义（按你最常改的顺序）

- `--noptmax`：IES 外循环迭代次数上限。调大不一定更好，建议先用 5–8 做稳定性测试。
- `--ies-num-reals`：ensemble 大小，越大越稳但越慢。发表级不确定性建议 `>=100`。
- `--batch`：DSSAT 批运行文件（决定试验文件与 TN/TRNO 集合）。
- `--harvest-var CHPDT|CHFPW`：多次采收口径（干重累计/鲜重累计），贯穿到 `PestHarvest.OUT`。
- `--bounds-review-*`：用敏感性分析生成的 `sensitivity_param_review.csv` 约束“哪些参数允许进入率定 + 默认边界”。
- `--tighten-from/--tighten-frac`：围绕上一版最优参数收缩可行域，提升可识别性、减少等价解。
- `--pwadm-sigma0/--pwadm-cv/--pwadm-sigma-factor`：多次采收（累计/增量）观测的权重体系。
- `--hwamm-sigma/--pwamm-sigma/--hiamm-sigma/...`：各观测组（obs group）的权重（权重=1/sigma^2）。

## 2 运行 PEST++ IES

## 并行运行（方案A：PEST++ manager/agent）

目标：并行跑 DSSAT 前向（IES / SEN 均适用），在不改动率定算法的前提下显著加速。

原则：每个并行 worker 必须在独立目录运行，避免 DSSAT 输出互相覆盖。

### 1) 为某个 run_dir 准备 agent 目录与脚本

在仓库根目录执行：

```powershell
cd C:\DSSAT48\Tomato_Cal

$runDir = "C:\DSSAT48\Tomato_Cal\Workspace\Calibration_Results\_runs\20260202_eggplant_stage2_v13_rootN_incEarly9"
$case = "eggplant_stage2_v13_rootN_incEarly9"

python tools\parallel\prepare_agents.py --run-dir $runDir --case $case --n-agents 6 --port 4010
```

如果不指定 `--n-agents/--port`，脚本将自动设置：

- `n_agents = max(1, CPU核心数-2)`
- `port = 4010..4999` 中的可用端口

成功后会在 `$runDir` 下生成：

- `_agents\agent_01..agent_06\`（每个 agent 一个独立工作目录）
- `start_agents.ps1` / `start_manager.ps1`（IES 并行启动脚本）
- `stop_agents.ps1` / `stop_manager.ps1` / `clean_agents.ps1`
- `start_sen_agents.ps1` / `start_sen_manager.ps1`（SEN 并行启动脚本）
- `stop_sen_agents.ps1` / `stop_sen_manager.ps1` / `clean_sen_agents.ps1`

日志与 PID：

- agent：`_agents\agent_*\panther_agent.stdout.log|stderr.log` 与 `panther_agent.pid`
- manager：`panther_manager.stdout.log|stderr.log` 与 `panther_manager.pid`

### 2) 启动 IES 并行

在 `$runDir` 下先启动 agents（会启动多个 pestpp-ies 进程）：

```powershell
cd $runDir
powershell -ExecutionPolicy Bypass -File .\start_agents.ps1
```

然后启动 manager（默认阻塞运行直到结束；也可用 `-Wait:$false` 后台运行）：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_manager.ps1 -Wait
```

停止与清理：

```powershell
powershell -ExecutionPolicy Bypass -File .\stop_manager.ps1
powershell -ExecutionPolicy Bypass -File .\stop_agents.ps1
powershell -ExecutionPolicy Bypass -File .\clean_agents.ps1
```

## 3 后处理与最优参数导出

```powershell
cd C:\DSSAT48\Tomato_Cal\Workspace
python analyze_results.py --prefix $prefix --run-dir $runDir
```

核心输出（默认都在 `Workspace\Calibration_Results\`）：

- `{prefix}_best_parameters_fixed.csv`：最优参数（用于确定性模拟）
- `{prefix}_bound_hits.csv`：贴边界证据（用于 tighten 或范围修订）
- `{prefix}_error_diag.csv`：残差诊断表
- `{prefix}_parameter_uncertainty.csv`：参数集合统计

## 4 确定性模拟与论文级指标表

```powershell
cd C:\DSSAT48\Tomato_Cal\Workspace

$detDir = "C:\DSSAT48\Tomato_Cal\Workspace\Calibration_Results\_det\${prefix}_best"
New-Item -ItemType Directory -Force -Path $detDir | Out-Null

cd $detDir
python "C:\DSSAT48\Tomato_Cal\Workspace\run_dssat.py" `
  --param-csv "C:\DSSAT48\Tomato_Cal\Workspace\Calibration_Results\${prefix}_best_parameters_fixed.csv" `
  --batch "C:\DSSAT48\Tomato_Cal\Workspace\DSSBatch.v48" `
  --harvest-var CHPDT

cd C:\DSSAT48\Tomato_Cal\Workspace
python analyze_results.py --metrics-grid --prefix $prefix --run-dir $detDir --batch DSSBatch.v48 --out "${prefix}_metrics_grid.csv"
```

指标表输出 `RMSE / NRMSE / d-index`，推荐同时报告总体与分 TRNO 结果，用于讨论 Genotype-by-environment interaction 的残差结构。

## 5 一键出图

```powershell
cd C:\DSSAT48\Tomato_Cal\Workspace
python plot_results.py --prefix $prefix
```

图表目录：`Workspace\Calibration_Results\plots\{prefix}\`。

## 6 手动微调最优参数并出图

目标：不跑 PEST，只在最优参数基础上人工微调（例如让前期采收更早、叶面积更快等），并快速生成指标表与图。

步骤：

1) 复制一份参数文件作为手动版本

```powershell
cd C:\DSSAT48\Tomato_Cal\Workspace

$base = "Calibration_Results\${prefix}_best_parameters_fixed.csv"
$manual = "Calibration_Results\${prefix}_manual_tuned.csv"
Copy-Item $base $manual -Force
```

2) 用 Excel/文本编辑器打开 `${prefix}_manual_tuned.csv`，修改 `value` 列

3) 用手动参数跑确定性模拟

```powershell
$detDir = "C:\DSSAT48\Tomato_Cal\Workspace\Calibration_Results\_det\${prefix}_manual"
New-Item -ItemType Directory -Force -Path $detDir | Out-Null

cd $detDir
python "C:\DSSAT48\Tomato_Cal\Workspace\run_dssat.py" --param-csv "C:\DSSAT48\Tomato_Cal\Workspace\$manual" --batch "C:\DSSAT48\Tomato_Cal\Workspace\DSSBatch.v48" --harvest-var CHPDT

cd C:\DSSAT48\Tomato_Cal\Workspace
python analyze_results.py --metrics-grid --prefix "${prefix}_manual" --run-dir $detDir --batch DSSBatch.v48 --out "${prefix}_manual_metrics_grid.csv"
python plot_results.py --prefix "${prefix}_manual"
```

这样你会得到一套新的 `metrics_grid.csv` 与图表目录 `plots\{prefix}_manual\`，用于快速迭代。

## 7 权重策略 方案A 早期采收增量加权

背景：仅用累计采收（cum）容易掩盖“采收启动偏晚/前几次采收为 0”的结构性偏差。方案 A 的目标是：在目标函数中显式提高早期采收增量（inc）的权重，从而让优化主动把采收曲线左移。

实现方式：构建阶段对采收观测分组（按 HNO）设置 sigma，权重为 `1/sigma^2`。对早期 HNO（例如 1–4）将 sigma 乘以 `weight_factor^(-0.5)`，等价于把权重放大 `weight_factor`。

可用参数：

- `--harvest-early-hno-max 4`：早期采收的最大 HNO
- `--harvest-early-weight-factor 9`：权重放大倍数（例：9 倍）
- `--harvest-early-apply-to inc`：只对增量加权（可选：`inc/cum/both`）

示例（建议用于“前期采收偏低”的问题定位）：

```powershell
python build_pest.py --mode eggplant_stage2 --prefix $prefix --noptmax 6 --ies-num-reals 80 --batch DSSBatch.v48 --harvest-var CHPDT --param-review-mode off --bounds-review-mode require --bounds-review-csv "Sensitivity_Analyze\SA_Project_Output\sensitivity_param_review.csv" --harvest-early-hno-max 4 --harvest-early-weight-factor 9 --harvest-early-apply-to inc --out-dir $runDir
```

## 8 SPE 中与低氮耐受相关的参数

你使用托鲁巴姆嫁接苗（砧木更耐贫瘠/低氮），在 DSSAT 的物种参数文件 `TMGRO048.SPE` 中，存在几类与“低氮适应性/氮胁迫响应”相关的参数（并非只有一个“临界氮浓度”参数，而是通过吸收能力、叶 N 对光合响应、N 动员等模块共同体现）。

在本项目的 `TMGRO048.SPE.base` 中，推荐优先关注：

- 氮吸收与根系吸收能力：`RNO3C`, `RNH4C`, `RTNO3`, `RTNH4`, `RTEXF`
- 叶氮对光合的响应函数：`FNPGN1-4`（对应 SPE 中 `FNPGN(4)` 的 4 个值）
- 叶氮与比叶重/光合关联参数：`NSLOPE`, `LNREF`, `PGREF`
- 氮动员能力（影响缺氮期对生长/采收的缓冲）：`NMOBMX`, `NVSMOB`, `NRCVR`

手动修改方法（不跑 PEST 也可验证）：

1) 在你的参数 csv（例如 `${prefix}_manual_tuned.csv`）里新增/修改这些键的值
2) 按 [手动微调最优参数并出图](#6-手动微调最优参数并出图) 运行一次确定性模拟

脚本会把这些键写入 `TMGRO048.SPE`，从而在模拟中体现砧木特性。

根系供氮能力参数在本项目中默认启用（`eggplant_stage2` 默认包含 `RTNO3/RTNH4/RTEXF`）。如需临时关闭，构建时加入：

```powershell
python build_pest.py --mode eggplant_stage2 --no-include-n-uptake ...
```

默认范围（可在 `bounds_review_csv` 中进一步收紧）：

- `RTNO3`: 0.010–0.050
- `RTNH4`: 0.010–0.050
- `RTEXF`: 0.05–0.25

补充约束：

- `XFINT` 已强制约束在 `0.12–0.50`（并满足 `<=1.0`），以规避 `IPDMND` 风险并减少不可解释的早期分配极端值。
- `FL-VS` 为固定常数（默认 100），不作为率定参数进入搜索空间。

## 9 关键生理参数速查

以下是你在 `eggplant_stage2` 最常需要解释/讨论的一组参数（按论文写作友好度排序）。

- 物候与 Thermal time
  - `EM-FL/FL-SH/FL-SD/SD-PM/FL-LF`：用 photothermal time / thermal time 表达的阶段持续时间（决定开花、坐果、成熟的时间轴）。
  - `CSDL/PPSEN`：光周期响应参数（控制日长效应与环境适应性）。
- 碳分配与采收曲线
  - `XFINT`：早期向果实分配的初始比例，影响“采收启动”与前段 harvest curve 形态（本项目已限定 `0.12–0.50`）。
  - `XFRT`：分配/库强相关上限参数，主要影响 harvest_total 与后段潜力。
  - `PODUR`：达到最终果负载所需的热时尺度，决定“前期集中/后期拉长”的季节分布。
  - `XFPHT`：分配达到峰值所需的光热时间尺度，常用于缓解“前高后低/前低后高”的结构性偏差。
- 冠层与源强
  - `LFMAX/SLAVR/SIZLF`：叶光合潜力与比叶面积/叶片尺度，决定 LAI 动力学与源强上限。
  - `TRIFL`：叶片出现速率（叶序形成），决定 LAI 上升速率与早期冠层建立。
- 根系供氮与 N uptake（默认启用）
  - `RTNO3/RTNH4`：根系对 NO3/NH4 的吸收能力标度参数（默认边界 `0.010–0.050`）。
  - `RTEXF`：根系吸收相关的效率/扩展因子（影响吸收对环境的响应幅度）。

## 常见问题与定位

- `build_pest.py` 提示找不到 `Evaluate.OUT`：DSSAT 有时会把 `Evaluate.OUT` 写到 `C:\DSSAT48\Evaluate.OUT`，构建阶段会自动在 `Workspace` 与 `C:\DSSAT48` 两处尝试读取。
- `PestHarvest.OUT` 里缺少 `@PWAIS@`：先运行一次 `python run_dssat.py ...` 以刷新输出文件，再重新 build。
- DSSAT 报 `ERROR - Invalid initial conditions date in file XXQL2501.TMX`：检查 `*INITIAL CONDITIONS` 的 `ICDAT` 是否为有效 `YYDDD`。
- `.ins` 报 `marker search failure`：检查对应 `Pest*.OUT` 的变量标签是否齐全、顺序是否稳定。
- 指标表为空或只有表头：多半是 `DSSBatch.v48` 指向的 TN 与 `*.TMT` 观测不匹配，或 `--run-dir` 指错。
