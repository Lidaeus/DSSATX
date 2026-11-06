"""Same-source humidity diagnostic; never edits frozen WTH/bundles."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
SOURCE=Path('D:/三季节数据汇总/分析结果/15_气象原始核查与耗水修订_20261011/数据')
OUT=ROOT/'workspace/audits/et_method_grid_20261012/humidity'


def build():
    OUT.mkdir(parents=True,exist_ok=True)
    halfhour=pd.read_csv(SOURCE/'2号_半小时来源与VPD.csv',parse_dates=['timestamp']).set_index('timestamp')
    ea=.6108*np.exp(17.27*halfhour['T']/(halfhour['T']+237.3))*halfhour.RH/100
    daily=ea.resample('D').agg(['mean','count'])
    log=np.log(daily['mean']/.6108)
    daily['DEWP']=237.3*log/(17.27-log)
    daily.loc[daily['count']!=48,'DEWP']=np.nan
    for target,series,how in [('TMAX',halfhour['T'],'max'),('TMIN',halfhour['T'],'min'),('RHUM',halfhour.RH,'mean')]:
        daily[target]=getattr(series.resample('D'),how)()
    daily['SRAD']=halfhour.solar.resample('D').sum()*.0018;daily.index.name='date'
    daily.to_csv(OUT/'same_source_daily_dewpoint.csv',encoding='utf-8-sig')
    file_manifest=pd.read_csv(SOURCE/'原始文件清单与SHA256.csv');rows=[];hashes={}
    design=json.loads((ROOT/'configs/runs/eggplant_26sp_n012_c31_joint67_20261011/design.json').read_text(encoding='utf-8'))
    for dataset in design['datasets']:
        dates=[]
        for line in (ROOT/dataset['bundle_path']/'XXTW2403.WTH').read_text().splitlines():
            values=line.split()
            if not values or len(values[0])!=7 or not values[0].isdigit():continue
            date=(pd.Timestamp(int(values[0][:4]),1,1)+pd.Timedelta(days=int(values[0][4:])-1)).strftime('%Y-%m-%d')
            if pd.Timestamp(date) not in daily.index:continue
            d=daily.loc[date]
            differences={k:float(d[k])-float(values[i]) for k,i in [('SRAD',1),('TMAX',2),('TMIN',3),('RHUM',5)]}
            valid=int(d['count'])==48 and np.isfinite(d.DEWP) and all(abs(v)<=.12 for v in differences.values())
            rows.append(dict(season_id=dataset['season_id'],date=date,count=int(d['count']),DEWP=float(d.DEWP) if np.isfinite(d.DEWP) else np.nan,
                same_source_weather_match=valid,**{k+'_difference':v for k,v in differences.items()}));dates.append(date)
        for file in halfhour.loc[min(dates):max(dates),'source'].dropna().unique():
            recorded=file_manifest[(file_manifest.station=='2号')&file_manifest.path.str.endswith(file)].iloc[0]
            digest=hashlib.sha256(Path(recorded.path).read_bytes()).hexdigest();assert digest==recorded.sha256
            hashes[recorded.path]=digest
    pd.DataFrame(rows).to_csv(OUT/'dewpoint_coverage_and_weather_match.csv',index=False,encoding='utf-8-sig')
    receipt=dict(definition='Daily DEWP from average actual vapor pressure of 48 paired half-hour T/RH observations; not mean-T times mean-RH.',
        input_derived_csv_sha256=hashlib.sha256((SOURCE/'2号_半小时来源与VPD.csv').read_bytes()).hexdigest(),raw_sha256=hashes,
        source_station='2号; same as uniform XXTW2403',missing_policy='DEWP=-99 on incomplete or weather-mismatched days; original fallback retained',
        no_original_weather_modified=True,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'rebuild_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':build()
