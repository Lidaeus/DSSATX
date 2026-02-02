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
- [0 基线检查](#0-基线检查)
- [1 构建率定任务](#1-构建率定任务)
- [2 运行 PEST++ IES](#2-运行-pest-ies)
- [3 后处理与最优参数导出](#3-后处理与最优参数导出)
- [4 确定性模拟与论文级指标表](#4-确定性模拟与论文级指标表)
- [5 一键出图](#5-一键出图)
- [6 手动微调最优参数并出图](#6-手动微调最优参数并出图)
- [7 权重策略 方案A 早期采收增量加权](#7-权重策略-方案a-早期采收增量加权)
- [8 SPE 中与低氮耐受相关的参数](#8-spe-中与低氮耐受相关的参数)
- [常见问题与定位](#常见问题与定位)

## 核心约定

- `prefix`：一次任务的唯一名称，建议包含阶段/日期/策略，例如 `eggplant_stage2_v12_yieldfocus`
- `run_dir`：构建输出目录（包含 `.pst/.tpl/.ins` 与参数模板），建议：`Workspace\Calibration_Results\_runs\<timestamp>_<prefix>`
- `det_dir`：确定性模拟目录（用某一套参数跑 DSSAT，用于出图/指标表），建议：`Workspace\Calibration_Results\_det\<prefix>_best`

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

python build_pest.py \
  --mode eggplant_stage2 \
  --prefix $prefix \
  --noptmax 6 \
  --ies-num-reals 80 \
  --batch DSSBatch.v48 \
  --harvest-var CHPDT \
  --param-review-mode off \
  --bounds-review-mode require \
  --bounds-review-csv "Sensitivity_Analyze\SA_Project_Output\sensitivity_param_review.csv" \
  --tighten-from "C:\DSSAT48\Tomato_Cal\Workspace\Calibration_Results\eggplant_stage2_v11_tight5_best_parameters_fixed.csv" \
  --tighten-frac 0.10 \
  --pwadm-sigma0 120 \
  --pwadm-cv 0.05 \
  --pwadm-sigma-factor 0.25 \
  --hiamm-sigma 0.25 \
  --hwamm-sigma 250 \
  --pwamm-sigma 150 \
  --out-dir $runDir
```

成功标志：输出 `PST file written to ...\{prefix}.pst`。

提示：`eggplant_stage2` 默认将 `KC_SLOPE`、`VSSINK` 纳入率定参数集。

## 2 运行 PEST++ IES

```powershell
cd $runDir
..\..\..\pestpp-5.2.16-win\bin\pestpp-ies.exe "$prefix.pst"
```

以 `.rec/.log` 中的 error/fail 与命令返回码判断是否成功。

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
python "C:\DSSAT48\Tomato_Cal\Workspace\run_dssat.py" \
  --param-csv "C:\DSSAT48\Tomato_Cal\Workspace\Calibration_Results\${prefix}_best_parameters_fixed.csv" \
  --batch "C:\DSSAT48\Tomato_Cal\Workspace\DSSBatch.v48" \
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

如需把根系供氮能力参数纳入率定（推荐放在 `eggplant_stage2` 阶段，且在物候已基本稳定后再引入），构建时加入：

```powershell
python build_pest.py --mode eggplant_stage2 --include-n-uptake ...
```

默认范围（可在 `bounds_review_csv` 中进一步收紧）：

- `RTNO3`: 0.006–0.030
- `RTNH4`: 0.006–0.030
- `RTEXF`: 0.05–0.25

## 常见问题与定位

- `build_pest.py` 提示找不到 `Evaluate.OUT`：DSSAT 有时会把 `Evaluate.OUT` 写到 `C:\DSSAT48\Evaluate.OUT`，构建阶段会自动在 `Workspace` 与 `C:\DSSAT48` 两处尝试读取。
- `PestHarvest.OUT` 里缺少 `@PWAIS@`：先运行一次 `python run_dssat.py ...` 以刷新输出文件，再重新 build。
- DSSAT 报 `ERROR - Invalid initial conditions date in file XXQL2501.TMX`：检查 `*INITIAL CONDITIONS` 的 `ICDAT` 是否为有效 `YYDDD`。
- `.ins` 报 `marker search failure`：检查对应 `Pest*.OUT` 的变量标签是否齐全、顺序是否稳定。
- 指标表为空或只有表头：多半是 `DSSBatch.v48` 指向的 TN 与 `*.TMT` 观测不匹配，或 `--run-dir` 指错。
