"""Re-run exact generated official inputs, preserving all native outputs.

No genotype, FileX, soil, executable or objective changes. Not calibration.
"""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.experiments.run_v50_mechanism_followup_20260902 import OUT as SOURCE, sha, verify_seal
from tools.analysis.audit_v46_best71_early_nstress_20260831 import parse_plantgro

OUT = ROOT / 'workspace/reports/v51_carbon_diagnostics_20260902'
CASES = ['control_A47', 'photo_0.90_4.20', 'photo_uptake_0.90_3.30', 'replay_E_i2_m3']


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    verify_seal()
    rows = []
    for case in CASES:
        for season in ['25SP', '26SP']:
            source = SOURCE / case / '_seasons' / season
            dest = OUT / case / season
            marker = dest / 'replay_audit.json'
            if marker.exists():
                rows.append(json.loads(marker.read_text()))
                continue
            if dest.exists():
                raise FileExistsError(f'Inspect incomplete replay: {dest}')
            dest.mkdir(parents=True)
            files = [p for p in source.iterdir() if p.suffix.upper() in {'.CUL', '.ECO', '.SPE', '.SOL', '.TMX', '.TMA', '.TMT', '.WTH', '.V48'}]
            hashes = {}
            for p in files:
                shutil.copy2(p, dest / p.name)
                hashes[p.name] = sha(p)
            command = [str(ROOT / 'DSCSM048.EXE'), 'CRGRO048', 'B', 'DSSBatch.selected.v48']
            result = subprocess.run(command, cwd=dest, input='\n'*8, text=True, capture_output=True, timeout=120)
            (dest / 'stdout.log').write_text(result.stdout, encoding='utf-8')
            (dest / 'stderr.log').write_text(result.stderr, encoding='utf-8')
            assert result.returncode == 0, dest
            for filename in ['PlantGro.OUT', 'PlantN.OUT']:
                a, b = parse_plantgro(dest / filename), parse_plantgro(source / filename)
                pd.testing.assert_frame_equal(a, b, check_exact=True)
            # FreshWt has descriptive headers; compare all numeric lines exactly.
            def numeric(p):
                return [x.strip() for x in p.read_text(errors='replace').splitlines() if x.strip() and x.strip()[0].isdigit()]
            assert numeric(dest / 'FreshWt.OUT') == numeric(source / 'FreshWt.OUT')
            assert (dest / 'PlantC.OUT').is_file()
            for name, digest in hashes.items():
                assert sha(source / name) == digest and sha(dest / name) == digest
            row = dict(case=case, season=season, exit_code=0, existing_numeric_outputs_match=True,
                       official_exe_sha256=sha(ROOT / 'DSCSM048.EXE'), input_hashes=hashes,
                       command=command, carbon_sha256=sha(dest / 'PlantC.OUT'))
            marker.write_text(json.dumps(row, indent=2), encoding='utf-8')
            rows.append(row)
            print(f'REPLAY VERIFIED {case} {season}', flush=True)
    verify_seal()
    (OUT / 'replay_manifest.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
