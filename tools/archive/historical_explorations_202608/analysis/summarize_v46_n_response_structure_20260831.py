"""Summarize observed/simulated nitrogen response structure for v46 best71.

The summary is deliberately independent of PEST Phi.  It exposes the actual
same-water contrasts (N1/N2/N3 minus N0) by season and harvest date, including
sign changes that can make a smooth nitrogen-response calibration impossible.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.calibration.build_pest import _read_tmt_harvest_events

HARVEST_RE = re.compile(
    r"^RUN\s+(?P<run>\d+)\s+TN\s+(?P<tn>\d+)\s+HNO\s+(?P<hno>\d+)\s+"
    r"DATE\s+(?P<date>\d+).*?@CHFPWS@\s+(?P<value>[-+0-9.eE]+)"
)


def _harvest(path: Path) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = HARVEST_RE.search(line)
        if m:
            rows.append({
                "global_run": int(m["run"]), "hno": int(m["hno"]),
                "date": int(m["date"]), "simulated": float(m["value"]),
            })
    return pd.DataFrame(rows)


def summarize(det_dir: Path, mapping_csv: Path, bundle_25sp: Path, bundle_26sp: Path, out_csv: Path) -> int:
    mapping = pd.read_csv(det_dir / "det_run_mapping.csv")
    mapping["global_run"] = mapping["global_run"].astype(int)
    mapping["treatment"] = mapping["treatment"].astype(int)
    mapping["season_id"] = mapping["season_id"].astype(str)
    map_cols = ["global_run", "season_id", "treatment"]
    mapping = mapping[map_cols].merge(
        pd.read_csv(mapping_csv)[["season_id", "treatment", "water_level", "nitrogen_level"]],
        on=["season_id", "treatment"], how="left", validate="one_to_one",
    )
    sim = _harvest(det_dir / "PestHarvest.OUT").merge(mapping, on="global_run", how="left", validate="many_to_one")

    obs_rows: list[pd.DataFrame] = []
    for season, bundle in (("25SP", bundle_25sp), ("26SP", bundle_26sp)):
        tmt = next(bundle.glob("*.TMT"))
        rows: list[dict[str, object]] = []
        # Reuse the same TMT parser used by build_pest, rather than the
        # generator's intermediate FileT_values.csv.  The latter can retain
        # pre-adjustment values and is not the authoritative calibration input.
        for treatment, events in _read_tmt_harvest_events(str(tmt)).items():
            for hno, event in enumerate(events, 1):
                value = float(event.get("chfpw", -99.0))
                if value == -99.0:
                    continue
                rows.append({
                    "season_id": season, "treatment": int(treatment),
                    "hno": hno, "date": int(event["date"]), "observed": value,
                })
        obs_rows.append(pd.DataFrame(rows))
    obs = pd.concat(obs_rows, ignore_index=True)
    obs = obs.merge(mapping[["season_id", "treatment", "water_level", "nitrogen_level"]].drop_duplicates(),
                    on=["season_id", "treatment"], how="left", validate="many_to_one")

    sim = sim.merge(obs[["season_id", "treatment", "hno", "date", "observed"]],
                    on=["season_id", "treatment", "hno"], how="left", suffixes=("", "_obs"))
    # Use the observed date as authoritative for the paired event; date drift is
    # retained explicitly so it cannot be hidden by a broad merge.
    sim["date_mismatch"] = sim["date"] != sim["date_obs"] if "date_obs" in sim else False
    sim["date"] = sim["date_obs"] if "date_obs" in sim else sim["date"]

    # Build N-level minus N0 contrasts within each season/water/HNO.
    base = sim[sim["nitrogen_level"] == "N0"][["season_id", "water_level", "hno", "date", "observed", "simulated"]]
    base = base.rename(columns={"observed": "observed_n0", "simulated": "simulated_n0"})
    target = sim[
        sim["nitrogen_level"].isin(["N1", "N2", "N3"])
        & sim["water_level"].isin(["W1", "W2", "W3"])
    ].copy()
    target = target.merge(base, on=["season_id", "water_level", "hno", "date"], how="left", validate="many_to_one")
    target["observed_response"] = target["observed"] - target["observed_n0"]
    target["simulated_response"] = target["simulated"] - target["simulated_n0"]
    target["response_error"] = target["simulated_response"] - target["observed_response"]
    target["observed_sign"] = target["observed_response"].map(lambda x: "positive" if x > 0 else "negative" if x < 0 else "zero")
    target["simulated_sign"] = target["simulated_response"].map(lambda x: "positive" if x > 0 else "negative" if x < 0 else "zero")
    target.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--det-dir", type=Path, required=True)
    p.add_argument("--mapping-csv", type=Path, required=True)
    p.add_argument("--bundle-25sp", type=Path, required=True)
    p.add_argument("--bundle-26sp", type=Path, required=True)
    p.add_argument("--out-csv", type=Path, required=True)
    a = p.parse_args()
    a.out_csv.parent.mkdir(parents=True, exist_ok=True)
    return summarize(a.det_dir, a.mapping_csv, a.bundle_25sp, a.bundle_26sp, a.out_csv)


if __name__ == "__main__":
    raise SystemExit(main())
