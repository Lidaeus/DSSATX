"""CLI: evaluate a calibration experiment from frozen comparison artefacts.

Reads a comparison CSV (observed/simulated pairs, frozen by export_paper_data
or produced by the experiment runner) and writes the three article result
tables: comparison_raw.csv, metrics_rawscale.csv, residual_diagnostics.csv.

The article profile enforces the CHPDT-only harvest contract (HWAM/PWAD/PWAI
rejected; CHFPW diagnostic-only).  This is a reporting/diagnostic entry -- it
imports no plotting library.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.reporting.experiment_evaluation import evaluate_experiment


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a calibration experiment (raw-scale metrics + residual diagnostics)."
    )
    parser.add_argument("--comparison-csv", required=True, help="Frozen observed/simulated pairs CSV.")
    parser.add_argument("--out-dir", required=True, help="Output directory for result tables.")
    parser.add_argument("--trajectory-csv", default=None, help="Optional trajectory CSV (reserved).")
    parser.add_argument("--treatment-metadata-csv", default=None, help="Optional treatment metadata.")
    parser.add_argument("--receipt-json", default=None, help="Optional experiment receipt (for experiment_id).")
    parser.add_argument("--profile", default="article_rawscale_v1")
    parser.add_argument("--seed", type=int, default=20260724)
    args = parser.parse_args()

    artefacts = evaluate_experiment(
        comparison_csv=args.comparison_csv,
        out_dir=args.out_dir,
        trajectory_csv=args.trajectory_csv,
        treatment_metadata_csv=args.treatment_metadata_csv,
        receipt_json=args.receipt_json,
        profile=args.profile,
        seed=args.seed,
    )
    print(json.dumps({k: str(v) for k, v in artefacts.items()}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
