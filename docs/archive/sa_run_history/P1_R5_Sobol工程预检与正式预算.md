# P1-R5 Sobol 工程预检与正式预算

> 状态：16参数清单已批准；Sobol工程预检通过；正式样本预算待审批
> 日期：2026-07-16
> 预检案例：`workspace/runs/p1_sobol_preflight_top16_n4_seed_20261114/`

## 1. 结论

用户继续推进后，上一轮推荐的16参数保守并集被固化为批准配置：14个 Morris 稳定核心加 `FL-SD`、`RTNH4` 两个 Top-15 边界参数。新的 Sobol 构建器只接受哈希匹配、状态为 `approved` 的清单，并把 frozen边界、输入包、230项输出、参数分布、随机种子、样本数和预期运行数写入 manifest。

真实 `N=4` 工程预检完成72/72个设计点，零模型失败，16个参数和230项响应全部按契约回收。Sobol运行审计、PEST++点估计复算和 bootstrap 程序均通过。该结果证明工程链路可进入正式阶段，但不构成任何参数敏感性结论。

`N=4` 中35/230项响应在两个基础样本矩阵上零方差；S1范围约为 `-141.543–63.318`，其中1213项为负、340项大于1；ST最高2.720，10项大于1。这是典型的小样本 Monte Carlo 不稳定，明确禁止用本预检进行排名、图表或论文解释。

## 2. 已批准参数集合

批准配置：

```text
configs/sa/approved_topk/
  eggplant_p1_sobol_top16_20260716.csv
  eggplant_p1_sobol_top16_20260716.json
```

参数为：`TRIFL, XFRT, TB2, RTNO3, FRLFF, LFMAX, EM-FL, XFINT, TO12, TO22, PM06, FRSTMF, TM2, NMOBMX, FL-SD, RTNH4`。

CSV按仓库 `.gitattributes` 的CRLF契约冻结，SHA-256为 `18e2cb97f6d8be6361940dff99c4df730450bde813d728f3667f9158dde1376b`。metadata同时绑定：

- frozen边界 SHA-256：`6b7e31248c7eb1aca173209bf9f8c5c2f86822be55ac4915e60803e58000674a`；
- 输出profile SHA-256：`46e8e539b3cfdf08dc2e747927b12adb9aab8e442b000a2e34d2798ee67e8ebd`；
- 输入manifest SHA-256：`5b7deac1502a5005cb46a1c2767a11d0567e13c094544f2faef3b9fdb950cb1b`。

任一内容变化都必须产生新的 approval ID，不能原地修改。

## 3. 本轮开发修复

### 3.1 案例构建

旧脚本允许任意Top-K CSV、原地修改 Morris 案例，并默认写入1000个基础样本。现改为：

- 只接受 `review_status=approved` 且CSV哈希匹配的审批文件；
- 在全新空目录构建，不覆盖 Morris 证据；
- 严格验证16个参数均为当前 frozen 中的 active 参数；
- 非Top-K参数固定为初值并把上下界收敛为该值；
- 重新读取写出的 `.pst`，确认可调参数集合与审批集合完全相等；
- 把审批文件快照、参数状态表和所有关键哈希复制到案例目录；
- 区分 `sensitivity_sobol_preflight_case` 与 `sensitivity_sobol_formal_case`，预检最多16个基础样本，正式案例最少32个。

### 3.2 运行与质量门

旧并行控制器把所有 `pestpp-sen` 案例都按 Morris 审计，导致 Sobol 即使正常完成也会因没有 `.mio` 而成为 `not_assessed`。现根据 `.pst` 的 `gsa_method` 路由：

- Morris继续检查轨迹和 elementary effects；
- Sobol检查完成标记、预期运行数、参数/输出run_id对齐、模型失败、有限值、DSSAT `-99`、230项响应、16参数、S1/ST矩阵完整性和非退化；
- controller丢失后的离线 finalize 同样采用方法特异审计，且不会重跑模型；
- 正式 Sobol 要求全部基础响应具有非零方差，预检只记录零方差数量且禁止解释指数。

### 3.3 bootstrap不确定性

新增程序从 `.sobol.par.csv` 验证 A、B 和16个混合矩阵的结构，再从 `.sobol.obs.csv` 重算：

```text
S1_i = mean[B × (AB_i - A)] / Var(A, B)
ST_i = 0.5 × mean[(A - AB_i)²] / Var(A, B)
```

预检中195项具有基础方差的响应×16参数，共3120组重算值全部在导出精度容差内复现 PEST++；200次 bootstrap 的最低有效重采样比例为0.995。35项零方差响应不生成伪置信区间。

正式案例拟使用1000次确定性 bootstrap，并保存 S1/ST 点估计、标准误和95%百分位区间。bootstrap只能量化给定采样设计的 Monte Carlo 不确定性，不能消除模型结构和输入数据不确定性。

## 4. 真实预检结果

| 项目 | 结果 |
|---|---:|
| 可调参数 | 16 |
| 基础样本 N | 4 |
| PEST++预期设计点 | `4×(16+2)=72` |
| 成功设计点 | 72/72 |
| 模型失败 | 0 |
| 回收响应 | 230/230 |
| 有限模拟值 | 16560/16560 |
| DSSAT缺失哨兵 | 0 |
| S1/ST有限值 | 7392/7392 |
| 基础方差可估响应 | 195/230 |
| bootstrap点估计复现 | 3120/3120 |
| 运行墙钟时间 | 约81秒（6 agents，本机） |

`scientific_status=validated` 在此仅表示“预检类型所声明的工程门通过”。manifest中的 `run_type=sensitivity_sobol_preflight_case` 会阻止该案例进入正式排名或论文数据出口。

## 5. 推荐正式自适应预算（待审批）

建议保持16参数、均匀分布和同一随机种子，按基础样本数递增：

| 阶段 | N | PEST++设计点 | 目的 |
|---|---:|---:|---|
| SBL-1 | 64 | 1152 | 首个正式估计、失败域和区间宽度检查 |
| SBL-2 | 128 | 2304 | 与N=64比较排名和过程组稳定性 |
| SBL-3 | 256 | 4608 | 仅在前两级未稳定时扩展 |

初始预算为3456次DSSAT候选运行，最大预算8064次。按本机预检吞吐粗略外推，前两级约65分钟，增加N=256后累计约2.5小时；正式耗时以实际manager记录为准。

每一级必须满足：

1. 全部设计点成功，230项响应有限、无 `-99`，参数和输出矩阵完整；
2. 230项基础响应全部非零方差；若少数离散端点仍零方差，应先判断结构性含义并单独审批，不得填零后继续；
3. PEST++ S1/ST与原始矩阵重算100%一致；
4. 1000次 bootstrap最低有效比例不低于95%；
5. N=64与N=128的四过程组等权综合ST排名 Spearman不低于0.95，Top-8 Jaccard不低于0.75，Top-8最大名次变化不超过2；
6. 若任一稳定性门失败，才执行N=256；N=128与N=256仍不稳定时停止，不发布正式排名并复核响应定义或采样预算。

过程组综合继续沿用 Morris 的防维度偏置原则：响应内归一化，处理/DAP在特征族内等权，最后对物候、冠层、生物量、产量/采收四组等权。S1、ST和 `ST-S1` 明细始终保留，不用综合分数替代单响应机制解释。

## 6. 下一审批点

建议批准上述 `N=64 → 128 → 必要时256` 自适应预算、同一16参数均匀分布、1000次bootstrap和稳定性阈值。批准前不启动正式Sobol；旧脚本的默认 `N=1000` 不再视为有效计划。

## 7. 关键证据哈希

| 产物 | SHA-256 |
|---|---|
| `run_manifest.yaml` | `76292dcaa6503ed0b86cd96d4361d65bad589e9901496218e3dad74af4b0dfd3` |
| `run_status.json` | `ec5e46fbbaf9dbde94263d75aca463a2e33a4182ecc4e2ab762af52d0785e3bb` |
| `sa_sen_sobol.pst` | `8e31e93bcdffb674fde0b47b8ff7ccacbf607f4fdf94bfd1674b1a6a413dc2f8` |
| `sa_sen_sobol.sobol.par.csv` | `681091c98f3942a29b380ac0e73be3a806ed66ada18406f5da07f70794535713` |
| `sa_sen_sobol.sobol.obs.csv` | `f4cf8a0f7b222c35533f366767b8cb5911802d55bf779c76d94c8aadadc4b058` |
| `sobol_run_quality.json` | `e679e5fdf9d0724e1d6f3dac8550fc6394179809ac78955f681f646a145fbca9` |
| `sobol_bootstrap_quality.json` | `354ab6658cb441b928ebb4eaab64778fda2126560004906b8223e9a93e2ecf10` |

预检案例由干净提交 `373b4ff` 构建和执行；增强的方差/重采样审计由干净提交 `4989617` 生成，两个审计manifest均记录源码提交和dirty状态。
