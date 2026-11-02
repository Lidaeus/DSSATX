"""Isolated P0b off/on replay. Does not calibrate or change any input vector."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime, timezone
from prepare_readiness import digest, manifest, redirect_profile, numeric_records, COMPARE_FILES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--exe', type=Path, required=True)
    args = parser.parse_args()
    cn = Path(r'D:/Tomato_Cal/subprojects/critical_n')
    frozen = cn/'reports/n_integration_v2_readiness_20261102/baseline_verified'
    old = json.loads((frozen/'readiness_receipt.json').read_text(encoding='utf-8'))
    protected = {p: digest(Path(p)) for p in old['protected_executables_before']}
    if protected != old['protected_executables_before']:
        raise ValueError('Protected executable identity changed before P0b')
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root/'bin').mkdir()
    exe = root/'bin/dscsm048_p0b.exe'
    shutil.copy2(args.exe, exe)
    repo = Path(__file__).resolve().parents[2]
    source_paths = ['CMakeLists.txt','Utilities/CG_P0Trace.f90','Plant/CROPGRO/CROPGRO.for',
                    'Plant/CROPGRO/GROW.for','Plant/CROPGRO/VEGGR.for','Soil/Inorganic_N/SoilNi.for',
                    'SPAM/SPAM.for','SPAM/ETPHOT.for','SPAM/ETPHR.for',
                    'Soil/CENTURY_OrganicMatter/CENTURY.for']
    receipt = {'created_utc':datetime.now(timezone.utc).isoformat(),
        'scope':'P0b official native diagnostics; 26SP historical preflight base; not V15 best; no calibration',
        'v15_mechanisms_adopted':False,
        'original_reference_receipt':str(frozen/'readiness_receipt.json'),
        'frozen_inputs':manifest(frozen/'inputs_26SP'),
        'binary':{'path':str(exe),'sha256':digest(exe)},
        'git_head_at_build_run':subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip(),
        'source_hashes':{p:digest(repo/p) for p in source_paths},
        'protected_before':protected,'runs':{}}
    try:
        for label, flag in [('trace_off','0'),('trace_on','1')]:
            run = root/label
            shutil.copytree(frozen/'inputs_26SP',run)
            redirect_profile(run/'DSSATPRO.v48',run)
            before = manifest(run)
            env = os.environ.copy()
            env['DSSAT_P0_TRACE'] = flag
            result = subprocess.run([str(exe),'B','DSSBatch.v48'],cwd=run,
                                    env=env,capture_output=True,timeout=900)
            (run/'engine_stdout.txt').write_bytes(result.stdout)
            (run/'engine_stderr.txt').write_bytes(result.stderr)
            info = (run/'INFO.OUT').read_text(errors='replace') if (run/'INFO.OUT').exists() else ''
            if result.returncode or not re.search(r'Normal end of run\s+12\b',info):
                raise RuntimeError(f'{label} failed; inspect stderr')
            if (run/'P0Trace.csv').exists() != (flag=='1'):
                raise RuntimeError('Trace switch did not control output')
            if any(digest(run/p)!=h for p,h in before.items()):
                raise RuntimeError('Frozen run inputs changed')
            comparisons={}
            for name in COMPARE_FILES:
                ref=numeric_records(frozen/'reference_26SP'/name)
                actual=numeric_records(run/name)
                comparisons[name]={'numeric_rows':len(actual),'exact':ref==actual,
                                   'sha256':digest(run/name)}
            # More extensive off/on comparisons cover all common OUT files with numeric rows.
            receipt['runs'][label]={'returncode':result.returncode,'normal_end_12':True,
                                    'trace_enabled':flag=='1','comparisons':comparisons,
                                    'input_hashes':before}
        receipt['off_on_numeric_comparisons']={}
        for output in sorted((root/'trace_off').glob('*.OUT')):
            try:
                off=numeric_records(output)
                on=numeric_records(root/'trace_on'/output.name)
            except ValueError as exc:
                if not str(exc).startswith('No comparable native data rows:'):
                    raise
                continue
            receipt['off_on_numeric_comparisons'][output.name]={'numeric_rows':len(off),'exact':off==on}
        receipt['protected_after']={p:digest(Path(p)) for p in protected}
        receipt['trace_sha256']=digest(root/'trace_on/P0Trace.csv')
        receipt['passed']=(receipt['protected_after']==protected and
             all(x['exact'] for run in receipt['runs'].values() for x in run['comparisons'].values()) and
             all(x['exact'] for x in receipt['off_on_numeric_comparisons'].values()))
        if not receipt['passed']:
            raise RuntimeError('P0b native replay comparison failed')
    except Exception as exc:
        receipt['passed']=False
        receipt['error']=repr(exc)
        raise
    finally:
        (root/'run_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':True,'receipt':str(root/'run_receipt.json'),
                      'off_on_native_files':len(receipt['off_on_numeric_comparisons']),
                      'trace_bytes':(root/'trace_on/P0Trace.csv').stat().st_size},ensure_ascii=False))


if __name__=='__main__':
    main()
