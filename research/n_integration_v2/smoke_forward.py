"""Frozen-input PEST adapter for the 4.8.6.4 stage-5 engineering smoke.

No physiological implementation is changed here. Failures never emit stale or
imputed objectives. Every native call has its own directory and budget receipt.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

import numpy as np
import pandas as pd


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.writing')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    tmp.replace(path)


def redirect(path, work):
    codes = {'SLD', 'CRD', 'TMD', 'WED'}
    found = set()
    lines = []
    for line in path.read_text().splitlines():
        if line[:3] in codes:
            found.add(line[:3])
            line = f'{line[:3]} {str(work)[:2]} {str(work)[2:]}'
        lines.append(line)
    if found != codes:
        raise ValueError('Incomplete native path isolation')
    path.write_text('\n'.join(lines) + '\n', encoding='ascii')


def inject_cultivar(work, values, fields):
    path = work / 'TMGRO048.CUL'
    lines = path.read_text().splitlines()
    positions = [i for i, line in enumerate(lines) if line.startswith('TM0008')]
    if len(positions) != 1:
        raise ValueError('Unique TM0008 cultivar required')
    i = positions[0]
    actual = {}
    for name, start in fields.items():
        value = values[name]
        # A decimal point is compulsory: native F6.0 also accepts integers,
        # but implicit decimal scaling differs in other cultivar readers.
        token, resolution = None, None
        for decimals in range(3, -1, -1):
            number = f'{value:.{decimals}f}'
            if decimals == 0:
                number += '.'
            if len(number) <= 5:
                token, resolution = ' ' + number.rjust(5), 10. ** (-decimals)
                break
        if token is None or len(token) != 6:
            raise ValueError('Cultivar six-column overflow: ' + name)
        lines[i] = lines[i][:start] + token + lines[i][start + 6:]
        actual[name] = float(lines[i][start:start + 6])
        if abs(actual[name] - value) > .5 * resolution + 1e-10:
            raise ValueError('Native injection error: ' + name)
    path.write_text('\n'.join(lines) + '\n', encoding='ascii')
    return actual


def extract(work, catalog, runtime):
    sys.path.insert(0, str(runtime))
    from src.calibration.single_season_n import extract_observations
    ordinary = catalog[catalog.variable != 'ADAP']
    records = extract_observations(work, ordinary)
    header, anthesis = None, {}
    for line in (work / 'Evaluate.OUT').read_text().splitlines():
        if line.startswith('@RUN'):
            header = line.lstrip('@').split()
        elif header and line.split() and line.split()[0].isdigit():
            tokens = line.split()
            if len(tokens) != len(header):
                raise ValueError('Malformed evaluation row')
            row = dict(zip(header, tokens))
            trt = int(row['TN'])
            if not row['EXCODE'].startswith('XXQL2601') or trt in anthesis:
                raise ValueError('Evaluation experiment/treatment identity')
            anthesis[trt] = float(row['ADAPS'])
    if set(anthesis) != set(range(1, 13)):
        raise ValueError('Incomplete anthesis coverage')
    extra = []
    for row in catalog[catalog.variable == 'ADAP'].to_dict('records'):
        extra.append(row | {'simulated': anthesis[int(row['trno'])]})
    records = pd.concat([records, pd.DataFrame(extra)], ignore_index=True).set_index('obsnme')
    records = records.loc[catalog.obsnme].reset_index()
    if len(records) != 612 or records.obsnme.duplicated().any():
        raise ValueError('Incomplete 612-target objective')
    if not np.isfinite(records.simulated).all() or records.simulated.min() < 0:
        raise ValueError('Nonfinite/negative objective')
    residual = ((records.simulated - records.observed) / records.fit_scale).to_numpy()
    delta = records.huber_delta.to_numpy()
    if not (catalog.loss.eq('pseudo_huber').all() and np.all(delta > 0)):
        raise ValueError('Unexpected frozen objective loss')
    records['pest_output'] = residual * np.sqrt(2 / (np.hypot(1, residual / delta) + 1))
    records['phi_contribution'] = (records.pest_output * records.final_weight) ** 2
    return records


def require_stage5_r2(config):
    if config.get('ni_stage') != 5 or config.get('root_mode') != 2:
        raise ValueError('This smoke requires explicit ni_stage=5 and root_mode=2')


def audit(work, config):
    require_stage5_r2(config)
    n = pd.read_csv(work / 'PlantNIntegration.csv', float_precision='round_trip')
    r = pd.read_csv(work / 'LayerNIntegration.csv', float_precision='round_trip')
    if len(n) != 1512 or not n.stage.eq(5).all() or set(n.run) != set(range(1, 13)):
        raise ValueError('Stage 5 not active on all 12 treatments/days')
    if n.duplicated(['run', 'yrdoy']).any() or not np.isfinite(n.to_numpy()).all():
        raise ValueError('Invalid daily nitrogen ledger')
    if not np.isfinite(r.to_numpy()).all() or r.duplicated(['run', 'yrdoy', 'layer']).any():
        raise ValueError('Invalid root layer ledger')
    # The unchanged Fortran sets r_diff only in root_mode=2. Positive native
    # diffusion is evidence of execution, rather than an echo of a requested
    # switch. This activation check is specific to this frozen 26SP smoke.
    diffusion = r.Diff_potential_gN_m2 > 0
    diffusion_runs = set(r.loc[diffusion, 'run'])
    if diffusion_runs != set(range(1, 13)):
        raise ValueError('Missing actual R2 diffusion evidence in a treatment')
    # Check independent Q stock-flow identity, not just the native residual.
    old_q = n.groupby('run')[['QNO3', 'QNH4']].shift().fillna(0).sum(axis=1)
    residual = old_q + n.U_NO3 + n.U_NH4 - n.A_NO3 - n.A_NH4 - n.inorg_litter - n.QNO3 - n.QNH4
    cap3 = n[['carrier_leaf', 'carrier_stem', 'carrier_root']].to_numpy() * config['q_no3_max']
    cap4 = n[['carrier_leaf', 'carrier_stem', 'carrier_root']].to_numpy() * config['q_nh4_max']
    excess = max(float((n[['QNO3_leaf', 'QNO3_stem', 'QNO3_root']].to_numpy() - cap3).max()),
                 float((n[['QNH4_leaf', 'QNH4_stem', 'QNH4_root']].to_numpy() - cap4).max()))
    flux = r.groupby(['run', 'yrdoy'])[['NO3_final_gN_m2', 'NH4_final_gN_m2']].sum()
    joined = n.set_index(['run', 'yrdoy'])[['U_NO3', 'U_NH4']].join(flux, how='left').fillna(0)
    root_error = max(float((joined.U_NO3 - joined.NO3_final_gN_m2).abs().max()),
                     float((joined.U_NH4 - joined.NH4_final_gN_m2).abs().max()))
    # Curves are evaluated at beginning-of-day mass; end-of-day output W is
    # not substituted as if it were the same state. Baseline amplitude at
    # establishment provides an independent parameter-to-model echo.
    first = n.groupby('run').head(1)
    if not np.allclose(first.leaf_crit, config['leaf_a'], atol=1e-10, rtol=0):
        raise ValueError('Leaf curve amplitude was not consumed')
    if not np.allclose(first.stem_crit, config['stem_a'], atol=1e-10, rtol=0):
        raise ValueError('Stem curve amplitude was not consumed')
    if n.Q_residual.abs().max() > 1e-9 or residual.abs().max() > 1e-9 or excess > 1e-9 or root_error > 2e-7:
        raise ValueError(f'New N budget/capacity/root handoff: {residual.abs().max()}, {excess}, {root_error}')
    if n[['QNO3', 'QNH4', 'A_NO3', 'A_NH4', 'U_NO3', 'U_NH4']].min().min() < -1e-12:
        raise ValueError('Negative new N state/flux')
    return dict(passed=True, days=len(n), stage=5, root_mode=2,
                R2_diffusion_rows=int(diffusion.sum()), R2_diffusion_treatments=len(diffusion_runs),
                R2_execution_evidence='positive native diffusion set exclusively by root_mode=2',
                Q_native_residual_max=float(n.Q_residual.abs().max()),
                Q_independent_residual_max=float(residual.abs().max()),
                capacity_excess_max=excess, root_handoff_max=root_error,
                legacy_organic_N_residual_max=float(n.legacy_organic_N_residual.abs().max()),
                legacy_growth_C_overrun_max=float(n.legacy_growth_C_overrun.abs().max()),
                legacy_bugs_deferred=True, organic_N_objective_operator='unchanged native LN%D/SN%D; assay reconciliation pending')


def evaluate(design_path, parameters, out):
    started = time.monotonic()
    design_path, out = Path(design_path).resolve(), Path(out).resolve()
    d = json.loads(design_path.read_text(encoding='utf8'))
    out.mkdir(parents=True, exist_ok=True)
    (out / 'FormalObjectives.OUT').unlink(missing_ok=True)
    trial = out / 'native_trials' / uuid.uuid4().hex
    trial.mkdir(parents=True)
    receipt = dict(success=False, trial=str(trial), design_sha256=sha(design_path), imputed=False)
    try:
        for path, h in d['frozen_hashes'].items():
            if sha(path) != h:
                raise ValueError('Frozen dependency changed: ' + path)
        frame = pd.read_csv(parameters)
        bounds = pd.read_csv(d['bounds'])
        if frame.name.duplicated().any() or set(frame.name) != set(bounds.pest_name):
            raise ValueError('Parameter identity coverage')
        search = dict(zip(frame.name, frame.value.astype(float)))
        values = {}
        for row in bounds.itertuples():
            value = search[row.pest_name]
            if not np.isfinite(value) or not row.lower - 1e-12 <= value <= row.upper + 1e-12:
                raise ValueError('Frozen parameter bound: ' + row.name)
            if row.status == 'fixed' and abs(value - row.init) > 1e-12:
                raise ValueError('Fixed parameter changed: ' + row.name)
            values[row.name] = value
        receipt['parameters'] = values
        for path in Path(d['inputs']).iterdir():
            if path.is_file():
                shutil.copy2(path, trial / path.name)
        redirect(trial / 'DSSATPRO.v48', trial)
        actual = inject_cultivar(trial, values, d['cultivar_fields'])
        config = {'ni_stage': 5, 'root_mode': 2, **{k: values[k] for k in d['nitrogen_names']}}
        require_stage5_r2(config)
        (trial / 'NIntegration.nml').write_text('&NINTEGRATION\n' + ''.join(f' {k}={v:.17g}\n' for k, v in config.items()) + '/\n', encoding='ascii')
        dump(trial / 'injection_receipt.json', dict(requested=values, cultivar_parsed=actual,
                                                  nitrogen_config=config, executable_sha256=sha(d['binary'])))
        env = os.environ.copy()
        env['DSSAT_P0_TRACE'] = '0'
        env['DSSAT_N_CONFIG'] = str(trial / 'NIntegration.nml')
        receipt['mode_activation'] = dict(required_ni_stage=5, required_root_mode=2,
                                           native_cwd=str(trial), DSSAT_N_CONFIG=env['DSSAT_N_CONFIG'],
                                           configuration_sha256=sha(trial / 'NIntegration.nml'))
        with (trial / 'native_stdout.log').open('wb') as stdout, (trial / 'native_stderr.log').open('wb') as stderr:
            r = subprocess.run([d['binary'], 'B', 'DSSBatch.v48'], cwd=trial, env=env, stdout=stdout, stderr=stderr, timeout=120)
        if r.returncode != 0 or not re.search(r'Normal end of run\s+12\b', (trial / 'INFO.OUT').read_text()):
            raise RuntimeError(f'Native failed ({r.returncode}); inspect {trial}')
        # Only the profile and six controlled cultivar fields may change.
        for path in Path(d['inputs']).iterdir():
            if path.is_file() and path.name not in {'DSSATPRO.v48', 'TMGRO048.CUL'}:
                if sha(path) != sha(trial / path.name):
                    raise ValueError('Frozen native input changed: ' + path.name)
        budget = audit(trial, config)
        comparison = extract(trial, pd.read_csv(d['observations']).fillna(''), Path(d['runtime']))
        comparison.to_csv(trial / 'comparison.csv', index=False)
        # Preserve requested AND actual rounded parameters; PEST optimizes
        # the requested vector through the native fixed-width operator.
        pd.DataFrame(values.items(), columns=['name', 'value']).to_csv(trial / 'parameters.csv', index=False)
        receipt.update(success=True, phi=float(comparison.phi_contribution.sum()), targets=len(comparison),
                       actual_cultivar=actual, nitrogen_config=config, budget=budget,
                       binary_sha256=sha(d['binary']))
        tmp = out / 'FormalObjectives.writing'
        tmp.write_text('\n'.join(f'{r.obsnme} {r.pest_output:.17g}' for r in comparison.itertuples()) + '\n', encoding='ascii')
        tmp.replace(out / 'FormalObjectives.OUT')
        dump(out / 'last_success.json', receipt)
        return receipt
    except BaseException as e:
        receipt.update(error=str(e), error_type=type(e).__name__)
        dump(out / 'last_failure.json', receipt)
        raise
    finally:
        receipt['elapsed_seconds'] = time.monotonic() - started
        dump(trial / 'receipt.json', receipt)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--design', required=True)
    p.add_argument('--parameters', default='parameters.csv')
    p.add_argument('--out', default='.')
    a = p.parse_args()
    evaluate(a.design, a.parameters, a.out)
