"""Delivery QC against immutable source artifacts and native output, then zip verification."""
from 官方对照公共读取 import *
import zipfile

R1=ROOT/'已填数据_stable79_20261019'
COMBINED=ROOT/'三组模型对照汇总_20261019'
OFFICIAL='92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a'
def close(a,b,tol=1e-9):assert np.allclose(a,b,rtol=tol,atol=tol,equal_nan=True)
def raw_standard(path):
    """Separate whitespace reader for independent validation of standard daily outputs."""
    rows=[];header=None;trt=None
    for line in path.read_text().splitlines():
        if line.startswith('*RUN'):header=None;trt=None
        m=re.match(r'\s*TREATMENT\s+(\d+)',line)
        if m:trt=int(m[1])
        if line.startswith('@YEAR'):header=line[1:].split()
        elif header and re.match(r'\s*20\d{2}\s+\d+',line):
            vals=line.split();assert len(vals)==len(header)
            r=dict(zip(header,map(float,vals)));r['trno']=trt
            r['date']=(pd.Timestamp(int(r['YEAR']),1,1)+pd.Timedelta(days=int(r['DOY'])-1)).strftime('%Y-%m-%d');rows.append(r)
    return pd.DataFrame(rows).set_index(['trno','date'])

def main():
    results={};original_manifest=json.loads((R1/'文件校验SHA256.json').read_text(encoding='utf8'))
    for entry in original_manifest:assert sha(ROOT/entry['file'])==entry['sha256'],entry['file']
    assert sha(ROOT/'stable79_补缺数据交付_20261019.zip')=='509d59b6b84770c138da885d3ff546c4adfd7b36900a762d57e075511122a391'
    results['unchanged_repeat1_manifest_files']=len(original_manifest);results['original_repeat1_zip_unchanged']=True
    baseline=pd.read_csv(R1/'01_运行与处理对应.csv');trial=Path(json.loads((R1/'原始运行收据.json').read_text(encoding='utf8'))['trial'])
    all_counts={};max_pool={};official_parameter_checks={}
    for rep in [2,3]:
        folder=ROOT/f'已填数据_重复{rep}_官方_20261019';raw=ROOT/f'原始模型输出/official_repeat{rep}_20261019'
        rec=json.loads((raw/'运行收据.json').read_text(encoding='utf8'))
        assert sha(rec['parameter_source'])==rec['parameter_sha256']==sha(raw/'指定最佳参数.csv')
        runmap=pd.read_csv(folder/'01_运行与处理对应.csv');assert len(runmap)==20 and runmap.block_id.isna().all()
        close(runmap.simulated_I_applied_mm,baseline.simulated_I_applied_mm);close(runmap.simulated_N_applied_kg_ha,baseline.simulated_N_applied_kg_ha)
        for s in ['26SP','25SP']:
            work=raw/s;assert sha(work/'DSCSM048.EXE')==OFFICIAL==sha('C:/DSSAT48/DSCSM048.EXE')
            assert not(work/'ERROR.OUT').exists()
            for item in rec['seasons']:
                if item['season_id']==s:
                    assert item['returncode']==0
                    for name,digest in item['actual_input_sha256'].items():assert sha(work/name)==digest
            source=Path(rec['parameter_source']).parent/'selected_deterministic/_model'
            for suffix in ['CUL','ECO','SPE']:
                assert sha(work/f'TMGRO048.{suffix}')==sha(source/f'TMGRO048.{suffix}')
            a=(trial/s/'SOIL.SOL').read_text().splitlines();b=(work/'SOIL.SOL').read_text().splitlines();assert len(a)==len(b)
            for x,y in zip(a,b):
                if x!=y:
                    assert rep==2 and x[:18]==y[:18]and x[24:]==y[24:]
            audit=pd.read_csv(work/'全部参数原生回读.csv');assert audit.passed.all()and len(audit)==(104 if rep==2 else 102)
            assert ((audit.requested-audit.actual_native).abs()<=audit.printed_resolution/2+1e-9).all()
            official_parameter_checks[f'R{rep}_{s}']=len(audit)
        water=pd.read_csv(folder/'02_逐日水量.csv');soil=pd.read_csv(folder/'03_边界土壤水.csv');period=pd.read_csv(folder/'08_分期与观测窗口ET汇总.csv')
        daily=pd.read_csv(folder/'10_逐日器官干物质与N状态.csv');organ=pd.read_csv(folder/'04_器官状态.csv');events=pd.read_csv(folder/'05_采收与其他移出.csv')
        assert len(water)==2504 and len(soil)==3796 and len(period)==244 and len(daily)==9888 and len(organ)==640 and len(events)==132
        assert not water.duplicated(['run_id','date']).any()
        assert not soil.duplicated(['run_id','date','state_timing','layer_top_cm','layer_bottom_cm']).any()
        assert not daily.duplicated(['run_id','date','organ','state_timing']).any()
        assert not events.duplicated(['run_id','date','event_type']).any()
        assert water[['drainage_below100_mm','capillary_into100_mm']].isna().all().all()
        assert daily[['P_kg_ha','K_kg_ha']].isna().all().all()and events[['N_kg_ha','P_kg_ha','K_kg_ha']].isna().all().all()
        assert daily.loc[daily.organ.eq('fruit_onplant'),['N_kg_ha','N_g_kg_DM']].isna().all().all()
        assert daily.loc[daily.organ.ne('fruit_onplant'),'N_kg_ha'].notna().all()
        close(water.ET_actual_mm,water.transp_actual_mm+water.evap_soil_actual_mm,tol=.001001)
        for run,r in runmap.set_index('run_id').iterrows():
            s='26SP'if r.season=='2026春'else'25SP';work=raw/s;trt=int(r.source_plot_code)
            et=raw_standard(work/'ET.OUT').xs(trt);pn=raw_standard(work/'PlantN.OUT').xs(trt);pg=raw_standard(work/'PlantGro.OUT').xs(trt)
            w=water[water.run_id.eq(run)].set_index('date');assert set(w.index)<=set(et.index)
            close(w.ET_actual_mm,et.loc[w.index,'ETAA']);close(w.transp_actual_mm,et.loc[w.index,'EPAA']);close(w.evap_soil_actual_mm,et.loc[w.index,'ESAA'])
            assert w.DAT.eq((pd.to_datetime(w.index)-pd.Timestamp(PLANT[s])).days).all()
            for p in period[period.run_id.eq(run)].itertuples():
                wanted=et[(et.index>=p.start_date)&(et.index<p.end_date_exclusive)];assert len(wanted)==p.n_daily_rows
                close(wanted.ETAA.sum(),p.ET_actual_mm);close(wanted.EPAA.sum(),p.transp_actual_mm);close(wanted.ESAA.sum(),p.evap_soil_actual_mm)
            for name,mass,nfield in [('leaf','LWAD','LNAD'),('stem','SWAD','SNAD'),('root','RWAD',None)]:
                d=daily[(daily.run_id.eq(run))&daily.organ.eq(name)].set_index('date')
                close(d.drymatter_kg_ha,pg.loc[d.index,mass]);close(d.N_kg_ha,pn.loc[d.index,nfield]if nfield else pg.loc[d.index,'RWAD']*pn.loc[d.index,'RN%D']/100)
            # Raw event cumulative reconciliation is independent of the cohort state identity.
            fresh=native(work/'FreshWt.OUT').xs(trt);e=events[events.run_id.eq(run)].set_index('date')
            close(e.drymatter_kg_ha,fresh.loc[e.index,'HPODW']);close(e.freshmass_kg_ha,fresh.loc[e.index,'HFPOW'])
            assert abs(e.drymatter_kg_ha.sum()-fresh.CHPDT.iloc[-1])<.55
            assert abs(e.freshmass_kg_ha.sum()-fresh.CHFPW.iloc[-1])<.55
        cal=pd.read_csv(folder/'07_校准与验证记录.csv');pairs=pd.read_csv(folder/'16_共同观测逐项核对.csv')
        assert len(cal)==len(pairs)==2371 and cal.data_use.eq('CHECK').all()
        assert cal.unit.notna().all()and pairs.unit.notna().all()
        expected_dates=pairs.interval_start.where(pairs.interval_start.notna(),pairs.date)
        assert cal.start_date.equals(expected_dates.rename('start_date'))
        pools=pd.read_csv(folder/'14_官方果实库口径差异.csv');max_pool[str(rep)]=float(pools.cohort_minus_organ_pool_DM_kg_ha.abs().max())
        all_counts[str(rep)]={p.name:len(pd.read_csv(p))for p in folder.glob('*.csv')}
    combined=pd.read_csv(COMBINED/'01_运行与处理对应.csv');assert len(combined)==60 and not combined.run_id.duplicated().any()and combined.block_id.isna().all()
    water=pd.read_csv(COMBINED/'02_逐日水量.csv');daily=pd.read_csv(COMBINED/'10_逐日器官干物质与N状态.csv');period=pd.read_csv(COMBINED/'08_分期与观测窗口ET汇总.csv')
    assert len(water)==7512 and len(daily)==29664 and len(period)==732
    assert not water.duplicated(['run_id','date']).any()
    assert not daily.duplicated(['run_id','date','organ','state_timing']).any()
    pairs=pd.read_csv(COMBINED/'16_三组共同观测逐项核对.csv');assert len(pairs)==3369
    assert pairs.groupby('obsnme').size().eq(3).all()
    limits=pairs.groupby('obsnme')['observed'].agg(['min','max']);assert ((limits['max']-limits['min']).abs()<=1e-10*(1+limits['max'].abs())).all()
    metrics=pd.read_csv(COMBINED/'18_三组共同观测指标.csv')
    for m in metrics.itertuples():
        s='26SP'if m.season=='2026春'else'25SP';q=pairs[(pairs.replicate_id==m.replicate_id)&(pairs.season_id==s)&(pairs.family==m.family)].dropna(subset=['observed','simulated'])
        assert len(q)==m.n_matched
        if len(q):close(np.sqrt(np.mean((q.simulated-q.observed)**2)),m.RMSE)
    results.update(passed=True,scope='文件来源/参数回读/共有驱动/数据转换与合并核验；不是模型科学适用性全面验收',official_parameters_verified=official_parameter_checks,
                   official_per_table_counts=all_counts,combined_counts=dict(run_scenarios=60,daily_water=7512,daily_organ=29664,period_ET=732),
                   official_fruit_pool_max_discrepancy_kg_ha=max_pool,unverified_fruit_N_left_missing=True,block_id_empty=True,replicates_are_model_scenarios=True)
    dump(ROOT/'三组交付核验.json',results)
    (ROOT/'交付入口_三组模型对照_20261019.md').write_text('''# 双春三组模型对照交付入口

已按用户确认的“沿用重复1输入，做同条件模型对照”完成：

| 标识 | 执行体 | 指定参数 |
|---|---|---|
| 重复1 | 自定义DSSAT 4.8.2 capacity_a | stable79_checkpointed150x5_20261018，沿用原交付 |
| 重复2 | 官方DSSAT 4.8.5 | eggplant_26sp_n012_rmse_joint65_200x5_20261012/best_calibration_parameters.csv |
| 重复3 | 官方DSSAT 4.8.5 | eggplant_26sp_n012_c31_joint67_20261011/final_parameters.csv |

直接使用`三组模型对照汇总_20261019/`中的合并CSV。共60处理方案、7512条逐日水量、29664条逐日四器官状态、732条ET窗口汇总。20表为60行最终产量、LAI、叶/茎干重、株高、季节ET、根吸N等汇总；18表为同一观测清单下的R²、NSE、d、RMSE等指标。

各自完整整理数据在`已填数据_stable79_20261019/`、`已填数据_重复2_官方_20261019/`、`已填数据_重复3_官方_20261019/`。新运行原始输入/输出、警告、共有输入哈希、全部参数回读在`原始模型输出/official_repeat2_20261019/`及`official_repeat3_20261019/`。

重复2的104项、重复3的102项参数均完成原生字段回读，四次季节运行全部正常退出。共有天气、初始状态和管理保持一致；率定土壤/蒸发参数及各自SPE固定项差异已明示，季节SLPF统一沿重复1。原重复1文件263项来源哈希及旧压缩包核对未改动。

“重复”是模型/参数方案编号，不能当作田间独立生物重复。官方版果实批次与器官库有最高369.4kg/ha差异，完整差异在各组14表；对应整果N和采出N未核验，留空。P/K及100cm界面通量限制仍保留；未补零或借用重复1。不能把新对照结果当作原批次原输入精确重放，也不能用本对照单独归因某项自定义机制。

`三组交付核验.json`给出核验范围与结果，`三组交付文件SHA256.json`提供逐文件校验。新压缩包`双春三组模型对照_20261019.zip`包含三套整理数据、合并表、三套原始运行、参数、说明及可复现整理/核验步骤；原stable79压缩包保留不变。
''',encoding='utf8')
    folders=[R1,ROOT/'已填数据_重复2_官方_20261019',ROOT/'已填数据_重复3_官方_20261019',COMBINED,
             ROOT/'原始模型输出/stable79_checkpointed150x5_20261019',ROOT/'原始模型输出/official_repeat2_20261019',ROOT/'原始模型输出/official_repeat3_20261019']
    files=[p for f in folders for p in f.rglob('*')if p.is_file()and'__pycache__'not in p.parts]
    files += [ROOT/n for n in ['00_先读_缺失清单与交付说明.md','01_缺失项与用途清单.csv','02_日期与区间.csv','03_字段字典.csv','官方重复23运行总收据.json','三组交付核验.json','交付入口_三组模型对照_20261019.md',
                               '运行官方重复23.py','官方对照公共读取.py','整理官方重复与三组合并.py','核验并打包三组交付.py','整理stable79补缺数据.py','核验stable79补缺交付.py']]
    files += [p for p in (ROOT/'填报模板').rglob('*')if p.is_file()]
    assert len(set(files))==len(files)
    manifest=[dict(file=p.relative_to(ROOT).as_posix(),bytes=p.stat().st_size,sha256=sha(p))for p in sorted(files)]
    dump(ROOT/'三组交付文件SHA256.json',manifest)
    archive=ROOT/'双春三组模型对照_20261019.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6)as z:
        for p in files+[ROOT/'三组交付文件SHA256.json']:z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(archive)as z:
        assert z.testzip()is None
        assert len(z.namelist())==len(manifest)+1
        for r in manifest:assert hashlib.sha256(z.read(r['file'])).hexdigest()==r['sha256'],r['file']
    dump(ROOT/'三组压缩包核验.json',dict(passed=True,file=archive.name,bytes=archive.stat().st_size,sha256=sha(archive),member_count=len(manifest)+1,all_member_hashes_verified=True))
    print(json.dumps(dict(passed=True,counts=results['combined_counts'],max_fruit_pool_discrepancy=max_pool,zip_MB=archive.stat().st_size/1024**2,files=len(manifest)+1),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
