# R 论文图流水线

本目录是论文主图、补充图和投稿版源文件的唯一绘图实现。Python 只负责
SA/率定运行诊断以及将结果导出为冻结的 tidy 数据包；R 不读取 DSSAT 或
PEST++ 的临时文件，也不猜测处理映射、迭代号或数据用途。

## 目录职责

```text
paper/
  R/                 R 绘图入口、统一主题和各图实现
  README.md          依赖、数据契约与复现命令
configs/figures/     出版 profile 与 Fig/FigS 注册表
src/reporting/
  figure_data.py     Python 侧 tidy 数据契约和历史适配
  export_paper_data.py 只导出数据，不绘图
  plot_results.py    Python 运行诊断兼容入口，不生成论文图号
```

## R 依赖

要求 R 4.3 或更高版本，以及 `ggplot2`、`patchwork`、`jsonlite`、
`svglite`。Windows 使用系统 `certutil` 计算 SHA-256；非 Windows 需要
`sha256sum`。入口会在绘图前一次性检查依赖，不会在正式运行时
联网安装包。

`Rscript` 应加入 `PATH`；若机器并存多个 R 版本，可用选定版本的完整
`Rscript.exe` 路径执行。不要让新 R 版本加载旧版本编译的用户包库。

## 两阶段复现

先由 Python 冻结渲染器无关的数据包：

```powershell
python -m src.reporting.export_paper_data --run-id <run_id> `
  --comparison-csv <comparison.csv> --phi-csv <case.phi.actual.csv> `
  --out-dir workspace/runs/<run_id>/paper_data
```

再由 R 生成论文图、每图 source CSV 和哈希清单：

```powershell
Rscript paper/R/make_all.R `
  --input-dir workspace/runs/<run_id>/paper_data `
  --out-dir workspace/runs/<run_id>/paper_figures
```

非 `science_validated` 数据默认被两端拒绝。仅版式开发可在两个命令中都
显式加入 `--allow-unvalidated-demo`；输出使用 `DEMO_` 前缀并带水印，不能
作为论文图引用。
