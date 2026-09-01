# 04 · 氮胁迫机制核心：NSTRES 的定义、平滑与判读

系列：[README](README.md) · 上一篇：[03 需求与动员](03_n_demand_and_mobilization.zh-CN.md) · 下一篇：[05 植株内分配](05_n_partitioning_in_plant.zh-CN.md)

**代码基准**：v4.8.6.0，`Plant/CROPGRO/VEGGR.for:236-260`（主）、`PODS.for:410-416`（CNSTRES）

---

## 1. NSTRES 的计算（逐行剖析）

```fortran
! VEGGR.for:236-256（INTEGR 阶段，位于当日 NAVL 级联的末段）
SUPPN = NFIXN + TRNU + NMINEA            ! :238 当日氮总供给（固氮+吸收+动员）
NSTFAC = MIN(NSTFAC,1.0); NSTFAC = MAX(NSTFAC,0.1)   ! :240-241 物种参数夹逼
PNSTRES = XNSTRES                         ! :246 昨日值
IF (SUPPN .LT. NSTFAC*NDMNEW .AND. NDMNEW .GT. 0.
     &  .AND. YRDOY .NE. YREMRG) THEN
    XNSTRES = MIN(1.0, SUPPN/(NDMNEW * NSTFAC))      ! :250
ELSE
    XNSTRES = 1.0                                     ! :252
ENDIF
NSTRES = XNSTRES*0.5 + PNSTRES*0.5                    ! :256 二日等权滑动平均
```

数学表达：

```
X_t = min{ 1,  S_t / (θ·D_t)  }          当 S_t < θ·D_t 且 D_t > 0 且非出苗日；否则 = 1
NSTRES_t = ½·X_t + ½·X_{t−1}

S_t = TRNU + NMINEA + NFIXN   （当日总供给）
D_t = NDMNEW                  （新组织生长需氮：NDMREP + NDMVEG，见 03 篇）
θ = NSTFAC                    （物种文件 !*CARB 段第 3 行，VEGGR.for:141 读取；夹逼于 [0.1, 1.0]）
```

## 2. 语义解读——与 CERES 浓度型因子的本质区别

| | CROPGRO（v4.8.6.0） | CERES 类模板 |
|---|---|---|
| 因子 | NSTRES = 供给/需求比 | NFAC = (TANC−TMNC)/(TCNC−TMNC)，浓度型 |
| 含义 | "今天凑不够明天的氮吗" | "植株氮浓度离临界多远" |
| 驱动变量 | TRNU、NMINEA、NDMNEW（流量） | TANC（存量浓度） |
| 时间响应 | 1 日滞后 + 2 日平滑，对突变敏感 | 随生物量稀释缓慢变化 |
| 阈值 | NSTFAC（默认语义 0.70）：供给 ≥ 70% 需求即无胁迫 | 无（线性归一） |

源码注释（`VEGGR.for:239` "KJB - Replacing a hardwire 0.70 for N-Stress"、`:244` 被注释的旧式 `SUPPN .LT. 0.70*NDMNEW`）表明：**历史上胁迫触发线是硬编码 0.70，后被参数化为 NSTFAC**。因此 NSTFAC=0.7 时，只有当总供给不足"新生长需求的 70%"才开始计胁迫，且胁迫强度按缺口比例线性放大。

**"总供给"的三项组成**值得注意：吸收（TRNU）+ 动员（NMINEA）+ 固氮（NFIXN）。所以：

- 营养生长后期 WNRLF 库大、动员强时，即使土壤无氮 NSTRES 也不降——**靠动员维生的日子被判定为"无胁迫"**，尽管叶片氮浓度正在被稀释、衰老在加速（RNITP 下降走 AGEFAC 路径）；
- 这解释了为什么 CROPGRO 的氮胁迫响应存在"缓冲期"（动员库耗竭前）与"陡降期"（库耗竭后供给断崖）。

## 3. 平滑与门控细节

1. **2 日等权滑动平均**（`:256`）：等价于一阶滞后滤波，避免单日吸收波动造成分配/SLA 震荡；
2. **出苗日豁免**（`:242-243,249` YRDOY≠YREMRG）：出苗当日种子氮 SDNPL 尚未计入供给体系，防止伪胁迫（源码注释 CHP）；
3. **NDMNEW > 0 守卫**：无生长需求（如满载后营养生长停滞）时恒为 1；
4. NSTRES 在 **VEGGR 出口**才更新，而 VEGGR 位于当日级联末段（`CROPGRO.for:1154`）——所以当日的 FRRT/SLA 用的是**昨日** NSTRES，PODS 当日的 CNSTRES 混入的也是昨日 NSTRES（见 §4）。

## 4. PODS 中的 8 日慢速版本 CNSTRES（`PODS.for:410-416`）

```fortran
CNSTRES = 0.875*CNSTRES + 0.125*NSTRES    ! 8 日指数滑动平均（时间常数约 7 天）
CPSTRES = 0.875*CPSTRES + 0.125*PStres2   ! 磷对应物（未启用，:416 注释）
```

- 生殖器官（荚壳生长目标氮浓度、花添加）用的是这个**慢变量**——源码注释 "Slow response to change in N stress"；
- 使用处以 √CNSTRES 进入（`PODS.for:600,631,635,757,777,780`），即中等胁迫时响应被钝化（凸变换），细节见 06 篇 §5。

## 5. NSTRES 的全部下游使用点（v4.8.6.0 全量清单）

| 使用点 | 变量路径 | 文件:行 | 效果 |
|---|---|---|---|
| 根分配 | FRRT = ATOP·(1−min(TURFAC,NSTRES,PStres2))·(1−FRRT)+FRRT | VEGGR.for:259-260 | 胁迫→根占比升高 |
| SLA（比叶面积） | NFSL = max(0.1, 1−(1−NSTRES)·NSLA)；CUMNSF=0.75CUMNSF+0.25NFSL | DEMAND.for:560-564 | 胁迫→叶片变薄（SLA 升） |
| 冠层高/宽 | HNHGT = max(0.1, 1−(1−NSTRES)·NHGT)；CUMNHT=0.75CUMNHT+0.25HNHGT | CANOPY.for:223-224 | 胁迫→株高生长受抑 |
| 荚壳目标氮浓度 | FNINSH×CNSTRES^0.5 | PODS.for:599-600,631,635 | 胁迫→荚壳允许更"贫氮"地生长 |
| 花添加 | ×min(SWADD1,SWADD2,CNSTRES^0.5) | PODS.for:776-780 | 胁迫→花数减少 |
| 籽粒成分兜底 | （通过 PODCOMP 的 NAVL 路径间接） | PODS.for:1003-1214 | 见 06 篇 §6 |
| R5 后动员加速 | NMOBR ×(1+0.3(1−NSTRES)) | DEMAND.for:246-249 | 胁迫→动员更快（正反馈） |
| 物候 | FNSTR(J)=1+(1−NSTRES)·NSENP(J)，与 FSW/FPSTR 取 min 乘入光温速率 PROG=FT·FUDAY·MIN(...) | PHENOL.for:248-250；RStages.for:204,237 | 按生态型逐期敏感度 NSENP∈[−1,1] 提前(+)或延迟(−)发育；NSENP=0 时无效应 |
| 棉花棉绒 | NSFLT（ cotton 专用） | LTGROW.for | 不适用于番茄 |

**明确不受 NSTRES 影响的**：光合 PG（走 RNITP/AGEFAC 浓度路径，`PHOTO.for:132`）、繁殖分配比 XFRT（只受温度/水分，`DEMAND.for:428-450`）。物候受 NSTRES 影响的强度由生态型文件逐期参数 NSENP 决定（NSENP=0 时等同无耦合）。

## 6. 数值行为示例（帮助校准判读）

设 NSTFAC=0.7，某日 NDMNEW=2.0 g/m²：

| TRNU+NMINEA+NFIXN | X_t | 说明 |
|---|---|---|
| 2.0（≥1.4） | 1.0 | 供给 ≥70% 需求 → 无胁迫 |
| 1.4 | 1.0 | 恰在触发线上 |
| 1.05 | 1.05/1.4 = 0.75 | 胁迫 25% |
| 0.35 | 0.25 | 重度胁迫 |
| 0 | 0 | 但经 2 日平均后 NSTRES 最多降到 0.5·X_t |

配合平滑：即使供给归零，NSTRES 第一日也只降到 0.5×X_t+0.5×1——**分配类响应的启动至少滞后 2-3 天**；而 PODS 的 CNSTRES（8 日平均）意味着**花荚减少的响应滞后约 1 周**。这是解释氮肥处理间产量差异时间动态时的重要结构特征。

## 7. 分析与标定提示

1. NSTFAC 是氮响应曲线形状的一阶控制参数：调大（→1）胁迫更早触发、更陡；调小（→0.5）缓冲更强；
2. NSLA（SLA 敏感度）、NHGT（株高敏感度）、ATOP（根分配幅度）、SENRTE（动员致衰速率）分别控制各下游通道的增益——它们与 NSTFAC 共同决定产量对氮的弹性；
3. 输出核查：`PlantGrow.out`/`Summary.out` 无 NSTRES 直接列，可用 `Work.out`（若编译启用）或在 Opgrow.for 加输出；OVERVIEW.OUT 不含胁迫序列。
