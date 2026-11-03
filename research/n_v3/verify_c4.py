"""Reconstruct organ DM, mobile carbohydrate, normal N recovery and area."""
import sys
import numpy as np
import pandas as pd
from workflow import OUT,dump

def tolerance(*values):
    return 32*np.finfo(np.float32).eps*np.maximum.reduce([np.ones_like(values[0]),*[np.abs(v)for v in values]])

results=[]
for name in sys.argv[1:]:
    work=OUT/'cases'/name
    selected=[]
    for chunk in pd.read_csv(work/'P0Trace.csv',chunksize=200000,usecols=['run','yrdoy','event','key','value']):
        selected.append(chunk[chunk.event.isin(['c4_grow_begin','c4_grow_end','c4_grow_flux','c4_carb_fate'])])
    trace=pd.concat(selected)
    tables={key:g.pivot(index=['run','yrdoy'],columns='key',values='value')for key,g in trace.groupby('event')}
    b=tables['c4_grow_begin'];e=tables['c4_grow_end'];f=tables['c4_grow_flux'];qout=tables['c4_carb_fate']
    assert len(b)==1512 and b.index.equals(e.index) and b.index.equals(f.index)
    leaf=pd.read_csv(work/'PlantNLeaf.csv',float_precision='round_trip').set_index(['run','yrdoy'])if(work/'PlantNLeaf.csv').exists()else None
    dm_errors={};carb_errors={}
    for organ in ['leaf','stem','root','shell','seed']:
        nm=f['Nmobile_'+organ]if organ!='seed'else 0
        cm=f['Cmobile_'+organ]if organ in ['leaf','stem','root']else qout.TOCHMINE if organ=='shell'else 0
        nadd=f['Nadd_'+organ]if organ in ['leaf','stem','root']else 0
        cadd=f['Cadd_'+organ]if organ in ['leaf','stem']else 0
        mobil_mass=nm/.16 if organ!='shell'else f.TOSHMINE
        expected=b['W_'+organ]+f['Wnew_'+organ]+cadd+nadd/.16-f['loss_'+organ]-mobil_mass-cm
        err=np.abs(e['W_'+organ]-expected)
        assert (err<=tolerance(b['W_'+organ],expected)).all(),(name,organ,'DM',err.max())
        dm_errors[organ]=float(err.max())
        if organ=='seed':continue
        q0=b['Q_'+organ]
        if organ in ['leaf','stem','root']:
            fraction=leaf['cell_loss_'+organ]if leaf is not None else np.minimum(1,f['loss_'+organ]/(b['W_'+organ]-nm/.16-cm).clip(1e-12))
            litter=(q0-cm).clip(0)*fraction;lock=0
        else:
            pre=(q0+f.alpha_shell*f.Wnew_shell-cm).clip(0)
            litter=pre*np.minimum(1,f.loss_shell/(b.W_shell+f.Wnew_shell-f.TOSHMINE-cm).clip(1e-12))
            lock=np.minimum((pre-litter).clip(0),f.mature_shell*(q0/b.W_shell.clip(1e-12)))
        expected=q0+f['alpha_'+organ]*f['Wnew_'+organ]+cadd-cm-litter-lock
        err=np.abs(e['Q_'+organ]-expected)
        assert (err<=tolerance(q0,expected)).all(),(name,organ,'CH2O',err.max())
        assert (np.abs(qout['Qout_'+organ]-litter)<=tolerance(q0,litter)).all()
        assert (e['Q_'+organ]+e['N_'+organ]/.16<=e['W_'+organ]+tolerance(e['W_'+organ])).all(),(name,organ,'component subset')
        carb_errors[organ]=float(err.max())
    assert (np.abs(e.PODWT-e.W_shell-e.W_seed)<=tolerance(e.PODWT,e.W_shell)).all()
    assert (np.abs(e.TOPWT-e.W_leaf-e.W_stem-e.PODWT)<=tolerance(e.TOPWT)).all()
    if leaf is not None:
        for organ in ['leaf','stem']:
            expected=b['N_'+organ]*leaf['cell_loss_'+organ]-leaf['sen_N_'+organ]
            assert (np.abs(expected-leaf['litter_N_'+organ])<1e-12).all()
            assert (leaf['sen_N_'+organ]<=leaf['sen_available_'+organ]+1e-12).all()
        area_expected=b.AREA+f.Wnew_leaf*f.F-leaf.old_area_lost
        assert (np.abs(e.AREA-area_expected)<=tolerance(b.AREA,area_expected)).all()
        n=pd.read_csv(work/'PlantNIntegration.csv',float_precision='round_trip').set_index(['run','yrdoy'])
        reconstructed=0
        for organ in ['leaf','stem','root']:
            frac=leaf['cell_loss_'+organ]
            assert frac.max()<1,'complete death needs before-loss pool diagnostics'
            reconstructed+=(n['QNO3_'+organ]+n['QNH4_'+organ])*frac/(1-frac)
        assert np.max(np.abs(reconstructed-n.inorg_litter))<1e-12
    cash=pd.read_csv(work/'PlantCCash.csv',float_precision='round_trip')
    residual=cash.PG+cash.actual_C_mined-cash.maintenance-cash.N_assim-cash.N_resynthesis-cash.veg_growth-cash.fruit_growth-cash.storage_cost
    assert np.max(np.abs(residual-cash.CH2O_residual))<1e-12
    assert (residual.abs()<=tolerance(cash.PG,cash.actual_C_mined)).all()
    if 'maintenance_potential' in cash:
        assert (cash.maintenance_unpaid>=0).all()
        assert abs(cash.maintenance_potential-cash.maintenance-cash.maintenance_unpaid).max()<1e-13
        assert (cash.maintenance<=cash.PG+cash.actual_C_mined+tolerance(cash.PG)).all()
    results.append(dict(case=name,passed=True,DM_residual_max=dm_errors,carbohydrate_residual_max=carb_errors,
        cash_residual_max=float(residual.abs().max()),normal_N_recovery=leaf[['sen_N_leaf','sen_N_stem']].sum().to_dict()if leaf is not None else None))
dump(OUT/('C4_verification_'+sys.argv[1]+'.json'),results)
print(results)
