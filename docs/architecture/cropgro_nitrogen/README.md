# CROPGRO 氮素代谢机制与临界氮稀释理论缝合架构技术规范

**体系代号**: `ARCH-CROP-N`  
**版本**: v1.0.0 (Publication-Grade Technical Specification)  
**发布日期**: 2026-10-12  
**维护机构**: Tomato_Cal 核心系统架构与作物模型研发团队  
**基准模型**: DSSAT CSM v4.8.2 / v4.8.6.0 (`Plant/CROPGRO/`, `SPAM/`, `Soil/`)  
**目标作物**: 温室无限生长型茄子 (依托番茄模型 `TMGRO048.CUL` / `TMGRO048.SPE` / `TMGRO048.ECO`)

---

## 1. 执行总纲与科研背景 (Executive Summary)

本技术规范系列旨在系统性解剖与重构农业系统模型 DSSAT (CROPGRO) 的氮素代谢动力学及其碳氮反馈网络，解决传统作物模型中**“大叶单库门槛动员”**范式与现代植物生态生理学**“临界氮稀释定律（Greenwood-Lemaire 曲线，$N_c = a W^{-b}$）”**之间的深层理论冲突。

在前期日光温室茄子多批次采收水氮试验的参数反演中，我们观察到两类标志性的机理失真：
1. **高水高氮处理下需氮量虚高**：模型在群落生物量巨大时仍强行按幼苗期高浓度要求计算器官氮需求，导致对外界供氮的依赖性被过度夸大；
2. **低氮与限制处理下假性早衰死锁**：为了压低氮浓度以逼近田间实测值，反演算法被迫放开内源再动员参数，触发了 $LFSEN = SENRTE \times \frac{NRUSLF}{0.16}$ 的杀伤性落叶级联，造成冠层叶面积指数（LAI）暴跌、深秋停茬异常；
3. **多批次采收锯齿阶跃冲击**：摘除低氮鲜果导致现存地上干重骤降，引发瞬时组织氮浓度与 $NNI$ 假性阶跃跳增（实测跳变 $+4.5\%$），破坏批次坐果节律；
4. **协同反演参数不可辨识性**：$CNC\_A$ 与初始叶蛋白 $PROLFI$ 灵敏度共线性高达 $-0.9948$，联合反演导致雅可比矩阵结构性亏秩（$\kappa \approx 8.77 \times 10^{16}$），必须作为外生固化不变量处理。

通过对 CROPGRO 10 多个核心 Fortran 源码子程序的底层逐行审计与拓扑解析，本规范确立了**“两级双轨数据流模型”**，绘制了**“下游次生冲击与敏感度风险分级矩阵”**，提出了**“累积有效生物量连续性契约 ($W_{\text{eff}} = CWAD + CUMHARVEST$)”**与**“冻结外生不变量反演协议”**，并构建了**“在机器精度质量守恒约束下集成临界氮稀释理论的高性能流式架构路线图”**。

---

## 2. 规范分册索引与导读路径 (Specification Index & Reading Path)

本架构规范由四个高度互锁的专题分册组成，建议按照以下科研与工程逻辑次序研读：

```
                              ┌────────────────────────────────────────────────────────┐
                              │                       README.md                        │
                              │           (总览导读、符号公约、统一变量字典索引)        │
                              └──────────────────────────┬─────────────────────────────┘
                                                         │
                                                         ▼
                              ┌────────────────────────────────────────────────────────┐
                              │             dataflow_and_callgraph.md (R1)             │
                              │   (Fortran 源码定位、17步时序、Mermaid顺序图、全量数据流)  │
                              └──────────────────────────┬─────────────────────────────┘
                                                         │
                                                         ▼
                              ┌────────────────────────────────────────────────────────┐
                              │              downstream_impact_matrix.md (R2)          │
                              │    (PCNL/PCNST 拓扑、8大消费通道、4大反馈环路、三级风险矩阵)    │
                              └──────────────────────────┬─────────────────────────────┘
                                                         │
                                                         ▼
                              ┌────────────────────────────────────────────────────────┐
                              │          critical_n_integration_proposals.md (R3)      │
                              │    (本质冲突剖析、3套集成架构、质量守恒解析证明、PEST++适配器)  │
                              └────────────────────────────────────────────────────────┘
```

| 规范分册文件 | 核心内容定位 | 解决的核心科学/工程问题 |
|---|---|---|
| **`README.md`** | 顶层架构导引、统一变量符号表、核心结论索引 | 统一全团队符号标准与理论框架 |
| **`dataflow_and_callgraph.md`** | CROPGRO 氮代谢底层调用拓扑与变量流全景图 | 明确从 `RATE` 到 `INTEGR` 17 步时序，提供逐行源码级数据流字典 |
| **`downstream_impact_matrix.md`** | 碳氮耦合反馈网络与次生冲击风险矩阵 | 剖析 PCNL/PCNST 对 8 大下游环节的传导效应，界定 4 大反馈环路与三级风险隔离区 |
| **`critical_n_integration_proposals.md`** | 临界氮稀释理论与 CROPGRO 无破坏性缝合架构设计 | 剖析单库与稀释定律冲突，给出方案 A/B/C、守恒分析证明及 PEST++ 适配器实现 |

---

## 3. 统一符号公约与核心变量对照表 (Unified Nomenclature Table)

为了消除跨学科交流与 Fortran/数学建模之间的术语歧义，本技术规范统一遵循以下数学符号与代码变量对照体系：

| 数学符号 | Fortran 源码变量 | 物理量纲 / 单位 | 物理学与生物学定义 | 核心计算公式或来源 |
|:---:|---|:---:|---|---|
| $W_{\text{eff}}$ / $W_{\text{cum}}$ | `(CWAD + CUMHARVEST) / 1000.0` | $\text{t DM/ha}$ | 地上部累积有效干生物量 (现存+下树果实) | $\frac{CWAD + \sum \text{HARVEST\_DRY}}{1000.0}$ |
| $N_{\text{eff}}$ / $N_{\text{act,cum}}$ | 规范累积全氮量比值 | 质量百分比 $\text{\%}$ | 地上部累积实际全氮质量百分比 | $100.0 \times \frac{CNAD + \sum \text{HARVEST\_N}}{CWAD + \sum \text{HARVEST\_DRY}}$ |
| $N_c(W)$ | 规范新增变量 | 质量百分比 $\text{\%}$ | 基于累积有效生物量的临界氮浓度 | $N_c(W) = a \cdot [\max(W_0, W_{\text{eff}})]^{-b}$ |
| $NNI$ | 规范新增变量 | 无量纲标量 | 植株氮营养指数 (Nitrogen Nutrition Index) | $NNI = N_{\text{eff}} / N_c(W)$ |
| $C_{\text{leaf}}$ | `PCNL` | 质量百分比 $\text{\%}$ | 现存绿叶组织总氮质量百分比 | $\text{PCNL} = \frac{\text{WTNLF}}{\text{WTLF}} \times 100.0$ |
| $C_{\text{stem}}$ | `PCNST` | 质量百分比 $\text{\%}$ | 现存茎秆组织总氮质量百分比 | $\text{PCNST} = \frac{\text{WTNST}}{\text{STMWT}} \times 100.0$ |
| $C_{\text{photo}}$ | `RNITP` | 质量百分比 $\text{\%}$ | 去除非结构碳的结构基功能叶氮百分比 | $\text{RNITP} = 100.0 \times \frac{\text{WTNLF}}{\text{WTLF} - \text{WCRLF}}$ |
| $\Phi_{\text{uptake}}$ | `TRNU` | $\text{g[N]/m}^2\text{/d}$ | 全剖面根系吸收总氮通量 | `NUPTAK.for:187`, $\sum (\text{UNO3}+\text{UNH4})/10$ |
| $\Phi_{\text{mine}}$ | `NMINEA` | $\text{g[N]/m}^2\text{/d}$ | 当日植株内源实际再动员总通量 | `MOBIL.for:65`, $\min(\text{NDMNEW}-\text{TRNU}, \text{NMINEP})$ |
| $D_{\text{total}}$ | `NDMTOT` | $\text{g[N]/m}^2\text{/d}$ | 当日植株全口径理论总需氮量 | $\text{NDMTOT} = \text{NDMREP} + \text{NDMVEG} + \text{NDMOLD}$ |
| $I_{\text{NSTRES}}$ | `NSTRES` | 无量纲, $[0.0, 1.0]$ | 2 日滑动平均平滑氮胁迫指数 (1为无胁迫) | `VEGGR.for:256`, $0.5 X_{\text{NSTRES},t} + 0.5 X_{\text{NSTRES},t-1}$ |
| $E_{\text{excess}}$ | `EXCESS` | 无量纲, $[0.447, 1.0]$ | 碳过剩光合反馈下调乘子 | `VEGGR.for:386`, $[1.20 - \min(1, \max(\text{PGLEFT}/\text{PG}, 0.2))]^{0.5}$ |
| $\Delta M_{\text{sen}}$ | `LFSEN` | $\text{g DM/m}^2\text{/d}$ | 氮动员抽调诱发的伴生功能叶片脱落干重 | `SENES.for:209` (:198), $\text{SENRTE} \times \frac{\text{NRUSLF}}{0.16}$ |
| $LFSEN_{\text{act}}$ | 方案 B 新增受控量 | $\text{g DM/m}^2\text{/d}$ | 方案 B 衰老阻尼限幅日脱落叶干重 | $\min(LFSEN, \; \gamma \cdot WLDOTN), \; \gamma \le 1.0$ |
| $\eta_{\text{photo}}$ | `AGEFAC` | 无量纲标量 | 叶片氮浓度对单叶光合的乘性影响因子 | `PHOTO.for:134`, $\frac{\text{CURV}(\text{FNPGN}, \text{RNITP})}{\text{CURV}(\text{FNPGN}, \text{LNREF})}$ |

---

## 4. 核心科学结论与工程决策 (Core Scientific Conclusions & Engineering Verdict)

### 4.1 核心科学发现 (Scientific Findings)
1. **双轨解耦机制的生理本质**：
   CROPGRO 巧妙地将氮胁迫切分为“流量型指数 $NSTRES$”与“存量型浓度 $RNITP$”。在水肥转入亏缺初期，庞大的可动员库（$\text{WNRLF}$）能够维持充足的动员通量（$\text{NMINEA}$），使得表观分配上 $NSTRES = 1.0$；但存量端 $RNITP$ 的下滑已在悄然抑制单叶光合。动员库耗尽时，系统将发生断崖式的 Case C 硬着陆。
2. **动员致衰是导致参数反演病态早衰的元凶**：
   公式 $\text{LFSEN} = \text{SENRTE} \times \frac{\text{NRUSLF}}{0.16}$ 建立了“动员即杀伤”的强正反馈。当反演程序试图通过调整动员参数使模拟叶氮浓度贴近田间后期走低的数据时，极易越过临界点 $\text{LFSEN} > \text{WLDOTN}$，诱发叶面积雪崩早衰。
3. **宏观异速稀释定律与微观器官单库的不可调和性**：
   在单库架构下，任何强行代数覆写组织浓度的行为均会击穿 `PlantNBal.for` 严密的机器精度质量守恒约束，甚至诱发求解器发散。
4. **多批次采收锯齿阶跃与累积生物量解耦**：
   单次鲜果采收导致现存地上干重骤降，诱发组织氮浓度与 $NNI$ 假性阶跃跳升（实测单日跳变 $+4.5\%$）。引入累积有效生物量 $W_{\text{eff}} = CWAD + CUMHARVEST$ 与累积全氮量 $N_{\text{eff}} = CNAD + CUMHARVEST\_N$，在数学上严格保证 $\Delta W_{\text{eff}} \equiv 0, \Delta N_c \equiv 0, \Delta NNI \equiv 0$，彻底消除分批采收的假性数值冲击。
5. **参数可辨识性定理与冻结不变量协议**：
   $CNC\_A$ 与初始叶蛋白 $PROLFI$ 灵敏度相关性高达 $-0.9948$，联合反演导致雅可比矩阵严重亏秩（$\kappa \approx 8.77 \times 10^{16}$，第 5 奇异值跌入数值零陷）。必须将 $CNC\_A$ ($4.85$)、$CNC\_B$ ($0.38$) 与 $CNC\_W0$ ($1.00$) 设为冻结外生不变量（`status: fixed`），作为刚性物理锚点指导反演收敛。

### 4.2 推荐无破坏性工程落地路线图 (Recommended Phased Roadmap)
针对以上科学矛盾，本架构团队做出如下分阶段工程裁决：

```
[Phase 1: 当前反演即刻落地]
方案 A: 后验软约束映射法 (Posterior Soft-Constraint Regularization)
  · 状态: 立即生效 (Drop-in Ready)
  · 策略: 保持 DSSAT Fortran 求解器零侵入；
          在 run_dssat.py 增加 PestCNC.OUT 高性能定宽流式导出适配器 (6.95 ms)；
          采用累积生物量 W_eff 消除采收锯齿波；
          在 build_pest.py 增加 cnc_nni 观测组、稀疏物候抽样 (3~5点/处理) 与标准权重 (0.05~0.50)；
          施加对称生理区间目标函数惩罚 (N0: 0.40~0.70; N3: 1.00~1.30)；
          将 CNC_A, CNC_B, CNC_W0 设为冻结外生不变量 (status: fixed)。
  · 收益: 0 编译风险，0 守恒破坏风险，直接消解反演优化中的 70% 边界触界与等效异构死锁。
      │
      ▼
[Phase 2: 机制深化受控储备]
方案 B: 动态内源光合耦合挂钩法 (Endogenous Photosynthetic Coupling)
  · 状态: 研发储备 (Research Baseline)
  · 策略: 搭建 DSSAT CSM v4.8 本地编译流水线；
          在 PHOTO.for 中注入有界平滑 Sigmoid 门控 S(NNI) 与出苗除零保护；
          在 SENES.for 强制配对日落叶限幅器 LFSEN_actual = min(LFSEN, gamma * WLDOTN)。
  · 收益: 模拟植物自发的光温碳氮协调生长，消除高氮处理下同化过量并阻断 3.12x 放大雪崩死锁。
      │
      ▼
[Phase 3: 作物模型下一代演化]
方案 C: 大叶单库向有效稀释层解耦法 (Effective Dilution Layer Decoupling)
  · 状态: 远期探索 (Next-Gen Architecture)
  · 策略: 彻底重写状态变量，分离代谢氮与结构稀释氮，阻断 LFSEN 毁灭性级联。
```

---

## 5. 质量保证与合规声明 (Quality Assurance & Compliance)

本系列规范所有数据流、行号与数学公式均经过本地完整 DSSAT CSM v4.8.2 / v4.8.6.0 源码的独立静态审计，且与本项目历史试验（XXQL2501、XXQL2601、XXQL2502）的数据治理规范、`tests/test_migration.py` 及 `tests/test_publication_figures.py` 严格保持 100% 向下兼容。
