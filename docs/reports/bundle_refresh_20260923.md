# 2026-09-23 DSSAT 输入包重建记录

## 当前输入与来源

| 季节 | 当前 bundle | 产量来源 | 初始矿质氮来源 | 实测氮深度 |
|---|---|---|---|---|
| 25SP | `xxql2501_corrected_20260923` | `2025春产量数据集.xlsx` | `2025春初始土壤基础养分.xlsx`（已为纯氮） | 0–60 cm |
| 26SP | `xxql2601_corrected_20260923` | `2026春产量集.xlsx` | `2026春土壤硝态氮氨态氮.xlsx` | 0–100 cm |
| 25FA | `xxql2502_corrected_20260923` | `2025秋季产量集.xlsx` | `2025秋土壤养分数据集.xlsx`（用户指定） | 0–60 cm |

源文件位于 `data/user/ref/DSSAT文件/` 的对应季节目录。每个 `input_manifest.json` 记录了实际采用的源工作簿 SHA-256、包内文件 SHA-256 和映射规则；现行包 ID 与 manifest 哈希统一登记在 `configs/experiments/current_bundles.json`。25FA 鲜重转干重沿用已确认的固定干物质比例 0.05。25SP 第 14 处理缺少独立土壤养分记录；用户确认沿用第 13 处理记录，并在 `soil_inventory_reconciliation.csv` 的 `source_trno` 列标明。

## 土壤层映射

DSSAT 目标层底深为 2、4、15、30、40、60、80、100、140、180 cm。实测浓度按来源层与目标层的重叠厚度乘以容重进行干土质量加权；含水量按重叠厚度加权。因此 15–30 cm 等跨实测边界的层由相邻实测层共同贡献。各处理逐层贡献见 `soil_depth_mapping_audit.csv`，实测范围积分核对见 `soil_inventory_reconciliation.csv`。

| 季节 | 积分核对行数 | 未舍入积分 | DSSAT 文件精度下最大相对误差 |
|---|---:|---|---:|
| 25SP | 77 | 全部守恒 | 0.6043% |
| 26SP | 84 | 全部守恒 | 0.4785% |
| 25FA | 84 | 全部守恒 | 0.3286% |

25SP 与 25FA 在 60 cm 以下无矿质氮实测，80、100 cm 等目标层使用 `SNO3=1`、`SNH4=0.5` mg N/kg；26SP 的 80、100 cm 值保留其独立实测数据。100 cm 以下未测部分也使用同一默认值，并在审计文件中标明 `dssat_default`。其他土壤性质和水分的深层先验在生成脚本中独立记录，不视作实测。

## 替换、归档与验证

`data/user/experiments/` 仅保留上述三个新包。77 个旧目录已完整移动至 `D:/Tomato_Cal_Cold_Storage/input_bundles_20260923/`，`archive_index.csv` 记录原位置、文件数、字节数和原 manifest 哈希；迁移后 77 个目录均存在，75 份原有 manifest 的哈希核验通过，另两个旧目录本来没有 manifest。重建过程的中间包保存在 `D:/Tomato_Cal_Cold_Storage/build_attempts_20260923/`，不在项目输入目录。

每季 bundle 通过 manifest 完整性、输入格式、观测审计和确定性 DSSAT 运行检查，运行中无 `ERROR.OUT`，平衡检查通过。从冷备份种子重新构建的三个包与当前包的 manifest SHA-256 完全一致。项目当前 `python -m pytest tests/ -q` 结果为 **645 passed, 5 skipped**。

按用户选择，依赖旧包的 21 份试验规格、129 份率定/管理/敏感性分析设计、5 份入口/矩阵文件和 34 份测试文件已移入 `docs/archive/data_pipeline/legacy_bundle_contracts_20260923/`；旧 bundle 构建入口已停用。当前 `configs/` 下没有引用已移走旧包的 JSON 设计。两个已改为新包路径的正式率定设计仍标为 `requires_revalidation_after_20260923_source_refresh` 且 `executable=false`，因为历史结论和阈值尚未用更正数据重新检验。确定性输入验证不等于重新完成参数率定。
