# Changelog

## 2026-07-18

- T2.2 最小集成修复（staged calibration 工具链），对应 T2.1 审查的 5 项发现：
  - [P0] 修复 `_fixed_from_provenance` 把代表 CSV 父目录当 run_dir 的 bug：新增 `_resolve_upstream_run_dir`，识别 finalize 子目录布局（`<run_dir>/calibration_finalize/stage_representative_params.csv`）与遗留 run 根目录布局两种合法位置。S1→S2 自动代表解继承入口现在可用。
  - [P1] 统一 manifest 标量序列化：新增 `serialize_manifest_scalar`（YAML 单引号标量，Windows 路径反斜杠保持字面），`_upsert_manifest_fields` 与 `_write_run_manifest` 都改用它，修掉 finalize 追加字段写出非法 YAML（双引号内 `\T` 被当转义）的同源 bug；`_strip_manifest_scalar` 同步升级，单/双引号 manifest 都能无损往返。
  - [P1] 新增 S1→S2 纯构建集成 smoke（`tests/test_staged_inheritance_smoke.py`）：mock prior-only S1 → finalize 生成中位数代表 → subprocess 调真实 build_pest S2 build，验证 S2 PST 含 6 参数（S1 fixed 钉死在中位数 + S2 active），不启动 DSSAT。
  - [P2] DesignSpec 暴露 `bounds_id`/`input_bundle`/`observation_policy_id`，staged 入口分两段交叉校验 CLI 实际值与 design 声明一致（bounds id 字符串、bundle id 来自 input_manifest、policy id 来自 CSV 文件名 stem），不一致即 `parser.error`。
  - 新增 manifest↔finalize↔代表参数三方哈希一致校验，任一不一致即失败并指明三方各自哈希。
  - [P2] Finding 5（`model_failed` 暂无证据生产者）按审查意见不在本轮扩展，保守归类为 `other_dropped` 已安全。
- 全测试：187 passed, 2 skipped（基线 179 → +8：7 单元 + 1 集成）。全程 `approval_scope=tooling_development`、`science_pending`，未启动 DSSAT/IES，未触达 validation。证据见 `docs/reports/P2_MVP_T2_2_修复记录_20260718.md`。

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
- 完成真实 DSSAT 参数响应、非退化 Morris 和非退化 IES 微型验证，证据见 `reports/P0_verification_report.md`。
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
