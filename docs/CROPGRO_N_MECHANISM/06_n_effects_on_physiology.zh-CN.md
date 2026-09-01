# 06 · 氮胁迫对各生理活动的作用点全图

系列：[README](README.md) · 上一篇：[05 植株内分配](05_n_partitioning_in_plant.zh-CN.md) · 下一篇：[07 数学总结](07_mathematical_model_summary.zh-CN.md)

**代码基准**：v4.8.6.0（`Plant/CROPGRO/`）

---

本文把氮影响生理活动的**全部通道**逐一列出，每条通道给出：输入量（NSTRES 供需型 / RNITP 浓度型 / NAVL 流量型）→ 数学形式 → 代码位置。

## 通道总览

| # | 过程 | 输入型 | 数学形式（核心） | 位置 |
|---|---|---|---|---|
| 1 | 冠层光合 | RNITP（浓度） | AGEFAC→AGEFCC→E_FAC 乘子 | PHOTO.for:132-195 |
| 2 | 光合下调（碳过剩反馈） | PGLEFT（间接氮） | PG×EXCESS, EXCESS=(1.20−min(1,PGLEFT/PG,0.20))^0.5 | PHOTO.for:231；VEGGR.for:373-389 |
| 3 | 比叶面积 SLA | NSTRES | NFSL=max(0.1,1−(1−NSTRES)·NSLA)→CUMNSF(4日EMA)→F | DEMAND.for:560-571 |
| 4 | 根冠分配 | NSTRES | FRRT += ATOP·(1−min(TURFAC,NSTRES,PStres2))·(1−FRRT) | VEGGR.for:259-260 |
| 5 | 冠层高/宽 | NSTRES | HNHGT=max(0.1,1−(1−NSTRES)·NHGT)→CUMNHT(4日EMA)→R̂CANHT | CANOPY.for:223-230 |
| 6 | 花添加 | NSTRES(8日) | ×min(SWADD1,SWADD2,CNSTRES^0.5) | PODS.for:776-780 |
| 7 | 结荚（成荚率） | RNITP(浓度) | RNITPD=(RNITP%−min)/(max−min)∈[0.1,1.1]，入 min() | PODS.for:748-757 |
| 8 | 荚壳生长与荚氮 | NSTRES(8日)+NAVL | ADDSHL ≤ NLEFT/(FNINSH·CNSTRES^0.5)；NGRSH=ADDSHL·PROSHI·0.16·CNSTRES^0.5 | PODS.for:599-635 |
| 9 | 籽粒灌浆速率 | NAVL(流量) | RSD=min(CRSD,NRSD,1)，NRSD=NAVL/NREQ | PODS.for:486-497 |
| 10 | 籽粒成分可塑性 | NAVL/PGAVLR 比 | PODCOMP 四情形 + Michaelis-Menten 型 XRSD | PODS.for:890-1227 |
| 11 | 叶衰老（动员致衰） | NRUSLF(流量) | LFSEN=SENRTE·NRUSLF/0.16 | SENES.for:198 |
| 12 | 氮动员加速（正反馈） | NSTRES | NMOBR×(1+0.3(1−NSTRES))（R5 后） | DEMAND.for:246-249 |
| 13 | 组织生长硬约束 | NAVL(流量) | NRATIO=NAVL/NGRVGG 压缩生长（情形 C） | VEGGR.for:309-332 |
| 14 | 物候（发育速率） | NSTRES | FNSTR(J)=1+(1−NSTRES)·NSENP(J)，与 FSW/FPSTR 取 min 后乘入 PROG=FT·FUDAY·MIN(FSW,FNSTR,FPSTR)（PHENOL.for:248-250；RStages.for:204,237）；NSENP 为生态型逐期参数∈[−1,1]，为 0 时无效应 | PHENOL.for:249 |

## §1 冠层光合的叶片氮路径（PHOTO.for）

```
PTSMAX = PHTMAX·(1−exp(−PAR/PARMAX))                       (:110)
AGEFAC = CURV(FNPGN 曲线, RNITP) / CURV(FNPGN, LNREF)      (:132-134)  物种曲线归一
AGEFCC = (1−exp(−2·AGEFAC))/(1−exp(−2))                    (:142)      饱和阻尼(降低冠层敏感度)
E_FAC  = AGEFCC·PStres1 (AGEFCC≥1) 或 min(AGEFCC,PStres1)  (:188-192)
PG     = PTSMAX·SLPF·PGFAC(LAI截获)·TPGFAC(昼温)·E_FAC·PGSLW(比叶重)·PRATIO(CO2)·PGLFMX·SWFAC  (:194-195)
```

- RNITP 是**结构叶氮浓度**（扣除碳储备，`GROW.for:998`），下限 PCNMIN；
- FNPGN 曲线（物种 `!*PHOT` 段）单峰：低叶氮区线性、高叶氮区平台——**AGEFAC 可 >1**（奢侈氮微增光合），E_FAC 处理保证 PStres1 语义不被破坏；
- PGSLW 使厚叶（低 SLA，通常高氮）单位叶面积光合更强——与 §3 的 SLA 通道构成**部分对冲**：氮胁迫→叶变薄→PGSLF 降，但同时每 g 生物量的叶面积增。

## §2 碳过剩的次日下调（EXCESS）

氮限制组织生长时碳花不出去（PGLEFT 大），模型不让 PGAVL 无限积累：

```
PGLEFT = max(0, PGAVL − (WLDOTN+WSDOTN+WRDOTN)·AGRVG − 储备分流)   (VEGGR.for:373-374)
EXCESS = (1.20 − min(1, max(PGLEFT/PG, 0.20)))^0.5                 (:385-389)
PG_次日 ×= EXCESS                                                   (PHOTO.for:231)
```

- PGLEFT/PG 小（<0.04）时 EXCESS≈1.09→夹逼≈1（无效果）；比值接近 1 时 EXCESS→√0.2≈0.447，即重度氮限制时次日光合降至约 45%；
- **这是氮胁迫压产量的第二大路径**（第一是情形 C 直接压缩生长），且是"全冠层反馈"——即使叶片氮浓度未降（动员维持期），只要碳过剩积累，PG 即被下调。

## §3 SLA（比叶面积）通道（DEMAND.for:555-574）

```
NFSL   = max(0.1, 1 − (1−NSTRES)·NSLA)        ! NSLA 物种敏感度，上限 1.2 (:560-562)
CUMNSF = 0.75·CUMNSF + 0.25·NFSL              ! 4 日 EMA (:564)
F(SLA) = FVEG·TPHFAC(温度)·PARSLA(光)·TURFSL(水)·CUMNSF     (:571)
```

氮胁迫→SLA 升（叶变薄）→同量生物量的叶面积更大但更"瘦"。后果：LAI 降得慢、但单叶光合（PGSLW）与 RNITP（浓度被稀释）同时变差。

## §4 根冠比与冠层形态

- **根分配**（VEGGR.for:259-260）：胁迫日根占比瞬间抬升，幅度 ATOP（物种参数）；与水分、磷胁迫取 min（最严者生效）；解除后按分配函数缓慢回落；
- **株高/株宽**（CANOPY.for:223-230）：HNHGT 下限 0.1（最多减 90%·NHGT），经 CUMNHT 4 日平均进入高度速率方程——影响光截获动态与冠层几何（RowSPC 光竞争）。

## §5 生殖过程（PODS.for）——氮最敏感的战场

### 5.1 花添加（`:776-780`）
```
FLWADD = 2·PMAX·TEMPOD·DRPP^1.3 · min(SWADD1, SWADD2, CNSTRES^0.5)
```
还受可用 C/N 上限约束：≤ PGNPOD/(SHMAXG·0.1·AGRSH1)，≤ NAVPOD/(SHMAXG·0.1·FNINSH·CNSTRES^0.5)。

### 5.2 成荚（`:748-757`）
```
RNITPD = (RNITP·0.01 − PROLFF·0.16)/(FNINL − PROLFF·0.16)   ! 归一化叶氮 ∈ [0.1, 1.1]
PODADD = PMAX·TEMPOD·DRPP^1.3 · min(SWADD1,SWADD2,RNITPD) · max(1−ACCAGE,0)
新增荚数 ≤ min(PODADD, C 上限, N 上限: NAVPOD/(SHMAXG·FNINSH·CNSTRES^0.5), FLADD)
```
- **RNITPD 是浓度型因子**：源码注释明确 "Scale pod addition to RNITP, leaf N for photo purposes"——叶氮不足直接少结荚；
- ACCAGE（有效灌浆年龄，NDSET 后积累）使结荚窗自然关闭；TRIGGR+CUMSIG<0.98 双条件终止后期荚（`:766-772`）。

### 5.3 荚壳生长（`:599-635`）
三重 min 约束：碳（PGLEFT/AGRSH1）、潜力（GRRAT1×SHELN）、**氮**（NLEFT/(FNINSH·CNSTRES^0.5)）；胁迫下荚壳氮浓度目标按 √CNSTRES 下调——允许"贫氮荚"存在以保荚数。

### 5.4 籽粒灌浆（`:486-531`）
```
CRSD = min(PGAVLR/(GDMSD·AGRSD1), 1)          ! 碳比
NREQ = FNINSD·min(PGAVLR/AGRSD1, GDMSD)       ! 与碳匹配的需氮
NRSD = NAVL/NREQ                              ! 氮比
RSD  = min(CRSD, NRSD, 1)                     ! 双重限制
单粒实长 = RSD·min(SDGR·SDNO, SDMAX)
NGRSD = ANINSD·RSD·min(...)                   ! ANINSD 为实际籽粒氮浓度
```

## §6 籽粒成分可塑性（PODCOMP，PODS.for:890-1227）

按 (NRSD, CRSD2, CUMSIG) 分四情形设定籽粒蛋白浓度 ANINSD ∈ [PROMIN, PROMAX]：

| 情形 | 条件 | ANINSD |
|---|---|---|
| 4 氮限制 | NRSD ≤ 1 | 由 Michaelis-Menten 型曲线定：XRSD=RH(PNINSD/PROMIN,θ)/RH(FNINSD/PROMIN,θ)；ANINSD=NAVL/(XRSD·min(PGAVLR/AGRSD1,GDMSD))，上限 FNINSD（`:1080-1093`） |
| 3 碳限制 | NRSD>1, CRSD2≤1 | min(PNINSD, PROMAX)——碳少氮多→高蛋白籽粒（`:1105-1118`） |
| 2 满载余碳 | NRSD>1, CRSD2>1, CUMSIG<0.98 | 按 N/C 供需比 RATION 三分之一斜率插值（`:1159-1168`） |
| 1 未满载 | CUMSIG≥0.98 | ANINSD=FNINSD（不变） |

随后脂/糖补偿（`:1189-1205`）：
```
DTLIP = 0.33·(FNINSD−ANINSD)·6.25；DTCAR=(FNINSD−ANINSD)·6.25−DTLIP
POTLIP += DTLIP；POTCAR += DTCAR          ! 蛋白每降 1%，脂 +0.33%、糖 +0.67%
AGRSD3 重算（成分→碳价）
RSD = min(NAVL/ANINSD, PGAVLR/AGRSD3)/GDMSD，截 1
```
CUMSIG = 0.8·CUMSIG + 0.2·CRSD（`:1030`）同时是"满载信号"，参与终止结荚。

## §7 动员致衰（SENES.for:192-201）

```
LFSEN = SENRTE · NRUSLF / 0.16     ! g 叶/g 动员蛋白
SLDOT += LFSEN（并入当日衰老）
```
- 每动员 1 g 蛋白质（=1/0.16 g N）触发 SENRTE g 叶片死亡——**动员即代价**，这使 R5 后靠动员灌浆的冠层快速变薄、AGEFAC 下降，形成"动员→衰老→光合降→更依赖动员"的正反馈环（与 §12 的动员加速环叠加）；
- 衰老叶按当时的"不可动员氮"浓度离开系统（GROW.for:736-740 NLOFF 计入 PCNL）。

## §8 各通道的时间尺度（响应滞后谱）

| 通道 | 变量 | 滞后 |
|---|---|---|
| 组织生长硬压缩（NRATIO/RSD） | 当日 NAVL | 0 日（即时） |
| 光合（叶氮） | RNITP | ~0-1 日（浓度随当日分配即变） |
| 光合（EXCESS） | PGLEFT | 1 日 |
| 根冠比/SLA/株高 | NSTRES | 1 日（昨日 NSTRES）+2/4 日平滑 |
| 动员加速 | NSTRES | 1 日 |
| 花荚 | CNSTRES（8 日 EMA） | ~1 周 |
| 叶衰老 | NRUSLF 累积效应 | 随累积渐进 |

这一滞后谱解释了氮肥处理产量差异的典型时间形态：施氮后生长几乎立即恢复，叶色/光合数日恢复，而荚数损失不可逆（花荚窗关闭后无法补偿）。
