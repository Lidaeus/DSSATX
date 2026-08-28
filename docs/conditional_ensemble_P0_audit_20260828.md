# P0 输入与口径审计记录 — 条件集合不确定性图表（2026-08-28）

对应方案：`docs/PEST_IES条件集合不确定性图表开发方案_20260828.md` §9 P0。
本文件冻结开发期全部口径决策；后续 P1–P5 只能引用、不得修改本文件。

## 1. 源批次与科学门状态

- 源 run 目录：`workspace/runs/e02_formal_armab_rrmse_official_200x6_20260828`
- run_id / case：`e02_formal_armab_rrmse_200x6_20260828`
- `run_status.json`：`status=completed`，`engineering_status=engineering_validated`，
  `scientific_status=not_assessed`
- `ies_quality/ies_run_quality.json`：`status=pass`，`science_validated=false`，
  `science_validation_mode=engineering_only`
- 无 `calibration_finalize.json`；`run_manifest.yaml` 未记录冻结输入哈希

**结论**：该批次未通过科学门。全部图表只能以 `--allow-unvalidated-demo` 输出
`DEMO_` 前缀 + 水印；正式 Fig/FigS 等待 science_validated 批次。

## 2. 冻结术语

- PEST-IES 最终参数集合 = **conditional parameter ensemble（条件参数集合）**。
- 确定性复跑成员分位范围 = **95% conditional-ensemble prediction interval
  （95% 条件集合预测区间）**。
- 禁用表述：confidence interval、credible interval、完整 posterior predictive interval。
- interval semantics 字段固定：`parameter_conditional_ensemble_only`。

## 3. 成员集合（预注册）

- 来源：`e02_formal_armab_rrmse_200x6_20260828.6.par.csv`（最终迭代 6）。
- 排除 `base` 行（非随机条件成员）。200 行 = realization 0–198 + base。
- `ies_quality/…member_status.csv` 全部 200 行 `state=retained,
  final_status=retained`；103 参数列无非有限值（已实测核验）。
- 主分析集合 = 所有数值有限且模型复跑有效的非 base 成员（预期 199，以实际
  complete-case 为准）；不得因 Phi 高删除成员。
- 区间敏感性对照：剔除机器质量标记异常成员（`final_status != retained`）后的
  集合。当前批次该集合与主集合相同（0 个被标记成员），仍输出对照表以固化流程。

## 4. 季节、处理与角色（冻结）

- 进入本轮数据包的季节：仅 `25SP`（XXQL2501，10 处理）与 `26SP`（XXQL2601，
  12 处理）。`25FA` 禁止进入（导出器 CLI 硬拒绝）。
- 校准处理：25SP = {2, 5, 10, 13}；26SP = {1, 3, 9, 12}
  （与 `configs/runs/e02_formal_armab_rrmse_200x6_20260828.json` `seasons[].treatments`
  一致）。其余 14 个春季处理 = `validation`（诊断验证角色）。
- 水×氮映射：`configs/figures/treatment_metadata_two_season_20260828.csv`
  （由 FileX 提取的 `two_season_water_n_mapping_from_filex.csv` 冻结；25SP 部分
  与既有 `treatment_metadata_xxql2501.csv` 逐行一致）。R 端只允许按
  `season_id × treatment` 显式 join，禁止从 TN 推断 W/N。
- 25SP 为 incomplete factorial（W3、W1 全氮梯度 + W2N0 + CKN2）；26SP 为完整
  3×4 析因。全处理补充图保留 25SP 空白格或按实际 10 处理排列，不伪造组合。

## 5. 变量与时间口径

- 事件级（`conditional_prediction_summary.csv`）：DRY_INC、DRY_CUM、FRESH_INC、
  FRESH_CUM（FileT 事件 × FreshWt.OUT CHPDT/CHFPW，d+1 有界最近匹配，与
  `build_season_harvest_compare` 同一算法）；LAID、LWAD、SWAD、CWAD
  （FileT × PlantGro.OUT，on-or-before 最近匹配）。
- 日轨迹级（`conditional_trajectory_summary.csv`）：LAID、LWAD、SWAD、CWAD
  （PlantGro.OUT）+ DRY_CUM、FRESH_CUM（FreshWt.OUT）。
- 时间轴：DAP（取自 PlantGro/FreshWt `DAP` 列；事件 DAP = 匹配用的模拟日期的
  DAP）。跨年日期不参与算术，全部经 DSSAT 输出的 YEAR/DOY/DAP 解析。
- 观测哨兵值：≤ −90（FileA/FileT -99 族）一律不进入分位数与指标。
- 观测一致性：FileT 来自不可变 bundle，跨成员观测值必须逐值一致，不一致即中止。
- 分位数：`numpy.quantile` 线性插值（method="linear"，numpy 版本写入质量 JSON）。
- 顺序门：每点 `q025 ≤ q25 ≤ median ≤ q75 ≤ q975`；DRY_CUM/FRESH_CUM 全部分位
  曲线沿时间非递减，违反即导出器中止。

## 6. 处理级残差指标（方案二，冻结公式）

对成员 r、处理 t、变量 v（h 遍历该处理全部有效事件）：

```text
signed_relative_bias_pct[r,t,v] = 100 × Σ_h(SIM−OBS) / Σ_h OBS
rrmse_pct[r,t,v]                = 100 × sqrt(mean_h((SIM−OBS)²)) / mean_h(|OBS|)
terminal_relative_error_pct[r,t,v] = 100 × (SIM_terminal − OBS_terminal) / OBS_terminal
```

主图使用 `terminal_relative_error_pct`（DRY_CUM）；补充口径
`signed_relative_bias_pct`、`rrmse_pct`。禁止逐事件 (SIM−OBS)/OBS 直接合并。

## 7. 复跑环境冻结

- DSSAT EXE：`D:\Tomato_Cal\DSCSM048.EXE`
  （SHA-256 `92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a`，
  与 `formal_launch_receipt.json.official_exe_sha256` 一致；已核验）。
- 基因型模板：`data/templates/genotype/TMGRO048.{CUL,ECO,SPE}.base`
  （由 `run_multiseason._copy_bundle` 投影，哈希记录入质量 JSON）。
- Season bundle：`data/user/experiments/xxql2501_formal_armab_rrmse_20260828`、
  `xxql2601_formal_armab_rrmse_20260828`；manifest SHA-256 必须与率定设计
  `configs/runs/e02_formal_armab_rrmse_200x6_20260828.json` 声明值一致
  （cd40b00f…、c10224f2…）。
- 参数注入：逐成员宽表行 → `name,value` CSV（列名大小写映射到 PEST tpl 名），
  经 `src/calibration/run_multiseason.py` + `src/calibration/run_dssat.py` 原有
  注入链，不新增注入实现。TM0008 cultivar、初始条件与窄范围土壤参数规则不变。
- 隔离：每成员独立沙箱目录，互不共享输出；worker 仅分片调度。

## 8. 代表处理（正文时序图，预注册）

`configs/figures/selected_treatments_conditional.csv`（选择规则在作图前冻结）：

| 季节 | TN | W×N | 角色 | 规则 |
|---|---|---|---|---|
| 25SP | 2 | W3N3 | Cal | 校准高水高氮极端 |
| 25SP | 13 | W1N0 | Cal | 校准低水无氮极端 |
| 25SP | 14 | CKN2 | Val | 析因外结构对照（CK 水分控制） |
| 26SP | 1 | W3N3 | Cal | 校准高水高氮极端 |
| 26SP | 12 | W1N0 | Cal | 校准低水无氮极端 |
| 26SP | 5 | W2N2 | Val | 距全部校准角点最远的 W×N 格（仅由元数据决定） |

共 6 个处理、Cal:Val = 3:3；两季均含双校准极端；≥1 未参与率定的中间水氮
处理（26SP TN5）；≥1 依冻结依据选择的困难处理（25SP TN14，析因外）。

## 9. 图号占位纪律

开发期一律使用诊断 ID，不占用正式 Fig/FigS 编号：

- 方案一 → `fig_model_performance_uncertainty`
- 方案二 → `diagnostic_conditional_residual_by_treatment`
- 方案三 → `fig4_dynamics_conditional` / `figs4_all_treatments_conditional`

正式编号待作者批准 + science_validated 数据后由 figure registry 更新。

## 10. P1/P2 执行与 20 成员 DEMO vs 全量 199 差异说明（2026-08-28）

两次重放使用同一冻结环境（官方 EXE sha `92173d5f…`、同两季 bundle manifest、
同基因型模板），仅成员数不同；run 未 science_validated，输出均为 DEMO 前缀 +
水印（`legacy_layout_demo`）。

| 项目 | 20 成员 DEMO | 全量 199 成员 |
|---|---|---|
| 有效成员 / 全局门 | 20/20（1.00 ≥ 0.98） | 199/199（1.00 ≥ 0.98） |
| 冻结 prediction 行 | 892 | 892（键集一致） |
| trajectory 行 | 15 972 | 15 712（均匀成员规则多剔除少量 DAP 尾部键） |
| DRY_CUM 平均 95% 区间宽 | 284 kg/ha | 319 kg/ha |
| DRY_CUM 平均 IQR 宽 | 119 kg/ha | 108 kg/ha |
| RRMSE（25SP Cal/Val） | 30.6% / 25.2% | 30.7% / 25.4% |
| RRMSE（26SP Cal/Val） | 43.3% / 38.9% | 43.0% / 38.7% |
| PICP95（四组范围） | 0.15–0.375 | 0.15–0.40 |
| RMPIW（四组范围） | 13.1–17.2% | 14.1–19.8% |

解读要点（P5）：

1. 中位数预测在两成员数下几乎不变（RRMSE 差 ≤0.3 个百分点），说明 20 成员
   DEMO 已能代表集合中位行为，可安全用于版面/接口 QA。
2. 全量 199 的 95% 区间更宽（尾部更肥），PICP95 与 RMPIW 必须成对解读：
   PICP95 仍低（≤0.40）且区间并不过宽（RMPIW ≤20%），即条件参数集合区间
   相对观测散布为**欠离散**——这是"仅传播参数不确定性"口径的预期结果，
   不构成拟合优度证据，也不宜通过加宽区间机械提高覆盖率。
3. 校准与诊断验证分组全部分开报告；全处理矩阵图各季固定 y 轴
   （`coord_cartesian` 共享限值，无 free-y），水氮响应压缩不可被缩放隐藏。

冻结产物路径：

- DEMO20：`paper_data/conditional_predictions_demo20/`、
  `paper_figures_conditional_demo20/`
- 全量：`paper_data/conditional_predictions_full199/`、
  `paper_figures_conditional_full199/`
