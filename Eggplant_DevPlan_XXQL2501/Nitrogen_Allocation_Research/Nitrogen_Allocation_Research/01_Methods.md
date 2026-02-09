# 方法与技术路线

## 研究设计
- 以 CROPGRO 主流程为骨架，定位氮相关子程序：DEMAND、NUPTAK、MOBIL、VEGGR、PODS
- 自上而下梳理：需求（NDMSD/NDMSDR）→ 供给（土壤吸收与动员）→ 胁迫因子（NSTRES/CNSTRES）→ 生殖分配（XFRT、果实与种子增长）

## 数据与实验文件
- /Users/lidaeus/Downloads/DSSAT_CSM_OS_REPORT/XXQL2501.TMA
- /Users/lidaeus/Downloads/DSSAT_CSM_OS_REPORT/XXQL2501.TMT
- /Users/lidaeus/Downloads/DSSAT_CSM_OS_REPORT/XXQL2501.TMX

## 代码定位
- DEMAND：计算种子/壳体生长需求与动员可用 N（NDMSDR）
- NUPTAK：以 (NDMTOT - NDMSDR) 为土壤氮吸收需求强度
- MOBIL：依据 NMINEP 与 WNR* 权重分配动员 N 至各器官
- VEGGR：计算氮胁迫因子 NSTRES 并影响根/叶/茎分配
- PODS：将 NSTRES 平滑为 CNSTRES 并作为壳体/种子氮限制项

## 变量与数据流
- 需求：NDMSD、GDMSD、CDMSD
- 动员：NMINEP、NDMSDR、GDMSDR、CDMSDR
- 胁迫：NSTRES（2 日均值）、CNSTRES（8 日均值）
- 分配：XFRT、PGAVLR、NLEFT、PGLEFT、壳体/种子增量

## 分析方法
- 代码级变量依赖图绘制，标注跨子程序的数据流与约束
- 基于非胁迫保护原则提出局部、条件性调节点

## 非胁迫保护原则
- 仅在生殖期（DAS>NR2）触发调节
- 仅在 NSTRES 低于阈值（如 <0.9）时生效
