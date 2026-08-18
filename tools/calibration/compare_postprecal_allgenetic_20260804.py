"""Create an auditable metric comparison for the 31- vs 80-parameter runs."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "workspace/runs/eggplant_26sp_w1w2_n012_postprecal_20260804"
EXT = ROOT / "workspace/runs/eggplant_26sp_w1w2_n012_postprecal_allgenetic_20260804"
BASE_CASE = BASE.name
EXT_CASE = EXT.name


def phi_summary(run: Path, case: str) -> pd.DataFrame:
    p = run / f"{case}.phi.actual.csv"
    d = pd.read_csv(p)
    return d[["iteration", "total_runs", "mean", "min", "max"]].rename(
        columns={"mean": "mean_phi", "min": "best_phi", "max": "max_phi"}
    )


def main() -> None:
    b = pd.read_csv(BASE / "best_member_fit_metrics.csv").set_index("scope")
    e = pd.read_csv(EXT / "best_member_fit_metrics.csv").set_index("scope")
    rows = []
    for scope in sorted(set(b.index) | set(e.index)):
        row = {"scope": scope}
        for col in ("n", "phi", "rmse", "mae", "bias", "nrmse_mean_abs_observed", "nse", "d_index", "r2"):
            row[f"baseline_{col}"] = b.loc[scope, col] if scope in b.index else float("nan")
            row[f"allgenetic_{col}"] = e.loc[scope, col] if scope in e.index else float("nan")
            if col == "bias":
                row["delta_abs_bias"] = abs(row[f"allgenetic_{col}"]) - abs(row[f"baseline_{col}"])
            else:
                row[f"delta_{col}"] = row[f"allgenetic_{col}"] - row[f"baseline_{col}"]
        rows.append(row)
    pd.DataFrame(rows).to_csv(EXT / "allgenetic_vs_31param_best_metrics.csv", index=False)
    phi = pd.concat(
        [phi_summary(BASE, BASE_CASE).assign(run="baseline_31param"),
         phi_summary(EXT, EXT_CASE).assign(run="allgenetic_80param")],
        ignore_index=True,
    )
    phi.to_csv(EXT / "allgenetic_vs_31param_phi_progression.csv", index=False)
    summary = {
        "baseline_case": BASE_CASE,
        "allgenetic_case": EXT_CASE,
        "baseline_active_parameters": 31,
        "allgenetic_active_parameters": 80,
        "baseline_best_phi": float(b.loc["overall", "phi"]),
        "allgenetic_best_phi": float(e.loc["overall", "phi"]),
        "best_phi_relative_reduction": float(1 - e.loc["overall", "phi"] / b.loc["overall", "phi"]),
        "baseline_overall_rmse": float(b.loc["overall", "rmse"]),
        "allgenetic_overall_rmse": float(e.loc["overall", "rmse"]),
        "overall_rmse_relative_reduction": float(1 - e.loc["overall", "rmse"] / b.loc["overall", "rmse"]),
        "baseline_overall_nse": float(b.loc["overall", "nse"]),
        "allgenetic_overall_nse": float(e.loc["overall", "nse"]),
        "allgenetic_engineering_status": "engineering_validated",
        "allgenetic_scope": "80 nonsoil genetic/structure parameters; soil and IC disabled",
    }
    (EXT / "allgenetic_vs_31param_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
