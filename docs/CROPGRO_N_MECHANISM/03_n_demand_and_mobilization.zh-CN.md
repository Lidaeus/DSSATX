# 03 · 需氮量体系与氮动员：DEMAND + MOBIL 的数学模型

系列：[README](README.md) · 上一篇：[02 根系吸收](02_n_uptake_supply.zh-CN.md) · 下一篇：[04 氮胁迫因子](04_n_stress_factor.zh-CN.md)

**代码基准**：v4.8.6.0，`Plant/CROPGRO/DEMAND.for`（1365 行）、`MOBIL.for`（107 行）

---

## 1. 目标氮浓度体系（三浓度结构）

CROPGRO 用"蛋白质组成"参数（物种文件 `!*PLAN`/`!*SEED`/`!*PODS` 段）定义各器官的三档氮浓度（g N/g 干重 = 蛋白质分数 × 0.16，蛋白质含氮 16%）：

| 档位 | 叶 | 茎 | 根 | 籽粒 | 荚壳 | 定义处 |
|---|---|---|---|---|---|---|
| **最大**（奢侈）FNIN | PROLFI×0.16 | PROSTI×0.16 | PRORTI×0.16 | SDPRO×0.16 | PROSHI×0.16 | `DEMAND.for:217-220`、`PODS.for:353` |
| **正常**（生长） | PROLFG×0.16 | PROSTG×0.16 | PRORTG×0.16 | — | — | `VEGGR.for:219-221`（FNINLG 等） |
| **最低**（下限） | PROLFF×0.16 | PROSTF×0.16 | PRORTF×0.16 | PROMIN | PROSHF×0.16 | 物种文件 `!*PLAN`（`DEMAND.for` IPDMND 809/813 行读取）；PROMIN/PROMAX/THETA 见 `PODS.for:965` |

- **需氮量**按最大浓度计（NUPTAK 的 ANDEM 上限）；**实际生长**在最大与最低之间按氮可用量插值（05 篇 §3）；**可动员氮库**以下限为界（§4）。

## 2. NDMNEW：新组织生长需氮（`DEMAND.for:622-629`）

```
AGRVG2 = AGRVG + (FRLF·PROLFI + FRRT·PRORTI + FRSTM·PROSTI)·RPROAV    ! 每 g 营养组织的总碳价（含蛋白合成）
NDMVEG = (CDMVEG/AGRVG2) × (FRLF·FNINL + FRSTM·FNINS + FRRT·FNINR)
NDMNEW = NDMREP + NDMVEG
```

- CDMVEG = 分配给营养生长的碳（`DEMAND.for:494-496`）；
- NDMREP = NDMSD + NDMSH（`482-484`）：
  - **籽粒** GDMSD 由 cohort 模型算出：单粒最大速率 SDGR = SDVAR×TMPFAC×REDPUN×(1−(1−DRPP)·SRMAX)×(1+TURADD)（`309-310`），逐龄组累加并受脱粒阈值 SDMAX 约束（`322-345`）；NDMSD = FNINSD×GDMSD（`355`）；
  - **荚壳** GDMSH 按 GRRAT1 = SHVAR×TMPFAC×(1−(1−DRPP)·SRMAX)×(1+TURADD)（`377`）逐 cohort 累加（`389-412`）；NDMSH = GDMSH×FNINSH（`483`）；
  - 当总碳需求 CDMREP > 可用 CAVTOT=PGAVL×XFRT 时按比例压缩（`462-478`）；
- XFRT（繁殖分配比）= XFRUIT×TEMXFR + XFRUIT×TURXFR，TURXFR=XFRMAX×(1−TURFAC)（`428-450`）——**注意 XFRT 不受氮胁迫直接影响**，氮对繁殖分配的作用走 PODS 内部的供给约束。

## 3. NDMOLD：老组织复充需氮（`DEMAND.for:634-656`）

目的：让亏氮组织（浓度低于目标）在有氮时"回填"。目标浓度随生殖成熟度下调：

```
若 DXR57 > 0（R5 后）:  FRNLFT = NRCVR + (1−NRCVR)·(1 − DXR57²)
目标浓度 NVSTL = PROLFF×0.16 + (FNINL − PROLFF×0.16)·FRNLFT    ! 从最大浓度滑向下限
             （茎、根同理）
NDMOLD = (WTLF−WCRLF)·max(0, NVSTL − PCNL/100)
       + (STMWT−WCRST)·max(0, NVSTS − PCNST/100)
       + (RTWT−WCRRT)·max(0, NVSTR − PCNRT/100)
上限截断: NDMOLD ≤ CNOLD/RNO3C×0.16     ! CNOLD = PGAVL−CDMREP（剩余碳要付得起硝酸盐还原代价）
```

- `WTLF−WCRLF`：去掉碳储备后的**结构**叶干重；
- NRCVR 为物种参数（R5 后目标浓度的恢复系数，`DEMAND.for:855` 附近读取 `!*CARB` 段）；
- 截断式保证"回填氮"不会超出碳预算——氮需求与碳预算耦合的典型设计。

## 4. NMINEP/NMOBR：潜在氮动员（`DEMAND.for:232-250`）

```
NMOBR  = NVSMOB × NMOBMX × TDUMX                          ! 营养期
R5 后: NMOBR = NMOBMX×TDUMX2 × (1+0.5(1−SWFAC)) × (1+0.3(1−NSTRES))
              × (NVSMOB + (1−NVSMOB)·max(XPOD, DXR57²))    ! :246-249
NMINEP = NMOBR × (WNRLF + WNRST + WNRRT + WNRSH)
```

- `WNRLF` 等 = 各器官**可动员氮库**（GROW.for:1006-1019）：`WNRLF = max(WTNLF − PROLFF×0.16×(WTLF−WCRLF), 0)`——组织氮中高出"最低蛋白"的部分；
- NMOBMX：单日可动员比例上限（物种 `!*CARB` 段）；NVSMOB：营养期相对速率；
- R5 后动员被**加速**：水分胁迫（SWFAC 低）+50%、氮胁迫（NSTRES 低）+30%、随 XPOD/DXR57² 增大——即"缺氮促动员、灌浆期促动员"；
- TDUMX/TDUMX2 为生理日速率缩放。

## 5. MOBIL：实际动员量（`MOBIL.for:50-73`）

```fortran
IF (NDMNEW − TRNU > 1.E-5 .AND. NMINEP > 1.E-4) THEN
    NMINEA = MIN(NDMNEW − TRNU, NMINEP)     ! 实际动员 = 亏缺与潜力取小
    NMINER = NMINEA/NMINEP × NMOBR          ! 实际动员速率比例
    NRUSLF = NMINER × WNRLF                 ! 按可动员库比例分摊到器官
    NRUSST = NMINER × WNRST
    NRUSRT = NMINER × WNRRT
    NRUSSH = NMINER × WNRSH
    CNMINE = NMINEA/0.16 × RPRO             ! 蛋白再合成碳代价（未使用）
ENDIF
```

关键语义：

1. **触发条件是新生长需求未被吸收满足**（NDMNEW−TRNU，不含 NDMOLD）——复充老组织的氮不能靠动员自身（那是左手倒右手）；
2. 动员量与潜力成比例：NMINEA/NMINEP = NMINER/NMOBR；
3. 器官间按 WNRLF:WNRST:WNRRT:WNRSH **等比例**抽取（不区分器官优先级）；
4. 动员的碳代价在 `CROPGRO.for:1022-1026` 从 PGAVL 扣除：NMINEA/0.16×RPRO；
5. **动员直接触发叶衰老**：SENES.for:198 `LFSEN = SENRTE×NRUSLF/0.16`（见 06 篇 §7）。

## 6. NDMSDR：籽粒对动员氮的预留（`DEMAND.for:361-371`）

```
NDMSDR = min(NDMSD, NMINEP)              ! 籽粒需求中可由动员氮满足的部分
GDMSDR = NDMSDR/FNINSD                   ! 对应的籽粒干重
CDMSDR = GDMSDR×(AGRSD1 + FNINSD×6.25×RPRO)   ! 其合成碳价（动员氮路线）
CDMSD  = (GDMSD−GDMSDR)×AGRSD2 + CDMSDR  ! 总碳需求 = 新吸收氮路线 + 动员氮路线
```

NUPTAK 的需求 ANDEM = (NDMTOT−NDMSDR)×10 因此**不重复**计算动员可覆盖的部分——这是供需闭环自洽的关键细节。

## 7. 完整需求汇总（`DEMAND.for:660`）

```
NDMTOT = NDMREP + NDMVEG + NDMOLD
       = (籽粒+荚壳新组织) + (茎叶根新组织) + (老组织复充)      全部按最大氮浓度计
```

次日 NUPTAK 用 NDMTOT−NDMSDR 作为吸收上限；MOBIL 用 NDMNEW 作为动员触发；VEGGR 用 NDMNEW×NSTFAC 作为 NSTRES 的分母（04 篇）。

## 8. 单位与换算约定（本系列通用）

| 量 | 单位 | 备注 |
|---|---|---|
| 蛋白质→氮 | ×0.16 | g N / g 蛋白质 |
| 氮→蛋白质 | ×6.25 | 上者倒数 |
| g/m² ↔ kg/ha | ×10 | 1 kg/ha = 0.1 g/m² |
| NO₃ ppm ↔ kg/ha | ×(BD×Δz×0.1) | KG2PPM 倒数（土壤篇 §6.3） |
