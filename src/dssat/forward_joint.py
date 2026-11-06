"""Joint-case forward entry, including explicit C31 phosphorus field injection."""
from pathlib import Path
import argparse
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.dssat import run_dssat as runner


def inject_phosphorus(path, values):
    markers = {"OPTLFP_FS": "OPTLFP-EM,", "OPTSTP_FS": "OPTSTP-EM,", "OPTSDP_FS": "OPTSDP-EM,"}
    number = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[Ee][-+]?\d+)?")
    path = Path(path)
    lines = path.read_text().splitlines(keepends=True)
    for name, marker in markers.items():
        if name not in values:
            continue
        indices = [i for i,line in enumerate(lines) if marker in line]
        if len(indices) != 1:
            raise ValueError(f"Ambiguous phosphorus field: {name}")
        i = indices[0]
        matches = list(number.finditer(lines[i].split("Optimum")[0]))
        if len(matches) != 3:
            raise ValueError("Phosphorus row must contain three growth stages")
        field = matches[2]
        text = f"{float(values[name]):{field.end()-field.start()}.4f}"
        if len(text) != field.end()-field.start():
            raise ValueError("Phosphorus value does not fit original DSSAT field")
        lines[i] = lines[i][:field.start()] + text + lines[i][field.end():]
    path.write_text("".join(lines))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--param-csv",required=True)
    parser.add_argument("--batch",default="DSSBatch.v48")
    args=parser.parse_args()
    runner.PARAM_CSV=args.param_csv;runner.BATCH_FILE=args.batch
    runner.DSSAT_MODEL="CRGRO048";runner.HARVEST_VAR="CHPDT"
    runner.KEEP_SOIL_WATER=True;runner.KEEP_NITROGEN_OUTPUTS=True
    values=runner._read_param_dict(args.param_csv)
    runner.validate_candidate_parameters(values)
    runner.update_cul_file(param_csv_path=args.param_csv,target_cultivar="TM0008")
    ecotype=runner._infer_ecotype_from_cul(runner.CUL_FILE,"TM0008") or "TM0001"
    runner.update_eco_file(param_csv_path=args.param_csv,target_ecotype=ecotype)
    runner.update_spe_file(param_csv_path=args.param_csv)
    inject_phosphorus(runner.SPE_FILE,values)
    runner.update_soil_file(param_csv_path=args.param_csv,batch_file=args.batch)
    runner.run_model()


if __name__=="__main__":main()
