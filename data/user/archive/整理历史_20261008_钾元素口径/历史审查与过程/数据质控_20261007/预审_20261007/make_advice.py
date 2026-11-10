from pathlib import Path
import json,csv,collections,statistics,sys,hashlib
sys.stdout.reconfigure(encoding='utf8')
OUT=Path(r'D:\三季节数据汇总\数据质控_20261007\预审_20261007')
d=json.loads((OUT/'预审上下文.json').read_text(encoding='utf8'))
keep='倾向保留原值'; replace='核验后倾向均值替代'; verify='优先核验，暂保留'
# Each entry is a contextual scientific judgment, not an automatic threshold rule.
quality25={
'H6':(replace,'Vc单独升高约71%，其余两次同为151.05。糖、蛋白、固形物未同幅升高。优先核对滴定量、空白及倍数；证实技术误差后，151.05更能代表其余重复。高氮不必须低Vc，此处不是按排序直接判错。'),
'H32':(keep,'低Vc可反映果龄或个体差异，糖和固形物没有对应测量矛盾。替代会把W1N2抬成此水处理下最高Vc，但不能为了得到“中氮最佳”而填补；先保留、核滴定记录。'),
'H37':(replace,'Vc单项偏高约47%，糖、蛋白和固形物只偏差约1%–6%。其余两次较接近，优先核查滴定终点/样品倍数；证实单项测定误差后可用170.199。当前数值仍在该日实测范围内，未确认错误。'),
'H40':(replace,'Vc高出其余两次约55%，糖仅高约16%、蛋白反低约8%。优先复核Vc原记录。替代可减少单株对W1N0均值的拉动，但零氮仍能合成Vc；必须证实技术误差才采用166.3692。'),
'I29':(keep,'同株Vc约低49%，蛋白低32%，多个营养品质指标共同偏低；高氮/亏水下的果实品质差异或果龄差异可解释。仅抬高蛋白会割裂该样品特征，暂保留并核制样记录。'),
'H78':(keep,'偏差30.05%刚超过旧提示线，蛋白同向偏高约23%，可解释为样果差异。该行三项吸光度是已确认填补，不能作为“其他指标一致”的独立旁证。没有依据把Vc压到均值。'),
'I47':(keep,'蛋白低37%且Vc低约25%，两个指标同向。该行酚/黄酮/花青素为填补，不当作实测旁证。更可能是样果综合差异之一；仅为使N2高于其他处理而替代不合适。'),
'I73':(keep,'蛋白偏高且Vc、总酚、黄酮也偏高，保留能保留该样果的营养品质特征。花青素反向不必然矛盾，色素与其他品质可分别响应发育阶段；不以平均值削平高值。'),
'M45':(keep,'低花青素同时伴随低Vc、蛋白、总酚及黄酮，水分略高。多指标共同变化提示样果/制样差异，不能仅把花青素抬高来修复处理曲线。核取样成熟度与提取记录，原值先保留。'),
'M52':(keep,'较高花青素伴随较高总酚、黄酮及Vc，存在同株共同变化。该指标是吸光度，不能用文献浓度阈值判错。保留并核取皮/匀浆口径。'),
'M54':(verify,'花青素单独偏低43%，但蛋白、总酚、黄酮不低。成熟度和取皮比例差异也可产生这种组合。优先核花青素提取、空白和测量波长；没有原记录证误前，不用0.2175硬性替代。'),
'M73':(keep,'该样果蛋白、Vc、总酚/黄酮高而花青素低。发育阶段下花青素与总酚可不同步，因此不能把“其他品质高”当成该值错误的证据。先保留，核取样和色素测定条件。')}
quality26={
'I50':(keep,'虽比其余两次高34%，保留后W3N3仍是同日Vc低值处理，并未破坏高氮品质可能受抑制的解释。两次接近不足以证第三次错；优先保留，复核滴定/原计算记录。'),
'I61':(keep,'W3N2的较高Vc可以是真实果样差异。原值并非同日Vc最大值，替代虽使重复更整齐，却没有独立错误证据。可核原记录并做有/无该值的结果比较。'),
'I68':(keep,'较高Vc伴随蛋白偏高约22%，具备样果营养差异的旁证。保留后W3N1均值仍低于W3N2，不必为固定施氮排序下调。优先核Vc测定而不直接替代。'),
'F114':(keep,'硬度较高，且同果样含水率更低、糖和固形物略高，存在组织状态差异的解释。两条规则对应同一位置，不能作为两份独立证据。核测量部位、果龄及仪器重复，先保留。')}
npk={
'I149':(keep,'K偏高且P同向较高，N略低；组织元素无需同幅变化。保留后的处理均值位于同日叶K实测处理范围中，不能按施N顺序强制下调K。'),
'I160':(replace,'叶K单项低约43%，N、P较接近其余重复；其余两次K的CV仅约3.8%。优先复核火焰读数、校准、稀释倍数和转录。若证实K测定误差，31.6389比低值更能代表其余重复；未证误不改。'),
'H197':(keep,'P偏差30.06%仅略超旧提示线，N、K也各低约14%–15%。存在样叶营养整体差异的解释；替代会进一步扩大该处理叶P高值，未证明更符合一般规律。'),
'I188':(keep,'K偏高同时N、P较高，可能是样叶营养特征。低水高氮下K不要求唯一方向；仅因均值替代后较平滑，不能删去较高重复。'),
'I211':(keep,'偏差30.24%处于旧提示线附近，K高而P低提示元素配比差异。P与K不是同一指标，不能强制同向。当前值在同日叶K实测范围内，优先保留。'),
'H241':(keep,'P与K同时低约30%–31%，N也略低，可反映样叶吸收/分配差异。不存在固定P随施N递增的约束；先保留，核取叶部位和样品制备。'),
'H245':(keep,'同株P、K均偏高约37%–38%，N偏高15%，具有共同营养状态变化的解释。分别以均值替代会消除真实样株特征；核样品重量但不直接替代。'),
'I245':(keep,'与H245为同株，P、K同向高、N也高；属于可能的样株整体差异，不是独立的必然录错。先保留，核同株称样和提取过程。'),
'G284':(keep,'N0样株N、P、K共同偏低，较低N本身符合不施氮条件下可能的样株差异。用均值会抬至约29.23，与该日多数施氮处理相当或更高，不能认为一定更合理。'),
'H284':(keep,'与G284同株，P较低而N/K也低；存在样株整体差异。P不是施N量的单调函数，优先保留并一并核称样/消解记录。'),
'G308':(verify,'该茎样N/P/K均低约39%–42%，比例接近，可能涉及共用称样量或稀释倍数，也可能是真实样株。另有W1N2整组较低，需先核样品编号/计算因子，不能直接把本样逐元素抬到均值。'),
'G315':(keep,'N偏高伴随P、K同向高；未施N仍有土壤供N，组织N不要求低于每个施N重复。较高N0单株可真实存在，不按N0应为0或固定递增关系替代。'),
'H308':(verify,'与G308/I308同株，三个元素浓度共同降低约四成。先整样核编号、干基称样量、定容/稀释倍数；若有计算错误应按原记录重算，而非先只填P均值。'),
'I308':(verify,'与G308/H308同株，三元素共同低约四成。该样K与同日W1N2低值组接近，需核编号及共用分母。原记录未核定前保留，不用59.1008自动替代。'),
'G334':(keep,'偏差31.13%刚过旧提示线，其余P/K也略高。较高N样株可以是真实；替代会让N3浓度更低，反而不能普遍宣称更符合“施N提高组织N”。'),
'G343':(verify,'该茎样N/P/K同时偏高约41%/54%/37%。可能是较富营养样株，也可能是共用质量/倍数问题。先整样核查，不只因其抬高W1N2就逐元素均值化。'),
'G361':(keep,'偏差31.02%接近旧提示线；N0浓度不是0，K同向高而P较低可来自元素分配。没有同株跨期追踪证据，不因跨期或施N排序不平滑替代。'),
'H343':(verify,'与G343/I343同株；P高54%同时N、K均高。核共用称样及倍数、样品组织纯度，确认计算问题再按原始记录重算。均值只可作证误后的有标记替代。'),
'H355':(verify,'同茎样P高约45%、K低约45%，N基本接近其余重复，不能由同一个等比例因子解释。优先核P、K分别的测定与样品编号；二者均值化会强制消去元素配比差异，暂保留。'),
'H360':(keep,'P高约38%，K同向较高，N接近其余重复。零氮处理不等于低磷或无磷；保留后的处理均值未超同日茎P范围，优先保留。'),
'I335':(keep,'K偏高同时N、P也高，提示可能的样株营养差异；保留后处理K均值也非同日最高。没有依据要求中氮K值被压低，暂保留。'),
'I343':(verify,'与G343/H343同株，N/P/K共同偏高。核取样组织、称样量及共用稀释倍数，不能把技术重复一致等同于其他样株能替代本株。'),
'I347':(keep,'K高而N接近、P偏低，可属于元素选择性吸收或分配差异，不是定律矛盾。核K仪器读数较有价值，但没有证据支持按施N量强制下调K。'),
'I355':(verify,'与H355同株，K低45%与P高45%反向，优先排查分别测定、转录或样品编号；也可能是真实配比。原记录未核前保留两项，不先各换均值。'),
'I358':(keep,'K偏差31.44%接近旧提示线，N和P也高约19%，共同偏高支持样株差异解释。N0仍可吸收K；替代不天然更符合施N响应。'),
'I359':(keep,'K低31%同时N、P也低，存在样株整体营养差异。亏水下吸收/分配变化可真实；当前值不是不可实现值，优先保留。'),
'G380':(keep,'N低31%伴随P/K低，可反映样株状态。替代会令同水下N0→N3排序更整齐，但该表测的是浓度而非总吸收量，不能为了恢复单调关系而改该株。'),
'H369':(keep,'P低34%，N/K也低，存在同株共同变化；并非只有P异常。先保留并核样段/称样口径，处理响应没有唯一P方向。'),
'H386':(keep,'N0样株P高且N/K也同向高，整体富集可真实存在。零氮不限制P必须低；不能仅为降低处理均值把样株变成另外两株的平均。'),
'H390':(keep,'P偏差30.86%接近旧提示线，N接近、K略低，可属于元素差异。先核比色原值，单凭30%提示不足以用均值替代。'),
'H394':(keep,'P偏高且N同向高、K略高，具备样株共同变化旁证。N0处理不等于P0，当前浓度在同日实测范围内，保留较有依据。'),
'I371':(verify,'该茎样当前N/P/K均高约42%/58%/53%，可能涉及共用称样或倍数，不能只下调K。优先同时核G371/H371/I371原记录；未列入旧筛查的伴随指标仅作为旁证，不扩大本次改值。'),
'I374':(keep,'K低31.76%略过旧提示线，N接近、P稍低，元素不要求同幅变化。优先保留，若火焰读数/倍数另有证误再考虑有标记的替代。')}
sources=[
{'id':'L1','title':'Zhou等，2023，茄子水氮优化研究','url':'https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2023.1211122/full','use':'其田间试验部分品质以中氮和轻度亏水较优；论文W编号与本项目含义不同，不能直接照搬W1/W2排序。'},
{'id':'L2','title':'Integrated Effects of Water and Nitrogen Coupling，2025','url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC11768376/','use':'冷旱区试验蛋白/Vc响应存在水氮交互及中等投入较优的情形，不证明每株或每季必须按同一顺序。'},
{'id':'L3','title':'Ji等，2022，日光温室茄子灌溉研究','url':'https://www.frontiersin.org/journals/microbiology/articles/10.3389/fmicb.2022.981288/full','use':'该温室试验不同灌量Vc未显著不同，说明不能用灌量固定排序单独判错。'},
{'id':'L4','title':'Scrapped but not neglected，2021，茄子果皮发育与酚类','url':'https://www.sciencedirect.com/science/article/pii/S098194282100440X','use':'其果皮发育研究中花青素与总酚变化幅度不一致；用于解释指标可不同步，不将其浓度值直接作为本项目吸光度阈值。'},
{'id':'L5','title':'Characterization and QTL identification under two N levels，2023','url':'https://www.sciopen.com/article/10.1016/j.hpj.2022.08.003','use':'茄子两个N水平下测量叶/果N及果实酚类等性状；基因型试验背景与本项目不同，不能据它给单个茎/叶样品设统一排序。'},
{'id':'L6','title':'Kirnak等，2002，亏水与茄子叶N/P/K','url':'https://uhra.herts.ac.uk/id/eprint/23360/','use':'叶养分对不同强度水分处理响应并非同一方向；仅有机构摘要可读，不作为组织浓度硬阈值或本项目W梯度的校正目标。'},
{'id':'L7','title':'NCES，A Study of Imputation Algorithms，2001','url':'https://nces.ed.gov/pubs2001/200117.pdf','use':'均值填补会压缩方差。全文打开受限，本次仅使用可检索的研究摘要/片段作为方法提示；本表同时列出替代对处理均值的实际影响。'}]
for c in d['cases']:
    f=Path(c['file']).name
    decision,reason=(quality25 if f.startswith('2025春品质') else quality26 if f=='2026春品质指标集.xlsx' else npk)[c['address']]
    assert c['current_value']==c['table_value'],(c['address'],'current source changed')
    peernote='；'.join(f'{a}={v:.6g}' for a,v in zip(c['peer_addresses'],c['peer_values']))
    c['decision']=decision;c['reason']=reason
    evidence=f"与其余{len(c['peer_values'])}个重复均值比{c['deviation']:+.2%}；其余重复CV={c['peer_cv']:.2%}。{reason}"
    before=[c['group_means'].get(c['w']+'N'+str(n)) for n in range(4)];after=list(before); ni=int(str(c['n'])[1:]);after[ni]=c['mean_after_replacement']
    sequence=lambda xs:' / '.join('未纳入' if x is None else f'{x:.4g}' for x in xs)
    response=f"本组均值{c['original_group_mean']:.6g}→{c['mean_after_replacement']:.6g}。同{c['w']}下N0→N3，保留：{sequence(before)}；替代：{sequence(after)}。仅本格替代，其余格不变；排序更整齐不证明错误。"
    if '花青素' in c['metric']:
        general='吸光度须同提取/空白/波长条件比较；指标可不同步，没有已核定的施水施N单调方向。';ids='L4'
    elif '硬度' in c['metric']:
        general='结合本样含水率与果龄核验；本项目未核定硬度的必然处理排序，也未核定统一绝对上限。';ids='L3'
    elif c['organ']:
        general='当前为组织浓度，不是养分总吸收量。按同日期同器官比较，不强制三个元素同向，也不将N0浓度视为0。';ids='L5、L6'
    else:
        general='品质对水氮有交互且可能非单调；论文处理定义与本项目不同，一般响应不能鉴定此株测定是否正确。';ids='L1、L2、L3'
    certainty='中等保留倾向；未证明无误' if decision==keep else '中等疑点；替代须先证误' if decision==replace else '原因未定；先查原记录'
    c['output']=[decision,evidence,c['peer_mean'],len(c['peer_values']),peernote,c['replacement_group_impact'],response,general,certainty,ids]
    c['relative_rank_comparison']=response
unique_counts=collections.Counter(c['decision'] for c in d['cases']);row_counts=collections.Counter({key:sum(len(c['audit_rows']) for c in d['cases'] if c['decision']==key) for key in unique_counts})
assert len(d['cases'])==49 and len(d['pending_rows'])==50
assert unique_counts=={keep:35,replace:4,verify:10},unique_counts
out={'headers':['预审建议','数据判断与核验事项','同处理其余均值（原单位）','其余可用重复数','其余重复位置与原值','替代后处理均值变化','处理响应比较（保留与替代）','一般规律及适用边界','建议确定性','依据编号'],'subtitle':'2026-10-07预审：50条待审记录/49个位置。新增S:AB列；用户已审167条不改。均值仅供证误后有标记替代，未改原测量。','cases':d['cases'],'sources':sources,'counts_unique':dict(unique_counts),'counts_rows':dict(row_counts),'pending_rows':d['pending_rows'],'already_reviewed_rows':d['reviewed_rows'],'audit_sha256':d['audit_sha256'],'source_sha256':d['source_sha256']}
(OUT/'逐项预审建议.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
with (OUT/'逐项预审建议.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['统计表行号','原文件','位置','日期','器官','处理','当前值']+out['headers'])
    for c in out['cases']:
        for r in c['audit_rows']:w.writerow([r,c['file'],c['address'],c['date'],c['organ'],c['w']+c['n'],c['current_value']]+c['output'])
four='\n'.join(f"| {Path(c['file']).name} | {c['address']} | {c['current_value']:.6g} | {c['peer_mean']:.6g} | {c['replacement_group_impact']:+.2%} |" for c in d['cases'] if c['decision']==replace)
allcases='\n'.join(f"| {','.join(map(str,c['audit_rows']))} | {Path(c['file']).name} | {c['address']} | {c['decision']} | {c['reason']} |" for c in d['cases'])
refs='\n'.join(f"- {s['id']}：[ {s['title']} ]({s['url']})。{s['use']}" for s in sources)
report=f'''# 品质与器官氮磷钾未审核记录预审

日期：2026-10-07。输入为当前源Excel和用户已审核的`更新数据核对与统计筛查.xlsx`。读取时164条“保留原值”、3条“已修正”，另50条“待人工核查”。本次只为这50条加建议，未修改原测量，也未替你完成最终人工审核。

50条对应49个位置：品质17条/16位置（F114重复触发两种规则），器官氮磷钾33条/33位置。这次器官候选实际都是2026春茎和叶，未有待审核的果实器官条目，不宣称已复核未列出的全部果实测量。

## 结论与操作

- 倾向保留：**35个位置/36条记录**。现有数值多在本项目相同日期的实测范围内，部分存在多个指标的同株共同变化；一般规律不足以证明错误。
- 核验后倾向同处理其余均值替代：**4个位置/4条记录**。优先复核仪器/滴定记录，只有证实技术或录入错误且无法恢复真实原值时，再用有标记的均值。不是已确认4个错误。
- 优先核验、暂保留：**10个位置/10条记录**。涉及整样NPK共同变化、P/K相反变化或吸光度取样条件不清，不能只把一个字段改到均值。

| 原文件 | 位置 | 当前值 | 同处理其余均值 | 替代对处理均值影响 |
|---|---|---:|---:|---:|
{four}

这里“同处理其余均值”严格限于**同季、同日期、同器官、同水氮组合、同指标**，排除候选本身及已确认填补项。当前每条均有另外2个可用生物学重复，不能把这个2值均值当作测量真值。既有的2025春弃用小区仍排除，未引入其他季或其他日期填补。

新建议在原统计表**S:AB**列。Q“处理状态”和R“处理决定”保留原样，已审行没有新增预审判断。重复定位F114两行建议相同；不是两份独立异常证据。表底部S225起列有依据编号及文献链接。新列可筛选“预审建议”，四个重点疑点仅供你最终核验。

## 为什么不以处理规律直接改测量

茄子田间水氮试验中存在中等氮和适度亏水下部分品质较高的情形（L1/L2），但日光温室试验也出现不同灌量下Vc不显著变化（L3）。这些处理定义、品种、环境与本项目不相同，因此不能把本项目W1机械等同论文W1，也不能把N2最高、所有浓度随N递增等当作校正目标。

本项目测量的是组织浓度，浓度与吸收量是不同量；仅凭施N量、同株N/P/K是否同方向或N0是否低于每个施N重复，不能识别测定错误。原有破坏性取样跨日期并非同一株，不把同号跨期变化视为同株异常。

花青素与总酚在果实发育中可不同步（L4）。该论文测果皮浓度，本项目记录吸光度，因此只借助其说明“不同指标不必同步”，不把其浓度范围用作本项目吸光度阈值。提取、空白、波长和取样部位记录尚缺，处理规律不能单独证实吸光度错误。

均值替代必然使重复更集中，不等于更真实；对这些候选，在仅另2个重复的情况下，用均值会人为压缩方差（方法来源L7）。表中的X列及Y列显示实际处理均值变化和施氮序列，仅用于结果敏感性判断，不按“哪个更平滑/更显著”选择数值。未进行显著性检验、未拟合目标响应曲线，所有倾向是预审判断。

## 重点整样核验

- 2026器官养分`G308/H308/I308`：N、P、K共同低约39%–42%，先查样品编号、称样量、定容和稀释倍数，确认有计算误差应由原记录重算。
- `G343/H343/I343`：三元素共同高约37%–54%；可能是样株特征，也可能是共用分母，不能先逐元素均值化。
- `I371`：当前对应样品G371/H371也高；这两项仅作为旁证，不新增最终改值或旧筛查行。
- `H355/I355`：同株P高/K低约45%，一个等比例因子不能解释，需要分别核测定和转录。
- 25春`M54`：花青素较低而其他品质不低，需要原取样及色素测定条件来判断，先保留。

## 所有位置的逐项判断

| 统计表行 | 原文件 | 位置 | 预审建议 | 具体判断 |
|---|---|---|---|---|
{allcases}

## 来源、局限与复核

直接数值依据是当前工作区三份Excel：25春品质、26春品质、26春茎叶果氮磷钾；其原值/缓存只读，单位沿用用户确认和表头，不用未确认的文献绝对范围进行跨单位筛除。预审上下文保存逐条两次对照、全处理均值和旁证数值。文献读取日为2026-10-07；论文原始网站或研究机构存档支持一般规律，无法证明本试验某样品称量或滴定错误。

{refs}

本次工作簿修订前备份保留全部人工决定。仅读取源Excel；未刷新外链、未替换任何品质/器官测量。后续若决定填补，须记录位置、原值、真实错误依据、替代来源及imputed标记；有真实原记录时优先恢复测量而非填平均。
'''
(OUT/'品质与器官养分预审说明.md').write_text(report,encoding='utf8')
nb={'cells':[{'cell_type':'markdown','metadata':{},'source':['# 2026-10-07预审的数值复核\n','下列只复核已保存的上下文与均值/影响计算，人工科学判断见逐项说明。不执行源数据或核对表写入。']},{'cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':["import json, statistics, math\nfrom pathlib import Path\nOUT=Path(r'D:\\三季节数据汇总\\数据质控_20261007\\预审_20261007')\nd=json.loads((OUT/'逐项预审建议.json').read_text(encoding='utf8'))\nfor c in d['cases']:\n    m=statistics.mean(c['peer_values'])\n    assert math.isclose(m,c['peer_mean'],rel_tol=1e-12)\n    original=(sum(c['peer_values'])+c['current_value'])/3\n    after=(sum(c['peer_values'])+m)/3\n    assert math.isclose((after-original)/original,c['replacement_group_impact'],rel_tol=1e-12,abs_tol=1e-12)\nprint(d['counts_unique'])\n"]}], 'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'}},'nbformat':4,'nbformat_minor':5}
(OUT/'预审数值复核.ipynb').write_text(json.dumps(nb,ensure_ascii=False,indent=2),encoding='utf8')
print('Unique',dict(unique_counts),'Rows',dict(row_counts)); print('Mean proposals',[(c['address'],c['peer_mean']) for c in out['cases'] if c['decision']==replace])
