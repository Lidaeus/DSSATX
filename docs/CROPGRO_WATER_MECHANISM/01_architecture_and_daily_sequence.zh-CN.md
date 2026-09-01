# 01 · 三模块架构与每日水分调用序列

系列：[README](README.md) · 下一篇：[02 土壤水运移](02_soil_water_movement.zh-CN.md)

**代码基准**：v4.8.6.0（`Soil/SoilWater/`、`SPAM/`、`Plant/CROPGRO/`）

---

## 1. 总体架构：谁负责什么

水分在 DSSAT-CSM 中由三个模块接力处理，植物模块（CROPGRO）把物种参数"借给"前两者：

```
┌─────────────────────────── Management（管理模块）───────────────────────────┐
│ 灌溉 IRRAMT、降雨 RAIN → 进入 WATBAL；秸秆覆盖 MULCH 状态                     │
└───────────────────────────────────────────────────────────────────────────┘
                    ▼
┌─────────────────── Soil/SoilWater/WATBAL（土壤水平衡，tipping-bucket）──────┐
│ 状态: SW(L)（内部土壤网格=MESOL=2 网格，见土壤篇）                           │
│ RATE: 雪/融雪 → 水表/毛管 → 覆盖截留 → 径流(RNOFF) → 入渗或饱和流(INFIL/SATFLO)│
│       → 暗管排水 → 毛管上升(UP_FLOW)                                        │
│ 输出: WINF（净入渗）、SWDELTS(排水)、SWDELTU(蒸发/上升)                       │
└───────────────────────────────────────────────────────────────────────────┘
                    ▼  SW、SWDELTS、SWDELTU、WINF
┌─────────────────────────── SPAM（土壤-植物-大气）──────────────────────────┐
│ 植物输入: RLV（昨日根长密度）、XHLAI/XLAI、CANHT、KTRANS=KEP、KSEVAP、       │
│           EORATIO、RWUMX、PORMIN（全部为物种参数，由 CROPGRO 导出）           │
│ RATE: 土温(STEMP) → 潜在吸水 ROOTWU(RWU, TRWUP) → 潜在蒸散 PET(EO)           │
│       → 潜在土面蒸发 PSE(EOS) → 实际土面蒸发 SOILEV(ES)（+覆盖/田面水）       │
│       → 潜在蒸腾 TRANS(EOP) → EP=min(EOP, TRWUP×10)                         │
│       → 实际吸水 XTRACT(RWU→SWDELTX, TRWU; EP 重算)                         │
│ 输出: EO/EOP/EOS/ES/EP、TRWUP（潜在供给）、TRWU（实际）、SWDELTX              │
└───────────────────────────────────────────────────────────────────────────┘
                    ▼  TRWUP、EOP
┌─────────────────────── Plant/CROPGRO（植物模块，本系列主角）────────────────┐
│ RATE: SWFAC/TURFAC = f(TRWUP, EOP, RWUEP1)   ← CROPGRO.for:684-702         │
│       PHENOL（FSW 物候、TURFAC 叶龄）、PHOTO（PG×SWFAC）…全部当日用当日因子  │
│ INTEGR: 生长/分配/衰老 → ROOTS 更新 RLV（供次日 SPAM 用）                     │
└───────────────────────────────────────────────────────────────────────────┘
                    ▼  RLV、XHLAI（次日）
```

**设计要点**：

1. **SPAM 不知道作物是谁**——它只接收 CROPGRO 导出的物种参数（KEP 蒸散消光、RWUMX 单位根长最大吸水、PORMIN 需氧孔隙下限、RWUEP1 扩张阈值、EORATIO）。作物差异全部通过这些参数表达；
2. **土壤供水能力（TRWUP）与作物需求（EOP）在 SPAM 会师**，但"胁迫有多严重"的判断（除法与阈值）由植物模块自己完成；
3. 反馈是**一日滞后**的：RLV/XLAI 用昨日值算今日吸水；今日生长改变明日的 RLV/XLAI。

## 2. 每日时间步内的模块内序列

### 2.1 WATBAL RATE（`WATBAL.for:276-454`）

| 步 | 调用 | 行号 | 说明 |
|---|---|---|---|
| 1 | SNOWFALL | 282-288 | TMAX≤1°C 或有积雪时：融雪 SNOMLT=min(TMAX+0.4·RAIN, SNOW)（`WBSUBS.for:44-58`）；否则 WATAVL=RAIN |
| 2 | WaterTable | 294-299 | 维护地下水位 ActWTD 与侧向流 netLatFlow（`WaterTable.f90`） |
| 3 | 覆盖截留 MULCHWATER | 360-365 | MEINF∈'RSM' 时覆盖层先吸水 |
| 4 | RNOFF | 367-369 | SCS-CN 型径流（无埂旱地）；水田(BUNDED)无径流；见 02 篇 §2 |
| 5 | INFIL 或 SATFLO | 380-402 | 有雨/灌日走 INFIL，无雨日走 SATFLO（见 02 篇 §3-4） |
| 6 | TILEDRAIN | 404-408 | 暗管排水（若配置） |
| 7 | UP_FLOW | 422-424 | 表层干燥时的毛管上升（MESEV='S' 除外），见 02 篇 §5 |
| 8 | 耕作混拌 | 430-451 | 当日耕作则混匀耕深内土壤水 |
| 9 | INTEGR | ~200-215 | SW(L) += SWDELTS+SWDELTU+SWDELTX+SWDELTT+SWDELTL（排水/蒸发上升/根系吸水/暗管/耕作五源汇） |

### 2.2 SPAM RATE（`SPAM.for:248-454`）

| 步 | 调用 | 行号 | 输出 |
|---|---|---|---|
| 1 | STEMP/STEMP_EPIC | 253-265 | 土温 ST（供吸水与物候用） |
| 2 | ROOTWU | 280-287 | 逐层潜在吸水 RWU(L)、总潜在 TRWUP（XHLAI>0 时） |
| 3 | PET | 300-305 | 潜在蒸散 EO（MEEVP 选法，默认 'R' Priestley-Taylor） |
| 4 | PSE | 314 | 潜在土面蒸发 EOS=EO×LAI 衰减函数 |
| 5 | FLOOD/MULCH/SOILEV | 317-370 | 依次由田面水、覆盖、土壤供应实际蒸发 ES（Ritchie 两阶段） |
| 6 | TRANS | 378-387 | 潜在蒸腾 EOP=EO·(1−e^(−KTRANS·XHLAI))·TRAT，截顶 ≤ EO−还原−EVAP |
| 7 | EP | 392-398 | **EP = min(EOP, TRWUP×10)**（cm→mm；旧 SWFACS 的替位计算） |
| 8 | XTRACT | 434-438 | 实际逐层吸水：WUF=min(1, EP_cm/TRWUP) 等比压缩 RWU 并受层可用水截顶；输出 SWDELTX、TRWU，并重算 EP=TRWU×10 |
| 9 | INTEGR | 460-472 | 累计 CET/CEP/CES 等 |

### 2.3 CROPGRO RATE（`CROPGRO.for:684-742`）

```fortran
SWFAC=1; TURFAC=1
EP1 = EOP*0.1                                  ! cm/d
IF (TRWUP/EP1 .LT. RWUEP1) TURFAC = (1./RWUEP1)*TRWUP/EP1   ! :695-696
IF (EP1 .GE. TRWUP)        SWFAC  = TRWUP/EP1                ! :698-699
→ 当日传入 PHENOL(:708)、PHOTO(:737) 等全部子程序
```

随后 INTEGR 阶段与氮系列 01 篇的日序列完全相同（PHENOL→DEMAND→NUPTAK→MOBIL→PODS→VEGGR→SENES→ROOTS→GROW），SWFAC/TURFAC/SATFAC 在其中各作用点见 05 篇。

## 3. 状态-速率闭环（水分视角）

```
ROOTS(昨日) ─RLV─► ROOTWU ─TRWUP─┐
                                 ├─► SWFAC/TURFAC(当日,植物) ─► 当日全部生理过程
PET ─EO─► TRANS ─EOP────────────┘            │
                                             ▼
XTRACT: SWDELTX（逐层实际吸水）─► WATBAL INTEGR: SW(L) 更新 ─► 次日 ROOTWU/SOILEV/...
                                             │
GROW/ROOTS: 新 RLV、XLAI ────────────────────┘（次日 SPAM 输入）
```

滞后结构：RLV/XLAI 一日滞后（供给侧）、SWFAC/TURFAC 无滞后（当日内闭环）、CUMTUR/ACCAGE 等形态记忆 20 日/渐进（05 篇）。

## 4. 番茄（CROPGRO-Tomato）语境

- 物种文件提供 KEP/EORATIO（!*EVAP 段，`IPPLNT.for:328`）、RWUEP1/RWUMX（!*ROOT 段第 1 行，`IPPLNT.for:291`）、PORMIN（!*ROOT 段第 4 行，`:297`）；KTRANS=KEP（`CROPGRO.for:246`）、KSEVAP 默认 −99（用旧法，`:247`）；
- 番茄通常起垄/设施栽培，若 FILEX 用 MESEV='S'（Sulieman-Ritchie 蒸发）则 UP_FLOW 不调用、蒸发走 ESR_SoilEvap（逐层 ES_LYR + UPFLOW 由该程序自算，`SPAM.for:352-356`）；
- 无田面水（非水稻）、无 puddled 分支；暗管/地下水位按管理配置启用。
