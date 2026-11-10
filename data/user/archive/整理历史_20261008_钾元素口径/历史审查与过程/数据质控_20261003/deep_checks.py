from investigate import *
import numpy as np, ast, zipfile
ROOT=OUT.parent
def book(f): return C[next(x for x in C if x.endswith(f))]['sheets']
print('CROSS SHEET 2026 GROWTH')
s=book('2026春生长指标集结果.xlsx'); summ=s['0502']; cross=[]
maps={'0602':{'F':'K','G':'L','H':'M','I':'H','J':'I','K':'N'},'0629':{'F':'E','G':'F','H':'G','I':'K','J':'L'},'0717':{'F':'F','G':'G','H':'H','I':'P','J':'Q','K':'R'}}
for name,m in maps.items():
    rr={tuple(x[:2]):r for r,x in rows(s[name],18) } if name!='0717' else {tuple(x[1:3]):r for r,x in rows(s[name],18)}
    for r,x in rows(summ,11):
        if x[0]!=int('2026'+name):continue
        dr=rr[(x[1],x[4])]
        for c,dc in m.items():
            a,b=value(summ,c+str(r)),value(s[name],dc+str(dr))
            if a is not None and b is not None and abs(a-b)>1e-8:
                cross.append([name,x[1],x[4],c+str(r),a,dc+str(dr),b,(a-b)/b if b else None])
print('counts',collections.Counter(x[0] for x in cross));print(cross[:24]);csvout('生长表内部差异.csv',['日期页','处理','重复','汇总页单元格','汇总值','日期页单元格','日期页值','相对差异'],cross)
print('GROWTH MISSING HEIGHT');print([(r,x) for r,x in rows(book('2025年秋季茄子生长指标集.xlsx')['Sheet1'],11) if x[5] is None or x[5]>500])
print('2025 POSITION CHANGES')
gs=book('2025春作物生长指标集.xlsx')['Sheet1'];print(collections.Counter((x[0],x[4],x[5]) for r,x in rows(gs,11)));print('2025 SAMPLE MISSING',collections.Counter((x[0],','.join(get_column_letter(i+1) for i in range(6,11) if x[i] is None)) for r,x in rows(gs,11)))
print('SEMANTIC 2025 INITIAL SOIL')
f=next(x for x in C if '初始' in x);cs=C[f]['sheets']['末-基础养分'];rs=R[f]['sheets']['末-基础养分'];mapping={'A':'A','E':'B','F':'C','G':'D','H':'E','I':'F','J':'G','K':'H','L':'I','M':'J','N':'K','O':'L','P':'M'}
for c,rc in mapping.items():
    diffs=[(r,value(cs,c+str(r)),value(rs,rc+str(r))) for r in range(2,110) if value(cs,c+str(r))!=value(rs,rc+str(r))]
    print(c,rc,'differences=',len(diffs),'examples=',diffs[:3])
print('SEMANTIC 2025 MOISTURE')
f=next(x for x in C if '2025春土壤含水' in x);cs=C[f]['sheets']['Sheet1'];rs=R[f]['sheets']['Sheet1']
for c in ['B','C','E','G']:
    d=[(r,value(cs,c+str(r)),value(rs,c+str(r))) for r in range(2,632) if abs(float(value(cs,c+str(r)))-float(value(rs,c+str(r))))>1e-10]
    print(c,len(d),d[:20])
print('DATES',[(r,value(cs,'O'+str(r)),str(openpyxl_date(value(rs,'O'+str(r))))) for r in []]) if False else None
print('2026 nitrate relationship')
f=next(x for x in C if '硝态' in x);cs=C[f]['sheets']['Sheet1'];rs=R[f]['sheets']['Sheet1'];x=np.array([float(value(cs,'F'+str(r))) for r in range(2,181)]);y=np.array([float(value(rs,'F'+str(r))) for r in range(2,181)]);a,b=np.polyfit(x,y,1);print(a,b,'max residual',max(abs(y-(a*x+b))),'last',value(cs,'F181'),value(rs,'F181'));print('ammonium relationship',np.polyfit(x,np.array([float(value(rs,'G'+str(r))) for r in range(2,181)]),1))
print('EXTERNAL LINKS')
for f,w in C.items():
    with zipfile.ZipFile(ROOT/f) as z:
        for n in z.namelist():
            if n.startswith('xl/externalLinks/_rels'): print(f,z.read(n).decode('utf8')[:1800])
print('GENERIC FORMULA RECOMPUTE')
checks=[];mismatch=[];unsupported=[];blanks=[]
for f,w in C.items():
    for n,s in w['sheets'].items():
        for a,fo in s['formulas'].items():
            form=fo['formula'][1:].replace('$','')
            if fo['cached'] is None: blanks.append([f,n,a,fo['formula']]);continue
            if '[' in form or ':' in form or '!' in form or re.search(r'[A-Z]{3,}\(',form):unsupported.append([f,n,a]);continue
            def sub(m):
                v=value(s,m.group());return repr(v if v is not None else 0)
            expr=re.sub(r'\b[A-Z]+\d+\b',sub,form).replace('^','**')
            try:
                tree=ast.parse(expr,mode='eval')
                if not all(isinstance(node,(ast.Expression,ast.BinOp,ast.UnaryOp,ast.Constant,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.Pow,ast.USub,ast.UAdd)) for node in ast.walk(tree)):raise ValueError()
                got=eval(compile(tree,'<formula>','eval'),{'__builtins__':{}})
                checks.append([f,n,a])
                bad=abs(got-fo['cached'])>max(1e-9,abs(got)*1e-9) if isinstance(got,(int,float)) and isinstance(fo['cached'],(int,float)) else got!=fo['cached']
                if bad:mismatch.append([f,n,a,fo['formula'],fo['cached'],got])
            except Exception:unsupported.append([f,n,a])
print('checked',len(checks),'mismatch',len(mismatch),'unsupported',len(unsupported),'blank',len(blanks));print(mismatch[:20]);csvout('公式复算差异.csv',['文件','工作表','单元格','公式','缓存值','独立复算值'],mismatch)
print('UNCACHED',blanks[:3])
print('SPAD DUP')
ss=book('2025秋季2号棚1130日spad窄数据.xlsx')['Sheet1'];rr=rows(ss,6);groups=collections.defaultdict(list)
for r,x in rr:groups[tuple(x[:5])].append((r,x[5]))
print('keys',len(groups),'key multiplicities',collections.Counter(len(x) for x in groups.values()),'exact_dup_surplus',len(rr)-len(set(tuple(x) for r,x in rr)));print(list(groups.items())[:3]);print('SPAD block valid',[sum(value(ss,'F'+str(r)) is not None for r in range(i,i+60)) for i in [2,62,122,182]])
