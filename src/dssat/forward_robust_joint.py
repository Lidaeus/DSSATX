"""Joint forward writer with pre-execution checks on actual rounded fields."""
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from src.dssat import run_dssat as runner
from src.dssat.forward_joint import inject_phosphorus
from src.dssat.forward_water_n import inject_environment
from src.calibration.single_season_n import read_injected_parameters
from src.calibration.robust_joint import check_relations

def main():
    p=argparse.ArgumentParser();p.add_argument('--param-csv',required=True);p.add_argument('--batch',default='DSSBatch.v48');a=p.parse_args()
    runner.PARAM_CSV=a.param_csv;runner.BATCH_FILE=a.batch;runner.DSSAT_MODEL='CRGRO048';runner.HARVEST_VAR='CHPDT'
    runner.KEEP_SOIL_WATER=True;runner.KEEP_NITROGEN_OUTPUTS=True
    values=runner._read_param_dict(a.param_csv)
    check_relations(values)
    runner.update_cul_file(param_csv_path=a.param_csv,target_cultivar='TM0008')
    ecotype=runner._infer_ecotype_from_cul(runner.CUL_FILE,'TM0008') or 'TM0001'
    runner.update_eco_file(param_csv_path=a.param_csv,target_ecotype=ecotype)
    runner.update_spe_file(param_csv_path=a.param_csv)
    inject_phosphorus(runner.SPE_FILE,values);inject_environment(Path.cwd(),values)
    actual={k:v[0] for k,v in read_injected_parameters(Path.cwd()).items()}
    check_relations(actual)
    runner.run_model()

if __name__=='__main__':main()
