"""Current native injector once, with printed-value checks before model execution."""
from pathlib import Path
import argparse
import sys
import pandas as pd
import re
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.dssat import run_dssat as runner
from src.calibration.all12_joint import check_relations
from src.calibration.single_season_n import read_injected_parameters


def main():
    p=argparse.ArgumentParser();p.add_argument('--param-csv',required=True);p.add_argument('--batch',default='DSSBatch.v48');a=p.parse_args()
    runner.PARAM_CSV=a.param_csv;runner.BATCH_FILE=a.batch;runner.DSSAT_MODEL='CRGRO048';runner.HARVEST_VAR='CHPDT'
    runner.KEEP_SOIL_WATER=True;runner.KEEP_NITROGEN_OUTPUTS=True
    values=runner._read_param_dict(a.param_csv);check_relations(values)
    runner.update_cul_file(param_csv_path=a.param_csv,target_cultivar='TM0008')
    eco=runner._infer_ecotype_from_cul(runner.CUL_FILE,'TM0008') or 'TM0001'
    runner.update_eco_file(param_csv_path=a.param_csv,target_ecotype=eco)
    runner.update_spe_file(param_csv_path=a.param_csv)
    # Current update_spe_file already injects the phosphorus anchors. Repeating
    # the historical four-decimal writer would break their newer precision.
    actual={k:v[0] for k,v in read_injected_parameters(Path.cwd()).items()};check_relations(actual)
    if actual['FL-LF']!=400 or actual['LNREF']<=actual['FNPGN1']:raise ValueError('Printed fixed/timing/N curve violation')
    # Edit only the approved current profile. The legacy soil writer also
    # manufactures an obsolete 26SP profile alias, unnecessary for XXSL2601.
    lines=Path('SOIL.SOL').read_text().splitlines(keepends=True)
    idx=next(i for i,l in enumerate(lines) if l.startswith('@ SCOM'))+1
    matches=list(re.finditer(r'[-+]?(?:\d*\.\d+|\d+)',lines[idx]));field=matches[6]
    season='26SP' if '2601' in runner._resolve_filex_from_batch(a.batch,str(Path.cwd())) else '25SP'
    text=f'{values["SLPF_"+season]:.3f}'.lstrip('0')
    if len(text)>field.end()-field.start():raise ValueError('Fixed SLPF does not fit')
    lines[idx]=lines[idx][:field.start()]+text.rjust(field.end()-field.start())+lines[idx][field.end():]
    Path('SOIL.SOL').write_text(''.join(lines))
    # These approved fields already equal the bundle. Omitting their no-op
    # writers preserves measured mineral-N formatting and the planting label.
    effective={k:v for k,v in values.items() if not k.startswith(('ICNS_','PAGE_','PENV_','SLPF_','SOIL_'))}
    pd.DataFrame(effective.items(),columns=['name','value']).to_csv('native_effective_parameters.csv',index=False)
    runner.PARAM_CSV='native_effective_parameters.csv'
    runner.run_model()


if __name__=='__main__':main()
