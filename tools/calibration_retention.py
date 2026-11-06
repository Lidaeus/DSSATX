"""Compact completed native trials after extraction; never alter scientific receipts.

Inspired by src.dssat.run_dssat.cleanup, with explicit audit evidence retention.
Only named, reproducible outputs and the per-trial executable are removable.
"""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from collections import deque
import hashlib
import json
import os
import re
import time

GENERATED_CSV = frozenset(n.lower() for n in (
    'RootNSupply.csv', 'NCBalance.csv', 'CAllocation.csv', 'DMState.csv',
    'OrganNState.csv', 'CH2OPools.csv', 'NAcceptance.csv', 'NFlux.csv',
    'NStateSignal.csv', 'NDecision.csv', 'CohortSync.csv', 'PhotoN.csv',
    'capacity_audit.csv', 'NCoordination.csv', 'NStateMemory.csv',
    'OrganFluxTrace.csv', 'CoordinationSolve.csv'))
KEEP_OUT = frozenset(n.lower() for n in (
    'NBufferParam.OUT', 'CNCParam.OUT', 'ERROR.OUT', 'WARNING.OUT',
    'FormalObjectives.OUT', 'NBufferFailure.txt'))
TAIL_CSV = frozenset(n.lower() for n in (
    'NCBalance.csv', 'CAllocation.csv', 'OrganNState.csv', 'DMState.csv',
    'RootNSupply.csv', 'CH2OPools.csv', 'NDecision.csv', 'NCoordination.csv',
    'OrganFluxTrace.csv', 'CoordinationSolve.csv'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.writing')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    tmp.replace(path)


def checked_trial(trial):
    raw = Path(trial).absolute()
    resolved = raw.resolve(strict=True)
    if raw != resolved or resolved.parent.name != 'native_trials' or not re.fullmatch(r'[0-9a-f]{32}', resolved.name):
        raise ValueError('Refuse cleanup outside a UUID native_trials directory: ' + str(raw))
    for p in [raw, *raw.parents]:
        if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
            raise ValueError('Refuse cleanup through a linked directory: ' + str(p))
    return resolved


def compact_trial(trial, *, success, require_evidence=True):
    """Idempotent; errors are explicit, originals receipts/checkpoints stay unchanged.

    Called only after the subprocess has exited and extraction/physics have finished.
    Failures retain logs, input files, error files, and short ledger tails.
    """
    trial = checked_trial(trial)
    manifest = trial / 'storage_retention.json'
    prior = {}
    if manifest.exists():
        prior = json.loads(manifest.read_text(encoding='utf8'))
        if prior.get('complete') and prior.get('version') == 2:
            return prior
    evidence = [trial / n for n in ('receipt.json', 'result.json', 'parameters.csv', 'comparison.csv') if (trial / n).is_file()]
    if require_evidence and not any(p.name in ('receipt.json', 'result.json') for p in evidence):
        raise ValueError('Missing completed trial receipt')
    if success and not (trial / 'comparison.csv').is_file():
        raise ValueError('Successful trial missing extracted targets')
    before = {str(p.relative_to(trial)): sha(p) for p in evidence}
    folders = [trial] + [p for p in trial.iterdir() if p.is_dir() and p.name in ('25SP', '26SP')]
    candidates = []
    for folder in folders:
        if folder.resolve() != folder or folder.is_symlink() or (hasattr(folder, 'is_junction') and folder.is_junction()):
            raise ValueError('Linked native season directory')
        for p in folder.iterdir():
            n = p.name.lower()
            if p.is_symlink():
                raise ValueError('Linked native file: ' + str(p))
            if not p.is_file() or n in KEEP_OUT:
                continue
            if n == 'dscsm048.exe' or n in GENERATED_CSV or p.suffix.lower() in ('.out', '.lst', '.rep'):
                if p.resolve().parent != folder:
                    raise ValueError('Unsafe cleanup target')
                candidates.append(p)
    removed = list(prior.get('deletion_plan', [])) if prior.get('complete') else []
    # Write the complete checked plan before the first unlink. No recursive deletion.
    current_plan = [dict(path=str(p.relative_to(trial)), bytes=p.stat().st_size) for p in candidates]
    plan = dict(version=2, mode='compact_success' if success else 'compact_failure',
                created_unix=time.time(), complete=False, retained_sha256=before,
                deletion_plan=removed + current_plan,
                logical_removed_bytes=0, removed_files=0)
    atomic_json(manifest, plan)
    for p, rec in zip(candidates, current_plan):
        if not success and p.name.lower() in TAIL_CSV:
            with p.open('rb') as f:
                header = f.readline()
                tail = deque(f, maxlen=64)
            p.with_name(p.stem + '.failure_tail.csv').write_bytes(header + b''.join(tail))
        p.unlink()
        removed.append(rec)
    for n, h in before.items():
        if sha(trial / n) != h:
            raise RuntimeError('Retained scientific evidence changed: ' + n)
    plan.update(complete=True, logical_removed_bytes=sum(x['bytes'] for x in removed), removed_files=len(removed))
    atomic_json(manifest, plan)
    return plan


def install_protocol(text):
    """Apply the retention integration to a freshly generated review protocol."""
    start = "def evaluate(design_path,param_csv,output_dir,keep_diagnostics=True):"
    assert text.count(start) == 1
    text = text.replace(start, "def evaluate(design_path,param_csv,output_dir,keep_diagnostics=True,keep_native=True):")
    end = "        receipt['elapsed_seconds']=time.time()-started;write_json(trial/'receipt.json',receipt)"
    assert text.count(end) == 1
    text = text.replace(end, end + "\n        if not keep_native:\n            from calibration_retention import compact_trial\n            try:\n                compact_trial(trial,success=receipt['success'])\n            except Exception as storage_exc:\n                receipt.update(success=False,storage_cleanup_error=repr(storage_exc),error='Storage retention failed: '+str(storage_exc),error_type='StorageRetentionError')\n                (out/'FormalObjectives.OUT').unlink(missing_ok=True)\n                write_json(trial/'receipt.json',receipt);write_json(out/'last_failure.json',receipt)\n                raise RuntimeError(receipt['error'])from storage_exc")
    return text


def install_forward(text):
    flag = "p.add_argument('--no-diagnostics',action='store_true');a=p.parse_args()"
    assert text.count(flag) == 1
    text = text.replace(flag, "p.add_argument('--no-diagnostics',action='store_true');p.add_argument('--keep-native',action='store_true');a=p.parse_args()")
    call = "evaluate(a.design,out/'physical_parameters.csv',out,not a.no_diagnostics)"
    assert text.count(call) == 1
    # The search wrapper appends exact search coordinates to the receipt. Compact
    # only AFTER that last write, otherwise its preserved receipt hash is stale.
    text = text.replace(call, "evaluate(a.design,out/'physical_parameters.csv',out,not a.no_diagnostics,keep_native=True)")
    marker = 'from resource_guard import reserve'
    assert text.count(marker) == 1
    text = text.replace(marker, marker + '\nfrom calibration_retention import finalize_callback_storage')
    failure = "        write_json(Path(q['trial'])/'receipt.json',q);write_json(out/'last_failure.json',q);raise"
    assert text.count(failure) == 1
    text = text.replace(failure, "        write_json(Path(q['trial'])/'receipt.json',q);write_json(out/'last_failure.json',q)\n        finalize_callback_storage(q,out,a.keep_native)\n        raise")
    success = "    write_json(Path(result['trial'])/'receipt.json',result);write_json(out/'last_success.json',result)"
    assert text.count(success) == 1
    return text.replace(success, success + '\n    finalize_callback_storage(result,out,a.keep_native)')


def finalize_callback_storage(receipt, out, keep_native):
    """Called after search coordinates have been persisted, on both exit paths."""
    if keep_native:
        return
    try:
        compact_trial(receipt['trial'], success=receipt['success'])
    except Exception as exc:
        receipt.update(success=False, storage_cleanup_error=repr(exc),
                       error='Storage retention failed: ' + str(exc), error_type='StorageRetentionError')
        (Path(out) / 'FormalObjectives.OUT').unlink(missing_ok=True)
        atomic_json(Path(receipt['trial']) / 'receipt.json', receipt)
        atomic_json(Path(out) / 'last_failure.json', receipt)
        raise RuntimeError(receipt['error']) from exc
