# 02 · 土壤水运移：tipping-bucket 的数学模型

系列：[README](README.md) · 上一篇：[01 架构与序列](01_architecture_and_daily_sequence.zh-CN.md) · 下一篇：[03 蒸散与根系吸水](03_et_demand_and_root_uptake.zh-CN.md)

**代码基准**：v4.8.6.0，`Soil/SoilWater/`（WATBAL.for、WBSUBS.for、RNOFF.for、INFIL.for、SATFLO.for）

---

## 1. 模型性质

DSSAT 默认土壤水动态是**容量型（capacity-based）tipping-bucket**逐日模型：

- 每层有三个特征含水量：LL（下限）、DUL（田间持水/排水上限）、SAT（饱和）；参数来自 .SOL 文件并经 LMATCH 映射到内部网格（见土壤篇）；
- 重力排水用整剖面一个速率系数 **SWCON**（.SOL 的 SLDR，1/d），层内饱和导水率 SWCN（SSKS，cm/hr）作为单日排水上限；
- **无 Richards 方程、非饱和导水率与水势梯度不显式出现**（除毛管上升一个扩散率近似，§5）；
- 时间步为 1 天，层内同质。

## 2. 产流：RNOFF（SCS-CN 变体，`RNOFF.for:72-116`）

```
SMX  = 254·(100/CN − 1)                       ! 蓄水容量参数（CN=.SOL 的 SLRO）
SWABI = 0.15·[(SAT₁−SW₁)/(SAT₁−0.5·LL₁) + (SAT₂−SW₂)/(SAT₂−0.5·LL₂)]   ! 前期湿度的顶两层代理
IABS = SWABI（无覆盖）；有覆盖时 IABS = SWABI + (0.6−SWABI)·MULCHCOVER
PB   = WATAVL − IABS·SMX                      ! 初损扣除后的有效雨量
RUNOFF = PB²/(WATAVL + (1−IABS)·SMX)          ! 当 PB>0，否则 0
```

- 初损比率 IABS 随表层变干而增大（SWABI 最大 0.30），覆盖最多抬到 0.6；
- 塑料膜比例 PMFRACTION>0 时：RUNOFF = WATAVL·PMFRACTION + RUNOFF·(1−PMFRACTION)（`:113-116`）；
- 水田（BUNDED）直接 RUNOFF=0（`WATBAL.for:350-353`）。

净入渗潜力：`WINF = WATAVL − RUNOFF + IRRAMT`；`PINF = WINF×0.1`（cm）（`WATBAL.for:371-375`）。

## 3. 有雨/灌溉日：INFIL（`INFIL.for:55-147`）

自上而下逐层执行（HOLD 为该层至 SAT 的剩余空间）：

```
若 PINF > HOLD（水超过该层饱和空间）:
    DRCM = SWCON·(SAT−DUL)·Δz        （第 1 层再乘 0.9——放湿表层的经验修正, :64-68）
    DRN(L) = PINF − HOLD + DRCM       ! 全层灌满至 SAT 并向下传递
    若 SWCN>0: DRN(L) ≤ SWCN×24       ! 单日导水上限（cm/d）
    层内 SW = SAT；超饱和部分 TMPEXCS 向上层回吐，最顶层的剩余 → EXCS → 计入径流
否则（水少于该层剩余空间）:
    SW += PINF/Δz
    若 SW ≥ DUL+0.003（导入的水使层超过 DUL）:
        DRCM = (SW−DUL)·SWCON·Δz（第 1 层×0.9）；DRN(L)=DRCM；SW −= DRCM
        （即：外加水最多把层抬到 DUL，以上的部分当天排走）
    否则 DRN(L)=0（干层把水全部扣留，PINI 归零停止下传）
PINF ← DRN(L)，进入下一层
DRAIN = 末层 DRN×10（mm）
```

**语义**：降水把各层依次填到 **DUL**（而非 SAT），超过 DUL 的水量当日按 SWCON 比例向下排；干层（SW<DUL）截留下渗水直到达到 DUL。

## 4. 无雨日：SATFLO 饱和再分配（`SATFLO.for:47-119`）

```
DRMX(L) = (SW(L)−DUL(L))·SWCON·Δz      ! 仅当 SW ≥ DUL+0.003
DRN(L)  = DRN(L−1) + DRMX(L) − HOLD(L)   ! HOLD=(DUL−SW)·Δz（干层的再吸纳容量, :66-70）
DRN(L) ≤ SWCN×24
自下而上校正：下层接收后不得超过 SAT，超过则削减上层来流（:86-106）
DRAIN = DRN(NLAYR)×10
```

即排水波逐层向下、干层重新吸水、饱和层回吐的级联。

## 5. 毛管上升：UP_FLOW（`WBSUBS.for` UP_FLOW 子程序）

表层变干时为蒸发补水（仅 MESEV≠'S' 路径）：

```
θ₁ = min(max(0,SW(L)−LL(L)), ESW(L))；θ₂ 同理（下层 M=L+1）
DBAR = min(100, 0.88·exp(35.4·θ̄))                       ! 扩散率经验式（θ̄ 为两层厚度加权）
GRAD = (θ₂/ESW(M) − θ₁/ESW(L))·加权厚度组合               ! 相对饱和度梯度
UPFLOW(L) = DBAR·GRAD/((Δz_L+Δz_M)/2)
约束: 仅当上层 SW ≤ DUL 时向上流；不得超过给体层可用水 SW_AVAIL(M)；
      接收层不得超过 DUL/SAT
```

与 SOILEV 的两阶段蒸发（03 篇 §3）配合，构成"表层蒸发—毛管补水"的耦对。

## 6. 特殊路径（WATBAL.for）

| 路径 | 触发 | 数学要点 | 位置 |
|---|---|---|---|
| 积雪 | TMAX≤1°C 或 SNOW>0 | 融雪=min(TMAX+0.4·RAIN, SNOW) | WBSUBS.for:44-58 |
| 水田（BUNDED） | 水稻类 | RUNOFF=0；WINF=FLOOD+IRR+RAIN | WATBAL.for:350-353 |
| 泥浆化（PUDDLED） | 水稻整地 | 全剖面先灌到 SAT；日排限 PUDPERC | :317-341 |
| 暗管排水 | FILEX 配置 | TILEDRAIN 按暗管深度/间距参数抽取 | TILEDRAIN.for |
| 地下水/毛管补水 | 配置 WTDEP | WaterTable.f90 维护 ActWTD、netLatFlow | :293-299 |
| 耕作混拌 | 当日耕作 | 耕深内土壤水按 TILMIX% 均化 | :428-451 |

## 7. 积分与守恒

日积分（`WATBAL.for:200-215`）：

```
SW(L) ← SW(L) + SWDELTS(排水/入渗) + SWDELTU(蒸发/上升) + SWDELTX(根系吸水)
                + SWDELTT(暗管) + SWDELTL(耕作)
```

水量平衡（WBAL.for 期末核对）：

```
Δ(SW·Δz) = RAIN + IRR − RUNOFF − DRAIN − ES − EP − 暗管 ± 侧向/田面水 ± 雪
```

**与内部网格的耦合**：以上全部逐层量都定义在 MESOL=2 的 LYRSET2 内部网格上。土壤文件分层方式会改变 Δz 与 DUL/SAT 的层内分布，从而改变：SWCON 排水的层间再吸纳 HOLD、入渗的逐层截留、蒸发的顶层层厚（AWEV1 ∝ Δz₁）——因此**同一场雨在不同分层的土壤文件下产生的入渗/径流/蒸发分配不同**（与氮吸收的网格敏感性同理）。

## 8. 模型性质的诚实清单

1. 无非饱和达西流；干旱区的深层补水、湿润峰的解析形状不可表达；
2. SWCON 是整剖面单一参数，排水对层结构的依赖只通过 (SW−DUL)·Δz 表达；
3. 日步长：高强度短时降雨的入渗动力学（Horton 过程细节）被 CN 初损近似吸收；
4. SWCN 只作"日排水上限"，不做层间导水差；
5. 毛管上升是扩散率经验式（DBAR=0.88·e^{35.4θ̄}），仅服务蒸发补水，不参与根系供水（根系供水走 ROOTWU 的容量模型，03 篇）。
