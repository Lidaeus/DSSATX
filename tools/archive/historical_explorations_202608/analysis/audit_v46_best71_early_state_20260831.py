"""Audit pre-first-harvest process state for the v46 best71 replay.

This read-only diagnostic joins ``PestTmtGrow.OUT`` (simulated process
states), authoritative TMT process observations, and ``PestHarvest.OUT``
first-event fresh yield.  It is intentionally separate from the calibration
objective and does not alter observations, weights, or bundles.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.calibration.build_pest import _read_tmt_harvest_events, _read_tmt_process_points


_RUN_RE = re.compile(r"RUN\s+(?P<run>\d+)\s+TN\s+(?P<tn>\d+)\s+DATE\s+(?P<date>\d+)")
_FIELD_RE = re.compile(r"@(?P<key>[A-Za-z0-9#]+)@\s+(?P<value>[-+0-9.Ee]+)")


def _parse_tmtgrow(path: Path) -> pd.DataFrame:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _RUN_RE.search(line)
        if not m:
            continue
        row: dict[str, object] = {
            "global_run": int(m.group("run")),
            "treatment_model": int(m.group("tn")),
            "date": int(m.group("date")),
        }
        for fm in _FIELD_RE.finditer(line):
            try:
                row[fm.group("key").upper()] = float(fm.group("value"))
            except ValueError:
                continue
        rows.append(row)
    if not rows:
        raise ValueError(f"no process rows parsed from {path}")
    return pd.DataFrame(rows)


def _parse_first_harvest(path: Path) -> pd.DataFrame:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("RUN") or "@CHFPWS@" not in line:
            continue
        fields = line.split()
        try:
            hix = fields.index("@CHFPWS@")
            hno = int(fields[5])
            if hno != 1:
                continue
            rows.append({
                "global_run": int(fields[1]),
                "treatment_model": int(fields[3]),
                "hno": hno,
                "date_sim": int(fields[7]),
                "sim_first_fresh": float(fields[hix + 1]),
            })
        except (ValueError, IndexError):
            continue
    if not rows:
        raise ValueError(f"no first harvest rows parsed from {path}")
    return pd.DataFrame(rows)


def _mapping(det_dir: Path, mapping_csv: Path, season: str) -> pd.DataFrame:
    run_map = pd.read_csv(det_dir / "det_run_mapping.csv")
    run_map["global_run"] = pd.to_numeric(run_map["global_run"], errors="raise").astype(int)
    run_map["treatment"] = pd.to_numeric(run_map["treatment"], errors="raise").astype(int)
    run_map = run_map[run_map["season_id"].astype(str).str.upper().eq(season.upper())].copy()
    meta = pd.read_csv(mapping_csv)
    meta = meta[["season_id", "treatment", "water_level", "nitrogen_level"]].copy()
    meta["treatment"] = pd.to_numeric(meta["treatment"], errors="raise").astype(int)
    meta = meta[meta["season_id"].astype(str).str.upper().eq(season.upper())]
    return run_map.merge(meta, on=["season_id", "treatment"], how="left", validate="one_to_one")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--det-dir", type=Path, required=True)
    p.add_argument("--mapping-csv", type=Path, required=True)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--season", default="26SP")
    p.add_argument("--out-dir", type=Path, required=True)
    args = p.parse_args()
    det_dir = args.det_dir.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    season = str(args.season).upper()

    mapping = _mapping(det_dir, args.mapping_csv.resolve(), season)
    pg = _parse_tmtgrow(det_dir / "PestTmtGrow.OUT")
    pg = pg.merge(mapping, on="global_run", how="inner", validate="many_to_one")
    pg = pg[pg["date"].between(26000, 26999)].copy()
    if pg.empty:
        raise ValueError(f"no {season} process rows in {det_dir}")

    tmt = next(args.bundle.resolve().glob("*.TMT"))
    obs_rows = []
    for treatment, points in _read_tmt_process_points(str(tmt)).items():
        for point in points:
            obs_rows.append({
                "treatment": int(treatment),
                "date": int(point["date"]),
                "obs_LAI": float(point["laid"]),
                "obs_LWAD": float(point["lwad"]),
                "obs_SWAD": float(point["swad"]),
                "obs_CHTD": float(point["chtd"]),
            })
    obs = pd.DataFrame(obs_rows)
    pair = pg.merge(obs, on=["treatment", "date"], how="left", validate="many_to_one")
    pair = pair.rename(columns={"LAIDS": "sim_LAI", "LWADS": "sim_LWAD", "SWADS": "sim_SWAD", "CHTDS": "sim_CHTD"})
    keep = ["global_run", "treatment", "water_level", "nitrogen_level", "date",
            "sim_LAI", "sim_LWAD", "sim_SWAD", "sim_CHTD",
            "obs_LAI", "obs_LWAD", "obs_SWAD", "obs_CHTD"]
    pair = pair[[c for c in keep if c in pair.columns]].sort_values(["date", "treatment"])
    pair.to_csv(out_dir / "early_state_pairs.csv", index=False, encoding="utf-8-sig")

    # Treatment spread and model/observation range ratio at every observed date.
    variables = [("LAI", "sim_LAI", "obs_LAI"), ("LWAD", "sim_LWAD", "obs_LWAD"),
                 ("SWAD", "sim_SWAD", "obs_SWAD"), ("CHTD", "sim_CHTD", "obs_CHTD")]
    spread_rows = []
    for date, g in pair.groupby("date", sort=True):
        for label, sim_col, obs_col in variables:
            for source, col in (("simulated", sim_col), ("observed", obs_col)):
                vals = pd.to_numeric(g[col], errors="coerce").dropna().to_numpy(float)
                if len(vals) == 0:
                    continue
                spread_rows.append({
                    "season": season, "date": int(date), "variable": label,
                    "source": source, "n": int(len(vals)),
                    "mean": float(np.mean(vals)), "min": float(np.min(vals)),
                    "max": float(np.max(vals)), "range": float(np.ptp(vals)),
                })
    spread = pd.DataFrame(spread_rows)
    spread.to_csv(out_dir / "early_state_spread_summary.csv", index=False, encoding="utf-8-sig")

    flags = []
    for (date, variable), g in spread.groupby(["date", "variable"], sort=True):
        sim = g.loc[g["source"].eq("simulated"), "range"]
        obsr = g.loc[g["source"].eq("observed"), "range"]
        if sim.empty or obsr.empty:
            continue
        ratio = float(sim.iloc[0] / obsr.iloc[0]) if obsr.iloc[0] > 0 else np.nan
        flags.append({"season": season, "date": int(date), "variable": variable,
                      "simulated_range": float(sim.iloc[0]), "observed_range": float(obsr.iloc[0]),
                      "range_ratio_sim_obs": ratio,
                      "spread_collapse_flag": bool(np.isfinite(ratio) and ratio < 0.25)})
    pd.DataFrame(flags).to_csv(out_dir / "early_state_flags.csv", index=False, encoding="utf-8-sig")

    harvest = _parse_first_harvest(det_dir / "PestHarvest.OUT")
    harvest = harvest.merge(mapping, on="global_run", how="inner", validate="one_to_one")
    tmt_events = _read_tmt_harvest_events(str(tmt))
    obs_h = []
    for treatment, events in tmt_events.items():
        if events:
            e = events[0]
            obs_h.append({"treatment": int(treatment), "date_obs": int(e["date"]),
                          "obs_first_fresh": float(e.get("chfpw", -99.0)),
                          "obs_first_hfpow": float(e.get("hfpow", -99.0))})
    first = harvest.merge(pd.DataFrame(obs_h), on="treatment", how="left", validate="one_to_one")
    first["residual_first_fresh"] = first["sim_first_fresh"] - first["obs_first_fresh"]
    first.to_csv(out_dir / "first_harvest_fresh_pairs.csv", index=False, encoding="utf-8-sig")

    first_valid = first.loc[first["obs_first_fresh"].gt(-99)]
    state_26122 = pair.loc[pair["date"].eq(26122)]
    audit = {
        "season": season,
        "det_dir": str(det_dir),
        "bundle": str(args.bundle.resolve()),
        "n_treatments": int(mapping["treatment"].nunique()),
        "n_process_rows": int(len(pair)),
        "process_dates": sorted(int(x) for x in pair["date"].unique()),
        "first_harvest_rows": int(len(first)),
        "first_harvest_date_sim_unique": sorted(int(x) for x in first["date_sim"].unique()),
        "first_harvest_date_obs_unique": sorted(int(x) for x in first["date_obs"].dropna().unique()),
        "first_harvest_date_mismatch_count": int((first["date_sim"] != first["date_obs"]).fillna(True).sum()),
        "state_26122_rows": int(len(state_26122)),
        "state_26122_simulated_lai_range": float(np.ptp(state_26122["sim_LAI"].to_numpy(float))) if len(state_26122) else None,
        "state_26122_observed_lai_range": float(np.ptp(state_26122["obs_LAI"].to_numpy(float))) if len(state_26122) else None,
        "first_harvest_sim_fresh_range": float(np.ptp(first_valid["sim_first_fresh"].to_numpy(float))) if len(first_valid) else None,
        "first_harvest_obs_fresh_range": float(np.ptp(first_valid["obs_first_fresh"].to_numpy(float))) if len(first_valid) else None,
    }
    (out_dir / "early_state_audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
