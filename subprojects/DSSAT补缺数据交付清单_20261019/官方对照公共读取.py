from pathlib import Path
import re,math,hashlib,ast,json
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parent
PLANT={'26SP':'2026-03-14','25SP':'2025-03-16'}
END={'26SP':'2026-07-17','25SP':'2025-07-13'}
SEASON={'26SP':'2026春','25SP':'2025春'}
LAYERS=[(0,5),(5,15),(15,30),(30,40),(40,50),(50,60),(60,70),(70,80),(80,100),(100,120),(120,140),(140,160),(160,180)]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def prev(date):return(pd.Timestamp(date)-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
def dat(s,date):return(pd.Timestamp(date)-pd.Timestamp(PLANT[s])).days
def native(path):
    path=Path(path);records=[];header=None;run=trt=None
    for line in path.read_text(encoding='utf8').splitlines():
        m=re.match(r'\*RUN\s+(\d+)',line)
        if m:run=int(m[1]);trt=None;header=None
        m=re.match(r'\s*TREATMENT\s+(\d+)',line)
        if m:trt=int(m[1])
        if line.lstrip().startswith('@YEAR'):header=line.strip().lstrip('@').split()
        elif header and re.match(r'\s*20\d{2}\s+\d+',line):
            widths=([5,4,6,6]+[9]*24 if path.name=='FreshWt.OUT'else
                    [5,4,6,6]+[8]*30+[10,8,8] if path.name=='PlantP.OUT'else None)
            if widths:
                pos=0;values=[]
                for width in widths:values.append(line[pos:pos+width].strip());pos+=width
                assert not line[pos:].strip(),(path,line)
            else:values=line.split()
            assert len(values)==len(header)and trt is not None and run is not None,(path,line)
            bad=[name for name,value in zip(header,values)if '*'in value]
            assert not bad or path.name=='PlantP.OUT',(path,bad)
            q=dict(zip(header,[float(v)if '*'not in v else np.nan for v in values]))
            if path.name=='PlantP.OUT':q['native_missing_fields']=';'.join(bad)
            q.update(trno=trt,run=run,date=(pd.Timestamp(int(q['YEAR']),1,1)+pd.Timedelta(days=int(q['DOY'])-1)).strftime('%Y-%m-%d'));records.append(q)
    q=pd.DataFrame(records)
    assert not q.empty and not q.duplicated(['trno','date']).any(),path
    return q.set_index(['trno','date']).sort_index()

def parameter_audit(work):
    # Reuse the independent reader function only, without importing frozen runtime modules.
    file=ROOT.parent/'critical_n/n_buffer_v13/runtime/src/calibration/single_season_n.py'
    tree=ast.parse(file.read_text(encoding='utf8'))
    fun=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='read_injected_parameters')
    ns=dict(Path=Path,re=re);exec(compile(ast.Module(body=[fun],type_ignores=[]),str(file),'exec'),ns)
    actual=ns['read_injected_parameters'](work)
    lines=(work/'TMGRO048.SPE').read_text().splitlines()
    def collect(names,tokens):
        for name,token in zip(names,tokens):
            if name:
                mantissa,_,exponent=token.lower().partition('e');decimals=len(mantissa.split('.')[1])if'.'in mantissa else 0
                actual[name]=(float(token),10.**((int(exponent)if exponent else 0)-decimals))
    for marker,names in [('3 LATE REPRODUCTIVE DEVELOPMENT',['TB3','TO13','TO23','TM3']),('ICMP,TCMP',['ICMP','TCMP']),('KEP, EORATIO',['KEP'])]:
        line=next(x for x in lines if marker in x);collect(names,line.split()[:len(names)])
    for marker,name in [('OPTLFP-EM,','OPTLFP_FS'),('OPTSTP-EM,','OPTSTP_FS'),('OPTSDP-EM,','OPTSDP_FS')]:
        line=next(x for x in lines if marker in x);collect([None,None,name],line.split()[:3])
    soil=(work/'SOIL.SOL').read_text().splitlines();i=next(i for i,x in enumerate(soil)if x.startswith('@ SCOM'))
    collect(['SOIL_SLDR'],[soil[i+1][18:24].strip()])
    q=pd.read_csv(work/'parameters.csv');assert set(q.name)<=set(actual),set(q.name)-set(actual)
    rows=[]
    for r in q.itertuples():
        value,resolution=actual[r.name]
        rows.append(dict(name=r.name,requested=r.value,actual_native=value,printed_resolution=resolution,passed=abs(r.value-value)<=resolution/2+1e-9))
    frame=pd.DataFrame(rows);assert frame.passed.all(),frame[~frame.passed].to_dict('records')
    frame.to_csv(work/'全部参数原生回读.csv',index=False,encoding='utf-8-sig')
    return len(frame)

if __name__=='__main__':
    rows=[]
    for rep in [2,3]:
        for s in ['26SP','25SP']:
            work=ROOT/f'原始模型输出/official_repeat{rep}_20261019'/s
            count=parameter_audit(work)
            frames={n:native(work/(n+'.OUT'))for n in ['ET','SoilWat','SoilWatBal','PlantGro','PlantN','FreshWt','PlantP']}
            print(rep,s,'parameters',count,'trts',frames['PlantGro'].index.get_level_values(0).unique().tolist(),flush=True)
            for name,q in frames.items():print(name,len(q),q.index.get_level_values(1).min(),q.index.get_level_values(1).max(),flush=True)
            pg,pn,fr=frames['PlantGro'],frames['PlantN'],frames['FreshWt']
            print('fruit DM check max',abs((fr.TOPOW-fr.HPODW)-pg.loc[fr.index,'PWAD']).max(),'fruitN negative',((pn.CNAD-pn.LNAD-pn.SNAD)<0).sum(),'ET residual',abs(frames['ET'].ETAA-frames['ET'].EPAA-frames['ET'].ESAA).max(),flush=True)
    pair=pd.read_csv(ROOT/'已填数据_stable79_20261019/16_原1123目标逐项对账.csv')
    print(pair.groupby(['variable','family']).size().to_string())
