"""Prepare an isolated, provenance-bound mechanism version and fixed-vector probes."""
from pathlib import Path
import json,zipfile,hashlib,shutil,subprocess,sys,importlib.util
ROOT=Path(__file__).resolve().parent;V=ROOT/'n_buffer_v15';AUDIT=ROOT/'reports/leaf_n_valley_audit_20261028'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,q):Path(p).write_text(json.dumps(q,ensure_ascii=False,indent=2),encoding='utf8')
def replace(s,old,new):
    assert s.count(old)==1,(old[:100],s.count(old));return s.replace(old,new)

def prepare():
    for d in ['source','build','bin','configs','runs','evidence','tests']: (V/d).mkdir(parents=True,exist_ok=True)
    if not(V/'runtime').exists():shutil.copytree(ROOT/'n_buffer_v14/runtime',V/'runtime',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ['protocol.py','forward_search.py','coordinates.py','native_precision.py','launch_ies.py','launch_checkpointed_ies.py']:
        if not(V/name).exists():shutil.copy2(ROOT/'n_buffer_v14'/name,V/name)
    meta=json.loads((ROOT/'n_buffer_v12/manifests/build_capacity_a.json').read_text())
    archive=ROOT/'n_buffer_v12/manifests/source_capacity_a.zip';assert sha(archive)==meta['source_archive_sha256']
    with zipfile.ZipFile(archive)as z:
        original={n:z.read('Plant/CROPGRO/'+n).decode()for n in ['N_BUFFER_V2.f90','NUPTAK.for']}
    for n,s in original.items():assert hashlib.sha256(s.encode()).hexdigest()==meta['sources'][n]
    return meta,original

def sources(original,weighted,proportional):
    s=original['N_BUFFER_V2.f90']
    s=replace(s,'  public :: nb_feedback_response','  public :: nb_feedback_response,nb_uptake_signal,nb_get_uptake_psi')
    s=replace(s,'  real(dp) :: nb_psi_n=0._dp, nb_dmax=0._dp','  real(dp) :: nb_uptake_psi=0._dp\n  real(dp) :: nb_psi_n=0._dp, nb_dmax=0._dp')
    s=replace(s,'    nb_psi_n=0._dp; nb_dmax=0._dp','    nb_uptake_psi=0._dp\n    nb_psi_n=0._dp; nb_dmax=0._dp')
    helpers='''  pure function nb_uptake_signal(total,critical,reserve,kmob,protect) result(signal)
    real(dp),intent(in)::total(2),critical(2),reserve(2),kmob,protect
    real(dp)::signal(2),ready(2),gap(2),unavailable(2)
    ! Signalling only: never mutate N inventory or credit an internal source.
    ready=min(max(0._dp,reserve)*nb_rate(kmob,1._dp),max(0._dp,reserve-protect*critical))
    gap=max(0._dp,critical-max(0._dp,total-reserve))
    unavailable=max(0._dp,reserve-ready)
    signal=max(0._dp,total-min(unavailable,max(0._dp,gap-ready)))
  end function

  pure real function nb_get_uptake_psi() result(p)
    p=real(nb_uptake_psi)
  end function

'''
    s=replace(s,'  pure real function nb_feedback_response(psi,alpha) result(f)',helpers+'  pure real function nb_feedback_response(psi,alpha) result(f)')
    s=replace(s,'    logical :: state_valid\n    call require(.not.pending', '    real(dp)::signal_n(2),ready_n(2),gap_n(2),signal_psi,nn_signal,nmin_signal,ncrit_signal,nmax_signal\n    integer::decision_unit\n    logical::decision_exists\n    logical :: state_valid\n    call require(.not.pending')
    old='''    total=old_n(1:3)
    repaired_n=0;'''
    new='''    signal_n=old_n(1:2)
    ready_n=min(max(0._dp,nb_reserve)*nb_rate(nb_kmob,1._dp),max(0._dp,nb_reserve-nb_protect*nb_ncrit(1:2)))
    gap_n=max(0._dp,nb_ncrit(1:2)-max(0._dp,old_n(1:2)-nb_reserve))
    nb_uptake_psi=nb_psi_n
'''
    if weighted:new+='''    signal_n=nb_uptake_signal(old_n(1:2),nb_ncrit(1:2),nb_reserve,nb_kmob,nb_protect)
    call nb_relative_state(real(dm(1:2),dp),signal_n,organ_conc(1:2),floor_ratio,cap_density, &
      nmin_signal,ncrit_signal,nmax_signal,signal_psi,nn_signal,state_valid)
    if(state_valid)nb_uptake_psi=max(-1._dp,min(1._dp,signal_psi))
'''
    s=replace(s,old,new+'    total=old_n(1:3)\n    repaired_n=0;')
    log='''    if(nb_write_diagnostics)then
      inquire(file='NDecision.csv',exist=decision_exists)
      open(newunit=decision_unit,file='NDecision.csv',status='unknown',position='append')
      if(.not.decision_exists)write(decision_unit,'(A)')'run,trt,yrdoy,das,total_psi,uptake_psi,'// &
        'leaf_total_n,stem_total_n,leaf_reserve,stem_reserve,leaf_ready_n,stem_ready_n,'// &
        'leaf_functional_gap,stem_functional_gap,leaf_signal_n,stem_signal_n,growth_request,repair_request,dmax_kgN_ha'
      write(decision_unit,'(4(I0,","),*(ES24.15,:,","))')run_key,trt_key,date_key,day_key, &
        nb_psi_n,nb_uptake_psi,old_n(1:2),nb_reserve,ready_n,gap_n,signal_n,growth_demand,sum(repair_request),nb_dmax
      close(decision_unit)
    endif
'''
    s=replace(s,'    root_out=real(nb_root_request)\n    pending=.true.',log+'    root_out=real(nb_root_request)\n    pending=.true.')
    if proportional:
        s=replace(s,'    repair_ratio=min(1._dp,max(0._dp,available-growth_demand)/max(1.e-12_dp,sum(repair_request)))',
          '''    ! Joint growth/repair sharing from root, seed and fast N only.
    ! Slowly mobilized structural N remains reserved for growth, not repairs.
    repair_ratio=min(1._dp,max(0._dp,available-sum(nb_bound_mob))/ &
      max(1.e-12_dp,growth_demand+sum(repair_request)))''')
    n=original['NUPTAK.for']
    n=replace(n,'nb_get_alpha_h,nb_get_alpha_l,nb_feedback_response','nb_get_alpha_h,nb_get_alpha_l,nb_feedback_response,\n     & nb_get_uptake_psi')
    n=replace(n,'        PSI_N = nb_get_psi()','        PSI_N = nb_get_uptake_psi()')
    for t in ['H','L']:
        n=replace(n,f'F_FB_{t} = 1.0 / (1.0 + EXP(MIN(40.0, nb_get_alpha_{t.lower()}() * PSI_N)))',f'F_FB_{t} = nb_feedback_response(PSI_N, nb_get_alpha_{t.lower()}())')
    return {'N_BUFFER_V2.f90':s,'NUPTAK.for':n}

def build(name,src,meta):
    build=V/'build'/name;build.mkdir(exist_ok=True)
    binary=V/'bin'/f'{name}.exe'
    if(build/'manifest.json').exists():
        q=json.loads((build/'manifest.json').read_text());assert sha(binary)==q['binary_sha256'];return binary
    srcdir=V/'source'/name;srcdir.mkdir(exist_ok=True)
    commands=[];objects={}
    for i,n in enumerate(['N_BUFFER_V2.f90','NUPTAK.for']):
        p=srcdir/n;p.write_text(src[n],encoding='utf8');obj=build/(n+'.obj')
        c=list(meta['commands'][i]);c=[('-J'+str(build))if x.startswith('-J')else x for x in c]
        # The caller compiles against its own modified module first.
        c.insert(1,'-I'+str(build));c[c.index('-c')+1]=str(p);c[c.index('-o')+1]=str(obj)
        cp=subprocess.run(c,cwd=build,capture_output=True,text=True);(build/(n+'.compile.log')).write_text(cp.stdout+cp.stderr)
        assert cp.returncode==0,cp.stderr;commands.append(c);objects[n+'.obj']=str(obj)
    linked=[]
    for path,h in meta['linked_objects'].items():assert sha(path)==h;linked.append(objects.get(Path(path).name,path))
    rsp=build/'link.rsp';rsp.write_text('\n'.join('"'+p.replace('\\','/')+'"'for p in linked))
    c=[meta['toolchain']['gfortran'],'@'+str(rsp),'-static','-static-libgcc','-static-libgfortran','-o',str(binary)]
    cp=subprocess.run(c,cwd=build,capture_output=True,text=True);(build/'link.log').write_text(cp.stdout+cp.stderr);assert cp.returncode==0,cp.stderr
    dump(build/'manifest.json',dict(version=name,binary=str(binary),binary_sha256=sha(binary),sources={str(srcdir/n):sha(srcdir/n)for n in src},compile_commands=commands,link_command=c,original_build_manifest_sha256=sha(ROOT/'n_buffer_v12/manifests/build_capacity_a.json')))
    return binary

def main():
    meta,original=prepare()
    builds=[]
    for name,w,p in [('v15_s1_interface',False,False),('v15_s2_weighted',True,False),('v15_s2_joint',False,True),('v15_s2_weighted_joint',True,True)]:
        b=build(name,sources(original,w,p),meta);builds.append(dict(name=name,weighted_signal=w,joint_growth_repair=p,binary=str(b),sha256=sha(b)))
    dump(V/'configs/mechanism_variants.json',dict(purpose='Independent controlled mechanism variants; no changes to parameter/observation bounds',variants=builds))
    print('BUILT',[(q['name'],q['sha256'][:12])for q in builds],flush=True)
if __name__=='__main__':main()
