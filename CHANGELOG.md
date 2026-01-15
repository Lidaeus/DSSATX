# Changelog

## 2026-01-15
- 在 `Workspace/run_dssat.py` 中将 `L#SD` 纳入从 `.TMT` 读取的过程观测点，并在 `PestTmtGrow.OUT` 写出 `@L#SDS@`。
- 在 `Workspace/run_dssat.py` 中将 `.TMT` 过程观测与 `PlantGro.OUT` 变量对齐，用“当日或之前最近一天”规则取模拟值。
- 在 `Workspace/analyze_results.py` 中新增过程变量对比表导出（`*_deterministic_process_compare.csv`）与过程指标汇总（RMSE/MAPE）。
- 在 `Workspace/build_pest.py` 中补充参数分组到文件位置的映射，并支持用“参数复核表”批量回写边界/初值/固定状态。
- 在 `Workspace/clean_workspace.py` 中按 prefix 归集并迁移运行产物到结果目录，避免污染工作区。
- 更新 `.gitignore`，忽略 `eggplant_stage2_v*` 与 `eggplant_v13` 运行产物，仅保留 v13 关键配置文件可提交。
