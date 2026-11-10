"""Versioned joint forward writer; only KEP and shared SLDR extend sealed inputs."""
from pathlib import Path
import argparse
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.dssat import run_dssat as runner
from src.dssat.forward_joint import inject_phosphorus


def inject_environment(work, values):
    work = Path(work)
    spe = work / 'TMGRO048.SPE'
    lines = spe.read_text().splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if 'KEP, EORATIO' in line]
    if len(matches) != 1:
        raise ValueError('Ambiguous KEP field')
    i = matches[0]
    # Retain the second field (EORATIO) and all following text byte for byte.
    if len(lines[i][:6].split()) != 1:
        raise ValueError('Unexpected KEP fixed-width field')
    lines[i] = f"{values['KEP']:6.3f}" + lines[i][6:]
    spe.write_text(''.join(lines))
    soil = work / 'SOIL.SOL'
    lines = soil.read_text().splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.startswith('@ SCOM')]
    if len(matches) != 1:
        raise ValueError('Expected one shared soil profile')
    i = matches[0] + 1
    if abs(float(lines[i][18:24])-float(lines[i].split()[3])) > 1e-10:
        raise ValueError('Unexpected SLDR field')
    lines[i] = lines[i][:18] + f"{values['SOIL_SLDR']:6.3f}" + lines[i][24:]
    soil.write_text(''.join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--param-csv', required=True)
    parser.add_argument('--batch', default='DSSBatch.v48')
    args = parser.parse_args()
    runner.PARAM_CSV = args.param_csv
    runner.BATCH_FILE = args.batch
    runner.DSSAT_MODEL = 'CRGRO048'
    runner.HARVEST_VAR = 'CHPDT'
    runner.KEEP_SOIL_WATER = True
    runner.KEEP_NITROGEN_OUTPUTS = True
    values = runner._read_param_dict(args.param_csv)
    runner.validate_candidate_parameters(values)
    runner.update_cul_file(param_csv_path=args.param_csv, target_cultivar='TM0008')
    ecotype = runner._infer_ecotype_from_cul(runner.CUL_FILE, 'TM0008') or 'TM0001'
    runner.update_eco_file(param_csv_path=args.param_csv, target_ecotype=ecotype)
    runner.update_spe_file(param_csv_path=args.param_csv)
    inject_phosphorus(runner.SPE_FILE, values)
    inject_environment(Path.cwd(), values)
    # No broad soil rewrite: the only authorized profile change is shared SLDR.
    runner.run_model()


if __name__ == '__main__':
    main()
