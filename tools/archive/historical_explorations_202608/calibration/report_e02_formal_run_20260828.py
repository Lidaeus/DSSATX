"""Audit the completed E02 formal IES run and export its best final member."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "workspace/runs/e02_formal_s1s2_springvalidated_official_200x6_20260828"
CASE = "e02_formal_s1s2_sv_200x6_20260828"
BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_formal_s1s2_springvalidated_bounds_20260828.csv"
OUT = RUN / "best_member_diagnostics"


def objective_family(token: object) -> str:
    value = str(token).upper()
    if value.startswith("SW") and value.endswith("S") and value[2:-1].isdigit():
        return "SOIL_WATER"
    return {
        "PDAPS": "PHENOLOGY",
        "ADAPS": "PHENOLOGY",
        "MDAPS": "PHENOLOGY",
        "HPODWS": "DRY_INCREMENT",
        "CHPDTS": "DRY_TERMINAL",
        "LAIDDS": "LAI_CHANGE",
        "LAIETS": "CANOPY_TERMINAL",
        "LWADDS": "LEAF_MASS_CHANGE",
        "LWETS": "LEAF_TERMINAL",
        "SWADDS": "STEM_MASS_CHANGE",
        "SWETS": "STEM_TERMINAL",
        "NRESPS": "N_RESPONSE",
        "WRESPS": "W_RESPONSE",
    }.get(value, value)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    phi = pd.read_csv(RUN / f"{CASE}.phi.actual.csv")
    meta = {"iteration", "total_runs", "mean", "standard_deviation", "min", "max"}
    realization_columns = [column for column in phi.columns if column not in meta]

    convergence = []
    for _, row in phi.iterrows():
        values = pd.to_numeric(row[realization_columns], errors="coerce")
        convergence.append(
            {
                "iteration": int(row["iteration"]),
                "total_runs": int(row["total_runs"]),
                "mean_phi": float(row["mean"]),
                "sd_phi": float(row["standard_deviation"]),
                "min_phi": float(values.min()),
                "min_phi_member": str(values.idxmin()),
                "base_phi": float(values["base"]),
                "finite_members": int(values.notna().sum()),
            }
        )
    convergence_frame = pd.DataFrame(convergence)
    convergence_frame.to_csv(OUT / "phi_convergence.csv", index=False, encoding="utf-8-sig")

    final_iteration = int(convergence_frame.iloc[-1]["iteration"])
    best_member = str(convergence_frame.iloc[-1]["min_phi_member"])
    best_phi = float(convergence_frame.iloc[-1]["min_phi"])
    parameters = pd.read_csv(RUN / f"{CASE}.{final_iteration}.par.csv").set_index("real_name")
    parameters.index = parameters.index.astype(str)
    best_parameters = parameters.loc[best_member].astype(float)
    pd.DataFrame({"name": best_parameters.index, "value": best_parameters.values}).to_csv(
        OUT / f"best_member_{best_member}_params.csv", index=False, encoding="utf-8"
    )

    registry = pd.read_csv(RUN / f"{CASE}_observation_registry.csv")
    active = registry.loc[
        registry["phi_role"].astype(str).str.lower().eq("calibration")
        & pd.to_numeric(registry["weight"], errors="coerce").gt(0)
    ].copy()
    observations = pd.read_csv(RUN / f"{CASE}.{final_iteration}.obs.csv").set_index("real_name")
    observations.index = observations.index.astype(str)
    prediction = observations.loc[best_member]
    active["pred_transformed"] = [float(prediction[str(name).lower()]) for name in active["obsnme"]]
    active["phi_contribution"] = (
        (active["pred_transformed"] - active["obsval"]) * active["weight"]
    ) ** 2
    active["objective_family"] = active["sim_token"].map(objective_family)
    family = (
        active.groupby(["season_id", "objective_family"], as_index=False)
        .agg(n=("obsnme", "size"), phi=("phi_contribution", "sum"))
    )
    family["phi_fraction"] = family["phi"] / family["phi"].sum()
    family.to_csv(OUT / "best_member_phi_by_family.csv", index=False, encoding="utf-8-sig")
    active.to_csv(OUT / "best_member_active_observations.csv", index=False, encoding="utf-8-sig")

    bounds = pd.read_csv(BOUNDS)
    bounds["name"] = bounds["name"].astype(str).str.lower()
    active_bounds = bounds.loc[bounds["status"].astype(str).str.lower().eq("active")].copy()
    final_ensemble = parameters.drop(index="base", errors="ignore")
    pressure_rows = []
    for _, row in active_bounds.iterrows():
        name = row["name"]
        lower, upper = float(row["lower"]), float(row["upper"])
        width = upper - lower
        selected = float(best_parameters[name])
        ensemble_values = pd.to_numeric(final_ensemble[name], errors="coerce")
        pressure_rows.append(
            {
                "name": name,
                "lower": lower,
                "upper": upper,
                "best_value": selected,
                "best_relative_distance_to_nearest_bound": min(selected - lower, upper - selected) / width,
                "ensemble_fraction_within_1pct_lower": float((ensemble_values <= lower + 0.01 * width).mean()),
                "ensemble_fraction_within_1pct_upper": float((ensemble_values >= upper - 0.01 * width).mean()),
                "ensemble_median": float(ensemble_values.median()),
            }
        )
    pressure = pd.DataFrame(pressure_rows).sort_values(
        "best_relative_distance_to_nearest_bound", ascending=True
    )
    pressure.to_csv(OUT / "parameter_boundary_pressure.csv", index=False, encoding="utf-8-sig")

    payload = {
        "case": CASE,
        "run_status": json.loads((RUN / "run_status.json").read_text(encoding="utf-8")),
        "final_iteration": final_iteration,
        "best_member": best_member,
        "best_phi": best_phi,
        "initial_mean_phi": float(convergence_frame.iloc[0]["mean_phi"]),
        "final_mean_phi": float(convergence_frame.iloc[-1]["mean_phi"]),
        "mean_phi_reduction_fraction": float(
            1.0 - convergence_frame.iloc[-1]["mean_phi"] / convergence_frame.iloc[0]["mean_phi"]
        ),
        "active_observations": int(len(active)),
        "active_parameters": int(len(active_bounds)),
        "family_phi_sum": float(family["phi"].sum()),
        "best_member_phi_difference": float(family["phi"].sum() - best_phi),
        "best_member_parameters": str(OUT / f"best_member_{best_member}_params.csv"),
    }
    (OUT / "run_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("\nPhi by family:\n", family.sort_values("phi", ascending=False).to_string(index=False))
    print("\nClosest selected-member boundaries:\n", pressure.head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
