"""Official-binary causal input probes, isolated generated SPE only."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.experiments.replay_v51_carbon_diagnostics_20260902 import OUT, sha, verify_seal
from tools.analysis.audit_v46_best71_early_nstress_20260831 import parse_plantgro
from src.common.param_registry import PHYSICAL_BOUNDS


def main():
    rows = []
    for name, marker, field, factor in [('PHTMAX', 'PARMAX,PHTMAX', 1, 1.1), ('PARMAX', 'PARMAX,PHTMAX', 0, 1.1), ('PGEFF', 'PGEFF SCV', 0, 1.05)]:
        for season in ['25SP', '26SP']:
            source = OUT / 'control_A47' / season
            dest = OUT / ('probe_'+name.lower()) / season
            if dest.exists():
                raise FileExistsError(dest)
            dest.mkdir(parents=True)
            for p in source.iterdir():
                if p.suffix.upper() in {'.CUL', '.ECO', '.SPE', '.SOL', '.TMX', '.TMA', '.TMT', '.WTH', '.V48'}:
                    shutil.copy2(p, dest / p.name)
            p = dest / 'TMGRO048.SPE'
            lines = p.read_text().splitlines(keepends=True)
            i = next(i for i, line in enumerate(lines) if marker in line)
            start, end = 6*field, 6*(field+1)
            old = float(lines[i][start:end])
            requested = old*factor
            text = f'{requested:6.4f}' if name == 'PGEFF' else f'{requested:6.2f}'
            assert len(text) == 6
            actual = float(text)
            lo, hi = PHYSICAL_BOUNDS[name]
            assert lo <= actual <= hi
            lines[i] = lines[i][:start] + text + lines[i][end:]
            p.write_text(''.join(lines), newline='')
            original = (source / p.name).read_text().splitlines()
            written = p.read_text().splitlines()
            assert len(original) == len(written)
            assert all(a == b for j,(a,b) in enumerate(zip(original,written)) if j != i)
            assert original[i][:start] == written[i][:start] and original[i][end:] == written[i][end:]
            result = subprocess.run([str(ROOT/'DSCSM048.EXE'), 'CRGRO048', 'B', 'DSSBatch.selected.v48'], cwd=dest, input='\n'*8, text=True, capture_output=True, timeout=120)
            (dest/'stdout.log').write_text(result.stdout, encoding='utf-8')
            assert result.returncode == 0
            for filename in ['PlantGro.OUT', 'PlantN.OUT', 'PlantC.OUT']:
                a, b = parse_plantgro(dest/filename), parse_plantgro(source/filename)
                assert list(a.columns) == list(b.columns) and a.shape == b.shape
                numeric = a.select_dtypes(include='number').columns
                difference = float(np.abs(a[numeric]-b[numeric]).max().max())
                rows.append(dict(parameter=name, season=season, original=old, requested=requested, actual=actual,
                                 file=filename, maximum_numeric_difference=difference,
                                 parameter_file_sha256=sha(p)))
            print('PROBED', name, season, flush=True)
    import pandas as pd
    pd.DataFrame(rows).to_csv(OUT/'photo_branch_probes.csv',index=False)
    verify_seal()


if __name__ == '__main__':
    main()
