"""Diagnose W2-W1 response structure for formal member 126."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "workspace/runs/e02_fixedsoil_nse_official_25sp26sp_200x6_20260817"
CANDIDATE = RUN / "deterministic_candidates/phi_q10_highest_nse"
MAPPING = ROOT / "configs/runs/e02_v2_25sp26sp_water_n_mapping_20260808.csv"
OUT = ROOT / "workspace/reports/member126_water_response_diagnostic_20260818"


def parse_plantgro(path: Path, season: str) -> pd.DataFrame:
    rows: list[dict] = []
    treatment = None
    header = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("*RUN"):
            match = re.search(r"XXQL\d+\s+(\d+)\s*$", line)
            treatment = int(match.group(1)) if match else None
            header = None
        elif treatment is not None and line.startswith(("@YEAR", "@  YEAR")):
            header = line.split()
        elif treatment is not None and header and line.strip() and not line.startswith(("!", "$", "*", "@")):
            values = line.split()
            if len(values) != len(header):
                continue
            record = dict(zip(header, values))
            if "WSPD" not in record:
                continue
            try:
                rows.append({
                    "season_id": season, "treatment": treatment,
                    "date_code": int(record["@YEAR"]), "dap": int(record.get("DAP", -1)),
                    "wspd": float(record["WSPD"]), "wsgd": float(record.get("WSGD", "nan")),
                })
            except (KeyError, ValueError):
                continue
    if not rows:
        raise ValueError(f"no WSPD rows parsed from {path}")
    return pd.DataFrame(rows)


def parse_harvest(path: Path, season: str) -> pd.DataFrame:
    pattern = re.compile(
        r"RUN\s+\d+\s+TN\s+(\d+)\s+HNO\s+(\d+)\s+DATE\s+(\d+).*?@CHPDTS(?:_T)?@\s+([-+0-9.Ee]+)"
    )
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.search(line)
        if match:
            rows.append({"season_id": season, "treatment": int(match.group(1)), "harvest": int(match.group(2)),
                         "date_code": int(match.group(3)), "simulated_chpdt": float(match.group(4))})
    return pd.DataFrame(rows)


def parse_irrigation(path: Path, season: str) -> pd.DataFrame:
    rows = []
    current_id = None
    current_name = None
    reading_events = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("*IRRIGATION AND WATER MANAGEMENT"):
            current_id = current_name = None
            reading_events = False
            continue
        if re.match(r"^@I\s+EFIR", line):
            reading_events = False
            continue
        if re.match(r"^@I\s+IDATE", line):
            reading_events = True
            continue
        if not line.strip() or line.startswith(("*", "@")):
            if line.startswith("*") and rows:
                reading_events = False
            continue
        values = line.split()
        if not reading_events and len(values) >= 9 and values[0].isdigit():
            current_id, current_name = int(values[0]), values[-1]
        elif reading_events and current_id is not None and len(values) >= 4 and values[0].isdigit():
            try:
                rows.append({"season_id": season, "irrigation_level_id": current_id, "irrigation_name": current_name,
                             "date_code": int(values[1]), "amount_mm": float(values[3])})
            except ValueError:
                pass
    return pd.DataFrame(rows)


def parse_soil_water(path: Path, season: str) -> pd.DataFrame:
    pattern = re.compile(r"RUN\s+\d+\s+TN\s+(\d+)\s+DATE\s+(\d+)\s+@(SW\d+S)@\s+([-+0-9.Ee]+)")
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.search(line)
        if match:
            rows.append({"season_id": season, "treatment": int(match.group(1)), "date_code": int(match.group(2)),
                         "soil_water_token": match.group(3), "soil_water": float(match.group(4))})
    return pd.DataFrame(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    mapping = pd.read_csv(MAPPING)
    daily_parts, harvest_parts, irrigation_parts, soil_parts = [], [], [], []
    for season in ("25SP", "26SP"):
        season_dir = CANDIDATE / "_seasons" / season
        daily_parts.append(parse_plantgro(season_dir / "PlantGro.OUT", season))
        harvest_parts.append(parse_harvest(season_dir / "PestHarvest.OUT", season))
        soil_parts.append(parse_soil_water(season_dir / "PestSoilWat.OUT", season))
        tmx = next(season_dir.glob("*.TMX"))
        irrigation_parts.append(parse_irrigation(tmx, season))
    daily = pd.concat(daily_parts, ignore_index=True).merge(mapping, on=["season_id", "treatment"], validate="many_to_one")
    harvest = pd.concat(harvest_parts, ignore_index=True).merge(mapping, on=["season_id", "treatment"], validate="many_to_one")
    irrigation = pd.concat(irrigation_parts, ignore_index=True)
    soil = pd.concat(soil_parts, ignore_index=True).merge(mapping, on=["season_id", "treatment"], validate="many_to_one")
    # PestSoilWat tokens are observation identifiers and therefore differ by
    # treatment.  Within a treatment/date they retain the audited shallow-to-
    # deep measured-depth order, which is the correct pairing key here.
    soil["depth_order"] = soil.groupby(["season_id", "treatment", "date_code"]).cumcount() + 1

    stress = (
        daily.groupby(["season_id", "treatment", "water_level", "nitrogen_level"], as_index=False)
        .agg(days=("wspd", "size"), wspd_mean=("wspd", "mean"), wspd_min=("wspd", "min"),
             wspd_days_above_005=("wspd", lambda x: int((x > .05).sum())),
             wspd_days_above_020=("wspd", lambda x: int((x > .20).sum())),
             wspd_stress_sum=("wspd", "sum"),
             wsgd_mean=("wsgd", "mean"), wsgd_min=("wsgd", "min"))
    )
    irrigation_summary = irrigation.groupby(["season_id", "irrigation_level_id", "irrigation_name"], as_index=False).agg(
        events=("amount_mm", "size"), irrigation_total_mm=("amount_mm", "sum"),
        first_date=("date_code", "min"), last_date=("date_code", "max"))

    final_harvest = harvest.loc[harvest.groupby(["season_id", "treatment"])["harvest"].idxmax()].copy()
    pair_rows = []
    for (season, nitrogen), group in final_harvest.groupby(["season_id", "nitrogen_level"]):
        by_water = group.set_index("water_level")
        if {"W2", "W1"}.issubset(by_water.index):
            high, low = by_water.loc["W2"], by_water.loc["W1"]
            pair_rows.append({"season_id": season, "nitrogen_level": nitrogen,
                              "w2_treatment": int(high.treatment), "w1_treatment": int(low.treatment),
                              "w2_final_chpdt": float(high.simulated_chpdt), "w1_final_chpdt": float(low.simulated_chpdt),
                              "simulated_w2_minus_w1": float(high.simulated_chpdt - low.simulated_chpdt)})
    pairs = pd.DataFrame(pair_rows)
    stress_pairs = stress[stress.water_level.isin(["W1", "W2"])].pivot(
        index=["season_id", "nitrogen_level"], columns="water_level",
        values=["wspd_mean", "wspd_min", "wspd_days_above_005", "wspd_stress_sum"],
    )
    stress_pairs.columns = [f"{metric.lower()}_{water.lower()}" for metric, water in stress_pairs.columns]
    stress_pairs = stress_pairs.reset_index()
    pair_diagnostic = pairs.merge(stress_pairs, on=["season_id", "nitrogen_level"], how="left", validate="one_to_one")
    pair_diagnostic["wspd_mean_w2_minus_w1"] = pair_diagnostic["wspd_mean_w2"] - pair_diagnostic["wspd_mean_w1"]
    pair_diagnostic["wspd_stress_w2_minus_w1"] = pair_diagnostic["wspd_stress_sum_w2"] - pair_diagnostic["wspd_stress_sum_w1"]

    soil_pairs = soil[soil.water_level.isin(["W1", "W2"])].pivot_table(
        index=["season_id", "nitrogen_level", "date_code", "depth_order"],
        columns="water_level", values="soil_water", aggfunc="first",
    ).dropna(subset=["W1", "W2"]).reset_index()
    soil_pairs["soil_water_w2_minus_w1"] = soil_pairs["W2"] - soil_pairs["W1"]

    outputs = {
        "daily_water_stress.csv": daily,
        "treatment_water_stress_summary.csv": stress,
        "irrigation_schedule.csv": irrigation,
        "irrigation_summary.csv": irrigation_summary,
        "soil_water_observation_date_pairs.csv": soil_pairs,
        "final_harvest_water_pairs.csv": pair_diagnostic,
    }
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False, encoding="utf-8-sig")
    summary = {
        "candidate": "formal member 126 / phi_q10_highest_nse deterministic replay",
        "wspd_interpretation": "0=no photosynthesis water stress; larger values indicate stronger stress",
        "pair_count": len(pair_diagnostic),
        "all_w2_irrigation_exceeds_w1": bool((mapping[mapping.water_level.eq("W2")].irrigation_mm.min() > mapping[mapping.water_level.eq("W1")].irrigation_mm.max())),
        "mean_simulated_w2_minus_w1_by_season": pair_diagnostic.groupby("season_id")["simulated_w2_minus_w1"].mean().to_dict(),
        "mean_wspd_difference_by_season": pair_diagnostic.groupby("season_id")["wspd_mean_w2_minus_w1"].mean().to_dict(),
        "mean_soil_water_w2_minus_w1_by_season": soil_pairs.groupby("season_id")["soil_water_w2_minus_w1"].mean().to_dict(),
    }
    (OUT / "diagnostic_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(pair_diagnostic.to_string(index=False))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
