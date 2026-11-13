import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RUNS = ROOT / 'workspace/runs'
OFF = RUNS / 'eggplant_final_springs_58_restored_bounds_final_200x4_8agents_20261107'
V15 = RUNS / 'coord5_joint76_formal200x5_20261030_direct1043'
REPLAY = V15 / 'final/deterministic_replay/native_trials/58f2c12f12104302bb0d0cc715d8fd00'
DESIGN = V15 / 'recovery_20261030/runtime/design_direct1043.json'
BUNDLES = {'25SP': 'xxql2501_refreshed_lwad_20261108', '26SP': 'xxql2601_final_20261105'}

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))

def run(model, season, pilot):
    bundle = ROOT / 'data/user/experiments' / BUNDLES[season]
    manifest = bundle / 'input_manifest.json'
    for entry in read(manifest)['files']:
        assert sha(bundle / entry['name']) == entry['sha256'], entry['name']
    design = read(DESIGN)
    if model == 'official':
        exe = Path('C:/DSSAT48/DSCSM048.EXE')
        genotype = OFF / ('validation' if season == '25SP' else 'selected_deterministic')
        params = OFF / 'best_calibration_parameters.csv'
        assert sha(params) == read(OFF / 'selection.json')['parameters_sha256']
    else:
        exe = Path(design['binary'])
        genotype = REPLAY / season
        params = V15 / 'final/best_parameters.csv'
        assert sha(exe) == design['binary_sha256']
        assert sha(exe) == sha(genotype / 'DSCSM048.EXE')
    work = OUT / ('pilot' if pilot else 'replay') / model / season
    work.mkdir(parents=True, exist_ok=False)
    names = ['SOIL.SOL','XXTW2403.WTH','DSSBatch.v48']
    ex = 'XXQL' + season[:2] + '01'
    names += [ex + '.' + ext for ext in ('TMX','TMA','TMT')]
    for name in names:
        shutil.copy2(bundle / name, work / name)
    for ext in ('CUL','ECO','SPE'):
        name = 'TMGRO048.' + ext
        shutil.copy2(genotype / name, work / name)
    for name in ('DSSAT48.INP','DSSAT48.INH','DSSATPRO.v48'):
        shutil.copy2(genotype / name, work / name)
    if pilot:
        batch = work / 'DSSBatch.v48'
        lines = batch.read_text().splitlines()
        rows = [s for s in lines if s.startswith(ex)]
        batch.write_text('\n'.join([s for s in lines if not s.startswith(ex)] + [rows[0],rows[-1]])+'\n')
    receipt = dict(bundle=str(bundle), bundle_sha256=sha(manifest), binary=str(exe), binary_sha256=sha(exe),
                   parameters=str(params), parameter_sha256=sha(params), genotype_source=str(genotype),
                   inputs={p.name:sha(p) for p in work.iterdir()})
    with (work/'native.log').open('wb') as log:
        p = subprocess.run([str(exe),'CRGRO048','B','DSSBatch.v48'],cwd=work,input=b'\n'*8,stdout=log,stderr=subprocess.STDOUT,timeout=240)
    assert p.returncode == 0 and not (work/'ERROR.OUT').exists(), work
    for name in ('PlantGro.OUT','PlantN.OUT','FreshWt.OUT','SoilWat.OUT','SoilNi.OUT'):
        assert (work/name).stat().st_size > 100, (work,name)
    (work/'receipt.json').write_text(json.dumps(receipt,indent=2))
    print(work, flush=True)

if __name__ == '__main__':
    import sys
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [pool.submit(run,m,s,'--pilot' in sys.argv) for m in ('official','coord5') for s in BUNDLES]
        for task in tasks:
            task.result()
