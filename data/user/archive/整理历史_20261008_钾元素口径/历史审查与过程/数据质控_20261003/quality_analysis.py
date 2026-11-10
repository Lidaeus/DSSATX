from investigate import *
import numpy as np, datetime, hashlib, zipfile
from openpyxl.utils.datetime import from_excel
issues=[]; details=[]; candidates=[]; profiles=[]; coverage=[]; semantic=[]
def issue(id,priority,kind,title,location,evidence,action,confidence='高'):
    issues.append([id,priority,kind,title,location,evidence,action,confidence,'待核实','',''])
def detail(id,f,n,a,v,reason,action): details.append([id,f,n,a,v,reason,action,'待核实',''])
def getfile(text): return next(f for f in C if f.endswith(text))
def sht(text,n='Sheet1'): return C[getfile(text)]['sheets'][n]
def num(v):
    try:return float(v)
    except:return None
def dt(v):
    if v is None:return '未记录'
    st=str(v)
    if 'T' in st:return st[:10]
    if len(st)==8 and st.isdigit():return st[:4]+'-'+st[4:6]+'-'+st[6:]
    return st
# Explicitly identified primary tables. Auxiliary pivots and lookup lists are not observations.
# date, plot, replicate, W, N, organ, depth columns; 1-based; 0 means absent.
specs=[
('2025年春季茄子植株样氮磷钾测定.xlsx','Sheet1',[1,3,4,8,9,2,0],[5,6,7]),
('2025春产量数据集.xlsx','Sheet1',[3,1,2,4,5,0,0],[6,7]),
('2025春作物生长指标集.xlsx','Sheet1',[1,2,5,3,4,0,0],[7,8,9,10,11]),
('2025春初始土壤基础养分.xlsx','末-基础养分',[0,1,5,3,4,0,6],list(range(7,17))),
('2025春品质集优先采用品质集中的果实含水率.xlsx','Sheet1',[1,2,3,4,5,0,0],list(range(7,15))),
('2025春土壤含水量数据集.xlsx','Sheet1',[15,10,11,12,13,0,8],[2,3,4,5,6,7]),
('2025年秋季茄子植株样氮磷钾测定.xlsx','Sheet1',[1,3,4,8,9,2,0],[5,6,7]),
('2025年秋季茄子生长指标集.xlsx','Sheet1',[1,2,3,4,5,0,0],list(range(6,12))),
('2025秋季2号棚1130日spad窄数据.xlsx','Sheet1',[1,5,4,2,3,0,0],[6]),
('2025秋季产量集.xlsx','2025秋季产量集',[1,2,5,3,4,0,0],[6,7]),
('20260106_2号棚取土.xlsx','Sheet1',[0,5,6,9,10,0,7],[2,3,4,8]),
('25年秋季2号棚品质指标集.xlsx','Sheet1',[1,2,3,4,5,0,0],list(range(6,21))),
('20260519_SPAD.xlsx','Sheet1',[1,2,3,4,5,0,0],[6]),
('2026春产量集.xlsx','Sheet1',[1,2,3,4,5,0,0],[6,7,8]),
('2026春品质指标集.xlsx','Sheet1',[1,2,5,3,4,0,0],list(range(6,15))),
('2026春土壤养分数据集.xlsx','Sheet1',[0,1,0,0,0,0,2],list(range(3,13))),
('2026春土壤含水量数据集.xlsx','Sheet1',[1,2,3,4,5,0,6],[7,8,9]),
('2026春土壤硝态氮氨态氮.xlsx','Sheet1',[0,1,2,3,4,0,5],[6]),
('2026春生长指标集结果.xlsx','0502',[1,2,5,3,4,0,0],list(range(6,12))),
('2026春茎叶果氮磷钾.xlsx','Sheet1',[6,1,2,3,4,5,0],[7,8,9])]
canonical={};all_type=[];physical=[];duplicate=[];missing=[]
for name,n,ids,ms in specs:
    f=getfile(name);s=C[f]['sheets'][n];width=max(max(ids),max(ms));rr=rows(s,width);canonical[f]=(n,ids,ms,rr)
    def key(x):return tuple(x[c-1] if c else None for c in ids)
    keys=collections.defaultdict(list);part=collections.defaultdict(list)
    for r,x in rr:
        k=key(x);keys[k].append(r)
        p=(dt(k[0]),k[5] or '',k[6] or '')
        part[p].append((r,x))
        for c in ms:
            v=x[c-1];a=get_column_letter(c)+str(r);hdr=value(s,get_column_letter(c)+'1')
            if isinstance(v,str) and num(v) is not None: all_type.append([f,n,a,v]);detail('Q18',f,n,a,v,'测量值以文本储存','转为数值，保留原数值')
            if v is None:missing.append([f,n,a,hdr,dt(k[0]),k[1],k[2]])
            if num(v) is not None:
                z=num(v)
                if z<0 or ('含水率' in hdr and not 0<=z<=1) or (hdr=='pH' and not 0<=z<=14):physical.append([f,n,a,v,hdr])
    dup=[(k,v) for k,v in keys.items() if len(v)>1];duplicate.extend([f,n,str(k),str(v)] for k,v in dup)
    coverage.append([f,n,len(rr),len(keys),len(dup),','.join(sorted({dt(x[ids[0]-1]) for r,x in rr})) if ids[0] else '未记录',','.join(str(x) for x in sorted({x[ids[1]-1] for r,x in rr},key=str)),','.join(str(x) for x in sorted({x[ids[2]-1] for r,x in rr},key=str)) if ids[2] else '未记录'])
    for p,prs in part.items():
        for c in ms:
            col=get_column_letter(c);hdr=value(s,col+'1');nums=[(r,num(x[c-1])) for r,x in prs if num(x[c-1]) is not None]; ns=[v for r,v in nums]; miss=len(prs)-len(ns)
            profiles.append([f,n,*p,hdr,len(prs),len(ns),miss,miss/len(prs),min(ns) if ns else None,statistics.median(ns) if ns else None,max(ns) if ns else None])
            # Robust distribution screen within season, date, organ and depth; no pooling across stages.
            if len(ns)>=12:
                q1,q3=np.quantile(ns,[.25,.75]);iq=q3-q1
                if iq>1e-12:
                    for r,z in nums:
                        if z<q1-3*iq or z>q3+3*iq:
                            candidates.append([f,n,col+str(r),hdr,*p,z,'分期3×IQR',float(q1-3*iq),float(q3+3*iq),'仅复核，不直接删除'])
            # Conservative n=3 screen: third differs >30% from other two mean; other pair differs <15%.
            tri=collections.defaultdict(list)
            if ids[2] and 'SPAD' not in hdr and '果鲜' not in hdr and '鲜果' not in hdr and '果含水' not in hdr and '单株果实个数' not in hdr and hdr!='平均果实个数':
                for r,x in prs:
                    if num(x[c-1]) is not None:tri[(x[ids[3]-1] if ids[3] else None,x[ids[4]-1] if ids[4] else None,x[ids[1]-1])].append((r,num(x[c-1])))
                for tk,vs in tri.items():
                    if len(vs)!=3:continue
                    for ix,(r,z) in enumerate(vs):
                        others=[v for j,(_,v) in enumerate(vs) if j!=ix];avg=sum(others)/2
                        if avg>0 and abs(z-avg)/avg>.30 and abs(others[0]-others[1])/avg<.15:
                            candidates.append([f,n,col+str(r),hdr,*p,z,'3个子样的30%偏差',avg*.7,avg*1.3,'检查样本差异和录入；不据此删除'])
csvout('数据覆盖.csv',['文件','主数据页','记录行数','候选键数','重复键组数','日期','小区编号','重复或行号'],coverage)
csvout('分期字段概况.csv',['文件','工作表','日期','器官','土层','字段','记录数','数值数','缺失数','缺失率','最小值','中位数','最大值'],profiles)
for z in candidates:
    n,ids,ms,rr=canonical[z[0]];r=coordinate_from_string(z[2])[1];x=next(x for rn,x in rr if rn==r)
    z.extend([x[ids[1]-1] if ids[1] else None,x[ids[2]-1] if ids[2] else None,x[ids[3]-1] if ids[3] else None,x[ids[4]-1] if ids[4] else None])
csvout('统计筛查.csv',['文件','工作表','单元格','指标','日期','器官','土层','当前值','筛查方法','下界','上界','建议','小区号','重复','水处理','氮处理'],candidates)
csvout('缺失位置.csv',['文件','工作表','单元格','指标','日期','小区号','重复'],missing)
csvout('重复键.csv',['文件','工作表','候选键','原始行号'],duplicate)
# Concrete findings and manual remediation, original values never overwritten.
issue('Q01','P1','疑似录入错误','秋季株高1301','2025秋生长 Sheet1!F100','2026-01-10，W3N3，小区1行3=1301，同组其他株高为百厘米量级','核对手写记录/量尺单位；可能130.1或130，但不得凭推测改值')
detail('Q01',getfile('2025年秋季茄子生长指标集.xlsx'),'Sheet1','F100',1301,'株高显著超出同季和相邻样本尺度','查原记录，确认后修正；不能直接改为130.1')
issue('Q02','P2','缺测','秋季3个株高缺失','2025秋生长 Sheet1!F86,F95,F97','2025-12-08小区10行1、小区12行2和4缺株高，其余生物量存在','补查记录；确实未测保留缺失，不填写0')
for a in ['F86','F95','F97']:detail('Q02',getfile('2025年秋季茄子生长指标集.xlsx'),'Sheet1',a,None,'株高缺测','补查记录或保留缺失')
cross=list(csv.DictReader(open(OUT/'生长表内部差异.csv',encoding='utf-8-sig')))
issue('Q03','P1','版本冲突','2026生长汇总与日期页110处不一致','2026春生长 0502 与0602/0629/0717','612组可比数值中110组不一致：0602=26，0629=35，0717=49；包含株高、干重、LAI等','先确定原始测量页与修订依据，再选唯一分析版本；禁止同时堆叠所有页')
for x in cross:detail('Q03',getfile('2026春生长指标集结果.xlsx'),'0502',x['汇总页单元格'],float(x['汇总值']),f"日期页{x['日期页']}!{x['日期页单元格']}={x['日期页值']}，处理{x['处理']}重复{x['重复']}",'核对记录，确认采用版本')
issue('Q04','P1','关联键','2026品质首批小区号口径变化','2026品质 Sheet1!B2:B49','2026-06-03=48个样本编号、12处理×4重复；6月24日及7月2日=12处理×3重复','保留原样本编号；建立经确认的样本编号→处理/独立小区映射，按日期+水氮处理+样本层级关联')
issue('Q05','P1','处理编码','2025初始土壤处理映射与春季其他表冲突','2025春初始土壤 末-基础养分!A:F','新列W1/W2/W3、N1/N2/N3/N4；小区2标W1N1，而2025春生长/产量小区2为W3N3；无日期','核查文件所属季节、初始/末期及原始处理图；不得简单把N4改N3或整体平移编号')
issue('Q06','P1','控制组编码','CK/CKS/CK2不能按文本直接合并','2025春生长/产量/品质/水分','水分小区1=CK、小区14=CK2；生长/产量小区1=CKS、小区14=CK；NPK只有小区14=CK','按季节+真实小区号建立两种控制组的定义，不直接把所有CK类合并')
issue('Q07','P1','重复层级','独立重复与行/植株/读数重复未分清','三季各文件重复、行号、行位置','产量多为1–3；秋生长/NPK1–4；秋品质及SPAD1–5；春季生长重复绑定行位置','补试验小区/区组/植株/实验室技术重复关系；统计检验前确定实验单位，避免伪重复')
issue('Q08','P2','覆盖缺口','2025春NPK只覆盖9个编号','2025春植株NPK Sheet1','81条=9处理×3器官×3子样；缺小区1、6、7、8、9，即CKS及W2四个处理；茎叶7月13日、果7月4日','查是否有未汇入记录；未测保留缺测，限制养分分析范围，不把不同日期当同日全株样本')
issue('Q09','P1','日期背景冲突','秋季观测延续到2026年1月','2025秋产量/生长/NPK/取土','采收2025-11-21/12-11/2026-01-05，生长至1月10日，NPK至1月9日，与说明的11月结束矛盾','核定真实定植及结束日期、采样日与测定日；确认前保留跨年日期，不改回2025年')
issue('Q10','P1','采收完整性','真实采收次数与背景说明不符','春季产量表','2025春9日期（378条）而文档称10次；2026春5日期（180条），5月26日至7月17日，而文档称8次、5月18日至7月15日','核查是否为合并批次或漏汇；完整性确认前不能将合计称全季总产')
issue('Q11','P2','空模板','2025春生长有84条全测量空行','2025生长 Sheet1!G86:K127,G170:K211','6月9日/6月21日各42条，仅日期和编号存在，全部5个测量字段空白；不是0值','补查是否确实取样；未取样则在分析视图排除空模板，保留原表并记原因')
for r in list(range(86,128))+list(range(170,212)):detail('Q11',getfile('2025春作物生长指标集.xlsx'),'Sheet1',f'G{r}:K{r}',None,'整行测量指标均空','查记录；分析时区别空模板与实测记录')
issue('Q12','P2','结构性缺测','品质缺测按日期集中','2025春、2025秋、2026春品质','25春酚/黄酮/花青素只有6月25日39条，其余81空；25秋半果水分60/60空；26春硬度6月3日48空，酚/黄酮/花青素后两期72空','核实是否未测；按指标有效样本数分析，不用处理均值补成独立重复，不将空白作0')
issue('Q13','P1','单位口径','吸光度与浓度、器官质量与产量需分开','品质、生长、土壤表头','25春明确为总酚/黄酮/花青素吸光度，26春未标单位；25春Vc及糖/蛋白未标单位；产量及干重部分也未标单位','补单位、标准曲线、稀释倍数、干/鲜基、称重范围及面积；未经换算不能跨季拼接')
issue('Q14','P1','分析输入缺口','水量平衡与效率所需输入不全','当前全部20个Excel及方案','未发现逐次灌溉、施肥事件、气象序列、排水/渗漏、有效小区面积/采收株数与确切定植日期表','补管理/气象/小区设计原始数据；ET不可用灌溉量直接代替；N0的PFP_N保留不适用')
issue('Q15','P1','无日期或重复','土壤养分缺采样日期和关键字段','2026土壤养分及硝态氮表','养分36条=12小区×3层，无采样日期/重复；硝态氮180条=12×3×5层，无日期且当前没有铵态氮列','补采样时间、复合样规则、真实重复及铵态氮；不能按行号与其他土壤表匹配')
issue('Q16','P1','外部链接','426个公式依赖未随项目提供的工作簿','25春水分及26春品质','25春210个日期外链至2025年5月24日测土.xlsx；26春216个品质指标外链至Mac路径7.2品质工作簿；目前有缓存值','获取原始外链文件并核对；保留缓存快照，另建经确认的值版供分析，避免自动更新改写')
issue('Q17','P1','已填补值','2025品质9个测量值实际为均值填补','2025品质 Sheet1!J12,J15,J31,K47:M47,K78:M78','3个含水率、6个吸光度由同组其他记录AVERAGE得到，不是独立实测','标注imputed及填补来源；推断分析剔除填补项或单独做敏感性分析；原值和公式保留')
for a in ['J12','J15','J31','K47','L47','M47','K78','L78','M78']:detail('Q17',getfile('2025春品质集优先采用品质集中的果实含水率.xlsx'),'Sheet1',a,value(sht('2025春品质集优先采用品质集中的果实含水率.xlsx'),a),'均值填补 '+sht('2025春品质集优先采用品质集中的果实含水率.xlsx')['formulas'][a]['formula'],'标注非实测，不能作为新的独立重复')
issue('Q18','P2','数值类型','2025水分有文本格式的湿干重','2025水分 Sheet1!B:C',f'{len(all_type)}个测量单元格为可转数字的文本，全部出现在25春水分湿/干重列','在分析副本转换为数值，保存原记录；不要让类型转换错误变成缺失或0')
issue('Q19','P1','测点键','秋SPAD同一候选键重复4次','2025秋SPAD Sheet1','240行、60个日期+小区+重复键，键各出现4次；前三批各60读数，第四批仅6读数，54空','补叶位/叶片/测点编号；逐株汇总技术读数，再按独立小区分析；相同键不等于可删除重复')
ss=sht('2025秋季2号棚1130日spad窄数据.xlsx')
for r,x in rows(ss,6):
    if x[5] is None:detail('Q19',getfile('2025秋季2号棚1130日spad窄数据.xlsx'),'Sheet1','F'+str(r),None,'第4批SPAD测点未填，未标测点号','补测点定义；确定是否计划测量或空模板')
issue('Q20','P1','重量量纲','1月土壤含水率疑似盒重单位未统一','20260106取土 Sheet1!B:H','240条湿/干重为几千，盒重约16–18；H=(C-D)/(D-B)。首行盒重16.3，湿8168，干7055：缓存0.158126；若湿干重=0.01g则应0.205161','核对天平读数和小数点约定；确认后统一单位复算240条，不直接使用现有含水率', '中高')
sm=sht('20260106_2号棚取土.xlsx');cor=[]
for r,x in rows(sm,10):
    corr=(x[2]-x[3])/(x[3]-x[1]*100)
    cor.append([r,x[0],x[4],x[5],x[6],x[1],x[2],x[3],x[7],corr,corr/x[7]-1])
    detail('Q20',getfile('20260106_2号棚取土.xlsx'),'Sheet1','H'+str(r),x[7],f'若湿/干重为0.01g计数，复算={corr:.9f}；原公式={sm["formulas"]["H"+str(r)]["formula"]}','先核实称重单位，再决定复算')
csvout('土壤含水率条件复算.csv',['行号','土盒','小区','重复','深度','盒重','湿重','干重','当前含水率','假设0.01g时复算','相对增幅'],cor)
issue('Q21','P2','重复数据页','1月取土Sheet1与Sheet1 (2)主体相同','20260106取土两个页','A:J的240条记录、测量值和公式缓存完全一致；第2页多编号映射，不能作为新增样本','选一个主体数据页导入，第2页只作映射来源；Sheet2盒重和Sheet3编号表也不作测量样本')
issue('Q22','P2','附加处理','2026 SPAD存在W4/NN0–NN2','20260519_SPAD Sheet1!A62:F76','Z1/Z2/Z3各5条，共15条；其他数据仅W1–W3及N0–N3','查附加试验设计；保留独立组别，不把NN2等自动改成N2')
issue('Q23','P2','编号稳定性','2025春重复号与行位置对应改变','2025生长与品质 F列','同一处理不同日期重复号1/2/3对应的边行/中间行关系发生变化；7月13日小区14重复1为边行','用真实行/植株标识核对纵向对应；破坏性取样不强行当同株连续测量')
issue('Q24','P2','小果样本口径','0629果鲜重有7个值低于50g','2026生长 0629!J3,J4,J6,J7,J19,J31,J36','7.27–23.03g，均为重复2/3；同日其他值可达1464.28g','核查是否未成熟小果、全株果重或半果/干重混栏；小值可能真实，不直接删除','中')
for r in [3,4,6,7,19,31,36]:detail('Q24',getfile('2026春生长指标集结果.xlsx'),'0629','J'+str(r),value(C[getfile('2026春生长指标集结果.xlsx')]['sheets']['0629'],'J'+str(r)),'果鲜重<50g，需确认称重对象','对照原称重表确认鲜/干基和果实大小')
issue('Q25','P2','果实干重缺测','0602半果干重整列缺失','2026生长 0602!J2:J37','36/36半果干重空；早期无果与果重为0也需保留生物学解释','查半果干重原表；未经配对不能按不同日期的水分率当作实测干重')
issue('Q26','P2','生物学变化','末期叶量下降及挂果为0不能机械判错','三季生长末期叶干重/LAI/果鲜重','破坏性样株、摘老叶/采收、衰老均可产生下降或当时无挂果；统计筛查不等于错误证据','核对田间摘叶和采收记录；不跨日期搬移数值，也不要求所有器官严格单调','中')
issue('Q27','P1','同步版本','2025春水分14条称重发生数值差异','两目录2025春水分','8个湿重、6个干重不同，带来14个含水率及14个体积含水率差异；日期630处仅Excel日期序列/类型不同','逐条对照原始称重记录确定版本；日期只统一显示/数据类型，不当作采样日期改变')
issue('Q28','P1','同步版本','2025初始土壤实质差异为112项测量','两目录2025初始土壤','按列语义对齐后其他104?列一致；铵态氮4项、硝态氮108项不同；当前多处理/灌水/施氮3列','不能按相同单元格直接覆盖；112个测量逐条确认，新增映射列另行核实')
issues[-1][5]='按列语义对齐后，11个共同字段的108条记录一致；铵态氮4项、硝态氮108项不同；当前多处理/灌水/施氮3列'
issue('Q29','P1','同步版本','2026土壤养分5项值不同','两目录2026土壤养分 H12,H13,L13,H25,L25','3个有机质、2个全氮值不同，差0.1–0.4；其他主体值一致','查测定原表/修订记录决定采用值；不默认较新文件或参照目录更正确')
issue('Q30','P1','同步版本','2026硝态氮180项全部不同','两目录2026硝态氮表 F2:F181/G列','同键180硝态氮值全部不同；参照多180个铵态氮值；参照硝态氮3项存文本；两边硝态氮比值不恒定','查测定与换算记录；不能用14/62统一解释；铵态氮列也应核实来源后补入')
issue('Q31','P2','待同步数据','参照独有3个土壤文件','参照2025春/秋','25春土壤有机质估算与校准集、25秋土壤养分、25秋2号棚取土；取土含20250809与20261002页','按用途补原始土壤数据；估算/校准值单独标注非原始测定；20261002页所属季节和日期须核实')
issue('Q32','P2','同步保护','当前独有4个文件应保留','当前2025秋/2026春','25秋SPAD、20260106取土、26春SPAD、26春茎叶果NPK在参照无同名文件','保留当前新增数据；按需要另做备份，不能用参照目录整体覆盖当前目录')
issue('Q33','P2','历史审查记录','参照QA日志与现有同名文件不完全吻合','参照源数据QA记录_20260818.json','日志称25春生长删除84占位行及旧26春生长加QA页；当前双方同名生长文件仍有84空行，26春结果文件没有剔除/QA页','历史记录仅作线索；不能视为当前文件已清洗或本次用户批准剔除，需找到被审查的对应版本')
issue('Q34','P2','产量换算','2026果重到产量换算系数不统一','2026产量 Sheet1!F:G','果实总重到产量存在多个系数，可能按有效采收株数或小区面积修正；未提供这些依据','逐批补采收株数、面积、边行口径及换算公式；不同系数本身不证明错误','中')
issue('Q35','P3','统计筛查','候选离群值需人工确认','统计筛查表',f'{len(candidates)}次规则触发（同一单元格可能触发两种规则），为分期3IQR及3子样相对差异，不含显著性检验','优先核实强异常和版本冲突；保留有实验依据的极值，对争议值做含/不含敏感性分析','中低')
# Semantic comparison corrects date serialization and shifted columns.
for f in sorted(set(C)|set(R)):
    if f not in C or f not in R:continue
    for n,cs in C[f]['sheets'].items():
        if n not in R[f]['sheets']:continue
        rs=R[f]['sheets'][n]
        mapping={get_column_letter(i):get_column_letter(i) for i in range(1,max(cs['cols'],rs['cols'])+1)}
        if '初始' in f:mapping={'A':'A','E':'B','F':'C','G':'D','H':'E','I':'F','J':'G','K':'H','L':'I','M':'J','N':'K','O':'L','P':'M'}
        for c,rc in mapping.items():
            for r in range(2,max(cs['rows'],rs['rows'])+1):
                a=c+str(r);b=rc+str(r);x=value(cs,a);y=value(rs,b)
                if x is None and y is None:continue
                kind='测量/字段值不同'
                if '2025春土壤含水' in f and c=='O' and isinstance(y,(float,int)):
                    if dt(x)==from_excel(y).date().isoformat():continue
                if num(x) is not None and num(y) is not None:
                    if abs(num(x)-num(y))<=max(1e-10,abs(num(x))*1e-10):continue
                elif x==y:continue
                semantic.append([f,n,a,value(cs,c+'1'),x,b,value(rs,rc+'1'),y,kind,'待核实',''])
csvout('按字段对齐差异.csv',['文件','工作表','当前单元格','当前字段','当前值','参照单元格','参照字段','参照值','差异类型','处理状态','处理说明'],semantic)
csvout('人工处理清单.csv',['编号','优先级','类型','问题','位置','证据','处理建议','置信度','状态','处理决定','依据'],issues)
csvout('疑点单元格.csv',['问题编号','文件','工作表','单元格或范围','当前值','疑点依据','处理建议','状态','处理说明'],details)
# Verification of relevant algebraic/physical identities against primary raw values.
checks=collections.Counter(); failures=[]
for text in ['2025春土壤含水量数据集.xlsx','2026春土壤含水量数据集.xlsx']:
    s=sht(text)
    for r,x in rows(s,15 if text.startswith('2025') else 9):
        if text.startswith('2025'):
            wet,dry,tare,bden,w,v=map(num,[x[1],x[2],x[3],x[5],x[4],x[6]])
            checks['湿重≥干重且干土质量为正']+=1
            if wet<dry or dry-tare*100<=0:failures.append([text,r,'重量关系'])
            checks['烘干法重量含水率复算']+=1
            if abs(w-(wet-dry)/(dry-tare*100))>1e-9:failures.append([text,r,'重量含水率复算'])
        else:bden,w,v=map(num,x[6:9])
        checks['体积含水率=重量含水率×容重']+=1
        if abs(v-w*bden)>1e-9:failures.append([text,r,'含水率换算'])
        checks['水分不超过估计孔隙率(假设颗粒密度2.65)']+=1
        if v>1-bden/2.65+1e-9:failures.append([text,r,'超过估计孔隙率'])
s=C[getfile('2026春生长指标集结果.xlsx')]['sheets']['0629']
for r,x in rows(s,14):
    for fresh,dry,water in [(7,10,12),(8,11,13)]:
        checks['0629干重≤鲜重及器官含水率复算']+=1
        if x[dry]>x[fresh] or abs(x[water]-(1-x[dry]/x[fresh]))>1e-9:failures.append(['0629',r,'干鲜重关系'])
s=C[getfile('2026春生长指标集结果.xlsx')]['sheets']['0717']
for r,x in rows(s,18):
    checks['0717总LAI=大叶LAI×(叶鲜重+小叶鲜重)/叶鲜重']+=1
    if abs(x[17]-x[10]*(x[13]+x[14])/x[13])>1e-8:failures.append(['0717',r,'小叶校正LAI'])
summary={'as_of':'2026-10-03','current_books':len(C),'current_sheets':sum(len(w['sheets']) for w in C.values()),'reference_books':len(R),'primary_rows':sum(x[2] for x in coverage),'issues':len(issues),'details':len(details),'candidate_rule_hits':len(candidates),'candidate_cells':len(set(tuple(x[:3]) for x in candidates)),'physical_violations':physical,'check_counts':dict(checks),'check_failures':failures,'semantic_diff_counts':dict(collections.Counter(x[0] for x in semantic)),'numeric_text_cells':len(all_type),'conditional_soil_relative_increase_range':[min(x[-1] for x in cor),max(x[-1] for x in cor)]}
issue('Q36','P1','已填补值/计算不一致','2025水分5项不等于原始称重复算','2025水分 Sheet1!E43,E257,E447,E487,E572','E43/E447/E487/E572使用其他样本AVERAGE代替本样本实测；E257硬填0.175148，与湿7570/干7135/盒17.48复算0.080750不同；G列随之改变','对照原始称重和修订依据，标出4项均值填补及1项不一致硬值；确认后复算，不作为5个独立实测')
for r in [43,257,447,487,572]:
    ss=sht('2025春土壤含水量数据集.xlsx');wet,dry,tare=map(num,[value(ss,'B'+str(r)),value(ss,'C'+str(r)),value(ss,'D'+str(r))]);z=(wet-dry)/(dry-tare*100)
    detail('Q36',getfile('2025春土壤含水量数据集.xlsx'),'Sheet1','E'+str(r),value(ss,'E'+str(r)),f'按本样本称重复算={z:.9f}；原式='+str(ss['formulas'].get('E'+str(r),{}).get('formula','硬填值')),'查原始重量记录与替代原因；标注填补')
issue('Q37','P2','汇总范围','秋SPAD透视表没有纳入第4批6个读数','2025秋SPAD Sheet3!B5:G7','Sheet3按前三批180个读数汇总；主表另有6个有效读数。全有效读数W1/W2/W3均值=57.579365/57.119355/57.516393，与透视表总计不同','明确第4批是否补测及是否纳入，确定范围后再刷新/重新汇总，保留原读数')
summary['issues']=len(issues);summary['details']=len(details)
csvout('人工处理清单.csv',['编号','优先级','类型','问题','位置','证据','处理建议','置信度','状态','处理决定','依据'],issues)
csvout('疑点单元格.csv',['问题编号','文件','工作表','单元格或范围','当前值','疑点依据','处理建议','状态','处理说明'],details)
json.dump({'summary':summary,'issues':issues,'details':details,'candidates':candidates,'profiles':profiles,'coverage':coverage,'semantic':semantic},open(OUT/'reviewed_results.json','w',encoding='utf8'),ensure_ascii=False,indent=2)
print(json.dumps(summary,ensure_ascii=False,indent=2))
