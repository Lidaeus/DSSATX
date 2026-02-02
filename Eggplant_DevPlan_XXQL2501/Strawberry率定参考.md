# Strawberry 率定参考（迁移到 Eggplant-on-Tomato 的可用结论）

参考论文：Sci. Hortic. (2021) 110538（CROPGRO-Strawberry from Tomato template）

## 1) 可迁移的核心率定逻辑

1. **版本迭代（Versioned calibration）优于一次性全参数联合**
   - 先把 Thermal time（温度响应/发育节奏）与冠层动力学对齐，再进入 multi-harvest 曲线与产量分配。
2. **当 multi-harvest 曲线出现“前期偏高、后期偏低（或反之）”结构偏差时**
   - 不要优先扩大常数分配参数集合；先判断是否需要引入随 Photothermal age（或 Thermal time）变化的动态分配机制。
3. **把管理效应显式化，而不是让遗传参数吸收管理噪声**
   - Strawberry 中的 transplant shock 属于结构项（管理/机制开关），其思路可迁移到“移栽苗龄大 + 前期去花/控果”等管理对茄子早期碳氮分配的影响。

## 2) 对本项目的直接启发（XXQL2501）

- 若在统一 `CUL/ECO/SPE` 下，某些处理（TN）长期与整体趋势相冲突：优先做“处理屏蔽实验”（替换 batch 文件）验证是否存在强 Genotype-by-environment interaction 或观测/管理不一致。
- 若要把 N uptake 作为机理入口：stage2 已默认启用 `RTNO3/RTNH4/RTEXF`；如需对照实验可用 `--no-include-n-uptake` 关闭，并用 RMSE、NRMSE、d-index 在 metrics grid 中量化是否真正改善（而非仅降低某一组的 bias）。

