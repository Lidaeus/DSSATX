# 04 · 水胁迫机制核心：SWFAC / TURFAC / SATFAC / FSW

系列：[README](README.md) · 上一篇：[03 蒸散与吸水](03_et_demand_and_root_uptake.zh-CN.md) · 下一篇：[05 生理作用点](05_water_effects_on_physiology.zh-CN.md)

**代码基准**：v4.8.6.0，`Plant/CROPGRO/CROPGRO.for:684-702`、`ROOTS.for:200-281`、`PHENOL.for:188-250`、`RStages.for:204`

---

## 1. SWFAC 与 TURFAC：定义（逐行剖析）

```fortran
! CROPGRO.for:684-702（RATE 阶段，出苗后且 ISWWAT='Y' 才计算，否则恒 1）
SWFAC  = 1.0
TURFAC = 1.0
IF (EOP .GT. 0.001) THEN
    EP1 = EOP * 0.1                                  ! 潜在蒸腾 cm/d
    IF (TRWUP / EP1 .LT. RWUEP1) THEN
        TURFAC = (1./RWUEP1) * TRWUP / EP1           ! :695-696
    ENDIF
    IF (EP1 .GE. TRWUP) THEN
        SWFAC = TRWUP / EP1                          ! :698-699
    ENDIF
ENDIF
```

数学表达：

```
TURFAC = min{1,  (TRWUP/EOP) / RWUEP1 }        扩张（turgor）胁迫因子
SWFAC  = min{1,  TRWUP/EOP }                  光合/代谢胁迫因子

TRWUP = 潜在根系吸水总量（ROOTWU，土壤供水能力侧，cm/d）
EOP   = 潜在蒸腾（TRANS，大气需求侧，mm/d）
RWUEP1= 物种阈值参数（.SPE !*ROOT 段第 1 行，IPPLNT.for:291），"扩张不受限所需的最小供给/需求比"
```

### 双阈值语义（本机制的精髓）

以 RWUEP1=1.5 为例：

| TRWUP/EOP | TURFAC | SWFAC | 解读 |
|---|---|---|---|
| ≥1.5 | 1.00 | 1.00 | 供水超过需求 1.5 倍：完全无胁迫 |
| 1.2 | 0.80 | 1.00 | **只有扩张受抑**（叶变小变厚），光合不受影响 |
| 1.0 | 0.67 | 1.00 | 恰好供需平衡：扩张已减 1/3 |
| 0.8 | 0.53 | 0.80 | 扩张与光合同时受抑 |
| 0.4 | 0.27 | 0.40 | 重度胁迫 |
| 0.0 | 0.00 | 0.00 | — |

即：**细胞扩张比光合代谢对缺水敏感得多**——这与实验证据（轻度干旱先抑叶面积后抑光合）一致，是 CROPGRO 水分响应曲线形状的第一控制点。RWUEP1 与氮侧的 NSTFAC（供需触发线）角色类似，但方向相反：RWUEP1 是"需求端放大器"（要求供给>需求），NSTFAC 是"供给端折扣"。

### 时间性质：无平滑、当日生效

- SWFAC/TURFAC 在 RATE 阶段计算，**同一天**就进入 PHENOL（:708）、PHOTO（:737）等全部消费点；
- 与氮侧对比鲜明：NSTRES 有 2 日滑动平均（`VEGGR.for:256`）、CNSTRES 有 8 日平均（`PODS.for:414`），而水胁迫因子**零平滑**——一日的高温低湿即可当日压低光合与扩张；
- 供给侧仍有隐性滞后：TRWUP 用的是昨日 RLV（根长）与当日晨 SW。

## 2. SATFAC：根长加权的渍涝指数（ROOTS.for:200-281）

```
逐层: SWEXF(L) = min(1, (SAT(L)−SW(L))/PORMIN)      ! PORMIN=物种最小需氧孔隙（!*ROOT:297）
SUMEX = Σ Δz·RLV·(1−SWEXF)；SUMRL = Σ Δz·RLV
SATFAC = SUMEX/SUMRL                                 ! :279-283（0=无渍涝，→1=根区全饱和）
```

**在 CROPGRO 中 SATFAC 只作诊断输出**（Opgrow/OPHARV 报表）；其生理效应不走 SATFAC 本身，而是通过 SWEXF 的三个直接作用实现（05 篇 §11）：

1. `ROOTWU.for:98-115`：饱和层吸水先经 2 天延迟（TSS）再按 SWEXF 压低（渍涝反而缺水）；
2. `ROOTS.for:242`：根系生长分布因子 RLDF ∝ min(SWDF, SWEXF)；
3. `ROOTS.for:230-239`：根死亡因子 RTSURV 含 1−RTEXF·(1−SWEXF)。

（对照：CERES 类模块用 (1.0−SATFAC) 直接乘叶生长/光合；CROPGRO 不是。）

## 3. FSW：物候的水胁迫调制（PHENOL.for + RStages.for）

```
发芽期（PH-1）: SWFEM = 播深 10cm 内平均 SW（PHENOL.for:188-222）
                FSW(1) = CURV('LIN',0,20,100,1000, SWFEM)      ! 0–20% 线性
                FSW(1) = 1 + (1−FSW(1))·WSENP(1)               ! :223-228
其余各期 J:     FSW(J) = 1 + (1−SWFAC)·WSENP(J)                ! :248
                （FNSTR/FPSTR 对 NSTRES/PStres2 同构，:249-250）
期进程（RStages.for:204,237）:
                PROG(J) = FT(J)·FUDAY(J)·MIN(FSW(J),FNSTR(J),FPSTR(J))
                PHZACC(J) += PROG(J)
```

- WSENP(J) 为**生态型文件逐期参数**，范围 [−1,+1]：负值缺水延迟发育、正值缺水提前发育（典型用途：干旱加速开花/成熟）；
- 三种养分胁迫取 **min**（最严者生效）后作为乘子——与花荚添加的 min(SWADD1,SWADD2,…) 风格一致；
- 另一条物候通道：营养期叶龄推进直接乘 TURFAC（`PHENOL.for:469`：VSTAGE += DTX·TRIFOL·EVMOD·TURFAC·(1−XPOD)）——缺水放慢出叶/节数，进而压低 VSTAGE 驱动的一切（株高、分配表、叶面积）。

## 4. 水—氮胁迫机制对照表

| 维度 | 水胁迫（SWFAC/TURFAC） | 氮胁迫（NSTRES） |
|---|---|---|
| 类型 | 供需比：TRWUP/EOP | 供需比：(TRNU+NMINEA+NFIXN)/(NSTFAC·NDMNEW) |
| 需求定义 | 大气蒸腾需求（能量学） | 新组织生长需氮（生化学） |
| 供给定义 | 土壤根系潜在吸水（容量模型） | 实际吸收+动员+固氮（流量） |
| 阈值 | 单一 RWUEP1（双因子共用） | NSTFAC（触发折扣） |
| 因子个数 | 2（扩张/代谢分离） | 1（+慢速 CNSTRES 用于生殖） |
| 平滑 | 无（当日） | 2 日 / 8 日滑动平均 |
| 直接乘光合 | **是**（PG×SWFAC） | 否（仅经叶氮 AGEFAC 与 EXCESS 间接） |
| 直接乘物候 | 是（FSW·WSENP、TURFAC 叶龄） | 是（FNSTR·NSENP） |
| 促进效应 | 多条（TURXFR、TURADD、根深扎、CUMTUR 补偿） | 少量（动员加速） |
| 计算位置 | 植物模块 CROPGRO.for:684 | 植物模块 VEGGR.for:238 |

## 5. 输出核查

- `PlantGro.out`：TURFAC/SWFAC 日序列列（Opgrow）；`Summary.out` 有胁迫天数统计；
- `ET.out`/`SW.OUT`（IDETW='Y'）：EO/EOP/EOS/ES/EP/TRWU/TRWUP 与逐层 SW——核对供需比逐日值的官方途径；
- SWFAC/TURFAC 无单独平滑状态，可直接用 ET.OUT 的 TRWUP 与 EOP 复算验证（TRWUP/EOP 即两因子的共同原比）。

## 6. 标定与分析提示

1. **RWUEP1 是水分响应曲线斜率的一阶旋钮**：调大→扩张更早受抑（LAI 对水分更敏感）；调小→叶面积钝感；
2. SWFAC 直接乘 PG，因此 RWUEP1 也间接决定"光合开始受害"的土壤水阈值（SWFAC<1 ⟺ TRWUP<EOP，由 ROOTWU 的 (SW−LL) 指数与 RWUMX 决定）；
3. RWUMX 与 RLV 共同决定 TRWUP 的绝对量——根系参数（RFAC 系列、RTDEP 速率）因此是水分胁迫强度的间接控制者；
4. 高 CO₂ 场景下 TRATIO 降 EOP → 同一土壤水状况下 SWFAC/TURFAC 更接近 1（CO₂ 缓解水胁迫的正效应），做 CO₂×水分交互时务必核对（03 篇 §4）。
