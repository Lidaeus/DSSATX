# P0 科研可信性修复基线审计

> 状态：已固化
> 审计日期：2026-07-15
> 升级前快照：`fdfb5b1`（`chore: snapshot project before P0 credibility upgrade`）

## 1. 环境与基线

- 操作系统：Windows；Python 3.13.12。
- DSSAT：`C:\DSSAT48\DSCSM048.EXE` 存在。
- PEST++：仓库捆绑 5.2.16；本地 `pestpp-ies` 微型运行可执行。
- P0 开始前测试：18 项通过，但未覆盖前向模型响应、全零敏感性和恒定 IES 的科学失败。
- 系统 Python 有 `pyemu 1.4.0`；项目旧 `.venv` 缺少 `pyemu`。P0 新增可重建依赖清单，当前系统环境仍提示缺少可选的 `flopy` legacy 支持。

## 2. 已固化的失败证据

### 2.1 冻结边界

`eggplant_v14_20260405.csv` 经统一 validator 检出 28 个 error，覆盖：反向上下界、初值越界、fixed 不一致、物理硬边界、温度顺序和土壤水分关系。该文件保持原样，P0 未自动交换边界、扩界或生成新的正式 frozen。

### 2.2 历史 Morris

`workspace/runs/test_sa_workflow` 的进程虽然完成，但效应结果全零。P0 质量门对该结果返回：

- `process_completed = true`
- `science_validated = false`
- 失败项：`morris_non_degenerate`

### 2.3 历史 IES

`workspace/runs/eggplant_stage2_v14_improved` 中 39 个先验参数存在离散度，但 200 个模拟观测没有实质离散度，Phi 基本恒定且参数未更新。P0 质量门返回：

- `process_completed = true`
- `science_validated = false`
- 失败项：`ies_simulation_variation`、`ies_phi_variation`、`ies_parameter_update`

## 3. 基线结论

历史结果只能用于故障复盘，不能用于论文中的敏感性排名、推荐参数或不确定性结论。P0 的修复目标不是改善历史数值，而是使同类退化结果在进入解释和制图前强制失败。

