# eggplant_spring58 参数率定便携包 — 运行指南

批次：`eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107`
（58 自由参数 · 511 项目标 · 40 成员 × 3 轮 IES · 8 并行代理 · 目标函数 Phi 预算 97）

## 1. 包内布局与解包目标位置

本包是**路径保持型**：率定代码在运行时（`trial.forward`）会按 `design.json` 中的
**绝对路径哈希**逐一校验 81 个封存文件。因此解包必须还原出相同的三个根路径：

| 包内目录 | 解包/复制到 | 说明 |
|---|---|---|
| `Tomato_Cal/` | `D:\Tomato_Cal\` | 代码、参数注册表、试验数据、运行目录、PEST++ |
| `Tomato_Cal_Cold_Storage/` | `D:\Tomato_Cal_Cold_Storage\` | 25SP 验证季数据包（率定后处理需要） |
| `DSSAT48/DSCSM048.EXE` | `C:\DSSAT48\DSCSM048.EXE` | DSSAT v4.8 主程序（若目标机已装 DSSAT 4.8，校验 SHA-256 一致即可，见 MANIFEST） |

如果目标机没有 D: 盘或不能写 C:\DSSAT48，见第 6 节"高级迁移"。

## 2. 软件环境

- Windows，Python 3.13（`python` 需在 PATH 上）。
- 依赖安装：
  ```
  cd D:\Tomato_Cal
  python -m pip install -r requirements.txt
  ```
  关键包：`pyemu>=1.4,<2`、`pandas`、`numpy`、`scipy`、`pyyaml`。
- PEST++ 已随包提供（`pestpp-5.2.16-win\bin\pestpp-ies.exe`），无需另装。
- 运行时需要可用的本地 TCP 端口（默认从 4010 起自动选择，8 个代理并行）。

## 3. 复跑该批次率定（推荐流程）

包内已包含该批次**已完成**的运行目录（供比对、留档）。复跑使用等价的干净案例：

1. 在原运行目录里生成全新 `joint` 案例并封存旧目录：
   ```
   cd D:\Tomato_Cal\workspace\runs\eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107
   python clean_restart\make_fresh_joint.py
   ```
   该脚本把现有 `joint\` 改名为 `joint_completed_reference_<时间戳>\`，
   再从 `clean_restart\` 复制出新的 `joint\`（pst/tpl/ins/初始集合/参数文件）。
   新 pst 的 model command 已改为 `"python"`（从 PATH 解析），其余与原批次逐字节同源。

2. 启动并行率定（与原批次完全相同的入口）：
   ```
   cd D:\Tomato_Cal
   python -X utf8 tools\parallel\run_parallel.py --run-dir workspace\runs\eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107\joint --case joint --mode ies --n-agents 8 --wait
   ```

3. 运行结束后的后处理（选优、确定性复算、验证季评估、梯度诊断）：
   ```
   cd D:\Tomato_Cal
   python -X utf8 -c "from tools.calibration.run_dual_morris98_trial_20261105 import read, finalize; import pandas as pd, json; RUN=r'workspace\runs\eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107'; d=read(RUN+r'\design.json'); b=pd.read_csv(d['frozen_bounds']).rename(columns={'name':'registry_name','native_name':'name'}); obs=pd.read_csv(RUN+r'\calibration_observations.csv').fillna(''); params=pd.read_csv(RUN+r'\joint\initial_ensemble.csv',index_col=0); finalize(__import__('pathlib').Path(RUN),b,obs,d,params)"
   ```

参考耗时：原批次 8 代理约 34 分钟（18:49–19:23）。

**注意**：`finalize` 会选择"通过保留率门槛的轮次中 Phi 最小的成员"，并用确定性
单次复算校验 Phi 一致（相对容差 1e-6）；验证季（25SP）只在选优完成后评估，
不参与任何参数或候选选择——这是设计约束，勿改动顺序。

## 4. 每次前向运行会发生什么（帮助排障）

PEST++ 每个成员调用：
`python -X utf8 tools\calibration\run_water_stress_expansion_40x3_20261107.py --forward <运行目录>`

1. 校验 `sealed_design.json` 与 `design.json` 的 SHA-256，以及全部 81 个源文件哈希；
2. 读取冻结参数上下界（58 自由 + 固定参数），序列化为 DSSAT 6 字符定宽基因字段
   （含前导空格规则与越界复查）；
3. 从 `<运行目录>\26SP_inputs` 载入输入载荷，注入参数后运行
   `C:\DSSAT48\DSCSM048.EXE CRGRO048 B DSSBatch.v48`（超时 150 秒）；
4. 从 `Evaluate/PlantGro/PlantN/FreshWt/SoilWat.OUT` 提取 511 项目标模拟值，
   经标准化 + 伪 Huber 编码写入 `FormalObjectives.OUT`（详见《目标函数设计说明》）。

任何一步失败都会写入代理目录的 `forward_failures.jsonl` 并使该成员本轮记失败；
失败成员**不会**被静默剔除——保留率低于 98% 的轮次不能参与选优。

## 5. 完整性校验

- `MANIFEST.csv`：包内每个文件的字节数与 SHA-256。
- 率定启动时的哈希校验（第 4 节第 1 步）即为最强的运行时完整性检查；
  任何文件被改动都会在第一次前向运行时报错并指明路径。
- 原批次结果文件在 `workspace\runs\<ID>\` 下保留
  （`calibration_comparison.csv`、`validation_comparison.csv`、`selection.json` 等），
  复跑后可逐项对比。

## 6. 高级迁移（不能使用 D:\ 与 C:\DSSAT48 时）

代码对三个绝对路径有依赖：`design.json` 内的源文件/数据集绝对路径、
`joint.pst` 的 model command、以及 `run_dual_morris98_trial_20261105.py` 顶部的
`EXE = Path("C:/DSSAT48/DSCSM048.EXE")`。迁移到其他盘符需要：

1. 修改 `design.json` 中所有绝对路径为新根路径（`source_hashes` 的键、
   `datasets.*.path`、`frozen_bounds`、`c31_actual_control_file` 等）；
2. 重新计算 `sealed_design.json`：`{"sha256": <新 design.json 的 SHA-256>}`；
3. 修改 `joint.pst` 的 model command 中两个绝对路径；
4. 修改 `run_dual_morris98_trial_20261105.py` 的 `EXE` 常量（或把 DSCSM048.EXE
   放到新机器的 `C:\DSSAT48\`，推荐后者，DSSAT 官方安装位置即此）。

上述改动会使运行脱离与原机器的哈希链条——请保留本包原始副本作为溯源依据。
