"""Decode explicit search coordinates, then run the unaltered native model."""
from pathlib import Path
import argparse,json,sys,uuid
import pandas as pd
from protocol import evaluate,write_json,validate
from coordinates import decode

def main():
    p=argparse.ArgumentParser();p.add_argument('--design',required=True);p.add_argument('--param-csv',required=True);p.add_argument('--output-dir',required=True);p.add_argument('--no-diagnostics',action='store_true');a=p.parse_args()
    d=json.loads(Path(a.design).read_text(encoding='utf8'));out=Path(a.output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    (out/'FormalObjectives.OUT').unlink(missing_ok=True)
    frame=pd.read_csv(a.param_csv)
    if frame.name.duplicated().any():raise ValueError('Duplicate search parameters')
    requested=dict(zip(frame.name,frame.value.astype(float)))
    bounds=pd.read_csv(d['bounds']).set_index('name')
    try:
        values=decode(requested,bounds);validate(values,bounds.reset_index())
    except ValueError as exc:
        trial=out/'native_trials'/uuid.uuid4().hex;trial.mkdir(parents=True)
        q=dict(success=False,trial=str(trial),error=str(exc),error_type='ValueError',search_parameters=requested,imputed=False)
        write_json(trial/'receipt.json',q);write_json(out/'last_failure.json',q);raise
    pd.DataFrame(values.items(),columns=['name','value']).to_csv(out/'physical_parameters.csv',index=False)
    try:
        result=evaluate(a.design,out/'physical_parameters.csv',out,not a.no_diagnostics)
    except Exception:
        q=json.loads((out/'last_failure.json').read_text(encoding='utf8'));q['search_parameters']=requested
        write_json(Path(q['trial'])/'receipt.json',q);write_json(out/'last_failure.json',q);raise
    result['search_parameters']=requested
    write_json(Path(result['trial'])/'receipt.json',result);write_json(out/'last_success.json',result)

if __name__=='__main__':main()
