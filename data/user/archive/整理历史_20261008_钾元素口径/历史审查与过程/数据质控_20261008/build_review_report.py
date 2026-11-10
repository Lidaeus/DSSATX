from pathlib import Path
import json,csv,collections,statistics,hashlib,datetime
ROOT=Path(r'D:\三季节数据汇总');OUT=ROOT/'数据质控_20261008';REF=Path(r'D:\Tomato_Cal\data\user\ref\DSSAT文件')
u=json.loads((OUT/'复查汇总.json').read_text('utf-8'));d=json.loads((OUT/'专项复核结果.json').read_text('utf-8'));s=json.loads((OUT/'snapshot.json').read_text('utf-8'))
def val(s,a):return s['formulas'][a]['cached'] if a in s['formulas'] else s['cells'].get(a)
def link(p,label=None):return '['+(label or p.name)+'](<'+str(p).replace('\\','/')+'>)'
def fmt(v):return f'{v:.9g}' if isinstance(v,(int,float)) else str(v)
def table(head,rows):return '\n'.join(['| '+' | '.join(head)+' |','|'+'|'.join(['---']*len(head))+'|']+['| '+' | '.join(str(v).replace('|','／').replace('\n',' ') for v in r)+' |' for r in rows])
q25='2025春\\2025春品质集优先采用品质集中的果实含水率.xlsx';q26='2026春\\2026春品质指标集.xlsx';npk='2026春\\2026春茎叶果氮磷钾.xlsx';soil='2026春\\2026春土壤养分数据集.xlsx'
old=json.loads((ROOT/'数据质控_20261007'/'snapshot.json').read_text('utf-8'))['current']
scan=list(csv.reader((OUT/'人工审核状态与当前源值.csv').open(encoding='utf-8-sig')))[1:]
still=[x for x in scan if x[16]=='已修正' and x[19]=='False']
counter=collections.Counter(x[1] for x in u['comparison'])
diff=list(csv.reader((OUT/'两目录单元格差异.csv').open(encoding='utf-8-sig')))[1:]
main_diff=collections.Counter(x[0] for x in diff if x[1]=='Sheet1')
ndiff=[x for x in diff if x[1]=='Sheet1']
scope25=[x for x in ndiff if x[0]==q25 and s['current'][q25]['sheets']['Sheet1']['cells'].get('B'+''.join(filter(str.isdigit,x[2]))) not in {1,6,7,8,9,14}]
spadtable=list(csv.reader((OUT/'SPAD处理均值方案对比.csv').open(encoding='utf-8-sig')))[1:]
maximpact=max(abs(float(x[4])-float(x[3])) for x in spadtable)
issues=[
 ['R01','高／确定',str(ROOT/npk),'Sheet1!H362','=F362*0.93 引用日期20260717，得18842466.81 mg/g','按原始测定/修正记录重新确定全磷值；两目录都有该错误，不能靠同步修复'],
 ['R02','高／引用确定，真值待核',str(ROOT/npk),'Sheet1!I362','=G362*0.93引用全氮29.994133，得全钾27.894544','核全钾独立原记录；不要用全氮推算全钾。上次全钾64.120300仅供定位，不能自动回填'],
 ['R03','中／确定',str(ROOT/soil),'Sheet1!G30/K30','G30已改189.697318；K30仍0.726647392；其他35行均满足G/K=391','若同一换算口径，K30对应0.485159380；核公式或独立测量口径后手动处理'],
 ['R04','中／确定',str(ROOT/q26),'Sheet2!C19/C16/C21','源I61已变，Vc透视求和仍为修正前值','手动刷新本地透视表并核对范围；展示处理浓度时用重复均值，当前页为求和'],
 ['R05','高／版本不一致确定',str(ROOT/q25),'Sheet1与参照同名文件','当前为10/03旧版本，参照10/08已修正；原始页28个位置不同','按较新时间优先核参照版本，备份旧版本后手动同步到当前'],
 ['R06','中／方法需说明',str(ROOT/soil),'Sheet1!E30/F30/G30','AVERAGE引用同土层其他11个小区，跨水氮处理；不是同处理重复均值','如保留，标记为同层跨小区估计值；确认初始土壤背景假设。避免作为小区独立实测值解释'],
 ['R07','中／记录需确认',str(ROOT/q25),'Sheet1!I29（及'+npk+' Sheet1!I374）','审核表标已修正，但当前、参照及上次快照都同值','确认是原记录复核后认可、另有文件未同步，还是修改尚未保存；不要求为改而改'],
 ['R08','低／统计提示',str(ROOT/soil),'Sheet1!F34','AP=20.856715；原值未变，在F30均值替代后新触发3×IQR','仅提醒查原记录；阈值变化不证明原值错误，先保留'],
]
with (OUT/'需核对问题清单.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.writer(f);w.writerow(['编号','严重性与证据','完整路径','位置','问题','处理建议']);w.writerows(issues)
lines=['# 2026-10-08只读复查与文件一致性报告','',
'本次只读取现有源数据及人工审核表，新增报告和明细文件；未修改、同步、删除任何原始Excel或原审核表。输入文件前后哈希保持一致。保存时间均为北京时间（UTC+8），使用文件最后修改时间，不把该时间当作测量日期。', '',
'检查范围：当前三季数据19份Excel／23页，参照目录20份Excel；同相对路径16对。读取人工审核表217条：196条保留原值、21条已修正、无待审。当前季节数据文件和参照目录的其他文件列在文件清单；历史质控目录、缓存、备份不作为待同步源数据。当前根目录3份说明Markdown不与参照生成脚本强行配对。', '',
'## 需要先处理的问题', '',
table(['编号','文件/位置','发现与建议'],[[x[0],x[2]+'／'+x[3],x[4]+'。'+x[5]] for x in issues]), '',
'R01/R02对应2026-07-17，小区1、重复1、W3N3、茎杆。完整参照路径也存在完全相同的公式：'+str(REF/npk)+'。上次快照H362=2.6864406779661、I362=64.1202995628348，当前全氮G362=29.9941329856584。如果本意是将各自旧指标乘0.93，则数学上分别为'+fmt(val(old[npk]['sheets']['Sheet1'],'H362')*.93)+'和'+fmt(val(old[npk]['sheets']['Sheet1'],'I362')*.93)+'；这只是对“下降7%”假设的演算，不是已核实的替代建议。需要你的原始记录确认。', '',
'R03中G30是AK（mg/kg）、K30是速效钾另一单位。其他35行的G/K均为391，但此行K仍对应修改前G30=284.119130239409。先明确K是否由G换算；若是，应联动更新；若K独立测得，记录不同口径。', '',
'R04具体核对：', '',table(['位置','保存的汇总值','当前源表复算值'],[[x[2],fmt(x[3]),fmt(x[4])] for x in d['pivot_checks'][:3]]), '',
'2025春参照品质Sheet2花青素总计10.068与当前原表合计一致，本次未发现总计过期。但该透视表仍包含W2、CK、CKS等已指定弃用处理；它可留作原始全表汇总，不能直接代表最终有效试验范围。2026品质页标“求和项:Vc”，是浓度数值求和，若用作处理浓度应取重复均值。', '',
'## 两目录版本对照', '',
f'16对同名Excel：14对字节完全一致，2对内容不同。另当前单侧3份、参照单侧4份Excel。品质文件差异包含原始页与透视页，原始数据的差异远少于全工作簿单元格差异。', '',
table(['文件','当前保存时间','参照保存时间','原始Sheet1差异','建议方向'],[[x[0],x[2],x[3],main_diff[x[0]],'参照 → 当前' if x[0]==q25 else '当前 → 参照'] for x in u['comparison'] if x[1]=='数据或工作表不一致']), '',
f'25春品质：原始Sheet1有28个位置不同（Vc 25个、M54花青素、I73蛋白、G56糖），其中{len(scope25)}个在当前认可的2025春有效小区范围内。参照另外新增Sheet2，共51个透视内容单元格；全工作簿79个值差异。G56由11.4811133200795变成一个空格，属于弃用小区6，不影响本次有效范围；读取时应当作缺失，不能当0或数值。参考较新版本是合理同步方向，但新版本仍要保留原测定依据。', '',
'26春品质：原始Sheet1只有I61不同：当前公式=AVERAGE(I59:I60)、缓存222.124469371958；参照304.488281805781。当前新增Sheet2共39个内容单元格，全工作簿40个值差异、1个公式差异。当前版本较新；同步后也需处理本报告的透视未刷新问题。', '',
'2026春器官NPK两端最新文件已字节完全一致，但含R01/R02；“一致”不代表“正确”。仅看保存时间也不能识别日期列误引用。', '',
'单侧Excel完整路径：', '',
table(['侧别','文件'],[['仅当前',str(ROOT/x[0])] if x[1]=='仅当前目录存在' else ['仅参照',str(REF/x[0])] for x in u['comparison'] if x[1].startswith('仅')]), '',
'当前独有的两份SPAD及20260106取土可按你的资料同步范围手动补入参照。参照独有的有机质校准、2025秋土壤养分、旧取土和三季无机氮参考应先核用途：名称不同、时间不同不能自动当作同一份文件的新旧版本；无机氮按既定口径暂不纳入分析。参照其他11个非Excel文件（脚本、说明、旧QA）列在清单，不按脚本更新时间替代实测数据。', '',
'完整逐文件清单：'+link(OUT/'两目录Excel对比.csv')+'；逐单元格内容：'+link(OUT/'两目录单元格差异.csv')+'；其他文件：'+link(OUT/'两目录文件清单.csv')+'。', '',
'## SPAD重复测量的排除依据', '',
'建议优先保留全部有效技术读数，先在每个生物学重复内平均，再比较水氮处理；3次与4次技术测量并不自动造成生物学重复不平衡。不得把同一植株的3/4次读数作为3/4个独立生物重复。', '',
'“距均值最远”适合提示核查，不足以直接证明测量失败；在只有4次测量时，每组机械删最远者会人为压缩组内变异。“不符合水氮规律”更不适合作为删除条件，会使结果向预期响应靠拢。NIST明确区分可疑点与已证实错误，无法确定错误时不建议简单删除；仪器厂家指出叶内位置和叶脉可带来读数差异，测量位置应统一并尽量避开叶脉。来源：[NIST异常值指南](https://itl.nist.gov/div898/handbook/eda/section3/eda35h.htm)、[Konica Minolta SPAD测点说明](https://www.konicaminolta.jp/instruments/support/faq/detail/p10/)。', '',
'此前“保留前三次”的建议是按表内顺序统一读数数目，不是判定第4次异常；表中顺序也不自动等同真实测量时间。现在更建议以全部有效读数的生物学重复均值作为主方案，前三次方案作为敏感性对照。若仍必须统一3次，应在看处理趋势前用记录明确的测点/测量顺序或固定随机抽样方案统一选择，并记录规则；有明确仪器、夹叶、叶脉、错误叶位等失败记录时才优先剔除对应读数。', '',
f'现有2025秋SPAD：186次有效读数、60个生物学重复组，54组3次、6组4次。六个四读数组CV仅约1.64%–4.15%，未仅凭这些偏差确认测量失败。保留前三次相对四次均值的单组变化为−0.691667至+0.766667 SPAD；折算到每处理5个生物学重复后，处理均值最大变化{maximpact:.6f} SPAD。这里只比较数值，不宣称显著性结论相同。', '',
table(['小区/水氮/重复','四次读数','四次均值','前三次均值','最远读数位置（仅对照）','删最远后的均值'],[[f'{x[0]}/{x[1]}{x[2]}/重复{x[3]}',x[4],fmt(x[6]),fmt(x[7]),x[9],fmt(x[11])] for x in d['spad_sensitivity']]), '',
'前三次排除位置F192、F198、F199、F202、F203、F210；算法最远位置分别F132、F18、F199、F202、F23、F90。这些位置用于说明规则会产生不同选择，**不是本次建议删去最远值**。原始位置在'+str(ROOT/'2025秋'/'2025秋季2号棚1130日spad窄数据.xlsx')+'，Sheet1。', '',
'SPAD详细方案对照：'+link(OUT/'SPAD六组方案敏感性.csv')+'；处理均值对照：'+link(OUT/'SPAD处理均值方案对比.csv')+'。', '',
'## 已完成复核及方法边界', '',
table(['季节生长表','有效株高数','范围','缺失'],[[x[0],x[2],f'{x[3]}–{x[4]}','无' if not x[5] else x[5]] for x in d['height']]), '',
'上述25春计数已按弃用小区及整枝专用日期排除。三季未发现新的小区号→水氮组合冲突；2026首批品质样本号仍单独按水氮及重复对齐。原有不同日期重复数、破坏性取样、跨年日期、整枝叶量下降、未使用挂果数及既定缺测，未重新当成待纠正错误。', '',
f'读取现有公式缓存，不更新外部链接。共复算{d["formula_checked"]}个可支持的本地算术/AVERAGE/SUM公式，缓存不一致0个，缺失缓存0个；另{d["formula_skipped"]}个外部、跨页或不支持的公式只读取现有缓存，未宣称完整验证。这说明H362算术计算成功，错误在指标引用逻辑，不能只依赖“Excel无报错”判断。', '',
'按上次规则重新筛查仍有207条命中／203个位置，这是统计提示，包含你已审核且决定保留的记录；不把“还会触发筛查”当作未完成清洗。本次新增定位只有F34、H362、I362，其中F34为阈值改变导致的提示。25春当前仍是旧品质版本，其已修正审核标签不能代替真正数据同步。', '',
'新增/确认均值填补：2025秋NPK E141/F141/G141为同处理其余3次均值；2026品质I61为其余2次均值；2026土壤E30/F30/G30为同深度其他11个小区均值。它们在最终分析中应保留来源标记，不能当作新增独立实测信息。', '',
'审核表标“已修正”但当前源数值未变的位置：', '',
table(['文件','位置','当前值','参照值','解释'],[[x[0],x[2],x[18],fmt(val(s['reference'][x[0]]['sheets']['Sheet1'],x[2])),'较新参照有变化，待同步' if x[0]==q25 and str(val(s['reference'][x[0]]['sheets']['Sheet1'],x[2]))!=x[18] else '两侧与上次均同值，需确认该标签含义'] for x in still]), '',
'筛查表旧“值”列与以前预审意见仍是当时快照，不能用它自动回填已经修正的源表。本次按只读要求未刷新原审核表、旧CSV或旧预审建议；新报告才反映本次读取状态。', '',
'## 可核查依据', '',
'源文件与保存时间清单：'+link(OUT/'两目录Excel对比.csv')+'。问题清单：'+link(OUT/'需核对问题清单.csv')+'。本地修改定位：'+link(OUT/'相对上次快照的修改.csv')+'。关键复核可在'+link(OUT/'只读复核.ipynb')+'重复查看。', '',
'结论适用到本次读取的已保存Excel；不包含未保存的活动Excel编辑、未提供仪器原始记录或新的显著性分析。']
(OUT/'只读复查与同步差异报告.md').write_text('\n'.join(lines),'utf-8')
cells=[{'cell_type':'markdown','metadata':{},'source':['# 2026-10-08只读关键复核\n','仅读取Excel与校验文件字节，不写入工作簿。运行目录与输出目录均为本次质控目录。']},
{'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],'source':['from pathlib import Path\n','import hashlib, json, statistics, openpyxl\n',"ROOT=Path(r'D:\\三季节数据汇总')\n","OUT=ROOT/'数据质控_20261008'\n","saved=json.loads((OUT/'复查汇总.json').read_text('utf-8'))\n","changed=[p for p,h in saved['source_sha256'].items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]\n","print('输入相对本次快照已改变的文件:', changed)\n"]},
{'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],'source':["w=openpyxl.load_workbook(ROOT/'2026春'/'2026春茎叶果氮磷钾.xlsx', data_only=False)\n","s=w['Sheet1']\n","print('H362公式/日期:',s['H362'].value,s['F362'].value)\n","print('I362公式/引用全氮:',s['I362'].value,s['G362'].value)\n","w.close()\n","w=openpyxl.load_workbook(ROOT/'2026春'/'2026春土壤养分数据集.xlsx',data_only=True)\n","s=w['Sheet1']\n","print('K30保存值/同表换算G30÷391:',s['K30'].value,s['G30'].value/391)\n","w.close()\n"]},
{'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],'source':["w=openpyxl.load_workbook(ROOT/'2026春'/'2026春品质指标集.xlsx',data_only=True)\n","s=w['Sheet1'];p=w['Sheet2']\n","print('透视C19 / 当前I59:I61合计:', p['C19'].value,sum(s[f'I{r}'].value for r in [59,60,61]))\n","w.close()\n"]}]
nb={'cells':cells,'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'},'language_info':{'name':'python','version':'3.13'}},'nbformat':4,'nbformat_minor':5}
(OUT/'只读复核.ipynb').write_text(json.dumps(nb,ensure_ascii=False,indent=2),'utf-8')
unchanged=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in u['source_sha256'].items())
assert unchanged
(OUT/'只读验证记录.json').write_text(json.dumps({'date':'2026-10-08','all_input_hashes_unchanged':True,'input_files_checked':len(u['source_sha256']),'review_table_not_modified':True,'source_workbooks_not_modified':True,'directory_sync_performed':False,'report':str(OUT/'只读复查与同步差异报告.md')},ensure_ascii=False,indent=2),'utf-8')
print('报告写出；输入文件全部未更改。关键问题8类，14对一致，2对内容不同。')
