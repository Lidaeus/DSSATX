"""Create the next E02 water/nitrogen-response bounds proposal from v3."""

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_posterior_soil_v3_20260802.csv"
OUT = ROOT / "data/parameter_registry/bounds_proposals/eggplant_e02_posterior_soil_wnresponse_v1_20260802.csv"

# Adjust only parameters whose final posterior was materially concentrated at
# a boundary and whose model role is water/N response. The changes are modest
# and remain inside the physical bounds in param_registry.py.
ADJUSTMENTS = {
    "RTNH4": (0.0015, 0.020613286999999994, "lower widened after 40% posterior near lower bound"),
    "NSTFAC": (0.68, 0.9429531299999999, "lower widened after 25% posterior near lower bound"),
    "NMOBMX": (0.02, 0.14, "upper widened after 50% posterior near upper bound"),
    "NVSMOB": (0.22, 0.5310603399999999, "lower widened after 55% posterior near lower bound"),
    "CMOBMX": (0.005, 0.05, "lower widened after 73% posterior near lower bound"),
    "RWUMX": (0.015, 0.075, "upper widened after 46% posterior near upper bound; lower modestly relaxed"),
    "DSWBAR": (7.0, 30.0, "lower widened after 45% posterior near lower bound"),
}

frame = pd.read_csv(SOURCE, encoding="utf-8-sig")
for name, (lower, upper, note) in ADJUSTMENTS.items():
    mask = frame["name"].astype(str).str.upper().eq(name)
    if int(mask.sum()) != 1:
        raise ValueError(f"Expected one row for {name}")
    frame.loc[mask, "lower"] = lower
    frame.loc[mask, "upper"] = upper
    frame.loc[mask, "notes"] = note
frame.to_csv(OUT, index=False, encoding="utf-8-sig")
print(OUT)
