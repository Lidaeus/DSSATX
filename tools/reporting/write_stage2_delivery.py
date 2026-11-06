"""Delivery index, captions, and review text from the frozen stage-2 evidence."""
from pathlib import Path
import csv
import html
import json
import hashlib
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'workspace/reviews/paper_stage2_20261031'
B=OUT/'paper_data'

FIGURES=[
 ('Fig2','两春气象与管理','Fig2_environment_management',
  '图2 两春C31运行所用的日尺度气象与灌溉施氮管理。两列分别为25SP和26SP，各行依次为最高与最低气温、太阳辐射、灌溉事件和施氮事件。红、蓝线分别为最高和最低气温；灌溉点形表示水分水平，施氮颜色表示氮水平。管理量来自实际归档FileX，基肥事件保留在真实定植前日期；N0不施氮，CK为独立对照。气象范围由定植日至最后一次实测采收确定，管理事件按实际输入保留。'),
 ('Fig3','敏感性与参考集合更新','Fig3_sensitivity_ensemble_update',
  '图3 历史双春参数筛选及参考IES集合更新。（a）25SP和26SP历史Morris筛选域中各过程内归一化的敏感性份额。各参数先在同一季节、过程和随机种子内计算份额，再对三个种子取均值；展示按全部所示过程与两季均值选出的前12项。一般遗传域和水氮响应域分别保留，不能将色块解释为跨原始输出单位的μ*直接比较或方差贡献率。（b）09/27参考IES八项参数的初始与最终2.5%–97.5%分位区间及中位数，横轴按各自实际PST工作域归一化。初始199、最终141个非base成员；区间不是C31确定性参数值或完整预测区间。'),
 ('Fig4','六变量一比一评价','Fig4_multivariable_performance',
  '图4 C31确定性模拟与实测值的比较。（a–f）依次为LAI、叶干重、茎干重、单次采收鲜重、累计采收鲜重及季末鲜果产量。蓝色与橙色分别表示25SP和26SP，实心与空心分别表示率定处理和留出处理。灰线为1:1线，各面板横纵轴范围、刻度和单位长度相同。n分别为92、92、92、159、159和23，表示有效配对数。采收采用同日归档读出；留出处理未进入所核对PST的正权重目标，历史选模独立性尚未证明。'),
 ('Fig5','冠层与营养器官动态','Fig5_growth_dynamics',
  '图5 两春代表处理的LAI、叶干重和茎干重动态。上、下行分别为25SP和26SP，各列依次为LAI、叶干重和茎干重。每季预先选定W3N3、W1N0及留出W1N1，选择依据为环境梯度与评价角色，未按拟合优劣挑选。实线来自真实日模拟轨迹，点为观测；氮水平用颜色、水水平用点形表示。误差棒仅在可追溯田间重复SD、重复数及节点匹配时绘制SE=SD/√n，不使用最小CV调整、插补或传播误差。相同变量两季共用纵轴范围。'),
 ('Fig6','持续采收累计与事件量','Fig6_harvest_dynamics',
  '图6 两春代表处理的持续采收模拟。四列分别为25SP W3N3、25SP W1N1、26SP W3N3及26SP W1N1；W1N1在两季均为留出处理。上行为累计采收鲜重，点为实测，普通折线连接真实采收日的模拟值；下行为单次采收鲜重，实心点为实测、空心点为模拟，竖线辅助标识采收事件。氮水平用颜色、水水平用点形表示。所有采收量采用相同观测当天读出；单次采收不连续平滑。'),
 ('Fig7','水氮响应曲线','Fig7_water_nitrogen_response',
  '图7 两春不同水氮处理的季末鲜果产量响应。两行分别为25SP和26SP，三列分别为W1、W2和W3。实心点及黑线表示实测，空心点及灰线表示模拟，同一处理的两值位于相同横坐标并用浅灰竖线配对。氮水平用颜色、水水平用点形表示，同一季节三面板共用纵轴范围，纵轴依据数据范围截取。25SP W2缺N1和N2，因此不补点、不跨缺口连线；CK不并入水分梯度。'),
 ('Fig8','动态分配固定参数前向对照','Fig8_partition_forward_comparison',
  '图8 动态分配参数化及固定参数前向对照，仅保留原设计（a）和（d）。（a）按模型可读XFINT=0.3799、XFPHT=43.7计算的归一化潜在生殖分配基准及XFINT=1的恒定基准；此为参数化函数，不是日模拟中的实际分配比例。（d）两季各变量全处理nRMSE，蓝色、橙色分别为C31基线和由C31直接关闭动态增幅的前向结果，圆点、三角分别表示25SP和26SP，灰线连接同一季节和变量。其他参数包括XMAGE保持不变。关闭方案没有重新率定，本图不作为“无动态分配模型经过最优率定后的性能”证据；正式消融应分别率定两种模型，本轮未重跑。'),
 ('Fig6视觉备选','累计单调视觉备选','Fig6_harvest_dynamics_smooth_visual',
  '图6累计部分的单调Hermite视觉备选。对同一组采收日模拟累计节点采用monoH.FC插值，曲线通过原节点且不下降，实测点与单次采收部分不变。插值仅用于视觉表达，不进入RMSE、nRMSE、NSE、d或任何目标函数。主建议采用普通采收节点折线版。'),
 ('补充气象比较','参考仪表板结构的气象比较','FigS_weather_comparison',
  '补充图 两春气象的日热条带及共同DAP窗口差值。上行依次为最高气温、最低气温和太阳辐射，色标在两季内一致，灰色为作物期外的已有数据、空白为无数据，红虚线为定植日和最后一次实测采收日。下行柱表示26SP−25SP逐日差，实线为完整7日居中滑动均值，点线为两季共同DAP窗口的平均差。沿用参考仪表板的比较思路与色系，实际数据分别来自C31所用XXLI2502与XXQL2601天气文件；不绘无直接观测的VPD。'),
 ('补充密度','十六项活动参数集合密度','FigS_parameter_density_141',
  '补充图 09/27参考IES的16项活动参数最终集合密度。初始199、最终141个非base成员；灰带为经验初始集合2.5%–97.5%分位区间，灰虚线与红实线分别为初始和最终中位数，蓝色为最终集合核密度，各面板密度峰值独立归一化。固定THRSH、XFINT和XFPHT不进入本图；KCAN保留全诊断，其前向响应已确认非零但很弱。核密度及收缩不单独证明高敏感或可辨识。'),
 ('补充相关','上三角秩相关','FigS_parameter_correlation_141',
  '补充图 与密度图相同16项活动参数在141个非base最终成员中的Spearman秩相关。只显示上三角，参数名水平写于对角线，色标固定−1至1。该结果描述当前集合的两两关联，不能仅由多数系数较小推出参数相互独立、异参同效弱或模型可辨识。'),
 ('补充水氮差值','施氮及灌溉绝对增产对照','FigS_management_contrasts',
  '补充图 施氮和灌溉增产的绝对差值。左侧比较各水层N3−N0，右侧比较同氮水平W2−W1或W3−W1；只使用实际存在的配对组合。实心点为实测差值、空心点为模拟差值，灰线连接同一对比，竖点线为零。单位均为t ha⁻¹，不计算以接近零观测为分母的比例，也不将处理边际分位数直接相减构造差值区间。')
]

def main():
    audit_paths = [
        'docs/archive/dssat_modules/crop_phenology/26SP_0629期LAI补齐方案与审计_20260831.md',
        'tools/experiments/build_refreshed_observations_20260917.py',
    ]
    (OUT/'supplemental_source_hashes.json').write_text(json.dumps({p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in audit_paths}, ensure_ascii=False, indent=2), encoding='utf-8')
    captions=['# 阶段2图注与表注','', '图1按用户要求取消。主图沿用设计编号2–8供核对，正式连续编号和正文交叉引用留到阶段3。补充图名为稳定主题ID，尚未指定最终S编号。全部为真实归档数据审阅版，科学状态未提升。','']
    rows=[]
    for identifier,title,stem,caption in FIGURES:
        if identifier in ['Fig4','Fig5','Fig8']:
            caption += ' 26SP DAP105的12个LAI评价值由叶干重与LAI比值关系推算，图4/图5用×标识，表1加*；含LAI的统一指标保留原全节点口径。'
        base='figures/DEMO_'+stem
        captions += ['## '+identifier+' '+title,'',f'[PNG]({base}.png)｜[PDF]({base}.pdf)｜[SVG]({base}.svg)｜[数据]({base}.source.csv)','',caption,'']
        rows.append(dict(design_id=identifier,title_zh=title,stem='DEMO_'+stem,caption_zh=caption))
    captions += ['## 表1 两春试验处理及评价数据范围','',
      '总灌水量和总施氮量为C31实际FileX配置，暂不等同于已核实的田间实际总量。Ep比例按原试验设计说明列示；CK独立，不归入水氮矩阵。n为处理×时点或事件的有效配对数，季末每处理1个值。率定13处理、留出10处理按实际PST核定。','',
      '## 表2 关键模型参数及C31确定性参数化结果','',
      '共24项，按物候、冠层、生殖采收和水氮过程列示。实际工作域来自09/27PST，C31候选值来自确定性候选CSV；两者与集合中位数不是同一对象。原番茄默认值尚未建立可信原始基线，统一留空，不计算变化百分比。模型可读关键参数精度另说明；固定项不进入本轮分布与相关分析。SENDAY按源码为水分胁迫相关衰老参数。','',
      '## 表3 C31两春模拟性能','',
      '两季×率定/留出×六变量24行，另列两春合并季末全部/率定/留出3行，共27行。保留n、RMSE、nRMSE、Bias、r²、NSE和d；nRMSE=100×RMSE/实测均值，Bias=模拟−实测。采收为同日工作口径；重复时间点不视为独立田间重复。留出不等于已经证明历史选模独立。','']
    captions += ['## LAI观测来源补充说明','',
      '26SP的LAI有12个值来自SLA关系推算（2026-06-29，DAP105），图4和图5用×叠加标识，并非直接测量。图4的LAI n=92和表3的26SP LAI n=48保留原C31全部评价节点，其中26SP直接测量为36个点。图8的LAI指标也沿用此口径。另提供[仅直接测量的LAI指标](paper_data/LAI_direct_measurement_metrics.csv)：26SP全部/率定/留出分别n=36/21/15，nRMSE=41.46%/37.31%/46.72%。推算点无实测SE，图中不绘其误差棒。','']
    (OUT/'阶段2图注与表注.md').write_text('\n'.join(captions),encoding='utf-8')
    with (OUT/'caption_registry.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    m=pd.read_csv(B/'performance_metrics.csv');contrasts=pd.read_csv(B/'water_nitrogen_contrasts.csv')
    stats=pd.read_csv(B/'water_nitrogen_contrast_summary.csv');weather=pd.read_csv(B/'weather_crop_summary.csv')
    dates=pd.read_csv(B/'season_dates.csv');diff=pd.read_csv(B/'weather_daily_difference.csv')
    text='''# 阶段2完成情况与结果口径

## 本轮交付

按用户最新要求完成七张主图（设计图2–8）、累计视觉备选和四张配套补充图，共12套PDF/SVG/600 dpi PNG，并附原始节点、日轨迹、指标及每图清单。图1本轮不绘制，旧阶段1文件只作为历史记录保留。三张主表提供可编辑Word和原精度CSV。

图8已删除原b、c累计轨迹面板，仅保留a与d。现有关闭方案确实以C31参数组为起点，将XFINT设为1使动态增幅失效，其他参数包括XMAGE不变；它是固定参数前向对照。本轮没有重新率定任何关闭模型，也没有运行DSSAT/PEST。正式消融仍需分别率定两种结构，并采用一致的预算、目标与评价处理；这一点同时写入图注和数据清单。

## 字体与版式

英文、数字及拉丁参数名使用Times New Roman，中文使用宋体（SimSun）。混排标签显式按字符分配字体，不依赖系统自动选取中文回退字体；PDF核对嵌入字体，SVG保留可编辑文本，PNG由相同图形对象导出。主图统一183 mm宽，保留7 pt正文及不超过170 mm的高度。Word按西文/东亚字体分别设置，主表为4页横向可编辑文档。

## 气象与管理

参考了用户指定的气象仪表板及`tools/reporting/plot_weather_comparison.py`。原脚本的默认数据路径在当前工作区已不存在，且默认从一个跨年天气文件读取两季；本轮没有直接重跑该Python论文图脚本，而是复用其比较思路和色系，在R中重建图形。新图分别读取C31归档25SP的XXLI2502.WTH和26SP的XXQL2601.WTH，管理事件直接由归档FileX提取；提取事件的灌溉与施氮总量已和阶段0逐处理总量核对一致。

作物期定义为定植日至最后一次实测采收，25SP为2025-03-16至2025-07-11（DAP 0–117，118日），26SP为2026-03-16至2026-07-17（DAP 0–123，124日）。主图2列日气象和实际灌溉施氮事件，配套气象图列日热条带及共同DAP窗口差值。日均相对湿度不用于伪造实测VPD，亦未编造修剪日期。

原始天气记录、每个管理事件、作物期统计及共同DAP差值均进入冻结CSV。整季均值与共同DAP窗口均值的分母不同，不能混写。

## 敏感性与集合

图3a来自历史双春Morris筛选，采用原冻结资料中的一般遗传域和水氮响应域，以各过程内归一化份额表达。三个种子平均后按两季和所示过程的均值选前12项；该展示规则只用于图形选取，不将各域原始μ*相加。历史筛选域不是C31附近的局部敏感性，更不是09/27率定工作域。本轮保留资料的science_pending来源状态。

2026-10-30新增的单季86参数30轨迹试验晚于C31，其原完整设计未全部通过，因此不替换为“生成C31所用的双春筛选”。该后来试验原始结果保留，本轮没有删除或改写。

图3b及密度/相关补图统一为09/27参考IES：初始199、最终141个非base成员。THRSH、XFINT、XFPHT在该批次固定，剔除其分布和相关；历史SA中XFINT可变与本轮固定并不矛盾。KCAN依据既有非零但弱的前向响应保留完整诊断，不列为主图核心高敏感参数。

## 代表处理与误差

图5每季按预设条件选择W3N3、W1N0和留出W1N1，覆盖高投入、低投入及留出角色；图6选择两季W3N3和W1N1共四列。每日LAI、叶干重、茎干重来自实际PlantGro轨迹，未用少量观测日期上的模拟值平滑伪造日曲线。

594个过程和采收配对中，245个生长配对能匹配真实重复SD和n_rep并计算SE。原始重复均值与FileA观测只存在归档舍入差异（LAI≤0.0005，干重≤0.5 kg ha⁻¹），已逐键核对。只在满足这些条件的选定节点画SE；最小CV调整、插补和鲜干比/累计方差传播不作为田间重复误差棒。

图6普通折线与monoH.FC备选成对保留，单次采收仍为事件点。插值不进入指标。图7同处理实测和模拟同横坐标，分别连接同水层连续存在的氮水平；25SP W2的缺失氮水平不补点、不跨缺口连线。

## 可用于结果段的水氮响应文字

在两春试验条件下，模型总体再现了施氮端点增产方向，但不同水层的响应幅度仍有偏差。以N3相对N0的季末鲜果产量增量评价，25SP三个水层的实测增产为4.75–12.32 t ha⁻¹，模拟为7.94–10.45 t ha⁻¹；26SP分别为5.79–15.33和8.29–12.05 t ha⁻¹。两季各三个端点对比的方向均一致，增量RMSE分别为3.82和4.10 t ha⁻¹。模型在W3下均高估施氮端点增量，且26SP W2与W3的模拟高氮响应趋于平台，与实测的局部下降或更明显处理差异并不完全一致（图7及配套差值图）。因此，端点增产为正不能表述为全部相邻施氮梯度均被准确重现。

同一氮水平下的水分增产对比显示，25SP六个有效W2−W1或W3−W1组合的实测与模拟方向全部一致，但模型总体高估增产幅度，差值RMSE为6.60 t ha⁻¹。26SP八个组合中七个方向一致（87.5%），差值RMSE为4.78 t ha⁻¹；其中N3下W3−W1实测为−0.232 t ha⁻¹，而模拟为+2.272 t ha⁻¹。该例外说明模型未完全捕捉高水高氮条件下的弱负响应。由于25SP W2缺少N1和N2，相关曲线保持断开，CK独立处理。上述结果支持对总体方向与响应幅度分别评价，尚不能仅由季末产量误差较小推出水氮优化能力已获充分验证。

## 可用于结果段的相关性文字

在排除base后的141个参考IES最终成员中，16项活动参数的两两Spearman相关多数接近零。绝对关联最大的三对为FL-SD与XMAGE（ρ=0.493）、FL-SD与XFRT（ρ=−0.377），以及PODUR与SFDUR（ρ=0.368）。这些结果表明当前集合中发育时序与生殖分配参数存在一定关联结构；弱两两相关不能证明参数独立，也不能据此断言异参同效总体较弱。该集合描述与C31确定性候选分别报告。

## 阶段边界

阶段2的图表制作与相应数值口径已完成。科学状态仍为audit_review_unvalidated；原番茄默认值、历史选模独立性、日内采收读出与可执行版本对应、实际管理量与田间原记录一致性，以及完整预测不确定性仍按阶段0缺口记录。表2原默认值留空，图4/表3使用“留出”而不称未经证明的独立盲验证。

原10.6版Word未改，已有正式图件及模型输入未覆盖。阶段3才统一最终连续编号、正文引用及Word副本排版。本轮不因制图提升数据科学状态。
'''
    text += '''

## 本轮新增的LAI来源核对

26SP在DAP105（2026-06-29）的12个LAI值被归档误差来源表标记为imputed_sla_ratio_20260831。它们由SLA关系推算，不应与直接田间测量混称。为保持与C31归档及既有指标可比，图4、表3、图8仍保留全部节点的原口径，但图4/图5用×单独标识，表1加*，并明确表注。推算点不绘实测SE。

剔除12个推算点后，26SP直接测量LAI为36对，RMSE=0.6261、nRMSE=41.46%；率定21对nRMSE=37.31%，留出15对nRMSE=46.72%。这些结果另列于LAI_direct_measurement_metrics.csv，不替换为“只修改样本数但保留原指标”的混合口径。原48节点nRMSE=35.81%含推算值，解释时须明确其评价目标组成。
'''
    text += '\n来源依据为[2026-08-31 LAI补齐方案与审计](../../../docs/archive/dssat_modules/crop_phenology/26SP_0629期LAI补齐方案与审计_20260831.md)及归档观测构建代码。原审计明确记载该日未测LAI，采用LAI=叶干重/18.52补齐；因此这些LAI推算值与叶干重不是独立观测证据。补充来源文件校验值见[supplemental_source_hashes.json](supplemental_source_hashes.json)。\n'
    (OUT/'阶段2完成情况与结果口径.md').write_text(text,encoding='utf-8')
    # A local review gallery, no external publication or service dependency.
    cards=[]
    for identifier,title,stem,caption in FIGURES:
        base='figures/DEMO_'+stem
        caption=next(r['caption_zh'] for r in rows if r['design_id']==identifier)
        note=''
        cards.append(f'<section id="{html.escape(stem)}"><h2>{html.escape(identifier+" "+title)}</h2><p><a href="{base}.pdf">PDF</a> · <a href="{base}.svg">SVG</a> · <a href="{base}.png">600 dpi PNG</a> · <a href="{base}.source.csv">源数据</a></p><a href="{base}.png"><img loading="lazy" src="{base}.png" alt="{html.escape(title)}"></a><p>{html.escape(caption+note)}</p></section>')
    gallery='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>C31论文阶段2图表总览</title><style>body{max-width:1150px;margin:30px auto;padding:0 24px;color:#202830;background:#fff;font-family:"Times New Roman","SimSun",serif;line-height:1.65}h1{font-size:27px}h2{font-size:22px}a{color:#155e88}img{display:block;width:100%;height:auto}section{margin:38px 0 64px;border-top:1px solid #d6dde2;padding-top:18px}p{font-size:17px}nav a{margin-right:16px}</style><h1>C31论文阶段2图表总览</h1><p>英文与数字 Times New Roman，中文宋体；图1取消，图8只保留a、d。关闭方案未重新率定。本页为真实归档数据审阅版，保留未完成科学审核标识。</p><nav><a href="tables/C31两春图表阶段2主表.docx">三张可编辑主表</a><a href="阶段2图注与表注.md">图注表注</a><a href="阶段2完成情况与结果口径.md">结果文字与口径</a><a href="paper_data/paper_data_manifest.json">数据来源清单</a></nav>'''+''.join(cards)+'</html>'
    (OUT/'图表总览.html').write_text(gallery,encoding='utf-8')
    lines=['# C31论文图表阶段2交付','','本轮完成最新字体要求、取消图1、图8仅保留a/d，以及阶段2量化图表。未重新率定关闭方案，原稿和已有正式图件未改。','',
      '- [全部图表预览](图表总览.html)','- [三张可编辑主表](tables/C31两春图表阶段2主表.docx)',
      '- [完整图注与表注](阶段2图注与表注.md)','- [完成情况与可用结果文字](阶段2完成情况与结果口径.md)',
      '- [冻结数据及来源清单](paper_data/paper_data_manifest.json)','- [数据核验](data_verification.json)及[最终验收](final_verification.json)','','## 七张主图','']
    for identifier,title,stem,_ in FIGURES[:7]:lines.append(f'- [{identifier} {title}](figures/DEMO_{stem}.png)')
    lines += ['','另附累计单调视觉备选、气象比较、141成员密度与上三角相关，以及水氮绝对差值图。每图有PDF/SVG/PNG、源CSV及独立清单。','',
      '三张主表分别含23个实际处理、24项关键参数、27行分季/分角色性能指标；精度CSV与排版CSV均位于tables目录。主文Word的连续编号和交叉引用留至阶段3。','',
      '科学状态保留audit_review_unvalidated。原番茄默认值尚未核实，表2留空；“留出”不自动等同于已证明历史选模独立。26SP的12个LAI推算值已单独标记，并另列仅直接测量的LAI指标。']
    (OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(OUT/'图表总览.html')

if __name__=='__main__':main()
