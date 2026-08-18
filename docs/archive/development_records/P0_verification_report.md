# P0 科研可信性修复验证报告

> 状态：实现与微型数值验收通过；等待用户验收
> 验证日期：2026-07-15
> 分支：`codex/p0-research-credibility`
> 基线快照：`fdfb5b1`

## 1. 结论

P0 已建立“参数写入—隔离 DSSAT—Morris/IES—科学质量门”的最小可信闭环。现在退出码 0 只代表流程完成；只有 `science_validated=true` 才允许进入科研解释。

本报告不批准正式 SA、正式率定或论文计算。当前 v14 frozen 仍被硬拒绝；新的正式边界、观测误差和阶段参数清单仍需用户审批。

## 2. 前后对比

| 检查 | P0 前 | P0 后 |
|---|---|---|
| 项目入口与路径 | 依赖 cwd、旧绝对路径和 `exec()` stub | 根目录统一解析；模块入口与兼容 stub 可从任意 cwd 调用 |
| 冻结边界 | 非法范围可继续进入构建 | 当前 v14 在生成 PST/运行前被 28 个 error 硬拒绝 |
| PEST weight | 多处使用 `1/sigma²` | 固化 `w=1/sigma`，并用手算 Phi 回归测试 |
| 动态变换 | Min–Max/log 可能产生尺度不一致 | 动态 Min–Max 与未审计 log 显式拒绝；pwtadj1 缺基线时失败 |
| DSSAT worker | 模型在共享 workspace 运行 | 每个运行目录拥有独立模板、试验、气象、土壤、可执行文件和 `CRD` |
| 输出有效性 | 可能回用旧文件 | `Evaluate.OUT` 必须是本次生成且非空；候选越界立即失败 |
| SA | 全零结果仍可生成排名 | 全零/非有限 Morris、Sobol 在排名前失败并写质量报告 |
| IES | 恒定 Phi 可被误读为收敛 | 检查先验、模拟观测、Phi、参数更新和迭代进展 |

## 3. 文件注入与真实 DSSAT 响应

文件级自动测试覆盖 CUL、ECO、SPE、SOIL 和 IC；同时验证了陈旧/空输出拒绝及固定宽度写入。真实配对运行均使用独立目录：

| 位置 | 扰动 | `Evaluate.OUT` 变化 | 证据 |
|---|---|---:|---|
| CUL | `LFMAX 1.27 → 1.50` | 10/10 数据行变化 | SHA256 `619339e2…` → `b26fcc78…` |
| ECO | `XFINT 0.12 → 0.30` | 10/10 数据行变化 | SHA256 `7e727dce…` → `f5c5c328…` |
| SPE | `KCAN 0.67 → 0.75` | 10/10 数据行变化 | SHA256 `7e727dce…` → `a63e0cdd…` |
| SOIL + IC | 第一层水分参数联合合法扰动 | 9/10 数据行变化 | SHA256 `7e727dce…` → `7f78d5f3…` |

SOIL/IC 测试只证明接口生效，不代表批准它们进入正式率定。

## 4. SA 与 IES smoke

### 4.1 Morris

运行目录：`workspace/runs/p0_morris_smoke`

- 5 个 active 参数，3 条 Morris 轨迹；
- 465 个参数—指标效应项全部有限；
- 305 项为实质非零；
- `process_completed=true`，`science_validated=true`。

历史全零 Morris 则被相同门禁拒绝，证明门禁同时覆盖正例与反例。

### 4.2 IES

运行目录：`workspace/runs/p0_ies_smoke_v4`

- 4 个 realization、5 个 adjustable 参数、1 次 assimilation iteration；
- 先验有 5 个变化参数列；模拟观测有 10 个变化列；
- Phi 相对离散度 `0.465455`；
- 参数 ensemble 最大可检测更新 `0.0771`；
- 所有 40 次前向运行完成；质量报告为 pass。

最佳 realization `2` 的独立确定性复跑得到 10 个 `ADAPS=38`，与 IES 保存的对应观测 ensemble 一致。

## 5. 自动验证

- `python -m pytest tests -q`
- `python -m compileall -q src tools tests`
- 标准入口帮助、任意 cwd 路径解析、冻结边界预检、权重审计、五类注入、质量门正反例均纳入回归或本地集成验证。

## 6. 保留限制与下一审批点

- 当前正式 v14 frozen 不可用于新计算；P0 没有替换它。
- smoke 使用的是仅供接口验证的临时小边界，不是生产边界。
- Morris smoke 只证明非退化，不构成稳定排名；多种子稳定性和 Sobol 收敛属于 P1。
- IES smoke 样本很小，只证明更新链路；不构成正式率定或后验推断。
- `flopy` 应随新依赖清单安装，以消除 `pyemu` legacy 模块警告。
- 正式进入 P1 前，需要用户审批新的 bounds proposal、土壤/IC 状态和正式 SA 参数范围。

建议验收口径：批准 P0 工程与科学质量门实现；保持正式 frozen 和历史科研结论停用；另行审批 P1 及新边界后再开始正式 SA。

## 8. 2026-07-15 防退化加固补充

在以 V14 作为测试参考时发现，原 `PHYSICAL_BOUNDS` 有一部分把 DSSAT 自带 TMGRO048 基线误判为越界。现已区分两类问题：

- 校验器误报已修正：硬安全包络现在包含 `WTPSD=0.004`、`SD-PM/FL-LF=400`、`SDPDV=111.4`、`PARMAX=41`、`PHTMAX=61`、`FINREF=220` 和 `EVMODC=0`；
- V14 frozen 的真实错误继续保留：5 个倒置边界、8 个初值不在候选范围、2 个 fixed 不恒定、3 个温度范围交叠和 2 个土壤水分范围交叠，共 20 个 error findings；另有 44 个 SOIL/IC active 警告。

新增回归门禁禁止：空边界表、active 零宽、空 `pargp`、构建器交换上下界或夹紧初值、IES 非有限模拟/Phi、重复 realization 以及超阈值 realization 丢失。

加固后的纯 Python 回归为 `66 passed`，迁移检查为 `9 passed`，`pip check` 无破损依赖。P1 基线前向模型产生 90/90 个有限输出。

基于 `proposal_from_sa_v14.csv` 生成了待审 `eggplant_p1_candidate_v1_20260715.csv`：57 个 CUL/ECO/SPE active，51 个 fixed，其中 44 个为 SOIL/IC。候选版本可以构建 57 参数、90 输出的 Morris 控制文件；基线中恒为 `-99` 的 MDAPS 已从当前默认输出移除。metadata 仍为 `pending`，因此正式 P1 readiness 按设计失败，未启动正式 Morris。
