# 01 · 架构总览与每日氮流调用序列

系列：[README](README.md) · 上一篇：无 · 下一篇：[02 根系吸收](02_n_uptake_supply.zh-CN.md)

**代码基准**：v4.8.6.0（`d6556cca`），`Plant/CROPGRO/CROPGRO.for`

---

## 1. CROPGRO 氮模拟的总体架构

CROPGRO 采用"**碳氮双供给、逐库满足、逐日平衡**"的池模型：

```
                 ┌────────────────────── 冠层光合 (PHOTO.for, RATE 阶段) ──────────────────────┐
                 │  PG = PTSMAX·SLPF·PGFAC·TPGFAC·E_FAC(叶片氮RNITP)·PGSLW·PRATIO·PGLFMX·SWFAC│
                 └──────────────────────────────┬──────────────────────────────────────────────┘
                                                │ × EXCESS（昨日碳过剩下调）
碳流 PGAVL = PG + CMINEP(碳储备动员) − MAINR(维持呼吸) − 合成/吸收/固氮代价
                                                │
   ┌────────────────────────────────────────────┼─────────────────────────────────────────────┐
   │                     同一时刻并行的氮流 NAVL（CROPGRO.for:962-1173 级联）                  │
   │  种子残留N(SDNPL) → +TRNU(根系吸收) → +NMINEA(氮动员) → +NFIXN(固氮,豆科)                │
   │      → −(NGRSD+NGRSH)  籽粒/荚壳 → −(NGRLF+NGRST+NGRRT)  茎叶根新组织                    │
   │      → −(NADLF+NADST+NADRT)  氮储备沉积（超出部分泄漏 NLEAK）                            │
   └──────────────────────────────────────────────────────────────────────────────────────────┘
```

要点：

- **NAVL**（available N，g[N]/m²/d）是当日植物可用于生长的氮总量；**PGAVL** 是碳对应物。二者在一天内按"繁殖器官优先、营养器官其次、剩余入储备"的顺序消耗（`CROPGRO.for:1096-1174`）。
- 每个器官的生长同时受碳、氮两个"供给/需求"比的约束，取较小者（见 06 篇）。
- 氮胁迫因子 **NSTRES 在当日碳氮平衡计算完之后**由 VEGGR 计算（`VEGGR.for:238-256`），**从次日**起影响分配、SLA、生殖等过程（供需驱动的滞后性）。

## 2. 模块阶段（DYNAMIC）与调用位置

CROPGRO.for 按 DSSAT 模块协议分阶段执行：

| 阶段 | 主要氮相关动作 |
|---|---|
| RUNINIT | 读物种文件各段参数（各子程序自行读取，如 NUPTAK 读 RTNO3/RTNH4，VEGGR 读 NSTFAC） |
| SEASINIT | 状态清零（NAV​L 相关中间量、NSTRES=1.0 等，`VEGGR.for:176-205`） |
| RATE | **PHOTO**（`CROPGRO.for:735-742`）：计算 PG 与 AGEFAC（叶片氮对光合的因子） |
| INTEGR | 氮流的全部主计算（本文第 3 节） |
| OUTPUT/SEASEND | PlantNBal 氮平衡报表、收获等 |

## 3. INTEGR 阶段的每日调用序列（逐步）

以下行号均指 `CROPGRO.for`（除注明外）。这是理解"氮素如何被吸收、分配、起作用"的主线：

| 步 | 调用/代码 | 行号 | 氮相关内容 |
|---|---|---|---|
| 0 | `CALL PHENOL` | 756-764 | 物候推进；水/氮/磷胁迫经生态型逐期参数 WSENP/NSENP/PSENP 调制各期进程：FNSTR(J)=1+(1−NSTRES)·NSENP(J)（`PHENOL.for:248-250`），与 FSW/FPSTR 取 min 后乘入光温速率 PROG=FT·FUDAY·MIN(FSW,FNSTR,FPSTR)（`RStages.for:204,237`）；NSENP=0 时无效应 |
| 0a | 出苗日一次性初始化 | 767-855 | GROW(EMERG) 建初体（WTNLF=WLFI×PROLFI×0.16 等，`GROW.for:441-445`）；DEMAND(EMERG) 设 FNINL=PROLFI×0.16 等（`DEMAND.for:217-220`）；PODS(EMERG) 设 FNINSH=PROSHI×0.16（`PODS.for:353`）；VEGGR(EMERG) 设最低氮浓度 FNINLG=PROLFG×0.16（`VEGGR.for:219-221`） |
| 1 | `NAVL=0; PGAVL=PG+CMINEP` | 888-902 | CMINEP = CMOBMX×(DTX+DXR57)×(四器官碳储备之和)：当日可动员碳上限 |
| 2 | `CALL RESPIR` | 906-915 | 维持呼吸 MAINR 从 PGAVL 扣除 |
| 3 | `CALL DEMAND(INTEGR,…)` | 941-954 | 计算需氮量体系（用**昨日** NSTRES、PCNL 等）：NDMTOT、NDMNEW、NDMOLD、NMINEP、NMOBR、FRLF/FRRT/FRSTM、XFRT、GDMSD/GDMSH（详见 03 篇） |
| 4 | 种子残留氮 | 962-968 | NAVL = SDNPL×DTX/7（播种 N 按生理日 7 天线性释放），并从 SDNPL 扣减 |
| 5 | `CALL NUPTAK(INTEGR,…)` | 975-978 | 土壤 NO3/NH4 吸收 → TRNO3U/TRNH4U/TRNU（详见 02 篇）；随后 983-989 扣吸收碳代价 RSPNO3=TRNO3U/0.16×RNO3C、RSPNH4 同理；993 行 NAVL += TRNU |
| 6 | `CALL MOBIL(INTEGR,…)` | 999-1002 | 氮动员：亏缺时 NMINEA = min(NDMNEW−TRNU, NMINEP)，按 WNRxx 比例从各器官抽取 NRUSxx（详见 03 篇 §4）；1022-1027 行 PGAVL −= NMINEA/0.16×RPRO（蛋白再合成代价），NAVL += NMINEA |
| 7 | 固氮门控 | 1065-1092 | 豆科（ISWSYM='Y'，VSTAGE>TTFIX）调 NFIX：NFIXN = MIN(CLEFT×0.16/RFIXN, DWNOD×SNACT)×TNFIX × MIN(SWFACT,SWMEM8,FLDACT)（`NFIX.for:328-329`）；ISWSYM='U' 或 ISWNIT≠'Y' 时按碳允许量兜底 NFIXN = max(0, NDMREP+NDMVEG−NAVL)（1079-1083，即"不模拟氮时视为不限氮"）；**番茄等非豆科：IPSIM 强制 ISWSYM='N'（`InputModule/IPSIM.for:225-236`），NFIXN=0**；1087-1092 行 PGAVL −= CNOD=RFIXN×NFIXN/0.16，NAVL += NFIXN |
| 8 | `CALL PODS(INTEGR,…)` | 1096-1109 | 实际籽粒/荚壳生长（WSDDTN/WSHDTN）与 NGRSD/NGRSH；花荚添加受 CNSTRES/RNITPD 限制（详见 06 篇 §5） |
| 9 | 繁殖器官扣除 | 1128-1141 | PGAVL −= WSDDTN×AGRSD3 + WSHDTN×AGRSH1；NAVL −= NGRSD+NGRSH |
| 10 | CSAVEV | 1148-1149 | 繁殖期碳储备分流：CSAVEV = CADPR1×PGAVL×FRACDN |
| 11 | `CALL VEGGR(INTEGR,…)` | 1154-1166 | 营养分配与生长：FRLF/FRRT/FRSTM（受昨日胁迫影响）、WLDOTN/WSDOTN/WRDOTN、NGRLF/NGRST/NGRRT、剩余氮 NADLF/NADST/NADRT、**NSTRES 本日计算**、EXCESS（详见 05 篇与 04 篇） |
| 12 | 营养器官扣除 | 1171-1174 | PGAVL −= AGRVG×(WLDOTN+WSDOTN+WRDOTN) + (CADLF+CADST)×PCH2O；NAVL −= (NGRLF+NGRST+NGRRT)+(NADLF+NADST+NADRT) |
| 13 | `CALL SENES` | 1178-1181 | 叶衰老：其中氮动员致衰 LFSEN = SENRTE×NRUSLF/0.16（`SENES.for:198`） |
| 14 | `CALL FREEZE`（条件） | 1186 | 冻害 |
| 15 | `CALL ROOTS(INTEGR,…)` | 1198-1202 | 根系生长与根长密度 RLV（RLV 是次日 NUPTAK 的输入） |
| 16 | 合成成本重算 | 1211-1225 | RPROAV = 按氮源加权的蛋白合成代价（(RSPNO3+RSPNH4)×0.16+NFIXN×RFIXN+NMINEA×RPRO)/(TRNU+NFIXN+NMINEA)；AGRSD2/AGRSH2/AGRVG2（含蛋白合成代价） |
| 17 | `CALL GROW(INTEGR,…)` | 1229-1257 | 状态积分：各器官干重与氮量、PCNL/PCNST/PCNRT/PCNSD/PCNSH、**RNITP=100×WTNLF/(WTLF−WCRLF)**（`GROW.for:998`）、可动员氮库 WNRLF/WNRST/WNRRT（`GROW.for:1006-1019`）——供次日 DEMAND/NUPTAK/PHOTO/PODS 使用 |

## 4. 日内氮流数据流图（状态-速率闭环）

```
      ┌────────────── 次日反馈环 ──────────────────────────────────────────┐
      │                                                                     │
      ▼                                                                     │
  GROW积分(昨日) ──► RNITP(叶片N%), PCNL/PCNST/PCNRT, WNRLF等可动员氮库, RLV(根长)
      │                    │                        │              │
      │                    ▼                        ▼              ▼
      │              PHOTO(RATE):AGEFAC      DEMAND:NDMTOT    NUPTAK:TRNU
      │              PG×EXCESS(碳过剩)        NDMNEW/NMINEP    (逐层RLV加权)
      │                    │                        │              │
      └──────────► CROPGRO(INTEGR): NAVL/PGAVL 级联（上文步骤1-12） ◄──────┘
                         │
                         ▼
              VEGGR: NSTRES(供需比) ──► 次日 FRRT/SLA(NFSL)/CANOPY/PODS(CNSTRES)
                         │
                         ▼
              GROW积分(本日): 更新各器官 N、RNITP、WNRLF ……（闭环）
```

**核心洞察**：

1. `NSTRES` 与 `AGEFAC` 是两个**不同**的氮胁迫量：前者是"供给/需求"比（当日算、次日生效），后者是"叶片氮浓度"的光合效率（浓度型、当日的）。二者同时存在，分别作用于不同过程。
2. 氮的全部下游影响要么改变**分配**（根冠比、繁殖分配 XFRT 不受氮直接影响、叶/茎比），要么改变**单位碳的氮浓度成本**（成分可塑性），要么改变**叶面积与叶片寿命**（SLA、衰老），要么直接**压缩生长速率**（NRATIO、RSD）。
3. 由于 NUPTAK 用的是**昨日根长密度 RLV**、DEMAND 用**昨日 NSTRES/PCNL**，而 VEGGR 的 NSTRES 又依赖当日的 TRNU/NMINEA——整个氮体系是带一日滞后的闭环，这也是 NSTRES 需要做 2 日滑动平均（`VEGGR.for:256`）的原因之一。

## 5. 番茄（CROPGRO-Tomato）的特化点

- 非豆科：`IPSIM.for:225-236` 的作物清单不含 'TO'（番茄），ISWSYM 强制 'N'，NFIXN 恒为 0，氮源只有吸收（TRNU）、动员（NMINEA）与种子残留（SDNPL）。
- 其余氮机制（NUPTAK/DEMAND/MOBIL/VEGGR/PODS/PODCOMP/SENES/PHOTO）与豆科完全同源，仅物种/品种/生态型参数不同。
- 棉花专用 LTGROW（棉绒生长含 NSFLT 氮因子，`LTGROW.for`）与花生专用 PODDET 等不适用于番茄，本系列仅在 06 篇注明。
