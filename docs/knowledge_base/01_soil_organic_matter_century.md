# Volume 01: CENTURY 土壤有机碳氮循环动力学与高肥力温室“假饱”机理

> **知识库分册编号**：`KB-DSSAT-CROPGRO-VOL-01`  
> **模块代码**：`CENTURY_SOM` (`Soil/Century/CENTURY.for`, `SOMCAS.for`, `SOMDEC_C.for`, `SOILNI.for`)  
> **适用品种与模型**：温室茄子（依托番茄模型引擎 `TMGRO048`，DSSAT CSM v4.8.2 / v4.8.6）  
> **核心议题**：三库碳动力学、净氮矿化通量计算、`SLNF` 静默重置与失效审计、CERES 与 CENTURY 对照证伪、`SASC_RATIO` 控被动碳库化解 N0 假饱

---

## 1. 模块架构与知识体系概述

在 DSSAT-CSM (Cropping System Model) 体系中，土壤有机质与养分周转模块负责模拟碳、氮、磷等生源要素的生物地球化学循环。对于设施蔬菜（如日光温室茄果类）连续耕作系统而言，土壤有机碳含量通常处于较高水平（总有机碳 $SAOC \approx 1.5\% \sim 2.5\%$，相当于土壤有机质 $SOM \approx 2.6\% \sim 4.3\%$）。在此类高肥力温室土壤中，土壤有机碳的矿化分解速率直接决定了土壤溶液中无机态氮（$\text{NO}_3^-$ 与 $\text{NH}_4^+$）的内生供给强度。

DSSAT 提供了两套独立的有机质周转子模型，由实验控制文件（FileX，`*.TMX`）中 `SIMULATION CONTROLS` 小节的开关变量 `MESOM` 选定：
1. **CERES-SOM 模式 (`MESOM = 'G'`)**：基于旧版 CERES 模型的单/双库经验降解模型，主要适用于低有机质、雨养大田作物的快速矿化计算；
2. **CENTURY-SOM 模式 (`MESOM = 'P'`)**：移植自 Parton 等人提出的经典 CENTURY 土壤有机质动力学模型，将有机质细分为活性、慢速与被动三大不同物理化学保护程度的动力学碳库。

本项目在早期探索中曾遭遇严重的**零氮（N0）处理“假饱”现象**：在完全不施外源化学氮肥的处理中，模型计算出的土壤内生矿化氮供给量过高（全季净矿化量高达 $145.2\text{ kg N/ha}$），导致 N0 处理植株生物量与产量模拟值居高不下，无法重现田间实测显著的施氮增产效应（田间实测 26SP 增产达 $+16.5\text{ t/ha}$，而模型初期模拟仅 $+6.2\text{ t/ha}$ 甚至倒挂减产）。

本分册系统阐述 CENTURY 模块的底层微分动力学方程、代码执行流、历史参数调控假说的证伪审计，以及通过 `SASC_RATIO` 调节被动碳库分配比例的最终解决方案。

---

## 2. CENTURY 三库碳动力学数学模型与控制方程

### 2.1 动力学碳库划分与物性参数

CENTURY 模型将进入土壤的有机碳与土壤原位有机碳解耦为三大动力学碳库（Pools）：
1. **活性微生物碳库 (Microbial / Active Organic Carbon, SOM1)**：
   - 组成：土壤活体微生物生物量、分泌物及微细易降解代谢物；
   - 周转时间（Turnover Time, $\tau_1$）：$0.1 \sim 1.0\text{ 年}$；
   - 基础分解速率常数（Base Decomposition Rate, $k_1$）：$0.0200\text{ day}^{-1}$；
   - 标称碳氮比 ($CN_1$)：$8.0 \sim 10.0$。
2. **慢速有机碳库 (Slow Organic Carbon, SOM2)**：
   - 组成：受物理包裹保护的微团聚体有机质及中度腐殖化植物残体；
   - 周转时间 ($\tau_2$)：$10 \sim 50\text{ 年}$；
   - 基础分解速率常数 ($k_2$）：$0.00055\text{ day}^{-1}$；
   - 标称碳氮比 ($CN_2$)：$11.0 \sim 15.0$。
3. **被动/惰性碳库 (Passive Organic Carbon, SOM3)**：
   - 组成：高度缩合的胡敏素、顽固芳香族碳以及与黏土矿物紧密结合的难降解有机碳；
   - 周转时间 ($\tau_3$)：$200 \sim 1500\text{ 年}$；
   - 基础分解速率常数 ($k_3$）：$0.000012\text{ day}^{-1}$；
   - 标称碳氮比 ($CN_3$)：$10.0 \sim 12.0$。

### 2.2 一级反应动力学微分方程

对于土层 $L$（层厚 $\Delta z_L$，单位 $\text{cm}$），每个碳库 $C_i(L)$（单位 $\text{kg C/ha}$）在日步长下的分解通量严格遵循一级动力学微分方程：

$$\frac{dC_i(L)}{dt} = - k_i \cdot C_i(L) \cdot f(T_L) \cdot f(W_L) \cdot f_{cult}(L)$$

式中：
- $k_i$ 为对应碳库的基础分解常数（$k_1 = 0.02$, $k_2 = 0.00055$, $k_3 = 0.000012\text{ d}^{-1}$）；
- $f(T_L)$ 为土壤温度环境影响因子；
- $f(W_L)$ 为土壤水分环境有效性因子；
- $f_{cult}(L)$ 为耕作扰动增强因子（设施温室通常取 $1.0$）。

#### 2.2.1 土壤温度响应函数 $f(T)$
在 `SOMDEC_C.for` 中，温度响应因子采用带有最适温区的非线性钟形曲线：

$$f(T_L) = \frac{T_{soil}(L) - T_{min}}{T_{opt} - T_{min}} \cdot \left( \frac{T_{max} - T_{soil}(L)}{T_{max} - T_{opt}} \right)^{\frac{T_{max} - T_{opt}}{T_{opt} - T_{min}}}$$

在标准参数下，$T_{min} = 0.0^\circ\text{C}$，$T_{opt} = 35.0^\circ\text{C}$，$T_{max} = 45.0^\circ\text{C}$。当土壤温度位于日光温室典型的 $18^\circ\text{C} \sim 28^\circ\text{C}$ 之间时，$f(T) \in [0.45, 0.82]$，为微生物矿化提供了持续高效的热量驱动。

#### 2.2.2 土壤水分响应函数 $f(W)$
水分响应因子取决于该土层当前体积含水量 $\theta(L)$、田间持水量 $SDUL(L)$、下限含水量 $SLLL(L)$ 与饱和含水量 $SSAT(L)$：

$$f(W_L) = \begin{cases} 
0.0, & \theta(L) \le SLLL(L) \\ 
\frac{\theta(L) - SLLL(L)}{SDUL(L) - SLLL(L)}, & SLLL(L) < \theta(L) \le SDUL(L) \\ 
1.0 - 0.5 \cdot \frac{\theta(L) - SDUL(L)}{SSAT(L) - SDUL(L)}, & SDUL(L) < \theta(L) \le SSAT(L) 
\end{cases}$$

在温室水肥一体化滴灌条件下，表层 $0 \sim 30\text{ cm}$ 土壤水分长期维持在田间持水量的 $70\% \sim 95\%$ 之间，因此 $f(W_L)$ 长期保持在 $0.70 \sim 1.00$ 的极高区间，加剧了有机质的快速分解。

### 2.3 碳周转与净氮矿化通量 ($NMNC$) 耦合模型

碳库分解产生的碳通量并不会全部释放为 $\text{CO}_2$，一部分作为微生物呼吸释放（比例为 $1 - E_i$），另一部分被微生物再同化并转化为新生 SOM1 或向下转移至 SOM2/SOM3。

碳转化通量矩阵方程：

$$\mathbf{F}_{C} = \begin{pmatrix} 
\text{SOM1} \to \text{SOM2} \\ 
\text{SOM1} \to \text{SOM3} \\ 
\text{SOM2} \to \text{SOM1} \\ 
\text{SOM2} \to \text{SOM3} \\ 
\text{SOM3} \to \text{SOM1} 
\end{pmatrix} = \begin{pmatrix} 
f_{12} \cdot E_1 \cdot \left|\frac{dC_1}{dt}\right| \\ 
f_{13} \cdot E_1 \cdot \left|\frac{dC_1}{dt}\right| \\ 
f_{21} \cdot E_2 \cdot \left|\frac{dC_2}{dt}\right| \\ 
f_{23} \cdot E_2 \cdot \left|\frac{dC_2}{dt}\right| \\ 
f_{31} \cdot E_3 \cdot \left|\frac{dC_3}{dt}\right| 
\end{pmatrix}$$

其中 $E_i$ 为微生物同化碳利用率（Microbial Carbon Use Efficiency, CUE，取 $0.45 \sim 0.55$），其余 $1 - E_i$ 转化为异养呼吸 $\text{CO}_2$。

伴随碳流的逐日分解与微生物再合成，土层 $L$ 释放至土壤无机矿质氮库（$\text{NH}_4^+$ 库）的净氮矿化量（Net Nitrogen Mineralization from Carbon, $NMNC(L)$，单位 $\text{kg N/(ha}\cdot\text{day)}$）由各库总释放氮与微生物同化吸持氮的代数差严格决定：

$$NMNC(L) = \sum_{i=1}^{3} \left[ \left|\frac{dC_i(L)}{dt}\right| \cdot \frac{1}{CN_i} - E_i \cdot \left|\frac{dC_i(L)}{dt}\right| \cdot \frac{1}{CN_{microbe}} \right]$$

- 当某库的碳氮比 $CN_i$ 较低（如 SOM1 的 $CN \approx 8$、SOM2 的 $CN \approx 12$）且微生物自身 $CN_{microbe} \approx 8$ 时，分解过程释放的氮素远超微生物合成新细胞所需的氮素，表现为**强烈的正向净矿化**；
- 若土壤初始碳库中活性碳（SOM1）与慢速碳（SOM2）占比过大，由于 $k_1$（0.02）与 $k_2$（0.00055）分解速率较快，每日将产生天量矿化氮，完全掩盖化肥处理之间的梯度差异。

---

## 3. Fortran 源码逐行审计：`SLNF` 静默重置与失效判定

在解决温室 N0“假饱”过程中，早期团队曾试图通过下调土壤剖面参数 `SLNF`（Soil Fertility Factor，土壤肥力因子，默认 1.0）至 0.4~0.6 来抑制内生矿化，甚至有算法工程师提议将 `SLNF` 的搜索空间放宽至 3.0~10.0。

通过对 DSSAT CSM v4.8.2 官方源码的逐行审计，证实该方案在理论与工程执行上存在**双重致命缺陷**。

### 3.1 审计一：`InputModule/IPSOIL_Inp.for` 中的静默截断与重置

在读取土壤数据库文件（`*.SOL`）的层属性时，`IPSOIL_Inp.for` 第 350~360 行解析参数：

```fortran
350:                  CASE('SCOM'); READ(C255(C1:C2),*,IOSTAT=ERR) SCOM
351:                  CASE('SALB'); READ(C255(C1:C2),*,IOSTAT=ERR) SALB
352:                  CASE('SLU1'); READ(C255(C1:C2),*,IOSTAT=ERR) U
353:                  CASE('SLDR'); READ(C255(C1:C2),*,IOSTAT=ERR) SWCON
354:                  CASE('SLRO'); READ(C255(C1:C2),*,IOSTAT=ERR) CN2
355:                  CASE('SLNF'); READ(C255(C1:C2),*,IOSTAT=ERR) SLNF
356:                  CASE('SLPF'); READ(C255(C1:C2),*,IOSTAT=ERR) SLPF
```

随后，在参数合法性检验阶段，`IPSOIL_Inp.for` 第 485~492 行执行了**无条件硬编码截断**：

```fortran
485:          IF (SLNF > 1.0 .OR. SLNF < 0.0) THEN
486:             SLNF = 1.0
487:             IF (ISWITCH%ISWNIT .NE. 'N') THEN
488:                MSG(1) = "Invalid value for SLNF in soil file."
489:                MSG(2) = "Value changed to 1.0."
490:               CALL WARNING(2,ERRKEY,MSG)
491:             ENDIF
492:          ENDIF
```

#### 审计结论 1：
当参数反演工具（如 PEST++）在大于 1.0 的范围（例如 1.5、3.0、10.0）进行参数寻优时，DSSAT 仅在内部向 `WARNING.OUT` 打印一条警告信息，并**静默将 `SLNF` 重置为 1.0**。从外部看，模型执行成功（Exit Code 0），但不同参数取值输出的目标函数（Phi）完全相同。这在反演参数空间内构建了一个虚假的平坦流形（Zero-Gradient Plateau），导致基于梯度或集合平滑的优化算法陷入无效空转。

---

### 3.2 审计二：`Soil/CENTURY_OrganicMatter/SOMDEC_C.for` 中 `DMOD` 乘数的物理注释与失效

即便将 `SLNF` 设定在合法区间 $[0.0, 1.0]$ 内（例如 0.4 或 0.6），该参数在 CENTURY 模式下依然**完全不参与计算**。

1. **变量映射溯源**：  
   在 `Utilities/ModuleDefs.for` 第 175 行：
   ```fortran
   175:        REAL ALES, DMOD, SLPF         !DMOD was SLNF
   ```
   在 `Soil/SoilUtilities/SOILDYN.for` 第 853 行：
   ```fortran
   853:      SOILPROP % DMOD   = DMOD        !formerly SLNF
   ```
   这证明底层数据结构中 `DMOD` 即对应土壤输入中的 `SLNF`。

2. **主控驱动注释**：  
   在 `Soil/CENTURY_OrganicMatter/CENTURY.for` 第 183~184 行，原本接收 `DMOD` 的代码已被彻底注释：
   ```fortran
   183: !      DMOD   = SOILPROP % DMOD
   184: !      IF (DMOD < -1.E-6) CALL ERROR("DMOD",0,"SOILPROP",0)
   ```

3. **分解通量逐库计算源码审计**：  
   查证 `Soil/CENTURY_OrganicMatter/SOMDEC_C.for`，官方代码维护日志与实际流计算如下：
   ```fortran
   24:  !  02/10/2009 CHP Remove effects of DMOD for CENTURY model
   ...
   189:      &    CULS1(SRFC) * TXS1(1) !* DMOD
   ...
   241:      &     !* DMOD
   ...
   306:           TCFLOW = SOM2C(L) * DEFAC(L) * DECS2(SOIL) * CULS2(L) !* DMOD
   ...
   353:           TCFLOW = SOM3C(L) * DEFAC(L) * DECS3(SOIL) * CULS3(L) !* DMOD
   ```

#### 审计结论 2：
在 CENTURY 有机质模块中，开发者自 2009 年起已明确移除了 `DMOD`（即 `SLNF`）对分解动力学的影响。SOM1、SOM2 与 SOM3 各碳库分解通量 `TCFLOW` 中，`!* DMOD` 均被显式注释。因此：
$$\frac{\partial NMNC}{\partial SLNF} \equiv 0.0 \quad (\forall\ MESOM = \text{'P'})$$
在 CENTURY 运行模式下调节 `SLNF` 无法降低任何土壤内生矿化氮。

---

## 4. CERES-SOM vs. CENTURY 多臂对照与中期坍塌机理

在认识到 `SLNF` 失效后，项目组曾提出切换回 CERES-SOM 模式（`MESOM = 'G'`）的多臂对照试验。然而，系统评估证明 CERES 模块无法胜任现代设施温室连续高负荷生产的模拟需求。

### 4.1 CERES-SOM 模式在温室环境下的缺陷

1. **库容结构单一，缺乏长期缓冲**：  
   CERES 模型（`SOILNI.for` / `NMINER.for`）主要依赖表层新鲜残茬库（`FON`）与未分层的腐殖质库（`HUM`）。在缺乏逐日大量外源新鲜秸秆输入的温室连作条件下，新鲜残茬库在定植后 30~45 天内即被迅速耗竭。
2. **生育中期矿化“断崖式坍塌”**：  
   实测温室茄子生殖生长期跨度达 60~90 天，需要土壤持续供给基础氮素。CERES 模式在定植前期因初始库过快分解出现短时氮过剩，但在开花挂果盛期（DAP 60 以后），内生矿化通量骤降至接近于零。
3. **高水处理报复性早衰**：  
   在充分灌溉高产处理（如 W3N2, W3N3）中，蒸腾量大、根系吸水量高，淋溶作用加速了前期累积矿质氮的下渗。中期矿化坍塌后，植株瞬间由氮素过剩转为极度重度缺氮，导致冠层下部叶片在 6 月上旬大面积发黄脱落，最终经济产量模拟偏差超过 $40\%$。

### 4.2 两种模块特性对照矩阵

| 评估维度 | CERES-SOM (`MESOM = 'G'`) | CENTURY-SOM (`MESOM = 'P'`) | 设施温室适用性判定 |
| :--- | :--- | :--- | :--- |
| **碳库动力学划分** | 粗放 2 库（新鲜有机物 FON + 腐殖质 HUM） | 严格 3 动力学库（活性 SOM1、慢速 SOM2、惰性 SOM3） | CENTURY 胜出：符合土壤物理保护机制 |
| **基础周转尺度** | 短期线性衰减（数月尺度） | 跨尺度耦合（月、十年、千纪三级时间常数） | CENTURY 胜出：兼顾当季爆发与长效缓冲 |
| **温室高温响应** | 高温下前期过度释放，中期快速枯竭 | 具有稳态温度敏感性函数，释放平稳可控 | CENTURY 胜出：避免生殖生长期氮断崖 |
| **`SLNF` 控制有效性** | **有效**（直接参与矿化乘数） | **无效**（代码已注释 `!* DMOD`） | 需注意：CERES 虽受控但缺乏生理机理 |
| **高有机质土壤可调控性**| 调控手段有限，极易造成生长停滞 | **可通过 `SASC_RATIO` 严格约束被动库分配** | **最终结论：必须坚持 CENTURY 架构** |

---

## 5. 高肥力温室“假饱”机理破解：`SASC_RATIO` 控被动碳库方案

### 5.1 假饱现象的本质：初始碳库分配失真

在 FileX 和土壤剖面输入中，土壤总有机碳（`SAOC`，%）通常来源于常规农化分析（重铬酸钾氧化外加热法）。常规化验仅能提供总有机碳总量，无法提供 SOM1、SOM2、SOM3 的动力学分配比例。

在未显式指定稳定有机碳时，DSSAT CENTURY 初始化子程序（`Soil/Century/CENTURY.for`）默认采用大田农田经验平衡公式分配碳库：
- 默认分配中，慢速库（SOM2）与活性库（SOM1）占据了初始碳库的大部分份额；
- 对于日光温室总有机碳高达 $1.5\% \sim 2.0\%$ 的熟化土壤，由于土温常年维持在 $15^\circ\text{C} \sim 28^\circ\text{C}$ 且滴灌湿润锋持续供水，大量碳进入 SOM1 和 SOM2 分解循环；
- 模拟计算的全季净矿化氮量（$NMNC$）达到 **128.4 ~ 145.2 kg N/ha**。对于目标产量 60~70 t/ha 的茄子而言，仅土壤内生矿化即满足了其 $70\% \sim 85\%$ 的总吸氮需求，致使 N0 处理无需外源氮肥即可获得与 N3 处理相当的高产，造成“假饱”与施氮增产效应失真。

### 5.2 解决方案：通过 `SASC` 锁定 SOM3 被动碳库

CENTURY 模块允许在 FileX 的 `@A SOIL ANALYSIS` 小节中显式指定稳定/被动有机碳（Stable Organic Carbon, `SASC`，%）。  
定义无量纲分配参数：

$$SASC\_RATIO = \frac{SASC(L)}{SAOC(L)}$$

当指定 `SASC` 后，模型将总有机碳的相应份额直接固化在基础分解速率极低（$k_3 = 0.000012\text{ d}^{-1}$）的 SOM3 惰性库中，剩余份额（$1 - SASC\_RATIO$）再进入可快速周转的 SOM1 和 SOM2。

### 5.3 `SASC_RATIO` 正交扫描试验与科学对账

项目组在 2025 春（25SP）与 2026 春（26SP）数据集上，对 $SASC\_RATIO \in [0.70, 0.95]$ 进行了系统性的正交梯度扫描（见下表）：

| SASC_RATIO 取值 | 全生育期内生净矿化量 (NMNC) | 26SP W1 施氮增产 ($\Delta Y$) (实测: +16.5 t/ha) | 25SP W1 施氮增产 ($\Delta Y$) (实测: +11.6 t/ha) | N0 状态与农学机理评价 |
| :---: | :---: | :---: | :---: | :---|
| **0.70** (历史粗放值) | 128.4 ~ 145.2 kg N/ha | +6.2 t/ha | -1.2 t/ha (施氮倒挂减产) | 活性碳高达 30%，矿化失控，N0 假饱严重，出现反常倒挂 |
| **0.88** (中阶过渡值) | 98.6 kg N/ha | +11.4 t/ha | +2.8 t/ha | 倒挂现象消除，但施氮响应弹性仍偏弱，未达实测响应 |
| **0.94** (**冠军 C15 选定**) | **88.4 kg N/ha** | **+16.2 t/ha (保真度 98.2%)** | **+6.7 ~ +8.24 t/ha** | **完美压实内生矿化，真实重现田间强施氮响应，双春拟合优度最高** |
| **0.95** (高阶约束值) | 83.1 kg N/ha | +16.8 t/ha | +7.1 t/ha | 施氮增产显著，但深秋低温期偶发氮素亏缺过早衰老风险 |

#### 科学事实定论：
1. 当 $SASC\_RATIO = 0.70$ 时，全季内生矿化量高达 $145.2\text{ kg N/ha}$，造成 25SP W1 处理施氮增产为负值（$-1.2\text{ t/ha}$），严重违背农学实际；
2. 随着 $SASC\_RATIO$ 提升至 **0.94**，全季矿化量稳定被压缩至 **88.4 kg N/ha**，释放了施氮响应空间，26SP W1 施氮增产达到 **+16.2 t/ha**，完美吻合田间实测值（$+16.5\text{ t/ha}$）；
3. 该参数与 26SP 初始无机氮折减系数 **`ICNS_26SP = 0.70`** 形成有机互补：`ICNS_26SP` 修正了苗期表层滴灌残氮局部富集采样误差，而 `SASC_RATIO = 0.94` 约束了全生育期的动态释放通量。

---

## 6. 工程实施与配置规范指南

### 6.1 FileX (`*.TMX`) 输入规范

在试验控制文件（FileX）中，必须确保以下两处配置协调一致：

1. **激活 CENTURY 模式**（`*SIMULATION CONTROLS` 小节）：
   ```text
   @N GENERAL     NYERS NREPS START SDATE RSEED SNAME.................... SMODEL
    1 GE              1     1     S 25076     1 DEFAULT METHOD
   @N OPTIONS     WATER NITRO SYMBI PHOSP POTAS DISID CHEM  TILL  CO2
    1 OP              Y     Y     N     N     N     N     N     N     M
   @N METHODS     WTHER INPRO MVEG  MCHM  MSOL  MLCH  MESOM MESEV MESOL
    1 ME              M     S     M     A     S     N     P     R     2
   ```
   **关键点**：`MESOM` 列必须显式指定为 **`P`**（代表 CENTURY 动力学模块），严禁指定为 `G`（CERES 模块）。

2. **注入稳定碳比例 `SASC`**（`*SOIL ANALYSIS` 小节）：
   各层根据实测总有机碳 $SAOC$ 与固化比例 $SASC\_RATIO = 0.94$ 逐层计算并填报 `SASC`：
   ```text
   *SOIL ANALYSIS
   @A SADAT  SMHB  SMPX  SMKE  SANAME
    1 25075 SA012 SA001 -99   Analysis Layer 1-10
   @A  SABL  SADM  SAOC  SANI  SAPHW  SAPHB  SMPX  SKE   SASC
    1     2   -99  1.85   -99   7.20   -99   -99   -99  1.739
    1     4   -99  1.85   -99   7.20   -99   -99   -99  1.739
    1    15   -99  1.70   -99   7.25   -99   -99   -99  1.598
    1    30   -99  1.45   -99   7.30   -99   -99   -99  1.363
    1    45   -99  1.10   -99   7.35   -99   -99   -99  1.034
    1    60   -99  0.85   -99   7.40   -99   -99   -99  0.799
    1    80   -99  0.60   -99   7.45   -99   -99   -99  0.564
    1   100   -99  0.45   -99   7.50   -99   -99   -99  0.423
    1   140   -99  0.30   -99   7.55   -99   -99   -99  0.282
    1   180   -99  0.20   -99   7.60   -99   -99   -99  0.188
   ```

### 6.2 模板文件 `.base` 维护禁忌
- **禁忌 1**：严禁在 `data/parameter_registry/` 或 PEST 控制文件（`*.pst`）中将 `SLNF` 作为活动待优化参数；
- **禁忌 2**：在编写自动构建脚本（如 `build_pest.py`）时，若检测到 `SLNF > 1.0`，应直接阻断报错，杜绝因 DSSAT 静默重置为 1.0 而导致算法陷入平坦平原。

---

## 7. 独立验证与对账方法

为验证本分册论述的源码事实与数据准确性，推荐执行以下验证命令：

### 7.1 Fortran 源码关键行独立检索
在系统终端执行以下 PowerShell 检查命令：

```powershell
# 1. 验证 IPSOIL_Inp.for 对 SLNF > 1.0 的静默拦截重置
powershell -Command "Select-String -Path 'D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\InputModule\IPSOIL_Inp.for' -Pattern 'SLNF > 1.0' -Context 0,6"

# 2. 验证 SOMDEC_C.for 中 DMOD (SLNF) 乘数的物理注释
powershell -Command "Select-String -Path 'D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Soil\CENTURY_OrganicMatter\SOMDEC_C.for' -Pattern '!* DMOD' -Context 0,2"

# 3. 验证 ModuleDefs.for 中 DMOD 原型为 SLNF 的注释说明
powershell -Command "Select-String -Path 'D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Utilities\ModuleDefs.for' -Pattern 'DMOD was SLNF' -Context 0,2"
```

### 7.2 系统回归与测试套件校验
运行项目核心测试以确认未破坏现有测试契约：

```bash
python tests/test_migration.py
python -m pytest tests/test_publication_figures.py
```

---

## 8. 参考文献与关联文档索引

1. **核心关联技术报告**：
   - `docs/archive/dssat_modules/soil_organic_matter/CROPGRO_Eggplant_SASC与深层根系SRGF网格试验科学对账报告_20260918.md`
   - `docs/archive/dssat_modules/soil_organic_matter/CROPGRO_Eggplant_CENTURY_SASC089_095正式参数率定验收报告_20260918.md`
   - `docs/archive/dssat_modules/soil_organic_matter/CROPGRO_Eggplant_CENTURY_SASC率定与26SP缩放固定执行验收报告_20260918.md`
   - `docs/archive/dssat_modules/nitrogen_phosphorus_dynamics/E02_v46_26SP_soil_N_scale_sweep_20260901.md`
2. **底层 Fortran 源码基准**：
   - Parton, W. J., et al. (1987). Analysis of factors controlling soil organic matter levels in Great Plains grasslands. *Soil Science Society of America Journal*, 51(5), 1173-1179.
   - Gijsman, A. J., et al. (2002). Modifying DSSAT for partial-or no-tillage systems: incorporating the CENTURY approach. *Agronomy Journal*, 94(3), 528-541.
