import pandas as pd
import numpy as np
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/analysis"))

from tools.calibration.profile_biomass_scale_parameters_20260827 import run_deterministic_eval, BASE_PARAM_FILE, PROFILE_DIR

df_base = pd.read_csv(BASE_PARAM_FILE)

combos = [
    {"TRIFL": 0.16, "LFMAX": 1.55, "SLAVR": 220.0, "SFDUR": 18.0},
    {"TRIFL": 0.18, "LFMAX": 1.55, "SLAVR": 220.0, "SFDUR": 18.0},
    {"TRIFL": 0.15, "LFMAX": 1.50, "SLAVR": 200.0, "SFDUR": 16.0},
    {"TRIFL": 0.17, "LFMAX": 1.50, "SLAVR": 220.0, "SFDUR": 18.0},
    {"TRIFL": 0.16, "LFMAX": 1.60, "SLAVR": 220.0, "SFDUR": 16.0},
    {"TRIFL": 0.18, "LFMAX": 1.60, "SLAVR": 240.0, "SFDUR": 18.0},
    {"TRIFL": 0.15, "LFMAX": 1.55, "SLAVR": 240.0, "SFDUR": 18.0},
]

print("=== Evaluating Biomass Scale Combination Profiles ===")
for idx, c in enumerate(combos):
    df_p = df_base.copy()
    for k, v in c.items():
        match = df_p["name"].astype(str).str.lower() == k.lower()
        if match.any():
            df_p.loc[match, "value"] = v
        else:
            df_p = pd.concat([df_p, pd.DataFrame([{"name": k, "value": v}])], ignore_index=True)

    run_id = f"combo_{idx}"
    p_file = PROFILE_DIR / f"{run_id}_params.csv"
    df_p.to_csv(p_file, index=False)

    res = run_deterministic_eval(p_file, run_id)
    if res.get("status") == "success":
        t_val = c["TRIFL"]
        l_val = c["LFMAX"]
        sl_val = c["SLAVR"]
        sf_val = c["SFDUR"]
        print(f"Combo {idx}: TRIFL={t_val}, LFMAX={l_val}, SLAVR={sl_val}, SFDUR={sf_val}")
        print(f"  25SP: Yield Bias = {res['25SP_DRY_CUM_BIAS']:+.1f} kg/ha (NSE = {res['25SP_DRY_CUM_NSE']:+.3f}), SWAD NSE = {res['25SP_SWAD_NSE']:+.3f}, LWAD NSE = {res['25SP_LWAD_NSE']:+.3f}, LAID NSE = {res['25SP_LAID_NSE']:+.3f}")
        print(f"  26SP: Yield Bias = {res['26SP_DRY_CUM_BIAS']:+.1f} kg/ha (NSE = {res['26SP_DRY_CUM_NSE']:+.3f}), SWAD NSE = {res['26SP_SWAD_NSE']:+.3f}, LWAD NSE = {res['26SP_LWAD_NSE']:+.3f}, LAID NSE = {res['26SP_LAID_NSE']:+.3f}")
        print("-" * 80)
