"""Assemble the Chinese C16 results/discussion and data-backed manuscript tables."""
from pathlib import Path
import json
import shutil
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'paper/06_C16_Revision_20260920'
DATA=OUT/'data'
SECTIONS=ROOT/'paper/01_Sections'
TABLES=ROOT/'paper/02_Tables/C16'
TABLES.mkdir(parents=True,exist_ok=True)
backup=OUT/'previous_C15_sections';backup.mkdir(exist_ok=True)
for name in ['03_Results_Section_C15.md','04_Discussion_Section_C15.md','00_Combined_Results_Discussion.md']:
    src=SECTIONS/name
    if src.exists() and not (backup/name).exists(): shutil.copy2(src,backup/name)

def md(headers,rows):
    return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']+['---:']*(len(headers)-1))+' |\n'+''.join('| '+' | '.join(map(str,row))+' |\n' for row in rows)

params=pd.read_csv(DATA/'C16_parameters_with_bounds.csv').set_index('name')
param_specs=[('tb1','SPE','发育基温','°C'),('em-fl','CUL','出苗至始花光温时间','光温日'),
    ('fl-sh','CUL','始花至始荚光温时间','光温日'),('fl-vs','CUL','始花至停止叶片扩展光温时间','光温日'),
    ('sd-pm','CUL','始粒至生理成熟光温时间','光温日'),('lfmax','CUL','参考条件下最大叶片光合速率','mg CO₂ m⁻² s⁻¹'),
    ('slavr','CUL','参考比叶面积','cm² g⁻¹'),('xfrt','CUL','向生殖器官分配的最大比例','g g⁻¹'),
    ('sfdur','CUL','种子充实持续时间','光温日'),('xmage','ECO','采收成熟判定果龄参数','光温日'),
    ('rwumx','SPE','单位根长最大吸水速率','cm³ cm⁻¹ d⁻¹'),('frlff','SPE','叶片分配函数参数','g g⁻¹')]
rows=[]
for name,domain,meaning,unit in param_specs:
    r=params.loc[name]
    rows.append([name.upper(),domain,meaning,unit,f'{r.c16_value:.5g}',
                 f'{r.lower:g}' if r.lower==r.upper else f'{r.lower:g}–{r.upper:g}',
                 '固定' if r.status=='fixed' else '率定'])
t1=md(['参数','文件层级','含义','单位','C16','本轮范围','状态'],rows)

m=pd.read_csv(DATA/'terminal_yield_metrics.csv').set_index('group')
groups=[('calibration','本轮率定处理'),('held_out_treatments','本轮留出处理'),('25SP','25SP 全处理'),('26SP','26SP 全处理'),('25FA','25FA 跨季节诊断'),('two_springs','两春季合并'),('all_35','三季合并')]
t2=md(['评价子集','n','实测均值','模拟均值','RMSE','NRMSE（%）','Bias','r²','NSE','d'],
    [[label,int(m.loc[g,'n']),*[f'{m.loc[g,k]:.2f}' for k in ['observed_mean','simulated_mean','rmse','nrmse_pct']],
      f'{m.loc[g,"bias"]:+.2f}',*[f'{m.loc[g,k]:.3f}' for k in ['r_squared','nse','d_index']]] for g,label in groups])
c=pd.read_csv(DATA/'C15_C16_nitrogen_contrasts.csv').set_index(['season','water','contrast'])
t3=md(['季节','水分水平','实测 ΔY','C15 ΔY','C16 ΔY','C16 响应偏差'],
    [[s,w,*[f'{c.loc[(s,w,"N3-N0"),k]:.3f}' for k in ['observed_gap','c15_simulated_gap','simulated_gap']],
      f'{c.loc[(s,w,"N3-N0"),"gap_bias"]:+.3f}'] for s in ['25SP','26SP','25FA'] for w in ['W3','W2','W1']])
w=pd.read_csv(DATA/'water_contrasts.csv').set_index(['season','nitrogen','contrast'])
t4=md(['季节','施氮水平','实测 W3−W1','C16 W3−W1','响应偏差'],
    [[s,n,f'{w.loc[(s,n,"W3-W1"),"observed_gap"]:.3f}',f'{w.loc[(s,n,"W3-W1"),"simulated_gap"]:.3f}',f'{w.loc[(s,n,"W3-W1"),"gap_bias"]:+.3f}']
     for s in ['25SP','26SP','25FA'] for n in ['N0','N1','N2','N3']])
p=pd.read_csv(DATA/'process_metrics_by_season.csv').set_index(['season','variable'])
exact=pd.read_csv(DATA/'process_metrics_exact_dates.csv').set_index(['season','variable'])
for variable in ['LAID','LWAD','SWAD']:
    p.loc[('25FA',variable),exact.columns]=exact.loc[('25FA',variable)]
vlabels={'LAID':'LAI','LWAD':'叶干重','SWAD':'茎干重','FRESH_INC':'单次采收鲜重','FRESH_CUM':'事件累计鲜重'}
t5=md(['季节','变量','n','RMSE','NRMSE（%）','Bias','NSE','d'],
    [[s,vlabels[v],int(p.loc[(s,v),'n']),f'{p.loc[(s,v),"rmse"]:.3f}',f'{p.loc[(s,v),"nrmse_pct"]:.2f}',
      f'{p.loc[(s,v),"bias"]:+.3f}',f'{p.loc[(s,v),"nse"]:.3f}',f'{p.loc[(s,v),"d_index"]:.3f}']
     for s in ['25SP','26SP','25FA'] for v in vlabels])
for i,t in enumerate([t1,t2,t3,t4,t5],1): (TABLES/f'Table_{i}_C16.md').write_text(t,encoding='utf-8')
for src in ['C16_parameters_with_bounds.csv','terminal_yield_metrics.csv','C15_C16_nitrogen_contrasts.csv','water_contrasts.csv','process_metrics_exact_dates.csv']:
    shutil.copy2(DATA/src,TABLES/src)
p.reset_index().to_csv(TABLES/'Table5_C16_metrics.csv',index=False)
legacy=TABLES/'process_metrics_by_season.csv'
if legacy.exists(): legacy.replace(TABLES/'process_metrics_by_season_ARCHIVED_PAIRING.csv')

results=f'''# 3 结果

## 3.1 代表参数成员及评价数据组成

本研究在 DSSAT–CROPGRO-Tomato 框架下对茄子进行参数化，以同一 PEST++ IES 率定批次第 6 次迭代的 real_90 成员（C16）作为代表参数解。该批次初始参数集合包含 150 个成员，最终参数集合保留 100 个成员。实际目标函数记录中，第 0 次迭代有 145 个有效 Phi 值，第 6 次迭代有 100 个；两者的中位数分别为 13,031.7 和 1,382.4（图 2）。C16 的 Phi 为 1,074.88。集合规模和有效目标函数记录数分别报告，避免将缺失或失败成员视为有效评价值。

C16 的选取优先考虑低水分处理下的施氮响应幅度，同时保留产量误差作为评价依据。以总体产量误差较小的同批次 C15 为参照，比较两者在相同处理和观测口径下的结果。C16 的主要参数见表 1，完整参数及冻结范围见补充数据。冻结表包含 70 个 active、93 个 fixed 和 2 个 disabled 条目；这些状态不意味着所有条目都获得了独立的生理识别。C16 的 TRIFL 为 1.30，位于本轮允许上界，其余 active 条目未在数值容差内触及上下界。

**表 1. C16 的主要参数及本轮冻结范围**

{t1}
注：CUL、ECO 和 SPE 分别为品种、生态型和物种文件层级。文件层级不等同于独立测定的遗传性状。范围是本轮率定约束，数值为参数 CSV 导出值；DSSAT 实际输入按固定字段宽度写入。FL-VS 和 SD-PM 本轮固定，不能解释为数据估计所得。

评价数据包含 2025 春季（25SP）、2026 春季（26SP）和 2025 秋季作物季（25FA）分别 11、12 和 12 个季节—处理组合。两春季中，13 个处理用于本轮率定，另 10 个处理作为本轮留出处理；秋季用于跨季节诊断。25FA 的最后一次采收发生在 2026 年 1 月，仍按同一秋季作物季归组。由于三季数据曾用于候选成员比较，留出处理和秋季结果不作为完全未参与模型开发的独立盲测证据。25SP 包含 W2N3、W2N0 和 CK，但缺少 W2N1、W2N2，分析保留该不平衡结构，不补造缺失组合。

## 3.2 季末产量精度及代表成员切换的取舍

C16 在 35 个季节—处理组合上的季末累计鲜果产量 RMSE 为 4.61 t ha⁻¹，NRMSE 为 9.15%，平均偏差为 −1.75 t ha⁻¹（表 2；图 3）。与 C15 的总体 NRMSE 8.06% 相比，C16 的总体误差有所增加。两春季合并 NRMSE 从 6.60% 增至 7.85%，其中 26SP 的 RMSE 从 4.99 增至 6.31 t ha⁻¹，平均低估 4.58 t ha⁻¹。相对地，本轮留出处理的 NRMSE 从 7.38% 降至 6.96%，平均偏差从 +2.51 降至 +0.24 t ha⁻¹。

**表 2. C16 季末累计鲜果产量的分组评价**

{t2}
注：均值、RMSE 和 Bias 的单位为 t ha⁻¹；Bias = 模拟−实测，NRMSE = RMSE/相应子集实测均值 × 100%。r² 为 Pearson 相关系数平方；NSE 以各子集实测均值为基准；d 为 Willmott 一致性指数。n 是季节—处理配对数，不是独立重复小区数。各评价子集相互重叠，不能将 n 相加。

尽管留出处理的 r² 从 C15 的 0.007 增至 0.390，C16 的 NSE 仍为 −0.807；26SP 和 25FA 的季末 NSE 分别为 −0.242 和 −1.430。因此，这些子集的平方误差仍高于使用相应实测均值作为统一预测的基准。25FA 的 RMSE 从 3.12 降至 2.77 t ha⁻¹，但处理间模拟标准差仅为 0.25 t ha⁻¹，实测为 1.85 t ha⁻¹，反映出明显的处理差异压缩。

三季合并 r² 为 0.971，NSE 为 0.965。实测产量总离差平方和的 97.1% 来自季间均值差异，因而这一较高的合并拟合度主要反映春秋产量量级的分离。分季节指标与处理响应提供了进一步区分成员性能的信息。

## 3.3 氮肥与水分响应的幅度和方向

以同季节、同水分水平的 N3−N0 产量差表征施氮响应。在 25SP 的 W1 下，C16 给出的增产量为 10.151 t ha⁻¹，实测为 11.590 t ha⁻¹，即再现实测幅度的 87.6%；C15 对应值为 4.798 t ha⁻¹，仅占实测幅度的 41.4%（表 3；图 6）。26SP 的 W1 和 W2 下，C16 的响应分别为 8.015 和 6.188 t ha⁻¹，约为实测幅度的 48.6% 和 65.0%。与 C15 相比，这两组改善较小，主要改善集中在 25SP 的 W1。

**表 3. 同水分水平下 N3−N0 的季末鲜果产量差及 C15–C16 比较**

{t3}
注：产量差及响应偏差单位均为 t ha⁻¹。C15 仅作同批次参照，所有当前代表解结果均为 C16。差值由未舍入数据计算；响应偏差 = 模拟差值−实测差值。该比较未进行重复小区层面的显著性检验。

C16 对施氮响应的改进并不一致。25SP 的 W2 下实测 N3−N0 为 +8.121 t ha⁻¹，而 C16 为 −2.929 t ha⁻¹，仍存在方向逆转。25SP 和 26SP 的 W3 下，C16 分别高估响应幅度 5.841 和 4.947 t ha⁻¹。秋季各水分水平的模拟 N3−N0 仅为 0.004–0.006 t ha⁻¹，远小于实测的 1.242–2.820 t ha⁻¹。

相邻施氮水平揭示了进一步的响应结构差异。例如，26SP 的 W2 下实测 N2−N1 为 +8.667 t ha⁻¹，C16 为 −0.020 t ha⁻¹；W3 下实测 N3−N2 为 −3.805 t ha⁻¹，C16 为 −0.002 t ha⁻¹。C16 的增产主要集中在 N0 到施氮处理的跨越，较高施氮水平之间的模拟差异较小。N3−N0 响应改善因而不能视为完整氮肥剂量响应已被再现。

保持施氮等级一致后，水分响应也呈现季节依赖性（表 4；图 6 配套水分响应图）。25SP 的 N0 下，W3−W1 的实测与模拟差值分别为 +8.681 和 +4.480 t ha⁻¹；26SP 的 N0 下分别为 +9.313 和 −3.793 t ha⁻¹，后者方向相反。秋季模拟 W3−W1 在各施氮水平下均约为 0.507 t ha⁻¹，而实测差值为 1.000–4.267 t ha⁻¹。

**表 4. 同施氮等级下 W3−W1 的季末鲜果产量差**

{t4}
注：单位为 t ha⁻¹。正值表示 W3 高于 W1，负值表示 W3 低于 W1。表中比较处理均值，不将水分等级自动换算为 ETc 比例；也不将有符号差值视为统计显著的水×氮交互。完整 W2−W1 对比随图源数据提供。

## 3.4 三季生长过程与分次采收诊断

25SP 和 26SP 的 LAI RMSE 分别为 0.759 和 0.886 m² m⁻²，叶干重 RMSE 分别为 318.6 和 324.9 kg ha⁻¹（表 5）。两春季的茎干重均被系统性低估，平均偏差分别为 −436.6 和 −555.5 kg ha⁻¹。每日模拟线与离散观测点的对比显示，C16 在部分春季 N0 处理中给出后期 LAI 和叶干重下降，而实测末期叶面积和叶干重仍保持较高水平（图 4；图 S4）。

**表 5. C16 的季内过程及采收事件评价**

{t5}
注：LAI 的 RMSE/Bias 单位为 m² m⁻²；叶、茎干重为 kg ha⁻¹；鲜果单次采收与事件累计鲜重为 t ha⁻¹。过程观测为 25SP/26SP 每处理 4 次、25FA 每处理 3 次；采收事件分别为每处理 10、5、3 次。秋季 2026-01-10 的过程观测晚于 01-06 的模型输出终点，故表中过程指标仅采用每处理 2 次同日配对（n=24）；动态图仍显示全部观测。n 是处理×观测日期配对数，同一处理的重复观测及累计采收值具有时间依赖性。指标不使用视觉插值曲线。

25SP、26SP 和 25FA 的事件累计鲜重 NSE 分别为 0.934、0.935 和 0.814，但单次采收鲜重 NSE 分别为 −1.221、0.053 和 −0.750。累计量所表现出的季内增加趋势与单次采收量的准确再现并不一致。25SP 有 12 个采收配对点在实测鲜重为正时模拟增量为零，提示采收批次与模拟产出的时间对应仍需检验。该季存档包含 7 月 17 日采收点，与试验说明所记 7 月 11 日末次采收不一致；本节按存档口径报告，日期差异的影响应在最终数据版本中单独复核。

25FA 的营养生长误差明显大于其季末产量相对误差：在同日配对口径下，LAI、叶干重和茎干重的 NRMSE 分别为 90.67%、99.09% 和 97.38%，且偏差均为负。若按旧配对程序将 1 月 6 日末日模拟值用于 1 月 10 日观测，三项 NRMSE 分别为 90.00%、104.48% 和 95.73%；这些近邻配对仅留作审计，不进入表 5 或 R 性能、残差图的统计。两种口径均显示明显的营养生长低估。全处理动态图显示全部观测的真实日期位置，包括模型输出结束后的观测点，并在同季同变量内使用统一纵轴；模型线保持原始终点。

## 3.5 叶氮约束与条件参数集合

2025 年 7 月 13 日的叶氮数据包含 9 个小区编号、每编号 3 条重复记录。按记录均值并与同日模拟值配对，实测叶氮质量分数为 4.28%–4.93%，C16 为 7.88%–19.80%；RMSE 为 7.55 个百分点，平均偏差为 +5.95 个百分点，NRMSE 为 165.80%，d 为 0.020（叶氮补充图）。W3N0 和 W1N0 的模拟值分别达到 18.06% 和 19.80%。原始表中的 CK/CK 标识保留为对照类别；因重复记录的独立性尚未确立，图中不绘制推断性的标准误差棒。

同批次最终条件参数集合中，TB1 的中位数为 8.584 °C，5%–95% 分位数为 8.078–9.239 °C，四分位距相对初始集合缩小 11.4%（图 S5）。C16 的 TB1 为 8.948 °C。条件集合分布、秩相关和候选对距离图描述的是本次率定批次，不随代表成员从 C15 改为 C16 而重新定义样本集合（图 S5–S7）。这些描述性集合特征与 C16 的叶氮偏差共同表明，较低目标函数值及部分产量响应改善尚未消除过程层面的约束缺口。
'''

discussion='''# 4 讨论

## 4.1 代表成员选择需要同时评价误差和管理响应

C16 的主要价值是提高了特定低水分条件下的氮肥产量响应幅度。25SP 的 W1 下，其 N3−N0 差值已接近实测，但三季总体 NRMSE 由 C15 的 8.06% 增至 9.15%，且 26SP 的均值低估加重。这一取舍说明，按总体产量误差选择成员与按处理对比选择成员，可能得到不同的代表解。对于水氮管理研究，成员评价需要把季末产量、同水分下的氮响应和同氮水平下的水分响应同时列出，才足以判断参数解是否适合目标用途。

本研究也显示了合并指标的局限。春秋季产量量级差异贡献了实测总变异的绝大部分，使三季合并 r² 和 NSE 较高；然而，留出处理和秋季的季末 NSE 仍为负。这些指标衡量的是不同层次的拟合性质，不能相互替代。后续代表成员选择宜采用预先规定的多准则规则，并将季内处理排序、响应幅度误差和方向错误作为明确评价项。Wallach 等（2021）关于作物模型率定差异的研究强调了率定过程与评价设计的可追溯性；本研究的成员比较进一步表明，选择准则本身也应作为方法的一部分报告。

## 4.2 氮响应增强的生理解释仍需过程证据

C16 的响应改善主要表现为 N0 与施氮处理间的分离，而 N1–N3 之间仍接近平台。这种模式与施氮阈值附近的限制解除相容，但单凭最终产量差不能确定其来源。土壤供氮、根系吸收、叶面积维持、碳氮分配和采收时序均可能影响模拟的处理差异。尤其是 25SP 的 W2 氮响应和 26SP 的 N0 水分响应仍然反向，说明一个低水分对比的改善尚不足以支持普遍的水氮互补或“施氮缓解干旱”结论。

叶氮偏差对机制解释构成了直接限制。C16 在春季 N0 处理中同时出现较早的叶面积下降和较高的模拟叶氮质量分数，提示应联合检查活叶干物质、叶氮总量、衰老转移和模型输出定义。浓度由氮量与干物质量共同决定，分母变化可能放大浓度，但当前配对结果尚不能区分其与氮吸收、再分配或观测尺度差异的贡献。在完成叶氮单位、取样器官与活叶口径的核对之前，不应把 C16 较强的产量氮响应解释为氮代谢机制已经被正确识别。

秋季的结果同样需要从过程约束出发理解。模拟能够给出较低的季节产量量级，却几乎不区分施氮水平，并显著低估叶面积和营养器官生物量。温度、辐射、物候、初始土壤状态和管理输入共同作用于该季模拟，现有证据不能将误差归因于单一基温参数。更有效的检验是比较这些过程在独立观测时点的偏差，并以有对照的参数或输入扰动确定响应丢失发生在何处。

## 4.3 连续采收作物的适配需要同时约束器官分配与采收事件

CROPGRO-Tomato 为茄子提供了可用的生长过程框架，但本次参数化并未获得同等程度的器官生长和采收批次精度。两春季茎干重持续低估、部分 N0 处理后期叶面积下降以及秋季营养生长低估，共同提示需要检验器官分配、叶片维持与生殖输出之间的匹配。Heuvelink（1996）通过番茄干物质分配模型讨论了器官库需求与分配的联系；该类过程假设可用于组织后续检验，但不能仅凭当前末期器官偏差确定具体的分配机制。

累计采收指标与单次采收指标的差异尤其关键。累计量包含随时间增长的共同趋势，并会吸收或抵消早晚批次间的误差。较高的事件累计 NSE 因而不能证明采收峰值、批次产量或采收间隔正确。对于连续采收茄子，应分别约束在株果实生长、达到采收条件的果实数量、鲜干物质关系和实际采收事件，并核对修剪、摘叶及留果管理记录。CROPGRO-Strawberry 的开发与改进也将温度响应、同化物分配及连续生殖生长适配纳入模型改进（Hopf 等，2022），为这类分过程评价提供了相关研究背景。

本研究同时保留事件折线和单调插值图，是为了区分原始采收节点与视觉表达。插值仅连接已有模拟节点，不增加观测、不补造秋季第四次采收，也不参与误差计算。后续涉及采收时序的判断应回到原始事件和每日模型输出，而非依赖曲线平滑程度。

## 4.4 条件参数集合收缩不等同于唯一的生理识别

C16 的 TB1 与最终集合中位数不同，而 TB1 的集合分位区间仍覆盖较宽范围。该结果支持报告本次参数化的不确定性，也提示不能将一个代表成员的基温直接解释为茄子的普适生理常数。FL-VS 和 SD-PM 等固定参数更不能被归为本次率定的生理发现。C16 的 TRIFL 触及上界，需要通过边界敏感性及物候或叶片出现观测检验，不能仅凭触界现象扩大参数范围。

IES 条件集合取决于初始分布、观测权重、参数约束及算法筛选。没有完整概率模型和相应检验时，其 5%–95% 区间宜称为集合分位区间，而非置信区间或可信区间。参数间 Spearman 相关只描述该条件集合中的关联，不构成生理因果网络。候选参数对的预测距离也取决于所选变量和归一化尺度；预测彼此相近并不保证接近实测。因而，同批次参数分布与异参同效图适合作为可辨识性诊断，不能替代 C16 对独立过程数据的检验。

## 4.5 适用范围与下一阶段验证

现阶段，C16 可作为兼顾部分氮响应的代表参数解，用于呈现本试验条件下产量、过程和管理响应之间的取舍。其改善具有明确的情景边界：25SP 的 W1 响应再现较好，但 W2 方向错误、秋季水氮响应压缩和叶氮高估仍未解决。因此，当前结果尚不足以直接推导最优灌溉施氮组合、跨地点适用性或已验证的节水减氮效益。

下一阶段应首先统一采收日期、处理标签、鲜干重和叶氮观测口径，并使用重复小区数据为处理对比提供不确定性范围。在此基础上，将 C16 与 C15 及其他候选成员的选择规则固定，在未参与调参和成员选择的新季节或地点进行评价。对机制改进，应优先检验春季 N0 叶片维持与氮浓度、秋季冠层生长和供氮响应、以及采收事件错配三个已被观测暴露的问题。只有这些检验同时改善过程拟合和管理响应，模型才适宜进一步用于稳健的水氮管理优化。

## 参考文献

1. Heuvelink, E., 1996. Dry matter partitioning in tomato: validation of a dynamic simulation model. *Annals of Botany* 77, 71–80. [DOI: 10.1006/anbo.1996.0009](https://doi.org/10.1006/anbo.1996.0009).
2. Hopf, A., Boote, K.J., Oh, J., Guan, Z., Agehara, S., Shelia, V., Whitaker, V.M., Asseng, S., Zhao, X., Hoogenboom, G., 2022. Development and improvement of the CROPGRO-Strawberry model. *Scientia Horticulturae* 291, 110538. [DOI: 10.1016/j.scienta.2021.110538](https://doi.org/10.1016/j.scienta.2021.110538).
3. Wallach, D., Palosuo, T., Thorburn, P., et al., 2021. The chaos in calibrating crop models: Lessons learned from a multi-model calibration exercise. *Environmental Modelling & Software* 145, 105206. [作者机构收录及全文](https://orbi.uliege.be/handle/2268/265623).
'''
(SECTIONS/'03_Results_Section_C16.md').write_text(results,encoding='utf-8')
(SECTIONS/'04_Discussion_Section_C16.md').write_text(discussion,encoding='utf-8')
combined='# C16（real_90）结果与讨论\n\n'+results+'\n---\n\n'+discussion
(SECTIONS/'00_Combined_Results_Discussion.md').write_text(combined,encoding='utf-8')
(OUT/'manuscript_summary.json').write_text(json.dumps(dict(results_characters=len(results),discussion_characters=len(discussion),tables=5,candidate='C16',comparison_member='C15'),ensure_ascii=False,indent=2),encoding='utf-8')
print(f'Wrote C16 sections and five tables: {len(results)} + {len(discussion)} characters.')
