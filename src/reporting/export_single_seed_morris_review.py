"""Read-only native-output recovery and frozen single-seed Morris figure data.

No model calls, no plotting, and no changes to the original full-design gate.
"""
from pathlib import Path
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import re
import sys
import zipfile

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from src.sensitivity.strict_forward import read_genotype_parameters

TRTS = [2,3,4,5,10,11,12,13]
FEATURES = ['ADAPS','PDFPS','LAI_AUC','LAI_PEAK','LAI_END','FRUITD_END','FRESH_END','CUMHARVEST_DAP50']
PRIMARY = ['ADAPS','LAI_AUC','FRUITD_END']
LABELS = {'ADAPS':('Anthesis','d'),'PDFPS':('First seed','d'),
          'LAI_AUC':('Seasonal LAI integral','LAI d'),'LAI_PEAK':('Peak LAI','m2 m-2'),
          'LAI_END':('End-season LAI','m2 m-2'),
          'FRUITD_END':('Cumulative dry harvest','kg DM ha-1'),
          'FRESH_END':('Cumulative fresh harvest','kg fresh ha-1'),
          'CUMHARVEST_DAP50':('50% cumulative dry harvest DAP','d')}


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,j): Path(p).write_text(json.dumps(j,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def daily(text, columns):
    result={};run=None;header=None
    for line in text.splitlines():
        m=re.match(r'^\*RUN\s+(\d+)',line)
        if m:run=int(m.group(1));header=None;continue
        if line.startswith('@YEAR'):
            header=line.split();positions={c:header.index(c) for c in ['DAP',*columns]};continue
        if run is None or header is None or not line.strip() or not line.lstrip()[0].isdigit():continue
        parts=line.split()
        if len(parts)<len(header):continue
        row={c:float(parts[i]) for c,i in positions.items()}
        result.setdefault(run,[]).append(row)
    return result


def evaluate(text):
    header=None;result=[]
    for line in text.splitlines():
        if line.startswith('@RUN'):header=line.split();continue
        if header and line.strip() and line.lstrip()[0].isdigit():
            parts=line.split()
            if len(parts)>=len(header):result.append(dict(zip(header,parts)))
    return result


def dap50(dap,harvest):
    if len(dap)==0 or harvest[-1]<=0 or (np.diff(harvest)<0).any():return np.nan
    target=.5*harvest[-1]
    i=int(np.flatnonzero(harvest>=target)[0])
    if i==0:return float(dap[0])
    return float(dap[i-1]+(target-harvest[i-1])/(harvest[i]-harvest[i-1])*(dap[i]-dap[i-1]))


def extract_record(path,out):
    record=json.loads(path.read_text(encoding='utf-8'));archive=path.parent/'native.zip'
    values=np.full((8,len(FEATURES)),np.nan);time_rows=[]
    with zipfile.ZipFile(archive) as z:
        e=evaluate(z.read('Evaluate.OUT').decode('utf-8',errors='replace'))
        pg=daily(z.read('PlantGro.OUT').decode('utf-8',errors='replace'),['LAID'])
        fw=daily(z.read('FreshWt.OUT').decode('utf-8',errors='replace'),['CHPDT','CHFPW'])
        assert len(e)==8 and {int(v['TN']) for v in e}==set(TRTS),path
        for row in e:
            treatment=int(row['TN']);run=int(row['@RUN']);index=TRTS.index(treatment)
            g=pg[run];f=fw[run]
            gd=np.array([r['DAP'] for r in g]);lai=np.array([r['LAID'] for r in g]);
            fd=np.array([r['DAP'] for r in f]);dry=np.array([r['CHPDT'] for r in f]);fresh=np.array([r['CHFPW'] for r in f])
            assert gd[-1]>=119 and fd[-1]>=119,(path,treatment,gd[-1],fd[-1])
            assert (np.diff(gd)>0).all() and (np.diff(fd)>0).all(),path
            assert np.isfinite(lai).all() and (lai>=0).all() and (dry>=0).all() and (fresh>=0).all(),path
            vals=[float(row['ADAPS']),float(row['PDFPS']),float(np.trapezoid(lai,gd)),float(max(lai)),float(lai[-1]),float(dry[-1]),float(fresh[-1]),dap50(fd,dry)]
            vals=[np.nan if v==-99 else v for v in vals]
            values[index]=vals
            time_rows.append({'treatment':treatment,'LAI_first_DAP':float(gd[0]),'LAI_last_DAP':float(gd[-1]),'harvest_last_DAP':float(fd[-1]),'dry_harvest':float(dry[-1]),'DAP50_estimable':bool(np.isfinite(vals[-1]))})
        actual=record.get('actual_parameters',{})
        if not actual:
            recovered=out/'recovered_genotypes'/path.parent.name;recovered.mkdir(parents=True)
            for name in ('TMGRO048.CUL','TMGRO048.ECO','TMGRO048.SPE'):(recovered/name).write_bytes(z.read(name))
            actual=read_genotype_parameters(recovered)
        native_success='Evaluate.OUT generated successfully' in z.read('console.txt').decode('utf-8',errors='replace')
    for name,target in [('SASC_RATIO',.9),('ICNS_25SP',1.),('ICNS_26SP',1.)]:
        assert abs(record['parameters'][name]-target)<1e-12
    # Compare independently recomputed scalar values to successful forward records.
    errors=[]
    if record['status']=='completed':
        for t,trt in enumerate(TRTS):
            for j,feature in enumerate(FEATURES):
                key=f'TN{trt}_{feature}'
                if key in record['responses'] and np.isfinite(values[t,j]):
                    errors.append(abs(values[t,j]-float(record['responses'][key])))
    assert native_success,path
    return {'path':str(path),'record':record,'values':values,'actual':actual,'times':time_rows,
            'max_recompute_error':max(errors,default=0.),'zip_sha256':sha(archive),'record_sha256':sha(path)}


def elementary_effects(x,actual,y,span):
    k=x.shape[1];r=len(x)//(k+1);ee=np.full((r,k,*y.shape[1:]),np.nan);steps=[]
    for trajectory in range(r):
        used=set()
        for step in range(1,k+1):
            right=trajectory*(k+1)+step;left=right-1
            changed=np.flatnonzero(abs(x[right]-x[left])>1e-10)
            written=np.flatnonzero(abs(actual[right]-actual[left])>1e-10)
            assert len(changed)==1 and list(changed)==list(written),(trajectory,step,changed,written)
            parameter=int(changed[0]);assert parameter not in used;used.add(parameter)
            delta=(actual[right,parameter]-actual[left,parameter])/span[parameter]
            assert abs(delta)>1e-12
            ee[trajectory,parameter]=(y[right]-y[left])/delta
            steps.append({'trajectory':trajectory,'step':step,'parameter_index':parameter,
                          'actual_delta':delta,'nominal_delta':(x[right,parameter]-x[left,parameter])/span[parameter]})
        assert len(used)==k
    return ee,steps


def knee(scores):
    scores=np.asarray(scores,float)
    if len(scores)<3 or max(scores)==min(scores):return 1
    x=np.linspace(0,1,len(scores));y=(scores-scores[-1])/(scores[0]-scores[-1])
    return int(np.argmax(1-x-y)+1)


def export(case,out,allow_demo):
    if not allow_demo:raise ValueError('Current full-design status is unvalidated; explicit --allow-unvalidated-demo is required')
    out.mkdir(parents=True,exist_ok=False)
    profile=json.loads((case/'runtime/config/output_profile.json').read_text(encoding='utf-8'))
    bounds_path=next((case.parent/'source_snapshot/data/parameter_registry/bounds_frozen/eggplant').glob('*refNguard*.csv'))
    bounds=pd.read_csv(bounds_path).set_index('name');bounds.index=bounds.index.str.upper()
    for item in json.loads((case/'runtime/runtime_manifest.json').read_text(encoding='utf-8'))['files']:
        assert sha(case/'runtime'/item['path'])==item['sha256'],item['path']
    xframe=pd.read_csv(case/'sa_sen_morris.sen.par.csv').set_index('run_id');xframe.columns=xframe.columns.str.upper()
    names=list(xframe.columns);k=len(names);r=len(xframe)//(k+1);assert (k,r)==(86,30)
    low=bounds.loc[names,'lower'].to_numpy();span=(bounds.loc[names,'upper']-bounds.loc[names,'lower']).to_numpy()
    paths=sorted((case/'_agents').glob('agent_*/_sa_records/*/record.json'));assert len(paths)==2610
    records=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(extract_record,p,out) for p in paths]
        for f in as_completed(futures):
            records.append(f.result())
            if len(records)%300==0:print(f'native outputs verified {len(records)}/2610',flush=True)
    nominal=np.array([[j['record']['parameters'][n] for n in names] for j in records])
    distance,indices=cKDTree((nominal-low)/span).query((xframe.to_numpy()-low)/span)
    assert max(distance)<1e-8 and len(set(indices))==2610
    records=[records[i] for i in indices];y=np.array([j['values'] for j in records])
    actual=np.array([[j['actual'][n] for n in names] for j in records])
    for feature in [*PRIMARY,'FRESH_END']:
        assert np.isfinite(y[:,:,FEATURES.index(feature)]).all(),feature
    max_error=max(j['max_recompute_error'] for j in records);assert max_error<1e-7,max_error
    # The scalar response is the equal-weight mean of all eight treatments,
    # before taking |EE| or its dispersion. Sigma is never averaged across runs.
    mean_y=y.mean(axis=1);ee,steps=elementary_effects(xframe.to_numpy(),actual,mean_y,span)
    ee_treatment,_=elementary_effects(xframe.to_numpy(),actual,y,span)
    np.savez_compressed(out/'native_reconstruction.npz',Y_treatment=y,Y_mean=mean_y,X=xframe.to_numpy(),X_actual=actual,
                        EE_mean=ee,EE_treatment=ee_treatment,parameters=names,features=FEATURES,treatments=TRTS)
    pd.DataFrame(mean_y,columns=FEATURES).to_csv(out/'scalar_responses.csv',index_label='run_id')
    pd.DataFrame(actual,columns=names).to_csv(out/'actual_parameters.csv',index_label='run_id')
    pd.DataFrame([{**s,'parameter':names[s['parameter_index']]} for s in steps]).to_csv(out/'step_audit.csv',index=False)
    pd.DataFrame([{'run_id':i,**t} for i,j in enumerate(records) for t in j['times']]).to_csv(out/'terminal_and_DAP50_audit.csv',index=False)
    provenance=pd.DataFrame([{'run_id':i,'record_path':j['path'],'original_status':j['record']['status'],
        'original_error':j['record']['error'],'record_sha256':j['record_sha256'],'native_zip_sha256':j['zip_sha256']} for i,j in enumerate(records)])
    provenance.to_csv(out/'source_records.csv',index=False,encoding='utf-8-sig')
    primary_indices=[FEATURES.index(n) for n in PRIMARY];selected_indices=[*primary_indices,FEATURES.index('FRESH_END'),FEATURES.index('LAI_PEAK')]
    selected_ee=ee[:,:,selected_indices];mu=selected_ee.mean(axis=0);ms=np.abs(selected_ee).mean(axis=0);sd=selected_ee.std(axis=0,ddof=1)
    assert np.isfinite(selected_ee).all()
    rng=np.random.default_rng(20261030);counts=rng.multinomial(r,np.full(r,1/r),size=1000)
    boot=(counts@np.abs(selected_ee).reshape(r,-1)/r).reshape(1000,k,len(selected_indices))
    ci=np.quantile(boot,[.025,.975],axis=0)
    scalar_rows=[]
    for j,feature_index in enumerate(selected_indices):
        response=FEATURES[feature_index];order=np.lexsort((np.array(names),-ms[:,j]));ranks=np.empty(k,int);ranks[order]=np.arange(1,k+1)
        for i,name in enumerate(names):
            scalar_rows.append({'response':response,'response_label':LABELS[response][0],'unit':LABELS[response][1],
                'parameter':name,'rank':int(ranks[i]),'mu':mu[i,j],'mu_star':ms[i,j],'sigma':sd[i,j],
                'ci_low':ci[0,i,j],'ci_high':ci[1,i,j],'relative_mu_star':ms[i,j]/ms[:,j].sum(),
                'sigma_over_mu_star':sd[i,j]/ms[i,j] if ms[i,j]>0 else np.nan,'n_valid':r})
    effects=pd.DataFrame(scalar_rows)
    primary_ms=ms[:,:3];score=(primary_ms/primary_ms.sum(axis=0)).mean(axis=1)
    ranking=pd.DataFrame({'parameter':names,'score':score}).sort_values(['score','parameter'],ascending=[False,True]).reset_index(drop=True)
    ranking['rank']=np.arange(1,k+1);ranking['cumulative']=ranking.score.cumsum();elbow=knee(ranking.score)
    k90=int(np.flatnonzero(ranking.cumulative>=.90)[0]+1);k95=int(np.flatnonzero(ranking.cumulative>=.95)[0]+1)
    core=set(ranking.head(elbow).parameter)
    per_response_top=set(effects[effects.response.isin(PRIMARY)&effects['rank'].le(5)].parameter)
    ranking['elbow_core']=ranking['rank']<=elbow;ranking['response_top5']=ranking.parameter.isin(per_response_top)
    ranking['display_core']=ranking.parameter.isin(core|per_response_top)
    effects=effects.merge(ranking[['parameter','elbow_core','response_top5','display_core']],on='parameter',validate='many_to_one')
    ranking.to_csv(out/'balanced_rankings.csv',index=False,encoding='utf-8-sig');effects.to_csv(out/'scalar_morris_effects.csv',index=False,encoding='utf-8-sig')
    coretable=effects[effects.display_core].copy();coretable.to_csv(out/'core_parameters.csv',index=False,encoding='utf-8-sig')
    knees=[]
    for b in boot[:,:,:3]:
        z=(b/b.sum(axis=0)).mean(axis=1);knees.append(knee(np.sort(z)[::-1]))
    # Compare treatment-mean and mean-of-treatment effects as a cancellation audit.
    cancellation=[]
    for feature in PRIMARY:
        j=FEATURES.index(feature);pooled=np.abs(ee_treatment[:,:,:,j]).mean(axis=(0,2));of_mean=np.abs(ee[:,:,j]).mean(axis=0)
        cancellation += [{'response':feature,'parameter':n,'mu_star_of_treatment_mean':of_mean[i],
                          'mean_treatment_mu_star':pooled[i],'ratio':of_mean[i]/pooled[i] if pooled[i]>0 else np.nan} for i,n in enumerate(names)]
    pd.DataFrame(cancellation).to_csv(out/'treatment_cancellation_audit.csv',index=False)
    audit=json.loads((case/'morris_audit/morris_run_audit.json').read_text(encoding='utf-8'))['summary']
    summary={'run_id':case.parent.name,'case':str(case),'seed':20261030,'trajectories':r,'parameters':k,'model_evaluations':len(xframe),
        'original_full_design':audit,'raw_model_runs_complete':2610,'focused_outputs_complete_trajectories':30,
        'focused_outputs':PRIMARY,'additional_outputs':['FRESH_END','LAI_PEAK'],
        'missing_DAP50_points':int((~np.isfinite(y[:,:,-1])).any(axis=1).sum()),
        'zero_dry_harvest_treatment_points':int((y[:,:,FEATURES.index('FRUITD_END')]==0).sum()),
        'max_independent_recompute_absolute_error':max_error,'sampling_matrix_match_distance':float(max(distance)),
        'original_design_status':'failed_response_estimability','focused_scope_status':'engineering_validated',
        'data_status':'science_pending','cross_seed_analysis':False,
        'aggregation':'Equal-weight average of 8 treatment outputs before EE statistics; 3 response-normalized mu* shares equally weighted for elbow.',
        'elbow_rank':elbow,'elbow_coverage':float(ranking.iloc[elbow-1].cumulative),'k90':k90,'k95':k95,
        'core_parameters':ranking.head(elbow).parameter.tolist(),'display_core_parameters':sorted(core|per_response_top),
        'bootstrap_elbow_q025_q975':list(map(float,np.quantile(knees,[.025,.975]))),
        'top5_by_response':{n:effects[effects.response.eq(n)].sort_values('rank').head(5).parameter.tolist() for n in [*PRIMARY,'FRESH_END','LAI_PEAK']}}
    write(out/'review_summary.json',summary)
    artifacts=[{'path':p.name,'sha256':sha(p),'role':p.stem} for p in sorted(out.iterdir()) if p.is_file()]
    manifest={'schema_version':1,'bundle_type':'morris_single_seed_review','run_id':case.parent.name,'data_status':'science_pending',
              'selected_scope_status':'engineering_validated','original_full_design_passed':False,'seed':20261030,'trajectories':30,
              'parameters':86,'scientific_status_promoted':False,'artifacts':artifacts,
              'input_bundle_manifest_sha256':sha(case/'runtime/input/input_manifest.json'),
              'bounds_sha256':sha(bounds_path),'sample_matrix_sha256':sha(case/'sa_sen_morris.sen.par.csv')}
    write(out/'paper_data_manifest.json',manifest)
    print(json.dumps(summary,ensure_ascii=True),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case-dir',required=True);p.add_argument('--out-dir',required=True);p.add_argument('--allow-unvalidated-demo',action='store_true');args=p.parse_args()
    export(Path(args.case_dir).resolve(),Path(args.out_dir).resolve(),args.allow_unvalidated_demo)
