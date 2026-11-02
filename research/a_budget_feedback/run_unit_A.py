from pathlib import Path
import json,os,re,subprocess,sys
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
sys.path.insert(0,str(REPO/'research/n_integration_v2'))
from run_stages import ENGINEERING
from smoke_forward import sha,dump
OUT=Path(sys.argv[1]);OUT.mkdir(parents=True,exist_ok=False)
cache=(REPO/'build/CMakeCache.txt').read_text(encoding='utf8')
fc=re.search(r'^CMAKE_Fortran_COMPILER:[^=]+=(.*)$',cache,re.M)[1].strip()
mods=OUT/'mod';mods.mkdir()
env=os.environ.copy();env['PATH']=str(Path(fc).parent)+';'+env['PATH'];env['DSSAT_N_CONFIG']=str(OUT/'NIntegration.nml')
cfg=dict(ni_stage=5,root_mode=2,**ENGINEERING,budget_revision=1)
(OUT/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v}\n'for k,v in cfg.items())+'/\n',encoding='ascii')
flags=['-ffree-line-length-none','-fcheck=all','-finit-real=snan','-ffpe-trap=invalid,zero,overflow']
commands=[[fc,'-I',str(REPO/'build/mod'),'-J',str(mods),*flags,'-c',str(REPO/'Plant/CROPGRO/CG_Nitrogen.f90'),'-o',str(OUT/'core.obj')],
          [fc,'-I',str(mods),'-I',str(REPO/'build/mod'),*flags,str(HERE/'native_A_tests.f90'),str(OUT/'core.obj'),'-o',str(OUT/'test.exe'),'-static','-static-libgcc','-static-libgfortran'],[str(OUT/'test.exe')]]
logs=[]
for cmd in commands:
 p=subprocess.run(cmd,cwd=OUT,env=env,capture_output=True,text=True)
 logs.append(p.stdout+p.stderr)
 (OUT/'log.txt').write_text('\n'.join(logs),encoding='utf8')
 if p.returncode:raise RuntimeError(logs[-1])
dump(OUT/'receipt.json',dict(passed=True,commands=commands,core_sha256=sha(REPO/'Plant/CROPGRO/CG_Nitrogen.f90')))
print(logs[-1])
