# 05 · 水胁迫对生理活动的作用点全图

系列：[README](README.md) · 上一篇：[04 胁迫因子](04_water_stress_factors.zh-CN.md) · 下一篇：[06 数学总结](06_mathematical_summary.zh-CN.md)

**代码基准**：v4.8.6.0（`Plant/CROPGRO/`）

---

与氮不同，**水的作用点既有抑制也有促进**。每条通道给出输入（SWFAC 代谢型 / TURFAC 膨压型 / SWDF·SWEXF 层域型 / SWBAR 湿度域型）、数学形式与位置。

## 通道总览

| # | 过程 | 输入 | 数学形式（核心） | 位置 |
|---|---|---|---|---|
| 1 | 冠层光合 | SWFAC | PG ×= SWFAC（直接乘子） | PHOTO.for:195 |
| 2 | R5 后光合容量累积衰减 | SWFAC | CUMSTR+=DXR57(1−SWFAC)XPOD/PHTHRS10；PG×(1−0.3CUMSTR) | PHOTO.for:225 |
| 3 | 比叶面积 SLA | TURFAC | TURFSL=max(0.1,1−(1−TURFAC)·TURSLA) | DEMAND.for:556 |
| 4 | 株高/株宽 | TURFAC | RCANHT ×= TURFAC | CANOPY.for:229 |
| 5 | 出叶/节数（VSTAGE） | TURFAC | VSTAGE += DTX·TRIFOL·EVMOD·TURFAC·(1−XPOD) | PHENOL.for:469 |
| 6 | 物候期进程 | SWFAC | FSW(J)=1+(1−SWFAC)·WSENP(J)，min 后乘 FT·FUDAY | PHENOL.for:248；RStages.for:204 |
| 7 | 根冠分配 | TURFAC | FRRT += ATOP·(1−min(TURFAC,NSTRES,PStres2))·(1−FRRT) | VEGGR.for:259-260 |
| 8 | 旱后叶分配补偿（记忆） | TURFAC | CUMTUR=0.95CUMTUR+0.05TURFAC；FRLF∝(1+0.6(1−CUMTUR)) | VEGGR.for:267-274 |
| 9 | 繁殖分配比 | TURFAC | TURXFR=XFRMAX(1−TURFAC)→XFRT | DEMAND.for:428-447 |
| 10 | 单粒/荚壳生长速率（促进） | TURFAC | TURADD=TABEX(YTRFAC,XTRFAC,TURFAC)；SDGR、GRRAT1 ×(1+TURADD) | DEMAND.for:305-310,377 |
| 11 | 花荚添加 | SWBAR、SWFAC | SWADD1(SWBAR 表)、SWADD2(SWFAC 表)；FLADD/PODADD ∝ min(...) | PODS.for:559-583,740-754 |
| 12 | 满载信号 ACCAGE | SWFAC | ACCAGE += TEMPOD·DRPP·SWFAC/MNESPM | PODS.for:741-743 |
| 13 | 水分胁迫致衰 | SWFAC(5日前) | WSLOSS=SENDAY(1−RATTP)WTLF，RATTP=滞后5日的SWFAC | SENES.for:169-227 |
| 14 | 根系分布/深扎/死亡 | SWDF、SWEXF、SWFAC | RLDF∝min(SWDF,SWEXF)；RTDEP 深扎加速；RTSURV 死亡 | ROOTS.for:203-270 |

## §1 光合（唯一直接乘 SWFAC 的碳路径）

```
PG = PTSMAX·SLPF·PGFAC·TPGFAC·E_FAC·PGSLW·PRATIO·PGLFMX·SWFAC     (PHOTO.for:194-195)
R5 后: PG ×= (1 − 0.3·CUMSTR)，CUMSTR += DXR57·(1−SWFAC)·XPOD/PHTHRS10  (:225)
```

CUMSTR 是**灌浆期胁迫的不可逆记账**（源码注释：最大约 0.2856→PG 最多再降 8.6%），叠加在当日 SWFAC 之上——解释了花期后连旱对产量的超比例伤害。

## §2 形态建成（全部走 TURFAC）

- **SLA**（DEMAND.for:555-571）：TURFSL=max(0.1,1−(1−TURFAC)·TURSLA) 乘入 F（新叶比叶面积）→ 缺水叶变厚（SLA 降），单叶变小但致密；
- **株高**（CANOPY.for:223-230）：RCANHT ∝ TURFAC·HPAR·HWTEM·CUMNHT（氮因子 HNHGT 另乘）；
- **出叶速率**（PHENOL.for:469）：节数增长乘 TURFAC → VSTAGE 滞后 → 所有 VSTAGE 驱动的表（分配 FRLF/FRSTM、株高表、叶面积）整体推迟。

## §3 分配：三条促/抑交织的通道

1. **根冠比**（VEGGR.for:259-260）：胁迫日根占比抬升 ATOP 幅度；水/氮/磷取 min——最严胁迫主导；解除后按 V-STAGE 分配表回落；
2. **CUMTUR 记忆**（:261-281）：CUMTUR=0.95·CUMTUR+0.05·TURFAC（~20 日滑动平均，源码注释）；叶分配 FRLF ∝ (1+0.6(1−CUMTUR))（上限 0.90(1−FRRT)）——**旱后复水把碳水化合物优先补叶**（重建冠层），是产量恢复弹性的来源之一；
3. **繁殖分配**（DEMAND.for:424-450）：TURXFR=XFRMAX·(1−TURFAC)（截 [0,1]）；XFRT=XFRUIT·TEMXFR+XFRUIT·TURXFR——**干旱把同化物推向果实**（繁殖优先），与根分配提升同时存在：有限 PG 中"根+果"两头挤茎叶。

## §4 生殖库：抑制与促进并存

- **单粒灌浆与荚壳生长反而加速**（DEMAND.for:305-310,377；PODS.for:524）：TURADD=TABEX(YTRFAC,XTRFAC,TURFAC,4)——轻度胁迫 TURADD>1（SAU 等的试验依据），SDGR、GRRAT1、SDMAX 乘 (1+TURADD)。机理语义：轻度缺水时单位库强的填充加速（库端补偿）；
- **花荚添加受抑**（PODS.for:559-583）：SWBAR=0–DSWBAR 深度（物种参数）内加权 (SW−LL)/(DUL−LL)；SWADD1=TABEX(YSWBAR 表, SWBAR)（土壤水视角）、SWADD2=TABEX(YSWFAC 表, SWFAC)（植物胁迫视角，轻度胁迫可>1）；
  - 花脱落 AFLW=RFLWAB(1−TDUMX)(1−SWADD2)（:717）；
  - 新花 FLWADD ∝ min(SWADD1,SWADD2,CNSTRES^0.5)（:776-777）；
  - 新荚 PODADD ∝ min(SWADD1,SWADD2,RNITPD)·max(1−ACCAGE,0)（:753-754）；
  - 荚壳生长供给比 SUPDAY ≤ SWADD1（:601-612）；
- **满载信号**（:741-743）：ACCAGE += TEMPOD·DRPP·SWFAC/MNESPM——SWFAC 低时 ACCAGE 累积变慢（灌浆不满载），配合 NDSET/TRIGGR 决定何时停止结荚。

## §5 衰老：五日滞后的胁迫记账（SENES.for:169-227）

```
SWFCAB(1) = 今日 SWFAC；SWFCAB(2..5) 逐日后移；RATTP = SWFCAB(NSWAB=5)   ! 5 日前的 SWFAC
WSLOSS = SENDAY·(1−RATTP)·WTLF，且 ≤ WTLF−CLW·PORLFT（SENMAX 表保留下限）
SLDOT += WSLOSS；SSDOT = SLDOT·PORPT（叶柄按比例）
```

胁迫致衰以**5 日前**的 SWFAC 驱动（连续 5 天干旱才开始掉叶），并受 SENMAX-VSTAGE 表的"保叶下限"约束。

## §6 根系：干与渍的双向塑造（ROOTS.for:200-270）

```
SWDF(L)  = min(1, (SW(L)−LL(L))/(0.25·(DUL(L)−LL(L))))     ! 干：可提水<25%ESW 时线性降
SWEXF(L) = min(1, (SAT(L)−SW(L))/PORMIN)                    ! 渍：氧亏
RTSURV(L) = min(1, 1−RTSDF·(1−SWDF), 1−RTEXF·(1−SWEXF))     ! 根存活（死亡=1−RTSURV）
RLDF(L) = WR(L)·Δz·min(SWDF,SWEXF)                          ! 新根长度分布权重
RTDEP += DTX·RFAC2(VSTAGE)·min(SWDF,SWEXF)·(1+0.25·(1−max(SWFAC,0.40)))   ! 深扎
```

- 已达根深以下：剖面性干旱（SWFAC<1）把深扎速率最多提高 25%（源码注释：约 12–13% @SWFAC=0.5）；根尖所在层的干/渍则拖慢深扎；
- 干（RTSDF）与渍（RTEXF）都直接杀根（RLV_WS），渍涝死亡有 ROOTWU 的 2 天延迟呼应；
- 根系响应是水分胁迫唯一的"主动适应"通道：更深更多根→次日 TRWUP↑→SWFAC 回升。

## §7 间接耦合（跨系列）

- **水→氮**：NUPTAK 的 SMDFR（氮系列 02 篇 §3.2）随干旱/过湿压低氮吸收；NMOBR 的 R5 后动员随 (1−SWFAC) 加速 50%（氮系列 03 篇 §4）；
- **水→磷**：PStres 与水胁迫在 FRRT、E_FAC 处同为 min 关系；
- **豆科**：NFIX 的 SWMEM8（8 日水分记忆）限固氮（番茄不适用）。

## §8 时间尺度谱（水分响应滞后总表）

| 通道 | 变量 | 滞后/记忆 |
|---|---|---|
| 光合、SLA、株高、出叶、分配、根深加速 | SWFAC/TURFAC | 0 日（当日） |
| R5 后光合容量衰减 | CUMSTR | 累积、不可逆 |
| 满载信号 ACCAGE | SWFAC | 渐进（积分量） |
| 胁迫致衰 | RATTP（5 日前 SWFAC） | 5 日 |
| 旱后叶分配补偿 | CUMTUR | ~20 日 |
| 根系适应→供水恢复 | RLV→TRWUP | 1 日起、渐进 |
| 花荚损失 | SWADD/ACCAGE/NDSET | 窗口关闭后不可逆 |
