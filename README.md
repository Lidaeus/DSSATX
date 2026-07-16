# Tomato_Cal：DSSAT 参数敏感性分析与率定工具

Tomato_Cal 面向作物模型研究者，目标是在 Windows 环境中提供可信、有效且易用的 DSSAT 参数敏感性分析（SA）与 PEST++ 参数率定工作流，并形成可复核、可复现、可用于论文写作的结果和图表。

本项目当前以茄子试验为主要用例。由于 DSSAT 4.8 没有独立的茄子模型，茄子与番茄共用 `TMGRO048.CUL/ECO/SPE` 和 CRGRO/Tomato 模型实现；参数登记中的 `crop` 字段用于区分作物参数集。

## 当前状态

- 代码已具备 DSSAT 运行、Morris/Sobol 分析、PEST++ IES 构建与结果整理的基础能力。
- 历史运行只能证明流程曾执行，不能证明其科研结论有效；P0 质量门现已能主动拒绝这些退化结果。
- 当前开发基线是 [产品定义与系统设计](项目重构规划.md)；详细风险和任务见 [P0 科研可信性修复开发计划](docs/P0_科研可信性修复开发计划.md)。
- P0 已在 `codex/p0-research-credibility` 实施并通过微型数值验证；后续批准的显式 log/处理均值 sigma 也已完成真实 DSSAT/PEST 冒烟，详见 [P0 验证报告](docs/reports/P0_verification_report.md) 与 [Observation Policy 验证记录](docs/reports/observation_policy_verification.md)。已有历史 SA 排名、率定最优参数或不确定性结果仍不得用于论文结论。
- 科研图表已冻结为“双轨制”：Python 只做 SA/率定运行诊断与论文数据导出，未来可能进入论文的图全部由 R 绘制；完整 Fig. 1–6/Fig. S1–S8 规划见 [科研图表设计与开发计划](docs/科研图表设计与开发计划.md)。
- P0 防退化加固已完成当前回归轮次。P1-R2 已修复旧 FileX 的 MF2 施肥行错序；P1-R3 进一步发现 `LAIXM` 实测/`LAIXS` 模拟字段混用和 DAP45 果实结构性零值，将正式候选契约收敛为10 TN/230响应。`XMAGE≥10、SLAREF≥260` v3 candidate 已通过独立 `r=8` 可行性预检，下一步须经用户批准冻结后，按“2个正式 seed 起步、稳定性不足时最多扩展到5个”执行。详见 [P1 科研分析启动计划](docs/P1_科研分析启动计划.md) 与 [P1-R3 预检报告](docs/reports/P1_R3_Morris可行性预检.md)。

## 产品原则

1. **科学有效优先于进程成功**：退出码为 0 只表示程序结束；质量门通过才表示结果可解释。
2. **每一步可追溯**：参数、观测、权重、随机种子、软件版本、命令和质量结论均进入运行清单。
3. **SA 与率定受控衔接**：SA 只产生候选建议，人工审核并冻结后才能进入率定。
4. **少而可辨识**：默认只率定有观测支撑且经 SA 筛选的参数；土壤和初始条件默认固定。
5. **率定与验证分离**：验证按完整处理或独立试验划分，不能随机拆散同一处理的观测行。
6. **论文产物由数据生成**：指标、图、表和方法说明均可由保存的运行产物重新生成。

## 目标工作流

```mermaid
flowchart LR
    A["原始数据与模板"] --> B["预检与基线模拟"]
    B --> C["Morris 筛选"]
    C --> D["Top-K Sobol 定量分析"]
    D --> E["人工审核并冻结参数边界"]
    E --> F["分阶段 PEST++ IES 率定"]
    F --> G["留出处理验证与确定性复跑"]
    G --> H["近似后验与异参同效分析"]
    H --> I["论文图表与可复现成果包"]
```

每个阶段都必须生成 `run_manifest` 和 `quality_report`。只有前一阶段质量门为 `pass`，下一阶段才可开始。

## 核心能力边界

| 能力 | 当前目标 |
|---|---|
| 参数治理 | 物理硬边界、基线建议、SA 提案和率定冻结边界分层管理 |
| 正向模拟 | 隔离运行 DSSAT，校验输出存在、完整、有限且随参数变化 |
| 敏感性分析 | Morris 初筛，Top-K Sobol 定量分析，包含重复种子和稳定性检查 |
| 参数率定 | 按物候、冠层/生长、产量等阶段进行 IES，控制维度和过拟合 |
| 观测与权重 | 明确单位、误差标准差、变换、相关性和用途；PEST 权重语义正确 |
| 不确定性 | 报告 IES 条件参数集合的近似后验特征，不夸大为严格贝叶斯后验 |
| 异参同效 | 联合参数分布、相关性、聚类/代表解和预测等效性分析 |
| 科研图表 | 矢量优先、色盲友好、灰度可辨、尺寸和字体可配置、图数一致 |

## 项目结构

```text
src/
  common/                 参数登记与共享约束
  dssat/                  DSSAT 正向运行
  sensitivity/            Morris/Sobol 工作流
  calibration/            PEST++ 任务构建与率定
  reporting/              Python 诊断、指标和 R 论文图数据导出
paper/R/                  唯一论文成图入口与统一 R 样式
data/
  raw/                    只读原始数据
  user/                   版本化用户 FileX/FileA/FileT/SOIL/气象输入包
  templates/              DSSAT 基线模板
  parameter_registry/     参数边界生命周期
configs/                  可版本控制的运行配置
workspace/runs/<run_id>/  隔离运行目录和完整证据链
tests/                    单元、集成与科学烟雾测试
docs/                     当前规范、开发计划和历史背景材料
```

## 关键科学约定

- `FL-VS` 固定为 `100.0`；`XFINT` 必须受数值安全边界约束。
- 参数冻结文件是率定可消费的唯一参数提案；不得自动选取“最新”SA 结果。
- 正式运行用 `--input-dir` 显式选择版本化用户输入包；当前待审包为 `data/user/experiments/xxql2501_20260716`，旧 `20260715` 包已停用。
- PEST 目标函数按 `Phi = Σ(w_i × residual_i)^2` 理解。若 `sigma_i` 是观测误差标准差，则基础权重为 `1 / sigma_i`，不是 `1 / sigma_i²`。
- 默认在原始物理尺度计算残差。任何对数等变换必须预先声明，并同时作用于观测和模拟；禁止用同批观测与候选模拟共同计算动态 Min–Max 范围。
- FileA/FileT 继续保存处理均值；原始重复另表保存并用于估计均值 sigma，不把同一处理重复作为共享同一个模拟值的独立 PEST 观测。
- 多次采收优先使用增量观测；累计观测仅作诊断，或在显式处理协方差时进入目标函数。
- IES 输出称为“条件参数集合”或“近似后验”，并同时报告先验、边界命中、收缩、相关性和预测覆盖。

## 环境与检查

运行与诊断主要依赖 Python 3.13+、`pandas`、`numpy`、`pyemu`、`flopy` 和 `matplotlib`。论文图另需 R 4.3+ 以及 `ggplot2`、`patchwork`、`jsonlite`、`svglite`。PEST++ 二进制位于 `pestpp-5.2.16-win/`，DSSAT 4.8 默认位于 `C:\DSSAT48\`。

依赖与代码级检查：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python -m compileall src tests tools
```

历史结果仅用于检查图表版式时，必须在数据导出和 R 绘图两端显式生成 DEMO：

```powershell
python -m src.reporting.export_paper_data --run-id eggplant_stage2_v14_full `
  --legacy-results-dir workspace `
  --phi-csv workspace/eggplant_stage2_v14_full.phi.actual.csv `
  --out-dir workspace/runs/figure_demo/paper_data --allow-unvalidated-demo

Rscript paper/R/make_all.R `
  --input-dir workspace/runs/figure_demo/paper_data `
  --out-dir workspace/runs/figure_demo/paper_figures `
  --allow-unvalidated-demo
```

持久化 IES 运行必须再执行科学质量门：

```powershell
python tools/check_run_quality.py --run-dir workspace/runs/<run_id> --prefix <prefix>
```

当前正式 `eggplant_v14_20260405` 冻结边界会被预检拒绝，这是预期行为；不得用 `--bounds-review-mode off` 绕过后开展正式计算。

## 文档入口

- [文档索引与规范层级](docs/README.md)
- [产品定义与系统设计](项目重构规划.md)
- [开发者指南](docs/DEVELOPER_GUIDE.md)
- [P0 科研可信性修复开发计划](docs/P0_科研可信性修复开发计划.md)
- [观测误差与权重设计](docs/权重设计方案改进提案.md)
- [近一个月可迁移成果整理（输入材料）](docs/近一个月可迁移成果整理.md)

## 明确不做

当前不建设通用云平台、可视化拖拽编排、多作物插件市场或复杂权限系统；也不以算法数量作为目标。只有在当前茄子/番茄案例通过科学质量门并稳定复现后，才考虑扩展作物和部署方式。
