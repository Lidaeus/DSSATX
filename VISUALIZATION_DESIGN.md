# DSSAT-PEST 可视化与后验分析系统设计文档

## 1. 项目概述
本项目旨在为 DSSAT 作物模型与 PEST++-IES 算法的率定结果提供出版级的可视化分析。重点展示参数的不确定性缩减、模型的时间序列拟合能力以及参数间的相关性。

## 2. 数据来源与流向

### 2.1 输入数据
1.  **参数集合 (Parameter Ensembles)**:
    *   **先验 (Prior)**: `Workspace/Calibration_Results/tomato_cal.0.par.csv` (迭代 0)
    *   **后验 (Posterior)**: `Workspace/Calibration_Results/tomato_cal.{最后一轮}.par.csv` (如迭代 12)
2.  **观测数据 (Observed Data)**:
    *   **时间序列**: 从实验文件 (`.T` 文件，如 `UFBR9401.TMT`) 中读取实测的 LAI (`LAID`) 和生物量 (`CWAD`)。
3.  **模拟数据 (Simulated Data)**:
    *   **状态**: 目前 PEST 输出的 `.obs.csv` 仅包含汇总统计量 (如最大 LAI)。
    *   **需求**: 需开发 `run_posterior_predictions.py` 模块，重新运行后验参数集，从 `PlantGro.OUT` 中提取每日模拟数据。

### 2.2 输出产物
所有图表将保存在 `Workspace/Visualization_Results/` 目录下。

## 3. 核心功能模块设计

### 3.1 模块一：参数不确定性分析 (Parameter Uncertainty)
*   **目标**: 展示数据约束对参数范围的压缩效果。
*   **图表类型**: **Split Violin Plot (小提琴图)** 或 **Boxplot (箱线图)**。
*   **逻辑**:
    1.  读取 Prior 和 Posterior 参数 CSV。
    2.  读取 `tomato_cal.pst` 获取每个参数的上下界 (Bounds)。
    3.  **归一化**: 将所有参数值映射到 [0, 1] 空间，以便在同一张图上比较不同量级的参数。
        *   $Norm = (Value - Lower) / (Upper - Lower)$
    4.  绘制成对的小提琴图：左侧为 Prior，右侧为 Posterior。
    5.  **解读**: 图形变窄表示不确定性降低。

### 3.2 模块二：时间序列集合拟合 (Ensemble Time Series)
*   **目标**: 展示模型对高频时序数据（LAI, Biomass）的拟合能力及预测置信区间。
*   **图表类型**: **Shaded Band Plot (置信区间带状图)**。
*   **逻辑**:
    1.  **后验预测**: 从后验参数集中随机抽取 N=50 个样本。
    2.  **批处理运行**: 调用 `run_dssat.py` 运行这 50 组参数。
    3.  **数据提取**: 解析生成的 `PlantGro.OUT`，提取每日的 `LAID` (LAI) 和 `CWAD` (Biomass)。
    4.  **统计计算**: 对每一天计算模拟值的 P2.5, P50 (Median), P97.5 (95% CI)。
    5.  **绘图**:
        *   **阴影带**: 95% 置信区间 (半透明)。
        *   **实线**: 中位数模拟轨迹。
        *   **散点**: 来自 `.T` 文件的实测数据。
    6.  **多子图**: 为每个处理 (Treatment) 或地点生成单独的子图。

### 3.3 模块三：参数相关性分析 (Correlation Matrix)
*   **目标**: 揭示参数间的权衡关系 (Trade-offs) 和异方同效性 (Equifinality)。
*   **图表类型**: **Heatmap (热力图)**。
*   **逻辑**:
    1.  读取 Posterior 参数矩阵。
    2.  计算 **Spearman Rank Correlation** (比 Pearson 更适合非线性关系)。
    3.  绘制热力图，使用红蓝配色 (Red=Pos, Blue=Neg)。
    4.  **聚类**: 对行列进行层次聚类 (Clustermap)，将相关性强的参数聚集在一起。

## 4. 脚本结构 (Python)

```python
# visualize_results.py

class ResultVisualizer:
    def __init__(self, workspace_dir):
        # 初始化路径和配置
        pass

    def load_parameters(self, iter_idx):
        # 读取指定迭代的参数文件
        pass

    def plot_param_uncertainty(self):
        # 绘制小提琴图
        pass

    def plot_correlation_matrix(self):
        # 绘制热力图
        pass

class PosteriorPredictor:
    def __init__(self, workspace_dir):
        # 初始化
        pass
        
    def run_ensemble(self, sample_size=50):
        # 运行 DSSAT 集合
        # 提取 PlantGro.OUT
        pass
        
    def plot_time_series(self, obs_file):
        # 绘制时序图
        pass

if __name__ == "__main__":
    # 主流程
    # 1. 可视化静态参数结果
    # 2. (可选) 运行后验预测并绘图
```

## 5. 开发计划
1.  **环境准备**: 确保 `seaborn`, `matplotlib`, `pandas` 已安装。
2.  **Step 1**: 实现 `plot_param_uncertainty` 和 `plot_correlation_matrix`。
3.  **Step 2**: 实现 `PosteriorPredictor` 类，重点是高效地批量运行 DSSAT 并解析输出。
4.  **Step 3**: 整合测试，生成最终报告。
