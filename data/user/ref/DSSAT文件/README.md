# DSSAT文件目录数据溯源与脚本说明

> **目录性质**：用户原始数据整理与参考包（Data Provenance & Reference Only）  
> **更新日期**：2026-09-14

本目录包含田间试验数据整理过程中从原始 Excel 提取、校验并生成 DSSAT 格式文件（FileX / FileA / FileT / SOIL）的过程脚本与数据源：

- `generate_dssat_v2.py` / `generate_dssat_all_seasons.py`：早期的试验文件批量生成脚本。
- `_check_*.py` / `_inspect_*.py`：用于核查 2025 春/秋季产量、水分、Excel 表头及数据完整性的一次性审计脚本。
- `2025秋/generate_dssat_filea_filet.py`：秋季数据整理脚本。

### 注意事项
1. **仅供溯源**：本目录下的所有脚本仅用于原始数据的整理、审计与格式转换溯源，**不参与**当前系统的自动化敏感性分析（SA）、PEST++ 校准以及模型运行流水线。
2. **生产数据真源**：正式校准与试验设计请使用规范化的数据包目录（`data/user/experiments/`、`data/raw/`）及统一构建工具（`tools/import_experiment_bundle.py`、`tools/setup_workspace.py`）。
