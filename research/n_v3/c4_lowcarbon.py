"""C4 robustness only: modified radiation is not a field-fit experiment."""
from concurrent.futures import ThreadPoolExecutor
from workflow import OUT,case,dump
from controlled_smoke import radiation

if __name__=='__main__':
    exe=OUT/'bin/c4_photo_candidate/dscsm048_c4_photo_candidate.exe'
    config=dict(state_timing=1,pods_n_state=1,remob_mode=1,remob_tau=10,
        protect_beta=.7,slow_ratio=3,luxury_priority=1,c4_budget=1,leaf_coupling=1,c4_photo=1,n_sen_rate=0)
    def one(item):
        name,factor=item
        return case(name,exe,config,input_modifier=lambda w:radiation(w,factor))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(one,[('C4_lowC35',.35),('C4_lowC10',.1)]))
    dump(OUT/'C4_lowcarbon_smoke.json',dict(role='diagnostic_robustness_not_calibration',cases=results))
