# Tomato_Cal

Tomato_Cal 是一个面向作物模型研究的 DSSAT 参数敏感性分析与 PEST++ IES 参数率定工具。它当前以茄子试验为主要案例；由于 DSSAT 4.8 没有独立茄子模型，项目使用 Tomato/CRGRO 的 `TMGRO048.CUL/ECO/SPE` 模型文件，并通过版本化输入、冻结参数范围和质量门保证结果可追溯。

项目的目标很明确：可靠地完成遗传参数筛选、分阶段率定、留出处理验证、条件参数集合/异参同效分析，并为论文输出可复现数据和 R 图表。它不是通用建模平台，也不会以增加算法数量代替科学审查。

## 当前状态

- DSSAT 参数注入、隔离运行、Morris/Sobol、分阶段 IES、确定性复跑和结果清单已经打通。
- S1–S4 工具开发运行已达到 `engineering_validated`，证明工具链可执行；现有运行仍是 `tooling_development / science_pending`，不能直接作为论文结论。
- staged builder 已可在干净 workspace 中仅依赖版本化 FileA/FileT 构建观测契约，不再读取旧 `workspace/Evaluate.OUT`。
- 两春一秋的 Morris 筛选已完成三 seed 汇总：XXQL2501 和 XXQL2601 的两个域稳定，XXQL2502 的一般遗传域稳定，而水氮域的 Top-15 边界仍有种子敏感性。当前论文图链据此生成明确标记的 `science_pending / DEMO_` 图；Sobol 的 XXQL2501 N64→N128 收敛门未通过，只作为补充的数值不确定性记录。详见 [敏感性分析论文写作参考](docs/论文材料与方法_正式遗传参数敏感性分析.md)。
- Python 只输出运行诊断和论文数据；所有可能进入论文的图由 `paper/R/` 统一绘制。

## 环境

- Windows，DSSAT 4.8 默认安装在 `C:\DSSAT48\`
- Python 3.13+
- PEST++ 5.2.16（仓库内 `pestpp-5.2.16-win/`）
- 论文图需要 R 4.3+、`ggplot2`、`patchwork`、`jsonlite`、`svglite`

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

## 准备输入

每次实验使用不可覆盖的输入包：

```text
data/user/experiments/<bundle_id>/
  <experiment>.TMX    # FileX
  <experiment>.TMA    # FileA
  <experiment>.TMT    # FileT
  SOIL.SOL
  <weather>.WTH
  DSSBatch.v48
  input_manifest.json
```

推荐通过导入工具创建新包：

```powershell
python tools/import_experiment_bundle.py `
  --source-dir <原始文件目录> `
  --soil <SOIL.SOL> --weather <气象文件> --batch <DSSBatch.v48> `
  --experiment <试验名> --bundle-id <新bundle_id> `
  --symbi Y
```

茄子借用 CROPGRO-Tomato 模型，但仍是非豆科作物；为兼容 DSSAT 4.8.5 的 CRGRO048 (Tomato) 模型启动运行，正式输入的 FileX simulation OPTIONS 必须为 `SYMBI=Y`，实际固氮参数 `FRCNOD` 固定为 0.05 并排除在 SA/率定之外。

遗传模型基线只放在：

```text
data/templates/genotype/TMGRO048.CUL.base
data/templates/genotype/TMGRO048.ECO.base
data/templates/genotype/TMGRO048.SPE.base
```

运行产生的 `.CUL/.ECO/.SPE` 是沙箱副本，不能回写为基线。详见 [目录与输入资产规范](docs/目录与输入资产规范.md)。

## 基本工作流

### 1. 敏感性分析

1. 创建并审核 SA 参数 proposal；通过 `tools/freeze_bounds.py` 生成新的 frozen bounds。
2. 为每个 seed 创建独立 case：

```powershell
python src/sensitivity/sa_build_sen_case.py `
  --param-review <审核后的参数CSV> `
  --case-dir workspace/runs/<sa_run_id> `
  --input-dir data/user/experiments/<sa_bundle_id> `
  --output-profile <输出定义JSON> `
  --morris-r <轨迹数> --morris-p <水平数> --random-seed <seed> `
  --run-type sensitivity_formal_case

python tools/parallel/run_parallel.py `
  --run-dir workspace/runs/<sa_run_id> --case sa_sen_morris `
  --mode sen --n-agents <并行数> --wait

python src/sensitivity/morris_audit.py `
  --case-dir workspace/runs/<sa_run_id> --case sa_sen_morris --require-formal
```

Morris 用于筛选；Sobol 只在用户批准的 Top-K、预算和至少两个有效尺度上用于定量与收敛判断。SA 结果不能自动成为率定边界。

### 2. 分阶段遗传参数率定

正式率定只读取 `bounds_frozen`，并显式指定输入包、观测策略和阶段设计：

```powershell
python src/calibration/build_pest.py `
  --mode eggplant_stage2 `
  --design-config configs/runs/<approved_design>.json --stage S1 `
  --bounds-id <approved_bounds_id> --bounds-crop eggplant `
  --input-dir data/user/experiments/<bundle_id> `
  --observation-policy-csv configs/runs/<policy>.csv `
  --prefix <run_id> --out-dir workspace/runs/<run_id>

python tools/parallel/run_parallel.py `
  --run-dir workspace/runs/<run_id> --case <run_id> `
  --mode ies --n-agents <并行数> --wait

python tools/check_run_quality.py `
  --run-dir workspace/runs/<run_id> --prefix <run_id>

python -m src.calibration.finalize_calibration `
  --run-dir workspace/runs/<run_id> --case <run_id>
```

S2–S4 必须从紧邻上游阶段的代表参数继承，并保留 manifest 和哈希。工程质量报告只说明运行完整；只有 `calibration_finalize.json` 能授权 `science_validated`。

### 3. 验证、条件参数集合和论文图

只有正式 finalize 通过后，才能运行 validation、posterior summary、候选解确定性复跑和正式论文导出。未验证数据必须显式使用 demo 开关，输出包含 `DEMO_` 前缀和水印，不能引用为论文图。

```powershell
python -m src.reporting.export_paper_data --help
Rscript paper/R/make_all.R --help
```

详细入口与状态门见 [用户指南](docs/敏感性分析与率定用户指南.md)。

## 关键科学约定

- PEST 权重为 `w = 1 / sigma`，因此 `Phi = Σ(w × residual)²`；禁止把 `1 / sigma²` 写入 weight。
- FileA/FileT 保留处理均值；原始重复另存长表，用于估计均值误差，不能伪装为多条独立 DSSAT 观测。
- 默认在原始物理尺度计算残差。log 变换必须同时作用于观测和模拟，并预声明 offset、reference 和 sigma 定义。
- 增量采收可进入率定；累计采收默认用于诊断，避免相关观测重复计权。
- calibration、validation、diagnostic 按完整处理划分，不随机拆散同一处理的时序行。
- IES 输出称为条件参数集合或近似后验；没有预测距离证据时不能宣称功能异参同效。

## 项目结构

```text
src/common/          公共契约和参数注册
src/dssat/           DSSAT 隔离运行
src/sensitivity/     Morris/Sobol
src/calibration/     PEST++ 构建、运行与 finalize
src/reporting/       指标、诊断和 R 数据导出
paper/R/             唯一论文成图入口
data/                原始输入、模板和参数范围
configs/             版本化运行配置
workspace/runs/      隔离运行及证据链（不入 Git）
docs/                当前规范、用户指南和历史归档
tests/               单元、集成和科研质量门测试
```

## 文档入口

- [文档索引](docs/README.md)
- [项目状态与正式科研启动清单](docs/项目状态与科研启动清单.md)
- [敏感性分析与率定用户指南](docs/敏感性分析与率定用户指南.md)
- [开发者指南](docs/DEVELOPER_GUIDE.md)
- [科研图表规范](docs/科研图表设计与开发计划.md)
- [历史归档](docs/archive/README.md)

发生冲突时，以根 README、文档索引列出的“当前规范”和代码质量门为准；`docs/archive/` 中的参数、边界、命令和科研结论只用于追溯。
