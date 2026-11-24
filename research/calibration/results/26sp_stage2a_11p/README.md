# 26SP 阶段 2A 与希尔旺长开关执行报告

本页记录首轮 24×2 试验。[续跑报告](continuation/execution.zh.md)记录后续通过验收并冻结的参数组。

在 `research/root-n-4864` 上沿用 80×4 最优成员的 CUL、ECO 和 SPE。用归档 SHA-256 核对完整私有 26SP 输入。冻结点 W3–N2 季末鲜果为 **75.05 t/ha**，与方案列出的公开样例 **66.6 t/ha** 应分开解读。

## 实施决定

| 方案建议 | 决定与依据 |
| --- | --- |
| 调低根吸容量，保留 F5/F6 回补 | 采用。保留现有组织叶、茎软目标的米氏插值和零曲率的线性路径。F5/F6 的供给与库容成组验证。所有试验固定 `org_reserve_cap=0,0`、`refill_tau=0`、`photo_sln_ref=1.05`。 |
| 用 `mode=2` 希尔项区分高氮处理 | 作为默认关闭的研究开关实现。沿用模型已有的日初合计底物填充率 `day_substrate_fill`，并要求有有效的正有机氮状态。生殖碳上限在原有 DEMAND 与 PODS 路径同步缩放，模式 1 的 `psi` 算法照旧。 |
| 核函数抽离、参数校验和 P0 诊断 | 采用。希尔核通过缩放后平方来处理有限正带宽，避免设置人为带宽下限。模式 2 单独追加填充率事件，原 P0 事件字段和默认输出保持兼容。原生测试覆盖端点、单调性、半最大响应和 15 组配置检查。未动 `NI_ASSIMILATE`、`NI_POD_FACTOR` 或守恒账序。 |
| 用 11 参数在关闭旺长时率定 | 采用方案的 F6 初值和上下界。原有 61 个激活参数中本轮有 8 个继续激活，另有 3 个参数首次激活，因而原有 61 个里冻结 53 个。根核数组参数仅释放硝态位置。 |
| 增权 N2 叶氮，保留留出及 N3 | 采用。5 月 2 日、6 月 2 日和 6 月 29 日的 9 个 N2 叶氮观测使用 0.40 个百分点的尺度，叶氮族合计 21 个有效点，训练全表 140 个正权重点。处理 7、10 只作留出。N3 和 7 月 17 日叶氮未进目标函数。 |
| 在 6 月 29 日验收 LAI | 在 6 月 29 日按方案判定 LAI 相邻级差严格为正。定性的 Φ 和留出门槛分别采用重加权对照的 110% 为 Φ 上限、两个留出处理的鲜果 RMSE 均不超过同口径冻结对照。三项指定守恒红线直接执行。 |
| 率定 2B 三参数 | 2A 数值验收未通过，正式 2B 率定保持待准入。完成了两套固定起点的开关配对，结果在[阶段 2B 对照报告](../26sp_stage2b_lux2/README.md)。 |
| 检查 W1 后评估水分乘子 | 已检查原生日输出的 `1−WSPD` 和 `1−WSGD`。W1 有短时缺水，希尔折减与水分胁迫交叠有限。本轮保留原开关公式，定量依据见[水分交互](../26sp_stage2b_lux2/README.md#低氮保护与水分交互)。 |

## 率定结果与阶段判定

PEST++ IES 5.2.27，24 成员 × 2 轮、8 个并行 worker、随机种子 20261124。累计 **132** 次前向运行，未记录前向失败。各代最优 Φ 为 **24.5551 → 24.3438 → 24.1124**，独立复跑末代成员 17 得到 **24.1124127**。相对 F6 的 **26.4005364** 降低 **8.7%**，相对重加权的 80×4 冻结对照 **23.5815383** 增加 **2.3%**。冻结对照、F6 和后验使用相同的观测和权重。

| 设置 | 鲜果 Φ | LAI Φ | 地上部干重 Φ | 叶氮 Φ | 总 Φ |
| --- | ---: | ---: | ---: | ---: | ---: |
| 冻结对照 | 10.195 | 7.183 | 5.293 | 0.910 | 23.582 |
| F6 初始对照 | 10.126 | 8.705 | 6.582 | 0.986 | 26.401 |
| IES 成员 17 | 10.017 | 7.983 | 5.422 | 0.690 | 24.112 |

| 最优成员的验收指标 | W2 | W3 |
| --- | ---: | ---: |
| 鲜果 N0 < N1 < N2 | 通过 | 通过 |
| N2−N1 鲜果（须为 +3 至 +6 t/ha） | +0.104 | +0.784 |
| 6 月 29 日 N2−N1 叶氮（须为 +0.25 至 +0.35 个百分点） | +0.10 | +0.13 |
| 6 月 29 日 N2−N1 茎氮（百分点） | +0.05 | +0.06 |
| 6 月 29 日相邻 LAI 级差 N0→N1 / N1→N2 | +1.206 / +0.017 | +1.326 / +0.053 |
| N2−N1 季节实际吸氮（kg N/ha） | +9.73 | +20.93 |

留出鲜果 RMSE 在 W3–N1 从 **6.37** 降至 **5.21 t/ha**，在 W1–N1 从 **8.36** 降至 **7.60 t/ha**。F6 起点的对应 RMSE 为 **4.71** 和 **6.51 t/ha**，这两项比后验更接近观测。后验 `rnk_vmax_scale=0.77514`、`pool_beta=0.05996`、`assim_no3_k=0.0002209` 分别距边界约为区间宽度的 1.73%、1.81%、2.98%，均在设定范围内。相较 F6，联合目标改善的同时，W2/W3 的施氮鲜果差缩小。以最低 Φ 作为交付候选需要继续通过独立梯度门槛。关闭模式 2 的最优点在生殖期超过 `f=0.76` 的 N1/N2/N3 天数为 W2 的 3/35/47 和 W3 的 1/18/44，N2 仍多日进入该开关的潜在响应区。

**2A 未通过，2B 保持探索性复跑。** 按方案保留现有鲜果验收区间。26SP 实测的 W2/W3 鲜果增量为 +7.24/+6.56 t/ha，W2 的实测 6 月 29 日叶氮级差为 +0.672 个百分点，均超过方案对应上限。此次模拟的关键落差是低于下限。调整区间需要另行确定，当前数据和门槛同时归档。

### 整季审计

Release 编译、原生 Fortran 测试、`tm_deficiency_26sp` CTest 和 7 个 Python 单测通过。关闭两条新机制后，12 个处理在 11 份对照输出中一致。最优成员的旧有机氮、生长碳和无机库存量残差上限分别为 **5.53×10⁻⁷ g N/m²**、**9.54×10⁻⁷ g CH₂O/m²**、**9.92×10⁻¹⁶ g N/m²**。全株季节氮账最大残差 **2.74×10⁻⁶ g N/m²**，实际日碳账最大残差 **3.89×10⁻⁶ g CH₂O/m²**。最优成员逐层审计计入了 39,000 个已匹配土壤结算行和 312 个季末待结算行。

### 复现与归档

[最佳参数](best_parameters.csv) · [最佳 namelist](best_nintegration.nml) · [原始边界](bounds.csv) · [IES 历史](ies_history.csv) · [复跑回执](replay_receipt.json) · [输入校验](input_receipt.json) · [门槛与守恒收据](assessment.json) · [逐处理指标](treatment_summary.csv)

以下命令从仓库根目录执行。设定原始私有试验包 `f6_experiment`，以及归档 80×4 的私有准备目录 `f6_inputs` 和原生回放目录 `f6_reference`。使用率定 Python 环境，并把 `f6_engine` 指向本次源码的隔离 Release 构建。回执中的哈希以运行时文件原始字节计算。

```sh
f6_work=build/26sp-f6
python research/calibration/f5_26sp.py prepare \
  --profile f6 --experiment "$f6_experiment" --inputs "$f6_inputs" \
  --out "$f6_work/stage"
python research/calibration/stage2_26sp.py compare \
  --engine "$f6_engine" --stage "$f6_work/stage" --reference "$f6_reference" \
  --out "$f6_work/paired"
python research/calibration/ies.py \
  --engine "$f6_engine" --inputs "$f6_work/stage/inputs" \
  --template "$f6_work/stage/NIntegration.nml.tpl" --bounds "$f6_work/stage/bounds.csv" \
  --observations "$f6_work/stage/observations.csv" \
  --members 24 --updates 2 --workers 8 --seed 20261124 --pestpp-ies pestpp-ies \
  --out "$f6_work/ies"
python research/calibration/replay.py --case "$f6_work/ies" --out "$f6_work/ies-replay"
python research/calibration/stage2_26sp.py posterior \
  --engine "$f6_engine" --stage "$f6_work/stage" --reference "$f6_work/paired/receipt.json" \
  --config "$f6_work/ies-replay/configs/NIntegration.nml" --out "$f6_work/posterior"
```
