# Code Review：并行执行模块（第 8 轮）

> 日期：2026-07-23
>
> 范围：`tools/parallel/run_parallel.py`（907 行）、`tools/parallel/prepare_agents.py`（293 行）
>
> 对照规范：`AGENTS.md`（Parallel Execution Model）、`docs/DSSAT并行隔离与输入路径规范.md`
>
> 关联前轮：第 5 轮（`run_dssat.py` 的 `_acquire_file_lock`/`_release_file_lock` 锁机制）
>
> 测试：`test_cmd_run_rejects_resume_with_ies_mode`、`test_parallel_run_status` 等 — 通过

## 审查结论

`run_parallel.py` 是功能完整、设计合理的并行执行管理器，核心隔离逻辑正确，与 `run_dssat.py` 的锁机制兼容。主要弱点在 `run_status.json` 的并发写入无锁保护（C1）和 PID 身份验证缺失（C2），这两点是影响正确性的核心问题。`prepare_agents.py` 是明显的过度设计——与 `run_parallel.py` 功能重叠，生成的 PowerShell 脚本路径仅被一个测试脚本使用，且其 `_copy_dir` 和 `ignore_names` 未同步改进。

---

## 发现清单

### C1 [严重] `run_status.json` 跨进程竞争条件

**位置**：`run_parallel.py` 全文，特别是 `cmd_run` 的 `_write_json` 全量重写（第 642、676、724、768 行）与 `cmd_stop`/`cmd_finalize`/`main` 的 `_update_run_status`（第 203-209 行 read-modify-write）

**现象**：`--no-wait` 模式下 detached 子进程运行 `cmd_run`，用户可在另一终端运行 `--stop`/`--status`/`--finalize`。两条写入路径并发：
- `cmd_run` 用 `_write_json` **全量重写**整个 JSON
- `cmd_stop`/`cmd_finalize` 用 `_update_run_status` **read-modify-write**

交错执行导致丢失更新：`cmd_stop` 写入的 `stop_requested_at` 可能被 `cmd_run` 的全量重写覆盖。

**与 `run_dssat.py` 的不一致**：`run_dssat.py` 对 CUL/ECO/SPE/SOIL/FileX 写入使用 `_acquire_file_lock`/`_release_file_lock` 实现互斥，而 `run_parallel.py` 对 `run_status.json` **完全没有锁保护**。

**影响**：`classify_manager_exit` 依赖 `stop_requested_at` 判断"operator stop"还是"natural completion"，字段丢失会导致 stop 被误分类为 `completed`。

---

### C2 [严重] PID 复用导致误判与误杀

**位置**：`_is_pid_alive`（第 154-166 行）、`_stop_pidfile`（第 169-183 行）、`cmd_stop` force 路径（第 466-487 行）、`cmd_finalize`（第 379、387 行）

**现象**：`_is_pid_alive` 用 `Get-Process -Id <pid>` 仅检查 PID 是否存在，不验证进程身份。Windows 进程结束后 PID 会被回收复用：
- PEST++ 退出后，若 PID 被新进程复用，`_is_pid_alive` 误判 PEST++ 仍在运行 → `cmd_finalize` 拒绝执行
- force-stop 模式下 `Stop-Process -Id <pid> -Force` 若 PID 已被无关进程复用，**误杀无关进程**

**缺失**：未记录进程启动时间（PID + start-time 二元组可唯一标识进程实例），也未验证进程名是否为 `pestpp-ies.exe`/`pestpp-sen.exe`。

---

### C3 [中] `_choose_free_port` TOCTOU 竞争

**位置**：`run_parallel.py` 第 40-53 行，`prepare_agents.py` 第 24-37 行（两份重复实现）

**现象**：`bind` → `close` → 返回端口号 → PEST++ manager 后续 `bind`。`close` 与 PEST++ `bind` 之间存在时间窗口，其他进程可能占用该端口。PEST++ manager 启动失败时无重试逻辑。

---

### C4 [中] `prepare_agents.py` 未排除 PEST++ 运行存储文件

**位置**：`prepare_agents.py` 第 155 行 `ignore_names = {args.agents_dir, "_agents", "__pycache__", "manager", "state"}`

**现象**：未排除 `.rns`/`.rmr`/`.rnu`/`.rnj`/`.rnf`/`.mio` 等 PEST++ 运行存储文件，也未排除 `pest.stp`。对比 `run_parallel.py` 第 575-579 行已正确排除这些文件。违反 `docs/DSSAT并行隔离与输入路径规范.md` 第 2.1 节。

---

### C5 [中] `_start_proc` 与 `_write_pid` 之间的文件句柄泄漏

**位置**：`run_parallel.py` 第 631-636 行（manager）和第 667-674 行（agent）

**现象**：`_start_proc` 成功后返回打开的 `out_f`/`err_f` 文件句柄。若随后 `_write_pid` 或 `_write_json` 抛异常，控制流进入 `finally`（第 805 行），但此时 `manager_handle` 尚未赋值，`finally` 中的关闭检查跳过 → **文件句柄泄漏**。

---

### O1 [严重·过度设计] `prepare_agents.py` 与 `run_parallel.py` 功能重叠，两套并行启动路径并存

**位置**：`prepare_agents.py` 第 173-276 行（PowerShell 脚本模板）vs `run_parallel.py` 第 631-674 行（Python subprocess 管理）

**现象**：`run_parallel.py` 用 Python `subprocess.Popen` 直接管理进程，是实际主入口；`prepare_agents.py` 生成 PowerShell 启停脚本，是另一套手动启动路径。两者各自实现沙箱准备，逻辑重复但不一致（见 C4）。

**实际使用**：`prepare_agents.py` 仅被 `tools/run_test_sa.py` 调用，`run_parallel.py` 的 `cmd_run` 完全自包含，不依赖 `prepare_agents.py`。

---

### O2 [中] 工具函数跨文件重复

**位置**：
- `_choose_free_port`：`run_parallel.py` 第 40-53 行 ≡ `prepare_agents.py` 第 24-37 行（完全相同）
- `_copy_dir`：`run_parallel.py` 第 63-77 行 vs `prepare_agents.py` 第 40-48 行（前者多了 Windows 目录锁等待逻辑，后者缺失）
- `_write_json`：`run_parallel.py` 第 186-189 行 ≡ `prepare_agents.py` 第 57-60 行

---

### O3 [中] Legacy PID 双写双读，移除时机未定义

**位置**：`run_parallel.py` 同时写 `state/agent.pid`（新）和 `panther_agent.pid`（legacy）（第 671-672 行 agent，第 634-635 行 manager），`_find_agent_pid`/`_find_manager_pid` 先读新位置再读 legacy（第 275-288 行）

**现象**：向后兼容代码无明确退役计划，增加了约 15 行重复逻辑。

---

### O4 [低] `cmd_run` 中 run_status.json 完整重写 4 次

**位置**：第 642、676、724、768 行

**现象**：每次 `_write_json` 重写整个文件，而非用 `_update_run_status` 增量更新。第 642-657 行的写入丢失了 `previous` 中除 `attempt` 外的所有字段。

---

### O5 [低] `prepare_agents.py` 用字符串 `.replace()` 生成 SEN 变体

**位置**：第 227-228 行

**现象**：`start_agents.replace("pestpp-ies.exe", "pestpp-sen.exe")` ——错误信息中的 `pestpp-ies.exe` 也会被替换，虽语义巧合正确，但属于意外替换。

---

### O6 [低] `--mode` 选项不一致

`prepare_agents.py` 支持 `ies`/`sen`/`both`（第 123 行）；`run_parallel.py` 仅支持 `ies`/`sen`（第 849 行）。`both` 模式生成两套脚本但无法被 `run_parallel.py` 消费。

---

### M1-M6 [次要]

| 编号 | 位置 | 问题 |
|---|---|---|
| M1 | `_is_pid_alive`/`_stop_pidfile` | 每次调用启动新 PowerShell 进程，性能开销大 |
| M2 | `run_parallel.py:575` | `ignore_names` 同时排除 `args.agents_dir` 和 `"_agents"`，默认值下冗余 |
| M3 | `prepare_agents.py:173-228` | PowerShell 模板用 f-string 直接插入 `args.case`/`host`，无转义 |
| M4 | `cmd_status` | 输出为纯文本表格，无 `--json` 选项 |
| M5 | `cmd_finalize:376-383` | IES 路径不像 SEN 路径显式验证 `.rec` 完成标记，验证逻辑不对称 |
| M6 | `_copy_dir` 的 `_ignore` 函数 | `ignore_names` 是扁平集合，子目录中同名文件/目录会被意外排除 |

---

## 已验证一致的关键点

| 验证项 | 结论 |
|---|---|
| Agent 文件隔离 | ✓ 每个 agent 获得完整 run directory 副本，独立工作目录，独立 `state/` 子目录 |
| PID 文件位置 | ✓ 写入 `state/agent.pid`，同时保留 legacy 位置 |
| 端口范围 4010-4999 | ✓ `_choose_free_port(start=4010, end=4999)` |
| 与 `run_dssat.py` 锁机制兼容 | ✓ 锁文件落在各 agent 的独立工作目录内，无跨 agent 冲突 |
| Manager 先于 agent 启动 | ✓ `_wait_for_manager_start` 给 manager 10 秒启动窗口 |
| `--resume --mode ies` 显式拒绝 | ✓ pestpp-ies 不支持 `/r`，fail-fast |
| Agent 早退 guard | ✓ `_wait_for_manager_with_agent_guard` 检测所有 agent 退出但 manager 仍运行 |
| 离线 finalize 证据要求 | ✓ 要求 manager 已停止 + `.rec` 完成标记 + 终态证据 |
| 退出码归一化 | ✓ `classify_manager_exit` 区分 completed/aborted/runtime_failed |

---

## 建议的后续行动（按优先级）

| 优先级 | 行动 | 对应问题 |
|---|---|---|
| **P1** | 为 `run_status.json` 加文件锁（参考 `run_dssat.py:817-859`），或统一所有写入走 `_update_run_status` 增量路径 | C1 |
| **P1** | PID 文件同时记录进程启动时间，`_is_pid_alive` 验证 PID + 启动时间二元组；或验证进程名 | C2 |
| **P1** | 修复 `_start_proc` 异常路径的文件句柄泄漏 | C5 |
| **P2** | 评估废弃 `prepare_agents.py` 的 PowerShell 脚本生成路径，统一到 `run_parallel.py`；若保留则同步 `_copy_dir` 和 `ignore_names` | O1, C4, O2 |
| **P2** | `_choose_free_port` 增加重试 | C3 |
| **P2** | 定义 Legacy PID 退役计划 | O3 |
| **P3** | `cmd_run` 改用 `_update_run_status` | O4 |

**可删代码行数估计**：~190 行（`prepare_agents.py` PowerShell 模板 ~130 行 + 重复工具函数 ~25 行 + Legacy PID ~15 行 + 冗余重写 ~20 行）。
