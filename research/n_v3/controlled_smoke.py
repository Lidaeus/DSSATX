"""Diagnostic robustness runs; do not interpret modified inputs as field fits."""
from concurrent.futures import ThreadPoolExecutor
import re
from workflow import OUT,case,dump

exe=OUT/'bin/delivery/dscsm048_delivery.exe'
common=dict(state_timing=1,pods_n_state=1,luxury_priority=1)
combined=dict(common,remob_mode=1,remob_tau=10,protect_beta=.7,slow_ratio=3)
def radiation(work,factor):
    files=list(work.glob('*.WTH'));assert len(files)==1
    p=files[0];lines=p.read_text(encoding='ascii').splitlines()
    header=next(l for l in lines if re.match(r'^@\s*DATE\b',l))
    assert header.lstrip('@').split().index('SRAD')==1
    changed=0
    for i,line in enumerate(lines):
        if re.match(r'^\s*\d{5,7}\s',line):
            assert len(line[:7])==7 and line[:7].isdigit()
            v=float(line[7:13]);assert v>=0
            text=f'{factor*v:6.2f}';assert len(text)==6
            lines[i]=line[:7]+text+line[13:]
            changed+=1
    assert changed>100
    p.write_text('\n'.join(lines)+'\n',encoding='ascii')
    dump(work/'controlled_input.json',dict(role='diagnostic_not_observed_weather',radiation_multiplier=factor,rows=changed))
def one(item):
    name,config,factor=item
    return case(name,exe,config,input_modifier=lambda w:radiation(w,factor))
if __name__=='__main__':
    args=[('delivery_lowC_C3',common,.35),('delivery_lowC_combined',combined,.35),('delivery_veryLowC_combined',combined,.1)]
    with ThreadPoolExecutor(max_workers=3)as pool:results=list(pool.map(one,args))
    dump(OUT/'delivery_controlled_smoke_receipt.json',dict(role='robustness_not_calibration_or_full_event_experiments',cases=results))
