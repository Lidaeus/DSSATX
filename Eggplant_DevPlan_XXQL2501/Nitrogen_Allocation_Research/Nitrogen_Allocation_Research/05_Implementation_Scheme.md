# 番茄氮素分配优化与 PEST++ 自动化实施方案

## 1. 核心优化思路
针对番茄（Tomato）在 DSSAT-CROPGRO 模型中的模拟表现，特别是低氮环境下果实生长受限的问题，本方案提供一种**非侵入式（无需修改源码）**的参数优化路径。通过调节 SPE 文件中的关键敏感性参数，缓和模型内部硬编码的“幂次惩罚”效应。

### 1.1 参数调节原理
- **核心变量**：`NSTFAC` (Nitrogen Stress Factor Threshold)
- **作用位置**：SPE 文件 `*CARBON AND NITROGEN MINING PARAMETERS` 断面。
- **数学逻辑**：`NSTRES = MIN(1.0, SUPPN / (NDMNEW * NSTFAC))`。减小 `NSTFAC` 可延迟氮胁迫因子的下降，从而间接抵消 `CNSTRES**0.5` 对果实增长的剧烈抑制。

## 2. PEST++ 自动校准架构
由于您使用 **PEST++** 套件，优化流程将从通用的遗传算法切换为基于高效率模型独立参数估计（Model-Independent Parameter Estimation）的框架。

### 2.1 PEST++ 核心组件配置
| 组件 | 文件类型 | 描述 |
|---|---|---|
| **Template File** | `.tpl` | 包含 SPE 或 FILEX 参数标记（如 `~ nstfac ~`）的模板文件 |
| **Instruction File** | `.ins` | 定义如何从 `Summary.OUT` 或 `PlantGro.OUT` 提取观测值（如 `PWAM`, `PNAM`） |
| **Control File** | `.pst` | PEST++ 核心控制文件，定义参数范围、观测权重及算法（如 `IES`） |
| **Model Wrapper** | `.py` / `.sh` | 调用 `DSCSM048.EXE` 并处理文件输入输出的中间脚本 |

### 2.2 优化参数空间（PEST++ 变量）
| 参数名称 | 初始值 | 范围 (Lower/Upper) | 转换类型 | 作用 |
|---|---|---|---|---|
| `nstfac` | 0.70 | [0.40, 0.85] | log | 调节低氮响应曲线起点 |
| `nmobmx` | 0.25 | [0.15, 0.40] | none | 调节组织氮动员最大速率 |
| `nvsmob` | 0.32 | [0.20, 0.50] | none | 调节营养器官可动员氮比例 |

## 3. 实施流程设计
利用 PEST++ 的高效迭代能力，建议采用 **IES (Iterative Ensemble Smoother)** 算法进行多参数协同估计。

### 3.1 步骤一：构建模板与指令
1.  **创建模板**：将 [TM.SPE](file:///Users/lidaeus/Downloads/DSSAT_CSM_OS_REPORT/dssat-csm-os/Data/Genotype/CPGRO048.SPE) 转换为 `TM.SPE.tpl`，使用 `~` 符号包裹变量。
2.  **编写指令**：针对 `PlantGro.OUT` 编写指令文件，精准提取关键生育期的生物量与氮素观测值。

### 3.2 步骤二：配置控制文件 (.pst)
- **Observations**：导入 [XXQL2501.TMA](file:///Users/lidaeus/Downloads/DSSAT_CSM_OS_REPORT/XXQL2501.TMA) 和 [XXQL2501.TMT](file:///Users/lidaeus/Downloads/DSSAT_CSM_OS_REPORT/XXQL2501.TMT) 中的实测数据。
- **Weights**：对低氮处理组的果实产量（PWAM）赋予更高权重，以强制模型拟合“耐低氮”表现。
- **Algorithm**：设置 `pestpp-ies` 模式，利用集成平滑算法在较少运行次数下获得全局最优解。

### 3.3 步骤三：执行与后处理
1.  运行 `pestpp-ies case.pst`。
2.  利用 PEST++ 自带的 `.phi` 文件分析目标函数下降情况。
3.  提取最优参数集（`.par`），回代入 DSSAT 验证非胁迫情景的保真度。

## 4. 实施路线图
1.  **环境准备**：将 `pestpp-ies` 执行文件放置于 DSSAT 工作目录。
2.  **敏感性分析**：先运行 `pestpp-sen` 确定 `NSTFAC` 对番茄产量的灵敏度指数。
3.  **参数估计**：执行 IES 循环，通常 5-10 代集成演化即可收敛。
4.  **不确定性评估**：利用 PEST++ 的后验分析功能，评估优化后参数的置信区间。

## 5. 预期效益
- **效率提升**：相比传统的 NSGA-II，PEST++ 在处理 DSSAT 这种具有高度非线性和较长运行时间的物理模型时，收敛速度提升 5-10 倍。
- **稳健性**：PEST++ 的权重系统能更好地平衡“低氮增产”与“高氮保真”之间的矛盾。
- **标准化**：完全兼容现有的 PEST 生态系统，方便进行后续的不确定性分析和风险评估。
