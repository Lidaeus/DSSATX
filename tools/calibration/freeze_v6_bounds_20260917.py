"""Generate and freeze eggplant_full_genetic_98pct_v6_20260917 bounds.

Key enhancements from V5:
1. Inherits posterior best values (Realization 46) as initial values (init).
2. Expands bounds by ~10% for the 4 parameters that hit/approached boundaries in V5:
   - kcan: lower 0.35 -> 0.30 (physical bounds [0.20, 1.00])
   - rwdth: lower 0.80 -> 0.70 (physical bounds [0.20, 2.50])
   - fnpgn1: lower 0.50 -> 0.40 (physical bounds [0.00, 10.00])
   - prostf: upper 0.12 -> 0.14 (physical bounds [0.00, 1.00])
3. Implements D2 decision:
   - icns_26sp: init 1.0, lower 0.80, upper 1.20, status 'active' (calibrated in narrow band around 1.0)
   - icns_25sp: init 1.0, lower 1.0, upper 1.0, status 'fixed'
4. All parameter bounds strictly checked and clamped against src/common/param_registry.py: PHYSICAL_BOUNDS.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd
import yaml

ROOT = Path("D:/Tomato_Cal")
sys.path.insert(0, str(ROOT))

from src.common.param_registry import PHYSICAL_BOUNDS

V5_BOUNDS_CSV = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_full_genetic_98pct_v5_20260915.csv"
V5_BEST_CSV = ROOT / "workspace/runs/full_genetic_98pct_v5_20260915/full_gen98_v5_best_parameters_fixed.csv"

OUT_CSV = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_full_genetic_98pct_v6_20260917.csv"
OUT_YAML = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_full_genetic_98pct_v6_20260917.yaml"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def build_v6_bounds():
    df_v5 = pd.read_csv(V5_BOUNDS_CSV)
    df_best = pd.read_csv(V5_BEST_CSV)
    best_map = dict(zip(df_best["name"].astype(str).str.lower(), df_best["value"]))

    df_v6 = df_v5.copy()

    # 1. Update initial values from V5 best realization
    for idx, row in df_v6.iterrows():
        pname_low = str(row["name"]).strip().lower()
        if pname_low in best_map:
            val = float(best_map[pname_low])
            # Ensure init is within [lower, upper]
            lb = float(row["lower"])
            ub = float(row["upper"])
            df_v6.at[idx, "init"] = max(lb, min(ub, val))

    # 2. Relax boundary hitting parameters by 10%
    relaxations = {
        "kcan": {"lower": 0.30},
        "rwdth": {"lower": 0.70},
        "fnpgn1": {"lower": 0.40},
        "prostf": {"upper": 0.14},
    }
    for idx, row in df_v6.iterrows():
        pname_low = str(row["name"]).strip().lower()
        if pname_low in relaxations:
            for bound_key, new_val in relaxations[pname_low].items():
                df_v6.at[idx, bound_key] = new_val
                print(f"[RELAX] {row['name']} {bound_key} -> {new_val}")

    # 3. Apply D2 decision for icns_26sp
    for idx, row in df_v6.iterrows():
        pname_low = str(row["name"]).strip().lower()
        if pname_low == "icns_26sp":
            df_v6.at[idx, "init"] = 1.0
            df_v6.at[idx, "lower"] = 0.80
            df_v6.at[idx, "upper"] = 1.20
            df_v6.at[idx, "status"] = "active"
            print(f"[D2] icns_26sp activated: [0.80, 1.20], init=1.0")
        elif pname_low == "icns_25sp":
            df_v6.at[idx, "init"] = 1.0
            df_v6.at[idx, "lower"] = 1.0
            df_v6.at[idx, "upper"] = 1.0
            df_v6.at[idx, "status"] = "fixed"

    # 4. Physical bounds verification and clamping
    for idx, row in df_v6.iterrows():
        pname = str(row["name"]).strip()
        pname_up = pname.upper()
        lb = float(row["lower"])
        ub = float(row["upper"])
        init_val = float(row["init"])

        if pname_up in PHYSICAL_BOUNDS:
            phys_min, phys_max = PHYSICAL_BOUNDS[pname_up]
            assert lb >= phys_min - 1e-7, f"{pname} lower {lb} < phys_min {phys_min}"
            assert ub <= phys_max + 1e-7, f"{pname} upper {ub} > phys_max {phys_max}"
            assert lb <= ub, f"{pname} lower {lb} > upper {ub}"
            init_clamped = max(lb, min(ub, init_val))
            df_v6.at[idx, "init"] = init_clamped

    # Save CSV
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_v6.to_csv(OUT_CSV, index=False, float_format="%.6f")
    csv_hash = sha256_file(OUT_CSV)
    print(f"[SAVE] Saved {OUT_CSV} (SHA-256: {csv_hash})")

    active_cnt = len(df_v6[df_v6["status"] == "active"])
    fixed_cnt = len(df_v6[df_v6["status"] == "fixed"])
    print(f"[STATS] Active: {active_cnt}, Fixed: {fixed_cnt}, Total: {len(df_v6)}")

    # Generate metadata YAML
    yaml_data = {
        "bounds_id": "eggplant_full_genetic_98pct_v6_20260917",
        "crop": "eggplant",
        "parent_bounds_id": "eggplant_full_genetic_98pct_v5_20260915",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "Antigravity AI / Lidaeus",
        "notes": (
            "V6 full genetic parameter bounds following 2026-09-17 data reconstruction and dual-plot soil refresh. "
            "Inherits Realization 46 posterior best parameters, relaxes 4 boundary-hitting parameters by ~10% "
            "(kcan, rwdth, fnpgn1, prostf), and activates icns_26sp in [0.80, 1.20] per Decision D2."
        ),
        "sha256": csv_hash,
        "n_active": int(active_cnt),
        "n_fixed": int(fixed_cnt),
        "n_total": len(df_v6),
        "sampling_method": "sobol",
        "calibration_scope": "25SP (W3N0, W3N3, W1N0, W1N3) + 26SP (W2N0, W2N3, W1N0, W1N3)",
    }
    with OUT_YAML.open("w", encoding="utf-8") as f:
        yaml.safe_dump(yaml_data, f, sort_keys=False, allow_unicode=True)
    print(f"[SAVE] Saved {OUT_YAML}")


if __name__ == "__main__":
    build_v6_bounds()
