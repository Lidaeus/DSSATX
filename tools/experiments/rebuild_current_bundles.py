"""Rebuild immutable three-season DSSAT inputs from the October 2026 sources.

Old FileX files supply model options/layout, and old FileA supplies spring
anthesis only. All quantitative observations come from current workbooks.
Weather thermal boundary must be selected explicitly before finalization.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.common.experiment_inputs import parse_filex, filex_section_text, validate_input_bundle, findings_as_dicts
from src.common.input_manifest import verify_manifest_integrity
from src.common.soil_depth_mapping import DepthInterval
from src.calibration.audit_observations import read_dssat_observation_table, audit_observation_bundle
from tools.experiments.build_corrected_bundles_20260923 import mapped_values, soil_profile_chem, bulk_density
from tools.soil.build_dual_plot_soil_profiles_20260917 import PHYSICAL_LAYERS, format_profile
from tools.soil.build_soil_water_tables_20260917 import compute_overlap_weights, format_weights, build_layer_mapping_df

REF = ROOT / 'data/user/ref/DSSAT文件'
DATE = '2026-10-10'
GRID = [r[0] for r in PHYSICAL_LAYERS]
SPECS = {
    '25SP': dict(folder='2025春', excode='XXQL2501', treatments=[2,3,4,5,10,11,12,13],
                 start='2025-03-09', water_date='2025-03-12', planting='2025-03-16', end='2025-07-13',
                 growth=('2025春作物生长指标集.xlsx','Sheet1','小区号','重复','日期'),
                 yield_=('2025春产量数据集.xlsx','Sheet1','小区号','行号','日期'),
                 quality=('2025春品质集优先采用品质集中的果实含水率.xlsx','Sheet1','果含水率'),
                 npk=('2025年春季茄子植株样氮磷钾测定.xlsx','取样日期','取样部位'),
                 water='2025春土壤含水量数据集.xlsx', management='2025春季灌水及施肥整理结果.xlsx'),
    '25FA': dict(folder='2025秋', excode='XXQL2502', treatments=list(range(1,13)),
                 start='2025-08-08', water_date='2025-08-09', planting='2025-08-13', end='2026-01-06',
                 growth=('2025年秋季茄子生长指标集.xlsx','Sheet1','小区','行号','日期'),
                 yield_=('2025秋季产量集.xlsx','2025秋季产量集','小区号','重复','日期'),
                 npk=('2025年秋季茄子植株样氮磷钾测定.xlsx','取样日期','取样部位'),
                 management='25年秋季茄子灌水施肥记录-整理.xlsx'),
    '26SP': dict(folder='2026春', excode='XXQL2601', treatments=list(range(1,13)),
                 start='2026-03-12', water_date='2026-03-14', planting='2026-03-14', end='2026-07-17',
                 growth=('2026春生长指标集结果.xlsx','2026生长指标汇总','小区','重复','取样日期'),
                 yield_=('2026春产量集.xlsx','Sheet1','小区号','重复','日期'),
                 quality=('2026春品质指标集.xlsx','Sheet1','半果含水率'),
                 npk=('2026春茎叶果氮磷钾.xlsx','日期','器官'),
                 water='2026春土壤含水量数据集.xlsx', management='2026年灌水施肥数据-整理.xlsx'),
}
A_COLUMNS = 'TRNO PDAT ADAT MDAT HDAT HWAM LWAM SWAM LAIX HIAM SNAM CNAM HWAH HWAHF'.split()
T_COLUMNS = 'TRNO DATE L#SD LAID L#PA LWAD RWAD SWAD M#AD SLAD CHTD CWID CNAM SNAM LNAM HFPOW CHFPW HPODW CHPDT PDMCD'.split()
PRECISION = dict(LAID=3, LAIX=3, CHTD=3, PDMCD=3, SNAM=2, LNAM=2)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_json(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2,
        default=lambda v:v.item() if isinstance(v,np.generic) else str(v))+'\n', encoding='utf-8')


def date_of(v):
    if pd.isna(v):
        raise ValueError('Missing date')
    if isinstance(v, (datetime, pd.Timestamp)):
        return pd.Timestamp(v).normalize()
    s = str(v).strip().removesuffix('.0')
    if s.isdigit():
        n = int(s)
        if n > 20000000:
            return pd.Timestamp(datetime.strptime(s, '%Y%m%d'))
        if 40000 < n < 50000:
            return pd.Timestamp(datetime(1899,12,30)+timedelta(days=n))
    if re.fullmatch(r'\d{4}/\d{4}', s):
        return pd.Timestamp(datetime.strptime(s, '%Y/%m%d'))
    return pd.Timestamp(s).normalize()


def code(v):
    return int(date_of(v).strftime('%y%j'))


def read(s, name, sheet='Sheet1', header=0):
    return pd.read_excel(REF / SPECS[s]['folder'] / name, sheet_name=sheet, header=header)


def canonical(s, spec):
    name, sheet, tn, rep, day = spec
    df = read(s,name,sheet).rename(columns={tn:'trno',rep:'rep',day:'date'})
    df['_source_row']=df.index+2
    df = df[df.trno.isin(SPECS[s]['treatments'])].copy()
    df['date'] = df.date.map(date_of)
    df[['trno','rep']] = df[['trno','rep']].astype(int)
    if df.duplicated(['trno','rep','date']).any():
        raise ValueError(f'{s} {name}: duplicate replicate/date')
    return df


def interpolate_at(frame, target, value_col):
    valid = frame[['date',value_col]].dropna().sort_values('date')
    if valid.empty or valid.date.duplicated().any():
        raise ValueError('Missing or duplicate interpolation nodes')
    xs = valid.date.map(lambda d:d.toordinal()).to_numpy()
    day = date_of(target).toordinal()
    value = float(np.interp(day, xs, valid[value_col].to_numpy(dtype=float)))
    method = 'endpoint_hold' if day < xs[0] or day > xs[-1] else ('exact' if day in xs else 'linear')
    left = valid.iloc[max(0,int(np.searchsorted(xs,day,side='right'))-1)]
    right = valid.iloc[min(len(xs)-1,int(np.searchsorted(xs,day,side='left')))]
    return value, method, left.date.date().isoformat(), right.date.date().isoformat()


def paired_nutrient(conc, mass):
    """mg/g DM * kg DM/ha / 1000 = kg nutrient/ha."""
    return np.asarray(conc,dtype=float)*np.asarray(mass,dtype=float)/1000


def mean_product(conc, mass):
    return float(np.mean(conc)*np.mean(mass)/1000)


def numeric_field(col, value):
    if pd.isna(value) or value == -99:
        return '   -99'
    digits = PRECISION.get(col,0)
    txt = f'{float(value):.{digits}f}'
    while len(txt)>5 and digits>0:
        digits -= 1
        txt = f'{float(value):.{digits}f}'
    if len(txt)>5:
        raise ValueError(f'{col} cannot be represented in a 6-character DSSAT field: {value}')
    return txt.rjust(6)


def write_obs(path, frame, columns, kind):
    lines = [f'*{kind}: {path.stem} EGGPLANT; rebuilt {DATE}',
             '! Current workbooks; no imputation. See decision_record.json and provenance tables.',
             '! MDAT missing: former PODD proxy is not an observed physiological maturity date.',
             '@TRNO ' + ''.join(f'{c:>6}' for c in columns[1:])]
    serialized=[]
    for _, row in frame.iterrows():
        fields=[numeric_field(c,row.get(c,np.nan)) for c in columns]
        lines.append(''.join(fields))
        serialized.append([float(f) for f in fields])
    path.write_text('\n'.join(lines)+'\n',encoding='ascii')
    return pd.DataFrame(serialized,columns=columns)


def observation_outputs(s, out, old):
    spec=SPECS[s]
    growth=canonical(s,spec['growth'])
    growth['SWAD']=pd.to_numeric(growth['茎干重'],errors='coerce')*27
    growth['LWAD']=pd.to_numeric(growth['叶干重'],errors='coerce')*27
    growth['LAID']=pd.to_numeric(growth['LAI'],errors='coerce')
    growth['CHTD']=pd.to_numeric(growth['株高'],errors='coerce')/100
    yield_df=canonical(s,spec['yield_']).rename(columns={'产量':'HFPOW'})
    npk_name,npk_day,organ=spec['npk']
    npk=read(s,npk_name).rename(columns={'小区号':'trno','重复':'rep',npk_day:'date',organ:'organ',
                                      '全氮（mg/g)':'N','全磷（mg/g)':'P','全钾（mg/g)':'K','全钾mg/g':'K'})
    npk=npk[npk.trno.isin(spec['treatments'])].copy()
    npk['date']=npk.date.map(date_of)
    npk[['trno','rep']]=npk[['trno','rep']].astype(int)
    npk['organ']=npk.organ.replace({'茎杆':'茎','叶片':'叶','果实':'果'})
    if npk.duplicated(['trno','rep','date','organ']).any():
        raise ValueError(f'{s}: duplicate NPK records')
    if s!='25FA':
        qname,qsheet,qwater=spec['quality']
        quality=canonical(s,(qname,qsheet,'小区号','重复','日期'))
        markers=pd.read_csv(REF/'人工处理值标记.csv')
        relevant=markers[(markers['文件'].str.replace('\\','/',regex=False)==spec['folder']+'/'+qname)&(markers['工作表']==qsheet)]
        water_column=get_column_letter(quality.columns.get_loc(qwater)+1)
        relevant=relevant[relevant['位置'].str.match(r'^'+water_column+r'\d+$')]
        marked_rows=set(relevant['位置'].str.extract(r'(\d+)')[0].astype(int))
        quality['approved_manual_moisture']=quality._source_row.isin(marked_rows)
        quality['dmfr']=1-pd.to_numeric(quality[qwater],errors='coerce')
        if not quality.dmfr.between(0,1,inclusive='neither').all():
            raise ValueError(f'{s}: invalid fruit moisture fraction')
    matches=[]
    yield_df['approved_manual_moisture_influence']=False
    for i,row in yield_df.iterrows():
        if s=='25FA':
            dmfr,method,left,right=.05,'approved_constant_0.05','',''
            manual=False
        else:
            q=quality[(quality.trno==row.trno)&(quality.rep==row.rep)]
            dmfr,method,left,right=interpolate_at(q,row.date,'dmfr')
            manual=bool(q[q.date.isin(pd.to_datetime([left,right]))].approved_manual_moisture.any())
        yield_df.loc[i,'PDMCD']=dmfr
        yield_df.loc[i,'HPODW']=float(row.HFPOW)*dmfr
        yield_df.loc[i,'approved_manual_moisture_influence']=manual
        matches.append(dict(trno=row.trno,rep=row.rep,date=row.date.date().isoformat(),
                            dmfr=dmfr,method=method,left_date=left,right_date=right,
                            approved_manual_moisture_influence=manual))
    yield_df=yield_df.sort_values(['trno','rep','date'])
    # Repeated harvests are the same plots. Accumulate BEFORE computing sample SD.
    for inc,cum in [('HFPOW','CHFPW'),('HPODW','CHPDT')]:
        yield_df[cum]=yield_df.groupby(['trno','rep'])[inc].cumsum()
    yield_df['cumulative_manual_moisture_influence']=yield_df.groupby(['trno','rep']).approved_manual_moisture_influence.cummax()
    nutrient_audit=[]
    nitrogen_summaries=[]
    for (tn,n_day,n_organ), ng in npk[npk.organ.isin(['茎','叶'])].groupby(['trno','date','organ']):
        g_day=n_day-pd.Timedelta(days=1) if s=='26SP' and n_day==pd.Timestamp('2026-06-03') else n_day
        gg=growth[(growth.trno==tn)&(growth.date==g_day)]
        mass_col='SWAD' if n_organ=='茎' else 'LWAD'
        model_col='SNAM' if n_organ=='茎' else 'LNAM'
        if gg.empty:
            raise ValueError(f'{s}: no matched dry mass for NPK TN{tn} {n_day}')
        if s=='25FA':
            conc=ng.N.dropna().to_numpy(float); mass=gg[mass_col].dropna().to_numpy(float)
            value=mean_product(conc,mass)
            # No paired-product sample SD can be inferred from two independent means.
            nitrogen_summaries.append(dict(trno=tn,date=g_day,variable=model_col,value=value,
                                          raw_sd=np.nan,n_rep=0,n_samples_concentration=len(conc),
                                          n_samples_mass=len(mass),sd_method='not_identifiable_from_unpaired_means'))
            for nutrient in ['N','P','K']:
                nutrient_audit.append(dict(trno=tn,organ=n_organ,growth_date=g_day.date().isoformat(),
                    concentration_date=n_day.date().isoformat(),nutrient=nutrient,
                    amount_kg_ha=mean_product(ng[nutrient].dropna(),mass),method='mean_concentration_times_mean_mass',
                    n_concentration=ng[nutrient].notna().sum(),n_mass=len(mass)))
        else:
            paired=ng.merge(gg[['rep',mass_col]],on='rep',validate='one_to_one')
            if len(paired)!=len(ng) or len(paired)!=len(gg):
                raise ValueError(f'{s}: incomplete replicate pairing')
            vals=paired_nutrient(paired.N,paired[mass_col])
            nitrogen_summaries.append(dict(trno=tn,date=g_day,variable=model_col,value=np.mean(vals),
                    raw_sd=np.std(vals,ddof=1),n_rep=len(vals),sd_method='paired_replicate_sample_sd'))
            for _,r in paired.iterrows():
                for nutrient in ['N','P','K']:
                    nutrient_audit.append(dict(trno=tn,rep=r.rep,organ=n_organ,
                        growth_date=g_day.date().isoformat(),concentration_date=n_day.date().isoformat(),
                        nutrient=nutrient,amount_kg_ha=float(r[nutrient]*r[mass_col]/1000),method='paired_product'))
    # Fruit N/P/K remain auxiliary; do not call standing+removed nutrient a model total-N observation.
    for i,row in yield_df.iterrows():
        fn=npk[(npk.trno==row.trno)&(npk.organ=='果')]
        if s!='25FA':
            fn=fn[fn.rep==row.rep]
        else:
            fn=fn.groupby('date',as_index=False)[['N','P','K']].mean()
        for nutrient in ['N','P','K']:
            value,method,left,right=interpolate_at(fn,row.date,nutrient)
            yield_df.loc[i,f'harvest_{nutrient}_kg_ha']=row.HPODW*value/1000
    long=[]
    def summarize(df, cols, workbook, sheet, rule):
        for (tn,day),g in df.groupby(['trno','date']):
            for c in cols:
                vals=g[c].dropna().to_numpy(float)
                if not len(vals):
                    continue
                flag='ok'
                if c in ['HPODW','PDMCD'] and g.approved_manual_moisture_influence.any():flag='includes_approved_manual_moisture'
                if c=='CHPDT' and g.cumulative_manual_moisture_influence.any():flag='includes_approved_manual_moisture'
                if s=='25FA' and c in ['HPODW','CHPDT','PDMCD']:flag='conditional_fixed_dry_fraction_0.05'
                long.append(dict(season_id=s,excode=spec['excode'],trno=tn,date=day.date().isoformat(),
                    variable=c,value=np.mean(vals),raw_sd=np.std(vals,ddof=1) if len(vals)>1 else np.nan,
                    n_rep=len(vals) if s!='25FA' or c in ['HFPOW','CHFPW','HPODW','CHPDT','PDMCD'] else 0,
                    n_samples=len(vals),sd_method=('sample_sd_sample_identity_not_independent_plot'
                        if s=='25FA' and c in ['SWAD','LWAD','LAID','CHTD'] else 'sample_sd'),
                    source_workbook=workbook,source_sheet=sheet,source_row_rule=rule,quality_flag=flag))
    summarize(growth,['SWAD','LWAD','LAID','CHTD'],spec['growth'][0],spec['growth'][1],'current_valid_samples;27000_plants_ha;cm_to_m')
    summarize(yield_df,['HFPOW','CHFPW','HPODW','CHPDT','PDMCD'],spec['yield_'][0],spec['yield_'][1],
              'per_plot_dry_conversion_then_cumsum;endpoint_hold' if s!='25FA' else 'fixed_dry_fraction_0.05_conditional_estimate')
    for r in nitrogen_summaries:
        r=dict(r);r['date']=r['date'].date().isoformat()
        long.append(dict(season_id=s,excode=spec['excode'],source_workbook=npk_name+';'+spec['growth'][0],
                    source_sheet='Sheet1;'+spec['growth'][1],source_row_rule='mean_times_mean' if s=='25FA' else 'paired_product',
                    quality_flag='approved_unpaired_mean_product' if s=='25FA' else 'ok',**r))
    uncertainty=pd.DataFrame(long)
    t=uncertainty.pivot(index=['trno','date'],columns='variable',values='value').reset_index()
    t=t.rename(columns={'trno':'TRNO'});t['DATE']=t.date.map(code);t=t.sort_values(['TRNO','DATE'])
    a_rows=[]
    olda=read_dssat_observation_table(old/f"{spec['excode']}.TMA").set_index('TRNO')
    for tn in spec['treatments']:
        tg=t[t.TRNO==tn];lastgrowth=tg[tg.LWAD.notna()].iloc[-1];lastyield=tg[tg.CHFPW.notna()].iloc[-1]
        a_rows.append(dict(TRNO=tn,PDAT=code(spec['planting']),ADAT=float(olda.loc[tn,'ADAT']) if s!='25FA' else -99,
            MDAT=-99,HDAT=int(lastyield.DATE),LAIX=tg.LAID.max(),LWAM=lastgrowth.LWAD,SWAM=lastgrowth.SWAD,
            HWAH=lastyield.CHPDT,HWAHF=lastyield.CHFPW))
    a=write_obs(out/f"{spec['excode']}.TMA",pd.DataFrame(a_rows),A_COLUMNS,'EXP.DATA (A)')
    t_printed=write_obs(out/f"{spec['excode']}.TMT",t,T_COLUMNS,'EXP.DATA (T)')
    a.to_csv(out/'FileA_values.csv',index=False);t_printed.to_csv(out/'FileT_values.csv',index=False)
    # Record both unrounded source mean and exact value consumed by the parser.
    printed=t_printed.set_index(['TRNO','DATE'])
    uncertainty['unrounded_source_mean']=uncertainty.value
    uncertainty['value']=[printed.loc[(r.trno,code(r.date)),r.variable] for r in uncertainty.itertuples()]
    uncertainty.to_csv(out/'observation_uncertainty.csv',index=False)
    growth.to_csv(out/'growth_replicates.csv',index=False)
    yield_df.to_csv(out/'harvest_replicates.csv',index=False)
    npk.to_csv(out/'plant_npk_source_values.csv',index=False)
    pd.DataFrame(nutrient_audit).to_csv(out/'standing_npk_calculation_audit.csv',index=False)
    pd.DataFrame(matches).to_csv(out/'fruit_quality_match_audit.csv',index=False)
    return growth,yield_df


def soil_water(s,out):
    spec=SPECS[s]
    frames=[]
    if s!='25FA':
        name=spec['water'];df=read(s,name)
        df=df.rename(columns={'小区号':'trno','重复':'rep','取样日期':'date','日期':'date',
                              '土层深度':'depth','深度':'depth','体积含水率':'vwc'})
        df['date']=df.date.map(date_of);df['source_sheet']='Sheet1';df['source_workbook']=name
        df['conversion']='source_vwc';frames.append(df)
    else:
        name='2025 2号棚秋季取土.xlsx'
        for sheet,day in [('20250809定植前取土','2025-08-09'),('20261002','2026-10-02')]:
            df=read(s,name,sheet).rename(columns={'小区号':'trno','重复':'rep','土层深度':'depth','深度':'depth',
                                                '体积含水率':'vwc'})
            df['date']=date_of(day);df['source_sheet']=sheet;df['source_workbook']=name
            df['conversion']='source_vwc';frames.append(df)
        name='20260106_2号棚取土.xlsx'
        df=read(s,name).rename(columns={'小区号':'trno','重复':'rep','深度':'depth'})
        df['vwc']=pd.to_numeric(df['土壤含水率'],errors='coerce')*df.depth.map(lambda d:bulk_density(*depth_of(d)))
        df['date']=date_of('2026-01-06');df['source_sheet']='Sheet1';df['source_workbook']=name
        df['conversion']='stored_gravimetric_fraction_times_shared_layer_bulk_density';frames.append(df)
    raw=pd.concat(frames,ignore_index=True);raw=raw[raw.trno.isin(spec['treatments'])].copy()
    raw['depth']=raw.depth.map(lambda d:'-'.join(map(str,depth_of(d))))
    if raw.duplicated(['trno','rep','date','depth']).any():
        raise ValueError(f'{s}: duplicate soil water samples')
    rows=[]
    for (tn,day,depth),g in raw.groupby(['trno','date','depth']):
        vals=g.vwc.dropna().to_numpy(float);top,bottom=depth_of(depth)
        weights=compute_overlap_weights(top,bottom)
        initial=day==date_of(spec['water_date']);outside=day>date_of(spec['end'])
        rows.append(dict(season_id=s,excode=spec['excode'],trno=int(tn),date=day.date().isoformat(),depth_label=depth,
            depth_top_cm=top,depth_bottom_cm=bottom,vwc_mean=np.mean(vals),vwc_sd=np.std(vals,ddof=1),
            n_rep=0 if s=='25FA' and day==date_of('2026-01-06') else len(vals),n_samples=len(vals),
            vwc_sd_method='sample_sd',source_workbook=g.source_workbook.iloc[0],source_sheet=g.source_sheet.iloc[0],
            source_row_rule=g.conversion.iloc[0],date_inference_note='user_confirmed_real_date',
            quality_flag='out_of_season' if outside else 'ok',initial_condition_only=initial,
            phi_role='out_of_season' if outside else ('initial_condition_only' if initial else 'soil_water_phi'),
            dssat_layer_weights=format_weights(weights),weight_sum=sum(weights.values())))
    df=pd.DataFrame(rows)
    df.to_csv(out/'soil_water_observations.csv',index=False)
    raw.to_csv(out/'soil_water_samples.csv',index=False)
    build_layer_mapping_df(s,sorted(raw.depth.unique())).to_csv(out/'soil_water_layer_mapping.csv',index=False)
    return df


def depth_of(value):
    text=str(value).replace('cm','').replace('–','-').strip()
    a,b=text.split('-')
    return int(float(a)),int(float(b))


def soil_chemistry(s):
    if s=='25SP':
        df=read(s,'2025春初始土壤基础养分.xlsx','末-基础养分').rename(columns={
            '小区':'trno','重复':'rep','深度':'depth','全氮TN':'total_n_gkg','速效磷':'available_p',
            '速效钾Cmol':'available_k','pH':'ph'})
        som=read(s,'2025春土壤有机质估算与校准集.xlsx','25SP有机质逐样详表').rename(columns={
            '小区号':'trno','重复':'rep','土样深度':'depth','校准后有机碳SOC(%)':'organic_c_pct'})
        df=df.merge(som[['trno','rep','depth','organic_c_pct']],on=['trno','rep','depth'],validate='one_to_one')
    else:
        name='2026春土壤养分数据集.xlsx' if s=='26SP' else '2025秋土壤养分数据集.xlsx'
        df=read(s,name).rename(columns={'小区号':'trno','土样深度':'depth','全氮':'total_n_gkg',
                 'AP(mg/kg)':'available_p','速效钾 Cmol':'available_k','pH':'ph','有机质':'som'})
        df['organic_c_pct']=pd.to_numeric(df.som,errors='coerce')/1.724
    df=df[df.trno.isin(SPECS[s]['treatments'])].copy()
    df[['top','bottom']]=pd.DataFrame(df.depth.map(depth_of).tolist(),index=df.index)
    columns=['total_n_gkg','organic_c_pct','ph','available_p','available_k']
    if df[columns].isna().any().any():
        raise ValueError(f'{s}: missing soil chemistry: {df[columns].isna().sum().to_dict()}')
    return df.groupby(['trno','top','bottom'],as_index=False)[columns].mean()


def initial_sections(s,chem,water,out):
    ref=pd.read_excel(REF/'三季实验初始硝态氮铵态氮参考.xlsx')
    nh4_col=next(c for c in ref if '铵态' in str(c));no3_col=next(c for c in ref if '硝态' in str(c))
    n_mapped={}
    for key,col,deep in [('SNH4',nh4_col,.5),('SNO3',no3_col,1.)]:
        previous=0;intervals=[]
        for _,r in ref.iterrows():
            bottom=int(r.iloc[0]);intervals.append(DepthInterval(previous,bottom,float(r[col]),bulk_density(previous,bottom),'shared_prebasal_N'))
            previous=bottom
        intervals.extend([DepthInterval(100,140,deep,1.55,'deep_prior'),DepthInterval(140,180,deep,1.60,'deep_prior')])
        n_mapped[key],_=mapped_values(intervals,mass_weighted=True)
    # Soil-water dates remain truthful in the CSV; values are initial-state proxies.
    icday=SPECS[s]['water_date'] if s=='25FA' else SPECS[s]['start']
    a=['*SOIL ANALYSIS'];c=['*INITIAL CONDITIONS'];audit=[]
    for tn in SPECS[s]['treatments']:
        sub=chem[chem.trno==tn];mapped={}
        for col,deep,mass in [('organic_c_pct',.1,True),('total_n_gkg',.1,True),('ph',8.,False),
                               ('available_p',None,True),('available_k',None,True)]:
            iv=[DepthInterval(int(r.top),int(r.bottom),float(getattr(r,col)),bulk_density(int(r.top),int(r.bottom))) for r in sub.itertuples()]
            if deep is None:
                deep=next(r.value for r in iv if r.bottom==60)
            mapped[col],mapping=mapped_values(iv,mass_weighted=mass,deep_value=deep)
            audit.extend(dict(trno=tn,column=col,**r) for r in mapping)
        a.extend(['@A SADAT  SMHB  SMPX  SMKE  SANAME',f'{tn:2d} {code(SPECS[s]["water_date"])} SA012 SA001 SA001 TN{tn}',
                  '@A  SABL  SADM  SAOC  SANI SAPHW SAPHB  SAPX  SAKE  SASC'])
        for i,bottom in enumerate(GRID):
            a.append(f'{tn:2d}{bottom:6d}{PHYSICAL_LAYERS[i][6]:6.2f}{mapped["organic_c_pct"][i]:6.2f}'
                f'{mapped["total_n_gkg"][i]/10:6.3f}{mapped["ph"][i]:6.2f}{-99:6d}'
                f'{mapped["available_p"][i]:6.1f}{mapped["available_k"][i]:6.1f}{-99:6d}')
        sw=water[(water.trno==tn)&(water.date==SPECS[s]['water_date'])]
        if len(sw)!=5:
            raise ValueError(f'{s} TN{tn}: missing initial water depths')
        iv=[DepthInterval(int(r.depth_top_cm),int(r.depth_bottom_cm),float(r.vwc_mean)) for r in sw.itertuples()]
        last=next(r.value for r in iv if r.bottom==100)
        iv.extend([DepthInterval(100,140,min(.300,max(.165,last)),source='deep_prior'),
                   DepthInterval(140,180,min(.280,max(.160,last)),source='deep_prior')])
        water_vals,mapping=mapped_values(iv,mass_weighted=False)
        audit.extend(dict(trno=tn,column='SH2O',**r) for r in mapping)
        c.extend(['@C   PCR ICDAT  ICRT  ICND  ICRN  ICRE  ICWD ICRES ICREN ICREP ICRIP ICRID ICNAME',
                  f'{tn:3d}   TM {code(icday)}  0.00   -99   -99     1   -99 0.000   -99   -99   -99   -99 TN{tn}_prebasal',
                  '@C  ICBL  SH2O  SNH4  SNO3'])
        for i,bottom in enumerate(GRID):
            c.append(f'{tn:2d}{bottom:6d}{water_vals[i]:6.3f}{n_mapped["SNH4"][i]:6.2f}{n_mapped["SNO3"][i]:6.2f}')
        for key,vals in n_mapped.items():
            audit.extend(dict(trno=tn,column=key,target_bottom_cm=b,mapped_value=v) for b,v in zip(GRID,vals))
    pd.DataFrame(audit).assign(contributions=lambda d:d.contributions.map(lambda v:json.dumps(v) if isinstance(v,list) else '')).to_csv(
        out/'soil_depth_mapping_audit.csv',index=False)
    return '\n'.join(a), '\n'.join(c)


def replace_section(text,heading,replacement):
    lines=text.splitlines();start=next(i for i,l in enumerate(lines) if l.startswith(heading))
    end=next((i for i in range(start+1,len(lines)) if lines[i].startswith('*')),len(lines))
    return '\n'.join(lines[:start]+replacement.splitlines()+['']+lines[end:])+'\n'


def management(s,parsed,out):
    spec=SPECS[s];pname=spec['management'];treatments=parsed['treatments']
    detail=read(s,pname,'TMX施肥明细',header=None)
    start=next(i for i in range(len(detail)) if str(detail.iloc[i,0]).strip()=='施肥方案F')
    header=detail.iloc[start].tolist();fert=detail.iloc[start+1:].copy();fert.columns=header
    fert=fert[pd.to_numeric(fert['施肥方案F'],errors='coerce').notna()].copy()
    fert['施肥方案F']=fert['施肥方案F'].astype(int)
    fert=fert.sort_values(['施肥方案F','TMX日期码','TMX行号'])
    lines=['*FERTILIZERS (INORGANIC)','@F FDATE  FMCD  FACD  FDEP  FAMN  FAMP  FAMK  FAMC  FAMO  FOCD FERNAME']
    for _,r in fert.iterrows():
        amounts=[r['深度cm'],r['N kg/ha'],r['P kg/ha'],r['采用K kg/ha'],r['Ca kg/ha'],r['其他kg/ha'],0]
        # DSSAT FileX FDATE/FMCD are six-wide after a two-character factor.
        lines.append(f'{int(r["施肥方案F"]):2d} {int(r["TMX日期码"]):5d} {r["肥料编码"]:5s} {r["施用编码"]:5s}'
                     + ''.join(numeric_field('SNAM',v) for v in amounts)+f' {r["氮水平"]}')
    fert.to_csv(out/'fertilizer_event_audit.csv',index=False)
    irr=[]
    if s=='25SP':
        df=read(s,pname,'灌水数据',header=None)
        for j in range(2,16):
            tn=int(df.iloc[0,j])
            if tn not in spec['treatments']:continue
            for i in range(2,len(df)):
                if pd.isna(df.iloc[i,0]):continue
                irr.append(dict(trno=tn,date=date_of(df.iloc[i,0]),mm=float(df.iloc[i,j])))
    else:
        sheet='Sheet1' if s=='26SP' else '修正数据'
        df=read(s,pname,sheet,header=None);tncol=0 if s=='26SP' else 1;stop=25 if s=='26SP' else 16
        for i in range(1,13):
            tn=int(df.iloc[i,tncol])
            for j in range(2,stop):
                if pd.isna(df.iloc[0,j]):continue
                irr.append(dict(trno=tn,date=date_of(df.iloc[0,j]),mm=float(df.iloc[i,j])))
    irr=pd.DataFrame(irr);irr['factor']=irr.trno.map(lambda tn:treatments[tn]['MI'])
    ilines=['*IRRIGATION AND WATER MANAGEMENT']
    for factor,g in irr.groupby('factor'):
        reference=g[g.trno==g.trno.iloc[0]].sort_values('date')
        for tn,gg in g.groupby('trno'):
            if not np.allclose(gg.sort_values('date').mm,reference.mm):
                raise ValueError(f'{s}: treatment irrigation differs inside shared MI{factor}')
        ilines.extend(['@I  EFIR  IDEP  ITHR  IEPT  IOFF  IAME  IAMT IRNAME',
            f'{factor:2d}     1    20    80    95   -99   -99   -99 measured_water', '@I IDATE  IROP IRVAL'])
        for r in reference.itertuples():
            ilines.append(f'{factor:2d} {code(r.date):5d} IR005{r.mm:6.2f}')
    irr.to_csv(out/'irrigation_event_audit.csv',index=False)
    return '\n'.join(lines),'\n'.join(ilines)


def filex_outputs(s,out,old,chem,water,yield_df,growth):
    spec=SPECS[s];ex=spec['excode'];oldx=old/f'{ex}.TMX';text=oldx.read_text(encoding='utf-8-sig').replace('\x1a','')
    parsed=parse_filex(oldx)
    fields=filex_section_text(oldx,'*FIELDS')
    fields=re.sub(r'(?m)^(\s*\d+\s+\S+\s+)\S+(?=\s+-99)',r'\g<1>XXTW2403',fields)
    text=replace_section(text,'*FIELDS',fields)
    section=['*TREATMENTS                        -------------FACTOR LEVELS------------',
             '@N R O C TNAME.................... CU FL SA IC MP MI MF MR MC MT ME MH SM']
    metadata=[]
    for tn in spec['treatments']:
        g=growth[growth.trno==tn].iloc[0];w=str(g['水处理']);n=str(g['氮处理'])
        fac=parsed['treatments'][tn]
        section.append(f'{tn:2d} 1 0 0 {w+"_"+n:<25}'+''.join(f'{fac[k]:3d}' for k in ['CU','FL','SA','IC','MP','MI','MF','MR','MC','MT','ME','MH','SM']))
        metadata.append(dict(treatment=tn,treatment_label=f'{w}_{n}',water_level=w,nitrogen_level=n))
    text=replace_section(text,'*TREATMENTS','\n'.join(section))
    soil,initial=initial_sections(s,chem,water,out)
    text=replace_section(text,'*SOIL ANALYSIS',soil);text=replace_section(text,'*INITIAL CONDITIONS',initial)
    plant=filex_section_text(oldx,'*PLANTING DETAILS')
    plant=re.sub(r'(?m)^(\s*\d+\s+)\d{5}',lambda m:m[1]+str(code(spec['planting'])),plant)
    text=replace_section(text,'*PLANTING DETAILS',plant)
    fert,irr=management(s,parsed,out)
    text=replace_section(text,'*FERTILIZERS (INORGANIC)',fert);text=replace_section(text,'*IRRIGATION AND WATER MANAGEMENT',irr)
    oldh=filex_section_text(oldx,'*HARVEST DETAILS')
    template=next(l for l in oldh.splitlines() if l.strip() and l.strip()[0].isdigit())
    # Rebuilding an already generated FileX must not copy a fragment of its
    # free-text HNAME (e.g. the first letter of "measured_harvest") as an option.
    harvest_tokens=template.split()
    harvest_options=''.join(f'{v:>6}' for v in harvest_tokens[2:7])
    harvest_name=harvest_tokens[7] if len(harvest_tokens)>7 else 'ALL'
    mh={parsed['treatments'][tn]['MH'] for tn in spec['treatments']}
    h=['*HARVEST DETAILS','@H HDATE  HSTG  HCOM HSIZE   HPC  HBPC HNAME']
    harvest_dates=sorted(yield_df.date.unique());end=date_of(spec['end']);harvest_audit=[]
    for factor in sorted(mh):
        for day in harvest_dates:
            # CRGRO reports a scheduled multi-harvest in the following daily
            # FreshWt record. Keep observation dates real; align execution to
            # the output day, as in the existing bundle's one-day convention.
            execution=date_of(day)-pd.Timedelta(days=1)
            h.append(f'{factor:2d} {code(execution):5d}'+harvest_options+f' {harvest_name} measured_harvest')
            harvest_audit.append(dict(factor=factor,observed_harvest_date=str(date_of(day).date()),
                model_execution_date=str(execution.date()),model_output_date=str(date_of(day).date()),
                role='measured_harvest;one_day_CRGRO_output_lag'))
        if end!=date_of(harvest_dates[-1])-pd.Timedelta(days=1):
            # Retain the trial until terminal observations; this is NOT a measured harvest.
            h.append(f'{factor:2d} {code(end):5d}'+harvest_options+f' {harvest_name} terminal_observation_only')
            harvest_audit.append(dict(factor=factor,observed_harvest_date='',model_execution_date=str(end.date()),
                model_output_date='',role='terminal_observation_only;no_measured_harvest'))
    text=replace_section(text,'*HARVEST DETAILS','\n'.join(h))
    pd.DataFrame(harvest_audit).to_csv(out/'harvest_schedule_audit.csv',index=False)
    text=re.sub(r'(?m)^(\s*\d+ GE\s+\d+\s+\d+\s+S\s+)\d{5}',lambda m:m[1]+str(code(spec['start'])),text)
    text=text.replace('Quncy, FL','Xinxiang, China').replace('Drip irrigated, states to be N rates but only one set of data here Trt 14?',
           'Greenhouse eggplant water x nitrogen trial; current measured inputs')
    (out/f'{ex}.TMX').write_text(text,encoding='ascii')
    batch=['$BATCH(TOMATO)','! Rebuilt from current measured treatment list',
           '@FILEX                                                                                        TRTNO     RP     SQ     OP     CO']
    for tn in spec['treatments']:
        batch.append(f'{ex+".TMX":<93}{tn:6d}{1:7d}{0:7d}{0:7d}{0:7d}')
    (out/'DSSBatch.v48').write_text('\n'.join(batch)+'\n',encoding='ascii')
    pd.DataFrame(metadata).to_csv(out/'treatment_metadata.csv',index=False)
    soil_id=parsed['soil_id']
    # Exact inherited physical/surface parameters; only seasonal measured chemistry changes.
    sol=(old/'SOIL.SOL').read_text(encoding='utf-8-sig');lines=sol.splitlines()
    first=next(i for i,l in enumerate(lines) if l.startswith('*'+soil_id));last=next((i for i in range(first+1,len(lines)) if lines[i].startswith('*')),len(lines))
    profile=lines[first:last];chem_layers=soil_profile_chem(chem)
    header_idx=next(i for i,l in enumerate(profile) if l.startswith('@') and 'SLB' in l and 'SLLL' in l)
    idx=0
    for j in range(header_idx+1,len(profile)):
        if not profile[j].strip() or profile[j].lstrip().startswith(('!','@')):continue
        if not profile[j].split()[0].isdigit():continue
        slni,ph,soc=chem_layers[idx];line=profile[j]
        profile[j]=line[:48]+f'{soc:6.2f}'+line[54:72]+f'{slni:6.3f}{ph:6.2f}'+line[84:]
        idx+=1
    if idx!=10:raise ValueError('Expected 10 physical soil layers')
    (out/'SOIL.SOL').write_text('*SOILS: inherited physical profile; current seasonal chemistry\n'+ '\n'.join(profile)+'\n',encoding='ascii')


def decision_record(boundary=None):
    return dict(date=DATE,shared_initial_mineral_N='all_seasons_all_treatments;mg_N_kg_dry_soil;before_basal',
        weather_source='XXTW2403.WTH_all_seasons',TAV_AMP=boundary or 'awaiting_user_decision',
        spring_anthesis='existing_TMA_ADAT;25SP_2025-04-22;26SP_2026-04-20',
        maturity='MDAT_missing;former_PODD_proxy_not_a_confirmed_maturity_observation',
        autumn_planting='current_TMX_2025-08-13',autumn_terminal='current_TMX_2026-01-06',density_plants_ha=27000,
        dry_mass_units='g_plant_to_kg_ha_times_27',autumn_sample_pairing='mean_concentration_times_mean_mass',
        autumn_soil_sheet_20261002_real_date='2026-10-02;preserved_out_of_season;excluded_from_phi',
        autumn_dry_fraction=.05,initial_water_temporal_proxy='25SP_3days_and_26SP_2days_carry_back_to_prebasal_start',
        initial_water_hidden_scaling='none;26SP_TN10_TN12_no_0.82_multiplier',
        unpaired_autumn_uncertainty='sample_SD_descriptive;independent_plot_n_rep_unknown_set_0',
        observation_missing_policy='no_imputation;no_historical_rep_removal;no_legacy_observation_fallback',
        calibration_status='engineering_validated_inputs;not_parameter_calibration_or_science_validated_results')


def historical_bundle_directory(bundle_id):
    """Resolve an explicit archived baseline; never use it as a current default."""
    active=ROOT/'data/user/experiments'/bundle_id
    if active.is_dir():
        return active
    registry_path=ROOT/'configs/experiments/bundle_archive_index.json'
    registry=json.loads(registry_path.read_text(encoding='utf-8')) if registry_path.exists() else {}
    entry=registry.get('bundles',{}).get(bundle_id)
    if not entry:
        raise FileNotFoundError(f'Historical input baseline unavailable: {bundle_id}')
    archived=Path(entry['archive_path'])
    if sha(archived/'input_manifest.json')!=entry['manifest_sha256']:
        raise ValueError(f'Archived baseline manifest changed: {bundle_id}')
    verify_manifest_integrity(archived)
    return archived


def build(out_root):
    if out_root.exists() and any(out_root.iterdir()):raise FileExistsError(f'Refuse nonempty staging: {out_root}')
    out_root.mkdir(parents=True,exist_ok=True)
    for s,spec in SPECS.items():
        ex=spec['excode'];old=historical_bundle_directory(f'{ex.lower()}_refreshed_20261010')
        out=out_root/f'{ex.lower()}_refreshed_20261010';out.mkdir()
        growth,harvest=observation_outputs(s,out,old)
        water=soil_water(s,out);chem=soil_chemistry(s)
        filex_outputs(s,out,old,chem,water,harvest,growth)
        genotype_sources=[]
        for name in ['TMGRO048.CUL','TMGRO048.ECO','TMGRO048.SPE']:
            base=ROOT/'data/templates/genotype'/(name+'.base')
            shutil.copy2(base,out/name);genotype_sources.append(base)
        markers=pd.read_csv(REF/'人工处理值标记.csv')
        markers[markers['文件'].str.startswith(spec['folder'])].to_csv(out/'manual_value_markers.csv',index=False)
        write_json(out/'decision_record.json',decision_record())
        sources=[*sorted((REF/spec['folder']).glob('*.xlsx')),REF/'三季实验初始硝态氮铵态氮参考.xlsx',
                 REF/'XXTW2403.WTH',REF/'人工处理值标记.csv',REF/'数据口径与质控记录.md',
                 REF/'试验背景与数据说明_温室茄子水氮试验.md',REF/'果实干物质与采收养分核算补充说明.md',
                 old/f'{ex}.TMX',old/f'{ex}.TMA',old/'SOIL.SOL',*genotype_sources]
        write_json(out/'source_provenance.json',dict(generator=str(Path(__file__).relative_to(ROOT)),generator_sha256=sha(__file__),
            sources=[dict(path=str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),sha256=sha(p),size_bytes=p.stat().st_size,
                          role=('current_workbook_snapshot;some_auxiliary_only' if p.suffix=='.xlsx' else
                                'weather' if p.suffix=='.WTH' else 'baseline_genotype_template' if p.suffix=='.base' else
                                'source_policy_or_manual_marker_registry' if p.suffix in ['.md','.csv'] else
                                'approved_model_layout_or_anthesis')) for p in sources]))
        print(f'Built observations, management, soils: {out.name}',flush=True)


def weather_output(s,out,boundary):
    start=date_of(SPECS[s]['start']);end=date_of(SPECS[s]['end'])
    lines=(REF/'XXTW2403.WTH').read_text(encoding='utf-8-sig').splitlines()
    h=next(i for i,l in enumerate(lines) if l.startswith('@') and l.split()[1]=='DATE')
    header=lines[:h+1];idx=next(i for i,l in enumerate(header) if l.startswith('@ INSI'))
    # This installed DSSAT executable recognizes '$' as the long weather-file
    # marker required to read YYYYDDD. Leave the source workbook/file intact.
    header[0]='$'+header[0][1:]
    parts=header[idx+1].split();tav,amp=([20.,6.] if boundary=='existing' else [20.7,22.7])
    header[idx+1]=f'{parts[0]:>6s}{float(parts[1]):8.3f}{float(parts[2]):9.3f}{float(parts[3]):6.0f}{tav:6.1f}{amp:6.1f}{float(parts[6]):6.1f}'
    rows=[];days=[]
    for line in lines[h+1:]:
        tokens=line.split()
        if not tokens or not tokens[0].isdigit():continue
        day=pd.Timestamp(datetime.strptime(tokens[0],'%Y%j'))
        if start<=day<=end:
            if day in days:raise ValueError('Duplicate weather within simulation window')
            if float(tokens[2])<float(tokens[3]) or any(float(t)==-99 for t in tokens[1:]):
                raise ValueError('Invalid weather within simulation window')
            # XXTW2403 is a three-year file. DSSAT expects its original
            # seven-character YYYYDDD dates, not annual YYDDD records.
            rows.append(line)
            days.append(day)
    if set(days)!=set(pd.date_range(start,end)):raise ValueError(f'{s}: weather day coverage mismatch')
    (out/'XXTW2403.WTH').write_text('\n'.join(header+rows)+'\n',encoding='ascii')
    write_json(out/'weather_window_audit.json',dict(source_sha256=sha(REF/'XXTW2403.WTH'),source_file='XXTW2403.WTH',
       first_day=str(start.date()),last_day=str(end.date()),n_days=len(days),TAV=tav,AMP=amp,
       source_daily_values_preserved=True,source_dates_preserved_YYYYDDD=True,
       compatibility_format='long_file_title_marker_$;DSSAT_station_metadata_fixed_width',
       source_known_interpolation='2026-03-24 kept as approved source interpolation'))


def smoke(out,tag='',genotype_dir=None):
    run=ROOT/'workspace/qa'/f'input_smoke_{out.name}{tag}'
    if run.exists():raise FileExistsError(f'Refuse reused smoke directory: {run}')
    run.mkdir(parents=True)
    for p in out.iterdir():
        if p.suffix.upper() in ['.TMX','.TMA','.TMT','.WTH','.SOL'] or p.name=='DSSBatch.v48':shutil.copy2(p,run/p.name)
    genotype={}
    for name in ['TMGRO048.CUL','TMGRO048.ECO','TMGRO048.SPE']:
        base=Path(genotype_dir)/name if genotype_dir is not None else ROOT/'data/templates/genotype'/(name+'.base')
        shutil.copy2(base,run/name);genotype[name]=dict(path=str(base.relative_to(ROOT)),sha256=sha(base))
    exe=Path(r'C:\DSSAT48\DSCSM048.EXE')
    cp=subprocess.run([str(exe),'CRGRO048','B','DSSBatch.v48'],cwd=run,capture_output=True,text=True,timeout=180)
    (run/'console.txt').write_text(cp.stdout+'\n'+cp.stderr,encoding='utf-8')
    required=['Evaluate.OUT','PlantGro.OUT','SoilWat.OUT','SoilNi.OUT','FreshWt.OUT','Summary.OUT']
    missing=[name for name in required if not (run/name).is_file() or (run/name).stat().st_size==0]
    error=(run/'ERROR.OUT').read_text(errors='replace') if (run/'ERROR.OUT').exists() else ''
    expected=len(parse_filex(next(out.glob('*.TMX')))['treatments'])
    counts={name:sum(l.startswith('*DSSAT') for l in (run/name).read_text(errors='replace').splitlines()) for name in required if (run/name).exists()}
    warnings=(run/'Warning.OUT').read_text(errors='replace') if (run/'Warning.OUT').exists() else ''
    premature=any(term in warnings.lower() for term in ['simulation will end','weather record not found','error opening weather'])
    summary=read_summary(run/'Summary.OUT')
    season=next(s for s,v in SPECS.items() if v['excode']==next(out.glob('*.TMX')).stem)
    last_required=int(date_of(SPECS[season]['end']).strftime('%Y%j'))
    short_runs=[int(r.TRNO) for r in summary.itertuples() if r.HDAT<last_required]
    from src.dssat.run_dssat import _read_soilwat_by_run, _soil_observation_records
    soil_by_run=_read_soilwat_by_run(str(run/'SoilWat.OUT'))
    fresh=read_daily_output(run/'FreshWt.OUT')
    nitrogen=read_daily_output(run/'SoilNi.OUT')
    parsed=parse_filex(next(out.glob('*.TMX')))
    treatment_list=SPECS[season]['treatments']
    irrigation=pd.read_csv(out/'irrigation_event_audit.csv')
    fertilizer=pd.read_csv(out/'fertilizer_event_audit.csv')
    observation=read_dssat_observation_table(next(out.glob('*.TMT')))
    scientific_failures=[];reconciliation=[]
    for runno,tn in enumerate(treatment_list,1):
        factor=parsed['treatments'][tn]
        row=summary[summary.TRNO==tn].iloc[0]
        irr_events=irrigation[irrigation.trno==tn]
        irr_expected=irr_events.mm.sum()
        # Native DSSAT48.INP prints each irrigation to 0.1 mm; Summary.OUT
        # then prints the cumulative value to integer mm. Bound both steps.
        irr_tolerance=.5+.05*len(irr_events)
        n_expected=fertilizer[fertilizer['施肥方案F']==factor['MF']]['N kg/ha'].sum()
        if abs(row.IRCM-irr_expected)>irr_tolerance or abs(row.NICM-n_expected)>.51:
            scientific_failures.append(f'TN{tn}: irrigation/fertilizer was not fully read')
        initial=parsed['initial_conditions'][factor['IC']];previous=0;expected_no3=0;expected_nh4=0
        for i,layer in enumerate(initial):
            dry_soil_mass_factor=(layer['depth']-previous)*PHYSICAL_LAYERS[i][6]*.1
            expected_no3+=layer['sno3']*dry_soil_mass_factor
            expected_nh4+=layer['snh4']*dry_soil_mass_factor;previous=layer['depth']
        initial_n=nitrogen[runno][min(nitrogen[runno])]
        if not np.isclose(initial_n['NITD'],expected_no3,rtol=.02,atol=.1) or not np.isclose(initial_n['NHTD'],expected_nh4,rtol=.02,atol=.1):
            scientific_failures.append(f'TN{tn}: initial N inventory differs from approved layer values')
        for date in observation[(observation.TRNO==tn)&(observation.CHFPW!=-99)].DATE.astype(int):
            event=fresh[runno].get(date,{})
            if not event or event.get('CHNUM',0)!=len(observation[(observation.TRNO==tn)&(observation.CHFPW!=-99)&(observation.DATE<=date)]):
                scientific_failures.append(f'TN{tn}: harvest record does not include event at {date}')
        for rec in _soil_observation_records(str(out/'soil_water_observations.csv')):
            if rec['trno']==tn and rec['date_code'] not in soil_by_run[runno]:
                scientific_failures.append(f'TN{tn}: no exact soil-water output on {rec["date_code"]}')
        reconciliation.append(dict(trno=tn,initial_NO3_expected_kg_ha=expected_no3,initial_NO3_sim_kg_ha=initial_n['NITD'],
            initial_NH4_expected_kg_ha=expected_nh4,initial_NH4_sim_kg_ha=initial_n['NHTD'],
            irrigation_source_mm=irr_expected,irrigation_sim_mm=row.IRCM,irrigation_serialization_tolerance_mm=irr_tolerance,
            fertilizer_N_source_kg_ha=n_expected,fertilizer_N_sim_kg_ha=row.NICM,
            fertilizer_P_source_kg_ha=float(fertilizer[fertilizer['施肥方案F']==factor['MF']]['P kg/ha'].sum()),
            fertilizer_P_sim_kg_ha=float(row.PICM)))
    report=dict(run_directory=str(run),returncode=cp.returncode,missing_outputs=missing,error_out=error,
                expected_treatments=expected,output_run_headers=counts,genotype_source=genotype,executable_sha256=sha(exe))
    report.update(premature_termination_warning=premature,required_terminal_date_YYYYDDD=last_required,
                  treatments_not_reaching_terminal=short_runs,summary_rows=summary.to_dict('records'),
                  scientific_readback_failures=scientific_failures,input_readback_reconciliation=reconciliation)
    write_json(run/'smoke_report.json',report)
    if cp.returncode or missing or error.strip() or premature or short_runs or scientific_failures or len(summary)!=expected or any(counts.get(n)!=expected for n in ['PlantGro.OUT','SoilWat.OUT','SoilNi.OUT','FreshWt.OUT']):
        raise RuntimeError(f'DSSAT smoke failed ({run}): returncode={cp.returncode}; missing={missing}; '
                           f'short_runs={short_runs}; readback_failures={scientific_failures}; see smoke_report.json')
    return report


def read_daily_output(path):
    result={};runno=None;header=None
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith('*RUN'):
            runno=int(line.split()[1]);header=None
        elif line.startswith('@YEAR'):
            header=line.lstrip('@').split()
        elif runno and header and line.strip() and line.strip()[0].isdigit():
            parts=line.split()
            if len(parts)!=len(header):raise ValueError(f'{path.name}: data/header mismatch')
            values={c:float(v) for c,v in zip(header,parts)}
            day=int(values['YEAR'])%100*1000+int(values['DOY'])
            result.setdefault(runno,{})[day]=values
    return result


def read_summary(path):
    header=None;rows=[];ends=[]
    for line in path.read_text(errors='replace').splitlines():
        if line.startswith('@'):
            matches=list(re.finditer(r'\S+',line))[1:]
            header=[m.group() for m in matches];ends=[m.end() for m in matches]
        elif header and line.strip() and line.strip()[0].isdigit():
            # Text fields may contain spaces; Summary.OUT is fixed width.
            tokens=[line[a:b].strip() for a,b in zip([0]+ends[:-1],ends)]
            rows.append(dict(zip(header,tokens)))
    df=pd.DataFrame(rows)
    for col in ['TRNO','PDAT','HDAT','IRCM','NICM','PICM','IR#M','NI#M']:
        df[col]=pd.to_numeric(df[col])
    return df


def check_weather_alternatives(out_root):
    """Validate two explicit scenarios without choosing or promoting either."""
    report={}
    for boundary in ['existing','source']:
        candidates=ROOT/'workspace/qa/thermal_boundary_inputs_20261010'/boundary
        if candidates.exists():raise FileExistsError(f'Refuse reused candidate directory: {candidates}')
        candidates.mkdir(parents=True)
        for s,spec in SPECS.items():
            name=f'{spec["excode"].lower()}_refreshed_20261010'
            out=candidates/name;shutil.copytree(out_root/name,out)
            weather_output(s,out,boundary)
            audit,_=audit_observation_bundle(out)
            if audit['error_count']:raise ValueError(audit['findings'])
            result=smoke(out,tag='_thermal_'+boundary)
            report[f'{s}_{boundary}']=result
            print(f'Weather scenario smoke passed: {s} {boundary}',flush=True)
    write_json(ROOT/'workspace/audits/input_refresh_20261010/thermal_scenario_smoke.json',report)


def finalize(out_root,boundary,promote=False):
    completed=[]
    for s,spec in SPECS.items():
        out=out_root/f'{spec["excode"].lower()}_refreshed_20261010'
        if (out/'input_manifest.json').exists():raise FileExistsError('Refuse rewriting finalized bundle')
        provenance=json.loads((out/'source_provenance.json').read_text(encoding='utf-8'))
        for r in provenance['sources']:
            if sha(ROOT/r['path'])!=r['sha256']:raise ValueError(f'Source changed during build: {r["path"]}')
        weather_output(s,out,boundary)
        write_json(out/'decision_record.json',decision_record(boundary))
        audit,events=audit_observation_bundle(out)
        write_json(out/'input_quality_audit.json',audit)
        events.to_csv(out/'harvest_increment_reconciliation.csv',index=False)
        errors=[r for r in audit['findings'] if r['severity']=='error']
        if errors:raise ValueError(f'{s}: bundle audit failed: {errors}')
        report=smoke(out);write_json(out/'dssat_smoke_report.json',report)
        acceptance=ROOT/'workspace/audits/input_refresh_20261010/calibration_reader_acceptance.json'
        candidate=ROOT/'workspace/qa/thermal_boundary_inputs_20261010'/boundary/out.name
        if acceptance.exists() and candidate.exists():
            for p in out.iterdir():
                if p.suffix.upper() in ['.TMX','.TMA','.TMT','.WTH','.SOL','.CUL','.ECO','.SPE'] or p.name=='DSSBatch.v48':
                    if sha(p)!=sha(candidate/p.name):raise ValueError('Calibration-reader acceptance input differs from finalized input')
            record=json.loads(acceptance.read_text(encoding='utf-8'))[f'{s}_{boundary}']
            write_json(out/'calibration_reader_acceptance.json',record)
        manifest=dict(bundle_id=out.name,created=DATE,season=s,immutable=True,
            intended_use='calibration_and_validation_inputs;not_calibrated_results',
            source_provenance_sha256=sha(out/'source_provenance.json'),generator_sha256=sha(__file__),
            decision_record=decision_record(boundary),engineering_checks='input_audit_and_baseline_DSSAT_smoke_passed',
            files=[dict(name=p.name,sha256=sha(p),size_bytes=p.stat().st_size) for p in sorted(out.iterdir()) if p.is_file()])
        write_json(out/'input_manifest.json',manifest);verify_manifest_integrity(out)
        completed.append((s,out))
        print(f'Finalized and verified: {out.name}',flush=True)
    if promote:
        destinations=[ROOT/'data/user/experiments'/p.name for _,p in completed]
        if any(p.exists() for p in destinations):raise FileExistsError('Refuse overwriting an immutable input bundle')
        for (_,source),dest in zip(completed,destinations):
            shutil.copytree(source,dest);verify_manifest_integrity(dest)
        index=dict(as_of=DATE,notes=f'Current workbook refresh; XXTW2403 all seasons; TAV/AMP {boundary}; baseline smoke passed',
                   bundles={s:dict(bundle_id=p.name,manifest_sha256=sha(p/'input_manifest.json')) for (s,_),p in zip(completed,destinations)})
        write_json(ROOT/'configs/experiments/current_bundles.json',index)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-root',type=Path,default=ROOT/'workspace/staging/input_refresh_20261010')
    parser.add_argument('--finalize',action='store_true')
    parser.add_argument('--weather-boundary',choices=['existing','source'])
    parser.add_argument('--promote',action='store_true')
    parser.add_argument('--check-weather-alternatives',action='store_true')
    args=parser.parse_args()
    if args.check_weather_alternatives:
        check_weather_alternatives(args.out_root)
    elif args.finalize:
        if not args.weather_boundary:parser.error('--finalize requires an explicit --weather-boundary decision')
        finalize(args.out_root,args.weather_boundary,args.promote)
    else:
        if args.promote:parser.error('--promote requires --finalize')
        build(args.out_root)


if __name__=='__main__':
    main()
