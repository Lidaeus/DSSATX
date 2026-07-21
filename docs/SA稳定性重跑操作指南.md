# Morris 与 Sobol 稳定性重跑

本入口只处理当前证据中明确需要扩大规模的两项，不会覆盖既有 Morris r=10/r=20、Sobol N=64/N=128 或其论文图表数据。

| 分析 | 原因 | 本次重跑 | 新结果位置 |
|---|---|---|---|
| Morris | XXQL2502 水氮响应域的 Top-15 成员边界不稳定 | 三个既定随机种子、`r=40` | `workspace/runs/morris_results_stability_rerun_v1/XXQL2502/r40/` |
| Sobol | XXQL2501 的 N64→N128 未达到预设收敛阈值；其他季节需形成同尺度审查 | 三季均以当前 N=128 为基线，新增 N=256，并分别比较 N128→N256 | `workspace/runs/sobol_stability_rerun_v1/<season>/convergence_n0128_n0256/` |

## 一键启动

运行前请先提交或暂存当前工作树中的预期代码改动。正式案例构建会拒绝 dirty worktree，以免结果无法映射到唯一提交。

双击 [start_stability_rerun.cmd](../tools/sa/start_stability_rerun.cmd)，或在项目根目录执行：

```powershell
python tools/sa/rerun_unstable_sa.py --all
```

运行使用 6 个并行 agent；各案例按顺序启动，避免端口与 DSSAT 资源冲突。预估新增计算量为 Morris 6720 次模型调用（3×40×56），Sobol 19200 次模型调用（3×256×25）。

## 安全与恢复

先检查不写入文件的执行计划：

```powershell
python tools/sa/rerun_unstable_sa.py --dry-run --all
```

中断后查看状态并继续未完成案例：

```powershell
python tools/sa/rerun_unstable_sa.py --status
python tools/sa/rerun_unstable_sa.py --all
```

脚本只跳过已经完成的案例；发现非空但缺少预期构建文件的目录会停止，而不会覆盖或混合运行。退出码 `0` 表示所有预设稳定性/收敛门通过；退出码 `2` 表示运行和汇总已完成、但至少一个门仍未通过，应检查对应 JSON/CSV 后再决定是否扩大规模。

配置和完整路径固定在 [stability_rerun_v1_20260722.json](../configs/sa/stability_rerun_v1_20260722.json)。如需改变样本量、种子、边界或输入包，应创建新的审批配置，不要直接修改已经启动的配置。
