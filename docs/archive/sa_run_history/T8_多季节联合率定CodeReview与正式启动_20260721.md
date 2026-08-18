# T8 多季节联合率定 Code Review、修复与正式启动说明

> 日期：2026-07-21  
> 结论：`code_review_passed / smoke_passed / formal_launcher_ready`  
> 正式率定尚未启动；由用户运行一键入口后启动。

## 1. 审查结论

协作者报告中的“PEST++ 5.2.16 在 472 observations + 51 groups 时发生 heap corruption”结论不成立。直接证据是原 agent 的 `panther_worker.rec`：`PestTmtGrow.OUT.ins` 在执行换行指令时提前遇到 EOF。根因在项目调度与合并代码，而非 PEST++ 的观测容量限制。

已确认并修复以下问题：

1. 多行丢失：旧合并器对每个 RUN 遇到第一行后立即 `break`，导致同一处理的其余过程观测和多次采收事件全部丢失。
2. RUN/TN 错配：调度器运行完整原始 batch，但构建器只选择部分处理；25FA 的设计顺序不是自然排序，因此全局 RUN 会映射到错误处理。
3. DSSAT batch 格式破坏：普通空格重写会破坏 FileX 固定宽度字段，使 DSSAT 把整行误读为文件名。现保持 `TRTNO` 固定列位置。
4. 权重策略反转：累计采收原被设为 1.25、增量采收为 1.0，与已批准设计相反；现改为累计 1.0、增量 1.25。
5. 权重审计不一致：原代码只改 PST，不同步 `weights.audit.csv`；现 PST、观测审计和组审计使用同一结果。
6. 零权重被重新激活：原 T8 重加权会把缺失值及诊断观测重新赋非零权重。现只重加权原本 active 的观测。
7. `phi_role` 未执行：`diagnostic_only` 和 `sensitivity_only` 原仍进入 Phi；现统一保持零权重。
8. IES 合同未收口：多季节分支提前退出，遗留默认 `ies_bad_phi_sigma=2.0` 且没有显式观测噪声 ensemble；现正式设置 `1e300` no-cull 并冻结 sigma 驱动的观测 ensemble。
9. 季节身份不显式：观测名和组名现带 `25SP_`/`25FA_` 前缀；registry 的 RUN 正则同时兼容日期和采收后缀。

XXQL2601 仍保持 validation 角色，未进入 PST 和参数更新。

## 2. 正式率定契约

- 率定季节：XXQL2501（25SP）+ XXQL2502（25FA），共享一套 17 个遗传参数。
- 独立验证：XXQL2601（26SP），率定阶段不读取其观测。
- 正式规模：240 realizations，`noptmax=4`，默认 8 agents。
- 自动高 Phi 筛除：关闭（`ies_bad_phi_sigma=1e300`）；模型失败与高 Phi 必须分开诊断。
- 观测误差：当前采用 `assumption_based_sigma_v2.csv`；FileA/FileT 保持物理实值，PEST 权重和 observation ensemble 使用同一审计 sigma。
- 观测角色：472 条注册观测，其中 448 条进入率定 Phi；24 条诊断/敏感性观测为零权重。
- 权重：`weight=(1/sigma_eff)*sqrt(phi_budget/n_g)`；累计采收预算 1.0，增量采收预算 1.25。

当前两季文件没有逐处理重复观测 SD，因此正式入口使用已登记的假设 sigma。以后获得重复数据时，应先更新观测政策或逐观测不确定性输入并重建 PST；不应在率定完成后追溯替换 sigma。

## 3. Smoke 证据

测试目录：`workspace/runs/t8_formal_launcher_smoke_20260721/`

- 单元/回归：311 passed，2 skipped。
- 双季 DSSAT：25SP 8/8、25FA 8/8，合计 16 RUN，返回码 0。
- PEST++ serial `noptmax=0`：返回码 0；472 条 INS 全部读取，无 EOF/instruction error/heap corruption。
- PEST++ parallel：2 agents，manager 返回码 0。
- registry：472/472 均映射到 season、experiment、treatment、global_run。
- 正式活动观测：448；非 calibration `phi_role` 的活动观测数为 0。
- 明确写入 observation ensemble 与 no-cull 策略。

## 4. 一键启动

Windows 下双击：

```text
tools/calibration/start_t8_formal.cmd
```

或在项目根目录运行：

```bash
python tools/calibration/run_t8_formal_multiseason.py
```

脚本会自动完成：构建独立 run 目录 → 核验 16 RUN/season role/registry/no-cull/observation ensemble → 8-agent PEST-IES → 等待结束。若只想再次检查构建而不启动率定：

```bash
python tools/calibration/run_t8_formal_multiseason.py --build-only
```

每次启动使用新的时间戳目录，并拒绝覆盖已有 run。构建后生成 `formal_launch_receipt.json`；只有并行管理器正常结束，状态才更新为 `pestpp_completed`。

## 5. 暂不增加的复杂度

- 不拆成两套独立 PST，也不拼接两个伪后验。
- 不因旧误诊减少科学上已选定的观测。
- 不自动调节 bad-Phi 阈值来追求保留率。
- 不在本轮增加数据库、GUI 或通用工作流框架。
- 不把 XXQL2601 提前用于调参或权重决策。
