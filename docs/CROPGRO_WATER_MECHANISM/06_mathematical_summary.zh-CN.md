# 06 · 数学建模总结：全方程清单、水平衡与参数索引

系列：[README](README.md) · 上一篇：[05 生理作用点](05_water_effects_on_physiology.zh-CN.md)

**代码基准**：v4.8.6.0。本篇把 01–05 篇浓缩为一套自洽数学模型，便于复现与方法学表述。

---

## 1. 状态变量与单位

| 状态 | 符号 | 单位 | 宿主 |
|---|---|---|---|
| 逐层体积含水量 | SW(L) | cm³/cm³ | WATBAL（内部网格=MESOL 网格） |
| 积雪 | SNOW | mm | WATBAL |
| 蒸发两阶段状态 | SUMES1/SUMES2/T | mm, mm, d | SOILEV |
| 渍涝持续天数 | TSS(L) | d | ROOTWU |
| 根长密度 | RLV(L) | cm/cm³ | ROOTS |
| 地下水位 | ActWTD | cm | WaterTable.f90 |

通量单位统一：mm/d（显示）与 cm/d（内部，×0.1 换算）。

## 2. 方程清单（按计算次序）

### 2.1 产流与入渗（WATBAL RATE）
```
SMX=254(100/CN−1)；SWABI=0.15·Σ_{1,2}(SAT−SW)/(SAT−0.5LL)；IABS=SWABI(或+覆盖项)
RUNOFF=(WATAVL−IABS·SMX)²/(WATAVL+(1−IABS)SMX)（当正）          RNOFF.for:78-111
WINF=WATAVL−RUNOFF+IRRAMT；PINF=WINF×0.1
雨日逐层: DRN(L)=PINF−HOLD+SWCON(SAT−DUL)Δz(表层×0.9)，≤SWCN×24；超饱和回吐/EXCS→径流
        干层截留: SW+=PINF/Δz 至 DUL，超出当日排出                  INFIL.for:55-147
无雨日: DRMX=(SW−DUL)SWCONΔz(SW≥DUL+0.003)；DRN(L)=DRN(L−1)+DRMX−HOLD  SATFLO.for:47-119
```

### 2.2 蒸散需求与供给（SPAM RATE）
```
EO: MEEVP 选法（R:PT 默认；F:FAO56；S/T:ASCE；D:动态PM；P/M:Penman 变体；H:逐时PT） PET.for
EOS = EO(1−0.39LAI)|LAI≤1；EO/1.1·e^{−0.4LAI}|LAI>1；（KSEVAP>0: EO·e^{−KSEVAP·LAI}）  PSE
EOP = EO(1−e^{−KTRANS·XHLAI})·TRAT(CO₂)，≤EO−EOP_reduc−EVAP              TRANS.for:83-139
q_L = 1.32e-3·e^{min((120−250LL)(SW−LL),40)}/(7.01−ln min(RLV,e^{7.01}))  ROOTWU.for:85-86
SWEXF=min(1,(SAT−SW)/PORMIN)（TSS>2 天后生效）；q_L ≤ RWUMX·SWEXF
RWU(L)=q_L·Δz·RLV；TRWUP=ΣRWU
EP=min(EOP,10·TRWUP)；WUF=min(1,EP_cm/TRWUP)；RWU×WUF≤SW_AVAIL·Δz；EP=10·TRWU   SPAM:395；XTRACT
```

### 2.3 胁迫因子（CROPGRO RATE）
```
TURFAC=min(1,(TRWUP/EOP)/RWUEP1)；SWFAC=min(1,TRWUP/EOP)        CROPGRO.for:691-700
SATFAC=ΣΔzRLV(1−SWEXF)/ΣΔzRLV（诊断）                            ROOTS.for:279-283
FSW(J)=1+(1−SWFAC)WSENP(J)；PROG=FT·FUDAY·MIN(FSW,FNSTR,FPSTR)   PHENOL:248；RStages:204
SWDF=min(1,(SW−LL)/(0.25(DUL−LL)))；RTSURV=min(1,1−RTSDF(1−SWDF),1−RTEXF(1−SWEXF))  ROOTS:222-230
```

### 2.4 生理作用点（选列，全表见 05 篇）
```
PG×=SWFAC；R5后 PG×(1−0.3CUMSTR)，CUMSTR+=DXR57(1−SWFAC)XPOD/PHTHRS10   PHOTO:195,225
TURFSL=max(0.1,1−(1−TURFAC)TURSLA)→F(SLA)                             DEMAND:556
FRRT+=ATOP(1−min(TURFAC,NSTRES,PStres2))(1−FRRT)                      VEGGR:259
CUMTUR=0.95CUMTUR+0.05TURFAC；FRLF∝(1+0.6(1−CUMTUR))                  VEGGR:267-273
TURXFR=XFRMAX(1−TURFAC)→XFRT；TURADD=TABEX(YTRFAC,XTRFAC,TURFAC)       DEMAND:428,305
SDGR、GRRAT1、SDMAX×(1+TURADD)                                        DEMAND:309,377；PODS:524
SWBAR=Σ(SW−LL)Δz·f/Σ(DUL−LL)Δz·f(0..DSWBAR)；SWADD1,2=表(SWBAR/SWFAC)   PODS:559-583
FLWADD∝min(SWADD1,SWADD2,CNSTRES^0.5)；PODADD∝min(SWADD1,SWADD2,RNITPD)(1−ACCAGE)
ACCAGE+=TEMPOD·DRPP·SWFAC/MNESPM                                       PODS:741-743
RATTP=SWFAC(5日前)；WSLOSS=SENDAY(1−RATTP)WTLF≤SENMAX 保留下限          SENES:169-227
RTDEP+=DTX·RFAC2·min(SWDF,SWEXF)(1+0.25(1−max(SWFAC,0.4)))            ROOTS:248-270
```

### 2.5 积分与守恒
```
SW(L)+=SWDELTS+SWDELTU+SWDELTX+SWDELTT+SWDELTL                     WATBAL:200-215
Δ(SW·Δz)=RAIN+IRR−RUNOFF−DRAIN−ES−EP−暗管±侧向/田面水±雪±毛管        WBAL.for
```

## 3. 参数索引（水路径）

| 参数 | 来源 | 含义 | 读取处 |
|---|---|---|---|
| CN（SLRO）、U（SLU1）、SWCON（SLDR）、SWCN（SSKS） | .SOL | 径流曲线数/蒸发上限/排水系数/导水上限 | IPSOIL_Inp |
| KEP、EORATIO | .SPE !*EVAP | 蒸散消光（KTRANS=KEP）、EO-LAI 放大比 | IPPLNT.for:328；CROPGRO.for:246 |
| RWUEP1、RWUMX | .SPE !*ROOT 第1行 | 扩张阈值/单根长最大吸水 | IPPLNT.for:291 |
| PORMIN | .SPE !*ROOT 第4行 | 最小需氧孔隙 | IPPLNT.for:297 |
| KSEVAP | 默认 −99（旧法） | 土面蒸发消光 | CROPGRO.for:247 |
| TURSLA、XFRMAX、XTRFAC/YTRFAC 表 | .SPE | SLA 水敏感/繁殖分配上限/TURADD 表 | DEMAND IPDMND |
| ATOP | .SPE !*VEGE | 胁迫根分配幅度 | VEGGR.for:158 |
| SENDAY、SENMAX 表 | .SPE | 致衰速率/保叶下限 | SENES.for:123 |
| RTSDF、RTEXF、RFAC 系列 | .SPE/.ECO | 干/渍根死亡、根深根长参数 | ROOTS.for |
| DSWBAR、XSWBAR/YSWBAR、XSWFAC/YSWFAC 表 | .SPE（PODS 段） | 花荚水分感应深度与两表 | PODS.for:195-213 |
| WSENP(J) | .ECO 逐期 | 物候水敏感（±1） | Ipphenol.for:184 |
| TRIFOL、MNESPM、SDVAR、SHVAR | .CUL | 出叶间隔/满载速率/单粒荚潜力 | Ipphenol/DEMAND |

## 4. 水—氮双系列机制学对照（论文式表述可用）

| 环节 | 氮 | 水 |
|---|---|---|
| 土壤侧状态 | NO₃/NH₄（ppm） | SW（cm³/cm³） |
| 传输模型 | 容量型（浓度指数饱和×根长线性） | 容量型（(SW−LL) 指数饱和×根长对数饱和） |
| 需求侧 | 生化需求（NDMNEW，目标浓度×潜在生长） | 能量需求（EOP，Penman/PT） |
| 供需汇合点 | NUPTAK（植物） | SPAM（EP=min）+植物除法 |
| 主胁迫因子 | NSTRES（供需比，2日平均） | SWFAC/TURFAC（供需比，双阈值，无平滑） |
| 浓度型因子 | RNITP→AGEFAC（光合）、RNITPD（结荚） | 无（SWBAR 是土壤水型而非植物水势型） |
| 直接限光合 | 无 | 有（PG×SWFAC） |
| 成分可塑性 | PODCMP 蛋白/脂/糖 | 无 |
| 记忆机制 | CNSTRES 8日、WNRF 库存量 | CUMTUR 20日、RATTP 5日、CUMSTR 不可逆 |
| 主动适应 | 根分配↑、氮动员 | 根分配↑+根深加速+繁殖分配↑+库强补偿 |
| 守恒闭包 | WTNTOT 平衡（PlantNBal） | 水量平衡（WBAL） |

## 5. 模型性质诚实清单

1. 全链条无土壤-植物水势与 ABA 信号——胁迫是**日尺度供需比**，干旱的"明日下午气孔先关"等非水力过程不可表达；
2. tipping-bucket 无非饱和流；毛管上升仅为蒸发补水的经验扩散式；
3. 吸水/吸收（N）均为容量模型且逐层等比缩放（WUF/NUF 同构），不模拟新根先锋层优先;
4. SWFAC/TURFAC 无平滑 → 水分响应日间噪声直接进入生长；若做统计降尺度/日内天气敏感性需注意；
5. 所有层域量定义在 MESOL 内部网格上——土壤文件分层通过 Δz、DUL/SAT 层分布间接改变 RUNOFF/入渗/蒸发/吸水的数值（见土壤篇与氮系列 02）；
6. 促进型通道（TURADD/TURXFR/CUMTUR 补偿）使水分响应**非单调**：轻度干旱产量可能高于充分供水，标定与优化时须按实测检验这些表的形状。

## 6. 现象→机制速查表

| 观察到的现象 | 负责机制 |
|---|---|
| 轻度干旱下 LAI 先降、生物量后降 | TURFAC 先于 SWFAC 触发（RWUEP1 双阈值，04 §1） |
| 干旱年份籽粒更小更满、单粒速率反而快 | TURADD 促进 + 繁殖分配 TURXFR（05 §3-4） |
| 复水后叶量快速回补 | CUMTUR 20 日记忆→FRLF 补偿（05 §3） |
| 花期连旱减产远超灌浆期同强度干旱 | 花荚添加 min(SWADD)+荚窗不可逆 + R5 后 CUMSTR 不可逆（05 §1,§4） |
| 渍涝表现如干旱+根腐 | SWEXF 双向：吸水受阻（TSS 2日延迟）+根死亡（05 §6） |
| 高 CO₂ 下水分胁迫减轻 | TRATIO 降 EOP→供需比改善（03 §4） |
| 干旱促进早花/早熟 | FSW·WSENP(J)（物候通道，04 §3） |
| 深层水利用差异大 | 根深加速条款 + ROOTWU 的 Δz·RLV 线性项（05 §6、03 §5） |

---

*本系列完。工作区：主仓库 `CROPGRO_WATER_MECHANISM/`；源码 worktree `/Users/lidaeus/Documents/NewDssat-analysis`（分支 `analysis/mesol2-layering`，官方 v4.8.6.0）。姊妹篇：氮系列 [../CROPGRO_N_MECHANISM](../CROPGRO_N_MECHANISM/README.md)、土壤分层与初始条件 [../MESOL_SOIL_LAYERING_AND_IC_INITIALIZATION_20260827.zh-CN.md](../MESOL_SOIL_LAYERING_AND_IC_INITIALIZATION_20260827.zh-CN.md)。*
