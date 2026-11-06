"""Compare the two E02 water x nitrogen response objective hypotheses."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.build_pest_multiseason import _family_for_group


CASES = {
    "observed_shape": {
        "run": ROOT / "workspace/runs/e02_joint62_nresponse_observedshape_100x4_20260730_v2",
        "diagnostic": ROOT / "workspace/diagnostics/e02_joint62_nresponse_observedshape_100x4_20260730_v2_best",
    },
    "monotone_plateau": {
        "run": ROOT / "workspace/runs/e02_joint62_nresponse_noexcessn_100x4_20260730_v2",
        "diagnostic": ROOT / "workspace/diagnostics/e02_joint62_nresponse_noexcessn_100x4_20260730_v2_best",
    },
}
MAPPING = ROOT / "configs/runs/e02_three_season_water_n_mapping_20260730.csv"
BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_joint62_v7_nstfac050_rhght035_20260730.csv"


def scores(obs: np.ndarray, sim: np.ndarray) -> dict[str, float]:
    obs = np.asarray(obs, float)
    sim = np.asarray(sim, float)
    residual = sim - obs
    denominator = float(np.sum((obs - obs.mean()) ** 2))
    return {
        "n": int(len(obs)),
        "rmse": float(np.sqrt(np.mean(residual**2))),
        "mae": float(np.mean(np.abs(residual))),
        "nse": float(1 - np.sum(residual**2) / denominator)
        if denominator > 0
        else np.nan,
        "r2": float(np.corrcoef(obs, sim)[0, 1] ** 2)
        if len(obs) > 1 and np.std(obs) > 0 and np.std(sim) > 0
        else np.nan,
        "bias": float(residual.mean()),
    }


def best_member(run: Path) -> tuple[str, float]:
    case = run.name
    phi = pd.read_csv(run / f"{case}.phi.actual.csv")
    final = phi.loc[phi["iteration"].eq(phi["iteration"].max())].iloc[0]
    members = [
        column for column in phi.columns
        if str(column).isdigit()
        and np.isfinite(pd.to_numeric(final[column], errors="coerce"))
    ]
    member = min(members, key=lambda name: float(final[name]))
    return member, float(final[member])


def phi_family(case_name: str, spec: dict[str, Path]) -> pd.DataFrame:
    run = spec["run"]
    case = run.name
    member, _ = best_member(run)
    pst = pyemu.Pst(str(run / f"{case}.pst"))
    obs_ensemble = pd.read_csv(run / f"{case}.4.obs.csv")
    real_col = next(
        column for column in obs_ensemble.columns
        if str(column).lower() in {"real_name", "realization"}
    )
    selected = obs_ensemble.loc[
        obs_ensemble[real_col].astype(str).str.replace(r"\.0$", "", regex=True)
        .eq(member)
    ]
    if len(selected) != 1:
        raise ValueError(f"{case_name}: best member {member} not unique")
    prediction = selected.iloc[0]
    rows = []
    for obsnme, record in pst.observation_data.iterrows():
        weight = float(record["weight"])
        if weight <= 0:
            continue
        key = str(obsnme).lower()
        sim = float(prediction[key])
        obs = float(record["obsval"])
        family = _family_for_group(str(record["obgnme"]))
        season_match = re.match(r"^([^_]+)_", str(obsnme))
        season = season_match.group(1).upper() if season_match else "UNKNOWN"
        rows.append(
            {
                "case": case_name,
                "season": season,
                "family": family,
                "obsnme": obsnme,
                "weighted_sq_residual": ((sim - obs) * weight) ** 2,
            }
        )
    detail = pd.DataFrame(rows)
    family = (
        detail.groupby(["case", "season", "family"], as_index=False)
        .agg(phi=("weighted_sq_residual", "sum"), n=("obsnme", "size"))
    )
    total = family.groupby("case")["phi"].transform("sum")
    family["phi_share_pct"] = 100 * family["phi"] / total
    return family


def fit_metrics() -> pd.DataFrame:
    frames = []
    for case_name, spec in CASES.items():
        frame = pd.read_csv(
            spec["diagnostic"] / "metrics_by_season_variable.csv"
        )
        frame.insert(0, "case", case_name)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def response_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    mapping = pd.read_csv(MAPPING)
    mapping = mapping.rename(columns={"season_id": "season"})
    response_frames = []
    cumulative_by_case = {}
    for case_name, spec in CASES.items():
        audit = spec["diagnostic"] / "n_response_audit"
        response = pd.read_csv(audit / "n_response_contrasts_by_harvest.csv")
        response["case"] = case_name
        response_frames.append(response)
        cumulative_by_case[case_name] = pd.read_csv(
            audit / "observed_simulated_cumulative_harvest.csv"
        )
    response = pd.concat(response_frames, ignore_index=True)

    # Build the no-excess-N monotone plateau target directly from observed
    # cumulative dry yield so the target remains independently auditable.
    source = cumulative_by_case["observed_shape"].copy()
    source["nitrogen_rank"] = (
        source["nitrogen_level"].str.extract(r"N(\d)").astype(int)
    )
    plateau_rows = []
    keys = ["season", "harvest_number", "water_level"]
    for key, group in source.groupby(keys):
        group = group.sort_values("nitrogen_rank")
        observed = group["observed"].to_numpy(float)
        plateau = np.maximum.accumulate(observed)
        n0 = plateau[0]
        for (_, row), target in zip(group.iloc[1:].iterrows(), plateau[1:]):
            plateau_rows.append(
                {
                    "season": key[0],
                    "harvest_number": int(key[1]),
                    "water_level": key[2],
                    "contrast": f"{row['nitrogen_level']}-N0",
                    "plateau_log_ratio": math.log1p(float(target))
                    - math.log1p(float(n0)),
                }
            )
    plateau = pd.DataFrame(plateau_rows)
    response = response.merge(
        plateau,
        on=["season", "harvest_number", "water_level", "contrast"],
        validate="many_to_one",
    )

    metric_rows = []
    for case_name, case_rows in response.groupby("case"):
        for target_name, target_col in (
            ("observed_shape", "observed_log_ratio"),
            ("monotone_plateau", "plateau_log_ratio"),
        ):
            for final_only in (False, True):
                scoped = case_rows
                if final_only:
                    max_hno = scoped.groupby(
                        ["season", "water_level"]
                    )["harvest_number"].transform("max")
                    scoped = scoped.loc[scoped["harvest_number"].eq(max_hno)]
                for dimensions, group in [
                    (("ALL", "ALL"), scoped),
                    *[
                        ((season, "ALL"), part)
                        for season, part in scoped.groupby("season")
                    ],
                    *[
                        ((season, water), part)
                        for (season, water), part
                        in scoped.groupby(["season", "water_level"])
                    ],
                ]:
                    result = scores(
                        group[target_col].to_numpy(float),
                        group["simulated_log_ratio"].to_numpy(float),
                    )
                    result.update(
                        {
                            "case": case_name,
                            "target": target_name,
                            "scope": "final_harvest" if final_only else "all_harvests",
                            "season": dimensions[0],
                            "water_level": dimensions[1],
                        }
                    )
                    metric_rows.append(result)
    return response, pd.DataFrame(metric_rows)


def posterior_comparison() -> pd.DataFrame:
    bounds = pd.read_csv(BOUNDS, encoding="utf-8-sig")
    bounds = bounds.loc[bounds["status"].astype(str).str.lower().eq("active")]
    summaries = {}
    for case_name, spec in CASES.items():
        frame = pd.read_csv(
            spec["diagnostic"] / "posterior_bounds_touch_summary.csv"
        )
        summaries[case_name] = frame.set_index("name")
    rows = []
    for _, bound in bounds.iterrows():
        name = str(bound["name"]).upper()
        if any(name not in frame.index for frame in summaries.values()):
            continue
        lower, upper = float(bound["lower"]), float(bound["upper"])
        span = upper - lower
        a = summaries["observed_shape"].loc[name]
        b = summaries["monotone_plateau"].loc[name]
        rows.append(
            {
                "name": name,
                "lower": lower,
                "upper": upper,
                "observed_q50": float(a["q50"]),
                "plateau_q50": float(b["q50"]),
                "q50_delta_plateau_minus_observed": float(b["q50"] - a["q50"]),
                "q50_delta_pct_span": (
                    float(100 * (b["q50"] - a["q50"]) / span)
                    if span > 0 else np.nan
                ),
                "observed_touch_pct": float(a["touch_pct"]),
                "plateau_touch_pct": float(b["touch_pct"]),
                "touch_delta_pp": float(b["touch_pct"] - a["touch_pct"]),
                "observed_best": float(a["best"]),
                "plateau_best": float(b["best"]),
            }
        )
    return pd.DataFrame(rows).sort_values(
        "q50_delta_pct_span", key=lambda values: values.abs(), ascending=False
    )


def main() -> int:
    out = ROOT / "workspace/diagnostics/e02_n_response_objective_comparison_20260730"
    out.mkdir(parents=True, exist_ok=True)
    fit = fit_metrics()
    response, response_metrics = response_tables()
    posterior = posterior_comparison()
    phi = pd.concat(
        [phi_family(case, spec) for case, spec in CASES.items()],
        ignore_index=True,
    )
    convergence = []
    summary = {}
    for case_name, spec in CASES.items():
        run = spec["run"]
        case = run.name
        member, best_phi = best_member(run)
        frame = pd.read_csv(run / f"{case}.phi.actual.csv")
        frame.insert(0, "case", case_name)
        convergence.append(frame)
        summary[case_name] = {
            "run_id": case,
            "best_member": member,
            "best_actual_phi": best_phi,
            "final_mean_phi": float(frame.iloc[-1]["mean"]),
            "engineering_status": json.loads(
                (run / "run_status.json").read_text(encoding="utf-8")
            )["engineering_status"],
        }
    fit.to_csv(out / "fit_metrics_by_case_season_variable.csv", index=False)
    response.to_csv(out / "n_response_contrasts_all_cases.csv", index=False)
    response_metrics.to_csv(out / "n_response_metrics.csv", index=False)
    posterior.to_csv(out / "posterior_comparison.csv", index=False)
    phi.to_csv(out / "best_member_phi_by_family_season.csv", index=False)
    pd.concat(convergence, ignore_index=True).to_csv(
        out / "phi_progression_both_cases.csv", index=False
    )
    (out / "comparison_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nResponse metrics (all harvests, matching target):")
    print(
        response_metrics.loc[
            response_metrics["scope"].eq("all_harvests")
            & response_metrics["season"].eq("ALL")
            & response_metrics["water_level"].eq("ALL")
            & (
                (
                    response_metrics["case"].eq("observed_shape")
                    & response_metrics["target"].eq("observed_shape")
                )
                | (
                    response_metrics["case"].eq("monotone_plateau")
                    & response_metrics["target"].eq("monotone_plateau")
                )
            )
        ].to_string(index=False)
    )
    print("\nBest-member Phi by family:")
    print(
        phi.groupby(["case", "family"], as_index=False)
        .agg(phi=("phi", "sum"), phi_share_pct=("phi_share_pct", "sum"))
        .sort_values(["case", "phi"], ascending=[True, False])
        .to_string(index=False)
    )
    print("\nLargest posterior median movements:")
    print(posterior.head(20).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
