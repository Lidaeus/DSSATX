# E01 正式 IES 前置 Code Review（2026-07-26）

## 1. 审查结论

**当前结论：E01 暂缓（HOLD），不应启动正式 200 members × 4 iterations 率定。**

协作者已经完成三季 v2 FileA/FileT、土壤含水率观测表、层映射表和确定性 smoke 的主体工作；用户更新后的三季 FileX 也均能驱动 DSSAT 正常运行。但是，现有“E00 PASS”和两个 v2 smoke 尚未覆盖正式 IES 的完整数据链。审查发现 6 项会改变观测日期、标准差、Phi 或正式运行可追溯性的 P0 问题。

本轮仅进行审查、证据核验和工作安排，未启动正式 IES。

## 2. 已核验通过的内容

1. 三季权威 FileX 已更新：
   - 25SP：TN2、3、4、5、9、10、11、12、13、14，共 10 个处理；
   - 25FA：TN1–TN12；
   - 26SP：TN1–TN12。
2. 25SP 的 TN1、6、7、8 已从 v2 FileA、FileT 和土壤观测表中排除，并有审计记录。
3. 三季 FileX 的无机肥管理行未再触发 `management_event_order_findings`。
4. 26SP 新产量表已被读取，包含 5 次观测日期和 12 个正式处理，当前产物包含 60 个处理—日期产量组合；Z1–Z3 非正式处理未进入率定产物。
5. 三季确定性 DSSAT smoke 均能生成 `PlantGro.OUT` 和 `FreshWt.OUT`。
6. `SoilWat.OUT` 实际包含 14 个输出子层；现有映射已按 14 个输出子层重新生成，而不是错误地直接按 `SOIL.SOL` 的 8 个 SLB 层读取。
7. 首次土壤含水率观测排除规则已写入数据产物：
   - 25SP：150 条，其中 50 条为初始条件、100 条拟进入 Phi；
   - 25FA：48 条均为首次观测，因此本季没有可进入 Phi 的土壤水分过程观测；
   - 26SP：240 条，其中 60 条为初始条件、180 条拟进入 Phi。

## 3. P0 阻塞问题

### P0-1：E01 规格与 v2 manifest 尚未形成可运行契约

证据：

- 7 个 E01 spec 均仍引用已经删除的 v1 manifest，调用 `ExperimentSpec.load()` 全部失败。
- E00–E06 共发现 22 处 `season_inputs[].input_manifest` 指向不存在的 v1 文件。
- 三个 v2 `input_manifest.json` 将 `files` 写成分组对象，同时另设 `files_flat`；项目正式校验器要求 `files` 为文件记录列表，因此 `verify_manifest_integrity()` 对三个 v2 bundle 全部报错：`must list at least one file`。
- 当前工作树有约 294 个变更条目，包含大量旧 bundle 删除和新产物未跟踪；最近一次提交仍为 `24ec71c`，尚不存在可冻结的 E01 输入版本。

影响：

- 当前正式启动脚本不能加载 E01 spec。
- 即使绕过 spec，运行 receipt 也不能由正式 manifest 校验器验证。
- 大量删除若未区分“历史冻结输入”和“可再生产物”，会破坏旧试验复现。

处理要求：

1. v2 manifest 必须复用 `src/common/input_manifest.py` 的正式 schema，`files` 写成平铺列表；分组信息可作为额外字段，但不能替代正式字段。
2. 更新 E00–E06 spec 和对应 multiseason design 中的 bundle 路径与 SHA-256。
3. 历史冻结输入不得直接删除；可再生产物如需清理，必须保留生成器、源 SHA、产物 manifest 和迁移说明。
4. 修复后提交代码与冻结输入；正式 E01 必须从 clean commit 启动并把 commit、spec SHA、manifest SHA 写入 receipt。

### P0-2：采收日期存在混合规则和二次移位风险

证据：

- `build_trial_observations_v2_20260726.py` 对 25SP 和 26SP 产量工作表日期主动减 1 天，但 25FA 未采用相同规则。
- 当前 v2 FileT 的直接采收日期为：
  - 25SP：25139…25202；
  - 25FA：25325、25345、26005；
  - 26SP：26145、26157、26166、26181、26197。
- 26SP 新工作表日期实际为 26146、26158、26167、26182、26198；当前 FileT 已被减 1 天。
- `src/calibration/run_multiseason.py::_prepare_t10_input_bundle()` 会删除目标处理已有的 FileX 采收行，再依据 FileT 日期再次减 1 天并重建采收事件。它会覆盖用户刚刚修正并确认的权威 FileX 采收表。
- 现有 v2 smoke 将日期一致性设为“仅报告、不作为失败条件”。25FA 和 26SP 的 FileT 日期与 `FreshWt.OUT` 累积量变化日期精确匹配数均为 0，但 smoke 仍返回 PASS。

影响：

- 25SP/26SP 可能发生两次减 1 天；
- 三季采用不同日期语义；
- 最后一次真实采收可能匹配到错误的累积值；
- 率定残差和 Phi 会被系统性改变。

处理要求：

1. **用户维护的三季 FileX 为采收管理的唯一权威来源，正式运行器不得再重写采收表。**
2. FileT 保存工作表的观测日期/观测语义，不在生成器中为适配模型而偷偷改日期。
3. 输出读取器在同一处理内按“观测日期附近”匹配 `FreshWt.OUT`，优先精确日期，其次采用预先声明的最近日期；每条观测必须记录 `observed_date`、`selected_output_date`、`date_delta_days` 和匹配方向。
4. terminal virtual event 只由 FileX 表达，读取器不得把它当作新增观测。
5. smoke 必须验证最后一次真实采收能够唯一匹配，且所有采收观测的匹配审计完整；不能只验证“至少存在一个事件”。

### P0-3：土壤含水率尚未真正进入 PEST++ Phi

证据：

- `src/dssat/run_dssat.py` 已支持 `--keep-soil-water`。
- `tools/calibration/run_e01_v2_soil_smoke.py` 为保留 `SoilWat.OUT`，明确绕过正式 PEST wrapper 并直接运行 DSSAT。
- `src/calibration/run_dssat.py` 的正式输出复制集合不包含 `SoilWat.OUT`。
- `build_pest.py` 尚无土壤水分观测构建、`PestSoilWat.OUT`、`.ins` 或 `SOIL_WATER` observation group。
- 项目配置中没有把 `SOIL_WATER` 组权重设置为 0.8。

影响：

当前 soil smoke 只证明“DSSAT 能输出土壤水分且离线脚本能匹配”，不能证明土壤水分参与遗传参数或土壤参数率定。若现在启动 E01，土壤水分对 Phi 的贡献为零。

处理要求：

1. 在正式 wrapper 中显式传递土壤水分保留模式，并把 `SoilWat.OUT` 转换为稳定、逐观测 token 化的 `PestSoilWat.OUT`。
2. builder 读取 `soil_water_observations.csv` 中 `phi_role=soil_water_phi` 的记录，生成 `.ins` 和 observation rows。
3. 使用已经审计的标准差，基础 PEST 权重仍为 `1/sigma`；组级倍率设置为 **0.8**，不得把 0.8 错当成标准差或再次平方。
4. 25FA 因只有首次测量，应明确记录 `SOIL_WATER n=0`，不能伪造过程约束。
5. 增加手算 Phi 回归：至少用 2 条土壤水分观测验证 `Phi = Σ(0.8 × residual / sigma)^2`。
6. formal smoke 必须检查 PST 中存在土壤组、非零观测数与 registry 一致、模拟值有限且无 `-99/NaN`。

### P0-4：CHTD 尚未贯通 FileT → DSSAT 输出 → PST

证据：

- 三季生长工作表均有株高字段，但 26SP 不同工作表使用了多种列名，如“株高”“株高 (cm)”和“株高 (Plant Height / cm)”。
- v2 生成器的 `TMT_FILL` 不含 CHTD，当前三个 v2 FileT 的 CHTD 非缺失数均为 0。
- `observation_uncertainty.csv` 不含 CHTD。
- `src/dssat/run_dssat.py` 的 `PestTmtGrow.OUT` 只输出 `L#SD/LAID/LWAD/SWAD`。
- `build_pest.py` 的 process observation 集合只支持 `LAID/LWAD/SWAD`，没有 CHTD。

影响：

株高既未写入 FileT，也不能被 PEST++ 读取；用户要求尚未实现。

处理要求：

1. 为三季生长表建立显式 CHTD 别名字典，统一单位为 cm，按处理—日期计算均值、样本 SD 和重复数。
2. 标准 DSSAT 兼容策略：
   - 时序株高写入 FileT 的 `CHTD`；
   - FileA 不新增非标准 `CHTD` 列。若后续确需季末株高，只在确认 DSSAT 标准 FileA 变量为 `CHTA` 且输出口径一致后加入。
3. 扩展 `PestTmtGrow.OUT`、`.ins`、builder observation registry、sigma/weight policy 和指标报告。
4. 加入端到端测试：FileT 的 CHTD 非缺失计数 = uncertainty registry 计数 = PST CHTD 观测计数。

### P0-5：25FA 和 26SP 产量标准差使用了重复的派生小区值

证据：

- 25SP 工作表中 `小区产量` 和 `加权小区产量` 在同一处理—日期内重复，154/154 组的 SD 均为 0；生成器已改用行级“产量”计算 SD，这一做法正确。
- 25FA 的 36 个处理—日期组中，“小区产量”组内 SD 全为 0；工作表另有行级“行产量”。
- 26SP 的 60 个处理—日期组中，“小区产量”组内 SD 全为 0；工作表另有逐重复“产量”，其组内 SD 均非零。
- 当前 25FA/26SP 生成器仍用重复的“小区产量”计算 SD，最终大量退化为 5% CV 下限，不代表实际重复变异。

影响：

观测标准差被人为压小或被固定下限替代，会改变相对权重、Phi 大小和参数后验收缩程度。

处理要求：

1. 25FA：观测均值采用审计后的“小区产量”口径，SD 从对应“行产量”的独立重复计算。
2. 26SP：观测均值采用“小区产量”，SD 从逐重复“产量”计算。
3. 对每季输出 `mean_source_column`、`sd_source_column`、`n_rep` 和 floor 是否触发。
4. 增加回归测试，禁止在存在有效独立重复时从组内恒定的派生总量计算 SD。

### P0-6：现有 E00/smoke 存在假阳性

证据：

- `run_e00_v2_audit.py` 返回 17 pass / 0 fail，但正式 manifest 校验器对三个 bundle 全部失败。
- E00 的 strict-fill 规则仍把 CHTD 排除在允许填充值之外。
- E00 只比较 TMA `HDAT` 与 FileT 最后采收日期，没有核验 FileX 权威采收事件、虚拟事件、`FreshWt.OUT` 选中日期及其一一映射。
- soil smoke 通过直跑 DSSAT，未经过正式 PEST wrapper/builder。
- 30 个定向回归测试结果为 20 passed / 10 failed；失败主要源于旧 bundle 被删除而测试与规格未迁移。

处理要求：

把 E00 和 smoke 改成正式启动门，而不是展示性报告。任何一项失败都应返回非零退出码：

1. 正式 manifest schema、文件 SHA 和 spec SHA；
2. 观测字段白名单/黑名单；
3. FileX—FileT—DSSAT 输出的采收匹配；
4. CHTD 和 SOIL_WATER 端到端 observation count；
5. PST 权重与手算 Phi；
6. 所有 E01 spec 可加载；
7. 定向回归测试全通过。

## 4. P1 问题

### P1-1：观测契约仍含已废弃指标

`configs/experiments/observation_profiles/direct_chpdt_log_v1.json` 仍把 CNAM 列为 diagnostic target。应从所有观测 profile、指标清单和报告变量注册表中移除：

- 主茎出叶数/L#SD；
- M#AD；
- CWID；
- L#PA；
- RWAD；
- CNAM；
- PDMCD。

这些列可以为了 DSSAT 标准 FileT 固定宽度格式保留为 `-99`，但不得生成观测、标准差、PEST observation 或科研指标。

CHTD 应加入允许的过程观测集合。是否在某个 E01 子试验中进入 Phi，应由 observation profile 显式声明，不能仅因 FileT 有值便自动纳入。

### P1-2：土壤参数与遗传参数应分两步，避免不可辨识混合

当前 `highdim55_dryonly_v1` 仅含遗传参数；现有 `--include-soil` 主要构建 SBDM，并未实现所需的窄范围水力参数集合。

建议采用最小可实施方案：

1. **E01-G（遗传预率定）**：SOIL_WATER 以组倍率 0.8 进入 Phi，土壤参数固定为实测/当前审定值，用于约束水分响应相关遗传参数。
2. **E01-S（土壤小范围预率定）**：遗传参数固定为 E01-G 代表值，只开放少量、有实测依据的 SLLL/SDUL/SSAT（必要时 SBDM），边界围绕实测值且强制 `SLLL < SDUL < SSAT`。
3. **联合敏感性复核**：只有 E01-S 显示土壤参数可辨识且能稳定改善独立过程残差后，才在后续联合率定中同时开放。
4. **SLPF/土壤综合肥力指数不要由土壤含水率单独率定**。它需要植株氮、生物量/干果产量和施氮梯度证据；若加入，应作为单独、窄范围、带先验约束的候选参数，不与水力参数一次性全部开放。

### P1-3：层映射不应只靠硬编码

当前 14 层映射与本次 `SoilWat.OUT` 一致，但生成器和 smoke 各自硬编码一份。正式实现应从实际 `SoilWat.OUT` header 解析层边界，并与冻结的 `soil_water_layer_mapping.csv` 比较；不一致时失败。避免更换土壤剖面或 DSSAT 输出设置后静默错层。

### P1-4：v2 manifest 的来源说明过时

当前 manifest 仍出现“copied from v1”“26SP fertilizer order pending”等文字，但实际来源已改为 `data/user/experiments/XXQL*`，26SP 当前也已通过管理次序检查。应更新来源字段和修复状态，避免论文追溯时自相矛盾。

## 5. 协作者执行顺序

### 阶段 A：冻结输入语义

1. 明确并编码单一采收日期契约：FileX 管理日不重写；FileT 保留观测日；输出就近匹配并审计。
2. 修正 25SP/25FA/26SP 产量日期生成和标准差来源。
3. 加入 CHTD，并删除禁用指标的所有观测契约引用。
4. 重新生成三季 FileA/FileT、uncertainty registry、质量匹配审计和 soil mapping。

### 阶段 B：接通正式 PEST 数据链

1. 实现 CHTD 的 runner/builder/INS/PST 链。
2. 实现 SOIL_WATER 的 keep、解析、层加权、token、INS、PST 和 0.8 组倍率。
3. 增加窄范围土壤参数 profile；与 genetic-only profile 分开。

### 阶段 C：修复正式契约和门禁

1. 修正 v2 manifest schema。
2. 更新 E00–E06 spec、multiseason design、SHA 和测试 fixture。
3. 将 E00 和 smoke 升级为端到端门禁。
4. 运行定向测试、全量测试和 20 members × 1 iteration IES smoke。
5. 提交并冻结 clean commit，生成正式 E01 启动 receipt。

## 6. E01 放行标准

同时满足以下条件才可启动正式率定：

- [ ] 三个 v2 bundle 通过 `verify_manifest_integrity()`；
- [ ] 7 个 E01 spec 均可由 `ExperimentSpec.load()` 加载；
- [ ] FileX 在 staging 前后字节一致，运行器不再重写采收事件；
- [ ] 所有真实采收观测都有唯一的 `FreshWt.OUT` 匹配记录，末次采收匹配通过；
- [ ] CHTD 三季计数在工作表、FileT、uncertainty、PST 中一致；
- [ ] 禁用指标的 PST observation count 全为 0；
- [ ] SOIL_WATER 在 25SP 为 100 条、25FA 为 0 条、26SP 为 180 条（若数据重生成后计数改变，必须有审计解释）；
- [ ] SOIL_WATER 组倍率为 0.8，手算 Phi 回归通过；
- [ ] 25FA/26SP 产量 SD 来自独立重复，不来自恒定派生小区总量；
- [ ] E00 端到端审核通过；
- [ ] 20 × 1 IES smoke 通过，模拟观测无 `-99/NaN/Inf`，realization 对齐；
- [ ] 定向测试和全量测试通过；
- [ ] 工作树 clean，正式运行 receipt 固定 git commit、spec SHA、manifest SHA 和 parameter profile SHA。

## 7. 当前测试记录

- `python tools/calibration/run_e00_v2_audit.py`：表面结果 PASS（17/17），但因门禁覆盖不足，不能作为正式放行依据。
- 三季 deterministic v2 smoke：3/3 DSSAT 可运行。
- 三季 soil smoke：3/3 可离线读取 `SoilWat.OUT`，但未接入 PEST。
- 定向 pytest：20 passed，10 failed。
- `ExperimentSpec.load(E01*)`：7/7 失败，原因是仍引用已删除的 v1 manifest。
- `verify_manifest_integrity(v2 bundle)`：3/3 失败，原因是 v2 manifest 的 `files` schema 不兼容正式校验器。

