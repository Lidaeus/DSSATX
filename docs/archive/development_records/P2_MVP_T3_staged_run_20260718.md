# P2-MVP T3 staged calibration 运行记录（2026-07-18）

> 任务ID：T3（S1→S2→S3→S4 staged IES 运行）
> 结论：**四阶段全部 `engineering_validated`**；继承链、manifest、确定性复跑产物完整保全。全程 `approval_scope=tooling_development`、`science_pending`，未读取 validation。
> 执行中发现并修复了一个 S4 active 参数重激活缺陷（`apply_parameter_stage` + `frozen_bounds`）。

## 1. 运行总览

| 阶段 | 参数 | 成员/轮 | 观测 | 工程状态 | 末轮 mean Phi | 代表参数（中位数）关键值 |
|---|---|---|---|---|---:|---|
| S1 | EM-FL, TRIFL（active） | 20/2 | ADAP（6 非零） | engineering_validated | 0.81 | EM-FL=23.25, TRIFL=0.623 |
| S2 | +NSTFAC,RTNO3,NMOBMX,NVSMOB（active）<br>EM-FL,TRIFL（fixed←S1） | 30/2 | LAIX,CNAM,LAID,LWAD,SWAD（102 非零） | engineering_validated | 2822 | NSTFAC=0.85(↑), NMOBMX=0.08(↓), RTNO3=0.031 |
| S3 | +XFRT,XFINT（active）<br>S1+4N（fixed←S2） | 30/2 | PWAI（66 非零） | engineering_validated | 159 | XFRT=0.943, XFINT=0.282 |
| S4 | EM-FL,TRIFL,4N（re-active）<br>XFRT,XFINT（fixed←S3） | 40/2 | ADAP,LAIX,CNAM,LAID,LWAD,SWAD（108 非零） | engineering_validated | 792 | TRIFL=0.2(↓), NVSMOB=0.301, RTNO3=0.023 |

Phi 量级差异源于各阶段观测组不同（S1 仅 ADAP 物候；S2 含 LAI/生物量/氮；S3 仅 PWAI 采收；S4 联合）。跨阶段**不可直接比较绝对 Phi**。

## 2. 继承链审计

四阶段共用同一冻结 bounds（`eggplant_p1_xxql2501_v4_sobol20_20260717`）、同一输入包（`xxql2501_20260716`）、同一 design（`eggplant_p2_tooling_design_20260718`）、同一随机种子（20260718）。每阶段的 `--fixed-from` 指向紧邻上游 `calibration_finalize/stage_representative_params.csv`：

```
S1 finalize → median CSV → S2 build --fixed-from → S2 finalize → median CSV → S3 build → S3 finalize → median CSV → S4 build → S4 finalize
```

`_fixed_from_provenance`（T2.2 修复）正确从 `calibration_finalize/` 子目录定位 run_dir，三方哈希（manifest↔finalize↔代表参数 metadata）全部一致。S2/S3/S4 的 fixed 参数值精确等于上游代表中位数（已在 PST `parval1` 验证）。

## 3. 工程执行中发现并修复的缺陷

### [P0] S4 active 参数被 `--fixed-from` 钉死（`npar_adj=0`）

**现象**：S4 首次 build 报告 `npar_adj:0`——所有 8 个参数（含设计要求 active 的 6 个）都是 `partrans=fixed`。S4 无法运行。

**根因**：`apply_fixed_params_csv`（build_pest.py:2359）把 `--fixed-from` 的每个参数设成 `status="fixed"` 且 `lower=upper=init=value`。随后 `apply_parameter_stage`（design_config.py:181）对 `active_params` 只是 `selected = [by_name[name] ...]` 直接取已被钉死的 dict，**没有恢复 active 状态或 bounds**。S2/S3 没暴露此 bug，因为它们的 active 参数不在 fixed_from CSV 里；S4 的 active 参数（EM-FL 等）恰好在 S3 代表 CSV 里，被钉死后无法重激活。

**修复**：
- `design_config.py` 新增 `load_frozen_bounds_lookup(path)` 从冻结 bounds CSV 构造 `{name: (lower, upper)}` 查找表。
- `apply_parameter_stage` 新增可选 `frozen_bounds` 参数；对 `active_params` 强制 `status="none"`（PEST 的可调术语，build 把 status 直接写入 partrans），并从 frozen_bounds 恢复 lower/upper；保留当前 init（来自上游代表值）作为 IES 起点。
- `build_pest.py` staged 入口调用 `apply_parameter_stage` 时传入从 `_prevalidated_bounds` 构造的 lookup。
- 回归测试 `test_s4_re_releases_parameters_pinned_by_fixed_from`：构造 S3 代表 CSV 钉死状态，断言修复后 6 active 参数恢复完整 bounds、2 fixed 参数保持钉死。

修复后 S4 build 正确报告 `npar_adj:6`，6 个 active 参数 `partrans=none` 且恢复原始 bounds（如 EM-FL lbnd=23.0/ubnd=31.0），init 保留为 S3 代表值（23.2541）。

### S4 首次 IES 被 kill + resume 失败

S4 首次 IES 在初始化阶段（40 成员刚启动）被外部 kill。尝试 `--resume` 失败：`Error: /r option not supported by pestpp-ies`。PEST++-IES 不支持 `/r` recourse 选项，`run_parallel.py --resume` 与 pestpp-ies 的兼容性是已知工具层限制（不在本轮修复范围）。解决方案是从干净 build 重新启动 S4 IES（不 resume），因为首次运行没完成任何迭代、无丢失工作。重新运行成功通过工程门。

## 4. 每阶段保全的产物

每个 `workspace/runs/t3_{s1,s2,s3,s4}_20260718/` 目录含：

- `run_manifest.yaml`（含 design_stage、bounds_id、fixed_from 哈希、approval_scope=tooling_development）
- `t3_{s}_20260718.pst` / `.tpl` / `.ins` / `_params.csv`
- `t3_{s}_20260718.phi.actual.csv`（iteration-realization 长格式 Phi）
- `t3_{s}_20260718.{0,1,2}.par.csv`（每轮参数 ensemble）
- `ies_quality/ies_run_quality.json` + `t3_{s}_20260718.member_status.csv`
- `calibration_finalize/calibration_finalize.json` + `stage_representative_params.csv` + `stage_representative_params.json`
- `representative_deterministic_rerun/`（含 `PestTmtGrow.OUT`/`PestHarvest.OUT`/`Evaluate.OUT` 等代表解确定性复跑输出）
- `manager/` + `_agents/`（PEST++ 运行日志）

**哈希绑定范围说明（T3.1 审查修正）**：`run_manifest.yaml` 绑定的是输入层契约 —— 输入包、冻结 bounds、observation policy、`--fixed-from` 上游继承、观测 ensemble、代表参数文件。它**不**直接绑定 PST、Phi 表、最终参数/模拟 ensemble、质量报告、成员状态表或确定性复跑输出。T3.1 起由 `calibration_finalize/calibration_artifacts_manifest.json` 为这些核心科研产物补上独立 SHA-256 清单（含 PST、末轮 par ensemble、phi.actual.csv、ies_run_quality.json、member_status.csv、finalize 负载、代表参数 CSV、以及 `representative_deterministic_rerun/*.OUT`）；`_agents/` 与 `manager/` 临时日志树刻意排除在外，避免建立复杂归档。运行目录被 .gitignore 忽略（不入库），本地完整保留供审计。

## 5. 边界遵守

- ✅ 全程 `approval_scope=tooling_development`、`science_status=science_pending`。
- ✅ 未读取 validation 处理（TN5/TN13 等 validation treatments 仅在 design split 中声明，未进入任何 Phi 或诊断）。
- ✅ 未为通过工程门调整阈值或恢复已剔除成员。
- ✅ 边界命中（NSTFAC=0.85 上界、NMOBMX=0.08 下界、TRIFL=0.2 下界、EM-FL=23.0 下界）只记录，未阻止工具开发。
- ✅ 未触达后验分布、PCA/VIF、equifinality 或论文图表。
- ✅ DSSAT/解析无失败；参数有注入、模拟有变化；Phi 有限且有变化；参数发生更新；继承哈希一致；确定性复跑产生预期文件。

## 6. 科学限制声明（不可作为科研结论）

按审查 T3 边界，以下只是工程诊断，**不构成科研结论**：
- S4 多个参数贴边界（TRIFL=0.2 下界、NSTFAC=0.85 上界等）提示当前 bounds/观测/模型结构存在强约束，需要后续科学审核（可能涉及 bounds 扩展、观测权重、模型机制）。
- 组间 Phi 不平衡需后续审计观测尺度与 σ（**T3.1 审查修正**：原记录误写为 "CNAM/HWAM vs LAI"，但 S2 的观测组里**没有 HWAM**）。S2 末轮主要 Phi 贡献实际来自**叶片生物量和 LAIX**：`lwadm_d25194`≈1257.3、`laixm`≈707.0、`lwadm_d25170`≈537.7，而 `cnamm`≈104.6。仍仅作为工程诊断，不构成科学结论。
- 所有结果标记 `engineering_validated`，不是 `science_validated`。后验、validation、论文图必须等独立科学审核通过后才能基于这些 ensemble 产生。

## 7. 下一步

T3 工程闭环完成。按 P2-MVP 计划，后续候选工作包（需用户审批）：
- 后验分布与参数收缩分析（基于 S4 ensemble）。
- 异参同效（equifinality）与 PCA/VIF 诊断。
- validation 冻结后的模型性能评估（Fig.3/4 等）。
- 代表确定性复跑输出的论文图表数据导出（R 渲染）。

在此之前，S4 ensemble 仅作为工程证据保留，不作为参数推荐或论文结论。
