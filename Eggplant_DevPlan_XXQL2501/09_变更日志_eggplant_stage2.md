# 09 变更日志（Eggplant Stage2 / XXQL2501）

本文件用于固化 `c:\DSSAT48\Tomato_Cal\Workspace` 中围绕 **Eggplant stage2（联合优化）** 的工程演进过程，重点记录 v6–v10 的 changelog、关键决策与可复现命令。

约定：

- “版本 vX” 对应 `Workspace` 下的 `eggplant_stage2_vX.*` 文件族（`.pst/.rec/.log/.par.csv/.obs.csv/...`）。
- “stage2” 指 `build_pest.py --mode eggplant_stage2` 构建的**多输出联合率定**：`PestEval.OUT` + `PestJoint.OUT` + `PestHarvest.OUT` + `PestTmtGrow.OUT`。

---

## v6（基线：stage2 早期版本）

**目的**

- 提供对照基线，暴露“多次采收拟合不足/权重不合理/鲜重链路不完整”等问题。

**输出/结果**

- 指标汇总（来自后续统一脚本）：`Calibration_Results/eggplant_stage2_v6_v10_harvest_metrics.csv`。

---

## v7（稳定性改进：权重与观测构建迭代）

**目的**

- 改善基线的不稳定拟合与异常权重影响，形成可用的 stage2 中间版本。

**输出/结果**

- 相比 v6，误差有明显改善（以干重累计 MAPE 为例：v6 `97.737%` → v7 `56.615%`，见 `Calibration_Results/eggplant_stage2_v6_v10_harvest_metrics.csv`）。

---

## v8（引入 CHFPW：把鲜重累计收获纳入率定目标）

**动机**

- 现场数据包含鲜重口径；仅用干重口径容易出现“收获曲线结构性偏差/欠拟合”。

**关键变更**

- `build_pest.py` 的 `--harvest-var` 用于决定 `eggplant_stage2/eggplant_harvest` 观测构建使用：
  - `CHPDT`：干重累计
  - `CHFPW`：鲜重累计
- 关键逻辑：`Tomato_Cal/Workspace/build_pest.py:1274`。

**可复现命令（示例）**

- 构建（以 v10 参数为例；v8 仅前缀不同）：
  - `python build_pest.py --mode eggplant_stage2 --prefix eggplant_stage2_v8 --batch DSSBatch.v48 --harvest-var CHFPW --param-review-mode off`

---

## v9（修复 harvest-var 传递 + 提升 XFRT 上限到 0.99）

**动机**

- `--harvest-var CHFPW` 需贯穿“PEST 构建 → DSSAT 前向运行 → PestHarvest.OUT 写出”的全链路。
- 你明确指出参数名应为 `XFRT` 且上限应提高到 `0.99`（必要时更高）。

**关键变更**

1) 修复 `run_dssat.py` 未将 `--harvest-var` 传递到 `PestHarvest.OUT` 写出函数的问题

- 修复点：`Tomato_Cal/Workspace/run_dssat.py:1452-1457`
- 命令行解析：`Tomato_Cal/Workspace/run_dssat.py:1470-1478`

2) 提升 `XFRT` 上限到 `0.99`

- 修改点：`Tomato_Cal/Workspace/TMGRO048.CUL.base:44`（`MAXIMA` 行，`XFRT` 列）
- 使 v9 PST 中 `XFRT` 上限变为 `0.99`：`Tomato_Cal/Workspace/eggplant_stage2_v9.pst:46`

**验证结论**

- v9 参数集合中 `XFRT` 出现触顶样本（`max=0.99` 且 near-upper 样本数=1），表明上限可能成为约束，继续上推合理。

---

## v10（将 XFRT 上限推到 1.00，并完成再校准）

**动机**

- v9 已触到 `XFRT=0.99` 上限；按“如有必要可更高”推进到 `1.00` 以消除边界约束。

**关键变更**

- `XFRT` 上限从 `0.99` 提升到 `1.00`：`Tomato_Cal/Workspace/TMGRO048.CUL.base:44`。

**历史命令（已执行；v13+ 推荐参见 07_率定流程_阶段2_全局联合优化与诊断.md）**

- 构建 v10：
  - `python build_pest.py --mode eggplant_stage2 --prefix eggplant_stage2_v10 --noptmax 6 --ies-num-reals 40 --batch DSSBatch.v48 --harvest-var CHFPW --param-review-mode off --pwadm-sigma0 500 --pwadm-cv 0.008`
- 运行校准：
  - `c:\DSSAT48\Tomato_Cal\pestpp-5.2.16-win\bin\pestpp-ies.exe eggplant_stage2_v10.pst`
- 输出确定性收获对比：
  - `python analyze_results.py --deterministic-harvest-compare --prefix eggplant_stage2_v10 --batch DSSBatch.v48`
- 统一生成 v6–v10 收获误差汇总：
  - `python analyze_results.py --harvest-metrics --prefixes "eggplant_stage2_v6,eggplant_stage2_v7,eggplant_stage2_v8,eggplant_stage2_v9,eggplant_stage2_v10" --out "eggplant_stage2_v6_v10_harvest_metrics.csv"`

**输出/结果**

- v10 收获对比：`Tomato_Cal/Workspace/Calibration_Results/eggplant_stage2_v10_deterministic_harvest_compare.csv`
- v6–v10 指标汇总：`Tomato_Cal/Workspace/Calibration_Results/eggplant_stage2_v6_v10_harvest_metrics.csv`
- v10 IES 收敛摘要：`Tomato_Cal/Workspace/eggplant_stage2_v10.rec`（尾部含 `best phi yet` 与完成时间）

**验证结论**

- v10 最新参数集合仍出现 `XFRT` 触顶样本（`max=1.0` 且 near-1.00 样本数=1），表明边界仍在发挥约束，但已满足“必要时更高”的放宽要求。

---

## v11（加入出籽率/出叶速率/多采收相关参数，并扩大 SDPDV 范围）

**动机**

- 你要求将 `PODER（14–58）`、`SDPDV（300–900）`、`XFPHT`、`XFINT`、`XMAGE`、种子数、控制出叶速率参数、出籽率加入率定并扩大范围。

**关键变更**

- 将 `THRSH`（出籽率/脱粒率）纳入 CUL 率定：`Tomato_Cal/Workspace/TMGRO048.CUL.base:41`。
- 扩大 CUL 边界：
  - `SDPDV`：`300–900`（种子数口径）：`Tomato_Cal/Workspace/TMGRO048.CUL.base:44`。
  - `PODUR`：下限放宽到 `14`（按你的 `PODER(14–58)` 需求对齐；当前基准 CUL 文件中对应字段名为 `PODUR`）：`Tomato_Cal/Workspace/TMGRO048.CUL.base:43-44`。
  - `THRSH`：`6.0–9.8`：`Tomato_Cal/Workspace/TMGRO048.CUL.base:43-44`。
- 将 `XFPHT`、`XFINT` 纳入 ECO 率定并设置边界：
  - 边界：`Tomato_Cal/Workspace/build_pest.py:18-32`
  - stage2 允许列表：`Tomato_Cal/Workspace/build_pest.py:1215-1248`
- 控制出叶速率参数使用 `TRIFL`（ECO 参数）并已在 stage2 中启用（同上）。

**历史命令（已执行；v13+ 推荐参见 07_率定流程_阶段2_全局联合优化与诊断.md）**

- 构建 v11：
  - `python build_pest.py --mode eggplant_stage2 --prefix eggplant_stage2_v11 --noptmax 6 --ies-num-reals 40 --batch DSSBatch.v48 --harvest-var CHFPW --param-review-mode off --pwadm-sigma0 500 --pwadm-cv 0.008`
- 运行校准：
  - `c:\DSSAT48\Tomato_Cal\pestpp-5.2.16-win\bin\pestpp-ies.exe eggplant_stage2_v11.pst`

**输出/结果**

- v11 IES 收敛摘要：`Tomato_Cal/Workspace/eggplant_stage2_v11.rec`（尾部含 `best phi yet: 30635.3`）。
- v11 BASE 参数（迭代 6）：`Tomato_Cal/Workspace/eggplant_stage2_v11.6.base.par`。

**诊断结论**

- v11 中 `LAIXM` 组对目标函数贡献占比最高，且由于边界显著放宽，初始集合出现大量“极差 realizations”，导致 ensemble mean phi 显著放大（见 `eggplant_stage2_v11.rec` 的 group phi summary）。
- `THRSH / SDPDV / XFPHT / XFINT` 在当前观测配置下敏感度较弱，BASE 解相对 v11 初值变化很小（对照 `eggplant_stage2_v11.0.base.par` 与 `eggplant_stage2_v11.6.base.par`）。

---

## v12（产量聚焦与参数空间收缩：yieldfocus）

**动机**

- 在多次采收曲线仍存在结构性偏差的阶段，优先把目标函数的“信号”聚焦到 harvest/process/joint 的关键指标组合，并收缩参数空间以提升可识别性。

**关键变更**

- 强化 `stage2` 的参数筛选与边界复审流程（以 `Sensitivity_Analyze/SA_Project_Output/sensitivity_param_review.csv` 为 single source of truth）。

---

## v13（引入根系供氮参数 + 强化早期采收约束：rootN_incEarly9）

**动机**

- 针对水-氮梯度下的处理差异，引入根系供氮相关参数作为显式机理入口，避免将处理差异“挤压”进纯品种参数。
- 对多次采收“前段曲线形态”施加更强约束，降低“前期偏差被后期总量抵消”的等价解风险。

**关键变更**

- stage2 引入根系供氮参数 `RTNO3/RTNH4/RTEXF` 进入联合率定参数集（当前工程已改为默认启用；如需临时关闭用 `--no-include-n-uptake`）。
- 引入早期采收权重增强：
  - `--harvest-early-hno-max 4`
  - `--harvest-early-weight-factor 9`
  - `--harvest-early-apply-to inc`

**结果概览（用于版本间 sanity check）**

- v13 的最优 fixed 参数中 `RTNO3` 接近上界（提示模型倾向提高 NO3 吸收能力以缓解早期 N-stress）。

---

## v14（剔除 TN5/TN9/TN13：exclTN5_TN9_TN13）

**动机**

- 针对 TN5/TN9/TN13 在 harvest_curve 上表现出的强冲突（疑似 G×E 或观测/管理不一致），先做“处理屏蔽”实验以判断它们是否导致参数识别偏置。

**关键变更**

- 新增 batch 文件：`Workspace/DSSBatch_excl_TN5_TN9_TN13.v48`。
- stage2 使用替代 batch 完成完整 IES，形成与 v13 可直接对照的“剔除处理”版本。

**结果概览（用于版本间 sanity check）**

- 与 v13 相比，overall（TN=-99）层面的 harvest_curve 与 harvest_total 指标显著改善；根系供氮参数最优值基本稳定（说明 RTNO3/RTNH4/RTEXF 在保留处理集合下可较稳定识别）。
