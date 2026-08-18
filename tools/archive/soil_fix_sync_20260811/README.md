# 土壤参数固定值同步 — 临时脚本归档（20260811）

2026-08-11 将用户固定的土壤物理参数（48 个）与土壤硝态氮/铵态氮参数（220 个）
同步到全部活跃试验 bundle 的过程中产生的临时脚本。

## 保留在 tools/calibration/ 的正式工具

- `sync_soil_fix_all_bundles_20260811.py` — 批量同步全部活跃 bundle 的
  SOIL.SOL（SLPF + 8 层土壤物理参数）与 25SP/26SP FileX ICBL（SNH4/SNO3）。
  后续如需重新同步或扩展到新 bundle，使用此脚本。

## 归档的中间脚本（按时间顺序，仅作追溯）

| 脚本 | 说明 |
|---|---|
| `sync_soil_fix_20260811.py` | 首次同步（仅 actual_trial 两个 bundle）——含 FileX ICBL 列错位 bug 与 SOIL.SOL 层内覆盖 bug |
| `repair_ic_sync_20260811.py` | 第一次 IC 修复尝试（token 索引错误） |
| `repair_ic_sync_v2_20260811.py` | 第二次 IC 修复尝试（语义解析，仍有宽度问题） |
| `repair_ic_sync_final_20260811.py` | 第三次 IC 修复（从参考副本重建，验证仍差 3 处） |
| `repair_ic_sync_final3_20260811.py` | 定宽重写 FileX ICBL（漏 SH2O 列） |
| `fix_soil_sol_20260811.py` | SOIL.SOL 原子替换尝试（token 距离列宽错误） |
| `rebuild_soil_sol_20260811.py` | SOIL.SOL 从基线重建（header 列位错误） |
| `rebuild_soil_sol_v2_20260811.py` | SOIL.SOL 定宽 6 字符列重建（最终有效版，被正式工具取代） |

## 关键教训（写入供后续参考）

1. **FileX ICBL 数据行有 5 个 token**（TN ICBL SH2O SNH4 SNO3），header 只列
   4 列（@C 是处理号）——定位 SNH4/SNO3 必须按 run_dssat 的语义解析
   （TN+depth 前缀后取 3 个语义 token），不能按 header 列序号。
2. **SOIL.SOL 是固定 6 字符列格式**（SLB=0-5, SLMH=6-11, ...），值在列内右
   对齐；窄 token（`.3`）可扩展为 `.31`，但不能按 token 间距扩展。
3. **同层多参数替换必须一次性原子应用**（收集 replacements 后从右到左），
   不能逐参数覆盖行。
4. `data/raw/soil/SOIL.SOL` 是 DSSAT 通用土壤库（11 层结构），不是本试验
   使用的 8 层剖面，切勿按层序号同步；已用 git 恢复原样。

## 验证结果（最终）

- 12 个活跃 bundle 的 SOIL.SOL：全部 48 项核对 0 issue（含 25FA/XXQL2502）
- 12 个活跃 25SP/26SP FileX：IC 全部匹配 fix（100/100、120/120、ref 100/100）
- DSSAT 实测：a3 exe 对修复后 bundle 跑 22 处理，exit 0
- `data/raw/experiments/XXQL2501.TMX`（只读原始快照，占位 IC）与
  `data/raw/soil/SOIL.SOL`（通用库）按不可变原则未替换
