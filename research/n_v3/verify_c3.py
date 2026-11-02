"""Independent kinetic-envelope, residual-carbon and late-recipient checks."""
import sys
import numpy as np
import pandas as pd
from workflow import OUT,dump
results=[]
for name in sys.argv[1:]:
    w=OUT/'cases'/name
    d=pd.read_csv(w/'PlantNLuxury.csv',float_precision='round_trip')
    n=pd.read_csv(w/'PlantNIntegration.csv',float_precision='round_trip')
    assert len(d)==1512 and not d.duplicated(['run','yrdoy']).any()
    for suffix in ['no3','nh4']:
        assert d['core_'+suffix].min()>=-1e-13
        assert (d['core_'+suffix]+d['late_'+suffix]<=d['cap_'+suffix]+1e-13).all()
        assert np.max(np.abs(d['core_'+suffix]+d['late_'+suffix]-n['A_'+suffix.upper()]))<1e-13
    amount=d.late_no3+d.late_nh4
    assert np.max(np.abs(amount-d.A_function_late-d.A_luxury))<1e-13
    assert np.max(np.abs(amount-d.NAD_late_leaf-d.NAD_late_stem))<1e-13
    assert np.max(np.abs(d.C_late-d.late_no3*d.cost_no3-d.late_nh4*d.cost_nh4))<1e-13
    assert (d.C_late<=d.C_available+1e-8).all()
    # Bound host storage rounding from the float32 interface, not from fit.
    tol=32*np.finfo(np.float32).eps*np.maximum(1,d.C_storage_before)
    error=np.abs(d.C_storage_before-d.C_storage_after-d.C_late)
    assert (error<=tol).all()
    assert (d.C_storage_after>=np.minimum(d.C_reserved,d.C_storage_before)-tol).all()
    price_error=np.abs(n.C_assim-(n.A_NO3*d.cost_no3+n.A_NH4*d.cost_nh4))
    assert (price_error<=32*np.finfo(np.float32).eps*np.maximum(1,n.C_assim)).all()
    results.append(dict(case=name,passed=True,late_N_total=float(amount.sum()),
        late_luxury_N_total=float(d.A_luxury.sum()),late_function_N_total=float(d.A_function_late.sum()),
        storage_C_rounding_max=float(error.max()),actual_cost_rounding_max=float(price_error.max())))
dump(OUT/('C3_verification_'+sys.argv[1]+'.json'),results)
print(results)
