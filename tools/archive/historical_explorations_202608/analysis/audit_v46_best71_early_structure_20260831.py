"""Audit early/final harvest structure for the v46 best71 nitrogen experiments.

This is an input/identifiability diagnostic, not a calibration scorer.  It
compares the authoritative TMT observations with the deterministic harvest
replay and reports the first and last harvest treatment spread, N contrasts,
and W contrasts.  A parameter trial should not be promoted while the model
has collapsed treatment spread at a harvest where observations clearly vary.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.calibration.build_pest import _read_tmt_harvest_events


def _read_harvest(path: Path) -> pd.DataFrame:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 8 or fields[0] != "RUN" or "@CHFPWS@" not in fields:
            continue
        try:
            hix = fields.index("@CHFPWS@")
            rows.append({"global_run": int(fields[1]), "hno": int(fields[5]),
                         "date_sim": int(fields[7]), "simulated": float(fields[hix + 1])})
        except (ValueError, IndexError):
            continue
    return pd.DataFrame(rows)


def _authoritative_pairs(det_dir: Path, mapping_csv: Path,
                         bundle_25sp: Path, bundle_26sp: Path) -> pd.DataFrame:
    """Rebuild the complete pair table, including N0 (the response summary
    intentionally omits N0 rows).  TMT is the authoritative observation source.
    """
    mapping = pd.read_csv(det_dir / "det_run_mapping.csv")
    mapping["global_run"] = mapping["global_run"].astype(int)
    mapping["treatment"] = mapping["treatment"].astype(int)
    mapping["season_id"] = mapping["season_id"].astype(str)
    meta = pd.read_csv(mapping_csv)[["season_id", "treatment", "water_level", "nitrogen_level"]]
    mapping = mapping.merge(meta, on=["season_id", "treatment"], how="left", validate="one_to_one")
    sim = _read_harvest(det_dir / "PestHarvest.OUT").merge(mapping, on="global_run", how="left", validate="many_to_one")
    obs_rows = []
    for season, bundle in (("25SP", bundle_25sp), ("26SP", bundle_26sp)):
        tmt = next(bundle.glob("*.TMT"))
        for treatment, events in _read_tmt_harvest_events(str(tmt)).items():
            for hno, event in enumerate(events, 1):
                value = float(event.get("chfpw", -99.0))
                if value != -99.0:
                    obs_rows.append({"season_id": season, "treatment": int(treatment),
                                     "hno": hno, "date_obs": int(event["date"]),
                                     "observed": value})
    obs = pd.DataFrame(obs_rows)
    out = sim.merge(obs, on=["season_id", "treatment", "hno"], how="inner", validate="one_to_one")
    out["date_mismatch"] = out["date_sim"] != out["date_obs"]
    return out


def _first_harvest_fruit_state(det_dir: Path, mapping_csv: Path) -> pd.DataFrame:
    """Extract fruit-number/size state at the 26SP first harvest.

    These fields help distinguish a missing N-response mechanism from a simple
    cumulative-yield extraction problem: if CHNUM/CMFNM/AFPWD are nearly
    invariant while observations differ strongly, no N-response weight can
    recreate the observed first event.
    """
    path = det_dir / "_seasons/26SP/FreshWt.OUT"
    if not path.is_file():
        return pd.DataFrame()
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header = next((x for x in lines if x.startswith("@YEAR")), None)
    if not header:
        return pd.DataFrame()
    cols = header[1:].split()
    rows = []
    run = None
    for line in lines:
        if line.startswith("*RUN"):
            try:
                run = int(line.split()[1])
            except (ValueError, IndexError):
                run = None
            continue
        fields = line.split()
        if run is not None and fields and fields[0] == "2026" and len(fields) == len(cols) and fields[1] == "146":
            row = {"global_run": run}
            row.update({k: fields[i] for i, k in enumerate(cols)})
            rows.append(row)
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    mapping = pd.read_csv(mapping_csv)[["season_id", "treatment", "water_level", "nitrogen_level"]]
    mapping = mapping[mapping["season_id"].eq("26SP")].copy()
    mapping["global_run"] = range(1, len(mapping) + 1)
    out = out.merge(mapping, on="global_run", how="left", validate="one_to_one")
    keep = ["global_run", "treatment", "water_level", "nitrogen_level",
            "AFPWD", "ADPWD", "CHNUM", "CMFNM", "CHFPW", "CHPDT", "MTFPW", "MTDPW"]
    return out[[x for x in keep if x in out.columns]]


def run(det_dir: Path, mapping_csv: Path,
        bundle_25sp: Path, bundle_26sp: Path, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Do not use the response summary as the pair source: it deliberately
    # drops N0, which would make N3-N0 auditing silently impossible.
    d = _authoritative_pairs(det_dir, mapping_csv, bundle_25sp, bundle_26sp)
    d["treatment"] = d["treatment"].astype(int)
    d["hno"] = d["hno"].astype(int)
    d["observed"] = pd.to_numeric(d["observed"], errors="coerce")
    d["simulated"] = pd.to_numeric(d["simulated"], errors="coerce")
    d = d.dropna(subset=["observed", "simulated"])

    # Keep only W1/W2/W3; CK is not a water-response level.
    d = d[d["water_level"].isin(["W1", "W2", "W3"])].copy()
    d["residual"] = d["simulated"] - d["observed"]
    d["abs_error"] = d["residual"].abs()
    d["relative_error"] = d["residual"] / d["observed"].replace(0, np.nan)
    d.to_csv(out_dir / "early_structure_pairs.csv", index=False, encoding="utf-8-sig")
    fruit = _first_harvest_fruit_state(det_dir, mapping_csv)
    fruit.to_csv(out_dir / "first_harvest_fruit_state.csv", index=False, encoding="utf-8-sig")

    # Treatment spread at each harvest.  CV is only reported when the mean is
    # positive; absolute range remains valid for signed/near-zero observations.
    spread_rows = []
    for (season, hno), g in d.groupby(["season_id", "hno"], sort=True):
        for source in ("observed", "simulated"):
            vals = g[source].to_numpy(float)
            mean = float(np.mean(vals)) if len(vals) else np.nan
            spread_rows.append({
                "season_id": season, "hno": int(hno), "source": source,
                "n_treatments": int(len(vals)), "mean": mean,
                "sd": float(np.std(vals, ddof=1)) if len(vals) > 1 else np.nan,
                "min": float(np.min(vals)) if len(vals) else np.nan,
                "max": float(np.max(vals)) if len(vals) else np.nan,
                "range": float(np.ptp(vals)) if len(vals) else np.nan,
                "cv": float(np.std(vals, ddof=1) / mean)
                if len(vals) > 1 and mean > 0 else np.nan,
            })
    spread = pd.DataFrame(spread_rows)
    spread.to_csv(out_dir / "harvest_spread_summary.csv", index=False, encoding="utf-8-sig")

    # Same-water N3-N0 and season-specific W contrast.  Missing contrasts are
    # retained explicitly rather than silently filled.
    n_rows, w_rows = [], []
    for (season, water, hno), g in d.groupby(["season_id", "water_level", "hno"], sort=True):
        for source in ("observed", "simulated"):
            x = g.set_index("nitrogen_level")[source]
            if "N3" in x.index and "N0" in x.index:
                n_rows.append({"season_id": season, "water_level": water,
                               "hno": int(hno), "source": source,
                               "n3_minus_n0": float(x["N3"] - x["N0"])})
    w_pair = {"25SP": ("W3", "W1"), "26SP": ("W2", "W1")}
    for (season, nitrogen, hno), g in d.groupby(["season_id", "nitrogen_level", "hno"], sort=True):
        wa, wb = w_pair.get(season, ("W3", "W1"))
        for source in ("observed", "simulated"):
            x = g.set_index("water_level")[source]
            if wa in x.index and wb in x.index:
                w_rows.append({"season_id": season, "nitrogen_level": nitrogen,
                               "hno": int(hno), "source": source,
                               "contrast": f"{wa}-{wb}",
                               "water_response": float(x[wa] - x[wb])})
    pd.DataFrame(n_rows).to_csv(out_dir / "n3_minus_n0_by_harvest.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(w_rows).to_csv(out_dir / "water_response_by_harvest.csv", index=False, encoding="utf-8-sig")

    # Machine-readable decision flags for the handoff.
    flags = []
    for (season, hno), g in d.groupby(["season_id", "hno"], sort=True):
        obs = g["observed"].to_numpy(float)
        sim = g["simulated"].to_numpy(float)
        obs_range, sim_range = float(np.ptp(obs)), float(np.ptp(sim))
        obs_cv = float(np.std(obs, ddof=1) / np.mean(obs)) if len(obs) > 1 and np.mean(obs) > 0 else np.nan
        sim_cv = float(np.std(sim, ddof=1) / np.mean(sim)) if len(sim) > 1 and np.mean(sim) > 0 else np.nan
        flags.append({
            "season_id": season, "hno": int(hno),
            "observed_range": obs_range, "simulated_range": sim_range,
            "range_ratio_sim_obs": sim_range / obs_range if obs_range > 0 else np.nan,
            "observed_cv": obs_cv, "simulated_cv": sim_cv,
            "spread_collapse_flag": bool(obs_range > 0 and sim_range / obs_range < 0.25),
            "n_treatment_rows": int(len(g)),
        })
    pd.DataFrame(flags).to_csv(out_dir / "early_structure_flags.csv", index=False, encoding="utf-8-sig")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--det-dir", type=Path, required=True)
    p.add_argument("--mapping-csv", type=Path, required=True)
    p.add_argument("--bundle-25sp", type=Path, required=True)
    p.add_argument("--bundle-26sp", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    a = p.parse_args()
    run(a.det_dir, a.mapping_csv, a.bundle_25sp, a.bundle_26sp, a.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
