"""Approved observed-only, single-seed Morris campaign with staged fail-stop QA."""
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd

NAME = 'sa_25sp_observed_morris86_seed20261030_r30_refNguard_20261030'
BOUNDS = 'eggplant_25sp_observed_morris_expanded86_refNguard_20261030'
BUNDLE = 'xxql2501_sa_observed_20261029'
PROFILE = 'eggplant_25sp_observed_expanded_morris_20261030_outputs.json'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write(p,value):
    Path(p).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def command(args,cwd=None,log=None,check=True):
    env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
    p=subprocess.run(list(map(str,args)),cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if log:Path(log).write_text(p.stdout+'\n'+p.stderr,encoding='utf-8')
    if check and p.returncode:raise RuntimeError(f'Command failed ({p.returncode}); log={log}: {p.stderr[-1500:]}')
    return p


def prepare():
    from src.common.input_manifest import verify_manifest_integrity
    verify_manifest_integrity(ROOT/'data/user/sa_bundles'/BUNDLE)
    run=ROOT/'workspace/runs'/NAME
    run.mkdir(parents=True,exist_ok=False)
    capsule=run/'source_snapshot';capsule.mkdir()
    for folder in ('src','tools/parallel'):
        for source in (ROOT/folder).rglob('*.py'):
            if '__pycache__' in source.parts:continue
            dst=capsule/source.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dst)
    dst=capsule/'tools/sa';dst.mkdir(parents=True)
    shutil.copy2(__file__,dst/Path(__file__).name)
    shutil.copytree(ROOT/'data/user/sa_bundles'/BUNDLE,capsule/'data/user/sa_bundles'/BUNDLE)
    templates=capsule/'data/templates';templates.mkdir(parents=True)
    for name in ('DSSAT48.INH','DSSAT48.INP','DSSATPRO.v48'):
        shutil.copy2(ROOT/'data/templates'/name,templates/name)
    genotype=templates/'genotype';genotype.mkdir()
    for name in ('TMGRO048.CUL','TMGRO048.ECO','TMGRO048.SPE'):
        shutil.copy2(ROOT/'data/user/sa_bundles'/BUNDLE/name,genotype/(name+'.base'))
    paths=[Path('configs/sa')/PROFILE]
    paths += [Path('data/parameter_registry/bounds_frozen/eggplant')/(BOUNDS+ext) for ext in ('.csv','.yaml')]
    paths += [Path('pestpp-5.2.16-win/bin/pestpp-sen.exe')]
    for relative in paths:
        target=capsule/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/relative,target)
    exe=capsule/'workspace/DSCSM048.EXE';exe.parent.mkdir();shutil.copy2(r'C:\DSSAT48\DSCSM048.EXE',exe)
    (capsule/'.gitignore').write_text('__pycache__/\n*.pyc\n',encoding='ascii')
    meta={'authorization':'User explicitly approved observed-only one-seed execution on 2026-10-30',
          'parent_checkout':str(ROOT),'model_sha256':sha(exe),
          'source_files':[{ 'path':p.relative_to(capsule).as_posix(),'sha256':sha(p)}
                          for p in sorted(capsule.rglob('*')) if p.is_file()]}
    write(capsule/'snapshot_provenance.json',meta)
    command(['git','init','--initial-branch=codex/observed-morris-20261030'],capsule)
    command(['git','add','.'],capsule)
    command(['git','-c','user.name=Codex','-c','user.email=codex@local.invalid','commit','-m','Freeze approved single-seed observed Morris runtime'],capsule)
    commit=command(['git','rev-parse','HEAD'],capsule).stdout.strip()
    assert not command(['git','status','--porcelain'],capsule).stdout.strip()
    write(run/'campaign_status.json',{'status':'prepared','source_commit':commit,'snapshot':str(capsule),
                                      'formal_seed':20261030,'formal_r':30,'cross_seed_analysis':False})
    print(str(run),flush=True)
    return run


def status(run,stage,**details):
    write(run/'campaign_status.json',{'status':stage,'updated_utc':datetime.now(timezone.utc).isoformat(),
        'formal_seed':20261030,'formal_r':30,'cross_seed_analysis':False,**details})


def run_vector(run,capsule,label,params):
    d=run/'preflight'/label;d.mkdir(parents=True,exist_ok=False)
    pd.DataFrame(sorted(params.items()),columns=['name','value']).to_csv(d/'params.csv',index=False)
    p=command([sys.executable,capsule/'src/sensitivity/sa_model.py','--workspace',d,
        '--batch',capsule/'data/user/sa_bundles'/BUNDLE/'DSSBatch.v48','--cultivar','TM0008',
        '--param-csv',d/'params.csv','--out',d/'responses.out',
        '--input-dir',capsule/'data/user/sa_bundles'/BUNDLE,
        '--output-profile',capsule/'configs/sa'/PROFILE],log=d/'forward.log',check=False)
    records=list((d/'_sa_records').glob('*/record.json'))
    record=json.loads(records[0].read_text(encoding='utf-8')) if records else {}
    return {'label':label,'exit_code':p.returncode,'record':str(records[0]) if records else '',
            'error':record.get('error',p.stderr[-1200:]),'elapsed_seconds':record.get('elapsed_seconds')}


def native_fixed_check(record,bundle):
    from src.common.experiment_inputs import parse_filex,filex_section_text
    record=Path(record)
    with zipfile.ZipFile(record.parent/'native.zip') as z:
        text=z.read('XXQL2501.TMX').decode('utf-8')
        # Native N inventory, before basal fertilizer: all eight treatments.
        lines=z.read('SoilNi.OUT').decode('utf-8').splitlines()
        inventories=[];header=None;first=False
        for line in lines:
            if line.startswith('*RUN'):first=True
            if line.startswith('@YEAR'):header=line.split();continue
            if first and header and line.strip() and line.split()[0]=='2025':
                row=dict(zip(header,line.split()))
                inventories.append([float(row['NITD']),float(row['NHTD'])]);first=False
        assert len(inventories)==8 and np.allclose(inventories,[63.6,22.2],atol=.051),inventories
        # Temporary readback text stays outside immutable source input.
        fx=record.parent/'readback.TMX';fx.write_text(text,encoding='utf-8')
        parsed=parse_filex(fx);source=parse_filex(bundle/'XXQL2501.TMX')
        for section in ('*IRRIGATION AND WATER MANAGEMENT','*FERTILIZERS (INORGANIC)','*HARVEST DETAILS'):
            assert filex_section_text(fx,section).strip()==filex_section_text(bundle/'XXQL2501.TMX',section).strip(),section
        count=0
        for line in filex_section_text(fx,'*SOIL ANALYSIS').splitlines():
            parts=line.split()
            if len(parts)==10 and parts[0].isdigit():
                assert abs(float(parts[-1])-.9*float(parts[3]))<=.0051,line
                count+=1
        assert count==80,count
        assert z.read('SOIL.SOL')==(bundle/'SOIL.SOL').read_bytes()
    return {'native_initial_n':inventories,'SASC_layers_checked':count,'management_unchanged':True,'soil_unchanged':True}


def build_case(run,capsule,dirname,r):
    d=run/dirname
    args=[sys.executable,capsule/'src/sensitivity/sa_build_sen_case.py',
          '--param-review',capsule/'data/parameter_registry/bounds_frozen/eggplant'/(BOUNDS+'.csv'),
          '--case-dir',d,'--input-dir',capsule/'data/user/sa_bundles'/BUNDLE,
          '--output-profile',capsule/'configs/sa'/PROFILE,'--morris-r',r,'--morris-p',6,
          '--morris-delta',.6,'--random-seed',20261030,
          '--run-type','sensitivity_preflight_case' if r==4 else 'sensitivity_formal_case']
    command(args,capsule,run/(dirname+'_build.log'))
    return d


def execute_case(run,capsule,d):
    p=command([sys.executable,capsule/'tools/parallel/run_parallel.py','--run-dir',d,
        '--case','sa_sen_morris','--mode','sen','--n-agents',6,'--wait'],
        cwd=capsule,log=run/(d.name+'_parallel.log'),check=False)
    if p.returncode:raise RuntimeError(f'{d.name} execution failed; see {d.name}_parallel.log')
    # Strict trajectory check independent of postprocessing response scope.
    sys.path.insert(0,str(capsule))
    from src.sensitivity.morris_audit import audit_morris_case
    from src.common.quality import assess_morris_audit
    audit=audit_morris_case(d)
    report=assess_morris_audit(audit)
    report.write(d/'morris_audit',stem='strict_trajectory_quality')
    report.require_pass()
    return audit


def postprocess(d,bounds_path,profile_path):
    """Independent normalized-coordinate EE reconstruction from native evidence."""
    profile=json.loads(profile_path.read_text(encoding='utf-8'))
    bounds=pd.read_csv(bounds_path).set_index('name');bounds.index=bounds.index.str.upper()
    x=pd.read_csv(d/'sa_sen_morris.sen.par.csv').set_index('run_id');x.columns=x.columns.str.upper()
    names=list(x.columns);k=len(names);r=len(x)//(k+1)
    assert k==86 and len(x)==r*(k+1)
    low=bounds.loc[names,'lower'].to_numpy();span=(bounds.loc[names,'upper']-bounds.loc[names,'lower']).to_numpy()
    records=[]
    for p in sorted((d/'_agents').glob('agent_*/_sa_records/*/record.json')):
        j=json.loads(p.read_text(encoding='utf-8'))
        if j['status']=='completed':records.append((p,j))
    rx=np.array([[j['parameters'][n] for n in names] for _,j in records])
    from scipy.spatial import cKDTree
    distance,indices=cKDTree((rx-low)/span).query((x.to_numpy()-low)/span)
    assert float(max(distance))<1e-4, float(max(distance))
    from src.sensitivity.output_contract import observation_names
    observations=observation_names(profile)
    selected=[records[i] for i in indices]
    y=np.array([[j['responses'].get(o,-99.) for o in observations] for _,j in selected],dtype=float)
    actual=np.array([[j['actual_parameters'][n] for n in names] for _,j in selected])
    for j,name in enumerate(observations):
        if not name.startswith('WN_'):
            y[y[:,j]==-99,j]=np.nan
    ranked=np.array([o in profile['ranking_observations'] for o in observations])
    assert np.isfinite(y[:,ranked]).all()
    ee=np.full((r,k,len(observations)),np.nan);nominal=np.full_like(ee,np.nan)
    step_rows=[]
    for trajectory in range(r):
        seen=set()
        for step in range(1,k+1):
            right=trajectory*(k+1)+step;left=right-1
            changed=np.flatnonzero(np.abs(x.iloc[right].to_numpy()-x.iloc[left].to_numpy())>1e-10)
            assert len(changed)==1
            i=int(changed[0]);assert i not in seen;seen.add(i)
            delta=(actual[right,i]-actual[left,i])/span[i]
            nominal_delta=(x.iloc[right,i]-x.iloc[left,i])/span[i]
            assert abs(delta)>1e-12
            collateral=np.flatnonzero(np.abs(actual[right]-actual[left])>1e-10)
            assert list(collateral)==[i],(names[i],collateral.tolist())
            ee[trajectory,i]=(y[right]-y[left])/delta
            nominal[trajectory,i]=(y[right]-y[left])/nominal_delta
            step_rows.append({'trajectory':trajectory,'step':step,'parameter':names[i],
                              'normalized_actual_step':delta,'normalized_nominal_step':nominal_delta})
    output=d/'single_seed_results';output.mkdir(exist_ok=True)
    pd.DataFrame(step_rows).to_csv(output/'actual_step_audit.csv',index=False)
    pd.DataFrame(y,columns=observations).to_csv(output/'Y.csv',index_label='run_id')
    pd.DataFrame(actual,columns=names).to_csv(output/'X_actual.csv',index_label='run_id')
    np.savez_compressed(output/'elementary_effects.npz',actual=ee,nominal=nominal,parameters=names,observations=observations)
    absolute=np.abs(ee);mu=np.nanmean(ee,axis=0);mustar=np.nanmean(absolute,axis=0);sigma=np.nanstd(ee,axis=0,ddof=1)
    rng=np.random.default_rng(20261030);counts=rng.multinomial(r,np.full(r,1/r),size=1000)
    boot=counts@np.nan_to_num(absolute).reshape(r,-1)/r
    ci=np.quantile(boot,[.025,.975],axis=0).reshape(2,k,len(observations))
    ci[:,~np.isfinite(ee).all(axis=0)]=np.nan
    effects=pd.DataFrame([{'parameter':n,'observation':o,'mu':mu[i,j],'mu_star':mustar[i,j],
         'sigma':sigma[i,j],'mu_star_ci_low':ci[0,i,j],'mu_star_ci_high':ci[1,i,j],
         'valid_effects':int(np.isfinite(ee[:,i,j]).sum()),'ranked':bool(ranked[j])}
         for i,n in enumerate(names) for j,o in enumerate(observations)])
    effects.to_csv(output/'morris_response_effects.csv',index=False,encoding='utf-8-sig')
    totals=mustar[:,ranked].sum(axis=0)
    degenerate=[o for o,total in zip(np.array(observations)[ranked],totals) if total<=1e-12]
    quality={'seed':20261030,'trajectories':r,'parameters':k,'outputs':len(observations),
             'ranked_outputs':int(ranked.sum()),'cross_seed_analysis':False,
             'missing_ranked_outputs':[],'degenerate_ranked_outputs':degenerate,
             'science_status':'science_pending','parameter_record_match_max_distance':float(max(distance))}
    write(output/'single_seed_quality.json',quality)
    if degenerate:raise ValueError('Ranked responses have no signal; see single_seed_quality.json')
    from src.sensitivity.morris_multiseed import _feature_metadata
    lookup={f:g for g,fs in profile['response_groups'].items() for f in fs}
    f=effects[effects.ranked].copy();f['relative_effect']=f.mu_star/f.groupby('observation').mu_star.transform('sum')
    f['feature_family']=[_feature_metadata(o)[1] for o in f.observation]
    f['response_group']=f.feature_family.map(lookup);assert f.response_group.notna().all()
    feature=f.groupby(['response_group','feature_family','parameter'],as_index=False).relative_effect.mean()
    groups=feature.groupby(['response_group','parameter'],as_index=False).relative_effect.mean()
    group_domain={g:domain for domain,gs in profile['ranking_domains'].items() for g in gs}
    groups['ranking_domain']=groups.response_group.map(group_domain)
    ranking=groups.groupby(['ranking_domain','parameter'],as_index=False).relative_effect.mean().rename(columns={'relative_effect':'score'})
    ranking=ranking.sort_values(['ranking_domain','score','parameter'],ascending=[True,False,True])
    ranking['rank']=ranking.groupby('ranking_domain').cumcount()+1
    groups.to_csv(output/'morris_group_scores.csv',index=False,encoding='utf-8-sig')
    ranking.to_csv(output/'morris_rankings.csv',index=False,encoding='utf-8-sig')
    ranking[ranking['rank']<=15].to_csv(output/'top15_proposal.csv',index=False,encoding='utf-8-sig')
    return quality,ranking


def campaign(run,resume=False):
    capsule=run/'source_snapshot';started=time.perf_counter()
    try:
        b=pd.read_csv(capsule/'data/parameter_registry/bounds_frozen/eggplant'/(BOUNDS+'.csv'))
        center=dict(zip(b.name,b.init));fixed=dict(zip(b.loc[b.status.eq('fixed'),'name'],b.loc[b.status.eq('fixed'),'init']))
        if resume:
            status(run,'preflight_replaying_same_failed_vectors')
            results=pd.read_csv(run/'preflight_results.csv').fillna('').to_dict('records')
            for i,item in enumerate(results):
                if int(item['exit_code']):
                    old=item.copy()
                    params=pd.read_csv(run/'preflight'/item['label']/'params.csv').set_index('name').value.to_dict()
                    results[i]=run_vector(run,capsule,'replay_'+item['label'],params)
                    results[i]['original_attempt']=old
            write(run/'same_vector_recovery.json',[x for x in results if 'original_attempt' in x])
        else:
            status(run,'preflight_baselines')
            initial=run_vector(run,capsule,'source_baseline',fixed)
            assert initial['exit_code']==0,initial
            native=native_fixed_check(initial['record'],capsule/'data/user/sa_bundles'/BUNDLE)
            write(run/'native_fixed_readback.json',native)
            centers=[run_vector(run,capsule,'center_1',center),run_vector(run,capsule,'center_2',center)]
            assert all(t['exit_code']==0 for t in centers),centers
            first=json.loads(Path(centers[0]['record']).read_text(encoding='utf-8'))['responses']
            second=json.loads(Path(centers[1]['record']).read_text(encoding='utf-8'))['responses']
            assert first==second,'Identical center baseline not deterministic'
            status(run,'preflight_boundaries',completed=3,planned=175)
            vectors=[]
            for row in b[b.status.eq('active')].itertuples():
                for level in ('lower','upper'):
                    params={**center,row.name:float(getattr(row,level))}
                    vectors.append((row.name+'_'+level,params))
            results=[initial,*centers]
            with ThreadPoolExecutor(max_workers=6) as pool:
                futures=[pool.submit(run_vector,run,capsule,label,params) for label,params in vectors]
                for future in as_completed(futures):
                    results.append(future.result())
                    if len(results)%12==0:status(run,'preflight_boundaries',completed=len(results),planned=175)
        pd.DataFrame(results).to_csv(run/'preflight_results.csv',index=False,encoding='utf-8-sig')
        failures=[x for x in results if x['exit_code']]
        if failures:
            write(run/'preflight_failures.json',failures)
            raise RuntimeError(f'{len(failures)} baseline/boundary evaluations failed; no domain repair performed')
        status(run,'pilot_running',completed_preflight=len(results))
        pilot=build_case(run,capsule,'pilot_r4',4);execute_case(run,capsule,pilot)
        pilot_quality,_=postprocess(pilot,capsule/'data/parameter_registry/bounds_frozen/eggplant'/(BOUNDS+'.csv'),capsule/'configs/sa'/PROFILE)
        assert pilot_quality['trajectories']==4
        status(run,'formal_running',pilot_completed=True,planned=2610)
        formal=build_case(run,capsule,'formal_r30',30);execute_case(run,capsule,formal)
        # The pilot is always reported separately; no assumption about RNG prefixes.
        px=pd.read_csv(pilot/'sa_sen_morris.sen.par.csv');fx=pd.read_csv(formal/'sa_sen_morris.sen.par.csv')
        write(run/'pilot_prefix_check.json',{'same_prefix':bool(np.allclose(px.to_numpy(),fx.iloc[:len(px)].to_numpy())),'pilot_reused':False})
        quality,ranking=postprocess(formal,capsule/'data/parameter_registry/bounds_frozen/eggplant'/(BOUNDS+'.csv'),capsule/'configs/sa'/PROFILE)
        status(run,'deterministic_replays')
        replays=[]
        for idx in (0,len(fx)//2,len(fx)-1):
            params={**fixed,**{str(k).upper():float(v) for k,v in fx.iloc[idx].to_dict().items() if k!='run_id'}}
            item=run_vector(run,capsule,f'replay_{idx}',params);assert item['exit_code']==0,item
            record=json.loads(Path(item['record']).read_text(encoding='utf-8'))
            reference=pd.read_csv(formal/'single_seed_results/Y.csv',index_col=0).loc[idx]
            for name in json.loads((capsule/'configs/sa'/PROFILE).read_text(encoding='utf-8'))['ranking_observations']:
                assert np.isclose(record['responses'][name],reference[name],rtol=1e-9,atol=1e-6)
            replays.append(item)
        write(run/'deterministic_replays.json',replays)
        lines=['# 2025春 observed 单seed Morris 结果','',
               'seed=20261030，86参数，30条完整轨迹，2610次正式计算。仅observed包；未分析跨seed稳定性。',
               '','模型与轨迹工程验证完成；科学解释仍受2025春实测背景、参数工作域及输入先验限制。',
               'μ*相对份额不是方差贡献率；Morris网格端点不是率定触边。','']
        for domain,g in ranking.groupby('ranking_domain',sort=False):
            lines += ['## '+domain,'','|排名|参数|相对效应份额|','|---:|---|---:|']
            lines += [f'|{row.rank}|{row.parameter}|{row.score:.4f}|' for row in g.head(15).itertuples()]
            lines.append('')
        (run/'Morris结果报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        status(run,'completed',formal_case=str(formal),quality=quality,elapsed_seconds=time.perf_counter()-started)
    except Exception as exc:
        import traceback
        (run/'campaign_error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        status(run,'stopped_for_review',error=f'{type(exc).__name__}: {exc}',elapsed_seconds=time.perf_counter()-started)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--run-dir')
    parser.add_argument('--resume-after-boundaries',action='store_true')
    args=parser.parse_args()
    if args.prepare:prepare()
    elif args.run_dir:campaign(Path(args.run_dir).resolve(),resume=args.resume_after_boundaries)
    else:parser.error('Select --prepare or --run-dir')
