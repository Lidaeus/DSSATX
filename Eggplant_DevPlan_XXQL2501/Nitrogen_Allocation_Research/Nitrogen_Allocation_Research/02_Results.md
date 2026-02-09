# 结果与机制分析

## 1. 氮胁迫的形成与传播
- 氮供给定义：SUPPN = NFIXN + TRNU + NMINEA，分别代表固氮、土壤吸收与组织动员
- NSTRES 计算逻辑：当 SUPPN < NSTFAC * NDMNEW 时，NSTRES = SUPPN / (NDMNEW * NSTFAC)，否则为 1.0
- NSTRES 时间平滑：XNSTRES 与 PNSTRES 进行 2 日加权平均，形成瞬时胁迫的缓冲响应
- CNSTRES 形成：PODS 中使用 8 日滑动平均 CNSTRES = 0.875 * CNSTRES + 0.125 * NSTRES
- 幂次惩罚：CNSTRES**0.5 进入壳体与种子 N 约束，放大低氮信号对果实生长的抑制

## 2. 果实氮需求与动员上限
- 种子氮需求：NDMSD = FNINSD * GDMSD
- 动员上限：NDMSDR = min(NDMSD, NMINEP)，将可动员 N 作为种子供给的硬上限
- 供需耦合：NUPTAK 中采用 ANDEM = (NDMTOT - NDMSDR) 作为土壤吸收需求强度
- 动员触发：当 NDMNEW - TRNU > 0 时，MOBIL 计算 NMINEA 并按 WNRLF/WNRST/WNRRT/WNRSH 分配

## 3. NLEFT/NAVL 对果实生长的边界效应
- NAVL 代表当日可用于生长的总氮，来源于 TRNU 与 NMINEA 的汇合
- NLEFT 为满足营养器官最小 N 需求后的剩余量，是进入壳体生长的实际上限
- PODS 中壳体增量受 NLEFT/(FNINSH*CNSTRES**0.5) 约束，形成 N 与胁迫的复合限制
- PGLEFT 与 NLEFT 同步消耗，形成碳-氮双重边界

## 3.1 番茄情景解释
- 生殖期窗口与果实快速增长阶段重叠，NSTRES 下降的影响会集中反映在果实端
- CNSTRES 的幂次惩罚在低氮条件下更显著，易导致壳体与种子增长同步受限
- 当 NDMSDR 被 NMINEP 上限压制时，土壤吸收需求同时下降，形成“低氮锁定”效应

## 4. 受氮胁迫影响的关键机制与参数
- NSTFAC：氮胁迫触发阈值，决定 SUPPN/NDMNEW 何时转入胁迫区
- XNSTRES/PNSTRES：NSTRES 的日尺度记忆项，决定胁迫响应的滞后性
- CNSTRES：生殖阶段的长记忆胁迫指标，直接参与幂次惩罚
- FRRT/FRLF/FRSTM：营养器官分配比例，受 NSTRES 与水分胁迫共同调节
- NDMSD/NDMSDR：种子氮需求与动员供给上限，是果实端 N 约束的核心
- NMINEP/NMINEA：组织可动员 N 潜力与实际动员量，控制胁迫下的缓冲能力
- NLEFT/PGLEFT：生殖生长可用 N 与 C 的边界变量，决定壳体与种子增量

## 5. 低氮条件下果实氮分配的关键调节点
- NDMSDR 上限策略：在低 NSTRES、生殖期提升动员优先级
- CNSTRES 指数策略：缓和低 NSTRES 下的幂次惩罚
- 动员权重策略：提高 WNRSH 比例以强化果实端缓冲

## 6. 风险与稳定性
- NDMSDR 过高会压低土壤吸收需求，引发土壤 N 估计偏差
- CNSTRES 过度缓和可能造成非胁迫期果实过快膨大
- 建议以阈值触发与阶段限定保证基线行为不变
