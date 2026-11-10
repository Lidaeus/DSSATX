from pathlib import Path
from datetime import date,timedelta
import csv,json,hashlib

OUT=Path(__file__).resolve().parent
T=OUT/'填报模板';T.mkdir(exist_ok=True)
(OUT/'原始模型输出').mkdir(exist_ok=True)
def save(path,cols,rows):
 with path.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
  for r in rows:w.writerow({c:r.get(c,'') for c in cols})
seasons={
 '2025春':dict(year=2025,waters=['W1','W3'],plant='2025-03-16',flower='2025-04-30',first='2025-05-20',end='2025-07-13',begin='2025-03-12',I={'W1':282.246528,'W3':481.594618},N=[0,122,254,364],plots={'W1':[13,12,11,10],'W3':[5,4,3,2]},targets=['2025-03-16','2025-04-30','2025-05-20','2025-05-22','2025-06-19','2025-07-13'],soil=['2025-03-12','2025-03-16','2025-04-30','2025-05-01','2025-05-20','2025-05-24','2025-07-12','2025-07-13','2025-07-14'],harvest=['2025-05-20','2025-05-26','2025-06-02','2025-06-07','2025-06-12','2025-06-19','2025-06-24','2025-07-03','2025-07-11']),
 '2026春':dict(year=2026,waters=['W1','W2','W3'],plant='2026-03-14',flower='2026-05-02',first='2026-05-26',end='2026-07-17',begin='2026-03-14',I={'W1':241.28,'W2':359.96,'W3':478.64},N=[0,120,240,361],plots={'W1':[12,10,6,3],'W2':[11,8,5,2],'W3':[9,7,4,1]},targets=['2026-03-14','2026-05-02','2026-05-26','2026-06-02','2026-06-29','2026-07-17'],soil=['2026-03-14','2026-05-02','2026-05-26','2026-06-02','2026-06-29','2026-07-17','2026-07-18'],harvest=['2026-05-26','2026-06-07','2026-06-16','2026-07-01','2026-07-17'])}
runs=[]
for season,s in seasons.items():
 for water in s['waters']:
  for n in range(4):
   runs.append(dict(season=season,run_id=f'S{s["year"]}_{water}_N{n}',W=water,N=f'N{n}',source_plot_code=s['plots'][water][n],density_plants_ha=27000,observed_I_mm=s['I'][water],observed_N_kg_ha=s['N'][n],transplant_date=s['plant'],first_harvest_date=s['first'],termination_date=s['end']))
save(T/'01_运行与处理对应.csv',['season','run_id','W','N','source_plot_code','block_id','ensemble_id','simulation_run_number','model','cultivar','density_plants_ha','observed_I_mm','observed_N_kg_ha','simulated_I_applied_mm','simulated_I_infiltrated_mm','simulated_N_applied_kg_ha','transplant_date','first_harvest_date','termination_date','source_directory','notes'],runs)
water=[];soil=[];org=[];events=[]
for r in runs:
 s=seasons[r['season']];base={k:r[k] for k in ['season','run_id','W','N']}
 dt=date.fromisoformat(s['begin']);end=date.fromisoformat(s['end'])
 while dt<=end:
  water.append(dict(base,date=dt.isoformat()));dt+=timedelta(days=1)
 for d in s['soil']:
  for top in range(0,100,20):soil.append(dict(base,date=d,layer_top_cm=top,layer_bottom_cm=top+20))
 for d in s['targets']:
  for o in ['stem','leaf','fruit_onplant']:
   note='定植苗初始状态' if d==s['plant'] else ('首收边界，优先采收前并可增加采收后状态' if d==s['first'] else '取样/末期对齐状态')
   org.append(dict(base,date=d,organ=o,target_note=note))
 for d in s['harvest']:events.append(dict(base,date=d,event_type='HARVEST',organ='fruit',quantity_scope='EVENT'))
watercols=['season','run_id','W','N','block_id','ensemble_id','date','ET_actual_mm','transp_actual_mm','evap_soil_actual_mm','irrigation_applied_mm','irrigation_infiltrated_mm','precip_effective_mm','runoff_mm','drainage_below100_mm','capillary_into100_mm','balance_depth_cm','value_origin','source_file','notes']
soilcols=['season','run_id','W','N','block_id','ensemble_id','date','state_timing','layer_top_cm','layer_bottom_cm','theta_v_m3_m3','layer_storage_mm','value_origin','source_file','notes']
orgcols=['season','run_id','W','N','block_id','ensemble_id','date','state_timing','organ','fruit_maturity_group','drymatter_kg_ha','freshmass_kg_ha','number_per_ha','N_kg_ha','P_kg_ha','K_kg_ha','N_g_kg_DM','P_g_kg_DM','K_g_kg_DM','value_origin','source_file','target_note','notes']
eventcols=['season','run_id','W','N','block_id','ensemble_id','date','event_timing','event_type','organ','quantity_scope','freshmass_kg_ha','drymatter_kg_ha','N_kg_ha','P_kg_ha','K_kg_ha','value_origin','source_file','notes']
save(T/'02_逐日水量.csv',watercols,water)
save(T/'03_边界土壤水.csv',soilcols,soil)
save(T/'04_器官状态.csv',orgcols,org)
save(T/'05_采收与其他移出.csv',eventcols,events)
save(T/'06_变量映射与支持情况.csv',['target_field','source_file','native_variable','native_definition','native_unit','output_frequency','stock_flow_cumulative','organ_scope','event_inclusion','support_status','conversion_formula','notes'],[dict(target_field=f) for f in ['ET_actual_mm','transp_actual_mm','evap_soil_actual_mm','theta_v_m3_m3','stem_drymatter_kg_ha','leaf_drymatter_kg_ha','fruit_onplant_drymatter_kg_ha','fruit_onplant_N_kg_ha','fruit_onplant_P_kg_ha','fruit_onplant_K_kg_ha','stem_N_kg_ha','stem_P_kg_ha','stem_K_kg_ha','leaf_N_kg_ha','leaf_P_kg_ha','leaf_K_kg_ha','harvest_drymatter_kg_ha','harvest_N_kg_ha','harvest_P_kg_ha','harvest_K_kg_ha','root_drymatter_kg_ha','root_N_kg_ha','root_P_kg_ha','root_K_kg_ha','pruning_export','litter_export','N_uptake_cumulative_kg_ha']])
save(T/'07_校准与验证记录.csv',['season','run_id','W','N','block_id','variable','unit','start_date','end_date_exclusive','state_timing','observed_value','simulated_value','data_use','observation_source','notes'],[])

intervals=[]
def interval(season,id,start,end,purpose,priority):
 intervals.append(dict(season=season,interval_id=id,start_date=start,end_date_exclusive=end,days=(date.fromisoformat(end)-date.fromisoformat(start)).days,purpose=purpose,priority=priority))
for season,s in seasons.items():
 y=s['year']; p=s['plant'];f=s['flower'];h=s['first'];e=s['end'];after=(date.fromisoformat(e)+timedelta(days=1)).isoformat()
 for id,a,b,purpose in [('SEEDLING',p,f,'按现行物候的苗期ET'),('FLOWER_FRUIT',f,h,'按首收边界的花果期ET'),('MATURITY_POINT',h,e,'至拉秧日时点的成熟采收期ET'),('SEASON_POINT',p,e,'与取土时点框架对齐的生育期ET'),('SEASON_CALENDAR',p,after,'包含拉秧整日的全生育期对照'),('LAST_DAY',e,after,'拉秧当天ET，支撑日历口径')]:
  interval(season,f'{y}_{id}',a,b,purpose,'日历口径对照' if id in ['SEASON_CALENDAR','LAST_DAY'] else '必需')
obs=[('2025春','2025-03-12','2025-05-01'),('2025春','2025-05-01','2025-05-24'),('2025春','2025-05-24','2025-07-12'),('2026春','2026-03-14','2026-05-02'),('2026春','2026-05-02','2026-06-29'),('2026春','2026-06-29','2026-07-17')]
for i,(s,a,b) in enumerate(obs):interval(s,f'OBS_WINDOW_{i+1:02d}',a,b,'已有实测窗口的模型核验/约束','核验必需')
for s,id,a,b,purpose in [('2025春','PRE_TRANSPLANT','2025-03-12','2025-03-16','从观测总窗中扣除定植前4日'),('2025春','MISSING_TAIL','2025-07-12','2025-07-13','已有观测终点到拉秧时点的缺日'),('2026春','USER_MAY02_JUN02','2026-05-02','2026-06-02','本次指定31 d取样间隔窗'),('2026春','FIRST_TO_JUN02','2026-05-26','2026-06-02','首收到第二次取样前7日'),('2026春','JUN02_JUN29','2026-06-02','2026-06-29','第二次取样到已有取土边界'),('2026春','JUN02_END','2026-06-02','2026-07-17','第二次取样后至拉秧时点')]:
 interval(s,id,a,b,purpose,'必需或核验')
save(OUT/'02_日期与区间.csv',list(intervals[0]),intervals)

gaps=[
 ('W01','必需','2026春','05-26/06-02无取土边界；花果成熟ET不能分开','逐日实际ET及边界0—100 cm土壤水','恢复24 d花果期/52 d成熟时点窗及31 d指定窗ET'),
 ('W02','必需','2025春','土样03-12/05-01/05-24/07-12不对应物候','全季逐日实际ET及03-16/04-30/05-20/07-13边界土壤水','同口径三阶段ET及全生育期ET'),
 ('W03','配套','两春','缺连续水量平衡通量及土壤水状态','蒸发/蒸腾/灌水/有效降水/径流/100 cm通量/剖面水分','验证和约束补缺ET'),
 ('F01','必需','2026春','05-02/06-02/06-29挂果量及养分未测','在株整果干物质及N/P/K','完善四期器官分配和累计量'),
 ('F02','必需','2026春','首收05-26缺完整器官边界','茎叶在株果干物质及N/P/K；当日采收量','独立阶段养分净增量'),
 ('F03','2025过程必需','2025春','中期茎叶浓度缺测；05-20精确同日干重也缺','04-30/05-20/05-22/06-19茎叶N/P/K及干物质','2025养分过程与阶段需肥验证'),
 ('F04','2025过程必需','2025春','中期挂果及末期少量未采果未计','04-30/05-20/05-22/06-19/07-13在株果干物质及N/P/K','完善同期果实库及末期口径对照'),
 ('F05','净增量配套','两春','定植苗初始干物质和养分未计','03-16/03-14初始苗茎叶及可选根N/P/K','扣除移栽带入量'),
 ('F06','可选改进','两春','逐批采果干物率与浓度存在日期代表性估算','真实5次/9次采收日干物质和N/P/K移出','评估现有插值/全季常量代表偏差'),
 ('F07','可选完整收支','两春','根/整枝/落叶量未计','边界根量、逐事件移出干物质及N/P/K','进一步扩大收支范围'),
 ('M01','所有模拟必需','两春','最终运行与处理和变量定义需核实','运行对应/参数/驱动/事件时点/验证说明','保证输出能够连接与复核'),
 ('M02','P/K补缺前必需','两春','模型P/K及整果养分输出能力尚未确认','明确原始字段及支持状态；不支持则说明混合算法','避免将N结果/胁迫系数误当P/K量')]
save(OUT/'01_缺失项与用途清单.csv',['gap_id','priority','season','gap','requested_data','purpose'],[dict(zip(['gap_id','priority','season','gap','requested_data','purpose'],g)) for g in gaps])

definitions={
 'season':('','2025春或2026春','必填'), 'run_id':('','运行唯一标识；模板标识可沿用，另填原始运行号','必填'),
 'W':('','水水平；2025仅W1/W3，2026 W1/W2/W3','必填'),'N':('','氮水平N0—N3','必填'),
 'block_id':('','真实区组1/2/3；处理级运行留空，不复制','条件必填'), 'ensemble_id':('','参数/情景集合编号，不是生物重复','如有'),
 'date':('YYYY-MM-DD','日历日期；DAT另按定植日计算','必填'),'state_timing':('','BOD/EOD/PRE_IRRIGATION/POST_TRANSPLANT/PRE_HARVEST/POST_HARVEST等，需解释日输出近似','必填'),
 'organ':('','stem/leaf/fruit_onplant/root；移出表可为fruit/stem/leaf','必填'),
 'value_origin':('','SIMULATED模型直接；DERIVED由模型量派生；HYBRID模型与实测/代理结合；OBSERVED仅核验','必填'),
 'source_file':('','原输出相对路径和Run号，便于追溯','必填'),
 'ET_actual_mm':('mm/d','该日实际土壤蒸发＋实际蒸腾；非ETo/潜在ET','必需'),
 'transp_actual_mm':('mm/d','该日实际植株蒸腾','ET配套'), 'evap_soil_actual_mm':('mm/d','该日实际土壤蒸发','ET配套'),
 'irrigation_applied_mm':('mm/d','实际施用灌水，区别入渗有效水','ET配套'), 'irrigation_infiltrated_mm':('mm/d','真正进入水量平衡的有效灌水；勿与施用水重复相加','ET配套'),
 'precip_effective_mm':('mm/d','温室内到达土壤的有效降水；露地降水不直接照搬','ET配套'),
 'runoff_mm':('mm/d','地表径流，模拟值原样报告','ET配套'),
 'drainage_below100_mm':('mm/d','跨100 cm边界向下通量；模型底部不在100 cm时不能冒名替代','尽可能提供'),
 'capillary_into100_mm':('mm/d','跨100 cm边界向上净补给，定义方向须说明','尽可能提供'),
 'balance_depth_cm':('cm','报告通量和贮水对应的深度范围','水量配套'),
 'layer_top_cm':('cm','模型真实土层上界；模板20 cm层可改为实际层界','必填'), 'layer_bottom_cm':('cm','模型真实土层下界','必填'),
 'theta_v_m3_m3':('m3/m3','体积含水率；百分数须先除100，重量含水率须另标','土壤水核心'),
 'layer_storage_mm':('mm','该层液态水贮量；=体积含水率×层厚cm×10','与含水率至少一项'),
 'drymatter_kg_ha':('kg DM/ha','该器官在株存量，或移出表指定范围的干物质量；果包括整果','养分核心'),
 'freshmass_kg_ha':('kg fresh/ha','鲜重仅辅助；不得与干基浓度直接相乘','可选'),
 'number_per_ha':('个/ha','在株果数，仅辅助','可选'), 'fruit_maturity_group':('','total/immature/mature；整果合计避免再加子组','如有'),
 'event_type':('','HARVEST/PRUNING/LEAF_LITTER/OTHER；无模拟不要填0事件','必填'),
 'event_timing':('','管理事件前后及当天序号，说明收支归属','必填'),
 'quantity_scope':('','EVENT为本次/当日量；CUMULATIVE为累计移出，不能混合相加','必填'),
 'observed_I_mm':('mm/season','项目核定的实测全季施用灌水，预填基线，不是模拟结果','已预填'),
 'observed_N_kg_ha':('kg N/ha/season','项目核定的实测全季施纯氮，预填基线','已预填'),
 'support_status':('','DIRECT/DERIVED/HYBRID/UNSUPPORTED/NOT_EXPORTED','变量表必填'),
 'stock_flow_cumulative':('','STOCK/FLOW/CUMULATIVE；说明是否已扣采收','变量表必填'),
 'data_use':('','CALIBRATION/VALIDATION/CHECK；与校准资料重用须说明','验证表必填')}
for el in ['N','P','K']:
 definitions[f'{el}_kg_ha']=('kg element/ha',f'器官{el}元素存量，或移出表指定范围移出量；非肥料投入量','如支持优先提供')
 definitions[f'{el}_g_kg_DM']=('g element/kg DM',f'器官{el}干基浓度；与mg/g数值相同，百分数需乘10','未给存量时与干物质配套')
save(OUT/'03_字段字典.csv',['field','unit','definition','required'],[dict(field=k,unit=v[0],definition=v[1],required=v[2]) for k,v in definitions.items()])

# Verify the scaffolds contain no invented numeric model results.
for rows,fields in [(water,['ET_actual_mm','transp_actual_mm','evap_soil_actual_mm']),(soil,['theta_v_m3_m3','layer_storage_mm']),(org,['drymatter_kg_ha','N_kg_ha','P_kg_ha','K_kg_ha']),(events,['drymatter_kg_ha','N_kg_ha','P_kg_ha','K_kg_ha'])]:
 assert all(not r.get(k) for r in rows for k in fields)
assert len(runs)==20 and len(org)==360 and len(events)==132
assert len({(r['season'],r['run_id'],r['date']) for r in water})==len(water)
assert len({(r['run_id'],r['date'],r['organ']) for r in org})==len(org)
assert all(r['days']>0 for r in intervals)
manifest={'runs':len(runs),'daily_water_skeleton_rows':len(water),'soil_boundary_skeleton_rows':len(soil),'organ_state_skeleton_rows':len(org),'harvest_event_skeleton_rows':len(events),'interval_requests':len(intervals),'no_simulated_values_filled':True,'templates_are_requests_not_results':True}
(OUT/'模板核验.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False,indent=2))
