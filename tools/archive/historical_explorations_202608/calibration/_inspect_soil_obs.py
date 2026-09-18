"""Quick inspection of soil water observations across three seasons."""
import pandas as pd
from pathlib import Path

BASE = Path(r"d:\Tomato_Cal\data\user\experiments")
seasons = [
    ("25SP", BASE / "xxql2501_actual_trial_calibration_v2_20260726"),
    ("25FA", BASE / "xxql2502_actual_trial_calibration_v2_20260726"),
    ("26SP", BASE / "xxql2601_actual_trial_calibration_v2_20260726"),
]

for season_id, bundle in seasons:
    csv = bundle / "soil_water_observations.csv"
    if not csv.is_file():
        print(f"{season_id}: MISSING {csv}")
        continue
    df = pd.read_csv(csv)
    init_only = df[df["initial_condition_only"] == True]
    phi = df[df["phi_role"] == "soil_water_phi"]
    print(f"{season_id}: total={len(df)}, init_cond={len(init_only)}, phi={len(phi)}")
    print(f"  treatments: {sorted(df['trno'].unique())}")
    print(f"  depths: {sorted(df['depth_label'].unique())}")
    print(f"  dates: {sorted(df['date'].unique())}")
    print()
