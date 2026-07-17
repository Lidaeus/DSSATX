# 异参同效分析开发报告

> 任务ID：EQ（异参同效分析接口与工具开发）
> 结论：**4 件套证据链 Python 工具已实现并在真实 P2 后验上验证**。遵循 DEVELOPER_GUIDE §5 与科研图表设计 line 121-123 的冻结数据契约。按计划 §5 line 172，本阶段冻结接口与门禁，不做自动判定。
> 标注：`engineering_preflight`（P2 ensemble 尚未正式通过质量门）。
> 更新日期：2026-07-17

> **P2-R0.7 更正（2026-07-17）**：(1) 本报告原称 "144 对功能异参同效"，但按 P2-R0.3 更正：这些只是**候选解对**（similar Phi + distant params），不是功能异参同效——后者要求预测距离也接近，需确定性复跑后才能判定。(2) 报告原称 7 个活跃参数，但 14 个校准参数中 7 个坍缩——按 P2-R0.2，坍缩参数应被标注而非消失（已修复：diagnostics 现覆盖全部 14 个，含 `collapsed` 标志）。(3) 异参同效入口现在绑定上游 IES 状态（P2-R0.1），不能自行升级为 science_validated。原报告保留追溯，降为 proposal。

## 1. 实现的 4 件套证据链

| 证据 | 函数 | 输出 CSV | P2 结果 |
|---|---|---|---|
| 1. 相关矩阵 | `compute_correlation_matrix` | `parameter_correlation.csv` | 最高 Pearson 0.633（NSTFAC–NVSMOB） |
| 2. VIF + 条件数 | `compute_vif_condition` | `vif_condition.csv` + `collinearity_metrics.csv` | 最大 VIF 2.38，条件数 3.06 |
| 3. PCA（sqrt(λ1/λ2)） | `compute_pca` | `pca_loadings.csv` | PC1 解释 31.5%，椭圆轴比 1.23 |
| 4. 功能异参同效 | `detect_functional_equifinality` | `functional_equifinality_pairs.csv` | 144 对（similar Phi, distant params） |

## 2. P2 后验的关键发现

### 后验收缩（7 个活跃参数）
14 个 stage2-active Sobol 参数中，**7 个在后验中仍变化**（其余 7 个边界紧、方差为零被过滤）：

| 参数 | IQR 收缩率 | 含义 |
|---|---|---|
| TM2 | **96.9%** | 温度响应（中）——强约束 |
| NSTFAC | **96.6%** | 氮胁迫因子——强约束 |
| NVSMOB | 93.9% | 营养器官氮迁移——强约束 |
| EM-FL | 72.4% | 出苗–开花——中度约束 |
| RTNO3 | 28.9% | 根系氮吸收——弱约束 |
| RTNH4 | 9.8% | 根系铵吸收——几乎未收缩 |
| RWDTH | -1.1% | 根宽——**未收缩**（先验=后验） |

**RWDTH 未收缩** 说明该参数在当前观测下不可辨识——先验与后验分布重叠。RTNH4 收缩极小（9.8%），也接近不可辨识。

### 共线性结构
- **条件数 3.06**（远低于警告阈值 30）——参数空间整体无严重共线性。
- **最大 VIF 2.38**（NVSMOB，远低于阈值 10）——无单参数被其他参数线性解释。
- **NSTFAC–NVSMOB 相关 0.633**——两个氮代谢参数存在补偿结构（中等强度）。

### 功能异参同效
**144 对**实现具有相似 Phi（best ±5%）但参数距离超过中位数。这表明存在大量等参同效解——不同参数组合达到相近拟合质量。椭圆轴比仅 1.23（接近 1 = 球形）进一步确认参数空间在多方向上等价展开，没有单一主导方向。

## 3. 数据契约（科研图表设计 line 121-123 对齐）

| 契约 | 文件 | 列 |
|---|---|---|
| 参数集合 | （待 export_posterior_ensemble） | `iteration/realization/parameter/value/lower/upper/status` |
| 异参同效 | `functional_equifinality_pairs.csv` | `pair_id/real_a/real_b/phi_a/phi_b/phi_total/parameter_distance/prediction_distance` |
| 收缩诊断 | `posterior_diagnostics.csv` | `parameter/prior_*/posterior_*/iqr_shrinkage/var_shrinkage/frac_near_*/multimodality_flag` |
| 相关 | `parameter_correlation.csv` | `parameter_a/parameter_b/pearson/spearman` |
| PCA | `pca_loadings.csv` | `component/parameter/loading/eigenvalue/explained_variance_ratio` |
| 共线性 | `vif_condition.csv` + `collinearity_metrics.csv` | `parameter/vif/r_squared` + `metric/value` |

`prediction_distance` 列当前为 NaN——待代表性解的确定性复跑后填入（计划 Fig.S7 前置条件）。

## 4. 门禁设计（warn 级，不 fail）

`assess_equifinality` 产出的 QualityReport 含 5 个检查，全部 warn 级（不拒绝运行）：

| 检查 | P2 实际值 | 阈值 | 状态 |
|---|---|---|---|
| `process_completed` | 7 active, 25 reals | ≥1 active | ✅ pass |
| `equifinality_max_correlation` | 0.633 | >0.8 warn | ✅ pass（低于阈值） |
| `equifinality_max_vif` | 2.38 | >10 warn | ✅ pass |
| `equifinality_condition_number` | 3.06 | >30 warn | ✅ pass |
| `equifinality_functional_pairs` | 144 | — | ⚠️ warn（记录，不判定） |

**整体 status=pass**——P2 后验无严重共线性或不可辨识警告，但功能异参同效对数较多（144），需在论文中讨论。

## 5. 明确不在本阶段

- **R 图表模块**（Fig.5/S5/S6/S7）——待 Python 数据契约冻结后由图表线开发
- **功能异参同效预测分化**（`prediction_distance`）——需先跑代表性解确定性复跑
- **自动异参同效判定/拒绝门禁**——计划 §5 line 172 明确排除
- **t-SNE 聚类**——计划科研图表设计 line 79 明确拒绝

## 6. 测试

`tests/test_equifinality.py`：8/8 通过（合成数据验证 4 件套 + 多峰检测 + 零方差过滤 + 全流程）。全套件 154 passed, 2 skipped。

## 7. 产物

- `src/reporting/equifinality.py`：核心模块（6 个计算函数 + CLI）
- `tests/test_equifinality.py`：8 个测试
- `workspace/runs/eggplant_stage2_v4_sobol20_p2/equifinality/`：P2 后验的 6 个 CSV + quality + manifest
- 本报告

## 8. 下一步

1. **代表性解确定性复跑**：从功能异参同效对中选 3-5 对，跑确定性 DSSAT 复跑，计算 `prediction_distance`，完成 Fig.S7 前置数据。
2. **R 图表开发**：基于冻结的 CSV 契约实现 Fig.5（可辨识性/异参同效）、Fig.S5（收缩+bounds）、Fig.S6（相关+PCA+VIF）、Fig.S7（功能对预测分化）。
3. **正式 P2 门禁通过后**：重跑异参同效分析，产出 `science_validated` 标注的结果。
