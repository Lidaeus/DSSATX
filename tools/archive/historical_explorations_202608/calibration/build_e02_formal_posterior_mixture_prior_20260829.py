"""Build the 200-member posterior/exploration mixture prior for formal IES."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.initial_ensemble import generate_lhs_ensemble


RUN_DIR = ROOT / "workspace/runs/e02_formal_yield_rebalanced_post_official_200x6_20260829"
CASE = "e02_formal_yield_rebalanced_post_200x6_20260829"
TARGET = RUN_DIR / f"{CASE}.0.par.csv"
BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_formal_yield_rebalanced_posterior_v1_20260829.csv"
PREVIOUS_RUN = ROOT / "workspace/runs/e02_formal_armab_rrmse_26spncal_official_200x6_20260828"
PREVIOUS_CASE = "e02_formal_armab_rrmse_26spncal_200x6_20260828"
RECEIPT = RUN_DIR / "posterior_mixture_prior_receipt.json"
PROVENANCE = RUN_DIR / "posterior_mixture_prior_members.csv"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clip(frame: pd.DataFrame, active: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    lookup = active.set_index("name")
    for name in active["name"]:
        result[name] = pd.to_numeric(result[name], errors="raise").clip(
            lower=float(lookup.loc[name, "lower"]),
            upper=float(lookup.loc[name, "upper"]),
        )
    return result


def main() -> int:
    if RECEIPT.exists() or PROVENANCE.exists():
        raise FileExistsError("refusing to overwrite posterior-mixture prior artifacts")
    if not TARGET.is_file():
        raise FileNotFoundError("build the formal PST and LHS ensemble first")

    bounds = pd.read_csv(BOUNDS)
    bounds["name"] = bounds["name"].astype(str).str.lower()
    active = bounds.loc[bounds["status"].astype(str).str.lower().eq("active")].copy()
    names = active["name"].tolist()
    if len(names) != 95:
        raise ValueError(f"expected 95 active parameters, found {len(names)}")

    posterior = pd.read_csv(PREVIOUS_RUN / f"{PREVIOUS_CASE}.6.par.csv")
    posterior.columns = [str(column).lower() for column in posterior.columns]
    best = pd.read_csv(PREVIOUS_RUN / f"{PREVIOUS_CASE}.5.par.csv").set_index("real_name")
    best.index = best.index.astype(str)
    best.columns = [str(column).lower() for column in best.columns]
    early = pd.read_csv(PREVIOUS_RUN / f"{PREVIOUS_CASE}.1.par.csv").set_index("real_name")
    early.index = early.index.astype(str)
    early.columns = [str(column).lower() for column in early.columns]
    missing = sorted(set(names) - set(posterior.columns))
    if missing:
        raise ValueError(f"posterior missing active parameters: {missing}")

    anchors = pd.DataFrame([
        posterior[names].median().to_dict(),
        pd.to_numeric(best.loc["103", names], errors="raise").to_dict(),
        pd.to_numeric(early.loc["39", names], errors="raise").to_dict(),
    ])
    anchors = _clip(anchors, active)

    rng = np.random.default_rng(43)
    selected = rng.choice(len(posterior), size=57, replace=False)
    posterior_members = _clip(posterior.iloc[selected][names].reset_index(drop=True), active)
    lhs = generate_lhs_ensemble(
        n_reals=140,
        bounds_df=active,
        seed=44,
        method="lhs",
        include_base=False,
    ).drop(columns=["real_name"])

    ensemble = pd.concat([anchors, posterior_members, lhs], ignore_index=True)
    if len(ensemble) != 200 or ensemble.isna().any().any():
        raise AssertionError(f"invalid mixture ensemble shape/content: {ensemble.shape}")
    ensemble.insert(0, "real_name", [str(index) for index in range(len(ensemble))])
    ensemble.to_csv(TARGET, index=False, encoding="utf-8")

    sources = ["posterior_median", "global_best_iter5_member103", "yield_rescue_iter1_member39"]
    sources += [f"posterior_iter6_member_{posterior.iloc[index]['real_name']}" for index in selected]
    sources += [f"lhs_seed44_member_{index}" for index in range(140)]
    pd.DataFrame({"real_name": ensemble["real_name"], "source": sources}).to_csv(
        PROVENANCE, index=False, encoding="utf-8-sig"
    )

    receipt = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "case": CASE,
        "ensemble": TARGET.name,
        "ensemble_sha256": sha256(TARGET),
        "members": 200,
        "active_parameters": 95,
        "composition": {
            "posterior_median_anchor": 1,
            "global_best_iter5_member103": 1,
            "yield_rescue_iter1_member39": 1,
            "sampled_final_posterior": 57,
            "full_bounds_lhs_exploration": 140,
        },
        "purpose": "preserve posterior correlations while retaining enough full-envelope exploration to escape the low-yield objective optimum",
        "provenance_csv": PROVENANCE.name,
        "provenance_sha256": sha256(PROVENANCE),
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
