import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.param_registry import assert_valid_frozen_bounds, validate_frozen_bounds

src_csv = Path("data/parameter_registry/bounds_frozen/eggplant/eggplant_full_gen_fnpgn3_real_sh2o_13trt_20260922.csv")
dst_proposal = Path("data/parameter_registry/bounds_proposals/eggplant_full_gen_final_opt_13trt_20260922.csv")

with open(src_csv, "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    rows = list(reader)
    fieldnames = reader.fieldnames

updates = {
    # KCAN
    "kcan": {"init": 0.549849, "lower": 0.50, "upper": 0.75, "status": "active"},
    # SIZLF
    "sizlf": {"init": 280.0, "lower": 260.0, "upper": 300.0, "status": "active"},
    # DSWBAR
    "dswbar": {"init": 6.5, "lower": 5.0, "upper": 8.0, "status": "active"},
    # THRSH
    "thrsh": {"init": 8.5, "lower": 8.5, "upper": 8.5, "status": "fixed"},
    # TB1
    "tb1": {"init": 8.35, "lower": 8.0, "upper": 10.0, "status": "active"},
    # SLAREF / SIZREF
    "slaref": {"init": 290.0, "lower": 290.0, "upper": 290.0, "status": "fixed"},
    "sizref": {"init": 290.0, "lower": 290.0, "upper": 290.0, "status": "fixed"},
    # SASC_RATIO
    "sasc_ratio": {"init": 0.92, "lower": 0.92, "upper": 0.92, "status": "fixed"},
    # ICNS_25SP
    "icns_25sp": {"init": 1.0, "lower": 1.0, "upper": 1.0, "status": "fixed"},
    # Organ proteins
    # Leaf
    "prolff": {"init": 0.069018, "lower": 0.04, "upper": 0.11, "status": "active"},
    "prolfg": {"init": 0.17836, "lower": 0.15, "upper": 0.28, "status": "active"},
    "prolfi": {"init": 0.348759, "lower": 0.26, "upper": 0.38, "status": "active"},
    # Stem
    "prostf": {"init": 0.065, "lower": 0.035, "upper": 0.085, "status": "active"},
    "prostg": {"init": 0.169424, "lower": 0.10, "upper": 0.20, "status": "active"},
    "prosti": {"init": 0.200, "lower": 0.16, "upper": 0.25, "status": "active"},
    # Root (Tomato ±5%)
    "prortf": {"init": 0.060, "lower": 0.057, "upper": 0.063, "status": "active"},
    "prortg": {"init": 0.119, "lower": 0.11305, "upper": 0.12495, "status": "active"},
    "prorti": {"init": 0.144, "lower": 0.1368, "upper": 0.1512, "status": "active"},
    # Fruit / Shell
    "proshg": {"init": 0.076748, "lower": 0.06, "upper": 0.14, "status": "active"},
    "proshi": {"init": 0.120, "lower": 0.08, "upper": 0.22, "status": "active"},
    # Phosphorus
    "optlfp_fs": {"init": 0.003209, "lower": 0.0025, "upper": 0.0045, "status": "active"},
    "optstp_fs": {"init": 0.002867, "lower": 0.0020, "upper": 0.0038, "status": "active"},
    "optsdp_fs": {"init": 0.004981, "lower": 0.0038, "upper": 0.0065, "status": "active"},
}

matched = set()
for r in rows:
    nl = r["name"].strip().lower()
    if nl in updates:
        matched.add(nl)
        u = updates[nl]
        for k, v in u.items():
            r[k] = str(v)

print(f"Updated {len(matched)} / {len(updates)} parameters.")
assert matched == set(updates.keys()), f"Missing: {set(updates.keys()) - matched}"

with open(dst_proposal, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"Wrote proposal: {dst_proposal}")
issues = validate_frozen_bounds(str(dst_proposal))
print(f"Validation issues ({len(issues)}):")
for issue in issues:
    print(" ", issue)

assert all(issue.severity != "error" for issue in issues), "Has validation errors!"
print("Proposal validation passed successfully!")
