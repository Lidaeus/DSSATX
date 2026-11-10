"""Freeze unchanged objective/bounds and register two paired small IES pilots."""
from pathlib import Path
import json,hashlib,socket
import pandas as pd
V=Path(__file__).resolve().parent;ROOT=V.parent;OLD=ROOT/'n_buffer_v14'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,q):Path(p).write_text(json.dumps(q,ensure_ascii=False,indent=2),encoding='utf8')
def translated(path):
    candidate=Path(str(path).replace(str(OLD),str(V)))
    return str(candidate)if candidate.is_file()else str(path)
def main():
    assert json.loads((V/'evidence/stage_1_to_4_checks.json').read_text())['native_module_tests_passed']
    original=OLD/'configs/joint_fresh76_a123_r2.json';source=json.loads(original.read_text());plans=[]
    ports=[]
    for p in range(4897,4999):
        try:
            with socket.socket()as s:s.bind(('127.0.0.1',p))
            ports.append(p)
            if len(ports)==2:break
        except OSError:continue
    variants=json.loads((V/'configs/mechanism_variants.json').read_text())['variants']
    for variant,port in zip([variants[0],variants[-1]],ports):
        d=json.loads(json.dumps(source));d['id']=variant['name']+'_fresh76_joint_pilot_20261028'
        for field in ['bounds','search_bounds']:d[field]=translated(d[field])
        assert sha(d['bounds'])==sha(source['bounds'])and sha(d['search_bounds'])==sha(source['search_bounds'])
        d['binary']=variant['binary'];d['binary_sha256']=variant['sha256']
        frozen={translated(p):h for p,h in source['frozen_hashes'].items()}
        for p,h in frozen.items():assert sha(p)==h,p
        for p in list(V.glob('*.py'))+list((V/'runtime').rglob('*.py'))+list((V/'source'/variant['name']).iterdir())+[Path(variant['binary'])]:frozen[str(p)]=sha(p)
        d['frozen_hashes']=frozen;d['mechanism_version']=variant;d['parent_design_sha256']=sha(original)
        d['objective_unchanged']=True;d['observation_count']=source['targets'];d['purpose']='Small paired mechanism calibration, not independent validation or automatic production promotion'
        path=V/'configs'/(d['id']+'.json');dump(path,d)
        plan=dict(name=variant['name'],run_id=variant['name']+'_100x2_20261028',design=str(path),design_sha256=sha(path),center=str(OLD/'runs/fresh76_a100x2_tcp_recovered_20261018/best_parameters.csv'),members=100,iterations=2,workers=3,seed=20261028,port=port,max_preflight_attempts=300,local_fraction=.05,broad_fraction=0.,parameter_domain_unchanged=True,objective_and_exclusions_unchanged=True,TRIFL_upper=.85)
        plans.append(plan)
    dump(V/'configs/registered_pilots.json',dict(purpose='Paired 100 x 2 constrained IES pilot; stage 3 predicted-capacity expansion not adopted',pilots=plans))
    for p in plans:print(p['name'],p['design'],'port',p['port'])
if __name__=='__main__':main()
