"""Freeze approved design, screen100 complete members, run IES and locked validation."""
from pathlib import Path
import argparse
import concurrent.futures as cf
from datetime import datetime,timezone
import json
import os
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pyemu
from scipy.stats import qmc
import yaml

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.calibration import sa98_joint40 as model
from src.calibration import single_season_n as legacy
from src.sensitivity.strict_forward import read_genotype_parameters

ID='eggplant_26sp_cal25sp_val_sa98_joint40_100x5_20261031'
REVIEW='configs/calibration_proposals/eggplant_26sp_cal25sp_val_sa98_review_20261031'
AUTH='好，先按当前的40参数方案进行参数率定；100成员×5轮；FL-LF固定400；SLPF：2025春0.93，2026春0.89。'


def stamp():return datetime.now(timezone.utc).isoformat()
def write(p,j):legacy.write_json(p,j)
def seal(config,d):
    write(config/'design.json',d);write(config/'frozen_configuration_receipt.json',dict(design_sha256=legacy.sha(config/'design.json'),updated_at=stamp()))


def prepare():
    config=ROOT/'configs/runs'/ID;run=ROOT/'workspace/runs'/ID
    if (config/'design.json').exists() or (run/'source_snapshot').exists():raise FileExistsError('Never overwrite a formal run')
    config.mkdir(parents=True,exist_ok=True);run.mkdir(parents=True,exist_ok=True)
    review=ROOT/REVIEW;j=json.loads((review/'proposal.json').read_text(encoding='utf-8'))
    receipt=json.loads((review/'review_receipt.json').read_text(encoding='utf-8'))
    for n,h in receipt['artifact_hashes'].items():
        if legacy.sha(review/n)!=h:raise ValueError('Review artifact changed: '+n)
    b=pd.read_csv(review/'bounds_proposal_strict40.csv').fillna('')
    b=b.drop(columns=[x for x in ['approved','executable','sa_init'] if x in b]);b['mode']='eggplant_stage2'
    fixed=pd.read_csv(review/'proposed_fixed_genotype_strict40.csv');bundle=ROOT/j['datasets'][1]['bundle_path']
    texts={k:(bundle/f'TMGRO048.{k}').read_text() for k in ['CUL','ECO','SPE']}
    names={k:next(l.split()[4 if k=='CUL' else 2:] for l in texts[k].splitlines() if l.startswith('@VAR#' if k=='CUL' else '@ECO#')) for k in ['CUL','ECO']}
    for r in fixed.itertuples():
        if r.name in set(b.name):continue
        # All other untouched fields stay fixed by the hashed templates. The
        # ECO TM field is not the registry's cardinal-temperature alias TM.
        if r.name!='PROSHF':continue
        loc='CUL' if r.name in names['CUL'] else 'ECO' if r.name in names['ECO'] else 'SPE'
        b.loc[len(b)]={c:'' for c in b.columns}|dict(name=r.name,init=r.value,lower=r.value,upper=r.value,status='fixed',pargp=loc+'_fixed',location=loc,file='TMGRO048.'+loc,cultivar='TM0008',ecotype='TM0001',mode='eggplant_stage2')
    env={'SASC_RATIO':.9,'ICNS_25SP':1.,'ICNS_26SP':1.,'PAGE_25SP':25.,'PENV_25SP':20.,'PAGE_26SP':24.,'PENV_26SP':20.,'SLPF_25SP':.93,'SLPF_26SP':.89,'SOIL_SLDR':.65,'KEP':.7}
    for n,v in env.items():
        loc='SOIL' if n.startswith(('SLPF','SOIL_')) else 'SPE' if n=='KEP' else 'IC'
        file='SOIL.SOL' if loc=='SOIL' else 'TMGRO048.SPE' if loc=='SPE' else 'XXQL2601.TMX'
        b.loc[len(b)]={c:'' for c in b.columns}|dict(name=n,init=v,lower=v,upper=v,status='fixed',pargp='fixed_environment',location=loc,file=file,cultivar='TM0008',ecotype='TM0001',mode='eggplant_stage2')
    assert b.status.eq('active').sum()==40 and not b.name.duplicated().any()
    b.to_csv(config/'approved_bounds_proposal.csv',index=False,encoding='utf-8-sig')
    result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools/freeze_bounds.py'),'--proposal',str(config/'approved_bounds_proposal.csv'),'--crop','eggplant','--bounds-id',ID,'--notes','User approved40;100x5;FLLF400;SLPF25=.93,26=.89'],capture_output=True,text=True,encoding='utf-8')
    (run/'freeze_bounds.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    obs=pd.read_csv(review/'proposed_calibration_targets.csv').fillna('');obs['obsnme']=[f's40_{i:04d}' for i in range(len(obs))]
    obs['approved']=True;obs['execution_enabled']=True;obs['final_weight']=obs.budget_multiplier
    # Encoded outputs already contain 1/sigma; PEST weights carry only budget scaling.
    obs.to_csv(config/'calibration_observations.csv',index=False)
    shutil.copy2(review/'proposed_objective_policy.csv',config/'approved_objective_policy.csv')
    allobs=pd.read_csv(review/'observation_evidence_catalog.csv').fillna('');val=allobs[allobs.role.eq('validation')].copy()
    val['obsnme']=[f'v25_{i:04d}' for i in range(len(val))];val.to_csv(config/'locked_validation_observations.csv',index=False)
    datasets=[]
    for ds in j['datasets']:
        z=dict(ds);z['roles']={z.pop('role'):z.pop('treatments')};datasets.append(z)
    runtime_files=['src/calibration/sa98_joint40.py','src/calibration/single_season_n.py','src/calibration/all12_joint.py','src/dssat/forward_sa98_joint40.py','src/dssat/run_dssat.py','src/dssat/array_expander.py','src/common/param_registry.py','src/common/input_manifest.py']
    frozen=ROOT/'data/parameter_registry/bounds_frozen/eggplant'/(ID+'.csv')
    d=dict(schema='approved_sa98_joint40_v1',approved=True,design_id=ID,approval=dict(user_statement=AUTH,recorded_at=stamp()),
           datasets=datasets,bounds_id=ID,bounds_sha256=legacy.sha(frozen),active_parameters=b[b.status.eq('active')].name.tolist(),
           ies_num_reals=100,noptmax=5,workers=6,seed=20261031,dssat_executable=j['dssat_executable'],dssat_executable_sha256=j['dssat_executable_sha256'],
           calibration_observations_sha256=legacy.sha(config/'calibration_observations.csv'),validation_sha256=legacy.sha(config/'locked_validation_observations.csv'),
           runtime_hashes={p:legacy.sha(ROOT/p) for p in runtime_files},ensemble_preflight_passed=False,scientific_status='science_pending',
           source_review_sha256=legacy.sha(review/'proposal.json'),selection_rule='Minimum complete calibration Phi across all iterations; no validation feedback',
           maximum_initial_native_candidates=2000,initialization='99 global Sobol feasible + center; no Phi filtering or historical warm start')
    seal(config,d)
    pd.DataFrame(dict(name=b.name,value=b.init)).to_csv(run/'initial_parameters.csv',index=False)
    # Immutable runtime copy. Each model process imports only this snapshot.
    cap=run/'source_snapshot';cap.mkdir()
    shutil.copytree(ROOT/'src',cap/'src',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT/'tools/parallel',cap/'tools/parallel',ignore=shutil.ignore_patterns('__pycache__'))
    (cap/'tools/calibration').mkdir(parents=True);shutil.copy2(__file__,cap/'tools/calibration'/Path(__file__).name)
    shutil.copytree(ROOT/'data/templates',cap/'data/templates',ignore=shutil.ignore_patterns('__pycache__'))
    for ds in datasets:shutil.copytree(ROOT/ds['bundle_path'],cap/ds['bundle_path'])
    for ext in ['csv','yaml']:
        dst=cap/'data/parameter_registry/bounds_frozen/eggplant'/f'{ID}.{ext}';dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(frozen.with_suffix('.'+ext),dst)
    shutil.copytree(config,cap/'configs/runs'/ID)
    (cap/'workspace').mkdir();shutil.copy2(d['dssat_executable'],cap/'workspace/DSCSM048.EXE')
    for binary_dir in ['pestpp-5.2.16-win']:
        shutil.copytree(ROOT/binary_dir,cap/binary_dir)
    write(run/'execution_authorization.json',dict(user_statement=AUTH,approved_at=stamp(),design=str(cap/'configs/runs'/ID/'design.json'),run_dir=str(run)))
    write(run/'pipeline_status.json',dict(status='prepared',phase='native_preflight_pending',updated_at=stamp()))
    return cap,run


def screen(task,design,run):
    name,values=task;folder=run/'initial_feasibility'/name;folder.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(folder/'parameters.csv',index=False)
    try:
        c=model.evaluate(design,folder/'parameters.csv',folder,preflight=True)
        return dict(name=name,accepted=True,values=values,prediction=c.pest_output.tolist(),phi=float(c.phi_contribution.sum()))
    except Exception as e:
        write(folder/'failure.json',dict(error=str(e),residual_filter_used=False));return dict(name=name,accepted=False,error=str(e))


def preflight(design,run):
    config=design.parent;d,b,obs=model.load_design(design,preflight=True);center=dict(zip(b.name,b.init));model.validate(center,b)
    base=screen(('base',center),design,run)
    accepted=[base] if base['accepted'] else []
    audits=[{k:v for k,v in base.items() if k not in ['values','prediction']}]
    active=b[b.status.eq('active')];points=qmc.Sobol(d=40,scramble=True,seed=d['seed']).random_base2(11)
    ordinal=0;native=1
    with cf.ThreadPoolExecutor(max_workers=6) as pool:
        while len(accepted)<100 and ordinal<len(points) and native<2000:
            batch=[]
            while len(batch)<min(6,100-len(accepted)) and ordinal<len(points):
                index=ordinal;v=center|dict(zip(active.name,active.lower.to_numpy()+points[index]*(active.upper-active.lower).to_numpy()));ordinal+=1
                try:v=model.validate(v,b)
                except Exception as e:
                    audits.append(dict(name=f'global_{index:05d}',accepted=False,error=str(e),phase='parameter_relations'));continue
                batch.append((f'global_{index:05d}',v))
            native+=len(batch)
            for r in pool.map(lambda task:screen(task,design,run),batch):
                audits.append({k:v for k,v in r.items() if k not in ['values','prediction']})
                if r['accepted']:accepted.append(r)
            pd.DataFrame(audits).to_csv(run/'initial_feasibility_audit.csv',index=False)
            write(run/'pipeline_status.json',dict(status='preflight',accepted=len(accepted),target=100,native_candidates=native,phase='native_initial_ensemble',updated_at=stamp()))
            print(f'Native preflight {len(accepted)}/100; attempted {native}',flush=True)
    if len(accepted)!=100:raise RuntimeError('Cannot form100 complete members within declared screening budget')
    if not base['accepted']:
        # Use first feasible ordinal, never lowest Phi or a fitted local domain.
        source_name=accepted[0]['name'];source=run/'initial_feasibility'/source_name
        shutil.copy2(run/'initial_parameters.csv',run/'nominal_center_parameters.csv')
        pd.DataFrame(accepted[0]['values'].items(),columns=['name','value']).to_csv(run/'initial_parameters.csv',index=False)
        shutil.copy2(source/'FormalObjectives.OUT',run/'initial_feasibility/base/FormalObjectives.OUT')
        accepted[0]['source_candidate']=source_name;accepted[0]['name']='base'
        d['feasible_base_source']=source_name
        d['initialization']='100 global Sobol feasible points; first ordinal is base; nominal center failed mature-fruit coverage; no Phi filtering'
    d['nominal_center_native_passed']=bool(base['accepted'])
    en=pd.DataFrame([r['values'] for r in accepted],index=[r['name'] for r in accepted]);en.columns=en.columns.str.lower()
    pred=pd.DataFrame([r['prediction'] for r in accepted],index=en.index,columns=obs.obsnme)
    en.to_csv(run/'initial_ensemble.csv');pred.to_csv(run/'initial_observation_ensemble.csv')
    d['ensemble_preflight_passed']=True;d['initial_ensemble_sha256']=legacy.sha(run/'initial_ensemble.csv');seal(config,d)
    build_case(design,run,en,obs,b)


def build_case(design,run,en,obs,b):
    work=run/'joint';work.mkdir()
    (work/'parameters.tpl').write_text('ptf ~\nname,value\n'+''.join(f'{r.name},~ {r.name.lower():<22} ~\n' for r in b.itertuples()),encoding='ascii')
    shutil.copy2(run/'initial_parameters.csv',work/'parameters.csv');shutil.copy2(run/'initial_feasibility/base/FormalObjectives.OUT',work/'FormalObjectives.OUT')
    (work/'objectives.ins').write_text('pif ~\n'+''.join(f'l1 w !{r.obsnme}!\n' for r in obs.itertuples()),encoding='ascii')
    pst=pyemu.Pst.from_io_files([str(work/'parameters.tpl')],[str(work/'parameters.csv')],[str(work/'objectives.ins')],[str(work/'FormalObjectives.OUT')],pst_path='.')
    for r in b.itertuples():pst.parameter_data.loc[r.name.lower(),['partrans','parval1','parlbnd','parubnd','pargp']]=['none' if r.status=='active' else 'fixed',en.loc['base',r.name.lower()],r.lower,r.upper,str(r.pargp).lower()]
    for r in obs.itertuples():pst.observation_data.loc[r.obsnme,['obsval','weight','obgnme']]=[0.,r.final_weight,r.family.lower()]
    pst.model_command=[f'"{sys.executable}" -X utf8 "{ROOT / "src/calibration/sa98_joint40.py"}" --design "{design}" --param-csv parameters.csv']
    pst.control_data.noptmax=5;pst.pestpp_options=dict(ies_num_reals=100,ies_include_base=True,ies_no_noise=True,ies_save_binary=False,
        ies_bad_phi_sigma=1e300,ies_initial_lambda=100.,ies_lambda_mults=[.1,1.,10.],lambda_scale_fac=[.05,.1,.25],ies_par_en='initial_ensemble.csv',rand_seed=20261031,
        ies_drop_conflicts=False,ies_pdc_sigma_distance=0.,ies_subset_size=30,panther_agent_no_ping_timeout_secs=600)
    en.to_csv(work/'initial_ensemble.csv');pst.write(str(work/'joint.pst'),version=1)
    check=pyemu.Pst(str(work/'joint.pst'));assert check.npar_adj==40 and check.nnz_obs==665
    (work/'run_manifest.yaml').write_text(yaml.safe_dump(dict(run_id=ID,n_params_active=40,n_obs=665,ies_num_reals=100,noptmax=5,agents=6,
        mode='eggplant_stage2',bounds_id=ID,batch_file='DSSBatch.v48',harvest_var='CHPDT',scientific_status='science_pending',minimum_member_retention=.98,design=str(design)),sort_keys=False),encoding='utf-8')


def finalize(design,run):
    d,b,obs=model.load_design(design);work=run/'joint';candidates=[]
    for op in work.glob('joint.*.obs.csv'):
        it=op.name.split('.')[1];pp=work/f'joint.{it}.par.csv'
        if not it.isdigit() or not pp.exists():continue
        o=pd.read_csv(op,index_col=0);p=pd.read_csv(pp,index_col=0);o.index=o.index.astype(str);p.index=p.index.astype(str)
        for real in o.index.intersection(p.index):
            y=o.loc[real,obs.obsnme].to_numpy(float)
            if not np.isfinite(y).all():continue
            v={r.name:float(p.loc[real,r.name.lower()]) for r in b.itertuples()}
            try:model.validate(v,b)
            except ValueError:continue
            candidates.append(dict(phi=float(np.square(y*obs.final_weight.to_numpy()).sum()),iteration=int(it),realization=real,parameter_file=str(pp)))
    if not candidates:raise RuntimeError('No complete selected candidate')
    pd.DataFrame(candidates).to_csv(run/'selection_audit.csv',index=False);best=min(candidates,key=lambda r:(r['phi'],r['iteration'],r['realization']))
    p=pd.read_csv(best['parameter_file'],index_col=0);p.index=p.index.astype(str);v={r.name:float(p.loc[best['realization'],r.name.lower()]) for r in b.itertuples()}
    selected=run/'best_calibration_parameters.csv';pd.DataFrame(v.items(),columns=['name','value']).to_csv(selected,index=False)
    compared=model.evaluate(design,selected,run/'selected_deterministic');phi=float(compared.phi_contribution.sum())
    if not np.isclose(phi,best['phi'],rtol=1e-6,atol=1e-8):raise RuntimeError('Selected Phi failed deterministic reproduction')
    write(run/'selection.json',best|dict(deterministic_phi=phi,validation_used=False))
    # Only after frozen calibration selection is validation allowed to run.
    if legacy.sha(design.parent/'locked_validation_observations.csv')!=d['validation_sha256']:raise ValueError('Validation catalog changed')
    val=pd.read_csv(design.parent/'locked_validation_observations.csv').fillna('');ds=next(x for x in d['datasets'] if x['season_id']=='25SP')
    native=model.simulate(run/'validation/_model',ds,v,d);model.extract(native,val,strict=False).to_csv(run/'validation_comparison.csv',index=False)
    boundary=[];index=b.set_index('name')
    for it in [4,5]:
        p=pd.read_csv(work/f'joint.{it}.par.csv',index_col=0)
        for name in d['active_parameters']:
            r=index.loc[name];x=(p[name.lower()]-r.lower)/(r.upper-r.lower)
            boundary.append(dict(iteration=it,name=name,near_lower=float(x.le(.02).mean()),near_upper=float(x.ge(.98).mean()),severe_lower=float(x.le(.005).mean()),severe_upper=float(x.ge(.995).mean()),selected_value=v[name]))
    pd.DataFrame(boundary).to_csv(run/'parameter_boundary_round4_5.csv',index=False)
    last=pd.read_csv(work/'joint.5.obs.csv',index_col=0);retention=len(last)/100
    native_gate=json.loads((work/'run_status.json').read_text(encoding='utf-8'))
    passed=retention>=.98 and native_gate.get('engineering_status')=='engineering_validated'
    write(run/'pipeline_status.json',dict(status='completed',phase='finished',selected_phi=phi,retained_members=len(last),member_retention=retention,
        engineering_status='engineering_validated' if passed else 'engineering_failed',scientific_status='science_pending_review' if passed else 'science_not_passed_engineering_gate',finished_at=stamp()))


def controller(design,run):
    try:
        preflight(design,run)
        write(run/'pipeline_status.json',dict(status='running',phase='ies',members=100,iterations=5,pid=os.getpid(),updated_at=stamp()))
        with (run/'parallel_controller.log').open('w',encoding='utf-8') as log:
            p=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools/parallel/run_parallel.py'),'--run-dir',str(run/'joint'),'--case','joint','--mode','ies','--n-agents','6','--wait'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if p.returncode:raise RuntimeError('Parallel controller exited with error')
        if 'analysis complete' not in (run/'joint/joint.rec').read_text(errors='replace').lower():raise RuntimeError('IES completion not confirmed')
        finalize(design,run)
    except Exception as e:
        write(run/'pipeline_status.json',dict(status='failed',error=str(e),updated_at=stamp()));raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--controller',action='store_true');p.add_argument('--design');p.add_argument('--run-dir');a=p.parse_args()
    if a.prepare:
        cap,run=prepare();print(json.dumps(dict(snapshot=str(cap),run=str(run)),ensure_ascii=False))
    elif a.controller:controller(Path(a.design).resolve(),Path(a.run_dir).resolve())
