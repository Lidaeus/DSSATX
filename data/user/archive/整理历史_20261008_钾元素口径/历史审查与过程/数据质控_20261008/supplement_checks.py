from pathlib import Path
import json,csv,re,ast,collections,statistics,math,hashlib
from openpyxl.utils.cell import get_column_letter,range_boundaries
ROOT=Path(r'D:\三季节数据汇总');OUT=ROOT/'数据质控_20261008'
S=json.loads((OUT/'snapshot.json').read_text('utf-8'));C=S['current'];R=S['reference']
U=json.loads((OUT/'复查汇总.json').read_text('utf-8'))
def v(s,a):return s['formulas'][a]['cached'] if a in s.get('formulas',{}) else s.get('cells',{}).get(a)
def csvout(name,head,rows):
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(head);w.writerows(rows)
def book(suffix,kind=C):return next((f,kind[f]['sheets']) for f in kind if f.endswith(suffix))
formula_checks=[];formula_bad=[];skipped=[];uncached=[];fills=[]
for f,w in C.items():
 for n,s in w['sheets'].items():
  for a,fo in s['formulas'].items():
   expr=fo['formula'][1:].replace('$','')
   if fo['cached'] is None:uncached.append([f,n,a,fo['formula']]);continue
   if '[' in expr or '!' in expr:skipped.append([f,n,a,'外部或跨页公式：按用户口径只读取缓存']);continue
   def average(m):
    vals=[];addrs=[]
    for token in m.group(2).split(','):
     token=token.strip()
     if ':' in token:
      c1,r1,c2,r2=range_boundaries(token)
      addrs.extend(get_column_letter(c)+str(r) for r in range(r1,r2+1) for c in range(c1,c2+1))
     else:addrs.append(token)
    vals=[v(s,k) for k in addrs if isinstance(v(s,k),(int,float))]
    if m.group(1)=='AVERAGE':
     fills.append([f,n,a,fo['formula'],fo['cached'],len(vals),';'.join(addrs)])
     return repr(statistics.mean(vals))
    return repr(sum(vals))
   try:
    expr=re.sub(r'\b(AVERAGE|SUM)\(([^()]*)\)',average,expr)
    expr=re.sub(r'\b[A-Z]+\d+\b',lambda m:repr(v(s,m.group()) if v(s,m.group()) is not None else 0),expr).replace('^','**')
    tree=ast.parse(expr,mode='eval')
    assert all(isinstance(t,(ast.Expression,ast.BinOp,ast.UnaryOp,ast.Constant,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow,ast.USub,ast.UAdd)) for t in ast.walk(tree))
    got=eval(compile(tree,'<read-only>','eval'),{'__builtins__':{}})
    formula_checks.append([f,n,a,fo['formula'],fo['cached'],got])
    numeric=isinstance(got,(int,float)) and isinstance(fo['cached'],(int,float))
    same=math.isclose(got,fo['cached'],rel_tol=1e-9,abs_tol=1e-9) if numeric else got==fo['cached']
    if not same:
     formula_bad.append(formula_checks[-1])
   except Exception:skipped.append([f,n,a,'不支持的公式，未宣称已复算'])
csvout('公式独立复算.csv',['文件','页','位置','公式','缓存','复算'],formula_checks)
csvout('公式缓存不一致.csv',['文件','页','位置','公式','缓存','复算'],formula_bad)
csvout('均值类公式位置.csv',['文件','页','位置','公式（并非全部属于填补）','缓存','参与数值数','引用位置'],fills)
obsolete=OUT/'均值公式填补位置.csv'
if obsolete.exists():obsolete.unlink()
csvout('公式未复算范围.csv',['文件','页','位置','原因'],skipped)
csvout('公式无缓存位置.csv',['文件','页','位置','公式'],uncached)

# Use the declared source schemas and user exclusion scope, not contiguous guessed headers.
tree=ast.parse((ROOT/'数据质控_20261007'/'update_analysis.py').read_text('utf-8'))
spec_node=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='specs' for t in n.targets))
assert all(not isinstance(t,ast.Name) or t.id in ['list','range'] for t in ast.walk(spec_node))
specs=eval(compile(ast.Expression(spec_node),'<schema only>','eval'),{'__builtins__':{},'list':list,'range':range})
objective=[];headers=[];mapping=collections.defaultdict(lambda:collections.defaultdict(list));coverage=[]
excluded={1,6,7,8,9,14}
for suffix,n,ids,ms in specs:
 f,ss=book(suffix);s=ss[n];count=0
 for r in range(2,s['rows']+1):
  if not any(v(s,get_column_letter(i)+str(r)) is not None for i in range(1,max(max(ids),max(ms))+1)):continue
  plot=v(s,get_column_letter(ids[1])+str(r)) if ids[1] else None
  if f.startswith('2025春') and plot in excluded:continue
  if '20260519_SPAD' in f and str(plot).startswith('Z'):continue
  count+=1
  day=v(s,get_column_letter(ids[0])+str(r)) if ids[0] else None
  if ids[3] and ids[4] and not ('2026春品质' in f and str(day)=='20260603'):
   wtr=v(s,get_column_letter(ids[3])+str(r));nit=v(s,get_column_letter(ids[4])+str(r))
   if wtr and nit:mapping[(f[:5],plot)][(wtr,nit)].append([f,n,r])
  for c in ms:
   a=get_column_letter(c)+str(r);z=v(s,a);hdr=v(s,get_column_letter(c)+'1')
   if isinstance(z,(int,float)):
    reason=None
    if z<0:reason='负测量值：需核对指标允许范围'
    if ('果含水率' in str(hdr) or '半果含水率' in str(hdr)) and not 0<=z<=1:reason='果实含水率超出0–1'
    if '全磷' in str(hdr) and '茎叶果' in f and z>1000:reason='组织全磷mg/g超过1000，且引用日期列'
    if hdr=='pH' and not 0<=z<=14:reason='pH超出通常0–14范围'
    if reason:objective.append([f,n,a,hdr,z,reason])
   elif isinstance(z,str) and z.strip():objective.append([f,n,a,hdr,z,'测量字段为非数值文本'])
 coverage.append([f,n,count])
conflicts=[[season,plot,str(list(groups)),str(dict(groups))] for (season,plot),groups in mapping.items() if len(groups)>1]
csvout('客观规则疑点.csv',['文件','页','位置','指标','值','问题'],objective)
csvout('处理映射冲突.csv',['季节','小区','处理组合','原位置'],conflicts)

# Height completeness in valid analysis scope; pruning-only dates are explicitly omitted.
height=[]
for suffix,n,c,plotcol,datecol in [('2025春作物生长指标集.xlsx','Sheet1','G','B','A'),('2025年秋季茄子生长指标集.xlsx','Sheet1','F','B','A'),('2026春生长指标集结果.xlsx','2026生长指标汇总','F','B','A')]:
 f,ss=book(suffix);s=ss[n];values=[];missing=[]
 for r in range(2,s['rows']+1):
  if v(s,plotcol+str(r)) is None:continue
  if f.startswith('2025春') and v(s,plotcol+str(r)) in excluded:continue
  day=str(v(s,datecol+str(r)))[:10]
  if f.startswith('2025春') and day in ['2025-06-09','2025-06-21']:continue
  z=v(s,c+str(r))
  if isinstance(z,(int,float)):values.append(z)
  else:missing.append(c+str(r))
 height.append([f,n,len(values),min(values),max(values),';'.join(missing)])
csvout('株高复查.csv',['文件','页','有效株高数','最小','最大','缺失位置'],height)

f,ss=book('2025秋季2号棚1130日spad窄数据.xlsx');s=ss['Sheet1'];groups=collections.defaultdict(list)
for r in range(2,s['rows']+1):
 z=v(s,'F'+str(r))
 if isinstance(z,(int,float)):groups[tuple(v(s,c+str(r)) for c in 'ABCDE')].append((r,z))
spad=[];treatments=collections.defaultdict(lambda:collections.defaultdict(list))
for k,vs in groups.items():
 z=[x[1] for x in vs];allmean=statistics.mean(z);first=statistics.mean(z[:3]);faridx=max(range(len(z)),key=lambda j:abs(z[j]-allmean))
 farmean=statistics.mean([x for j,x in enumerate(z) if j!=faridx]) if len(z)==4 else allmean
 for name,avg in [('全部有效读数先平均',allmean),('按表顺序前三次',first),('删除距四次均值最远者',farmean)]:treatments[k[1:3]][name].append(avg)
 if len(z)==4:spad.append([k[4],k[1],k[2],k[3],';'.join('F'+str(r)+'='+str(x) for r,x in vs),statistics.stdev(z)/allmean,allmean,first,first-allmean,'F'+str(vs[faridx][0]),z[faridx],farmean,farmean-allmean,statistics.stdev(z),statistics.stdev([x for j,x in enumerate(z) if j!=faridx])])
csvout('SPAD六组方案敏感性.csv',['小区','水','氮','生物重复','四次原读数','四次CV','四次均值','前三次均值','前三次减全均值','最远读数位置','最远读数','删除最远者均值','删最远减全均值','四次SD','删最远后三次SD'],spad)
csvout('SPAD处理均值方案对比.csv',['水','氮','生物重复数','全部有效读数先平均','表顺序前三次','删最远读数'],[[*k,len(x['全部有效读数先平均']),statistics.mean(x['全部有效读数先平均']),statistics.mean(x['按表顺序前三次']),statistics.mean(x['删除距四次均值最远者'])] for k,x in sorted(treatments.items())])

# Independently verify pivot totals against the latest base data.
pivots=[]
f,ss=book('2026春品质指标集.xlsx');s=ss['Sheet1'];pivot=ss['Sheet2'];g=collections.defaultdict(list)
for r in range(2,s['rows']+1):
 if v(s,'A'+str(r))==20260624 and isinstance(v(s,'I'+str(r)),(int,float)):g[(v(s,'C'+str(r)),v(s,'D'+str(r)))].append(v(s,'I'+str(r)))
pivots.append([f,'Sheet2','C19',v(pivot,'C19'),sum(g[('W3','N2')]),'W3N2的Vc求和未更新；源I61已修正'])
pivots.append([f,'Sheet2','C16',v(pivot,'C16'),sum(sum(vs) for k,vs in g.items() if k[0]=='W3'),'W3小计未更新'])
pivots.append([f,'Sheet2','C21',v(pivot,'C21'),sum(sum(vs) for vs in g.values()),'总计未更新'])
f,ss=book('2025春品质集优先采用品质集中的果实含水率.xlsx',R);s=ss['Sheet1'];pivot=ss['Sheet2']
anthos=sum(v(s,'M'+str(r)) for r in range(2,s['rows']+1) if isinstance(v(s,'M'+str(r)),(int,float)))
pivots.append(['参照/'+f,'Sheet2','C28',v(pivot,'C28'),anthos,'按所有原表花青素记录求和，需核透视表来源范围及刷新状态'])
csvout('透视汇总与源表对照.csv',['文件','页','位置','已保存汇总值','当前源表复算值','判断'],pivots)

f,ss=book('2026春土壤养分数据集.xlsx');s=ss['Sheet1']
soilratios=[[r,v(s,'G'+str(r)),v(s,'K'+str(r)),v(s,'G'+str(r))/391, v(s,'K'+str(r))-v(s,'G'+str(r))/391] for r in range(2,38)]
csvout('土壤AK双单位核对.csv',['行','G_AK_mgkg','K_速效钾','同表统一换算G除391','差值'],soilratios)
result={'formula_checked':len(formula_checks),'formula_cache_mismatches':formula_bad,'formula_skipped':len(skipped),'uncached':uncached,'objective_findings':objective,'mapping_conflicts':conflicts,'height':height,'spad_groups':len(groups),'spad_readings':sum(len(z) for z in groups.values()),'spad_sensitivity':spad,'pivot_checks':pivots,'soil_K30_expected':v(s,'G30')/391,'soil_K30_current':v(s,'K30')}
(OUT/'专项复核结果.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps({k:result[k] for k in ['formula_checked','formula_cache_mismatches','formula_skipped','uncached','objective_findings','mapping_conflicts','height','soil_K30_expected','soil_K30_current']},ensure_ascii=False,indent=2))
assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in U['source_sha256'].items())
print('只读复核通过，原文件及审核表未更改。')
