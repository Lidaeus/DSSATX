"""Derive an immutable FileX bundle with uniform default initial mineral N.

Only the ``*INITIAL CONDITIONS`` layer rows are changed.  Soil water, soil
analysis, fertilizer management, observations, weather and soil assets remain
byte-identical to the source bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _field(value: float) -> str:
    rendered = format(float(value), ".6g")
    if rendered.startswith("0."):
        rendered = rendered[1:]
    elif rendered.startswith("-0."):
        rendered = "-." + rendered[3:]
    if len(rendered) > 6:
        raise ValueError(f"Initial-condition value does not fit FileX width: {value}")
    return rendered.rjust(6)


def replace_initial_mineral_n(
    text: str,
    *,
    snh4: float,
    sno3: float,
) -> tuple[str, list[dict[str, float]]]:
    """Set SNH4/SNO3 on every FileX initial-condition layer row."""

    lines = text.splitlines()
    in_initial = False
    layer_header = False
    audit: list[dict[str, float]] = []
    for index, line in enumerate(lines):
        upper = line.strip().upper()
        if upper.startswith("*INITIAL CONDITIONS"):
            in_initial = True
            continue
        if in_initial and upper.startswith("*") and not upper.startswith("*INITIAL CONDITIONS"):
            break
        if not in_initial:
            continue
        if upper.startswith("@C") and all(token in upper for token in ("ICBL", "SH2O", "SNH4", "SNO3")):
            layer_header = True
            continue
        if upper.startswith("@C"):
            layer_header = False
            continue
        if not layer_header:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            ic = int(parts[0])
            depth = int(float(parts[1]))
            sh2o = float(parts[2])
            old_snh4 = float(parts[3])
            old_sno3 = float(parts[4])
        except ValueError:
            continue
        lines[index] = (
            f"{ic:3d}{depth:6d}{_field(sh2o)}{_field(snh4)}{_field(sno3)}"
        )
        audit.append(
            {
                "ic": ic,
                "depth_cm": depth,
                "old_snh4": old_snh4,
                "old_sno3": old_sno3,
                "new_snh4": float(snh4),
                "new_sno3": float(sno3),
            }
        )
    if not audit:
        raise ValueError("No *INITIAL CONDITIONS SNH4/SNO3 rows were found")
    return "\n".join(lines) + "\n", audit


def _refresh_file_record(record: dict, bundle: Path, filex_name: str) -> None:
    name = str(record.get("name") or "")
    path = bundle / name
    if path.is_file():
        record["sha256"] = sha256(path)
        record["bytes"] = path.stat().st_size
    if name == filex_name:
        record["derived_transformation"] = "uniform_default_initial_mineral_n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-bundle", type=Path, required=True)
    parser.add_argument("--output-bundle", type=Path, required=True)
    parser.add_argument("--filex-name", required=True)
    parser.add_argument("--sno3", type=float, default=1.0)
    parser.add_argument("--snh4", type=float, default=0.5)
    args = parser.parse_args()

    source = args.source_bundle.resolve()
    output = args.output_bundle.resolve()
    source_manifest = source / "input_manifest.json"
    source_filex = source / args.filex_name
    if not source_manifest.is_file():
        raise FileNotFoundError(source_manifest)
    if not source_filex.is_file():
        raise FileNotFoundError(source_filex)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing bundle: {output}")

    shutil.copytree(source, output)
    output_filex = output / args.filex_name
    original_text = output_filex.read_text(encoding="utf-8")
    transformed_text, audit = replace_initial_mineral_n(
        original_text,
        snh4=args.snh4,
        sno3=args.sno3,
    )
    output_filex.write_text(transformed_text, encoding="utf-8", newline="")

    manifest_path = output / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bundle_id"] = output.name
    manifest["derived_from_bundle"] = source.name
    manifest["derived_from_manifest_sha256"] = sha256(source_manifest)
    manifest["created_at"] = datetime.now(timezone.utc).isoformat()
    manifest["intended_use"] = "special_three_season_default_initial_n_parameter_calibration"
    manifest["scenario_type"] = "special_default_initial_mineral_n_calibration"
    manifest["initial_condition_policy"] = (
        "counterfactual_uniform_default_mineral_n_sno3_1_snh4_0.5"
    )
    transformations = list(manifest.get("counterfactual_transformations") or [])
    transformations.append(
        {
            "transformation_id": "uniform_default_initial_mineral_n_v1_20260730",
            "section": "*INITIAL CONDITIONS",
            "fields": {"SNO3": float(args.sno3), "SNH4": float(args.snh4)},
            "scope": "all initial-condition treatments and all declared layers",
            "unchanged": [
                "ICDAT",
                "SH2O",
                "*SOIL ANALYSIS",
                "fertilizer management",
                "irrigation management",
                "weather",
                "SOIL.SOL",
                "observations",
            ],
            "row_count": len(audit),
        }
    )
    manifest["counterfactual_transformations"] = transformations
    manifest["initial_mineral_n_audit"] = {
        "filex": args.filex_name,
        "row_count": len(audit),
        "ic_count": len({int(row["ic"]) for row in audit}),
        "depths_cm": sorted({int(row["depth_cm"]) for row in audit}),
        "SNO3": float(args.sno3),
        "SNH4": float(args.snh4),
        "source_filex_sha256": sha256(source_filex),
        "rows": audit,
    }
    for record in manifest.get("files", []):
        _refresh_file_record(record, output, args.filex_name)
    for records in manifest.get("files_by_role", {}).values():
        for record in records:
            _refresh_file_record(record, output, args.filex_name)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "bundle": str(output),
                "manifest_sha256": sha256(manifest_path),
                "filex_sha256": sha256(output_filex),
                "rows_changed": len(audit),
                "initial_condition_levels": len({int(row["ic"]) for row in audit}),
                "depths_cm": sorted({int(row["depth_cm"]) for row in audit}),
                "SNO3": args.sno3,
                "SNH4": args.snh4,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
