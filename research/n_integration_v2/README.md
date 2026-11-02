# 4.8.6.4 氮机制 v2 分阶段开发准备

本目录只包含执行准备、接口约定和基线回放工具；**尚未实现新根吸收、无机氮库或同化模块**。

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
