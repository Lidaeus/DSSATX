"""Per-value verification of conditional replay members (plan P1, gate 4).

For retained member sandboxes (``--verify-members`` of the exporter) this tool
re-parses the raw DSSAT outputs with an independent minimal parser — not the
extractor under test — and compares every harvested event value against a fresh
run of the exporter's extraction functions.  Any mismatch means the frozen
conditional tables cannot be trusted.

Usage::

    python tools/analysis/verify_conditional_replay_members.py \
        --quality-json workspace/runs/<run>/paper_data/conditional_.../conditional_replay_quality.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.export_conditional_predictions import (  # noqa: E402
    extract_member_events,
    extract_member_trajectory,
)

_RUN_TN = re.compile(r"\*RUN\s+(\d+).*?XXQL\d+\s+(\d+)", re.IGNORECASE)


def _parse_dssat_table(path: Path, variables: list[str]) -> dict[int, dict[str, list[dict[str, float]]]]:
    """Independent block parser: run -> variable -> list of {DAP, YEAR, DOY, value}."""
    result: dict[int, dict[str, list[dict[str, float]]]] = {}
    current_tn: int | None = None
    header: list[str] | None = None
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if raw.startswith("*RUN"):
            match = _RUN_TN.search(raw)
            current_tn = int(match.group(2)) if match else None
            if current_tn is not None:
                result.setdefault(current_tn, {v: [] for v in variables})
            header = None
            continue
        if line.startswith("@"):
            header = line.split()
            continue
        if current_tn is None or header is None or not line or line.startswith(("*", "!")):
            continue
        parts = line.split()
        if len(parts) < len(header):
            continue
        record = dict(zip(header, parts))
        try:
            year = int(record["@YEAR"])
            doy = int(record["DOY"])
            dap = float(record["DAP"])
        except (KeyError, ValueError):
            continue
        for variable in variables:
            try:
                value = float(record[variable])
            except (KeyError, ValueError):
                continue
            result[current_tn][variable].append(
                {"dap": dap, "date_code": (year % 100) * 1000 + doy, "value": value}
            )
    return result


def verify_member(member_dir: Path, season_specs: list[dict], tolerance: float = 1e-6) -> dict:
    """Compare exporter extraction vs independent raw parsing for one member."""
    mismatches: list[str] = []
    checked_events = 0
    checked_days = 0
    for spec in season_specs:
        season_dir = member_dir / "_seasons" / spec["season_id"]
        trajectory = extract_member_trajectory(
            season_dir=season_dir,
            season_id=spec["season_id"],
            run_id="verify",
            data_status="verify",
            roles=spec["roles"],
        )
        dap_lookup = {
            (str(row.treatment), int(row.date_code)): float(row.dap)
            for row in trajectory.drop_duplicates(["treatment", "date_code"]).itertuples(index=False)
        }
        events = extract_member_events(
            season_dir=season_dir,
            season_id=spec["season_id"],
            experiment_code=spec["experiment_code"],
            roles=spec["roles"],
            dap_lookup=dap_lookup,
        )

        plantgro = _parse_dssat_table(
            season_dir / "PlantGro.OUT", ["LAID", "LWAD", "SWAD", "CWAD", "DAP"]
        )
        freshwt = _parse_dssat_table(
            season_dir / "FreshWt.OUT", ["CHPDT", "CHFPW", "DAP"]
        )

        # Trajectory cross-check: every extracted daily value must equal the
        # independent parse of the same run/variable/date.
        raw_lookup: dict[tuple[str, str, int], float] = {}
        for source, variables in (
            (plantgro, {"LAID": "LAID", "LWAD": "LWAD", "SWAD": "SWAD", "CWAD": "CWAD"}),
            (freshwt, {"CHPDT": "DRY_CUM", "CHFPW": "FRESH_CUM"}),
        ):
            for tn, by_var in source.items():
                for source_var, contract_var in variables.items():
                    for row in by_var[source_var]:
                        if row["value"] == -99:
                            continue
                        raw_lookup[(str(tn), contract_var, int(row["date_code"]))] = row["value"]
        for row in trajectory.itertuples(index=False):
            key = (str(row.treatment), row.variable, int(row.date_code))
            if key not in raw_lookup:
                mismatches.append(f"trajectory {spec['season_id']} {key} missing in raw parse")
                continue
            checked_days += 1
            if abs(raw_lookup[key] - float(row.simulated)) > tolerance:
                mismatches.append(
                    f"trajectory {spec['season_id']} {key}: extracted {row.simulated} != raw {raw_lookup[key]}"
                )

        # Event cross-check: harvest cumulative values must equal the raw
        # FreshWt value at the matched (on-or-before date+1) date.
        harvest = events[events["variable"].isin(["DRY_CUM", "FRESH_CUM"])]
        for row in harvest.itertuples(index=False):
            tn = int(row.treatment)
            source_var = "CHPDT" if row.variable == "DRY_CUM" else "CHFPW"
            series = {entry["date_code"]: entry["value"] for entry in freshwt[tn][source_var]}
            from src.reporting.analyze_results import _yyddd_add_days

            target = _yyddd_add_days(int(row.date_code), 1)
            candidates = [d for d in series if d <= target and series[d] != -99]
            if not candidates:
                mismatches.append(f"event {spec['season_id']} TN{tn} {row.variable}@{row.date_code}: no raw candidate")
                continue
            matched = max(candidates)
            checked_events += 1
            if abs(series[matched] - float(row.simulated)) > tolerance:
                mismatches.append(
                    f"event {spec['season_id']} TN{tn} {row.variable}@{row.date_code}: "
                    f"extracted {row.simulated} != raw {series[matched]}"
                )
    return {
        "member_dir": str(member_dir),
        "checked_events": checked_events,
        "checked_days": checked_days,
        "mismatches": mismatches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-value conditional replay verification")
    parser.add_argument("--quality-json", required=True)
    parser.add_argument("--tolerance", type=float, default=1e-6)
    args = parser.parse_args(argv)

    quality = json.loads(Path(args.quality_json).read_text(encoding="utf-8"))
    retained = quality.get("verification_members_retained") or {}
    if not retained:
        print("no retained verification members recorded; nothing to verify")
        return 1

    # Rebuild the season specs from the frozen two-season metadata copy.
    bundle_dir = Path(args.quality_json).parent
    metadata = pd.read_csv(bundle_dir / "treatment_metadata_two_season.csv", dtype={"treatment": str})
    design = json.loads(Path(quality["replay_environment"]["calibration_design"]).read_text(encoding="utf-8"))
    design_seasons = {s["season_id"]: s for s in design["seasons"]}
    season_specs = []
    for season in ("25SP", "26SP"):
        roles = {
            str(row.treatment): str(row.dataset_role)
            for row in metadata[metadata["season_id"] == season].itertuples(index=False)
        }
        season_specs.append(
            {
                "season_id": season,
                "experiment_code": str(design_seasons[season]["experiment_code"]),
                "roles": roles,
            }
        )

    failures = 0
    for real, member_dir in sorted(retained.items(), key=lambda item: int(item[0])):
        result = verify_member(Path(member_dir), season_specs, args.tolerance)
        status = "OK" if not result["mismatches"] else "MISMATCH"
        print(
            f"member {real}: {status} — {result['checked_events']} events, "
            f"{result['checked_days']} trajectory days checked"
        )
        for message in result["mismatches"][:10]:
            print(f"  {message}")
        failures += len(result["mismatches"])
    if failures:
        print(f"FAILED: {failures} mismatches")
        return 1
    print("all retained members verified per-value against raw DSSAT outputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
