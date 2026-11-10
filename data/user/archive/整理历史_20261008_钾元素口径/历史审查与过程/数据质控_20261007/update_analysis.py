from pathlib import Path
import json,csv,statistics,collections,re,sys,hashlib
import numpy as np
from openpyxl.utils.cell import get_column_letter,coordinate_from_string
from openpyxl.utils.datetime import from_excel
sys.stdout.reconfigure(encoding='utf8')
ROOT=Path(r'D:\三季节数据汇总');OUT=ROOT/'数据质控_20261007'
S=json.loads((OUT/'snapshot.json').read_text(encoding='utf8'));C=S['current'];R=S['reference']
def val(s,a):return s['formulas'][a]['cached'] if a in s['formulas'] else s['cells'].get(a)
def rows(s,width):return [(r,[val(s,get_column_letter(i)+str(r)) for i in range(1,width+1)]) for r in range(2,s['rows']+1) if any(val(s,get_column_letter(i)+str(r)) is not None for i in range(1,width+1))]
def date(v):
    if v is None:return '未记录'
    z=str(v)
    if isinstance(v,(int,float)) and 30000<v<60000:return from_excel(v).date().isoformat()
    if 'T' in z:return z[:10]
    if len(z)==8 and z.isdigit():return z[:4]+'-'+z[4:6]+'-'+z[6:]
    return z
def csvout(file,head,data):
    with open(OUT/file,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(head);w.writerows(data)
def file(suffix):return next(f for f in C if f.endswith(suffix))
excluded25={1,6,7,8,9,14}
rules={'version':'2026-10-07','authoritative_source':'当前Excel；不刷新外部链接，使用缓存','exclude_treatments':{'2025春':sorted(excluded25)},'spring2026_growth_sheet':'2026生长指标汇总','drop_SPAD_technical_reads':'建议按表内批次保留前三次有效读数，排除第4批6次；原表不删','exclude_attached_SPAD_groups':['Z1','Z2','Z3'],'soil_inorganic_N':'暂缓','missing':'保留缺失，不新增均值填补','user_confirmed_imputation':'保留，标记来源；不参与新异常值筛查','plant_fruit_stock':'不用于后续分析','pruning_dates25':['2025-06-09','2025-06-21'],'units25quality':{'Vc':'mg/kg','糖':'mg/kg（用户指定；待确认是否限25春）','蛋白':'mg/kg（用户指定；待确认是否限25春）'},'total_phenols_flavonoids_anthocyanins':'吸光度','yield':'kg/ha','dry_mass':'g/株（一般口径）','rain_mm':0,'TMX_virtual_harvest':'最后真实采收后增加虚拟操作，仅模型辅助，非实测产量或新的分析批次'}
rules['units25quality']={'Vc':'mg/kg','糖':'mg/g','蛋白':'mg/g'}
rules['units_all_seasons']={'糖':'mg/g','蛋白':'mg/g','总酚/黄酮/花青素':'吸光度'}
rules['soil_20260106_weight_units']='湿/干重为实际克数×100；盒重为g；H=(C-D)/(D-B*100)已修订'
rules['C257']='用户指定反算值6702；不是新增原始称重；E257及对应G257保留'
(OUT/'当前数据口径.json').write_text(json.dumps(rules,ensure_ascii=False,indent=2),encoding='utf8')
# SPAD: identify reads by unchanged table order, not values.
f=file('2025秋季2号棚1130日spad窄数据.xlsx');s=C[f]['sheets']['Sheet1'];groups=collections.defaultdict(list)
for r,x in rows(s,6):
    if isinstance(x[5],(int,float)):groups[tuple(x[:5])].append((r,x[5]))
spad=[];avgrows=[];spadmask=[]
for k,vs in groups.items():
    kept=vs[:3];oldmean=statistics.mean(v for r,v in vs);newmean=statistics.mean(v for r,v in kept)
    avgrows.append([date(k[0]),k[4],k[1],k[2],k[3],len(vs),oldmean,newmean,statistics.stdev(v for r,v in kept),len(kept),newmean-oldmean])
    for j,(r,v) in enumerate(vs):
        spadmask.append([f,'Sheet1','F'+str(r),date(k[0]),k[4],k[1],k[2],k[3],j+1,v,'保留' if j<3 else '建议排除','按表内批次统一前三次；不依赖数值高低'])
        if j>=3:spad.append([f,'Sheet1','F'+str(r),date(k[0]),k[4],k[1],k[2],k[3],v,[v for rr,v in kept][0],[v for rr,v in kept][1],[v for rr,v in kept][2],oldmean,newmean,newmean-oldmean,oldmean and (newmean-oldmean)/oldmean,'表内第4次有效读数；前三次齐全','待人工采用'])
csvout('SPAD建议排除读数.csv',['文件','工作表','单元格','日期','小区','水处理','氮处理','生物学重复','建议排除读数','保留第1次','保留第2次','保留第3次','四次均值','三次均值','均值变化','相对变化','依据','处理状态'],spad)
csvout('SPAD逐次读数与规则.csv',['文件','工作表','单元格','日期','小区','水处理','氮处理','生物学重复','测定序号','SPAD值','分析选择','依据'],spadmask)
csvout('SPAD生物学重复汇总.csv',['日期','小区','水处理','氮处理','生物学重复','原有效读数数','原均值','前三次均值','前三次SD','保留读数数','均值变化'],avgrows)
# Source-specific schemas. All ids remain original; sample ids in 2026 quality are separate from treatment.
specs=[
('2025年春季茄子植株样氮磷钾测定.xlsx','Sheet1',[1,3,4,8,9,2,0],[5,6,7]),
('2025春产量数据集.xlsx','Sheet1',[3,1,2,4,5,0,0],[6,7]),
('2025春作物生长指标集.xlsx','Sheet1',[1,2,5,3,4,0,0],[7,8,9,11]),
('2025春初始土壤基础养分.xlsx','末-基础养分',[0,1,2,0,0,0,3],[4,5,6,7,8,9,10,13]),
('2025春品质集优先采用品质集中的果实含水率.xlsx','Sheet1',[1,2,3,4,5,0,0],list(range(7,15))),
('2025春土壤含水量数据集.xlsx','Sheet1',[15,10,11,12,13,0,8],[2,3,4,5,6,7]),
('2025年秋季茄子植株样氮磷钾测定.xlsx','Sheet1',[1,3,4,8,9,2,0],[5,6,7]),
('2025年秋季茄子生长指标集.xlsx','Sheet1',[1,2,3,4,5,0,0],[6,7,8,11]),
('2025秋季产量集.xlsx','2025秋季产量集',[1,2,5,3,4,0,0],[6,7]),
('20260106_2号棚取土.xlsx','Sheet1',[0,5,6,9,10,0,7],[2,3,4,8]),
('25年秋季2号棚品质指标集.xlsx','Sheet1',[1,2,3,4,5,0,0],list(range(6,21))),
('20260519_SPAD.xlsx','Sheet1',[1,2,3,4,5,0,0],[6]),
('2026春产量集.xlsx','Sheet1',[1,2,3,4,5,0,0],[6,7,8]),
('2026春品质指标集.xlsx','Sheet1',[1,2,5,3,4,0,0],list(range(6,15))),
('2026春土壤养分数据集.xlsx','Sheet1',[0,1,0,0,0,0,2],list(range(3,13))),
('2026春土壤含水量数据集.xlsx','Sheet1',[1,2,3,4,5,0,6],[7,8,9]),
('2026春生长指标集结果.xlsx','2026生长指标汇总',[1,2,5,3,4,0,0],list(range(6,12))),
('2026春茎叶果氮磷钾.xlsx','Sheet1',[6,1,2,3,4,5,0],[7,8,9])]
known_means={file('2025春品质集优先采用品质集中的果实含水率.xlsx'):{'J12','J15','J31','K47','L47','M47','K78','L78','M78'},file('2025春土壤含水量数据集.xlsx'):{'E43','E257','E447','E487','E572','G43','G257','G447','G487','G572'}}
coverage=[];profile=[];screens=[];mask=[];meanmarks=[];typeerrors=[]
reconstructed={file('2025春土壤含水量数据集.xlsx'):{'C257'}}
def process(f,n,ids,ms,rr,s,spad_avg=False):
    kept=[];empty=0;scopeout=0
    for r,x in rr:
        plot=x[ids[1]-1];day=date(x[ids[0]-1]) if ids[0] else ('2026-01-06（文件名；表内未记日期）' if '20260106' in f else '未记录')
        why='保留';action='纳入范围'
        if f.startswith('2025春') and plot in excluded25:why='试验区意外：用户指定排除2025春处理';action='排除范围';scopeout+=1
        elif '20260519_SPAD' in f and str(plot).startswith('Z'):why='附加处理暂不分析';action='排除范围';scopeout+=1
        elif '2025春作物生长' in f and day in ['2025-06-09','2025-06-21']:why='整枝打杈日期，不使用整枝数据';action='排除范围';empty+=1
        mask.append([f,n,r,day,plot,x[ids[2]-1] if ids[2] else None,action,why])
        if action=='纳入范围':kept.append((r,x))
    dates=sorted({date(x[ids[0]-1]) for r,x in kept}) if ids[0] else ['未记录']
    coverage.append([f,n,len(rr),len(kept),scopeout,empty,','.join(dates),','.join(str(v) for v in sorted({x[ids[1]-1] for r,x in kept},key=str))])
    parts=collections.defaultdict(list)
    for r,x in kept:
        day=date(x[ids[0]-1]) if ids[0] else '未记录';parts[(day,x[ids[5]-1] if ids[5] else '',x[ids[6]-1] if ids[6] else '')].append((r,x))
    def record(c,r,z,p,method,lo,hi,x):
        hdr='SPAD前三次均值' if spad_avg else val(s,get_column_letter(c)+'1')
        ident=[x[ids[j]-1] if ids[j] else None for j in [1,2,3,4]]
        if '2026春品质' in f and p[0]=='2026-06-03':note='首批小区号为样本流水号；按水氮处理+生物学重复定位'
        elif spad_avg:note='基于前三次测定均值；原始位置见SPAD读数规则表'
        else:note='核查原记录；候选不等于错误'
        screens.append([f,n,('生物重复='+str(ident[1])+';小区='+str(ident[0])) if spad_avg else get_column_letter(c)+str(r),hdr,*p,z,method,lo,hi,*ident,note,'待人工核查',''])
    for p,prs in parts.items():
        for c in ms:
            col=get_column_letter(c);hdr='SPAD前三次均值' if spad_avg else val(s,col+'1');numbers=[];observed=[];impute=0
            for r,x in prs:
                a=col+str(r);v=x[c-1]
                if isinstance(v,(int,float)):
                    numbers.append((r,float(v),x))
                    if a in known_means.get(f,set()):impute+=1;meanmarks.append([f,n,a,v,'用户确认异常剔除后的填补/手工值','保留，标记；不作为新离群候选'])
                    elif a in reconstructed.get(f,set()):impute+=1;meanmarks.append([f,n,a,v,'用户指定含水率反算并取整的干重；非原始称重','保留6702；不作为新离群候选'])
                    else:observed.append((r,float(v),x))
                elif isinstance(v,str) and v.strip():typeerrors.append([f,n,a,v])
            vs=[v for r,v,x in numbers];ov=[v for r,v,x in observed]
            profile.append([f,n,*p,hdr,len(prs),len(vs),len(prs)-len(vs),impute,min(vs) if vs else None,statistics.median(vs) if vs else None,max(vs) if vs else None])
            if len(ov)>=12:
                q1,q3=np.quantile(ov,[.25,.75]);iq=q3-q1
                if iq>1e-12:
                    for r,z,x in observed:
                        if z<q1-3*iq or z>q3+3*iq:record(c,r,z,p,'分期/器官/土层3×IQR',float(q1-3*iq),float(q3+3*iq),x)
            # Use any actual biological-repeat count; never automatically remove repeats to force n=3.
            within=collections.defaultdict(list)
            if ids[2] and 'SPAD' not in hdr and '果实个数' not in hdr and '果实总重' not in hdr:
                for r,z,x in observed:
                    tkey=(x[ids[3]-1] if ids[3] else None,x[ids[4]-1] if ids[4] else None)
                    if '2026春品质' not in f:tkey+=(x[ids[1]-1],)
                    within[tkey].append((r,z,x))
                for tk,vs3 in within.items():
                    if len(vs3)!=3:continue
                    for j,(r,z,x) in enumerate(vs3):
                        oth=[v for i,(_,v,_) in enumerate(vs3) if i!=j];m=sum(oth)/2
                        if m>0 and abs(z-m)/m>.30 and abs(oth[0]-oth[1])/m<.15:record(c,r,z,p,'3子样相对偏差>30%',m*.7,m*1.3,x)
for suffix,n,ids,ms in specs:
    f=file(suffix);s=C[f]['sheets'][n];process(f,n,ids,ms,rows(s,max(max(ids),max(ms))),s)
# SPAD analysis table has one row per biological replicate, averaged over 3 technical readings.
f=file('2025秋季2号棚1130日spad窄数据.xlsx'); rr=[]
for i,x in enumerate(avgrows,2):rr.append((i,[x[0],x[1],x[4],x[2],x[3],x[7]]))
process(f,'生物学重复汇总（分析视图）',[1,2,3,4,5,0,0],[6],rr,C[f]['sheets']['Sheet1'],True)
csvout('更新统计筛查.csv',['文件','工作表或分析视图','单元格或定位','指标','日期','器官','土层','值','方法','下界','上界','小区或样本号','重复','水处理','氮处理','解释','处理状态','处理决定'],screens)
csvout('更新分期概况.csv',['文件','工作表','日期','器官','土层','指标','记录数','数值数','缺失数','已标填补/手工值数','最小值','中位数','最大值'],profile)
csvout('分析范围与排除记录.csv',['文件','工作表','原行号','日期','小区','重复','分析选择','依据'],mask)
csvout('更新数据覆盖.csv',['文件','工作表或分析视图','原记录数','纳入范围数','指定排除数','整枝日期排除数','保留日期','保留小区或样本号'],coverage)
csvout('已确认填补值.csv',['文件','工作表','位置','当前值','来源说明','分析口径'],meanmarks)
csvout('非数值测量字段.csv',['文件','工作表','位置','当前值'],typeerrors)
summary={'date':'2026-10-07','current_books':len(C),'current_sheets':sum(len(w['sheets']) for w in C.values()),'reference_books':len(R),'screen_rule_hits':len(screens),'screen_locations':len(set(tuple(x[:3]) for x in screens)),'spad_original_observed':sum(len(x) for x in groups.values()),'spad_groups':len(groups),'spad_drop_suggestions':len(spad),'spad_kept_reads':sum(min(3,len(x)) for x in groups.values()),'spad_mean_changes':[x[-1] for x in avgrows if x[5]==4],'known_fill_records':len(meanmarks),'non_numeric_measurements':len(typeerrors),'spring25_retained_plots':[2,3,4,5,10,11,12,13]}
data={'summary':summary,'rules':rules,'spad':spad,'spad_means':avgrows,'screens':screens,'coverage':coverage,'profiles':profile,'masks':mask,'confirmed_fill':meanmarks}
summary['known_fill_records']=len(meanmarks)-1
summary['reconstructed_weight_records']=1
previous=OUT/'reviewed_results.json'
if previous.exists():
    previous_data=json.loads(previous.read_text(encoding='utf8'))
    if 'issue_status' in previous_data:data['issue_status']=previous_data['issue_status']
(OUT/'reviewed_results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(summary,ensure_ascii=False,indent=2));print('SPAD DROP',spad)
