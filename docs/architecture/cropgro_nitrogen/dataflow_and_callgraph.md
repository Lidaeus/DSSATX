# CROPGRO 氮素代谢模块调用时序与变量数据流全景规范

**文档标识**: `ARCH-N-01`  
**版本**: v1.0.0 (Publication-Grade Specification)  
**作者**: Technical Documentation Architecture Team  
**审核基准**: DSSAT CSM v4.8.2 / v4.8.6.0 (`Plant/CROPGRO/`, `SPAM/`, `Soil/`)  
**目标作物/模型**: 温室茄子 (依托番茄模型 `TMGRO048.CUL` / `TMGRO048.SPE` / `TMGRO048.ECO`)  
**状态**: 冻结生效 (Frozen Architectural Standard)

---

## 1. 架构总览与执行范式 (Executive Architecture Overview)

DSSAT CSM (Cropping System Model) 下的 CROPGRO 模型采用标准离散时间状态空间架构，以日（Day）为推进步长，并在每一天严格切分为两个核心物理阶段：
1. **速率计算阶段 (`DYNAMIC == RATE`)**：根据前一日积分固化的植株存量状态、土壤环境与即时光温驱动，计算瞬时光合碳同化速率（`PHOTO.for`）。
2. **状态积分阶段 (`DYNAMIC == INTEGR`)**：依序执行物候推进、碳氮可用库重置、维持呼吸扣除、器官需氮估算、土壤根系吸氮、体内氮素再动员、生殖与营养分配、动员致死衰老、根系延伸、以及各器官生物量与氮素状态变量数值积分。

在全生育期内，系统通过物候事件（出苗 `EMERG`、开花 `FLR`、首果 `R3`、始采/灌浆 `R5`、生理成熟 `MAT`）动态切换分配拓扑。氮代谢模块并非孤立运行，而是通过**“流量供需比控制”**与**“存量浓度反馈”**双轨耦合，深度嵌入作物的碳捕获与异速生长网络。

---

## 2. Fortran 子程序逐日调用拓扑与 17 步时序规范 (Calling Sequence Specification)

主控程序 `CROPGRO.for` 在主推进循环（`DYNAMIC == INTEGR` 阶段）中，按以下 17 步不可逆拓扑严格编排氮代谢子程序。以下逐行规范各步骤的调用位置、前置依赖、核心方程与后置数据流动。

```
                              ┌────────────────────────────────────────────────────────┐
                              │                 DYNAMIC == RATE 阶段                   │
                              └────────────────────────────────────────────────────────┘
                                                         │
                                        ┌────────────────┴────────────────┐
                                        │  CALL PHOTO (CROPGRO.for:753)   │
                                        │  输入昨日 RNITP, 算得 PG, AGEFAC │
                                        └────────────────┬────────────────┘
                                                         │
                              ┌──────────────────────────▼─────────────────────────────┐
                              │                DYNAMIC == INTEGR 阶段                  │
                              └────────────────────────────────────────────────────────┘
                                                         │
   Step 0: 物候推进                ┌─────────────────────┴──────────────────────┐
                                   │  CALL PHENOL (CROPGRO.for:773)             │
                                   │  NSTRES 经 NSENP 调制各期光温发育速率       │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 0a: 出苗日一次性初始化     ├─ [若 DAS == NVEG0 出苗日] ─────────────────┤
   (DAS == NVEG0)                  │  CALL GROW(EMERG)   -> WTNLF, SDNPL        │
                                   │  CALL ROOTS(EMERG)  -> RLV, RTDEP          │
                                   │  CALL DEMAND(EMERG) -> FNINL, FNINR, FNINS │
                                   │  CALL PODS(EMERG)   -> FNINSH              │
                                   │  CALL VEGGR(EMERG)  -> FNINLG, FNINRG      │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 1: 碳氮可用库重置          ┌─────────────────────┴──────────────────────┐
                                   │  NAVL = 0.0; PGAVL = PG + CMINEP           │
                                   │  (CROPGRO.for:905, 918-919)                │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 2: 维持呼吸扣除            ┌─────────────────────┴──────────────────────┐
                                   │  CALL RESPIR -> MAINR;                     │
                                   │  PGAVL = MAX(0.0, PGAVL - MAINR) (:923-932)│
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 3: 需氮量体系评估          ┌─────────────────────┴──────────────────────┐
   (用昨日状态)                    │  CALL DEMAND(INTEGR) (CROPGRO.for:958)     │
                                   │  -> NDMREP, NDMVEG, NDMNEW, NDMOLD, NDMTOT │
                                   │  -> NMINEP, NMOBR, FRLF, FRSTM, FRRT       │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 4: 种子残留氮释放          ┌─────────────────────┴──────────────────────┐
                                   │  NAVL = MAX(0.0, SDNPL * DTX / 7.0) (:980) │
                                   │  SDNPL = SDNPL - NAVL                      │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 5: 根系土壤吸氮            ┌─────────────────────┴──────────────────────┐
                                   │  CALL NUPTAK(INTEGR) (CROPGRO.for:992)     │
                                   │  ANDEM=(NDMTOT-NDMSDR)*10 -> UNO3, UNH4    │
                                   │  PGAVL -= (RSPNO3 + RSPNH4) (:1005)        │
                                   │  NAVL += TRNU (:1010)                      │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 6: 内源氮素动员            ┌─────────────────────┴──────────────────────┐
                                   │  CALL MOBIL(INTEGR) (CROPGRO.for:1016)     │
                                   │  NMINEA = MIN(NDMNEW-TRNU, NMINEP)         │
                                   │  抽取 NRUSLF, NRUSST, NRUSRT, NRUSSH       │
                                   │  PGAVL -= NMINEA/0.16*RPRO (:1040)         │
                                   │  NAVL += NMINEA (:1044)                    │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 7: 固氮门控 (茄果类=0)     ┌─────────────────────┴──────────────────────┐
                                   │  番茄/茄子 ISWSYM='N', NFIXN=0.0 (:1082)   │
                                   │  NAVL += NFIXN (:1109)                     │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 8: 生殖器官优先分配        ┌─────────────────────┴──────────────────────┐
                                   │  CALL PODS(INTEGR) (CROPGRO.for:1113)      │
                                   │  CALL PODCOMP (籽粒成分双曲线可塑性调整)   │
                                   │  算得 WSDDTN, WSHDTN, NGRSD, NGRSH         │
                                   │  更新慢速胁迫: CNSTRES = 0.875*C + 0.125*N │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 9: 扣除生殖器官 C/N        ┌─────────────────────┴──────────────────────┐
                                   │  PGAVL -= (WSDDTN*AGRSD3 + WSHDTN*AGRSH1)  │
                                   │  NAVL  -= (NGRSD + NGRSH) (:1151-1158)     │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 10: 碳储备预存分流         ┌─────────────────────┴──────────────────────┐
                                   │  CSAVEV = CADPR1 * PGAVL * FRACDN (:1165)  │
                                   │  PGAVL -= CSAVEV                           │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 11: 营养生长与 NSTRES 计算 ┌─────────────────────┴──────────────────────┐
                                   │  CALL VEGGR(INTEGR) (CROPGRO.for:1171)     │
                                   │  计算当日总供给 SUPPN = TRNU + NMINEA      │
                                   │  计算瞬时 XNSTRES 与平滑 NSTRES (:250,256) │
                                   │  三浓度判断: A(充分), B(稀释), C(硬压缩)   │
                                   │  算得 WLDOTN, WSDOTN, WRDOTN, NGRLF..      │
                                   │  计算余碳 EXCESS (反馈次日光合)            │
                                   │  余氮分配: NLEAK 溢出泄漏, NADLF.. 入储备   │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 12: 扣除营养器官 C/N       ┌─────────────────────┴──────────────────────┐
                                   │  PGAVL -= AGRVG*生长 - (CADLF+CADST)*PCH2O │
                                   │  NAVL  -= (NGRLF+NGRST+NGRRT) - NAD* (:1188│
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 13: 衰老与动员致死叶面积   ┌─────────────────────┴──────────────────────┐
                                   │  CALL SENES(INTEGR) (CROPGRO.for:1195)     │
                                   │  LFSEN = SENRTE * NRUSLF / 0.16 (:209)     │
                                   │  SLDOT = SLDOT + LFSEN (:211)              │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 14: 根系生长与深度扩展     ┌─────────────────────┴──────────────────────┐
                                   │  CALL ROOTS(INTEGR) (CROPGRO.for:1216)     │
                                   │  更新 RLV(L) (供次日 NUPTAK 吸收)          │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 15: 蛋白合成碳代价重算     ┌─────────────────────┴──────────────────────┐
                                   │  加权合成代价 RPROAV, 重算 AGRVG2 (:1230)  │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 16: 状态变量数值积分       ┌─────────────────────┴──────────────────────┐
                                   │  CALL GROW(INTEGR) (CROPGRO.for:1247)      │
                                   │  积分 WTLF, STMWT, RTWT, SDWT, SHELWT      │
                                   │  积分 WTNLF, WTNST, WTNRT, WTNSD, WTNSH    │
                                   │  更新 AREALF, XLAI (含动员叶面积损失)       │
                                   │  计算 PCNL, PCNST, PCNRT, PCNSD, PCNSH     │
                                   │  计算 RNITP (结构基叶氮%), WNRLF (可动员库) │
                                   └─────────────────────┬──────────────────────┘
                                                         │
   Step 17: 报表输出与次日循环     ┌─────────────────────┴──────────────────────┐
                                   │  CALL Opgrow (输出 PlantGro.OUT)           │
                                   │  输出 PCNPOD = (WTNSH+WTNSD)/PODWT*100     │
                                   └────────────────────────────────────────────┘
```

---

## 3. 标准 Mermaid 每日时序执行图 (Sequence Diagram)

```mermaid
sequenceDiagram
    autonumber
    participant CSM as CSM_Main / LAND
    participant CG as CROPGRO.for (主控引擎)
    participant PHO as PHOTO.for (RATE)
    participant PHE as PHENOL.for (INTEGR)
    participant DEM as DEMAND.for
    participant NUP as NUPTAK.for
    participant MOB as MOBIL.for
    participant POD as PODS.for
    participant VEG as VEGGR.for
    participant SEN as SENES.for
    participant ROO as ROOTS.for
    participant GRO as GROW.for
    participant OPG as Opgrow.for

    Note over CSM,CG: === 每日速率阶段 (DYNAMIC == RATE) ===
    CG->>PHO: 1. CALL PHOTO (输入昨日 RNITP, EXCESS, SLAAD, SWFAC)
    Note over PHO: AGEFAC = CURV(FNPGN, RNITP) / CURV(FNPGN, LNREF)<br/>AGEFCC = (1 - exp(-2*AGEFAC))/(1 - exp(-2))<br/>PG = PTSMAX * SLPF * PGFAC * TPGFAC * E_FAC * PGSLW * EXCESS
    PHO-->>CG: 返回当日总同化碳 PG, AGEFAC

    Note over CSM,CG: === 每日积分阶段 (DYNAMIC == INTEGR) ===
    CG->>PHE: 2. CALL PHENOL (输入昨日 NSTRES, TGRO, SWFAC)
    Note over PHE: FNSTR(J) = 1 + (1 - NSTRES) * NSENP(J)<br/>推进发育阶段 VSTAGE, RSTAGE, DTT, DXR57
    PHE-->>CG: 返回物候状态与时温步长 DTX, DXR57

    Note over CG: 3. 初始化当日可用库:<br/>NAVL = 0.0 + SDNPL*DTX/7<br/>PGAVL = PG + CMINEP - MAINR

    CG->>DEM: 4. CALL DEMAND (输入昨日 NSTRES, PCNL, WTLF, STMWT, RTWT)
    Note over DEM: 1. 动员潜力 NMINEP = NMOBR * (WNRLF + WNRST + WNRRT + WNRSH)<br/>2. 生殖需氮 NDMREP = FNINSD*GDMSD + FNINSH*GDMSH<br/>3. 比叶面积 NFSL = max(0.1, 1 - (1-NSTRES)*NSLA)<br/>4. 营养需氮 NDMVEG = (CDMVEG/AGRVG2)*(FRLF*FNINL + ...)<br/>5. 老组织复充 NDMOLD = sum((WT - WCR)*max(0, NVST - PCN/100))<br/>6. 总需氮 NDMTOT = NDMREP + NDMVEG + NDMOLD
    DEM-->>CG: 返回 NDMNEW, NDMTOT, NDMSDR, NMINEP, FRLF, FRSTM, FRRT

    CG->>NUP: 5. CALL NUPTAK (输入 ANDEM = (NDMTOT - NDMSDR)*10, NO3, NH4, RLV, SW)
    Note over NUP: 逐层计算: FNO3 = 1 - exp(-0.08*NO3)<br/>RFAC = RLV * sqrt(SMDFR) * DLAYR * 100<br/>RNO3U = RFAC * FNO3 * RTNO3<br/>NUF = min(1.0, ANDEM / sum(RNO3U+RNH4U))<br/>UNO3 = min(RNO3U*NUF, SNO3 - 0.25/KG2PPM)
    NUP-->>CG: 返回分层吸收 UNO3, UNH4, 总吸收 TRNU (g/m²)
    Note over CG: 扣除吸收能量代价: PGAVL -= (TRNO3U/0.16*RNO3C + TRNH4U/0.16*RNH4C)<br/>累加氮库: NAVL += TRNU

    CG->>MOB: 6. CALL MOBIL (输入 NDMNEW, TRNU, NMINEP, NMOBR, WNRxx)
    Note over MOB: 判断亏缺: IF (NDMNEW - TRNU > 1e-5 AND NMINEP > 1e-4)<br/>NMINEA = min(NDMNEW - TRNU, NMINEP)<br/>NRUSLF = (NMINEA/NMINEP) * NMOBR * WNRLF (各器官等比抽取)
    MOB-->>CG: 返回实际动员量 NMINEA 及各器官抽取量 NRUSxx
    Note over CG: 扣除再合成代价: PGAVL -= NMINEA/0.16 * RPRO<br/>累加氮库: NAVL += NMINEA

    Note over CG: 7. 固氮门控 (茄果类 ISWSYM='N', NFIXN = 0.0)

    CG->>POD: 8. CALL PODS (输入 NAVL, PGAVL, 昨日 RNITP, NSTRES, GDMSD)
    Note over POD: 1. 慢速滤波 CNSTRES = 0.875*CNSTRES + 0.125*NSTRES<br/>2. 籽粒灌浆 RSD = min(CRSD, NRSD, 1.0)<br/>3. PODCOMP 调整籽粒蛋白/油/糖成分<br/>4. 成荚与花添加受 RNITPD 与 CNSTRES^0.5 约束
    POD-->>CG: 返回实际生殖生长 WSDDTN, WSHDTN 及吸氮 NGRSD, NGRSH
    Note over CG: 优先扣除生殖库消耗:<br/>PGAVL -= (WSDDTN*AGRSD3 + WSHDTN*AGRSH1)<br/>NAVL -= (NGRSD + NGRSH)

    Note over CG: 9. 碳储备分流: CSAVEV = CADPR1 * PGAVL * FRACDN; PGAVL -= CSAVEV

    CG->>VEG: 10. CALL VEGGR (输入剩余 NAVL, PGAVL, NDMNEW, NDMOLD, 昨日 NSTRES)
    Note over VEG: 1. 计算总供给 SUPPN = TRNU + NMINEA (+ NFIXN)<br/>2. 瞬时胁迫 XNSTRES = min(1.0, SUPPN/(NDMNEW * NSTFAC))<br/>   平滑胁迫 NSTRES = 0.5*XNSTRES + 0.5*PNSTRES<br/>3. 根系分配调节 FRRT += ATOP*(1 - min(TURFAC, NSTRES))*(1 - FRRT)<br/>4. 三浓度营养生长判定:<br/>   - Case A (NAVL >= NGRVEG): 最大蛋白生长<br/>   - Case B (NGRVGG <= NAVL < NGRVEG): 氮稀释生长, 浓度下降干重不降<br/>   - Case C (NAVL < NGRVGG): 硬约束压缩 NRATIO = NAVL/NGRVGG, 干重缩水<br/>5. 碳过剩因子 EXCESS = (1.20 - min(1, max(PGLEFT/PG, 0.2)))^0.5<br/>6. 余氮入库 NADxx 与溢出泄漏 NLEAK
    VEG-->>CG: 返回 WLDOTN, WSDOTN, WRDOTN, NGRLF, NGRST, NGRRT, NSTRES, EXCESS, NADxx
    Note over CG: 扣除营养库消耗:<br/>PGAVL -= AGRVG*生长 + (CADLF+CADST)*PCH2O<br/>NAVL -= (NGRLF+NGRST+NGRRT) + sum(NADxx)

    CG->>SEN: 11. CALL SENES (输入 NRUSLF, VSTAGE, PAR, XLAI, WTLF)
    Note over SEN: 氮动员致衰: LFSEN = SENRTE * NRUSLF / 0.16<br/>自然衰老 + 弱光衰老 + 动员致衰 -> SLDOT
    SEN-->>CG: 返回叶片脱落干重 SLDOT, 茎脱落 SSDOT

    CG->>ROO: 12. CALL ROOTS (输入 FRRT, WRDOTN, SW, SOILPROP)
    Note over ROO: 积分根重 RTWT, 扩展根深 RTDEP, 更新剖面根长密度 RLV(L)
    ROO-->>CG: 返回更新后的 RLV(L) (供次日 NUPTAK)

    Note over CG: 13. 加权蛋白合成代价 RPROAV 重算, 准备明日 AGRVG2

    CG->>GRO: 14. CALL GROW (输入 WLDOTN, NGRLF, NRUSLF, NADLF, SLDOT, ...)
    Note over GRO: 1. 积分器官干重: WTLF += WLDOT, STMWT += WSDOT, RTWT += WRDOT...<br/>2. 积分器官氮量: WTNLF += NLDOT, WTNST += NSDOT, WTNRT += NRDOT...<br/>3. 更新叶面积: ALFDOT = WLDOTN*F - (SLDOT + NRUSLF/0.16)*SLA + ...; XLAI = AREALF/10000<br/>4. 反算组织氮浓度: PCNL = WTNLF/WTLF*100, PCNST, PCNRT, PCNSH, PCNSD<br/>5. 反算结构叶氮%: RNITP = 100*WTNLF/(WTLF - WCRLF)<br/>6. 更新可动员氮库: WNRLF = max(0.0, WTNLF - PROLFF*0.16*(WTLF - WCRLF))
    GRO-->>CG: 返回最新器官干重、氮浓度 PCNL/PCNST、RNITP、可动员库 WNRxx

    CG->>OPG: 15. CALL Opgrow (记录 PlantGro.OUT)
    Note over OPG: 输出 PCNL, PCNST, PCNPOD = (WTNSH+WTNSD)/PODWT*100, WTLF, XLAI...
```

---

## 4. 全量变量数据流字典与数学公式 (Full Dataflow Variable Dictionary)

本节建立 CROPGRO 氮代谢的规范变量字典，所有变量均提供其 Fortran 源码路径、物理行号、量纲、物理定义及严格数学公式。

### 4.1 外部驱动输入变量 (External Driver Inputs)

| 变量标识 | 源码定义位置 | 物理量纲 / 单位 | 变量角色与生理学定义 | 核心计算公式 / 转换逻辑 |
|---|---|---|---|---|
| `NO3(L)` | `SOILNI.for` / `NUPTAK.for:112` | $\mu\text{g N/g 土}$ ($\text{ppm}$) | 土壤剖面第 $L$ 层瞬时硝态氮质量浓度 | 经 `SNO3(L) = NO3(L) / KG2PPM(L)` 换算为 $\text{kg N/ha}$ |
| `NH4(L)` | `SOILNI.for` / `NUPTAK.for:113` | $\mu\text{g N/g 土}$ ($\text{ppm}$) | 土壤剖面第 $L$ 层瞬时铵态氮质量浓度 | 经 `SNH4(L) = NH4(L) / KG2PPM(L)` 换算为 $\text{kg N/ha}$ |
| `TRNU` | `NUPTAK.for:187`, `CROPGRO.for:995` | $\text{g[N]/m}^2\text{/d}$ | 全剖面根系吸收总氮通量，外部供给驱动 | $\text{TRNU} = \frac{\sum_L (\text{UNO3}(L) + \text{UNH4}(L))}{10.0}$ |
| `PG` | `PHOTO.for:236`, `CROPGRO.for:758` | $\text{g[CH}_2\text{O]/m}^2\text{/d}$ | 当日冠层毛光合总碳水化合物生产量 | $\text{PG} = \text{PTSMAX} \cdot \text{SLPF} \cdot \text{PGFAC} \cdot \text{TPGFAC} \cdot E_{\text{FAC}} \cdot \text{PGSLW} \cdot \text{PRATIO} \cdot \text{PGLFMX} \cdot \text{SWFAC} \cdot \text{EXCESS}$ |
| `PGAVL` | `CROPGRO.for:919` | $\text{g[CH}_2\text{O]/m}^2\text{/d}$ | 当日扣除维持呼吸与合成代谢后的有效碳可用量 | $\text{PGAVL} = \text{PG} + \text{CMINEP} - \text{MAINR} - \text{RSPNO3} - \text{RSPNH4}$ |
| `RLV(L)` | `CROPGRO.for:1220` (调用) / `ROOTS.for:333` (更新), `NUPTAK.for:124` | $\text{cm 根/cm}^3\text{ 土}$ | 第 $L$ 土层根长密度，决定根系与土壤氮接触截面 | 逐日按根系生物量分配与有效积温垂直延伸推进 |
| `SW(L)` | `SOILWAT.for`, `NUPTAK.for:133` | $\text{cm}^3/\text{cm}^3$ | 第 $L$ 土层当前体积含水率 | 用于计算吸收土壤水分干旱与渍水双向抑制因子 $\text{SMDFR}(L)$ |

### 4.2 品种/物种遗传生理参数 (Genetic & Physiological Parameters)

| 参数代码 | 模板/源码来源 | 读取行号 | 物理量纲 / 取值范围 | 生理机制与功能解释 |
|---|---|---|---|---|
| `PROLFI` | `TMGRO048.SPE` `!*PLAN` | `DEMAND.for:809` | 分数 ($\text{g 蛋白/g DM}$), $0.22\sim 0.30$ | 叶片**最大初始（奢侈吸收）**蛋白质分数；新叶目标需氮天花板 |
| `PROLFG` | `TMGRO048.SPE` `!*PLAN` | `VEGGR.for:121` | 分数 ($\text{g 蛋白/g DM}$), $0.16\sim 0.22$ | 叶片**正常生长（标准稀释）**蛋白质分数；Case B 生长门槛 |
| `PROLFF` | `TMGRO048.SPE` `!*PLAN` | `DEMAND.for:813` | 分数 ($\text{g 蛋白/g DM}$), $0.10\sim 0.14$ | 叶片**极限残余**蛋白质分数；不可动用结构蛋白质死底线 |
| `PROSTI` / `PROSTF` | `TMGRO048.SPE` `!*PLAN` | `DEMAND.for:809,813` | 分数 ($\text{g 蛋白/g DM}$) | 茎秆最大初始与极限残余蛋白质分数 |
| `PRORTI` / `PRORTF` | `TMGRO048.SPE` `!*PLAN` | `DEMAND.for:809,813` | 分数 ($\text{g 蛋白/g DM}$) | 根系最大初始与极限残余蛋白质分数 |
| `PROSHI` / `PROSHF` | `TMGRO048.SPE` `!*PODS` | `PODS.for:175` | 分数 ($\text{g 蛋白/g DM}$) | 荚壳（果皮）最大初始与极限残余蛋白质分数 |
| `SDPRO` | `TMGRO048.CUL` `*CULTI` | `DEMAND.for:767` | 分数 ($\text{g 蛋白/g DM}$) | 籽粒基准蛋白质分数（番茄/茄子对应种子/胎座核心） |
| `PROMIN` / `PROMAX` | `TMGRO048.SPE` `!*PLAN` | `PODS.for:965` | 分数 ($\text{g 蛋白/g DM}$) | 籽粒蛋白质浓度的绝对最低与最高生理可塑界限 |
| `THETA` | `TMGRO048.SPE` `!*PLAN` | `PODS.for:965` | 无量纲, $[0.0, 1.0]$ | 籽粒成分响应氮缺乏的双曲线曲率因子 (`PODCOMP`) |
| `RTNO3` | `TMGRO048.SPE` `!*ROOT` | `NUPTAK.for:75` | $\text{mg N/cm 根/d}$, $0.02\sim 0.06$ | 单位根长硝态氮最大潜在主动吸收能力 |
| `RTNH4` | `TMGRO048.SPE` `!*ROOT` | `NUPTAK.for:75` | $\text{mg N/cm 根/d}$, $0.02\sim 0.06$ | 单位根长铵态氮最大潜在主动吸收能力 |
| `NMOBMX` | `TMGRO048.SPE` `!*CARB` | `DEMAND.for:855` | $\text{d}^{-1}$, $0.04\sim 0.08$ | 单日可动员氮库最大抽取比例上限 |
| `NVSMOB` | `TMGRO048.SPE` `!*CARB` | `DEMAND.for:855` | 无量纲, $0.10\sim 0.50$ | 营养生长阶段相对于生殖期的相对氮动员速率折扣因子 |
| `NRCVR` | `TMGRO048.SPE` `!*CARB` | `DEMAND.for:855` | 无量纲, $[0.0, 1.0]$ | 生殖成熟期 (R5 后) 植株组织氮浓度的生理回填恢复系数 |
| `NSTFAC` | `TMGRO048.SPE` `!*CARB` | `VEGGR.for:141` | 无量纲, $[0.1, 1.0]$, 默认 0.70 | 氮胁迫触发门槛系数（供给低于需求的该比例时触发胁迫） |
| `NSLA` | `TMGRO048.SPE` `!*LEAF` | `DEMAND.for:902` | 无量纲, 上限 1.2 | 比叶面积对氮胁迫的敏感度因子（缺氮导致叶片变厚变硬） |
| `SENRTE` | `TMGRO048.SPE` `!*SENI` | `SENES.for:123` | $\text{g DM/g 动员蛋白}$, $4.0\sim 8.0$ | 氮动员抽调引起的叶面积与生物量牺牲破坏系数 |
| `ATOP` | `TMGRO048.SPE` `!*VEGE` | `VEGGR.for:158` | 无量纲, $0.20\sim 0.50$ | 遭遇水氮胁迫时分配给根系干物质的最大提升幅度 |
| `NHGT` | `TMGRO048.SPE` `!*CANO` | `CANOPY.for:128` (参数读取), `220-224` (NSTRES折减) | 无量纲, 上限 1.4 | 冠层垂直高度扩展对氮胁迫的敏感折减斜率 |
| `RNO3C` | `TMGRO048.SPE` `!*RESP` | `DEMAND.for:791` | $\text{g CH}_2\text{O/g N}$, 1.798 | 硝酸盐还原同化为氨的呼吸代谢能量代价 |
| `RNH4C` | `TMGRO048.SPE` `!*RESP` | `IPPLNT.for:170` (品种参数读取), `CROPGRO.for:1001` (同化能耗) | $\text{g CH}_2\text{O/g N}$, 0.462 | 铵态氮同化为氨基酸的呼吸代谢代价 |
| `RPRO` | `TMGRO048.SPE` `!*RESP` | `DEMAND.for:791` | $\text{g CH}_2\text{O/g 蛋白}$, 0.380 | 动员游离氨基酸重新合成结构蛋白的二次代谢代价 |
| `FNPGN(1..4)` | `TMGRO048.SPE` `!*PHOT` | `PHOTO.for:85` | 4 点样条控制点坐标 | 叶片氮浓度对单叶光合作用响应曲线控制点 |
| `LNREF` | `TMGRO048.SPE` `!*PHOT` | `PHOTO.for:88` | 质量百分比 $\text{\%}$, $3.8\sim 4.5$ | 叶片光合参考基准氮浓度（归一化使 $\text{AGEFAC}=1.0$） |

### 4.3 内部状态与中介通量变量 (State & Intermediate Flux Variables)

| 变量代码 | 源码定义位置 | 物理量纲 / 单位 | 变量角色定义 | 严密计算数学公式 |
|---|---|---|---|---|
| `FNINL` | `DEMAND.for:218` | $\text{g N/g 干重}$ | 叶片最大初始目标氮浓度 | $\text{FNINL} = \text{PROLFI} \times 0.16$ |
| `FNINLG` | `VEGGR.for:219` | $\text{g N/g 干重}$ | 叶片正常生长生理最低允许氮浓度 | $\text{FNINLG} = \text{PROLFG} \times 0.16$ |
| `NDMREP` | `DEMAND.for:484` | $\text{g[N]/m}^2\text{/d}$ | 生殖器官（籽粒+荚壳）当日新生长需氮量 | $\text{NDMREP} = \text{GDMSD} \cdot \text{FNINSD} + \text{GDMSH} \cdot \text{FNINSH}$ |
| `NDMVEG` | `DEMAND.for:627` | $\text{g[N]/m}^2\text{/d}$ | 营养器官（叶+茎+根）新生长需氮量 | $\text{NDMVEG} = \frac{\text{CDMVEG}}{\text{AGRVG2}} \cdot (\text{FRLF}\cdot\text{FNINL} + \text{FRSTM}\cdot\text{FNINS} + \text{FRRT}\cdot\text{FNINR})$ |
| `NDMNEW` | `DEMAND.for:629` | $\text{g[N]/m}^2\text{/d}$ | 当日全株所有新形成器官的总需氮量 | $\text{NDMNEW} = \text{NDMREP} + \text{NDMVEG}$ |
| `NDMOLD` | `DEMAND.for:650-654` | $\text{g[N]/m}^2\text{/d}$ | 营养器官因前期亏缺需回填复充的氮量 | $\text{NDMOLD} = \min\left[\sum_{\text{organ}} (\text{WT}-\text{WCR})\cdot\max(0, \text{NVST}-\frac{\text{PCN}}{100}), \frac{\text{CNOLD}}{\text{RNO3C}}\cdot 0.16\right]$ |
| `NDMTOT` | `DEMAND.for:660` | $\text{g[N]/m}^2\text{/d}$ | 当日植株全口径理论总需氮量 | $\text{NDMTOT} = \text{NDMNEW} + \text{NDMOLD}$ |
| `NDMSDR` | `DEMAND.for:361` | $\text{g[N]/m}^2\text{/d}$ | 籽粒需氮中可由体内动员氮满足的配额 | $\text{NDMSDR} = \min(\text{NDMSD}, \text{NMINEP})$ |
| `ANDEM` | `NUPTAK.for:118` | $\text{kg[N]/ha/d}$ | 换算为公顷尺度的根系吸氮需求 | $\text{ANDEM} = (\text{NDMTOT} - \text{NDMSDR}) \times 10.0$ |
| `NUF` | `NUPTAK.for:165` | 无量纲, $[0.0, 1.0]$ | 根系吸氮需求与土壤潜在供给缩放比 | $\text{NUF} = \min\left(1.0, \frac{\text{ANDEM}}{\sum_L (\text{RNO3U}_L + \text{RNH4U}_L)}\right)$ |
| `NAVL` | `CROPGRO.for:905-1109` | $\text{g[N]/m}^2\text{/d}$ | 当日植株体内可用于生长分配的总可用氮库 | 级联累加: $\text{NAVL} = \text{SDNPL}_{\text{rel}} + \text{TRNU} + \text{NMINEA} + \text{NFIXN}$ |
| `NMOBR` | `DEMAND.for:244-249` | $\text{d}^{-1}$ | 当日受生育期与环境胁迫调控的动员率 | R5后: $\text{NMOBR} = \text{NMOBMX}\cdot\text{TDUMX2}\cdot[1+0.5(1-\text{SWFAC})]\cdot[1+0.3(1-\text{NSTRES})]\dots$ |
| `NMINEP` | `DEMAND.for:250` | $\text{g[N]/m}^2\text{/d}$ | 全株体内存储的可动员氮的最大潜在供给能力 | $\text{NMINEP} = \text{NMOBR} \times (\text{WNRLF} + \text{WNRST} + \text{WNRRT} + \text{WNRSH})$ |
| `NMINEA` | `MOBIL.for:65-66` | $\text{g[N]/m}^2\text{/d}$ | 当日实际从营养器官水解抽取的总动员氮量 | 当 $\text{NDMNEW} > \text{TRNU}$ 时: $\text{NMINEA} = \min(\text{NDMNEW} - \text{TRNU}, \text{NMINEP})$ |
| `NRUSLF` | `MOBIL.for:68` | $\text{g[N]/m}^2\text{/d}$ | 当日从功能叶片中实际抽取的动员氮通量 | $\text{NRUSLF} = \left(\frac{\text{NMINEA}}{\text{NMINEP}}\right) \cdot \text{NMOBR} \cdot \text{WNRLF}$ |
| `WNRLF` | `GROW.for:1007` | $\text{g[N]/m}^2$ | 叶片当前高出最低生存蛋白界限的可动员氮库 | $\text{WNRLF} = \max\left[\text{WTNLF} - \text{PROLFF}\cdot 0.16\cdot (\text{WTLF} - \text{WCRLF}), 0.0\right]$ |
| `SUPPN` | `VEGGR.for:238` | $\text{g[N]/m}^2\text{/d}$ | 当日可向新组织分配的总氮供给通量 | $\text{SUPPN} = \text{TRNU} + \text{NMINEA} + \text{NFIXN}$ |
| `XNSTRES` | `VEGGR.for:250` | 无量纲, $[0.0, 1.0]$ | 当日未平滑的瞬时氮胁迫指数（1为无胁迫） | 若 $\text{SUPPN} < \text{NSTFAC}\cdot\text{NDMNEW}$: $X_{\text{NSTRES}} = \frac{\text{SUPPN}}{\text{NDMNEW}\cdot\text{NSTFAC}}$，否则 $1.0$ |
| `NSTRES` | `VEGGR.for:256` | 无量纲, $[0.0, 1.0]$ | 二日等权滑动平均平滑氮胁迫指数 | $\text{NSTRES}_t = 0.5 \cdot X_{\text{NSTRES},t} + 0.5 \cdot X_{\text{NSTRES},t-1}$ |
| `CNSTRES` | `PODS.for:414` | 无量纲, $[0.0, 1.0]$ | 作用于生殖发育（花荚添加）的 8 日指数慢变量 | $\text{CNSTRES}_t = 0.875 \cdot \text{CNSTRES}_{t-1} + 0.125 \cdot \text{NSTRES}_t$ |
| `NRATIO` | `VEGGR.for:316` | 无量纲, $\le 1.0$ | Case C 硬约束下由于氮不足对营养干重增长的压缩比 | $\text{NRATIO} = \frac{\text{NAVL}}{\text{NGRVGG}}$ （此时叶茎根新干重均乘以该比例） |
| `EXCESS` | `VEGGR.for:386` | 无量纲, $[0.447, 1.0]$ | 营养生长受阻引起的碳过剩对次日总光合的下调乘子 | $\text{EXCESS} = \left[1.20 - \min\left(1.0, \max\left(\frac{\text{PGLEFT}}{\text{PG}}, 0.20\right)\right)\right]^{0.5}$ |
| `NLEAK` | `VEGGR.for:444` | $\text{g[N]/m}^2\text{/d}$ | 奢侈积累超出老组织复充容量后的溢出泄漏通量 | $\text{NLEAK} = \max(0.0, \text{NLEFT} - \text{NDMOLD})$ |
| `RNITP` | `GROW.for:998` | 质量百分比 $\text{\%}$ | 基于结构性无储备叶片干重的真叶氮百分比 | $\text{RNITP} = 100.0 \times \frac{\text{WTNLF}}{\text{WTLF} - \text{WCRLF}}$ (下限 $\text{PCNMIN}$) |
| `AGEFAC` | `PHOTO.for:134` | 无量纲, 可 $>1.0$ | 叶片真氮浓度对单叶潜在光合作用的乘性响应因子 | $\text{AGEFAC} = \frac{\text{CURV}(\text{FNPGN}, \text{RNITP})}{\text{CURV}(\text{FNPGN}, \text{LNREF})}$ |
| `AGEFCC` | `PHOTO.for:142` | 无量纲 | 单叶光合到群体冠层光合的指数饱和平滑因子 | $\text{AGEFCC} = \frac{1.0 - \exp(-2.0 \cdot \text{AGEFAC})}{1.0 - \exp(-2.0)}$ |
| `LFSEN` | `SENES.for:209` | $\text{g DM/m}^2\text{/d}$ | 氮动员抽调引发的伴生功能叶片衰老脱落干重 | $\text{LFSEN} = \text{SENRTE} \times \frac{\text{NRUSLF}}{0.16}$ |

### 4.4 核心输出变量 (Core Model Outputs)

| 输出代码 | 源码定义位置 | 物理量纲 / 单位 | 生物学与农艺学意义 | 严密计算数学公式 |
|---|---|---|---|---|
| `PCNL` | `GROW.for:959` | 百分比 ($\text{\%}$) | 冠层功能叶片全氮质量百分比 (含非结构碳) | $\text{PCNL} = \frac{\text{WTNLF}}{\text{WTLF}} \times 100.0$ |
| `PCNST` | `GROW.for:965` | 百分比 ($\text{\%}$) | 茎秆全氮质量百分比 | $\text{PCNST} = \frac{\text{WTNST}}{\text{STMWT}} \times 100.0$ |
| `PCNRT` | `GROW.for:971` | 百分比 ($\text{\%}$) | 根系全氮质量百分比 | $\text{PCNRT} = \frac{\text{WTNRT}}{\text{RTWT}} \times 100.0$ |
| `PCNSH` | `GROW.for:977` | 百分比 ($\text{\%}$) | 荚壳（果皮/果肉）全氮质量百分比 | $\text{PCNSH} = \frac{\text{WTNSH}}{\text{SHELWT}} \times 100.0$ |
| `PCNSD` | `GROW.for:985` | 百分比 ($\text{\%}$) | 籽粒（种子/胎座）全氮质量百分比 | $\text{PCNSD} = \frac{\text{WTNSD}}{\text{SDWT}} \times 100.0$ |
| `PCNPO` / `PCNPOD` | `Opgrow.for:462` | 百分比 ($\text{\%}$) | 整个生殖器官（单果整体）全氮质量百分比 | $\text{PCNPOD} = \frac{\text{WTNSH} + \text{WTNSD}}{\text{SHELWT} + \text{SDWT}} \times 100.0$ |
| `WTLF` | `GROW.for:621` | $\text{g/m}^2$ (地表投影) | 现存活绿叶干重（未脱落） | $\text{WTLF}_{t} = \text{WTLF}_{t-1} + \text{WLDOT}$ |
| `STMWT` / `WTST` | `GROW.for:622` | $\text{g/m}^2$ | 现存主茎与侧枝地上部结构干重 | $\text{STMWT}_{t} = \text{STMWT}_{t-1} + \text{WSDOT}$ |
| `RTWT` / `WTRT` | `GROW.for:625` | $\text{g/m}^2$ | 全土壤剖面现存活根系总干重 | $\text{RTWT}_{t} = \text{RTWT}_{t-1} + \text{WRDOT}$ |
| `SHELWT` | `GROW.for:624` | $\text{g/m}^2$ | 现存荚壳（果肉/果皮）干重 | $\text{SHELWT}_{t} = \text{SHELWT}_{t-1} + \text{WSHDOT}$ |
| `SDWT` | `GROW.for:623` | $\text{g/m}^2$ | 现存成熟与未成熟籽粒干重 | $\text{SDWT}_{t} = \text{SDWT}_{t-1} + \text{WSDDOT}$ |
| `PODWT` | `GROW.for:626` | $\text{g/m}^2$ | 现存生殖器官总干重 ($\text{SHELWT} + \text{SDWT}$) | $\text{PODWT}_{t} = \text{PODWT}_{t-1} + \text{WPDOT}$ |
| `WTSO` | `GROW.for:687` | $\text{g/m}^2$ | 累计脱落/衰老茎秆干重 | $\text{WTSO}_{t} = \text{WTSO}_{t-1} + \text{SSDOT} + \text{WSIDOT}$ |
| `WTLO` | `GROW.for:686` | $\text{g/m}^2$ | 累计脱落/衰老叶片干重 | $\text{WTLO}_{t} = \text{WTLO}_{t-1} + \text{SLDOT} + \text{WLIDOT} + \text{WLFDOT}$ |
| `AREALF` | `GROW.for:1087` | $\text{cm}^2\text{ 叶/m}^2\text{ 地}$ | 冠层现存绿叶单面总表面积 | $\text{AREALF}_{t} = \text{AREALF}_{t-1} + \text{ALFDOT}$ |
| `XLAI` / `LAI` | `GROW.for:1088` | $\text{m}^2\text{ 叶/m}^2\text{ 地}$ | 冠层叶面积指数 (Leaf Area Index) | $\text{XLAI} = \frac{\text{AREALF}}{10000.0}$ |

---

## 5. 核心代谢与调节机制深度解剖 (Mechanistic Deep Dive)

### 5.1 流量供需比 (`NSTRES`) 与存量浓度 (`RNITP`) 的双轨解耦机制
CROPGRO 与 CERES 模板最大的理论分水岭在于：**CERES 采用纯存量浓度标量驱动全株胁迫，而 CROPGRO 建立了“流量控制分配、存量反馈光合”的双轨体系**。

在 `VEGGR.for:238-256` 中：
$$X_{\text{NSTRES}} = \min\left(1.0, \; \frac{\text{SUPPN}}{\text{NDMNEW} \cdot \text{NSTFAC}}\right) = \min\left(1.0, \; \frac{\text{TRNU} + \text{NMINEA}}{\text{NDMNEW} \cdot \text{NSTFAC}}\right)$$
而在 `PHOTO.for:134` 中：
$$\text{AGEFAC} = \frac{\text{CURV}\left(\text{FNPGN}, \; 100.0 \times \frac{\text{WTNLF}}{\text{WTLF} - \text{WCRLF}}\right)}{\text{CURV}(\text{FNPGN}, \; \text{LNREF})}$$

这种双轨设计的生理意涵在于：
1. **缓冲延迟效应 (Buffering Delay)**：当土壤开始干旱或脱肥（$\text{TRNU} \to 0$）时，只要植株前期营养充足，体内庞大的可动员库 $\text{WNRLF}$ 能够释放充足的动员通量（$\text{NMINEA} \approx \text{NDMNEW}$），使得 $\text{SUPPN} \ge \text{NSTFAC} \cdot \text{NDMNEW}$，此时 $X_{\text{NSTRES}} \equiv 1.0$。在此期间，新叶扩展速率和根冠分配未受任何表观抑制；
2. **潜在贫氮化 (Hidden Dilution)**：在流量表观“无胁迫”的背后，存量端 $\text{WTNLF}$ 被快速抽调，$\text{RNITP}$ 开始单调下滑，单叶光合悄然衰减；
3. **断崖式硬着陆 (Abrupt Crash)**：一旦可动员库触底（$\text{WNRLF} \to 0$），$\text{NMINEA}$ 骤降，$\text{SUPPN}$ 瞬间归零，模型在 1~2 天内直接跌入 Case C 硬压缩状态（$\text{NRATIO} \ll 1.0$），引发组织扩张停止与叶面积暴跌。

### 5.2 可用氮库 (`NAVL`) 的严格层级优先级消耗机制
在每日积分步长中，植株当天的总可用氮库 $\text{NAVL}$（由根系吸收 $\text{TRNU}$ 与内源动员 $\text{NMINEA}$ 汇集而成）遵循严格的**生殖绝对优先（Sink-First Priority）**准则：

$$\begin{aligned}
\text{Step 1 (生殖库优先抽取)}: & \quad \Delta \text{NAVL}_{\text{rep}} = \text{NGRSD} + \text{NGRSH} \\
& \quad \text{NAVL}_{\text{post-rep}} = \text{NAVL} - \Delta \text{NAVL}_{\text{rep}} \\
\text{Step 2 (营养库二级分配)}: & \quad \Delta \text{NAVL}_{\text{veg}} = \text{NGRLF} + \text{NGRST} + \text{NGRRT} \\
& \quad \text{NAVL}_{\text{post-veg}} = \text{NAVL}_{\text{post-rep}} - \Delta \text{NAVL}_{\text{veg}} \\
\text{Step 3 (老组织储备充填)}: & \quad \Delta \text{NAVL}_{\text{refill}} = \min(\text{NAVL}_{\text{post-veg}}, \; \text{NDMOLD}) \\
\text{Step 4 (奢侈溢出不可逆泄漏)}: & \quad \text{NLEAK} = \max(0.0, \; \text{NAVL}_{\text{post-veg}} - \text{NDMOLD})
\end{aligned}$$

在茄果类盛果期，果实对氮的强力虹吸常使得 $\text{NAVL}_{\text{post-rep}}$ 严重匮乏，营养生长被动成为“余量承受者”，直接导致 Case B 稀释生长或 Case C 生长停止。

### 5.3 碳过剩 (`EXCESS`) 对全冠层光合的间接反馈
在低氮环境下，即便水分与光照极佳，作物的碳同化仍会受到剧烈压制。CROPGRO 并非通过直接在光合方程中乘以 $NSTRES$ 来实现此点，而是通过**“生长端利用受限 $\to$ 结构碳过剩 $\to$ 反馈抑制同化端”**的精妙间接机制（`VEGGR.for:386`）：

$$\text{EXCESS} = \left[ 1.20 - \min\left(1.0, \; \max\left(\frac{\text{PGLEFT}}{\text{PG}}, \; 0.20\right)\right) \right]^{0.5}$$

当氮亏缺导致组织生长受抑（Case C 中新叶干重乘以 $\text{NRATIO} < 1.0$）时，当日未被消费的同化产物 $\text{PGLEFT}$ 累积。当 $\frac{\text{PGLEFT}}{\text{PG}} \to 1.0$ 时，$\text{EXCESS} = (1.20 - 1.0)^{0.5} \approx 0.447$。次日毛光合 $\text{PG}$ 直接被下调至 $44.7\%$！这解释了低氮处理下植株整体生物量积累停滞的根本原因。

### 5.4 动员致衰正反馈死锁
在 `SENES.for:209` 中（外层逻辑外壳为 198 行）：
$$\text{LFSEN} = \text{SENRTE} \times \frac{\text{NRUSLF}}{0.16}$$
由于温室茄子物种参数中 $\text{SENRTE}$ 约为 $4.4\sim 6.5\text{ g DM/g 蛋白}$，这意味着**植株每抽调 $1\text{ g}$ 氮素（折合 $6.25\text{ g}$ 粗蛋白），就必须伴生破坏脱落 $27.5\sim 40.6\text{ g}$ 绿叶干重！**
在灌浆盛期或外部供氮中断时，该方程构成了毁灭性的正反馈死锁（Positive Feedback Avalanche）：
$$\text{缺氮} \longrightarrow \text{加剧动员 } (\text{NRUSLF} \uparrow) \longrightarrow \text{叶片暴毙 } (\text{LFSEN} \uparrow) \longrightarrow \text{LAI 崩塌} \longrightarrow \text{总光合腰斩} \longrightarrow \text{根系缺碳吸氮更差} \longrightarrow \text{恶性早衰死锁}$$

---

## 6. 接口契约与后续分册引用关系 (Interface Contracts)

本文件作为 CROPGRO 氮代谢底层架构规范的基础卷（`ARCH-N-01`），为后续两份核心架构规范提供权威的数据流与行号依据：
1. **下游反馈与次生冲击风险矩阵 (`ARCH-N-02`, `downstream_impact_matrix.md`)**：以本卷 4.4 节定义的 `PCNL`、`PCNST`、`RNITP` 与 `NSTRES` 为源节点，完整展开 8 大下游消费环节与 4 大反馈环路。
2. **临界氮稀释集成架构与 PEST++ 适配设计 (`ARCH-N-03`, `critical_n_integration_proposals.md`)**：以本卷 5 节揭示的“单库门槛动员”、“质量守恒闭环”与“动员致衰死锁”为问题原点，设计无破坏性缝合架构。
