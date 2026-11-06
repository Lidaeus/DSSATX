"""Explicit bijective search coordinates for native protein constraints.

Only two coordinates change. Original physical bounds stay intact. A documented
one-field-quantum margin protects the 3-decimal SPE encoding. Every proposal
retains its search and physical vectors; no failed-output substitution occurs.
"""
import numpy as np
import pandas as pd

POSITIONS={'PROLFG':('LF_PROTEIN_POS','PROLFI',.014),
           'PROSTG':('ST_PROTEIN_POS','PROSTI',.008)}

def upper(values,bounds,name):
    _,maximum,margin=POSITIONS[name]
    return min(float(bounds.loc[name,'upper']),float(values[maximum])-margin)

PARTITION_ALIAS='LEAF_PARTITION_POS'

def partition_upper(values,bounds):
    return min(float(bounds.loc['FRLFF','upper']),1.-float(values['FRSTMF']))

def decode(search,bounds):
    expected=(set(bounds.index)-set(POSITIONS)-{'FRLFF'})|{p[0]for p in POSITIONS.values()}|{PARTITION_ALIAS}
    if set(search)!=expected:raise ValueError('Search parameter identity coverage')
    values={k:float(v)for k,v in search.items()if k not in {p[0]for p in POSITIONS.values()}|{PARTITION_ALIAS}}
    u=float(search[PARTITION_ALIAS]);lo=float(bounds.loc['FRLFF','lower']);hi=partition_upper(values,bounds)
    if not np.isfinite(u) or not 0<=u<=1 or hi<lo: raise ValueError('Partition coordinate domain')
    values['FRLFF']=lo+u*(hi-lo)
    for name,(alias,_,_)in POSITIONS.items():
        u=float(search[alias]);lo=float(bounds.loc[name,'lower']);hi=upper(values,bounds,name)
        if not np.isfinite(u)or not 0<=u<=1 or hi<lo:raise ValueError('Protein coordinate domain '+name)
        values[name]=lo+u*(hi-lo)
    return {name:values[name]for name in bounds.index}

def encode(values,bounds):
    search=dict(values)
    lo=float(bounds.loc['FRLFF','lower']);hi=partition_upper(values,bounds)
    u=(values['FRLFF']-lo)/(hi-lo)
    if not 0<=u<=1: raise ValueError('Physical center outside feasible partition')
    del search['FRLFF'];search[PARTITION_ALIAS]=u
    for name,(alias,_,_)in POSITIONS.items():
        lo=float(bounds.loc[name,'lower']);hi=upper(values,bounds,name)
        u=(values[name]-lo)/(hi-lo)
        if not 0<=u<=1:raise ValueError('Physical center outside encoded feasible domain '+name)
        del search[name];search[alias]=u
    return search

def search_bounds(bounds,center):
    result=bounds.reset_index().copy()
    for name,(alias,_,_)in POSITIONS.items():
        mask=result.name.eq(name);result.loc[mask,['name','lower','upper']]=[alias,0.,1.]
    result.loc[result.name.eq('FRLFF'),['name','lower','upper']]=[PARTITION_ALIAS,0.,1.]
    result['init']=result.name.map(encode(center,bounds))
    return result
