"""Write the source-backed stage 0/1 review; never edits manuscript inputs."""
from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'workspace/reviews/paper_stage01_20261031'
B = OUT / 'paper_data'


def table(df):
    def cell(x):
        if pd.isna(x): return '—'
        if isinstance(x, float): return f'{x:.6g}'
        return str(x).replace('|', '/').replace('\n', '<br>')
    lines = ['| ' + ' | '.join(df.columns) + ' |', '| ' + ' | '.join(['---'] * len(df.columns)) + ' |']
    return '\n'.join(lines + ['| ' + ' | '.join(cell(x) for x in row) + ' |' for row in df.itertuples(index=False, name=None)])


def main():
    m = pd.read_csv(B / 'performance_metrics.csv')
    p = pd.read_csv(B / 'parameter_reconciliation.csv')
    roles = pd.read_csv(B / 'treatment_role_audit.csv')
    management = pd.read_csv(B / 'management_audit.csv')
    receipt = json.loads((OUT / 'stage0_verification.json').read_text(encoding='utf-8'))
    core_names = ['CSDL', 'PPSEN', 'EM-FL', 'FL-SH', 'FL-SD', 'FL-LF', 'FL-VS', 'LFMAX', 'SLAVR',
                  'SIZLF', 'XFRT', 'WTPSD', 'SFDUR', 'SDPDV', 'PODUR', 'THRSH', 'LNGSH', 'XMAGE',
                  'XFINT', 'XFPHT', 'KCAN', 'TB1', 'PM09']
    core = p[p.parameter.isin(core_names)].copy()
    core['parameter'] = pd.Categorical(core.parameter, categories=core_names, ordered=True)
    core = core.sort_values('parameter')
    core.to_csv(OUT / '核心参数核对表.csv', index=False, encoding='utf-8-sig')
    ledger = [
        ('参数及持续采收段', 'XMAGE', '19.0', '13.3802；模型可读13.4', '参数CSV与ECO固定列宽文件'),
        ('参数及动态分配段', 'XFINT', '0.12', '0.379887；模型可读0.3799', '参数CSV与ECO固定列宽文件'),
        ('参数及动态分配段', 'XFPHT', '38.8', '43.7261；模型可读43.7', '参数CSV与ECO固定列宽文件'),
        ('持续采收参数段', 'LNGSH', '23.2', '18.0（候选CSV）', 'parameter_reconciliation.csv'),
        ('持续采收参数段', 'SFDUR', '24.6', '20.0（候选CSV）', 'parameter_reconciliation.csv'),
        ('摘要及2.2', '留出季末产量d', '0.834', '0.837434，三位小数0.837', '两春留出10处理；同日；C31确定性'),
        ('2.2', '25SP累计鲜重nRMSE/NSE/d', '9.66% / 0.968 / 0.992', '12.984552% / 0.944326 / 0.987068', '99个处理×采收事件配对；同日'),
        ('2.2', '26SP累计鲜重nRMSE/NSE/d', '20.57% / 0.866 / 0.967', '9.824061% / 0.969609 / 0.992147', '60个处理×采收事件配对；同日'),
        ('表5及生长结果', '25SP LAI RMSE', '0.353', '0.620186', '44个生长配对；C31确定性'),
        ('表5及生长结果', '26SP LAI RMSE', '0.791', '0.643234', '48个生长配对；C31确定性'),
        ('方法及图例', '率定/留出角色', '每季四角点的叙述需核改', '25SP 6/5；26SP 7/5；合计13/10', '实际PST正权重行与实际批处理文件交叉核对'),
        ('参数集合分析', '最终成员数', '142含base', '141非base用于本次重算；142仅为含base总行数', '不改写既有142口径图件，阶段2需同步重绘'),
        ('图注及不确定性', 'THRSH/XFINT/XFPHT后验', '若作为本轮可变参数分析则不适用', '本轮固定；不画后验、不计秩相关', '实际PST transform=fixed'),
    ]
    ledger = pd.DataFrame(ledger, columns=['位置', '项目', '现稿或既有口径', '统一建议', '计算范围或证据'])
    ledger.to_csv(OUT / '现稿数值与口径对账.csv', index=False, encoding='utf-8-sig')
    inventory = json.loads((ROOT / 'workspace/reviews/figure_system_plan_20261019/manuscript_inventory.json').read_text(encoding='utf-8'))
    table_parameters = []
    for number, entry in enumerate(inventory['tables'], 1):
        if entry['rows'][0][:1] != ['参数']: continue
        for row in entry['rows'][1:]:
            hit = p[p.parameter.eq(row[0].upper())]
            if len(hit) != 1:
                table_parameters.append(dict(现稿表=number, 参数=row[0], 现稿原始值=row[2], 现稿率定值=row[3], C31候选值=None, 结论='未直接匹配参数注册名；另核对', 原始值状态='尚未核实原番茄模板'))
                continue
            value = float(hit.c31_candidate_value.iloc[0])
            try: same = abs(float(row[3])-value) < 1e-6
            except ValueError: same = False
            table_parameters.append(dict(现稿表=number, 参数=row[0], 现稿原始值=row[2], 现稿率定值=row[3], C31候选值=value, 结论='与C31一致' if same else '与C31不一致', 原始值状态='尚未核实原番茄模板'))
    table_parameters = pd.DataFrame(table_parameters)
    table_parameters.to_csv(OUT / '现稿参数表逐项对账.csv', index=False, encoding='utf-8-sig')
    table_performance = []
    for row in inventory['tables'][4]['rows'][1:]:
        if row[0] not in ['25SP','26SP']: continue
        variable = 'LAID' if row[1].startswith('LAI') else 'LWAD' if row[1].startswith('叶') else 'SWAD'
        actual = m[(m.variant=='baseline') & (m.date_offset_days==0) & (m.dataset_role=='all') & (m.season_id==row[0]) & (m.variable==variable)].iloc[0]
        for index, key in enumerate(['n','rmse','nrmse_pct','r_squared','nse','d_index'],2):
            table_performance.append(dict(现稿表=5,季节=row[0],变量=variable,指标=key,现稿值=row[index],C31统一值=actual[key]))
    pd.DataFrame(table_performance).to_csv(OUT / '现稿表5逐项对账.csv', index=False, encoding='utf-8-sig')
    metrics_main = m[(m.variant == 'baseline') & (m.date_offset_days == 0)].copy()
    metrics_main.to_csv(OUT / 'C31同日性能统一表.csv', index=False, encoding='utf-8-sig')
    metrics_ablation = m[(m.dataset_role == 'all') & (m.date_offset_days == 0)].copy()
    metrics_ablation.to_csv(OUT / '动态分配消融指标.csv', index=False, encoding='utf-8-sig')
    role_table = roles[['season_id', 'treatment', 'water_level', 'nitrogen_level', 'evaluation_label_zh', 'positive_objective_rows']].rename(columns={
        'season_id': '季节', 'treatment': '处理编号', 'water_level': '水分', 'nitrogen_level': '氮素',
        'evaluation_label_zh': '评价角色', 'positive_objective_rows': '实际目标行数'})
    main_summary = metrics_main[(metrics_main.dataset_role == 'all') & metrics_main.season_id.isin(['25SP', '26SP'])][['season_id', 'variable', 'n', 'rmse', 'nrmse_pct', 'bias', 'nse', 'd_index']]
    main_summary.columns = ['季节', '变量', 'n', 'RMSE', 'nRMSE（%）', 'Bias', 'NSE', 'd']
    core_summary = core[['parameter', 'c31_candidate_value', 'working_lower', 'working_upper', 'fixed_in_reference_ies', 'ensemble_median']].copy()
    core_summary.columns = ['参数', 'C31候选值', '实际PST下界', '实际PST上界', '参考IES中固定', '参考集合中位数']
    management_summary = management.groupby(['season_id', 'water_level']).irrigation_mm.first().reset_index()
    management_summary.columns = ['季节', '水分', '实际配置灌水量（mm）']
    nitrogen_summary = management.groupby(['season_id', 'nitrogen_level']).nitrogen_kg_ha.first().reset_index()
    nitrogen_summary.columns = ['季节', '氮素', '实际配置施氮量（kg ha⁻¹）']
    text = f'''# 阶段0：C31基线核对与统一口径

核查日期：2026-10-31。范围：2025春（25SP）、2026春（26SP）。沿用用户确认的C31；本次没有重新率定、没有修改10.6原Word、没有覆盖已有正式图件。阶段0交付为核对结果及可复用冻结数据，阶段1交付为三种图形的样板和累计视觉备选。

## 1. 已冻结的共同口径

1. **确定性结果使用C31 / c28_scheme1_tb1_92**。参数来自[候选参数](../../candidates/candidate_c31_scheme1_dual_spring_precision/params.csv)，运行输出来自[25SP](../../runs/c31_deterministic/_seasons/25SP/)和[26SP](../../runs/c31_deterministic/_seasons/26SP/)。C31与09/27 IES最终集合并非同一代表参数组；集合中位数不能替换C31参数后继续沿用C31性能。
2. **13个率定处理、10个留出处理**。角色由实际PST正权重行、实际DSSBatch与冻结角色表共同核定，详见下一节。图中文字使用“留出处理”，暂不称“独立盲验证”。
3. **采收主图暂用观测当天的归档日输出**，以保持与既有C31及消融基线一致。另保留DATE+1比较，不混进同一指标。当前归档输出中两种读出所得基线采收指标数值相同；26SP末次DATE+1缺日，已显式回退到当天。源代码归档版本与可执行文件版本不同，科学意义上的日内读出规则仍需最终确认。
4. 参数集合诊断统一使用**141个非base最终成员**；初始为199个非base成员。200/142分别只是含base的总行数。这里只重算、导出核对统计，阶段2再更新全部密度、相关及正文数值。
5. 本次数据状态保留`audit_review_unvalidated`，图上保留DEMO/样板标识。可追溯、可复算不等于已完成全部科学有效性审查。

## 2. 实际目标函数与角色

参考运行：`full_gen_13trt_final_scheme1_tb1_tighten_200x6_20260927`。实际PST有**168个参数行，其中67个活动、101个固定**；run_manifest的191不能当作本轮活动参数数量。实际目标函数共**455个正权重行**，其中443个观测或派生目标、12个人工约束（6个`pen_ctrs`、6个`pen_monos`）。不能把455全部称为田间实测样本。

目标组包含物候、最大LAI、地上部氮量、时点LAI/叶干重/茎干重/累计干采收，以及累计和单次干采收目标；本轮PST中没有直接的鲜果采收观测目标。因此“联合约束了鲜果采收”需要说明干重目标及鲜干比转换路径，不能把鲜果评价值直接称为本轮PST目标。

{table(role_table)}

全部455个正权重行只对应上表13个率定处理。**这一证据只排除了该PST直接使用留出目标，不能证明预率定、历史候选筛选或权重调整从未参考留出数据。** C31候选与参考IES批次的衔接、历史模型选择独立性仍未完全建立，故不使用未经限定的“独立验证”。完整组别、权重与逐行映射见[目标组核对](paper_data/objective_group_audit.csv)、[目标逐行核对](paper_data/objective_observations.csv)。

## 3. 参数、域与固定状态

{table(core_summary)}

上表的候选值保留率定CSV精度；实际模型文件有固定列宽及舍入，关键ECO参数实际读入为**XMAGE=13.4、XFPHT=43.7、XFINT=0.3799**。图8参数化函数使用这一模型可读精度。完整168项、实际PST工作域、冻结建议域、文件位置、非base集合分位数、IQR收缩和边界命中比例见[参数核对表](paper_data/parameter_reconciliation.csv)。实际PST工作域与冻结域分列，不能互相替代，也不能当作物理硬边界。

THRSH=8.5、XFINT、XFPHT在本轮参考IES中均固定，三者不进入本轮后验密度或相关矩阵。固定只表示本轮未联合更新，不表示其数值没有上游选取过程。KCAN位于SPE，当前PHOTO=L配置下，既有15次单参数前向核验显示非零但很弱的数值响应；保留全诊断，不以其集合收缩将其表述为核心高敏感参数。原证据见[既有KCAN核验](../paper_sections_audit_20261005/response_parameter_revision/kcan_verification.json)。

**番茄原模板默认值尚未建立可信基线。** 项目现有`.base`已被参数化，不能直接当作未经修改的CROPGRO-Tomato原默认。本次全部标记`tomato_default_verified=False`，不把稿中“由默认值增至/降至”的前半句自动写进新主表。未来需要指定DSSAT版本、原始品种/生态型与原始文件哈希后再补这一列。

集合为09/27参考IES参数条件集合；尚不能将其区间直接称为C31的完整预测区间。新的141非base分位数、IQR及相关需要配套更新；既有142含base图注不能只把数字改成141而不重算。

## 4. 实际模型管理量及气象

{table(management_summary)}

{table(nitrogen_summary)}

这些是归档FileX的**实际配置总量**，尚不等于已经核定的真实田间总量。稿中名义120/240/360 kg ha⁻¹可以描述试验设计，但不能替代模型实输入122/254/364或120/240/361。25SP存在W2N3；缺W2N1与W2N2，不补点。CK为独立对照，不能冒充W2N2。

25SP实际引用气象站`XXLI2502.WTH`，26SP为`XXQL2601.WTH`。站名/文件名不用于推断试验季节。归档天气文件覆盖范围分别为2025001–2026199、2026001–2026199（这是文件覆盖，不是作物生育期）。共同字段为DATE、SRAD、TMAX、TMIN、RAIN、RHUM。没有直接VPD或30分钟温湿度序列，也未取得可追溯的修剪事件日期；不据此编造VPD图或修剪竖线。下一阶段绘气象管理图时应截取真实模拟/试验日期。

完整逐处理管理因子、灌溉/施氮事件计数及输入文件见[管理核对](paper_data/management_audit.csv)；气象见[天气来源核对](paper_data/weather_audit.csv)。本轮没有修改FileX或天气源文件来迎合现稿。

## 5. C31确定性性能

nRMSE=100×RMSE/实测均值，Bias=模拟−实测；r²为观测与模拟Pearson相关系数的平方，与NSE分列。叶/茎干重单位为kg ha⁻¹，鲜重为t ha⁻¹，LAI为m² m⁻²。累计采收与单次采收的n为“处理×事件”配对数量，不是独立田间重复数。

{table(main_summary)}

两春合并季末产量：n=23，RMSE=3.586024 t ha⁻¹，nRMSE=5.566853%，d=0.908354。率定13处理nRMSE=5.435306%、r²=0.820023、d=0.933612；留出10处理nRMSE=5.738475%、r²=0.678127、d=0.837434、NSE=0.005978。结果不应只引用较好的相关系数而忽略留出终产量NSE接近0的表现。

主图4的LAI、叶干重、茎干重各92对；单次及累计鲜重各159对；季末鲜果产量23对，总计617对。前两类鲜重与末次鲜重在统计含义上不同，不能将三者合并计算一个总体n或把季末点当作新增独立采收事件。

## 6. 现稿对账与修改方向

{table(ledger)}

现稿参数表3、表4逐项核对如下；未核实的“原始值”不能用于计算相对变化百分比。详细数据见[参数表逐项对账](现稿参数表逐项对账.csv)，表5两春全部指标对账见[表5逐项对账](现稿表5逐项对账.csv)。25FA暂不纳入本轮两春图表体系。

{table(table_parameters)}

完整统一指标见[C31同日性能统一表](C31同日性能统一表.csv)，包含两季、率定/留出及合并季末结果。正文原9.66%/20.57%与本轮同一C31确定性数据不一致；本轮同日与DATE+1基线数值也相同，不能仅用“一天偏移”解释这组差异。若要保留另一套数值，必须另指明候选、集合汇总方式、节点及来源，而不能与C31消融混用。

## 7. 观测误差与消融边界

归档不确定性共860行，其中`replicate_sd`且n_rep>1、quality_flag=ok的320行具备作为实测重复误差的候选资格（25SP 161行、26SP 159行）；仍须与具体图形变量、单位和节点逐键匹配后才可绘图。其余包含最小CV调整、日期固定误差、插补、鲜干比传播及累计方差传播，均不能直接当作田间实测重复SD。阶段1样板未使用这些混合误差棒。详见[误差来源核对](paper_data/observation_uncertainty_audit.csv)。

图8复用既有隔离前向运行，以XFINT=1关闭动态增幅，XMAGE和其他输入不变，不重新率定。两种关闭方式的等价性及基线复现已有18次运行证据；本次重新从归档输出构建1824个配对，全部与既有核验一致，C31当天594对和23个季末点也分别复现。

关闭后25SP/26SP累计鲜重nRMSE由12.98%/9.82%升至35.70%/19.12%；两春合并季末nRMSE由5.57%升至16.84%。但26SP LAI由35.81%降至26.24%，叶/茎干重误差分别由21.17%/21.55%升至40.71%/44.81%。这支持“当前参数化和试验条件下动态分配对联合模拟有作用”，不单独证明其对所有无限生长作物不可替代，也不能排除关闭后重新率定得到不同结果。

## 8. 验收与尚待闭合的科学问题

数据核对完成；来源哈希、逐点比较、角色、成员及舍入均有记录。科学缺口已明确登记：①未经修改的番茄默认模板；②历史选模/预率定的留出独立性；③采收日内读出与可执行版本对应；④模型实际管理量与原田间记录一致性；⑤完整预测不确定性及覆盖率。以上缺口不通过制图自动消除。

验收文件：[阶段0核对记录](stage0_verification.json)、[源文件哈希](source_hashes.json)、[冻结数据清单](paper_data/paper_data_manifest.json)。原稿SHA-256已纳入源清单并在交付前复核。阶段1的图、图注与使用边界见[阶段1交付说明](阶段1图注与使用说明.md)。
'''
    (OUT / '阶段0核对与统一口径.md').write_text(text, encoding='utf-8')
    captions = '''# 阶段1：三张样板图与图注

2026-10-31。按已确认方案完成图1、图8及图4小样。设计编号暂定；全部183 mm宽，微软雅黑，600 dpi PNG，并提供PDF与可编辑SVG。图1高124 mm，图8高160 mm，图4高128 mm。图内保留DEMO/样板标识，表示科学审核尚有未闭合项；不是虚构数据，也不代表已通过最终论文验收。未改动10.6原Word及既有正式图件。

## 图1 模型机制及参数率定评价流程

[预览PNG](figures/DEMO_Fig1_framework_prototype.png)｜[PDF](figures/DEMO_Fig1_framework_prototype.pdf)｜[SVG](figures/DEMO_Fig1_framework_prototype.svg)｜[节点来源](figures/DEMO_Fig1_framework_prototype.source.csv)｜[箭头关系](figures/DEMO_Fig1_framework_prototype.edges.csv)

**建议图注：** 图1 CROPGRO茄子参数化的机制框架及率定评价流程。（a）叶片同化物供给、营养生长、生殖分配上限、连续果实队列及采收的概念关系。XFINT和XFPHT控制生殖分配基准的动态比例；品种参数XFRT提供最大分配基准，实际分配还受环境修正、同化物供给及器官需求等制约。采收同时受果龄阈值XMAGE和输入采收安排约束。（b）从试验资料与敏感性筛选到分过程预率定、PEST++ IES联合更新及评价的研究流程。参考IES批次采用13个率定处理；C31确定性候选、留出评价及参考条件集合分别记录，不将其视为完全相同的参数对象。

**使用说明：** 这是关系示意，不是质量守恒的Sankey图；框宽和箭头宽不表示通量。Morris及分过程预率定不表示其历史全过程均已证明未参考留出数据。XMAGE不能画成单独决定自由采收日期的机制。框中的XFRT指输入品种参数；运行时同名有效分配量还包含环境修正。

## 图8 动态分配的固定参数前向对照

[采收节点折线PNG](figures/DEMO_Fig8_ablation_prototype.png)｜[PDF](figures/DEMO_Fig8_ablation_prototype.pdf)｜[SVG](figures/DEMO_Fig8_ablation_prototype.svg)｜[事件配对](figures/DEMO_Fig8_ablation_prototype.source.csv)｜[指标](figures/DEMO_Fig8_ablation_prototype.metrics.csv)｜[函数数据](figures/DEMO_Fig8_ablation_prototype.function_source.csv)

**建议图注：** 图8 动态生殖分配对C31模拟结果的影响。（a）按模型可读参数XFINT=0.3799、XFPHT=43.7构建的归一化潜在分配基准，随开花后光温时间线性增加至1；关闭方案将XFINT设为1。该曲线是参数化函数，不是日模拟中的实际同化物分配比例。（b,c）2025春和2026春W3N3代表处理的累计采收鲜重；黑边空心点为观测，蓝线为C31基线，橙线为关闭动态分配后的前向模拟，普通折线连接实际采收日的模拟输出。（d）两季各变量全处理nRMSE，灰线连接同一季节与变量的基线和关闭结果，圆点及三角分别表示两季。除关闭设置外，XMAGE及其他参数、环境与管理保持一致，未重新率定。采收采用与C31归档对齐的观测当天工作口径。

**使用说明：** 两季W3N3是跨季同等级、预先可解释的代表处理；（d）使用全部23处理，不由（b,c）外推。26SP W3N3的累计轨迹差异较小，必须保留，不能为突出机制另挑差异最大的处理。26SP LAI关闭后误差降低，在（d）明确保留。季末鲜重每处理只取最后一次累计值；累计与单次采收按全部事件评价，指标数量及定义不同。图中不应声称“动态分配对每个变量均有改善”。

**累计视觉备选：** [单调Hermite PNG](figures/DEMO_Fig8_ablation_prototype_smooth_visual.png)｜[PDF](figures/DEMO_Fig8_ablation_prototype_smooth_visual.pdf)｜[SVG](figures/DEMO_Fig8_ablation_prototype_smooth_visual.svg)。使用monoH.FC、经过采收节点且不下降，仅用于比较视觉表达；所有指标仍由原始节点计算。主建议保留普通采收节点折线。

## 图4 六变量1:1评价小样

[预览PNG](figures/DEMO_Fig4_validation_prototype.png)｜[PDF](figures/DEMO_Fig4_validation_prototype.pdf)｜[SVG](figures/DEMO_Fig4_validation_prototype.svg)｜[617个配对](figures/DEMO_Fig4_validation_prototype.source.csv)｜[分组指标](figures/DEMO_Fig4_validation_prototype.metrics.csv)

**建议图注：** 图4 C31确定性模拟与实测值的比较。（a–f）依次为LAI、叶干重、茎干重、单次采收鲜重、累计采收鲜重和季末鲜果产量。蓝色、橙色分别代表2025春、2026春；实心与空心分别表示率定处理和留出处理。灰线为1:1线，各面板横纵坐标采用相同范围、刻度及单位长度。每点对应一个处理的观测节点；n为有效配对数，分别为92、92、92、159、159和23。采收以观测当天归档输出配对；留出处理未进入所核对PST的正权重目标，但历史选模独立性尚未证明。

**使用说明：** 不以回归线代替1:1线。不同变量不强制共用0–80坐标。当前无参数区间，避免将参考IES分位区间混称为C31预测区间。完整RMSE、nRMSE、Bias、r²、NSE、d及Cal/留出拆分见阶段0统一性能表；重复时间点不当作独立田间重复。

## 复现与后续使用

冻结数据见[paper_data清单](paper_data/paper_data_manifest.json)，图件来源与环境版本见[渲染清单](figures/figure_manifest.json)，各图另有同名前缀的`figure_manifest.json`。Python只做读取、核对和冻结，R是唯一论文图渲染器；没有另建Python绘图实现。

本轮完成阶段0及阶段1。阶段2再用同一口径完成其他主图、三张主表、141成员集合图及指标文字；阶段3才在Word副本统一编号与排版。现在不把样板编号直接替换进原稿。
'''
    (OUT / '阶段1图注与使用说明.md').write_text(captions, encoding='utf-8')
    readme = '''# 论文图表重构：阶段0与阶段1交付

日期：2026-10-31。沿用C31，原Word、原始运行及已有正式图件未改。

- [阶段0：核对结果与统一口径](阶段0核对与统一口径.md)
- [阶段1：三张样板图、图注与使用说明](阶段1图注与使用说明.md)
- [现稿数值与口径对账CSV](现稿数值与口径对账.csv)
- [现稿参数表逐项对账CSV](现稿参数表逐项对账.csv)及[表5逐项对账CSV](现稿表5逐项对账.csv)
- [核心参数核对CSV](核心参数核对表.csv)
- [C31同日统一指标CSV](C31同日性能统一表.csv)
- [动态分配消融指标CSV](动态分配消融指标.csv)
- [阶段0机器核验](stage0_verification.json)及[最终验收](final_verification.json)

样板采用真实归档数据，但科学状态未提升。原模板默认值、历史选模独立性、采收读出规则及田间管理量一致性仍有明确未闭合项，详见阶段0报告。
'''
    (OUT / 'README.md').write_text(readme, encoding='utf-8')
    assert receipt['source_files_unchanged']


if __name__ == '__main__':
    main()
