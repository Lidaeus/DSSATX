# 07 · 数学建模总结：全方程清单、守恒律与参数索引

系列：[README](README.md) · 上一篇：[06 生理作用点](06_n_effects_on_physiology.zh-CN.md)

**代码基准**：v4.8.6.0（`Plant/CROPGRO/`）。本文把 01–06 篇的机制浓缩为一套自洽的数学模型，便于复现、改造或写方法章节。

---

## 1. 状态变量与单位

| 状态 | 符号 | 单位 | 更新处 |
|---|---|---|---|
| 器官干重 | WTLF/STMWT/RTWT/SHELWT/SDWT | g/m² | GROW.for |
| 器官氮量 | WTNLF/WTNST/WTNRT/WTNSH/WTNSD | g N/m² | GROW.for:828-866 |
| 碳储备 | WCRLF/WCRST/WCRRT/WCRSH | g CH2O/m² | GROW.for |
| 可动员氮库 | WNRLF/WNRST/WNRRT/WNRSH | g N/m² | GROW.for:1006-1019 |
| 叶氮浓度 | PCNL、RNITP（结构基） | % | GROW.for:959,998 |
| 根长密度 | RLV(L) | cm/cm³ | ROOTS.for |
| 土壤无机氮 | NO3(L)、NH4(L) | ppm | 土壤模块 |

换算常数：蛋白×0.16=N；g/m²×10=kg/ha；ppm×(BD·Δz·0.1)=kg/ha。

## 2. 方程清单（按计算次序）

### 2.1 碳供给
```
CMINEP = CMOBMX·(DTX+DXR57)·ΣWCR                        CROPGRO.for:901
PGAVL  = PG + CMINEP − MAINR − RSPNO3 − RSPNH4 − NMINEA/0.16·RPRO − CNOD  :902-1091
PG     = PTSMAX·SLPF·PGFAC·TPGFAC·E_FAC·PGSLW·PRATIO·PGLFMX·SWFAC·EXCESS  PHOTO.for:194-195,231
```

### 2.2 需氮
```
FNINL=PROLFI·0.16 等（三浓度体系）                        DEMAND.for:217-220
GDMSD = Σ_cohort min(SDGR·SDNO, SDMAX)；SDGR=SDVAR·TMPFAC·REDPUN·(1−(1−DRPP)SRMAX)(1+TURADD)  :309-345
GDMSH = Σ_cohort ADDSHL_pot（GRRAT1 同构）                :377-412
NDMREP = FNINSD·GDMSD + FNINSH·GDMSH                     :482-484
NDMVEG = (CDMVEG/AGRVG2)·Σ(f·FNIN)                       :627-628
NDMNEW = NDMREP + NDMVEG                                 :629
NDMOLD = Σ_organ 结构重·max(0, NVST(DXR57) − 实际N%) ≤ CNOLD/RNO3C·0.16   :634-655
NDMTOT = NDMNEW + NDMOLD                                 :660
```

### 2.3 吸收（分层）
```
FNO3(L) = 1−e^(−0.08·NO3(L))（截 0.04/1）                NUPTAK.for:125-130
SMDFR   = 分段水分因子，下限 0.1                          :132-141
RNO3U(L)= RLV·√SMDFR·Δz·100·FNO3·RTNO3                   :144-154
NUF     = min(1, (NDMTOT−NDMSDR)·10 / ΣRNO3U)            :160-165
UNO3(L) = min(NUF·RNO3U, SNO3 − 0.25/KG2PPM)             :168-177
TRNU    = Σ(UNO3+UNH4)/10                                :178-187
```

### 2.4 动员
```
NMOBR  = NVSMOB·NMOBMX·TDUMX；R5 后 ×(1+0.5(1−SWFAC))(1+0.3(1−NSTRES))(NVSMOB+(1−NVSMOB)max(XPOD,DXR57²))
NMINEP = NMOBR·ΣWNR                                     DEMAND.for:244-250
NMINEA = min(NDMNEW − TRNU, NMINEP)（当 NDMNEW−TRNU>1e−5）  MOBIL.for:64-66
NRUSlf = (NMINEA/NMINEP)·NMOBR·WNRLF（各器官同构）          :67-71
```

### 2.5 胁迫因子
```
X_t    = min(1, (TRNU+NMINEA+NFIXN)/(NSTFAC·NDMNEW))     VEGGR.for:238-253
NSTRES = ½X_t + ½X_{t−1}                                 :256
CNSTRES= 0.875·CNSTRES + 0.125·NSTRES                    PODS.for:414
```

### 2.6 生殖生长
```
RSD   = min(CRSD, NRSD, 1)；NRSD=NAVL/(FNINSD·min(PGAVLR/AGRSD1,GDMSD))   PODS.for:486-497
PODCOMP: XRSD（θ 型双曲线）→ ANINSD→POTLIP/POTCAR 补偿→AGRSD3→RSD 重算    :1003-1213
ADDSHL ≤ min(PGLEFT/AGRSH1, GRRAT1·SHELN, NLEFT/(FNINSH·CNSTRES^0.5))     :599-614
NGRSH = ADDSHL·PROSHI·0.16·CNSTRES^0.5                   :631
RNITPD=(RNITP%−PROLFF·0.16)/(FNINL−PROLFF·0.16)∈[0.1,1.1]  :750-752
PODADD∝min(SWADD1,SWADD2,RNITPD)·max(1−ACCAGE,0)，另受 N 上限            :753-757
FLWADD∝min(SWADD1,SWADD2,CNSTRES^0.5)                     :776-777
```

### 2.7 营养生长（三浓度）
```
VGRDEM = PGAVL/AGRVG；WLDOTN=FRLF·VGRDEM 等              VEGGR.for:290-293
情形B（稀释）: NGRLF=NAVL·NGRLF/NGRVEG（截自身）           :338-342
情形C（硬约束）: NRATIO=NAVL/NGRVGG；W*x·NRATIO            :309-322
余氮: NLEAK=max(0,NLEFT−NDMOLD)；NADLF=NLEFT_rest·FRLF·FNINL/Σ(f·FNIN)   :441-453
EXCESS=(1.20−min(1,max(PGLEFT/PG,0.2)))^0.5               :385-389
```

### 2.8 形态与衰老
```
FRRT += ATOP·(1−min(TURFAC,NSTRES,PStres2))·(1−FRRT)      VEGGR.for:259-260
NFSL = max(0.1,1−(1−NSTRES)·NSLA)；CUMNSF=0.75C+0.25NFSL  DEMAND.for:560-564
HNHGT= max(0.1,1−(1−NSTRES)·NHGT)；CUMNHT 同构             CANOPY.for:223-224
LFSEN= SENRTE·NRUSLF/0.16                                 SENES.for:198
```

### 2.9 状态积分
```
NLDOT = NGRLF − NLOFF − NRUSLF + NADLF·(1−损失率)；WTNLF += NLDOT   GROW.for:746-828
RNITP = 100·WTNLF/(WTLF−WCRLF)（下限 PCNMIN）               :997-1001
WNRLF = max(WTNLF − PROLFF·0.16·(WTLF−WCRLF), 0)           :1006-1007
RPROAV= Σ(源代价×源量)/(源总量)                             CROPGRO.for:1211-1216
```

## 3. 守恒律

**碳**：PGAVL 全部用于 生长合成（AGR 系数已含成分代价）+ 储备 ± 动员 ± 吸收/固氮氮同化代价 + 泄漏近似；EXCESS 机制保证过剩不无限累积（通过压 PG）。

**氮（严格）**：
```
ΔWTNTOT = TRNU + NFIXN + ΔSDNPL(−) − ΣN_off − NLEAK − 收获移除
```
内部转移（动员→新组织）净零。PlantNBal.for 按此核对（期末误差应为数值级）。

**两条关键不等式**：
```
TRNU ≤ min(NDMTOT−NDMSDR, ΣL 潜在供给)        吸收双上限
NAVL 级联各汇的扣除 ≤ 剩余量（MAX(0,·) 处处截断）
```

## 4. 参数索引（氮相关，物种 *.SPE 为主）

| 参数 | 段 | 含义 | 读取处 |
|---|---|---|---|
| PROLFI/PROLFF、PROSTI/PROSTF、PRORTI/PRORTF | !*PLAN | 叶/茎/根 最大/最低蛋白分数 | DEMAND.for IPDMND (~809/813) |
| PROLFG/PROSTG/PRORTG | !*PLAN | 正常生长蛋白分数 | VEGGR.for:121-127 |
| SDPRO、PROSHI/PROSHF | *CULTI / !*PODS | 籽粒蛋白；荚壳最大/最低蛋白 | DEMAND.for(~767)；PODS.for:175 |
| PROMIN/PROMAX/THETA | !*PLAN | 籽粒蛋白下/上限与曲线形状 | PODS.for:965 |
| RNO3C、RPRO | !*RESP | 硝酸盐还原、蛋白再合成碳代价 | DEMAND.for:791 |
| RNH4C | !*RESP | 铵同化碳代价 | INCOMP.for |
| RFIXN | !*NODU（豆科） | 固氮碳代价 | NFIX.for |
| NMOBMX、NVSMOB、NRCVR | !*CARB | 动员速率上限/相对速率/R5后恢复系数 | DEMAND.for:855 |
| NSTFAC | !*CARB | 胁迫触发阈值（原硬编码 0.70） | VEGGR.for:141 |
| RTNO3、RTNH4 | !*ROOT | 单位根长吸收能力 | NUPTAK.for:75 |
| NSLA | !*LEAF | SLA 的氮敏感度（上限 1.2） | DEMAND.for IPDMND(~902) |
| SENRTE | !*SENI | 动员致衰系数 | SENES.for:123 |
| ATOP | !*VEGE | 胁迫下根分配最大增量 | VEGGR.for:158 |
| NHGT | !*CANO（ECO 段可覆盖） | 株高氮敏感度（上限 1.4） | CANOPY.for |
| FNPGN 曲线 + LNREF | !*PHOT | 光合—叶氮曲线及参考 | PHOTO.for |
| CMOBMX、CADSTF | !*CARB | 碳动员/储备参数 | VEGGR.for:138 |

（品种文件 *.CUL 的 SDPRO/SDLIP、生态型 *.ECO 的部分形态参数另计。）

## 5. 模型性质的诚实清单（做方法学表述时可用）

1. 吸收模型为容量型（根长×浓度饱和×水分），**不含**质流-扩散动力学与根际耗竭；
2. NSTRES 为流量比型胁迫，**不含**浓度型当量（浓度效应仅通过 RNITP→AGEFAC 与 RNITPD→结荚两条通道体现）；
3. 光合不直接乘 NSTRES；EXCESS 反馈构成唯一的"氮→次日总光合"乘性路径；
4. 物候与氮的耦合由生态型逐期参数 NSENP 控制（FNSTR=1+(1−NSTRES)·NSENP，与 FSW/FPSTR 取 min 乘入光温速率，`PHENOL.for:249`、`RStages.for:204`；NSENP=0 时无效应）；
5. 氮动员按库等比例抽取、无器官优先级；泄漏 NLEAK 为一阶损失近似；
6. 全部氮-生理响应含 0-8 日不等滞后（06 篇 §8），校准试验设计需考虑时间尺度匹配；
7. 土壤分层（MESOL=2 的 LYRSET2 网格）通过 RLV·Δz 加权与分层残留截断影响吸收的数量与分布（02 篇 §6）。

## 6. 快速回查：现象→机制速查表

| 观察到的现象 | 负责机制（本系列） |
|---|---|
| 低氮下生物量先慢后快滑落 | 情形 C 压缩 + EXCESS 下调 + 动员耗竭断崖（05 §3、06 §2、04 §2） |
| 低氮下 LAI 降得比生物量慢 | SLA 通道（叶变薄，06 §3） |
| 低氮下根冠比升高 | FRRT 通道（06 §4） |
| 低氮下荚数剧减、单荚重降幅小 | RNITPD 结荚限制 + 荚壳 √CNSTRES 允许贫氮生长（06 §5） |
| 低氮籽粒蛋白%下降、脂+0.33/糖+0.67 补偿 | PODCOMP（06 §6） |
| 后期叶快速黄死 | SENRTE 动员致衰正反馈（06 §7） |
| 施氮后产量恢复有 1 周以上迟滞 | CNSTRES 8 日平均 + 荚窗不可逆（06 §8） |
| 同施氮量下分层土壤文件结果不同 | 内部网格改变 ΣRLV·Δz 与残留截断（02 §6 + 土壤篇） |

---

*本系列完。全部结论基于官方 v4.8.6.0 源码静态分析；如需逐行核对，worktree 位于 `/Users/lidaeus/Documents/NewDssat-analysis`（分支 `analysis/mesol2-layering`）。*
