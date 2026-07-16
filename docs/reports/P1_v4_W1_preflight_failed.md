# P1 v4 — W1 r=8 扰动预检报告

> 任务ID：W1（v4 `r=8` 扰动预检）
> 结论：**失败（`failed`）**。464/464 DSSAT 运行成功完成，但全部 164 项响应在所有参数扰动下零方差；根因是 DSSAT 运行时未读取项目注入的 CUL/ECO/SPE 文件，对所有候选参数产生固定输出。**未通过 W1 科研门禁，不得进入 W2 正式 Morris。**
> 运行日期：2026-07-17
> 案例：`workspace/runs/p1_wn_v4_preflight_r8/`
> 源码提交：`d5e1c0a`（W0 集成检查点）
> 结果标记：`engineering_preflight` / `failed`（不作为正式排名，不进入论文图表）

## 1. 执行可追溯性

| 项 | 值 |
|---|---|
| 输入包 | `data/user/experiments/xxql2501_sa_counterfactual_v1_20260716` |
| 冻结 bounds | `eggplant_p1_xxql2501_v3_20260716`（57 active） |
| 输出 profile | `configs/sa/eggplant_p1_outputs.json`（164 项，双域） |
| input_manifest SHA-256 | `bdede79d723cfbf02e8517a86c56d6c6c1693c26a950fff83e7f104133ef7d77` |
| bounds SHA-256 | `6b7e31248c7eb1aca173209bf9f8c5c2f86822be55ac4915e60803e58000674a` |
| output_profile SHA-256 | `0923aa1ed16627243da8a2d50a63209bc9ba3fcb19f9e42d7e38b71ced9e27dc` |
| Morris 规模 | `r=8, p=6, delta=0.6`，理论 464 设计点 |
| 随机种子 | `20260716` |
| 并行配置 | 6 agent，PESTPP-SEN 模式 |

三个核心 SHA 与 W0 检查点（`docs/reports/P1_v4_W0_integration_checkpoint.md`）完全一致。案例在 W0 干净提交 `d5e1c0a` 之后构建；manifest 的 `git_dirty: true` 仅由未跟踪的 `workspace/formal_source_66513df/` 源码快照引起，不涉及任何代码、配置或输入。

## 2. 运行层门禁（`morris_run_quality`）—— 全部通过

| 检查 | 结果 | 阈值 |
|---|---|---|
| process_completed | pass | completed / 0 not_finalized |
| morris_no_runtime_failures | pass (0) | 0 |
| morris_no_model_failures | pass (0) | 0 |
| morris_complete_trajectories | pass (8/8) | 8 |
| morris_balanced_effect_coverage | pass (每参数 8 effects) | 8 |
| morris_final_summary_exists | pass (.mio 存在) | true |
| morris_design_structure | pass (每步只变一个参数) | 0 |

464/464 设计点成功，6 agent 全部正常退出，PEST++ manager 退出码 0，无运行时/模型/未知失败。从运行调度层面看，W1 流程本身是健康的。

## 3. 结果层门禁（`morris_result_quality`）—— 失败

| 检查 | 结果 | 阈值 |
|---|---|---|
| process_completed | pass (9348 effects) | ≥1 |
| morris_finite | pass (9348/9348) | 9348 |
| **morris_non_degenerate** | **fail (actual=0)** | ≥1 |
| **morris_output_non_degenerate** | **fail (degenerate_count=164)** | 0 |

**全部 164 项响应都被判为退化（零方差）。** `sa_sen_morris.mio` 的 9348 行（57 参数 × 164 响应）中，`sen_mean_abs` 与 `sen_std_dev` 全部为 0。这意味着同一个参数向量在不同设计点产生的 DSSAT 输出完全相同，所以每条 elementary effect = 0。

零方差响应覆盖全部 8 个核心处理（TN2/3/4/5/10/11/12/13）的全部 17 项基础响应，以及 28 项水/氮/水×氮派生响应 —— 完整清单见 `workspace/runs/p1_wn_v4_preflight_r8/morris_audit/morris_result_quality.json`。

## 4. 根因诊断

零方差意味着前向模型对参数扰动无响应。为了区分"参数域内真实不敏感"与"参数注入失败"，在 W1 案例 SHA 不变的前提下做了独立的 DSSAT 注入链验证（产物保留在 `workspace/runs/p1_wn_v4_preflight_r8_debug/`）：

### 4.1 注入链写入侧——正常

`src/dssat/run_dssat.py::update_cul_file()` 正确读取参数 CSV 与 `workspace/TMGRO048.CUL.base`，把冻结初值写入 `workspace/TMGRO048.CUL`。三份 CUL 的 TM0008 行对比：

| 位置 | LFMAX | EM-FL | 来源 |
|---|---|---|---|
| `workspace/TMGRO048.CUL`（run_dssat 写入） | 1.27 | 26.0 | 注入后初值 |
| `workspace/TMGRO048.CUL.base`（模板） | 1.27 | 23.3 | 冻结边界初值 |
| `C:\DSSAT48\TMGRO048.CUL` | 1.11 | 20.0 | DSSAT 自带旧值（与项目无关） |

注入侧写入正常，问题不在 `run_dssat.py` 的参数格式化或固定宽度替换。

### 4.2 DSSAT 读取侧——失败

四组独立扰动测试，每组都用同一个 `baseline` 参数 CSV 触发 `run_dssat.py`，但手动修改 DSSAT 实际可能读取的 CUL 位置，然后 diff 两次 `Evaluate.OUT`：

| 测试 | 扰动位置 | 扰动参数与幅度 | `Evaluate.OUT` 差异 |
|---|---|---|---|
| A | `C:\DSSAT48\Genotype\TMGRO048.CUL` | LFMAX 1.27→1.36 | 无（字节相同） |
| B | `C:\DSSAT48\Genotype\TMGRO048.CUL` | EM-FL 23.3→31.0（物候大扰动） | 无 |
| C | `CRD` 重定向到隔离目录 + 该目录 CUL | LFMAX 1.27→5.00（4 倍极端） | 无 |
| D | 项目根 CWD `./TMGRO048.CUL` | LFMAX 1.27→5.00 | 无 |

**四组测试 `Evaluate.OUT` 全部字节相同**（`diff` 退出码 0）。即便 LFMAX 放大 4 倍这种会显著改变光合作用的极端扰动，DSSAT 输出也纹丝不动。

### 4.3 DSSAT 确实在运行

- agent worker 日志显示每次 run 耗时 3–7 秒，DSCSM048.EXE 正常调用；
- `PlantGro.OUT` 含完整每日动态（LAI、LWAD、SWAD、CWAD 逐日变化），说明 DSSAT 物理模型在跑；
- `_assert_fresh_nonempty` 时间戳门禁通过，输出非陈旧；
- `Evaluate.OUT` 的 10 个处理（TN2/3/4/5/9/10/11/12/13/14）模拟值在物候（ADAPS=23）和生物量（CWAMS≈6000）上几乎相同，无视水氮差异——这本身就是参数未生效的强信号。

### 4.4 P0 微型验证案例对比——决定性证据

P0 计划 §2.3 记录的"全零 Morris"问题在 P0 修复后曾通过微型验证（`workspace/runs/p0_dssat_perturbed/`），那次验证确实产生了非零响应（baseline `LFMAX=1.27` 与 perturbed `LFMAX=1.50` 的 `Evaluate.OUT` 不同：baseline TN2 `CWAMS=5247, ADAPS=36`，perturbed 不同）。对比两个案例的 DSSAT 运行配置：

| 配置项 | P0 微型验证（曾成功） | v4 SA W1（失败） |
|---|---|---|
| 运行 CWD | `workspace/runs/p0_dssat_perturbed/` | `workspace/runs/p1_wn_v4_preflight_r8/_agents/agent_XX/_sa_tmp_runs/run_XXX/`（临时目录） |
| `DSSATPRO.v48` 的 CRD | `D:\Tomato_Cal\workspace\runs\p0_dssat_perturbed`（指向案例自身目录） | `run_dir`（临时目录，由 `_write_dssatpro_with_crd` 改写） |
| `TMGRO048.CUL/ECO/SPE` 位置 | **在 CRD 目录内**（与 CRD 指向相同） | 写入项目 `workspace/`（CWD 相对路径），**不在 `run_dir` 内** |
| 结果 | DSSAT 读到扰动 CUL，输出随参数变化 | DSSAT 在 `run_dir`（空）找不到 CUL，回退到默认位置读旧 CUL，输出固定 |

### 4.5 根因结论——`_sync_genotype_files_to_run_dir` 未被调用

代码层面的精确根因：

```text
src/dssat/run_dssat.py:806  def _sync_genotype_files_to_run_dir(src_dir, run_dir):  ← 已定义
                            （全仓库唯一引用就是这一定义行，从未被任何流程调用）
src/dssat/run_dssat.py:1663 def update_cul_file(...):  → 写入 CUL_FILE = "TMGRO048.CUL"（CWD 相对路径）
src/dssat/run_dssat.py:2552 _write_dssatpro_with_crd(...)  → CRD 改写为 run_dir
```

执行链：
1. `sa_model.py` 在临时 `run_dir` 内以 `cwd=run_dir` 调用 `run_dssat.py`；
2. `run_dssat.py::update_cul_file()` 把含扰动参数的 CUL 写到 CWD（即 `run_dir`）—— 但 PEST++ 的工作目录约定下，CWD 实际是 agent 目录而非 `run_dir`，且即便写到 `run_dir`，CRD 也只指向 `run_dir` 根目录；
3. `_write_dssatpro_with_crd()` 把 `DSSATPRO.v48` 的 CRD 改写为 `run_dir`，并写到 `run_dir/DSSATPRO.v48`；
4. **但 DSCSM048.EXE 在 `run_dir` 启动时，CUL/ECO/SPE 并不在 `run_dir` 内**（`_sync_genotype_files_to_run_dir` 本应完成这一复制，却从未被调用）；
5. DSSAT 按 CRD 在 `run_dir` 找不到 CUL，回退到某个默认位置（可能是 `C:\DSSAT48\Genotype` 或 EXE 同目录的缓存），读到的永远是旧 CUL，所以 464 次运行输出完全相同。

P0 微型验证之所以成功，是因为它的 `run_dir` 就是含 CUL 的案例目录本身（CWD = CRD 目录 = CUL 所在目录），三者在同一目录下，不需要 `_sync_genotype_files_to_run_dir`。v4 SA 的多 agent 隔离架构打破了这一假设：每个 agent 在独立临时 `run_dir` 内跑 DSSAT，但 CUL 从未被复制进去。

这是一个**运行编排层缺陷**，不是 SA 输出契约（164 项）、bounds（57 active）、输入包（SA 反事实 v1）或 DSSAT 安装的问题。W1 预检正是为暴露这类问题而存在，它在浪费正式预算前成功拦截了。

## 5. 与历史问题的关系

P0 计划 §2.3 记录过同一现象："408 个 Morris 模型运行进程退出码为 0，但全部 elementary effects、均值绝对敏感度和标准差均为 0。" P0 的修复集中在注入链代码、bounds 合法性和质量门禁，并验证过"真实 DSSAT 参数响应、非退化 Morris 微型验证"（`docs/reports/P0_verification_report.md`）。W1 暴露的失败表明，P0 的微型验证可能使用了不同的 DSSAT 调用路径或参数子集，没有覆盖到 v4 SA 完整 57 参数×8 处理×164 响应下的 DSSAT genotype 读取行为。需要复核 P0 验证案例与 v4 SA 案例的 DSSAT 调用差异。

## 6. 已保留的证据产物

| 产物 | 路径 |
|---|---|
| 运行案例 | `workspace/runs/p1_wn_v4_preflight_r8/` |
| 运行审计 | `…/morris_audit/morris_run_audit.json`、`morris_run_quality.json`、`morris_result_quality.json`、`morris_trajectory_status.csv`、`morris_effect_coverage.csv`、`morris_failures.csv` |
| PEST++ 产物 | `…/sa_sen_morris.{pst,mio,rec,rmr,rns,raw.csv,group.msn,group.raw.csv}`、`sa_sen_morris.sen.par.csv` |
| 注入链验证 | `workspace/runs/p1_wn_v4_preflight_r8_debug/`（4 组 diff 测试的 baseline/perturbed `Evaluate.OUT`、CUL 备份、DSSATPRO 备份） |
| 运行日志 | `workspace/runs/p1_wn_v4_preflight_r8_w1_run.log` |

DSSATPRO.v48 与 `C:\DSSAT48\Genotype\TMGRO048.CUL` 在每次测试后均已从备份恢复到原始内容；未对 DSSAT 安装做持久修改。

## 7. 未解决风险与审批边界

本失败**不修改** v4 SA 输出契约（164 项）、bounds（57 active）或输入包（SA 反事实 v1）。这些契约本身在 W0 已通过基线验证（DSSAT 基线 164/164 项有限、0 个 `-99`），W1 失败不推翻契约设计。

按 `docs/P1_v4_下一阶段协作执行计划.md` §4"集成门与审批边界"，以下事项需要用户审批后才能继续：

1. **DSSAT genotype 读取路径的修复方案**。这是运行环境层问题，可能涉及：
   - 确认 DSSAT v4.8 batch mode（`DSCSM048.EXE B DSSBatch.v48`）实际查找 CUL 的路径规则；
   - 是否需要把 CUL/ECO/SPE 显式复制到 DSSAT 启动 CWD（注意 `_sync_genotype_files_to_run_dir` 已定义但**从未被调用**，可能是预期调用点缺失）；
   - 是否需要在 `DSSATPRO.v48` 之外配置环境变量或调整 DSSAT 调用方式；
   - 是否需要回溯 P0 微型验证案例，确认它当时是如何让 DSSAT 读到扰动 CUL 的。
2. **修复后的 W1 重跑**。修复方案确认后，必须从干净检查点重建 W1 案例并重跑 464 设计点；不得在当前失败案例上"打补丁"续跑。
3. **是否复核 P0 验证报告**。若 P0 微型验证与 v4 SA 用了不同的 DSSAT 调用路径，P0 的"非退化验证"证据需要重新审视。

**在用户批准修复方案前，不进入 W2 正式 Morris，不修改 164 项契约，不调整门禁阈值，不删除零方差响应。** 当前 `.mio` 全零结果仅供失败诊断，不作为正式参数排名，不进入 Fig.1/S1/S2。

## 8. 下一步建议（供用户决策）

- **优先级最高**：在 `run_model()` 的 `subprocess.run([exe_path, "B", batch_arg], cwd=run_dir)`（`src/dssat/run_dssat.py:2592`）**之前**补一次 `_sync_genotype_files_to_run_dir(workspace_dir, run_dir)` 调用，把 `workspace/TMGRO048.{CUL,ECO,SPE}` 复制到 `run_dir`。这样 DSSAT 在 `run_dir`（CRD 指向目录）内就能读到含扰动参数的 CUL。注意 `update_cul_file/update_eco_file/update_spe_file`（L2695–2698）当前写入的是 CWD 相对路径，需确认在 `sa_model.py` 调用链下 CWD 与 `workspace_dir` 的关系，或直接让 `update_*_file` 写入到 `run_dir`。
- 修复后新增一条回归测试：扰动一个强敏感参数（如 `EM-FL` 或 `LFMAX`），断言 `Evaluate.OUT` 的 `ADAPS`/`CWAMS`/`LAIXS` 等关键列在两次运行间发生数值变化（`diff` 退出码非 0）。这条测试应加入 W1 重跑的前置门禁，杜绝"运行成功但参数未生效"的静默失败再次发生。该测试还应断言 `run_dir/TMGRO048.CUL` 的存在与 mtime 新于 run 开始时间。
- 复核 P0 微型验证案例（`p0_dssat_perturbed`）为何能在没有 `_sync_genotype_files_to_run_dir` 的情况下成功——原因是它的 CWD=CRD 目录=CUL 所在目录，三者重合。v4 SA 的多 agent 临时目录架构不满足这一重合，所以必须显式同步。P0 的成功不应被解读为"`_sync_genotype_files_to_run_dir` 是死代码可以删除"，而应理解为"P0 的运行目录布局恰好绕过了这一缺陷"。
- 修复落地后，从干净检查点重建 W1 案例并重跑 464 设计点；不得在当前失败案例上打补丁续跑。重跑前先做一次单 agent 烟雾测试（如 `r=1`），确认至少一个强敏感参数的 elementary effect 非零，再启动完整 `r=8`。
