"""Freeze a 25FA conditional bounds set with only 12 temperature terms active."""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_posterior_soil_wnresponse_v1_20260802.csv"
BEST = ROOT / "workspace/runs/e02_joint62_posterior_soil_wnresponse_200x5_20260802/best_member_metrics_rawscale/best_member_parameters.csv"
OUT = ROOT / "data/parameter_registry/bounds_proposals/eggplant_e02_25fa_temp12_from_wnresponse200x5_20260802.csv"
ACTIVE = {"TB1", "TB2", "TB3", "TM1", "TM2", "TM3", "TO11", "TO12", "TO13", "TO21", "TO22", "TO23"}

b = pd.read_csv(SOURCE, encoding="utf-8-sig")
p = pd.read_csv(BEST, encoding="utf-8-sig").iloc[0]
lookup = {str(k).upper(): float(v) for k, v in p.items() if str(k).upper() != "REAL_NAME"}
b["status"] = b["name"].astype(str).str.upper().map(lambda x: "active" if x in ACTIVE else "fixed")
for i, row in b.iterrows():
    name = str(row["name"]).upper()
    if name in lookup:
        value = lookup[name]
        value = min(max(value, float(row["lower"])), float(row["upper"]))
        b.at[i, "init"] = value
    if name in ACTIVE:
        b.at[i, "notes"] = "25FA-only 12-temperature diagnostic calibration from e02_joint62_posterior_soil_wnresponse_200x5_20260802 best member"
    else:
        b.at[i, "lower"] = b.at[i, "init"]
        b.at[i, "upper"] = b.at[i, "init"]
        b.at[i, "notes"] = "Fixed at e02_joint62_posterior_soil_wnresponse_200x5_20260802 best member for 25FA conditional trial"
b.to_csv(OUT, index=False, encoding="utf-8-sig")
print(OUT)
