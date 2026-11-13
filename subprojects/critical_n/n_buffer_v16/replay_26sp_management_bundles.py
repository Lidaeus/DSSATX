"""Deterministic V15 S1 replays with explicitly supplied management bundles."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pandas as pd

import protocol


VERSION = Path(__file__).resolve().parent
REFERENCE = VERSION / 'evidence/unified_final_20261029/reference_selection.json'
MANAGEMENT = ('DSSBatch.v48', 'XXQL2601.TMX', 'XXQL2601.TMA', 'XXQL2601.TMT', 'XXTW2403.WTH', 'SOIL.SOL')


def run(bundle, work):
    reference = json.loads(REFERENCE.read_text(encoding='utf8'))
    design = json.loads(Path(reference['latest_design']).read_text(encoding='utf8'))
    dataset = next(row for row in design['datasets'] if row['season_id'] == '26SP')
    params = REFERENCE.parent / 'retained_reference/best_parameters.csv'
    assert protocol.sha(params) == reference['parameter_sha256']
    assert protocol.sha(design['binary']) == reference['binary_sha256']
    for path, digest in design['frozen_hashes'].items():
        assert protocol.sha(path) == digest, path
    manifest_path = bundle / 'input_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    assert manifest['season'] == '26SP'
    for row in manifest['files']:
        assert protocol.sha(bundle / row['name']) == row['sha256'], row['name']
    work.mkdir(parents=True, exist_ok=False)
    for name, digest in dataset['native_hashes'].items():
        if name in MANAGEMENT or name.endswith('.csv') or name == 'SOIL.SOL.base':
            continue
        source = Path(dataset['native_inputs']) / name
        assert protocol.sha(source) == digest, source
        shutil.copy2(source, work / name)
    for name in (*MANAGEMENT, 'treatment_metadata.csv'):
        shutil.copy2(bundle / name, work / name)
    shutil.copy2(params, work / 'parameters.csv')
    bounds = pd.read_csv(design['bounds'])
    values = pd.read_csv(params).set_index('name').value.to_dict()
    protocol.validate(values, bounds)
    soil_lines = (bundle / 'SOIL.SOL').read_text().splitlines()
    scom = next(i for i, row in enumerate(soil_lines) if row.startswith('@ SCOM')) + 1
    soil_sldr = float(soil_lines[scom][18:24])
    soil_slpf = float(soil_lines[scom][36:42])
    settings = protocol.inject(work, values, soil_slpf, design.get('native_precision_improved', True))
    protocol.reference.audit_injection(work, values, [p for p in design['active'] if not p.startswith('NB_') and p != 'SLPF_25SP'])
    # Environment injection also writes SLDR. Restore the specified profile verbatim.
    shutil.copy2(bundle / 'SOIL.SOL', work / 'SOIL.SOL')
    management_hashes = {name: protocol.sha(work / name) for name in MANAGEMENT}
    assert all(digest == protocol.sha(bundle / name) for name, digest in management_hashes.items())
    executable = work / 'DSCSM048.EXE'
    shutil.copy2(design['binary'], executable)
    assert protocol.sha(executable) == reference['binary_sha256']
    protocol.write_json(work / 'injected_inputs.json', {p.name: protocol.sha(p) for p in work.iterdir() if p.is_file()})
    completed = subprocess.run([str(executable), 'CRGRO048', 'B', 'DSSBatch.v48'], cwd=work,
                               input='\n' * 8, capture_output=True, text=True, timeout=240)
    (work / 'native.log').write_text(completed.stdout + completed.stderr, encoding='utf8')
    assert completed.returncode == 0 and not (work / 'ERROR.OUT').exists(), work / 'native.log'
    np.testing.assert_allclose(np.loadtxt(work / 'NBufferParam.OUT', skiprows=1), settings, atol=.000501, rtol=0)
    physics = protocol.physics(work, dataset['treatments'], design['strict_capacity'])
    protocol.write_json(work / 'replay_receipt.json', dict(
        success=True, bundle=str(bundle), bundle_manifest_sha256=protocol.sha(manifest_path),
        reference_selection=str(REFERENCE), parameter_sha256=reference['parameter_sha256'],
        binary_sha256=reference['binary_sha256'], management_sha256=management_hashes,
        soil_policy='supplied profile verbatim', effective_SLDR=soil_sldr, effective_SLPF=soil_slpf,
        treatments=dataset['treatments'], physics=physics))
    print(bundle.name, physics, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('work', type=Path)
    args = parser.parse_args()
    run(args.bundle.resolve(), args.work.resolve())
