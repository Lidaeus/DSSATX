"""Prepare, execute and independently replay an isolated real 24x2 PEST-IES smoke."""
from pathlib import Path
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time

import numpy as np
import pandas as pd
import pyemu

from smoke_forward import dump, sha, evaluate
from run_stages import ENGINEERING

MAIN = Path('D:/Tomato_Cal')
CN = MAIN / 'subprojects/critical_n'
HERE = Path(__file__).resolve().parent
FIELDS = {'EM-FL': 48, 'FL-SH': 54, 'FL-SD': 60, 'LFMAX': 78, 'SLAVR': 84, 'PODUR': 120}
ACTIVE_N = ['q_no3_max', 'assim_no3_v', 'root_v', 'root_k', 'leaf_a', 'stem_a', 'photo_gamma', 'growth_tau']


def prepare(root):
    root.mkdir(parents=True, exist_ok=False)
    (root / 'bin').mkdir()
    engine = CN / 'reports/n_integration_stages_20261102/bin/dscsm048_4864_nintegration_p5_240ed59d.exe'
    shutil.copy2(engine, root / 'bin/dscsm048_p5.exe')
    pest = MAIN / 'pestpp-5.2.16-win/bin/pestpp-ies.exe'
    shutil.copy2(pest, root / 'bin/pestpp-ies.exe')
    shutil.copytree(CN / 'reports/n_integration_v2_readiness_20261102/baseline_verified/inputs_26SP', root / 'inputs')
    runtime = root / 'runtime'
    shutil.copytree(MAIN / 'src', runtime / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(HERE / 'smoke_forward.py', runtime / 'smoke_forward.py')
    shutil.copy2(HERE / 'calibration_smoke.py', runtime / 'calibration_smoke.py')
    catalog = CN / 'smoke_joint100x4_20261101/catalogs/26SP_observations.csv'
    shutil.copy2(catalog, root / 'observations.csv')
    obs = pd.read_csv(root / 'observations.csv').fillna('')
    if len(obs) != 612 or obs.obsnme.duplicated().any() or not obs.season_id.eq('26SP').all():
        raise ValueError('Frozen all12 objective identity')
    if not obs.dataset_role.eq('calibration').all() or not obs.execution_enabled.eq(True).all():
        raise ValueError('Inactive or noncalibration target')
    if obs[obs.date.eq('2026-07-17')].variable.isin(['LEAF_N_PCT', 'STEM_N_PCT']).any():
        raise ValueError('Excluded N observation leaked')
    sys.path.insert(0, str(runtime))
    from src.calibration.single_season_n import read_injected_parameters
    from src.common.param_registry import PHYSICAL_BOUNDS
    legacy = read_injected_parameters(root / 'inputs')
    parent_file = CN / 'smoke_joint100x4_20261101/data/parameter_registry/bounds_frozen/eggplant/functional_photo_joint73_smoke_20261101.csv'
    parent = pd.read_csv(parent_file).set_index('name')
    rows = []
    # Working domains are deliberately narrow engineering priors. They are
    # frozen before PEST reads them, not inferred as biological confidence.
    for name, value in ENGINEERING.items():
        active = name in ACTIVE_N
        low, high = (.75 * value, 1.25 * value) if active else (value, value)
        if name == 'growth_tau': low, high = 1., 3.
        if name == 'photo_gamma': low, high = .7, 1.3
        rows.append(dict(name=name, init=value, lower=low, upper=high,
                         status='active' if active else 'fixed', pargp='new_n',
                         location='NIntegration.nml', unit_role='engineering; see mechanism specification'))
    for name in FIELDS:
        value = legacy[name][0]
        low = max(float(parent.loc[name, 'lower']), .8 * value)
        high = min(float(parent.loc[name, 'upper']), 1.2 * value)
        if not PHYSICAL_BOUNDS[name][0] <= low <= value <= high <= PHYSICAL_BOUNDS[name][1]:
            raise ValueError('Native frozen/physical domain ' + name)
        rows.append(dict(name=name, init=value, lower=low, upper=high, status='active', pargp='native_cul',
                         location='TMGRO048.CUL:TM0008', unit_role='native CUL definition'))
    bounds = pd.DataFrame(rows)
    bounds['pest_name'] = [f'p{i:03}' for i in range(len(bounds))]
    (root / 'data/parameter_registry/bounds_frozen/eggplant').mkdir(parents=True)
    bounds_file = root / 'data/parameter_registry/bounds_frozen/eggplant/n4864_p5_smoke14.csv'
    bounds.to_csv(bounds_file, index=False)
    dump(bounds_file.with_suffix('.meta.json'), dict(status='frozen', purpose='user-requested engineering smoke only',
         active_parameters=14, parent_native_bounds=str(parent_file), parent_native_bounds_sha256=sha(parent_file),
         new_parameter_domains='local smoke priors; not publication-calibrated or inferred physical bounds',
         physiological_V15_borrowing=False, baseline='prior official4864 regression BASE, not V15 best'))
    protected = json.loads((CN / 'reports/n_integration_v2_readiness_20261102/baseline_verified/readiness_receipt.json').read_text())['protected_executables_before']
    if not all(sha(p) == h for p, h in protected.items()):
        raise ValueError('Protected executable changed before smoke')
    immutable = [root / 'bin/dscsm048_p5.exe', root / 'bin/pestpp-ies.exe', root / 'observations.csv',
                 bounds_file, bounds_file.with_suffix('.meta.json')]
    immutable += list((root / 'inputs').glob('*'))
    immutable += [p for p in runtime.rglob('*') if p.is_file()]
    d = dict(schema='n4864_stage5_smoke_v1', members=24, updates=2, workers=6, seed=20261102,
             required_mode={'ni_stage': 5, 'root_mode': 2},
             season='26SP', treatments=list(range(1, 13)), targets=612, active=14,
             bounds=str(bounds_file), binary=str(root / 'bin/dscsm048_p5.exe'), binary_sha256=sha(engine),
             observations=str(root / 'observations.csv'), inputs=str(root / 'inputs'), runtime=str(runtime),
             cultivar_fields=FIELDS, nitrogen_names=list(ENGINEERING),
             source_head=subprocess.check_output(['git', '-C', str(HERE.parents[1]), 'rev-parse', 'HEAD'], text=True).strip(),
             source_mechanism_commit='240ed59d4ad83469c522d321d1fd8be68060e931',
             engineering_only=True, V15_adopted=False, legacy_bug_policy='record and defer; never compensate residual',
             N_observation_limitation='unchanged native reduced organic N output operator; laboratory nitrate recovery unknown; not a validated total-N likelihood',
             protected=protected, frozen_hashes={str(p): sha(p) for p in immutable})
    dump(root / 'design.json', d)
    template = root / 'template'
    template.mkdir()
    (template / 'parameters.tpl').write_text('ptf ~\nname,value\n' + ''.join(f'{r.pest_name},~ {r.pest_name:18} ~\n' for r in bounds.itertuples()), encoding='ascii')
    pd.DataFrame({'name': bounds.pest_name, 'value': bounds.init}).to_csv(template / 'parameters.csv', index=False)
    (template / 'objectives.ins').write_text('pif ~\n' + ''.join(f'l1 w !{name}!\n' for name in obs.obsnme), encoding='ascii')
    pst = pyemu.Pst.from_io_files([str(template / 'parameters.tpl')], [str(template / 'parameters.csv')],
                                [str(template / 'objectives.ins')], [str(template / 'FormalObjectives.OUT')])
    pst.model_input_data.loc[:, 'pest_file'] = 'parameters.tpl'
    pst.model_input_data.loc[:, 'model_file'] = 'parameters.csv'
    pst.model_output_data.loc[:, 'pest_file'] = 'objectives.ins'
    pst.model_output_data.loc[:, 'model_file'] = 'FormalObjectives.OUT'
    for row in bounds.itertuples():
        pst.parameter_data.loc[row.pest_name, ['parval1', 'parlbnd', 'parubnd', 'pargp', 'partrans']] = [row.init, row.lower, row.upper, row.pargp, 'log' if row.status == 'active' else 'fixed']
    for row in obs.itertuples():
        pst.observation_data.loc[row.obsnme, ['obsval', 'weight', 'obgnme']] = [0., row.final_weight, row.family.lower()]
    pst.model_command = [f'"{sys.executable}" -X utf8 "{runtime / "smoke_forward.py"}" --design "{root / "design.json"}"']
    pst.control_data.noptmax = 2
    pst.control_data.phiredstp = 0.
    pst.control_data.nphinored = 10
    pst.control_data.nphistp = 10
    pst.control_data.relparstp = 0.
    pst.control_data.nrelpar = 10
    pst.pestpp_options = dict(ies_num_reals=24, ies_par_en='initial.par.csv', ies_no_noise=True,
                             ies_include_base=True, ies_save_binary=False, ies_reg_factor=0.,
                             ies_initial_lambda=10., ies_lambda_mults=[1.], ies_subset_size=24,
                             ies_bad_phi=1.e10, overdue_giveup_minutes=5., overdue_giveup_fac=20.)
    pst.write(str(template / 'smoke.pst'), version=2)
    # Explicit frozen local ensemble; no hidden feasibility rejection or repair.
    rng = np.random.default_rng(20261102)
    ensemble = pd.DataFrame(np.tile(bounds.init.to_numpy(), (24, 1)), columns=bounds.pest_name,
                            index=['base'] + [f'r{i:03}' for i in range(1, 24)])
    for row in bounds[bounds.status.eq('active')].itertuples():
        ensemble.loc[ensemble.index != 'base', row.pest_name] = rng.uniform(row.lower, row.upper, 23)
    ensemble.to_csv(template / 'initial.par.csv', index_label='real_name')
    dump(root / 'execution_status.json', dict(stage='prepared', completed=False))
    return d


def preflight(root, d):
    base = root / 'template/parameters.csv'
    first = evaluate(root / 'design.json', base, root / 'preflight/base')
    again = evaluate(root / 'design.json', base, root / 'preflight/repeat')
    if first['phi'] != again['phi']:
        raise ValueError('Deterministic repeat changed Phi')
    # Perturb each active field independently before launching IES. A change
    # must reach the native process, not just the written input file.
    bound = pd.read_csv(d['bounds'])
    baseline = pd.read_csv(Path(first['trial']) / 'PlantNIntegration.csv')
    baseline_comp = pd.read_csv(Path(first['trial']) / 'comparison.csv')
    probes = []
    for row in bound[bound.status.eq('active')].itertuples():
        out = root / 'preflight' / row.pest_name
        out.mkdir()
        frame = pd.read_csv(base)
        value = row.lower if abs(row.init - row.lower) > abs(row.upper - row.init) else row.upper
        frame.loc[frame.name.eq(row.pest_name), 'value'] = value
        frame.to_csv(out / 'parameters.csv', index=False)
        result = evaluate(root / 'design.json', out / 'parameters.csv', out)
        native = pd.read_csv(Path(result['trial']) / 'PlantNIntegration.csv')
        changed = float(np.max(np.abs(native.iloc[:, 3:].to_numpy() - baseline.iloc[:, 3:].to_numpy())))
        comp = pd.read_csv(Path(result['trial']) / 'comparison.csv')
        effect = float((comp.simulated - baseline_comp.simulated).abs().max())
        if changed <= 1e-12:
            raise ValueError('Inert parameter in native mechanism: ' + row.name)
        probes.append(dict(name=row.name, requested=value, native_state_max_change=changed,
                           objective_max_change=effect, phi=result['phi']))
        print('probe', row.name, 'native_change', changed, 'objective_change', effect, flush=True)
    pd.DataFrame(probes).to_csv(root / 'parameter_wiring_preflight.csv', index=False)
    dump(root / 'preflight_receipt.json', dict(passed=True, deterministic_phi=first['phi'],
                                             active_probes=len(probes), no_rejected_or_imputed_members=True))


def launch(root, d):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    master = root / 'manager'
    shutil.copytree(root / 'template', master)
    workers = []
    for i in range(d['workers']):
        path = root / '_agents' / f'agent_{i + 1:02}'
        shutil.copytree(root / 'template', path)
        workers.append(path)
    children, streams = [], []
    env = os.environ.copy()
    for key in ['DSSAT_CUSTOM_EXE', 'DSSAT_N_CONFIG', 'DSSAT_P0_TRACE']:
        env.pop(key, None)
    started = time.monotonic()
    try:
        log = (master / 'pest_stdout.log').open('wb'); streams.append(log)
        cmd = [str(root / 'bin/pestpp-ies.exe'), 'smoke.pst', '/h', f':{port}']
        process = subprocess.Popen(cmd, cwd=master, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        children.append(process)
        for path in workers:
            log = (path / 'pest_stdout.log').open('wb'); streams.append(log)
            p = subprocess.Popen([str(root / 'bin/pestpp-ies.exe'), 'smoke.pst', '/h', f'127.0.0.1:{port}'],
                                 cwd=path, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            children.append(p)
        dump(root / 'execution_status.json', dict(stage='ies_running', completed=False, port=port,
                                                  owned_pids=[p.pid for p in children], workers=len(workers)))
        while process.poll() is None:
            if time.monotonic() - started > 3600:
                raise TimeoutError('Owned PEST manager exceeded one-hour smoke limit')
            time.sleep(1)
        if process.returncode:
            raise RuntimeError(f'PEST-IES manager returned {process.returncode}; inspect manager/pest_stdout.log')
        print('PEST manager normal exit', flush=True)
    finally:
        for p in children:
            if p.poll() is None:
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    subprocess.run(['taskkill', '/PID', str(p.pid), '/T', '/F'], capture_output=True)
        for stream in streams:
            stream.close()


def finalize(root, d):
    manager = root / 'manager'
    # Presence of an ensemble alone is insufficient: require both updates
    # in actual Phi history and finite complete final member objectives.
    phi = pd.read_csv(manager / 'smoke.phi.actual.csv')
    if int(phi['iteration'].max()) != 2:
        raise RuntimeError('PEST did not complete the requested two updates')
    final_obs = pd.read_csv(manager / 'smoke.2.obs.csv', index_col=0)
    if len(final_obs) != 24 or not np.isfinite(final_obs.to_numpy()).all():
        raise RuntimeError('Final ensemble lost members/nonfinite objectives')
    all_trials = list((root / 'preflight').glob('*/native_trials/*/receipt.json'))
    all_trials += list((root / '_agents').glob('*/native_trials/*/receipt.json'))
    all_trials += list(manager.glob('native_trials/*/receipt.json'))
    receipts = [json.loads(p.read_text()) for p in all_trials]
    successful = [x for x in receipts if x['success']]
    pest_receipts = [x for x in successful if '/preflight/' not in x['trial'].replace('\\', '/')]
    if not pest_receipts:
        raise RuntimeError('No real native PEST evaluation')
    best = min(pest_receipts, key=lambda x: x['phi'])
    bounds = pd.read_csv(d['bounds'])
    best_values = best['parameters']
    replay = root / 'selected_deterministic'
    replay.mkdir(exist_ok=True)
    pd.DataFrame([(r.pest_name, best_values[r.name]) for r in bounds.itertuples()], columns=['name', 'value']).to_csv(replay / 'parameters.csv', index=False)
    pd.DataFrame(best_values.items(), columns=['name', 'value']).to_csv(root / 'best_parameters.csv', index=False)
    result = evaluate(root / 'design.json', replay / 'parameters.csv', replay)
    if not np.isclose(result['phi'], best['phi'], atol=1e-10, rtol=1e-12):
        raise RuntimeError('Selected native replay differs from IES evaluation')
    comparison = pd.read_csv(Path(result['trial']) / 'comparison.csv')
    comparison.to_csv(root / 'best_comparison.csv', index=False)
    metrics = []
    for family, q in comparison.groupby('family'):
        error = q.simulated - q.observed
        rmse = float(np.sqrt(np.mean(error ** 2)))
        denominator = float(np.square(q.observed - q.observed.mean()).sum())
        willmott = float(np.square(np.abs(q.simulated - q.observed.mean()) + np.abs(q.observed - q.observed.mean())).sum())
        metrics.append(dict(family=family, variable=q.variable.iloc[0], n=len(q), unit=q.unit.iloc[0],
                            rmse=rmse, nrmse_pct=100 * rmse / q.observed.mean(), bias=float(error.mean()),
                            nse=1 - float(np.square(error).sum()) / denominator if denominator else None,
                            d_index=1 - float(np.square(error).sum()) / willmott if willmott else None,
                            phi=float(q.phi_contribution.sum())))
    pd.DataFrame(metrics).to_csv(root / 'best_metrics.csv', index=False)
    replay_receipts = [json.loads(p.read_text()) for p in replay.glob('native_trials/*/receipt.json')]
    all_receipts = receipts + replay_receipts
    calls = pd.DataFrame([dict(trial=x['trial'], success=x['success'], phi=x.get('phi'),
                               error=x.get('error', ''), elapsed_seconds=x['elapsed_seconds']) for x in all_receipts])
    calls.to_csv(root / 'all_evaluation_audit.csv', index=False)
    base_phi = json.loads((root / 'preflight_receipt.json').read_text())['deterministic_phi']
    for path, h in d['frozen_hashes'].items():
        if sha(path) != h: raise RuntimeError('Frozen file changed after IES: ' + path)
    if not all(sha(p) == h for p, h in d['protected'].items()):
        raise RuntimeError('Protected executable changed')
    report = dict(completed=True, completed_updates=2, final_members=24, active_parameters=14,
                  workers=6, binary_sha256=d['binary_sha256'], initial_center_phi=base_phi,
                  best_actual_evaluated_phi=best['phi'], replay_phi=result['phi'],
                  improvement_pct=100 * (base_phi - best['phi']) / base_phi,
                  evaluations=len(all_receipts), preflight_evaluations=len(receipts) - len(pest_receipts),
                  independent_replays=len(replay_receipts), pest_native_evaluations=len(pest_receipts),
                  failures=sum(not x['success'] for x in all_receipts), selected_trial=result['trial'],
                  new_N_budget=result['budget'], protected_unchanged=True, scientific_validation=False,
                  limitations=[d['N_observation_limitation'], 'local engineering priors, 24x2 is a smoke, not a final joint calibration',
                               'original organic-N/C/harvest bugs remain deferred; no residual masking',
                               'no controlled-event validation or publication inference'])
    dump(root / 'final_audit.json', report)
    table = pd.DataFrame(metrics)[['family', 'n', 'rmse', 'nrmse_pct', 'bias', 'phi']]
    # Markdown delivery does not require the optional pandas/tabulate package.
    markdown_table = '| ' + ' | '.join(table.columns) + ' |\n'
    markdown_table += '| ' + ' | '.join(['---'] * len(table.columns)) + ' |\n'
    for row in table.itertuples(index=False, name=None):
        markdown_table += '| ' + ' | '.join(f'{v:.4g}' if isinstance(v, (float, np.floating)) else str(v) for v in row) + ' |\n'
    text = ['# DSSAT 4.8.6.4 阶段5小型联合率定 smoke 测试', '',
            '实际运行 PEST++ IES：24成员 × 2次更新，6个并行工作进程。26春12处理，612个既有直接观测目标，14个活动参数（8个新氮参数＋6个原生生长／物候参数）。', '',
            f'执行体：`{d["binary"]}`；SHA-256：`{d["binary_sha256"]}`。每次原生运行显式指定独立 NIntegration.nml，阶段5、新根系R2均启用。', '',
            f'中心 Phi={base_phi:.8f}；实际评估的最佳 Phi={best["phi"]:.8f}；独立重跑 Phi={result["phi"]:.8f}，相对中心下降 {report["improvement_pct"]:.2f}%。', '',
            f'原生评估共{len(all_receipts)}次（预检{report["preflight_evaluations"]}次、PEST实际调度{len(pest_receipts)}次、独立重跑{len(replay_receipts)}次），失败{report["failures"]}次。最终24成员完整，实际Phi记录到第2轮。每轮默认测试3种步长，168次PEST调度不等于168个独立后验样本。', '',
            markdown_table, '',
            '所有成功候选均核验新无机氮库独立收支、库容、层吸收向植株交接、完整处理日覆盖。原生有机氮残差与生长碳超支单列，继续按照用户要求列账待统一处理；不把新库守恒等同于全模型守恒。', '',
            f'最佳重跑预算：`{json.dumps(result["budget"], ensure_ascii=False)}`', '',
            '本次未借鉴V15 S1机制或最佳参数，未修改官方／正式自定义执行体、共享输入或历史批次。原生参数从已冻结4.8.6.4回归BASE读取；新参数以阶段5工程值为中心；边界、目标、执行体、运行代码均在批次内冻结并核验哈希。', '',
            '这是工程smoke，不是正式最优参数或机制有效性的证明。茎叶氮暂沿用现有原生LN%D/SN%D输出算子；新无机氮已单列，试验消解对硝态氮的回收口径尚未核实，因此不能把本次氮拟合解释为已验证的总氮拟合。其余既有目标权重和算子未改动。', '',
            '下一步：先依据失败谱、参数接线响应与边界命中诊断处理工程问题；统一核算已列账原生bug并核对氮观测算子；再开展受控事件／消融，最后设计正式率定。未新增季节或日期生长护栏，未引入SPAD／气体交换等替代目标。']
    (root / 'smoke测试结果报告.md').write_text('\n'.join(text) + '\n', encoding='utf8')
    dump(root / 'execution_status.json', dict(stage='completed', completed=True, updates=2, members=24))
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--finalize-only', action='store_true', help='audit completed IES; never relaunch PEST')
    a = p.parse_args()
    root = a.out.resolve()
    try:
        if a.resume or a.finalize_only:
            d = json.loads((root / 'design.json').read_text())
        else:
            d = prepare(root)
            preflight(root, d)
        if not a.finalize_only:
            launch(root, d)
        finalize(root, d)
    except BaseException as e:
        if root.exists(): dump(root / 'execution_status.json', dict(stage='failed', completed=False, error=str(e)))
        raise


if __name__ == '__main__':
    main()
