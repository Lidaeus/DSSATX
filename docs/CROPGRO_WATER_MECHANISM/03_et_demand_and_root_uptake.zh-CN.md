# 03 · 蒸散需求与根系吸水：PET / TRANS / SOILEV / ROOTWU / XTRACT

系列：[README](README.md) · 上一篇：[02 土壤水运移](02_soil_water_movement.zh-CN.md) · 下一篇：[04 水胁迫因子](04_water_stress_factors.zh-CN.md)

**代码基准**：v4.8.6.0，`SPAM/`

---

## 1. 潜在蒸散 EO：七种方法（PET.for:88-150，MEEVP 选择）

| MEEVP | 子程序 | 方法 | 备注 |
|---|---|---|---|
| R（默认，IPSIM.for:137） | PETPT | Priestley-Taylor | 无风速/湿度需求 |
| F | PETPEN | FAO-56 Penman-Monteith 参考 ET | 用 EORATIO 放大到作物冠层 |
| S / T | PETASCE | ASCE 双作物系数法（Kcb/Ke/REFET） | EOP=KCB·REFET、EOS=KE·REFET（覆盖 TRANS/PSE 内分支） |
| D | PETDYN | 动态 Penman-Monteith（用 CANHT 等冠层阻抗） | |
| P | PETPNO | FAO-24 Penman | |
| M | PETMEY | Penman-Meyer（南 NSW） | |
| H | PETPTH | 逐时 Priestley-Taylor + VPD 函数 | 供 TRANS 逐时路径 |

**作物侧的两个"接口参数"**：EORATIO（EO 随 LAI 的放大比，供 FAO-56 类）与 KTRANS（=KEP，蒸散消光系数，`CROPGRO.for:246`），均来自物种文件 `!*EVAP` 段（`IPPLNT.for:328`）。

## 2. 潜在土面蒸发 EOS（PSE，PET.for）

```
KE≥0（ASCE）:  EOS = KE·REFET
KSEVAP ≤ 0（默认，CROPGRO.for:247 置 −99）:
    XLAI ≤ 1:  EOS = EO·(1 − 0.39·LAI)
    XLAI > 1:  EOS = EO/1.1·exp(−0.4·LAI)
KSEVAP > 0:   EOS = EO·exp(−KSEVAP·LAI)
```

## 3. 实际土面蒸发 ES：Ritchie 两阶段（SOILEV.for）

**状态**（SEASINIT 由 SW(1) 初始化，`:55-78`）：阶段一累计 SUMES1、阶段二累计 SUMES2、阶段二天数 T；U=.SOL 的 SLU1（阶段一蒸发上限，mm）；风干系数 SWEF=0.9−0.00038·(Δz₁−30)²。

**RATE 逻辑**（`:82-174`）：

```
阶段一（土壤湿，SUMES1<U，ESUP，:200-228）:
    SUMES1 += EOS
    若 SUMES1 > U:  ES = EOS − 0.4·(SUMES1−U)；SUMES2 = 0.6·(SUMES1−U)；T=(SUMES2/3.5)²；SUMES1=U
    否则:           ES = EOS
阶段二（:96-119）:
    T += 1；ES = 3.5·T^0.5 − SUMES2        ! Σ=3.5·√t 的日增量（衰减曲线）
    有雨 WINF 时: ES ≤ max(0.8·WINF, ES+WINF?) 且 ≤ EOS；SUMES2 += ES−WINF；T 重算
    （足够大的雨把状态机拉回阶段一）
两重上限:
    顶层可提水 AWEV1 = (SW₁−SWEF·LL₁)·Δz₁·10（:139-159，超出时回收两阶段状态量）
    SWMIN = SW_AVail−SWEF·LL₁；ES ≤ SWMIN·Δz₁·10（:168-174）
塑料膜: ES ×(1−PMFRACTION)
```

替代路径：MESEV='S'（Sulieman-Ritchie，`ESR_SoilEvap.for`）逐层算 ES_LYR 并自算向上流 UPFLOW（`SPAM.for:350-356`）。

覆盖层与田面水先行蒸发（`SPAM.for:317-370`）：需求依次由 FLOOD（EF）→ MULCH（EM）→ 土壤（ES）满足，EVAP=ES+EM+EF。

## 4. 潜在蒸腾 EOP（TRANS.for:80-142）

```
FDINT = 1 − exp(−KTRANS·XHLAI)                    ! 冠层能量截获（能量消光，非 PAR）
MEEVP≠'H':  EOP = EO·FDINT
MEEVP='H':  EOP = Σ_h ET0(h)·FDINT·VPDFPHR(h)      ! 逐时 PT×VPD 函数
CO₂ 修正:   TRAT = TRATIO(CROP, CO2, TAVG, WINDSP, XHLAI)（:83）
            EOP_reduc = EOP·(1−TRAT)；EOP ×= TRAT   （:127-128，高 CO₂ 降蒸腾）
上限:       EOP ≤ EO − EOP_reduc − EVAP            （:138-139，腾发不超总需求）
KCB≥0（ASCE）: EOP = KCB·REFET（:96-97）
```

## 5. 潜在根系吸水 TRWUP（ROOTWU.for:66-123，Ritchie 模型）

对每层 RLV>1e-5 cm/cm³ 且 SW>LL：

```
q_L = SWCON1·exp(min(SWCON2(L)·(SW(L)−LL(L)), 40)) / (SWCON3 − ln(min(RLV(L), e^{SWCON3})))
     [cm³水/cm根/d]
SWCON1=1.32e-3（常数）；SWCON3=7.01（常数）
SWCON2(L) = 120 − 250·LL(L)（LL>0.30 时取 45）      ! 土壤"吸水难度"随下限升而降

渍涝（氧亏）约束:
    若 SAT−SW ≥ PORMIN（或 PORMIN≈0，淹水水稻）: TSS(L)=0
    否则 TSS(L)+=1；当 TSS>2 天: SWEXF=(SAT−SW)/PORMIN（截 [0,1]），否则 SWEXF=1
q_L ≤ RWUMX·SWEXF 且 ≤ RWUMX                        ! RWUMX=物种最大单根长吸水（!*ROOT）

RWU(L) = q_L·Δz(L)·RLV(L)   [cm/d]；TRWUP = Σ RWU(L)
```

**结构性质**：吸水速率随 (SW−LL) 指数饱和（SWCON2≈35–45 /cm³ 土壤分数）、随 RLV 对数饱和（根密集时单根效率递减）、线性于层厚；**无水势梯度/质流-扩散的显式动力学**；RWUMX 是物种上限闸门（典型 0.03 cm³/cm/d 量级，物种文件值）。

## 6. 实际吸水与蒸腾 EP（SPAM.for:392-398 + XTRACT，SPSUBS.for）

```
EP = min(EOP, TRWUP×10)                    ! cm→mm（SPAM.for:395）
XTRACT:  WUF = min(1, EP_cm/TRWUP)
         逐层: RWU(L)×WUF，且 ≤ SW_AVAIL(L)·Δz（可用水截顶）
         TRWU = Σ RWU；EP = TRWU×10（若层水不足 EP 再被压低）
         SWDELTX(L) = −RWU(L)/Δz（交给 WATBAL 积分）
```

即：需求不足时各层**等比例**压缩（与 NUPTAK 的 NUF 同构，见氮系列 02 篇对照）。

## 7. 逐时路径（MEEVP='Z' 或 MEPHO='L'，ETPHOT.for）

辐射传输逐时分区（hedgerow）求解光合与蒸散，同时内嵌水胁迫：

```
SWFAC = 1；若 EOP>0.01: SWFAC = TRWUP/(EOP×0.1)      （:666-670）
PG、PGCO2、LMXSLN、LMXSHN、PGNOON ×= SWFAC·PSTRES1    （:681-685）
R5 后: CUMSTR += DXR57·(1−SWFAC)·XPOD/PHTHRS10        （:691，与日路径同构）
```

## 8. 模型性质清单

1. "潜在—实际"两级结构贯穿：EO→EOS/EOP→ES/EP；TRWUP→TRWU；
2. 腾发分割用**同一消光系数框架**（KTRANS/KSEVAP）而非 Penman-Monteith 冠层阻抗（除 'D'/'S' 方法）；
3. 吸水是容量模型——干旱对吸水的抑制通过 (SW−LL) 的指数项一次性表达，无土壤-根-叶水势链，因此**无"非水力信号"（ABA 类）机制**；胁迫完全由 04 篇的供需比在后端定义；
4. CO₂ 对蒸腾的效应（TRATIO）使大气 CO₂ 抬升时 EOP 下降、SWFAC/TURFAC 缓解——氮系列中 CO₂ 只经 PRATIO 影响光合，两系列在此解耦。
