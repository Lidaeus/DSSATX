"""Export official model scenarios, retaining missing-output and fruit-pool differences."""
from 官方对照公共读取 import *
import shutil

R1=ROOT/'已填数据_stable79_20261019'
TEMPLATE=ROOT/'填报模板'
REQUESTS=pd.read_csv(ROOT/'02_日期与区间.csv')
BASEMAP=pd.read_csv(R1/'01_运行与处理对应.csv').fillna('')
PAIR=pd.read_csv(R1/'16_原1123目标逐项对账.csv')
DIAG=pd.read_csv(R1/'17_原始诊断逐项对账.csv')
TARGETS={name:pd.read_csv(TEMPLATE/name)for name in ['03_边界土壤水.csv','04_器官状态.csv','05_采收与其他移出.csv']}
SPECS={2:'eggplant_26sp_n012_rmse_joint65_200x5_20261012',3:'eggplant_26sp_n012_c31_joint67_20261011'}
UNITS={'SWAD':'kg DM/ha','LWAD':'kg DM/ha','HFPOW':'kg fresh/ha','HPODW':'kg DM/ha','CHPDT':'kg DM/ha','CHFPW':'kg fresh/ha',
       'LNAM':'kg N/ha','SNAM':'kg N/ha','LEAF_N_PCT':'% DM','STEM_N_PCT':'% DM','FRUIT_N_PCT':'% DM','PDMCD':'kg DM/kg fresh',
       'LAID':'m2/m2','CHTD':'m','ADAP':'day','VWC':'m3/m3','WB100_INTERVAL':'mm',
       'N_ADJACENT_FRESH_CONTRAST':'kg fresh/ha','W_FRESH_CONTRAST':'kg fresh/ha'}
def save(out,name,rows,template=None,extras=()):
    q=rows.copy()if isinstance(rows,pd.DataFrame)else pd.DataFrame(rows)
    if template:q=q.reindex(columns=list(pd.read_csv(TEMPLATE/template,nrows=0).columns)+list(extras))
    q.to_csv(out/name,index=False,encoding='utf-8-sig',float_format='%.17g',na_rep='')
    return q
def metric(q):
    good=q.dropna(subset=['observed','simulated']);o=good.observed.to_numpy(float);v=good.simulated.to_numpy(float);e=v-o
    result=dict(n_expected=len(q),n_matched=len(good))
    if not len(good):return result
    den=((o-o.mean())**2).sum();dd=((abs(v-o.mean())+abs(o-o.mean()))**2).sum()
    result.update(RMSE=float(np.sqrt(np.mean(e*e))),NRMSE_percent=float(np.sqrt(np.mean(e*e))/o.mean()*100)if o.mean()else None,
                  R2=float(np.corrcoef(o,v)[0,1]**2)if np.std(o)>0 and np.std(v)>0 else None,
                  NSE=float(1-(e*e).sum()/den)if den else None,d=float(1-(e*e).sum()/dd)if dd else None,bias=float(e.mean()))
    return result

def export(rep):
    raw=ROOT/f'原始模型输出/official_repeat{rep}_20261019'
    out=ROOT/f'已填数据_重复{rep}_官方_20261019';out.mkdir(exist_ok=True)
    buckets={k:[]for k in ['water','soil','organ','daily','events','period','extra','N','P','event_check','pool','inputs','pairs','cal','summary']}
    runmap=BASEMAP.copy();rec=json.loads((raw/'运行收据.json').read_text(encoding='utf8'))
    for s in ['26SP','25SP']:
        work=raw/s;parameter_audit(work)
        frames={n:native(work/(n+'.OUT'))for n in ['ET','SoilWat','SoilWatBal','PlantGro','PlantN','FreshWt','PlantP']}
        expected=set(runmap.loc[runmap.season.eq(SEASON[s]),'source_plot_code'].astype(int))
        assert all(set(q.index.get_level_values(0))==expected for q in frames.values())
        # Verify printed layer boundaries, rather than assuming input SOL layers survive the engine's remapping.
        header=next(l for l in(work/'SoilWat.OUT').read_text().splitlines()if '0-5'in l)
        assert [tuple(map(int,x))for x in re.findall(r'(\d+)-(\d+)',header)]==LAYERS
        evallines=(work/'Evaluate.OUT').read_text().splitlines();eh=next(l.lstrip('@').split()for l in evallines if l.startswith('@RUN'))
        anthesis={int(q['TN']):float(q['ADAPS'])for l in evallines if l.split()and l.split()[0].isdigit()for q in [dict(zip(eh,l.split()))]}
        fert=pd.read_csv(work/'fertilizer_event_audit.csv')
        for ix,r in runmap[runmap.season.eq(SEASON[s])].iterrows():
            trt=int(r.source_plot_code);base=dict(season=SEASON[s],run_id=r.run_id,W=r.W,N=r.N,block_id='',ensemble_id=SPECS[rep])
            et,sw,wb,pg,pn,fr,pp=[frames[k].xs(trt)for k in ['ET','SoilWat','SoilWatBal','PlantGro','PlantN','FreshWt','PlantP']]
            assert et.EFAA.eq(0).all()and et.EMAA.eq(0).all()
            assert abs(et.ETAA-et.EPAA-et.ESAA).max()<=.001001
            assert abs(et.EPAA-wb.loc[et.index,'EPAD']).max()<=.005001
            assert abs(et.ESAA-wb.loc[et.index,'ESAD']).max()<=.005001
            assert set(pg.index)==set(pn.index)==set(pd.date_range(PLANT[s],END[s]).strftime('%Y-%m-%d'))
            def source(*files):return';'.join((work/f).relative_to(ROOT).as_posix()+f';TRT={trt}'for f in files)
            def storage(date,depth=100):
                return sum(float(sw.loc[date,f'SW{i}D'])*max(0,min(b,depth)-a)*10 for i,(a,b)in enumerate(LAYERS,1)if a<depth)
            def fruit(date,pre=False):
                if date not in fr.index:
                    assert pg.loc[date,'PWAD']==0
                    return float(pg.loc[date,'PWAD']),None,None,'PlantGro.PWAD；FreshWt尚未开始，原生整数kg/ha打印'
                f=fr.loc[date];mass=float(f.TOPOW-(0 if pre else f.HPODW));fresh=float(f.TOFPW-(0 if pre else f.HFPOW))
                assert mass>=-.10001 and fresh>=-.60001
                # Both native cohort dry weights print to 0.1 kg/ha; no arbitrary near-zero clipping.
                if mass<0:mass=None
                if fresh<0:fresh=None
                number=float(f.TOSHN)*10000 if pre or f.HPODW==0 else None
                return mass,fresh,number,'FreshWt果实批次库；'+('采出前TOPOW/TOFPW'if pre else'采后TOPOW−HPODW / TOFPW−HFPOW')
            def organ(date,name,timing='EOD_POST_HARVEST',target=''):
                g,n=pg.loc[date],pn.loc[date];fresh=number=N=None
                if name=='fruit_onplant':
                    mass,fresh,number,definition=fruit(date,timing.startswith('PRE_'))
                    note=definition+'；官方果实批次库与器官库不一致，整果N及浓度未通过同口径核查，留空；差异见14表。'
                    files=['PlantGro.OUT','FreshWt.OUT','PlantN.OUT']
                else:
                    mass=float(g[{'leaf':'LWAD','stem':'SWAD','root':'RWAD'}[name]])
                    N=float(n[{'leaf':'LNAD','stem':'SNAD'}[name]])if name!='root'else mass*float(n['RN%D'])/100
                    note='叶/茎N为PlantN打印原值；根N=RWAD×RN%D/100。DM原生整数kg/ha，叶茎N 0.1kg/ha，根N% 0.1%；保留打印精度。'
                    files=['PlantGro.OUT','PlantN.OUT']
                if date==PLANT[s]:note+='移栽当日模型日末状态，非独立实测苗携入量。'
                if timing.startswith('PRE_'):note+='茎叶根仍取同日末；不主张日内完全同步。'
                return base|dict(date=date,DAT=dat(s,date),state_timing=timing,organ=name,fruit_maturity_group='total'if name=='fruit_onplant'else'',
                                 drymatter_kg_ha=mass,freshmass_kg_ha=fresh,number_per_ha=number,N_kg_ha=N,P_kg_ha=None,K_kg_ha=None,
                                 N_g_kg_DM=N/mass*1000 if N is not None and mass is not None and mass>0 else None,P_g_kg_DM=None,K_g_kg_DM=None,
                                 value_origin='DERIVED',source_file=source(*files),target_note=target,notes=note+'P/K核心值留空，未进行实测浓度混合补值。')
            start='2025-03-12'if s=='25SP'else PLANT[s]
            for date in pd.date_range(start,END[s]).strftime('%Y-%m-%d'):
                e,w=et.loc[date],wb.loc[date]
                buckets['water'].append(base|dict(date=date,DAT=dat(s,date),ET_actual_mm=e.ETAA,transp_actual_mm=e.EPAA,evap_soil_actual_mm=e.ESAA,
                    irrigation_applied_mm=w.IRRD,irrigation_infiltrated_mm=w.IRRD,precip_effective_mm=w.PRED,runoff_mm=w.ROFD,
                    drainage_below100_mm=None,capillary_into100_mm=None,balance_depth_cm=180,value_origin='SIMULATED',source_file=source('ET.OUT','SoilWatBal.OUT'),
                    notes='FROP=1；实际ET，EFIR=1。100cm界面独立通量未输出，不能用180cm底排水代替。'))
                buckets['extra'].append(base|dict(date=date,DAT=dat(s,date),state_timing='EOD',storage_0_100_mm=storage(date),storage_0_180_mm=w.SWTD,
                    drainage_model_bottom_180_mm=w.DRND,lateral_inflow_net_mm=w.LFLOD,flood_outflow_mm=w.FROD,tile_drain_mm=w.TDFD,
                    native_WBAL_mm=w.WBAL,native_CUMWBAL_mm=w.CUMWBAL,water_root_depth_cm=pg.loc[date,'RDPD']*100 if date in pg.index else None,
                    value_origin='DERIVED',source_file=source('SoilWat.OUT','SoilWatBal.OUT')))
            for date in sorted(set(TARGETS['03_边界土壤水.csv'].query('run_id==@r.run_id').date)):
                for timing,sd in [('EOD',date),('BOD_DERIVED_PREV_EOD',prev(date))]:
                    if sd not in sw.index:continue
                    for i,(a,b)in enumerate(LAYERS,1):
                        theta=float(sw.loc[sd,f'SW{i}D'])
                        buckets['soil'].append(base|dict(date=date,DAT=dat(s,date),state_timing=timing,layer_top_cm=a,layer_bottom_cm=b,
                            theta_v_m3_m3=theta,layer_storage_mm=theta*(b-a)*10,value_origin='DERIVED',source_file=source('SoilWat.OUT'),
                            notes=f'原生层SW{i}D，状态源日期{sd}；日初由前日日末近似，不代表灌前瞬时值；theta打印分辨率0.001'))
            for date in pg.index:
                for name in ['stem','leaf','fruit_onplant','root']:
                    buckets['daily'].append(organ(date,name,'POST_TRANSPLANT_MODEL_EOD'if date==PLANT[s]else'EOD_POST_HARVEST'))
            for date in sorted(set(TARGETS['04_器官状态.csv'].query('run_id==@r.run_id').date)):
                for name in ['stem','leaf','fruit_onplant','root']:
                    buckets['organ'].append(organ(date,name,'POST_TRANSPLANT_MODEL_EOD'if date==PLANT[s]else'EOD_POST_HARVEST','请求日期模型状态'))
                    if date in fr.index and fr.loc[date,'HPODW']>0:buckets['organ'].append(organ(date,name,'PRE_HARVEST_RECONSTRUCTED','同日批次采出前；其他器官同日末'))
            dates=set(fr[(fr.HPODW>0)|(fr.HFPOW>0)].index)|set(TARGETS['05_采收与其他移出.csv'].query('run_id==@r.run_id').date)
            for date in sorted(dates):
                f=fr.loc[date];post,_,_,_=fruit(date)
                buckets['events'].append(base|dict(date=date,DAT=dat(s,date),event_timing='MODEL_ACTUAL_EVENT_INTEGRATION',event_type='HARVEST',organ='fruit',quantity_scope='EVENT',
                    freshmass_kg_ha=f.HFPOW,drymatter_kg_ha=f.HPODW,N_kg_ha=None,P_kg_ha=None,K_kg_ha=None,value_origin='SIMULATED',source_file=source('FreshWt.OUT'),
                    notes='本次整果采出量；非累计。标准输出无已核验的本次整果采出N/P/K，留空，不用当日采后浓度反乘。'))
                buckets['event_check'].append(base|dict(date=date,pre_fruit_dm_kg_ha=f.TOPOW,harvest_drymass_kg_ha=f.HPODW,post_fruit_dm_kg_ha=post,
                    arithmetic_residual_kg_ha=f.TOPOW-f.HPODW-post,PlantGro_PWAD_kg_ha=pg.loc[date,'PWAD'],cohort_minus_organ_pool_kg_ha=post-pg.loc[date,'PWAD'],
                    notes='前后差值为输出算术核查，非独立质量守恒证明。'))
            # Uptake is native cumulative external N; first-day increment is relative to season reset zero.
            uptake_daily=pn.NUPC.diff();uptake_daily.iloc[0]=pn.NUPC.iloc[0]
            for date,n in pn.iterrows():
                buckets['N'].append(base|dict(date=date,DAT=dat(s,date),root_uptake_N_kg_ha=uptake_daily.loc[date],root_uptake_cumulative_N_kg_ha=n.NUPC,
                    harvest_N_kg_ha=None,harvest_cumulative_N_kg_ha=None,nonharvest_wholeplant_N_loss_kg_ha=None,fixation_N_kg_ha=n.NFXD,
                    initial_plant_and_seed_N_kg_ha=None,end_plant_and_seed_N_kg_ha=None,N_balance_residual_kg_ha=None,value_origin='DERIVED',
                    notes='NUPC为原生累计根吸N；日值为相邻打印累计差，0.1kg/ha分辨率，非高精度真实日通量。无自定义收支账本，其余未核验值留空。',source_file=source('PlantN.OUT')))
            for date,f in fr.iterrows():
                g,n=pg.loc[date],pn.loc[date];cohort=f.TOPOW-f.HPODW
                buckets['pool'].append(base|dict(date=date,DAT=dat(s,date),cohort_post_fruit_DM_kg_ha=cohort,native_PlantGro_PWAD_kg_ha=g.PWAD,
                    cohort_minus_organ_pool_DM_kg_ha=cohort-g.PWAD,native_PlantN_CNAD_kg_ha=n.CNAD,native_PlantN_LNAD_kg_ha=n.LNAD,
                    native_PlantN_SNAD_kg_ha=n.SNAD,native_GNAD_seed_N_kg_ha=n.GNAD,canopy_minus_leaf_stem_N_kg_ha=n.CNAD-n.LNAD-n.SNAD,
                    native_shell_N_percent=n.SHND,native_seed_N_percent=n['GN%D'],status='DIAGNOSTIC_ONLY_NOT_CORE_FRUIT_N',source_file=source('FreshWt.OUT','PlantGro.OUT','PlantN.OUT')))
            for date,p in pp.iterrows():
                buckets['P'].append(base|dict(date=date,DAT=dat(s,date),generic_shoot_combined_P_kg_ha=p.SHPAD,generic_root_P_kg_ha=p.RTPAD,
                    generic_shell_P_kg_ha=p.SLPAD,generic_seed_P_kg_ha=p.SDPAD,generic_plant_P_kg_ha=p.PPAD,generic_shell_DM_kg_ha=p.SHAD,generic_seed_DM_kg_ha=p.GWAD,
                    status='NOT_VALIDATED_FOR_GAP_FILL',value_origin='SIMULATED',native_missing_fields=p.native_missing_fields,source_file=source('PlantP.OUT')))
            for interval in REQUESTS[REQUESTS.season.eq(SEASON[s])].to_dict('records'):
                a,b=interval['start_date'],interval['end_date_exclusive'];dates=pd.date_range(a,pd.Timestamp(b)-pd.Timedelta(days=1)).strftime('%Y-%m-%d');e,w=et.loc[dates],wb.loc[dates]
                buckets['period'].append(base|interval|dict(start_DAT=dat(s,a),end_DAT_exclusive=dat(s,b),n_daily_rows=len(e),ET_actual_mm=e.ETAA.sum(),ET_intensity_mm_d=e.ETAA.mean(),
                    transp_actual_mm=e.EPAA.sum(),evap_soil_actual_mm=e.ESAA.sum(),irrigation_effective_mm=w.IRRD.sum(),precip_effective_mm=w.PRED.sum(),runoff_mm=w.ROFD.sum(),drainage_model_bottom_180_mm=w.DRND.sum(),
                    storage_start_BOD_0_100_mm=storage(prev(a)),storage_end_BOD_0_100_mm=storage(prev(b)),delta_storage_0_100_mm=storage(prev(b))-storage(prev(a)),value_origin='DERIVED',
                    notes='严格[start,end)，前日日末近似日初；纯模型ET；保留原请求时窗，不因模型物候改变分期。'))
            def observation(q):
                date,var=q['date'],q['variable']
                if var in ['SWAD','LWAD','LAID','CHTD']:return float(pg.loc[date,var]),'matched_direct_native'
                if var in ['CHFPW','CHPDT','HPODW','HFPOW']:return float(fr.loc[date,var]),'matched_direct_native'
                if var in ['LEAF_N_PCT','STEM_N_PCT','LNAM','SNAM']:
                    field={'LEAF_N_PCT':'LN%D','STEM_N_PCT':'SN%D','LNAM':'LNAD','SNAM':'SNAD'}[var]
                    return float(pn.loc[date,field]),'matched_direct_native'
                if var=='ADAP':return anthesis[trt],'matched_native_Evaluate_ADAPS'
                if var=='PDMCD':
                    f=fr.loc[date]
                    return(float(f.HPODW/f.HFPOW),'derived_event_DM_over_fresh')if f.HFPOW>0 else(None,'no_positive_event_fresh_mass')
                if var=='VWC':
                    weights=[p.split(':')for p in q['dssat_layer_weights'].split(';')]
                    return sum(float(sw.loc[date,f'SW{int(i)+1}D'])*float(w)for i,w in weights),'matched_original_layer_weight_operator'
                if var=='WB100_INTERVAL':
                    a,b=q['interval_start'],q['interval_end'];dates=pd.date_range(a,pd.Timestamp(b)-pd.Timedelta(days=1)).strftime('%Y-%m-%d');w=wb.loc[dates]
                    return float((w.IRRD+w.PRED-w.ROFD).sum()-storage(prev(b))+storage(prev(a))),'I+P-runoff-deltaS100_proxy_NOT_direct_ET'
                if var in ['N_ADJACENT_FRESH_CONTRAST','W_FRESH_CONTRAST']:
                    other=int(q['paired_trno']);return float(fr.loc[date,'CHFPW']-frames['FreshWt'].loc[(other,date),'CHFPW']),'matched_signed_cumulative_fresh_difference'
                if var=='FRUIT_N_PCT':return None,'UNVERIFIED_mature_fruit_N_operator_do_not_substitute_seed_or_all_fruit'
                return None,'NOT_SUPPORTED'
            for table,role in [(PAIR,'ORIGINAL_STABLE79_TARGET_REFERENCE'),(DIAG,'ORIGINAL_DIAGNOSTIC_REFERENCE')]:
                for q in table[table.season_id.eq(s)&table.trno.eq(trt)].to_dict('records'):
                    value,status=observation(q)
                    p={k:q.get(k)for k in ['season_id','trno','date','variable','unit','observed','family','obsnme','source_file','observation_operator','interval_start','interval_end']}
                    unit=q.get('unit');unit=unit if isinstance(unit,str)and unit else UNITS[q['variable']]
                    p['unit']=unit
                    p.update(simulated=value,comparison_status=status,reference_catalog=role,data_use='COMMON_INPUT_MODEL_CHECK',replicate_id=rep,
                             calibration_claim='本次未率定，当前共同输入核对不能冒充原历史批次复现或新增独立验证')
                    buckets['pairs'].append(p)
                    buckets['cal'].append(base|dict(variable=q['variable'],unit=unit,start_date=q.get('interval_start')if pd.notna(q.get('interval_start'))else q['date'],
                        end_date_exclusive=q.get('interval_end')if pd.notna(q.get('interval_end'))else'',state_timing='MODEL_NATIVE_DAILY_EVENT_STATE',observed_value=q['observed'],simulated_value=value,
                        data_use='CHECK',observation_source=q.get('source_file',''),notes=role+'；'+status+'；同条件新运行，非本次重新率定；果实N按当日商品成熟果定义，未以全果或前日采出替代。'))
            totalI=float(wb.IRRD.sum());totalN=float(fert[fert['氮水平'].eq(r.N)]['N kg/ha'].sum())
            runmap.loc[ix,['ensemble_id','simulation_run_number','model','cultivar','simulated_I_applied_mm','simulated_I_infiltrated_mm','simulated_N_applied_kg_ha','source_directory','notes']]=[
                SPECS[rep],int(pg.run.iloc[0]),'Official DSSAT 4.8.5 CRGRO048 (eggplant on tomato)','TM0008/TM0001',totalI,totalI,totalN,work.relative_to(ROOT).as_posix(),
                f'重复{rep}为模型/参数方案，无区组生物重复；沿用重复1共同驱动，非历史批次完整原输入重放；官方原生参数文件和执行体。']
            buckets['inputs'].append(base|dict(observed_I_mm=r.observed_I_mm,model_I_mm=totalI,I_difference_mm=totalI-float(r.observed_I_mm),observed_N_kg_ha=r.observed_N_kg_ha,model_N_kg_ha=totalN))
            g,f=pg.loc[END[s]],fr.loc[END[s]]
            buckets['summary'].append(base|dict(date=END[s],final_harvest_fresh_kg_ha=f.CHFPW,final_harvest_dry_kg_ha=f.CHPDT,final_LAI=g.LAID,final_leaf_DM_kg_ha=g.LWAD,final_stem_DM_kg_ha=g.SWAD,
                final_height_m=g.CHTD,season_actual_ET_mm=et.loc[PLANT[s]:END[s],'ETAA'].sum(),final_root_N_uptake_kg_ha=pn.loc[END[s],'NUPC'],final_cohort_fruit_DM_kg_ha=fruit(END[s])[0]))
    save(out,'01_运行与处理对应.csv',runmap,'01_运行与处理对应.csv')
    for key,name,template in [('water','02_逐日水量.csv','02_逐日水量.csv'),('soil','03_边界土壤水.csv','03_边界土壤水.csv'),('organ','04_器官状态.csv','04_器官状态.csv'),('events','05_采收与其他移出.csv','05_采收与其他移出.csv'),('daily','10_逐日器官干物质与N状态.csv','04_器官状态.csv')]:save(out,name,buckets[key],template,['DAT'])
    save(out,'07_校准与验证记录.csv',buckets['cal'],'07_校准与验证记录.csv')
    for key,name in [('period','08_分期与观测窗口ET汇总.csv'),('extra','09_逐日180cm水量与100cm贮水.csv'),('N','11_逐日根吸N与采出损失账本.csv'),('P','12_原生P输出_未经补缺适用性验证.csv'),('event_check','13_采收前后干物质对账.csv'),('pool','14_官方果实库口径差异.csv'),('inputs','15_实测与模型投入对照.csv'),('pairs','16_共同观测逐项核对.csv'),('summary','20_各处理最终状态与季节汇总.csv')]:save(out,name,buckets[key])
    pairs=pd.DataFrame(buckets['pairs']);rows=[]
    for keys,g in pairs.groupby(['season_id','reference_catalog','family']):rows.append(dict(season=SEASON[keys[0]],reference_catalog=keys[1],family=keys[2])|metric(g))
    save(out,'18_共同观测核对指标.csv',rows)
    mapping=pd.read_csv(R1/'06_变量映射与支持情况.csv')
    mapping['event_inclusion']='官方逐日打印；果实批次采出前/后见state_timing；无自定义账本'
    for i,m in mapping.iterrows():
        field=m.target_field
        if m.source_file=='DMState.csv'and field!='harvest_drymatter_kg_ha':
            mapping.loc[i,['source_file','native_variable','native_unit','conversion_formula','notes']]=['PlantGro.OUT'if not field.startswith('fruit_')else'FreshWt.OUT',{'stem_drymatter_kg_ha':'SWAD','leaf_drymatter_kg_ha':'LWAD','root_drymatter_kg_ha':'RWAD'}.get(field,'TOPOW-HPODW'),'kg/ha','native kg/ha; no ×10','官方打印精度；果实采用批次库，不和PlantGro果实库或N池混配']
        if m.source_file=='OrganNState.csv':
            if field.startswith('fruit_'):
                mapping.loc[i,['source_file','native_variable','native_definition','native_unit','support_status','conversion_formula','notes']]=['PlantN.OUT / FreshWt.OUT','UNVERIFIED','官方同口径整果N未核验','kg N/ha','NOT_EXPORTED','','官方批次果重与器官库不一致，未将种子N或跨池差值冒充同口径整果N']
            else:mname={'stem_N_kg_ha':'SNAD','leaf_N_kg_ha':'LNAD','root_N_kg_ha':'RWAD*RN%D/100'}[field];mapping.loc[i,['source_file','native_variable','native_unit','conversion_formula','notes']]=['PlantN.OUT / PlantGro.OUT',mname,'kg N/ha',mname,'原生打印精度，非自定义高精度账本']
        if m.source_file=='NCBalance.csv':
            if field=='N_uptake_cumulative_kg_ha':mapping.loc[i,['source_file','native_variable','native_unit','conversion_formula','notes']]=['PlantN.OUT','NUPC','kg N/ha','native cumulative NUPC','不含初始苗N与内部转运；日增量来自打印累计差分']
            else:mapping.loc[i,['source_file','native_variable','native_definition','native_unit','support_status','conversion_formula','notes']]=['standard official output','none','无可靠同口径原生输出','kg N/ha','NOT_EXPORTED','','官方无该自定义账本；无可靠同口径替代值']
        if field=='harvest_drymatter_kg_ha':mapping.loc[i,['source_file','native_variable','native_unit','conversion_formula','notes']]=['FreshWt.OUT','HPODW','kg/ha','native HPODW','逐次整果采出干重，不是CHPDT累计值']
    save(out,'06_变量映射与支持情况.csv',mapping)
    gaps=pd.read_csv(R1/'19_逐缺项交付状态.csv');mask=gaps.gap_id.str.startswith('F');gaps.loc[mask,'limitation']=gaps.loc[mask,'limitation'].fillna('')+'官方版叶/茎/根N可交付；与批次果库对应的整果N及逐次采出N未核验，留空；不能主张完整植株N收支闭合。'
    save(out,'19_逐缺项交付状态.csv',gaps)
    shutil.copy2(raw/'指定最佳参数.csv',out/'指定最佳参数.csv');shutil.copy2(raw/'运行收据.json',out/'原始运行收据.json')
    for s in ['26SP','25SP']:shutil.copy2(raw/s/'全部参数原生回读.csv',out/f'{s}_全部参数原生回读.csv')
    note=f'''# 重复{rep}：官方DSSAT同条件模型对照

指定参数批次：{SPECS[rep]}。执行体为官方DSSAT 4.8.5，哈希与C:/DSSAT48安装及历史归档一致。共12个2026春处理、8个2025春处理，两个季节均重新实际运行完成。本次没有重新率定。

天气、初始状态、水肥及采收日程沿用重复1。2026/2025土壤SLPF仍为0.890/0.927，未使用历史批次的季节SLPF。基因文件采用历史最佳候选已经编码的原生CUL/ECO/SPE，不经当前注入器二次舍入。重复2的已率定SOIL_SLDR写入0.896、KEP为0.879；重复3无这两项参数，保留其SPE固定KEP=0.70，SLDR沿共同土壤为0.930。参数表104/102项逐项回读，原生分辨率内一致。共有驱动逐文件哈希对照和原始警告随原始运行保留。

01—11与重复1核心表对应；12为未经补缺适用性验证的原生P辅助值；13仅为果实批次采出前后算术核查；14逐日完整保存官方批次果库与器官库差异；16—18为基于重复1共同观测清单的新运行核对，不能当作原历史目标函数、原率定指标或新增独立验证；20汇总最终状态。原批次历史2026 N012率定、N3留出、2025春验证的角色仅属于当时协议，不自动迁移到本次共同输入运行。

果实批次采后DM=FreshWt.TOPOW−HPODW，鲜重=TOFPW−HFPOW。PlantGro.PWAD与此不总一致，不能以简单差值证明模型物理质量守恒。整果N及逐次采出N未核验同池对应，核心表留空；PlantN的跨器官N差值、种子N/壳N浓度只作14表诊断。根N由原生根干重×根N百分比推导，叶茎N取原生直接存量。原生打印精度低于自定义高精度账本，差分吸N不应解释为高精度日通量。

果实N实测按当天另摘商品成熟果理解，不改成前一天采收果，也不以全在株果、种子浓度替代。P未验证分器官/时点/多次采出对应，K过程关闭，P/K核心值留空。100cm上/下通量未输出，180cm排水另列，ET为逐日实际值，不是参考ET，也无独立直接ET验证。保留官方原始CaCO3缺失、低辐射及耕作深度等警告，不修改共同输入消除警告。

“重复{rep}”表示用户指定的模型/参数方案，同处理确定性模拟，无田间区组，block_id留空。不能把三套模型结果的离散程度当作田间三次独立生物重复，不能据此计算田间重复误差或用于声称田间显著性。
'''
    (out/'00_交付说明与使用限制.md').write_text(note,encoding='utf8')
    print(f'Repeat {rep} exported: '+str({k:len(v)for k,v in buckets.items()}),flush=True)
    return out

def combine(outs):
    out=ROOT/'三组模型对照汇总_20261019';out.mkdir(exist_ok=True)
    names=['01_运行与处理对应.csv','02_逐日水量.csv','03_边界土壤水.csv','04_器官状态.csv','05_采收与其他移出.csv','06_变量映射与支持情况.csv','07_校准与验证记录.csv','08_分期与观测窗口ET汇总.csv','09_逐日180cm水量与100cm贮水.csv','10_逐日器官干物质与N状态.csv','11_逐日根吸N与采出损失账本.csv','12_原生P输出_未经补缺适用性验证.csv','15_实测与模型投入对照.csv','19_逐缺项交付状态.csv']
    for name in names:
        parts=[]
        for rep,folder in enumerate([R1]+outs,1):
            q=pd.read_csv(folder/name);q.insert(0,'replicate_id',rep);q.insert(1,'replicate_label',f'重复{rep}');q.insert(2,'replicate_type','MODEL_PARAMETER_SCENARIO')
            q.insert(3,'model_scenario','stable79_checkpointed150x5_20261018'if rep==1 else SPECS[rep])
            if 'run_id'in q:q.insert(4,'source_run_id',q.run_id);q['run_id']=f'R{rep}_'+q.run_id
            q['delivery_source_file']=(folder/name).relative_to(ROOT).as_posix();parts.append(q)
        save(out,name,pd.concat(parts,ignore_index=True))
    metrics=[];common=[]
    for rep,folder in enumerate([R1]+outs,1):
        if rep==1:
            q=PAIR.copy();q['reference_catalog']='ORIGINAL_STABLE79_TARGET_REFERENCE'
        else:q=pd.read_csv(folder/'16_共同观测逐项核对.csv').query("reference_catalog=='ORIGINAL_STABLE79_TARGET_REFERENCE'")
        q=q[['season_id','trno','date','variable','unit','family','obsnme','observed','simulated','reference_catalog']].copy();q['replicate_id']=rep;common.append(q)
        for keys,g in q.groupby(['season_id','family']):metrics.append(dict(replicate_id=rep,season=SEASON[keys[0]],family=keys[1],evaluation='共同原目标观测清单；本次对照核对，非重新率定')|metric(g))
    save(out,'18_三组共同观测指标.csv',metrics);save(out,'16_三组共同观测逐项核对.csv',pd.concat(common,ignore_index=True))
    # Exact observed values must be shared, not quietly replaced by historical batch catalogs.
    c=pd.concat(common,ignore_index=True);observed_ranges=c.groupby('obsnme')['observed'].agg(['min','max'])
    assert ((observed_ranges['max']-observed_ranges['min']).abs()<=1e-10*(1+observed_ranges['max'].abs())).all()
    summaries=[]
    for rep,folder in enumerate([R1]+outs,1):
        if rep>1:q=pd.read_csv(folder/'20_各处理最终状态与季节汇总.csv')
        else:
            rows=[]
            receipt=json.loads((R1/'原始运行收据.json').read_text(encoding='utf8'));trial=Path(receipt['trial'])
            for r in BASEMAP.itertuples():
                s='26SP'if r.season=='2026春'else'25SP';trt=int(r.source_plot_code)
                p=next(z for z in PAIR.to_dict('records')if z['season_id']==s and z['trno']==trt and z['family']=='FINAL_FRESH_YIELD')
                pg=native(trial/s/'PlantGro.OUT').loc[(trt,END[s])]
                daily=pd.read_csv(R1/'10_逐日器官干物质与N状态.csv');leaf=daily[(daily.run_id==r.run_id)&(daily.date==END[s])&(daily.organ=='leaf')].iloc[0];stem=daily[(daily.run_id==r.run_id)&(daily.date==END[s])&(daily.organ=='stem')].iloc[0]
                n=pd.read_csv(R1/'11_逐日根吸N与采出损失账本.csv');n=n[(n.run_id==r.run_id)&(n.date==END[s])].iloc[0]
                water=pd.read_csv(R1/'02_逐日水量.csv');water=water[(water.run_id==r.run_id)&(water.date>=PLANT[s])]
                dm=daily[(daily.run_id==r.run_id)&(daily.date==END[s])&(daily.organ=='fruit_onplant')].iloc[0].drymatter_kg_ha
                dry=PAIR[(PAIR.season_id==s)&(PAIR.trno==trt)&(PAIR.family=='FINAL_DRY_YIELD')].iloc[0].simulated
                rows.append(dict(season=r.season,run_id=r.run_id,W=r.W,N=r.N,date=END[s],final_harvest_fresh_kg_ha=p['simulated'],final_harvest_dry_kg_ha=dry,final_LAI=pg.LAID,
                    final_leaf_DM_kg_ha=leaf.drymatter_kg_ha,final_stem_DM_kg_ha=stem.drymatter_kg_ha,final_height_m=pg.CHTD,season_actual_ET_mm=water.ET_actual_mm.sum(),final_root_N_uptake_kg_ha=n.root_uptake_cumulative_N_kg_ha,final_cohort_fruit_DM_kg_ha=dm))
            q=pd.DataFrame(rows)
        q.insert(0,'replicate_id',rep);q['source_run_id']=q.run_id;q['run_id']=f'R{rep}_'+q.run_id;summaries.append(q)
    save(out,'20_三组最终状态与季节汇总.csv',pd.concat(summaries,ignore_index=True))
    (out/'00_先读_三组定义与差异.md').write_text('''# 三组模型对照数据

重复1：自定义DSSAT 4.8.2，stable79_checkpointed150x5_20261018，沿用已完成交付；重复2：官方DSSAT 4.8.5，joint65_20261012最佳参数；重复3：官方DSSAT 4.8.5，joint67_20261011/final_parameters.csv。

重复2、3均已用重复1的双春天气、土壤初始条件、水肥及采收日程实际重新运行，各20处理。共有驱动逐文件哈希已核对。季节SLPF统一为0.890/0.927。重复2保留自己的率定SLDR=.896及KEP=.879；重复3无这两个率定项，SLDR沿共同土壤=.930，KEP沿该历史SPE固定=.70。其余原生基因参数按指定归档值回读核验。

所有合并表新增replicate_id、replicate_label、replicate_type与model_scenario。run_id加R1/R2/R3前缀防止重复键误连接，source_run_id保留同一处理键；block_id始终为空。原重复1文件和旧压缩包均保持不变。

这是三种模型/参数方案的模拟对照，不能作为田间独立生物重复，也不能将三者标准差/标准误用于田间显著性检验。模型版本、机制、基因参数及率定环境参数一并不同，本设计不能单独归因某一自定义机制的因果效应。

01—12为核心及辅助表，15为投入对照，16为同一观测清单逐项新核对，18为共同观测指标（R²=Pearson相关平方；NSE/d保留偏差，缺值不补零），19为逐缺项限制，20为60条最终状态和季节汇总。07保留重复1原始CALIBRATION/CHECK；重复2/3均记CHECK，本次没有重新率定，也未把新共同输入冒充原历史协议或独立验证。16/18的果实N仅重复1原记录有值，官方未核验的同日商品成熟果对应值为空，不能比较三组该项指标优劣。

官方版果实批次库与PlantGro器官库不一致，差异详见各自14表。统一核心果重按批次采后存量，官方同口径整果N与采出N留空；自定义版则有高精度账本。这些缺值代表输出/口径限制。叶茎N为官方直接存量，根N为根干重×根N%推导，保留原生打印精度。P核心值未验证，K关闭；100cm界面通量未输出；不能宣称三套完整N/P/K或100cm水量收支均闭合。

每套完整原始输出、输入哈希、运行日志、警告与参数回读均保留。公式、状态时点和原数据限制请同时查阅各组00说明及06映射表。
''',encoding='utf8')
    return out

if __name__=='__main__':combine([export(2),export(3)])
