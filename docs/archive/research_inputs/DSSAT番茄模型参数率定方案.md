# **基于PESTpp-IES算法的DSSAT CROPGRO-Tomato模型参数自动率定与不确定性分析实施方案**

> 文档状态：历史领域方案，仅供背景参考。具体参数、算法、后验解释和实施步骤不得直接覆盖当前质量门与分阶段设计。当前规范见 [产品定义与系统设计](../../../项目重构规划.md)。
> 状态更新：2026-07-15

## **第一章 绪论：作物模型参数估计的科学范式转型**

### **1.1 作物生长模型在农业系统中的地位与挑战**

在现代精准农业与气候变化适应性研究中，基于过程的作物生长模型（Process-Based Crop Models, PBCMs）已成为不可或缺的核心工具。其中，农业技术转移决策支持系统（Decision Support System for Agrotechnology Transfer, DSSAT）作为全球应用最为广泛的综合性模型平台之一，其内部集成的CROPGRO模块能够通过模拟光合作用、呼吸作用、碳氮分配及物候发育等复杂的生理生态过程，对番茄（*Solanum lycopersicum*）等作物的生长动态进行精细化预测 1。然而，模型的预测能力在很大程度上取决于输入参数的准确性，特别是反映作物品种特性的遗传参数（Genetic Coefficients）。这些参数通常无法直接测量，而必须通过田间观测数据进行反演或率定（Calibration）。

传统的参数率定方法多依赖于“试错法”（Trial-and-Error），这种方法不仅耗时费力，而且严重依赖于建模者的经验，极易陷入局部最优解，且无法量化参数的不确定性 4。随着计算能力的提升，自动化参数估算工具逐渐成为主流。DSSAT自带的GLUE（Generalized Likelihood Uncertainty Estimation）虽然提供了一种贝叶斯框架下的不确定性分析途径，但其基于蒙特卡洛随机采样的效率较低，往往需要数万次模型运行才能收敛 4。相比之下，模型独立的参数估算工具PEST（Parameter ESTimation）及其升级版PESTpp-IES（Iterative Ensemble Smoother），凭借其高效的算法架构和对非线性问题的强大处理能力，正在成为作物模型参数率定的新标准 6。

### **1.2 PESTpp-IES算法的选择依据与优势**

在本方案中，针对DSSAT CROPGRO-Tomato模型的率定任务，我们明确选择使用PESTpp-IES算法，而非传统的PEST（基于高斯-马奎特-列文伯格算法，GML）或GLUE。这一决策基于以下深刻的理论与实践考量：

首先，作物模型具有高度的非线性与阈值效应。例如，番茄的开花时间（Anthesis）受积温（Thermal Time）控制，一旦温度未达到基点温度，发育速率即为零。这种非连续的响应面使得传统的基于梯度的算法（如GML）在计算雅可比矩阵（Jacobian Matrix）时容易失真，或者陷入众多的局部极小值中无法自拔 4。PESTpp-IES采用集合平滑（Ensemble Smoother）的方法，通过一组参数样本（Realizations）的协方差来近似雅可比矩阵，从而避免了直接计算梯度的数值不稳定性，能够更鲁棒地处理高度非线性的响应面 9。

其次，参数的“异参同效”现象（Equifinality）在番茄模拟中尤为突出。例如，提高光合作用效率参数（LFMAX）与增加光合产物向果实分配比例（XFRUIT）都可能导致最终产量的增加。传统的单一最优解算法无法区分这两种机制，而PESTpp-IES通过输出一个后验参数集合（Posterior Ensemble），能够完整地呈现出所有可能满足观测数据的参数组合。这不仅给出了最佳估计值，更量化了参数的不确定性范围，为后续的风险评估提供了坚实的统计学基础 12。

最后，计算效率的考量。在处理包含时间序列（File T）的大数据量反演时，传统PEST每次迭代需要的模型运行次数与参数数量成正比（$2N+1$次），而PESTpp-IES的运行次数仅取决于集合的大小（通常为50-100次），与待估参数的数量无关。这意味着我们可以同时率定物候、形态、光合及产量相关的十几个参数，而不会显著增加计算成本。此外，PESTpp-IES天生支持高度并行的计算架构，能够充分利用现代多核处理器的优势 9。

## ---

**第二章 DSSAT CROPGRO-Tomato模型机理与待定参数解析**

### **2.1 CROPGRO-Tomato的模型架构**

CROPGRO是一个通用的豆类及蔬菜作物生长模型，其核心在于通过每日的时间步长，模拟作物对光、温、水、氮等环境因子的响应。对于番茄而言，模型区分了无限生长型（Indeterminate）和有限生长型（Determinate）品种，这一特性通过营养生长与生殖生长的并进或终止来体现。模型的数据输入流包括气象数据（File W）、土壤数据（File S）和管理数据（File X），而品种特性则由物种文件（\*.SPE）、生态型文件（\*.ECO）和栽培种文件（\*.CUL）共同定义 3。

在率定过程中，我们要修正的是反映特定品种遗传特性的\*.CUL文件中的参数。这些参数控制着作物生命周期的关键节点（如开花、坐果、成熟）以及生物量的累积与分配效率。

### **2.2 关键遗传参数的生理意义与率定优先级**

根据DSSAT的参数定义文档及相关文献，我们筛选出以下对番茄生长模拟最为敏感的参数作为本次率定的对象。这些参数按其对模型输出的影响逻辑，可分为物候参数、形态与光合参数、产量与分配参数三大类 15。

#### **2.2.1 物候发育参数 (Phenology)**

物候参数决定了作物生长阶段的划分，是模型校准的第一步。若物候期模拟错误，后续的生物量累积将基于错误的生长阶段，导致全盘皆输。

| 参数代码 | 参数定义 (Definition) | 单位 | 生理意义与率定策略 |
| :---- | :---- | :---- | :---- |
| **EM-FL (P1)** | 出苗到开花的光热时间 | 光热天 (photothermal days) | 决定营养生长期的长短。对于番茄，此参数直接控制开花日期（ADAT）。由于番茄是喜温作物，该参数对温度极其敏感。率定目标：File A中的开花日期。 |
| **FL-SH** | 开花到初果（坐果）的时间 | 光热天 | 决定了从生殖生长开始到果实快速膨大期的滞后时间。影响早期果实生物量的积累。 |
| **FL-SD** | 开花到第一粒种子形成的时间 | 光热天 | 通常与FL-SH紧密相关，影响种子库的建立。 |
| **SD-PM** | 第一粒种子形成到生理成熟的时间 | 光热天 | 决定了生殖生长期的总长度和最终收获日期（MDAT）。率定目标：File A中的成熟日期。 |
| **FL-LF** | 开花到叶片停止生长的时间 | 光热天 | 对于有限生长型番茄至关重要，决定了冠层何时停止扩展。对于无限生长型，此值通常较大。 |

#### **2.2.2 光合与形态参数 (Photosynthesis & Morphology)**

这组参数控制“源”（Source）的大小和效率，直接影响生物量的累积速率（File T中的CWAD）和叶面积指数（File T中的LAID）。

| 参数代码 | 参数定义 (Definition) | 单位 | 生理意义与率定策略 |
| :---- | :---- | :---- | :---- |
| **LFMAX** | 最大单叶光合速率 | mg CO2/m²/s | 整个模型的“发动机”。该值略微增加会显著提高全生育期的生物量积累。它是产量形成的核心驱动力，但极易与其他参数发生“异参同效”。 |
| **SLAVR** | 标准条件下的比叶面积 | cm²/g | 决定了投入叶片的干物质能转化为多少叶面积。此参数直接控制LAI的增长曲线。若模拟的LAI偏低而生物量正常，需调大此值。 |
| **SIZLF** | 最大叶片尺寸 | cm² | 影响早期冠层的郁闭速度。 |

#### **2.2.3 产量分配参数 (Partitioning & Yield)**

这组参数控制光合产物向“库”（Sink）的分配，即最终产量（File A中的HWAM）和收获指数（HI）。

| 参数代码 | 参数定义 (Definition) | 单位 | 生理意义与率定策略 |
| :---- | :---- | :---- | :---- |
| **XFRUIT** | 每日干物质向果实分配的最大比例 | 0-1 (无量纲) | 决定了生殖生长期间，营养器官与生殖器官的竞争关系。若生物量模拟准确但产量偏低，需提高此值。 |
| **WTPSD** | 最大单粒种子重量 | g | 影响种子的库容量。 |
| **SFDUR** | 单个果实/种子的灌浆持续时间 | 光热天 | 决定了单个果实的生长周期，影响单果重。 |

### **2.3 参数取值范围与先验分布**

PESTpp-IES要求为每个参数设定上下界（Bounds）。合理的上下界设置能防止模型进入非生物学意义的参数空间（如负的生长速率）。

* **策略：** 以DSSAT自带的标准番茄品种（如FL\_47或Sunny）的参数值为先验均值（Mean）。  
* **范围：** 建议将上下界设定为默认值的 $\\pm 20\\%$ 至 $\\pm 30\\%$。例如，若EM-FL默认值为32.0，则搜索范围可设为 $\[24.0, 40.0\]$。对于XFRUIT等0-1之间的参数，需确保上限不超过1.0 17。

## ---

**第三章 系统架构设计与接口工程**

实施自动化率定的核心难点在于构建PEST与DSSAT之间的通讯接口。DSSAT本质上是一组Fortran编译的可执行程序，它通过读取固定格式的文本文件进行输入输出。因此，我们必须构建一套严密的“前处理-执行-后处理”机制。

### **3.1 总体工作流逻辑**

我们将采用“非侵入式”耦合策略。PEST作为主控程序，通过调用一个系统命令（Wrapper Script）来驱动DSSAT。

1. **PEST写入阶段：** PEST根据当前的参数推测值，利用\*\*模板文件（Template File,.tpl）\*\*生成新的DSSAT品种参数文件（TOMGRO.CUL）。  
2. **模型执行阶段：** PEST调用Python编写的封装脚本（Wrapper Script）。该脚本负责清理旧文件、调用DSSAT主程序（DSCM048.EXE）、并监控运行状态。  
3. **结果读取阶段：** PEST利用\*\*指令文件（Instruction File,.ins）\*\*从DSSAT的输出文件（PlantGro.OUT 和 Evaluate.OUT）中提取对应的模拟值，并计算与观测值的残差 18。

### **3.2 模板文件 (.tpl) 的构建技术**

DSSAT的输入文件（特别是.CUL文件）严格遵循固定列宽（Fixed-width）格式。任何列的错位都会导致模型读取错误甚至崩溃。

**技术细节：**

* **头部标识：** 文件首行必须是 ptf \#，声明 \# 为参数占位符的分隔符。  
* **格式对齐：** 必须使用文本编辑器（如VS Code或Notepad++）精确对齐每一列。PEST写入的数值长度可能会变化（例如 10.5 vs 10.5001），因此需要在PEST控制文件中指定参数的精度格式（PARFMT），强制其输出为固定宽度的字符串（如 %10.4f），或者在模板文件中预留足够的空间。

TOMGRO.TPL 文件示例：  
ptf \#  
\*TOMATO GENOTYPE COEFFICIENTS: CRGRO048 MODEL  
\!ECO\! \!CSDL\!\!PPSEN\!\!EM-FL\!\!FL-SH\!\!FL-SD\!\!SD-PM\!\!FL-LF\!\!LFMAX\!\!SLAVR\!\!SIZLF\!\!XFRUIT\!\!WTPSD\!\!SFDUR\!\!SDPDV\!\!PODUR\!  
@VAR\# VAR-NAME......... EXP\# ECO\# CSDL PPSEN EM-FL FL-SH FL-SD SD-PM FL-LF LFMAX SLAVR SIZLF XFRUIT WTPSD SFDUR SDPDV PODUR  
\#VAR\_ID\# \#VAR\_NAME \#. \#ECO\_ID \# \#CSDL \# \#PPSEN\# \#EM-FL\# \#FL-SH\# \#FL-SD\# \#SD-PM\# \#FL-LF\# \#LFMAX\# \#SLAVR\# \#SIZLF\# \#XFRUIT\# \#WTPSD\# \#SFDUR\# \#SDPDV\# \#PODUR\#  
注意：\#EM-FL\# 等占位符的宽度必须与原文件中的数据列宽完全一致（通常为6个字符）。 20

### **3.3 指令文件 (.ins) 与输出解析策略**

DSSAT的主要输出文件是 PlantGro.OUT（每日生长数据）和 Evaluate.OUT（季节末总结）。

解析 PlantGro.OUT 的挑战：  
该文件包含每日的模拟值，且表头上方有若干行元数据。对于时间序列数据（File T），观测数据通常是在特定的日期（如种植后30天、60天等）测量的。PEST的指令文件需要精确跳转到这些特定的日期行进行读取。  
**技术细节：**

* **头部标识：** pif @，声明 @ 为标记符。  
* **定位策略：** 使用 S2 指令搜索特定的处理名称，使用 l&（行搜索）指令查找具体的“种植后天数”（DAP）。

PlantGro.ins 文件示例：  
pif @

# **搜索处理名称，确保读取的是正确的试验处理**

S2 @TREATMENT 1@

# **跳过表头**

l5

# **查找DAP=30的那一行，读取LAI和生物量**

l&@ 30 @\!sim\_lai\_30\!\!sim\_cwad\_30\!

# **继续查找DAP=60的那一行**

l&@ 60 @\!sim\_lai\_60\!\!sim\_cwad\_60\!  
这种方法的优点是稳健性强，即使模型输出了额外日期的模拟值，l& 指令也能跳过无关行直接定位目标行。 22

### **3.4 Python封装脚本的设计 (run\_dssat.py)**

为了增强系统的鲁棒性，不建议直接在PEST中调用DSSAT的EXE文件，而是调用一个Python脚本。

**脚本功能逻辑：**

1. **环境清理：** os.remove('PlantGro.OUT')，防止读取上一次运行的残留文件。  
2. **批处理配置：** 确保 DSSBatch.v48 文件中仅包含当前用于率定的试验处理（File X中的Treatments），避免运行无关试验浪费时间。  
3. **模型执行：** 使用 subprocess.run() 启动模型。  
4. **错误捕获：** 检查模型返回值。如果模型崩溃（非0返回），则生成一个包含极大惩罚值的伪造输出文件，防止PEST中断 23。

## ---

**第四章 PESTpp-IES 深度配置与参数设定**

本章将详细阐述如何配置 PESTpp-IES 的核心控制文件（Control File, .pst），这是整个系统的“大脑”。

### **4.1 控制文件结构与“++”参数**

PESTpp-IES 向下兼容标准 PEST 格式，但通过 \++ 开头的特殊参数来控制其独有的集合平滑功能。这些参数通常位于 .pst 文件的末尾或 \* control data 部分 9。

#### **4.1.1 集合大小与迭代次数**

* **\++ies\_num\_reals (集合大小):** 建议设置为 **50 到 100**。  
  * *原理：* 集合越大，对雅可比矩阵的秩（Rank）估计越准确，不仅能更好地探索参数空间，还能防止过度拟合。对于作物模型这种参数维度中等（10-20个参数）的问题，100个样本足以捕捉参数间的相关性 9。  
* **NOPTMAX (迭代次数):** 建议设置为 **4 到 6**。  
  * *原理：* 与传统GLM算法需要几十次迭代不同，IES算法利用集合的统计特性，通常在几次迭代内就能迅速收敛到卡方分布的目标值附近。过多的迭代可能导致过度拟合观测数据的噪声 25。

#### **4.1.2 初始集合生成**

* **\++ies\_parameter\_ensemble:**  
  * 若不指定此文件，PESTpp-IES 将根据 \* parameter data 章节中定义的初始值和上下界，自动生成高斯分布或均匀分布的初始参数集合。  
  * *建议：* 初次尝试时让程序自动生成，以简化流程。若需要引入参数间的先验相关性（例如，假设 P1 和 P2 正相关），则需使用 pyemu 等工具预先生成并提供一个 CSV 格式的参数集合文件 21。

#### **4.1.3 正则化与定位化 (Regularization & Localization)**

* **\++ies\_reg\_factor (正则化因子):** 建议设为 **0.05 或 0.1**。  
  * *作用：* 这是一个加权系数，用于在目标函数中平衡“数据匹配误差”和“参数偏离先验值的程度”。适当的正则化可以防止参数为了迎合噪声数据而跑偏到不合理的数值范围 27。  
* **\++ies\_localization\_matrix (定位化矩阵):**  
  * *作用：* 在高维地下水模型中常用，用于切断物理上不相关的参数与观测值的联系。在作物模型中，由于参数间的生物学关联紧密（如光合参数同时影响LAI和产量），通常**不建议**初学者启用定位化，以免人为割裂生理联系，除非你非常确定某些参数（如开花参数）绝不应受后期观测值（如最终产量）的影响 17。

### **4.2 观测数据的加权策略**

这是决定率定成败的关键艺术。PESTpp-IES 将权重视为测量标准差的倒数（$w \= 1/\\sigma$）。

* **物候数据 (File A):** 给予最高权重。  
  * *理由：* 如果开花期模拟错了，后续所有的生物量累积曲线在时间轴上都是错位的，此时去拟合生物量毫无意义。建议权重设为 $1.0 / 1$ (即允许1天的误差)。  
* **产量数据 (File A):** 给予中等权重。  
  * *理由：* 产量是最终目标，建议权重设为 $1.0 / (0.1 \\times Yield\_{obs})$ (即允许10%的误差)。  
* **时间序列数据 (File T \- LAI, CWAD):** 给予较低权重。  
  * *理由：* 时间序列包含很多个数据点（如10个采样日）。如果每个点的权重都很高，它们的总和将压倒物候和产量数据，导致模型过度关注生长曲线的局部波动而牺牲整体趋势。建议通过“逆方差加权”或将整个时间序列的总权重归一化 28。

## ---

**第五章 实施路线图与操作指南**

本章将上述理论转化为可执行的操作步骤。

### **阶段一：环境准备与基准测试**

1. **软件安装：** 安装 DSSAT v4.8 和 PEST++ 套件（将 pestpp-ies.exe 加入系统环境变量）。  
2. **工作目录构建：** 创建文件夹 C:\\DSSAT48\Tomato\_Cal。将 DSSAT 的主程序、DSSBatch.v48、TOMGRO.SPE、TOMGRO.ECO 以及用户的 File X, File S, File W 全部复制到该目录。  
3. **基准运行：** 使用默认参数运行一次 DSSAT，确保生成的 PlantGro.OUT 和 Evaluate.OUT 数据正常。

### **阶段二：构建 Python 接口脚本 (run\_dssat.py)**

编写如下脚本以自动化运行流程：

Python

import os  
import subprocess  
import time

def run\_model():  
    \# 1\. 清理旧输出  
    if os.path.exists("PlantGro.OUT"): os.remove("PlantGro.OUT")  
    if os.path.exists("Evaluate.OUT"): os.remove("Evaluate.OUT")  
      
    \# 2\. 调用DSSAT (B模式)  
    \# 注意：DSSBatch.v48必须已配置好指向File X  
    try:  
        subprocess.run(, check=True)  
    except subprocess.CalledProcessError:  
        print("Model crashed\!")  
        \# 即使崩溃也要生成伪造的输出文件供PEST读取，防止PEST退出  
        \# (此处省略伪造文件代码，实际操作中应写入极大值)

if \_\_name\_\_ \== "\_\_main\_\_":  
    run\_model()

### **阶段三：生成 PEST 文件**

1. **制作 .tpl 文件：** 复制 TOMGRO.CUL，将待定参数（如 EM-FL 的数值）替换为 \#P1\_PAR\#。  
2. **制作 .ins 文件：** 根据 PlantGro.OUT 的结构和 File T 中的观测日期，编写指令文件。  
3. **生成 .pst 控制文件：** 使用 pyemu 库可以极大地简化这一步。

Python

import pyemu  
import os

\# 定义参数名和观测名  
par\_names \=  
obs\_names \=

\# 初始化 PST 对象 (假设已有 tpl 和 ins 文件)  
pst \= pyemu.Pst.from\_io\_files("TOMGRO.tpl", "TOMGRO.CUL",   
                              \["Evaluate.ins", "PlantGro.ins"\],   
                             )

\# 设置参数范围和初始值  
pst.parameter\_data.loc\["P1", "parval1"\] \= 28.0  
pst.parameter\_data.loc\["P1", "parlbnd"\] \= 20.0  
pst.parameter\_data.loc\["P1", "parubnd"\] \= 40.0  
\#... 设置其他参数...

\# 配置 PESTpp-IES 特有选项  
pst.pestpp\_options\["ies\_num\_reals"\] \= 80  
pst.pestpp\_options\["ies\_par\_en"\] \= "prior.jcb" \# 可选  
pst.control\_data.noptmax \= 5

\# 保存  
pst.write("tomato\_ies.pst")

29

### **阶段四：执行与监控**

在命令行中运行：  
pestpp-ies.exe tomato\_ies.pst /h :4001  
(注：如果需要并行计算，可以启动多个 worker 监听端口)  
观察屏幕输出的 Phi 值变化。如果 Phi 值在前 2-3 次迭代中显著下降，说明集合正在向最优区域收敛。

## ---

**第六章 结果验证与后续分析**

### **6.1 收敛性与后验分析**

PESTpp-IES 运行结束后，会生成一系列 \*.phi 和 \*.par 文件（如 tomato\_ies.1.par.csv, tomato\_ies.2.par.csv）。

* **不确定性分析：** 读取最后一次迭代的参数集合 CSV 文件。计算每个参数的标准差。如果某参数（如 LFMAX）的后验分布很窄，说明该参数对模型结果影响显著且已被数据锁定。如果某参数分布依然很宽（接近先验分布），说明数据对其不敏感，或者存在多解性 12。

### **6.2 交叉验证 (Cross-Validation)**

不要仅看率定结果的拟合度（R² 或 RMSE）。必须使用“留一法”或独立的年份数据进行验证。将 PEST 得到的参数均值代入模型，运行未参与率定的处理（File X 中的 Validation Treatments），检查模型在这些新环境下的表现。

## ---

**第七章 常见问题与排查 (Troubleshooting)**

### **7.1 "Model run failed"**

* **原因：** 参数组合越界导致 DSSAT 运算错误（如除以零）。  
* **对策：** 检查 .pst 文件中的参数下界。例如，确保光合速率 LFMAX 不小于 0，发育时间 EM-FL 不小于 10。利用 \++ies\_bad\_phi 选项，让 PESTpp 自动剔除那些导致模型崩溃的参数样本，而不中断整个进程 27。

### **7.2 模拟结果无变化 (Zero Sensitivity)**

* **原因：** 模板文件 (.tpl) 中的占位符宽度错误，导致 PEST 写入的参数未能正确替换原文件中的数值（DSSAT 依然读取旧值）。  
* **对策：** 仔细检查 .CUL 文件。确保 PEST 写入的新文件在列对齐上与原文件**完全一致**。DSSAT 是 Fortran 程序，对列的位置非常敏感。

### **7.3 异参同效 (Equifinality)**

* **现象：** 产量拟合得很好，但 LAI 偏低，单果重偏高。  
* **对策：** 这是因为模型通过错误的机制（高分配率、低源）达成了正确的产量。必须增加 File T 中 LAI 和生物量的观测权重，强制模型必须先拟合好“源”（Source），再去拟合“库”（Sink）。

## ---

**结语**

通过实施本方案，您将建立起一套基于 PESTpp-IES 的现代化作物模型率定系统。这不仅能高效地解决番茄模型的参数估计问题，更能为您提供关于模型结构不确定性和数据质量的深刻洞见。相比于传统的 GLUE 或手动调参，这种方法在计算效率、结果的统计学严谨性以及对非线性生物过程的适应性上都具有显著优势。建议您按照本报告的路线图，从构建 Python 接口脚本开始，逐步推进各项工作。

#### **引用的著作**

1. Exploring DSSAT: A Powerful Tool for Crop Growth Simulation \- Climate Change Academy, 访问时间为 十二月 12, 2025， [https://climatechange.academy/climate-change-assessment-tools/exploring-dssat-crop-growth-simulation/](https://climatechange.academy/climate-change-assessment-tools/exploring-dssat-crop-growth-simulation/)  
2. DSSAT.net \- Official Home of the DSSAT Cropping Systems Model, 访问时间为 十二月 12, 2025， [https://dssat.net/](https://dssat.net/)  
3. The DSSAT cropping system model \- Agricultural and Biological Engineering, 访问时间为 十二月 12, 2025， [https://abe.ufl.edu/Faculty/jjones/ABE\_5646/Week%207/The%20DSSAT%20Cropping%20System%20Model.pdf](https://abe.ufl.edu/Faculty/jjones/ABE_5646/Week%207/The%20DSSAT%20Cropping%20System%20Model.pdf)  
4. Estimating crop genetic parameters for DSSAT with modified PEST software, 访问时间为 十二月 12, 2025， [https://papers.agrivy.com/webfiles/papers/2020-EJA-MA-HAIJIAO.pdf](https://papers.agrivy.com/webfiles/papers/2020-EJA-MA-HAIJIAO.pdf)  
5. Estimating crop genetic parameters of the DSSAT model with modified PEST software \- Publication : USDA ARS, 访问时间为 十二月 12, 2025， [https://www.ars.usda.gov/research/publications/publication/?seqNo115=361567](https://www.ars.usda.gov/research/publications/publication/?seqNo115=361567)  
6. Embracing Iterative Ensemble Smoother Modeling for Predictive Design Evaluation with Uncertainty – An Application at the Shiprock, 访问时间为 十二月 12, 2025， [https://energy.gov/sites/default/files/2024-04/Embracing%20Iterative%20Ensemble%20Smoother%20Modeling.pdf](https://energy.gov/sites/default/files/2024-04/Embracing%20Iterative%20Ensemble%20Smoother%20Modeling.pdf)  
7. A model-independent iterative ensemble smoother for efficient history-matching and uncertainty quantification in very high dimensions | Request PDF \- ResearchGate, 访问时间为 十二月 12, 2025， [https://www.researchgate.net/publication/325910423\_A\_model-independent\_iterative\_ensemble\_smoother\_for\_efficient\_history-matching\_and\_uncertainty\_quantification\_in\_very\_high\_dimensions](https://www.researchgate.net/publication/325910423_A_model-independent_iterative_ensemble_smoother_for_efficient_history-matching_and_uncertainty_quantification_in_very_high_dimensions)  
8. Uncertainty of CERES-Maize Calibration under Different Irrigation Strategies Using PEST Optimization Algorithm \- USDA ARS, 访问时间为 十二月 12, 2025， [https://www.ars.usda.gov/ARSUserFiles/3495/46.%20agronomy-09-00241%20(4).pdf](https://www.ars.usda.gov/ARSUserFiles/3495/46.%20agronomy-09-00241%20\(4\).pdf)  
9. Nonlinear uncertainty analysis \> PESTPP-IES \- Decision-support modelling, 访问时间为 十二月 12, 2025， [https://help.pesthomepage.org/pestpp-ies.html](https://help.pesthomepage.org/pestpp-ies.html)  
10. A framework for parameter estimation, sensitivity analysis, and uncertainty analysis for holistic hydrologic modeling using SWAT \- HESS, 访问时间为 十二月 12, 2025， [https://hess.copernicus.org/articles/28/21/2024/hess-28-21-2024.pdf](https://hess.copernicus.org/articles/28/21/2024/hess-28-21-2024.pdf)  
11. Introduction to Iterative Ensemble Smoother, 访问时间为 十二月 12, 2025， [https://download.feflow.com/html/help100/fepest/13\_Ensemble\_Smoothing/Iterative\_Ensemble\_Smoother.html](https://download.feflow.com/html/help100/fepest/13_Ensemble_Smoothing/Iterative_Ensemble_Smoother.html)  
12. Flow Regime-Dependent, Discharge Uncertainty Envelope for Uncertainty Analysis with Ensemble Methods \- MDPI, 访问时间为 十二月 12, 2025， [https://www.mdpi.com/2073-4441/15/6/1133](https://www.mdpi.com/2073-4441/15/6/1133)  
13. usgs/pestpp: tools for scalable and non-intrusive parameter estimation, uncertainty analysis and sensitivity analysis \- GitHub, 访问时间为 十二月 12, 2025， [https://github.com/usgs/pestpp](https://github.com/usgs/pestpp)  
14. PESTPP Workshop Based On GV Workshop | PDF | Parameter (Computer Programming) | Matrix (Mathematics) \- Scribd, 访问时间为 十二月 12, 2025， [https://www.scribd.com/document/710575216/PESTPP-workshop-based-on-GV-workshop](https://www.scribd.com/document/710575216/PESTPP-workshop-based-on-GV-workshop)  
15. Improving the CROPGRO-Tomato Model for Predicting Growth and Yield Response to Temperature in \- ASHS Journals, 访问时间为 十二月 12, 2025， [https://journals.ashs.org/view/journals/hortsci/47/8/article-p1038.xml](https://journals.ashs.org/view/journals/hortsci/47/8/article-p1038.xml)  
16. DSSAT User's Guide Vol. 4, 访问时间为 十二月 12, 2025， [https://dssat.net/wp-content/uploads/2011/10/DSSAT-vol4.pdf](https://dssat.net/wp-content/uploads/2011/10/DSSAT-vol4.pdf)  
17. FePEST 8.0 Documentation \- IES Required Settings, 访问时间为 十二月 12, 2025， [https://download.feflow.com/html/help80/fepest/13\_Ensemble\_Smoothing/IES\_Required\_Settings.html](https://download.feflow.com/html/help80/fepest/13_Ensemble_Smoothing/IES_Required_Settings.html)  
18. Dancing with models \> PEST-model communication, 访问时间为 十二月 12, 2025， [https://help.pesthomepage.org/pest-model-communication.html](https://help.pesthomepage.org/pest-model-communication.html)  
19. Structure of PEST control file, 访问时间为 十二月 12, 2025， [https://help.pesthomepage.org/structure-of-pest-control-file.html](https://help.pesthomepage.org/structure-of-pest-control-file.html)  
20. Creating a PEST control file \- Decision-support modelling, 访问时间为 十二月 12, 2025， [https://help.pesthomepage.org/creating-a-pest-control-file.html](https://help.pesthomepage.org/creating-a-pest-control-file.html)  
21. pyemu.ParameterEnsemble, 访问时间为 十二月 12, 2025， [https://pyemu.readthedocs.io/en/develop/\_autosummary/pyemu.ParameterEnsemble.html](https://pyemu.readthedocs.io/en/develop/_autosummary/pyemu.ParameterEnsemble.html)  
22. Using PEST to Calibrate Models \- Making Connections \- isee systems, 访问时间为 十二月 12, 2025， [https://blog.iseesystems.com/modeling-tips/calibrate-models-pest/](https://blog.iseesystems.com/modeling-tips/calibrate-models-pest/)  
23. DS4Ag/dpest: Python package automating PEST file creation for DSSAT crop model calibration. Generates template files for Cultivar and Ecotype parameters, instruction files for OVERVIEW.OUT and PlantGro.OUT, and the main PEST control file. Includes utility to extend PlantGro.OUT files for complete time series compatibility. \- GitHub, 访问时间为 十二月 12, 2025， [https://github.com/DS4Ag/dpest](https://github.com/DS4Ag/dpest)  
24. pestpp/documentation/pestpp\_users\_manual.md at master \- GitHub, 访问时间为 十二月 12, 2025， [https://github.com/usgs/pestpp/blob/master/documentation/pestpp\_users\_manual.md](https://github.com/usgs/pestpp/blob/master/documentation/pestpp_users_manual.md)  
25. Nonlinear uncertainty analysis \- Decision-support modelling \- PEST, 访问时间为 十二月 12, 2025， [https://help.pesthomepage.org/nonlinear-uncertainty-analysis.html](https://help.pesthomepage.org/nonlinear-uncertainty-analysis.html)  
26. FePEST 7.1 Documentation \- Termination Criteria, 访问时间为 十二月 12, 2025， [https://download.feflow.com/html/help71/fepest/03\_Estimation/Settings/Optimization\_Control/terminationcriteria.html](https://download.feflow.com/html/help71/fepest/03_Estimation/Settings/Optimization_Control/terminationcriteria.html)  
27. mwtoews/pestpp-jtwhite79: PEST++ inverse model project \- GitHub, 访问时间为 十二月 12, 2025， [https://github.com/mwtoews/pestpp-jtwhite79](https://github.com/mwtoews/pestpp-jtwhite79)  
28. Crop Model Calibration \- agmiporg, 访问时间为 十二月 12, 2025， [https://agmip.org/crop-model-calibration-3/](https://agmip.org/crop-model-calibration-3/)  
29. dpest \- PyPI, 访问时间为 十二月 12, 2025， [https://pypi.org/project/dpest/](https://pypi.org/project/dpest/)  
30. intro to pyemu \- Groundwater Modelling Decision Support Initiative \- gmdsi, 访问时间为 十二月 12, 2025， [https://gmdsi.org/blog/intro-to-pyemu/](https://gmdsi.org/blog/intro-to-pyemu/)
