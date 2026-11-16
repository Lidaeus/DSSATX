# 可重复使用的自定义DSSAT氮梯度诊断图册

这是一套**运行机制诊断**工具，全部图名为`diagnostic_*`，不生成Fig/FigS，
不修改论文图表实现、正式图号、模型代码、率定参数或观测目标。
Python按项目规定负责调试图；如果将来进入论文，另从冻结CSV走既有R论文流程。

## 一次生成

在 DSSATX 内运行。使用已经生成的原生输出，显式指定处理映射。无实测配对表时使用 `--simulation-only`。

```sh
python research/n_diagnostics/make_atlas.py --case-dir build/smoke-4864 \
  --metadata research/fixtures/v7-26sp/treatment_metadata.csv \
  --simulation-only --label "DSSATX 4.8.6.4" --out-dir build/atlas-4864
```

`--reference-case-dir` 比较另一项运行。`--extra-n-source` 和 `--extra-n-unit` 指定额外诊断观测，保留日期和单位。图册先冻结输入数据及 SHA-256，再读取冻结数据绘图。

`diagnostics.py yield` 支持累计鲜产，`diagnostics.py daily` 支持原生逐日输出和逐层 CSV。V15 S3/S4 可直接绘制 `NStatePsi.csv` 等原生列。旧版 `RootKernelLedger.csv` 缺少 run 标识，执行体可能只保留最后一次运行的账本。转换时用 `kernel_ledger_daily.py --run` 指定经核实的 run。样例终点鲜产表位于 `terminal/`。

## 图册内容

| 页组 | 诊断问题 |
|---|---|
| 00／00b | 差异在Q、同化、N状态、LAI、光合、产量的哪一环节变小；可选版本对照 |
| 01 | 等效硝态Q、铵态Q与总Q库存；不是实测液泡 |
| 02 | 日NO3/NH4同化、累计同化与站存有机N，通量和库存分开 |
| 03／03b | 茎叶有机浓度、茎叶加权总N、三条软参照曲线与实际轨迹 |
| 04／04b | LAI、新生／损失面积、叶DM、SLA及实际接受比例 |
| 05 | 实际冠层PG、累计PG、PG/LAI和真实叶级光合氮能力 |
| 06／06b | 原始采收事件与阶梯累计、最终实测对照；另留单调Hermite视觉备选 |
| 07a—d | 叶、茎、根、果实分库以及全株互不重叠库存组成 |
| 08a—c | 经典NNI、带宽z、共享G、实际NSTRES、h、坐果反馈与功能缺口／保护 |
| 09 | 原始曲线重合时，直接看N2−N1及N3−N1的同日差 |
| 10 | 质流、扩散、根膜候选与实际吸氮分开，禁止“质流＋实际吸收”重复加总 |

主图按W1/W2/W3分面；N0灰、N1蓝、N2橙、N3红；水处理沿用三角／方／圆。
同一指标的三个水处理共用纵轴，观测与日模拟分别点／线。没有审计SE就不画误差棒。
库存堆叠页的颜色表示库类型，施氮水平用面板标题表示，不把R与其父Norg重复相加。

## 最小数据与可选能力

必需：`PlantGro.OUT`、`FreshWt.OUT`、`PlantNIntegration.csv`、`PlantCCash.csv`、
`comparison.csv`，以及明确处理映射。支持当前4.8.6.4 NI阶段5的字段契约，
不把旧4.8.2 V15文件强行当作相同模型。每日输出必须覆盖所审查的生长期。

可选：`PlantNP2.csv`的真实R、`PlantNLAI.csv`的新叶接受、`PlantNV3.csv`的状态、
`PlantNRemob.csv`、`PlantNLuxury.csv`、`LayerNIntegration.csv`、`P0Trace.csv`。
缺失项显示未提供；若配置明确禁用R，则零只是该模型不设R，不是测得无储备。
关闭新扩叶模式时，不把日账中的旁路值1冒充实际启用的h(G)。

`P0Trace`可提供精确站存果／根瘤／苗源N、真实NSTRES和实际叶级能力；
没有trace时果实N可用原生FRNAD（保留其打印精度），NSTRES只在逐日输出下
用1−NSTD还原并注明，能力因子不凭PG或NNI猜造。
FreshWt在开花前不输出：只有首次输出CHFPW=CHNUM=0才可据累计计数确证此前无采收；
其他缺失保持缺失，开始输出后的断日直接拒绝。观测日期不移动。

## 差异指标

每一水水平和同一天先计算N1/N2/N3最大值减最小值，再取全季最大范围。
不将不同日期的峰值相减。N3−N0保留符号，并同时输出全部相邻差和完整日序列。
总览只以同水水平该变量全季绝对峰值归一化，提供跨环节的描述性尺度；
全零分母为NA，绝对单位始终另存。不设“有差异即正确”门槛，不强制氮排序。

## 验证与复核

```powershell
python -X utf8 research/n_diagnostics/test_contract.py
```

另在真实数据中独立核验：器官Q之和、R亲本关系、茎叶质量加权、
根层结算对整株U、全器官有机N对原生A账、真实NSTRES对1−NSTD、
单次／累计鲜产及冻结目标观测日期与来源单位。图册保存每页源CSV、观测CSV、
PNG/PDF/SVG和manifest，另合并为`diagnostic_atlas.pdf`及Markdown目录。
这些是运行诊断证据，不自动将数据提升为science_validated或论文图。

## 只调整版式

`--render-only --out-dir <现有图册目录>`复用冻结CSV；输出figures目录必须不存在。
先把确有缺陷的旧版图单独归档，不覆盖已确认工作的图表。重绘仍校验冻结数据哈希，
不重新读取模型结果或改写已冻结数据。
