# Changelog

## 2026-07-15

- 将用户更新的 XXQL2501 FileX/SOIL 及配套 FileA/FileT/气象/批处理导入版本化输入包，新增 SHA-256 清单和跨文件科学门禁；权威坐标统一为 35.16°N、113.8°E。
- DSSAT、SA 和率定入口新增显式 `--input-dir`，正式运行可隔离使用用户定义文件，避免从旧 `data/raw`/`Workspace` 隐式取值。
- 批准并冻结 `eggplant_p1_xxql2501_v1_20260715`：57 active，8 层土壤实值 fixed，50 个 TN×层初始水分记录 disabled；废弃错误的 6 层共用 IC 语义。
- 审计 TN2/TN3 与旧 90 项输出：改为全部 10 TN、240 项响应；过程点对齐 FileT 的 DAP 45/67/95/119，移除冗余跨处理均值。
- 正式 Morris 预算提高为 5 个固定种子×`r=30`，合计理论 8700 次 DSSAT；新增输入、输出、边界和本地化回归测试。
- 加固 P0 回归测试：固化 V14 的真实失败基线，拒绝空边界、active 零宽、空参数组、非法边界交换/夹紧、IES 非有限输出、Phi 非有限值及 realization 异常丢失。
- 修正物理硬边界错误排除 DSSAT 自带基线的问题，并以 V14 设计 proposal 生成待审 P1 候选：57 个 CUL/ECO/SPE active，44 个 SOIL/IC 参数恢复 fixed。
- 新增 P1 bounds readiness 门禁和启动计划；pending proposal 仅允许技术构建，未批准时正式预检必须失败。
- frozen metadata 新增最终 CSV 哈希，P1 启动前会检测审批后文件是否被修改。
- P1 基线输出预检发现 MDAPS 全部为 `-99`，已从当前案例默认 SA 输出契约移除，防止缺失指标污染 Morris。
- 修复 `pandas>=3` 与 FloPy 3.10 要求 `pandas<3` 的不可满足依赖组合，新增运行环境版本契约测试。
- 新增可审计 Observation Policy：FileA/FileT 保留实际尺度，`.pst` 观测与 PEST tagged 模拟按同一 `ln((y+offset)/reference)` 变换。
- 新增处理均值 sigma 计算与审计字段，区分重复 SD、`n_effective`、模型误差、sigma 下限和来源；明确禁止把同一处理重复伪装成独立模拟观测。
- 物候、冠层、生物量和增量采收默认等组倍率，提供增量采收 `1.1` 的显式对照示例；pwtadj1 保持停用，未来只按总组 Phi 且经数量/相关性审核后考虑。
- 创建升级前快照 `fdfb5b1`，并在 `codex/p0-research-credibility` 实施 P0 科研可信性修复。
- 统一项目路径与兼容入口，改为每个 worker 独立 DSSAT 运行目录，并拒绝陈旧/空输出。
- 新增冻结边界、候选参数、Morris/Sobol 与 IES 科学质量门；历史退化运行现会明确失败。
- 修复 CUL/ECO/SPE/SOIL/IC 注入链、IC 表状态解析和 frozen `init/status` 应用。
- 完成真实 DSSAT 参数响应、非退化 Morris 和非退化 IES 微型验证，证据见 `reports/P0_verification_report.md`。
- 重写产品定义与系统设计，将项目目标收敛为可信、有效、易用的 DSSAT SA/率定科研工具。
- 建立 `process_completed` 与 `science_validated` 两级状态及阶段质量门。
- 明确 SA 提案、人工审核、冻结边界和率定之间的受控衔接。
- 修订观测误差与权重规范：PEST 基础权重使用 `1/sigma`，停用动态 Min–Max 和静默组权重回退设计。
- 将历史 SA/率定结论降级为归档背景，等待 P0/P1 后用有效运行重建。
- 新增文档索引，并同步 SA 输出和测试质量规范。

## 2026-01-15
- 在 `Workspace/run_dssat.py` 中将 `L#SD` 纳入从 `.TMT` 读取的过程观测点，并在 `PestTmtGrow.OUT` 写出 `@L#SDS@`。
- 在 `Workspace/run_dssat.py` 中将 `.TMT` 过程观测与 `PlantGro.OUT` 变量对齐，用“当日或之前最近一天”规则取模拟值。
- 在 `Workspace/analyze_results.py` 中新增过程变量对比表导出（`*_deterministic_process_compare.csv`）与过程指标汇总（RMSE/MAPE）。
- 在 `Workspace/build_pest.py` 中补充参数分组到文件位置的映射，并支持用“参数复核表”批量回写边界/初值/固定状态。
- 在 `Workspace/clean_workspace.py` 中按 prefix 归集并迁移运行产物到结果目录，避免污染工作区。
- 更新 `.gitignore`，忽略 `eggplant_stage2_v*` 与 `eggplant_v13` 运行产物，仅保留 v13 关键配置文件可提交。
