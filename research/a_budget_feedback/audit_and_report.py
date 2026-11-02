"""Final independent evidence audit and Chinese Markdown engineering report."""
from pathlib import Path
import collections,json,re,shutil,subprocess,sys
import numpy as np
import pandas as pd
from run_regression import OUT,REPO,sha,dump

ROOT=OUT.parents[1]/'runs/n4864_A_joint80x4_20261102_r1'
DATA=OUT/'analysis'


def md(df):
    lines=['| '+' | '.join(df.columns)+' |','| '+' | '.join(['---']*len(df.columns))+' |']
    for row in df.itertuples(index=False,name=None):
        vals=[]
        for x in row:
            if pd.isna(x):vals.append('—')
            elif isinstance(x,(float,np.floating)):vals.append(f'{x:.5g}')
            else:vals.append(str(x))
        lines.append('| '+' | '.join(vals)+' |')
    return '\n'.join(lines)


def main():
    d=json.loads((ROOT/'design.json').read_text(encoding='utf8'))
    completion=json.loads((ROOT/'completion_receipt.json').read_text(encoding='utf8'))
    assert completion['updates']==4 and completion['requested_members']==80
    assert completion['workers']==6 and completion['active']==75
    assert len(pd.read_csv(ROOT/'template/initial.par.csv'))==80
    assert all(sha(p)==h for p,h in d['frozen_hashes'].items())
    assert all(sha(p)==h for p,h in d['protected'].items())
    bounds=pd.read_csv(d['bounds']);reference=pd.read_csv(ROOT/'reference_active_76.csv').set_index('name')
    native=bounds[(bounds.pargp=='native')&(bounds.status=='active')].set_index('name')
    assert len(native)==58 and native[['lower','upper']].equals(reference.loc[native.index,['lower','upper']])
    wiring=pd.read_csv(ROOT/'parameter_wiring_preflight.csv');assert len(wiring)==75 and wiring.success.all()and wiring.effective.all()
    # Audit every failed forward natively, independently of missing objectives.
    receipts=[json.loads(p.read_text(encoding='utf8'))for p in ROOT.glob('_agents/*/native_trials/*/receipt.json')]
    failed=[r for r in receipts if not r['success']]
    failures=collections.Counter(r.get('error','')for r in failed)
    extra=[]
    for r in failed:
        w=Path(r['trial']);n=pd.read_csv(w/'PlantNIntegration.csv');a=pd.read_csv(w/'PlantABudget.csv')
        q0=n.groupby('run')[['QNO3','QNH4']].shift().fillna(0).sum(axis=1)
        qres=q0+n.U_NO3+n.U_NH4-n.A_NO3-n.A_NH4-n.inorg_litter-n.QNO3-n.QNH4
        nr=a.organic_end_including_seed-a.organic_begin_including_seed+a.cumulative_loss_end-a.cumulative_loss_begin+a.leak_end-a.leak_begin-a.A_committed
        nl=1e-5+2e-6*np.maximum(a.organic_end_including_seed,a.organic_begin_including_seed)
        over=np.maximum(0,a.veg_C_actual-a.veg_C_available)
        assert len(a)==1512 and a.budget_revision.eq(1).all()and len(n)==1512 and n.stage.eq(5).all()
        assert qres.abs().max()<1e-9 and (nr.abs()<=nl).all()and over.max()<2e-5
        extra.append(dict(trial=r['trial'],failure=r.get('error'),Q_independent_residual_max=qres.abs().max(),
                          organic_independent_residual_max=nr.abs().max(),veg_C_overrun_max=over.max(),native_budget_passed=True))
    pd.DataFrame(extra).to_csv(DATA/'failed_forward_budget_audit.csv',index=False)
    assert len(receipts)==completion['native_IES_evaluations'] and len(failed)==completion['failures']
    phi=pd.read_csv(ROOT/'manager/smoke.phi.actual.csv')
    sizes=[]
    for i in range(5):
        obs=pd.read_csv(ROOT/f'manager/smoke.{i}.obs.csv',index_col=0)
        assert np.isfinite(obs.to_numpy()).all()
        sizes.append(dict(iteration=i,members=len(obs),mean_phi=phi.loc[phi.iteration.eq(i),'mean'].iloc[0],min_phi=phi.loc[phi.iteration.eq(i),'min'].iloc[0]))
    pd.DataFrame(sizes).to_csv(DATA/'actual_iteration_members.csv',index=False)
    comp=pd.read_csv(ROOT/'best_comparison.csv');best=json.loads((ROOT/'best_parameters.exact.json').read_text(encoding='utf8'))
    assert len(comp)==612 and not comp.obsnme.duplicated().any()
    assert np.isclose(comp.phi_contribution.sum(),completion['best_actual_phi'],rtol=1e-12,atol=1e-10)
    exact=json.loads((ROOT/'exact_replay_receipt.json').read_text(encoding='utf8'))
    assert exact['parameter_bits_identical']and all(exact['actual_native_inputs_identical'].values())and exact['original_phi']==exact['replay_phi']
    b=bounds.copy();b['best_value']=b.name.map(best);b['relative_position']=(b.best_value-b.lower)/(b.upper-b.lower)
    b['near_working_bound_1pct']=(b.relative_position<=.01)|(b.relative_position>=.99)
    b.to_csv(DATA/'best_parameter_positions.csv',index=False)
    definitions={
      'q_no3_max':('g N/g carrier DM','硝态库容量；carrier为显式支持代理，不等于观测干重'),
      'assim_no3_v':('g N/(g carrier DM·d)','比同化潜力；实际总潜力再乘carrier，并受底物、温度、C和接纳限制'),
      'assim_no3_k':('g N/g carrier DM','比硝态底物半饱和浓度'),
      'root_v':('g N/(m root·d)','单支米氏硝态膜运输潜力'),
      'root_k':('mg N/L water','硝态根表运输半饱和浓度'),
      'diffusion_k':('L water/(m root·d)','有效根际扩散系数；进入供给-膜运输闭环，不与主动通量重复相加'),
      'pool_beta':('1','无机库占用对吸收的反馈强度'),
      'leaf_a':('g N/g leaf DM','叶幂函数幅度系数；数学1 t/ha参照'),
      'stem_a':('g N/g stem DM','茎幂函数幅度系数；数学1 t/ha参照'),
      'leaf_b':('1','叶稀释指数'), 'stem_b':('1','茎稀释指数'),
      'min_ratio':('1','叶/茎共同的下软参考与临界之比'),
      'max_ratio':('1','叶/茎共同的上软参考与临界之比'),
      'photo_gamma':('1','功能面积N响应指数'),
      'growth_tau':('d','统一生长状态恢复时间尺度'),
      'photo_slw_ref':('g DM/cm² leaf','功能面积N参考的比叶重尺度；乘10000换算g DM/m²叶'),
      'curve_w0':('t DM/ha','站存叶+茎DM的稀释起点'),
    }
    new=b[(b.pargp=='new_n')&(b.status=='active')][['name','init','lower','upper','best_value']].copy()
    assert set(new.name)==set(definitions)
    new['unit']=new.name.map(lambda k:definitions[k][0]);new['definition']=new.name.map(lambda k:definitions[k][1])
    new.to_csv(DATA/'NI_parameter_definitions_and_bounds.csv',index=False)
    # Accepted final-member objective, independent of PEST's rounded summary.
    ob=pd.read_csv(ROOT/'manager/smoke.4.obs.csv',index_col=0)
    weights=pd.read_csv(d['observations']).set_index('obsnme').final_weight
    ob.columns=ob.columns.str.lower();weights.index=weights.index.str.lower()
    finalphis=ob.mul(weights.loc[ob.columns],axis=1).pow(2).sum(axis=1)
    pd.DataFrame(dict(realization=finalphis.index,phi=finalphis.values)).to_csv(DATA/'final_member_phi_recomputed.csv',index=False)
    meta=pd.read_csv(DATA/'treatment_metadata.csv');meta=meta.set_index('run')
    ys=comp[comp.family.eq('FINAL_FRESH_YIELD')].set_index('trno')
    contrasts=[]
    for water in ['W1','W2','W3']:
        ids=meta[meta.water.eq(water)]
        control=int(ids[ids.nitrogen.eq('N0')].index[0])
        for nitrogen in ['N1','N2','N3']:
            tr=int(ids[ids.nitrogen.eq(nitrogen)].index[0])
            contrasts.append(dict(water=water,nitrogen=nitrogen,observed_delta_t_ha=(ys.loc[tr,'observed']-ys.loc[control,'observed'])/1000,
                                  simulated_delta_t_ha=(ys.loc[tr,'simulated']-ys.loc[control,'simulated'])/1000))
    pd.DataFrame(contrasts).to_csv(DATA/'best_N_response_contrasts.csv',index=False)
    from src.calibration.single_season_n import read_native
    stage_rows=[]
    stage_cases={'old_r020':OUT.parents[1]/'runs/early_n_r020_diag_20261102/cases/baseline',
                 'A_fixed':OUT/'regression/A_verified','best_fit':OUT/'best_native_trace'}
    for name,path in stage_cases.items():
        g=read_native(path/'PlantGro.OUT').reset_index()
        for tr,q in g.groupby('trno'):
            for threshold,label in [(1,'R1'),(5,'R5')]:
                first=q[q.GSTD.ge(threshold)].iloc[0]
                stage_rows.append(dict(case=name,trno=tr,stage=label,GSTD_threshold=threshold,date=first.date,DAP=first.DAP))
    pd.DataFrame(stage_rows).to_csv(DATA/'R1_R5_native_stage_check.csv',index=False)
    # Preserve a portable exact replay adapter without modifying historical runtime.
    replaydir=ROOT/'exact_replay_runtime';replaydir.mkdir(exist_ok=True)
    shutil.copy2(REPO/'research/a_budget_feedback/forward_A.py',replaydir/'forward_A.py')
    shutil.copy2(ROOT/'runtime/smoke_forward.py',replaydir/'smoke_forward.py')
    selected=Path(completion['best_trial'])
    shutil.copy2(selected/'NIntegration.nml',ROOT/'best_NIntegration.nml')
    shutil.copy2(ROOT/'bin/dscsm048_A.exe',OUT/'bin/dscsm048_4864_A_verified.exe')
    receipt=dict(passed=True,requested_members=80,completed_updates=4,final_members=completion['final_members'],
         native_calls=len(receipts),successful_native_calls=len(receipts)-len(failed),failed_native_calls=len(failed),
         failed_native_budgets_passed=len(extra),failure_reasons=dict(failures),
         all_frozen_dependencies_unchanged=True,all_protected_binaries_unchanged=True,
         native_reference_ranges_preserved=58,active_native=58,active_NI=17,all_active_wiring_probes_passed=75,
         best_phi=completion['best_actual_phi'],final_accepted_min_phi=float(finalphis.min()),
         exact_replay_passed=True,model_source_commit=d['final_source_commit'],
         evidence_tool_commit=subprocess.check_output(['git','-C',str(REPO),'rev-parse','HEAD'],text=True).strip(),
         binary_sha256=d['binary_sha256'],
         quality_scope='new inorganic and committed organic N; vegetative growth payment; actual residue return; not complete elemental C closure or external validation')
    dump(OUT/'final_independent_audit.json',receipt)

    metrics=pd.read_csv(ROOT/'best_metrics.csv')
    show=metrics[['family','n','rmse','nrmse_pct','bias','nse','phi']].copy()
    # Keep units explicit: the raw metrics CSV retains kg/ha for mass/yield.
    for key in ['FINAL_FRESH_YIELD','HARVEST_FRESH_CUMULATIVE_EARLY','HARVEST_FRESH_EVENT','LEAF_DRY_MASS','STEM_DRY_MASS']:
        show.loc[show.family.eq(key),['rmse','bias']]/=1000
    show=show.rename(columns={'family':'指标','n':'样本数','rmse':'RMSE','nrmse_pct':'NRMSE%','bias':'偏差','nse':'NSE','phi':'Phi'})
    source=pd.read_csv(DATA/'N_source_and_C_paths.csv');budgets=pd.read_csv(DATA/'treatment_budgets.csv')
    sources=source[source.run.isin([2,11])][['case','label','leaf_mobil_gN_m2','stem_mobil_gN_m2','fruit_new_N_gN_m2','photo_factor_ge_0p99_days']]
    sources=sources.rename(columns={'case':'模型','label':'处理','leaf_mobil_gN_m2':'叶动员gN/m²','stem_mobil_gN_m2':'茎动员gN/m²','fruit_new_N_gN_m2':'果实新增N g/m²','photo_factor_ge_0p99_days':'光合因子≥0.99天数'})
    ab=pd.read_csv(DATA/'leaf_mobilization_ablation.csv')
    absum=ab[['case','W2_N3_yield_t_ha','W2_N0_yield_t_ha','W2_N3_minus_N0_t_ha']].rename(columns={'case':'方案','W2_N3_yield_t_ha':'N3鲜产t/ha','W2_N0_yield_t_ha':'N0鲜产t/ha','W2_N3_minus_N0_t_ha':'N3−N0 t/ha'})
    bands=pd.read_csv(DATA/'observed_leaf_and_reference_bands.csv');band=bands[(bands['case']=='old_r020')&bands.label.eq('W2_N0')]
    band=band[['date','observed','leaf_min_pct','leaf_crit_pct','leaf_max_pct']].rename(columns={'date':'日期','observed':'N0实测%','leaf_min_pct':'Nmin%','leaf_crit_pct':'Ncrit%','leaf_max_pct':'Nmax%'})
    grid=pd.read_csv(DATA/'controlled_curve_grid.csv')[['w0','min_ratio','max_ratio','phi','yield_nrmse_pct','W2_N3_minus_N0_t_ha']]
    grid=grid.rename(columns={'w0':'W0','min_ratio':'下比值','max_ratio':'上比值','phi':'Phi','yield_nrmse_pct':'鲜产NRMSE%','W2_N3_minus_N0_t_ha':'W2 N3−N0 t/ha'})
    cash=[]
    for name in ['old_r020','A_fixed','best_fit']:
        s=source[source['case'].eq(name)].set_index('run');c=budgets[budgets['case'].eq(name)].set_index('run')
        cash.append(dict(模型=name,高氮多得光合C=s.loc[2,'gross_PG_gCH2O_m2']-s.loc[11,'gross_PG_gCH2O_m2'],
                         高氮多付同化C=c.loc[2,'C_assim_gCH2O_m2']-c.loc[11,'C_assim_gCH2O_m2'],
                         果实C差=s.loc[2,'fruit_C_gCH2O_m2']-s.loc[11,'fruit_C_gCH2O_m2']))
    pd.DataFrame(cash).to_csv(DATA/'W2_carbon_contrasts.csv',index=False)
    earlyold=128.9634143172542
    text=f'''# A方案修复、叶氮库归因、三曲线对照与80×4联合率定报告

日期：2026-11-02，范围仅26春12处理。本文是工程诊断与率定记录，未作论文或独立预测验证。

## 1. 已完成什么，尚不能宣称什么

已完成A方案的实际接纳/主N预算及营养生长C付款修复、原生回归、0.7/1.0与带宽对照、75活动参数接线验证、独立冻结边界，并真实调用PEST++ IES运行80初始成员×4次更新、6并行。

**结果不是“问题全部解决”：最佳Phi降至{completion['best_actual_phi']:.8f}，鲜产NRMSE为7.97%，但W2的N3−N0仍为−1.6836 t/ha，且最终仅保留56成员。守恒与平均拟合改善，不等于水氮响应已正确。**该组参数作为机制研究候选保留，不宜据此开展正式水氮管理优化。

独立工作树：`{REPO}`；分支`codex/a-budget-feedback-20261102`；机制源代码冻结提交`{d['final_source_commit']}`。率定执行体SHA-256为`{d['binary_sha256']}`，复制交付于`bin/dscsm048_4864_A_verified.exe`。官方、旧正式自定义和其他受保护执行体均未覆盖。V15只引用用户指定参数表的活动项/范围，没有移植其生理实现。

## 2. W2_N0为何低叶N却比N3高产

### 2.1 叶库动员具有因果贡献，但不是唯一原因

旧r020的W2_N0全季叶N动员0.9642 g/m²，N3仅0.0520 g/m²，约18.6倍；两者果实新增N均约6.22 g/m²。N0用更多内部氮替代当季同化氮。原生PODS仍优先获得共享NAVL，低氮不必同步转化为较低果实供氮。

{md(sources)}

光合因子统计基于125个实际光合日。旧模型两处理均125天≥0.99。A后N0为78天，最佳组为61天，说明反馈已经拉开；产量倒序仍存在，不能再仅以“光合完全没有N响应”解释。

另编译叶动员比例为0.5和0的独立诊断执行体，重算实际总NMINEA，其余供体不额外补偿；采用完全相同输入复跑12处理。率定执行体和目标未改动。

{md(absum)}

旧模型禁用叶动员后倒序消失；最佳组禁用叶动员使N0由65.6600降至61.9512 t/ha、N3仅由63.9764降至63.9227，N3−N0由−1.6836变为+1.9715。因此，当前最佳组仍明显依赖叶库支持低氮果实产量。但减半动员会略增N0产量，反映保叶维持同化与向果实供N的权衡；**禁止叶动员不是可推荐的生理修复**，也未采用为新正式机制。

共享NAVL没有来源标签，不能把全部NRUSLF称作直接输给果实。逐日可行流量界限和“充分混合记账”估计已分别导出：旧N0叶→果直接累计可行区间约0—0.9560 gN/m²，混合估计0.4357；最佳组约0—2.2345，混合估计1.0776。这些是预算界限/记账估计，不是实测同位素示踪或新的生理分配规则。

### 2.2 高氮的额外收益仍被额外同化成本抵消

下表为W2的N3−N0，单位均为g CH2O/m²：

{md(pd.DataFrame(cash))}

高N得到更多总光合，也支付了更多同化C；额外同化付款略高于光合增加。低N还可以使用成本较低的内部有机N再转运。结合原生果实优先供N与当前可动员叶N范围，这是低叶N仍维持果实产量的主要机制链。维持、周转、储C和组织组成也参与，不能把这三项差额当作完整元素C归因。

## 3. 当前参考带：比例偏宽，同时整条参照偏低

旧配置`Nmin=0.4Nc, Nmax=1.25Nc`，带宽为0.85Nc，并非统计置信带或由实测识别出的生理容许范围。初期叶Nc=3.2088%，下/上参考为1.2835%/4.0110%。

{md(band)}

关键是：这三次N0实测不仅远高于Nmin，也都高于旧Nmax。因而问题包括参考曲线整体位置，不能只把下限向上推。N0是零施氮，仍可能利用初始土壤N、矿化和原有库存；它不等于结构N耗尽处理。其观测不能直接设为最低生理浓度。

A将可动员叶/茎N的剩余参照改为动态Nmin；在原40%下参考较低时，这反而释放了更多后期可动员N：同参数A的W2_N0叶动员由0.964增至1.713，最佳组进一步为2.249 g/m²。这是此次排查发现的重要代价，说明**函数化下参考并不自动等于合理的功能叶保护**。原生PROLFF/PROSTF仍参与衰老组织N组成，不能再把其数值直接解释为当前活体供体的全部下限。

当前叶、茎各有a/b，但共用min_ratio/max_ratio；三曲线并非三个独立试验识别的结构/功能/奢侈氮关系。测定的有机/总N口径仍需核实，本次保持LN%D/SN%D既有算子，没有用未知硝态回收比例补偿拟合。

## 4. A方案具体修复及回归

1. VEGGR按实际新组织N组成计算C付款，并同步缩减最终DM/N，消除L02生长量已确定后成本变更造成的超支。
2. 旧组织按各自亏缺和接纳空间补N，不再跟随新叶/茎分配份额；蛋白补入同时增加DM的效应纳入接纳量。实际补N/储C不被旧组织损失比例二次扣除，处理L03。
3. 同一叶生长接受量控制新叶DM及面积，移除DEMAND对SLA重复施加的N乘子；预测浓度接近下参考时及时抑制叶扩展，恢复仍保留时间尺度。未接纳的叶储C转到原生茎储C并支付同一PCH2O费用。
4. 功能面积N参考显式为photo_slw_ref；超过Nc的有机N不自动同比增加Pmax，超过功能亏缺的补N不自动增加同比叶面积。保留新组织PROLFG/PROLFI最低组成关系参与联合率定，没有把软Nmin强行设为新组织化学最低浓度。
5. 采收果肉N从残体回土通量剔除（L01）；种子采收N累计改用PCNSD（L04）。额外发现采收N输出超过可用库存的日期，按实际N库存结算输出，保留原果实N需求/组成设计，不做果实稀释。
6. 根残体按实际NROFF返回各土层，消除更新前后浓度混用。组织损失先受可用N约束，不以负库存保护掩盖超支。
7. 新增PlantABudget.csv，给出实际有机N前后库存、损失、同化、叶扩展和营养生长C付款；新Q库、土层吸收交接仍独立审计。
8. 原诊断图将GSTD≥5标为R1，实际为R5。新诊断不复用该标记；R1按GSTD≥1/原生开花输出核对，逐处理日期见`analysis/R1_R5_native_stage_check.csv`。率定一直使用原生开花输出，并未以错误图标日期作目标。

旧模式revision=0与官方mode=0各8类输出精确复现，A重复运行8类输出一致；29项原生核心检查及9项A检查通过。12组最终曲线对照全部正常完成12处理并通过新账本检查。

旧r020单日有机N残差最大3.27e−3 gN/m²、营养生长C超支最大0.9832 gCH2O/m²；A同参数降到约3.08e−7和4.77e−7，最佳组分别约4.05e−7和9.54e−7。A表层残体独立回算误差最大约2.52e−7 gN/m²；旧模型存在采收N重复回土。根返回误差由约3.00e−4降至约1.91e−9 gN/m²。

历史Python测试25项通过后，停在既有跨季历史CSV的4.56%→4.59%稀释断言；此测试不运行本次执行体，未改写历史数据强求通过，也未把25秋适用性纳入本轮。**未宣称全测试绿灯或完整元素C闭账**。GRWRES部分原生诊断仍按吸收量计算还原呼吸，解释实际同化支出应使用新账本；整株DM/元素C及其他stage组合需另作完整核查。

## 5. 0.7/1.0与带宽受控对照

定义`Nc=a·max(W,W0)^(-b)`，W为站存叶+茎DM（t/ha）。本次a保留幂律在1 t/ha处的系数；0.7与1.0方案在W≥1时相同，0.7提高幼苗平台（b=0.3时约11.3%），只隔离断点影响。若将a改定义为幼苗平台，会得到另一组整体移动的曲线，不能与本次混读。

其他参数固定，2断点×3下比值×2上比值：

{md(grid)}

单独抬Nmin或用0.7起点没有改善总拟合，虽然部分处理响应差值增大。将Nmax从1.25Nc降至1.1Nc可减轻高N额外补库成本并改善W2排序；仍未达到实测响应。上述对照不是各结构分别充分率定后的胜负，不证明0.7生理上错误。后续联合域记录为W0 0.7—1.5、min_ratio 0.4—0.75、max_ratio 1.1—1.25，范围属于工程工作域。

## 6. 参数参考、真实率定与失败谱

用户指定76参数表逐字节快照、SHA和适配说明见`parameter_reference/`。58个兼容原生活动参数保留原lower/upper，包含物候、ICMP/TCMP及TRIFL≤0.85。4个旧CNC、9个NB、RTNO3、旧FNPGN1/2/LNREF及25春SLPF没有按名称直接替换到新版。新增17个NI活动参数独立定义/冻结，共75活动。

全部75项通过原生扰动：TCMP在ICMP=2.5的交互环境下显示作用，保持活动；PM06远端点没有当天成熟果，失败保留，另一端点证实接线有效，原范围未缩。单点有响应只证明接线，不等于可识别。KEP尚未列入主注册表物理硬域，本轮保留用户0.76—0.9工作域并做局部工程核查，未新增全局物理硬限。

新增NI定义、初值、边界、最佳值和单位完整保存在`analysis/NI_parameter_definitions_and_bounds.csv`。尤其assim_no3_v是按carrier归一的g N/(g carrier DM·d)，需再乘carrier；不是固定的g N/m²/d。新工作域属于工程先验，不冒充成熟生理硬边界。17项简表如下：

{md(new[['name','lower','upper','best_value','unit']].rename(columns={'name':'NI参数','lower':'下界','upper':'上界','best_value':'最佳值','unit':'单位'}))}

率定固定26春、12处理、612个原有直接观测及权重；NSTFAC/NRCVR/SENRT2固定，FL-VS=100。未加日期/季节生长护栏或SPAD/光合替代目标。初始80组在冻结全域内取起点±12%全域宽度的局部均匀分布，seed=20261102；全边界仍供IES更新。使用真实PEST++5.2.16，6个独立原生工作进程。

{md(pd.DataFrame(sizes).rename(columns={'iteration':'更新轮次','members':'实际成员','mean_phi':'均值Phi','min_phi':'最小Phi'}))}

PEST主程序运行19.27分钟，原生IES评估779次：744次成功、35次失败；失败均为7月2日某处理商品成熟果浓度无法定义，独立复核这35次的1512处理日N/营养生长C账仍通过。没有运行超时、预算断言失败、补零、上一日替代或陈旧目标复用。

初始18成员失效，更新阶段继续丢失，最终56成员。失败候选剔除是[PEST++官方手册§9.2.7](https://github.com/usgs/pestpp/blob/master/documentation/pestpp_users_manual.md#s13-2-7)所述行为；本轮不是80个完整后验样本，不能把初始规模写成最终保留数，也不据其给出管理不确定性结论。

PEST正常结束后，后处理最初因“最终必须仍有80成员”的假设中断；现分开记录请求80、实际56及`full_80_member_retention=false`，收尾状态为`completed_with_member_attrition`。这修复了状态汇报，不表示补齐成员；没有因此重启率定、放松预算或改写失败观测。

已核查一个失败原生案例：7月1日采走成熟果干重585.4 kg/ha；7月2日MTDSH/MTDSD均0，仍有未成熟果肉46.8 kg/ha；7月3日又出现成熟果肉14.7 kg/ha。FreshWt在当前日按PAGE≥XMAGE累积成熟果并采收，**不是提取器把当日采收后的零值误当采收前库存**。实际7月2日另摘商品果这一事实要求后续审查商品成熟定义、果实cohort形成和采收选择性；本次没有挪动采样日、删目标或杜撰浓度。

## 7. 最佳组、重现与拟合局限

所有实际评估候选最佳Phi={completion['best_actual_phi']:.12f}；从写出精度有限的最终成员观测CSV重算最小Phi约{float(finalphis.min()):.5f}，不以其末位差异替代原生精确重放结果。相对旧r020最佳128.9634下降{100*(earlyold-completion['best_actual_phi'])/earlyold:.2f}%；相对本轮新起点151.2061下降约58.13%。这些仅是相同目标定义下的训练拟合。

最初回放Phi有约4.12e−5差异，定位到默认CSV浮点读取损失末位，实际固定列原生字段相同而NML连续参数末位不同。现使用round_trip适配器独立重放，参数浮点值及实际原生输入（排除工作路径）逐字节一致，Phi完全相同。历史冻结运行代码/原始评估不改写。精确参数保存在`best_parameters.exact.json`，后续部署应使用修复的`exact_replay_runtime/forward_A.py`；不能只依赖默认CSV解析。

质量指标如下。产量、累计/单次鲜采收及叶/茎干重的RMSE/偏差已在本表换为t/ha；原CSV保留kg/ha。氮浓度为百分点，冠高m，土壤水分体积比，物候d；NRMSE使用实测均值，NSE未定义以—显示。

{md(show)}

鲜产均值61.70 t/ha，实测均值约64.96 t/ha；叶N仍平均低估0.645个百分点，叶N的NSE为负，茎干重NRMSE仍38.2%。物候仍有4天偏差。低Phi不能代替这些质量指标。

最佳W2_N3=63.9764、N0=65.6600 t/ha，实测分别71.86995、61.63245，实测差+10.2375；模型差−1.6836，比旧倒序更大。全部水氮差值见`analysis/best_N_response_contrasts.csv`。当前目标以直接绝对观测拟合为主，降低各指标综合残差不保证正确的处理间因果响应；本次未擅自增加响应目标或改变权重。

最佳a_leaf≈3.6563%、a_stem≈2.2500%，W0≈0.9715，min_ratio≈0.4289，max_ratio≈1.10008，photo_slw_ref≈28.36 gDM/m²叶。上参考比值贴近工程下界；物候与库容/同化也发生联动。参数位置和全表见`analysis/best_parameter_positions.csv`，不能据75项接线验证宣称75项独立可识别。

## 8. 下一步应优先做什么

1. **先修正成熟果观测的可定义性问题**：保持当天商品成熟果对象，核查XMAGE、cohort粒度、采收管理及独立采样的对应。由机制/管理事实解决7月1日清空→7月2日无样本的模型缺口；不以日期生长护栏、填值或移动日期来保住成员数。
2. **拆开叶片储备供N与功能氮消耗的代价**：当前动态Nmin太低时释放过多可动员N。先固定根吸收做动员强度、最低活体保留和功能面积N的交互对照，检验源汇补偿；不能仅将NMOBMX一律调低或禁止叶→果。
3. **审查功能需求与富余补库的同化C优先级**：实际接纳、付款现已守恒，但同时向Nmax补充仍可能占用C、给高N带来成本而功能收益趋饱和。把功能缺口与富余补充的时序/优先级做独立消融，不以任意减小硝酸还原成本换取拟合。
4. **用同日叶DM、LAI、叶有机/总N的配对核定参照尺度**，再决定是否给叶/茎分别的最低比例或独立曲线形状；目前N0浓度高于上参考说明仅缩带不足。继续扩展整株DM/元素C与原生诊断输出一致性核查。
5. 完成连续N梯度、断氮恢复、施氮脉冲、富N储备与低C对照后，再启动下一轮联合率定；保留本次75项范围出处和实际接线证据，不将本轮低Phi候选直接升为管理版本。如拟借鉴V15 S1的储备/功能氮分离实现，仍须先提交具体差异并取得用户审批。

## 9. 可复核文件

- 率定批次：`{ROOT}`；`design.json`、`data/parameter_registry/bounds_frozen/eggplant/A_joint_20261102.csv`、`completion_receipt.json`、`exact_replay_receipt.json`。
- 本目录：`final_independent_audit.json`、`final_controlled_curve_receipt.json`、`best_trace_ablation_receipt.json`、`analysis/`下全部来源/预算/对照/失败谱CSV。
- 源码与可复现脚本：独立分支`research/a_budget_feedback/`；核心变更为CG_Nitrogen、DEMAND、VEGGR、CROPGRO、GROW；更新后的原生bug台账在`research/n_integration_v2/deferred_bug_ledger.md`。
- `figures/diagnostic_*.png`仅是工程运行诊断，不是论文图。未修改主项目图表渲染器、共享PEST模板或观测目录。
'''
    report=OUT/'A方案修复_氮库归因_曲线对照与80x4率定报告_20261102.md'
    report.write_text(text,encoding='utf8')
    files=[report,OUT/'final_independent_audit.json']+list(DATA.glob('*.csv'))+[p for p in (OUT/'figures').glob('diagnostic_*.png')]
    dump(OUT/'delivery_manifest.json',dict(status='engineering_completed_with_member_attrition_and_unresolved_N_response',
         files={str(p.relative_to(OUT)):sha(p)for p in files},binary_sha256=d['binary_sha256'],
         no_production_binary_replacement=True,V15_physiology_adopted=False))
    print('REPORT',report)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
