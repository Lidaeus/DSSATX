"""Same-binary C4 regression/ablation and low-C robustness, not calibration."""
import json
from concurrent.futures import ThreadPoolExecutor
from workflow import CN,OUT,case,dump
from controlled_smoke import radiation

COMMON=dict(state_timing=1,pods_n_state=1,remob_mode=1,remob_tau=10,
    protect_beta=.7,slow_ratio=3,luxury_priority=1)
FULL=dict(COMMON,c4_budget=1,leaf_coupling=1,c4_photo=1,n_sen_rate=0)
PREVIOUS=CN/'reports/n_v3_execution_20261103'

def specs():
    items=[]
    for suffix in ['mode0','A']:
        cfg=json.loads((PREVIOUS/f'cases/delivery_{suffix}/receipt.json').read_text(encoding='utf8'))['config']
        items.append(('delivery_'+suffix,cfg,None))
    items.extend([
        ('delivery_C3',COMMON,None),
        ('delivery_photo',dict(COMMON,c4_photo=1),None),
        ('delivery_stock',dict(COMMON,c4_budget=1),None),
        ('delivery_stock_photo',dict(COMMON,c4_budget=1,c4_photo=1),None),
        ('delivery_full',FULL,None),
        ('delivery_sen02',dict(FULL,n_sen_rate=.02),None),
        ('delivery_repeat',FULL,None),
        ('delivery_nogate',dict(FULL,remob_severity=0),None),
        ('delivery_lowC35',FULL,.35),
        ('delivery_lowC10',FULL,.1)])
    return items

if __name__=='__main__':
    exe=OUT/'bin/delivery/dscsm048_delivery.exe'
    def one(item):
        name,cfg,factor=item
        modifier=(lambda w:radiation(w,factor)) if factor is not None else None
        return case(name,exe,cfg,input_modifier=modifier)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(one,specs()))
    dump(OUT/'C4_delivery_cases.json',dict(calibration=False,cases=results))
