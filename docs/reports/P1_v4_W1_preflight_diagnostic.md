# P1 v4 — W1 预检诊断报告

> 任务ID：W1（SA v4 `r=8` 扰动预检）
> 结论：**阻塞**。PESTPP-SEN 语义已通过 smoke 验证澄清（计划命令正确，464 设计点）；但 DSSAT 输出读取存在格式错配 bug——`sa_model.py` 读 `PlantGro.OUT`/`FreshWt.OUT`/`Evaluate.OUT`（原始 DSSAT 输出），而 `run_dssat.py` 只保留 `Pest*.OUT`（PEST 格式输出）并清理原始文件，导致 164 项输出全部为 `-99`。DSSAT 本身运行正常并产生了真实数据（已在 `Pest*.OUT` 中验证）。
> 标注：`engineering_preflight`（诊断）；预检结果不得用于论文排名。
> 更新日期：2026-07-17

## 1. PESTPP-SEN `gsa_morris_p` 语义澄清（已解决）

### 矛盾
计划 W1 命令为 `--morris-r 8 --morris-p 6`，验收标准要求「464 设计点」和「每个参数 8 个有效 elementary effects」。
- 字面 `p=6`（6 组）→ 每条轨迹 7 步 → 56 次运行，效应为组级而非参数级。
- 464 = 8 × 58，即每条轨迹 58 步 = 57 参数 + 1（每参数一组）。

### Smoke 验证（r=1）
从干净检查点（commit `d5e1c0a`）构建 r=1 smoke 案例（`workspace/runs/p1_wn_v4_smoke_r1`）并实际运行：

- `sa_sen_morris.sen.par.csv`：**58 行 × 58 列**（57 参数 + 1 基准点/轨迹）。
- `sa_sen_morris.mio`：9348 行 = 57 参数 × 164 观测，`n_samples=1`（每参数 1 个 elementary effect）。
- `.rec`：`gsa_morris_p: 6`，`gsa_morris_r: 1`。

### 结论
**PESTPP-SEN 的 `gsa_morris_p` 在本配置中是离散化级数（Morris Δ），而非参数组数**。即使 `p=6`，PESTPP-SEN 仍逐参数步进（OAT），每条轨迹产生 `npar+1 = 58` 个设计点。因此：
- `r=8, p=6` → 8 × 58 = **464 设计点**，每参数 8 个 elementary effects —— 与计划验收标准完全一致。
- W2 `r=30, p=6` → 30 × 58 = **1740 次运行** —— 与计划一致。

**计划命令 `--morris-r 8 --morris-p 6` 正确，无需修改。**

## 2. 阻塞性 bug：DSSAT 输出格式错配

### 现象
已完成的 r=8 预检运行（`workspace/runs/p1_wn_v4_preflight_r8`，6 agents，464/464 成功，0 失败，8/8 完整轨迹）：
- `morris_run_quality.json`：**pass**（过程完整、0 失败、8/8 轨迹、每参数 8 个效应）。
- `morris_result_quality.json`：**fail** —— `morris_non_degenerate: fail`，`degenerate_count: 164`（全部 164 项输出退化）。
- agent 级 `SA_Indicators.OUT`：164 行，**每行均为 `-99.000000`**（DSSAT 缺失哨兵）。
- `sa_sen_morris.mio`：全部 `sen_mean_abs = 0.0`。

### 根因诊断（已隔离）
通过自包含单次运行（所有 FileX/天气/土壤/参数均在运行目录本地）确认：

1. **DSSAT 运行正常**：`DSCSM048.EXE B DSSBatch.v48` 在 ~0.78 秒内退出码 0，产生真实输出。
2. **真实数据存在于 `Pest*.OUT`**（PEST 格式，由 `run_dssat.py` 的 `_write_pest_*` 函数从原始输出转换写出）：
   - `PestTmtGrow.OUT`：真实日动态（LAID 0.002→14.0、LWAD 1→3894、SWAD 1→4698，跨处理变化）。
   - `PestHarvest.OUT`：真实采收数据（PWAD 累计 96→2040，跨采收期变化）。
3. **`sa_model.py` 读取的原始 DSSAT 输出被清理**：`sa_model.py`（`src/sensitivity/sa_model.py:404-408`）从运行目录读 `Evaluate.OUT`/`PlantGro.OUT`/`FreshWt.OUT`，但 `run_dssat.py` 在成功路径末尾调用 `cleanup(run_dir, keep_dssat_outputs=True)` 后，这些原始文件不在运行目录中（实测只剩 `Pest*.OUT`）。

### 数据流错配
```
DSSAT → [PlantGro.OUT, FreshWt.OUT, Evaluate.OUT] (原始，瞬时存在)
                                     │
              run_dssat.py _write_pest_* 转换并保留：
                                     ↓
              [PestTmtGrow.OUT, PestHarvest.OUT, PestEval.OUT, ...] (PEST 格式，保留)
                                     │
              cleanup(keep_dssat_outputs=True) 后：原始文件消失
                                     │
sa_model.py 读 [PlantGro.OUT, FreshWt.OUT, Evaluate.OUT] → 不存在 → 全部 -99
```

注：`run_dssat.py` 的 `_sync_outputs_from_filex_dir`（`src/dssat/run_dssat.py:781`）尝试从 FileX 目录同步原始输出，但 DSSAT（经 `DSSATPRO.v48` 的 `CRD` 重定向）将输出写到运行目录，而非 FileX 目录；同步源/目标错配。

## 3. 修复方案（待用户审批——涉及共享文件）

此 bug 不是 164 项契约变更，不是公共 IC/SA bundle 变更，不触发计划 §4 的科学审批边界。但修复涉及计划 §2 标记的**共享高冲突文件**：

- `src/dssat/run_dssat.py`（共享：率定与 SA 共用）
- `src/sensitivity/sa_model.py`（SA 所有权）

两个互斥修复方向（需用户选择）：

| 方案 | 改动 | 优点 | 风险 |
|---|---|---|---|
| **A：`sa_model.py` 改读 `Pest*.OUT`** | 仅改 `sa_model.py` 的解析器（`_parse_evaluate_out`/`_parse_dssat_out_by_run`），从 `PestTmtGrow.OUT`/`PestHarvest.OUT`/`PestEval.OUT` 提取，与率定路径使用同一输出格式 | 不动 `run_dssat.py`，零率定回归风险；SA 与率定输出格式统一 | 需重写 SA 解析器以匹配 PEST 格式（`@LAIDS@`/`@PWADS@` 等列名映射） |
| **B：`run_dssat.py` 保留原始输出供 SA** | 给 `run_dssat.py` 增加显式 `--retain-raw-outputs` 或环境变量，SA 调用时保留 `PlantGro.OUT`/`FreshWt.OUT`/`Evaluate.OUT` | SA 解析器不动 | 改动共享 `run_dssat.py`，需确认不干扰率定的清理策略 |

**建议方案 A**：它使 SA 与率定共享同一套保留输出，减少长期维护面，且不动率定核心。

## 4. 已验证通过的部分（无需重做）

- W0 集成检查点（commit `d5e1c0a`）：全部门禁与测试。
- PESTPP-SEN `morris_p` 语义（smoke r=1 实证）：计划命令正确。
- r=8 预检的**运行基础设施**完整：464 设计点、6-agent 并行、8/8 轨迹、0 失败、manifest 三哈希一致。
- DSSAT 模型本身正常：真实动态数据已确认存在于 `Pest*.OUT`。

修复输出读取 bug 后，**无需重新设计或重新审批**，直接重建并重跑 r=8 预检即可。

## 5. 触发用户审批

按计划 §2「共享高冲突文件修改前通知其他负责人」与 §4 审批边界：

- **请确认采用方案 A 还是方案 B**（或第三方案）。
- 确认后我将修复、补充回归测试（验证 SA 能从 `Pest*.OUT` 提取非 `-99` 值），重建 r=8 预检并完成 W1 验收。

在用户确认前，不修改 `run_dssat.py` 或 `sa_model.py` 的输出读取逻辑。

## 6. 产物

- `workspace/runs/p1_wn_v4_preflight_r8/`：已完成的 r=8 预检（输出全 `-99`，保留供修复后对比）。
- `workspace/runs/p1_wn_v4_preflight_r8/morris_audit/`：完整审计（run pass / result fail）。
- 本报告：`docs/reports/P1_v4_W1_preflight_diagnostic.md`。
- smoke r=1 案例已清理（语义已确认，无需保留）。

## 7. 标注

`engineering_preflight`（诊断）。预检结果因输出全 `-99` 而 `science_validated=False`，未用于任何排名。等待用户对修复方案的确认。
