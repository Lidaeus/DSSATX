"""Audit IC depths against DSSAT's declared soil profile and MESOL setting.

This is a provenance audit, not a rewriting tool.  In this project the TMX
initial-condition observations are at measurement depths (2, 4, 15, ... cm),
while the selected SOIL.SOL profile uses model layer bases (10, 30, ... cm)
and ``MESOL=2``.  The report deliberately separates these facts so that an
unmatched measurement depth is not silently changed to a soil boundary.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd


def _find_tmx(season_dir: Path) -> Path:
    files = sorted(season_dir.glob("*.TMX"))
    if not files:
        raise FileNotFoundError(f"no TMX in {season_dir}")
    return files[0]


def _soil_id(tmx: Path) -> str:
    lines = tmx.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("@L ID_FIELD") and i + 1 < len(lines):
            fields = lines[i + 1].split()
            # ID_SOIL follows the field-depth token (SLDP); split() gives
            # [treatment, ..., SL, depth, ID_SOIL, ...].
            if len(fields) > 11:
                return fields[11]
    raise ValueError(f"could not find ID_SOIL in {tmx}")


def _mesol(tmx: Path) -> str:
    lines = tmx.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("@N METHODS") and i + 1 < len(lines):
            data = lines[i + 1].split()
            if data:
                return data[-1]
    raise ValueError(f"could not find MESOL row in {tmx}")


def _ic_depths(tmx: Path) -> list[float]:
    depths: set[float] = set()
    in_ic = False
    for line in tmx.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lstrip().startswith("*INITIAL CONDITIONS"):
            in_ic = True
            continue
        if in_ic and line.startswith("*"):
            in_ic = False
        if in_ic and line.lstrip().startswith("@C") and "ICBL" in line:
            continue
        if in_ic:
            fields = line.split()
            if len(fields) >= 5 and re.fullmatch(r"\d+", fields[0]):
                try:
                    depth = float(fields[1])
                    # The IC header row contains ICDAT=-99 in this position;
                    # only non-negative ICBL depths are measurement rows.
                    if depth >= 0:
                        depths.add(depth)
                except ValueError:
                    pass
    return sorted(depths)


def _soil_layers(soil: Path, soil_id: str) -> list[float]:
    lines = soil.read_text(encoding="utf-8", errors="replace").splitlines()
    marker = f"*{soil_id}"
    active = False
    in_layer_table = False
    depths: list[float] = []
    for line in lines:
        if line.startswith("*"):
            active = line.startswith(marker)
            in_layer_table = False
            continue
        if not active:
            continue
        if line.lstrip().startswith("@  SLB"):
            in_layer_table = True
            continue
        if line.lstrip().startswith("@"):
            continue
        if not in_layer_table:
            continue
        fields = line.split()
        if fields and re.fullmatch(r"[-+]?\d+(?:\.\d+)?", fields[0]):
            try:
                depths.append(float(fields[0]))
            except ValueError:
                pass
    return depths


def audit(season_dirs: list[Path], mapping_csvs: list[Path], out_json: Path) -> int:
    seasons: list[dict[str, object]] = []
    for season_dir in season_dirs:
        tmx = _find_tmx(season_dir)
        soil = season_dir / "SOIL.SOL"
        sid = _soil_id(tmx)
        ic = _ic_depths(tmx)
        layers = _soil_layers(soil, sid)
        exact = [d for d in ic if d in layers]
        seasons.append({
            "season_dir": str(season_dir),
            "tmx": str(tmx),
            "soil_file": str(soil),
            "soil_id": sid,
            "mesol": _mesol(tmx),
            "ic_depths_cm": ic,
            "soil_layer_bases_cm": layers,
            "exact_boundary_depths_cm": exact,
            "unmatched_measurement_depths_cm": [d for d in ic if d not in exact],
            "interpretation": (
                "MESOL=2 is declared; unmatched IC depths are measurement-grid "
                "provenance items requiring an explicit DSSAT assignment audit, "
                "not grounds for silently rewriting TMX depths."
            ),
        })

    mapping_summary: list[dict[str, object]] = []
    for mapping_csv in mapping_csvs:
        if not mapping_csv.is_file():
            mapping_summary.append({"path": str(mapping_csv), "missing_file": True, "pass": False})
            continue
        frame = pd.read_csv(mapping_csv)
        required = {
            "season_id", "measured_depth_top_cm", "measured_depth_bottom_cm",
            "dssat_layer_top_cm", "dssat_layer_bottom_cm", "overlap_weight",
        }
        missing = sorted(required - set(frame.columns))
        checks: list[dict[str, object]] = []
        if not missing:
            for season, group in frame.groupby("season_id", sort=True):
                weights = group.groupby(
                    ["measured_depth_top_cm", "measured_depth_bottom_cm"],
                    dropna=False,
                )["overlap_weight"].sum()
                checks.append({
                    "season_id": str(season),
                    "rows": int(len(group)),
                    "weight_groups": int(len(weights)),
                    "max_weight_sum_error": float((weights - 1.0).abs().max()),
                    "pass": bool((weights - 1.0).abs().le(1e-8).all()),
                })
        mapping_summary.append({
            "path": str(mapping_csv),
            "missing_columns": missing,
            "checks": checks,
            "pass": not missing and all(bool(x["pass"]) for x in checks),
        })

    report = {
        "schema_version": 1,
        "status": "provenance_audit",
        "seasons": seasons,
        "mapping": mapping_summary,
        "formal_use_decision": (
            "Do not change IC depths automatically.  Before a new formal run, "
            "attach a generated MESOL=2 assignment table or an equivalent DSSAT "
            "run log showing how measurement-depth IC values are distributed."
        ),
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season-dir", action="append", type=Path, required=True)
    parser.add_argument("--mapping-csv", action="append", type=Path, default=[])
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()
    return audit(args.season_dir, args.mapping_csv, args.out_json)


if __name__ == "__main__":
    raise SystemExit(main())
