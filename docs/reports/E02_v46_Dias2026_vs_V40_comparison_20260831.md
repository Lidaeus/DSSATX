# E02 v46 Dias 2026 方案与 v40 及早期版本对比审计（2026-08-31）

## 结论摘要

两个“效果很好”的目录确实显示出明显的产量尺度改善，但它们不是独立的 PEST++-IES 正式率定结果，而是以 v46 best71 为锚点的确定性网格重放。因而可以确认“哪些改动伴随改善”，但不能把全部改善归因于某一个氮参数或论文灵感。

最可靠的结论是：

1. **锚点/候选选择和数据事件口径是最大影响因素。** v40 的 best125 是候选审计中 `gate_pass=False` 的回退选择；v46 best71 使用了新的 Step-20 初始条件方案，并统一为 25SP 9 个真实采收事件。v40 的 25SP 还包含第 10 个额外事件（n=100，而 v46/Dias 为 n=90），所以不能直接用原始 Phi 或 25SP 产量指标作严格因果比较。
2. **XFRT（源库分配）是两个网格中最强的产量尺度驱动。** 早期放宽试验中 XFRT=0.85/0.88/0.91 的平均自定义 Phi 为 508.75/543.41/599.43；双氮试验为 520.56/578.46/654.85。最低 XFRT（0.85）几乎总是占据最优组合，说明主要改善来自源库/产量尺度，而不是初始氮翻倍本身。
3. **Dias 风格的 C–N 参数预设有机理合理性，并对 25SP 产量和部分氮误差有帮助，但证据仍是混杂的。** 早期放宽候选相对 v46 best71：25SP FRESH_CUM NSE 0.8246→0.9086、终产量 RRMSE 14.90%→9.88%，26SP 氮 MAE 下降约 9.4%；但 26SP FRESH_CUM NSE 0.9265→0.9069，LAI 也未改善。双氮候选相对同一锚点的双氮基线：25SP 产量改善很大，26SP 氮 MAE 仅下降约 3.8%。
4. **初始土壤矿质氮翻倍不应作为正式方案保留。** 固定参数下，双氮基线的氮 MAE 从正常基线的 3,560/3,499 增至 6,462/7,808（25SP/26SP），氮响应反而恶化；其最优结果主要由参数组合和 XFRT 驱动。

## 可复现实证产物

- 对比脚本：[compare_v46_dias2026_vs_v40_20260831.py](D:/Tomato_Cal/tools/analysis/compare_v46_dias2026_vs_v40_20260831.py)
- 长表指标：[metric_comparison_long.csv](D:/Tomato_Cal/workspace/reports/e02_v46_dias2026_vs_v40_20260831/metric_comparison_long.csv)
- 宽表及相对 v40 差值：[metric_comparison_wide.csv](D:/Tomato_Cal/workspace/reports/e02_v46_dias2026_vs_v40_20260831/metric_comparison_wide.csv)
- 参数差异：[parameter_comparison.csv](D:/Tomato_Cal/workspace/reports/e02_v46_dias2026_vs_v40_20260831/parameter_comparison.csv)
- 谱系/哈希审计：[lineage_audit.json](D:/Tomato_Cal/workspace/reports/e02_v46_dias2026_vs_v40_20260831/lineage_audit.json)

指标均直接读取各批次的 `metrics_by_season_variable.csv`；没有重新拼接观测或改变 NSE/RRMSE 定义。

## 1. 共同指标对比

| 批次/候选 | 25SP FRESH_CUM NSE / RRMSE | 26SP FRESH_CUM NSE / RRMSE | 25SP LAID NSE | 26SP LAID NSE | 备注 |
|---|---:|---:|---:|---:|---|
| v31 best187 | 0.808 / 23.47% | 0.679 / 32.14% | 0.815 | 0.420 | v40 之前的早期正式版本 |
| v38 best70 | 0.719 / 28.42% | 0.851 / 21.90% | 0.894 | 0.609 | Scheme-4 土壤版本 |
| v40 best125 | 0.823 / 22.58%* | 0.485 / 40.69% | 0.782 | -1.391 | 审计标记 gate_pass=False；25SP n=100* |
| v46 best71 | 0.825 / 22.82% | 0.927 / 15.37% | 0.472 | -2.465 | Step-20/custom26SP 锚点 |
| Dias early-relaxed | 0.909 / 16.48% | 0.907 / 17.30% | 0.618 | -2.655 | 163 行确定性网格，早期采收降权 |
| Dias double-N | 0.945 / 12.80% | 0.909 / 17.14% | 0.763 | -3.672 | 217 行确定性网格，初始 N 翻倍 |

这里的“早期/双氮”候选均使用 v46 统一的 25SP n=90、26SP n=60 产量事件；v40 的 25SP n=100 是重要的口径差异。v40 figure manifest 中记录的 `best_phi=541.634` 也未被正式 `.phi.actual.csv` 支持：该文件中第4轮 member125 的 Phi 为 1100.7，最低第4轮 Phi 为 member34 的 977.924。

## 2. 配置演进及影响归因

### 2.1 v40 → v46：锚点与初始条件先发生变化

两者仍使用同一 frozen bounds、同一 114 个激活参数、同一 200 realizations/4 rounds/6 agents、同一鲜重目标函数（终产量 RRMSE λ=750、N3−N0、W2−W1）。主要差异是：

- v46 使用 25SP Step-20（35%/40%/100%）和 26SP custom Step-20（35%/28%/50%），并使用深层低氮 1.0/0.5；
- v40 使用旧的校正硝酸盐/收获缩放方案；
- v40 的 best125 未通过候选硬门槛，却被 manifest 当作“最佳成员”。

因此，v40→v46 的 26SP 产量恢复（NSE 0.485→0.927）首先应解释为**锚点、输入和候选选择被纠正**，不能直接解释为 Dias 氮机理效果。

### 2.2 v46 → Dias early-relaxed：氮参数预设与收获权重同时改变

网格脚本将以下参数成组替换：

- 器官蛋白质水平：PROL*/PROST*/PRORT*/PROSH*；
- 氮响应/动员：NSTFAC、RTNH4、RTNO3、NMOBMX、NVSMOB、SENRTE；
- 叶氮—光合曲线：FNPGN1、FNPGN2、LNREF、NSLOPE；
- 源库耦合：XFRT；
- 自定义收获评分将 H1/H2 降权为 0.10/0.20。

网格主效应显示 XFRT 对自定义 Phi 的相关性约 0.97（报告中的汇总为约 0.966），明显大于 RTNO3、FNPGN1/2 或 LNREF。因此该候选的“Phi 很低”主要证明了源库尺度与早期事件权重的作用；氮参数的改善是次要且未达到项目原定 30% 氮误差门槛。

### 2.3 Dias double-N：输入改变与参数改变不可分离

固定 v46 锚点、只将初始 SNO3/SNH4 翻倍时，产量略有变化但氮 MAE 显著变差。再叠加参数网格后，25SP 产量 RRMSE 降到 5.26%，但 26SP 氮 MAE 仅从 7,808 降至 7,512（约 3.8%），而且 26SP LAI 进一步变差。该结果不支持把“初始氮翻倍”写入正式 bundle。

## 3. 是否是论文灵感起作用？

论文 *Modeling nitrogen effects on field-grown fresh-market tomato using the CROPGRO-Tomato model* 的公开摘要明确强调：用多环境、多氮水平的生长和氮积累数据校准 CROPGRO-Tomato，并通过器官氮状态、氮吸收/分配和产量响应共同约束模型（ScienceDirect：[论文页面](https://www.sciencedirect.com/science/article/pii/S030442382600292X)）。这与本项目采用器官蛋白质参数、氮需求—动员—光合响应联动的思路一致，因此可说它提供了**合理的机理假设和参数先验方向**。

但本批次没有更换 `TMGRO048.SPE` 或 DSSAT 可执行文件；两个 Dias 目录的 `.pst` 与 v46 正式 `.pst` 哈希相同，且源目录没有 `.phi.actual.csv`。所以目前不能声称论文模型“被移植并验证”或单独造成改善。严格表述应为：**论文启发了参数化和试验设计；已观察到的改善主要由 v46 锚点/输入口径、XFRT 源库参数及早期收获评分共同造成，论文启发的 C–N 参数贡献尚未通过消融试验识别。**

## 4. 建议的下一步验证

1. **不把两个“best_member_1”直接晋级为正式后验。** 它们是确定性网格最优行，不是独立 IES 集合成员。
2. **以 v46 best71、正常初始 N、统一 n=90/60 事件为唯一基线，做最小消融 IES：**
   - A：v46 基线；
   - B：仅 Dias C–N 参数预设（不改 XFRT、不改收获权重）；
   - C：仅 XFRT/源库参数；
   - D：仅早期 H1/H2 降权；
   - E：C+D；
   - F：C+XFRT+D。
3. 每臂使用相同 60–100 realizations、noptmax=3、6 agents；除本臂参数外全部固定 v46 best71。正式晋级同时检查：两季鲜重终产量 RRMSE、LAI、W_RESPONSE、N1/N2/N3 响应层和边界压力。
4. 论文中可保留 Dias 机理作为“参数先验与消融假设来源”，但只有当 B 相对 A 在相同目标和事件口径下重复改善，才能把它列为已验证的关键贡献。

