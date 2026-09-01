# 05 · 植株内氮分配：NAVL 级联、三浓度生长与储备库

系列：[README](README.md) · 上一篇：[04 胁迫因子](04_n_stress_factor.zh-CN.md) · 下一篇：[06 生理作用点](06_n_effects_on_physiology.zh-CN.md)

**代码基准**：v4.8.6.0，`CROPGRO.for:962-1174`（级联）、`VEGGR.for:284-459`（营养生长氮逻辑）、`GROW.for:740-1019`（状态积分）

---

## 1. NAVL 的日内级联（完整次序）

NAVL（available N）按固定次序流经各"汇"，任一汇只见到上游剩余量：

```
① 种子残留   NAVL = SDNPL×DTX/7                                (CROPGRO.for:962-968)
② 根系吸收   NAVL += TRNU（碳代价 RSPNO3/RSPNH4 已从 PGAVL 扣） (975-994)
③ 氮动员     NAVL += NMINEA（碳代价 NMINEA/0.16×RPRO 从 PGAVL 扣）(999-1027)
④ 固氮       NAVL += NFIXN（碳代价 CNOD=RFIXN×NFIXN/0.16）      (1065-1092；番茄=0)
⑤ 籽粒/荚壳  NAVL −= NGRSD + NGRSH（PODS 内按 min(C比, N比) 定量）(1096-1141)
⑥ 茎叶根新组织 NAVL −= NGRLF + NGRST + NGRRT（VEGGR 三浓度逻辑）  (1154-1172)
⑦ 氮储备沉积 NAVL −= NADLF + NADST + NADRT（超出 NDMOLD 的余氮入库，泄漏 NLEAK）(441-459,1173)
```

顺序语义：**繁殖库先于营养库**（⑤ 在 ⑥ 前）、**生长先于储备**（⑥ 在 ⑦ 前）、吸收/动员/固氮是并联源（② ③ ④）。

## 2. 繁殖器官的氮定量（PODS，简述，详见 06 篇 §5-6）

- 籽粒：NGRSD = ANINSD × RSD × min(SDGR·SDNO, SDMAX)，其中 RSD = min(CRSD, NRSD, 1)，NRSD = NAVL/(FNINSD×min(PGAVLR/AGRSD1, GDMSD))——**当日 NAVL 与 PGAVLR 的双约束**；
- 荚壳：目标氮浓度随胁迫下调——NGRSH = ADDSHL×PROSHI×0.16×CNSTRES^0.5，且 ADDSHL ≤ NLEFT/(FNINSH×CNSTRES^0.5)（`PODS.for:599-635`）。

## 3. 营养器官的三浓度生长逻辑（VEGGR.for:284-369）

营养生长速率 VGRDEM = PGAVL/AGRVG 先按碳定出**潜在**组织增量 WLDOTN/WSDOTN/WRDOTN，随后按氮可用量 NAVL 校正：

```
最大需氮:  NGRVEG = WLDOTN·FNINL + WSDOTN·FNINS + WRDOTN·FNINR      (:297-300)
最低需氮:  NGRVGG = WLDOTN·FNINLG + WSDOTN·FNINSG + WRDOTN·FNINRG  (:304-307)
```

三种情形：

### 情形 A：NAVL ≥ NGRVEG（氮充足）
组织按**最大浓度**生长，NGRLF/NGRST/NGRRT 按 FNINL 等执行，余氮进入 §4 储备。

### 情形 B：NGRVGG ≤ NAVL < NGRVEG（氮稀释生长）`(:333-342)`
```
生长速率不压缩，但各器官需氮按比例下调：
NGRLF = min(NAVL·NGRLF/NGRVEG, NGRLF)（茎、根同理）→ 新组织氮浓度介于最低与最大之间
```
随后 `:346-360` 反算新组织的实际蛋白分数 PROLFT = NGRLF×(100/16)/WLDOTN，并据此下调合成碳价 AGRVG（`:365-368`）——氮稀释生长的碳"折扣"。

### 情形 C：NAVL < NGRVGG（氮低于生存线）`(:310-332)`
```
NRATIO = NAVL/NGRVGG
WLDOTN、WSDOTN、WRDOTN 全部 ×NRATIO    ← 整体压缩组织生长
NGRLF 等 = 最低浓度 × 压缩后干重
AGRVG 按最低蛋白组成重算
```
即：**宁可少长，也不长出低于 PROLFF 下限的"空壳"组织**。这是 CROPGRO 氮限制生物量最直接的机制（比 NSTRES 的分配效应更硬）。

## 4. 剩余氮：储备沉积与"泄漏"（VEGGR.for:441-459）

```
NLEFT = max(0, NAVL − (NGRLF+NGRST+NGRRT))
IF NLEFT > NDMOLD:  NLEAK = NLEFT − NDMOLD；TNLEAK 累计   ← 溢出部分永久丢失
                     NLEFT −= NLEAK
NADRAT = NLEFT / (FRLF·FNINL + FRSTM·FNINS + FRRT·FNINR)
NADLF  = NADRAT·FRLF·FNINL   （NADST、NADRT 同理）         ← 按分配格局存入各器官氮储备
```

- 上限语义：储备沉积最多补到 NDMOLD（老组织回填需求，03 篇 §3），再多的氮**泄漏**（模拟奢侈吸收后随衰老/淋洗等损失的一阶近似）；
- NADLF 等在 GROW 中并入组织氮（受当日衰老损失折扣，`GROW.for:746-750`），从而抬高 PCNL/RNITP 与可动员库。

## 5. 状态积分与浓度反算（GROW.for:740-1019）

各器官氮量的净变化（以叶为例，`:746-750,828`）：

```
NLOFF = 衰老+虫害叶带走的氮（SLDOT 等按 PCNL 计，:736-740）
NLDOT = NGRLF − NLOFF − NRUSLF + NADLF·(1 − 当日损失率)
WTNLF += NLDOT        （茎 NSDOT、根 NRDOT、荚壳 NSHDOT、籽粒 NSDDOT 同构，:756-866）
```

随后反算浓度与可动员库（`:957-1019`）：

```
PCNL  = 100·WTNLF/WTLF                              ! 叶氮百分数（输出用）
RNITP = 100·WTNLF/(WTLF − WCRLF)（下限 PCNMIN）     ! 结构叶氮%——PHOTO 光合因子输入
WNRLF = max(WTNLF − PROLFF×0.16×(WTLF−WCRLF), 0)    ! 可动员氮库（茎根荚壳同理 WNRST/WNRRT/WNRSH）
```

闭环：WNRLF 决定次日 NMINEP 与 NRUSLF（03 篇 §4-5），RNITP 决定次日 AGEFAC（06 篇 §2），PCNL 决定次日 NDMOLD 与结荚的 RNITPD（06 篇 §5）。

## 6. 氮的合成碳代价（能量偶联）

不同氮源合成蛋白质的碳代价不同，按当日来源加权（`CROPGRO.for:1211-1216`）：

```
RPROAV = [(RSPNO3+RSPNH4)×0.16 + NFIXN×RFIXN + NMINEA×RPRO] / (TRNU+NFIXN+NMINEA)
```

RNO3C（硝酸盐还原）> RNH4C（铵同化）> RPRO（蛋白再合成）> RFIXN 视物种。RPROAV 进入 AGRSD2/AGRSH2/AGRVG2（`:1221-1225`），使"氮源结构"影响生长碳成本——例如硝态氮为主的植株同化代价高于铵态氮为主的。

## 7. 物质守恒恒等式（日尺度）

对植物总氮 WTNTOT = WTNLF+WTNST+WTNRT+WTNSH+WTNSD+WTNNOD（`GROW.for:871`）：

```
ΔWTNTOT = TRNU + NFIXN + (SDNPL 释放) − (NLOFF+NSOFF+NROFF+NSHOFF+NSDOFF) − NLEAK
```

- 动员 NRUSxx 是**内部转移**（从器官 N 中减去、进入 NAVL 再回到新组织），净和为零；
- 溢出泄漏 NLEAK 与各"OFF"项是仅有的丢失通道（另有收获移除走 HRes_CGRO）；
- PlantNBal.for 期末核对这一恒等式（允许数值舍入差）。

## 8. 番茄场景的分布特征（要点）

- 全部氮源=吸收+动员+种子残留（无固氮）；
- 番茄为**无限生长+多穗采收**型（XFRT 低、生殖窗长），氮的"情形 B 稀释生长"阶段长，PCNL 缓慢下滑直至触发情形 C 与动员致衰——这是氮响应曲线后段弯折的植株内成因。
