"""Isolated C4 calibration operator; derived from frozen A, with explicit C1-C4 switches and journals."""
from pathlib import Path
import argparse,json,os,re,shutil,subprocess,sys,time,uuid
import numpy as np
import pandas as pd
from smoke_forward import sha,dump,redirect,extract,audit

SPE={
 'PARMAX,PHTMAX':['PARMAX','PHTMAX','KCAN','KC_SLOPE'],
 'PGEFF SCV KDIF':['PGEFF','SCV','KDIF','LFANGB'],
 'SLWREF,SLWSLO':['SLWREF','SLWSLO','NSLOPE','LNREF','PGREF'],
 'PROLFI,PROLFG,PROLFF':['PROLFI','PROLFG','PROLFF','PROSTI','PROSTG','PROSTF'],
 'PRORTI,PRORTG,PRORTF':['PRORTI','PRORTG','PRORTF','PROSHI','PROSHG','PROSHF'],
 'CMOBMX,CADSTF':['CMOBMX','CADSTF','CADPR1','NMOBMX','NVSMOB','NRCVR'],
 'WTFSD,PORPT':['WTFSD','PORPT','FRSTMF','FRLFF','ATOP','FRCNOD'],
 'FINREF,SLAREF':['FINREF','SLAREF','SIZREF','VSSINK','EVMODC'],
 'SENRTE,SENRT2':['SENRTE','SENRT2','SENDAY','FREEZ1','FREEZ2'],
 'RTDEPI,RFAC1':['RTDEPI','RFAC1','RTSEN','RLDSM','RTSDF','RWUEP1','RWUMX'],
 'RTNO3,RTNH4':['RTNO3','RTNH4','PORMIN','RTEXF'],
 'DSWBAR,XFRMAX':['DSWBAR','XFRMAX','SHLAG'],
 'XSWBAR(1-5)':['__x1','__x2','SWBAR_REC'],
 'YSWBAR(1-5)':['__y1','__y2','YSWBAR_MID'],
 'VEGETATIVE DEVELOPMENT':['TB1','TO11','TO21','TM1'],
 'EARLY REPRODUCTIVE DEVELOPMENT':['TB2','TO12','TO22','TM2'],
 'ICMP,TCMP':['ICMP','TCMP'],
 'KEP, EORATIO':['KEP'],
}


def token(value):
    for precision in range(7,-1,-1):
        s=f'{value:.{precision}f}'
        if precision==0:s+='.'
        if s.startswith('0.'):s=s[1:]
        if len(s)<=5:return ' '+s.rjust(5)
    raise ValueError('six-column overflow')


def inject(work,values,runtime):
    sys.path.insert(0,str(runtime))
    from src.calibration.single_season_n import read_injected_parameters
    mapping={}
    for ext,header,identity,skip,start in [('CUL','@VAR#','TM0008',4,36),('ECO','@ECO#','TM0001',2,18)]:
        p=work/f'TMGRO048.{ext}';lines=p.read_text(encoding='ascii').splitlines()
        names=next(l.split()[skip:]for l in lines if l.startswith(header))
        i=next(i for i,l in enumerate(lines)if l.startswith(identity))
        for j,n in enumerate(names):
            if n in values:
                pos=start+6*j
                lines[i]=lines[i][:pos]+token(values[n])+lines[i][pos+6:]
                mapping[n]=str(p.name)+f':{i+1}:{pos+1}-{pos+6}'
        p.write_text('\n'.join(lines)+'\n',encoding='ascii')
    p=work/'TMGRO048.SPE';lines=p.read_text(encoding='ascii').splitlines()
    for marker,names in SPE.items():
        i=next(i for i,l in enumerate(lines)if marker in l)
        for j,n in enumerate(names):
            if n in values:
                pos=j*6
                lines[i]=lines[i][:pos]+token(values[n])+lines[i][pos+6:]
                mapping[n]=p.name+f':{i+1}:{pos+1}-{pos+6}'
    for name,j in [('SENPOR_LATE',3),('SENMAX_LATE',7)]:
        if name in values:
            i=next(i for i,l in enumerate(lines)if 'SENPOR.........'in l)+1;pos=j*6
            lines[i]=lines[i][:pos]+token(values[name])+lines[i][pos+6:]
            mapping[name]=p.name+f':{i+1}:{pos+1}-{pos+6}'
    p.write_text('\n'.join(lines)+'\n',encoding='ascii')
    if 'SOIL_SLDR'in values:
        p=work/'SOIL.SOL';lines=p.read_text(encoding='ascii').splitlines()
        indices=[i+1 for i,l in enumerate(lines)if l.startswith('@ SCOM')]
        if len(indices)!=1:raise ValueError('Ambiguous soil profile')
        i=indices[0];lines[i]=lines[i][:18]+token(values['SOIL_SLDR'])+lines[i][24:]
        p.write_text('\n'.join(lines)+'\n',encoding='ascii');mapping['SOIL_SLDR']=p.name+f':{i+1}:19-24'
    if set(values)!=set(mapping):raise ValueError('Missing native injection '+str(set(values)-set(mapping)))
    actual=read_injected_parameters(work)
    lines=(work/'TMGRO048.SPE').read_text(encoding='ascii').splitlines()
    for name,marker,start in [('ICMP','ICMP,TCMP',0),('TCMP','ICMP,TCMP',6),('KEP','KEP, EORATIO',0)]:
        s=next(l for l in lines if marker in l)[start:start+6].strip()
        actual[name]=(float(s),10.**(-len(s.partition('.')[2])))
    lines=(work/'SOIL.SOL').read_text(encoding='ascii').splitlines()
    s=lines[next(i for i,l in enumerate(lines)if l.startswith('@ SCOM'))+1][18:24].strip()
    actual['SOIL_SLDR']=(float(s),10.**(-len(s.partition('.')[2])))
    rows=[]
    for name,value in values.items():
        v,res=actual[name]
        if abs(value-v)>.5*res+1.e-9:raise ValueError(f'Independent native read-back failed: {name}: {value} -> {v}')
        rows.append(dict(name=name,requested=value,actual=v,resolution=res,field=mapping[name]))
    pd.DataFrame(rows).to_csv(work/'native_injection_audit.csv',index=False)
    return rows


def audit_A(work,config):
    cfg=dict(config)
    for organ in ['leaf','stem']:
        cinf=config.get(organ+'_inf',0)
        if cinf:
            cfg[organ+'_a']=cinf+(config[organ+'_a']-cinf)*config['curve_w0']**(-config[organ+'_b'])
        else:
            cfg[organ+'_a']=config[organ+'_a']*config['curve_w0']**(-config[organ+'_b'])
    result=audit(work,cfg)
    n=pd.read_csv(work/'PlantABudget.csv')
    if len(n)!=1512 or n.duplicated(['run','yrdoy']).any()or not n.budget_revision.eq(1).all():raise ValueError('A activation/coverage')
    residual=n.organic_end_including_seed-n.organic_begin_including_seed+n.cumulative_loss_end-n.cumulative_loss_begin+n.leak_end-n.leak_begin-n.A_committed
    limit=1.e-5+2.e-6*np.maximum(n.organic_begin_including_seed,n.organic_end_including_seed)
    if (residual.abs()>limit).any():raise ValueError('Independent committed organic N budget')
    if (n.veg_C_actual-n.veg_C_available).max()>2.e-5:raise ValueError('Independent vegetative C budget')
    if not np.allclose(n.curve_w0,config['curve_w0'],rtol=0,atol=1.e-12):raise ValueError('Breakpoint not consumed')
    if not np.allclose(n.photo_slw_ref,config['photo_slw_ref'],rtol=0,atol=1.e-12):raise ValueError('Functional N reference not consumed')
    result.update(legacy_bugs_deferred=False,A_activated=True,organic_independent_residual_max=float(residual.abs().max()),
                  vegetative_C_overrun_max=float(np.maximum(0,n.veg_C_actual-n.veg_C_available).max()))
    return result


def audit_c4(work,config):
    result=audit_A(work,config)
    def load(name):
        frame=pd.read_csv(work/name,float_precision='round_trip')
        if len(frame)!=1512 or frame.duplicated(['run','yrdoy']).any():raise ValueError('C4 journal coverage '+name)
        return frame.set_index(['run','yrdoy'])
    cash=load('PlantCCash.csv');leaf=load('PlantNLeaf.csv');mob=load('PlantNRemob.csv');old=load('PlantABudget.csv')
    state=load('PlantNV3.csv');lux=load('PlantNLuxury.csv')
    for frame in [leaf,mob,old,state,lux]:
        if not frame.index.equals(cash.index):raise ValueError('C4 journal alignment')
    res=cash.PG+cash.actual_C_mined-cash.maintenance-cash.N_assim-cash.N_resynthesis-cash.veg_growth-cash.fruit_growth-cash.storage_cost
    tolerance=32*np.finfo(np.float32).eps*np.maximum.reduce([np.ones(len(cash)),abs(cash.PG),abs(cash.actual_C_mined)])
    if (abs(res)>tolerance).any() or abs(res-cash.CH2O_residual).max()>1e-12:raise ValueError('Independent C4 CH2O payments')
    if cash.maintenance_unpaid.min()<0 or abs(cash.maintenance_potential-cash.maintenance-cash.maintenance_unpaid).max()>1e-12:raise ValueError('C4 maintenance accounting')
    source=0
    for organ in ['leaf','stem','root','shell']:
        actual=mob['safe_'+organ]+mob['function_'+organ]+leaf['sen_N_'+organ]
        source+=actual
        if organ!='shell' and abs(actual-old['mobilized_'+organ]).max()>1e-12:raise ValueError('C4 donor source '+organ)
    planned=mob.filter(regex='^plan_').sum(axis=1)-mob.filter(regex='^returned_').sum(axis=1)
    repair=0
    if config.get('common_acceptance')==1:
        p2=load('PlantNP2.csv')
        if not p2.index.equals(cash.index):raise ValueError('P2 recipient journal alignment')
        repair=p2[['repair_used_leaf','repair_used_stem','repair_used_root']].sum(axis=1)
    if abs(source-planned).max()>1e-12 or (source>mob.new_growth_N_actual+repair+1e-6).any():raise ValueError('C4 source-recipient reconciliation')
    for organ in ['leaf','stem']:
        if (leaf['sen_N_'+organ]>leaf['sen_available_'+organ]+1e-12).any():raise ValueError('C4 dying material balance')
    if not leaf.n_sen_rate.eq(config['n_sen_rate']).all():raise ValueError('C4 senescence setting not consumed')
    if not np.allclose(mob.tau,config['remob_tau'],rtol=0,atol=1e-12) or not np.allclose(mob.protect_beta,config['protect_beta'],rtol=0,atol=1e-14):raise ValueError('C4 remobilization settings not consumed')
    previous=state.groupby('run')[['growth_end','z_leaf_end','z_stem_end']].shift()
    valid=state.valid.eq(1)
    if valid.sum()!=1500 or abs(state.loc[valid,'growth_day']-previous.loc[valid,'growth_end']).max()>1e-12:raise ValueError('C4 state timing')
    if abs(state.pod_n_factor-(1-(1-state.z_leaf_day.clip(0,1))**2)).max()>1e-12:raise ValueError('C4 PODS state')
    for species in ['no3','nh4']:
        if (lux['core_'+species]+lux['late_'+species]>lux['cap_'+species]+1e-12).any():raise ValueError('C4 finite assimilation envelope')
    if (lux.C_late>lux.C_available+1e-8).any():raise ValueError('C4 late C expense')
    result.update(C4_activated=True,CH2O_payment_residual_max=float(abs(res).max()),
        normal_aging_N_total=float(leaf.filter(regex='^sen_N_').sum().sum()),
        functional_export_N_total=float(mob.filter(regex='^function_').sum().sum()),
        whole_elemental_C_closed=False)
    return result

def evaluate(design_path,parameters,out):
    start=time.monotonic();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    (out/'FormalObjectives.OUT').unlink(missing_ok=True)
    d=json.loads(Path(design_path).read_text(encoding='utf8'))
    work=out/'native_trials'/uuid.uuid4().hex;work.mkdir(parents=True)
    receipt=dict(success=False,trial=str(work),imputed=False)
    try:
        for p,h in d.get('frozen_hashes',{}).items():
            if sha(p)!=h:raise ValueError('Frozen dependency changed: '+p)
        bounds=pd.read_csv(d['bounds'],float_precision='round_trip');frame=pd.read_csv(parameters,float_precision='round_trip')
        if frame.name.duplicated().any()or set(frame.name)!=set(bounds.pest_name):raise ValueError('Parameter identity')
        raw=frame.set_index('name').value.to_dict();values={r.name:float(raw[r.pest_name])for r in bounds.itertuples()}
        receipt['parameters']=values
        for r in bounds.itertuples():
            if not np.isfinite(values[r.name])or not r.lower-1e-12<=values[r.name]<=r.upper+1e-12:raise ValueError('Bound '+r.name)
            if r.status=='fixed'and abs(values[r.name]-r.init)>1e-12:raise ValueError('Fixed '+r.name)
        for p in Path(d['inputs']).iterdir():
            if p.is_file():shutil.copy2(p,work/p.name)
        redirect(work/'DSSATPRO.v48',work)
        natives={k:v for k,v in values.items()if k not in d['nitrogen_names']}
        receipt['injection']=inject(work,natives,Path(d['runtime']))
        config=dict(d['fixed_nitrogen_config'])
        config.update({k:values[k]for k in d['nitrogen_names']})
        if any(config.get(k)!=v for k,v in d['required_mode'].items()):raise ValueError('C4 required mode not enabled')
        if sha(d['binary'])!=d['binary_sha256']:raise ValueError('C4 executable identity changed')
        receipt['nitrogen_config']=config
        (work/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v:.17g}\n'for k,v in config.items())+'/\n',encoding='ascii')
        env=os.environ.copy();env['DSSAT_N_CONFIG']=str(work/'NIntegration.nml');env['DSSAT_P0_TRACE']='0'
        with(work/'stdout.log').open('wb')as so,(work/'stderr.log').open('wb')as se:
            p=subprocess.run([d['binary'],'B','DSSBatch.v48'],cwd=work,env=env,stdout=so,stderr=se,timeout=180)
        if p.returncode or not re.search(r'Normal end of run\s+12\b',(work/'INFO.OUT').read_text(encoding='utf8')):raise RuntimeError('Native failed: '+(work/'stderr.log').read_text(encoding='utf8')[-800:])
        budget=audit_c4(work,config)
        receipt['budget']=budget
        comp=extract(work,pd.read_csv(d['observations']).fillna(''),Path(d['runtime']))
        comp.to_csv(work/'comparison.csv',index=False)
        receipt.update(success=True,parameters=values,nitrogen_config=config,budget=budget,phi=float(comp.phi_contribution.sum()),binary_sha256=sha(d['binary']))
        tmp=out/'FormalObjectives.writing'
        tmp.write_text('\n'.join(f'{r.obsnme} {r.pest_output:.17g}'for r in comp.itertuples())+'\n',encoding='ascii');tmp.replace(out/'FormalObjectives.OUT')
        dump(out/'last_success.json',receipt)
        return receipt
    except BaseException as e:
        receipt.update(error=str(e),error_type=type(e).__name__)
        dump(out/'last_failure.json',receipt)
        raise
    finally:
        receipt['elapsed_seconds']=time.monotonic()-start
        dump(work/'receipt.json',receipt)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--design',required=True);p.add_argument('--parameters',default='parameters.csv');p.add_argument('--out',default='.')
    a=p.parse_args();evaluate(a.design,a.parameters,a.out)
