"""Compare posterior-edge-adjusted rerun against the previous all-genetic run."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "workspace/runs/eggplant_26sp_w1w2_n012_postprecal_allgenetic_20260804"
NEW = ROOT / "workspace/runs/eggplant_26sp_w1w2_n012_postprecal_allgenetic_postadj_nrexp065_20260804"


def main() -> int:
    b = pd.read_csv(BASE / "best_member_fit_metrics.csv").set_index("scope")
    n = pd.read_csv(NEW / "best_member_fit_metrics.csv").set_index("scope")
    rows = []
    for scope in sorted(set(b.index) | set(n.index)):
        row = {"scope": scope}
        for col in ("n", "phi", "rmse", "mae", "bias", "nrmse_mean_abs_observed", "nse", "d_index", "r2"):
            row[f"baseline_{col}"] = b.loc[scope, col] if scope in b.index else float("nan")
            row[f"postadj_{col}"] = n.loc[scope, col] if scope in n.index else float("nan")
            row[f"delta_{col}"] = row[f"postadj_{col}"] - row[f"baseline_{col}"]
        rows.append(row)
    pd.DataFrame(rows).to_csv(NEW / "postadj_vs_allgenetic_best_metrics.csv", index=False)
    bp = pd.read_csv(BASE / f"{BASE.name}.phi.actual.csv")
    np_ = pd.read_csv(NEW / f"{NEW.name}.phi.actual.csv")
    phi = pd.concat([
        bp[["iteration", "total_runs", "mean", "min", "max"]].assign(run="allgenetic_80param"),
        np_[["iteration", "total_runs", "mean", "min", "max"]].assign(run="postadj_nrexp065_80param"),
    ], ignore_index=True).rename(columns={"mean": "mean_phi", "min": "best_phi", "max": "max_phi"})
    phi.to_csv(NEW / "postadj_vs_allgenetic_phi_progression.csv", index=False)
    summary = {
        "baseline_case": BASE.name,
        "postadj_case": NEW.name,
        "baseline_best_phi": float(b.loc["overall", "phi"]),
        "postadj_best_phi": float(n.loc["overall", "phi"]),
        "baseline_overall_rmse": float(b.loc["overall", "rmse"]),
        "postadj_overall_rmse": float(n.loc["overall", "rmse"]),
        "baseline_overall_mae": float(b.loc["overall", "mae"]),
        "postadj_overall_mae": float(n.loc["overall", "mae"]),
        "baseline_overall_nse": float(b.loc["overall", "nse"]),
        "postadj_overall_nse": float(n.loc["overall", "nse"]),
        "postadj_bounds_id": "eggplant_26sp_w1w2_n012_postprecal_allgenetic_postadj_nrexp065_20260804",
        "nrexp_range": [0.65, 10.0],
        "engineering_status": "engineering_validated",
    }
    (NEW / "postadj_vs_allgenetic_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
