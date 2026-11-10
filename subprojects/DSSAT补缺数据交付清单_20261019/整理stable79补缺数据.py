"""Reproducible scientific CSV delivery from the exact retained native replay.

No calibration, date shifts, invented replicates, P/K proxies or model edits.
"""
from pathlib import Path
import json,re,math,hashlib,shutil
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parent/'critical_n/n_buffer_v13'
BASE=PROJECT/'runs/stable79_checkpointed150x5_20261018'
RAW=ROOT/'原始模型输出/stable79_checkpointed150x5_20261019'
OUT=ROOT/'已填数据_stable79_20261019'
OUT.mkdir(exist_ok=True)
receipt=json.loads((RAW/'last_success.json').read_text(encoding='utf8'))
TRIAL=Path(receipt['trial'])
design=json.loads((PROJECT/'configs/capacity_a_stable79_checkpointed_r4.json').read_text(encoding='utf8'))
TEMPLATE=ROOT/'填报模板'
SEASON={'26SP':'2026春','25SP':'2025春'}
PLANT={'26SP':'2026-03-14','25SP':'2025-03-16'}
END={'26SP':'2026-07-17','25SP':'2025-07-13'}
FIRST={'26SP':'2026-05-26','25SP':'2025-05-20'}
LAYERS=[(0,5),(5,15),(15,30),(30,40),(40,50),(50,60),(60,70),(70,80),(80,100),(100,120),(120,140),(140,160),(160,180)]

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def js(p,q):Path(p).write_text(json.dumps(q,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def iso(code):
    v=int(code);return (pd.Timestamp(v//1000,1,1)+pd.Timedelta(days=v%1000-1)).strftime('%Y-%m-%d')
def previous(date):return (pd.Timestamp(date)-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
def dat(s,date):return (pd.Timestamp(date)-pd.Timestamp(PLANT[s])).days
def source(s,file,trt):return f'{(TRIAL/s/file).relative_to(ROOT).as_posix()};TRT={trt}'
def save(name,rows,template=None,extras=()):
    q=rows.copy() if isinstance(rows,pd.DataFrame) else pd.DataFrame(rows)
    if template:
        cols=list(pd.read_csv(TEMPLATE/template,nrows=0).columns)+list(extras)
        q=q.reindex(columns=cols)
    q.to_csv(OUT/name,index=False,encoding='utf-8-sig',float_format='%.12g',na_rep='')
    return q

def native(path):
    records=[];header=None;run=trt=None
    for line in path.read_text(encoding='utf8').splitlines():
        m=re.match(r'\*RUN\s+(\d+)',line)
        if m:run=int(m[1]);trt=None;header=None
        m=re.match(r'\s*TREATMENT\s+(\d+)',line)
        if m:trt=int(m[1])
        if line.lstrip().startswith('@YEAR'):header=line.strip().lstrip('@').split()
        elif header and re.match(r'\s*20\d{2}\s+\d+',line):
            widths=([5,4,6,6]+[8]*25 if path.name=='FreshWt.OUT'else
                    [5,4,6,6]+[8]*30+[10,8,8] if path.name=='PlantP.OUT'else None)
            if widths:
                pos=0;values=[]
                for width in widths:values.append(line[pos:pos+width].strip());pos+=width
                if line[pos:].strip():raise ValueError('Unexpected fixed-width tail '+str(path))
            else:values=line.split()
            if len(values)!=len(header) or trt is None or run is None:raise ValueError('Native row identity '+str(path))
            bad=[name for name,value in zip(header,values)if '*'in value]
            if bad and path.name!='PlantP.OUT':raise ValueError('Native overflow '+str(path)+' '+str(bad))
            q=dict(zip(header,[float(v)if '*'not in v else np.nan for v in values]))
            if path.name!='PlantP.OUT'and not all(math.isfinite(v)for v in q.values()):raise ValueError('Nonfinite output')
            if path.name=='PlantP.OUT':q['native_missing_fields']=';'.join(bad)
            q.update(trno=trt,run=run,date=iso(int(q['YEAR'])*1000+int(q['DOY'])));records.append(q)
    q=pd.DataFrame(records)
    assert not q.empty and not q.duplicated(['trno','date']).any(),path
    return q.set_index(['trno','date']).sort_index()

def ledger(work,name):
    q=pd.read_csv(work/(name+'.csv'));q['date']=q.yrdoy.map(iso)
    assert not q.duplicated(['trt','date']).any()
    return q.set_index(['trt','date']).sort_index()

runmap=pd.read_csv(TEMPLATE/'01_运行与处理对应.csv').fillna('')
all_water=[];all_soil=[];all_org=[];all_daily_org=[];all_events=[];all_extra=[];all_period=[]
all_cal=[];all_N=[];all_P=[];event_checks=[];pissues=[];summary_rows=[];input_diffs=[]
comparison=pd.read_csv(TRIAL/'comparison.csv');diagnostics=pd.read_csv(TRIAL/'diagnostic_comparison.csv')
requests=pd.read_csv(ROOT/'02_日期与区间.csv')
organ_targets=pd.read_csv(TEMPLATE/'04_器官状态.csv')
soil_targets=pd.read_csv(TEMPLATE/'03_边界土壤水.csv')
event_targets=pd.read_csv(TEMPLATE/'05_采收与其他移出.csv')

for ds in design['datasets']:
    s=ds['season_id'];season=SEASON[s];work=TRIAL/s
    frames={n:native(work/(n+'.OUT'))for n in ['ET','SoilWat','SoilWatBal','FreshWt','PlantGro','PlantN','PlantP','Weather']}
    dm=ledger(work,'DMState');ns=ledger(work,'OrganNState');nb=ledger(work,'NCBalance')
    metadata=pd.read_csv(work/'treatment_metadata.csv').set_index('treatment')
    fertil=pd.read_csv(work/'fertilizer_event_audit.csv')
    for ix,r in runmap[runmap.season.eq(season)].iterrows():
        trt=int(r.source_plot_code);keybase=dict(season=season,run_id=r.run_id,W=r.W,N=r.N,block_id='',ensemble_id='stable79_best_deterministic')
        assert metadata.loc[trt,'water_level']==r.W and metadata.loc[trt,'nitrogen_level']==r.N
        et=frames['ET'].xs(trt);sw=frames['SoilWat'].xs(trt);wb=frames['SoilWatBal'].xs(trt)
        fr=frames['FreshWt'].xs(trt);pg=frames['PlantGro'].xs(trt);pn=frames['PlantN'].xs(trt)
        dd=dm.xs(trt);nn=ns.xs(trt);bb=nb.xs(trt);pp=frames['PlantP'].xs(trt)
        assert set(dd.index)==set(nn.index)==set(bb.index)==set(pg.index)
        # Current exact engine has no intercepted-water or mulch evaporation.
        assert et.EFAA.eq(0).all() and et.EMAA.eq(0).all()
        assert (et.ETAA-et.EPAA-et.ESAA).abs().max()<=.001001
        assert (et.EPAA-wb.loc[et.index,'EPAD']).abs().max()<=.005001
        assert (et.ESAA-wb.loc[et.index,'ESAD']).abs().max()<=.005001
        def storage(date,depth=100):
            row=sw.loc[date]
            return sum(float(row[f'SW{i}D'])*max(0,min(bottom,depth)-top)*10 for i,(top,bottom)in enumerate(LAYERS,1)if top<depth)
        # Model SW output is end of day. BOD is previous EOD, not a new simulation.
        start='2025-03-12'if s=='25SP'else PLANT[s]
        dates=pd.date_range(start,END[s]).strftime('%Y-%m-%d')
        for date in dates:
            e=et.loc[date];w=wb.loc[date]
            all_water.append(keybase|dict(date=date,DAT=dat(s,date),ET_actual_mm=e.ETAA,transp_actual_mm=e.EPAA,evap_soil_actual_mm=e.ESAA,
                irrigation_applied_mm=w.IRRD,irrigation_infiltrated_mm=w.IRRD,precip_effective_mm=w.PRED,runoff_mm=w.ROFD,
                drainage_below100_mm=None,capillary_into100_mm=None,balance_depth_cm=180,value_origin='SIMULATED',
                source_file=source(s,'ET.OUT',trt)+';'+source(s,'SoilWatBal.OUT',trt),
                notes='FROP=1;ETAA/EPAA/ESAA为逐日实际量;EFIR=1，IRRD施用=有效灌水;100cm通量未输出，不填0；180cm底排水另表'))
            all_extra.append(keybase|dict(date=date,DAT=dat(s,date),state_timing='EOD',storage_0_100_mm=storage(date),storage_0_180_mm=w.SWTD,
                drainage_model_bottom_180_mm=w.DRND,lateral_inflow_net_mm=w.LFLOD,flood_outflow_mm=w.FROD,tile_drain_mm=w.TDFD,
                native_WBAL_mm=w.WBAL,native_CUMWBAL_mm=w.CUMWBAL,water_root_depth_cm=pg.loc[date,'RDPD']*100 if date in pg.index else None,
                value_origin='DERIVED',source_file=source(s,'SoilWat.OUT',trt)+';'+source(s,'SoilWatBal.OUT',trt)))
        for date in sorted(set(soil_targets[soil_targets.run_id.eq(r.run_id)].date)):
            for timing,srcdate in [('EOD',date),('BOD_DERIVED_PREV_EOD',previous(date))]:
                if srcdate not in sw.index:continue
                row=sw.loc[srcdate]
                for i,(top,bottom)in enumerate(LAYERS,1):
                    theta=float(row[f'SW{i}D'])
                    all_soil.append(keybase|dict(date=date,DAT=dat(s,date),state_timing=timing,layer_top_cm=top,layer_bottom_cm=bottom,
                        theta_v_m3_m3=theta,layer_storage_mm=theta*(bottom-top)*10,value_origin='DERIVED',source_file=source(s,'SoilWat.OUT',trt),
                        notes=f'原生层SW{i}D，状态源日期{srcdate}；日初为前日日末近似，不代表已观测的灌前瞬时值；含水率原打印分辨率0.001'))
        def organ_row(date,organ,timing='EOD_POST_HARVEST',target=''):
            d=dd.loc[date];n=nn.loc[date];balance=bb.loc[date]
            name={'leaf':'leaf','stem':'stem','root':'root'}.get(organ)
            mass=float(d[name+'_dm'] if name else d.shell_dm+d.seed_dm)*10
            nitrogen=float(n[name+'_n']if name else n.fruit_n)*10
            fresh=number=None
            if organ=='fruit_onplant':
                if date in fr.index:
                    f=fr.loc[date];fresh=float(f.TOFPW-f.HFPOW)
                    number=float(f.TOSHN)*10000 if d.harvest_dm==0 else (0. if mass==0 else None)
                    # TOPOW/TOFPW are pre-removal cohort totals; ledger is EOD.
                    assert abs(float(f.TOPOW)-mass-float(d.harvest_dm)*10)<=.10001
                    assert fresh>=-.60001
                    fresh=0. if mass==0 else (fresh if fresh>=0 else None)
                elif mass==0:fresh=number=0.
                if timing=='PRE_HARVEST_RECONSTRUCTED':
                    mass+=float(d.harvest_dm)*10;nitrogen+=float(balance.harvest_n)*10
                    fresh=float(fr.loc[date,'TOFPW'])
                    number=float(fr.loc[date,'TOSHN'])*10000
            note='P/K未填写：P分器官及多次采收未通过对应核验，K过程关闭。N总量已含内部储库子集，未重复相加。'
            if date==PLANT[s]:note+='本行为模型移栽初始日末量，不能称独立实测苗携入量。'
            if timing=='PRE_HARVEST_RECONSTRUCTED':note+='采出量加回形成收支等价事件前状态；茎叶取同日末，不主张日内精确同步。'
            if date==END[s] and s=='25SP'and organ=='fruit_onplant':note+='含本轮模拟末期未采果；与原少量不计口径另列。'
            if date==END[s] and s=='26SP'and organ=='fruit_onplant'and mass>1e-8:note+='模型末期仍有在株果，不能据此推翻现场无未采果事实。'
            return keybase|dict(date=date,DAT=dat(s,date),state_timing=timing,organ=organ,fruit_maturity_group='total'if organ=='fruit_onplant'else'',
                drymatter_kg_ha=mass,freshmass_kg_ha=fresh,number_per_ha=number,N_kg_ha=nitrogen,P_kg_ha=None,K_kg_ha=None,
                N_g_kg_DM=nitrogen/mass*1000 if mass>0 else None,P_g_kg_DM=None,K_g_kg_DM=None,value_origin='DERIVED',
                source_file=source(s,'DMState.csv',trt)+';'+source(s,'OrganNState.csv',trt)+((';'+source(s,'NCBalance.csv',trt))if timing.startswith('PRE_')else''),target_note=target,notes=note)
        for date in dd.index:
            for organ in ['stem','leaf','fruit_onplant','root']:
                row=organ_row(date,organ,'POST_TRANSPLANT_MODEL_EOD'if date==PLANT[s]else'EOD_POST_HARVEST')
                all_daily_org.append(row)
        selected=organ_targets[organ_targets.run_id.eq(r.run_id)]
        for date in sorted(selected.date.unique()):
            for organ in ['stem','leaf','fruit_onplant','root']:
                target='模型初始苗日末量'if date==PLANT[s]else'请求日期模型日末状态'
                all_org.append(organ_row(date,organ,'POST_TRANSPLANT_MODEL_EOD'if date==PLANT[s]else'EOD_POST_HARVEST',target))
                if date in fr.index and float(dd.loc[date,'harvest_dm'])>0:
                    all_org.append(organ_row(date,organ,'PRE_HARVEST_RECONSTRUCTED','同日采出量加回的收支等价事件前状态'))
        actual=fr[(fr.HPODW>0)|(fr.HFPOW>0)].index
        requested_events=set(event_targets[event_targets.run_id.eq(r.run_id)].date)
        for date in sorted(set(actual)|requested_events):
            d=dd.loc[date];b=bb.loc[date];f=fr.loc[date]
            hd=float(d.harvest_dm)*10;hn=float(b.harvest_n)*10
            all_events.append(keybase|dict(date=date,DAT=dat(s,date),event_timing='MODEL_ACTUAL_EVENT_INTEGRATION',event_type='HARVEST',organ='fruit',quantity_scope='EVENT',
                freshmass_kg_ha=f.HFPOW,drymatter_kg_ha=hd,N_kg_ha=hn,P_kg_ha=None,K_kg_ha=None,value_origin='DERIVED',
                source_file=source(s,'FreshWt.OUT',trt)+';'+source(s,'DMState.csv',trt)+';'+source(s,'NCBalance.csv',trt),
                notes='整果=果皮果肉(shell)+种子(seed)；N来自真实采出账本；P/K留空。未把累计采出再当本次量。'))
            event_checks.append(dict(season=season,run_id=r.run_id,date=date,harvest_dm_ledger_kg_ha=hd,HPODW=f.HPODW,
                pre_fruit_dm_kg_ha=f.TOPOW,post_fruit_dm_kg_ha=(float(d.shell_dm)+float(d.seed_dm))*10,
                pre_post_harvest_residual_kg_ha=float(f.TOPOW)-(float(d.shell_dm)+float(d.seed_dm))*10-hd))
        cum=bb.root_input.cumsum()*10
        for date,b in bb.iterrows():
            all_N.append(keybase|dict(date=date,DAT=dat(s,date),root_uptake_N_kg_ha=float(b.root_input)*10,
                root_uptake_cumulative_N_kg_ha=float(cum.loc[date]),harvest_N_kg_ha=float(b.harvest_n)*10,
                harvest_cumulative_N_kg_ha=float(bb.loc[:date,'harvest_n'].sum())*10,nonharvest_wholeplant_N_loss_kg_ha=float(b.outside_loss-b.harvest_n)*10,
                fixation_N_kg_ha=float(b.fixation_input)*10,initial_plant_and_seed_N_kg_ha=float(bb.begin_plant_and_seed_n.iloc[0])*10,
                end_plant_and_seed_N_kg_ha=float(b.end_plant_and_seed_n)*10,N_balance_residual_kg_ha=float(b.plant_residual)*10,
                value_origin='DERIVED',
                notes='累计根吸收不含初始苗/种子N、内部转运或固氮。非采收总N损失未分离落叶/根/整枝；不可当作地上部整枝量。',
                source_file=source(s,'NCBalance.csv',trt)))
        # Preserve generic P output as unvalidated auxiliary data, not filled P stocks.
        for date,p in pp.iterrows():
            all_P.append(keybase|dict(date=date,DAT=dat(s,date),generic_shoot_combined_P_kg_ha=p.SHPAD,generic_root_P_kg_ha=p.RTPAD,
                generic_shell_P_kg_ha=p.SLPAD,generic_seed_P_kg_ha=p.SDPAD,generic_plant_P_kg_ha=p.PPAD,
                generic_shell_DM_kg_ha=p.SHAD,generic_seed_DM_kg_ha=p.GWAD,P_grow_state_timing='GENERIC_P_PRE_CROPGRO_GROW',
                status='NOT_VALIDATED_FOR_GAP_FILL',value_origin='SIMULATED',native_missing_fields=p.native_missing_fields,source_file=source(s,'PlantP.OUT',trt)))
            if date in dd.index and float(dd.loc[date,'shell_dm']+dd.loc[date,'seed_dm'])==0 and p.SLPAD+p.SDPAD>.001:
                pissues.append(dict(season=season,run_id=r.run_id,date=date,post_fruit_dm_kg_ha=0,generic_P_fruit_kg_ha=p.SLPAD+p.SDPAD))
        for interval in requests[requests.season.eq(season)].to_dict('records'):
            start,end=interval['start_date'],interval['end_date_exclusive'];wanted=pd.date_range(start,pd.Timestamp(end)-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            assert set(wanted)<=set(et.index)
            q=et.loc[wanted];w=wb.loc[wanted]
            all_period.append(keybase|interval|dict(start_DAT=dat(s,start),end_DAT_exclusive=dat(s,end),n_daily_rows=len(q),
                ET_actual_mm=q.ETAA.sum(),ET_intensity_mm_d=q.ETAA.mean(),transp_actual_mm=q.EPAA.sum(),evap_soil_actual_mm=q.ESAA.sum(),
                irrigation_effective_mm=w.IRRD.sum(),precip_effective_mm=w.PRED.sum(),runoff_mm=w.ROFD.sum(),drainage_model_bottom_180_mm=w.DRND.sum(),
                storage_start_BOD_0_100_mm=storage(previous(start)),storage_end_BOD_0_100_mm=storage(previous(end)),
                delta_storage_0_100_mm=storage(previous(end))-storage(previous(start)),value_origin='DERIVED',
                notes='严格[start,end)，日初贮水取前日日末；180cm排水不等于100cm下渗；纯模型ET，未按观测窗口重标定。'))
        for table,role in [(comparison,'CALIBRATION'),(diagnostics,'CHECK')]:
            selected=table[table.season_id.eq(s)&table.trno.eq(trt)]
            for q in selected.to_dict('records'):
                unit=q.get('unit','')
                if not isinstance(unit,str)or not unit:
                    unit={'SWAD':'kg DM/ha','LWAD':'kg DM/ha','CHPDT':'kg DM/ha','HPODW':'kg DM/ha','CHFPW':'kg fresh/ha','HFPOW':'kg fresh/ha',
                          'LNAM':'kg N/ha','SNAM':'kg N/ha','LEAF_N_PCT':'% DM','STEM_N_PCT':'% DM','FRUIT_N_PCT':'% DM','PDMCD':'kg DM/kg fresh',
                          'CHTD':'m','LAID':'m2/m2','VWC':'m3/m3','WB100_INTERVAL':'mm','ADAP':'day'}.get(q['variable'],'kg fresh/ha')
                all_cal.append(keybase|dict(variable=q['variable'],unit=unit,start_date=q.get('interval_start')if pd.notna(q.get('interval_start'))else q['date'],
                    end_date_exclusive=q['interval_end']if pd.notna(q.get('interval_end'))else'',
                    state_timing='MODEL_NATIVE_DAILY_EVENT_STATE',observed_value=q['observed'],simulated_value=q['simulated'],data_use=role,
                    observation_source=q.get('source_file',''),notes='指定stable79原协议：两春均参与率定；点状态日期置start_date，非ET积分窗；未匹配保持空值。'+('WB100原算子为闭开区间水量平衡代理量，不是独立ET实测；原字段另表保存。'if q['variable']=='WB100_INTERVAL'else'')))
        totalI=float(wb.IRRD.sum());totalN=float(fertil[fertil['氮水平'].eq(r.N)]['N kg/ha'].sum())
        runmap.loc[ix,['ensemble_id','simulation_run_number','model','cultivar','simulated_I_applied_mm','simulated_I_infiltrated_mm','simulated_N_applied_kg_ha','source_directory','notes']]=[
            'stable79_best_deterministic',int(pg.run.iloc[0]),'DSSAT 4.8.2 CRGRO048 custom capacity_a (eggplant on tomato)','TM0008/TM0001',totalI,totalI,totalN,
            (work.relative_to(ROOT)).as_posix(),'处理级确定性模拟，无区组重复；两春均为率定集。I为原生有效灌水(EFIR=1)，施N含定植前基肥；不覆盖预填实测投入。']
        input_diffs.append(dict(season=season,run_id=r.run_id,observed_I_mm=float(r.observed_I_mm),model_I_mm=totalI,I_difference_mm=totalI-float(r.observed_I_mm),observed_N_kg_ha=float(r.observed_N_kg_ha),model_N_kg_ha=totalN))

save('01_运行与处理对应.csv',runmap,'01_运行与处理对应.csv')
save('02_逐日水量.csv',all_water,'02_逐日水量.csv',['DAT'])
save('03_边界土壤水.csv',all_soil,'03_边界土壤水.csv',['DAT'])
save('04_器官状态.csv',all_org,'04_器官状态.csv',['DAT'])
save('05_采收与其他移出.csv',all_events,'05_采收与其他移出.csv',['DAT'])
save('07_校准与验证记录.csv',all_cal,'07_校准与验证记录.csv')
save('08_分期与观测窗口ET汇总.csv',all_period)
save('09_逐日180cm水量与100cm贮水.csv',all_extra)
save('10_逐日器官干物质与N状态.csv',all_daily_org,'04_器官状态.csv',['DAT'])
save('11_逐日根吸N与采出损失账本.csv',all_N)
save('12_原生P输出_未经补缺适用性验证.csv',all_P)
save('13_采收前后干物质对账.csv',event_checks)
save('14_P状态时点不一致记录.csv',pissues)
save('15_实测与模型投入对照.csv',input_diffs)
mapping=[]
def mapfield(target,file,var,definition,unit,kind,scope,status='DIRECT',formula='',notes=''):
    mapping.append(dict(target_field=target,source_file=file,native_variable=var,native_definition=definition,native_unit=unit,
        output_frequency='daily; FROP=1',stock_flow_cumulative=kind,organ_scope=scope,event_inclusion='见state_timing/event_timing；过程账本为当日日末已扣采出',
        support_status=status,conversion_formula=formula,notes=notes))
for target,var in [('ET_actual_mm','ETAA'),('transp_actual_mm','EPAA'),('evap_soil_actual_mm','ESAA')]:
    mapfield(target,'ET.OUT',var,'FROP=1时为当日实际量，非潜在/参考ET','mm/d','FLOW','植株与土壤',notes='EFAA=EMAA=0已逐点核查；ETAA=EPAA+ESAA在0.001mm打印误差内')
for target,var in [('irrigation_applied_mm','IRRD'),('irrigation_infiltrated_mm','IRRD'),('precip_effective_mm','PRED'),('runoff_mm','ROFD')]:
    mapfield(target,'SoilWatBal.OUT',var,'进入模型水量平衡的当日量','mm/d','FLOW','0–180cm模型剖面',notes='本批EFIR=1且径流为0；不把施用水与有效水重复相加')
for target in ['drainage_below100_mm','capillary_into100_mm']:
    mapfield(target,'SoilWatBal.OUT','none at 100cm','100cm界面独立通量未打印','mm/d','FLOW','100cm界面',status='NOT_EXPORTED',notes='DRND为180cm剖面底部排水，不能替代；也未将ET与ΔS100残差冒充界面通量')
mapfield('theta_v_m3_m3','SoilWat.OUT','SW1D..SW13D','真实13层液态体积含水率','m3/m3','STOCK','0–180cm原生层',notes='BOD由前日EOD近似；不混同灌水前瞬时值')
mapfield('layer_storage_mm','SoilWat.OUT','SW1D..SW13D','层贮水由真实层厚计算','m3/m3','STOCK','各原生层',status='DERIVED',formula='theta × (bottom_cm-top_cm) × 10')
for organ in ['stem','leaf','root']:
    mapfield(organ+'_drymatter_kg_ha','DMState.csv',organ+'_dm','已扣采出/损失的日末器官干物质','g/m2','STOCK',organ,status='DERIVED',formula='native × 10')
    mapfield(organ+'_N_kg_ha','OrganNState.csv',organ+'_n','器官总N，储备库是子集，不能再加','g N/m2','STOCK',organ,status='DERIVED',formula='native × 10')
    for el in ['P','K']:
        mapfield(organ+'_'+el+'_kg_ha','PlantP.OUT'if el=='P'else'POTAS=N',{'root':'RTPAD'}.get(organ,'SHPAD aggregated')if el=='P'else'none',
            'P仅有合并shoot及root等通用池；无独立茎叶P且时点/多次采收未验证'if el=='P'else'K模拟关闭','kg/ha','STOCK',organ,
            status='NOT_EXPORTED'if el=='P'and organ=='root'else'UNSUPPORTED',notes='未做干物质×实测浓度混合估算；P原值仅另表供审查')
mapfield('fruit_onplant_drymatter_kg_ha','DMState.csv','shell_dm+seed_dm','全部在株整果，含所有成熟度，日末已扣采出','g/m2','STOCK','fruit shell+seed',status='DERIVED',formula='(shell_dm+seed_dm) × 10',notes='不使用累计已采量；FreshWt.TOPOW为同日采出前cohort总量，只用于对账')
mapfield('fruit_onplant_N_kg_ha','OrganNState.csv','fruit_n','全部在株果皮/果肉及种子总N','g N/m2','STOCK','whole fruit',status='DERIVED',formula='fruit_n × 10',notes='不是GNAD种子N；预采收等价状态加回NCBalance.harvest_n')
for el in ['P','K']:
    mapfield('fruit_onplant_'+el+'_kg_ha','PlantP.OUT'if el=='P'else'POTAS=N','SLPAD+SDPAD'if el=='P'else'none','P通用池尚未匹配当日在株库；K关闭','kg/ha','STOCK','whole fruit',status='NOT_EXPORTED'if el=='P'else'UNSUPPORTED',notes='部分果DM=0但原生P>0，见14表；未作为可靠补缺值')
mapfield('harvest_drymatter_kg_ha','DMState.csv','harvest_dm','当日整果采出干重','g/m2','FLOW','whole fruit',status='DERIVED',formula='harvest_dm × 10',notes='与FreshWt.HPODW逐点对账')
mapfield('harvest_freshmass_kg_ha','FreshWt.OUT','HFPOW','当日整果采出鲜重','kg/ha','FLOW','whole fruit')
mapfield('harvest_N_kg_ha','NCBalance.csv','harvest_n','本次真实整果N采出','g N/m2','FLOW','whole fruit',status='DERIVED',formula='harvest_n × 10',notes='累计N另在11表；不重复加CHPDTN')
for el in ['P','K']:mapfield('harvest_'+el+'_kg_ha','not available','none','无可核验的逐次整果P/K采出量','kg/ha','FLOW','whole fruit',status='UNSUPPORTED')
mapfield('pruning_export','management MC=0','none','无对应已模拟整枝事件，不能填0事件冒充实测未整枝','kg/ha','FLOW','leaf/stem',status='UNSUPPORTED')
mapfield('litter_export','NCBalance.csv','outside_loss-harvest_n','有非采收全株N损失合计，未分解到落叶/根/整枝','g N/m2','FLOW','whole plant',status='NOT_EXPORTED',notes='合计N另在11表；不冒充完整落叶DM/N事件')
mapfield('N_uptake_cumulative_kg_ha','NCBalance.csv','root_input','模型累计实际根吸N，不含初始苗/种子N和内部转运','g N/m2/d','CUMULATIVE','root to whole plant',status='DERIVED',formula='cumsum(root_input) × 10')
mapfield('DAT','calendar date','date-transplant_date','本研究定植日为DAT0，独立于DAS和DAP','day','STOCK','calendar',status='DERIVED',formula='date - transplant_date')
save('06_变量映射与支持情况.csv',mapping,'06_变量映射与支持情况.csv')
# Transparent summary metrics: both seasons are calibration, not a holdout.
metric_rows=[]
for role,table in [('CALIBRATION',comparison),('CHECK',diagnostics)]:
    for (s,fam),g in table.groupby(['season_id','family']):
        q=g.dropna(subset=['observed','simulated']);o=q.observed.to_numpy(float);v=q.simulated.to_numpy(float);e=v-o
        if not len(q):continue
        den=((o-o.mean())**2).sum();dden=((abs(v-o.mean())+abs(o-o.mean()))**2).sum()
        metric_rows.append(dict(season=SEASON[s],data_use=role,family=fam,n_expected=len(g),n_matched=len(q),RMSE=np.sqrt(np.mean(e*e)),
            NRMSE_percent=np.sqrt(np.mean(e*e))/o.mean()*100 if o.mean()else None,
            R2=float(np.corrcoef(o,v)[0,1]**2)if np.std(o)>0 and np.std(v)>0 else None,NSE=1-(e*e).sum()/den if den else None,
            d=1-(e*e).sum()/dden if dden else None,bias=e.mean(),notes='R2为Pearson相关系数平方；NSE保留系统偏差；ET无独立直接验证'))
save('18_率定与诊断指标汇总.csv',metric_rows)
shutil.copy2(TRIAL/'comparison.csv',OUT/'16_原1123目标逐项对账.csv')
shutil.copy2(TRIAL/'diagnostic_comparison.csv',OUT/'17_原始诊断逐项对账.csv')
shutil.copy2(BASE/'best_parameters.csv',OUT/'最佳参数_120项.csv')
js(OUT/'原始运行收据.json',receipt)
shutil.copy2(PROJECT/'configs/capacity_a_stable79_checkpointed_r4.json',OUT/'原冻结率定配置_含原路径.json')
shutil.copy2(BASE/'champion_audit.json',OUT/'原最佳候选审计.json')
shutil.copy2(BASE/'run_manifest.json',OUT/'原率定运行登记.json')
sources=OUT/'字段核查源码';sources.mkdir(exist_ok=True)
source_root=ROOT.parent/'critical_n/n_buffer_v12/experiments/cold_rebuild/source'
for rel in ['Plant/CROPGRO/FreshWt.for','Plant/CROPGRO/GROW.for','Plant/CROPGRO/N_BUFFER_V2.f90','Plant/Generic-PlantP/OpPlantP.for','Plant/Generic-PlantP/P_CGRO.for','Soil/SoilWater/OPWBAL.for','SPAM/PET.for']:
    shutil.copy2(source_root/rel,sources/Path(rel).name)
gap_rows=[]
gap_request=pd.read_csv(ROOT/'01_缺失项与用途清单.csv')
for g in gap_request.to_dict('records'):
    code=g['gap_id'];status='DELIVERED'
    limitation=''
    if code=='W03':status='PARTIAL';limitation='100cm独立向上/向下通量未打印；已交真实层水分、100cm贮水和180cm底部排水，不互相冒名。'
    if code.startswith('F'):
        status='PARTIAL';limitation='器官干物质与N已交；P/K核心值留空，未作HYBRID。'
        if code=='F05':limitation+='初始量为模型移栽日末携入/状态近似，不是独立实测苗初始量。'
        if code=='F07':limitation+='根DM/N已交；非采收全株N损失合计另交，未分解完整落叶/整枝DM及各元素移出。'
    if code=='M02':limitation='支持能力已核查；P合并器官/时点及多采收未验证，K过程关闭；不强行填齐。'
    gap_rows.append(g|dict(delivery_status=status,limitation=limitation))
save('19_逐缺项交付状态.csv',gap_rows)
note=f'''# 指定stable79最佳参数的双春补缺交付

交付日期：2026-10-19。原研究参考：stable79_checkpointed150x5_20261018。

本次使用该批次best_parameters.csv的完整120项参数，在同一个自定义capacity_a执行体上重新运行12个2026春处理和8个2025春处理。未采用后来fresh76批次参数，未修改参数、遗传文件模板、天气、土壤或管理协议。重放输出位置：{TRIAL.relative_to(ROOT).as_posix()}。

## 数据入口

01—07为所需七张表，保留模板列名，必要表末增加DAT。08为所有24种请求窗的逐处理纯模型ET汇总，共244条；09补180cm底部通量及0—100cm贮水；10为完整逐日四器官状态；11为根吸N、采出和其他损失账本。12、14的P输出仅供能力核验，不能作为可靠P补缺值。13核对采收前后整果干重。15列实测/模型投入差异。16—18为原1123目标、诊断及指标。19逐项说明完成与限制。

每个处理只有一条确定性模拟，block_id为空，ensemble_id只表示指定最佳参数情景，不是生物重复。所有日期为公历，DAT以真实定植日为0重新计算。两春均参与了原联合率定，07用CALIBRATION/CHECK，不伪称2025为独立VALIDATION。

## 时间、器官及量纲

分期沿交付清单：2026花果期[05-02,05-26)，另给指定[05-02,06-02)；2025花果期[04-30,05-20)。默认以119/125天时点窗衔接原水量平衡，同时保留120/126天日历窗。所有ET严格[start,end)，不因模型花期不同重切实测分期。

水分SW为日末。BOD_DERIVED_PREV_EOD表示以前日日末近似当日日初；因此07-14/07-18只有对应前日日末推得的BOD，没有伪造次日日末或延长生长。模型日尺度结果不等于现场当天灌水前瞬时状态。

核心器官值取DMState/OrganNState日末、采出后状态，质量单位g/m²乘10转kg/ha。全部在株整果干物质=(shell_dm+seed_dm)×10，N=fruit_n×10，不只取成熟果或GNAD种子N；内部储N为总N子集，不额外再加。PRE_HARVEST_RECONSTRUCTED是将同日采出DM/N加回形成收支等价的事件前状态，茎叶沿用同日日末，不主张日内完全同步。

FreshWt的TOPOW/TOFPW在本版本先汇总cohort后移除成熟果，因此是采出前全部果量。直接当作采后挂果会重复计入同日采出。核心使用高精度日末账本；鲜重辅助值用TOFPW−HFPOW，打印舍入误差内、已确认DM=0时填真实0。采收移出按EVENT，累计量另列，不能重复相加。

器官N为模型总N存量，浓度按1000×Nkg/DMkg计算g/kg；零干重时浓度留空，不能虚构0浓度。累计根吸N来自NCBalance.root_input积分，不包括初始苗/种子N、固氮和内部转运。初始苗状态只是本版本PLWT/PAGE等设定下的模型移栽日末量，未被追认为实测苗携入量。

2026末期现场无未采果的事实不被模型推翻；表内保留模型实际剩余量，若不为0作为模型偏差/事件差异记录。2025末期本次显式纳入模拟未采果，与原少量不计范围不同。

## 不能强行补齐的内容

- 真实土壤13层到180cm，0—100cm界面是第9层底。DRND为180cm底排水；未输出的100cm跨界双向流量保持空白，不能假填0或用180cm值替代。水分根深可超过100cm，不能把全株ET与ΔS100残差直接当100cm通量。
- P虽然开关为Y并输出PlantP，但仅有合并shoot等通用池，缺独立茎叶P存量；本次有{len(pissues)}条同日果DM=0而原生果P>0的记录，且部分通用字段打印溢出。其日内时点/多次采收对应未验证。12保留原值和溢出字段，核心P暂不交作可信补缺结果；K开关N，核心K不支持。未拿施肥量、胁迫系数或成熟果浓度代替器官存量，也未擅自制作混合估算。
- 显式整枝过程未模拟，不填0事件。11只有非采收全株N损失合计，不冒充完整整枝/落叶DM/N/P/K收支。
- ET是本次模型的纯模拟结果；原率定包含水分和区间水量平衡代理量，不是独立日ET验证。根吸N也不是独立实测验证结果。07/18保留全部拟合与诊断误差；产量拟合好不证明日ET、挂果和每个养分过程都准确。
- 模型出现的180cm深排水原样交付。与原试验忽略深排水的假设不一致时，需继续评估ET适用性，不能将排水置零或直接覆盖观测窗口ET。本次未制作“观测ET约束拆分”结果。

## 原始工程与运行

每季原始目录包含本次实际写入的CUL/ECO/SPE/SOL、TMX、批处理、天气、可执行文件、运行头、全部OUT、诊断CSV和原生日志。运行配置/参数/原审计另附。原始模板“填报模板”及所有原始工作簿均未改动。复算入口为本目录上一级整理stable79补缺数据.py；先原版本运行，再执行提取。最终核验和全部交付文件SHA256见交付核验.json及文件校验SHA256.json。
'''
(OUT/'00_交付说明与使用限制.md').write_text(note,encoding='utf8')
run_note=f'''# DSSAT补缺运行说明（已填写）

运行日期：2026-10-19。执行体DSSAT 4.8.2.000，CRGRO048-Tomato，茄子参数TM0008/TM0001/TMGRO048，自定义NBUF严格库容capacity_a。二进制SHA256：{design['binary_sha256']}。模型内部碳氮/干物质审核见原始运行收据。

最终输出/工程：{TRIAL.relative_to(ROOT).as_posix()}/26SP 与 /25SP。每个目录含整季全部处理，实际Run→处理映射在01表。最佳参数见最佳参数_120项.csv。2026 SLPF=0.890，2025 SLPF={receipt['parameters']['SLPF_25SP']:.15g}；其余参数原样，未套用后续TRIFL≤0.85协议。

两季天气均为各自目录XXTW2403.WTH，2025日期2025、2026日期2026；文件头均记为2号棚去重半小时来源。该运行包不足以独立证明2025原9号/2号补齐细节，故不冒称9号完整实测天气。保留实际天气文件及哈希供核对。WTH SRAD为MJ/m²/d，未把论文W/m²原样写入；24h平均W/m²到日能量的换算系数为0.0864。WARNING.OUT记录低辐射警告，2025部分0被模型内部置为0.1；文件未修改，实际Weather.OUT一并保留。

方法：EVAPO=R，即PET.for中的Priestley–Taylor潜在ET路径；交付实际ET取FROP=1的ETAA、实际EPAA和ESAA。WATER=Y、NITRO=Y、SYMBI=N、PHOSP=Y、POTAS=N；IRRIG=R、FERTI=R、HARVS=R（按记录日程），RESID=N。各管理方案EFIR=1，灌水IR005。温室天气降水为0，模型径流等真实零由输出核实，排水未置零。

土壤SOIL.SOL，13层：0–5、5–15、15–30、30–40、40–50、50–60、60–70、70–80、80–100、100–120、120–140、140–160、160–180cm；处理初始水氮及土壤属性由各自TMX IC及SOIL配置读入。氮吸收设置NB_ROOT_DEPTH=40cm；不能将其等同于水分根深，实际RDPD另在09表逐日交付。土壤SLDR={receipt['parameters']['SOIL_SLDR']:.12g}。详细初始条件、实际水肥逐事件输入保留原工程。

定植：2025-03-16、2026-03-14，PLME=T，PPOP=PPOE=2.7株/m²（27000株/ha），PLWT=15 kg/ha（SDWTPL，原GROW定义；不能误当15 g/m²），PAGE=25/24d。实际逐日水分输出起点2025-03-09和2026-03-12，SoilWat还含前一日初始化状态；相对现场时点属于模型近似，不重写成取土实测。施肥含定植前基肥，01保留实测核定总量与模型总量。

采收：2026五次05-26、06-07、06-16、07-01、07-17；2025九次05-20、05-26、06-02、06-07、06-12、06-19、06-24、07-03、07-11。只移除当日模型成熟果，未强制把所有未成熟果也采掉；终止控制事件不伪造为采收量。未显式模拟田间全部抹花/整枝。其他损失有模型过程，但完整分器官事件未导出，不冒充已测。

状态和累计量：原生SoilWat为日末；DMState/OrganNState为当日已扣采出的整器官状态；FreshWt的TOPOW/TOFPW为采出前cohort合计，HPODW/HFPOW为本次，CHPDT/CHFPW为累计，详见00说明。NCBalance.harvest_n积分为累计采出N，root_input积分为实际根吸N。初始苗携入量为模型设定日末状态，不是独立苗样实测。

校准/验证：2026春12处理与2025春8处理均参与stable79联合率定，原1123目标全部保留核对；不得将2025重标为独立验证。18表包含RMSE/NRMSE/R2/NSE/d及匹配数，07为逐点。日ET、根吸N及P/K没有本次独立留出验证；水分/区间代理量拟合不等于直接ET验证。

分期维持清单现行边界，另给31天指定窗；以119/125天时点窗为主要衔接口径，120/126天日历窗同时交付。只有20条处理级确定性运行，无生物重复或参数集合不确定性区间。P/K及100cm通量等限制见00/06/19。
'''
(OUT/'运行说明_已填写.md').write_text(run_note,encoding='utf8')
print(json.dumps(dict(output=str(OUT),water=len(all_water),soil=len(all_soil),organ=len(all_org),daily_organ=len(all_daily_org),harvest=len(all_events),intervals=len(all_period),P_timing_inconsistencies=len(pissues)),ensure_ascii=False,indent=2))
