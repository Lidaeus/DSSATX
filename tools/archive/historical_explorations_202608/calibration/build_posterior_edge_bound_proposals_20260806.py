"""Create auditable bound proposals from the final 33/83-member ensembles.

Only parameters with a final-ensemble boundary fraction above 5% are widened.
The affected side is expanded by 15% of the previous range and clipped to the
physical registry bounds.  Fixed parameters and custom A3 rows are untouched.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyemu

from src.common.param_registry import PHYSICAL_BOUNDS


ROOT = Path(__file__).resolve().parents[2]
SPECS = [
    {
        "label": "33",
        "run": ROOT / "workspace/runs/e02_v2_rawdiff_terminal_nresp01_soil02_saactive_a3_nr_zp_200x4_20260806",
        "bounds_id": "eggplant_two_spring_morris_top95_genetic_precal_20260804",
        "proposal_id": "eggplant_two_spring_morris_top95_genetic_postedge_20260806",
    },
    {
        "label": "83",
        "run": ROOT / "workspace/runs/e02_v2_rawdiff_terminal_nresp01_soil02_saall_a3_nr_zp_200x4_20260806",
        "bounds_id": "eggplant_two_spring_organ_n_v1_20260803",
        "proposal_id": "eggplant_two_spring_organ_n_postedge_20260806",
    },
]


def _physical(name: str, lower: float, upper: float) -> tuple[float, float]:
    bound = PHYSICAL_BOUNDS.get(name.upper()) or PHYSICAL_BOUNDS.get(name)
    if not bound:
        return lower, upper
    return max(lower, float(bound[0])), min(upper, float(bound[1]))


def main() -> None:
    out_dir = ROOT / "data/parameter_registry/bounds_proposals/eggplant"
    for spec in SPECS:
        run = spec["run"]
        case = run.name
        pst = pyemu.Pst(str(run / f"{case}.pst"))
        pdata = pst.parameter_data.copy()
        pdata.index = pdata.index.astype(str).str.lower()
        adjustable = pdata.loc[pdata.partrans.astype(str).str.lower().ne("fixed")]
        final_iter = max(
            int(p.name.split(".")[-3])
            for p in run.glob(f"{case}.*.par.csv")
            if p.name.split(".")[-3].isdigit()
        )
        ensemble = pd.read_csv(run / f"{case}.{final_iter}.par.csv").set_index("real_name")
        rows = pd.read_csv(
            ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{spec['bounds_id']}.csv",
            encoding="utf-8-sig",
        )
        for text_col in ("review_note", "notes"):
            if text_col in rows.columns:
                rows[text_col] = rows[text_col].fillna("").astype(str)
        changes = []
        for idx, row in rows.iterrows():
            name = str(row["name"]).strip()
            key = name.lower()
            if key not in adjustable.index or key not in ensemble.columns:
                continue
            old_lower = float(row["lower"])
            old_upper = float(row["upper"])
            span = old_upper - old_lower
            if span <= 0:
                continue
            tol = max(1e-10, 1e-6 * abs(span))
            values = pd.to_numeric(ensemble[key], errors="coerce")
            frac_lower = float((abs(values - old_lower) <= tol).mean())
            frac_upper = float((abs(values - old_upper) <= tol).mean())
            q05 = float(values.quantile(0.05))
            q95 = float(values.quantile(0.95))
            new_lower, new_upper = old_lower, old_upper
            reasons = []
            if frac_lower > 0.05:
                new_lower = old_lower - 0.15 * span
                reasons.append(f"lower_edge_frac={frac_lower:.3f};q05={q05:.8g}")
            if frac_upper > 0.05:
                new_upper = old_upper + 0.15 * span
                reasons.append(f"upper_edge_frac={frac_upper:.3f};q95={q95:.8g}")
            new_lower, new_upper = _physical(name, new_lower, new_upper)
            # Preserve DSSAT's coupled temperature-stage ordering constraints.
            # The registry validator requires these independent ranges to be
            # safe for every draw, not just for the posterior median.
            if spec["label"] == "83" and name.upper() == "TM2":
                new_lower = max(new_lower, 33.5)
            if spec["label"] == "83" and name.upper() == "TO21":
                new_lower = max(new_lower, 27.6)  # TO11 upper is 27.5
            if spec["label"] == "83" and name.upper() == "TO13":
                new_upper = min(new_upper, 27.9)  # TO23 lower is 28.0
            if new_lower >= new_upper:
                new_lower, new_upper = old_lower, old_upper
            if (new_lower, new_upper) != (old_lower, old_upper):
                rows.at[idx, "lower"] = new_lower
                rows.at[idx, "upper"] = new_upper
                rows.at[idx, "review_note"] = (
                    f"posterior-edge proposal from {case}; " + "; ".join(reasons) +
                    "; 15% range-side expansion clipped to physical bounds"
                )
                rows.at[idx, "notes"] = "Retain active status; review after rerun"
                changes.append((name, old_lower, old_upper, new_lower, new_upper, frac_lower, frac_upper))
        out = out_dir / f"{spec['proposal_id']}.csv"
        rows.to_csv(out, index=False, encoding="utf-8-sig")
        print(f"{spec['label']} proposal: {out}")
        for c in changes:
            print("  ", c)


if __name__ == "__main__":
    main()
