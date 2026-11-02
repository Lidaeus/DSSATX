"""Private leaf-only mobilization ablations; never alter the calibrated binary."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os,re,subprocess,sys
from run_regression import REPO,OUT,case,dump,sha

build=REPO/'build'
fc=re.search(r'^CMAKE_Fortran_COMPILER:[^=]+=(.*)$',(build/'CMakeCache.txt').read_text(encoding='utf8'),re.M)[1].strip()
env=os.environ.copy();env['PATH']=str(Path(fc).parent)+';'+env['PATH']
line=next(l for l in (build/'build.ninja').read_text(encoding='utf8').splitlines()if l.startswith('build bin/dscsm048.exe:'))
objects=[build/x for x in line.split()if x.endswith('.obj')]
assert len(objects)>500 and sum('CROPGRO/MOBIL.for.obj'in p.as_posix()for p in objects)==1
source=REPO/'Plant/CROPGRO/MOBIL.for'
jobs=[]
for factor in [0.,.5]:
    w=OUT/'leaf_mobil_ablation'/f'leaf_{factor}';w.mkdir(parents=True,exist_ok=False)
    text=source.read_text(encoding='utf8')
    old='         NRUSLF = NMINER * WNRLF'
    assert text.count(old)==1
    text=text.replace(old,f'         NRUSLF = {factor:.1f} * NMINER * WNRLF')
    text=text.replace('         CNMINE = NMINEA / 0.16 * RPRO',
                      '         NMINEA = NRUSLF + NRUSST + NRUSRT + NRUSSH\n         CNMINE = NMINEA / 0.16 * RPRO')
    patched=w/'MOBIL_leaf_ablation.for';patched.write_text(text,encoding='utf8')
    obj=w/'mobil.obj';exe=w/'dscsm048_leaf_ablation.exe'
    commands=[[fc,'-I',str(build/'mod'),'-ffixed-line-length-none','-O3','-c',str(patched),'-o',str(obj)]]
    rsp=w/'objects.rsp'
    rsp.write_text(' '.join('"'+str(obj if 'CROPGRO/MOBIL.for.obj'in p.as_posix()else p)+'"'for p in objects),encoding='ascii')
    commands.append([fc,'@'+str(rsp),'-o',str(exe),'-static','-static-libgcc','-static-libgfortran'])
    logs=[]
    for command in commands:
        r=subprocess.run(command,cwd=w,env=env,capture_output=True,text=True);logs.append(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError(logs[-1])
    (w/'build.log').write_text('\n'.join(logs),encoding='utf8')
    dump(w/'build_receipt.json',dict(purpose='controlled leaf-only donor ablation; never used for parameter calibration',
         factor=factor,source_sha256=sha(source),patched_sha256=sha(patched),binary_sha256=sha(exe),commands=commands,
         remaining_donors='native unscaled fluxes; actual total NMINEA recomputed; no compensatory extra donor mining',
         V15_physiology=False))
    jobs.append((f'diagnostic_leaf_mobil_{factor}',{'budget_revision':1},False,exe))
with ThreadPoolExecutor(max_workers=2)as pool:results=list(pool.map(lambda args:case(*args),jobs))
dump(OUT/'leaf_mobil_ablation_receipt.json',dict(cases=results,all_passed=all(r['success']for r in results)))
