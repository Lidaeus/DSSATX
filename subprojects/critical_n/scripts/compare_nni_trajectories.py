#!/usr/bin/env python3
"""Diagnostic script comparing standing NNI vs cumulative effective NNI trajectories.

Demonstrates the elimination of sawtooth jumps across fruit harvests:
- Standing NNI shows artificial jumps of +0.05 to +0.09 at harvest dates
  due to the removal of low-N mature fruits.
- Cumulative effective NNI (W_eff = CWAD + CUMHARVEST) is smooth,
  continuous, and monotonic.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from subprojects.critical_n.adapters.pest_cnc_exporter import export_cnc_dataframe


def compare_trajectories(run_dir: Path, output_csv: Path | None = None) -> pd.DataFrame:
    df = export_cnc_dataframe(run_dir)
    valid_df = df[df["is_valid"]].copy()

    # Identify harvest jump days: where cum_harvest_dm increased from previous day
    valid_df["harvest_dm_inc"] = valid_df.groupby("run_id")["cum_harvest_dm"].diff().fillna(0.0)
    valid_df["standing_nni_jump"] = valid_df.groupby("run_id")["n_act_standing"].diff().fillna(0.0)
    valid_df["cum_nni_diff"] = valid_df.groupby("run_id")["nni"].diff().fillna(0.0)

    harvest_events = valid_df[valid_df["harvest_dm_inc"] > 20.0]

    print(f"Total valid daily steps: {len(valid_df)}")
    print(f"Identified fruit harvest events: {len(harvest_events)}")

    if not harvest_events.empty:
        print("\n--- SAMPLE HARVEST EVENTS: STANDING VS CUMULATIVE JUMPS ---")
        cols_to_show = [
            "run_id",
            "treatment_id",
            "das",
            "cwad",
            "cum_harvest_dm",
            "harvest_dm_inc",
            "w_standing",
            "w_eff",
            "n_act_standing",
            "n_act_cum",
            "nni",
            "standing_nni_jump",
            "cum_nni_diff",
        ]
        sample = harvest_events[cols_to_show].head(8)
        print(sample.to_string(index=False))

    if output_csv:
        valid_df.to_csv(output_csv, index=False)
        print(f"\nSaved detailed trajectory comparison to {output_csv}")

    return valid_df


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare standing vs cumulative NNI trajectories.")
    parser.add_argument("--run-dir", type=str, default="scratch/test_0.5")
    parser.add_argument("--out-csv", type=str, default=None)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"Error: {run_dir} is not a directory", file=sys.stderr)
        return 1

    out_csv = Path(args.out_csv) if args.out_csv else None
    compare_trajectories(run_dir, out_csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
