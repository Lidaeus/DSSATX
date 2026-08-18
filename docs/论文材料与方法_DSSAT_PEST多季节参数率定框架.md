# 基于 DSSAT–PEST++-IES 的茄子多季节遗传参数率定框架

> 文档性质：论文“材料与方法”写作底稿。正文所述方法对应当前 T10 M1：共享参数加预登记秋季有效偏移。方括号内容应在投稿前替换；后验分布、共线性、异参同效和独立验证部分只有在正式率定完成后才能使用过去时描述。

## 方法概要

本研究以 DSSAT Cropping System Model（CSM）v4.8 为过程模型，采用 CROPGRO 框架下的番茄模型文件表示无限生长型茄子的生长、器官分配、水分响应和氮素响应。由于 DSSAT 尚无本研究所需的原生茄子模型，茄子品种参数写入 `TMGRO048.CUL`、`TMGRO048.ECO` 和 `TMGRO048.SPE`，而各季的天气、土壤、初始水氮状态及田间管理保持为相应试验的实测或实际记录。参数反演采用模型无关的 PEST++ iterative ensemble smoother（PESTPP-IES），以共享遗传与生理参数联合解释 2025 年春季和秋季试验；仅对预登记的过程参数在 2025 秋季施加零中心有效偏移。2026 年春季封存用于独立验证，并只使用共享参数。

当前正式配置包含 41 个活动共享参数、7 个活动秋季偏移和 23 个固定参数。率定目标包括冠层叶面积指数、叶和茎干物质、植株氮积累以及连续采收鲜重和干重；物候仅作为低权重辅助约束，最大叶面积指数、收获指数以及 DSSAT 默认的单次/累计产量汇总指标不参与参数更新。连续采收鲜重和干重采用同尺度自然对数残差，以缓解累计量随时间增加所造成的异方差。观测误差权重与科学目标族的 Phi 预算分开定义，使采收日期数量较多的时序数据不会仅因观测条数多而支配目标函数。

正式 M1 率定使用 200 个参数集合成员和 4 次 IES 更新。各集合成员在两个率定季节使用相同的共享参数和各季实际的环境、初始条件及管理输入；25 秋仅应用 `TB1/TB2/TB3`、`LFMAX`、`SLAVR`、`XFRT`、`SFDUR` 的预登记偏移。为避免高维非线性更新产生数值崩溃，IES 采用完整（非近似）更新、lambda 乘子 `0.5, 1, 10` 和线搜索因子 `0.9, 1.0`；该数值稳定设置不改变观测、权重、参数边界或偏移定义。高 Phi 成员不被自动视为模型失败；只有 DSSAT 非零退出、输出缺失、非有限值或提取失败才定义为工程失败。最终集合用于后验分布、参数相关性、可识别性和异参同效分析，独立验证数据不参与参数更新或率定方案选择。

## 1. 试验资料与数据分工

### 1.1 率定和验证资料

联合率定使用同一茄子品种的两个季节：

| 数据集 | 季节角色 | 试验代码 | 纳入处理 | 用途 |
|---|---|---|---|---|
| 2025 春 | calibration | XXQL2501 | TN2、3、4、5、10、11、12、13 | 参数更新 |
| 2025 秋 | calibration | XXQL2502 | TN3、4、7、9、1、6、10、12 | 参数更新 |
| 2026 春 | validation | XXQL2601 | TN1–TN12 | 独立验证；率定阶段封存 |

2025 春试验覆盖高水和低水条件下的高、中、低和零氮处理，可用于约束水分、氮素及其交互响应。2025 秋试验用于检验同一套参数跨季节解释生长与连续采收过程的能力。2026 春试验在率定方案、参数边界和分析规则冻结后才解封，以减少验证信息泄漏。

各季的 FileX、FileA、FileT、天气文件和土壤文件构成独立输入包。处理编号与 FileX 中的 treatment number 严格对应。率定包保留各季实测土壤水分、矿质氮和管理条件；敏感性分析阶段使用的受控反事实初始条件不用于正式率定。

> 投稿前补充：[试验地点、经纬度、温室类型、茄子品种、移栽日期、株行距、灌水和施氮梯度、重复数、取样方法、鲜重和干重测定方法]。

### 1.2 观测变量及其角色

当前 T10 构建共登记 464 条观测，其中 432 条进入目标函数，32 条仅用于诊断。下列数量来自 2026-07-22 通过 smoke 的冻结构建；若 FileA/FileT 经审计后更正，应由正式 PST 的 observation registry 重新生成论文中的样本数。活动观测的构成为：

| 变量 | 含义 | 单位 | 2025 春活动观测数 | 2025 秋活动观测数 | 率定角色 |
|---|---|---:|---:|---:|---|
| ADAP | 移栽后至开花的天数 | d | 8 | 0 | 低权重辅助约束 |
| LAID | 叶面积指数时间点 | m² m⁻² | 40 | 24 | 冠层过程 |
| LWAD | 叶干物质 | kg ha⁻¹ | 40 | 24 | 生物量过程 |
| SWAD | 茎干物质 | kg ha⁻¹ | 40 | 24 | 生物量过程 |
| CNAM | 植株氮积累量 | kg N ha⁻¹ | 8 | 0 | 植株氮过程 |
| CHFPW | 累计采收鲜重 | kg ha⁻¹ | 88 | 24 | 核心收获目标，log 残差 |
| CHPDT | 累计采收干重 | kg ha⁻¹ | 88 | 24 | 核心收获目标，log 残差 |

LAIX（最大 LAI）和 HIAM（收获指数）仅作为诊断量。HWAM 不进入当前 PST；PWAD 和 PWAI 也从正式率定观测链中移除。原因是 DSSAT 的季末收获量、地上部总量和默认产量汇总语义不能稳定对应无限生长型茄子的持续采收实测量。论文中的连续采收评价应使用 FileT 和 `FreshWt.OUT` 中定义一致的 CHFPW、CHPDT，不得以名称相似的 PWAD/PWAI 替代。

## 2. 作物模型与参数化

### 2.1 DSSAT 模型设置

模拟采用 DSSAT-CSM v4.8 的 `CRGRO048` 模型执行程序和番茄遗传参数文件。DSSAT-CSM 以模块化方式耦合作物生长、天气、土壤水分、土壤碳氮和田间管理过程（Jones et al., 2003；Hoogenboom et al., 2019）。茄子与番茄共享模型结构不意味着两种作物具有相同参数；本研究通过茄子试验数据率定品种、生态型和物种层参数，并将“使用番茄模型结构表示茄子”作为结构不确定性来源保留在讨论中。

每次模型调用均在独立工作目录中执行。PEST++ 写出候选参数后，运行器将其注入固定宽度的 `.CUL/.ECO/.SPE` 本地副本，再调用 DSSAT。天气、土壤、初始条件和管理文件按季复制到运行目录，源输入包保持只读。DSSAT 输出经预定义 instruction 文件映射为 PEST++ 观测 token，从而构成非侵入式模型接口。

### 2.2 参数域

T10 M0 同时率定 41 个遗传或生理参数，涵盖叶面积与冠层结构、果实分配和采收发育、冠层光合、根系水分响应、根系氮吸收、源库关系、温度基点及氮素再转运。参数边界在率定前冻结，运行时不得根据拟合结果自动扩展。运行器可参照参数注册表记录超出历史安全范围的风险，但不以该类启发式阈值替代 frozen bounds 或在 DSSAT 运行前冻结成员。

23 个参数在 M0 中固定，包括光周期参数、部分阶段持续时间、参考比叶面积和尚未充分识别的三基点温度组。特别地，`SLAREF=300`，`EM-V1=22`，`FL-VS=120`；M0 率定共享 `TB1–TB3`，而 `TM1–TM3`、`TO11–TO23` 保持固定，以避免在季节温度信息不足时同时反演多组高度相关的温度响应参数。

`XMAGE` 的范围为 8–30，`XFPHT` 的范围为 31–70，因此所有候选都满足严格约束 `XMAGE < XFPHT`。参数 `XFINT` 的冻结范围为 0.08–0.50；运行器对低于历史提示阈值 0.12 的候选写入审计警告，但不在 DSSAT 运行前删除成员。成员是否保留由 DSSAT 返回码、必需输出和提取完整性决定，而不由运行器的历史经验阈值替代。全部活动参数及边界见附录 A。

## 3. 多季节联合率定设计

本研究采用共享参数的多季节联合反演，而不是分别率定春、秋两套参数后再平均。设参数向量为 \(\boldsymbol{\theta}\)，两个率定季的模型响应分别为

\[
\mathbf{y}_{25SP}=M_{25SP}(\boldsymbol{\theta},\mathbf{x}_{25SP}),\qquad
\mathbf{y}_{25FA}=M_{25FA}(\boldsymbol{\theta},\mathbf{x}_{25FA}),
\]

其中 \(\mathbf{x}_s\) 包含季节 \(s\) 的天气、土壤、初始水氮状态和管理措施。两个季节共享同一个 \(\boldsymbol{\theta}\)，但不共享 \(\mathbf{x}_s\)。当前 M1 对 25SP 使用 \(\boldsymbol{\theta}\)，对 25FA 使用共享值加预先冻结的参数偏移：`TB1/TB2/TB3` 为加性偏移，`LFMAX/SLAVR/SFDUR` 为 log 乘性偏移，`XFRT` 为 logit 加性偏移。偏移的初值均为 0，且不向 26SP 验证季传播；它们被解释为 2025 秋条件下的有效过程修正，而不是第二套遗传参数。

PESTPP-IES 是基于 Levenberg–Marquardt 型迭代集合平滑的模型无关参数估计方法（Chen and Oliver, 2013；White, 2018）。本研究设置参数集合成员数为 200、最大更新轮次为 4，随机种子固定为 `20260722`。PEST++ 根据冻结参数域及先验协方差生成先验集合，并通过参数—观测交叉协方差迭代更新集合。显式生成观测噪声集合，使目标函数中的观测不确定性与 IES 数据扰动使用同一套 \(\sigma\) 定义。

参数集合是有限样本下的近似条件分布，不应被解释为严格的解析贝叶斯后验。其可靠性依赖参数先验、观测误差、模型结构、集合规模和非线性程度；因此，本研究同时报告先验和末轮集合，而不只报告单一最优参数集。

## 4. 观测误差与尺度变换

### 4.1 处理均值的有效标准差

FileA 和 FileT 当前记录处理均值。若重复层标准差 \(s_i\) 和有效重复数 \(n_{\mathrm{eff},i}\) 可获得，则观测 \(i\) 的有效标准差定义为

\[
\sigma_{i,\mathrm{eff}}=
\sqrt{\frac{s_i^2}{n_{\mathrm{eff},i}}+
\sigma_{i,\mathrm{model}}^2+
\sigma_{i,\mathrm{floor}}^2},
\]

其中 \(\sigma_{i,\mathrm{model}}\) 表示模型与田间尺度不匹配造成的附加误差，\(\sigma_{i,\mathrm{floor}}\) 防止观测方差过小导致单个观测获得不合理的大权重。对于同一植株上的重复时间观测，\(n_{\mathrm{eff}}\) 不应机械等于样本数，而应根据独立试验单元或区组数确定。

当前数据尚未提供重复层标准差，因此 T10 使用预先冻结的假设标准差，而不是从拟合残差反推误差：ADAP 25 d、LAID 2.0 m² m⁻²、LWAD 150 kg ha⁻¹、SWAD 200 kg ha⁻¹、CNAM 25 kg N ha⁻¹、CHFPW 和 CHPDT 250 kg ha⁻¹；各变量另分别加入预登记的模型误差和误差下限。该处理使率定可以执行，但后验区间必须表述为“条件于假设误差模型的参数不确定性”。获得原始重复数据后，应在不改变 FileA/FileT 均值的前提下，通过旁车不确定性表提供 `mean, sd, n_rep, n_eff`，重新计算 \(\sigma_{\mathrm{eff}}\)。

### 4.2 累计采收序列的对数残差

连续采收累计量通常随时间增大，其原始尺度误差方差也可能增大。参考 CROPGRO-Strawberry 对多次采收过程的建模经验（Hopf et al., 2022），CHFPW 和 CHPDT 在 PEST 专用观测空间中采用自然对数变换：

\[
z(y)=\ln\left(\frac{y+c}{r}\right),
\]

其中 \(c=1\ \mathrm{kg\ ha^{-1}}\) 是观测与模拟共同使用的零点修正，\(r=1\ \mathrm{kg\ ha^{-1}}\) 用于使对数自变量无量纲。若 \(y+c\le 0\)，该观测或模拟被判为无效。原始尺度标准差按对数正态/Delta 近似传播为

\[
\sigma_{i,\log}=
\sqrt{\ln\left[1+left(\frac{\sigma_{i,\mathrm{raw}}}{y_i+c}\right)^2\right]}.
\]

观测值和模拟值使用完全相同的变换。FileT、`FreshWt.OUT`、常规拟合指标和论文图始终保留 kg ha⁻¹ 原始尺度。实现上，运行器先把原始 CHFPW/CHPDT 写入审计文件和 PEST tagged 输出，再由同一 observation-transform 配置对模拟 token 执行一次变换；观测端在构建 PST 时执行同一定义，以防重复 log 或尺度不一致。

对数变换可缓解异方差，但不能消除累计观测之间的时间相关性，也不能使鲜重和由鲜重推导的干重相互独立。该问题通过目标族总预算加以限制，并在论文局限性中明确说明；当前框架未拟合完整时间协方差矩阵。

## 5. 目标函数与目标族平衡

设观测 \(o_i\)、模拟 \(s_i(\boldsymbol{\theta})\)，其残差尺度变换为 \(g_i(\cdot)\)，则标准化残差为

\[
e_i(\boldsymbol{\theta})=
\frac{g_i[s_i(\boldsymbol{\theta})]-g_i(o_i)}{\sigma_i}.
\]

原始统计权重固定为 \(1/\sigma_i\)。为避免观测数量多的变量主导率定，在每个“季节 × 科学目标族”内部再乘以

\[
a_{sf}=\sqrt{\frac{B_f}{n_{sf}}},
\qquad
w_i=\frac{1}{\sigma_i}\sqrt{\frac{B_f}{n_{sf}}},
\]

其中 \(B_f\) 为目标族 \(f\) 的预登记 Phi 预算，\(n_{sf}\) 为季节 \(s\) 中该目标族的活动观测数。总目标函数为

\[
\Phi(\boldsymbol{\theta})=
\sum_s\sum_f\sum_{i\in(s,f)}
\left\{w_i\left[g_i(s_i)-g_i(o_i)\right]\right\}^2.
\]

目标族预算为：

| 科学目标族 | \(B_f\) | 说明 |
|---|---:|---|
| PHENO | 0.10 | 物候低优先级，不允许主导无限生长型移栽茄子的率定 |
| CANOPY | 1.00 | LAID；LAIX 仅诊断 |
| BIOMASS | 1.00 | LWAD 与 SWAD 共享预算 |
| PLANT_N | 1.00 | CNAM；仅有观测的季节参与 |
| HARVEST_FRESH | 1.25 | CHFPW 完整累计序列，log 残差 |
| HARVEST_DRY | 1.25 | CHPDT 完整累计序列，log 残差 |

所有采收日期 H1–Hn 共同分享一次收获目标预算；增加采收次数会提高时序分辨率，但不会线性增加该变量在 Phi 中的总影响。`pwtadj1` 未启用，运行中也不根据阶段性拟合结果重新平衡组权重，避免目标函数定义随率定过程改变。

## 6. 连续采收事件和日期对齐

DSSAT 在收获管理事件后的次日才完整写出相应累计收获状态，而模拟结束于最后收获日时可能遗漏最后一次真实采收输出。为解决这一问题，本研究只在每个集合成员的本地 FileX 副本中执行以下处理：

1. 将 FileT 中真实采收日 \(d\) 对应的模型收获管理事件设置为 \(d-1\)；
2. 在最后一个真实模型收获事件后增加一个不对应观测、不进入 Phi 的虚拟末次收获事件；
3. 保证模拟时间覆盖虚拟事件后的状态写出；
4. 源 FileX 和 FileT 保持不变，并记录本地收获事件日程。

提取模拟 CHFPW/CHPDT 时，以 FileT 观测日期 \(d\) 为中心，只在 \([d-1,d+1]\) 内选择日期距离最小的有限模拟值；等距离时选择较晚日期，以对应 DSSAT 的日更新后写出语义。窗口内无有效值时该模型运行失败，不使用无界的 nearest-on-or-before 替代。每次运行均保存观测日期、模型事件日期、实际读取日期、原始鲜重和干重以及匹配窗口，用于审计末次采收是否正确读取。

## 7. IES 运行质量控制

每个集合成员在独立目录运行，两季按顺序完成后才合并 PEST 输出。任何季节失败都会使该成员整体标记为 `model_failed`，且不得向 PEST++ 提供上一轮遗留输出。工程失败包括：DSSAT 非零退出、必需输出缺失或为空、活动观测 token 缺失、非有限值、日期窗口内无法匹配，以及季节—处理—RUN 映射不一致。

正式设置 `ies_bad_phi_sigma=1×10³⁰⁰`，实质上禁用基于集合 Phi 均值和标准差的自动剔除。模型成功但 Phi 较高的成员定义为 `phi_outlier` 或低拟合成员，而不是模型失败。该成员仍保留在参数更新和后验诊断中，除非存在预先定义的工程失败证据。这样可减少参数空间尾部、多峰解或异参同效分支被经验阈值提前截断的风险。

正式运行前执行构建与接口检查，确认：41 个活动参数、432 条活动观测、两季 16 个 RUN、200 个集合成员、4 次更新、显式观测噪声集合、无 PWAD/PWAI/HWAM 活动观测、CHFPW/CHPDT 同尺度 log 转换以及禁用高 Phi 自动剔除。模型接口 smoke 要求两个季节全部处理返回码为 0，最后真实采收值可读取，源输入包哈希不变。

## 8. 拟合能力与独立验证

率定和验证均在原始物理尺度上分别按“季节 × 变量”计算指标。设观测为 \(o_i\)，模拟为 \(s_i\)，样本数为 \(n\)，则

\[
\mathrm{RMSE}=\sqrt{\frac{1}{n}\sum_{i=1}^{n}(s_i-o_i)^2},
\]

\[
\mathrm{RRMSE}=100\times\frac{\mathrm{RMSE}}{\bar{o}},
\]

\[
\mathrm{NSE}=1-\frac{\sum_i(s_i-o_i)^2}{\sum_i(o_i-\bar{o})^2},
\]

\[
\mathrm{Bias}=\frac{1}{n}\sum_i(s_i-o_i).
\]

同时报告 Pearson \(R^2\) 和 Willmott agreement index。\(R^2\) 仅表示线性同步性，不能代替对系统偏差敏感的 NSE、RMSE 和 Bias。对于 CHFPW/CHPDT，除全时序指标外，还报告最终累计量误差；不对累计序列差分后再伪装成独立增量观测。所有指标至少给出样本数和单位，不跨单位计算无物理意义的总体 RMSE。

率定阶段报告 2025 春、2025 秋的拟合表现和跨季节一致性。冻结参数集后，以 2026 春全部处理进行独立验证，验证观测不用于参数选择、边界调整、权重调整或模型结构选择。若在查看验证结果后再次修改参数域或目标函数，则原验证季失去严格独立验证资格，应明确改称模型改进数据。

## 9. 后验分布、参数共线性和异参同效分析

以下分析使用工程成功的完整先验集合与末轮集合，不先按高 Phi 截断参数空间。

### 9.1 后验分布与可识别性

对每个参数报告先验和末轮集合的中位数、均值、标准差、2.5%–97.5% 分位区间及边界接触率。以

\[
S_j=1-\frac{\mathrm{SD}_{post,j}}{\mathrm{SD}_{prior,j}}
\]

描述参数 \(j\) 的相对收缩程度，并结合先验—后验分布重叠、组 Phi 响应和边界接触判断可识别性。高收缩并不自动代表参数机制正确；若参数贴边、预测仍有系统偏差或结果对误差模型敏感，应优先考虑参数边界或模型结构问题。

### 9.2 参数相关性与共线性

分别在先验和末轮集合中计算参数 Pearson 和 Spearman 相关矩阵。共享参数和 PEST 侧偏移参数必须一起分析，同时导出按季节投影后的实际 DSSAT 参数表，避免把共享 `LFMAX` 与 `DLFMAX_AUT` 等误认为两套独立品种系数。对标准化参数集合进行主成分分析或奇异值分解，报告主成分解释比例、主要载荷和条件结构。相关性分析的目的不是机械删除所有高相关参数，而是识别由当前观测条件产生的补偿关系。只在末轮集合中出现的相关性称为“观测条件下的后验相关性”，不解释为完整参数空间中的固有因果关系。

### 9.3 异参同效

异参同效分析保留多个能产生相近总体 Phi 或相近核心变量性能、但位于不同参数区域的成员。近优成员阈值应在查看参数分布前预先登记，例如采用末轮 Phi 的最低 10% 作为描述性近优集合，并同时报告完整末轮集合，避免阈值选择掩盖不确定性。参数距离按冻结先验范围标准化：

\[
d_{ab}=\sqrt{\sum_j
\left(\frac{\theta_{a,j}-\theta_{b,j}}
{U_j-L_j}\right)^2},
\]

其中 \(U_j,L_j\) 为参数上下界。若两个成员具有相近 Phi 和预测误差但 \(d_{ab}\) 较大，则视为异参同效候选。进一步比较这些成员的分季组 Phi、水氮处理响应、参数边界位置以及 2026 春独立预测。只有在不查看验证结果的前提下预先制定规则，才能根据异参同效结果合理收窄参数范围、增加生理约束或补充观测；不得只保留单一最优成员后再声称参数已唯一识别。

## 10. 可重复性与数据追溯

正式运行由以下入口构建并执行：

```bat
tools\calibration\start_t10_formal.cmd
```

该入口默认构建 200 成员、4 次更新的 T10 M0 case。构建阶段生成并冻结：

- PEST control、template 和 instruction 文件；
- 参数 bounds ID、随机种子及命令行；
- season–treatment–RUN 映射；
- 观测注册表和权重审计；
- 目标族预算审计；
- 观测变换定义和观测噪声集合；
- 输入包 manifest/hash；
- 本地虚拟采收事件和日期读取审计；
- 运行状态、失败分类及正式启动 receipt。

论文归档时应同时保存 DSSAT 精确子版本、PEST++ 版本、Git commit、frozen bounds 文件、设计 JSON、观测策略、目标族策略、正式 PST、先验/末轮参数集合和原始尺度预测—观测配对表。仅保存“最佳参数 CSV”不足以复现实验。

## 11. 方法适用边界

1. **作物结构替代。** 本研究使用番茄 CROPGRO 模型结构描述茄子，参数率定只能在既定模型结构内改善数据匹配，不能消除结构性误差。
2. **标准差尚属假设。** 当前 FileA/FileT 是处理均值，尚无重复层标准差；参数后验宽度受假设 \(\sigma\) 明显影响。获得重复数据后应进行误差模型敏感性分析。
3. **累计序列相关。** log 变换缓解异方差，但未显式拟合同一处理内的时间协方差；目标族预算只能限制数据量主导，不能代替完整相关误差模型。
4. **鲜重和干重相关。** 若 CHPDT 由 CHFPW 和干物质比例换算，两者不独立；二者同时进入 Phi 是为了约束不同物理量，但不能把信息量简单视为翻倍。
5. **IES 后验是近似。** 有限集合、非线性、边界和先验设定均会影响末轮分布；应报告先验、全部成功末轮成员及敏感性分析。
6. **物候解释受限。** 无限生长型移栽茄子的部分物候终点缺乏清晰观测意义，因此物候只保留低权重辅助作用。
7. **验证必须封存。** 在正式参数和分析规则冻结前，不得使用 XXQL2601 指导参数选择。

## 附录 A：T10 M0 活动参数及冻结范围

| 参数 | 下界 | 上界 | 参数组 |
|---|---:|---:|---|
| LFMAX | 0.90 | 1.50 | 叶片生长 |
| SIZLF | 240 | 380 | 叶片生长 |
| SLAVR | 240 | 330 | 叶片生长 |
| XFRT | 0.70 | 1.00 | 果实分配 |
| FL-SD | 5 | 25 | 开花—种子发育 |
| FL-SH | 1 | 6 | 开花—采收 |
| PODUR | 25 | 60 | 荚果/果实持续期 |
| SDPDV | 80 | 300 | 单果/种子规模 |
| SFDUR | 8 | 30 | 充实持续期 |
| RHGHT | 0.80 | 2.20 | 株型结构 |
| RWDTH | 0.70 | 2.00 | 株型结构 |
| TRIFL | 0.40 | 0.65 | 株型结构 |
| JU-R0 | 2 | 12 | 生态型物候 |
| LNGSH | 25 | 50 | 生态型物候 |
| PM06 | 0.35 | 0.75 | 生态型物候 |
| PM09 | 0.60 | 1.00 | 生态型物候 |
| XFINT | 0.08 | 0.50 | 生态型物候/果实需求 |
| XFPHT | 31 | 70 | 生态型物候 |
| XMAGE | 8 | 30 | 生态型物候 |
| KCAN | 0.50 | 0.90 | 冠层光合 |
| KC_SLOPE | 0.04 | 0.20 | 冠层光合 |
| PARMAX | 25 | 55 | 冠层光合 |
| PHTMAX | 40 | 80 | 冠层光合 |
| ATOP | 0.55 | 1.00 | 根系/水分 |
| FRLFF | 0.25 | 0.50 | 根系/水分 |
| FRSTMF | 0.35 | 0.70 | 根系/水分 |
| PORPT | 0.12 | 0.30 | 根系/水分 |
| RTNO3 | 0.008 | 0.050 | 根系硝态氮吸收 |
| RTNH4 | 0.008 | 0.050 | 根系铵态氮吸收 |
| RTEXF | 0.05 | 0.25 | 根系氮吸收 |
| WTFSD | 0.35 | 0.75 | 根系/水分 |
| FINREF | 150 | 320 | 源库关系 |
| SIZREF | 200 | 420 | 源库关系 |
| VSSINK | 1.5 | 8.0 | 源库关系 |
| TB1 | 6 | 14 | 温度基点 |
| TB2 | 6 | 14 | 温度基点 |
| TB3 | 6 | 14 | 温度基点 |
| NSTFAC | 0.20 | 1.00 | 氮胁迫 |
| NMOBMX | 0.02 | 0.50 | 氮再转运 |
| NVSMOB | 0.15 | 0.60 | 氮再转运 |
| NRCVR | 0.03 | 0.35 | 氮回收 |

固定参数为：CSDL、PPSEN、THRSH、WTPSD、EM-FL、FL-LF、SD-PM、EM-V1、FL-VS、PL-EM、V1-JU、FRCNOD、EVMODC、SLAREF、TM1–TM3、TO11–TO13 和 TO21–TO23。完整初值、文件位置、参数组和审核说明以 `eggplant_t10_m0_v1_20260722.csv` 为准。

## 附录 B：可直接改写为论文正文的精简版本

> Crop growth was simulated using the DSSAT Cropping System Model v4.8. Because DSSAT does not provide a native eggplant model suitable for the present experiment, the CROPGRO tomato model structure was adopted and its cultivar, ecotype, and species coefficients were parameterized for the experimental eggplant cultivar. Weather, soil, initial soil water and mineral N, and management inputs were specified independently for each growing season using the corresponding experimental records. A common set of genetic and physiological parameters was jointly estimated against the 2025 spring and autumn experiments, whereas the 2026 spring experiment was withheld for independent validation.
>
> Parameter estimation was performed with PESTPP-IES using 200 realizations and four iterative updates. Forty-one genetic and physiological parameters were adjustable within pre-registered bounds, while 23 weakly identifiable or structurally redundant parameters were fixed. Calibration targets comprised LAI, leaf and stem dry mass, plant N accumulation, and cumulative fresh and dry fruit harvest. Phenology received a low objective-function budget, and maximum LAI, harvest index, HWAM, PWAD, and PWAI were excluded from parameter updating. Cumulative fresh and dry harvest observations and simulations were transformed as \(\ln[(y+1\ \mathrm{kg\ ha^{-1}})/(1\ \mathrm{kg\ ha^{-1}})]\); all reported fit statistics remained on the original physical scale.
>
> Observation weights were defined as the inverse of the effective standard deviation and were further scaled by the square root of a pre-registered family-level Phi budget divided by the number of active observations within each season and target family. This prevented densely sampled harvest series from dominating the objective function. The relative-Phi rejection threshold was disabled; only explicit model or output failures were excluded. Prior and final ensembles were retained for posterior-distribution, parameter-correlation, identifiability, and equifinality analyses. Model performance was evaluated separately by season and variable using RMSE, RRMSE, NSE, bias, \(R^2\), and the Willmott agreement index, followed by evaluation against the withheld 2026 spring experiment.

## 参考文献

1. Chen, Y., & Oliver, D. S. (2013). Levenberg–Marquardt forms of the iterative ensemble smoother for efficient history matching and uncertainty quantification. *Computational Geosciences*, 17, 689–703. https://doi.org/10.1007/s10596-013-9351-5
2. Hoogenboom, G., Porter, C. H., Boote, K. J., et al. (2019). The DSSAT crop modeling ecosystem. In *Advances in Crop Modelling for a Sustainable Agriculture* (pp. 173–216). https://doi.org/10.19103/AS.2019.0061.10
3. Hopf, A., Boote, K. J., Oh, J., et al. (2022). Development and improvement of the CROPGRO-Strawberry model. *Scientia Horticulturae*, 291, 110538. https://doi.org/10.1016/j.scienta.2021.110538
4. Jones, J. W., Hoogenboom, G., Porter, C. H., et al. (2003). The DSSAT cropping system model. *European Journal of Agronomy*, 18, 235–265. https://doi.org/10.1016/S1161-0301(02)00107-7
5. Nash, J. E., & Sutcliffe, J. V. (1970). River flow forecasting through conceptual models part I—A discussion of principles. *Journal of Hydrology*, 10, 282–290. https://doi.org/10.1016/0022-1694(70)90255-6
6. White, J. T. (2018). A model-independent iterative ensemble smoother for efficient history-matching and uncertainty quantification in very high dimensions. *Environmental Modelling & Software*, 109, 191–201. https://doi.org/10.1016/j.envsoft.2018.06.009
7. Willmott, C. J. (1982). Some comments on the evaluation of model performance. *Bulletin of the American Meteorological Society*, 63, 1309–1313. https://doi.org/10.1175/1520-0477(1982)063%3C1309:SCOEOM%3E2.0.CO;2

## 项目内方法依据

- 多季节设计：`configs/runs/eggplant_t10_m1_25sp_25fa_autumn_offsets_v1.json`
- 观测误差与尺度策略：`configs/runs/assumption_based_sigma_v4.csv`
- 科学目标族预算：`configs/runs/t10_multiseason_group_policy_v1.csv`
- 冻结参数范围：`data/parameter_registry/bounds_frozen/eggplant/eggplant_t10_m1_autumn_offsets_v1_20260723.csv`
- T10 历史详细设计：`docs/archive/sa_run_history/T10_直接连续采收与季节适应性联合率定方案_20260722.md`
- 正式启动入口：`tools/calibration/start_t10_m1_seasonal_offsets.cmd`
- 季节投影后验导出：`python -m src.reporting.export_seasonal_parameters --run-dir <run_dir> --prefix <run_id> --design configs/runs/eggplant_t10_m1_25sp_25fa_autumn_offsets_v1.json`
