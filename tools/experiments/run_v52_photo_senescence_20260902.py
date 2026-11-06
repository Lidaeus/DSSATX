"""Paired deterministic photosynthesis/senescence probes; no IES or input edits."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.experiments.run_v50_mechanism_followup_20260902 import verify_seal, gradients, member
from tools.calibration.run_v49_mechanism_multiarm_20260902 import paths, logged, parse_outputs, dump, sha
from tools.analysis.evaluate_v49_mechanism_20260902 import evaluate, guard
from src.common.param_registry import PHYSICAL_BOUNDS
from src.dssat.array_expander import expand_senpor

OUT = ROOT / 'workspace/reports/v52_photo_senescence_20260902'
CONTROL = ROOT / 'workspace/reports/v50_mechanism_followup_20260902/control_A47'
OLD = ROOT / 'workspace/reports/v49_mechanism_20260902/A_ic_control/anchor'


def plan():
    base = member('A_ic_control', 3, 47)
    canopy = member('E_canopy', 2, 3)
    tasks = []
    for code, pgeff in [('p0', base['pgeff']), ('p025', .0589), ('p05', .0604)]:
        def add(name, changes):
            changes = {'pgeff': pgeff, **changes}
            tasks.append(dict(label=f'{code}_{name}', changes=changes, values={**base, **changes}))
        add('control', {})
        for senrte in [3.75, 4.5]:
            add(f'senrte{senrte:g}', {'senrte': senrte})
        # Existing expander changes BOTH late nodes. 1/3 reproduces node3=.12
        # while increasing node4 from .16 to .33. .16 is NOT a no-op anchor.
        for late, tag in [(1/3, '033'), (.5, '050'), (2/3, '067')]:
            add(f'senpor{tag}', {'senpor_late': late})
        add('senpor033_senrte375', {'senpor_late': 1/3, 'senrte': 3.75})
        # Genetic-only E2/3 transplant; ICNS remains A47 in BOTH seasons.
        add('canopyE', {k: canopy[k] for k in ['slavr', 'lfmax', 'frlff', 'senrte']})
    tasks.append(dict(label='p05_senday002', changes={'pgeff': .0604, 'senday': .02},
                      values={**base, 'pgeff': .0604, 'senday': .02}))
    for task in tasks:
        validate_task(task, base)
    return tasks


def validate_task(task, base):
    values, changes = task['values'], task['changes']
    allowed = {'pgeff', 'senrte', 'senpor_late', 'slavr', 'lfmax', 'frlff', 'senday'}
    assert set(changes) <= allowed
    assert set(values) == set(base) | set(changes)
    for k, v in values.items():
        if k not in changes:
            assert v == base[k], k
    for k, v in changes.items():
        lo, hi = (0., 1.) if k == 'senpor_late' else PHYSICAL_BOUNDS[k.upper()]
        assert lo <= v <= hi and np.isfinite(v), (k, v)
    for key in ['icns_25sp', 'icns_26sp']:
        assert values[key] == base[key] and .4 <= values[key] <= .8
    if 'senpor4' in task:
        assert 'senpor_late' not in values and .16 <= task['senpor4'] <= .20


def refine_plan():
    """Stage2: direct last-node probes, preserving all earlier SENPOR nodes."""
    base = member('A_ic_control', 3, 47)
    sources = [t for t in plan() if t['label'] in ['p0_control','p025_control','p05_control','p025_canopyE','p05_canopyE']]
    tasks = []
    for source in sources:
        for last in [.17,.18,.20]:
            task = {**source, 'label': f"fine_{source['label']}_last{last:.2f}", 'senpor4': last}
            validate_task(task,base)
            tasks.append(task)
    return tasks


def last_node_template(original, value):
    assert .16 <= value <= .20
    lines=original.splitlines(keepends=True)
    i=next(i for i,s in enumerate(lines) if 'SENPOR.........' in s)+1
    assert [float(lines[i][6*j:6*(j+1)]) for j in range(4)] == [0.,0.,.12,.16]
    lines[i]=lines[i][:18]+f'{value:6.3f}'+lines[i][24:]
    return ''.join(lines)


def audit_injection(dest, task):
    rows = []
    for season in ['25SP', '26SP']:
        folder = dest / '_seasons' / season
        ref = CONTROL / '_seasons' / season
        # Identical environmental inputs, including transformed initial N and soil.
        for old in ref.iterdir():
            # DSSATPRO.v48 stores absolute sandbox paths and must differ.
            if old.suffix.upper() in {'.TMX', '.TMA', '.TMT', '.SOL', '.WTH'} or old.name == 'DSSBatch.selected.v48':
                assert sha(old) == sha(folder / old.name), old.name
        original = (ref / 'TMGRO048.SPE').read_text().splitlines()
        actual = (folder / 'TMGRO048.SPE').read_text().splitlines()
        assert len(original) == len(actual)
        specs = {'pgeff': ('PGEFF SCV', 0, .00005),
                 'senrte': ('SENRTE,SENRT2', 0, .005),
                 'senday': ('SENRTE,SENRT2', 2, .005),
                 'frlff': ('WTFSD,PORPT,FRSTMF,FRLFF', 3, .005)}
        allowed_fields = set()
        for name, (marker, field, tolerance) in specs.items():
            index = next(i for i, s in enumerate(actual) if marker in s)
            value = float(actual[index][6*field:6*(field+1)])
            assert abs(value-task['values'][name]) <= tolerance + 1e-9, (name, value)
            rows.append(dict(season=season, name=name, requested=task['values'][name], actual=value))
            if name in task['changes']:
                allowed_fields.add((index, field))
        index = next(i for i, s in enumerate(actual) if 'SENPOR.........' in s) + 1
        expected = expand_senpor(task['values']['senpor_late']).y_values if 'senpor_late' in task['changes'] else (0., 0., .12, task.get('senpor4',.16))
        for field, request in enumerate(expected):
            value = float(actual[index][6*field:6*(field+1)])
            assert abs(value-request) <= .005000001
            rows.append(dict(season=season, name=f'SENPOR{field+1}', requested=request, actual=value))
            if 'senpor_late' in task['changes']:
                allowed_fields.add((index, field))
        if 'senpor4' in task:
            allowed_fields.add((index,3))
        if 'senpor_late' in task['changes']:
            # Existing expander reformats all eight cells: SENMAX values must
            # stay identical, while leading-zero/space formatting may differ.
            for field in range(4, 8):
                assert float(actual[index][6*field:6*(field+1)]) == float(original[index][6*field:6*(field+1)])
                allowed_fields.add((index, field))
        # Every SPE character outside the explicit modified 6-character cells is fixed.
        for i, (a, b) in enumerate(zip(original, actual)):
            assert len(a) == len(b), i
            for j, (ca, cb) in enumerate(zip(a, b)):
                assert ca == cb or (i, j//6) in allowed_fields, (i+1, j+1, ca, cb)
        # Cultivar change audit uses the original generated header, not guessed offsets.
        for filename, marker in [('TMGRO048.CUL', '@VAR#'), ('TMGRO048.ECO', '@ECO#')]:
            old, new = (ref / filename).read_text().splitlines(), (folder / filename).read_text().splitlines()
            assert len(old) == len(new)
            if 'slavr' in task['changes'] and filename.endswith('.CUL'):
                header = next(line for line in old if line.startswith(marker))
                fields = [header.index(k.upper()) for k in ['slavr', 'lfmax']]
                # Fixed-width fields end at header token ends, each width6.
                spans = [(i+len(k)-6, i+len(k)) for i,k in zip(fields, ['SLAVR', 'LFMAX'])]
                for a,b in zip(old,new):
                    if a == b:
                        continue
                    assert a.startswith('TM0008') and b.startswith('TM0008')
                    for j,(ca,cb) in enumerate(zip(a,b)):
                        assert ca == cb or any(lo <= j < hi for lo,hi in spans), (filename,j)
                    for k,(lo,hi) in zip(['slavr','lfmax'], spans):
                        value = float(b[lo:hi])
                        tolerance = .51 if k == 'slavr' else .0051
                        assert abs(value-task['values'][k]) <= tolerance, (k,value)
                        rows.append(dict(season=season, name=k, requested=task['values'][k], actual=value))
            else:
                assert old == new, filename
    pd.DataFrame(rows).to_csv(dest / 'injection_audit.csv', index=False)


def acceptance(fit, reference):
    a, b = [x.set_index(['season','variable']) for x in [fit,reference]]
    checks = []
    def check(label, passed, delta):
        checks.append(dict(check=label, passed=bool(passed), delta=float(delta)))
    for season in ['25SP','26SP']:
        gain = a.loc[(season,'FRESH_CUM'),'nse'] - b.loc[(season,'FRESH_CUM'),'nse']
        check(season+'_yield_NSE_gain_001', gain >= .01, gain)
        gain = a.loc[(season,'LAID'),'nse'] - b.loc[(season,'LAID'),'nse']
        check(season+'_LAI_NSE_loss_le003', gain >= -.03, gain)
        terminal = a.loc[(season,'FRESH_TERMINAL'),'rrmse_pct']
        change = terminal - b.loc[(season,'FRESH_TERMINAL'),'rrmse_pct']
        check(season+'_terminal_RRMSE_le25_nonworse', terminal <= 25 and change <= 0, change)
        for variable in ['LAID_early','LAID_late']:
            ratio = a.loc[(season,variable),'rmse']/b.loc[(season,variable),'rmse'] - 1
            check(season+'_'+variable+'_RMSE_increase_le10pct', ratio <= .1, ratio)
    for key in a.index:
        if key[1].startswith(('NRESPS_','WRESPS_')):
            ratio = a.loc[key,'rmse']/b.loc[key,'rmse'] - 1
            check('_'.join(key)+'_RMSE_increase_le10pct', ratio <= .1, ratio)
    return dict(passed=all(x['passed'] for x in checks), checks=checks)


def execute(task):
    dest = OUT / task['label']
    if dest.exists():
        assert json.loads((dest/'task.json').read_text()) == task
        if (dest/'completed.json').exists():
            return
        raise FileExistsError(f'Incomplete task requires inspection: {dest}')
    verify_seal()
    dest.mkdir(parents=True)
    dump(dest/'task.json', task)
    pd.DataFrame(task['values'].items(), columns=['name','value']).to_csv(dest/'params.csv',index=False)
    case, run, design, _ = paths('A_ic_control')
    command = [sys.executable, str(ROOT/'src/calibration/run_multiseason.py'), '--design', str(design),
            '--param-csv', str(dest/'params.csv'), '--prefix', task['label'], '--harvest-var','CHFPW',
            '--keep-nitrogen-outputs','--keep-soil-water','--observation-transform-config',
            str(run/f'{case}.observation_transforms.json')]
    if 'senpor4' not in task:
        logged(command, dest/'run.log', cwd=dest)
    else:
        source = ROOT/'data/templates/genotype/TMGRO048.SPE.base'
        isolated = dest/'senpor_last_node.SPE.base'
        isolated.write_text(last_node_template(source.read_text(),task['senpor4']),newline='')
        env = {**os.environ, 'PYTHONPATH':str(ROOT), 'PYTHONUTF8':'1',
               'DSSAT_CUSTOM_EXE':str(ROOT/'DSCSM048.EXE'), 'DSSAT_SPE_BASE':str(isolated)}
        with (dest/'run.log').open('w',encoding='utf-8') as stream:
            result = subprocess.run(command,cwd=dest,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=300)
        assert result.returncode == 0, dest/'run.log'
        dump(dest/'template_override.json',dict(source=str(source),source_sha256=sha(source),
               template_sha256=sha(isolated),field='SENPOR fourth node ONLY',value=task['senpor4']))
    finish(task)


def finish(task):
    dest = OUT/task['label']
    assert json.loads((dest/'task.json').read_text()) == task
    verify_seal()
    audit_injection(dest, task)
    case,run,_,_ = paths('A_ic_control')
    predicted = parse_outputs(run,case,dest)
    if task['label'] == 'p0_control':
        np.testing.assert_allclose(predicted, parse_outputs(run,case,CONTROL), rtol=0, atol=1e-9)
    predicted.to_csv(dest/'parsed_observations.csv')
    fit = evaluate('A_ic_control',dest,task['values'])
    gradients(dest)
    gates = acceptance(fit,pd.read_csv(CONTROL/'fit_metrics.csv'))
    previous_guard = guard(fit,pd.read_csv(OLD/'fit_metrics.csv'))
    dump(dest/'completed.json', dict(status='completed', observations=len(predicted),
          gates=gates, v48_guard=previous_guard, scientific_promotion=False,
          code_sha256=sha(Path(__file__))))
    print('COMPLETED '+task['label'],flush=True)


def summarize(tasks):
    rows, stages, all_checks = [], [], []
    for task in tasks:
        dest = OUT/task['label']
        if not (dest/'completed.json').exists():
            continue
        fit = pd.read_csv(dest/'fit_metrics.csv')
        completion = json.loads((dest/'completed.json').read_text())
        row = dict(label=task['label'], phi=pd.read_csv(dest/'objective_residuals.csv').actual_phi.sum(),
                   candidate_pass=completion['gates']['passed'], v48_scale_canopy_pass=completion['v48_guard']['scale_canopy_pass'])
        idx = fit.set_index(['season','variable'])
        for season in ['25SP','26SP']:
            for variable,col in [('FRESH_CUM','nse'),('DRY_CUM','nse'),('LAID','nse'),('FRESH_TERMINAL','rrmse_pct'),('LAID_early','rmse'),('LAID_late','rmse')]:
                row[f'{season}_{variable}_{col}'] = idx.loc[(season,variable),col]
        rows.append(row)
        for c in completion['gates']['checks']:
            all_checks.append(dict(label=task['label'],**c))
        stages.append(fit.assign(label=task['label']))
    pd.DataFrame(rows).to_csv(OUT/'summary.csv',index=False)
    pd.DataFrame(all_checks).to_csv(OUT/'guard_checks.csv',index=False)
    if stages:
        pd.concat(stages,ignore_index=True).to_csv(OUT/'all_fit_metrics.csv',index=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',action='store_true')
    p.add_argument('--finish',help='Analyze inspected, already complete model output without rerunning')
    p.add_argument('--refine',action='store_true',help='Stage2 small last-node probes after stage1 inspection')
    args=p.parse_args()
    tasks=plan()
    OUT.mkdir(parents=True,exist_ok=True)
    payload=dict(tasks=tasks, mode='deterministic_only', parameter_anchor='v49 A iteration3 member47',
       controlled_inputs='same A47 ICNS, soil, weather, observations, objectives and source/sink parameters',
       senpor_note='Existing expander: node3=.36*late and node4=late. Original .12,.16 retained for controls; never call .16 a no-op.',
       gates='Both fresh NSE +.01; each LAI NSE loss<=.03; terminal RRMSE<=25% and nonworse; early/late LAI and every N/W stratum RMSE increase<=10%; secondary v48 guard.',
       no_new_IES_bounds=True, source_exe_sha256=sha(ROOT/'DSCSM048.EXE'))
    path=OUT/'plan.json'
    if path.exists():
        assert json.loads(path.read_text()) == payload
    else:
        dump(path,payload)
    if args.refine:
        refinement = refine_plan()
        fine_payload = dict(tasks=refinement,stage='follow-up after stage1',
            question='Can small, last-node-only senescence preserve PGEFF yield gain?',
            source_plan_sha256=sha(path),acceptance='unchanged stage1 gates; adaptive in-sample exploration')
        fine_path=OUT/'refinement_plan.json'
        if fine_path.exists():
            assert json.loads(fine_path.read_text()) == fine_payload
        else:
            dump(fine_path,fine_payload)
        tasks += refinement
    if args.finish:
        finish(next(t for t in tasks if t['label']==args.finish))
    if args.run:
        for task in tasks:
            execute(task)
            summarize(tasks)
        verify_seal()
        dump(OUT/('refinement_status.json' if args.refine else 'status.json'),dict(status='completed',candidate_pairs=len(tasks),season_runs=2*len(tasks),
                                  script_sha256=sha(Path(__file__))))
    print(f'Validated {len(tasks)} paired tasks')


if __name__=='__main__':
    main()
