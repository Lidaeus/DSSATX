# P2 N4 S1 工程阶段复盘（2026-07-18）

## 结论

S1 IES 进程正常完成，但工程门失败，不能进入 S2。失败不是 DSSAT 进程崩溃：三轮升级的 manager 日志均为 `F0/T0`，所有实际模型调用都返回完成；PEST++ 因 Phi 异常/过大主动剔除成员。

运行目录：`workspace/runs/p2_n4_s1_20260718`

| 项目 | 结果 |
|---|---:|
| 阶段参数 | EM-FL、TRIFL（2） |
| 非零 Phi 观测 | 36，全部 calibration |
| 初始成员 | 40 |
| 第 1/2/3 轮剔除 | 3 / 2 / 3 |
| 末轮保留 | 32/40 = 0.80 |
| 工程门阈值 | ≥0.90 |
| DSSAT 运行失败 | 0 |
| Phi 非有限值 | 16/160 |
| 平均 Phi | 152.55 → 33.76 → 18.73 → 16.26 |

## 证据

- `ies_quality/ies_run_quality.json`：`engineering_failed`，失败项为 `ies_realization_alignment` 与 `ies_final_realization_alignment`；模拟输出存在跨成员变化，参数也发生更新。
- `manager/panther_manager.stdout.log`：三次 `dropping realizations as bad`，分别为 3、2、3；每次模型运行统计均为 `F0/T0`。
- `p2_n4_s1_20260718.1/.2/.3.pdc.csv`：35 个 calibration 观测与先验模拟集合存在明显冲突。
- `p2_n4_s1_20260718.3.pcs.csv`：EM-FL 约 93.75% 成员贴近下界，TRIFL 约 87.5% 成员贴近下界，提示当前阶段边界/目标存在强约束。

## 科学解释（仅使用 calibration）

S1 同时把 LAID 时间序列纳入 Phi，但只释放 EM-FL/TRIFL，其余冠层和生物量参数固定。TN2 的典型校准观测—模拟对为：

| 日期 | LAI 观测 | LAI 模拟（末轮代表成员） |
|---|---:|---:|
| 25075 | 0.010 | 0.003 |
| 25120 | 0.295 | 0.007 |
| 25142 | 1.209 | 0.296 |
| 25194 | 3.382 | 7.356 |

这表明当前差异主要是冠层增长/尺度基线问题，未必能由两个物候参数独立解释。PEST++ 将极端 Phi 成员剔除后仍得到较低平均 Phi，但这不能被解释为 S1 已经科学有效。

## 当前处理决定

1. 不把本次运行标记为 `science_validated`，不查看 TN5/TN13 validation，不启动 S2。
2. 用户已批准保守方案：后续 S1 的 Phi 只保留 ADAP 物候观测；LAID 由 DSSAT runner 保留为诊断输出，不参与率定目标，待冠层/生长阶段再使用。
3. 按新配置先做小规模 calibration-only 预检，确认成员保留率和 ADAP 组 Phi，再决定是否重跑完整 S1。

## 方案 1 执行结果

用户批准后，S1 配置已改为 `PestEval.OUT: ADAP`，并在 manifest 中记录 `PestTmtGrow.OUT: LAID` 为诊断输出。12-realization 预检通过工程门（保留率 1.00、Phi 全有限）；随后完整 40-realization、3 轮 S1 于 `workspace/runs/p2_n4_s1_adap_20260718` 完成：

- 工程门通过：保留率 1.00，Phi 160/160 有限，DSSAT 失败 0；
- ADAP 组 Phi 均发生变化，参数 ensemble 发生更新；
- 末轮参数仍有边界聚集（EM-FL 约 45% 贴近下界），因此只能作为工程通过的 S1 率定证据，不能由自动门直接升级为科研有效；
- 未查看 validation，未运行 S2。
