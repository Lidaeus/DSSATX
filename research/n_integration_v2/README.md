# 4.8.6.4 氮机制 v2 分阶段开发准备

本目录包含准备、P0b追踪及五阶段氮机制的实现/工程验证。**新机制已接通；小型联合率定入口见下，原生bug按用户要求延期统一处理。工程smoke不代表正式参数率定或机制有效性验证。**

## 当前入口：五阶段实现

- 机制代码提交：`240ed59d`，依次接通库存、有限同化、独立根吸收、茎叶软曲线及L路线替换反馈。
- 规格：`integrated_mechanism_spec.zh.md`；原生bug台账：`deferred_bug_ledger.md`。
- 最终证据：`D:/Tomato_Cal/subprojects/critical_n/reports/n_integration_stages_20261102/accepted_all`、`accepted_r1`、`accepted_feedback_r0`、`accepted_unit`、`final_audit`。
- 29项原生检查、8配置×12处理工程运行；原版43类输出数值一致，新Q日/季账独立闭合。原生有机N/C差额另外保留。
- 果实氮没有新增稀释；V15借鉴登记仍为零。

**没有配置时新执行体仍走原版模式。启用新机制必须将NIntegration.nml放入实际运行目录，或显式设置DSSAT_N_CONFIG。单独切换DSSAT_CUSTOM_EXE不能保证启用了新机制。** 主项目的PEST注册/模板保持不变；新入口通过隔离适配器接通并冻结氮配置、局部边界、目标、原生输入和运行代码。

## 阶段5的小型PEST-IES联合率定

`calibration_smoke.py`真实调用PEST++ IES，24成员×2次更新、6个并行；26SP 12处理，沿用既有612个直接观测目标。联合调整8个新氮参数和6个原生生长／物候参数，不采用V15机制或其最佳参数。新参数只用窄幅工程先验，其余机制参数固定；这不是正式的全参数率定。每个原生调用显式指定独立的NIntegration.nml，核查新库收支、名义库容、根层交接和完整日覆盖，保留原生有机N/C残差。

```powershell
python research/n_integration_v2/calibration_smoke.py --out D:/new_unique_smoke_directory
python research/n_integration_v2/test_smoke_adapter.py
python research/n_integration_v2/audit_smoke_receipts.py --run D:/completed_smoke_directory
```

工具拒绝覆盖已有批次。运行前逐一扰动14个活动字段以证明接线；运行后确认实际完成2次更新、24个最终成员、独立重跑最低Phi实际评估向量。每轮PEST会测试3种默认步长，实际原生调用数大于成员数×更新次数，不把线搜索隐藏为额外更新。输出包括Markdown报告、逐目标比较、最佳参数、逐类指标、评估和冻结文件收据。`--resume`仅用于已准备好但尚未创建manager的批次，不能作为失败批次自动重启机制。

当前运行证据目录：`D:/Tomato_Cal/subprojects/critical_n/runs/n4864_p5_smoke14_24x2_r1_20261102`；状态以其中`execution_status.json`、`final_audit.json`和`smoke测试结果报告.md`为准。旧的无机氮尚未进入原生LN%D/SN%D，暂时沿用既有观测算子；在消解法对硝态氮回收口径核定前，不宣称总氮拟合已获验证。

```powershell
python research/n_integration_v2/run_stages.py --out D:/new_isolated_run --exe build/bin/dscsm048.exe --stages 0 1 2 3 4 5
python research/n_integration_v2/run_native_tests.py --out D:/new_isolated_unit
```

`stage*_engineering.nml`仅作工程测试，不是推荐生理参数。`integrate_nitrogen.py`是初始P1/P2历史接线工具，`instrument_p0b.py`是历史P0一次性插入工具；完整当前实现以Git提交为准，不要在已接入源码上重复运行这些工具。下文P0与准备记录保留为历史。

## P0b状态（2026-11-02）

已实现可关闭的 `DSSAT_P0_TRACE=0/1` 诊断，默认关闭；仅输出 `P0Trace.csv`，所有生理赋值保持官方原样。最终运行证据：`D:/Tomato_Cal/subprojects/critical_n/reports/p0b_trace_4864_20261102/final_run`，最终分析在 `analysis/`。诊断实现提交为 `16caa847`。

26SP 12处理的追踪关闭/开启回放通过：8类选定输出均与冻结官方参照数值一致，43类有数值行的原生OUT在开关之间完全一致。跨日吸氮、RWU缓存、初始化、RPROAV与L光合路线已追踪。原生预算存在已定位问题，不将其标记为物理预算全部通过；详见本次执行报告。

```powershell
python research/n_integration_v2/run_p0b.py --out D:/Tomato_Cal/subprojects/critical_n/reports/p0b_trace_4864_20261102/new_run --exe build/bin/dscsm048.exe
python research/n_integration_v2/analyze_p0b.py --run D:/Tomato_Cal/subprojects/critical_n/reports/p0b_trace_4864_20261102/new_run
```

输出路径须全新。诊断CSV若已存在会报错，避免把不同执行混在同一账本。分析只验证本次26SP单季批处理，未将其扩称轮作或跨季节验证。下文准备阶段P0清单作为历史任务定义保留，T01—T07状态见更新后的测试矩阵。

用户要求：V15 S1经验或机制的借鉴必须先汇报并经其审批。本阶段没有采用V15机制；使用的是前阶段已经冻结的历史base输入作官方回归，不是V15最优组，也没有读取/迁移V15源码。

- 官方起点：`25c93b9a2f73f8ec45bf441b198dac5fb7b22849` / `v4.8.6.4`。
- 独立分支：`codex/n-integration-v2-20261102`。
- 独立工作树：`D:/Tomato_Cal_worktrees/dssat4864-n-integration-v2-20261102`。
- 评估报告：`D:/Tomato_Cal/subprojects/critical_n/reports/n_integration_v2_readiness_20261102/可行性评估与分阶段执行准备.md`。
- 准备收据：上述报告目录的 `baseline_verified/readiness_receipt.json`。
- `execution_contract.json` 中的 null 是待核定项，**不能转换为默认生理参数**；新模式尚不可用。

## 已完成的准备验证

重新编译未修改机制的官方源码，独立回放官方原构建与新分支构建各一次，均为26SP的12个处理。8类原生输出数值记录与冻结参照完全一致。使用的是历史 preflight **base** 参数输入，不是 V15 s1 最佳参数；本检查不评价拟合能力。

新分支二进制与原构建哈希不同是允许的：分支名写入官方版本横幅，不能把二进制哈希相同作为跨分支构建要求。以来源、编译信息、源码哈希及行为回归共同识别。

## 接下来第一个实施单元：P0 trace

1. 只加可关闭的诊断，保留 `(root_mode,assim_mode)=(0,0)` 的数值流程。
2. 在 `SPAM(RATE)` 完成后记录实际RWU、EP及其运行/日期标记；在CROPGRO的RATE保存对应SW、土壤可用N快照。不得将INTEGR更新后的SW悄悄配给RATE的RWU。
3. 跟踪 `CROPGRO(INTEGR)` 最终UNO3/UNH4与下一次 `SoilNi(RATE)` 扣除的逐层数组。不得在土壤已经扣除后回滚植株通量，或同时另扣一次土壤。
4. 输出独立pending账本，联合系统库存使用 `soil_book + plant - pending_debit`。季末、最后一个生长日和处理切换都要检查；保留原土壤输出定义。
5. 核对 `TNLEAK` 是SEASINIT清零、日内累加的累计量。日外流用差分，不能每日把累计量重新累加。
6. 完成 `RPROAV`、再转运重合成成本、实际有机氮接受量与 `MEPHO=L` 的调用图。

P0通过之后，先原根系+新氮库的隔离实验，再有限同化，再R1/R2根模块，最后三曲线与替换式反馈。根核函数可提前独立验证，但整株新根模式必须有接收与预算端点。

## 运行工具

在本工作树运行（输出路径必须全新，工具拒绝覆盖）：

```powershell
python research/n_integration_v2/prepare_readiness.py `
  --output-root D:/Tomato_Cal/subprojects/critical_n/reports/n_integration_v2_readiness_20261102/new_replay `
  --candidate-exe D:/Tomato_Cal_worktrees/dssat4864-n-integration-v2-20261102/build/bin/dscsm048.exe
```

只用于**未修改**基线回放。工具确认关键模型源文件与官方树一致，冻结输入，隔离profile路径，复核受保护执行体哈希；不会启动PEST，不会替换任何现有执行体。今后机制改变后需另建机制试验驱动，不应移除此工具的源码一致性保护。

## 固定研究约束

沿用 `D:/Tomato_Cal/subprojects/critical_n/AGENTS.md`。当前研究对象为走TMGRO048的茄子，不另开番茄或甜椒前置项目；本轮26SP，不纳入25秋或跨季节适用性验收。禁止分季/日期生长护栏；禁止将SPAD、气体交换或荧光代理硬塞入率定目标；7月17日茎叶N仍仅诊断；果实N按当天独立采摘商品成熟果实定义。

参数、模式和测试规范的准备不等于机制已获验证。不能把本次官方回归通过写成“新模型守恒/机理/拟合通过”。
