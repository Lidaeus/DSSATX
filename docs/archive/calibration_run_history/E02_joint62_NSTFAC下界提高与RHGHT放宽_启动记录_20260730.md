# E02 joint62 NSTFAC 下界提高与 RHGHT 放宽：启动记录

日期：2026-07-30

## 目的

在三季真实 FileX 初始氮条件下，提高 `NSTFAC` 的允许下界，检验模型对施氮量差异的响应能否增强；同时根据历次联合率定中 `RHGHT` 持续靠近下界的结果，继续开放较低冠层形态参数。

## 唯一主动边界变更

| 参数 | 母版范围 | 本轮范围 | 处理 |
|---|---:|---:|---|
| `NSTFAC` | 0.10–1.00 | **0.50–1.00** | 排除上一正式后验的低值区，检验较高 NSTFAC 是否增强氮响应 |
| `RHGHT` | 0.50–2.20 | **0.35–2.20** | 用户批准继续沿长期下界聚集方向放宽 |

其余参数范围继承
`eggplant_e02_joint62_v6_touchrelax_slpf096_20260729`，包括
`SOIL_SLPF=0.90–0.96`。

`RHGHT` 的项目物理硬下界已同步由 0.50 更新为 0.35；该修改是本轮冻结边界能够通过物理约束检查的必要条件。

## 保持不变的率定合同

- 三季：25SP、25FA、26SP。
- 三季均使用真实 FileX 初始土壤氮，不使用统一 `SNO3=1`、`SNH4=0.5` 特别版。
- 25SP 数据包：
  `xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729`。
- 25FA、26SP 使用各自 `v7_adap34_plantn_slpf_20260729` 数据包。
- 活动参数：62个（55个共享参数及7个25FA季节偏移量）。
- `ADAP` 永久保持 diagnostic-only，不进入 Phi。
- `HARVEST_DRY` 目标族预算为 2.5。
- CHPDT 保持过程变换合同；其他观测与权重合同不变。
- 规模：150个成员、5次 IES 更新、6个并行代理。

## 运行资产

- 冻结边界：
  `eggplant_e02_joint62_v7_nstfac050_rhght035_20260730`
- 三季设计：
  `configs/runs/eggplant_e02_joint62_three_season_actualn_nstfac050_rhght035_v1_20260730.json`
- 启动脚本：
  `tools/calibration/run_e02_three_season_nstfac_rhght.py`
- 运行目录：
  `workspace/runs/e02_joint62_three_season_nstfac050_rhght035_150x5_20260730_062543`

## 启动检查

- JSON 与 Python 语法检查通过。
- 冻结边界物理约束检查通过。
- 相关测试18项中17项通过；唯一失败来自旧测试依赖的数据目录
  `xxql2501_symbi_n_candidate_20260719` 不存在，与本轮代码和数据无关。
- 构建预检通过，正式并行运行已经启动，状态为 `running`。

