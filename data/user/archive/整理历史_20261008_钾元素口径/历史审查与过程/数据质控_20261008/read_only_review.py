from pathlib import Path
import sys,json,csv,hashlib,datetime,collections,re,math,statistics
import openpyxl
ROOT=Path(r'D:\三季节数据汇总')
REF=Path(r'D:\Tomato_Cal\data\user\ref\DSSAT文件')
OUT=ROOT/'数据质控_20261008'
OUT.mkdir(exist_ok=True)
sys.stdout.reconfigure(encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def csvout(name,headers,data):
    with (OUT/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(headers);w.writerows(data)
def inventory(root,current=False):
    paths=sorted(root.glob('202*/*')) if current else sorted(root.rglob('*'))
    return {str(p.relative_to(root)):{'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size,'mtime':datetime.datetime.fromtimestamp(p.stat().st_mtime,datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'mtime_ns':p.stat().st_mtime_ns} for p in paths if p.is_file() and not p.name.startswith('~$') and '__pycache__' not in p.parts}
I=inventory(ROOT,True);J=inventory(REF)
control=ROOT/'数据质控_20261007'/'更新数据核对与统计筛查.xlsx'
source_hashes={d['path']:d['sha256'] for d in [*I.values(),*J.values()]}
source_hashes[str(control)]=sha(control)
(OUT/'只读输入快照.json').write_text(json.dumps({'current':I,'reference':J,'review_table_sha256':sha(control)},ensure_ascii=False,indent=2),'utf-8')
code=(ROOT/'数据质控_20261003'/'audit.py').read_text('utf-8')
code=code.replace("OUT=ROOT/'数据质控_20261003'","OUT=ROOT/'数据质控_20261008'")
code=code.replace("sorted(ROOT.glob('202*/*.xlsx'))","sorted(p for p in ROOT.glob('202*/*.xlsx') if not p.name.startswith('~$'))")
code=code.replace("sorted(REF.rglob('*.xlsx'))","sorted(p for p in REF.rglob('*.xlsx') if not p.name.startswith('~$'))")
exec(compile(code,'read_only_snapshot','exec'),{})
S=json.loads((OUT/'snapshot.json').read_text('utf-8'));C=S['current'];R=S['reference']
def val(s,a):return s.get('formulas',{}).get(a,{}).get('cached') if a in s.get('formulas',{}) else s.get('cells',{}).get(a)
def norm(v):return None if v=='' else v
def equal(a,b):
    a,b=norm(a),norm(b)
    if isinstance(a,(int,float)) and isinstance(b,(int,float)):
        return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10)
    return a==b
diff=[];compare=[];sheetdiff=[]
for f in sorted(set(C)|set(R)):
    a,b=C.get(f),R.get(f);nvalues=nformulas=0
    if not a or not b:
        status='仅当前目录存在' if a else '仅参照目录存在';proposal='单侧文件；先核用途，不能仅按时间覆盖其他名称文件'
    else:
        for n in sorted(set(a['sheets'])|set(b['sheets'])):
            sa=a['sheets'].get(n,{});sb=b['sheets'].get(n,{})
            if bool(sa)!=bool(sb):sheetdiff.append([f,n,'仅当前页' if sa else '仅参照页'])
            for addr in sorted(set(sa.get('cells',{}))|set(sb.get('cells',{})),key=openpyxl.utils.cell.coordinate_to_tuple):
                av,bv=val(sa,addr),val(sb,addr)
                ar,br=sa.get('cells',{}).get(addr),sb.get('cells',{}).get(addr)
                changed=not equal(av,bv);formula_changed=ar!=br and (addr in sa.get('formulas',{}) or addr in sb.get('formulas',{}))
                if changed or formula_changed:
                    nvalues+=changed;nformulas+=formula_changed
                    diff.append([f,n,addr,ar,br,av,bv,'计算值/记录差异' if changed else '仅公式表达差异'])
        status='字节完全一致' if a['sha256']==b['sha256'] else ('数据或工作表不一致' if nvalues or a['sheets'].keys()!=b['sheets'].keys() else ('公式不同，缓存值一致' if nformulas else '单元格值和公式一致，仅格式/元数据不同'))
        newer='当前' if I[f]['mtime_ns']>J[f]['mtime_ns'] else ('参照' if J[f]['mtime_ns']>I[f]['mtime_ns'] else '同一时间')
        proposal=('无需同步' if status=='字节完全一致' else f'按保存时间：{newer}较新；保留另一版本备份，核对差异后手动同步')
    compare.append([f,status,I.get(f,{}).get('mtime'),J.get(f,{}).get('mtime'),a and a['size'],b and b['size'],nvalues,nformulas,proposal])
csvout('两目录Excel对比.csv',['相对路径','一致性','当前保存时间_北京时间','参照保存时间_北京时间','当前大小','参照大小','值差异数','公式差异数','版本建议'],compare)
csvout('两目录单元格差异.csv',['相对路径','工作表','位置','当前记录或公式','参照记录或公式','当前缓存值','参照缓存值','差异类型'],diff)
csvout('工作表结构差异.csv',['相对路径','工作表','位置'],sheetdiff)
csvout('两目录文件清单.csv',['相对路径','状态','当前保存时间_北京时间','参照保存时间_北京时间','当前字节数','参照字节数'],[[f,'字节一致' if f in I and f in J and I[f]['sha256']==J[f]['sha256'] else ('双侧文件不同' if f in I and f in J else '仅当前' if f in I else '仅参照'),I.get(f,{}).get('mtime'),J.get(f,{}).get('mtime'),I.get(f,{}).get('bytes'),J.get(f,{}).get('bytes')] for f in sorted(set(I)|set(J))])
old=json.loads((ROOT/'数据质控_20261007'/'snapshot.json').read_text('utf-8'))['current']
localchanges=[]
for f in C:
    a,b=C[f],old.get(f,{'sheets':{}})
    for n in set(a['sheets'])|set(b['sheets']):
        sa=a['sheets'].get(n,{});sb=b['sheets'].get(n,{})
        for addr in sorted(set(sa.get('cells',{}))|set(sb.get('cells',{})),key=openpyxl.utils.cell.coordinate_to_tuple):
            if not equal(val(sa,addr),val(sb,addr)) or sa.get('formulas',{}).get(addr,{}).get('formula')!=sb.get('formulas',{}).get(addr,{}).get('formula'):
                localchanges.append([f,n,addr,val(sb,addr),val(sa,addr),sb.get('cells',{}).get(addr),sa.get('cells',{}).get(addr)])
csvout('相对上次快照的修改.csv',['相对路径','工作表','位置','10月7日快照值','当前值','10月7日原记录或公式','当前记录或公式'],localchanges)
# Reuse the earlier screening checks only in the NEW output folder; never overwrite the manual review table.
code=(ROOT/'数据质控_20261007'/'update_analysis.py').read_text('utf-8')
code=code.replace("OUT=ROOT/'数据质控_20261007'","OUT=ROOT/'数据质控_20261008'")
code=code.replace('2026-10-07','2026-10-08')
exec(compile(code,'read_only_screening','exec'),{})
wb=openpyxl.load_workbook(control,data_only=True);ws=wb['更新统计筛查']
decisions=[];stat=collections.Counter()
for row in ws.iter_rows(min_row=6,max_row=222,values_only=True):
    if not row[0]:continue
    stat[str(row[16])]+=1
    f,n,addr=row[:3];raw=val(C.get(f,{}).get('sheets',{}).get(n,{}),addr) if re.match(r'^[A-Z]+\d+$',str(addr)) else None
    decisions.append([*row[:18],raw, None if raw is None else not equal(row[7],raw)])
wb.close()
csvout('人工审核状态与当前源值.csv',['文件','页','位置','指标','日期','器官','土层','旧筛查值','方法','下界','上界','小区','重复','水','氮','解释','审核状态','审核决定','当前源值','筛查值是否已过期'],decisions)
print('REVIEW STATE',dict(stat))
print('COMPARISON',json.dumps(compare,ensure_ascii=False))
print('CHANGED SINCE OCT7',len(localchanges),dict(collections.Counter(x[0] for x in localchanges)))
print('FORMULA ERRORS',[(f,n,len(s['errors'])) for f,w in C.items() for n,s in w['sheets'].items() if s['errors']])
print('INVENTORY',len(I),len(J))
(OUT/'复查汇总.json').write_text(json.dumps({'comparison':compare,'change_count':len(localchanges),'review_status':dict(stat),'source_sha256':source_hashes},ensure_ascii=False,indent=2),'utf-8')
assert all(sha(Path(p))==h for p,h in source_hashes.items()),'Input changed during review.'
print('全部输入文件哈希保持不变。')
