import json, sys, collections, math, csv, re, statistics
from pathlib import Path
from openpyxl.utils.cell import coordinate_from_string, column_index_from_string, get_column_letter
sys.stdout.reconfigure(encoding='utf-8')
OUT=Path(r'D:\三季节数据汇总\数据质控_20261003')
S=json.loads((OUT/'snapshot.json').read_text(encoding='utf8')); C=S['current']; R=S['reference']
def value(s,a):
    return s['formulas'].get(a,{}).get('cached') if a in s['formulas'] else s['cells'].get(a)
def rows(s,cols=None):
    if cols is None: cols=s['cols']
    return [(r,[value(s,f'{get_column_letter(c)}{r}') for c in range(1,cols+1)]) for r in range(2,s['rows']+1) if any(value(s,f'{get_column_letter(c)}{r}') is not None for c in range(1,cols+1))]
def csvout(name,headers,data):
    with open(OUT/name,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(headers);w.writerows(data)
if __name__=='__main__':
    diff=[]; inventory=[]
    for f in sorted(set(C)|set(R)):
        a,b=C.get(f),R.get(f)
        if not a or not b:
            state='仅当前存在' if a else '仅参照存在'
            inventory.append([f,state,a and a['size'],b and b['size'],None,None]);continue
        changes=[]; semantic=0
        for n in sorted(set(a['sheets'])|set(b['sheets'])):
            sa=a['sheets'].get(n,{'cells':{},'formulas':{}});sb=b['sheets'].get(n,{'cells':{},'formulas':{}})
            for x in sorted(set(sa['cells'])|set(sb['cells']),key=lambda x:(coordinate_from_string(x)[1],column_index_from_string(coordinate_from_string(x)[0]))):
                va,vb=sa['cells'].get(x),sb['cells'].get(x)
                ca,cb=value(sa,x),value(sb,x)
                if va!=vb or ca!=cb:
                    changes.append([f,n,x,va,vb,ca,cb,'值差异' if ca!=cb else '公式/表达差异'])
                    semantic+=ca!=cb
        diff+=changes
        state='字节完全相同' if a['sha256']==b['sha256'] else ('内容差异' if changes else '仅格式或元数据差异')
        inventory.append([f,state,a['size'],b['size'],len(changes),semantic])
    csvout('文件对比.csv',['相对路径','状态','当前字节数','参照字节数','单元格差异数','计算值差异数'],inventory)
    csvout('单元格差异.csv',['文件','工作表','单元格','当前原值或公式','参照原值或公式','当前计算值','参照计算值','类型'],diff)
    print('COMPARISON');print('\n'.join(str(x) for x in inventory))
    for f,w in C.items():
        print('\nFILE',f)
        for n,s in w['sheets'].items():
            width=next((i for i in range(1,s['cols']+1) if value(s,get_column_letter(i)+'1') is None),s['cols']+1)-1
            if width<2: continue
            rr=rows(s,width)
            # Ignore right side notes; width is first contiguous header row.
            print('SHEET',n,'width',width,'rows',len(rr),'uncached',sum(x['cached'] is None for x in s['formulas'].values()))
            for c in range(width):
                vals=[(r,x[c]) for r,x in rr]; hdr=value(s,get_column_letter(c+1)+'1')
                nums=[(r,v) for r,v in vals if isinstance(v,(float,int))]
                missing=[r for r,v in vals if v is None]
                if nums and c>=5:
                    ns=sorted(v for r,v in nums); med=statistics.median(ns)
                    q1=ns[len(ns)//4];q3=ns[(len(ns)*3)//4];iqr=q3-q1
                    far=[(r,round(v,5)) for r,v in nums if iqr>0 and (v<q1-3*iqr or v>q3+3*iqr)]
                    print(get_column_letter(c+1),hdr,'n=',len(nums),'missing=',len(missing),'range',round(ns[0],5),round(ns[-1],5),'far=',far[:18])
                else:
                    cnt=collections.Counter(str(v) for r,v in vals if v is not None)
                    print(get_column_letter(c+1),hdr,'missing=',len(missing),'distinct=',len(cnt),'values=',cnt.most_common(16))
            print('TAIL',rr[-3:])
