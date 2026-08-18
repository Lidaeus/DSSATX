"""Prepare a posterior-edge-adjusted bounds proposal for the all-genetic run."""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.common.param_registry import PHYSICAL_BOUNDS
SOURCE = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_26sp_w1w2_n012_postprecal_allgenetic_20260804.csv"
POSTERIOR = ROOT / "workspace/runs/eggplant_26sp_w1w2_n012_postprecal_allgenetic_20260804/eggplant_26sp_w1w2_n012_postprecal_allgenetic_20260804.4.par.csv"
NEW_ID = "eggplant_26sp_w1w2_n012_postprecal_allgenetic_postadj_nrexp065_20260804"
PROPOSAL = ROOT / f"data/parameter_registry/bounds_proposals/eggplant/{NEW_ID}.csv"
AUDIT = ROOT / f"data/parameter_registry/bounds_proposals/eggplant/{NEW_ID}_posterior_edge_audit.csv"

# Only parameters with posterior edge pressure and no hard/structural reason
# to retain the old boundary are released. Values are deliberately modest.
UPDATES: dict[str, tuple[float, float, str]] = {
    "NREXP": (0.65, 10.0, "user-requested release: NREXP 0.65-10"),
    "DSWBAR": (12.0, 25.39433325, "lower-edge pressure; lower released modestly to 12.0"),
    "LNGSH": (26.0, 48.8, "lower-edge pressure; lower released modestly to 26.0"),
    "PODUR": (26.0, 58.0, "lower-edge pressure; lower released modestly to 26.0"),
    "PROLFG": (0.125, 0.30, "lower-edge pressure; lower released modestly to 0.125"),
    "PRORTG": (0.110, 0.14, "lower-edge pressure; lower released modestly to 0.110"),
    "PRORTI": (0.134, 0.18, "lower-edge pressure; lower released modestly to 0.134"),
    "RTEXF": (0.020, 0.25, "lower-edge pressure; lower released modestly to 0.020"),
    "RTNO3": (0.010, 0.025, "lower-edge pressure; lower released modestly to 0.010"),
    "SDPDV": (70.0, 300.0, "lower-edge pressure; lower released modestly to 70"),
    "RWDTH": (0.70, 1.70, "upper-edge pressure; upper released modestly to 1.70"),
    "TB1": (7.50, 10.25, "upper-edge pressure; upper released while preserving TB1 < TO11"),
    "TB3": (8.00, 12.40, "upper-edge pressure; upper released while preserving TB3 < TO13"),
    "TRIFL": (0.50, 0.70, "upper-edge pressure; upper released modestly to 0.70"),
}

RETAINED_EDGE_NOTES = {
    "EM-V1": "upper edge retained at physical hard limit 40",
    "PL-EM": "upper edge retained at physical hard limit 12",
    "PM06": "upper edge retained at physical hard limit 1",
    "PM09": "upper edge retained at physical hard limit 1",
    "XFRT": "upper edge retained at physical hard limit 1",
    "FL-SH": "lower edge retained at physical hard limit 1",
    "JU-R0": "lower edge retained at physical hard limit 2",
    "KCAN": "lower edge retained at known DSSAT numerical-stability floor 0.60",
    "SENDAY": "lower edge retained at physical hard limit 0",
    "TO12": "upper edge retained to preserve TO12 < TO22 independent-range order",
    "TO23": "lower edge retained to preserve TO13 < TO23 independent-range order",
}


def main() -> int:
    source = pd.read_csv(SOURCE, encoding="utf-8-sig")
    posterior = pd.read_csv(POSTERIOR)
    active = source[source["status"].eq("active")]
    if len(active) != 80 or set(active["name"].astype(str).str.upper()) != set(c.upper() for c in posterior.columns if c != "real_name") & set(active["name"].astype(str).str.upper()):
        raise RuntimeError("unexpected active/posterior parameter contract")
    col_map = {str(c).upper(): c for c in posterior.columns if c != "real_name"}
    proposal = source.copy()
    audit_rows = []
    for idx, row in source.iterrows():
        name = str(row["name"]).upper()
        if str(row["status"]).lower() != "active":
            continue
        values = pd.to_numeric(posterior[col_map[name]], errors="coerce").dropna().to_numpy(float)
        lo = float(row["lower"]); hi = float(row["upper"]); width = hi - lo
        tol = max(abs(width) * 0.01, 1e-12)
        q01, q05, q50, q95, q99 = (float(np.quantile(values, q)) for q in (0.01, 0.05, 0.50, 0.95, 0.99))
        frac_lo = float(np.mean(values <= lo + tol)); frac_hi = float(np.mean(values >= hi - tol))
        pressure = frac_lo >= 0.05 or frac_hi >= 0.05
        new_lo, new_hi = lo, hi
        decision = "unchanged_no_edge_pressure"
        note = str(row.get("review_note", ""))
        if name in UPDATES:
            new_lo, new_hi, note = UPDATES[name]
            decision = "released_by_posterior_edge" if name != "NREXP" else "user_requested_release"
        elif pressure and name in RETAINED_EDGE_NOTES:
            note = RETAINED_EDGE_NOTES[name]
            decision = "retained_hard_or_structural_limit"
        elif pressure:
            decision = "edge_pressure_reviewed_no_safe_release"
        if name != "NREXP" and name in PHYSICAL_BOUNDS:
            phys_lo, phys_hi = PHYSICAL_BOUNDS[name]
            new_lo, new_hi = max(new_lo, phys_lo), min(new_hi, phys_hi)
        if not new_lo < new_hi:
            raise RuntimeError(f"invalid proposed range for {name}: {new_lo}, {new_hi}")
        if not (new_lo <= float(row["init"]) <= new_hi):
            raise RuntimeError(f"init outside proposed range for {name}: init={row['init']}, range={new_lo}-{new_hi}")
        proposal.loc[idx, "lower"] = new_lo
        proposal.loc[idx, "upper"] = new_hi
        if name in UPDATES or pressure:
            proposal.loc[idx, "review_note"] = note
            proposal.loc[idx, "decision_role"] = "posterior_edge_boundary_review"
            proposal.loc[idx, "evidence_basis"] = "allgenetic_80param_IES_final_iteration_4_posterior"
        audit_rows.append({
            "name": name, "prior_lower": lo, "prior_upper": hi, "proposed_lower": new_lo, "proposed_upper": new_hi,
            "q01": q01, "q05": q05, "q50": q50, "q95": q95, "q99": q99, "posterior_min": float(values.min()), "posterior_max": float(values.max()),
            "frac_lower_1pct": frac_lo, "frac_upper_1pct": frac_hi, "edge_pressure": pressure, "decision": decision, "note": note,
        })
    # Explicit user constraint and project invariants.
    nidx = proposal[proposal["name"].astype(str).str.upper().eq("NREXP")].index
    if len(nidx) != 1:
        raise RuntimeError("NREXP row missing or duplicated")
    proposal.loc[nidx[0], ["lower", "upper"]] = [0.65, 10.0]
    fl = proposal[proposal["name"].astype(str).str.upper().eq("FL-VS")].iloc[0]
    if str(fl["status"]).lower() != "fixed" or float(fl["init"]) != 120.0:
        raise RuntimeError("FL-VS must remain fixed at 120")
    if proposal[(proposal["status"].eq("active")) & (proposal["location"].astype(str).str.upper().isin({"SOIL", "IC", "INIT"}))].shape[0]:
        raise RuntimeError("soil/IC/INIT parameters must remain inactive")
    PROPOSAL.parent.mkdir(parents=True, exist_ok=True)
    proposal.to_csv(PROPOSAL, index=False, encoding="utf-8-sig")
    pd.DataFrame(audit_rows).to_csv(AUDIT, index=False, encoding="utf-8-sig")
    print(f"proposal={PROPOSAL}")
    print(f"audit={AUDIT}")
    print(f"active={int(proposal.status.eq('active').sum())}; changed={sum(a['decision'] in {'released_by_posterior_edge','user_requested_release'} for a in audit_rows)}; edge_pressure={sum(a['edge_pressure'] for a in audit_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
