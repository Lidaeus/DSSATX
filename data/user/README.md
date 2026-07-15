# 用户定义的 DSSAT 输入

每个实验使用一个不可覆盖的版本目录：`data/user/experiments/<bundle_id>/`。
同一目录应放置 FileX（`.TMX`）、FileA（`.TMA`）、FileT（`.TMT`）、`SOIL.SOL`、所需气象文件和 `DSSBatch.v48`。运行时用 `--input-dir` 显式选择目录；不得依赖“最新文件”或静默回退。

推荐通过 `tools/import_experiment_bundle.py` 导入。工具会生成含 SHA-256、处理列表、土壤剖面、初始条件和跨文件检查结果的 `input_manifest.json`，并拒绝覆盖已有版本。
