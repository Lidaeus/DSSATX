# P2 N4 S2 运行复盘（2026-07-18）

## 首次运行

首次 S2 IES 运行目录为 `workspace/runs/p2_n4_s2_20260718`。DSSAT 进程本身无失败（manager 日志为 `F0/T0`），但工程门失败：末轮保留率 44/60=0.733，Phi 非有限值 38/300。

原因已由 calibration 观测与 Phi 组分定位：`CNAM` 实测值约 100–170，而当时的 `assumption_based_sigma_v2.csv` 将 `CNAMM` 设为 sigma=0.25、model_sigma=0.05、floor=0.025。这相当于把氮数量按百分点评价，CNAM 组平均 Phi 约 1.03×10^6，远高于其他组并主导 PEST++ 的坏成员剔除；107/108 个观测被标记为 prior-data conflict。

这不是 S2 参数本身的科学结论，而是观测单位 policy 错误。`CNAM` 在当前 FileA/模型输出中应按氮数量（约 kg N ha−1 量级）处理，而不是氮百分比。已将 v2 policy 的 CNAMM 恢复为 sigma=25、model_sigma=5、floor=2，并保留本次失败作为审计证据。

## 修正策略后的复跑

使用同一 S1 固定基线（`EM-FL`、`TRIFL`）及修正后的 CNAMM policy，重新运行：

- run：`workspace/runs/p2_n4_s2_fixcnamm_20260718`；
- 规模：60 个先验成员，4 个 IES 更新轮次，6 个隔离 agent；
- DSSAT/agent 运行失败：0；参数、模拟观测均为有限值；参数发生更新并完成 4 轮；
- PEST++ 的 `ies_bad_phi_sigma=2` 按“均值 + 2σ”规则逐轮剔除高 Phi 成员，最终保留 53/60（0.8833），低于项目工程门 0.90；累计 Phi 有限值为 278/300；
- `run_status.json` 为 `engineering_failed`，失败原因仅为 `ies_realization_alignment` 和 `ies_final_realization_alignment`。这不是 DSSAT 进程失败，而是当前异常 Phi 剔除策略造成的成员保留率不足。

修正后初始 Phi 均值约 31,426，末轮约 31,103；CNAMM 不再产生上一轮的百万量级异常。当前结果仍不能称为科学有效，也不应进入后验或 validation 分析。

另一个需要保留的诊断是组间 Phi 仍明显不平衡：末轮 `HWAMM` 约 2.83×10^4，而 `CNAMM` 约 104，LAI/叶片/茎秆组更低。这说明修正了 CNAMM 的单位后，S2 还不能直接解释为“各生理组等权”；应先审计 HWAMM 的观测尺度、σ 与观测数量，再决定是否调整组权重。

## 后续决策

下一步不能只审核或放宽 `ies_bad_phi_sigma` 后重跑 S2。二次核验发现，相关运行没有显式 observation-noise contract，PESTPP-IES 在运行时自动切换为 no-noise；同时出现近全量 prior-data conflict 和参数边界坍缩。应先修正观测噪声表达和 prior coverage，再用同一初始集合做保留/关闭相对 Phi 筛除的配对诊断。详见 `docs/reports/P2_IES高Phi筛除评估与应对策略_20260718.md`。

不能为通过工程门而事后调整阈值或恢复已剔除成员。相关运行继续标记为工程预检失败，不进入 S3、后验分布或论文证据包。

## 用户批准的观测设计修订

连续采收茄子的季末地上部生物量 `HWAM` 会受多次采收强烈扰动，不能作为稳定的率定目标；`HIAM` 同理仅保留为敏感性/机制诊断。后续阶段的率定目标改为：

- `PestHarvest.OUT` 的每次采收增量（`PWAI`）;
- 同一采收事件上的累积量（`PWAD`）；
- LAI、植株氮和过程生物量观测继续按阶段设计使用。

`PWAM` 季末汇总不再与累积采收序列重复进入 Phi。该修订已同步到设计配置、S2/S3/S4 默认输出和回归测试。当前重跑仍需明确选择干重或鲜重 `--harvest-var`；本次历史运行使用的是干重 `CHPDT`，不能把它表述为同时率定了干重和鲜重。

## 修订设计的 S2 干重运行结果

运行目录：`workspace/runs/p2_n4_s2_harvest_20260718`。

- PST 审计：234 个非零观测；无 `HWAMM`、`PWAMM` 或 `HIAMM` 率定观测；包含 11 次采收的 `PWADM_H1…H11` 和 `PWAIM_H1…H11`，以及 LAI、CNAM、LAID、LWAD、SWAD；
- 规模：60 个先验成员、4 轮 IES、6 个隔离 agent；DSSAT/agent 运行失败数为 0；
- 参数、模拟观测均有限，参数确实更新；但 PEST++ 继续按 `ies_bad_phi_sigma=2` 剔除高 Phi 成员，末轮仅保留 50/60（0.833），累计 Phi 有限值 277/300，工程门仍为 `engineering_failed`；
- 末轮组 Phi 中，LWAD 后期过程约 1.26×10^3、LAIX 约 687、各次累积采收约 3–590；没有 HWAM 造成的季末地上部生物量支配问题，但采收/过程组的数量与 σ 仍需在异常成员策略审核后重新检查。

这次运行证明观测划分已按连续采收作物逻辑修订，但不能作为率定、后验或论文证据。鲜重尚未在同一 PST 中同时加入：当前 runner 的 `--harvest-var` 一次只选择 `CHPDT`（干重）或 `CHFPW`（鲜重），本次使用 `CHPDT`。在工程门策略确定后，再单独实现/审计双尺度采收观测的组合方式。

## 二次核验补充（2026-07-18）

对 `p2_n4_s2_harvest_20260718` 的逐轮 ensemble、PDC 和参数分布复算表明：

- 60→50 是 10 个不同 realization 被 `ies_bad_phi_sigma` 筛除；`277/300` 有限 Phi 中的 23 个缺失单元格包含成员退出后在后续轮次的累计缺失，不能表述成 23 个运行失败；
- `ies_drop_conflicts=0`，233/234 prior-data conflict 是观测层诊断，不是 10 个 realization 被删的直接原因；
- REC 明确记录因未提供 observation-noise-specific option 而自动切换为 no-noise；
- final ensemble 中 NSTFAC 全部位于上界、NMOBMX 全部位于下界，RTNO3 和 NVSMOB 也分别接近上、下界；
- NSTFAC 与 NMOBMX 的 final 方差为零，当前集合不能支持相关、VIF、PCA 或后验不确定性解释。

因此，“仅调整高 Phi 阈值”已被更完整的根因诊断策略取代。
