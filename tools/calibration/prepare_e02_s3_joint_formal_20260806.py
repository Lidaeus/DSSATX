"""Prepare the E02-S3 joint formal-calibration contract.

The S1 and S2 final IES ensembles are treated as stage-specific posterior
evidence.  This script writes an auditable posterior/edge report, proposes
new bounds with one deterministic rule, and emits the S3 staged design.  It
does not freeze the proposal; promotion remains an explicit command through
``tools/freeze_bounds.py``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.common.param_registry import PHYSICAL_BOUNDS


OLD_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_s1s2_morris_top95_plus_a3_0805_v3_20260806.csv"
S1_PAR = ROOT / "workspace/runs/e02_s1_canopy_morris_top95_a3_0805_100x3_20260806/e02_s1_canopy_morris_top95_a3_0805_100x3_20260806.3.par.csv"
S2_PAR = ROOT / "workspace/runs/e02_s2_harvest_terminal_morris_top95_a3_0805_100x3_20260806_retry2/e02_s2_harvest_terminal_morris_top95_a3_0805_100x3_20260806_retry2.3.par.csv"
S2_REP = ROOT / "workspace/runs/e02_s2_harvest_terminal_morris_top95_a3_0805_100x3_20260806_retry2/calibration_finalize/stage_representative_params.csv"
STAGED_DESIGN = ROOT / "configs/runs/eggplant_e02_s1s2_morris_top95_plus_a3_0805_20260806.json"
MULTI_DESIGN = ROOT / "configs/runs/eggplant_e02_s1s2_a3_0805_multiseason_20260806.json"
OUT_DIR = ROOT / "workspace/runs/e02_s3_joint_formal_preparation_20260806"
PROPOSAL_ID = "eggplant_e02_s3_joint_posterior_adjusted_a3_0805_v2_20260806"
DESIGN_ID = "eggplant_e02_s3_joint_formal_a3_0805_v2_20260806"
MULTI_S3_ID = "eggplant_e02_s3_joint_formal_multiseason_a3_0805_v2_20260806"
SAFE_LOWER = {"NUPK50": 1.0, "NUPCMN": 0.01, "RTNH4": 0.01}

S1_ACTIVE = [
    "CMOBMX", "EM-FL", "EM-V1", "FL-SD", "FRLFF", "LFMAX", "NMOBMX",
    "NVSMOB", "PM06", "RWUMX", "SENDAY", "TB1", "TB2", "TO11", "TO12",
    "TRIFL", "XFINT",
]
S2_ACTIVE = [
    "PROLFF", "PROLFG", "PROLFI", "PRORTF", "PRORTG", "PRORTI", "PROSHF",
    "PROSHI", "PROSTF", "PROSTG", "PROSTI", "RTNH4", "RTNO3", "XFRT",
    "NREXP", "NRMIN", "NUPK50", "NUPCMN",
]
ACTIVE = S1_ACTIVE + S2_ACTIVE


def _physical(name: str, lower: float, upper: float) -> tuple[float, float, bool, bool]:
    bounds = PHYSICAL_BOUNDS.get(name.upper())
    if not bounds:
        return lower, upper, False, False
    pl, pu = map(float, bounds)
    return max(lower, pl), min(upper, pu), lower < pl, upper > pu


def _adjust(row: pd.Series, x: pd.Series, representative: float) -> dict[str, Any]:
    name = str(row["name"]).strip().upper()
    lo, hi = float(row.lower), float(row.upper)
    width = max(hi - lo, 1.0e-12)
    x = pd.to_numeric(x, errors="coerce").dropna()
    q025, q05, q50, q95, q975 = [float(x.quantile(q)) for q in (0.025, 0.05, 0.50, 0.95, 0.975)]
    edge_tol = 0.02 * width
    edge_low = float((x <= lo + edge_tol + 1.0e-12).mean())
    edge_high = float((x >= hi - edge_tol - 1.0e-12).mean())

    # Posterior-centered contraction with a minimum 10% prior-width guard.
    # A material edge hit (>=10% of realizations) expands the corresponding
    # side by 25% of the old width before physical bounds are applied.
    pad = max(0.10 * width, 0.25 * max(q95 - q05, 0.0))
    new_lo = q05 - pad
    new_hi = q95 + pad
    expansion = []
    if edge_low >= 0.10:
        new_lo = lo - 0.25 * width
        expansion.append("lower")
    if edge_high >= 0.10:
        new_hi = hi + 0.25 * width
        expansion.append("upper")

    # Never exclude the inherited representative; this is a hard build gate.
    new_lo = min(new_lo, float(representative))
    new_hi = max(new_hi, float(representative))
    new_lo, new_hi, _, _ = _physical(name, new_lo, new_hi)
    if name in SAFE_LOWER:
        new_lo = max(new_lo, float(SAFE_LOWER[name]))
    # A physical clip can still leave an invalid interval when the proposal
    # was entirely outside the executable domain; fail loudly instead.
    if not (math.isfinite(new_lo) and math.isfinite(new_hi) and new_lo < new_hi):
        raise ValueError(f"invalid adjusted bounds for {name}: {new_lo}, {new_hi}")

    return {
        "name": name,
        "source_stage": "S1" if name in S1_ACTIVE else "S2",
        "prior_lower": lo,
        "prior_upper": hi,
        "posterior_min": float(x.min()),
        "posterior_q025": q025,
        "posterior_q05": q05,
        "posterior_median": q50,
        "posterior_q95": q95,
        "posterior_q975": q975,
        "posterior_max": float(x.max()),
        "edge_lower_frac": edge_low,
        "edge_upper_frac": edge_high,
        "edge_lower_hit": edge_low >= 0.10,
        "edge_upper_hit": edge_high >= 0.10,
        "expansion_sides": ",".join(expansion),
        "representative": float(representative),
        "new_lower": float(new_lo),
        "new_upper": float(new_hi),
        "physical_clipped": bool(new_lo != (lo - 0.25 * width if edge_low >= 0.10 else q05 - pad)
                              or new_hi != (hi + 0.25 * width if edge_high >= 0.10 else q95 + pad)),
        "posterior_width_fraction": float((q95 - q05) / width),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bounds = pd.read_csv(OLD_BOUNDS)
    s1 = pd.read_csv(S1_PAR)
    s2 = pd.read_csv(S2_PAR)
    rep = pd.read_csv(S2_REP)
    rep_map = {str(r.name).strip().upper(): float(r.value) for r in rep.itertuples(index=False)}

    audit_rows = []
    for name in ACTIVE:
        row = bounds.loc[bounds.name.str.upper() == name].iloc[0]
        source = s1 if name in S1_ACTIVE else s2
        col = name.lower()
        if col not in source.columns:
            raise KeyError(f"posterior column missing for {name}: {col}")
        representative = rep_map.get(name, float(row.init))
        audit_rows.append(_adjust(row, source[col], representative))

    audit = pd.DataFrame(audit_rows)
    audit.to_csv(OUT_DIR / "posterior_bound_audit.csv", index=False, encoding="utf-8-sig")

    proposal = bounds.copy()
    for item in audit_rows:
        mask = proposal.name.str.upper() == item["name"]
        proposal.loc[mask, "init"] = item["representative"]
        proposal.loc[mask, "lower"] = item["new_lower"]
        proposal.loc[mask, "upper"] = item["new_upper"]
        proposal.loc[mask, "status"] = "active"
    proposal_path = ROOT / f"data/parameter_registry/bounds_proposals/eggplant/{PROPOSAL_ID}.csv"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal.to_csv(proposal_path, index=False, encoding="utf-8-sig")

    staged = json.loads(STAGED_DESIGN.read_text(encoding="utf-8"))
    all_base = sorted({p for stage in staged["stages"].values() for key in ("active_params", "fixed_params") for p in stage[key]})
    fixed = [p for p in all_base if p not in ACTIVE]
    soil = [f"SW{i:04d}" for i in range(1, 61)]
    s3 = {
        "schema_version": 1,
        "design_table_id": staged["design_table_id"],
        "bounds_id": PROPOSAL_ID,
        "input_bundle": staged["input_bundle"],
        "observation_policy_id": staged["observation_policy_id"],
        "approval_scope": staged["approval_scope"],
        "validation_split_id": staged["validation_split_id"],
        "stages": {
            "S3": {
                "active_params": ACTIVE,
                "fixed_params": fixed,
                "observation_outputs": {
                    "PestEval.OUT": ["ADAP"],
                    "PestJoint.OUT": ["LAIX", "CNAM"],
                    "PestHarvest.OUT": ["CHFPW", "CHPDT", "HPODW"],
                    "PestTmtGrow.OUT": ["LAID", "LWAD", "SWAD", "CHTD", "SNAM", "LNAM", "LAIDD", "LAIET", "LWADD", "LWET", "SWADD", "SWET"],
                    "PestSoilWat.OUT": soil,
                    "PestNResponse.OUT": ["NRESP"],
                },
                "representative_outputs": {
                    "PestEval.OUT": ["ADAP"],
                    "PestJoint.OUT": ["LAIX", "CNAM"],
                    "PestHarvest.OUT": ["CHPDT", "HPODW"],
                    "PestTmtGrow.OUT": ["LAID", "LWAD", "SWAD", "SNAM", "LNAM"],
                    "PestSoilWat.OUT": soil[:10],
                    "PestNResponse.OUT": ["NRESP"],
                },
                "purpose": "S3 根据 S1/S2 后验分布和触边情况调整边界后的联合正式率定（25SP 六处理；无秋季）",
            }
        },
    }
    design_path = ROOT / f"configs/runs/{DESIGN_ID}.json"
    design_path.write_text(json.dumps(s3, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    multi = json.loads(MULTI_DESIGN.read_text(encoding="utf-8"))
    multi["design_id"] = MULTI_S3_ID
    multi["shared_parameter_scope"] = "S3 joint release of all 35 Morris-top95 plus A3 0805 custom parameters"
    multi["formal"] = {"n_reals": 200, "noptmax": 4, "initial_ensemble_method": "sobol"}
    multi_path = ROOT / f"configs/runs/{MULTI_S3_ID}.json"
    multi_path.write_text(json.dumps(multi, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    meta = {
        "proposal_id": PROPOSAL_ID,
        "proposal_path": str(proposal_path),
        "design_path": str(design_path),
        "multiseason_design_path": str(multi_path),
        "source_bounds": str(OLD_BOUNDS),
        "s1_posterior": str(S1_PAR),
        "s2_posterior": str(S2_PAR),
        "s2_representative": str(S2_REP),
        "edge_threshold": 0.10,
        "edge_tolerance_fraction": 0.02,
        "edge_expansion_fraction": 0.25,
        "posterior_padding_rule": "max(0.10*prior_width, 0.25*(q95-q05)); representative always included; physical bounds clipped",
        "engineering_safe_floors": SAFE_LOWER,
        "active_parameter_count": len(ACTIVE),
        "fixed_parameter_count": len(fixed),
    }
    (OUT_DIR / "preparation_manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"S3 audit: {OUT_DIR / 'posterior_bound_audit.csv'}")
    print(f"S3 proposal: {proposal_path}")
    print(f"S3 design: {design_path}")
    print(f"active={len(ACTIVE)} fixed={len(fixed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
