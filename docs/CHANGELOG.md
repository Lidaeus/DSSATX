# Changelog

## 2026-09-14（项目代码全域静态分析与代码净化实施）

- **根目录与非受控目录物理清理**：
  - 彻底清理根目录下散落的临时重定向文件（`--help.rec`）、R 画板缓存（`Rplots.pdf`）、根目录直接运行生成的 `Pest*.OUT` (7个) 与 `*mapping.csv` (3个)；
  - 清理根目录下多余的 `DSCSM048.EXE` 副本（保留 `workspace/` 及系统的单一来源）；
  - 清理根目录未清理的工作目录 `_seasons/`（含 40 个过程文件）与历史崩溃转储 `failed_dssat_artifacts/`；
  - 移除外部无 package.json 的孤立包目录 `node_modules/` 以及 `data/user/ref/~$25SP硝态氮铵态氮参考.xlsx` 临时锁文件；
  - 彻底移除未受版本控制但严重干扰全局搜索的 8 月 macOS 历史整库克隆目录 `macOS_dssat_n_response_workspace_20260803/`，以及 102 个子目录的错名图表转储目录 `figture/`。
- **工作区 (`workspace/`) 淘汰旧脚本治理**：
  - 彻底删除 15 个 2026-07-21 遗留旧调试脚本（`generate_pst.py`, `generate_pst_improved.py`, `debug_tmtgrow.py`, `extract_baseline_sims.py`, `extract_best_params.py`, `generate_pest_outputs.py`, `run_dssat_direct.py`, `run_dssat_test.py`, `setup_improved_run.py`, `test_exe.py`, `test_pest_out.py`, `test_pest_out2.py`, `test_stub.py`, `test_tmtgrow.py`, `verify_improved_weights.py`）及废弃文件（`DSSBat`, `t8_formal_run_20260721.log`, `_v14_excl_tighten.csv`, `trash/`, `tmp/`, `scratch/`）；
  - 将 `workspace/plot_results.py` 存根规范化为与 `analyze_results.py` 一致的 `runpy.run_module` 模式；
  - 严格保留受 `tests/test_migration.py` 保护的 3 个兼容存根（`analyze_results.py`, `build_pest.py`, `run_dssat.py`）。
- **工具箱 (`tools/`) 瘦身与结构化归档**：
  - 彻底清理 `tools/scratch/` 下直接改源码的 3 个热补丁脚本及过期根级补丁（`patch_build_pest_paths.py`, `sort_docs.py`, `run_test_sa.py`）；
  - 建立 `tools/archive/historical_explorations_202608/` 与 `tools/archive/historical_sa_202607/`，将 400 余个 7-8 月历史探索性单次脚本统一归档隔离；
  - 顶层 `tools/` 恢复为以 `run_parallel.py`, `freeze_bounds.py`, `import_experiment_bundle.py` 为核心的 16 个受控生产工具。
- **核心代码库架构去重 (`src/calibration/run_dssat.py`)**：
  - 消除 `src/calibration/run_dssat.py` 与 `src/dssat/run_dssat.py` 之间 4140 行逐字重复代码；
  - `src/calibration/run_dssat.py` 重构为轻量级隔离调度包装器（175 行），直接调用并委托底层 `src.dssat.run_dssat`，并向后兼容导出 `prepare_run_directory`, `DATA_DIR`, `_atomic_copy_back` 等隔离 API；
  - 全套回归测试（`test_dssat_safety.py`, `test_concurrency_isolation.py`, `test_run_state_and_parallel.py`, `test_migration.py`）32 项全部 100% 通过。
- **数据目录说明完善**：
  - 在 `data/user/ref/DSSAT文件/` 下建立 `README.md`，明确该目录下历史整理脚本仅用于原始数据审计溯源，不参与自动化校准管线；
  - `notebooks/` 历史文件移入 `notebooks/archive/`。


- 完成三路只读盘点（报告：`docs/开源整理_绘图代码与图表资产静态分析报告_20260831.md`）：R 论文轨 17 文件无孤立脚本、无死函数；Python 诊断轨约 50 文件、以 plot_dynamics.py 与 evaluate_fixedsoil_official_best189 两大引擎为核心，全部输出落在 gitignored 区；figture/（287MB）与 figures/（53MB）仅写不读、src 零依赖；git 跟踪图像当前为 0。
- 按用户裁决执行：13 个 0818 批次零引用一次性绘图/评估脚本归档 `tools/archive/oneshot_plot_diagnostics_20260804_10/`（组内自洽，附 README）；R 管线删除两个"实现未登记"的灰色分支（`fig1_sa_results`、`figs1_sa` combined，连同 `build_morris_results`/`build_morris_s1_combined`，R parse 验证通过）；命名合规——`fig_fixed_multi_arm_*` 与 `analyze_results` 的 8 处输出统一 `diagnostic_` 前缀（plot_dynamics.py 两处无前缀输出因协作者 WIP 未动，已记录于协作者确认单）。
- figture/、figures/、workspace 图表产物按裁决**全部保留**（figures/ 根部 fig01-06 为唯一不可再生资产）；4 个 untracked 一次性绘图脚本列入《待协作者确认》问题 3。
- 事实更新：本日确认协作者 2026-08-30 条目（25SP 观测全链条重构）后，25SP 鲜产量现行口径已改为算术平均、废除加权小区产量——绘图审查报告中"加权产量"结论相应标注为历史口径（见该报告 §五附注）。
- 视觉核查与废案清理（用户批准）：抽检 6 张代表图确认 figures/ 根部 fig01-06 套装为废案（fig01-03 X 轴把 YYDDD 误作 DAP 致模拟线坍缩、fig04 指标超数学上限、全部为重构前旧契约且生成脚本未入库不可复现），撤回此前"保留并入库"建议；删除 figures/ 整目录、figture/ 根部 18 个重复副本、`_history` 23 个 DEMO 图目录、哈希污染的 `paper_figures_conditional_full199`、`r_paper_demo/paper_figures` 旧版式与 `workspace/generate_comparisons.py`；归档 v6/T10 时代诊断脚本至 `tools/archive/superseded_diag_20260831/`。figture/ 旧批次与全部现行绘图代码按裁决保留。
- 26SP 0629 期缺失 LAI 补齐（用户批准方案 A）：叶干重/LAI 比值全季稳定（三期均值 17.90–18.96，总 CV≈12%），留一期交叉验证证明全局常数方案最优（MAE 6.1%，分处理方案反而退化至 9.3%）；以 R=18.52 反推 26180 期 12 个小区 LAID（32 行有效重复，4 行已批准剔除标记排除），raw_sd=sqrt(sd²+(0.079·LAI)²) 并全程携带 imputed 标记。**只增不改**：新版本 bundle `xxql2601_lai0629_imputed_20260831` 派生自 canonical XXQL2601 且逐字节保留其全部既有数值（不预设 26SP 数值系裁决），FileA LAIX 保持仅实测。运行时闸门一致性 max diff=0.0。审计：`docs/26SP_0629期LAI补齐方案与审计_20260831.md`。
- 论文图/诊断图目检评审（11 张）：条件集合 5 张与 Morris Fig1 为出版级予以保留；建议淘汰 FigS7（3 对条形信息密度过低）与 S5/S6 渲染件、FigS2 n64_n128 旧单季版；建议立项 R 重实现 response_structure_audit（响应幅度比量化，registry 无对应图）与 metrics 热图面板——见 `docs/开源整理_论文图与诊断图评审建议_20260831.md`（4 个执行项待用户裁决）。

## 2026-08-30（25SP 观测数据全链条重构、品质集升级与全项目同步）

- **25SP 采收事件与鲜产口径修正**：
  - 剔除 `2025春产量数据集.xlsx` 中 7月17日 与 7月22日 估算采收记录，25SP 采收事件统一截止于真实实测末次 **2025-07-11（DAP 117 / `25192`）**，共 10 次真实采收事件；
  - 鲜产量计算口径统一为**小区内各行实测产量（`产量` 列）直接算术平均**，废除早期基于 `加权小区产量` 的几何加权；
  - TMX `*HARVEST DETAILS` 10 次采收事件同步更新。
- **25SP 果实品质与干物质率升级（2025春品质集.csv）**：
  - 废除原仅 1 次测定且含离群值的品质来源，全面升级为包含 3 次独立全小区测定的 [`data/user/ref/DSSAT文件/2025春/2025春品质集.csv`](file:///d:/Tomato_Cal/data/user/ref/DSSAT文件/2025春/2025春品质集.csv)；
  - 各采收批次就近动态匹配实测干物质率（DMFR），彻底纠正 W1N0（小区 13）干物质率异常偏低（3.21% $\rightarrow$ **5.39%**，累积干重从 1,771.6 恢复至 **2,975.5 kg/ha**）；
  - 更新核心生成器 [`tools/experiments/build_trial_observations_v2_20260726.py`](file:///d:/Tomato_Cal/tools/experiments/build_trial_observations_v2_20260726.py) 重建权威 `XXQL2501.TMA`、`XXQL2501.TMT`、`FileT_values.csv`、`FileA_values.csv`、`fruit_quality_match_audit.csv`、`observation_uncertainty.csv`。
- **25SP 初始土壤无机氮按物理小区号映射与 6/7/8 处理清理**：
  - 依据最新 [`data/user/ref/25SP硝态氮铵态氮参考.xlsx`](file:///d:/Tomato_Cal/data/user/ref/25SP硝态氮铵态氮参考.xlsx)（工作表 `三重复与判定`），以物理**小区号（Plot Number 2, 3, 4, 5, 9, 10, 11, 12, 13）** 作为唯一索引计算 20/40/60 cm 三重复算术平均值；
  - 权威模版 [`data/user/ref/XXQL2501.TMX`](file:///d:/Tomato_Cal/data/user/ref/XXQL2501.TMX) 彻底清理 6、7、8 处理的数据段与表头，保证定宽格式 100% 规范。
- **全项目原子分发与同步**：
  - 新增标准化同步工具 [`tools/experiments/sync_25sp_tmx_tma_tmt_20260830.py`](file:///d:/Tomato_Cal/tools/experiments/sync_25sp_tmx_tma_tmt_20260830.py)；
  - 完成全项目所有运行目录与历史归档的原子更新：**3,284 个 `XXQL2501.TMX`**、**3,084 个 `XXQL2501.TMA`**、**3,085 个 `XXQL2501.TMT`** 同步成功率 100%；
  - 核心自动化回归测试 10/10 全部通过。

- 完成 TMA(FileA)/TMT(FileT) 生成链路、文档口径与 25SP 均值口径的只读审查（报告：`docs/开源整理_TMT_TMA数据链唯一性与25SP均值口径审查_20260830.md`）。确认：运行时只读+强一致性闸门完好；生成侧存在 6 个内容级写入方 + 10 余个复制/同步方，无单一权威入口；25SP 重复之间均为算术平均（审查时点唯一加权为鲜产量的小区内行位置加权，源 xlsx 预计算；**该加权口径已被本条目上方的 08-30 重构废除**）。
- 取证确认 HEAD 提交状态健康：canonical 根 bundle 按设计保留剔除前数值，repfilter→from_scratch→armab 派生链含 2026-08-19 已批准的剔除修正且链内一致；**但当前未提交的协作者 WIP 已把整条 25SP 派生链观测文件批量回退为剔除前数值**（结构性根因：REMOVALS 仅存在于 apply_repfilter 旁路，经 canonical 生成器的再生产生剔除前数值）。已出具 `docs/待协作者确认_观测数值系与WIP覆盖_20260830.md`（含 26SP 同一观测 4 值并存与双缩放 WIP 脚本冲突），待确认后处置。
- 按用户裁决执行：canonical 根目录放置 `OBSERVATION_AUTHORITY_NOTICE_20260830.md`（repfilter 系为权威）；《DSSAT_FileA_FileT_Excel操作指南》加"已被取代"横幅（旧生成器算术产量口径 vs 现行加权产量）；《数据来源与配置规范手册》§3.2 标注 LAIX 禁入 Phi、N2−N0 已收窄为 N3−N0。定宽丢失举报经核实为误报，关闭。

## 2026-08-29（开源整理批次 1：元文档事实性修正）

- 依据代码静态分析报告（`docs/开源整理_代码静态分析报告_20260829.md`）修正元文档与代码不符项：`requirements.txt` 补 `scipy`/`pymoo`/`pyyaml`、移除全仓库未 import 的 `flopy`。
- README 与《目录与输入资产规范》的 SYMBI 政策由过期 `SYMBI=Y` 更正为现行非豆科政策 `SYMBI=N`（配套 `POTAS=N`，见 2026-07-20/21 条目）；`FRCNOD` 描述改为与 `param_registry.py` 一致（保留 (0,1) 物理域窄幅 SA 探测，非固定值）；README Sobol 状态行更新为三季 N128→N256 证据链，写作参考链接改指 W5 重构版；README 结构图补 `src/management/` 与 `tools/`。
- AGENTS.md：`format_val()` 更正为 `_format_to_width()` / `_format_to_width_preserve_space()`；FL-VS/XFINT 约束以 `param_registry.py` 为真源改写；观测组由 4 组补全为 8 组；Workspace stub 描述按实际机制更正；figure registry 描述按 23 行现状重写；移除易变的"当前分支"信息，改为指向 git 与本 CHANGELOG。
- `.gitignore`：`figures/` 锚定为 `/figures/`，解除对 `configs/figures/` 配置的误伤。
- CLAUDE.md 降级为指向 AGENTS.md 的指针；《绘图工作交接文档_20260801》删除（其运行诊断轨说明并入《科研图表设计与开发计划》§4）；《生理黄金平衡解设计原理与复现指南》移入 `docs/archive/designs/`。
- 开源整理批次 2（文档裁决与归档）：47 项过时文档按主题归档入 `docs/archive/`（论文旧底稿 2、SA 历史 2、任务卡/模板/参考 4、reports 31 份等），`ARCHIVE_MANIFEST` 登记去向与理由；`docs/README.md` 索引重写覆盖全部现行区文档；修复 7 处死链；《项目状态与科研启动清单》补 8 月状态摘要。
- 开源整理批次 3（非核心代码清理）：删除 `src/parallel/` 空包、`src/reporting/posterior_extended.py`（520 行零引用）、`src/sensitivity/sa_postprocess_sobol_interpret.py`（硬编码路径一次性脚本）及 `build_pest.py` 三个已声明废弃的 mode 分支（eggplant_harvest/process/v13，约 240 行；旧命令现硬拒绝而非落入 legacy 分支）；约 60 个历史迭代脚本按家族归档入 `tools/archive/` 六个主题目录；`tools/experiments/` 11 个 `test_*.py` 更名 `exp_*.py`（避免 pytest 误收集）；删除 2 个临时 `.mjs`；`setup_workspace.py` 同步移除对已删路径的引用。
- 已知待修（批次 4）：`d216627` 快照将 `src/calibration/run_dssat.py` 覆盖为 `src/dssat/run_dssat.py` 副本，原隔离层 API（`prepare_run_directory`/`_RAW_DSSAT_OUTPUT_FILES`/`_atomic_copy_back`）丢失，`src/management` 导入链与 `test_dssat_safety`/`test_concurrency_isolation` 暂断裂。

## 2026-08-28（协作者率定代码演化快照 20260820-28 入库）

- 输入包演化：0-4/60cm 土壤剖面系列、13 层 SLNF、measuredn 实测无机氮 IC 替换（三个 v3_measuredn 版本化输入包）等（协作者 WIP）。
- 试验配置与冻结边界矩阵更新（协作者 WIP）；率定工具（prepare/launch/evaluate/plot）批量演化与新增。
- 新增 ArmAB RRMSE 26SPN 率定评估绘图脚本与诊断结果集；batch-1 率定准备（报告驱动的边界释放与 W_RESPONSE 预算提升）。
- PEST-IES 条件集合不确定性图表管线（方案一/二/三，20 成员 DEMO + 全量 199）；paper/R 图表脚本更新。
- 仓库结构精简：根目录运行残留解除跟踪、`_seasons` 陈旧物化清理、figture 末轮批次目录删除、untrack node_modules。

## 2026-08-19（重复剔除与数据 QA 执行）

- 执行批准的重复剔除方案（15 例，repfilter_v1）；追加小区 7 叶干重剔除，并记录被拒绝的跨日期交换指令。
- 25SP 9 号处理 INITIAL CONDITIONS 按用户指定值同步全部活跃 TMX。

## 2026-08-18（GLM 后续率定开发 WP1–WP5 与源数据卫生）

- GLM 后续率定：新增 IES→GLM 构建器与并行 `glm` 模式（WP1/WP2）；Jacobian 审计器、评价器、正式启动器与基线冻结（WP3/WP4/WP5）；差分步长抽查与稳定性判据修正；烟雾试验问题修复、code review 五项缺陷修复 + 回归测试、端到端基线验证。
- 源数据卫生：生长指标源数据质量审查报告（20260818）与离群值分解；执行方案 A（零测量值改动）。
- checkpoint：IES-NSE 两季正式率定代码基线（20260817 官方运行产物状态）。

## 2026-07-30（SA 证据 finalize 与论文图产出）

- finalize sensitivity evidence and paper figures：三季 Morris/Sobol 证据冻结与 R 论文图链产出。

## 2026-07-23（v2 方案操作机制代码实现：DAP 物化 + NSGA-III + 两年编排）

在 v2 方案配置与数据门之上，补齐方案描述的操作机制代码，使正式运行链路在参数集冻结后可直接启动：

- 新增 `src/management/dap_policy.py`：DAP（移栽后天数）政策物化器。`build_calendar_stages()` 把统一的 DAP 阶段通过各年移栽日期映射到 YYDDD 日历（2025: DAP96→25171、DAP145→25220；2026: DAP96→26165、DAP129→26198），同一政策在两年日历不同但 DAP 区间相同。`materialize_dap_scenario()` 复用 v1 已审计的 FileX 改写原语（`_events`/`_allocate`/`_replace_field`），但用 DAP 推导的日历阶段驱动；强制单次灌溉上限、DAP96 后停氮、S4 氮比例=0；基肥（移栽前事件）归入定植阶段；写 `MgmtEvent.OUT` 账本（`rainfall_considered=false`）与 manifest。`read_final_chfpw()` 包装 `_read_freshwt_var_by_run` 返回 `FreshWt.OUT` 末行累计鲜果重。
- 新增 `src/management/nsga3_search.py`：`maximin_lhs_initial_population()` 用 `scipy.stats.qmc.LatinHypercube`（random-cd 优化）生成可复现的 128 候选初始种群（仅播种，非正式结果）；`decode_to_candidate()` 把 8 维决策向量解码为 `CandidatePolicy`（S4 灌溉比例=剩余、S4 氮比例=0，simplex 约束按构造满足）；`TwoYearRobustProblem`（pymoo）暴露 4 个最小化目标（产量取负）+ 2 个逐年产量底线不等式约束，失败 DSSAT 候选给大惩罚并判不可行；`build_nsga3()` 用 Das–Dennis 参考方向构造 NSGA-III。
- 新增 `src/management/robust_orchestrator.py`：`evaluate_policy_two_years()` 对 2025、2026 各物化→stage→execute→读 CHFPW；`run_formal_nsga3()` 顶层入口，先 `load_formal_design`（含降雨审计），再校验参数集 `science_validated`——未通过且无 `--allow-engineering-precheck` 时 `PermissionError` 阻断；逐 seed 跑 NSGA-III，写出 Pareto CSV 与 manifest；工程预检输出强制带 `engineering_precheck_` 前缀、`approval_scope=engineering_precheck`，不可作为正式结果引用。
- 新增 `tools/run_formal_optimization.py` CLI（`--design/--parameter-set-dir/--work-root/--seeds/--allow-engineering-precheck` 等）。
- 更新 `src/management/__init__.py` 导出 v2 公共 API（`CandidatePolicy`、`build_calendar_stages`、`decode_to_candidate`、`evaluate_policy_two_years`、`run_formal_nsga3` 等）。
- 新增 `tests/test_management_dap_policy.py`（9 条）与 `tests/test_management_nsga3_search.py`（8 条）；全部 27 条管理测试通过（含 v1，无回归）。NSGA-III 真实 DSSAT 运行受参数门保护，单元测试用可注入的 mock 评估器，不依赖真实 DSSAT。

## 2026-07-23（双春季气象驱动的直接 DSSAT 多目标稳健优化方案 v2）

- 将管理优化方法由“32 个 LHS 点 + 季节总水量/总氮量比例”升级为直接 DSSAT–NSGA-III 双春季稳健优化；LHS 降级为初始种群，不再被当作正式优化结果。
- 正式研究对象仅包含新乡 2025 春和 2026 春气象，同一套水氮政策在两年分别运行，四目标为：两年平均鲜果产量、较差年份鲜果产量（最大化），季节灌溉量、季节施氮量（最小化）。
- 管理政策改用统一 DAP 生育阶段（定植缓苗 0–28、冠层扩展 29–63、开花–早采收 64–96、盛果–后期 97–145）传递，避免把 2025 日历日期直接套到 2026；末段施氮固定为零。
- 逐年施加 90% 产量底线（`yield_floor_fraction_of_year_specific_reference`），并在 `aggregate_policy_evidence()` 中分别按年评估，防止均值掩盖某一年的显著减产。
- “天气稳健性试验”与“两年实际初始土壤条件回放”在配置中明确分角色，避免混淆天气效应与初始条件效应。
- 硝态氮淋失仅在 DSSAT 氮平衡输出经单位与质量守恒审计后才允许进入目标函数；当前以施氮量为资源投入目标，不伪称环境损失。阶段土壤水分触发阈值列为第二阶段，在串行状态续跑器验证前不宣称完成实时阈值优化。
- `load_formal_design()` 增加双年气象门：校验移栽—末次采收覆盖，并对 `.WTH` 全记录审计 `RAIN=0`（温室滴灌系统无降雨作为管理供水）。两个春季文件均已确认降雨量为 0。
- 设计测试增至 6 条，覆盖双年天气年与无代理、稳健聚合与较差年、降雨审计、覆盖门、LHS 仅作初始种群、逐年产量底线。状态为 `formal_design_ready_parameter_pending`。

## 2026-07-22（T10 直接连续采收与季节适应性联合率定方案，待实施）

- T10 改用 FileT/FreshWt.OUT 的直接累计 `CHFPW`、`CHPDT`，取消 PWAD/PWAI 及累计差分进入正式 Phi。
- 对 CHFPW/CHPDT 冻结同尺度 `ln((y+1 kg ha-1)/(1 kg ha-1))` 目标函数，以缓解时序累计量异方差；原始 FileT、DSSAT 输出、指标和论文图保持物理尺度。
- 采收日历规定真实模型采收提前 1 天、在本地 FileX 副本追加虚拟末次采收并延长模拟结束日；输出采用真实观测日 ±1 天有界就近读取，虚拟事件不产生 Phi 或图表点。
- T10 Phi 家庭预算调整为 `PLANT_N=1.00`、`HARVEST_FRESH=1.25`、`HARVEST_DRY=1.25`，并要求按家庭—季节—变量一次性分配，避免采收轮次膨胀。
- T10 候选 `XFPHT` 下界由 35 放宽为 31，仍以 `XMAGE=8–30` 保证所有样本严格满足 `XMAGE<XFPHT`。

## 2026-07-22（T9 连续采收观测合同与高维率定提案）

- T9 高维诊断候选扩展为 55 个共享作物/生理参数；`EM-V1` 按用户决定恢复旧版基线 22 和 10–40 诊断域，`FL-VS` 使用 100–140。
- 新增 T9 observation/group policy：物候 family budget 降至 0.25，LAIX 强制 diagnostic-only，PWAI 为主要收获证据，每季仅最终 PWAD 作为累计锚点。
- HWAM 永久退出率定 builder；显式重新加入会失败，policy 即使误设 calibration 也会强制零权重。保留 runner 输出仅供历史诊断。
- 修复多季 design 已声明 observation policy、但未显式传 CLI 时未自动加载的问题；T9 PST smoke 生成 464 条登记观测、336 条活动观测，HWAM=0、LAIX 活动数=0、最终 PWAD 活动数=16。
- 对账旧/新 Phi：旧最低 21,552.8 中 HIAM 贡献约 19,292.2；扣除不适用 HIAM 和重复 HWAM 后约 2,115.2，说明数万与数千主要是目标及权重尺度差异。
- T9 code review 修复：冻结的 64 项参数现均进入 PST（55 active + 9 fixed）；补齐根氮、氮胁迫和 ECO 参数的物理硬边界；IES 工程门只审计进入 Phi 的观测，零权重缺失诊断不再误报模型失败；一键启动器默认严格执行 D1 的 600 members、2 次更新，并在工程质量门失败时返回非零。8-member/1-update smoke 通过，8/8 成员保留。

## 2026-07-21（实际试验率定/验证输入包）

- 将 XXQL2502、XXQL2601 原 FileX 的 `SYMBI` 由 Y 改为非豆科适用的 N，保持 DSSAT OPTIONS 固定宽度；两季原始目录补齐 SOIL.SOL。
- 用户确认 plot 1–12 与 TN1–TN12 一一对应；FileA/FileT 标题和注释改为标准 DSSAT treatment-number 语义，不改观测数值。
- 输入导入工具新增独立 observation source、calibration/validation 角色和 actual-trial 保留门；正式包必须逐字保留 `*SOIL ANALYSIS`、`*INITIAL CONDITIONS` 及逐处理 IC/SA/MI/MF，拒绝受控 SA 的统一初始条件。
- 生成 XXQL2502 actual-trial calibration 包和 XXQL2601 independent-validation 包；validation manifest 禁止 parameter calibration。两包完整性与观测审计通过，仅保留深层 SSKS/土壤质地缺失及植株氮观测范围等已披露警告。

## 2026-07-21（T7 v2 参数率定设计与基础代码）

- 将主率定选择规则改为：排除模型定义不适用的 `PM06` 后，分别在 general-genetic 与 water-nitrogen-response 域累计至 90%，再取 17 参数并集；新增可复现、默认拒绝 `science_pending` 的 proposal-only 选择器。
- 审计 XXQL2502/XXQL2601 FileA/FileT：累计采收单调且 FileA 派生量与 FileT 一致；识别原始输入目录缺 SOIL.SOL、`SYMBI=Y`、XXQL2601 肥料事件行序，以及 TRNO plot→treatment 映射待确认等正式运行阻塞项。
- 修复报告解析器在 FileT 仅提供 CHPDT/CHFPW 时未生成增量采收的问题，统一用相邻累计值差分并增加回归测试。
- 新增只读异参同效约束审查器：根据边界堆积、坍缩、强 Spearman 补偿和功能性异参同效候选生成 review proposal；永不自动修改 frozen bounds。
- T7 主设计更新为 17 参数、P/C/N 分块工程诊断和 240-real 全新联合先验；XXQL2501+XXQL2502 联合率定、XXQL2601 独立验证的正式运行仍受输入、sigma、边界和资源审批门控制。

## 2026-07-20（三季正式敏感性分析输入与交接）

- 将 XXQL2501、XXQL2502、XXQL2601 导入版本化 sensitivity source bundle；早期曾误用 `SYMBI=Y`，现已由 2026-07-21 修复统一替换为非豆科政策 `SYMBI=N、POTAS=N`。同时修正 XXQL2502 季节标题，在不改变施肥值的前提下规范 XXQL2601 MF2 行序，并按用户确认将 XXQL2601 TN12 更正为 W1/N0。
- 为三季生成共同 `MI1/MI3 × MF1–MF4` 八处理受控 SA FileX；季内 IC 按深度中位数统一，原始用户目录保持不变。
- 输入校验增加显式 simulation-only 模式：FileA/FileT 对 SA 可选，对率定/验证仍为硬门；SA builder 与反事实输入生成器使用该模式。
- 汇总 2025 春秋植株 NPK；主 55 参数域不变，新增叶/茎/shell `PRO*` 独立 SA-B 候选范围，root `PRORT*` 因无根样继续固定。
- 新增三季设计 v2 与实施交接；正式运行仍须通过 baseline、输出契约和 bounds freeze 门。

## 2026-07-19（正式多季遗传 SA 参数域候选）

- 建立两春一秋候选设计：同域同 seed 逐季 Morris、逐季质控后汇总；推荐一春一秋率定、另一春整季验证，待三季输入齐全后冻结。
- 分阶段温度候选域更新为 `TB*=8–12`、`TO1*=20–27.5`、`TO2*=28–33`、`TM*=34–45 °C`；`FL-VS` 改为初值 120、SA 范围 100–140，并增加率定可辨识性条件。
- 修复动态分配参数矛盾：候选 `XMAGE=8–30`、`XFPHT=35–70`、`XFINT=0.10–0.35`，数值安全包络与科研建议范围分离。
- `FRCNOD` 归入根瘤参数组并固定排除；FileX 输入审计新增非豆科 `SYMBI=Y` 兼容性校验门禁，导入工具支持可追溯修正并继承来源 manifest。
- 主遗传 SA 中固定实测 SOIL/IC；测量偏差仅进入单独、窄范围且由测量误差驱动的环境稳健性分析。
- 新候选 bounds 仍为 `proposed/ready_for_formal_run=false`；仓库尚缺第二季春季和秋季输入，未启动正式 DSSAT/SA/IES。
- 全套回归 `236 passed, 2 skipped`，`compileall` 通过。

## 2026-07-19（staged builder 干净环境修复）

- `eggplant_stage2` 的物候和季末实测值改为直接从版本化 FileA 构建；时序与采收继续从 FileT 构建，不再读取 `workspace/Evaluate.OUT`。
- 多输出 PST 构建器仅在输出定义缺少观测 DataFrame 时才读取 Evaluate；staged 输出全部携带冻结观测表，旧模拟输出无法影响观测值、权重或结构。
- staged 继承冒烟改用输入 bundle 内的 `DSSBatch.v48`，新增 FileA 数值转换和“禁止读取旧 Evaluate”回归测试。
- `compileall` 通过；全套测试 `232 passed, 2 skipped`。

## 2026-07-19（文档体系收口）

- 重写根目录 `README.md`，统一项目定位、当前科研边界、输入位置、敏感性分析、分阶段率定、结果检查和论文图表入口。
- 新增“项目状态与科研启动清单”和“敏感性分析与率定用户指南”，将分散在阶段计划中的仍有效规则合并为当前用户入口。
- 将已完成计划、旧设计、迁移材料、历史交接和旧 SA 说明迁入 `docs/archive/`；上游手册与模型背景材料迁入 `docs/reference/`；实施报告保留在 `docs/reports/` 并新增索引。
- 明确权威顺序：当前产品定义与规范优先，报告只记录证据，归档文档不得作为新运行配置依据。
- 全套回归为 `229 passed, 2 skipped, 1 failed`；失败揭示 staged builder 在干净 workspace 下仍隐式依赖旧 `Evaluate.OUT`，已记入科研启动清单，留待独立代码修复。

## 2026-07-19（目录清理与输入资产规范）

- 明确 FileX/FileA/FileT 与配套土壤、气象、批处理文件必须放在版本化 `data/user/experiments/<bundle_id>/`；CUL/ECO/SPE 基线模板必须放在 `data/templates/genotype/*.base`，运行副本仅能存在于 `workspace/runs/<run_id>/`。
- 清理可再生缓存、布局 demo 与旧 workspace 根目录运行输出；保留已审计运行、正式 SA 来源快照和历史归档，避免破坏可追溯证据。

## 2026-07-19（T4.4 正式论文包证据链收口）

- 正式 `paper_data_manifest.json` 现在强制携带同一 run manifest 中的 input、bounds、observation policy 和 validation split SHA-256；缺失或格式错误时导出失败。
- R 对正式率定图强制 `scenario_type=actual_trial_calibration` 与四类冻结 provenance；DEMO 仍只能显式用于布局 QA。

## 2026-07-19（T4.3 最小 R 图表接入）

- 新增经过哈希、run_id 与 `tooling_demo` 状态绑定的 T4 数据适配器；R 仅消费其冻结 CSV/manifest，绝不读取 DSSAT/PEST++ 临时目录。
- Fig. S5–S7 已完成 DEMO 核心和真实 R 4.5.2 导出 QA：参数独立尺度的 conditional-ensemble 区间、Spearman 描述矩阵、候选对参数/预测距离。所有输出为 `DEMO_`、有水印且不可作为科研结论；PCA/VIF/t-SNE/聚类不纳入 MVP。
- 测试：`228 passed, 2 skipped`；图表契约定向测试 `18 passed`。

## 2026-07-19（T4.2.1-B code review 补丁完成）

- 修复 posterior 上游哈希缺失/格式错误时可绕过冻结链的缺口；两个必需 SHA-256 现必须存在、格式正确且与当前 S4 相等。
- 新增 posterior `candidate_pair_count` 与哈希绑定 CSV 行数一致性校验。
- 统一默认 runner 实际 subprocess 与 candidate run manifest 的完整 argv；非零返回码诊断与 stderr SHA-256 进入两级 manifest 证据链。
- header-only candidate comparison 补齐 `candidate_side`，成功/失败 bundle 保持同一最小 schema。
- 提交 `10d3498`；候选模块 `26 passed`，全套 `225 passed, 2 skipped`，compileall 通过。本轮未运行 DSSAT，未改变距离/comparison 定义，已复核的 `_v2` 继续作为 `tooling_demo` 数据。

## 2026-07-19（T4.2.1 契约收口完成）

- T4.2.1 候选解预测复跑契约收口（A 代码+测试 / C 受控重放+审计）全部完成，闭合 T4.2 code review 的 5 项发现（3 P1 + 2 P2）。代码提交 `3433c29`。
- [P1] 冻结证据链闭合：observation policy 与 harvest_var 默认从 S4 run_manifest 解析；CLI 覆盖必须哈希/值匹配冻结值；posterior 上游 `calibration_finalize_sha256`/`calibration_artifacts_manifest_sha256` 与当前 S4 强制比对，不一致即在任何模型调用前失败。
- [P1] 候选运行完整性：候选目录必须本次新建且空（拒绝复用旧 OUT，无 --force）；候选可用性要求 `returncode==0 AND 无 missing`；非零返回码 + 预存旧 OUT 的场景现标记为 `prediction_incomplete`（不再误判成功）；默认 runner 不再 raise，返回非零码并把 stderr 诊断存入 run dir。
- [P1] candidate_comparison.csv 现写 A/B 两侧 + `candidate_side` 字段（修复原只含 A 侧、丢失 realization 16/20/32 的 bug）。
- [P2] 消费端 candidate-pair schema 门：1-3 对、唯一 pair_id、real_a≠real_b、严格非负整数（4.5 拒绝而非截断为 4）、最多 6 唯一 realization。
- [P2] 执行元数据冻结：去掉 `--cultivar TM0008` 硬编码（与 S4 model command 一致，cultivar 由冻结 FileX 决定）；每个 candidate_run_manifest.json 记录可复现 argv + harvest_var；sigma 分量语义改为基础 sigma>0、附加 model_sigma/sigma_floor≥0（匹配共享 observation-policy 语义）、组合 sigma_eff 有限正。
- 新增 8 项负向/回归测试（与 5 项发现一一对应 + sigma 散活）：policy CLI 哈希不匹配、harvest_var 不匹配、posterior 上游过期、schema 严格（4 对/4.5/自配对/重复 pair_id）、非空 out_dir 拒绝、非零返回码+预存旧 OUT→incomplete、comparison 含 A/B 两侧、argv 无 --cultivar。
- T4.2.1-C 受控重放：从干净 `3433c29` 重新生成 posterior demo + 运行 candidate_predictions 到新目录 `t4_candidate_predictions_v2/`（未覆盖 T4.2-B）。6/6 returncode=0，A/B comparison 覆盖全 6 realizations，3 对距离与 T4.2-B 精确一致（0.134508/0.015569/0.022550），manifest git_dirty=false，17 artifacts 哈希逐项复核 0 failures。
- 全套测试 219 passed/2 skipped（基线 211 → +8）；compileall src+tests 通过。全程 tooling_demo/science_pending，未运行新 IES/SA，未改 bounds/sigma/split。证据见 `docs/archive/development_records/P2_MVP_T4_2_1_运行审计_20260719.md`。

## 2026-07-19（T4.2 候选解预测复跑完成）

- T4.2 候选解预测复跑三阶段（A 代码+测试 / B 真实复跑 / C 文档）全部完成。新建 `src/reporting/candidate_predictions.py`（单入口 `build_candidate_prediction_bundle` + CLI）：manifest 链哈希校验 → 候选 realization 提取/参数导出（含 S4 固定的 XFRT/XFINT）→ ≤6 次隔离确定性 DSSAT 复跑（`src/calibration/run_dssat.py` 脚本路径调用）→ 复用 `validation_metrics.build_comparison_from_rerun` → 冻结 prediction distance（A/B 一对一对齐、raw-scale sigma_eff 不含 group_multiplier、RMS 分层、变量+角色双等权、只用 validation/diagnostic）→ 分类（tooling_demo 下只输出 demo_*/incomplete）→ 17 artifacts SHA-256 manifest。从干净 `b263159`（git_dirty=false）重跑：6 realization 全部 returncode=0，3 对候选（4/16、9/20、2/32）全 `demo_prediction_similar`（prediction_distance 0.13/0.016/0.023，远低于 1.0σ 阈值）。
- 从 `validation_metrics.py` 提取 `build_comparison_from_rerun()` 公共函数，代表解与候选解共用同一 comparison 定义（交接 §6）。
- 新增 `tests/test_candidate_predictions.py`（12 测试，覆盖交接 §9 全部 11 项 + sigma 手算）：hash 篡改/缺 demo flag/realization 缺失重复非有限/去重/A-B 错配/calibration 排除/手算回归/sigma 缺失非正非 raw/失败 incomplete/demo 禁科学标签/manifest POSIX+哈希复核。全套 211 passed/2 skipped。
- 修复 `_default_dssat_runner` 调用方式：`-m src.calibration.run_dssat` 在隔离 cwd 下找不到 src 包，改用脚本绝对路径（与 `sa_model.py` 同模式）。
- 全程 `tooling_demo`/`science_pending`，未读 calibration Phi，未运行新 IES/SA，未改 bounds/sigma/split，未输出科学标签。结果不建立功能异参同效。证据见 `docs/archive/development_records/P2_MVP_T4_2_运行审计_20260719.md`。

## 2026-07-18（T3.1 review 与 T4 最小接口）

- 复核 T3.1：干净 S4 的 16 项核心产物哈希、40/40 成员和工程状态均通过；修正审计记录中末轮 mean Phi，将误写的 `760.956` 更正为文件实值 `791.927`。
- artifact manifest 路径统一写为 POSIX 相对路径，并新增下游校验器；缺失、重复、越界或 SHA-256 不匹配的产物在 validation/posterior 读取前硬失败。
- 新增 `src.reporting.validation_metrics`：只从冻结输入包和代表确定性复跑读取数据，按 calibration/validation/diagnostic 完整处理角色输出 canonical `comparison.csv` 与逐角色逐变量 RMSE/MAE/bias；`science_pending` 运行必须显式使用 demo 门。
- 新增 `src.reporting.posterior_summary`：稳定入口只输出全部可调参数的边际收缩/边界诊断、Spearman 相关和最多 3 对候选解；不把 PCA/VIF/聚类纳入 MVP，不在 prediction distance 缺失时称为功能异参同效。

## 2026-07-18（T3 staged run）

- T3 staged calibration 四阶段（S1→S2→S3→S4）全部 `engineering_validated`，继承链完整：S1（20/2, ADAP）→ S2（30/2, +4N, LAI/生物量/氮）→ S3（30/2, +XFRT/XFINT, PWAI 采收）→ S4（40/2, 联合 6 参数）。Phi 分别收敛到 0.81/2822/159/792；每阶段生成中位数代表参数、确定性复跑（LAID/PWAI）和完整 manifest/哈希。全程 `approval_scope=tooling_development`、`science_pending`，未读 validation。证据见 `docs/archive/development_records/P2_MVP_T3_staged_run_20260718.md`。
- [P0] 修复 S4 active 参数被 `--fixed-from` 钉死的缺陷：`apply_fixed_params_csv` 把 fixed_from 的每个参数设成 `status=fixed` 且 `lower=upper=init`，随后 `apply_parameter_stage` 对 active_params 未恢复状态/bounds，导致 S4 `npar_adj=0` 无法运行（S2/S3 因 active 参数不在 fixed_from CSV 里未暴露）。修复：新增 `load_frozen_bounds_lookup`，`apply_parameter_stage` 新增 `frozen_bounds` 参数，对 active 参数强制 `status="none"` 并从冻结 bounds 恢复 lower/upper，保留代表值为 init。回归测试 `test_s4_re_releases_parameters_pinned_by_fixed_from` 覆盖。
- 发现 `run_parallel.py --resume` 与 pestpp-ies 不兼容（`/r option not supported by pestpp-ies`）；S4 改为从干净 build 重新启动。该工具层限制不在本轮修复范围。

## 2026-07-18

- T2.2 最小集成修复（staged calibration 工具链），对应 T2.1 审查的 5 项发现：
  - [P0] 修复 `_fixed_from_provenance` 把代表 CSV 父目录当 run_dir 的 bug：新增 `_resolve_upstream_run_dir`，识别 finalize 子目录布局（`<run_dir>/calibration_finalize/stage_representative_params.csv`）与遗留 run 根目录布局两种合法位置。S1→S2 自动代表解继承入口现在可用。
  - [P1] 统一 manifest 标量序列化：新增 `serialize_manifest_scalar`（YAML 单引号标量，Windows 路径反斜杠保持字面），`_upsert_manifest_fields` 与 `_write_run_manifest` 都改用它，修掉 finalize 追加字段写出非法 YAML（双引号内 `\T` 被当转义）的同源 bug；`_strip_manifest_scalar` 同步升级，单/双引号 manifest 都能无损往返。
  - [P1] 新增 S1→S2 纯构建集成 smoke（`tests/test_staged_inheritance_smoke.py`）：mock prior-only S1 → finalize 生成中位数代表 → subprocess 调真实 build_pest S2 build，验证 S2 PST 含 6 参数（S1 fixed 钉死在中位数 + S2 active），不启动 DSSAT。
  - [P2] DesignSpec 暴露 `bounds_id`/`input_bundle`/`observation_policy_id`，staged 入口分两段交叉校验 CLI 实际值与 design 声明一致（bounds id 字符串、bundle id 来自 input_manifest、policy id 来自 CSV 文件名 stem），不一致即 `parser.error`。
  - 新增 manifest↔finalize↔代表参数三方哈希一致校验，任一不一致即失败并指明三方各自哈希。
  - [P2] Finding 5（`model_failed` 暂无证据生产者）按审查意见不在本轮扩展，保守归类为 `other_dropped` 已安全。
- 全测试：187 passed, 2 skipped（基线 179 → +8：7 单元 + 1 集成）。全程 `approval_scope=tooling_development`、`science_pending`，未启动 DSSAT/IES，未触达 validation。证据见 `docs/archive/development_records/P2_MVP_T2_2_修复记录_20260718.md`。

## 2026-07-16

- 用户批准受控水氮 SA v4：新增 `xxql2501_sa_counterfactual_v1_20260716`，以8个核心处理的分层中位数统一全部 FileX IC 区段的 SH2O/SNH4/SNO3，仅保留 TN2–5/TN10–13 批处理；率定包 `xxql2501_20260716` 保持实测处理特异 IC 不变。
- SA 输出由旧10 TN/230项升级为8 TN/164项：删除 DAP67/95/119 累计果实干重及结构性零方差/冗余响应，新增累计干重 DAP50、成对水分差、按0/130/271/399 kg N ha-1计算的氮响应斜率和斜率差水×氮交互；一般遗传影响与水氮响应分域排名。
- 新增 SA 反事实包生成器、输出契约验证和回归测试；修复 FileX 固定宽度替换。公共剖面最大 SNO3=34.15，且清除未引用旧 IC15 的 SNO3=196 后，DSSAT 基线164/164项有限、无缺失。旧 v3 profile 以原审批哈希归档，既有 Top16/Sobol 批准不得迁移到 v4。
- 批准并哈希冻结16参数 Sobol 清单；旧任意CSV/原地覆盖脚本改为审批门控、全新目录构建，并绑定 frozen、输入和230项输出哈希。
- 并行控制器新增 Morris/Sobol 方法特异审计；Sobol检查完整设计矩阵、0模型失败、无 `-99`、参数/响应契约和有限非退化指数，离线finalize不再误用Morris `.mio`。
- 新增从PEST++ A/B/混合矩阵重算S1/ST及bootstrap区间的可追溯工具；真实 `N=4` 预检72/72成功并复现3120/3120可估点估计，同时确认35项基础零方差，禁止解释小样本排名。
- 完成三个 `r=30` 正式 Morris 案例；seed `20260812`、`20260826` 均1740/1740成功并通过230项逐响应门禁，跨 seed Spearman=0.9962、Top-15 Jaccard=0.875，按自适应预算停止扩展。
- seed `20260729` 的1/1740模型失败定位为 TN2/TN3/TN14 与边界参数组合的可重复交互，整 seed 排除且不据此单独收紧 `SLAVR`；新增离线严格 finalize，应对 controller 丢失但 PEST++ 已正常完成的案例。
- 生成待审 Morris Top-K proposal：14参数稳定核心加边界参数 `FL-SD`、`RTNH4` 的16参数保守并集；未自动启动 Sobol。
- 用户批准并冻结 `eggplant_p1_xxql2501_v3_20260716`，冻结 CSV 与已验证 proposal 字节一致且无自动修复；P1 readiness 全部通过。
- 正式 Morris 改为先构建两个新 seed，显式拒绝历史失败 seed `20260715`；新增跨 seed 稳定性分析，按响应内归一化、特征族和四过程组等权汇总，并自动应用 Spearman/Top-15 Jaccard 判停门槛。
- r=8 预检发现旧响应契约把 DSSAT 实测 `LAIXM` 误作模拟响应，且 `FRUITD_DAP045` 在整个候选域结构性为零；修复为 `LAIXS`，拆分 LAI/果实过程点并将契约收敛为10 TN/230项。
- Morris 科研状态新增逐响应非退化门禁；并行运行结束后同时审核轨迹完整性和 `.mio` 有限性/响应覆盖，避免“进程成功、整体非零”掩盖局部无效输出。
- 新增 P1 运行失败原因长期复盘与复查命令；建立 Git 行尾契约，科研 CSV/JSON 固定 CRLF、代码及 YAML/Markdown 固定 LF，DSSAT 输入按原始字节保存，避免 clean worktree 中审批哈希漂移并兼容既有审批哈希。
- 完成 P1-R2 失效归因：IC 替换不能消除失败，MF 水平具有决定性影响；进一步确认旧 FileX 的 MF2 施肥行分块/错序改变了 DSSAT 实际执行结果。
- 新增管理事件因子连续性和日期顺序输入门禁；创建仅重排 MF2 行、事件值不变的 `xxql2501_20260716` 输入包，旧包不得继续正式使用。
- 输出项目保持10 TN/240项不变，profile ID 升级为 `eggplant_p1_all_treatments_v2` 并绑定新输入包，避免把旧输入身份带入新运行。
- 用户决定深层缺失 `SSKS`、`SLCL/SLSI` 不参与 SA；继续作为 warning/论文限制披露，不再阻塞 P1。
- 新增待审 v3 candidate（`XMAGE 10–20`、`SLAREF 260–375`）；代表失败在新输入与全部处理上70/70重放成功，仍须独立 `r=8` 预检后才能批准冻结。
- 完成 P1-R1 科研运行可靠性：并行运行区分完成、中断、运行时失败和科研状态，支持后台 controller、可审计停止及经 PEST++ 5.2.16 实测的 `.rns` 恢复。
- 新增 Morris 轨迹审计、失败分类、elementary-effect 覆盖率和正式结果门禁；部分轨迹、模型失败或恢复后缺失在途点均不得生成正式排名。
- 新增失败候选精确重放和按 TN 拆分诊断；seed 20260715 的7个代表失败均稳定复现并仅出现在 TN2，v2 暂停正式使用且不自动创建 v3。
- 输入审计显式报告目标土壤深层 `SSKS` 和 `SLCL/SLSI` 缺失，禁止静默接受 DSSAT 默认土壤纹理作为已验证数据。
- 正式 Morris 从预先固定 5 个 seed 改为自适应预算：先执行 2 个完整有效 seed，达到总体 Spearman ≥ 0.90 且 Top-15 Jaccard ≥ 0.80 时停止，否则最多扩展到 5 个。
- 冻结 Python/R 图表职责：Python 仅做 SA/率定诊断和论文数据导出，R 成为未来论文图与补充图的唯一渲染器。
- 新增 `paper/R` 统一主题与 Fig. 2/3/4 核心实现、双重 DEMO 门和 R 产物 SHA-256 manifest；移除 Python 论文绘图入口与样式模块。

## 2026-07-15

- 建立 Fig. 1–6/Fig. S1–S8 科研图表注册表、统一出版 profile、tidy 数据契约和图表 manifest。
- 新增多变量观测—模拟、代表处理动态和 realization 分布 Φ 收敛核心图，支持 PDF/SVG/600 dpi PNG 与源数据导出。
- 删除硬编码迭代、目录并在绘图时重跑模型的旧 `visualize_results`/`visualize_eggplant`；旧 plot_results 仅保留诊断兼容。
- 历史结果必须显式 `--allow-unvalidated-demo`，生成 `demo_` 文件与 `legacy_layout_demo` 标识，不能误作论文证据。
- 将用户更新的 XXQL2501 FileX/SOIL 及配套 FileA/FileT/气象/批处理导入版本化输入包，新增 SHA-256 清单和跨文件科学门禁；权威坐标统一为 35.16°N、113.8°E。
- DSSAT、SA 和率定入口新增显式 `--input-dir`，正式运行可隔离使用用户定义文件，避免从旧 `data/raw`/`Workspace` 隐式取值。
- 批准并冻结 `eggplant_p1_xxql2501_v1_20260715`：57 active，8 层土壤实值 fixed，50 个 TN×层初始水分记录 disabled；废弃错误的 6 层共用 IC 语义。
- 审计 TN2/TN3 与旧 90 项输出：改为全部 10 TN、240 项响应；过程点对齐 FileT 的 DAP 45/67/95/119，移除冗余跨处理均值。
- 当日曾将正式 Morris 预算提高为 5 个固定种子×`r=30`（最多 8700 次 DSSAT）；该固定预算已于 2026-07-16 被 P1-R1 自适应 seed 方案取代。新增输入、输出、边界和本地化回归测试。
- 首个 v1 正式 seed 因 XMAGE/XFPHT 重叠范围产生非法轨迹而触发高失败率门禁并中止；v1 标记 superseded，v2 用 `XMAGE 5–20`、`XFPHT 25–40` 保证严格顺序，并将该关系加入 frozen validator 回归。
- 加固 P0 回归测试：固化 V14 的真实失败基线，拒绝空边界、active 零宽、空参数组、非法边界交换/夹紧、IES 非有限输出、Phi 非有限值及 realization 异常丢失。
- 修正物理硬边界错误排除 DSSAT 自带基线的问题，并以 V14 设计 proposal 生成待审 P1 候选：57 个 CUL/ECO/SPE active，44 个 SOIL/IC 参数恢复 fixed。
- 新增 P1 bounds readiness 门禁和启动计划；pending proposal 仅允许技术构建，未批准时正式预检必须失败。
- frozen metadata 新增最终 CSV 哈希，P1 启动前会检测审批后文件是否被修改。
- P1 基线输出预检发现 MDAPS 全部为 `-99`，已从当前案例默认 SA 输出契约移除，防止缺失指标污染 Morris。
- 修复 `pandas>=3` 与 FloPy 3.10 要求 `pandas<3` 的不可满足依赖组合，新增运行环境版本契约测试。
- 新增可审计 Observation Policy：FileA/FileT 保留实际尺度，`.pst` 观测与 PEST tagged 模拟按同一 `ln((y+offset)/reference)` 变换。
- 新增处理均值 sigma 计算与审计字段，区分重复 SD、`n_effective`、模型误差、sigma 下限和来源；明确禁止把同一处理重复伪装成独立模拟观测。
- 物候、冠层、生物量和增量采收默认等组倍率，提供增量采收 `1.1` 的显式对照示例；pwtadj1 保持停用，未来只按总组 Phi 且经数量/相关性审核后考虑。
- 创建升级前快照 `fdfb5b1`，并在 `codex/p0-research-credibility` 实施 P0 科研可信性修复。
- 统一项目路径与兼容入口，改为每个 worker 独立 DSSAT 运行目录，并拒绝陈旧/空输出。
- 新增冻结边界、候选参数、Morris/Sobol 与 IES 科学质量门；历史退化运行现会明确失败。
- 修复 CUL/ECO/SPE/SOIL/IC 注入链、IC 表状态解析和 frozen `init/status` 应用。
- 完成真实 DSSAT 参数响应、非退化 Morris 和非退化 IES 微型验证，证据见 `archive/development_records/P0_verification_report.md`。
- 重写产品定义与系统设计，将项目目标收敛为可信、有效、易用的 DSSAT SA/率定科研工具。
- 建立 `process_completed` 与 `science_validated` 两级状态及阶段质量门。
- 明确 SA 提案、人工审核、冻结边界和率定之间的受控衔接。
- 修订观测误差与权重规范：PEST 基础权重使用 `1/sigma`，停用动态 Min–Max 和静默组权重回退设计。
- 将历史 SA/率定结论降级为归档背景，等待 P0/P1 后用有效运行重建。
- 新增文档索引，并同步 SA 输出和测试质量规范。

## 2026-01-15
- 在 `Workspace/run_dssat.py` 中将 `L#SD` 纳入从 `.TMT` 读取的过程观测点，并在 `PestTmtGrow.OUT` 写出 `@L#SDS@`。
- 在 `Workspace/run_dssat.py` 中将 `.TMT` 过程观测与 `PlantGro.OUT` 变量对齐，用“当日或之前最近一天”规则取模拟值。
- 在 `Workspace/analyze_results.py` 中新增过程变量对比表导出（`*_deterministic_process_compare.csv`）与过程指标汇总（RMSE/MAPE）。
- 在 `Workspace/build_pest.py` 中补充参数分组到文件位置的映射，并支持用“参数复核表”批量回写边界/初值/固定状态。
- 在 `Workspace/clean_workspace.py` 中按 prefix 归集并迁移运行产物到结果目录，避免污染工作区。
- 更新 `.gitignore`，忽略 `eggplant_stage2_v*` 与 `eggplant_v13` 运行产物，仅保留 v13 关键配置文件可提交。
