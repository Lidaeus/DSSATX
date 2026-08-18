# E01 正式 IES 前置审查复核（2026-07-26）

## 结论

E01 的“正式输入、PST 构建、单成员 wrapper、PEST++ 控制值 smoke”链路已通过，可以进入用户审批后的正式率定。尚未运行 200 × 4 正式 IES；本记录中的 PEST++ smoke 仅为 1 个控制值 realization、`NOPTMAX=0`，不产生科研结论。

## 本轮修复与审查证据

### 1. v2 输入与引用

- 三季 v2 bundle 的 `input_manifest.json` 已恢复为正式扁平 `files` schema，且 `verify_manifest_integrity()` 三季均通过。
- E00、E01 以及 E02–E06 中仍可解析的 design/spec 已迁移到当前 v2 bundle；25SP 的处理集合统一受 `[2,3,4,5,9,10,11,12,13,14]` 约束。
- E02/E03/E05 仍明确处于“23 参数冻结边界尚未批准”的模板状态，加载时的参数数量错误是预期的科研门槛，不是 E01 输入错误。

### 2. FileT、CHTD 与采收日期

- FileX 由用户维护的权威版本决定，`run_multiseason.py` 不再重写 HARVEST DETAILS。
- FileT 保留观测原始日期；模型输出读取采用同一处就近日期选择，不再生成第二套隐含日期。
- CHTD 已完成三季别名解析、均值/样本 SD、FileT 写入、`PestTmtGrow.OUT` 模拟 token、builder observation/Phi 的端到端链路。
- 重新生成后 CHTD 非缺失计数为 25SP=40、25FA=36、26SP=48；E00 审计通过。

### 3. 土壤含水率进入 Phi

- wrapper 将 `soil_water_observations.csv` 与 `soil_water_layer_mapping.csv` 复制进隔离 run，并在存在土壤观测时显式传递 `--keep-soil-water`。
- DSSAT 的 `SoilWat.OUT` 按已审计的 14 个输出子层解析，按观测日期最近值匹配并按 `dssat_layer_weights` 汇总；首个测量日由 `phi_role=initial_condition_only` 排除。
- builder 为 `phi_role=soil_water_phi` 记录生成 `PestSoilWat.OUT` 的 tagged INS/PST 观测；25FA 没有有效过程观测时不伪造约束。
- `SOIL_WATER` 组权重明确为 `0.8 × (1/sigma)`，没有把 0.8 再平方或混入 SD。E01 25SP organ 构建审计显示 100 条土壤观测、`weight*sigma=0.8`，group audit 的 multiplier=0.8。

### 4. 标准差与指标口径

- 25FA/26SP 产量均值继续使用小区产量，SD 改用独立行/逐重复产量列；不再从同一小区汇总值计算重复 SD。
- 25SP 的 TN1、6、7、8 在 FileA、FileT、土壤观测和 E01 设计中均被排除，并有审计记录。
- HWAM、PWAD、PWAI、CNAM、RWAD、PDMCD 等禁用指标未重新进入正式观测目标。

## Smoke 结果

1. `tools/calibration/run_e00_v2_audit.py`：17/17 checks PASS。
2. `tools/calibration/run_e01_v2_smoke.py`：三季 3/3 PASS；三季 DSSAT 成功，FileT/FreshWt 采收事件可解析，CHTD 来源审计通过，PestSoilWat 文件有效。
3. E01 organ PST build：55 个可调参数，500 条观测记录，其中 260 条在该 organ 子试验中有效；包含 100 条 SOIL_WATER 观测和 40 条 CHTD 观测。
4. PEST++ control-value smoke：`NOPTMAX=0`、1 个 realization，DSSAT 10 个处理全部成功，PEST++ 报告 0 failed；`PestSoilWat.OUT` 生成 100 条 token 且无 `-99`。
5. 两季联合 soil smoke（25SP+25FA）：16 个处理全部成功；合并文件只包含 25SP 的 80 条有效土壤 token，25FA 保持空文件（n=0），没有伪造过程约束。
6. 相关回归测试集 31/31 通过（输入审计、E01 子试验策略、DSSAT failure artifact、T10 direct harvest、legacy mode）。

## 尚未宣称通过的事项

- 正式 200 members × 4 iterations 尚未启动；不得把 smoke Phi 或单次控制值当作率定结果。
- E02/E03/E05 的 23 参数冻结边界尚未批准，因此这些 spec 保持显式阻塞。
- SoilWat 的“土壤参数小范围率定”仍应作为单独子试验；本轮仅完成观测进入 Phi，未将所有土壤参数自动打开。
- 正式运行前仍应从 clean commit 生成 receipt，记录 bundle/spec SHA、PST SHA、git commit 和运行参数。

## 正式 E01 启动建议

先运行 `tools/calibration/run_e01_formal.py --build-only` 检查六个可识别子试验的 PST 观测计数、CHTD/SOIL_WATER 权重审计和输入 SHA；25SP 物候子试验因当前无有效 ADAP 已从正式启动清单中退休。审核无误后，再由用户执行正式 IES。正式结果只从 `run_status.json`、PEST++ `.rec/.phi.actual.csv` 和冻结的观测 registry 读取。
