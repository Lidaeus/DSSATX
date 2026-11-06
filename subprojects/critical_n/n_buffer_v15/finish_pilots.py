"""Receipt-backed selection, independent replays and complete audit after both pilots.

Can wait on this already-running one-off calculation; no scheduling or external messages.
"""
from pathlib import Path
import argparse,json,time,hashlib,subprocess,sys,importlib.util
import pandas as pd
import numpy as np
V=Path(__file__).resolve().parent;ROOT=V.parent
spec=importlib.util.spec_from_file_location('counterfactual',ROOT/'reports/growth_causal_audit_20261023/run_counterfactuals.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def dump(p,x):m.dump(p,x)

def audit(plan):
    run=V/'runs'/plan['run_id'];design=json.loads(Path(plan['design']).read_text());b=pd.read_csv(design['search_bounds']);active=b[b.status=='active']
    calls=[];valid=[]
    for p in run.rglob('receipt.json'):
        if 'selected_deterministic' in p.parts:continue
        q=json.loads(p.read_text());success=q.get('success',False)
        calls.append(dict(receipt=str(p),success=success,phi=q.get('phi'),error_type=q.get('error_type',''),error=q.get('error',''),elapsed_seconds=q.get('elapsed_seconds'),trial=q.get('trial','')))
        if success:
            assert q['complete_targets']==1079 and q['binary_sha256']==design['binary_sha256']
            assert all(z['passed']and z['nominal_capacity_passed']for z in q['physics'].values())
            valid.append(q)
    pd.DataFrame(calls).to_csv(run/'all_evaluation_audit.csv',index=False)
    failures=pd.DataFrame(calls);failures=failures[~failures.success]
    if len(failures):failures.groupby(['error_type','error'],dropna=False).size().reset_index(name='count').to_csv(run/'failure_spectrum.csv',index=False)
    best=min(valid,key=lambda q:q['phi'])
    pd.DataFrame(best['parameters'].items(),columns=['name','value']).to_csv(run/'best_parameters.csv',index=False,float_format='%.17g')
    out=run/'selected_deterministic'
    if not(out/'last_success.json').exists():
        cp=subprocess.run([sys.executable,'-X','utf8',str(V/'protocol.py'),'--design',plan['design'],'--param-csv',str(run/'best_parameters.csv'),'--output-dir',str(out)],cwd=V,capture_output=True,text=True,timeout=600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (run/'selected_replay.log').write_text(cp.stdout+cp.stderr,encoding='utf8');assert cp.returncode==0,cp.stdout[-1000:]+cp.stderr[-1000:]
    replay=json.loads((out/'last_success.json').read_text());assert replay['success']and np.isclose(replay['phi'],best['phi'],rtol=1e-9,atol=1e-8)
    stages=[]
    for f in sorted((run/'stages').glob('step_*/stage_receipt.json')):stages.append(json.loads(f.read_text()))
    terminal=pd.read_csv(run/f'checkpoints/iteration_{plan["iterations"]}.lineage.csv');assert len(terminal)==plan['members']
    states=[]
    for step in range(plan['iterations']+1):
        p=run/f'checkpoints/iteration_{step}.par.csv';q=pd.read_csv(p,index_col=0);columns=active.name.str.lower().tolist();matrix=q[columns].to_numpy(float)
        matrix=(matrix-matrix.mean(axis=0))/(active.upper-active.lower).to_numpy()
        singular=np.linalg.svd(matrix,compute_uv=False)
        states.append(dict(iteration=step,members=len(q),unique_parameter_rows=int(len(q.drop_duplicates())),normalized_rank=int(np.linalg.matrix_rank(matrix)),singular_max=float(singular[0]),singular_min=float(singular[-1]),variance_trace=float(np.sum(singular**2)/max(1,len(q)-1)),held=int(pd.read_csv(run/f'checkpoints/iteration_{step}.lineage.csv').held.sum())))
    pd.DataFrame(states).to_csv(run/'ensemble_quality.csv',index=False)
    initial=pd.read_csv(run/'checkpoints/iteration_0.lineage.csv')
    result=dict(run_id=plan['run_id'],mechanism=plan['name'],success=True,all_calls=len(calls),successful_calls=len(valid),failed_calls=len(failures),initial_phi_min=float(initial.phi.min()),initial_phi_mean=float(initial.phi.mean()),terminal_phi_min=float(terminal.phi.min()),terminal_phi_mean=float(terminal.phi.mean()),best_all_evaluated_phi=float(best['phi']),best_source_trial=best['trial'],selected_replay_trial=replay['trial'],selected_replay_phi=replay['phi'],binary_sha256=design['binary_sha256'],parameter_sha256=m.sha(run/'best_parameters.csv'),physics=replay['physics'],stages=stages,ensemble=states,selection_rule='Minimum complete current-objective Phi across all genuinely evaluated feasible trials, followed by independent deterministic replay; no seasonal/date/valley guardrails',independent_validation=False,original_baseline_replaced=False)
    dump(run/'final_audit.json',result);return result

def export(reports,output_override=None):
    out=Path(output_override)if output_override is not None else V/'evidence/final';out.mkdir(parents=True,exist_ok=True)
    baseline=json.loads((ROOT/'reports/leaf_n_valley_audit_20261028/reruns/latest_A/last_success.json').read_text())
    cases=[('V14_baseline',Path(baseline['trial']))]+[(r['mechanism'],Path(r['selected_replay_trial']))for r in reports]
    metrics=[];pairs=[];daily=[]
    for label,trial in cases:
        q=pd.read_csv(trial/'comparison.csv');x=m.metrics(q);x['model']=label;metrics.append(x);q['model']=label;pairs.append(q)
        for season in ['26SP','25SP']:
            pn=m.native(trial/season/'PlantN.OUT').reset_index();pg=m.native(trial/season/'PlantGro.OUT').reset_index()
            md=pd.read_csv(trial/season/'treatment_metadata.csv').rename(columns={'treatment':'trno'})
            pn=pn.merge(pg[['trno','date','DAP','LAID','LWAD','SWAD','L#SD']],on=['trno','date'],validate='one_to_one',suffixes=('','_g'))
            pn['dap']=pn['DAP_g']if 'DAP_g'in pn else pn['DAP'];pn['leaf_n_pct']=pn['LN%D'];pn['season_id']=season;pn['model']=label
            pn=pn.merge(md,on='trno',validate='many_to_one');daily.append(pn)
    pd.concat(metrics,ignore_index=True).to_csv(out/'metrics.csv',index=False)
    pd.concat(pairs,ignore_index=True).to_csv(out/'comparison.csv',index=False)
    pd.concat(daily,ignore_index=True).to_csv(out/'daily_leafN.csv',index=False)
    m.dump(out/'data_manifest.json',dict(data_status='actual_deterministic_diagnostic',independent_validation=False,artifacts=[dict(path=n,sha256=m.sha(out/n))for n in ['metrics.csv','comparison.csv','daily_leafN.csv']]))
    return out

def report(reports,out):
    lines=['# V15 机制修正与两季小规模联合率定结果','', '这是实际计算后的最终报告。沿用1079项目标、原冻结边界和观测排除规则；没有分季/关键日期生长护栏或叶氮单调约束。V14基准保留。','',
      '阶段1–4的完整实施与限制见上一级 `阶段1至4实施审查.md`。移动库容只完成受控子系统收敛测试，未冒充整个DSSAT子步算法，也未将不完整预测扩容纳入率定。','',
      '| 小试 | 最佳真实可行 Φ | 终态检查点最低 Φ | 有效评估/失败 |','|---|---:|---:|---:|']
    for r in reports:lines.append(f'| {r["mechanism"]} | {r["selected_replay_phi"]:.6f} | {r["terminal_phi_min"]:.6f} | {r["successful_calls"]}/{r["failed_calls"]} |')
    lines+=['','原V14 A同口径Φ=126.220740；仅接口修复沿用旧参数为127.715672；组合机制沿用旧参数为137.004753。新表为重新率定后、独立确定性复核的结果。最佳点从所有完整可行的真实评估中选择，可能来自预检或PEST候选，不等同于终态集合最低点。','', '## 集合与失败','']
    for r in reports:
        lines.append(f'### {r["mechanism"]}')
        for s in r['stages']:lines.append(f'- 更新{s["step"]}：原始PEST存活{s["raw_pest_survivors"]}，检查点{s["checkpoint_members"]}，保持前一真实配对{s["held"]}。')
        e=r['ensemble'][-1];lines.append(f'- 终态唯一参数向量{e["unique_parameter_rows"]}，归一化秩{e["normalized_rank"]}。保留100成员不代表100个独立新更新或后验样本；完整方差和奇异值见运行目录ensemble_quality.csv。')
    lines+=['','## 各变量拟合','', 'RMSE按变量原单位；R²为相关系数平方。NSE对小实测方差敏感，未定义时记为“—”。完整逐点对账见comparison.csv；同一数据用于率定，不能称为独立验证。','', '| 模型 | 季节 | 指标 | n | RMSE | R² | NSE | d |','|---|---|---|---:|---:|---:|---:|---:|']
    metrics=pd.read_csv(out/'metrics.csv');wanted=['FINAL_FRESH_YIELD','HARVEST_FRESH_EVENT','HARVEST_FRESH_CUMULATIVE_EARLY','CANOPY_LAI','LEAF_DRY_MASS','STEM_DRY_MASS','HEIGHT','LEAF_N_CONCENTRATION','STEM_N_CONCENTRATION','FRUIT_N_CONCENTRATION']
    def fmt(x):return '—'if pd.isna(x)else f'{x:.4f}'
    for row in metrics[metrics.family.isin(wanted)].itertuples():lines.append(f'| {row.model} | {row.season} | {row.family} | {row.n_matched} | {fmt(row.RMSE)} | {fmt(row.R2)} | {fmt(row.NSE)} | {fmt(row.d)} |')
    best=min(reports,key=lambda r:r['selected_replay_phi'])
    decision=dict(best_new_candidate=best['run_id'],new_candidate_phi=best['selected_replay_phi'],baseline_phi=126.22073951970546,lower_than_preserved_baseline=best['selected_replay_phi']<126.22073951970546,production_baseline_replaced=False,requires_interpretation='Full-fit comparison is calibration evidence, not proof of early valley biology or chemical N-pool identity.')
    dump(out/'candidate_recommendation.json',decision)
    lines+=['','## 保留与后续','',f'两组新候选中完整目标最低者为 `{best["run_id"]}`。其最佳参数、独立复跑及完整物理检查保存在相应运行目录，V14正式执行体和原最佳参数未覆盖。', '','当前没有波谷期叶氮、叶序/叶面积实测；不以局部曲线更平滑作为优胜依据。下一步仍是联立存活干重—储备接受—根/土壤氮—同化碳退款，再研究是否引入真正的全模型子步；氮形态缺乏实测时不任意改变非蛋白储备质量系数。']
    (out/'最终实施与率定报告.md').write_text('\n'.join(lines),encoding='utf8')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--wait',action='store_true');a=ap.parse_args()
    plans=json.loads((V/'configs/registered_pilots.json').read_text())['pilots']
    dump(V/'evidence/finalization_status.json',dict(stage='waiting_for_pilots',one_off=True))
    try:
        while True:
            states=[json.loads((V/'runs'/p['run_id']/'status.json').read_text())for p in plans]
            if all(s['stage']=='ies_completed'for s in states):break
            if any(s['stage']in ['ies_failed','preflight_budget_exhausted']for s in states):raise RuntimeError('Pilot stopped; preserve failure evidence and repair before continuation: '+str(states))
            if not a.wait:raise RuntimeError('Pilots are still running')
            time.sleep(10)
        dump(V/'evidence/finalization_status.json',dict(stage='receipt_audit_and_replay'))
        reports=[audit(p)for p in plans];out=export(reports);report(reports,out)
        dump(V/'evidence/final/pilot_audits.json',reports)
        # R renderer consumes only frozen exported tables.
        cp=subprocess.run(['C:/Program Files/R/R-4.5.2/bin/Rscript.exe',str(V/'render_final.R'),str(out)],cwd=V,capture_output=True,text=True,timeout=240)
        (out/'R_render.log').write_text(cp.stdout+cp.stderr,encoding='utf8');assert cp.returncode==0,cp.stderr
        dump(V/'evidence/finalization_status.json',dict(stage='complete',report=str(out/'最终实施与率定报告.md'),no_production_overwrite=True))
        print('FINAL AUDIT COMPLETE',[(r['mechanism'],r['selected_replay_phi'])for r in reports],flush=True)
    except Exception as exc:
        dump(V/'evidence/finalization_status.json',dict(stage='failed',error=str(exc),no_imputation=True));raise
if __name__=='__main__':main()
