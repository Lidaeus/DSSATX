"""Generate bounds proposal for CROPGRO-Eggplant 60 genetic parameters (>98% sensitivity)."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, ".")

from src.common.param_registry import PHYSICAL_BOUNDS, assert_valid_frozen_bounds

# 1. Parse the 60 parameters and bounds from the canonical plan report
doc_path = Path("docs/reports/CROPGRO_Eggplant_全量主效遗传参数98敏感度覆盖率定方案_20260914.md")
lines = doc_path.read_text(encoding="utf-8").splitlines()

plan_params = {}
fl_vs_spec = None
for line in lines[304:367]:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) >= 13 and parts[1].isdigit():
        idx = int(parts[1])
        code = parts[2].strip("` ").upper()
        pargp = parts[3].strip("` ")
        file_ = parts[4].strip("` ")
        lower = float(parts[9].replace("*", "").strip())
        upper = float(parts[10].replace("*", "").strip())
        init = float(parts[11].replace("*", "").strip())
        plan_params[code] = {
            "idx": idx,
            "name": code.lower(),
            "pargp": pargp,
            "file": file_,
            "lower": lower,
            "upper": upper,
            "init": init,
            "status": "active",
        }
    elif "FL-VS" in line:
        parts = [p.strip() for p in line.split("|")]
        code = "FL-VS"
        lower = float(parts[9].replace("*", "").strip())
        upper = float(parts[10].replace("*", "").strip())
        init = float(parts[11].replace("*", "").strip())
        fl_vs_spec = {
            "name": code.lower(),
            "lower": lower,
            "upper": upper,
            "init": init,
            "status": "fixed",
        }

print(f"Loaded {len(plan_params)} parameters from plan doc.")
assert len(plan_params) == 60, f"Expected 60 parameters, got {len(plan_params)}"
assert fl_vs_spec is not None, "Missing FL-VS spec"

# 2. Read base template CSV
base_csv_path = Path("data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_wnp_s1_s5_20260914.csv")
with open(base_csv_path, "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    fieldnames = list(reader.fieldnames)
    base_rows = list(reader)

print(f"Loaded {len(base_rows)} rows from {base_csv_path}")

# 3. Update rows
new_rows = []
active_seen = set()

for row in base_rows:
    name_u = row["name"].strip().upper()
    r = dict(row)
    if name_u in plan_params:
        spec = plan_params[name_u]
        r["init"] = f"{spec['init']:.6g}"
        r["lower"] = f"{spec['lower']:.6g}"
        r["upper"] = f"{spec['upper']:.6g}"
        r["status"] = "active"
        active_seen.add(name_u)
    elif name_u == "FL-VS":
        r["init"] = f"{fl_vs_spec['init']:.6g}"
        r["lower"] = f"{fl_vs_spec['lower']:.6g}"
        r["upper"] = f"{fl_vs_spec['upper']:.6g}"
        r["status"] = "fixed"
    else:
        # Fixed or disabled
        status = r.get("status", "fixed").strip().lower()
        if status != "disabled":
            r["status"] = "fixed"
            init_val = float(r["init"])
            r["lower"] = f"{init_val:.6g}"
            r["upper"] = f"{init_val:.6g}"
        else:
            init_val = float(r["init"])
            r["lower"] = f"{init_val:.6g}"
            r["upper"] = f"{init_val:.6g}"
    new_rows.append(r)

missing_active = set(plan_params.keys()) - active_seen
assert not missing_active, f"Missing active parameters in base CSV: {missing_active}"

print(f"Updated {len(new_rows)} rows ({len(active_seen)} active).")

# 4. Write to proposal CSV
out_proposal = Path("data/parameter_registry/bounds_proposals/eggplant_full_genetic_98pct_20260914.csv")
out_proposal.parent.mkdir(parents=True, exist_ok=True)
with open(out_proposal, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(new_rows)

print(f"Proposal written to {out_proposal}")

# 5. Validate proposal
issues = assert_valid_frozen_bounds(out_proposal)
for w in [i for i in issues if i.severity == "warning"]:
    print(f"WARNING: {w.message}")

print("Validation succeeded without errors!")
