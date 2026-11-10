from pathlib import Path
import json,csv,re,ast,math,hashlib,zipfile,statistics,collections,shutil,sys
from openpyxl import load_workbook
sys.stdout.reconfigure(encoding='utf8')
ROOT=Path(r'D:\三季节数据汇总'); OUT=ROOT/'数据质控_20261007'; REF=Path(r'D:\Tomato_Cal\data\user\ref\DSSAT文件')
S=json.loads((OUT/'snapshot.json').read_text(encoding='utf8')); BEFORE=json.loads((OUT/'检查前快照.json').read_text(encoding='utf8'))
D=json.loads((OUT/'reviewed_results.json').read_text(encoding='utf8'))
C=S['current']; R=S['reference']
def value(s,a):return s['formulas'][a]['cached'] if a in s['formulas'] else s['cells'].get(a)
def sheet(suffix,n='Sheet1',reference=False):
    pool=R if reference else C
    return pool[next(f for f in pool if f.endswith(suffix))]['sheets'][n]
def csvout(name,head,rows):
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:w=csv.writer(f);w.writerow(head);w.writerows(rows)

# Recheck source integrity independently of the patch and statistical routines.
changed=[f for f in C if C[f]['sha256']!=BEFORE['current'][f]['sha256']]
assert set(changed)=={'2025春\\2025春土壤含水量数据集.xlsx','2025秋\\20260106_2号棚取土.xlsx'}
assert all(R[f]['sha256']==BEFORE['reference'][f]['sha256'] for f in R)
assert not [(f,n,s['errors']) for f,w in C.items() for n,s in w['sheets'].items() if s['errors']]
verification={'current_books':len(C),'current_sheets':sum(len(w['sheets']) for w in C.values()),'source_changed_files':changed,'reference_unchanged':True,'formula_error_cells':0}
for f in changed:
    old=BEFORE['current'][f]['sheets'];new=C[f]['sheets'];delta=[]
    for n,s in new.items():
        for a in set(s['cells'])|set(s['formulas'])|set(old[n]['cells'])|set(old[n]['formulas']):
            if s['cells'].get(a)!=old[n]['cells'].get(a) or s['formulas'].get(a)!=old[n]['formulas'].get(a):delta.append((n,a))
    expected=[('Sheet1','C257')] if '2025春' in f else [('Sheet1','H'+str(r)) for r in range(2,242)]
    assert set(delta)==set(expected),(f,delta)
    with zipfile.ZipFile(ROOT/f) as current,zipfile.ZipFile(OUT/'修订前备份'/Path(f).name) as backup:
        assert set(current.namelist())==set(backup.namelist())
        assert [n for n in current.namelist() if current.read(n)!=backup.read(n)]==['xl/worksheets/sheet1.xml']
    verification[f]={'changed_cells':len(delta),'only_sheet1_package_part_changed':True}
ws=sheet('20260106_2号棚取土.xlsx'); waterdiff=[]; waterbad=[]
for r in range(2,242):
    b,c,d=[value(ws,x+str(r)) for x in 'BCD']; h=value(ws,'H'+str(r)); calc=(c-d)/(d-b*100)
    assert math.isclose(h,calc,rel_tol=1e-12,abs_tol=1e-12)
    if not c>=d>b*100 or h<0:waterbad.append(r)
    old=value(BEFORE['current']['2025秋\\20260106_2号棚取土.xlsx']['sheets']['Sheet1'],'H'+str(r));waterdiff.append((h-old)/old)
assert not waterbad
verification['soil_240_recalculated']={'first':value(ws,'H2'),'min':min(value(ws,'H'+str(r)) for r in range(2,242)),'max':max(value(ws,'H'+str(r)) for r in range(2,242)),'relative_increase_min':min(waterdiff),'relative_increase_max':max(waterdiff),'wet_dry_box_order_valid':True}
ws=sheet('2025春土壤含水量数据集.xlsx');assert value(ws,'C257')==6702
verification['C257_manual_moisture']={'stored_E257':value(ws,'E257'),'recomputed_from_rounded_weight':(value(ws,'B257')-6702)/(6702-value(ws,'D257')*100),'keep_manual_E257':True}
height=sheet('2025年秋季茄子生长指标集.xlsx'); assert [value(height,a) for a in ['F86','F95','F97','F100']]==[114,124,126,131]
verification['height_check']={'F86':114,'F95':124,'F97':126,'F100':131}
assert list(C[next(f for f in C if f.endswith('2026春生长指标集结果.xlsx'))]['sheets'])==['2026生长指标汇总']
# Simple numeric arithmetic formula checks, preserving unsupported/external formula caches.
checked=0;unsupported=0;blanks=0;mismatches=[]
for f,w in C.items():
    for n,s in w['sheets'].items():
        for a,fo in s['formulas'].items():
            form=fo['formula'][1:].replace('$','');cached=fo['cached']
            if cached is None:blanks+=1;continue
            if '[' in form or ':' in form or '!' in form or re.search(r'[A-Z]{3,}\(',form):unsupported+=1;continue
            try:
                expr=re.sub(r'\b[A-Z]+\d+\b',lambda m:repr(value(s,m.group()) if value(s,m.group()) is not None else 0),form).replace('^','**')
                tree=ast.parse(expr,mode='eval')
                assert all(isinstance(node,(ast.Expression,ast.BinOp,ast.UnaryOp,ast.Constant,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow,ast.USub,ast.UAdd)) for node in ast.walk(tree))
                got=eval(compile(tree,'<formula>','eval'),{'__builtins__':{}});checked+=1
                good=math.isclose(got,cached,rel_tol=1e-9,abs_tol=1e-9) if isinstance(got,(int,float)) and isinstance(cached,(int,float)) else got==cached
                if not good:mismatches.append([f,n,a,fo['formula'],cached,got])
            except Exception:unsupported+=1
verification['simple_formulas']={'checked':checked,'mismatch':len(mismatches),'unsupported_or_external':unsupported,'empty_cache':blanks}
csvout('公式复算差异.csv',['文件','工作表','单元格','公式','缓存','独立复算'],mismatches)
assert not mismatches
# Verify soil and moisture field laws for every applicable row, including preserved excluded records.
physical=[]
for f,n,moisture,density,volume in [('2025春土壤含水量数据集.xlsx','Sheet1','E','F','G'),('2026春土壤含水量数据集.xlsx','Sheet1','H','G','I')]:
    s=sheet(f,n)
    for r in range(2,s['rows']+1):
        m=value(s,moisture+str(r));b=value(s,density+str(r));v=value(s,volume+str(r))
        if isinstance(m,(int,float)) and isinstance(b,(int,float)) and isinstance(v,(int,float)):
            if not 0<=m<=1 or not 0<=v<=1 or b<=0 or not math.isclose(m*b,v,rel_tol=1e-9,abs_tol=1e-9):physical.append([f,n,r,m,b,v])
verification['water_density_relation_failures']=physical;assert not physical
# All screening entries obey the new masks; reconstruction and confirmed filled values stay out.
for x in D['screens']:
    if x[0].startswith('2025春'):assert x[11] not in {1,6,7,8,9,14}
    assert (x[0],x[2]) not in {(m[0],m[2]) for m in D['confirmed_fill']}
    assert x[4] not in ['2025-06-09','2025-06-21']
assert len(D['spad'])==6 and len(D['spad_means'])==60 and all(x[9]==3 for x in D['spad_means'])
assert D['summary']['screen_rule_hits']==217 and D['summary']['screen_locations']==213

# Reference-only autumn nutrient data are remarkably similar to current 2026 data: keep evidence.
autumn=sheet('2025秋土壤养分数据集.xlsx',reference=True); spring=sheet('2026春土壤养分数据集.xlsx'); season_diffs=[];equal=0
for r in range(2,38):
    for c in 'CDEFGHIJKL':
        a=c+str(r);av=value(autumn,a);sv=value(spring,a)
        if isinstance(av,(int,float)) and isinstance(sv,(int,float)) and math.isclose(av,sv,rel_tol=1e-12,abs_tol=1e-12):equal+=1
        else:season_diffs.append([a,av,sv])
assert equal==355 and len(season_diffs)==5
csvout('参照秋季土壤与当前2026养分对照.csv',['位置','参照秋季值','当前2026春值'],season_diffs)
verification['reference_autumn_vs_current_spring']={'matching_measurements':equal,'measurements_compared':360,'differences':season_diffs}
csvout('参照非Excel文件清单.csv',['完整路径','相对路径','字节数'],[(str(p),str(p.relative_to(REF)),p.stat().st_size) for p in REF.rglob('*') if p.is_file() and p.suffix.lower()!='.xlsx' and not p.name.startswith('~$')])
(OUT/'验证结果.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf8')

status=[
('Q01','已关闭：用户修正','秋季株高异常','Sheet1!F100=131，原1301已改；本次未改株高','按当前Excel纳入'),
('Q02','已关闭：用户补齐','秋季株高缺测','F86/F95/F97现为114/124/126','按当前Excel纳入'),
('Q03','已关闭：唯一汇总页','2026生长内部版本','仅存2026生长指标汇总，144行；日期页已删除','只用汇总页'),
('Q04','保留编号；限制关联','2026品质首批样本编号','6月3日B列1–48；后两期1–12。保留原号，本次按水氮处理+生物学重复分组','跨表关联时需区分样本流水号与小区号，不按首批B列直接连产量'),
('Q05','已关闭：旧错列删除','2025初始土壤映射','当前13列，错误W/N新增列已删除；同季以小区号对齐','土壤采样日和初/末阶段仍未记在表内，不据页名推断'),
('Q06','已关闭：旧编码修正','2025水分控制组','当前编码已统一；两个控制组均在2025春排除范围','按同季小区号关联'),
('Q07','按用户口径保留','生物学重复数不同','不同日期/指标实际3、4或5个重复属试验安排；不强制删到3','只统一SPAD技术读数，不统一生物学重复数'),
('Q08','分析范围已排除','2025春放弃处理','排除小区1、6、7、8、9、14；保留2、3、4、5、10、11、12、13','所有2025春分析使用排除记录；不外推为其他季同号排除'),
('Q09','已关闭：跨年保留','秋季观测日期','真实采收11-21/12-11/2026-01-05；生长和NPK现至2026-01-06','背景说明已更新，不改回2025年'),
('Q10','说明文档已纠正','实际采收批次','Excel实记25春9次、25秋3次、26春5次；按实际记录统计','未来TMX最后实采后加虚拟操作，不计入实测产量'),
('Q11','分析范围已排除','2025春整枝日期空行','6月9日/21日是弃用的整枝打杈数据；84原始行保留','筛查不再当补测缺口，不填0'),
('Q12','已确认真实缺测','品质缺测/遗失','依用户确认保留空白，按日期和指标有效数分析','不新增均值填补'),
('Q13','口径已更新','品质及重量单位','三季糖/蛋白mg/g；总酚/黄酮/花青素吸光度；25春Vc mg/kg；产量kg/ha；干重一般g/株','其他未明确单位不跨季强制换算；详见报告'),
('Q14','待后续补全','灌溉施肥气象输入','温室降雨0；确切定植日/管理事件/面积等待用户补充','暂不据旧文档数值计算ET、效率或DAT'),
('Q15','按用户口径保留','2026养分汇总与无机氮','养分36条为处理后的汇总，不能恢复成独立重复；无机氮暂缓','不把3土层当3重复；无日期不做初末变化'),
('Q16','按用户口径保留','外链公式缓存','本次保留当前缓存，不刷新外部链接','报告/分析读取缓存，保留公式溯源'),
('Q17','已标记并保留','2025品质均值替代','9个用户确认替代测量标明来源，本次不列新异常候选','后续推断分析可做有/无替代值敏感性比较'),
('Q18','已关闭：类型纠正','数字文本重量','原97项数字文本已改为数值；当前测量字段无非数值文本','按当前Excel读取'),
('Q19','建议已列；原表未删','SPAD统一3次技术测定','建议排除F192/F198/F199/F202/F203/F210；保留表内前三次有效读数','用户手动采用；本次分析视图暂按此建议'),
('Q20','已修订并验证','20260106重量量纲','用户确认湿/干重×100、盒重g；H2:H241改为(C-D)/(D-B*100)，240条缓存已重算','原称重不改；完整修订明细和备份已保存'),
('Q21','已关闭：重复页删除','取土重复及无关页','当前主体Sheet1和盒重辅助页；无重复测量页','辅助页不堆叠为观测'),
('Q22','分析范围已排除','附加W4/NN处理','2026 SPAD的Z1/Z2/Z3共15行附加处理排除','原始表保留'),
('Q23','按表注和破坏性取样','重复号与行位置','按表注读取，跨日期同号是不同植株','不强行建同株重复测量关系'),
('Q24','当前已无对应列','旧0629小果鲜重','历史路径与J3/J4/J6/J7/J19/J31/J36见报告；0629页已被用户删除','当前汇总无该列，关闭本项'),
('Q25','当前已无对应列','旧0602半果干重缺失','历史路径与J2:J37见报告；0602页已被用户删除','当前汇总无该列，不再要求补齐'),
('Q26','已确认生物学解释','叶量下降/挂果0','末期整枝打杈可使叶量下降；植株挂果不用于分析','不做跨日期单调性修正，不筛查挂果列'),
('Q27','旧差异已关闭；新增1处','2025春水分同步','修订前与参照无值差；本次C257=6702，参照7135，只有这一处实质差异','由用户向参照同步6702，E257/G257保持'),
('Q28','已关闭：Excel一致','2025初始土壤同步','当前与参照文件字节完全相同；旧112项差异消除','以后以当前Excel为准'),
('Q29','已关闭：Excel一致','2026土壤养分同步','当前与参照文件字节完全相同；旧5项差异消除','勿用参照秋季同形养分文件覆盖本文件'),
('Q30','当前旧文件已删除','硝态/铵态氮版本','原2026无机氮工作簿现双方均无；参照新添三季初始无机氮参考','无机氮暂不纳入，不用旧审查数值'),
('Q31','已展开；需人工判断','参照独有土壤文件','现4个；有机质估算/校准不是测定；秋季养分355/360测量与当前26春相同；取土20261002日期需确认','完整路径与5处差值见报告；不自动导入'),
('Q32','已重新比较目录','当前独有文件','现3个：秋SPAD、20260106取土、20260519 SPAD；2026器官NPK已双边一致','本次未自动同步；所需文件由用户选择'),
('Q33','旧记录标为历史','旧审查结论冲突','10月3日审查已标为历史；当前口径及本次复核报告为入口','历史QA不用于执行删除、填补或重新映射'),
('Q34','已确认换算有效','果实总重到产量系数','用户确认按有效采收株数修正，多个系数有效','按Excel产量列保留，不统一系数'),
('Q35','已更新；待人工处理','统计候选复核','217次触发、213个独立定位；采用新范围、缓存、已确认替代值标记','在更新统计筛查黄色列填写决定/依据，不自动删值'),
('Q36','C257已修订；手填保留','2025水分替代及反算','用户指定C257=6702；E257手填及G257保持。4均值E和5对应G已标记','C257标为反算值；取整复算小差不覆盖手填E257'),
('Q37','建议与汇总已统一','秋SPAD原透视范围','建议按前三次180读数形成60个生物学重复均值，与原Sheet3范围一致','原始透视和读数未刷新/删除；用新分析视图')]
D['issue_status']=[list(x) for x in status]
csvout('事项处理状态.csv',['编号','本次状态','事项','处理或依据','后续行动'],status)
(OUT/'reviewed_results.json').write_text(json.dumps(D,ensure_ascii=False,indent=2),encoding='utf8')

# Update explanatory documents without discarding the original proposed analysis framework.
for fn in ['试验背景与数据说明_温室茄子水氮试验.md','数据分析方案.md']:
    dest=OUT/'修订前备份'/fn
    if not dest.exists():shutil.copy2(ROOT/fn,dest)
conflicts=[]
def replace(text,old,new,topic):
    if old not in text:raise ValueError('Cannot find document passage: '+old[:80])
    conflicts.append(['试验背景与数据说明_温室茄子水氮试验.md',topic,old,new,'已纠正说明；未据文档改Excel'])
    return text.replace(old,new)
p=ROOT/'试验背景与数据说明_温室茄子水氮试验.md'; t=p.read_text(encoding='utf8')
t=replace(t,'v1.0 (2026-09-19)','v1.1 (2026-10-07)','版本')
policy='''
> **2026-10-07执行口径**：以 `D:\\三季节数据汇总` 当前Excel及用户最新确认优先；参考目录、衍生CSV、DSSAT文件、旧QA和本文历史背景不能覆盖当前Excel。最新审查见 `数据质控_20261007/复核更新报告.md`。下述灌溉/施肥、土壤物理参数、仪器方法和品种等历史背景中未由当前Excel提供证据的内容，保留为待核定背景，不作为已核验的分析输入。
>
> 2025春仅分析小区2、3、4、5、10、11、12、13；1、6、7、8、9、14因意外弃用，其他季不按同号排除。重复数按各指标/日期实际记录，技术测定与生物学重复分开。破坏性取样跨日期同重复号并非同株。三季糖、蛋白mg/g；酚/黄酮/花青素为吸光度；25春Vc mg/kg；Excel产量kg/ha，原始干重一般g/株。

'''
pos=t.index('\n---');t=t[:pos]+ '\n'+policy+t[pos:]
t=replace(t,'秋茬（25FA）：通常于 8 月中旬定植，11 月中下旬拉秧，全生育期约 90~100 天。','秋茬（25FA）：观测延续至2026年1月6日，最后真实采收为2026年1月5日；确切定植和拉秧日期待管理记录补齐，不按11月结束计算生育天数。','秋季跨年')
t=replace(t,'**试验开始前 0~60 cm 土层初始土壤养分本底（2号棚实测基准）**','**历史文档中的0~60 cm土壤背景值（来源日期与采样状态未核定，不作为当前实测基准）**','土壤来源')
t=replace(t,'> **土壤养分特征解析**：试验地土壤呈典型微碱性（pH 8.6~8.8），表层（0~20 cm）有机质中等偏低，速效磷与速效钾富集非常明显，但碱解氮和全氮偏低，表现出对氮素补充的高度敏感性。','> 上表仅保留历史背景，正式分析须从对应季节Excel读取。25春基础养分文件没有实测有机质列；参照有机质估算文件依据全氮和假设C:N推算，且有校准系数，不作为独立有机质测定。26春养分为用户处理后的汇总，未提供采样日期和重复，不推断为三次独立重复或初始本底。','土壤阶段与估算')
t=replace(t,'试验采用**水分（3 水平）× 施氮量（4 水平）的两因素完全随机区组设计**，共设 12 个主要处理，部分季度设有农户常规灌水对照（CK）。每个处理设 **3 次独立重复**，共计 36~39 个试验小区。','处理映射按同一季节Excel小区号对齐。2025春原始数据有14个处理编号，当前仅保留W1、W3各4个氮水平共8个处理；2025秋和2026春为W1–W3×N0–N3共12个处理。不同日期/指标的生物学重复数可为3、4或5，按实有记录及表注使用，不将记录行数等同独立小区数；本次只对SPAD技术读数建议统一前三次。','设计与重复数')
# Correct mapping rows that had omitted two actual 2025 spring W2 treatments.
t=t.replace('`TN8 (26)` | $W_2$','`TN8 (25) / TN8 (26)` | $W_2$').replace('84 | — | Trt 8 |','84 | Trt 8（弃用） | Trt 8 |')
t=t.replace('`TN5 (26)` | $W_2$','`TN7 (25) / TN5 (26)` | $W_2$').replace('168 | — | Trt 5 |','168 | Trt 7（弃用） | Trt 5 |')
table_end=t.index('\n---',t.index('| **CK (CKN2)**'))
t=t[:table_end]+'\n> 2025春另有小区1=CKS；1、6、7、8、9、14全部弃用，上表仅保存历史处理映射。上表灌水量、施肥量和TMX编号在管理数据补齐前均为待核定背景，不能直接用于效率计算或生成最终TMX。\n'+t[table_end:]
t=replace(t,'试验设计设 11 个处理（包含 CK），全季经历了 10 次独立分批采收','原始Excel含14个处理编号（含CKS/CK），当前分析保留8个，实际记录9次分批采收','25春批次与处理')
t=replace(t,'周期：2025年8月中旬至11月下旬。','观测覆盖：2025年10月2日至2026年1月6日；确切定植日待补。','秋季观测范围')
t=replace(t,'后期受低温寡照、早霜冷害胁迫，植株生长与采收期较短（仅有效采收 3 茬，总产在 12~19 t/ha 之间）。','真实采收3批，日期为2025-11-21、2025-12-11、2026-01-05；背景中的低温、早霜等机制须气象与田间记录支持，累计产量以Excel计算。','秋季批次及未经确认的产量背景')
t=replace(t,'项目内所有实测原始数据与清洗后的结构化数据集中存放于以下路径，AI 协作者可直接依据文件路径定位读取：','本次权威实测输入位于 `D:\\三季节数据汇总\\2025春`、`2025秋`、`2026春`。下方是参考项目目录结构；其中CSV/TMX/TMA/TMT须依据当前Excel重新生成并核对后使用，不能默认已同步。','源数据优先级')
t=t.replace('← 核心实验原始 Excel 测定表格 (最全源数据)','← 参考Excel目录；与当前权威工作区比较后人工同步')
t=t.replace('(包含0502/0602/0629/0717共4期详实取样)','(只使用2026生长指标汇总，含05-02/06-02/06-29/07-17四期)').replace('(全区 8 茬分批采收鲜产明细)','(实际5批采收，05-26至07-17)').replace('(各期土壤无机氮及养分变动)','(36条养分汇总；无机氮暂缓，未记日期/重复)')
t=replace(t,'每次采样均包含各处理的 3 次独立重复植株：','每次按Excel实有的生物学重复和表注取样；破坏性取样跨日期并非同一植株，不能仅凭同重复号视为同株连续观测：','破坏性取样')
t=replace(t,'单株叶片干重折合单位面积生物量（kg/ha）。','原始记录一般为g/株；转换到DSSAT面积生物量LWAD（kg/ha）时需经核定的密度。','叶干重量纲')
t=replace(t,'包含主茎与侧枝的木质化结构干重（kg/ha）。','原始干重一般为g/株；转换到SWAD（kg/ha）需乘种植密度（株/ha）再除1000。','茎干重量纲')
t=replace(t,'2025年春季（25SP）：从 5月20日（DAP 65）至 7月11日（DAP 117），共计进行 **10 次采收**。','2025年春季（25SP）：**9次**，2025-05-20、05-26、06-02、06-07、06-12、06-19、06-24、07-03、07-11；定植日未核定，不冻结DAP。','25春真实采收日期')
t=replace(t,'2026年春季（26SP）：从 5月18日 至 7月15日，共计进行 **8 次连续采收**。','2025年秋季（25FA）：**3次**，2025-11-21、2025-12-11、2026-01-05。\n   * 2026年春季（26SP）：**5次**，2026-05-26、06-07、06-16、07-01、07-17。\n   * 按用户确认的本项目TMX生成约定，最后真实采收后再加一次虚拟采收，用作模型输出辅助。它不增加真实批次、不生成观测值、不计入实际累计鲜重/产量；具体虚拟日期和操作参数在制作TMX时确定。','26春批次和虚拟操作')
t=replace(t,'记录每个小区各种植行的采收重量（kg）。','直接采用Excel的产量列（kg/ha），按有效采收株数修正的多个换算系数保留；“果实总重”是其上游量，未核定其称重口径前不按kg直接替代产量列。','实际产量量纲')
t=t.replace('| mg/g FW 或 % |','| mg/g（三季，用户确认） |').replace('| mg/g FW |','| mg/g（三季，用户确认；鲜/干基按实验记录） |')
t=t.replace('| mg/100g FW |','| 25春mg/kg；其他季按表头及确认口径 |').replace('| mg/g 或 OD 值 |','| 吸光度（OD） |').replace('| OD/g 或 mg/100g |','| 吸光度（OD） |')
t=replace(t,'* **重复与标准差**：每个处理以 3 个独立重复小区的平均值（Mean）代表该处理水平，变异程度以标准差（SD）或标准误（SE）表达。','* **重复与标准差**：各处理按指标、日期的实际生物学重复数报告Mean、SD和有效n；不把SPAD技术读数当独立生物学重复。已聚合的26春土壤养分不能反推出SD/SE。','统计单位')
t=replace(t,'**2025-07-11（DAP 117）**','**2025-07-11**（真实采收末日；DAP待确切定植日）','采收截止DAP')
t=t.replace('[原始高维评价指标矩阵 X (35处理 × 10指标)]','[按保留范围构建的指标矩阵 X（实际处理/季节数 × 实际有效指标数）]')
t=t.replace('| 叶片干重 | kg/ha | 70 ~ 1700 |','| 叶片干重 | 原始g/株；LWAD转换后kg/ha | 按实测分布核查 |').replace('| 茎秆干重 | kg/ha | 80 ~ 3000 |','| 茎秆干重 | 原始g/株；SWAD转换后kg/ha | 按实测分布核查 |').replace('| 地上部营养干重总和 | kg/ha | 180 ~ 4500 |','| 地上部营养干重总和 | 原始g/株；CWAD转换后kg/ha | 按实测分布核查 |')
t=t.replace('| 鲜果采收累计产量 | t/ha | 12 ~ 78 |','| 鲜果采收累计产量 | Excel kg/ha；展示t/ha需除1000 | 按Excel累计 |').replace('| 果实维生素 C | mg/100g FW | 80 ~ 260 |','| 果实维生素 C | 25春mg/kg；其他季核定 | 按本季实测分布 |')
t=t.replace('| 果实总酚吸光度/含量 | OD 或 mg/g |','| 果实总酚吸光度 | OD |').replace('| 果实类黄酮吸光度/含量 | OD 或 mg/g |','| 果实类黄酮吸光度 | OD |').replace('| 果实花青素吸光度/含量 | OD 或 mg/g |','| 果实花青素吸光度 | OD |')
t=replace(t,'优先从结构化 CSV 文件或规范格式的','优先从当前权威Excel读取，CSV须与当前Excel重新核对；使用','Excel优先于CSV')
t=replace(t,'严禁机械插值为 0，应采用同处理同重复的有效观测值或均值对齐。','保留缺失，不新增均值填补；只保留用户已经确认的替代值并标记来源。同号破坏性样株跨日期不得用另一日期值冒充补测。','缺测处理')
t+='\n> 字段字典中的典型范围只作历史背景，不作为自动删值阈值。植株挂果指标本次不纳入后续分析；叶量/LAI末期下降可源于整枝打杈。任何衍生干果产量须标为估算，25秋品质表半果水分缺测不能视为0或以别季值冒充。\n'
p.write_text(t,encoding='utf8')
p=ROOT/'数据分析方案.md';t=p.read_text(encoding='utf8')
top='''# 当前数据执行约定（2026-10-07）

本方案的方法建议须服从当前Excel和用户确认的数据口径。先完成 `数据质控_20261007/更新数据核对与统计筛查.xlsx` 的人工核对，再开展正式推断分析。

- 2025春排除小区1、6、7、8、9、14，只分析2、3、4、5、10、11、12、13；该季不具备完整W1/W2/W3三水平，不能把弃用处理填补回完整设计。
- 同季按小区号对齐，跨季同号不代表同处理。26春品质首期B列为样本流水编号口径，跨表关联需使用水氮处理及经确认的样本层级；不直接将1–48当小区号。
- 各指标实际生物学重复数可不同，按有效n报告。秋SPAD建议按表内前三次技术读数计算生物学重复均值，仅建议排除第四次6个有效读数；原表尚未删，不能把180次读数当180个生物学重复。
- 破坏性取样不同日期不是同株，不因重复编号相同直接使用同株重复测量模型。26春土壤养分已为汇总，不能将3个土层当作3个独立重复。
- 三季糖、蛋白mg/g；总酚、黄酮、花青素为吸光度；25春Vc mg/kg；Excel产量kg/ha；原始干重一般g/株，面积生物量另用核定密度换算。
- 生长只用26春汇总页。25春6月9日/21日整枝空行弃用；叶量末期下降不判错。植株挂果指标及附加W4/NN处理不参与本次分析。
- 采收按实际Excel：25春9次、25秋3次（11月21日/12月11日/次年1月5日）、26春5次（5月26日/6月7日/6月16日/7月1日/7月17日）。秋生长和NPK到2026年1月6日。未来TMX最后真实采收后加虚拟采收，仅作模型辅助，不计入真实批次或产量。
- 缺测保留，不自动填补。已确认均值替代和手填值保留并标记；外部公式只用当前缓存。20260106土壤水分已按湿/干重×100、盒重g重算，25春C257已按用户指定反算为6702，手填E257保留。
- 无机氮数据暂缓；气象、逐次灌溉施肥、实际面积、确切定植日期后续补充。温室降雨0；输入不足时不从旧文档直接取数计算ET/WUE/PFP或DAT。使用吸光度跨季比较时另核实验条件，不能自动称为浓度。
- 产量按Excel已有换算结果，有效采收株数产生的多个系数保留；分析使用实测采收表，不使用植株在某取样日的挂果存量。下方涉及果位/分枝/挂果等扩展分析，仅在另有适用采收观测且用户采用时开展。

---

'''
t=top+t
t=t.replace('假设你的试验是3个灌水水平×3或4个施氮水平×3个重复，那么原始数据必须保留到：','原始数据保留到实际水氮组合、实际生物学重复和日期/阶段；不强制每期每指标3个重复，也不补齐弃用的2025春W2：')
t=t.replace('> 水 × 氮 × 时间的混合模型/重复测量模型','> 水 × 氮 × 时间模型，并依据实际随机化与实验单位设置随机效应。只有有证据证明同一对象连续测定，才对该对象使用重复测量相关结构；破坏性取样各日期是不同植株。')
t=t.replace('有完整重复数据时采用混合模型更合适。','若试验设计支持可采用混合模型；技术读数先汇总至生物学重复，破坏性取样不按同株重复测量建模。')
t=t.replace('横轴建议用DAT，纵轴kg/ha。','横轴在确切定植日补齐后可用DAT，目前先用真实日期；纵轴若用kg/ha，须先把g/株按核定种植密度换算。')
t=t.replace('如果你下一步把**设施茄子现有的原始Excel数据/数据目录发给我**，我可以进一步按照这套方案帮你做成一份更具体的 **“已有数据—缺失数据—计算指标—统计方法—出图—出表—对应章节”一一对应的分析任务清单**，这样你就可以直接从第一项开始往下执行。','当前Excel目录已经复核。下一步由研究者处理更新统计筛查表，并补齐管理与气象等分析输入；随后按各指标实际覆盖开展分析。')
p.write_text(t,encoding='utf8')
conflicts.append(['数据分析方案.md','实际范围/重复/单位/时间模型','旧方案按通用完整设计、同株重复测量、固定DAT构想','已加入当前执行约定，纠正破坏性跨期关系和质量单位','已更新；方法框架保留'])
csvout('Excel与说明文件冲突清单.csv',['文件','事项','旧说明','当前口径/修订说明','状态'],conflicts)

# A durable, self-contained report, with every historical issue kept for traceability.
spadtable='\n'.join(f'| {x[2]} | {x[4]} | {x[5]}{x[6]} | {x[7]} | {x[8]:g} | {x[12]:.4f} | {x[13]:.4f} | {x[14]:+.4f} |' for x in D['spad'])
diffstable='\n'.join(f'| {a} | {b:.12g} | {c:.12g} |' for a,b,c in season_diffs)
screencounts=collections.Counter(x[0] for x in D['screens']); distinct=collections.defaultdict(set)
for x in D['screens']:distinct[x[0]].add(tuple(x[:3]))
screentable='\n'.join(f'| {f} | {len(distinct[f])} | {n} |' for f,n in screencounts.items())
statustable='\n'.join('| '+' | '.join(x[:4])+' |' for x in status)
report=f'''# 三季数据复核与更新报告

复核日期：2026-10-07。依据当前Excel及用户对Q01–Q37的逐项回复。本报告和配套新核对表替代10月3日的待处理结论；旧记录保留为历史证据。当前19个Excel、22个工作表均已读取，参考目录20个Excel。辅助透视表、盒重字典不算新增测量。

## 本次落地的修订

1. `D:\\三季节数据汇总\\2025春\\2025春土壤含水量数据集.xlsx`，`Sheet1!C257`从7135改为用户指定的**6702**。这是按手填水分反算并取整的干重，不是找回的原始称重。`E257={verification['C257_manual_moisture']['stored_E257']:.15g}`及G257保留。取整重量复算约{verification['C257_manual_moisture']['recomputed_from_rounded_weight']:.9f}，小差由取整产生，继续以用户指定手填E257为准。
2. `D:\\三季节数据汇总\\2025秋\\20260106_2号棚取土.xlsx`，`Sheet1!H2:H241`的240条公式统一为`=(C-D)/(D-B*100)`，公式缓存同时更新。湿/干重原数是实际克数×100，盒重仍为克；原始称重没有改写。首条0.158125790→**0.205161290**。新水分范围{verification['soil_240_recalculated']['min']:.6f}–{verification['soil_240_recalculated']['max']:.6f}，相对旧结果增加{min(waterdiff):.2%}–{max(waterdiff):.2%}。
3. 两个源Excel修改前均已备份至`修订前备份`；两文件分别只有C257和240个H单元格发生变化，外链、其他公式/缓存和其他包内部件保留。其余17个源Excel没有本次改动，参照Excel均未改动。
4. 说明文档的采收批次、秋季跨年、Excel权威性、单位、实际重复数、破坏性取样和TMX虚拟操作已更新，旧版也已备份。历史背景管理数值标为待核定，不以其代替将来补齐的记录。

## 已核实用户修改和采用口径

- 秋生长株高F86/F95/F97/F100为114/124/126/131；株高本次未改。当前该表株高无缺失、没有原1301尺度问题。
- 2026生长仅存`2026生长指标汇总`，144行四期；旧日期页及其内部冲突已经不存在。
- 2025春初始土壤错误新增映射列已删除，剩13列；同一季节按小区号对齐。水分控制组旧编码已修正。原97项文本重量已数值化。
- **2025春**所有后续分析排除1、6、7、8、9、14，保留2、3、4、5、10、11、12、13，即W1/W3×N0–N3。原始记录保留，分析掩码见`分析范围与排除记录.csv`。其他季节不按相同编号排除。
- 25春6月9日/21日84条整枝空记录不用于分析、不补0；在保留8处理范围内有48条这种空行。附加SPAD Z1/Z2/Z3的15条测量也排除。植株挂果列不筛查、不用于后续分析；叶量下降可源于整枝打杈。
- 缺测或遗失保留缺失；已确认替代测量19项标记并保留，不列入新离群候选；另标记C257的1项反算重量。使用现有外链缓存，不刷新外部链接。
- 三季糖/蛋白统一**mg/g**（最终回复优先于早先mg/kg）；总酚/黄酮/花青素为**吸光度**；25春Vc **mg/kg**；产量**kg/ha**；原始干重一般**g/株**。仅纠正定义，不擅自对原数乘除1000。其他尚未明确的单位/鲜干基按表头保留，跨季拼接前再确认。
- 2026土壤养分为用户已处理的汇总，36条=12处理×3土层，土层不当作独立重复，无日期不做初末变化。硝态/铵态氮暂不考虑，等补季末数据。
- 不因不同日期/指标实际重复数不同而删除生物学重复；表注优先。破坏性样株跨期同号不代表同株连续测量。
- 秋真实采收2025-11-21、2025-12-11、2026-01-05；生长/NPK至2026-01-06。25春实记9批；26春实记5批：2026-05-26、06-07、06-16、07-01、07-17。多个果重到产量系数按有效采收株数修正，保留Excel产量。
- 将来制作TMX，按用户确认的项目生成约定在最后真实采收后加虚拟采收，仅模型辅助，不是新的实测批次、不计累计产量。当前未制作TMX或虚构观测。

## Q19/Q37：SPAD统一三次技术测定的建议

完整路径：`D:\\三季节数据汇总\\2025秋\\2025秋季2号棚1130日spad窄数据.xlsx`，`Sheet1`，2025-11-30。

60个生物学重复中54个有3个有效读数，6个有4个。建议统一保留**表内顺序前三次有效读数**，排除第4次的六个读数。这里的顺序仅指表内批次顺序，未声称是已确认的实际测量时间。该规则不依赖数值大小，不挑最大/最小，也不以“使方差变小”为依据。如果第4次记录有另行注明的复测替代意义，则应先按记录确认再采用。本次给出建议并计算分析视图，**原始SPAD读数未删除**。

| 建议排除位置 | 小区 | 处理 | 生物学重复 | 排除值 | 四次均值 | 三次均值 | 变化 |
|---|---:|---|---:|---:|---:|---:|---:|
{spadtable}

相对均值影响绝对值最大1.36%。原186次有效读数→建议180次→仍为60个生物学重复均值，不是180个生物学样本。54个第四次空位没有测量值，不算剔除观测。按前三次计算与原Sheet3的180读数口径一致。不同生物学重复也可以用各自全部3/4读数的均值，但用户当前要求统一3次，故采用固定顺序的可复核建议。具体保留读数和均值见核对表“SPAD建议排除”“SPAD重复均值”及CSV。

## 更新后的统计筛查（Q35）

按新范围重新计算：**217次规则触发，213个独立定位**（4个位置同时触发两种规则），取代旧343个候选位置。数量下降不代表所有旧候选都被证实错误；主要来源是弃用处理、旧日期页/列删除，以及确认填补值不再重复报错。

方法仍为同季同日期/器官/土层的3×IQR（至少12个未填补数值），以及有且仅有3个可用子样时，一值相对另外两值均值偏差>30%、另外两值相差<15%的提示。所有方法都只是人工复核线索，处理效应、小样本波动、检出限和测量精度均可触发；不作异常自动删除或显著性检验。

| 文件 | 独立候选定位数 | 规则触发数 |
|---|---:|---:|
{screentable}

“更新统计筛查”包含文件、页/分析视图、精确定位、当前值、分组、阈值、处理和重复。请在黄色“处理状态”“处理决定”列填写决定及依据；确认保留的极值保留，确证录错再改，确认缺测保留空白。未将其他测量自动删值/填补。覆盖、分期缺测数和逐行排除原因另见CSV。

## Q24/Q25：你要求的完整路径与当前状态

两项都来自历史文件：`D:\\三季节数据汇总\\2026春\\2026春生长指标集结果.xlsx`。

- **Q24**：旧`0629`页，`J3、J4、J6、J7、J19、J31、J36`，当时为7.27–23.03g的果鲜重，提问是确认称重对象，未判定为错误。
- **Q25**：旧`0602`页，`J2:J37`半果干重36个空位。

你现已删除这两张旧页。当前唯一汇总页没有这些果实测量列，因此现在查不到是正常的；两项关闭，不在新筛查表要求你处理，也不恢复旧页。

## 当前目录与参照目录的差异

实际参照路径为`D:\\Tomato_Cal\\data\\user\\ref\\DSSAT文件`；最初提供的缺少`data`路径不存在。以当前Excel为准，未自动同步任何参照文件。

当前19本、参照20本。16个同名共同文件中**15个字节完全相同，1个有1处实质值差异**：25春水分`Sheet1!C257`当前6702/参照7135，是本次按你授权新增的差异。修订前双方没有测量数值差异（仅格式/文件内部元信息不同）。Q28初始土壤及Q29的26春养分已一致；Q27旧14条称重差异已消除。旧无机氮文件已不在双方目录，Q30不再沿用旧版本数据。

当前独有3个：

- `D:\\三季节数据汇总\\2025秋\\2025秋季2号棚1130日spad窄数据.xlsx`
- `D:\\三季节数据汇总\\2025秋\\20260106_2号棚取土.xlsx`（本次重算版本）
- `D:\\三季节数据汇总\\2026春\\20260519_SPAD.xlsx`

26春器官NPK现双方相同。需备份或向参照同步上述当前文件时，使用当前版本；不要用参照目录整体覆盖当前数据。完整相同/差异表见`文件对比.csv`，本次唯一共同数值差异见`单元格差异.csv`；参照非Excel脚本、README、旧QA另列清单，不作测量值来源。

## Q31：参照独有文件逐项展开

### 1. 25春有机质估算/校准，非独立测量

完整路径：`D:\\Tomato_Cal\\data\\user\\ref\\DSSAT文件\\2025春\\2025春土壤有机质估算与校准集.xlsx`。

包含“25SP有机质逐样详表”117记录、“处理均值汇总表”39记录和“估算原理与依据”。估算用全氮g/kg除10转成TN%，假定C:N=11，SOC%=TN(g/kg)×1.1，SOM%=SOC%×1.724，即TN×1.8964，再乘校准系数。小区5、13系数1.2，小区9系数0.88，其余1。文件说明该系数用于模型产量误差校准。

这代表小区5/13（目前仍保留）有机质被再提高20%，是推算和模型校准输入，不能当作两项新的独立有机质实测，也不用于验证模型自身的产量或与TN作独立证据的相关。与26春均值相近不证明每个25春小区值真实。若模型需要，单列“估算/校准有机质”及假设，不混入实测土壤统计。当前不自动导入。

### 2. 参照25秋养分与当前26春几乎同值，需判断采样归属

完整路径：`D:\\Tomato_Cal\\data\\user\\ref\\DSSAT文件\\2025秋\\2025秋土壤养分数据集.xlsx`，`Sheet1`，36条=12小区×3层，未提供日期或重复。

在C:L十个测量字段的360个值中，**355个与当前26春养分相同**；A:B的72个小区/土层键也相同。因此A:L共432个字段中427个同值。仅以下5处不同：

| 位置 | 参照25秋 | 当前26春 |
|---|---:|---:|
{diffstable}

强相似提示可能有跨季复制、同一基准引用或季节标签待核对；它并不能单凭相似性证明抄错。请核原始取土日期、测定报告和文件用途：确为秋季独立测量才补入秋季；若是26春旧版/通用基准，保留溯源标识，不重复当秋季测量。当前26春文件双方一致，勿据此再把5个值改回参照秋季值。末两列无机氮暂缓。

### 3. 秋季另一份取土并非20260106的同名旧版

完整路径：`D:\\Tomato_Cal\\data\\user\\ref\\DSSAT文件\\2025秋\\2025 2号棚秋季取土.xlsx`。

- `20250809定植前取土`：180条=12小区×3重复×5土层（0–100cm）。湿/干重×100、盒重g，其水分公式已统一单位。H列田间持水量数如23.255表示百分数，E列含水率为小数；I列`E/H*100`得到0.871777等是相对持水量的**比例**（若显示为百分率则87.1777%）。需在使用时明确显示单位，不据此直接认定为100倍计算错误。
- `20261002`：144条=12小区×3重复×4土层（0–80cm），湿干重记录为克数。页名对应2026-10-02但位于2025秋目录且无表内日期，需判断是真正2026年10月2日还是2025-10-02页名错误。不能自动改年，也不能把少80–100cm层补0或和20260106当同批数据。

建议先核日期与用途，再决定是否补入2025秋水分时序；当前不自动同步。

### 4. 新增三季初始无机氮参考，暂不使用

完整路径：`D:\\Tomato_Cal\\data\\user\\ref\\DSSAT文件\\三季实验初始硝态氮铵态氮参考.xlsx`。

为5土层参考平均值，不含小区、重复和实测日期。80–100cm的铵态氮0.5/硝态氮1等同值不能自行判断是实测还是模型占位。按你暂不考虑无机氮的指示，本次只登记文件存在，不补入观测、不替代后续季末测定。

## 其他文件冲突及历史记录

当前两份说明文档已按Excel纠正，具体前后文字见`Excel与说明文件冲突清单.csv`。旧文档中的土壤“初始本底”、灌施肥总量、仪器方法、品种/模型参数等未在本次Excel中有足够溯源证据，已标明历史背景待核定。本文不擅自补造管理/气象或推断所有历史描述错误。

`数据质控_20261003`的审查报告和核对表为10月3日历史快照；旧QA及旧CSV/DSSAT模型观测须先同当前Excel核对，不据旧报告宣称现在仍有1301、110处内部生长冲突或519项目录差异。根目录“数据口径与质控记录.md”提供最新入口。未删除原数据或参考文件；供保留历史溯源，不作为待处理任务重复执行。

## 验证、复核入口和仍待处理项

- 读取19本22页，错误缓存0；{checked}个简单内部算术公式独立复算，无缓存不一致。{unsupported}个复杂函数/外链保留缓存，不声称全部独立重算；{blanks}项空缓存来自辅助公式，未当原始测量缺失。240条新水分公式另外全部独立验证。
- 所有取土240条满足湿重≥干重且扣除盒重后干土质量正；两春1350条重量水分×容重与体积水分一致，水分在0–1内。土壤持水量不是机械剔除上限。
- 19项用户确认替代测量、1项反算重量均有来源标记；候选表不含这些位置、弃用2025春小区、整枝空日期或附加SPAD处理。
- **待你处理**：213个统计候选位置；是否采用六个SPAD排除建议；Q31参照独有资料的季节/用途；Q04首批品质编号跨表的物理身份（处理内本次筛查已用水氮+重复，未猜小区号）；土壤日期/始末状态和其他未明确单位在正式跨季分析前确认。
- **待后续补**：管理、气象、实际面积/有效株数记录、确切定植日及季末无机氮。温室降雨0已记录，不妨碍本次筛查，但目前不足以完成水量平衡、投入效率或DAT。
- 核对工作簿：`更新数据核对与统计筛查.xlsx`；报告外的全量CSV涵盖分期范围、缺测/数值概况、文件差异和SPAD逐次读数。`数据质控复核.ipynb`为只读复核入口，不执行源文件改写。

## Q01–Q37本次状态总表

| 编号 | 本次状态 | 事项 | 处理或依据 |
|---|---|---|---|
{statustable}
'''
(OUT/'复核更新报告.md').write_text(report,encoding='utf8')
(ROOT/'数据口径与质控记录.md').write_text('''# 当前数据口径与质控记录

更新：2026-10-07。当前Excel和用户最新确认是权威来源。最新报告：[复核更新报告](数据质控_20261007/复核更新报告.md)；当前人工清单：[更新数据核对与统计筛查](数据质控_20261007/更新数据核对与统计筛查.xlsx)。

已修改25春水分C257=6702及秋季20260106取土240个含水率公式，完整源文件备份在最新质控目录“修订前备份”。2025春弃用小区1、6、7、8、9、14。三季糖/蛋白mg/g，酚/黄酮/花青素为吸光度。SPAD建议排除六个第4次有效读数，原表未删除。

20261003目录及参考项目旧QA仅作历史快照，不再代表当前待处理问题，不据其执行旧值回填或删除。若其他CSV、TMX/TMA/TMT或说明与当前Excel冲突，以Excel为准并重新生成/核对衍生数据。尚未完成新的正式统计分析，候选值等待人工确认。
''',encoding='utf8')
old=ROOT/'数据质控_20261003'/'数据清洗检查报告.md';ot=old.read_text(encoding='utf8')
banner='> **历史快照，已由2026-10-07复核替代。** 以下值和待处理状态仅对应10月3日文件，不代表当前数据。最新入口：[复核更新报告](../数据质控_20261007/复核更新报告.md)。\n\n'
if banner not in ot:old.write_text(banner+ot,encoding='utf8')
(ROOT/'数据质控_20261003'/'历史记录说明.md').write_text('本目录全部Excel/CSV/JSON/报告为2026-10-03历史审查快照。当前任务以 ../数据质控_20261007 的报告、核对表和当前数据口径为准，不将本目录候选或历史源数据值再次回填到当前Excel。历史证据保留，未重算本目录。\n',encoding='utf8')
nb={'cells':[{'cell_type':'markdown','metadata':{},'source':['# 2026-10-07当前数据只读复核\n','当前Excel为准；本笔记本仅读取源数据并在质控目录更新快照/筛查输出，不执行C257或水分公式改写。SPAD前三次为建议分析视图，原读数保留。']},{'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],'source':["from pathlib import Path\nimport json, runpy\nROOT=Path(r'D:\\三季节数据汇总'); OUT=ROOT/'数据质控_20261007'\nrunpy.run_path(str(OUT/'reinspect.py'),run_name='__main__')\n"]},{'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],'source':["runpy.run_path(str(OUT/'update_analysis.py'),run_name='__main__')\nd=json.loads((OUT/'reviewed_results.json').read_text(encoding='utf8'))\nd['summary']\n"]},{'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],'source':["from openpyxl import load_workbook\nbook=load_workbook(ROOT/'2025秋'/'20260106_2号棚取土.xlsx',data_only=True,read_only=True)\ns=book['Sheet1']\nfor row in range(2,242):\n    b,c,d,h=[s[f'{col}{row}'].value for col in ['B','C','D','H']]\n    assert abs(h-(c-d)/(d-b*100))<1e-12\nbook.close()\nprint('240条水分复算通过；新公式使用统一重量单位')\n"]}], 'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.12'}},'nbformat':4,'nbformat_minor':5}
(OUT/'数据质控复核.ipynb').write_text(json.dumps(nb,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'verification':verification,'summary':D['summary'],'document_conflicts_corrected':len(conflicts),'status_rows':len(status),'reports_written':True},ensure_ascii=False,indent=2))
