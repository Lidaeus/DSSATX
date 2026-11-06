"""Create the complete frozen bounds contract for the 8-term N subspace."""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
src = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_joint54_v2_20260729.csv"
dst = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_n_response8_slpf_v1_20260729.csv"
active = {"NMOBMX", "NRCVR", "NSTFAC", "NVSMOB", "RTEXF", "RTNH4", "RTNO3"}
d = pd.read_csv(src, encoding="utf-8-sig")
rows = []
for _, r in d.iterrows():
    name = str(r["name"]).strip().upper()
    if name in active:
        if name == "RTEXF": r["lower"] = 0.025
        elif name == "RTNH4": r["lower"] = 0.004
        elif name == "RTNO3": r["lower"] = 0.006
        r["status"] = "active"
        r["review_note"] = "N-response subspace; user-approved lower-bound relaxation where specified"
    else:
        r["lower"] = r["init"]
        r["upper"] = r["init"]
        r["status"] = "fixed"
        r["review_note"] = "Fixed while identifying nitrogen response subspace"
    rows.append(r.to_dict())
rows.append({"name":"SOIL_SLPF","init":0.92,"lower":0.65,"upper":1.0,"status":"active",
             "pargp":"SOIL_Fertility","location":"SOIL","file":"SOIL.SOL","cultivar":"TM0008",
             "ecotype":"TM0001","mode":"both","review_note":"User-required DSSAT SLPF soil fertility index"})
out = pd.DataFrame(rows, columns=d.columns)
out.to_csv(dst, index=False, encoding="utf-8-sig")
print(dst)
print(out.status.value_counts().to_dict())
