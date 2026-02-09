# 流程图与变量依赖图

## 1. 氮分配主流程图

```mermaid
flowchart TD
  A[DEMAND: 计算 NDMSD/NDMSDR] --> B[NUPTAK: 土壤吸收需求 ANDEM]
  A --> C[MOBIL: 组织动员 NMINEA]
  C --> D[NAVL: 可用 N 汇总]
  D --> E[VEGGR: NSTRES 计算与分配]
  E --> F[PODS: CNSTRES 约束果实生长]
  F --> G[果实增量与 NLEFT 更新]
```

## 2. 变量依赖图（关键变量）

```mermaid
flowchart LR
  NDMSD --> NDMSDR
  NMINEP --> NDMSDR
  NDMSDR --> ANDEM
  ANDEM --> TRNU
  TRNU --> SUPPN
  NMINEA --> SUPPN
  SUPPN --> NSTRES
  NSTRES --> CNSTRES
  CNSTRES --> NGRSH
  NAVL --> NLEFT
  NLEFT --> ADDSHL
  XFRT --> PGAVLR
  PGAVLR --> WSDDTN
  WSDDTN --> NGRSD
```

## 3. 低氮果实氮分配调节点示意

```mermaid
flowchart TD
  X[低 NSTRES 且生殖期] --> A1[提高 NDMSDR 上限]
  X --> A2[缓和 CNSTRES 幂次惩罚]
  X --> A3[提升 WNRSH 动员权重]
  A1 --> B1[提高动员 N 对种子覆盖]
  A2 --> B2[降低壳体 N 限制]
  A3 --> B3[增强果实端缓冲]
```

## 4. 分层机制框架图（论文概念图）

```mermaid
flowchart LR
  subgraph Supply[供给层]
    S1[TRNU 土壤吸收]
    S2[NMINEA 组织动员]
    S3[NFIXN 生物固氮]
  end
  subgraph Demand[需求层]
    D1[NDMNEW 新增组织需求]
    D2[NDMSD 种子需求]
    D3[NDMSH 壳体需求]
  end
  subgraph Stress[胁迫层]
    T1[NSTRES 日尺度胁迫]
    T2[CNSTRES 生殖期胁迫]
  end
  subgraph Allocation[分配层]
    A1[NLEFT 可用 N 边界]
    A2[FRLF/FRRT/FRSTM 营养分配]
  end
  subgraph Fruit[果实层]
    F1[ADDSHL 壳体增量]
    F2[NGRSD 种子 N 增量]
  end

  S1 --> T1
  S2 --> T1
  S3 --> T1
  D1 --> T1
  T1 --> T2
  T1 --> A2
  T2 --> F1
  A1 --> F1
  D2 --> F2
```

## 5. 生育期状态-阶段图（机制窗口）

```mermaid
stateDiagram-v2
  [*] --> 营养生长期
  营养生长期 --> 生殖前期: NR1
  生殖前期 --> 果实快速增长期: NR2
  果实快速增长期 --> 生殖后期: NR5
  生殖后期 --> 成熟期: NR7
  生殖前期 --> 生殖前期: NSTRES 平滑
  果实快速增长期 --> 果实快速增长期: CNSTRES 平滑
```

## 6. 论文用公式化表达（核心机制方程）

- 供给汇总

\[
SUPPN = NFIXN + TRNU + NMINEA
\]

- 氮胁迫形成与平滑

\[
NSTRES_t = \begin{cases}
\min\left(1, \frac{SUPPN}{NDMNEW \cdot NSTFAC}\right), & SUPPN < NDMNEW \cdot NSTFAC \\
1, & \text{otherwise}
\end{cases}
\]

\[
NSTRES_t = 0.5 \cdot NSTRES_t + 0.5 \cdot NSTRES_{t-1}
\]

\[
CNSTRES_t = 0.875 \cdot CNSTRES_{t-1} + 0.125 \cdot NSTRES_t
\]

- 果实氮需求与动员上限

\[
NDMSD = FNINSD \cdot GDMSD
\]

\[
NDMSDR = \min(NDMSD, NMINEP)
\]

\[
ANDEM = (NDMTOT - NDMSDR) \times 10
\]

- 壳体增长的氮约束

\[
ADDSHL \le \frac{NLEFT}{FNINSH \cdot CNSTRES^{0.5}}
\]

## 7. 机制-参数-观测对照矩阵（论文表格）

| 机制 | 关键变量 | 作用位置 | 论文可解释观测指标 |
|---|---|---|---|
| 氮胁迫形成 | SUPPN, NDMNEW, NSTFAC, NSTRES | VEGGR | 低氮处理下的生长速率下降 |
| 生殖期记忆 | CNSTRES | PODS | 果实增长期的持续抑制 |
| 动员上限 | NMINEP, NDMSDR | DEMAND | 低氮下种子 N 供给上限 |
| 土壤吸收反馈 | ANDEM, TRNU | NUPTAK | 吸收强度随动员上升而下降 |
| 果实 N 约束 | NLEFT, FNINSH, CNSTRES | PODS | 果实增长边界与延迟 |
| 组织分配响应 | FRLF, FRRT, FRSTM | VEGGR | 叶/根/茎分配比例变化 |

## 8. 机制逻辑树（因果路径表达）

```mermaid
mindmap
  root((氮胁迫机制))
    供给
      TRNU
      NMINEA
      NFIXN
    需求
      NDMNEW
      NDMSD
      NDMSH
    胁迫
      NSTRES
        平滑
      CNSTRES
        幂次惩罚
    果实
      NLEFT
      ADDSHL
      NGRSD
```

## 9. UML 表达（过程协作图）

```mermaid
sequenceDiagram
  participant DEMAND
  participant NUPTAK
  participant MOBIL
  participant VEGGR
  participant PODS

  DEMAND->>DEMAND: 计算 NDMSD/NDMSDR/NDMTOT
  DEMAND->>NUPTAK: 传递 NDMSDR 与 NDMTOT
  NUPTAK->>DEMAND: 返回 TRNU
  DEMAND->>MOBIL: 传递 NDMNEW 与 TRNU
  MOBIL->>DEMAND: 返回 NMINEA
  DEMAND->>VEGGR: 传递 SUPPN 与 NDMNEW
  VEGGR->>VEGGR: 计算 NSTRES 平滑
  VEGGR->>PODS: 传递 NSTRES 与 NLEFT
  PODS->>PODS: 计算 CNSTRES 并施加幂次约束
  PODS->>DEMAND: 更新果实增量与 N 消耗
```
