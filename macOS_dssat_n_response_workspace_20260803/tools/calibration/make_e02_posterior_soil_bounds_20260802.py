"""Create the reviewed bounds proposal for the posterior-narrow soil-uncertainty run.

The proposal is deliberately reproducible: existing active genetic bounds are
contracted around the final 5--95 percent posterior interval (with a small
padding and a minimum width), while water/N parameters remain active.  The
soil hydraulic/physical groups are added from the actual IBSB910017 profile.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.calibration.build_pest import _read_soil_layers


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_joint62_v8_softn_response_20260802.csv"
POST = ROOT / "workspace/runs/e02_joint62_softn_response_95pct_dmc5_formal_200x5_20260802/e02_joint62_softn_response_95pct_dmc5_formal_200x5_20260802.5.par.csv"
SOIL = ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729/SOIL.SOL"


def _key(name: str) -> str:
    return str(name).strip().lower()


def make(out: Path) -> pd.DataFrame:
    base = pd.read_csv(BASE, encoding="utf-8-sig")
    post = pd.read_csv(POST)
    active = base[base["status"].astype(str).str.lower().eq("active")].copy()
    pcols = {_key(c): c for c in post.columns if c != "real_name"}

    # Narrow only existing adjustable terms.  Fixed rows are retained verbatim.
    for i, row in base.iterrows():
        if str(row["status"]).lower() != "active":
            continue
        # Seasonal offset terms are PEST-only coordinates and must remain
        # centered at zero; their physical bounds are projected separately.
        if str(row["name"]).upper().endswith("_AUT"):
            continue
        c = pcols.get(_key(row["name"]))
        if c is None:
            continue
        vals = pd.to_numeric(post[c], errors="coerce").dropna()
        if vals.empty:
            continue
        q05, q95 = vals.quantile([0.05, 0.95]).tolist()
        old_lb, old_ub = float(row["lower"]), float(row["upper"])
        old_w = old_ub - old_lb
        pad = 0.10 * max(q95 - q05, 1e-12)
        lb = max(old_lb, q05 - pad)
        ub = min(old_ub, q95 + pad)
        # Avoid a numerically unidentifiable razor-thin interval.
        min_w = max(1e-8, 0.15 * old_w)
        if ub - lb < min_w:
            mid = float(vals.median())
            lb = max(old_lb, mid - min_w / 2.0)
            ub = min(old_ub, mid + min_w / 2.0)
        if ub <= lb:
            continue
        base.at[i, "lower"] = lb
        base.at[i, "upper"] = ub
        base.at[i, "init"] = min(max(float(row["init"]), lb), ub)
        base.at[i, "review_note"] = "Posterior q05-q95 with 10% padding; minimum 15% of prior width."

    # Requested SPE water/N-linked terms absent from the 62-bound file.
    extras = [
        ("LNREF", 4.5, 3.0, 6.0, "SPE_Other"),  # registry hard bound is 3--6
        ("CMOBMX", 0.022, 0.010, 0.050, "SPE_Other"),
        ("RWUMX", 0.040, 0.020, 0.060, "SPE_Other"),
        ("DSWBAR", 15.0, 10.0, 30.0, "SPE_Other"),
        ("XFRMAX", 0.0, 0.0, 0.50, "SPE_Other"),
    ]
    for name, init, lb, ub, group in extras:
        if name in set(base["name"]):
            continue
        base.loc[len(base)] = {
            "name": name, "init": init, "lower": lb, "upper": ub,
            "status": "active", "pargp": group, "location": "SPE",
            "file": "TMGRO048.SPE.base", "cultivar": "TM0008",
            "ecotype": "TM0001", "mode": "both",
            "review_note": "Requested water/N-linked SPE term; physical hard bounds retained.",
        }

    # Add all eight layers present in the IBSB910017 profile.  The four groups
    # are intentionally grouped by layer, preserving SLLL < SDUL < SSAT.
    layers = _read_soil_layers(str(SOIL), "IBTM910017")
    if len(layers) != 8:
        raise RuntimeError(f"Expected 8 IBSB910017 layers, found {len(layers)}")
    for i, layer in enumerate(layers, start=1):
        # Broad measurement uncertainty is scientifically relevant, but DSSAT
        # can become numerically singular when all layers move by 10--20% at
        # once.  The small-run engineering domain therefore starts with a
        # conservative ±2% density and ±5% LL/SAT envelope; these are active
        # nuisance groups and can be widened after a stable smoke is proven.
        vals = {"SBDM": (0.98, 1.02), "SLLL": (0.95, 1.05)}
        for field, (lofac, hifac) in vals.items():
            name = f"SOIL_{field}_{i:02d}"
            if name in set(base["name"]):
                continue
            init = float(layer[field])
            lb, ub = init * lofac, init * hifac
            base.loc[len(base)] = {
                "name": name, "init": init, "lower": lb, "upper": ub,
                "status": "active",
                "pargp": "SOIL_Phys" if field == "SBDM" else "SOIL_WatRet",
                "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008",
                "ecotype": "TM0001", "mode": "both",
                "review_note": "IBTM910017 layer-specific uncertainty group; relation SLLL<SDUL<SSAT retained.",
            }
        # The validator requires independent ranges to guarantee the water
        # retention ordering for every candidate, not just at the initial value.
        slll = float(layer["SLLL"])
        sdul = float(layer["SDUL"])
        ssat = float(layer["SSAT"])
        sdul_lb = max(0.01, 0.95 * sdul)
        sdul_ub = min(0.80, 1.05 * sdul, 0.92 * ssat)
        ssat_lb = max(0.01, 0.95 * ssat, sdul_ub + 0.005)
        ssat_ub = min(0.80, 1.05 * ssat)
        if not (sdul_lb < sdul_ub < ssat_lb < ssat_ub):
            raise RuntimeError(f"Cannot construct ordered water ranges for layer {i}")
        for field, init, lb, ub in [
            ("SDUL", sdul, sdul_lb, sdul_ub),
            ("SSAT", ssat, ssat_lb, ssat_ub),
        ]:
            name = f"SOIL_{field}_{i:02d}"
            base.loc[len(base)] = {
                "name": name, "init": init, "lower": lb, "upper": ub,
                "status": "active", "pargp": "SOIL_WatRet",
                "location": "SOIL", "file": "SOIL.SOL", "cultivar": "TM0008",
                "ecotype": "TM0001", "mode": "both",
                "review_note": "IBTM910017 layer-specific uncertainty group; relation SLLL<SDUL<SSAT retained.",
            }
    out.parent.mkdir(parents=True, exist_ok=True)
    base.to_csv(out, index=False, encoding="utf-8-sig")
    return base


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    df = make(args.out)
    print(f"wrote {args.out} rows={len(df)} active={(df.status == 'active').sum()}")
    print("added:", ", ".join(df.loc[df.name.str.startswith("SOIL_") | df.name.isin(["LNREF", "CMOBMX", "RWUMX", "DSWBAR", "XFRMAX"]), "name"].tolist()))
