"""Reusable diagnostic atlas: freeze, independently check, render, and index."""
from pathlib import Path
import argparse,json,subprocess
import pandas as pd
from data import freeze,sha,dump
from metrics import contrasts
from catalogue import V,PLATES,HOMEOSTASIS_PLATES,ASSIM_PLATES,POOL_CONCENTRATIONS
from render import Atlas

def freeze_bundle(case,metadata,destination,label,profile,extra_n,extra_n_unit,comparison=None,simulation_only=False):
    d,o,state=freeze(case,metadata,destination,label,profile,extra_n,extra_n_unit,comparison,simulation_only)
    delta,summary=contrasts(d)
    delta.to_csv(destination/'diagnostic_contrasts.csv',index=False)
    summary.to_csv(destination/'diagnostic_separation_summary.csv',index=False)
    pd.DataFrame([dict(variable=k,label=v[0],unit=v[1],temporal_type=v[2],observed_family=v[3],
        available=d[k].notna().any() if k in d else False) for k,v in V.items()]).to_csv(destination/'variable_catalogue.csv',index=False)
    state['bundle_artifacts']={p.name:sha(p) for p in destination.glob('*.csv')}
    dump(destination/'source_manifest.json',state)
    return state

def index(out,atlas,reference_state=None):
    label=atlas.state['label'];d=atlas.d;summary=atlas.summary
    lines=['# 自定义DSSAT氮梯度诊断图册','',f'本次配置：**{label}**。共{atlas.state["treatments"]}处理、{atlas.state["days"]}日。',
        '', '[打开整套PDF图册](figures/diagnostic_atlas.pdf)。所有图是机制运行诊断，不等同独立科学验证。','',
        '## 使用顺序','',
        '先看00总览定位差异在哪个环节变小，再看相应原始曲线；当N1—N3重合时看09差值页。'
        '01看等效无机Q，02分清同化通量和库存，03看茎叶浓度，04看面积形成，05看实际光合，06看真实采收。'
        '07分库，08核查状态刻度和实际响应，10区分根系供给潜力与实际吸收。','',
        '## 必须保留的口径','',
        '- “液泡库”是等效无机Q，包含NO3和NH4；器官分摊不能解释成已验证的真实液泡运输。',
        '- 每日同化和累计同化是流量／累计流量，有机N是库存；采收和损失会使库存降低。R是Norg的一部分，不能再把两者相加。',
        '- 冠层浓度按站存叶＋茎干重加权；不包含根或果实。总N含Q，有机N浓度与总N浓度分开。',
        '- PG是模型实际冠层日光合碳输入；PG/LAI是冠层平均面积指标，不是LI-6400叶片净光合速率。光合氮因子另列。',
        '- 光合能力色带是日内实际调用范围，不是置信区间；调用均值没有按辐射或同化量加权。',
        '- 经典NNI为Corg/Ncrit，带宽状态z为(非储备浓度−Nmin)/(Ncrit−Nmin)；原始状态没有截成0—1。',
        '- 目标观测为实心点；7月17日等仅作诊断的叶茎N为空心点，未改目标函数。没有经审计的SE，因此不画误差棒。',
        '- 06采用原始采收阶梯／事件；06b只是单调Hermite视觉备选，不参与任何误差指标。',
        '- 缺失变量显示“未提供”，不以零替代。高氮相对差的分母为同水处理该变量全季绝对峰值；全零时相对量为NA。',
        '- 差异表是描述性比较，不强制N0<N1<N2<N3，也不构造日期生长护栏。','',
        '## 本批读图提示','']
    for key in ['Q_total','A_daily','canopy_Corg_pct','lai','PG_daily','yield_cumulative','photo_N_mean','growth_day']:
        q=summary[summary.variable.eq(key)].set_index('water_level')
        values='；'.join(f'{w}={q.loc[w,"high_N_max_range"]:.5g}' for w in ['W1','W2','W3'] if w in q.index)
        lines.append(f'- {V[key][0]}：N1—N3全季最大同日范围 {values}（{V[key][1]}）。')
    final=atlas.obs[atlas.obs.family.eq('FINAL_FRESH_YIELD')]
    lines+=['','### N3−N0最终鲜产差','', '| 水水平 | 模拟 (t/ha) | 实测 (t/ha) |','|---|---:|---:|']
    for water,g in final.groupby('water_level'):
        x=g.set_index('nitrogen_level')
        if {'N0','N3'}<=set(x.index):lines.append(f'| {water} | {(x.loc["N3","simulated"]-x.loc["N0","simulated"])/1000:.4f} | {(x.loc["N3","observed"]-x.loc["N0","observed"])/1000:.4f} |')
    lines+=['','## 分图入口','', '| 图页 | PNG预览 | 矢量PDF | 源数据 |','|---|---|---|---|']
    for fig in atlas.inventory:
        name=fig['name']
        lines.append(f'| {fig["title"]} | [打开](figures/{name}.png) | [PDF](figures/{name}.pdf) | [CSV](figures/{name}.source.csv) |')
    lines+=['','## 复用与来源','',
        '本图册使用明确指定的运行目录和处理映射，不自动寻找“最新”或“最佳”。生成过程不运行／修改DSSAT，不改变参数和观测。',
        '[变量目录](data/variable_catalogue.csv)｜[原始值与派生值](data/diagnostic_daily.csv)｜[同日差值](data/diagnostic_contrasts.csv)｜[差异汇总](data/diagnostic_separation_summary.csv)｜[来源与配置](data/source_manifest.json)。',
        '', '不同版本可对相同源目录重复使用同一入口，每次使用新输出目录，已有图册不会覆盖。'
        '缺R或P0Trace等可选输出时，相应图面留空并说明；核心PlantNIntegration与PlantCCash缺失时明确拒绝，不能拿其他模型结果拼补。']
    if reference_state:lines+=['','本次冻结了明确指定的参考配置，比较页只比较差异幅度；具体版本见reference_data/source_manifest.json，不据整包配置差异推断单一机制的贡献。']
    lines+=['','### 当前缺口与注记','']+[f'- {n}' for n in atlas.state['notes']]
    (out/'诊断图册_阅读说明与结果.md').write_text('\n'.join(lines)+'\n',encoding='utf8')

def render_frozen(out,profile):
    state=json.loads((out/'data/source_manifest.json').read_text(encoding='utf8'))
    reference_state=None;reference_summary=None
    if (out/'reference_data/source_manifest.json').exists():
        reference_state=json.loads((out/'reference_data/source_manifest.json').read_text(encoding='utf8'))
        reference_summary=pd.read_csv(out/'reference_data/diagnostic_separation_summary.csv')
    atlas=Atlas(out/'data',out/'figures',profile)
    try:
        atlas.overview()
        for name,title,fields,note in PLATES:
            if name == '01_vacuolar_equivalent' and set(POOL_CONCENTRATIONS).issubset(atlas.d):
                title = '等效“液泡”无机氮库的库存与浓度'
                fields = fields + POOL_CONCENTRATIONS
                note = '前三行为地面面积库存，后三行为库存除以叶、茎、根的支撑代理量。浓度单位以N计，支撑量为零时留空。'
            atlas.timeseries(name,title,fields,note)
        if 'Q_reference' in atlas.d:
            for name,title,fields,note in HOMEOSTASIS_PLATES:atlas.timeseries(name,title,fields,note)
        if 'chain_main_kinetic' in atlas.d:
            for name,title,fields,note in ASSIM_PLATES:atlas.timeseries(name,title,fields,note)
        atlas.yield_plate();atlas.yield_plate(smooth=True);atlas.dilution_curves();atlas.pool_composition();atlas.high_n_differences()
        if reference_summary is not None:atlas.overview('00b_reference_high_N','高氮处理差异：冻结对照与当前配置',reference_summary)
    finally:atlas.close()
    index(out,atlas,reference_state)
    try:commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[1],
                                       stderr=subprocess.DEVNULL,text=True).strip()
    except (subprocess.CalledProcessError,OSError):commit=None
    dump(out/'diagnostic_delivery_manifest.json',dict(source_commit=commit,case_dir=state['case_dir'],
        binary_sha256=state['binary_sha256'],figure_count=len(atlas.inventory),objective_rows=state['objective_rows'],
        additional_diagnostic_N_observations=state['additional_diagnostic_N_observations'],
        model_code_edited=False,model_executed=False,objectives_changed=False,diagnostic_only=True,
        source_files={str(p.relative_to(Path(__file__).parent)):sha(p) for p in Path(__file__).parent.glob('*.py')},
        atlas_sha256=sha(out/'figures/diagnostic_atlas.pdf'),figure_manifest_sha256=sha(out/'figures/figure_manifest.json')))
    print(json.dumps(dict(output=str(out),figures=len(atlas.inventory),rows=state['rows'],extra_diagnostic_N=state['additional_diagnostic_N_observations']),ensure_ascii=False))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--case-dir',type=Path);ap.add_argument('--metadata',type=Path)
    ap.add_argument('--out-dir',type=Path,required=True);ap.add_argument('--label')
    ap.add_argument('--render-only',action='store_true',help='Use the already frozen CSV bundle; figures/ must not exist')
    ap.add_argument('--profile',type=Path,default=Path(__file__).resolve().with_name('profile.json'))
    ap.add_argument('--extra-n-source',type=Path);ap.add_argument('--extra-n-unit',choices=['g/kg','percent'])
    ap.add_argument('--reference-case-dir',type=Path)
    observations=ap.add_mutually_exclusive_group()
    observations.add_argument('--comparison',type=Path,help='Use current matched comparison from this case')
    observations.add_argument('--simulation-only',action='store_true',help='Render native outputs without a comparison table')
    args=ap.parse_args();out=args.out_dir.resolve()
    if args.render_only:
        render_frozen(out,args.profile)
        return
    if args.case_dir is None or args.metadata is None or not args.label:ap.error('--case-dir, --metadata and --label are required when freezing data')
    if args.simulation_only and args.extra_n_source:ap.error('--simulation-only cannot overlay observations')
    out.mkdir(parents=True,exist_ok=False)
    state=freeze_bundle(args.case_dir,args.metadata,out/'data',args.label,args.profile,args.extra_n_source,args.extra_n_unit,
                        args.comparison,args.simulation_only)
    reference_state=None;reference_summary=None
    if args.reference_case_dir:
        reference_state=freeze_bundle(args.reference_case_dir,args.metadata,out/'reference_data','C4冻结参考',args.profile,
                                      args.extra_n_source,args.extra_n_unit,simulation_only=args.simulation_only)
        reference_summary=pd.read_csv(out/'reference_data/diagnostic_separation_summary.csv')
        genotype=[]
        for name in ['TMGRO048.CUL','TMGRO048.ECO','TMGRO048.SPE','SOIL.SOL']:
            left=args.case_dir/name;right=args.reference_case_dir/name
            genotype.append(dict(file=name,same=sha(left)==sha(right)))
        dump(out/'version_comparison_scope.json',dict(native_parameter_files=genotype,
            same_native_parameters=all(r['same'] for r in genotype),
            current_config=state['config'],reference_config=reference_state['config'],single_mechanism_causal_attribution=False))
    render_frozen(out,args.profile)

if __name__=='__main__':main()
