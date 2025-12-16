# DSSAT-PEST 番茄模型自动化率定系统

本项目旨在通过连接 **DSSAT (Decision Support System for Agrotechnology Transfer)** 作物模型与 **PEST++ (Parameter ESTimation)** 优化引擎，实现番茄 (Tomato) 作物模型参数的自动化率定。

该系统能够自动调整 DSSAT 的品种参数 (`.CUL` 文件)，以最小化模拟值与实测值（如产量、生物量、物候期）之间的误差。

## 📋 目录
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [关键文件说明](#关键文件说明)
- [结果解读](#结果解读)

## 🛠 环境要求

在使用本系统前，请确保您的环境满足以下要求：

1.  **操作系统**: Windows 10/11
2.  **DSSAT**: 已安装 DSSAT v4.8 (默认路径 `C:\DSSAT48`)
3.  **Python**: Python 3.8+
    - 依赖库: `pandas`, `pyemu`
    ```bash
    pip install pandas pyemu
    ```
4.  **PEST++**: 已内置于 `pestpp-5.2.16-win` 目录下，无需单独安装。

## 🚀 快速开始

### 第一步：构建 PEST 控制文件
进入工作目录并运行构建脚本。此步骤会读取 DSSAT 的输出模板和观测数据，生成 PEST 所需的 `.pst` 控制文件。

```powershell
cd C:\DSSAT48\Tomato_Cal\Workspace
python build_pest.py
```

*成功提示*: 脚本将输出 `PST file written to ...\tomato_cal.pst`。

### 第二步：运行率定 (串行模式)
使用 PEST++ 的迭代集合平滑算法 (IES) 进行参数优化。由于计算量较小，默认使用串行模式。

```powershell
..\pestpp-5.2.16-win\bin\pestpp-ies.exe tomato_cal.pst
```

*运行过程*: 
- PEST 会多次调用 `run_dssat.py`。
- 每次调用都会更新 `TMGRO048.CUL` 参数 -> 运行 DSSAT -> 提取结果。
- 屏幕将显示每一次迭代的目标函数 (Phi) 变化。

## 📂 项目结构

```
C:\DSSAT48\Tomato_Cal\
├── Workspace/                 # 核心工作目录
│   ├── build_pest.py          # [脚本] 构建 PEST 控制文件
│   ├── run_dssat.py           # [脚本] 模型运行接口 (Model Wrapper)
│   ├── TMGRO048.CUL.base      # [模板] 品种参数基准文件
│   ├── Evaluate.OUT           # [输出] DSSAT 模拟结果缓存
│   ├── tomato_cal.pst         # [配置] PEST 主控制文件
│   └── ... (DSSAT 输入文件)
├── pestpp-5.2.16-win/         # PEST++ 可执行程序
└── README.md                  # 说明文档
```

## 📝 关键文件说明

### 1. 输入文件
*   **`TMGRO048.CUL.base`**: 品种参数模板。若需调整待率定的参数范围，请直接修改此文件中的 `!Calibration` 标记以及 `MINIMA`/`MAXIMA` 行。
*   **`Evaluate.OUT`**: DSSAT 的评估输出文件，PEST 从此处读取模拟结果。

### 2. 核心脚本
*   **`build_pest.py`**: 
    - 解析 `Evaluate.OUT` 自动识别观测值。
    - 生成 PEST 指令文件 (`.ins`) 和参数模板文件 (`.tpl`)。
    - 包含对物候指标（如 ADAPS, MDAPS）的特殊处理逻辑。
*   **`run_dssat.py`**:
    - 将 PEST 生成的参数写入 DSSAT 格式的 `.CUL` 文件。
    - 调用 `DSCSM048.EXE` 执行模拟。
    - 确保 `Evaluate.OUT` 生成成功。

## 📊 结果解读

运行完成后，重点关注 `Workspace` 目录下的以下文件：

### 1. 拟合效果 (`calibration_results_analysis.csv`)
由 `analyze_results.py` 脚本生成，提供了详细的残差分析和置信区间。
*   **关键列**:
    *   `Measured`: 实测值
    *   `Simulated_Mean`: 模拟值（集合平均）
    *   `Residual`: 残差 (Measured - Simulated)
    *   `Sim_Lower_95` / `Sim_Upper_95`: 模拟值的 95% 置信区间
    *   `Percent_Error`: 相对误差百分比
*   **统计摘要**: 运行脚本时会在终端输出整体 RMSE 和 Mean Bias。

### 2. 参数不确定性 (`parameter_uncertainty_analysis.csv`)
记录了最终参数集合的统计特性。
*   **用途**: 评估参数的收敛情况和不确定性范围。
*   **关键列**:
    *   `mean`: 参数均值
    *   `std`: 参数标准差（不确定性）
    *   `2.5%` / `97.5%`: 参数的 95% 置信区间

### 3. 目标函数 (Phi)
在 `tomato_cal.phi.actual.csv` 中查看每一代迭代的目标函数值变化趋势。

## 📈 高级分析工具

本项目内置了 `analyze_results.py` 脚本，用于对 PEST++ 的集合输出进行统计后处理。

**使用方法**:
```powershell
python analyze_results.py
```
该脚本会自动读取最新的迭代结果，计算残差、RMSE、偏差，并将详细表格保存为 CSV 文件，方便在 Excel 中进一步绘图分析。

---
**提示**: 如需重新开始率定，建议先运行 `python build_pest.py` 重置 PST 文件。
