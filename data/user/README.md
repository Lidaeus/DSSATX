# 用户定义的 DSSAT 输入

当前可用于新工作流的三个季节包列于 `configs/experiments/current_bundles.json`。2026-09-23 前的 77 个输入包已移至 `D:/Tomato_Cal_Cold_Storage/input_bundles_20260923/`，并由该目录的 `archive_index.csv` 记录。旧包只用于历史溯源；新率定、敏感性分析及验证需显式选择当前包。原有运行结果仍绑定当时的数据哈希，不随新包更新。

每个实验使用一个不可覆盖的版本目录：`data/user/experiments/<bundle_id>/`。
同一目录应放置 FileX（`.TMX`）、FileA（`.TMA`）、FileT（`.TMT`）、`SOIL.SOL`、所需气象文件和 `DSSBatch.v48`。运行时用 `--input-dir` 显式选择目录；不得依赖“最新文件”或静默回退。

目录内文件都是**原始实验输入**：不在这里写入 PEST 参数、DSSAT 输出或任何运行时副本。需要修订 FileA/FileT/FileX 时，新建一个新的 `<bundle_id>`，复制后修改并重新生成 manifest；不得覆盖已冻结 bundle。

遗传模型模板不属于本目录：`TMGRO048.CUL.base`、`TMGRO048.ECO.base`、`TMGRO048.SPE.base` 固定存放在 `data/templates/genotype/`，并由 Git 版本管理。率定运行只在各自的 `workspace/runs/<run_id>/` 沙箱内生成可写的 `.CUL/.ECO/.SPE` 副本，不能把副本回写到模板或实验输入包。

推荐通过 `tools/import_experiment_bundle.py` 导入。工具会生成含 SHA-256、处理列表、土壤剖面、初始条件和跨文件检查结果的 `input_manifest.json`，并拒绝覆盖已有版本。
