# DSSAT-PEST 参数敏感性分析指南

本文档详细介绍了如何使用 `run_sensitivity.py` 脚本对 DSSAT 模型参数进行全局敏感性分析（Global Sensitivity Analysis, GSA）。

## 1. 简介与原理

在进行复杂的模型率定之前，了解哪些参数对输出结果影响最大是至关重要的。本系统集成了 **Morris 方法**（Morris Method / Elementary Effects），这是一种高效的筛选方法，适用于参数众多的计算模型。

### 1.1 为什么要作敏感性分析？
*   **筛选关键参数**: 识别出对产量、开花期等关键指标影响最大的参数，重点率定这些参数。
*   **固定不敏感参数**: 将对结果几乎无影响的参数固定为默认值，减少率定过程的计算量，避免过拟合。
*   **理解模型行为**: 深入了解模型在不同参数组合下的响应机制。

### 1.2 Morris 方法原理
Morris 方法通过在参数空间内构建多条随机轨迹（Trajectories），计算每个参数的“基本效应”（Elementary Effect）。
*   **均值 ($\mu^*$) / 绝对均值 (Mean Abs)**: 反映参数对模型输出的总体影响幅度。值越大，参数越重要。
*   **标准差 ($\sigma$)**: 反映参数与其他参数的交互作用或非线性效应。值越大，说明该参数的影响越不稳定（受其他参数取值影响）。

---

## 2. 脚本说明

*   **脚本路径**: `c:\DSSAT48\Tomato_Cal\Workspace\run_sensitivity.py`
*   **核心引擎**: `pestpp-sen.exe` (PEST++ Sensitivity Analyzer)
*   **依赖文件**: 需要 `build_pest.py` 生成的基础控制文件 (`tomato_cal.pst`)。

### 2.1 代码逻辑流程
1.  **初始化**: 读取现有的 `tomato_cal.pst`（原用于率定的控制文件）。
2.  **配置 GSA**: 创建一个新的控制文件 `tomato_sen.pst`，修改运行模式为 `gsa_method = morris`，并设置采样参数（如轨迹数 `gsa_morris_r`）。
3.  **执行计算**: 调用 `pestpp-sen.exe`，它会根据 Morris 采样策略生成多组参数，驱动 DSSAT 并行或串行运行。
4.  **结果分析**: 读取生成的 `.msn` (Morris Sensitivity) 文件，提取关键指标，按敏感度排序并导出报表。

---

## 3. 使用方法

### 步骤 1: 准备环境
确保你已经成功运行过一次 `build_pest.py`，以保证基础的 PEST 控制文件和参数模板存在。

```powershell
cd C:\DSSAT48\Tomato_Cal\Workspace
python build_pest.py
```

### 步骤 2: 运行敏感性分析
直接运行脚本即可。默认配置下，它会使用 Morris 方法，生成 6 条轨迹。

```powershell
python run_sensitivity.py
```

**运行过程**:
*   控制台会显示正在运行的进度。
*   由于需要运行多次模型（计算量 $\approx$ 轨迹数 $\times$ (参数数 + 1)），可能需要几分钟时间。

### 步骤 3: 查看结果
运行结束后，所有的结果文件和图表都会自动保存到 **`Sensitivity_Results`** 文件夹中：

*   **图表**:
    *   `Morris_Ranking_BarPlot.png/.pdf`: 参数敏感性排名条形图（出版级质量）。
    *   `Morris_Interaction_Scatter.png/.pdf`: 均值与标准差的散点图，展示参数交互作用。
*   **数据**:
    *   `sensitivity_report_morris.csv`: 经过整理和排序的敏感性分析报告。
    *   `tomato_sen_raw.msn`: 原始的 Morris 分析结果文件。

控制台也会直接打印排名前 10 的敏感参数。

---

## 4. 结果解读指南

打开生成的 `sensitivity_report_morris.csv`，重点关注以下两列：

| 列名 | 含义 | 解读 |
| :--- | :--- | :--- |
| **sen_mean_abs** | **绝对平均敏感度** | **主要指标**。数值越大，说明该参数稍微改变一点，就会引起模拟结果（如产量）剧烈变化。<br>建议：优先率定排名前 3-5 的参数。 |
| **sen_std_dev** | **敏感度标准差** | **辅助指标**。数值越大，说明该参数与其他参数存在复杂的“纠缠”关系（交互作用）。<br>建议：如果某参数 Mean Abs 很大且 Std Dev 也很大，说明它非常关键且复杂，需谨慎设定范围。 |

### 示例数据分析
*(基于最近一次运行结果)*

| 参数 | Mean Abs | Std Dev | 判定 |
| :--- | :--- | :--- | :--- |
| **EM-FL** (出苗-开花) | 8.49E+07 | 1.12E+08 | **极度敏感**。这是模型的“起搏器”，必须首先准确率定。 |
| **XFRT** (果实分配率) | 1.35E+07 | 1.07E+07 | **高度敏感**。直接决定产量高低。 |
| **FL-LF** (开花-叶止) | 6.33E+06 | 7.99E+06 | **中度敏感**。影响光合面积持续时间。 |
| **PODUR** (采摘期) | 0.00 | 0.00 | **不敏感**。在当前实验设置下，改变此参数对结果无影响（可以固定）。 |

---

## 5. 高级配置 (针对开发人员)

如果需要修改采样数量或分析方法，请编辑 `run_sensitivity.py` 中的 `setup_sensitivity_pst` 函数调用：

```python
if __name__ == "__main__":
    # ...
    
    # 增加采样数 (提高精度，但计算时间变长)
    # sample_size = 10 (建议范围 4-10)
    setup_sensitivity_pst(method="morris", sample_size=10) 
    
    # 切换为 Sobol 方法 (计算量巨大，仅建议参数较少时使用)
    # setup_sensitivity_pst(method="sobol", sample_size=100)
    
    run_sensitivity()
```
