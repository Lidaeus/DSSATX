# AGENTS.md — subprojects 工作区

本工作区（`D:\Tomato_Cal\subprojects\`）是主项目（见上级 `D:\Tomato_Cal\AGENTS.md`）的**研究子项目区**，核心是 `critical_n/`：自定义 DSSAT 引擎（CRGRO048-CNC）的氮机制重构、多版本氮缓冲实验与联合率定。主仓库的率定/图表规则在此继续适用；本文件只补充子项目特有事实。

## 布局与版本谱系（严禁混拼）

- `critical_n/bin/dscsm048_cnc.exe` — 当前最新正式沙箱引擎（Scheme B+ Phase 2，gfortran/CMake 构建）。官方 `C:\DSSAT48\DSCSM048.EXE` 永不修改。
- `critical_n/dssat_csm_cnc/` — 引擎完整源码树（改动集中在 `Plant/CROPGRO/`：DEMAND、CROPGRO、GROW、MOBIL、PHOTO、SENES、PODS、FreshWt）。
- `critical_n/fortran_patch/` — 补丁源与 `patches/*.patch`（`src_scheme_b/*.FOR` 为定制例程参考实现）。
- `critical_n/n_buffer_v1..v16/` — 按版本冻结的实验目录：V12 capacity_a / V13 为里程碑正式执行体；V14 率定稳定版；V15（HATS/LATS 接口、储备加权）、V16 为**未覆盖正式基准的研究版**。各版本有独立执行体与构建哈希——**不得把各分支机制拼成未实际运行的"最终模型"**。
- `critical_n/core/` — 机制 Python 参考实现（`dilution_curve.py`、`effective_biomass.py`），公式须与 Fortran 保持一致。
- `critical_n/docs/CUSTOM_DSSAT_CNC_PEST_IES_GUIDE.md` — 引擎规格、参数边界、SPE 模板规范的权威文档，改引擎前必读。
- `critical_n/reports/`、`critical_n/runs/` — 正式报告与运行工作区（All12-CNC 联合率定等）。
- 带日期目录（如 `leaf_n_gradient_20261016/`）= 一次性诊断研究，保留为记录。

## 氮浓度控制机制（改 DEMAND/GROW 前必须理解）

1. 有效生物量 `WEFF = (TOPWT + CUM_HPODWT)/100`（t DM/ha，含分批采收果实累加；`CROPGRO.for:903/1035`）——采收日严格连续。
2. 冠层临界氮稀释：`Nc = CNC_NC_INF + (CNC_A-CNC_NC_INF)·(max(CNC_W0,W)/CNC_W0)^(-CNC_B)`（`DEMAND.for:632-639`；NNI 门控在 `CROPGRO.for:806-826`，Phase 2 已剔除 PHOTO 冗余乘子）。
3. 叶新生组织目标 `FNINL = min(PROLFI·0.16, max(PROLFG·0.16+0.002, 1.05·Nc/100))`；稀释分数 `FR_DIL` 由 FNINL 在 PROLFI/PROLFF 区间位置决定；茎目标 `FNINS` 经 FR_DIL 联动并被 [PROSTG·0.16+0.001, PROSTI·0.16] 夹紧（`DEMAND.for:640-656`）。老组织回补目标 NVSTL/NVSTS 同样随曲线稀释，R5.7 后向 PROLFF/PROSTF 地板回落。
4. 奢侈氮缓冲：`c_opt,L = PROLFG·0.16` 为功能蛋白/液泡缓冲边界，功能库 1/0.16=6.25、缓冲库 4.4 g DM/g N 化学计量对称（`GROW.for:492-507`）。
5. SPE 卡片 `!*CRITICAL NITROGEN DILUTION` 用 **`READ(C80,'(4F6.0)')` 严格 6 列定宽**读取，越界自动回退默认 4.85/0.38/1.00/1.70（`DEMAND.for:1009-1047`）；模板占位符每个严格 6 列，超宽即静默回退。`PROLFG/PROSTG` 文件值≤0 时回退 `PROLFI·0.815 / PROSTI·0.723`。

## 关键约束

- **先读 `critical_n/AGENTS.md`**（用户约束，效力最高）：永不加入分季/关键日期生长护栏；率定目标仅限与 DSSAT 输出直接对应的实测变量；SPAD/光合/茎粗/品质测量不纳入目标。
- 率定参数边界以 `reports/all12_cnc_active_bounds.csv` 与指南 §4 为准；CNC 四参数活动域 CNC_A∈[4.2,5.2]、CNC_B∈[0.3,0.45]、CNC_W0∈[0.8,1.5]、CNC_NC_INF∈[1.4,2.0]，正式率定收敛于 4.85/0.38/1.00/1.70。
- 质量守恒断言（植株/土壤全氮、名义库容零超限）不得为拟合放宽；运行须留独立复核与证据收据。
- 修改 Fortran 后须重编译 `dscsm048_cnc.exe` 并跑 `critical_n/tests/`（原生单元 + 两季回归）才能采信。
- 主仓库接入方式：环境变量 `DSSAT_CUSTOM_EXE` 指向沙箱 exe（指南 §5）。

## 常用命令

```bash
# 机制单元/回归测试（Python 参考实现与 Fortran 一致性）
python -m pytest subprojects/critical_n/tests/ -x

# 沙箱引擎重新构建（进入 dssat_csm_cnc，CMake + Ninja + gfortran）
cmake --build build --target dscsm048_cnc

# 官方原版对照运行（确认零侵入）
# C:\DSSAT48\DSCSM048.EXE 哈希：92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a
```

## 事实速查

- 茄子走 TMGRO048（番茄模型）文件；`crop` 字段区分参数值。
- 当前正式率定集：`reports/all12_cnc_calibrated_parameters.csv`（64 活动参数含 CNC 四参数）。
- `maintenance/` 只是存储清理工具；不改变任何模型机制。
- 各 `n_buffer_v*/README.md` 记录该版机制与验收状态，判断"最新正式"以 README 与 `docs/project_milestone_*.json` 为准，不按目录名或时间猜测。
