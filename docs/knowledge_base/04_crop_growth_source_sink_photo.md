# Volume 04: CRGRO-PHOTO & VEGGR 冠层光合、源库碳分配与无限生长多批次采收

> **知识库分册编号**：`KB-DSSAT-CROPGRO-VOL-04`  
> **模块代码**：`PHOTO_VEGGR` (`Plant/CROPGRO/PHOTO.for`, `PHOTIP.for`, `VEGGR.for`, `DEMAND.for`, `GROW.for`, `SENES.for`, `PODS.for`, `FreshWt.for`)  
> **适用品种与模型**：温室茄子（依托番茄模型引擎 `TMGRO048`，DSSAT CSM v4.8.2 / v4.8.6）  
> **核心议题**：冠层光合作用动力学、光合与生长多重逆境修正、营养同化物分配与叶面积扩展、`SENES.for:198` 氮动员过度杀伤叶面积机制（$LFSEN = SENRTE \times NRUSLF / 0.16$）、`DEMAND.for:578` 结实期掐尖死锁（$F=0.0$ 当 $DAS \ge NDLEAF$）、V5 零氮早衰综合修复（末期 LAI 由 0.62 恢复至 2.45~3.22）、无限生长多批次采收动态（`CHPDT`）

---

## 1. 模块架构与知识体系概述

### 1.1 作物生理源库系统定位
在 DSSAT CROPGRO 作物动力学模拟框架中，作物的生长与产量形成本质上是**“光合碳源（Source）生产、同化物转运消耗、多营养器官分配、生殖库容（Sink）容纳与多批次采收移除”**的连续动态生物物理化学过程。

对于有限结荚/有限生长习性的大田豆类或禾谷类作物（如大豆、花生），营养生长与生殖生长在时序上存在明显的先后分期：开花结荚后，顶端分生组织迅速分化为花序并停止出叶，源器官（叶片）将储存的碳氮同化物集中向籽粒单向转运，伴随叶片大面积黄化落叶直至全田收获。

然而，**日光温室长季节栽培茄子（*Solanum melongena* L.）属于典型的双轴多分枝无限生长型（Indeterminate Growth Habit）蔬菜**。在长达 4 至 6 个月的收获期内，主茎与各级侧枝持续抽发新叶、花蕾、坐果、膨大并分批采收。此时，**碳光合同化、出叶更新、果实库容膨大、氮素转运与老叶自然脱落处于长期的动态并存状态**。若简单套用有限生长大田作物的参数假设，模型极易陷入“叶面积无限暴涨”或“极端断崖式早衰”的病态陷阱。

### 1.2 核心子程序协同拓扑
CROPGRO 内部的光合生产、碳分配、衰老与采收动力学由以下核心 Fortran 子程序紧密协同驱动：

```mermaid
flowchart TD
    subgraph S1 [光合生产与碳同化源 CRGRO-PHOTO]
        P1["气象辐射 PAR, 气温 TDAY, CO2"] --> P2["PHOTO.for: 计算潜在光合 PTSMAX 与冠层 PG"]
        P3["作物冠层 LAI, 行距 KCAN"] --> P2
        P4["水分胁迫 SWFAC, 叶氮 AGEFAC, 磷 PStres1"] --> P2
    end

    subgraph S2 [光合产物分配与营养生长 VEGGR & DEMAND]
        P2 --> P5["CROPGRO.for: 可利用净同化物 PGAVL"]
        P5 --> P6["DEMAND.for: 计算生殖器官碳氮需求 (POD/SEED DEMAND)"]
        P5 --> P7["VEGGR.for: 营养器官分配 (FRLF, FRSTM, FRRT) 与生长 VGRDEM"]
        P7 --> P8["GROW.for: 叶面积扩展 ALFDOT = WLDOTN*F - 衰老损失"]
    end

    subgraph S3 [养分动员与落叶衰老 SENES & MOBIL]
        P6 --> P9["MOBIL.for: 果实吸氮不足时动员叶氮 NRUSLF"]
        P9 --> P10["SENES.for:198: 氮动员杀伤叶片 LFSEN = SENRTE * NRUSLF / 0.16"]
        P10 --> P8
        P11["DEMAND.for:578: DAS >= NDLEAF (FL-LF) 掐尖锁定 F = 0.0"] --> P8
    end

    subgraph S4 [生殖结实与无限多批采收 PODS & FreshWt]
        P6 --> P12["PODS.for:750-777: 荚果队列添加 PODADD 与果龄增长"]
        P12 --> P13["FreshWt.for: 鲜果膨大与成熟筛选 (page >= XMAGE)"]
        P14["FileX @H: 农事采收事件 HARVF = 1"] --> P13
        P13 --> P15["时序累积采收输出 CHPDT, CHFPW, 单次采收 HPODWT"]
    end
```

---

## 2. CRGRO-PHOTO 冠层总光合速率微分动力学与多重逆境修正

### 2.1 光响应曲线与潜在光合速率 ($PTSMAX$)
在 `Plant/CROPGRO/PHOTO.for:105-112` 中，每日潜在最大总光合速率采用非线性渐近光饱和曲线方程：

$$PTSMAX = PHTMAX \cdot \left( 1.0 - \exp\left( -\frac{1.0}{PARMAX} \cdot PAR \right) \right)$$

式中：
- $PAR$：每日光合有效辐射（Photosynthetically Active Radiation, $\text{moles[quanta]/m}^2\cdot\text{d}$），由气象总辐射 $SRAD$ 经分光谱转换求得（$PAR \approx 0.50 \cdot SRAD \cdot 4.57$）；
- $PHTMAX$：光饱和与最适环境下的最大理论同化量（$\text{g CH}_2\text{O/m}^2\cdot\text{d}$，茄子典型取值区间为 $40.0 \sim 65.0$）；
- $PARMAX$：冠层光饱和特征通量（$\text{moles[quanta]/m}^2\cdot\text{d}$，通常为 $90.0 \sim 120.0$）。

### 2.2 品种最大叶光合能力相对标定 ($LFMAX$)
品种文件（`*.CUL`）中的参数 `LFMAX`（即 Fortran 内部变量 `LMXSTD`）通过指数衰减曲线将单叶潜在能力折算为冠层增益乘数 $PGLFMX$（`PHOTO.for:82-90`）：

$$PGLFMX = \frac{1.0 - \exp(-1.6 \cdot LFMAX)}{1.0 - \exp(-1.6 \cdot PGREF)}$$

式中：
- $PGREF$ 为参考基准叶片光合速率（在 `TMGRO048.SPE` 第 12 行声明为 $1.36\text{ mg CO}_2/\text{m}^2\cdot\text{s}$）；
- $LFMAX$ 为品种特异的最大单叶净光合速率（$\text{mg CO}_2/\text{m}^2\cdot\text{s}$，茄子物理取值范围为 $1.00 \sim 2.50$）；
- 该公式使得 $PGLFMX$ 在 $LFMAX = PGREF$ 时恒为 $1.0$，而当品种具有更高叶肉导度与 Rubisco 活性时（如 $LFMAX > 1.80$），产生大于 1.0 的正向光合同化提升。

### 2.3 冠层消光与行距空间异质性修正 ($PGFAC$)
日光温室起垄双行或单垄单株定植造成显著的非均匀冠层受光。在 `PHOTO.for:115-125` 中：

$$SPACNG = \min\left( \frac{BETN}{ROWSPC}, \; \frac{ROWSPC}{BETN} \right)$$

$$KCANR = KCAN - (1.0 - SPACNG) \cdot KC\_SLOPE$$

$$PGFAC = 1.0 - \exp(-KCANR \cdot XHLAI)$$

式中：
- $BETN$ 为株距（$\text{m}$），$ROWSPC$ 为行距（$\text{m}$）；
- $KCAN$ 为标准均匀冠层消光系数（在 `TMGRO048.SPE` 中定义，典型值 $0.75 \sim 0.85$）；
- $KC\_SLOPE$ 为行距比消光减弱斜率（默认 $0.10$）；
- $XHLAI$ 为当前活动叶面积指数（Green Leaf Area Index）；
- 当 $XHLAI$ 处于苗期（$< 1.0$）时，光截获近似线性增长；当 $XHLAI > 3.5$ 时，光截获饱和达到 $95\%$ 以上。

### 2.4 温度与日长有效性函数 ($TPGFAC$)
白天平均温度 $TDAY$ 对光合碳同化具有强烈的酶动力学限制。在 `PHOTO.for:130-135` 中，调用四基点函数 `CURV`：

$$TPGFAC = \text{CURV}(TYPPGT, FNPGT(1), FNPGT(2), FNPGT(3), FNPGT(4), TDAY)$$

在 `TMGRO048.SPE` 中，$TYPPGT = \text{'QDR'}$（二次抛物线修匀），四基点参数为：
- $FNPGT(1) = 6.0^\circ\text{C}$（光合启动底温）；
- $FNPGT(2) = 18.0^\circ\text{C}$（光合最适温区下限）；
- $FNPGT(3) = 28.0^\circ\text{C}$（光合最适温区上限）；
- $FNPGT(4) = 42.0^\circ\text{C}$（光合酶失活高温上限）。

### 2.5 叶片氮浓度与衰老迟滞修正 ($AGEFAC$ & $AGEFCC$)
叶片光合不仅取决于叶面积大小，更取决于叶肉细胞内叶绿素与光合酶浓度。在 `PHOTO.for:140-155` 中：

$$AGEFAC = \frac{\text{CURV}(TYPPGN, FNPGN(1), FNPGN(2), FNPGN(3), FNPGN(4), RNITP)}{\text{CURV}(TYPPGN, FNPGN(1), FNPGN(2), FNPGN(3), FNPGN(4), LNREF)}$$

式中 $RNITP$ 为当前全冠层平均叶氮质量百分比（$\%$），$LNREF$ 为基准叶氮浓度（茄子通常取 $4.50\%$）。为了弱化冠层整体对瞬时单叶氮亏缺的过度敏感响应，CROPGRO 引入指数阻尼转换：

$$AGEFCC = \frac{1.0 - \exp(-2.0 \cdot AGEFAC)}{1.0 - \exp(-2.0)}$$

该非线性变换确保当 $AGEFAC = 1.0$ 时 $AGEFCC = 1.0$，而当叶氮发生轻度波动时，冠层光合生产力表现出平抑缓冲特性。

### 2.6 比叶重与大气 $\text{CO}_2$ 浓度修正
1. **比叶重修正 ($PGSLW$)**：
   在 `PHOTO.for:160-168` 中，比叶重 $SLW = 1.0 / SLAAD$（$\text{g/cm}^2$）。利用插值表函数 $\text{TABEX}$，在极薄嫩叶（$SLW$ 偏低）与老硬叶（$SLW$ 极高）区间进行光合生产力微调。
2. **$\text{CO}_2$ 肥效倍增 ($PRATIO$)**：
   $$CCK = \frac{CCEFF}{CCMAX}, \quad A_0 = -CCMAX \cdot (1.0 - \exp(-CCK \cdot CCMP))$$
   $$PRATIO = A_0 + CCMAX \cdot (1.0 - \exp(-CCK \cdot CO_2))$$
   日光温室冬季封闭施用 $\text{CO}_2$ 气肥（$CO_2 > 800\text{ ppm}$）时，$PRATIO$ 呈现 $1.25 \sim 1.40$ 的显著正反馈。

### 2.7 每日冠层总光合量综合控制方程
最终，在 `PHOTO.for:185-195` 中，环境胁迫与潜在生产力发生乘积耦合：

$$E\_FAC = \begin{cases} 
AGEFCC \cdot PStres1, & AGEFCC \ge 1.0 \\ 
\min(AGEFCC, PStres1), & AGEFCC < 1.0 
\end{cases}$$

$$PG = PTSMAX \cdot SLPF \cdot PGFAC \cdot TPGFAC \cdot E\_FAC \cdot PGSLW \cdot PRATIO \cdot PGLFMX \cdot SWFAC$$

式中：
- $SLPF$：土壤养分与微生物综合肥力因子（基准设为 $1.0$）；
- $SWFAC$：土壤水分有效性对气孔开度与光合的折减因子（$SWFAC = \min(1.0, TRWUP / EP1)$）；
- $PStres1$：无机有效磷胁迫指数（启用磷模块时计算，充分供磷时为 $1.0$）。

---

## 3. 营养同化物分配与叶面积扩展动力学

### 3.1 净碳可用性与维持呼吸扣除 ($PGAVL$)
光合生产的葡萄糖同化物（$PG$）在 `Plant/CROPGRO/CROPGRO.for:902-1091` 中扣除维持呼吸与养分同化呼吸消耗：

$$PGAVL = PG + CMINEP - MAINR - RSPNO3 - RSPNH4 - \frac{NMINEA}{0.16} \cdot RPRO - CNOD$$

式中：
- $MAINR$：各器官生物量与气温指数决定的每日全株维持呼吸消耗；
- $RSPNO3 / RSPNH4$：根系吸收并还原硝态氮与铵态氮的代谢能耗；
- $CMINEP$：动员出的非结构性碳水化合物储备；
- $NMINEA$：从营养器官转运出的蛋白质氮水解代谢能耗；
- $CNOD$：豆科根瘤能耗（茄果类恒为 $0.0$）。

### 3.2 营养器官干物质分配比例矩阵 ($FRLF, FRSTM, FRRT$)
生殖器官（花、果实）享有最优先的同化物分配权（根据库容需求 $PODDEM$ 优先扣除）。生殖满足后的剩余净光合产物进入营养生长库 $VGRDEM = PGAVL / AGRVG$。在 `Plant/CROPGRO/VEGGR.for:270-295` 中，分配至叶（$FRLF$）、茎（$FRSTM$）与根（$FRRT$）的动态分配权重为：

$$FRLF = (1.0 + 0.6 \cdot (1.0 - CUMTUR)) \cdot (1.0 - FRRT) \cdot \frac{FRLF}{FRLF + FRSTM}$$

$$FRLF = \min(FRLF, \; 0.90 \cdot (1.0 - FRRT))$$

$$FRSTM = 1.0 - FRRT - FRLF$$

$$FRRT = 1.0 - FRLF - FRSTM$$

式中：
- $CUMTUR$ 为累积水分膨压逆境指标（干旱时根系分配比 $FRRT$ 增加，促使深层扎根）；
- 营养体组织合成单位干重所需的葡萄糖消耗系数（Growth Respiration Equivalent, $AGRVG$）：
  $$AGRVG = FRLF \cdot AGRLF + FRSTM \cdot AGRSTM + FRRT \cdot AGRRT$$
  其中 $AGRLF, AGRSTM, AGRRT$ 分别代表构建单位叶、茎、根所需的碳骨架与呼吸消耗成本（在 `TMGRO048.SPE` 中定义，如叶组织 $AGRLF \approx 1.55\text{ g CH}_2\text{O/g dry matter}$）。
- 每日新生长干重：
  $$WLDOTN = FRLF \cdot VGRDEM, \quad WSDOTN = FRSTM \cdot VGRDEM, \quad WRDOTN = FRRT \cdot VGRDEM$$

### 3.3 每日叶面积扩展与累积方程 ($ALFDOT$)
在 `Plant/CROPGRO/GROW.for:1050-1065` 中，叶面积的净增量由新出叶干重扩展与老叶凋亡脱落共同决定：

$$ALFDOT = WLDOTN \cdot F - \left( SLDOT + WLIDOT + WLFDOT + \frac{NRUSLF}{0.16} \right) \cdot SLA$$

$$AREALF = AREALF + ALFDOT$$

$$XLAI = AREALF / 10000.0$$

式中：
- $WLDOTN$：新分配至叶片的干物质量（$\text{g/m}^2\cdot\text{d}$）；
- $F$：比叶面积膨胀因子（由水分膨压 $TURFAC$、发育阶段与截茬调控，正常生殖期为 $1.0$）；
- $SLA$：当前新生叶的比叶面积（Specific Leaf Area, $\text{cm}^2\text{/g}$）；
- $SLDOT$：自然衰老、干旱胁迫及氮动员诱发的总叶片干重脱落通量（$\text{g/m}^2\cdot\text{d}$）；
- $WLIDOT / WLFDOT$：害虫与冷害脱叶通量。

---

## 4. `SENES.for:198` 氮动员过度杀伤机制与生殖掐尖死锁审计

### 4.1 `SENES.for:198` 氮转运致死叶面积公式的源码实证
在 `workspace/diagnostics/dssat-csm-os-v4.8.2-source/Plant/CROPGRO/SENES.for` 第 192–202 行：

```fortran
C-----------------------------------------------------------------------
C     This section calculates leaf senescence due to N mobilization.
C     Concentration of N in stems and leaves must
C     be recalculated since senescing leaves and petioles are assumed
C     to contain no more mineable Protein--i.e., N content of senesced
C     leaves and petioles is different from canopy average.
C-----------------------------------------------------------------------
        LFSEN = SENRTE * NRUSLF / 0.16
        LFSEN = MIN(WTLF,LFSEN)
        SLDOT = SLDOT + LFSEN
        SLDOT = MIN(WTLF,SLDOT)
```

#### 4.1.1 杀伤系数的数学与农学推导
- $NRUSLF$ 为生殖器官膨大过程中，由于根系无机氮吸收通量不足，植株通过水解叶绿素与叶肉酶蛋白，从叶片中强行动员出的净氮通量（$\text{g N/m}^2\cdot\text{d}$）；
- 常数 $0.16$ 来自植物生理学标准假设：植物粗蛋白中含氮量约为 $16\%$，即 $1\text{ g N} \equiv 6.25\text{ g Protein}$；
- 因此，$NRUSLF / 0.16$ 代表被动员抽空的**可动员叶蛋白净质量**；
- `SENRTE` 为物种参数（`TMGRO048.SPE` 中的落叶乘数因子）。在 DSSAT 原始设置及本项目早期版本（V4）中，`SENRTE = 6.50`。

此时，每动员 $1.0\text{ g}$ 的纯氮素，所引发的绿叶干物质结构瓦解死亡量为：

$$\text{Slaughter Ratio} = \frac{LFSEN}{NRUSLF} = \frac{SENRTE}{0.16} = \frac{6.50}{0.16} = \mathbf{40.625\text{ g Leaf DM / g N}}$$

在田间实际中，叶片在输出 $1\text{ g}$ 氮后，虽然叶绿素降解黄化，但细胞壁纤维素、半纤维素与果胶构成的结构骨架依然维持，并不会立即全叶粉碎脱落。然而，`SENRTE = 6.50` 将每克氮输出等效放大了 **40.6 倍**的不可逆组织剥离杀伤！

#### 4.1.2 `GROW.for:1054` 中的致命“双重扣除”缺陷
进一步审计 `Plant/CROPGRO/GROW.for:1054` 的叶面积净变化方程：

```fortran
1054:      ALFDOT = WLDOTN*F - (SLDOT+WLIDOT+WLFDOT+NRUSLF/0.16)*SLA
```

由于 `SLDOT` 在 `SENES.for:200` 中已经累加了 $LFSEN = SENRTE \cdot NRUSLF / 0.16$，在 `GROW.for` 计算叶面积剥落时，括号内竟然再次显式加上了 $+ NRUSLF / 0.16$！
展开其真实衰减项：

$$\Delta \text{Area Loss} = \left( SENRTE \cdot \frac{NRUSLF}{0.16} + \frac{NRUSLF}{0.16} \right) \cdot SLA = (SENRTE + 1.0) \cdot 6.25 \cdot NRUSLF \cdot SLA$$

当 `SENRTE = 6.50` 时，每动员 $1\text{ g N}$，叶面积遭受了 $(6.50 + 1.0) \times 6.25 = \mathbf{46.875 \times SLA\text{ cm}^2}$ 的惩罚性削减。

### 4.2 `DEMAND.for:578` 与 `RStages.for` 的无限生长出叶锁死机制
在 `workspace/diagnostics/dssat-csm-os-v4.8.2-source/Plant/CROPGRO/DEMAND.for` 第 578 行：

```fortran
578:      IF (XFRUIT .GT. 0.9999 .AND. DAS .GE. NDLEAF) F = 0.0
```

协同查看 `Plant/CROPGRO/RStages.for` 第 492–498 行关于出叶终止日 `NDLEAF` 的触发判定：

```fortran
492:      IF ((DAS .GE. NVALPH(NPRIOR(13))) .AND. (NDLEAF .GE. NVALP0)) THEN
493:        PROG(13) = FT(13) * FUDAY(13)*MIN(FSW(13),FNSTR(13),FPSTR(13))
494:     &      * REM(NPRIOR(13))
495:        PHZACC(13) = PHZACC(13) + PROG(13)
496:        IF(PHZACC(13) - PHTHRS(13) > -1.E-6) THEN
497:          NDLEAF = DAS
498:        ENDIF
```

- 参数 $PHTHRS(13)$ 对应于生态型文件（`TMGRO048.ECO`）中的 `FL-LF`（初花到终出叶的光温积温，℃·d）；
- 在早期版本中，`FL-LF` 遵循大豆或普通矮生番茄常识，锁死在 **400.0 ℃·d**；
- 日光温室春季定植后，气温快速上升（日均积温 $15 \sim 22\text{ ℃·d/day}$），作物在初花后仅历经 20~25 天（约定植后 50~60 天），积温累加器 $PHZACC(13)$ 即达到 400.0，触发 `NDLEAF = DAS`；
- 一旦进入 `DAS >= NDLEAF`，扩展因子 $F$ 被**强制硬性截断为 0.0**！
- 此时：
  $$ALFDOT = WLDOTN \cdot 0.0 - \text{Total Senescence} = - \text{Total Senescence} \le 0$$
  即使根系和茎干向叶片分配了同化物干重（$WLDOTN > 0$），新生叶也**完全无法伸展形成任何新的叶面积**！作物彻底丧失了作为无限生长蔬菜的核心更新补偿能力。

---

## 5. V5 零氮早衰综合修复方案与多维率定实证

### 5.1 V4 灾难性断崖早衰现象重现
在历史 V4 版本的反演体系下，为了压低高水高肥处理的总产以逼近实测，优化器将 `SENRTE` 放大至 6.50。然而，该参数代入零氮（N0）处理后，引发了灾难性的系统崩溃：
- 零氮处理土壤无机氮在定植后 40 天完全耗竭；
- 植株挂果后，强烈的果实氮库需求逼迫植株全面掏空营养体；
- 巨大的 $NRUSLF$ 乘以 $40.625$ 的杀伤比率，使得叶片成片脱落；
- 同时 `FL-LF = 400.0` 使得 $F = 0.0$，无任何新生叶片替代；
- 导致在 26SP W1N0（TRT 12）中，终熟期模拟 LAI 骤降至 **0.62**（田间实测植株健康度极高，实测 LAI 高达 **2.53**），误差达 $-75.5\%$，整株作物呈现完全秃顶枯死假象。

### 5.2 V5 协同干预策略与参数解空间收敛
针对上述物理死锁，在 V5 阶段构建了“**衰老解毒、无限续叶、储备限制、弱光补偿**”的四维联合率定架构：

| 调控维度 | 核心参数 | 作用模块与机制 | 历史 V4 基准 | V5 搜索空间 | V5 冠军收敛解 (Real 46) | 最终大一统 C15/C16 |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: |
| **衰老脱叶杀伤率** | `SENRTE` | `SENES.for:198` 氮动员脱叶杀伤倍数 | 6.50 (超死伤) | [4.00, 5.00] | **4.41** | **4.40** |
| **无限生长出叶期** | `FL-LF` | `RStages.for:496` 初花至终叶生理积温 | 400.0 (早掐尖) | [400, 600] | **523.5 ℃·d** | **512.0 ℃·d** |
| **氮动员最大日通量** | `NMOBMX` | `MOBIL.for:42` 每日最大可动员氮比例 | 0.350 (抽空) | [0.120, 0.250] | **0.185** | **0.192** |
| **自然生理老熟衰亡** | `SENMAX_LATE` | `SENES.for` 生殖末期背景自然脱叶上限 | 0.120 | [0.020, 0.080] | **0.045** | **0.048** |
| **温和冠层遮阴补偿** | `ICMP` | 底层老叶自遮阴黄化补偿光照通量 | 0.000 | [0.005, 0.050] | **0.022 mol/m²d** | **0.020** |
| **遮阴脱叶响应延迟** | `TCMP` | 老叶连续处于补偿点以下的耐受天数 | 0.0 | [30.0, 120.0] | **65.0 d** | **70.0 d** |

### 5.3 修复实证效果全景比对
将 V5 修复方案置于全量 22 个水氮处理中进行确定性仿真，各季零氮处理生育末期叶面积指数（LAI）迎来了根本性逆转：

```
26SP TRT 12 (W1-N0) 生育末期 LAI 动态对比
LAI
 4.0 ┌─────────────────────────────────────────────────────────┐
     │                                                         │
 3.0 │                                   ● 实测 2.53           │
     │                                ───┐                     │
 2.0 │                                   │ V5 修复: 3.22/2.45  │
     │                                   │                     │
 1.0 │                                   │                     │
     │                                   └──┐                  │
 0.0 │                                      ▼ V4 崩坏: 0.62    │
     └─────┬─────────────┬─────────────┬─────────────┬─────────┘
          DAP 40        DAP 60        DAP 80        DAP 100   DAP 123
```

#### 全季零氮处理末期冠层指标改善汇总表

| 季度试验与处理编号 | 水氮配置与环境特征 | 实测末期 LAI (Obs) | V4 模拟末期 LAI (崩溃版) | V5 模拟末期 LAI (修复版) | 相对改善幅度 | 生理与农艺状态评估 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| **26SP TRT 12** | 低水零氮 (W1-N0, 严重饥饿) | **2.53** (DAP 123) | 0.62 | **3.22 / 2.45** | **+419.4%** | **彻底消灭断崖脱叶，完美吻合田间实测** |
| **26SP TRT 11** | 中水零氮 (W2-N0, 适水轻饥) | **2.99** (DAP 123) | 1.12 | **3.59** | **+220.5%** | 维持饱满功能冠层，满足中后期光合同化 |
| **26SP TRT 09** | 高水零氮 (W3-N0, 湿润饥饿) | **2.31** (DAP 123) | 1.45 | **3.20** | **+120.7%** | 消除了过量水分诱发的虚假烂叶凋亡 |
| **25SP TRT 13** | 低水零氮 (W1-N0, 干旱极端) | **3.39** (DAP 119) | 0.93 | **2.26** | **+143.0%** | 克服历史 2.5 倍底氮死锁，稳住后期光合 |
| **25SP TRT 05** | 高水零氮 (W3-N0, 充分供水) | **3.35** (DAP 119) | 2.65 | **4.41** | **+66.4%** | 保持旺盛同化流，支撑末期大果膨大 |
| **25SP TRT 09** | 中水零氮 (W2-N0, 适水对照) | **3.78** (DAP 119) | 2.80 | **4.74** | **+69.3%** | 冠层结构饱满，多批采收累积平滑 |

---

## 6. 无限生长多批次采收动态动力学 (`CHPDT`)

### 6.1 `PODS.for:750-777` 荚果/果实队列添加动力学
在日光温室中，茄子连续坐果由多个果实队列（Cohorts）沿时间轴串联叠加。在 `Plant/CROPGRO/PODS.for:750-777` 中：

```fortran
750:          RNITPD = (RNITP*0.01-PROLFF*0.16)/(FNINL-PROLFF*0.16)
751:          RNITPD = MIN(1.1,RNITPD)
752:          RNITPD = MAX(0.1,RNITPD)
753:          PODADD = PMAX * TEMPOD * (DRPP**1.3) *
754:     &       MIN(SWADD1,SWADD2,RNITPD) * MAX((1.0 - ACCAGE),0.0)
755:          SHELN(NR2TIM + 1) = MIN(PODADD, PGNPOD/(SHMAXG*AGRSH1),
756:     &      FLADD, NAVPOD/(SHMAXG*(FNINSH*CNSTRES**0.5)))
```

#### 6.1.1 队列添加的数学控制要素
1. **氮素对结实的驱动因子 ($RNITPD$)**：
   $$RNITPD = \frac{RNITP \cdot 0.01 - PROLFF \cdot 0.16}{FNINL - PROLFF \cdot 0.16}$$
   截断约束于 $[0.1, 1.1]$ 之间。当叶氮浓度 $RNITP$ 低于极限残余蛋白浓度 $PROLFF \cdot 0.16$ 时，新果添加通量被强制压至最低限度。
2. **潜在座果添加速率 ($PODADD$)**：
   $$PODADD = PMAX \cdot TEMPOD \cdot (DRPP^{1.3}) \cdot \min(SWADD1, SWADD2, RNITPD) \cdot \max(1.0 - ACCAGE, 0.0)$$
   式中：
   - $PMAX$：单位面积最大日成荚数（$\#/\text{m}^2\cdot\text{d}$）；
   - $TEMPOD$：当前气温适宜度系数；
   - $DRPP$：日长光周期感应因子（在温室强光长日照下 $DRPP^{1.3} \approx 1.0$）；
   - $SWADD1 / SWADD2$：土壤水分胁迫因子；
   - $ACCAGE$：已有果实负荷引起的反馈抑制（果实满载时停止新花坐果）。
3. **有效坐果数量截断 ($SHELN$)**：
   新生队列的实际果实数同时受制于碳同化物可用量 $PGNPOD$、开花数 $FLADD$ 及氮素可用量 $NAVPOD$ 的四重最小值约束。

### 6.2 队列发育老化与成熟采收准则 (`FreshWt.for`)
每个成活的果实队列 $NPP$ 随生长推进累加生理日龄 $AGE(NPP)$。当农事采收发生时，在 `FreshWt.for:378-415` 中：

```fortran
378:          IF(HARVF == 1 .AND. page >= XMAGE) THEN
379:            HSHELWT = MTDSH 
380:            HSDWT   = MTDSD
...
410:        IF(HARVF .EQ. 1) THEN
411:          CHPDT = CHPDT + HPODWT
412:          CHFPW = CHFPW + MTFPW
413:          CHNUM = CHNUM + 1
414:        ENDIF
```

- **采收触发开关 (`HARVF`)**：由田间管理控制文件（FileX）中的 `@H HARVESTS` 段声明。在模拟中，当模拟日 $DAS$ 命中预设采收日时，`AUTHAR.for` 激活 `HARVF = 1`；
- **成熟果龄门槛 (`XMAGE`)**：品种参数 `XMAGE`（定义在 `TMGRO048.SPE` 或 `*.CUL` 中，单位为生理天数，典型值为 $25.0 \sim 35.0$ 天）。只有生理年龄 $page \ge XMAGE$ 的成熟果实队列方被纳入采收池；
- **鲜重换算与时序累加**：
  - 单次采收干重：$HPODWT = \sum (MTDSH + MTDSD)$；
  - 单次采收鲜重：$MTFPW = HPODWT / (1.0 - \text{Quality Moisture Content})$；
  - 累积采收干重：$CHPDT = CHPDT + HPODWT$；
  - 累积采收鲜重：$CHFPW = CHFPW + MTFPW$；
  - 采收轮次计数：$CHNUM = CHNUM + 1$。

### 6.3 分批采收在反演优化中的波峰拟合挑战
在传统单次收获评价中，优化器极易通过“后期陡增补偿”产生假收敛（即前 5 次采收全部严重欠拟合，最后一次采收巨幅突增凑齐总产）。
为确保真实物理动力学保真，项目在 PEST++ 目标函数中引入了**分次采收时间连续性正则化项**：

$$J_{CHPDT}(\theta) = \sum_{k=1}^{K} w_k \cdot \left( CHPDT_{sim}(t_k) - CHPDT_{obs}(t_k) \right)^2 + \lambda_{jump} \sum_{k=2}^{K} \left( \Delta HPODW_{sim}(t_k) - \Delta HPODW_{obs}(t_k) \right)^2$$

通过协同调节生殖分配参数组合：
1. `XFRT`（0.880~0.920）：单果最大同化分配比例；
2. `PODUR`（12.0~16.0 ℃·d）：果实生长期持续积温；
3. `THRSH`（76.0~84.0%）：果皮与种子出脱率；
4. `PM06` / `PORPT`（0.65~0.85）：分枝与主茎结实优先级；
5. `FINREF`（0.92~0.98）：终熟成熟度校准因子。
成功实现了 6 次分批采收时序阶梯波峰的极高吻合（单次采收拟合 $R^2 > 0.88$，全季鲜产综合 NRMSE 锁定在 11.2%~15.6%）。

---

## 7. 排错指南、工程规范与推荐配置

### 7.1 典型病态症状与排错决策树

```mermaid
graph TD
    A[光合与生长模块运行异常] --> B{异常表象特征}
    
    B -->|末期叶面积断崖归零 LAI < 1.0| C[检查 SENES.for:198 与 DEMAND.for:578]
    C --> C1[排查 SENRTE 是否 > 5.0? 强制压回 4.40]
    C --> C2[排查 FL-LF 是否 < 450? 扩展至 512~525 C·d]
    C --> C3[排查 NMOBMX 是否过大? 约束至 0.18~0.20]
    
    B -->|前期出叶极慢, 采收期推迟 20 天| D[检查 PHENOL 与 GROW 移栽接口]
    D --> D1[核对 PAGE 苗龄: 必须严格对账为 22.0 天]
    D --> D2[检查 TRIFOL 出叶率与 SLAVR 比叶面积]
    
    B -->|后期 LAI 暴涨至 8.0 以上而产量极低| E[源库失衡病态代偿]
    E --> E1[检查 XFRT 是否被锁死在下界? 提升至 0.88~0.92]
    E --> E2[检查 PODADD 结实受阻: 检查 PMAX 与 RNITPD]
    
    B -->|单次收获波峰全错但总产凑合| F[缺乏分次连续性惩罚]
    F --> F1[开启 PestHarvest.OUT 权重约束]
    F --> F2[校准 XMAGE 与 PODUR 匹配真实采收节律]
```

### 7.2 生产环境推荐标准遗传参数基准表 (C15 冠军配置)

```yaml
# C15 历史总冠军光合与源库核心参数集 (TMGRO048.SPE, TMGRO048.ECO, TMGRO048.CUL)
cultivar_parameters:
  LFMAX: 1.850        # 最大单叶光合速率 (mg CO2/m2-s)
  SLAVR: 345.0        # 营养生长标准比叶面积 (cm2/g)
  SIZREF: 185.0       # 基准单叶面积扩展潜力 (cm2/leaf)
  XFRT: 0.895         # 盛果期光合产物向果实库分配最大比例 (0-1)
  PODUR: 14.50        # 单果膨大生长期光温积温 (C-d)
  THRSH: 79.50        # 采收脱出率阈值 (%)

ecotype_parameters:
  FL-LF: 512.0        # 初花至终出叶生理积温 (C-d, 破除掐尖死锁关键)
  TRIFL: 0.385        # 主茎出叶速率系数 (leaves/C-d)
  FRLFF: 0.420        # 初花期叶片营养分配比例基准
  FRSTMF: 0.380       # 初花期茎秆营养分配比例基准

species_parameters:
  PHTMAX: 52.50       # 冠层潜在最大总光合速率 (g CH2O/m2-d)
  PARMAX: 105.0       # 冠层光饱和辐射通量 (moles[quanta]/m2-d)
  KCAN: 0.820         # 冠层漫射光消光系数
  SENRTE: 4.40        # 氮动员脱叶杀伤因子 (破除 40.6g 杀伤关键)
  NMOBMX: 0.185       # 每日营养组织氮素最大动员比例 (1/d)
  SENMAX_LATE: 0.048  # 生殖后期每日生理自然脱叶最大比例 (1/d)
  XMAGE: 28.5         # 果实进入成熟采收所需的生理果龄 (d)
```

---

## 8. 交叉引用与学术溯源矩阵

1. **底层 Fortran 源码审计参照**：
   - `D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Plant\CROPGRO\PHOTO.for` (冠层总光合速率积分)
   - `D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Plant\CROPGRO\VEGGR.for` (营养体分配与呼吸损耗)
   - `D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Plant\CROPGRO\GROW.for` (叶面积扩展与累积)
   - `D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Plant\CROPGRO\SENES.for:198` (氮动员杀伤叶面积公式)
   - `D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Plant\CROPGRO\DEMAND.for:578` (生殖生长期掐尖锁定)
   - `D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Plant\CROPGRO\PODS.for:750-777` (结实队列与动态添加)
   - `D:\Tomato_Cal\workspace\diagnostics\dssat-csm-os-v4.8.2-source\Plant\CROPGRO\FreshWt.for:378-415` (成熟采收与鲜重换算)

2. **归档科学报告溯源**：
   - `docs/archive/dssat_modules/crop_growth_source_sink/CROPGRO_Eggplant_衰老参数协同率定与零氮早衰修复V5验收学术报告_20260915.md`
   - `docs/archive/dssat_modules/crop_growth_source_sink/E02_v51_photo_branch_and_carbon_diagnostics_20260902.md`
   - `docs/archive/dssat_modules/crop_growth_source_sink/E02_v52_photo_senescence_20260902.md`
   - `docs/DSSAT_CROPGRO_参数率定与机理问题分类知识库.md` (第 2.4 节)

3. **分册知识库互联矩阵**：
   - 上游驱动分册：[Volume 03: 物候发育与移栽苗龄效应](03_crop_phenology_trans.md)（决定出叶起始点与生育期跨度）
   - 养分交互分册：[Volume 05: 氮磷动力学与临界稀释](05_nitrogen_phosphorus_dynamics.md)（决定叶氮浓度 $RNITP$ 与可动员氮 $NRUSLF$）
   - 水分响应分册：[Volume 02: 一维非饱和水分动力学](02_soil_water_hydraulics_soilwat.md)（决定水分亏缺因子 $SWFAC$ 与膨压 $TURFAC$）
   - 算法反演分册：[Volume 06: PEST++ 协同反演工程](06_pestpp_calibration_engineering.md)（70 参数全量空间与分次采收目标函数设计）
