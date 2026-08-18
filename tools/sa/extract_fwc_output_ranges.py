from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.sensitivity.replay_morris_failure import read_candidate, write_candidate_csv
from src.sensitivity.sa_model import compute_indicators


def replay_case(case_dir: str, out_dir: str):
    root = Path(case_dir)
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    obs_order = [line.strip() for line in (root / 'sa_obs_order.txt').read_text(encoding='utf-8').splitlines() if line.strip()]
    params = pd.read_csv(root / 'sa_sen_morris.sen.par.csv')
    run_manifest = {}
    for line in (root / 'run_manifest.yaml').read_text(encoding='utf-8').splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            run_manifest[k.strip()] = v.strip().strip("'")
    input_dir = run_manifest['input_dir']
    cultivar = run_manifest.get('cultivar', 'TM0008')
    batch_path = Path(input_dir) / 'DSSBatch.v48'

    all_rows = []
    for run_id in params['run_id'].tolist():
        run_dir = dest / f'run_{int(run_id):04d}'
        run_dir.mkdir(parents=True, exist_ok=True)
        candidate = read_candidate(root / 'sa_sen_morris.sen.par.csv', int(run_id))
        param_csv = write_candidate_csv(candidate, run_dir / 'sa_params.csv')
        out_path = run_dir / 'SA_Indicators.OUT'
        compute_indicators(
            workspace_dir=str(run_dir),
            batch_path=str(batch_path),
            cultivar=cultivar,
            param_csv_path=str(param_csv),
            out_path=str(out_path),
            obs_order_path=str(root / 'sa_obs_order.txt'),
            input_dir=str(input_dir),
            failure_artifact_dir=str(run_dir / 'failure_artifacts'),
        )
        values = pd.read_csv(out_path, header=None, names=['value'])
        values['observation_name'] = obs_order[:len(values)]
        values['value'] = pd.to_numeric(values['value'], errors='coerce')
        values['run_id'] = int(run_id)
        all_rows.append(values)

    frame = pd.concat(all_rows, ignore_index=True)
    target = frame[frame['observation_name'].str.contains('FWC_END|FWC_PEAK|PDMCD_END|PDMCD_PEAK|FWC_FROM_RATIO_END', regex=True)].copy()
    target['metric'] = target['observation_name'].str.replace(r'^(TN\d+|WN_[A-Z0-9_]+)_', '', regex=True)
    target['treatment'] = target['observation_name'].str.extract(r'^(TN\d+|WN_[A-Z0-9_]+)')[0]
    metric_ranges = target.groupby('metric')['value'].agg(['min','max','mean']).reset_index()
    treatment_ranges = target.groupby(['treatment','metric'])['value'].agg(['min','max','mean']).reset_index()
    frame.to_csv(dest / 'all_indicator_outputs.csv', index=False, encoding='utf-8-sig')
    metric_ranges.to_csv(dest / 'fruit_water_true_metric_ranges.csv', index=False, encoding='utf-8-sig')
    treatment_ranges.to_csv(dest / 'fruit_water_true_treatment_ranges.csv', index=False, encoding='utf-8-sig')
    (dest / 'fruit_water_true_ranges.json').write_text(
        json.dumps(
            {
                'case_dir': str(root),
                'metric_ranges': metric_ranges.to_dict(orient='records'),
            },
            ensure_ascii=False,
            indent=2,
        ) + '\n',
        encoding='utf-8',
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case-dir', required=True)
    parser.add_argument('--out-dir', required=True)
    args = parser.parse_args()
    replay_case(args.case_dir, args.out_dir)
