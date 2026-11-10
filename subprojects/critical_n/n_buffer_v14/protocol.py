"""Frozen dual-spring model protocol. No physiological changes in this module."""
from pathlib import Path
import hashlib,json,os,re,shutil,subprocess,time,uuid
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent
import sys
sys.path.insert(0,str(ROOT/'runtime'))
from src.calibration.single_season_n import read_native,extract_observations as point_extract,read_injected_parameters
from src.calibration import reviewfix_joint as reference
from src.calibration.water_n_joint import water_balance100
from src.common.param_registry import PHYSICAL_BOUNDS
from src.dssat import run_dssat as runner
from src.dssat.forward_joint import inject_phosphorus
from src.dssat.forward_water_n import inject_environment
from native_precision import improve_fields

SIGNED={'N_FRESH_CONTRAST','W_FRESH_CONTRAST','N_ADJACENT_FRESH_CONTRAST','WB100_INTERVAL'}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write_json(p,value):
    p=Path(p);temp=p.with_name(p.name+'.writing')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');temp.replace(p)

def validate(values,bounds):
    if set(values)!=set(bounds.name) or bounds.name.duplicated().any():raise ValueError('Parameter identity coverage')
    for row in bounds.itertuples():
        x=values[row.name]
        if not np.isfinite(x) or not row.lower-1e-10<=x<=row.upper+1e-10:raise ValueError('Frozen bound '+row.name)
        if row.status=='fixed' and abs(x-row.init)>1e-9:raise ValueError('Fixed parameter '+row.name)
        if row.name in PHYSICAL_BOUNDS and not PHYSICAL_BOUNDS[row.name][0]<=x<=PHYSICAL_BOUNDS[row.name][1]:raise ValueError('Physical bound '+row.name)
    if not values['CNC_A']>values['CNC_NC_INF']>0 or min(values['CNC_B'],values['CNC_W0'])<=0:raise ValueError('CNC monotonicity')
    if values['FRLFF']+values['FRSTMF']>1:raise ValueError('Negative root partition')
    for organ in ['LF','ST','RT']:
        if not values['PRO'+organ+'F']<=values['PRO'+organ+'G']<=values['PRO'+organ+'I']:raise ValueError('Protein order '+organ)
    # IPDMND in the frozen native binary requires space for demand dilution,
    # not merely F <= G <= I. These are native constraints, not new biology.
    for organ,minimum in [('LF',.0125),('ST',.00625)]:
        if values['PRO'+organ+'I']-values['PRO'+organ+'G'] < minimum-6.25e-7:
            raise ValueError('Protein dilution margin '+organ)
    if not 0<=values['NB_TARGET_RATIO']<=1 or not 0<=values['NB_STEM_TARGET_RATIO']<=1:raise ValueError('Reserve target ratio')
    if values['NB_CAPACITY']<.02:raise ValueError('Capacity below protection coefficient')
    if values['XMAGE']>=values['XFPHT']:raise ValueError('Maturity after terminal harvest age')
    for names in [('TB1','TO11','TO21','TM1'),('TB2','TO12','TO22','TM2'),('FNPGN1','FNPGN2','FNPGN3')]:
        if not all(values[a]<values[b] for a,b in zip(names,names[1:])):raise ValueError('Ordered response '+str(names))

def inject(work,values,slpf,precision=True):
    before=Path.cwd();previous=os.environ.get('DSSAT_SPE_BASE')
    try:
        os.chdir(work);os.environ['DSSAT_SPE_BASE']=str(work/'TMGRO048.SPE.base')
        runner.PARAM_CSV='parameters.csv';runner.BATCH_FILE='DSSBatch.v48'
        runner.update_cul_file(param_csv_path='parameters.csv',target_cultivar='TM0008')
        runner.update_eco_file(param_csv_path='parameters.csv',target_ecotype='TM0001')
        runner.update_spe_file(param_csv_path='parameters.csv')
        inject_phosphorus(runner.SPE_FILE,values);inject_environment(work,values);reference.inject_cnc_fields(work,values)
        if precision: improve_fields(work,values)
        capacity=values['NB_CAPACITY'];protect=.02
        card=[1.,values['NB_KMOB'],values['NB_KFILL'],protect,
            protect+values['NB_TARGET_RATIO']*(capacity-protect),capacity,.10,0.,values['NB_SOIL_ALPHA'],1.,
            values['NB_STEM_BMULT'],protect+values['NB_STEM_TARGET_RATIO']*(capacity-protect),
            values['NB_BETA_GROW'],values['NB_ALPHA_H'],values['NB_ALPHA_L'],values['NB_ROOT_DEPTH']]
        fields=[f'{x:6.3f}'for x in card[:15]]+[f'{card[15]:6.1f}']
        if any(len(x)!=6 for x in fields):raise ValueError('NBUF field width')
        with(work/'TMGRO048.SPE').open('a',encoding='ascii')as handle:handle.write('\n!*ORGAN NITROGEN RESERVES AND BUFFER DILUTION\n'+''.join(fields)+'\n')
        path=work/'SOIL.SOL';lines=path.read_text().splitlines(True);indices=[i for i,l in enumerate(lines)if l.startswith('@ SCOM')]
        if len(indices)!=1:raise ValueError('One explicit soil profile required')
        i=indices[0]+1;lines[i]=lines[i][:36]+f'{slpf:6.3f}'+lines[i][42:];path.write_text(''.join(lines))
        return card
    finally:
        os.chdir(before)
        if previous is None:os.environ.pop('DSSAT_SPE_BASE',None)
        else:os.environ['DSSAT_SPE_BASE']=previous

def anthesis(work,excode,expected):
    header=None;result={}
    for line in(work/'Evaluate.OUT').read_text().splitlines():
        if line.startswith('@RUN'):header=line.lstrip('@').split()
        elif header and line.split()and line.split()[0].isdigit():
            parts=line.split()
            if len(parts)!=len(header):raise ValueError('Malformed Evaluate row')
            row=dict(zip(header,parts))
            if not row['EXCODE'].startswith(excode):continue
            trt=int(row['TN']);value=float(row['ADAPS'])
            if trt in result or not np.isfinite(value)or value<0:raise ValueError('Anthesis identity/value')
            result[trt]=value
    if set(result)!=set(expected):raise ValueError('Anthesis coverage')
    return result

def extract(work,obs,excode,expected,diagnostic=False):
    frames={name:read_native(work/(name+'.OUT'))for name in ['PlantGro','PlantN','FreshWt','SoilWat']}
    for name,frame in frames.items():
        if set(frame.index.get_level_values('trno'))!=set(expected):raise ValueError('Native treatment coverage '+name)
    ads=anthesis(work,excode,expected);records=[]
    ordinary=obs[~obs.variable.isin(SIGNED|{'ADAP','W_FRESH_SIGN_PENALTY','N2_SIGN_PENALTY'})]
    if not diagnostic:
        normal=point_extract(work,ordinary,native_frames=frames).set_index('obsnme') if len(ordinary)else pd.DataFrame()
    else:normal=None
    for row in obs.to_dict('records'):
        try:
            var=row['variable']
            if var=='ADAP':value=ads[int(row['trno'])]
            elif var=='WB100_INTERVAL':
                header=next(l for l in(work/'SoilWat.OUT').read_text().splitlines()if '0-5'in l)
                layers=[tuple(map(int,v))for v in re.findall(r'(\d+)-(\d+)',header)]
                value=water_balance100(frames['SoilWat'],row['trno'],row['interval_start'],row['interval_end'],layers)
            elif var in SIGNED|{'W_FRESH_SIGN_PENALTY','N2_SIGN_PENALTY'}:
                value=float(frames['FreshWt'].loc[(int(row['trno']),row['date']),'CHFPW']-frames['FreshWt'].loc[(int(row['paired_trno']),row['date']),'CHFPW'])
                if var.endswith('SIGN_PENALTY'):value=max(0.,-value)
            elif diagnostic:value=float(point_extract(work,pd.DataFrame([row]),native_frames=frames).simulated.iloc[0])
            else:value=float(normal.loc[row['obsnme'],'simulated'])
            if not np.isfinite(value)or(var not in SIGNED and value<0):raise ValueError('Nonfinite/nonphysical target')
            records.append(row|dict(simulated=float(value),comparison_status='matched',error=''))
        except (ValueError,KeyError)as exc:
            if not diagnostic:raise
            records.append(row|dict(simulated=None,comparison_status='unmatched',error=str(exc)))
    result=pd.DataFrame(records)
    if len(result)!=len(obs)or result.obsnme.duplicated().any()or set(result.obsnme)!=set(obs.obsnme):raise ValueError('Target identity coverage')
    return result

def encode(comp):
    z=comp.copy();res=(z.simulated-z.observed)/z.fit_scale
    d=z.huber_delta.to_numpy();v=res.to_numpy()
    if not np.isfinite(v).all():raise ValueError('Incomplete objective')
    z['pest_output']=v*np.sqrt(2/(np.hypot(1,v/d)+1))
    z['phi_contribution']=(z.pest_output*z.final_weight)**2
    return z

def physics(work,expected,strict):
    keys=['run','trt','yrdoy','das'];tables={n:pd.read_csv(work/(n+'.csv'))for n in ['NCBalance','CAllocation','DMState','OrganNState','RootNSupply','CH2OPools']}
    for name,q in tables.items():
        k=keys+(['layer']if name=='RootNSupply'else ['organ']if name=='CH2OPools'else [])
        if q.empty or set(q.trt)!=set(expected)or q.duplicated(k).any()or not np.isfinite(q.to_numpy()).all():raise ValueError('Incomplete/nonfinite ledger '+name)
    n,c,dm,state,rr=[tables[n]for n in ['NCBalance','CAllocation','DMState','OrganNState','RootNSupply']]
    for q in [c,dm,state]:
        if set(map(tuple,q[keys].values))!=set(map(tuple,n[keys].values)):raise ValueError('Ledger date coverage')
    if n.filter(regex='residual').abs().to_numpy().max()>2e-4:raise ValueError('Internal N balance')
    ct=np.maximum(1e-5,100*np.finfo('float32').eps*np.maximum(1,c.actual_available_ch2o.abs()))
    if(c.residual_ch2o.abs()>ct).any()or(c.end_ch2o < -ct).any():raise ValueError('C budget closure')
    dmt=np.maximum(2e-5,40*np.finfo('float32').eps*np.maximum(1,dm[['leaf_dm','stem_dm','root_dm','shell_dm','seed_dm']].sum(axis=1)))
    if(dm.filter(regex='residual').abs().max(axis=1)>dmt).any():raise ValueError('DM budget closure')
    rt=rr.groupby(keys).actual_kgN_ha.sum().reset_index().merge(n[keys+['root_input']],on=keys,validate='one_to_one')
    if len(rt)!=len(n)or((rt.actual_kgN_ha/10-rt.root_input).abs()>2e-6).any():raise ValueError('Layer/plant root N disagreement')
    actual=read_injected_parameters(work);card=np.loadtxt(work/'NBufferParam.OUT',skiprows=1);cnc=np.loadtxt(work/'CNCParam.OUT',skiprows=1)
    density=card[5]*cnc[0]/100;cap=np.column_stack([state.leaf_dm*density,state.stem_dm*density*actual['PROSTI'][0]/actual['PROLFI'][0]])
    reserves=state[['leaf_reserve','stem_reserve']].to_numpy();excess=reserves-cap;over=excess>2e-5
    pd.DataFrame(dict(run=state.run,trt=state.trt,yrdoy=state.yrdoy,das=state.das,
        leaf_cap=cap[:,0],stem_cap=cap[:,1],leaf_reserve=reserves[:,0],stem_reserve=reserves[:,1],
        leaf_excess=excess[:,0],stem_excess=excess[:,1])).to_csv(work/'capacity_audit.csv',index=False)
    if strict and over.any():raise ValueError('Nominal reserve capacity violated')
    if(work/'NAcceptance.csv').exists():
        a=pd.read_csv(work/'NAcceptance.csv')
        if len(a)!=len(n)or a.duplicated(keys).any()or not np.isfinite(a.to_numpy()).all():raise ValueError('Acceptance trace coverage')
        if(a[['leaf_store','stem_store']].to_numpy()>a[['leaf_fill_limit','stem_fill_limit']].to_numpy()+2e-6).any():raise ValueError('Daily fill limit')
        if (a.prepaid_assim_ch2o-a.accepted_assim_ch2o-a.refunded_assim_ch2o).abs().max()>2e-5:raise ValueError('Assimilation refund mismatch')
    native=reference.audit_mass_balance(work,expected)
    return dict(passed=True,strict_capacity=strict,nominal_capacity_passed=not bool(over.any()),
        over_capacity_records=int(over.any(axis=1).sum()),max_capacity_excess_g_m2=float(excess.max()),
        max_n_residual=float(n.filter(regex='residual').abs().to_numpy().max()),
        max_soil_n_residual=max(row['soil_daily_or_cumulative_max_kg_ha']for row in native))

def summarize(comp):
    rows=[]
    for(season,family),g in comp.groupby(['season_id','family']):
        good=g[g.simulated.notna()];e=good.simulated-good.observed
        mean=float(good.observed.mean())if len(good)else 0
        rows.append(dict(season=season,family=family,n_expected=len(g),n_matched=len(good),
            rmse=float(np.sqrt(np.mean(e**2)))if len(good)else None,
            nrmse=float(100*np.sqrt(np.mean(e**2))/mean)if len(good)and mean else None,
            bias=float(e.mean())if len(good)else None))
    return pd.DataFrame(rows)

def evaluate(design_path,param_csv,output_dir,keep_diagnostics=True):
    started=time.time();design_path=Path(design_path).resolve();d=json.loads(design_path.read_text());out=Path(output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    (out/'FormalObjectives.OUT').unlink(missing_ok=True)
    trial=out/'native_trials'/uuid.uuid4().hex;trial.mkdir(parents=True)
    receipt=dict(success=False,trial=str(trial),design_sha256=sha(design_path),binary_sha256=d['binary_sha256'],imputed=False)
    try:
        for path,h in d['frozen_hashes'].items():
            if sha(path)!=h:raise ValueError('Frozen dependency changed '+path)
        params=pd.read_csv(Path(param_csv).resolve())
        if params.name.duplicated().any():raise ValueError('Duplicate parameters')
        values=dict(zip(params.name,params.value.astype(float)));bounds=pd.read_csv(d['bounds']);validate(values,bounds)
        pd.DataFrame(values.items(),columns=['name','value']).to_csv(trial/'parameters.csv',index=False)
        receipt['parameters']=values;all_comp=[];all_diag=[];receipts={}
        for ds in d['datasets']:
            season=ds['season_id'];work=trial/season;work.mkdir()
            for name,h in ds['native_hashes'].items():
                src=Path(ds['native_inputs'])/name
                if sha(src)!=h:raise ValueError('Frozen native input changed '+name)
                shutil.copy2(src,work/name)
            try:os.link(d['binary'],work/'DSCSM048.EXE')
            except OSError:shutil.copy2(d['binary'],work/'DSCSM048.EXE')
            if sha(work/'DSCSM048.EXE')!=d['binary_sha256']:raise ValueError('Executable mismatch')
            pd.DataFrame(values.items(),columns=['name','value']).to_csv(work/'parameters.csv',index=False)
            slpf=float(values['SLPF_25SP']) if(season=='25SP' and 'SLPF_25SP' in values)else ds['slpf']
            settings=inject(work,values,slpf,d.get('native_precision_improved',True))
            reference.audit_injection(work,values,[v for v in d['active']if not v.startswith('NB_')and v!='SLPF_25SP'])
            encoded=read_injected_parameters(work)
            for organ,minimum in [('LF',.0125),('ST',.00625)]:
                gap=encoded['PRO'+organ+'I'][0]-encoded['PRO'+organ+'G'][0]
                if gap < minimum-6.25e-7:raise ValueError('Encoded protein dilution margin '+organ)
            soil_lines=(work/'SOIL.SOL').read_text().splitlines()
            scom_idx=next(i for i,x in enumerate(soil_lines)if x.startswith('@ SCOM'))
            if abs(float(soil_lines[scom_idx+1][36:42])-slpf)>0.001:raise ValueError('SLPF injection mismatch '+season)
            write_json(work/'injected_inputs.json',{p.name:sha(p)for p in work.iterdir()if p.is_file()})
            cp=subprocess.run(['./DSCSM048.EXE','CRGRO048','B','DSSBatch.v48'],executable=str(work/'DSCSM048.EXE'),cwd=work,input='\n'*8,capture_output=True,text=True,timeout=240)
            (work/'native.log').write_text(cp.stdout+cp.stderr,encoding='utf8')
            if cp.returncode or(work/'ERROR.OUT').exists():
                failure=work/'NBufferFailure.txt'
                if cp.returncode==86 and failure.exists() and failure.read_text().splitlines()[0].strip()=='CH2O pool is not an organ DM subset':
                    raise ValueError('Native infeasible CH2O organ subset; season='+season)
                raise RuntimeError('Native failure '+season+': '+str(cp.returncode))
            if not np.allclose(np.loadtxt(work/'NBufferParam.OUT',skiprows=1),settings,atol=.000501,rtol=0):raise ValueError('Reserve injection readback')
            receipts[season]=physics(work,ds['treatments'],d['strict_capacity'])
            write_json(work/'physics.json',receipts[season])
            obs=pd.read_csv(ds['observations']).fillna('');comp=extract(work,obs,ds['excode'],ds['treatments']);all_comp.append(comp)
            # All diagnostic rows remain visible, including no-mature-fruit cases.
            if keep_diagnostics:
                diag=pd.read_csv(ds['diagnostics']).fillna('');all_diag.append(extract(work,diag,ds['excode'],ds['treatments'],diagnostic=True))
        result=encode(pd.concat(all_comp,ignore_index=True))
        if len(result)!=d['targets']or set(result.obsnme)!=set(d['observation_names']):raise ValueError('Joint target coverage')
        result.to_csv(trial/'comparison.csv',index=False);summarize(result).to_csv(trial/'metrics.csv',index=False)
        if all_diag:
            diag=pd.concat(all_diag,ignore_index=True);diag.to_csv(trial/'diagnostic_comparison.csv',index=False);summarize(diag).to_csv(trial/'diagnostic_metrics.csv',index=False)
        temp=out/'FormalObjectives.writing';temp.write_text('\n'.join(f'{row.obsnme} {row.pest_output:.15g}'for row in result.itertuples())+'\n',encoding='ascii');temp.replace(out/'FormalObjectives.OUT')
        receipt.update(success=True,complete_targets=len(result),phi=float(result.phi_contribution.sum()),physics=receipts)
        write_json(out/'last_success.json',receipt)
        return receipt
    except Exception as exc:
        receipt.update(error=str(exc),error_type=type(exc).__name__)
        write_json(out/'last_failure.json',receipt);raise
    finally:
        receipt['elapsed_seconds']=time.time()-started;write_json(trial/'receipt.json',receipt)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--design',required=True);p.add_argument('--param-csv',required=True);p.add_argument('--output-dir',required=True);p.add_argument('--no-diagnostics',action='store_true');a=p.parse_args()
    evaluate(a.design,a.param_csv,a.output_dir,not a.no_diagnostics)
