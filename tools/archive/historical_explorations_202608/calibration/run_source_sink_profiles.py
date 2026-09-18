import pandas as pd
import numpy as np
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/analysis"))

from tools.calibration.profile_biomass_scale_parameters_20260827 import run_deterministic_eval, BASE_PARAM_FILE, PROFILE_DIR

df_base = pd.read_csv(BASE_PARAM_FILE)

params_to_test = {
    "CADSTF": [0.0, 0.20, 0.40, 0.60, 0.80],
    "CADPR1": [0.0, 0.10, 0.20, 0.30, 0.40],
    "PM06": [0.60, 0.70, 0.80, 0.90, 0.95],
    "PARMAX": [0.80, 0.90, 0.95, 0.98, 1.00],
    "LFMAX": [1.40, 1.50, 1.60, 1.70],
}

print("=== Evaluating Key Source-Sink Parameters ===")
for p, vals in params_to_test.items():
    print(f"\n--- Profiling {p} ---")
    for val in vals:
        df_p = df_base.copy()
        match = df_p["name"].astype(str).str.lower() == p.lower()
        if match.any():
            df_p.loc[match, "value"] = val
        else:
            df_p = pd.concat([df_p, pd.DataFrame([{"name": p, "value": val}])], ignore_index=True)

        run_id = f"prof_{p}_{val}"
        p_file = PROFILE_DIR / f"{run_id}_params.csv"
        df_p.to_csv(p_file, index=False)

        res = run_deterministic_eval(p_file, run_id)
        if res.get("status") == "success":
            y25_b = res["25SP_DRY_CUM_BIAS"]
            y25_n = res["25SP_DRY_CUM_NSE"]
            s25_n = res["25SP_SWAD_NSE"]
            l25_n = res["25SP_LWAD_NSE"]
            y26_b = res["26SP_DRY_CUM_BIAS"]
            y26_n = res["26SP_DRY_CUM_NSE"]
            s26_n = res["26SP_SWAD_NSE"]
            l26_n = res["26SP_LWAD_NSE"]
            print(f"  {p} = {val:5.2f} | 25SP Yld Bias: {y25_b:+7.1f} (NSE={y25_n:+.2f}), SWAD NSE={s25_n:+.2f}, LWAD NSE={l25_n:+.2f} | 26SP Yld Bias: {y26_b:+7.1f} (NSE={y26_n:+.2f}), SWAD NSE={s26_n:+.2f}, LWAD NSE={l26_n:+.2f}")
