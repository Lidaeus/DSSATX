# 08 工程实施路线图：对 Tomato_Cal 的改造

本章从“工程实现”角度，说明如何在 `c:\DSSAT48\Tomato_Cal` 现有框架上实现上述调参计划，而不破坏现有番茄校准工程。

---

## 1. 工作目录与文件组织

建议将“每次率定运行”做成可追溯、可复现、可清理的独立目录，并避免在 `Workspace` 根目录堆积中间产物：

- 试验文件：
  - `XXQL2501.TMX`、`XXQL2501.TMA`、`XXQL2501.TMT`、`XXQL2501.WTH`（如需）
- 模板文件：
  - 保持 `TMGRO048.CUL.base / TMGRO048.ECO / TMGRO048.SPE` 为“茄子载体”模板（避免混用其他作物/品种）
- 单次运行目录（推荐）：
  - `Workspace/Calibration_Results/_runs/<run_id>/`（例如 `Calibration_Results/_runs/20260201_eggplant_stage2_v10/`）
  - 通过 `build_pest.py --out-dir <run_dir>` 让 `.pst/.tpl/.ins/*_params.csv/*_param_review.csv` 全部落在同一目录

可以通过 `DSSBatch.v48` 增加 `XXQL2501` 的批处理项，用于单一试验率定。

中间文件清理策略：

- 若历史版本仍在 `Workspace` 根目录产出，可使用 `clean_workspace.py` 归档（默认归档到 `Calibration_Results/_runs/<timestamp>/`），避免污染后续“从零重跑”的工作区。

---

## 2. PEST 接口脚本的最小改造点

### 2.1 `build_pest.py`

当前逻辑已经支持：

1. 从 `TMGRO048.CUL.base` 读取参数、初值与 `MINIMA/MAXIMA` 范围，并按 `!Calibration` 行筛选 P/G 参数。
2. 读取 `Evaluate.OUT` 的 `xxxS/xxxM` 成对列生成观测，并在 `eggplant_pheno/growth/joint` 模式下通过 `group_sigmas` 写入 `weight = 1/σ^2`。
3. 对 `PestEval.OUT / PestGrow.OUT / PestJoint.OUT` 使用 `@COL@` 标签型指令文件解析（避免依赖列序与 `l3` 偏移）。
4. 读取 `XXQL2501.TMT` 中的多次采收记录，与 `PlantGro.OUT` 中按日输出的 `PWAD` 对齐，生成 `PestHarvest.OUT` 并在 `eggplant_harvest` 模式下构造基于分次采收的 pst 文件（观测名形如 `PWADS_R{run}_H{hno}`，分组名形如 `PWADM_H{hno}`）。
5. 读取 `XXQL2501.TMT` 中的过程采样点（`LAID/LWAD/SWAD`），与 `PlantGro.OUT` 的同名日值对齐，生成 `PestTmtGrow.OUT` 并在 `eggplant_process` 模式下构造过程 pst 文件（观测名形如 `LAIDS_R{run}_D{date}`，分组名形如 `LAIDM_D{date}`）。

并已支持 `stage2` 的“一次构建、多输出联合率定”模式：

- `python build_pest.py --mode eggplant_stage2 ...` 会在同一个 `.pst` 内同时纳入：
  - `PestEval.OUT`（物候弱约束）
  - `PestJoint.OUT`（季末汇总的联合观测）
  - `PestHarvest.OUT`（多次采收序列观测）
  - `PestTmtGrow.OUT`（过程点观测）
- `--harvest-var` 控制多次采收观测口径：
  - `CHPDT`：干重累计
  - `CHFPW`：鲜重累计

- `--include-soil/--include-ic` 用于把“测定可能有偏”的土壤物理与初始含水率作为小范围偏差项纳入联合率定：
  - `--include-soil`：释放 `SOIL_SBDM_*`（容重）
  - `--include-ic`：释放 `IC_SH2O_*`（初始体积含水率）
  - 推荐使用相对边界（默认 ±3%）：`--soil-sbdm-frac 0.03 --ic-sh2o-frac 0.03`
  - “按层同幅度”指：对每一层以该层初值为中心做相同比例的上下浮动（不同层的绝对浮动量不同）

为支持 Eggplant-on-Tomato：

1. 若 `XXQL2501` 的 `Evaluate.OUT` 字段命名与默认不一致，直接在 `build_pest.py` 中调整 `obs_bases/critical/group_sigmas`（当前通过 `--mode` 选择）。
2. 如需进一步加入 LAI/器官干重的过程观测，可在现有 `eggplant_growth/eggplant_joint/eggplant_harvest` 基础上扩展观测筛选逻辑（按本计划中的权重建议配置 `group_sigmas`）。
3. 在参数解析环节中：
   - 确保 `!Calibration` 行与 `MINIMA/MAXIMA` 中包含本计划使用的全部 CUL 参数；
   - 将 `ECO/SPE` 的参数范围作为显式配置注入到参数集合中（因 `ECO/SPE` 文件本身不提供 `MINIMA/MAXIMA`）。

并已支持把“敏感性分析输出的统一范围表”作为单一可信来源（single source of truth）：

- `sensitivity_param_review.csv`：`Workspace/Sensitivity_Analyze/SA_Project_Output/sensitivity_param_review.csv`
- `build_pest.py --bounds-review-mode require` 会将各模式构建的参数边界强制对齐到该文件

### 2.2 `run_dssat.py`

现有逻辑会更新 `TMGRO048.CUL` 文件，并从 DSSAT 输出生成四类带标记输出：

- `PestEval.OUT`（物候模式使用，当前列为 `ADAPS/ADAPM`）；
- `PestGrow.OUT`（生长模式使用，当前列为 `HWAMS/LAIXS/CNAMS`）；
- `PestJoint.OUT`（联合模式使用，当前列为 `HWAMS/LAIXS/CNAMS/CHTAS/CNAAS/PWAMS/H#AMS/HIAMS`）；
- `PestHarvest.OUT`（多次采收模式使用，按 `RUN/TN/HNO/DATE` 输出 `@PWADS@`，由 `PlantGro.OUT(PWAD)` 与 `XXQL2501.TMT` 对齐生成）。
- `PestTmtGrow.OUT`（过程观测模式使用，按 `RUN/TN/DATE` 输出 `@LAIDS@/@LWADS@/@SWADS@`，由 `PlantGro.OUT(LAID/LWAD/SWAD)` 与 `XXQL2501.TMT` 对齐生成）。

`run_dssat.py` 已支持：

1. 从参数表更新 `TMGRO048.CUL`（`update_cul_file()`）。
2. 从参数表更新 `TMGRO048.ECO`（`update_eco_file()`）。
3. 从参数表更新 `TMGRO048.SPE` 的三基点温度（`update_spe_file()`：`TB/TO1/TO2/TM`）。

并已支持把 `--harvest-var` 贯穿到 `PestHarvest.OUT` 的写出逻辑（用于在同一条前向运行命令中切换 `CHPDT/CHFPW`）：

- 关键调用点：`Tomato_Cal/Workspace/run_dssat.py:1452-1457`
- 参数解析：`Tomato_Cal/Workspace/run_dssat.py:1470-1478`

注意：任何对 `SPE/ECO` 的写入必须保持原有 Fortran 固定宽度格式。

为降低“路径不一致导致 DSSAT 读取了另一份遗传文件”的风险，建议把每次前向运行做成“运行环境自洽”：

1. 钉死本次运行的 `run_dir`（即 DSSAT 批运行实际启动目录）。
2. 在启动 DSSAT 前，将当前 worker 目录中更新后的 `TMGRO048.CUL/.ECO/.SPE` 复制到 `run_dir`。
3. 强制本次运行的 `DSSATPRO.v48` 中 `CRD` 指向 `run_dir`，确保 DSSAT 使用同一套遗传文件。

该策略可显著降低 `XFINT` 等 ECO 参数因读取源不一致而触发的 `IPDMND` 风险。

若后续确认需要“动态分配”（例如 `XFRT` 随光热龄/热时变化）来匹配多次采收的季节分布，这通常超出纯输入文件可表达能力，应按“模型结构升级”处理：

1. 优先检查 CROPGRO048 现有机制是否已有可用的时变分配接口（避免改源码）。
2. 若确需改动，建议以最小侵入方式实现：仅引入 1 个时变函数（输入由 ECO/CUL 给出），并保留开关以与原模型对照。

---

## 3. 阶段化工程配置

为支持阶段 1 与阶段 2 的分步率定流程，建议按“配置文件”方式管理参数集与权重：

1. 创建阶段化的 PEST 配置：
   - `tomato_cal_eggplant_pheno.pst`：只包含物候相关观测与参数；
   - `tomato_cal_eggplant_growth.pst`：在前者基础上加入 LAI/器官干重；
   - `tomato_cal_eggplant_process.pst`：加入 `TMT` 的 `LAID/LWAD/SWAD` 过程点；
   - `tomato_cal_eggplant_yield.pst`：再加入产量/多次采收；
   - `tomato_cal_eggplant_joint.pst`：用于阶段 2 联合优化。
2. `build_pest.py` 中通过 `--mode` 选择当前构建的 `pst` 类型（`eggplant_pheno/growth/process/harvest/joint`）。

跨阶段参数固定/继承（用于“上一阶段已确认的参数不再回滚”）：

- 用 `build_pest.py --fixed-from <csv>` 将参数固定为常数（其上下界被设置为同一值，`partrans=fixed`）
- 固定参数建议按阶段命名并集中存放：
  - `Calibration_Results/_fixed/stage1_fixed.csv`
  - `Calibration_Results/_fixed/soil_bias_fixed.csv`
  - `Calibration_Results/_fixed/spe_temp_fixed.csv`

固定 CSV 的最小格式：

- 表头：`name,value`
- 仅包含需要固定/覆盖的参数行（例如 `XFRT,0.85`）

固定 CSV 的推荐来源：

- `analyze_results.py` 会在完成一次 IES 结果汇总后输出：`{prefix}_best_parameters_fixed.csv`（已是 `name,value` 格式），可直接用于下一阶段：
  - `python build_pest.py --mode eggplant_stage2 --fixed-from "Calibration_Results\\{prefix}_best_parameters_fixed.csv" ...`

当出现“参数贴边界/范围冲突证据”时，建议生成 `XXQL2501` 专用范围建议表（需人工复核后再启用）：

- 证据来源：`{prefix}_bound_hits.csv`
- 建议生成：`python analyze_results.py --suggest-xxql-bounds --prefix {prefix} --bounds-review-csv "Workspace\\Sensitivity_Analyze\\SA_Project_Output\\sensitivity_param_review.csv" --extend-frac 0.20`

建议在 stage2 的“默认允许参数集”中显式按敏感性优先级组织：

- ECO：优先保证 `TRIFL/RWDTH/RHGHT/XMAGE` 可用；`XFINT/XFPHT` 仅在首批偏差诊断成立时启用。
- CUL：优先保证 `XFRT/PODUR/SFDUR` 可用，并同步维护 `TMGRO048.CUL.base` 的 `MINIMA/MAXIMA`。
- SPE：优先保证 Thermal time（`TB2/TO22/TO11` 等）与 `KCAN` 的边界与写入路径可控。

---

## 4. 结果管理与可复现性

为确保整个 Eggplant-on-Tomato 工程可复现：

1. 约定结果输出目录：
   - `Calibration_Results/Eggplant_XXQL2501/Phase1_Phenology/`
   - `Calibration_Results/Eggplant_XXQL2501/Phase1_Growth/`
   - `Calibration_Results/Eggplant_XXQL2501/Phase1_Yield/`
   - `Calibration_Results/Eggplant_XXQL2501/Phase2_Joint/`
2. 每次正式运行前，保留：
   - 当前 `.pst` 文件
   - 当前 `.CUL/.ECO/.SPE` 模板快照
   - 当前权重表与参数范围快照

当前工程已额外提供两个“确定性对比与指标汇总”产物（位于 `Workspace/Calibration_Results`）：

- `{prefix}_deterministic_harvest_compare.csv`：按 `TMT` 采收日期对齐的 `OBS_*` vs `SIM_*`（干重/鲜重，累计/增量）
- `eggplant_stage2_v6_v10_harvest_metrics.csv`：跨版本的 RMSE/MAPE 汇总表

并提供论文级的“指标网格（Metrics Grid）”产物：

- `{prefix}_metrics_grid.csv`：总体 + 分 `TRNO(TN)` 的 RMSE、NRMSE、d-index（支持 harvest/process/joint 三类观测）

---

## 5. 扩展到多试验/多年份的预留接口

本计划以 `XXQL2501` 为起点，但工程架构应支持后续增加其他茄子试验：

1. 如需多试验/多年份拼接，可在单独配置文件中定义试验列表与权重（当前 `run.info` 为 PEST++ 运行时信息文件，不作为工程配置入口）。
2. 在 `build_pest.py` 中根据试验列表拼接多行 `Evaluate.OUT`，并给不同试验的观测附加分组标记（用于后续分组统计和 AICc 评估）。
