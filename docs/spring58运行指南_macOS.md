# spring58 参数率定线 · macOS 运行指南

> 原始：Windows 便携包 `eggplant_spring58_calibration_portable_20261109.zip`
> （sha256 `9f2eaf29…ddd7`，MANIFEST 全量溯源）。批次
> `eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107`
> （58 自由参数 · 511 目标 · 族预算 Phi=97 · 40 成员 × 3 轮 · 8 代理）。
> 目标函数与权重设计见 [率定目标函数设计_spring58_20261109](率定目标函数设计_spring58_20261109.md)
> —— **逐字节保留，未做任何数学改动**。

## 1. 移植内容与验证集决定

移植器 `tools/calibration/port_spring58_macos.py`（幂等，可重复执行）：

- **率定集** `xxql2601_final_20261105`（包版覆盖项目旧副本，内容有演进）
- **验证集** `xxql2501_refreshed_lwad_20261108`（**用户决定 2026-11-09**：替代
  原 `xxql2501_refreshed_20261027`；后者不引入项目，留包内溯源）。切换通过
  包自带构建函数完成：`observation_catalog(LWAD, "25SP")` 重建锁定验证表
  （568 行，ADAP 口径与原表一致）、`native.model_payload/context` 重建
  `25SP_inputs` 载荷（SLPF=0.92）
- 11 个试验链脚本 + `tools/sa/run_dual_spring_morris_final_bundles_20261107.py`
  → `tools/calibration/`、`tools/sa/`；冻结边界与 proposal 入
  `data/parameter_registry/`；13 个封存运行目录（restored 全套 + 12 祖先存根）
  → `workspace/runs/`（**不入 Git**，磁盘 + 原 zip 为归档）
- `design.json` 全部 Windows 路径键值重写为 POSIX + 引擎键重指 + 重密封；
  `port_macos.json` 节记录路径映射、验证集切换与引擎溯源

## 2. 引擎与已修复的平台差异

| 项 | 内容 |
|---|---|
| 引擎版本 | Windows 官方 `C:\DSSAT48\DSCSM048.EXE` 为 **4.8.5.000**（首版误判 4.8.6.4 已纠正）。macOS 构建 `base-485-src`（tag `v4.8.5.0`）→ `.local/build-485-release/bin/dscsm048` |
| gfortran 严格性 | 两处 Windows Intel 放行、gfortran 运行时拒绝的 FORMAT 缺逗号已修（OPSOILNI.for:139 运行时 `T52X` 构造、OPSWBL.for:173 重复组前缺逗号）——**修复只加逗号，输出字节不变** |
| CO2 数据表 | FileX `ICO2=M`；v4.8.5.0 tag 的 `CO2048.WDA` 止于 2023（超年沿用表末值），Windows 安装器自带更新表未随包。当前用 **4.8.5.62 数据表**（2026≈429-431 ppm，物理合理）。后续提供 Windows `CO2048.WDA` 即可恢复逐位等价 |
| engine 哈希 | 跨平台二进制指纹必异：`DSSAT_ENGINE_SHA256` 登记原生构建指纹，Windows 原指纹留档 |

## 3. 复跑率定（等价干净案例）

```bash
cd ~/dev/Tomato_Cal
# 1) 移植/刷新（如已移植则跳过；会重建 joint 并重密封）
.venv/bin/python tools/calibration/port_spring58_macos.py \
  --engine .local/build-485-release/bin/dscsm048 \
  --engine-sha b7f55c95dda8a52fc7c830ad26e24b4e99b9e284da160455155a9420d0db5010 \
  --std-data .local/485mix-std \
  --std-data-note "4.8.5.0 code tables + 4.8.5.62 StandardData (CO2 through 2026)"

# 2) 81 文件哈希门在每次前向运行时自动校验（design.json 密封）

# 3) 并行率定（与 Windows 同入口）
env PATH="$PWD/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
  DSSAT_CUSTOM_EXE="$PWD/.local/build-485-release/bin/dscsm048" \
  DSSAT_STD_DATA_DIR="$PWD/.local/485mix-std" \
  DSSAT_ENGINE_SHA256=b7f55c95… \
  .venv/bin/python tools/parallel/run_parallel.py \
  --run-dir workspace/runs/eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107/joint \
  --case joint --mode ies --n-agents 8 --wait

# 4) 后处理（选优→确定性复算→LWAD 验证季→梯度诊断；顺序不可变）
.venv/bin/python -X utf8 -c "
from tools.calibration.run_dual_morris98_trial_20261105 import read, finalize
import pandas as pd, pathlib
RUN = pathlib.Path('workspace/runs/eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107')
d = read(RUN/'design.json')
b = pd.read_csv(d['frozen_bounds']).rename(columns={'name':'registry_name','native_name':'name'})
obs = pd.read_csv(RUN/'calibration_observations.csv').fillna('')
params = pd.read_csv(RUN/'joint/initial_ensemble.csv', index_col=0)
finalize(RUN, b, obs, d, params)"
```

## 4. 本次移植修好的三个 macOS 专属缺陷（均已有 V15/经验对照）

1. `_wait_for_manager_start` 只等 10 秒且不确认监听就绪——511 观测大 pst
   初始化超窗，agent 握手竞态失败。现等待 manager 日志出现
   "listening on socket"（`tools/parallel/run_parallel.py`）。
2. **pestpp-ies 5.2.27（apple 构建）execv 剥掉命令首 token 的前导 `/`**——
   绝对路径解释器永远无法启动，全部实现秒败。解法与 V15 一致：模型命令
   首 token 用裸 `python`（run_parallel 启动 env 已把 .venv/bin 置于 PATH）。
3. 冻结链校验的祖先 bounds（4 件）随封存目录一并入库，81 键哈希门 81/81。

## 5. 验证状态

- **一级（确定性复算）**：Windows 最优成员（Phi=84.7269878728234）单次前向
  管线全通（511 目标落盘）。当前 Phi Δ≈+2.0%，来源=CO2 表（见上表）；
  Python 层目标函数/权重/提取/编码与 Windows 逐字节同源。
- **二级（40×3 复跑）**：修复缺陷 1-2 后正常运行；完成后 `finalize` 产出
  `selection.json / round_quality.csv / calibration_comparison.csv /
  validation_comparison.csv`（LWAD 验证季）与梯度诊断，与 Windows
  `round_quality.csv`（0-3 轮 min_phi 84.727/84.831/84.601/93.467）作量级对照。
