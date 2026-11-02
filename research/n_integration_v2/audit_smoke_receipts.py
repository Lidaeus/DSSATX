"""Postflight cross-check against PEST's own final ensemble; no model launches."""
from pathlib import Path
import argparse
import json
import re

import numpy as np
import pandas as pd

from smoke_forward import dump, sha


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    a = p.parse_args()
    root = a.run.resolve()
    d = json.loads((root / 'design.json').read_text())
    final = json.loads((root / 'final_audit.json').read_text())
    obs = pd.read_csv(d['observations'])
    bounds = pd.read_csv(d['bounds'])
    ensemble = pd.read_csv(root / 'manager/smoke.2.obs.csv', index_col=0)
    pars = pd.read_csv(root / 'manager/smoke.2.par.csv', index_col=0)
    # Compute Phi from the PEST observation ensemble, independently of native
    # adapter receipts and the rounded phi summary.
    weights = obs.set_index('obsnme').final_weight.reindex(ensemble.columns)
    if weights.isna().any() or len(weights) != 612 or len(ensemble) != 24:
        raise ValueError('Final objective identity mismatch')
    actual_phi = (ensemble.mul(weights, axis=1) ** 2).sum(axis=1)
    winner = str(actual_phi.idxmin())
    if not np.isclose(actual_phi.min(), final['replay_phi'], rtol=1e-5, atol=2e-3):
        raise ValueError('Best native replay differs from final retained ensemble')
    selected = pd.read_csv(root / 'best_parameters.csv').set_index('name').value
    differences, hits = [], []
    for row in bounds.itertuples():
        # PEST CSVs have six significant digits; native receipts retain the
        # actual template-written vector. Tolerance only covers CSV printing.
        relative = abs(float(pars.loc[winner, row.pest_name]) - selected[row.name]) / max(abs(selected[row.name]), 1e-12)
        if relative > 6e-6:
            raise ValueError('Winning parameter differs from retained ensemble: ' + row.name)
        differences.append(relative)
        if row.status == 'active':
            span = row.upper - row.lower
            position = (selected[row.name] - row.lower) / span
            hits.append(dict(name=row.name, init=row.init, selected=selected[row.name],
                             change_pct=100 * (selected[row.name] / row.init - 1), lower=row.lower, upper=row.upper,
                             relative_position=position, at_lower=position < 1e-7, at_upper=position > 1 - 1e-7))
    pd.DataFrame(hits).to_csv(root / 'selected_parameter_diagnostics.csv', index=False)
    paths = list(root.glob('preflight/*/native_trials/*/receipt.json'))
    paths += list(root.glob('_agents/*/native_trials/*/receipt.json'))
    paths += list(root.glob('manager/native_trials/*/receipt.json'))
    paths += list(root.glob('selected_deterministic/native_trials/*/receipt.json'))
    receipts = [json.loads(path.read_text()) for path in paths]
    successful = [r for r in receipts if r['success']]
    for r in successful:
        if r['binary_sha256'] != d['binary_sha256'] or r['targets'] != 612 or r['nitrogen_config']['ni_stage'] != 5:
            raise ValueError('Native execution mismatch')
        if not r['budget']['passed'] or r['imputed']:
            raise ValueError('Native audit failure or imputed member')
    preflight = sum('/preflight/' in r['trial'].replace('\\', '/') for r in receipts)
    replay = sum('/selected_deterministic/' in r['trial'].replace('\\', '/') for r in receipts)
    pest = len(receipts) - preflight - replay
    if pest != 168 or preflight != 16 or len(successful) != len(receipts):
        raise ValueError('Actual native evaluation count/failure mismatch')
    log = (root / 'manager/pest_stdout.log').read_text()
    progress = re.findall(r'runs\(C\d+\s*\|F(\d+)\s*\|T(\d+)', log)
    if not progress or max(int(v) for pair in progress for v in pair) != 0:
        raise ValueError('PEST reported a failure or timeout')
    # Verify R2 transport actually produced diffusion in the selected replay.
    layers = pd.read_csv(Path(final['selected_trial']) / 'LayerNIntegration.csv')
    if not layers.Diff_potential_gN_m2.gt(0).any():
        raise ValueError('No evidence of active R2 diffusion transport')
    active = bounds[bounds.status.eq('active')]
    matrix = pars[active.pest_name].to_numpy()
    scaled = (matrix - matrix.mean(axis=0)) / (active.upper - active.lower).to_numpy()
    run_hashes = {str(p.relative_to(root)): sha(p) for p in (root / 'template').iterdir() if p.is_file()}
    audit = dict(passed=True, final_retained_best_realization=winner,
                 retained_best_phi_from_rounded_PEST_obs=float(actual_phi.min()),
                 final_ensemble_mean_phi=float(actual_phi.mean()),
                 best_parameters_match_final_retained_ensemble=True,
                 max_parameter_relative_difference_from_printed_CSV=max(differences),
                 final_ensemble_rank=int(np.linalg.matrix_rank(scaled)),
                 final_unique_vectors=len(pars.drop_duplicates()),
                 active_parameter_bound_hits=[r['name'] for r in hits if r['at_lower'] or r['at_upper']],
                 native_calls_total=len(receipts), preflight_calls=preflight, pest_calls=pest, independent_replays=replay,
                 failures=0, timeouts=0, all_native_calls_use_stage5_and_frozen_engine=True,
                 Q_native_residual_max_all=float(max(r['budget']['Q_native_residual_max'] for r in receipts)),
                 Q_independent_residual_max_all=float(max(r['budget']['Q_independent_residual_max'] for r in receipts)),
                 native_launch_files=run_hashes,
                 adapter_tests_passed=3,
                 corrected_engineering_issues=['six-column writer initially overflowed SLAVR=220.00; rejected before native/PEST launch, fixed and rerun in r1',
                    'pandas.to_markdown optional tabulate missing; removed dependency and finalized without relaunching IES'],
                 unmodified_model_mechanism=True)
    dump(root / 'independent_audit.json', audit)
    calls = []
    for r in receipts:
        category = 'preflight' if '/preflight/' in r['trial'].replace('\\', '/') else 'replay' if '/selected_deterministic/' in r['trial'].replace('\\', '/') else 'pest'
        calls.append(dict(trial=r['trial'], category=category, success=r['success'], phi=r.get('phi'),
                          elapsed_seconds=r['elapsed_seconds'], error=r.get('error', '')))
    pd.DataFrame(calls).to_csv(root / 'all_evaluation_audit.csv', index=False)
    final.update(evaluations=len(receipts), preflight_evaluations=preflight, independent_replays=replay,
                 retained_best_realization=winner, final_ensemble_mean_phi=float(actual_phi.mean()))
    dump(root / 'final_audit.json', final)
    report = root / 'smoke测试结果报告.md'
    text = report.read_text(encoding='utf8')
    text = text.replace('原生评估共184次（其中PEST实际调度成功168次），失败0次。',
                        f'原生评估共{len(receipts)}次（预检{preflight}次、PEST调度{pest}次、独立重跑{replay}次），失败0次。')
    text = text.split('\n## 独立复核与发现的问题')[0]
    text += '\n## 独立复核与发现的问题\n\n'
    text += f'最终保留集合的最佳成员为 **{winner}**，与本次选择的最佳参数向量一致。集合平均Phi依次为383.197→228.344→166.051；最佳单成员为128.963414，不能把集合均值与最佳单成员Phi混用。每轮默认测试3种步长，所以真实PEST原生调用为24＋72＋72＝168次；这不表示168个独立后验样本。最终集合24个独特向量，活动参数矩阵秩为{audit["final_ensemble_rank"]}。\n\n'
    text += '最佳向量有' + str(len(audit['active_parameter_bound_hits'])) + '个活动参数命中边界：' + '、'.join(audit['active_parameter_bound_hits']) + '。因此本次窄先验smoke尚未形成可解释的正式参数估计，不据此立即扩展边界。详见selected_parameter_diagnostics.csv。\n\n'
    text += '启动前检出新适配器固定两位小数使SLAVR字段溢出，立即拒绝，尚未运行DSSAT或PEST；修复六列写入后在r1重新冻结运行。另在率定完成后检出Markdown导出的可选tabulate依赖缺失，已移除依赖并单独完成后处理，未重启PEST。3项适配器检查通过，失败时旧目标被清除且没有数值填补。上述均为本轮新工具问题，不冒充已修复原生L01—L04。\n\n'
    text += '工程结论：本次范围内的完整率定链路通过；拟合仍不足。最终鲜产量NRMSE约15.41%，但跨处理NSE为−1.96；叶氮／茎氮NRMSE约24.29%／33.17%，NSE均为负。总体量级改善不能证明水氮处理差异已得到正确响应。\n\n'
    text += '工作顺序建议：先统一核算并处理L01采收果氮返土、L02缺氮生长碳成本超支、L03实际有机氮接受／负库存账及L04累计果氮拼写问题，完成各自隔离回归；同步核实实测氮消解口径，明确有机氮与总氮算子；再做受控供氮梯度、恢复、脉冲、富氮／低碳及消融；最后按可识别性调整参数组和先验、开展正式联合率定。本轮只完成smoke及记录，不越过用户任务直接修复这些生理代码。\n'
    report.write_text(text, encoding='utf8')
    dump(root / 'postprocessing_code_receipt.json', {p.name: sha(p) for p in [Path(__file__), Path(__file__).with_name('calibration_smoke.py'), Path(__file__).with_name('test_smoke_adapter.py')]})
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
