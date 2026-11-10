# Volume 03: CRGRO-PHENOL & TRANS 物候发育、移栽苗龄效应与基温跨季泛化

> **知识库分册编号**：`KB-DSSAT-CROPGRO-VOL-03`  
> **模块代码**：`PHENOL_TRANS` (`Plant/CROPGRO/PHENOL.for`, `TRANS.for`, `Ipphenol.for`, `RStages.for`, `Utilities/UTILS.for`)  
> **适用品种与模型**：温室茄子（依托番茄模型引擎 `TMGRO048`，DSSAT CSM v4.8.2 / v4.8.6）  
> **核心议题**：四基点温度分段梯形插值方程、移栽苗龄 `PAGE` 生理积分机理与 7 梯度矩阵（$PAGE < 19\text{d}$ 减产 $70\%$ 归因及 22.0d 农事日志对账）、基温 `TB1` 春季过拟合与“秋季低温飞车”消解（$6.5 \sim 7.5^\circ\text{C}$ 飞车至 $27.5\text{ t/ha}$ vs. $8.9 \sim 9.21^\circ\text{C}$ 降温截茬盲测 NRMSE=18.38%）

---

## 1. 模块架构与物候发育理论

在 CROPGRO 作物生长模型中，物候发育进程（Phenological Development）是调控整株碳氮分配、叶面积扩展、器官形态建成及多次开花坐果节律的“时钟驱动核心”。

茄果类蔬菜（如茄子、番茄）属于具有无限生长习性（Indeterminate Growth Habit）的多年生草本植物。在农业生产中，主要经历以下生理发育阶段（Phenological Stages）：
1. **播种与出苗期**（Stage 1: Emergence, 出土发芽）；
2. **营养生长期与幼苗期**（Stage 2: Vegetative Stages, 展开叶节位 $VSTAGE$ 逐节增加）；
3. **初花期**（Stage 3: First Flower, $R1$ / 代码 `ADAPS`）；
4. **首果形成期**（Stage 4: First Pod / Fruit, $R3$ / 代码 `PDFPS`）；
5. **始收与盛果期**（Stage 5: Full Seed / Pod Fill, $R5$ / 进入分批次采收 `CHPDT`）；
6. **终熟与生理拉秧**（Stage 7/8: Physiological Maturity / Season End）。

物候模拟由 `PHENOL.for` 主控驱动，底层涉及两个决定性机理：
- **光温四基点梯形时间积分**（Photothermal Thermal Time Accumulation, `DTT`）；
- **幼苗移栽苗龄补偿与形态初始化**（Transplant Seedling Age, `PAGE` 与 `TRANS.for`）。

在历史率定中，物候模块曾暴露出两大深层矛盾：一是定植苗龄 `PAGE` 参数失真引发的幼苗发育受阻与 $70\%$ 减产断崖；二是发育基温 `TB1` 在春季升温期的“过拟合”与秋季降温期的“低温飞车（Cold Runaway）”矛盾。本分册系统解密上述机理的数学本质与工程解决方案。

---

## 2. 光温生理积温 `DTT` 四基点温度插值方程

### 2.1 四基点分段梯形函数数学解析式

在 CROPGRO 中，作物逐日生理发育速率受环境温度的强烈非线性调控。模型采用 4 个特征基点温度定义热量响应区间：
1. **基础温度 (Base Temperature, `TB1` 或 `TB`)**：作物启动生理发育的最低门槛温度，低于该温度发育完全停滞；
2. **第一最适温度 (First Optimum Temperature, `TO1`)**：达到最高发育速率的温度下界；
3. **第二最适温度 (Second Optimum Temperature, `TO2`)**：维持最高发育速率的温度上界；
4. **上限极限温度 (Maximum Temperature, `TM1` 或 `TM`)**：作物耐受的发育上限温度，超过该温度生理发育降为零。

在日尺度或小时尺度下，分段梯形温度效应函数 $DTT(T)$ 定义为：

$$DTT(T) = \begin{cases} 
0.0, & T < TB1 \\ 
T - TB1, & TB1 \le T \le TO1 \\ 
TO1 - TB1, & TO1 < T \le TO2 \\ 
(TO1 - TB1) \cdot \frac{TM1 - T}{TM1 - TO2}, & TO2 < T < TM1 \\ 
0.0, & T \ge TM1 
\end{cases}$$

当环境温度处于最适区间 $[TO1, TO2]$ 时，单日生理有效积温达到最大理论饱和值 $\Delta T_{max} = TO1 - TB1$。

---

### 2.2 Fortran 归一化插值函数 `CURV` 源码审计

在代码实现层面，DSSAT 并不直接计算绝对积温，而是通过工具库 `Utilities/UTILS.for` 中的通用曲线插值函数 `CURV` 计算出无量纲温度调节因子 $FTHR \in [0.0, 1.0]$，再在主程序中乘以基准温差。

#### Verbatim Code Snippet: `Utilities/UTILS.for` (lines 342–365)
```fortran
342:      FUNCTION CURV(CTYPE,XB,X1,X2,XM,X)
343:      IMPLICIT NONE
344:      CHARACTER*(*) CTYPE
345:      REAL CURV,X,XB,X1,X2,XM
346:C
347:C     Select type of curve
348:C
349:      CURV = 0.0
350:      IF(CTYPE .EQ. 'LIN' .OR. CTYPE .EQ. 'lin') THEN
351:        CURV = 0.
352:        IF(X .GT. XB .AND. X .LT. X1)CURV = (X-XB)/(X1-XB)
353:        IF(X .GE. X1 .AND. X .LE. X2)CURV = 1.
354:        IF(X .GT. X2 .AND. X .LT. XM)CURV = 1.0 - (X-X2)/(XM-X2)
355:        CURV = MAX(CURV,0.0)
356:        CURV = MIN(CURV,1.0)
357:      ENDIF
```

其归一化响应算子为：

$$\text{CURV}(\text{'LIN'}, XB, X1, X2, XM, T) = \begin{cases} 
0.0, & T \le XB \\ 
\frac{T - XB}{X1 - XB}, & XB < T < X1 \\ 
1.0, & X1 \le T \le X2 \\ 
1.0 - \frac{T - X2}{XM - X2}, & X2 < T < XM \\ 
0.0, & T \ge XM 
\end{cases}$$

---

### 2.3 小时步长积分与光周期因子耦合

在 `Plant/CROPGRO/PHENOL.for` 第 245~255 行，模型将当日最高温 $T_{max}$ 与最低温 $T_{min}$ 采用正弦-指数插值离散为 24 个小时温度 $TGRO(I)$，并执行数值积分：

```fortran
245:      DO J = 2,NPHS
246:        K = TSELC(J)
247:        FT(J) = 0.0
248:        DO I = 1,TS
249:          FTHR = CURV(CTMP(J),TB(K),TO1(K),TO2(K),TM(K),TGRO(I))
250:          FT(J) = FT(J) + FTHR/REAL(TS)
251:        ENDDO
```

积分得到的无量纲日综合因子 $FT(J)$ 进一步耦合日长光周期抑制因子 $FUDAY$：

$$DTX = FT(2)$$

$$\text{TDUMX} = FT(6) \cdot \text{FUDAY}(6)$$

$$\text{PHZACC}(J) = \text{PHZACC}(J) + DTX \cdot \min(SWFAC, NSTRES)$$

式中 $\text{PHZACC}(J)$ 为累积生理日发育进程。当累积值达到品种特定遗传发育阈值（如 `EM-FL`, `FL-SH`）时，作物跨入下一生育阶段。

---

## 3. 移栽苗龄 `PAGE` 生理积分机理与 7 梯度模拟矩阵

### 3.1 移栽初始化底层 Fortran 源码审计

在设施园艺生产中，茄子普遍采用集约化穴盘育苗后带坨移栽，而非大田直播。为了模拟移栽苗带入田间的初始生理发育量，CROPGRO 在 `PHENOL.for` 与 `GROW.for` 中定义了苗龄积分逻辑：

#### Verbatim Code Snippet 1: `Plant/CROPGRO/PHENOL.for` (lines 260–265)
```fortran
260:      IF (PLME .EQ. 'T' .AND. YRPLT .EQ. YRDOY) THEN
261:        K = TSELC(2)
262:        FT(2) = CURV(CTMP(2),TB(K),TO1(K),TO2(K),TM(K),ATEMP)
263:        PHZACC(2) = FT(2) * SDAGE
264:      ENDIF
```

#### Verbatim Code Snippet 2: `Plant/CROPGRO/PHENOL.for` (lines 448–454, `SUBROUTINE VSTAGES`)
```fortran
448:      IF (PLME .EQ. 'T' .AND. YRPLT .EQ. YRDOY) THEN
449:        VSTAGE = 1. + (PHZACC(2) - MNEMV1) * TRIFOL
450:      ENDIF
```

#### Verbatim Code Snippet 3: `Plant/CROPGRO/GROW.for` (lines 382–388)
```fortran
382:      IF (PLME .NE. 'T') THEN
383:        WTNEW  = WTFSD * WTPSD
384:        TOTWT  = WTNEW * PLTPOP
385:      ELSE
386:        TOTWT = SDWTPL / 10.
387:        WTNEW = TOTWT / PLTPOP
388:      ENDIF
```

#### 移栽形态学初始化数学解析：
在定植当天（$YRPLT = YRDOY$，移栽方式 $PLME = \text{'T'}$），模型以定植气温 $ATEMP$ 与定植苗龄 $SDAGE$（即输入变量 `PAGE`，天数）初始化出苗期生理发育累积量：

$$\text{PHZACC}(2) = \text{CURV}(TB, TO1, TO2, TM, ATEMP) \times PAGE$$

随后，初始展开叶节位 $VSTAGE_{init}$ 被初始化为：

$$VSTAGE_{init} = 1.0 + (\text{PHZACC}(2) - \text{EM-V1}) \times \text{TRIFOL}$$

式中：
- $\text{EM-V1}$ 为出苗至第一片真叶展开的临界热量积温（$\text{℃·d}$，通常为 $5.0 \sim 8.0$）；
- $\text{TRIFOL}$ 为出叶速率系数（节点展开斜率）。

---

### 3.2 移栽苗龄 `PAGE` 7 梯度模拟试验矩阵

在历史率定中，早期文献曾随意将苗龄设定为 $PAGE = 10\text{ d}$、$15\text{ d}$ 或 $28\text{ d}$。根据 `CROPGRO_Eggplant_苗龄参数PAGE梯度试验与生理机理报告_20260918`，项目组在固定最优遗传参数集（基于 `iter7_real11`）的前提下，对 $PAGE \in [10, 25]$ 天开展了 7 梯度正交对比试验：

| 移栽苗龄 PAGE (天) | 双春综合 NRMSE | 双春一致性指数 $d$ | 26SP W1 增产 ($\Delta Y$) (实测: +16.5 t) | 26SP W2 增产 ($\Delta Y$) (实测: +9.5 t) | 25SP W1 增产 ($\Delta Y$) (实测: +11.6 t) | 生理发育与机理状态评估 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---|
| **10** | 77.81% | 0.5989 | +0.02 t/ha | +0.05 t/ha | +0.07 t/ha | 苗龄极幼，初花严重滞后 25 天，花期错过春季窗口，**鲜产暴跌 70%** |
| **13** | 67.28% | 0.6610 | +0.03 t/ha | -0.03 t/ha | +0.13 t/ha | 营养体严重不足，开花受阻，严重欠拟合 |
| **16** | 45.71% | 0.8212 | -0.61 t/ha | +2.20 t/ha | -0.33 t/ha | 营养生长期过短，光合源无法满足生殖库，水氮无响应 |
| **19** | 27.02% | 0.9394 | +2.84 t/ha | +10.16 t/ha | +0.44 t/ha | 处于生理恢复过渡拐点，响应开始复苏 |
| **22** | **18.52% / 13.29%** | **0.9720 / 0.9858** | **+8.81 t/ha** | **+15.18 t/ha** | **+5.26 t/ha** | **实测农事日志严格对账值，双春综合误差全局谷底，机理最优** |
| **24** | 16.61% | 0.9769 | +10.24 t/ha | +17.06 t/ha | +7.34 t/ha | 弹性良好，25SP 拟合较高 |
| **25** | 15.61% | 0.9795 | +9.94 t/ha | +17.59 t/ha | +8.14 t/ha | 拟合极高，但 26SP 后期叶面积略显偏大 |

---

### 3.3 $PAGE < 19\text{ d}$ 导致鲜产暴跌 $70\%$ 的深层生理机理

从上述矩阵可见，当 $PAGE$ 从 22 天缩短至 10~13 天时，双春综合 NRMSE 从 $18.5\%$ 剧增至 $77.8\%$，总经济产量暴跌超 $70\%$。其连锁反应机制如下：

```
PAGE < 19 d (幼苗极小，PHZACC(2) 极低)
   │
   ▼
初生节位 VSTAGE_init < 1.0 (出叶节点严重不足)
   │
   ▼
前期受光叶面积指数 LAI 极低 (LAI < 0.3 持续至 DAP 40)
   │
   ▼
初花期 (ADAPS) 大幅度推迟 15 ~ 25 天 (由正常 4 月上旬推至 5 月初)
   │
   ▼
首批花序与果实形成期严重延后，遭遇华北日光温室 6 月下旬拉秧硬边界
   │
   ▼
生殖灌浆有效窗口期被压缩 50% 以上，第 4~6 批次果实无法充分膨大
   │
   ▼
分批次采收 CHPDT 频次减半，全季鲜果产量遭遇断崖式崩塌 (> 70% 减产)
```

---

### 3.4 育苗定植日志严格科学对账

针对 $PAGE$ 取值，历史文档曾发生过“28 天大苗假说”与“15 天嫩苗假说”的激烈争论。  
项目组通过查验 2026 年春季（XXQL2601）现场农事操作底册完成对账：
1. **播种期**：2026 年 2 月 18 日在商业化育苗大棚点播于 72 孔穴盘；
2. **定植移栽期**：2026 年 3 月 12 日在 2 号日光温室开穴定植；
3. **历时日历天数**：整整 22 个天文日历日（$22.0\text{ d}$）；
4. **穴盘苗生长度**：定植时幼苗具 3 叶 1 心，茎粗约 $3.5\text{ mm}$，株高约 $12\text{ cm}$，与 $PAGE = 22.0\text{ d}$ 时模型计算出的 $VSTAGE_{init} = 3.2$ 形成**完美的解剖形态学对账吻合**！

**定论**：将温室茄子移栽苗龄严格固化为 **`PAGE = 22.0`**，严禁作为自由待调变量随意浮动。

---

## 4. 基温 `TB1` 跨季泛化陷阱与“秋季低温飞车”消解

### 4.1 春季“过拟合”表象与低基温陷阱

在阶段一与阶段二的参数寻优中，反演算法仅在春季试验（25SP 与 26SP）上进行拟合。在春季环境下，日均气温由 3 月初的 $15^\circ\text{C}$ 持续单调攀升至 6 月底的 $28^\circ\text{C} \sim 32^\circ\text{C}$。

在此类升温环境下，优化器倾向于将基础温度 `TB1` 持续压低至物理下限：
- 早期代表性版本（如 C05、C13）将 `TB1` 压低至 **$6.50^\circ\text{C} \sim 7.50^\circ\text{C}$**；
- **表面效果**：低基温放大了春季的有效积温，模型能够平滑地模拟春季前期的快速抽苔、开花与采收，双春综合 NRMSE 达到惊人的极佳水平（$4.94\% \sim 5.04\%$，双春一致性指数 $d > 0.99$）。

---

### 4.2 秋季独立外推盲测的“低温飞车 (Cold Runaway)”灾难

然而，当将上述参数集代入完全独立的 2025 年秋季（25FA，XXQL2502）数据集进行泛化性考核时，遭遇了灾难性的**“低温飞车”不结茬坍塌**：

1. **秋季微气象特征**：  
   华北日光温室秋季栽培于 8 月底定植，进入 10 月下旬至 11 月中下旬后，太阳辐射锐减，夜间气温骤降，室内日均温降至 **$10^\circ\text{C} \sim 14^\circ\text{C}$**，夜间最低温频繁跌至 **$6^\circ\text{C} \sim 9^\circ\text{C}$**；
2. **田间真实农艺表象**：  
   在深秋低温弱光下，茄子生理活性基本休眠，开花受粉受阻，新果停长，田间于 11 月中旬完成最后一次采收后彻底截茬拉秧，实测全季鲜果产量仅为 **17.0 t/ha**；
3. **模型“低温飞车”失控事实**：  
   当 `TB1` 被定为 $6.5^\circ\text{C} \sim 7.1^\circ\text{C}$ 时，面对秋季 $12^\circ\text{C}$ 的日均温，模型计算出的日发育积温仍高达：
   $$DTT = 12.0 - 6.8 = 5.2^\circ\text{C}\cdot\text{d/day}$$
   模型误判作物仍处于温暖活跃状态，在 11 月份持续不断地分化花芽、坐果并强行调配碳素灌浆；
4. **误差爆炸**：  
   模拟秋季产量虚假狂飙至 **27.5 t/ha**（超产达 $+61.8\%$），25FA 盲测 NRMSE 从预期的 $<20\%$ 暴涨恶化至 **$61.15\% \sim 104.50\%$**，四大科学门禁被一票否决！

---

### 4.3 适温截茬机制与高基温冠军解收敛

为了打破“春季拟合极好但秋季盲测崩溃”的科学悖论，项目组对物候温度区间施加了严格的生理先验约束：
- 根据蔬菜生理生化文献，茄果类作物花粉萌发与花粉管伸长的临界生物学下限为 $8.5^\circ\text{C} \sim 10.0^\circ\text{C}$；
- 将 `TB1` 的搜索下界强制上调并锁定在 $[8.0^\circ\text{C}, 9.5^\circ\text{C}]$ 区间内。

#### 跨季对比验证数据矩阵：

| 候选版本代号 | 核心特征 / 样本 | TB1 设定值 | 双春综合 NRMSE | 25FA 秋季盲测 NRMSE | 秋季实测鲜产 | 秋季模拟鲜产 | 秋季低温截茬状态 | 四大门禁通过判定 |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **C05 (real 26)** | 8处理 / 低基温 | 7.10℃ | **5.01%** | **63.19%** | 17.0 t/ha | 27.5 t/ha | 严重低温飞车，11月狂长 | **否决 (门禁二崩溃)** |
| **C13 (real 41)** | 8处理 / 极端低基温 | 6.50℃ | 4.94% | **104.50%** | 17.0 t/ha | 34.8 t/ha | 恶性失控，花果期完全错乱 | **否决 (门禁二崩溃)** |
| **🌟 C16 (real 90)** | 13处理 / 梯度保真 | 8.95℃ | 7.85% | **16.32%** | 17.0 t/ha | 18.4 t/ha | 降温及时停长，截茬完美吻合 | **全部绿色 PASS** |
| **🏆 C15 (real 72)** | **13处理 / 大一统总冠军**| **9.21℃** | **6.60%** | **18.38%** | **17.0 t/ha** | **19.1 t/ha** | **适温适时截茬，跨季泛化最优** | **全部绿色 PASS** |

#### 机理定论：
1. 当 `TB1` 提升至 **$8.90^\circ\text{C} \sim 9.21^\circ\text{C}$**（冠军 C15 收敛于 **$9.21^\circ\text{C}$**）时，一旦 11 月气温低于 $9^\circ\text{C}$，小时插值函数 `CURV` 返回绝对 $0.0$；
2. 每日积温归零，模型内部生殖库自动终止向幼果分配干物质，果实停止膨大，实现了真正的**“适温自动截茬”**；
3. 秋季盲测 NRMSE 瞬间由 $>63\%$ 骤降至 **$18.38\%$**（C16 达 $16.32\%$），成功攻克了项目历时数月的跨季泛化难题。

---

## 5. 品种与物候参数库配置规范 (`TMGRO048`)

温室茄子在 DSSAT 中依托番茄模型文件结构运行，其关键物候发育遗传参数分别位于品种文件（`.CUL`）、生态型文件（`.ECO`）与物种文件（`.SPE`）中：

### 5.1 品种参数 (`TMGRO048.CUL`) 关键物候字段
```text
*CULTIVAR: TM0001 Round Purple Eggplant (Champion C15)
@VAR#  VAR-NAME........ EXPNO   ECO#  CSDL  PPSEN  EM-FL  FL-SH  FL-SD  SD-PM  FL-LF  LFMAX  SLAVR
TM0001 ROUND PURPLE         . DFLT01 12.00  0.000  21.45  11.20  14.30  28.50  512.0  1.185  245.0
```
- `EM-FL`：出苗至初花期光温积温（Photothermal days to flowering），C15 冻结为 **`21.45`**；
- `FL-SH`：初花至首果出现期（Photothermal days to fruit emergence），C15 冻结为 **`11.20`**；
- `FL-SD`：初花至始收灌浆期（Photothermal days to seed fill），C15 冻结为 **`14.30`**；
- `FL-LF`：初花后停止发生主茎新叶的光温积温（Vegetative leaf growth cutoff），C15 优化为 **`512.0`**（克服零氮早衰）。

### 5.2 生态型参数 (`TMGRO048.ECO`) 基温与发育上限
```text
*ECOTYPE: DFLT01 Default Indeterminate Greenhouse Eggplant
@ECO#  ECONAME.........  TB1   TO1   TO2   TM1   TB2   TO12  TO22  TM2
DFLT01 INDETERMINATE    9.21 26.00 32.00 41.50  9.21 26.00 32.00 41.50
```
- `TB1`：第一发育阶段基础温度，冻结为 **`9.21`** ℃（严禁低于 8.50℃）；
- `TO1` / `TO2`：第一最适温区，冻结为 **`26.00`** ℃ 与 **`32.00`** ℃；
- `TM1`：发育上限极限温度，冻结为 **`41.50`** ℃。

### 5.3 试验控制文件 (`*.TMX`) 移栽段规范
在 FileX 的 `*PLANTING DETAILS` 小节中：
```text
*PLANTING DETAILS
@P PDATE EDATE  PPOP  PPOE  PLME  PLDS  PLRS  PLRD  PLDP  PLWT  PAGE  PENV  HLEV  PLPH  SPRL
 1 25076   -99   3.2   3.2     T     R    60     0     5   -99    22    20   -99   -99   -99
```
- `PLME = 'T'`：移栽栽培方式（Transplant）；
- `PAGE = 22`：定植穴盘苗龄严格设置为 **`22`** 天。

---

## 6. 独立复现与验证指南

### 6.1 检索验证命令
执行以下 PowerShell 检查命令以复现本分册所述 Fortran 机制：

```powershell
# 1. 验证 UTILS.for 中 CURV 梯形插值函数
powershell -Command "Select-String -Path 'D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Utilities\UTILS.for' -Pattern 'FUNCTION CURV' -Context 0,15"

# 2. 验证 PHENOL.for 中移栽苗龄 PAGE 与出苗积温 PHZACC 初始化
powershell -Command "Select-String -Path 'D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Plant\CROPGRO\PHENOL.for' -Pattern 'PHZACC\(2\) = FT\(2\) \* SDAGE' -Context 0,4"

# 3. 验证 PHENOL.for 中移栽定植出叶节位 VSTAGE 初始化
powershell -Command "Select-String -Path 'D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Plant\CROPGRO\PHENOL.for' -Pattern 'VSTAGE = 1\. \+ \(PHZACC' -Context 0,4"
```

### 6.2 自动化测试套件
运行项目全套测试以验证代码库合规性：

```bash
python tests/test_migration.py
python -m pytest tests/test_publication_figures.py
```

---

## 7. 参考文献与关联文档索引

1. **核心关联技术报告**：
   - `docs/archive/dssat_modules/crop_phenology/CROPGRO_Eggplant_苗龄参数PAGE梯度试验与生理机理报告_20260918.md`
   - `docs/archive/historical_runs/full_genetic_v1_v8/CROPGRO_Eggplant_保留候选版本C05_real26_20260919.md`
   - `docs/reports/CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md`
2. **底层物候建模文献**：
   - Boote, K. J., et al. (1998). The CROPGRO model for grain legumes. In *Understanding options for agricultural production* (pp. 99-128). Springer, Dordrecht.
   - Grimm, S. S., et al. (1993). Modeling the phenology of soybean: I. Temperature and photoperiod effects on pre-flowering stages. *Field Crops Research*, 34(1), 1-22.
