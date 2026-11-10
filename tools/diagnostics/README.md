# DSSAT 运行诊断绘图工具 · macOS

适配自 2026-11-08 交接包 `DSSAT_diagnostics_macOS_20261108.zip`
（sha256 `8773bbcd…409b7ee`；原包解压于 `.local/incoming/`，含 20MB 的
V7 样例数据 `examples/v7`，未纳入仓库）。绘图读取已生成的 DSSAT 原生
输出或实测／模拟配对表。Python 诊断文件统一使用 `diagnostic_*`。

## 安装

本目录已并入 Tomato_Cal，直接用项目 venv（依赖与 requirements.txt 一致）：

```bash
cd ~/dev/Tomato_Cal
.venv/bin/python tools/diagnostics/atlas/test_contract.py
.venv/bin/python tools/diagnostics/diagnostics.py yield --help
```

每次使用新的输出目录。诊断程序不会覆盖已有图表。

## 1. 最终鲜产对施氮的响应

重点输出是 `diagnostic_nitrogen_yield_response.png`。横坐标为 N0–N3，季节分面、共享产量纵轴，点形区分水处理。空心点和连线为模拟，实心点为实测。缺少的氮水平在固定横坐标上留空。图下方按水处理同时列出模拟和实测的 N3−N2，单位 kg/ha。附表保存逐处理的实测、模拟、残差以及 N3−N2 和 N3−N0。季节拟合表提供样本量、RMSE 和平均偏差，残差方向为模拟减实测。

用自带的两春季样例快速复现

```bash
python diagnostics.py yield \
  --terminal examples/terminal/terminal_fresh_yield_for_plot.csv \
  --metadata examples/terminal/treatment_metadata.csv \
  --out outputs/example-yield \
  --label 'Archived trial | 152/200 retained, 98% gate missed'
```

`--terminal` 直接使用项目率定报告生成的终点鲜产表。表中的 `obs_t_ha` 和 `sim_t_ha` 已是 t/ha。若手头是当前运行的 `comparison.csv` 或 `all_observed_simulated_pairs.csv`，可改用 `--comparison`，程序读取 CHFPW 累计鲜产，优先取明确标记的 `FINAL_FRESH_YIELD`，否则取每处理最后一条实测配对日期。配对表源值应为 kg fresh/ha。

### 刚跑完 DSSAT 时

```bash
CASE="/path/to/current/run"
META="/path/to/treatment_metadata.csv"
OBS="/path/to/observation_or_comparison.csv"

python diagnostics.py yield --case-dir "$CASE" --season 26SP \
  --metadata "$META" --comparison "$OBS" --out outputs/current-yield
```

此模式从**本次运行**的 `FreshWt.OUT` 读取 CHFPW，`--comparison` 只提供实测和日期。程序核查实测终点日期存在，并且其模拟累计值与运行终点一致。对模拟单独诊断时可省略 `--comparison`。如需两季并排，从已配对的两季终点表或比较表进入。切勿把 `CHPDT` 累计干产和 `HFPOW` 单次鲜产当成终点累计鲜产。

处理映射 CSV 提供 `treatment,water_level,nitrogen_level`，多季还需 `season_id`。推荐提供原生 `treatment_label` 做交叉核查。每季每个水氮组合只对应一个汇总处理。程序会核查映射覆盖和重复处理，并保留 `dataset_role`（若有）。

## 2. 任意内部变量的逐日图

```bash
python diagnostics.py daily --case-dir examples/v7 --season 26SP \
  --metadata examples/v7/treatment_metadata.csv \
  --file PlantNIntegration.csv \
  --field 'QNO3:g N/m2' --field 'A_NO3:g N/m2/day' \
  --out outputs/example-daily
```

重复 `--field` 可画多个字段，冒号后是可选的显示单位。横坐标用 `PlantGro.OUT` 的 DAP，按运行号和日期对齐。图的空白表示当天没有该字段的值。常用输入如下。

| 看什么 | 文件与字段举例 |
|---|---|
| 冠层与原生胁迫 | `PlantGro.OUT` 中的 `LAID, LWAD, SWAD, NSTD, WSPD, WSGD` |
| 同化、氮库与氮状态 | `PlantNIntegration.csv` 中的 `QNO3, QNH4, A_NO3, A_NH4, Norg_leaf, NNI_functional_leaf` |
| 叶面积与光合碳 | `PlantNLAI.csv` 中的 `new_leaf_area, LAI_end`，以及 `PlantCCash.csv` 的 `PG` |
| 分层根吸收 | `LayerNIntegration.csv` 的 `NO3_final_gN_m2`，加 `--layer 1` 等指定层 |
| V15 S1 等旧版 | 同样可画其 `OrganNState.csv`、`NFlux.csv`、`RootNSupply.csv` 的原生列。内部变量沿用各版本自己的字段定义 |

该入口需要 CSV 含 `run,yrdoy` 且按运行／日期唯一。分层表可先选一层。具有多个事件或器官记录的长表应先提取到这个粒度。DSSAT OUT 文件通过 CRGRO 的 RUN、TREATMENT、YEAR 行解析。

## 3. 定制氮引擎的完整图册

```bash
python atlas/make_atlas.py --case-dir examples/v7 \
  --metadata examples/v7/treatment_metadata.csv \
  --label 'V7 area-N quadratic test · 26SP' --out-dir outputs/example-atlas
```

全套输出位于 `outputs/example-atlas/figures/diagnostic_atlas.pdf`。涵盖根吸收、氮状态、等效无机 Q 库、有机储备、同化与碳预算、器官浓度、LAI、光合与分批采收。图册按 W1–W3 和 N0–N3 排版，需要当前定制引擎的 `PlantNIntegration.csv` 和 `PlantCCash.csv` 等。原生 DSSAT 或 V15 S1 用上面的逐日入口，并按该版本已有变量画图。

完整图册默认读取运行目录下与本次运行匹配的 `comparison.csv`。也可用 `--comparison` 显式指定。新运行只有原生输出时，用 `--simulation-only` 绘制内部变量与模拟采收，再用第 1 节的命令单独对照实测。勿把旧的模拟列作为本次运行的配对数据。若中文字体未自动找到，设置 `DSSAT_DIAGNOSTIC_FONT` 为本机中文字体文件的完整路径，例如在系统有该文件时

```bash
export DSSAT_DIAGNOSTIC_FONT="/System/Library/Fonts/Supplemental/Songti.ttc"
```

## 样例与验证

- `examples/terminal` 是 2026-11-08 的两春季历史试验诊断数据，覆盖 20 个水氮处理。原报告中该试验保留 152/200 个成员，未达到原 98% 门槛。随包预览仅用于核查出图口径。
- `examples/v7` 是 2026-11-04 V7 面积氮二次试验的 26SP 原生输出，12 处理 × 126 天。保留绘图所需文件和匹配的 612 项比较表。大体积 P0Trace 未随样例附带，缺少的日内量会在图册中标注或留空。
- 产量图整理自原 `tools/calibration/plot_diagnostic_custom.py` 的施氮响应设计。完整图册沿用已有 `research/n_diagnostics` 代码，并增加独立配置和仅模拟入口。
- 在 Windows 上验证了历史终点表、直接比较表、原生终点、逐日及逐层图，以及带实测和仅模拟的 23 页图册。macOS 上的首次运行请按本页命令验证。仅完整中文图册需要 CJK 字体。
