"""Audit three-season water×nitrogen mappings and observed dry-yield responses.

The mapping is derived from each current FileX.  It intentionally does not
trust the early SA contract's W1/W3 labels because XXQL2501 uses a different
MI-number ordering from XXQL2502/XXQL2601.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.experiment_inputs import parse_filex
from src.sensitivity.treatment_factor_attribution import fertilizer_n_total_kg_ha


DEFAULT_COMPARISON = (
    ROOT
    / "workspace/diagnostics"
    / "e02_joint62_three_season_nstfac050_rhght035_150x5_20260730_best"
    / "comparison_original_scale.csv"
)
SEASONS = {
    "25SP": (
        "XXQL2501",
        ROOT
        / "data/user/experiments"
        / "xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"
        / "XXQL2501.TMX",
    ),
    "25FA": (
        "XXQL2502",
        ROOT
        / "data/user/experiments"
        / "xxql2502_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"
        / "XXQL2502.TMX",
    ),
    "26SP": (
        "XXQL2601",
        ROOT
        / "data/user/experiments"
        / "xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"
        / "XXQL2601.TMX",
    ),
}


def irrigation_profiles(filex: Path) -> dict[int, dict[str, float | str]]:
    profiles: dict[int, dict[str, float | str]] = {}
    in_section = False
    header_kind = ""
    for raw in filex.read_text(encoding="utf-8", errors="ignore").splitlines():
        upper = raw.strip().upper()
        if upper.startswith("*IRRIGATION AND WATER MANAGEMENT"):
            in_section = True
            continue
        if in_section and raw.startswith("*"):
            break
        if not in_section or not upper:
            continue
        if upper.startswith("@I"):
            header_kind = "events" if "IDATE" in upper and "IRVAL" in upper else "profile"
            continue
        tokens = raw.split()
        if not tokens:
            continue
        try:
            level = int(tokens[0])
        except ValueError:
            continue
        if header_kind == "profile":
            profiles.setdefault(level, {"name": tokens[-1].upper(), "total_mm": 0.0})
        elif header_kind == "events" and len(tokens) >= 4:
            profiles.setdefault(level, {"name": f"MI{level}", "total_mm": 0.0})
            profiles[level]["total_mm"] = float(profiles[level]["total_mm"]) + float(tokens[3])
    return profiles


def treatment_mapping(season: str, experiment: str, filex: Path) -> pd.DataFrame:
    parsed = parse_filex(filex)
    text = filex.read_text(encoding="utf-8", errors="ignore")
    irrig = irrigation_profiles(filex)
    rows = []
    for treatment, factors in parsed["treatments"].items():
        mi = int(factors["MI"])
        mf = int(factors["MF"])
        if mi not in irrig:
            continue
        water_name = str(irrig[mi]["name"]).upper()
        if water_name not in {"W1", "W3"}:
            continue
        dose = fertilizer_n_total_kg_ha(text, mf)
        rows.append(
            {
                "season": season,
                "experiment": experiment,
                "treatment": int(treatment),
                "mi": mi,
                "water_level": water_name,
                "irrigation_mm": float(irrig[mi]["total_mm"]),
                "mf": mf,
                "nitrogen_kg_ha": dose,
            }
        )
    frame = pd.DataFrame(rows)
    for water, group in frame.groupby("water_level"):
        doses = sorted(group["nitrogen_kg_ha"].unique())
        if len(doses) != 4:
            raise RuntimeError(f"{season} {water}: expected four N doses, found {doses}")
        labels = {dose: f"N{index}" for index, dose in enumerate(doses)}
        # Ascending dose is N0,N1,N2,N3.
        frame.loc[group.index, "nitrogen_level"] = group["nitrogen_kg_ha"].map(labels)
    return frame.sort_values(["water_level", "nitrogen_kg_ha"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comparison", type=Path, default=DEFAULT_COMPARISON)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "workspace/diagnostics/e02_three_season_n_response_objective_audit_20260730",
    )
    args = parser.parse_args()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    mappings = pd.concat(
        [
            treatment_mapping(season, experiment, filex)
            for season, (experiment, filex) in SEASONS.items()
        ],
        ignore_index=True,
    )
    problems: list[str] = []
    for season, season_rows in mappings.groupby("season"):
        combos = season_rows[["water_level", "nitrogen_level"]].drop_duplicates()
        if len(combos) != 8:
            problems.append(f"{season}: expected complete 2x4 design; found {len(combos)} cells")
        totals = season_rows.groupby("water_level")["irrigation_mm"].first()
        if not float(totals["W3"]) > float(totals["W1"]):
            problems.append(f"{season}: FileX W3 irrigation is not greater than W1")
    if problems:
        raise RuntimeError("; ".join(problems))

    comparison = pd.read_csv(args.comparison)
    harvest = comparison.loc[
        comparison["variable"].eq("DRY_CUM"),
        ["season", "treatment", "harvest_number", "time", "observed", "simulated"],
    ].copy()
    harvest["treatment"] = pd.to_numeric(harvest["treatment"], errors="raise").astype(int)
    harvest["harvest_number"] = pd.to_numeric(
        harvest["harvest_number"], errors="raise"
    )
    harvest = harvest.merge(
        mappings[
            [
                "season",
                "treatment",
                "water_level",
                "nitrogen_level",
                "nitrogen_kg_ha",
                "irrigation_mm",
            ]
        ],
        on=["season", "treatment"],
        how="inner",
        validate="many_to_one",
    )
    cell_counts = (
        harvest.groupby(["season", "harvest_number", "water_level"])
        .size()
        .rename("n_cells")
        .reset_index()
    )
    incomplete = cell_counts.loc[cell_counts["n_cells"].ne(4)]
    if not incomplete.empty:
        problems.append(
            f"{len(incomplete)} season/harvest/water groups lack all four N levels"
        )

    contrast_rows = []
    for keys, group in harvest.groupby(["season", "harvest_number", "water_level"]):
        season, harvest_number, water = keys
        by_n = group.set_index("nitrogen_level")
        if not {"N0", "N1", "N2", "N3"} <= set(by_n.index):
            continue
        n0_obs = float(by_n.loc["N0", "observed"])
        n0_sim = float(by_n.loc["N0", "simulated"])
        for level in ("N1", "N2", "N3"):
            contrast_rows.append(
                {
                    "season": season,
                    "harvest_number": int(harvest_number),
                    "water_level": water,
                    "contrast": f"{level}-N0",
                    "observed_difference": float(by_n.loc[level, "observed"]) - n0_obs,
                    "simulated_difference": float(by_n.loc[level, "simulated"]) - n0_sim,
                    "observed_log_ratio": float(
                        np.log1p(float(by_n.loc[level, "observed"])) - np.log1p(n0_obs)
                    ),
                    "simulated_log_ratio": float(
                        np.log1p(float(by_n.loc[level, "simulated"])) - np.log1p(n0_sim)
                    ),
                }
            )
    contrasts = pd.DataFrame(contrast_rows)

    final_rows = (
        harvest.sort_values("harvest_number")
        .groupby(["season", "water_level", "nitrogen_level"], as_index=False)
        .tail(1)
        .sort_values(["season", "water_level", "nitrogen_kg_ha"])
    )
    final_contrasts = (
        contrasts.sort_values("harvest_number")
        .groupby(["season", "water_level", "contrast"], as_index=False)
        .tail(1)
        .sort_values(["season", "water_level", "contrast"])
    )

    mappings.to_csv(out_dir / "treatment_water_nitrogen_mapping.csv", index=False)
    harvest.to_csv(out_dir / "observed_simulated_cumulative_harvest.csv", index=False)
    contrasts.to_csv(out_dir / "n_response_contrasts_by_harvest.csv", index=False)
    final_rows.to_csv(out_dir / "final_yield_by_water_nitrogen.csv", index=False)
    final_contrasts.to_csv(out_dir / "final_n_response_contrasts.csv", index=False)
    summary = {
        "status": "passed" if not problems else "warning",
        "seasons": sorted(mappings["season"].unique()),
        "mapping_rows": int(len(mappings)),
        "complete_factorial_cells_per_season": 8,
        "contrast_rows": int(len(contrasts)),
        "problems": problems,
        "important_mapping_finding": (
            "XXQL2501 MI numbering is opposite XXQL2502/XXQL2601; "
            "FileX IRNAME and irrigation totals control W1/W3 labels."
        ),
    }
    (out_dir / "audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nFinal observed yields:")
    print(
        final_rows[
            [
                "season",
                "water_level",
                "nitrogen_level",
                "nitrogen_kg_ha",
                "observed",
                "simulated",
            ]
        ].to_string(index=False)
    )
    print("\nFinal response contrasts:")
    print(final_contrasts.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
