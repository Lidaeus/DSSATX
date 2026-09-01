"""Audit N/W response output against the paired harvest source values.

The audit is deliberately independent of PEST Phi.  It verifies that each
``PestNResponse.OUT``/``PestWResponse.OUT`` row is reproducible from the same
``PestHarvest.OUT`` event, explicit treatment mapping, and CHFPW source.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
HARVEST_RE = re.compile(
    r"^RUN\s+(?P<run>\d+)\s+TN\s+(?P<tn>\d+)\s+HNO\s+(?P<hno>\d+)\s+"
    r"DATE\s+(?P<date>\d+).*?@CHFPWS@\s+(?P<value>[-+0-9.eE]+)"
)
RESP_RE = re.compile(
    r"^RUN\s+(?P<run>\d+)\s+TN\s+(?P<tn>\d+)\s+@HNO@\s+(?P<hno>\d+)\s+"
    r"DATE\s+(?P<date>\d+).*?@(?P<token>NRESPS|WRESPS)@\s+(?P<value>[-+0-9.eE]+)"
)


def _read_harvest(path: Path) -> dict[tuple[int, int], tuple[int, float]]:
    values: dict[tuple[int, int], tuple[int, float]] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = HARVEST_RE.search(line)
        if match:
            values[(int(match["run"]), int(match["hno"]))] = (
                int(match["date"]), float(match["value"])
            )
    return values


def _read_response(path: Path, token: str) -> dict[tuple[int, int], tuple[int, float]]:
    values: dict[tuple[int, int], tuple[int, float]] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = RESP_RE.search(line)
        if match and match["token"] == token:
            values[(int(match["run"]), int(match["hno"]))] = (
                int(match["date"]), float(match["value"])
            )
    return values


def _write_rows(out_dir: Path, rows: list[dict[str, object]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "nw_pairing_audit.csv"
    fields = list(rows[0]) if rows else ["status"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = pd.DataFrame(rows)
    summary_path = out_dir / "nw_pairing_audit_summary.csv"
    if summary.empty:
        pd.DataFrame([{"rows": 0, "pass": False}]).to_csv(
            summary_path, index=False, encoding="utf-8-sig"
        )
        return
    pd.DataFrame(
        [{
            "rows": len(summary),
            "pass_rows": int(summary["status"].eq("pass").sum()),
            "fail_rows": int(summary["status"].eq("fail").sum()),
            "missing_rows": int(summary["status"].eq("missing").sum()),
            "max_abs_difference": float(summary["abs_difference"].fillna(0).max()),
            "pass": bool(summary["status"].eq("pass").all()),
        }]
    ).to_csv(summary_path, index=False, encoding="utf-8-sig")


def audit(det_root: Path, mapping_csv: Path, run_mapping_csv: Path, out_dir: Path) -> int:
    from src.calibration.nitrogen_response import load_n_response_mapping

    run_mapping = pd.read_csv(run_mapping_csv).to_dict("records")
    mapping = load_n_response_mapping(mapping_csv, run_mapping, response_levels=("N3",))
    by_run = {
        int(row.global_run): {
            "season": str(row.season_id),
            "treatment": int(row.treatment),
            "water": str(row.water_level),
            "nitrogen": str(row.nitrogen_level),
        }
        for row in mapping.itertuples(index=False)
    }
    harvest = _read_harvest(det_root / "PestHarvest.OUT")
    n_output = _read_response(det_root / "PestNResponse.OUT", "NRESPS")
    w_output = _read_response(det_root / "PestWResponse.OUT", "WRESPS")
    source: dict[tuple[str, int, str, str], tuple[int, int, float]] = {}
    for (run, hno), (date, value) in harvest.items():
        meta = by_run.get(run)
        if meta:
            source[(meta["season"], hno, meta["water"], meta["nitrogen"])] = (
                run, date, value
            )

    rows: list[dict[str, object]] = []
    for family, output in (("N_RESPONSE", n_output), ("W_RESPONSE", w_output)):
        for (run, hno), (date, observed_output) in sorted(output.items()):
            meta = by_run.get(run)
            if not meta:
                rows.append({"family": family, "global_run": run, "hno": hno, "status": "missing"})
                continue
            season, water, nitrogen = meta["season"], meta["water"], meta["nitrogen"]
            if family == "N_RESPONSE":
                current = source.get((season, hno, water, nitrogen))
                reference = source.get((season, hno, water, "N0"))
                reference_label = "N0"
            else:
                high = "W3" if season == "25SP" else "W2"
                current = source.get((season, hno, high, nitrogen))
                reference = source.get((season, hno, "W1", nitrogen))
                reference_label = "W1"
            if current is None or reference is None:
                rows.append({
                    "family": family, "season": season, "global_run": run,
                    "treatment": meta["treatment"], "water": water,
                    "nitrogen": nitrogen, "hno": hno, "date": date,
                    "source_variable": "CHFPW", "reference": reference_label,
                    "status": "missing",
                })
                continue
            expected = current[2] - reference[2]
            delta = observed_output - expected
            rows.append({
                "family": family, "season": season, "global_run": run,
                "treatment": meta["treatment"], "water": water,
                "nitrogen": nitrogen, "hno": hno, "date": date,
                "source_variable": "CHFPW", "reference": reference_label,
                "current_source_value": current[2], "reference_source_value": reference[2],
                "expected_contrast": expected, "output_contrast": observed_output,
                "abs_difference": abs(delta),
                "status": "pass" if abs(delta) <= 1e-8 and date == current[1] else "fail",
            })
    _write_rows(out_dir, rows)
    summary = pd.DataFrame(rows)
    if summary.empty or not summary["status"].eq("pass").all():
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--det-root", type=Path, required=True)
    parser.add_argument("--mapping-csv", type=Path, required=True)
    parser.add_argument("--run-mapping-csv", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    return audit(args.det_root, args.mapping_csv, args.run_mapping_csv, args.out_dir)


if __name__ == "__main__":
    raise SystemExit(main())
