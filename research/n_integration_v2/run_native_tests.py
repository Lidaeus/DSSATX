"""Compile the actual new Fortran core with strict runtime checks and execute it."""
from pathlib import Path
import argparse,json,subprocess,os,re
from run_stages import ENGINEERING
from prepare_readiness import digest

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 repo=Path(__file__).resolve().parents[2];out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
 mods=out/'mod';mods.mkdir()
 cache=(repo/'build/CMakeCache.txt').read_text()
 fc=Path(re.search(r'^CMAKE_Fortran_COMPILER:[^=]+=(.*)$',cache,re.M)[1].strip())
 env=os.environ.copy();env['PATH']=str(fc.parent)+';'+env['PATH'];env.pop('DSSAT_N_CONFIG',None)
 cfg={'ni_stage':5,'root_mode':2,**ENGINEERING}
 (out/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v}\n' for k,v in cfg.items())+'/\n',encoding='ascii')
 core=repo/'Plant/CROPGRO/CG_Nitrogen.f90';test=repo/'research/n_integration_v2/native_n_tests.f90'
 flags=['-ffree-line-length-none','-fcheck=all','-finit-real=snan','-ffpe-trap=invalid,zero,overflow']
 commands=[[str(fc),'-I',str(repo/'build/mod'),'-J',str(mods),*flags,'-c',str(core),'-o',str(out/'core.obj')],
  [str(fc),'-I',str(mods),'-I',str(repo/'build/mod'),*flags,str(test),str(out/'core.obj'),'-o',str(out/'test_n.exe'),'-static','-static-libgcc','-static-libgfortran']]
 logs=[]
 for cmd in commands:
  r=subprocess.run(cmd,cwd=out,env=env,capture_output=True,text=True);logs.append(r.stdout+r.stderr)
  if r.returncode:raise RuntimeError(logs[-1])
 r=subprocess.run([str(out/'test_n.exe')],cwd=out,env=env,capture_output=True,text=True)
 (out/'test_log.txt').write_text('\n'.join(logs)+r.stdout+r.stderr,encoding='utf-8')
 if r.returncode:raise RuntimeError(r.stdout+r.stderr)
 m=re.search(r'NATIVE_N_CHECKS_PASSED=(\d+)',r.stdout);assert m
 receipt={'passed':True,'checks':int(m[1]),'compiler':str(fc),'commands':commands,
  'core_sha256':digest(core),'test_sha256':digest(test),'configuration_role':'engineering_only',
  'unit_test_binary_sha256':digest(out/'test_n.exe')}
 (out/'unit_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
 print(r.stdout.strip())
if __name__=='__main__':main()
