# DSSAT × PEST++ 智能率定与作物生理建模经验知识库 (Knowledge Base)

本知识库系统性整理并沉淀了本项目在茄子（基于 DSSAT-CROPGRO TMGRO048 模型）× PEST++ (IES) 多季节、多处理自动化参数率定与生理机理调试中的全套核心经验、数学推导、代码陷阱与避坑指南。

---

## 知识库目录导航

| 序号 | 模块名称 | 核心内容与解决的关键问题 | 适用场景 |
| :--- | :--- | :--- | :--- |
| **01** | [目标函数构建与权重多尺度平衡机制](file:///D:/Tomato_Cal/docs/calibration_knowledge_base/01_目标函数构建与权重多尺度平衡机制.md) | 深入解析目标掩盖与权重失真机理、多尺度观测（物理实值 vs 对数无量纲）权重推导、T8/T10 预算分配公式、前缀匹配陷阱 | 目标函数设计、权重调优、解决“产量模拟极差但 Phi 极小”问题 |
| **02** | [CROPGRO氮代谢与胁迫响应参数调控机理](file:///D:/Tomato_Cal/docs/calibration_knowledge_base/02_CROPGRO氮代谢与胁迫响应参数调控机理.md) | CROPGRO 氮代谢计算链条、平缓极端氮胁迫的四阶调节机理、45 组数值受控实验参数边界沉淀、8 处理率定 vs 验证集设计 | 氮胁迫异常调优、生理参数物理边界设定、水氮梯度对比目标构建 |
| **03** | [PEST_IES算法调优与大规模并行工程实践](file:///D:/Tomato_Cal/docs/calibration_knowledge_base/03_PEST_IES算法调优与大规模并行工程实践.md) | GLM-IES 集合平滑器数学原理、Marquardt Lambda 步长机制、先验-数据冲突（PDC）防崩溃配置、沙箱并行与进程守护 | 高性能并行率定部署、解决 SVD 崩溃与数值停滞、算法收敛性诊断 |
| **04** | [生殖分配与源库平衡黄金参数域](file:///D:/Tomato_Cal/docs/calibration_knowledge_base/04_生殖分配与源库平衡黄金参数域.md) | 无限生长型茄果类作物源库平衡博弈、`XFRT/PGEFF/NMOBMX` 等参数触边机理、异参同效防范、多层参数防御体系 | 遗传参数率定、产量与营养生长失衡纠正、参数后验可信度审计 |
| **05** | [数据质量治理与全处理拟合能力审计方法论](file:///D:/Tomato_Cal/docs/calibration_knowledge_base/05_数据质量治理与全处理拟合能力审计方法论.md) | 实测硝态氮与含水率清洗复盘、鲜重直接率定决策、22 处理全景回放矩阵、双轨图表规范与学术严谨性保障 | 试验数据预处理、回放验证、科研图表输出与成果发表准备 |

---

## 核心设计哲学

1. **显式严谨性（Explicit Rigor）**：
   - 严禁隐式推断水氮处理梯度；
   - 严禁图表渲染端私自调用 `geom_smooth()` 拟合缺失观测；
   - 严禁算法端私自丢弃或修改先验冲突的物理权重。
2. **多层参数防护（Layered Defense）**：
   - 物理硬边界（Physical Hard Bounds） $\rightarrow$ 基线建议（Baseline） $\rightarrow$ 敏感性提议（Proposal） $\rightarrow$ 冻结参数库（Frozen Bounds）。
3. **可复现性（Reproducibility）**：
   - 每次正式率定必须通过确定性回放（Deterministic Replay）在 22 个处理上验证全生命周期动态（LAI、生物量、土壤水、鲜产量）。
