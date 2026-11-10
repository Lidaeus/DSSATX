from pathlib import Path
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel
import json,collections,statistics,re,sys,hashlib
sys.stdout.reconfigure(encoding='utf8')
ROOT=Path(r'D:\三季节数据汇总'); OUT=ROOT/'数据质控_20261007'/'预审_20261007'
AUDIT=ROOT/'数据质控_20261007'/'更新数据核对与统计筛查.xlsx'
formbook=load_workbook(AUDIT,data_only=False); audit=load_workbook(AUDIT,data_only=True)
ws=audit['更新统计筛查']; pending=[];already=[]
for row in range(6,ws.max_row+1):
    x=[ws.cell(row,c).value for c in range(1,19)]
    if (x[16] in [None,'','待人工核查','未审核','尚未审核']) and not (x[17] and str(x[17]).strip()) and ('品质' in x[0] or '氮磷钾' in x[0]):pending.append((row,x))
    else:already.append((row,x))
def date(v):
    if hasattr(v,'date'):return v.date().isoformat()
    if isinstance(v,(int,float)) and 30000<v<60000:return from_excel(v).date().isoformat()
    s=str(v)
    return s[:4]+'-'+s[4:6]+'-'+s[6:] if len(s)==8 and s.isdigit() else s[:10]
schemas={
 '2025春品质集优先采用品质集中的果实含水率.xlsx':{'d':0,'p':1,'r':2,'w':3,'n':4,'metrics':list(range(6,14)),'kind':'quality'},
 '2026春品质指标集.xlsx':{'d':0,'p':1,'r':4,'w':2,'n':3,'metrics':list(range(5,14)),'kind':'quality'},
 '2026春茎叶果氮磷钾.xlsx':{'d':5,'p':0,'r':1,'w':2,'n':3,'o':4,'metrics':[6,7,8],'kind':'NPK'}}
imputed={('2025春\\2025春品质集优先采用品质集中的果实含水率.xlsx',a) for a in ['J12','J15','J31','K47','L47','M47','K78','L78','M78']}
cache={};sourcehashes={}
for f in sorted({x[0] for r,x in pending}):
    b=load_workbook(ROOT/f,data_only=True); fs=load_workbook(ROOT/f,data_only=False);s=b['Sheet1'];sc=schemas[Path(f).name]
    data=[]
    for ri in range(2,s.max_row+1):
        x=[s.cell(ri,ci).value for ci in range(1,s.max_column+1)]
        if x[sc['w']] is None:continue
        if f.startswith('2025春') and x[sc['p']] in {1,6,7,8,9,14}:continue
        organ=str(x[sc['o']]) if 'o' in sc else ''
        data.append({'row':ri,'date':date(x[sc['d']]),'plot':x[sc['p']],'repeat':x[sc['r']],'w':x[sc['w']],'n':x[sc['n']],'organ':organ,'values':x,'formulas':[fs['Sheet1'].cell(ri,c).value if fs['Sheet1'].cell(ri,c).data_type=='f' else None for c in range(1,s.max_column+1)]})
    cache[f]={'schema':sc,'header':[s.cell(1,c).value for c in range(1,s.max_column+1)],'rows':data};sourcehashes[f]=hashlib.sha256((ROOT/f).read_bytes()).hexdigest()
    b.close();fs.close()
cases={}
for auditrow,x in pending:
    f=x[0];a=x[2];key=f+'!'+a
    if key in cases:cases[key]['audit_rows'].append(auditrow);continue
    sc=cache[f]['schema'];col=ws.cell(auditrow,3).value;letters=re.match(r'[A-Z]+',col).group();ci=0
    for z in letters:ci=ci*26+ord(z)-64
    ci-=1;rowid=int(re.search(r'\d+',col).group());data=cache[f]['rows'];me=next(r for r in data if r['row']==rowid)
    part=[r for r in data if (r['date'],r['organ'])==(me['date'],me['organ'])]
    peers=[r for r in part if (r['w'],r['n'])==(me['w'],me['n']) and r['row']!=rowid and isinstance(r['values'][ci],(int,float)) and (f,letters+str(r['row'])) not in imputed]
    v=me['values'][ci];peer_values=[r['values'][ci] for r in peers];m=statistics.mean(peer_values) if peer_values else None
    treatment=[r['values'][ci] for r in part if (r['w'],r['n'])==(me['w'],me['n']) and isinstance(r['values'][ci],(int,float))]
    grouped=collections.defaultdict(list)
    for r in part:
        if isinstance(r['values'][ci],(int,float)) and (f,letters+str(r['row'])) not in imputed:grouped[(r['w'],r['n'])].append(r['values'][ci])
    groupmeans={str(w)+str(n):statistics.mean(values) for (w,n),values in grouped.items()}
    cross=[]
    for cj in sc['metrics']:
        vv=me['values'][cj];pp=[r['values'][cj] for r in part if (r['w'],r['n'])==(me['w'],me['n']) and r['row']!=rowid and isinstance(r['values'][cj],(int,float))]
        if isinstance(vv,(int,float)) and pp:
            mm=statistics.mean(pp);cross.append({'metric':cache[f]['header'][cj],'value':vv,'peer_mean':mm,'peer_values':pp,'deviation':(vv-mm)/mm if mm else None})
    item={'audit_rows':[auditrow],'file':f,'sheet':x[1],'address':a,'col_index':ci,'metric':x[3],'date':me['date'],'organ':me['organ'],'plot':me['plot'],'repeat':me['repeat'],'w':me['w'],'n':me['n'],'table_value':x[7],'current_value':v,'peer_values':peer_values,'peer_addresses':[letters+str(r['row']) for r in peers],'peer_mean':m,'peer_cv':statistics.stdev(peer_values)/m if len(peer_values)>1 and m else None,'deviation':(v-m)/m if m else None,'original_group_mean':statistics.mean(treatment),'mean_after_replacement':(sum(treatment)-v+m)/len(treatment) if m else None,'replacement_group_impact':((sum(treatment)-v+m)/len(treatment)-statistics.mean(treatment))/statistics.mean(treatment) if m else None,'group_means':groupmeans,'partition_min':min(r['values'][ci] for r in part if isinstance(r['values'][ci],(int,float))),'partition_max':max(r['values'][ci] for r in part if isinstance(r['values'][ci],(int,float))),'cross_metrics':cross,'current_formula':me['formulas'][ci]}
    cases[key]=item
result={'pending_rows':[r for r,x in pending],'reviewed_rows':[r for r,x in already],'cases':list(cases.values()),'source_data':cache,'source_sha256':sourcehashes,'audit_sha256':hashlib.sha256(AUDIT.read_bytes()).hexdigest()}
(OUT/'预审上下文.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
for it in cases.values():
    print(f"Rows{it['audit_rows']} {Path(it['file']).name} {it['address']} {it['date']} {it['organ']} {it['w']}{it['n']} rep{it['repeat']} {it['metric']} = {it['current_value']:.6g}")
    print(' peers',[round(a,5) for a in it['peer_values']],'mean',round(it['peer_mean'],5),'dev',round(it['deviation']*100,2),'peerCV',round(it['peer_cv']*100,2),'group impact',round(it['replacement_group_impact']*100,2))
    print(' groups',{k:round(v,4) for k,v in it['group_means'].items()})
    print('cross',[(m['metric'],round(m['value'],4),round(m['deviation']*100,2)) for m in it['cross_metrics']])
print('PENDING',len(pending),'UNIQUE',len(cases),'REVIEWED',len(already))
