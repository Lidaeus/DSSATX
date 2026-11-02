"""Compile the actual core and all native test drivers with runtime traps."""
from pathlib import Path
import argparse,os,re,subprocess
from workflow import REPO,OUT,dump,sha,env_build
from run_stages import ENGINEERING

a=argparse.ArgumentParser();a.add_argument('label');args=a.parse_args()
work=OUT/'units'/args.label;work.mkdir(parents=True,exist_ok=False)
mods=work/'mod';mods.mkdir()
cache=(REPO/'build/CMakeCache.txt').read_text()
fc=re.search(r'^CMAKE_Fortran_COMPILER:[^=]+=(.*)$',cache,re.M)[1]
flags=['-ffree-line-length-none','-fcheck=all','-finit-real=snan','-ffpe-trap=invalid,zero,overflow']
env=env_build();env['DSSAT_N_CONFIG']=str(work/'NIntegration.nml')
cfg=dict(ni_stage=5,root_mode=2,budget_revision=1,**ENGINEERING)
(work/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v}\n'for k,v in cfg.items())+'/\n')
def run(cmd):
    p=subprocess.run(cmd,cwd=work,env=env,capture_output=True,text=True)
    with(work/'tests.log').open('a',encoding='utf8')as f:f.write(p.stdout+p.stderr)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    return p.stdout
run([fc,'-I',str(REPO/'build/mod'),'-J',str(mods),*flags,'-c',str(REPO/'Plant/CROPGRO/CG_Nitrogen.f90'),'-o',str(work/'core.obj')])
results=[]
for source in ['research/n_integration_v2/native_n_tests.f90','research/a_budget_feedback/native_A_tests.f90','research/n_v3/native_v3_tests.f90']:
    exe=work/(Path(source).stem+'.exe')
    run([fc,'-I',str(mods),'-I',str(REPO/'build/mod'),*flags,str(REPO/source),str(work/'core.obj'),'-o',str(exe),'-static','-static-libgcc','-static-libgfortran'])
    output=run([str(exe)]);print(output.strip())
    results.append(dict(source=source,source_sha256=sha(REPO/source),output=output))
dump(work/'receipt.json',dict(passed=True,core_sha256=sha(REPO/'Plant/CROPGRO/CG_Nitrogen.f90'),drivers=results))
